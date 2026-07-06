"""
Complete 1-in/1-out JOIN-SPLIT circuit (execnode/stark/joinsplit_circuit.py, doc/privacy.md): the ENTIRE
shielded transfer statement in ONE zero-knowledge proof — owner binding, input commitment, Merkle membership,
nullifier, output commitment, AND value conservation over the SECRET values — revealing only root, nf, cm_out,
public_value, fee.

Run: python3 tests/test_stark_joinsplit_circuit.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, joinsplit_circuit as JC, stark

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NSK, VIN, RHO = 0xCAFE, 900, 0x9999
SIBS, DIRS = [111, 222, 333, 444], [0, 1, 0, 1]
VOUT, OWN_OUT, RHO_OUT = 850, 0xABC, 0x5555
PUB, FEE = 0, 50                                     # 900 + 0 == 850 + 50

def _prove(q=stark.NUM_QUERIES):   # q must match the protocol NUM_QUERIES so verify_transfer accepts it (C-1)
    """Prove the module's canonical 900-in/850+50-fee transfer and return (proof, root, nf, cm_out)."""
    return JC.prove_transfer(NSK, VIN, RHO, SIBS, DIRS, VOUT, OWN_OUT, RHO_OUT, PUB, FEE, num_queries=q)

def t1_trace_matches_direct():
    """Prove the AIR trace reproduces the direct transfer() outputs (root, nf, cm_out)."""
    owner, cm_in, nf, root, cm_out = JC.transfer(NSK, VIN, RHO, SIBS, DIRS, VOUT, OWN_OUT, RHO_OUT)
    _, _, _, troot, tnf, tcm = JC.build_trace(NSK, VIN, RHO, SIBS, DIRS, VOUT, OWN_OUT, RHO_OUT)
    assert troot == root and tnf == nf and tcm == cm_out, "circuit must reproduce the whole transfer"

def t2_valid_transfer_verifies():
    """Prove an honest join-split transfer proof passes verify_transfer."""
    proof, root, nf, cm_out = _prove()
    ok, why = JC.verify_transfer(proof, root, nf, cm_out, PUB, FEE, lambda r: True)
    assert ok, f"a valid transfer must verify: {why}"

def t3_conservation_enforced():
    """Prove value conservation is enforced: claiming a different public fee is rejected."""
    proof, root, nf, cm_out = _prove()
    ok, _ = JC.verify_transfer(proof, root, nf, cm_out, PUB, FEE - 10, lambda r: True)   # claim a different fee
    assert not ok, "value conservation must be enforced (a wrong fee is rejected)"

def t4_wrong_outputs_or_nullifier_rejected():
    """Prove a tampered output commitment or nullifier is rejected."""
    proof, root, nf, cm_out = _prove()
    assert not JC.verify_transfer(proof, root, nf, F.add(cm_out, 1), PUB, FEE, lambda r: True)[0]
    assert not JC.verify_transfer(proof, root, F.add(nf, 1), cm_out, PUB, FEE, lambda r: True)[0]

def t5_membership_and_anchor():
    """Prove a wrong Merkle root and an unknown anchor are both rejected."""
    proof, root, nf, cm_out = _prove()
    assert not JC.verify_transfer(proof, F.add(root, 1), nf, cm_out, PUB, FEE, lambda r: True)[0], "wrong root"
    ok, why = JC.verify_transfer(proof, root, nf, cm_out, PUB, FEE, lambda r: False)
    assert not ok and "anchor" in why, "unknown anchor must be rejected"

def t6_full_proof_through_verify_transfer_seam():
    """Prove a full depth-TREE_DEPTH proof passes shielded.verify_transfer, while a wrong fee or wrong-depth proof (H1) is rejected by the seam."""
    # route the FULL join-split proof through the real verify_transfer seam (execnode/shielded.py). The seam
    # pins the proof's Merkle depth to the field pool's TREE_DEPTH (H1), so build a real depth-TREE_DEPTH path.
    from execnode import shielded
    from execnode.shielded_field import TREE_DEPTH
    sibs = [i + 1 for i in range(TREE_DEPTH)]
    dirs = [i % 2 for i in range(TREE_DEPTH)]
    proof, root, nf, cm_out = JC.prove_transfer(NSK, VIN, RHO, sibs, dirs, VOUT, OWN_OUT, RHO_OUT, PUB, FEE)
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
    # H1: a proof whose Merkle depth != TREE_DEPTH must be rejected by the seam
    shallow_proof, sr, snf, scm = _prove()   # module SIBS/DIRS have depth 4
    shallow = {"stark": {"joinsplit": {"proof": shallow_proof, "root": sr, "nf": snf, "cm_out": scm,
                                       "public_value": PUB, "fee": FEE}}}
    ok3, why3 = shielded.verify_transfer({"out_commitments": [scm]}, shallow, lambda r: True)
    assert not ok3 and "depth" in why3, f"wrong-depth proof must be rejected by the seam, got {ok3} ({why3})"

def t7_c3_wraparound_exit_rejected():
    """Prove the C-3 mod-P wraparound exit (negative public_value forcing change ~ 2^64) is rejected by the in-circuit range proof."""
    # C-3: spend the real 900-coin note but declare public_value = -10^18. Value conservation forces the
    # "change" value to wrap mod P into a ~2^64 field element; the in-circuit range proof (< 2^61) must reject.
    X = 10 ** 18
    v_out_wrapped = (VIN - X) % F.P                 # ≈ P, far outside [0, 2^61)
    proof, root, nf, cm_out = JC.prove_transfer(NSK, VIN, RHO, SIBS, DIRS, v_out_wrapped, OWN_OUT, RHO_OUT, -X, 0)
    ok, why = JC.verify_transfer(proof, root, nf, cm_out, -X, 0, lambda r: True)
    assert not ok, f"C-3 wraparound exit MUST be rejected by the range proof, got ok={ok} ({why})"

def t8_c3_in_range_value_still_verifies():
    """Prove the largest in-range value (2^61 - 1) still verifies — the range proof accepts honest txs."""
    # the largest in-range value (< 2^61) must still verify — the range proof doesn't reject honest txs.
    big = (1 << 61) - 1
    proof, root, nf, cm_out = JC.prove_transfer(NSK, big, RHO, SIBS, DIRS, big, OWN_OUT, RHO_OUT, 0, 0)
    ok, why = JC.verify_transfer(proof, root, nf, cm_out, 0, 0, lambda r: True)
    assert ok, f"an in-range value must still verify: {why}"

def t9_c3b_2output_wraparound_rejected():
    """Prove a value of exactly 2^61 is rejected (C-3b two-output wraparound; the bound is strict < 2^61)."""
    # C-3b: the 2-output conservation wraparound (1-coin input -> 2^62 exit) must be rejected now that every
    # value is bounded to < 2^61. (Full end-to-end PoC is in tests/test_stark_joinsplit2.py.)
    big_oob = (1 << 61)                              # exactly 2^61 -> out of range under the 3-top-bit rule
    proof, root, nf, cm_out = JC.prove_transfer(NSK, VIN, RHO, SIBS, DIRS, big_oob, OWN_OUT, RHO_OUT,
                                                (VIN - big_oob), 0)
    ok, why = JC.verify_transfer(proof, root, nf, cm_out, (VIN - big_oob), 0, lambda r: True)
    assert not ok, f"a value of exactly 2^61 MUST be rejected (bound is < 2^61), got ok={ok} ({why})"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
