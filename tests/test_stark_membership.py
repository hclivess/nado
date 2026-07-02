"""
Merkle-membership STARK (execnode/stark/membership.py, doc/privacy.md): prove a PRIVATE leaf sits in the tree
at a PUBLIC root via a PRIVATE path + direction bits, in zero-knowledge. A valid path verifies; a wrong root,
an unknown anchor, or a tampered path is rejected.

Run: python3 tests/test_stark_membership.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, membership as M

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

LEAF, SIBS, DIRS = 0xABCDEF12345, [1111, 2222, 3333, 4444], [0, 1, 1, 0]

def t1_trace_matches_direct():
    _, _, _, root = M.build_trace(LEAF, SIBS, DIRS)
    assert root == M.merkle_root_from_path(LEAF, SIBS, DIRS), "AIR trace must reproduce the Merkle root"

def t2_valid_membership_verifies():
    proof, root = M.prove_membership(LEAF, SIBS, DIRS)
    ok, why = M.verify_membership(proof, root, lambda r: True)
    assert ok, f"valid membership must verify: {why}"

def t3_wrong_root_rejected():
    proof, root = M.prove_membership(LEAF, SIBS, DIRS)
    ok, _ = M.verify_membership(proof, F.add(root, 1), lambda r: True)
    assert not ok, "a wrong root must be rejected"

def t4_unknown_anchor_rejected():
    proof, root = M.prove_membership(LEAF, SIBS, DIRS)
    ok, why = M.verify_membership(proof, root, lambda r: False)
    assert not ok and "anchor" in why, f"an unknown anchor must be rejected: {why}"

def t5_different_directions_change_root():
    # the direction bits are part of the witness — flipping one yields a different root (position matters)
    r1 = M.merkle_root_from_path(LEAF, SIBS, [0, 1, 1, 0])
    r2 = M.merkle_root_from_path(LEAF, SIBS, [1, 1, 1, 0])
    assert r1 != r2, "direction bits must affect the root"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
