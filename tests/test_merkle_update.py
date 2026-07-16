"""
Merkle-UPDATE AIR (execnode/stark/merkle_update.py) — the in-circuit O(1) core of state-root binding. Proves
that rewriting ONE leaf old_val → new_val at a shared position turns pre_root into post_root (two parallel
alghash sponge folds over shared sibling/dir columns). CROSS-CHECKED against the native storage_tree folds:
the AIR's pre_root/post_root must equal storage_tree's, and the proof must verify; soundness — a wrong
old/new/pre/post, or a proof whose two chains don't share the path, is rejected.

Run: python3 tests/test_merkle_update.py
"""
import os, sys, copy, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import merkle_update as MU, storage_tree as ST, field as F, backend as B

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

D, NQ = 8, 8


def _case(seed):
    random.seed(seed)
    vals = {}
    while len(vals) < 12:
        vals[random.randrange(1 << D)] = random.randrange(1, F.P)
    store = ST.SparseStore(D, dict(vals))
    k = next(iter(vals))
    old = store.get(k)
    new = (old + 987654321) % F.P
    siblings = store.path(k)
    dirs = [(k >> i) & 1 for i in range(D)]
    return store, k, old, new, siblings, dirs


def t_roots_match_storage_tree():
    """The AIR's pre_root/post_root equal storage_tree's native folds (same hash, same direction convention)."""
    store, k, old, new, siblings, dirs = _case(1)
    proof, pre_root, post_root = MU.prove_update(old, new, siblings, dirs, num_queries=NQ, backend=B.ALGHASH2)
    assert pre_root == ST.fold(old, k, siblings) == store.root(), "pre_root must match the native fold"
    store.set(k, new)
    assert post_root == store.root(), "post_root must be the tree with the slot rewritten"


def t_update_proof_verifies():
    store, k, old, new, siblings, dirs = _case(2)
    proof, pre_root, post_root = MU.prove_update(old, new, siblings, dirs, num_queries=NQ, backend=B.ALGHASH2)
    ok, why = MU.verify_update(proof, old, new, pre_root, post_root, dirs, num_queries=NQ, backend=B.ALGHASH2)
    assert ok, f"honest update proof must verify: {why}"


def t_fresh_slot_update():
    """Writing a previously-EMPTY slot (old = 0) is a valid update too."""
    store, _k, _o, _n, _s, _d = _case(3)
    empty = next(k2 for k2 in range(1 << D) if k2 not in store.values)
    siblings = store.path(empty)
    dirs = [(empty >> i) & 1 for i in range(D)]
    proof, pre_root, post_root = MU.prove_update(0, 4242, siblings, dirs, num_queries=NQ, backend=B.ALGHASH2)
    assert pre_root == store.root()
    store.set(empty, 4242)
    assert post_root == store.root()
    ok, why = MU.verify_update(proof, 0, 4242, pre_root, post_root, dirs, num_queries=NQ, backend=B.ALGHASH2)
    assert ok, why


def t_soundness():
    """A verifier that pins a WRONG public value/root rejects the proof (the boundaries are the statement)."""
    store, k, old, new, siblings, dirs = _case(4)
    proof, pre_root, post_root = MU.prove_update(old, new, siblings, dirs, num_queries=NQ, backend=B.ALGHASH2)
    P = F.P
    assert not MU.verify_update(proof, old, new, pre_root, (post_root + 1) % P, dirs, num_queries=NQ, backend=B.ALGHASH2)[0], "wrong post_root"
    assert not MU.verify_update(proof, old, new, (pre_root + 1) % P, post_root, dirs, num_queries=NQ, backend=B.ALGHASH2)[0], "wrong pre_root"
    assert not MU.verify_update(proof, (old + 1) % P, new, pre_root, post_root, dirs, num_queries=NQ, backend=B.ALGHASH2)[0], "wrong old_val"
    assert not MU.verify_update(proof, old, (new + 1) % P, pre_root, post_root, dirs, num_queries=NQ, backend=B.ALGHASH2)[0], "wrong new_val"
    wrong_dirs = list(dirs); wrong_dirs[0] ^= 1                  # flip one position bit
    assert not MU.verify_update(proof, old, new, pre_root, post_root, wrong_dirs, num_queries=NQ, backend=B.ALGHASH2)[0], "wrong position"


def t_tampered_trace_rejected():
    """A tampered opening (a corrupted committed cell) fails the composition spot-check."""
    store, k, old, new, siblings, dirs = _case(5)
    proof, pre_root, post_root = MU.prove_update(old, new, siblings, dirs, num_queries=NQ, backend=B.ALGHASH2)
    bad = copy.deepcopy(proof)
    q = bad["openings"][0]["cols"][MU.SIB]
    q["cur"] = (int(q["cur"]) + 1) % F.P
    ok, _ = MU.verify_update(bad, old, new, pre_root, post_root, dirs, num_queries=NQ, backend=B.ALGHASH2)
    assert not ok, "a tampered committed cell must be rejected"


def t_recursion_committed():
    """Provable under the RECURSION backend too (rleaf/rnode) → foldable into settlement later."""
    store, k, old, new, siblings, dirs = _case(6)
    proof, pre_root, post_root = MU.prove_update(old, new, siblings, dirs, num_queries=NQ, backend=B.RECURSION)
    ok, why = MU.verify_update(proof, old, new, pre_root, post_root, dirs, num_queries=NQ, backend=B.RECURSION)
    assert ok, f"RECURSION-committed update must verify: {why}"


if __name__ == "__main__":
    check("AIR roots match storage_tree native folds", t_roots_match_storage_tree)
    check("honest update proof verifies", t_update_proof_verifies)
    check("fresh-slot (old=0) update verifies", t_fresh_slot_update)
    check("soundness: wrong public value/root rejected", t_soundness)
    check("tampered committed cell rejected", t_tampered_trace_rejected)
    check("provable + verifiable under RECURSION backend (foldable)", t_recursion_committed)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
