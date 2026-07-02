"""
Field-native shielded pool + delegated prover (execnode/shielded_field.py, doc/privacy.md): the Phase-2 pool
whose notes are exactly what the zk-STARK proves. The tree path folds to the root as the circuit's membership
does, and a delegated STARK transfer verifies through the real verify_transfer seam.

Run: python3 tests/test_shielded_field.py   (slow — generates a real STARK proof)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, membership as MB
from execnode import shielded_field as SF, shielded

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _pool_with_note(nsk, value, rho):
    pool = SF.FieldShieldedPool()
    pool.append(alghash.commit(1, 2, 3))
    cm = alghash.commit(value, alghash.owner_of(nsk), rho)
    pool.append(cm)
    pool.append(alghash.commit(9, 9, 9))
    return pool, cm, pool.position(cm)


def t1_tree_path_folds_to_root():
    pool, cm, pos = _pool_with_note(0x1111, 1000, 0x2222)
    sibs, dirs = SF.tree_path(pool.commitments, pos)
    assert len(sibs) == SF.TREE_DEPTH
    assert MB.merkle_root_from_path(cm, sibs, dirs) == pool.root(), "path must fold to the pool root (== circuit membership)"

def t2_empty_root_and_anchors():
    pool = SF.FieldShieldedPool()
    assert pool.root() == SF.EMPTY_ROOT and pool.knows_root(SF.EMPTY_ROOT)
    r0 = pool.root(); pool.append(alghash.commit(5, 6, 7))
    assert pool.knows_root(r0) and pool.knows_root(pool.root()), "anchor window keeps past + current roots"

def t3_delegated_transfer_verifies():
    pool, cm, pos = _pool_with_note(0x1111, 1000, 0x2222)
    out_owner = alghash.owner_of(0x3333)
    bundle, public = SF.prove_transfer(pool, 0x1111, 1000, 0x2222, pos, 950, out_owner, 0x4444,
                                       public_value=0, fee=50)   # protocol NUM_QUERIES (C-1)
    ok, why = shielded.verify_transfer(public, bundle, pool.knows_root)
    assert ok, f"a delegated STARK transfer must verify through verify_transfer: {why}"

def t4_conservation_violation_rejected():
    pool, cm, pos = _pool_with_note(0x1111, 1000, 0x2222)
    out_owner = alghash.owner_of(0x3333)
    bundle, public = SF.prove_transfer(pool, 0x1111, 1000, 0x2222, pos, 950, out_owner, 0x4444,
                                       public_value=0, fee=50)   # protocol NUM_QUERIES (C-1)
    bundle["stark"]["joinsplit"]["fee"] = 40                 # claim a different fee than proven
    ok, _ = shielded.verify_transfer(public, bundle, pool.knows_root)
    assert not ok, "a conservation-violating transfer must be rejected"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
