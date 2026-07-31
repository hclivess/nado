"""PARALLEL STATE MERGE (execnode/stark/state_merge.py) — two transitions proven from the SAME pre-root
composed into one, which is what lets off-chain execution be spread across machines and settled once.

The positive checks are easy; the ones that matter are the refusals. A merge is sound only if it discharges
all three obligations (doc/state-merge.md), and each has a corresponding attack here:

  * OVERLAPPING KEYS — the merged root would depend on application order, so it would not be a function of
    the inputs at all.
  * DIFFERENT PRE-ROOTS — the two transitions describe different worlds and nothing connects them.
  * A DROPPED UPDATE — the subtle one. A prover that silently omits one side's write settles a state in which
    that write never happened, and every other check still passes. verify_merge compares the merged list
    against the exact union for this reason.

Run: python3 tests/test_state_merge.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import state_merge as SM, state_transition as SX, storage_tree as ST, field as F

DEPTH = 8
NQ = 2
fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _store(values=None):
    return ST.SparseStore(DEPTH, values or {1: 11, 2: 22, 3: 33})


def _two_sides():
    """Two transitions from the SAME pre-root over DISJOINT keys — the mergeable case."""
    base = {1: 11, 2: 22, 3: 33}
    a = SX.prove_transition(_store(base), [(1, 111), (4, 44)], num_queries=NQ)
    b = SX.prove_transition(_store(base), [(2, 222), (5, 55)], num_queries=NQ)
    return base, a, b


def t_disjoint_accepted():
    _base, a, b = _two_sides()
    ok, why = SM.check_disjoint(a, b)
    assert ok, why


def t_merge_root_is_order_independent():
    """The merged root must be a pure function of the two inputs — merging B into A and A into B agree."""
    base, a, b = _two_sides()
    p1 = SM.merge_plan(a, b, _store(base))
    p2 = SM.merge_plan(b, a, _store(base))
    assert p1["post_root"] == p2["post_root"], "merged root depends on merge order"
    # ...and it equals simply applying every update to the pre-state
    ref = _store(base)
    for k, v in ((1, 111), (4, 44), (2, 222), (5, 55)):
        ref.set(k, v)
    assert p1["post_root"] == tuple(ref.root()), "merged root != applying both update sets"


def t_merge_proves_and_verifies():
    base, a, b = _two_sides()
    merged = SM.prove_merge(a, b, _store(base), num_queries=NQ)
    ok, why = SM.verify_merge(merged, a, b, num_queries=NQ)
    assert ok, why
    # the merged bundle is an ORDINARY transition: it verifies on its own terms too, so merges nest
    ok2, why2 = SX.verify_transition(merged, tuple(a["roots"][0]), tuple(merged["roots"][-1]),
                                     num_queries=NQ)
    assert ok2, why2


def t_overlapping_keys_refused():
    """Both sides write key 2 — the merged root would depend on who goes last."""
    base = {1: 11, 2: 22}
    a = SX.prove_transition(_store(base), [(2, 222)], num_queries=NQ)
    b = SX.prove_transition(_store(base), [(2, 999)], num_queries=NQ)
    ok, why = SM.check_disjoint(a, b)
    assert not ok, "overlapping key sets must be refused"
    assert "overlap" in why, why
    try:
        SM.merge_plan(a, b, _store(base))
        raise AssertionError("merge_plan must raise on overlapping keys")
    except SM.MergeError:
        pass


def t_different_pre_roots_refused():
    a = SX.prove_transition(_store({1: 11}), [(4, 44)], num_queries=NQ)
    b = SX.prove_transition(_store({1: 99}), [(5, 55)], num_queries=NQ)
    ok, why = SM.check_disjoint(a, b)
    assert not ok, "different pre-roots must be refused"
    assert "pre-root" in why, why


def t_dropped_update_rejected():
    """THE attack: a merged bundle that quietly omits one side's write. Its own proof is perfectly valid —
    only comparing against the union catches it."""
    base, a, b = _two_sides()
    # a "merge" that silently drops b's (5, 55)
    partial = SX.prove_transition(_store(base), [(1, 111), (2, 222), (4, 44)], num_queries=NQ)
    ok_self, _ = SX.verify_transition(partial, tuple(a["roots"][0]), tuple(partial["roots"][-1]),
                                      num_queries=NQ)
    assert ok_self, "control: the partial transition is internally valid, which is what makes this dangerous"
    ok, why = SM.verify_merge(partial, a, b, num_queries=NQ)
    assert not ok, "a merge missing one side's update must be REJECTED"
    assert "union" in why, why


def t_added_update_rejected():
    """The mirror attack: a merged bundle with an EXTRA write nobody proved."""
    base, a, b = _two_sides()
    extra = SX.prove_transition(_store(base), [(1, 111), (2, 222), (4, 44), (5, 55), (6, 66)],
                                num_queries=NQ)
    ok, why = SM.verify_merge(extra, a, b, num_queries=NQ)
    assert not ok, "a merge with an unproven extra update must be REJECTED"
    assert "union" in why, why


def t_wrong_values_rejected():
    """Right keys, wrong value — the merged list must match the inputs exactly, not merely in shape."""
    base, a, b = _two_sides()
    bad = SX.prove_transition(_store(base), [(1, 111), (2, 222), (4, 44), (5, 5555)], num_queries=NQ)
    ok, why = SM.verify_merge(bad, a, b, num_queries=NQ)
    assert not ok, "a merge with an altered value must be REJECTED"


def t_self_overlapping_side_refused():
    """A side that writes the same key twice cannot be merged in parallel: its second write depends on its
    own first, and no interleaving preserves that while also mixing in the other side."""
    base = {1: 11}
    a = SX.prove_transition(_store(base), [(1, 111), (1, 222)], num_queries=NQ)
    b = SX.prove_transition(_store(base), [(2, 22)], num_queries=NQ)
    ok, why = SM.check_disjoint(a, b)
    assert not ok, "a self-overlapping side must be refused"
    assert "more than once" in why, why


if __name__ == "__main__":
    check("disjoint transitions are mergeable", t_disjoint_accepted)
    check("merged root is order-independent and equals applying both", t_merge_root_is_order_independent)
    check("merge proves and verifies (and nests as an ordinary transition)", t_merge_proves_and_verifies)
    check("OVERLAPPING keys refused", t_overlapping_keys_refused)
    check("DIFFERENT pre-roots refused", t_different_pre_roots_refused)
    check("DROPPED update rejected", t_dropped_update_rejected)
    check("ADDED update rejected", t_added_update_rejected)
    check("ALTERED value rejected", t_wrong_values_rejected)
    check("self-overlapping side refused", t_self_overlapping_side_refused)
    print()
    print("ALL PASS — parallel merge composes only what it can prove" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
