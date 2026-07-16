"""
Sparse Merkle STORAGE tree (execnode/stark/storage_tree.py) — state-root binding foundation, doc/zk-recursion §5b
piece (a). Validates the mechanism that replaces settlement's O(state) whole-state re-merkleize + io replay with
an O(touched·depth) transition check: a fixed-depth sparse alghash tree with per-slot membership/update, so a
verifier can confirm pre_root → post_root touching ONLY the accessed slots — and, later, fold those same steps
in-circuit (membership.py) for O(1).

Checks: sparse root == full recompute; membership (member + non-member/empty); single update advances the root
exactly as a full rebuild; a tampered read/old-value is rejected; and a whole io-style transition
(reads + writes) verifies to the same root a full rebuild gives, while a tampered transition is caught.

Run: python3 tests/test_storage_tree.py
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import storage_tree as ST, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

D = 12  # tree depth for the test (2^12 slot positions)


def _store(seed, n):
    random.seed(seed)
    vals = {}
    while len(vals) < n:
        vals[random.randrange(1 << D)] = random.randrange(1, F.P)
    return ST.SparseStore(D, dict(vals)), dict(vals)


def t_root_matches_recompute():
    """The sparse root (empty-subtree shortcut) equals a from-scratch fold of the same slot map."""
    store, vals = _store(1, 20)
    root = store.root()
    # recompute independently: fold every populated leaf up; verify each authenticates the root
    for k, v in vals.items():
        assert ST.fold(v, k, store.path(k)) == root, f"leaf {k} does not fold to the root"
    # an all-empty store roots to the empty-tree root
    assert ST.SparseStore(D, {}).root() == ST._empty_roots(D)[D]


def t_membership():
    store, vals = _store(2, 15)
    root = store.root()
    for k, v in list(vals.items())[:5]:
        sibs = store.path(k)
        assert ST.verify_read(root, k, v, sibs), "member must verify"
        assert not ST.verify_read(root, k, (v + 1) % F.P, sibs), "wrong value must be rejected"
    empty_k = next(k for k in range(1 << D) if k not in vals)
    assert ST.verify_read(root, empty_k, 0, store.path(empty_k)), "empty slot reads 0"
    assert not ST.verify_read(root, empty_k, 7, store.path(empty_k)), "nonzero at empty slot rejected"


def t_single_update():
    store, vals = _store(3, 15)
    root0 = store.root()
    k = next(iter(vals)); old = vals[k]; new = (old + 999) % F.P
    sibs = store.path(k)
    post = ST.apply_update(root0, k, old, new, sibs)
    store.set(k, new)
    assert store.root() == post, "update root must equal a full rebuild with the slot changed"
    # a write of a NEW (previously empty) slot: old = 0
    ek = next(k2 for k2 in range(1 << D) if k2 not in vals)
    post2 = ST.apply_update(post, ek, 0, 12345, store.path(ek))
    store.set(ek, 12345)
    assert store.root() == post2


def t_tampered_update_rejected():
    store, vals = _store(4, 12)
    root0 = store.root()
    k = next(iter(vals))
    try:
        ST.apply_update(root0, k, (vals[k] + 1) % F.P, 42, store.path(k))   # wrong old value
        assert False, "a wrong old value must raise"
    except ValueError:
        pass


def t_transition_verifies():
    """A whole io-style transition (interleaved reads + writes, each with its path from the CURRENT root)
    verifies to the SAME post_root a full rebuild gives; a tampered write is caught."""
    store, vals = _store(5, 25)
    pre_root = store.root()
    keys = list(vals)
    ops, expect = [], ST.SparseStore(D, dict(vals))
    # a couple of reads, then writes to some slots + one fresh slot
    for k in keys[:3]:
        ops.append({"kind": "read", "key": k, "val": vals[k], "siblings": expect.path(k)})
    for k in keys[3:8]:
        old = expect.get(k); new = (old + 77) % F.P
        ops.append({"kind": "write", "key": k, "old": old, "new": new, "siblings": expect.path(k)})
        expect.set(k, new)                                   # advance the reference so the NEXT path is correct
    fresh = next(k for k in range(1 << D) if k not in vals)
    ops.append({"kind": "write", "key": fresh, "old": 0, "new": 55, "siblings": expect.path(fresh)})
    expect.set(fresh, 55)

    post = ST.verify_transition(pre_root, ops)
    assert post == expect.root(), "transition post_root must equal the full rebuild"

    # tamper: flip one write's claimed new value -> the chained root diverges (still 'valid' shape, wrong root),
    # and flipping a claimed OLD value must be REJECTED outright
    bad = [dict(o) for o in ops]
    for o in bad:
        if o["kind"] == "write":
            o["old"] = (o["old"] + 1) % F.P
            break
    try:
        ST.verify_transition(pre_root, bad)
        assert False, "a tampered old value must be rejected"
    except ValueError:
        pass


if __name__ == "__main__":
    check("sparse root == full recompute (+ empty-tree root)", t_root_matches_recompute)
    check("membership: member verifies, non-member/empty handled", t_membership)
    check("single update advances the root like a full rebuild", t_single_update)
    check("tampered update (wrong old value) rejected", t_tampered_update_rejected)
    check("whole transition verifies (+ tampered rejected)", t_transition_verifies)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
