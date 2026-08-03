#!/usr/bin/env python3
"""
diagnose_wedge.py — localise a state divergence to the exact block, over HTTP, read-only.

    python3 scripts/diagnose_wedge.py [--host 127.0.0.1] [--port 9173]

WHY THIS EXISTS. When a node refuses to extend with

    Block N state_root <theirs> != our as-of-parent L1 state <ours> — our state diverged from the producer

the useful question is not "which node is right" (the fleet is, by weight) but **which block did it enter
at**, and nothing exposes per-DB roots over HTTP to answer that directly. It turns out you do not need
them.

THE TRICK. ops/block_ops.block_content_hash puts `state_root` INSIDE the block-hash preimage. So:

  * agreeing with a peer on block N's HASH means agreeing on the state root that block commits — comparing
    hashes is a state comparison, not merely a chain comparison;
  * block N's `state_root` is the AS-OF-PARENT state (the state after N-1).

Therefore, if you agree with peers up to and including block N but they reject your state for N+1, the
corruption entered **while applying block N**. Two HTTP endpoints and a bisection get you there.

Then it prints that block's transaction count, which is the part that tells you what KIND of fault it is.
A block with transactions means suspect the transactions. A block with ZERO transactions is much more
informative: identical prior state plus an identical empty block (whose reward is also hash-committed) is
a deterministic function, so a differing result proves something wrote to the database OUTSIDE block
application — a non-block-derived write, which no peer can ever reconstruct because it never existed as a
transaction. That is a completely different bug hunt, and worth being pointed at rather than guessed.

Read-only: only GETs. It never imports node modules, so it cannot touch the chain database (importing
nado.py has import-time writes, and /root/nado symlinks to the live data dir — see the header of
tests/test_fresh_node_boots.py for what that once cost).
"""
import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def get(url, timeout=12):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def status(host, port=9173):
    try:
        return get(f"http://{host}:{port}/status")
    except Exception as e:
        return {"_error": str(e)[:80]}


