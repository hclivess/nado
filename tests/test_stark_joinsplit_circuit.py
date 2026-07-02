"""
Complete 1-in/1-out JOIN-SPLIT circuit (execnode/stark/joinsplit_circuit.py, doc/privacy.md): the ENTIRE
shielded transfer statement in ONE zero-knowledge proof — owner binding, input commitment, Merkle membership,
nullifier, output commitment, AND value conservation over the SECRET values — revealing only root, nf, cm_out,
public_value, fee.

Run: python3 tests/test_stark_joinsplit_circuit.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, joinsplit_circuit as JC

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NSK, VIN, RHO = 0xCAFE, 900, 0x9999
SIBS, DIRS = [111, 222, 333, 444], [0, 1, 0, 1]
VOUT, OWN_OUT, RHO_OUT = 850, 0xABC, 0x5555
PUB, FEE = 0, 50                                     # 900 + 0 == 850 + 50

def _prove(q=40):   # q must match the protocol NUM_QUERIES so verify_transfer accepts it (C-1)
    return JC.prove_transfer(NSK, VIN, RHO, SIBS, DIRS, VOUT, OWN_OUT, RHO_OUT, PUB, FEE, num_queries=q)

def t1_trace_matches_direct():
    owner, cm_in, nf, root, cm_out = JC.transfer(NSK, VIN, RHO, SIBS, DIRS, VOUT, OWN_OUT, RHO_OUT)
    _, _, _, troot, tnf, tcm = JC.build_trace(NSK, VIN, RHO, SIBS, DIRS, VOUT, OWN_OUT, RHO_OUT)
    assert troot == root and tnf == nf and tcm == cm_out, "circuit must reproduce the whole transfer"

def t2_valid_transfer_verifies():
    proof, root, nf, cm_out = _prove()
    ok, why = JC.verify_transfer(proof, root, nf, cm_out, PUB, FEE, lambda r: True)
    assert ok, f"a valid transfer must verify: {why}"

def t3_conservation_enforced():
    proof, root, nf, cm_out = _prove()
    ok, _ = JC.verify_transfer(proof, root, nf, cm_out, PUB, FEE - 10, lambda r: True)   # claim a different fee
    assert not ok, "value conservation must be enforced (a wrong fee is rejected)"

def t4_wrong_outputs_or_nullifier_rejected():
    proof, root, nf, cm_out = _prove()
    assert not JC.verify_transfer(proof, root, nf, F.add(cm_out, 1), PUB, FEE, lambda r: True)[0]
    assert not JC.verify_transfer(proof, root, F.add(nf, 1), cm_out, PUB, FEE, lambda r: True)[0]

def t5_membership_and_anchor():
    proof, root, nf, cm_out = _prove()
    assert not JC.verify_transfer(proof, F.add(root, 1), nf, cm_out, PUB, FEE, lambda r: True)[0], "wrong root"
    ok, why = JC.verify_transfer(proof, root, nf, cm_out, PUB, FEE, lambda r: False)
    assert not ok and "anchor" in why, "unknown anchor must be rejected"

def t6_full_proof_through_verify_transfer_seam():
    # route the FULL join-split proof through the real verify_transfer seam (execnode/shielded.py)
    from execnode import shielded
    proof, root, nf, cm_out = _prove()
    bundle = {"stark": {"joinsplit": {"proof": proof, "root": root, "nf": nf, "cm_out": cm_out,
                                      "public_value": PUB, "fee": FEE}}}
    public = {"out_commitments": [cm_out]}
    ok, why = shielded.verify_transfer(public, bundle, lambda r: True)
    assert ok, f"a full STARK transfer must verify through verify_transfer: {why}"
    # tamper the public fee -> conservation fails through the seam
    bad = {"stark": {"joinsplit": {"proof": proof, "root": root, "nf": nf, "cm_out": cm_out,
                                   "public_value": PUB, "fee": FEE - 5}}}
    ok2, _ = shielded.verify_transfer(public, bad, lambda r: True)
    assert not ok2, "verify_transfer must reject a conservation-violating STARK transfer"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
