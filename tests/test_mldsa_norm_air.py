"""
ML-DSA-44 verify AIR — sub-circuit 1: the ||z||_inf < GAMMA_1 - BETA coefficient bound
(execnode/stark/mldsa_norm_air.py). See doc/zk-signature-aggregation.md.

Validates against the golden reference (dilithium_py, the node's pure-Python PQ backend): the params match,
a REAL signature's decoded z proves + verifies the bound, a tampered (out-of-bound) public coefficient is
rejected, and an out-of-bound coefficient is unprovable by an honest prover.

Run: python3 tests/test_mldsa_norm_air.py
"""
import os, sys, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_mldsa_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_params as P, mldsa_norm_air as NA

fails = 0
def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 4                                     # reduced query strength — this test checks CORRECTNESS, not soundness margin


def _golden():
    """dilithium_py (the node's pure-Python ML-DSA backend) — the byte-exact reference."""
    from dilithium_py.ml_dsa import ML_DSA_44 as m
    return m


def _z_coeffs(m, pk, sig):
    """Flat CENTERED z coefficients from a signature, canonicalized to [0, Q) (the AIR's interface)."""
    _c, z, _h = m._unpack_sig(sig)
    flat = []
    for row in z._data:
        for pol in row:
            flat += list(pol.coeffs)
    return [x % P.Q for x in flat]


def t_params_match_reference():
    m = _golden()
    for attr, ours in (("d", P.D), ("tau", P.TAU), ("gamma_1", P.GAMMA_1), ("gamma_2", P.GAMMA_2),
                       ("k", P.K), ("l", P.L), ("eta", P.ETA), ("omega", P.OMEGA),
                       ("beta", P.BETA), ("c_tilde_bytes", P.C_TILDE_BYTES)):
        ref = getattr(m, attr)
        assert ref == ours, f"param {attr}: ours {ours} != dilithium_py {ref}"
    assert P.Z_BOUND == P.GAMMA_1 - P.BETA == 130994


_M = _golden()
_PK, _SK = _M.keygen()
_SIG = _M.sign(_SK, b"nado-norm-air")
assert _M.verify(_PK, b"nado-norm-air", _SIG), "reference signature must verify"
_Z = _z_coeffs(_M, _PK, _SIG)
_PROOF = NA.prove(_Z, num_queries=NQ)


def t_real_signature_z_in_bound():
    assert len(_Z) == P.L * P.N == 1024
    ok, why = NA.verify(_PROOF, _Z, num_queries=NQ)
    assert ok, f"a real signature's z must prove + verify the norm bound: {why}"


def t_tampered_public_coeff_rejected():
    """Verify the SAME proof against a public z with one coefficient pushed into the forbidden band — the
    boundary no longer matches the proven trace, so it is rejected (the proof is bound to the exact z)."""
    bad = list(_Z)
    bad[7] = (P.Q - 1) // 2                 # dead center => |centered| ~ Q/2, far out of bound
    ok, _ = NA.verify(_PROOF, bad, num_queries=NQ)
    assert not ok, "a tampered public coefficient must be rejected"


def t_out_of_bound_is_unprovable():
    """An honest prover cannot even build a trace for an out-of-bound coefficient."""
    bad = list(_Z)
    bad[0] = (P.Q - 1) // 2                 # centered value ~ Q/2 >> B
    try:
        NA.prove(bad, num_queries=NQ)
        raise AssertionError("proving an out-of-bound coefficient must raise")
    except ValueError:
        pass


def t_boundary_bound_coeff_passes():
    """The extreme in-bound coefficients (centered = +-(B-1)) prove; one step beyond does not."""
    Bm1 = P.Z_BOUND - 1
    ok, why = NA.verify(NA.prove([Bm1 % P.Q, (-Bm1) % P.Q], num_queries=NQ), [Bm1 % P.Q, (-Bm1) % P.Q], num_queries=NQ)
    assert ok, f"centered +-(B-1) must be in bound: {why}"
    try:
        NA.prove([P.Z_BOUND % P.Q], num_queries=NQ)      # centered = B, exactly the rejection threshold
        raise AssertionError("centered value == B must be unprovable")
    except ValueError:
        pass


if __name__ == "__main__":
    check("params match dilithium_py", t_params_match_reference)
    check("real signature z proves + verifies the norm bound", t_real_signature_z_in_bound)
    check("tampered public coefficient rejected", t_tampered_public_coeff_rejected)
    check("out-of-bound coefficient is unprovable", t_out_of_bound_is_unprovable)
    check("centered +-(B-1) in bound, B out of bound", t_boundary_bound_coeff_passes)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