def block_hash(host, n, port=9173):
    """The block hash at height n, or None when the node does not have that height."""
    try:
        d = get(f"http://{host}:{port}/get_block_number?number={n}")
        b = d.get("block") or d
        return b.get("block_hash")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9173)
    a = ap.parse_args()

    me = status(a.host, a.port)
    if "_error" in me:
        print(f"cannot reach the local node: {me['_error']}")
        return 2
    peers = get(f"http://{a.host}:{a.port}/peers").get("peers", [])
    with ThreadPoolExecutor(8) as ex:
        pst = dict(zip(peers, ex.map(lambda p: status(p, a.port), peers)))

    ours = int(me["latest_block_height"])
    live = {p: int(s["latest_block_height"]) for p, s in pst.items()
            if "_error" not in s and s.get("latest_block_height") is not None}
    if not live:
        print("no peer answered — this is a connectivity problem, not a state divergence")
        return 2
    # PICK THE MAJORITY CHAIN, NOT THE TALLEST PEER. Choosing max(height) as the reference is the very
    # mistake this script exists to catch: height is a claim about PROGRESS, not about identity, and a peer
    # stranded on its own fork mines unopposed and therefore climbs FASTER than the real chain. Measured
    # live on 2026-08-03: one peer sat 64 blocks ahead of four agreeing nodes on a fork of its own, and
    # selecting it made this tool report US as diverged.
    #
    # So group the peers (and ourselves) by the block hash they hold at a recent SHARED height, and use the
    # largest group as the reference. A tie is reported rather than silently broken.
    # Probe just below OUR OWN tip, not at the fleet minimum. Taking min() across all peers picks a height
    # BELOW any recent fork whenever one peer is still catching up — measured live: a peer 800 blocks behind
    # dragged the probe to a height everyone still agreed on, so a real fork 400 blocks higher was invisible
    # and the tool fell through to the tallest-peer behaviour it was meant to replace. Only peers that
    # actually hold the probe height take part.
    probe_h = max(0, ours - 8)                    # a few blocks back so propagation lag is not read as a fork
    voters = [p for p, h in live.items() if h >= probe_h]
    if not voters:
        voters = list(live)
    groups = {}
    with ThreadPoolExecutor(8) as ex:
        hs = dict(zip(["__local__"] + voters,
                      ex.map(lambda hp: block_hash(hp, probe_h, a.port),
                             [a.host] + voters)))
    for who, h in hs.items():
        if h:
            groups.setdefault(h, []).append(who)
    print(f"local  height {ours}")
    for p, h in sorted(live.items(), key=lambda kv: -kv[1]):
        print(f"  peer {p:<18} height {h}")
    if len(groups) > 1:
        print(f"\n!! THE FLEET DISAGREES at height {probe_h} — {len(groups)} distinct chains:")
        for h, who in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            tag = " (us)" if "__local__" in who else ""
            print(f"     {h}  {len(who)} node(s){tag}: {', '.join(w for w in who if w != '__local__') or 'local only'}")
    majority = max(groups.values(), key=len) if groups else []
    on_majority = "__local__" in majority
    ref_peers = [w for w in majority if w != "__local__"]
    if len(groups) > 1 and on_majority:
        print("\nWe are on the MAJORITY chain. The minority node(s) above are the ones to investigate,")
        print("not this one — run this script THERE.")
        return 0
    if not ref_peers:
        print("\nno peer shares our chain — cannot localise against a reference.")
        return 2
    best_peer = max(ref_peers, key=lambda p: live[p])
    best_h = live[best_peer]
    print(f"\nreference (majority chain): {best_peer} at height {best_h}")
    if best_h <= ours:
        print("\nno peer is ahead — this node is not behind; nothing to localise.")
        return 0
    print(f"\nbehind by {best_h - ours} blocks; bisecting against {best_peer} for the last AGREED block\n")

    # RETENTION FIRST. A peer that PRUNES answers 404 for old heights, and "the peer does not have it" is
    # not "we disagree" — conflating the two walks the bisection all the way to block 0 and reports the
    # divergence at block 1, which is what the first version of this script did on a fleet of pruning
    # nodes. Establish the window where BOTH sides actually hold the block, and only bisect inside it.
    def pair(n):
        return block_hash(a.host, n, a.port), block_hash(best_peer, n, a.port)

    def both_have(n):
        x, y = pair(n)
        return x is not None and y is not None

    floor_ = 0
    if not both_have(ours):
        print(f"the peer does not serve our tip height {ours} — cannot compare.")
        return 2
    if not both_have(0):
        # both_have() is monotone in height (false below the pruning watermark, true above), so binary
        # search straight for the boundary. An earlier version walked BACK from our tip, which succeeds
        # immediately at the tip and "found" a window one block wide — reporting a pruning peer as
        # retaining nothing.
        lo_missing, hi_present = 0, ours
        while lo_missing < hi_present - 1:
            mid = (lo_missing + hi_present) // 2
            if both_have(mid):
                hi_present = mid
            else:
                lo_missing = mid
        floor_ = hi_present
        print(f"(peer prunes; earliest height held by both nodes is {floor_})")

    ours_f, theirs_f = pair(floor_)
    if ours_f != theirs_f:
        print(f"we already DISAGREE at {floor_}, the earliest block both nodes still hold —")
        print("the divergence predates the shared retention window and cannot be localised over HTTP.")
        return 1

    # Bisect for the highest height where our hash == the peer's. block_content_hash commits state_root,
    # so the last agreed height is the last height whose committed STATE we also agree on.
    lo, hi = floor_, ours
    ours_t, theirs_t = pair(hi)
    if ours_t is not None and ours_t == theirs_t:
        lo = hi
    else:
        while lo < hi - 1:
            mid = (lo + hi) // 2
            ours_h, theirs_h = pair(mid)
            if ours_h is not None and ours_h == theirs_h:
                lo = mid
            else:
                hi = mid
    print(f"last block we AGREE on: {lo}")

    # THE CULPRIT IS THE LAST AGREED BLOCK, NOT THE FIRST DISAGREEING ONE. Block N's state_root is the
    # AS-OF-PARENT state, so agreeing on block N's hash attests the state after N-1. Agreeing through `lo`
    # therefore attests state after lo-1; the DISPUTED state is "state after lo", which is what block lo+1
    # commits. That state was produced by APPLYING block lo. Reporting lo+1 (the first hash mismatch) points
    # at the block that merely REVEALED the fault — and on a node producing its own fork, lo+1 is its own
    # block, which is a symptom rather than a cause.
    culprit = lo
    print(f"=> the disputed state is 'state after {lo}', attested by block {lo + 1}")
    print(f"=> it was produced by APPLYING block {culprit}\n")
    try:
        d = get(f"http://{best_peer}:{a.port}/get_block_number?number={culprit}")
        b = d.get("block") or d
        txs = b.get("block_transactions") or []
        print(f"block {culprit}: creator={str(b.get('block_creator'))[:20]}  transactions={len(txs)}")
        for t in txs[:20]:
            print(f"   recipient={str(t.get('recipient'))[:22]:<24} sender={str(t.get('sender'))[:14]} "
                  f"amount={t.get('amount')}")
        if not txs:
            print("\n  *** ZERO TRANSACTIONS ***")
            print("  Identical prior state + an identical EMPTY block (its reward is hash-committed too)")
            print("  is a deterministic function. A differing result therefore proves something wrote to")
            print("  this node's database OUTSIDE block application. No peer can reconstruct such a write:")
            print("  it never existed as a transaction, so it was never gossiped and never in a block.")
            print("  Hunt for a non-block writer (a stray process against the live data dir, a migration")
            print("  run mid-flight), NOT for a bad transaction.")
    except Exception as e:
        print(f"could not fetch block {culprit} from {best_peer}: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
