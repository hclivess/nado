"""
Full AUTHORISED-SPEND circuit (execnode/stark/spend_full.py, doc/privacy.md): the complete input side of a
shielded spend in ONE zero-knowledge proof — owner=H(nsk), cm=commit(value,owner,rho), nf=H(nsk,rho), and
membership of cm to the public root, all bound by the shared secret nsk/rho and revealing only root + nf.

Run: python3 tests/test_stark_spend_full.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, spend_full as SF

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NSK, V, RHO = 0xCAFE, 700, 0x9999
SIBS, DIRS = [111, 222, 333, 444], [0, 1, 0, 1]

def t1_trace_matches_direct():
    """Prove the AIR trace reproduces the direct owner->commit->nullifier->membership chain (root, nf)."""
    owner, cm, nf, root = SF.full_spend(NSK, V, RHO, SIBS, DIRS)
    _, _, _, troot, tnf = SF.build_trace(NSK, V, RHO, SIBS, DIRS)
    assert troot == root and tnf == nf, "circuit must reproduce owner->commit->nullifier->membership"

def t2_valid_spend_verifies():
    """Prove an honest authorised-spend proof passes verify_spend."""
    proof, root, nf = SF.prove_spend(NSK, V, RHO, SIBS, DIRS)
    ok, why = SF.verify_spend(proof, root, nf, lambda r: True)
    assert ok, f"a valid authorised spend must verify: {why}"

def t3_wrong_root_rejected():
    """Prove verification against a wrong public root is rejected."""
    proof, root, nf = SF.prove_spend(NSK, V, RHO, SIBS, DIRS)
    assert not SF.verify_spend(proof, F.add(root, 1), nf, lambda r: True)[0], "wrong root must be rejected"

def t4_wrong_nullifier_rejected():
    """Prove a tampered public nullifier is rejected."""
    proof, root, nf = SF.prove_spend(NSK, V, RHO, SIBS, DIRS)
    assert not SF.verify_spend(proof, root, F.add(nf, 1), lambda r: True)[0], "wrong nf must be rejected"

def t5_unknown_anchor_rejected():
    """Prove a root the anchor callback doesn't recognize is rejected."""
    proof, root, nf = SF.prove_spend(NSK, V, RHO, SIBS, DIRS)
    ok, why = SF.verify_spend(proof, root, nf, lambda r: False)
    assert not ok and "anchor" in why, "unknown anchor must be rejected"

def t6_nullifier_binds_the_key():
    """Prove nf = H(nsk, rho) binds the spend key: a different nsk yields a different nullifier."""
    # nf is H(nsk,rho); a different spend key yields a different nullifier (authorisation binding)
    _, _, nf1, _ = SF.full_spend(NSK, V, RHO, SIBS, DIRS)
    _, _, nf2, _ = SF.full_spend(NSK + 1, V, RHO, SIBS, DIRS)
    assert nf1 != nf2, "the nullifier must bind the spend key"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
