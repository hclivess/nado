"""
ML-DSA-44 verify AIR — sub-circuit 3b: the full 256-point negacyclic NTT (execnode/stark/mldsa_ntt_air.py),
composed from the proven butterfly gadget. Validated against dilithium_py's REAL to_ntt / from_ntt /
ntt_coefficient_multiplication. See doc/zk-signature-aggregation.md.

Run: python3 tests/test_mldsa_ntt_air.py
"""
import os, sys, random, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_ntt_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_params as P, mldsa_ntt_air as NTT

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

NQ = 2
Q, N = P.Q, P.N


def _ring():
    from dilithium_py.polynomials.polynomials import PolynomialRing
    return PolynomialRing()


def _rand_poly(seed):
    random.seed(seed)
    return [random.randrange(Q) for _ in range(N)]


def t_zetas_match_reference():
    check("zeta table matches dilithium_py ntt_zetas", NTT.ZETAS == _ring().ntt_zetas)
    check("ntt_f (256^-1 mod Q) matches", NTT.NTT_F == _ring().ntt_f)


def t_forward_matches_dilithium():
    """apply_forward reproduces dilithium's to_ntt exactly, for random + edge polynomials."""
    R = _ring()
    for seed in (1, 7, 42):
        c = _rand_poly(seed)
        got, bfs = NTT.apply_forward(c)
        want = R(c[:]).to_ntt().coeffs
        check(f"forward NTT matches to_ntt (seed {seed})", got == [x % Q for x in want])
        check(f"  schedule is 8 stages x 128 butterflies (seed {seed})", len(bfs) == 8 * 128)


def t_inverse_matches_dilithium():
    """apply_inverse reproduces dilithium's from_ntt (incl. the 256^-1 scale)."""
    R = _ring()
    for seed in (3, 11):
        c = _rand_poly(seed)
        ntt_poly = R(c[:], is_ntt=True)
        want = ntt_poly.from_ntt().coeffs
        got, _bfs = NTT.apply_inverse(c)
        check(f"inverse NTT matches from_ntt (seed {seed})", got == [x % Q for x in want])


def t_roundtrip():
    c = _rand_poly(99)
    fwd, _ = NTT.apply_forward(c)
    back, _ = NTT.apply_inverse(fwd)
    check("NTT roundtrip is the identity", back == [x % Q for x in c])


def t_pointwise_multiplication():
    """NTT-domain pointwise product == dilithium ntt_coefficient_multiplication, and NTT(f)*NTT(g) inverted
    equals the negacyclic product of f and g (the operation A·z actually needs)."""
    R = _ring()
    f, g = _rand_poly(5), _rand_poly(6)
    F_, _ = NTT.apply_forward(f)
    G_, _ = NTT.apply_forward(g)
    prod, pairs = NTT.pointwise(F_, G_)
    want = R(f[:], is_ntt=True).ntt_coefficient_multiplication(F_, G_)
    check("pointwise product matches ntt_coefficient_multiplication", prod == [x % Q for x in want])
    check("pointwise emits one (a,b) pair per coefficient", len(pairs) == N)
    # and the full multiply path agrees with dilithium's own NTT multiplication
    ref = R(f[:]).to_ntt() * R(g[:]).to_ntt()
    back, _ = NTT.apply_inverse(prod)
    check("inverse(NTT(f)·NTT(g)) == dilithium NTT multiplication", back == [x % Q for x in ref.from_ntt().coeffs])


def t_prove_verify_forward():
    """PROVE a full forward NTT (1024 butterflies) and verify it against the public input/output."""
    c = _rand_poly(21)
    proof, out, bfs = NTT.prove_forward(c, num_queries=NQ)
    check("forward NTT proof covers 1024 butterflies", len(bfs) == 1024)
    ok, why = NTT.verify_forward(proof, c, out, num_queries=NQ)
    check(f"full 256-point forward NTT proves + verifies ({why})", ok)
    # a wrong claimed output must be rejected
    bad = list(out); bad[0] = (bad[0] + 1) % Q
    ok2, _ = NTT.verify_forward(proof, c, bad, num_queries=NQ)
    check("a tampered NTT output is rejected", not ok2)


if __name__ == "__main__":
    try:
        t_zetas_match_reference()
        t_forward_matches_dilithium()
        t_inverse_matches_dilithium()
        t_roundtrip()
        t_pointwise_multiplication()
        t_prove_verify_forward()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — the full 256-point NTT matches Dilithium" if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
