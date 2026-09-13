#!/usr/bin/env python3
"""Fleet tip diagnostic: is this a fork, a lag, or a wedge — and where exactly.

WHY THIS IS A SCRIPT AND NOT A PASTED SNIPPET. Every tip investigation here has been re-typed from
scratch, and each time the *order* of the questions was the thing that mattered rather than any one
query: "same height, different hash" separates a fork from a lag, movement separates a wedge from
propagation, and the fork point measured against the finality floor separates a divergence a node can
recover from by itself from one where only a purge moves it. Getting that order wrong costs an hour
chasing a stale `last_block_reject` that turns out to be the system working.

Read-only. It calls /status and /get_block over HTTP and changes nothing, so it is safe to run against
production at any time — which is the point: the first thing you want during an incident is a command
you are not afraid of.

    python3 scripts/fleet_tips.py                 # one pass
    python3 scripts/fleet_tips.py --watch 75      # sample twice, 75 s apart, to see who is moving
    python3 scripts/fleet_tips.py --json          # machine-readable, for a cron or a paste

Exit status is 0 when the fleet agrees, 1 when any node is frozen or forked — so it can gate a loop.
"""
import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PORT = 9173
TIMEOUT = 8
# A node that has not moved between two samples is frozen; one whose height DROPS is worse than frozen
# and gets its own label, because a receding tip means rollback without re-sync.
FROZEN, BEHIND, OK, RECEDING = "FROZEN", "behind", "ok", "RECEDING"


def _get(ip, path, timeout=TIMEOUT):
    try:
        with urllib.request.urlopen(f"http://{ip}:{PORT}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def peers_from_disk(path="peers.dat"):
    """The node's own peer table plus loopback. Deliberately NOT the live peer list from /peers: a node
    that has lost its peers is exactly the node under investigation, and asking it who to ask would hide
    the hosts that matter."""
    try:
        with open(path) as f:
            return ["127.0.0.1"] + sorted(json.load(f).keys())
    except Exception:
        return ["127.0.0.1"]


def sample(ips):
    """{ip: status} for every node that answers. A node that does not answer is omitted rather than
    recorded as height 0 — absent and stalled are different problems."""
    def one(ip):
        return ip, _get(ip, "/status")
    with ThreadPoolExecutor(16) as ex:
        return {ip: s for ip, s in ex.map(one, ips) if s}


def block_hash(ip, height):
    b = _get(ip, f"/get_block?number={height}")
    if not b:
        return None
    b = b.get("block", b)
    return (b or {}).get("block_hash")


def fork_point(ip_a, ip_b, lo, hi):
    """Highest height at which two nodes still agree, by binary search over [lo, hi].

    TEST THE TOP FIRST. A binary search whose invariant is "agree at lo, disagree at hi" is only sound if
    something actually established disagreement at hi — and hi is the stuck node's own tip, where the
    overwhelmingly common case is that it AGREES and is merely short. Assuming it instead reported every
    frozen node as "agrees to tip-1, differs after", which reads as a one-block fork on nine nodes at once.
    A uniform answer across unrelated nodes is the tell that the answer came from the method, not the fleet.

    Returns `hi` when they agree there (no fork, just lag), or None when they already disagree at `lo` —
    the divergence is deeper than the window, which is itself the answer: widen it, or the node is far
    enough gone that the floor comparison is what counts.
    """
    ha, hb = block_hash(ip_a, hi), block_hash(ip_b, hi)
    if ha and hb and ha == hb:
        return hi                                  # agreed at the top: BEHIND, not forked
    if block_hash(ip_a, lo) != block_hash(ip_b, lo):
        return None
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        ha, hb = block_hash(ip_a, mid), block_hash(ip_b, mid)
        if ha and hb and ha == hb:
            lo = mid
        else:
            hi = mid
    return lo


def classify_node(prev, now):
    if prev is None:
        return BEHIND
    if now < prev:
        return RECEDING
    if now == prev:
        return FROZEN
    return OK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0, metavar="SECONDS",
                    help="sample twice this far apart, to tell a wedge from propagation")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--peers", default="peers.dat")
    args = ap.parse_args()

    ips = peers_from_disk(args.peers)
    first = sample(ips)
    if not first:
        print("no node answered", file=sys.stderr)
        return 2
    if args.watch:
        time.sleep(args.watch)
        second = sample(ips)
    else:
        second = first

    tip = max(s.get("latest_block_height") or 0 for s in second.values())
    canonical = max(second, key=lambda ip: second[ip].get("latest_block_height") or 0)

    report = {"tip": tip, "canonical_node": canonical, "watched_s": args.watch, "nodes": []}
    for ip, s in sorted(second.items(), key=lambda kv: -(kv[1].get("latest_block_height") or 0)):
        h = s.get("latest_block_height") or 0
        prev = (first.get(ip) or {}).get("latest_block_height") if args.watch else None
        row = {
            "ip": ip, "height": h, "behind": tip - h,
            "moved": (h - prev) if prev is not None else None,
            "state": classify_node(prev, h) if args.watch else (OK if tip - h < 3 else BEHIND),
            "commit": str(s.get("running_commit"))[:12],
            "hard_finality": s.get("hard_finality"),
            "recovery": s.get("recovery"),
        }
        # The discriminating measurement, and the expensive one: only for nodes that are actually stuck.
        if row["state"] in (FROZEN, RECEDING) and ip != canonical:
            floor = int(s.get("hard_finality") or 0)
            anc = fork_point(canonical, ip, max(floor, 1), h)
            row["fork_after"] = anc
            row["above_floor"] = (anc is not None and anc >= floor)
            # WHY IT IS STUCK, not just where. A hash comparison cannot see a STATE divergence: the node
            # holds the agreed block at the agreed height and still refuses the next one because its own
            # computed state root differs from the producer's. That node is BEHIND by every hash test ever
            # run against it and will never move, so the reject reason is part of the diagnosis, not colour.
            rej = (s.get("last_block_reject") or {}).get("error") or ""
            if anc is not None and anc >= h:
                row["verdict"] = "lagging, no fork"
                if "state_root" in rej:
                    row["verdict"] = "STATE divergence: blocks agree, state root does not — no rollback can fix this"
                elif rej:
                    row["verdict"] += f" — rejecting: {rej.split(chr(10))[0][:90]}"
            elif row["above_floor"]:
                row["verdict"] = "REORG: rollback is legal and is not happening"
            else:
                row["verdict"] = "at/below the finality floor — only a purge moves it"
            row["verdict_self"] = (s.get("recovery") or {}).get("state")
        report["nodes"].append(row)

    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"tip {tip}   canonical {canonical}   {len(report['nodes'])} nodes"
              + (f"   watched {args.watch}s" if args.watch else ""))
        print(f"{'node':42s} {'height':>8} {'behind':>7} {'moved':>6}  {'state':<9} {'commit':<13} note")
        for r in report["nodes"]:
            note = r.get("verdict") or ""
            if r.get("fork_after") is not None:
                note = f"agrees to {r['fork_after']}, differs after — {note}"
            print(f"{r['ip']:42s} {r['height']:>8} {r['behind']:>7} "
                  f"{'' if r['moved'] is None else r['moved']:>6}  {r['state']:<9} {r['commit']:<13} {note}")
        bad = [r for r in report["nodes"] if r["state"] in (FROZEN, RECEDING)]
        if bad:
            print(f"\n{len(bad)} node(s) not advancing: " + ", ".join(r["ip"] for r in bad))
    return 1 if any(r["state"] in (FROZEN, RECEDING) for r in report["nodes"]) else 0


if __name__ == "__main__":
    sys.exit(main())
