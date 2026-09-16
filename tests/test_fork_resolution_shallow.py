"""A ONE-BLOCK SPLIT IS RESOLVED IN TWO ROUNDS (ops/fork_resolution.find_common_ancestor, SHALLOW_SPLIT_DEPTH).

2026-09-17: the relay measured 49 probe rounds (43 s) to learn that its ancestor was one block below its tip —
the generic search discovered the fleet's pruning floor near block 0 first (eight retries per unanswerable
height) and bisected after. A matching majority hash at tip-k commits to the whole prefix, so the ancestor is
tip-k exactly. Pins: 1-, 2- and 3-block splits resolve in k+1 rounds; a deeper fork still lands on its true
divergence through the generic path; a tip-1 nobody can answer falls through to the generic path unchanged.
Run: python3 tests/test_fork_resolution_shallow.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import fork_resolution as fr

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond: fails.append(label)

ours = {h: f"h{h}" for h in range(0, 1001)}
peers = [f"p{i}" for i in range(6)]
def split_at(first_divergent, unanswerable=()):
    def probe(peer, h):
        if h in unanswerable: return None
        return (f"h{h}" if h < first_divergent else f"x{h}", 1)
    return probe

for depth in (1, 2, 3):
    anc, probes = fr.find_common_ancestor(lambda h: ours.get(h), tip=1000, peers=peers, probe=split_at(1001 - depth), floor=0)
    check(anc == 1000 - depth and probes == depth + 1, f"a {depth}-block split resolves to {1000 - depth} in {depth + 1} rounds (got {anc}, {probes})")
anc, probes = fr.find_common_ancestor(lambda h: ours.get(h), tip=1000, peers=peers, probe=split_at(731), floor=500)
check(anc == 730 and probes > fr.SHALLOW_SPLIT_DEPTH + 1, f"a deep fork still lands on its true divergence through the generic path ({anc}, {probes} rounds)")
anc, probes = fr.find_common_ancestor(lambda h: ours.get(h), tip=1000, peers=peers, probe=split_at(1000, unanswerable={999}), floor=500)
check(probes > fr.SHALLOW_SPLIT_DEPTH + 1, f"a tip-1 nobody can answer falls through to the generic path, whose verdict is unchanged ({anc}, {probes} rounds)")
anc, probes = fr.find_common_ancestor(lambda h: ours.get(h), tip=1000, peers=peers, probe=split_at(2000), floor=500)
check(anc == 1000 and probes == 1, "a merely-short node is still answered at the tip in one round")
print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
