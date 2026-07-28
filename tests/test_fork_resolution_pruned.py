"""FORK RESOLUTION ON A PRUNED FLEET.

find_common_ancestor binary-searches [floor, tip] for the highest height where our hash matches the
majority's. It used to probe `floor` (0) first and treat an empty answer as "no majority could be
established" — i.e. UNKNOWN, do nothing.

But peers PRUNE history. On 2026-07-28 no peer on the fleet could serve h0, h1, h5000 or h11000; the lowest
commonly-held height was ~h12000. So every verdict came back `ancestor=None, probes=9` — eight retries at
the tip, one at the floor, give up — and two nodes that had ALREADY PROVEN they were stranded (stranded=True,
3 peers disagreeing, 0 agreeing) could never obtain the second confirmation the purge requires. The
self-heal was blocked not by the fork detection but by the floor.

The answerable range is a contiguous WINDOW at the top of the chain, bounded below by pruning and above by
how far the peers have synced. Neither end may be assumed. These checks pin that the search finds the
window instead of giving up beneath it — while keeping UNKNOWN for the cases that genuinely warrant it,
since UNKNOWN is what stops a node from purging itself on bad information.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import fork_resolution as FR

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


def make_world(fork_at, window_lo, window_hi, peer_tip=None):
    """A fleet on chain B that has pruned below window_lo and holds nothing above window_hi.

    We are on chain A, which shares history with B up to `fork_at` and diverges after it."""
    def our_hash_at(h):
        return f"C{h}" if h <= fork_at else f"A{h}"

    def probe(peer, h):
        if h < window_lo or h > window_hi:
            return None                      # pruned below / not synced above
        return f"C{h}" if h <= fork_at else f"B{h}"

    return our_hash_at, probe


PEERS = ["p1", "p2", "p3"]

# THE LIVE CASE. Fleet pruned below h12000; we forked at h12505 and raced on to h12910 with our finality
# floor at h12865 — so the divergence is BELOW our floor and no rollback can cross it.
our_hash_at, probe = make_world(fork_at=12505, window_lo=12000, window_hi=13500)
v = FR.resolve(our_hash_at=our_hash_at, tip=12910, finalized=12865, peers=PEERS, probe=probe)
check(v["state"] == FR.DEAD_FORK, f"pruned fleet + fork below finality -> DEAD_FORK (got {v['state']})")
check(v["ancestor"] == 12505, f"finds the exact fork point through the pruning (got {v['ancestor']})")

# The same search must still work when the fork is ABOVE the finality floor: that is a recoverable reorg,
# and calling it a dead fork would purge a node that only needed a rollback.
v = FR.resolve(our_hash_at=our_hash_at, tip=12910, finalized=12100, peers=PEERS, probe=probe)
check(v["state"] == FR.REORG, f"pruned fleet + fork above finality -> REORG, not a purge (got {v['state']})")

# Not forked at all, just short: our whole chain is a prefix of theirs. Must be BEHIND -> forward sync.
# Reading this as a fork is what wedged a node on 2026-07-20.
same_chain = (lambda h: f"C{h}"), (lambda peer, h: f"C{h}" if 12000 <= h <= 13500 else None)
v = FR.resolve(our_hash_at=same_chain[0], tip=12910, finalized=12865, peers=PEERS, probe=same_chain[1])
check(v["state"] == FR.BEHIND, f"pruned fleet + same chain -> BEHIND, never a purge (got {v['state']})")

# THE REGRESSION ITSELF: with floor=0 unanswerable, the old code returned UNKNOWN here.
v = FR.resolve(our_hash_at=our_hash_at, tip=12910, finalized=12865, peers=PEERS, probe=probe)
check(v["state"] != FR.UNKNOWN,
      "an unanswerable floor no longer collapses the verdict to UNKNOWN (the bug that blocked the heal)")

# A node that RACED AHEAD of the pruned window on both ends — peers hold neither our tip nor the floor.
our_hash_at2, probe2 = make_world(fork_at=12505, window_lo=12000, window_hi=12700)
v = FR.resolve(our_hash_at=our_hash_at2, tip=12910, finalized=12865, peers=PEERS, probe=probe2)
check(v["state"] == FR.DEAD_FORK,
      f"raced ahead AND pruned below: still conclusive from inside the window (got {v['state']})")

# SAFETY DIRECTION — these must stay UNKNOWN. A node must never destroy chain data on no evidence.
silent = FR.resolve(our_hash_at=our_hash_at, tip=12910, finalized=12865, peers=PEERS,
                    probe=lambda peer, h: None)
check(silent["state"] == FR.UNKNOWN, "peers that answer NOWHERE stay UNKNOWN (no purge on silence)")

split = FR.resolve(our_hash_at=our_hash_at, tip=12910, finalized=12865, peers=PEERS,
                   probe=lambda peer, h: f"{peer}-{h}" if 12000 <= h <= 13500 else None)
check(split["state"] == FR.UNKNOWN, "peers that all disagree with EACH OTHER stay UNKNOWN (no majority)")

lonely = FR.resolve(our_hash_at=our_hash_at, tip=12910, finalized=12865, peers=["p1"], probe=probe)
check(lonely["state"] == FR.UNKNOWN, "a single answering peer cannot reach min_answers=2 -> UNKNOWN")

# A heavily pruned peer set still has to yield a verdict. The doubling stride alone jumps over a narrow
# window (its gaps grow to half the range), so the uniform sweep has to catch it.
our3, probe3 = make_world(fork_at=12505, window_lo=12450, window_hi=12850)
v = FR.resolve(our_hash_at=our3, tip=12910, finalized=12865, peers=PEERS, probe=probe3)
check(v["state"] == FR.DEAD_FORK, f"a 400-block answerable window is still conclusive (got {v['state']})")

# The search is BOUNDED, so a sufficiently narrow window may fall between its samples. Whether any
# specific window is found is a matter of alignment and not worth pinning — what must hold for EVERY
# window is that the verdict is either RIGHT or UNKNOWN, and never a confidently wrong one. BEHIND or
# REORG here would be actively dangerous: BEHIND makes a forked node sync forward on its own dead chain,
# REORG makes it attempt a rollback that finality must refuse.
bad = []
for lo in range(12100, 12900, 37):
    for width in (5, 20, 100, 500):
        o, p = make_world(fork_at=12505, window_lo=lo, window_hi=lo + width)
        state = FR.resolve(our_hash_at=o, tip=12910, finalized=12865, peers=PEERS, probe=p)["state"]
        if state not in (FR.DEAD_FORK, FR.UNKNOWN):
            bad.append((lo, width, state))
check(not bad,
      f"across {22 * 4} pruned-window shapes the verdict is only ever DEAD_FORK or UNKNOWN — never a "
      f"confidently wrong action" + (f" (violations: {bad[:3]})" if bad else ""))

# Probe cost must stay logarithmic — this runs against live peers over HTTP.
v = FR.resolve(our_hash_at=our_hash_at, tip=12910, finalized=12865, peers=PEERS, probe=probe)
check(v["probes"] < 200, f"probe count stays bounded ({v['probes']})")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL PRUNED-FLEET FORK-RESOLUTION CHECKS PASSED")
