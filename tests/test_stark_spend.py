"""
Composed SPEND circuit (execnode/stark/spend.py, doc/privacy.md): commitment binding + Merkle membership in
ONE zero-knowledge proof — "I know an opening (value, owner, rho) whose commitment is a leaf in the tree at the
public root", hiding the opening AND which leaf. The two gadgets share a hidden witness (cm), which is what a
private spend requires.

Run: python3 tests/test_stark_spend.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, spend as SP

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

V, OWN, RHO = 500, 0xBEEF, 0x1234
SIBS, DIRS = [111, 222, 333, 444], [0, 1, 0, 1]

def t1_trace_matches_direct():
    cm, root = SP.spend_root(V, OWN, RHO, SIBS, DIRS)
    _, _, _, troot = SP.build_trace(V, OWN, RHO, SIBS, DIRS)
    assert cm == alghash.commit(V, OWN, RHO) and troot == root, "circuit must reproduce commit()+membership"

def t2_valid_spend_verifies():
    proof, root = SP.prove_spend(V, OWN, RHO, SIBS, DIRS)
    ok, why = SP.verify_spend(proof, root, lambda r: True)
    assert ok, f"a valid spend must verify: {why}"

def t3_wrong_root_rejected():
    proof, root = SP.prove_spend(V, OWN, RHO, SIBS, DIRS)
    ok, _ = SP.verify_spend(proof, F.add(root, 1), lambda r: True)
    assert not ok, "a wrong root must be rejected"

def t4_unknown_anchor_rejected():
    proof, root = SP.prove_spend(V, OWN, RHO, SIBS, DIRS)
    ok, why = SP.verify_spend(proof, root, lambda r: False)
    assert not ok and "anchor" in why, "an unknown anchor must be rejected"

def t5_different_opening_different_root():
    _, r1 = SP.spend_root(V, OWN, RHO, SIBS, DIRS)
    _, r2 = SP.spend_root(V + 1, OWN, RHO, SIBS, DIRS)    # a different value -> different commitment -> different tree fit
    assert r1 != r2, "the opening is bound into the proven root"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
