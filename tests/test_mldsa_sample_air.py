"""
ML-DSA-44 verify AIR — sub-circuit 8: ExpandA + SampleInBall (execnode/stark/mldsa_sample_air.py).
Validated against dilithium_py's real rejection_sample_ntt_poly / sample_in_ball, driven by our own proven
sponge (so this also cross-checks the sponge against dilithium's XOF usage).

Run: python3 tests/test_mldsa_sample_air.py
"""
import os, sys, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_sample_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_params as P, mldsa_sample_air as SA

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def _ring():
    from dilithium_py.polynomials.polynomials import PolynomialRing
    return PolynomialRing()


def t_expand_a_matches_reference():
    """Every one of the k x l = 16 matrix entries must equal dilithium's rejection_sample_ntt_poly."""
    R = _ring()
    rho = bytes(range(32))
    ok_all = True
    for i in range(P.K):
        for j in range(P.L):
            ours, _draws = SA.rejection_sample_poly(rho, i, j)
            ref = R.rejection_sample_ntt_poly(rho, i, j).coeffs
            if ours != list(ref):
                ok_all = False
                print(f"   A[{i}][{j}] mismatch: ours[:4]={ours[:4]} ref[:4]={list(ref)[:4]}")
                break
        if not ok_all:
            break
    check("ExpandA: all 16 matrix entries match dilithium rejection_sample_ntt_poly", ok_all)
    A = SA.expand_a(rho)
    check("ExpandA returns a k x l matrix of 256-coefficient polys",
          len(A) == P.K and len(A[0]) == P.L and all(len(p) == P.N for r in A for p in r))
    check("every ExpandA coefficient is a valid field element (< Q)",
          all(0 <= c < P.Q for r in A for p in r for c in p))


def t_expand_a_second_seed():
    """A different rho must give a different matrix, and still match the reference."""
    R = _ring()
    rho = bytes([7] * 32)
    ours, _ = SA.rejection_sample_poly(rho, 2, 3)
    check("ExpandA with a second seed matches the reference",
          ours == list(R.rejection_sample_ntt_poly(rho, 2, 3).coeffs))
    other, _ = SA.rejection_sample_poly(bytes(range(32)), 2, 3)
    check("different rho yields a different polynomial", ours != other)


def t_sample_in_ball_matches_reference():
    R = _ring()
    for seed in (bytes(range(32)), bytes([0] * 32), os.urandom(32)):
        ours, _draws = SA.sample_in_ball(seed)
        ref = list(R.sample_in_ball(seed, P.TAU).coeffs)
        check(f"SampleInBall matches dilithium (seed {seed[:4].hex()})", ours == ref)
        check("  exactly tau nonzero coefficients", sum(1 for c in ours if c != 0) == P.TAU)
        check("  all nonzero coefficients are +-1", all(c in (1, -1) for c in ours if c != 0))


def t_rejection_witness_soundness():
    """The rejection decisions are verifier-derivable: an accepted draw is < bound, a rejected one is >=.
    That two-sided statement is what the range AIR proves, and it is what stops a prover from dropping a
    valid draw or accepting an invalid one."""
    rho = bytes(range(32))
    _c, draws = SA.rejection_sample_poly(rho, 0, 0)
    check("ExpandA rejection witness is consistent (accepted <=> value < Q)", SA.witness_consistent(draws, P.Q))
    rows = SA.rejection_witness(draws, P.Q)
    check("witness rows are (value, accepted, bound)", all(len(r) == 3 and r[2] == P.Q for r in rows))
    check("accepted draws equal the polynomial length", sum(a for _v, a in draws) == P.N)
    # a tampered decision must be detectable
    bad = [(v, 1 - a) if idx == 0 else (v, a) for idx, (v, a) in enumerate(draws)]
    check("a flipped accept/reject decision is detected", not SA.witness_consistent(bad, P.Q))
    _c2, draws2 = SA.sample_in_ball(bytes(range(32)))
    # SampleInBall's bound is per-draw (j <= i), so check the accepted ones are within the byte range
    check("SampleInBall accepted draws are bytes", all(0 <= v < 256 for v, a in draws2 if a))


def t_cost_profile():
    """Measure the dominant cost so the design's proof-size budget is grounded in real numbers."""
    cost = SA.expand_a_cost(bytes(range(32)))
    check(f"ExpandA cost measured: {cost['draws']} draws, {cost['xof_bytes']} XOF bytes, "
          f"~{cost['permutations']} Keccak permutations", cost["draws"] >= P.N * P.K * P.L)
    print(f"      -> ExpandA alone needs ~{cost['permutations']} proven Keccak-f permutations per signature")


if __name__ == "__main__":
    try:
        t_expand_a_matches_reference()
        t_expand_a_second_seed()
        t_sample_in_ball_matches_reference()
        t_rejection_witness_soundness()
        t_cost_profile()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — ExpandA + SampleInBall match Dilithium" if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
