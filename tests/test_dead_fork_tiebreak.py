"""DEAD-FORK ESCAPE: SYMMETRY BREAKER.

The purge+resync escape destroys chain-derived data, so it is only safe if AT MOST ONE side of a split can
ever run it. Quorum cannot decide that. On both sides of a 2-2 split a node truthfully observes a majority
of its non-self peers disagreeing with it, so any quorum value that fires on one side fires on the other:
on 2026-07-28 both pairs purged, resynced from each other, and the fleet went from one chain to two sharing
only genesis. That storm is why the normal_mode caller was disabled — which then left local and .141 stuck
on dead branches for hours with a perfectly correct probe nothing was allowed to act on.

Weight breaks the symmetry the way fork choice already does: the lighter side yields. These checks pin that
property, especially the two directions that must resolve to "nobody purges" — ties and unknown weights.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loops.core_loop import lighter_than_disagreeing

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


def pool(**kw):
    return {ip: {"latest_block_weight": w} for ip, w in kw.items()}


# THE STORM CASE. A 2-2 split: each side sees the other two disagreeing. Exactly one side may purge.
LIGHT, HEAVY = 4_185_703, 4_387_835
light_side_yields, _ = lighter_than_disagreeing(LIGHT, ["b1", "b2"], pool(b1=HEAVY, b2=HEAVY))
heavy_side_stays, _ = lighter_than_disagreeing(HEAVY, ["a1", "a2"], pool(a1=LIGHT, a2=LIGHT))
check(light_side_yields, "2-2 split: the LIGHTER side yields (purges)")
check(not heavy_side_stays, "2-2 split: the HEAVIER side stays put")
check(light_side_yields != heavy_side_stays,
      "2-2 split: EXACTLY ONE side purges — a mutual wipe is impossible")

# Ties must not purge. Two nodes at identical weight would both yield, which is the storm again.
tie, _ = lighter_than_disagreeing(LIGHT, ["b1"], pool(b1=LIGHT))
check(not tie, "equal weight does NOT purge (a tie would let both sides yield)")

# Unknown weight is not evidence of a heavier chain. A peer missing from the status pool, or advertising
# garbage, must never be read as "they are ahead, wipe yourself".
missing, _ = lighter_than_disagreeing(LIGHT, ["ghost"], {})
check(not missing, "a peer absent from the status pool does not trigger a purge")

garbage, _ = lighter_than_disagreeing(LIGHT, ["b1"], {"b1": {"latest_block_weight": "not-a-number"}})
check(not garbage, "a peer advertising a non-numeric weight does not trigger a purge")

nonsense, _ = lighter_than_disagreeing(LIGHT, ["b1"], {"b1": "not-a-dict"})
check(not nonsense, "a malformed status entry does not trigger a purge")

check(not lighter_than_disagreeing(LIGHT, [], pool(b1=HEAVY))[0],
      "no disagreeing peers means no purge, however heavy the pool is")
check(not lighter_than_disagreeing(LIGHT, None, None)[0],
      "missing probe detail degrades to no purge, not a crash")

# The heaviest disagreeing peer is what counts — one heavy peer among light ones still outranks us.
mixed, heaviest = lighter_than_disagreeing(LIGHT, ["b1", "b2"], pool(b1=1, b2=HEAVY))
check(mixed and heaviest == HEAVY, "the HEAVIEST disagreeing peer decides, not the first or the average")

# Only DISAGREEING peers count. A heavy peer that agrees with us is on our chain — it is not evidence that
# our chain is abandoned, and reading it as such would make a node purge toward itself.
agreeing, _ = lighter_than_disagreeing(LIGHT, ["b1"], pool(b1=LIGHT, friend=HEAVY))
check(not agreeing, "a heavy AGREEING peer is ignored (only disagreeing peers can outweigh us)")

# Being ahead by a single unit is still ahead — the rule is strict, not fuzzy.
one_more, _ = lighter_than_disagreeing(LIGHT, ["b1"], pool(b1=LIGHT + 1))
check(one_more, "strictly heavier by 1 does yield (the comparison is strict, not approximate)")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL DEAD-FORK TIE-BREAK CHECKS PASSED")
