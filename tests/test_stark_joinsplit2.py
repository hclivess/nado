"""
2-output JOIN-SPLIT circuit (execnode/stark/joinsplit2.py, doc/privacy.md): 1-in/2-out — a shielded transfer
that sends any amount and keeps the CHANGE, in one zero-knowledge STARK. Public: root, nf, cm_out1, cm_out2,
public_value, fee; conservation v_in + public_value = v_out1 + v_out2 + fee over the SECRET values.

Run: python3 tests/test_stark_joinsplit2.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, joinsplit2 as J2, stark
from execnode import shielded_field as SF

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NSK, VIN, RHO = 0xCAFE, 1000, 0x1111
V1, O1, R1 = 700, alghash.owner_of(0xB0B), 0x2222        # to recipient
V2, O2, R2 = 300, alghash.owner_of(0xCAFE), 0x3333       # change back to self

def _pool():
    pool = SF.FieldShieldedPool()
    pool.append(alghash.commit(VIN, alghash.owner_of(NSK), RHO))
    sibs, dirs = SF.tree_path(pool.commitments, 0)
    return pool, sibs, dirs

def _prove(pub=0, fee=0, q=stark.NUM_QUERIES):   # q must match the protocol NUM_QUERIES so verify_transfer accepts it (C-1)
    pool, sibs, dirs = _pool()
    return J2.prove_transfer(NSK, VIN, RHO, sibs, dirs, V1, O1, R1, V2, O2, R2, pub, fee, num_queries=q)

def t1_trace_matches():
    pool, sibs, dirs = _pool()
    owner, cmi, nf, root, cm1, cm2 = J2.transfer(NSK, VIN, RHO, sibs, dirs, V1, O1, R1, V2, O2, R2)
    _, _, _, tr, tn, tc1, tc2 = J2.build_trace(NSK, VIN, RHO, sibs, dirs, V1, O1, R1, V2, O2, R2)
    assert tr == root and tn == nf and tc1 == cm1 and tc2 == cm2, "circuit must reproduce the 2-output transfer"

def t2_valid_transfer_verifies():
    proof, root, nf, cm1, cm2 = _prove()
    ok, why = J2.verify_transfer(proof, root, nf, cm1, cm2, 0, 0, lambda r: True)
    assert ok, f"a valid 2-output transfer must verify: {why}"

def t3_conservation_enforced():
    proof, root, nf, cm1, cm2 = _prove()
    assert not J2.verify_transfer(proof, root, nf, cm1, cm2, 0, 10, lambda r: True)[0], "wrong fee must be rejected"

def t4_wrong_outputs_rejected():
    proof, root, nf, cm1, cm2 = _prove()
    assert not J2.verify_transfer(proof, root, nf, F.add(cm1, 1), cm2, 0, 0, lambda r: True)[0]
    assert not J2.verify_transfer(proof, root, nf, cm1, F.add(cm2, 1), 0, 0, lambda r: True)[0]

def t5_membership_and_anchor():
    proof, root, nf, cm1, cm2 = _prove()
    assert not J2.verify_transfer(proof, F.add(root, 1), nf, cm1, cm2, 0, 0, lambda r: True)[0]
    ok, why = J2.verify_transfer(proof, root, nf, cm1, cm2, 0, 0, lambda r: False)
    assert not ok and "anchor" in why

def t6_c3_wraparound_exit_rejected():
    # C-3: spend the real 1000-coin note but declare public_value = -10^18. Conservation forces a "change"
    # value to wrap mod P into a ~2^64 field element; the in-circuit range proof (< 2^62) must reject it.
    pool, sibs, dirs = _pool()
    X = 10 ** 18
    v2_wrapped = (VIN - V1 - (-X)) % F.P            # v_in - v1 - v2 == fee - public_value(=-X) -> v2 wraps
    proof, root, nf, cm1, cm2 = J2.prove_transfer(NSK, VIN, RHO, sibs, dirs, V1, O1, R1,
                                                  v2_wrapped, O2, R2, -X, 0)
    ok, why = J2.verify_transfer(proof, root, nf, cm1, cm2, -X, 0, lambda r: True)
    assert not ok, f"C-3 wraparound exit MUST be rejected, got ok={ok} ({why})"

def t7_c3_in_range_values_verify():
    # large-but-in-range values (< 2^61) still verify
    pool = SF.FieldShieldedPool()
    big = (1 << 61) - 1
    pool.append(alghash.commit(big, alghash.owner_of(NSK), RHO))
    sibs, dirs = SF.tree_path(pool.commitments, 0)
    proof, root, nf, cm1, cm2 = J2.prove_transfer(NSK, big, RHO, sibs, dirs, big - 1, O1, R1, 1, O2, R2, 0, 0)
    ok, why = J2.verify_transfer(proof, root, nf, cm1, cm2, 0, 0, lambda r: True)
    assert ok, f"in-range values must still verify: {why}"

def t8_c3b_2output_conservation_wraparound_rejected():
    # C-3b: the 2-output conservation wraparound. Deposit 1000, but with fee=2^62 / public_value=-2^62 and two
    # ~2^62 change outputs the mod-P equation admits (v_in - v_out1 - v_out2) - (fee - pv) == -P, which under the
    # OLD 2^62 bound recorded a 2^62-coin unshield from a 1000-coin note. Under the < 2^61 bound the crafted
    # outputs are out of range -> the range proof rejects. (v_out1 = 2^62-1 exceeds 2^61.)
    pool, sibs, dirs = _pool()
    pv, fee = -(1 << 62), (1 << 62)
    VOUT1, VOUT2 = (1 << 62) - 1, (1 << 62) - (1 << 32) + 1002
    assert (VIN - VOUT1 - VOUT2) % F.P == (fee - pv) % F.P, "the mod-P equation still balances (the exploit premise)"
    proof, root, nf, cm1, cm2 = J2.prove_transfer(NSK, VIN, RHO, sibs, dirs, VOUT1, O1, R1, VOUT2, O2, R2, pv, fee)
    ok, why = J2.verify_transfer(proof, root, nf, cm1, cm2, pv, fee, lambda r: True)
    assert not ok, f"C-3b 2-output wraparound MUST be rejected, got ok={ok} ({why})"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
