"""
ML-DSA-44 verify AIR — sub-circuit 3a: the NTT butterfly gadget (execnode/stark/mldsa_butterfly_air.py).
Validated against dilithium_py's real ntt_zetas table + the exact to_ntt butterfly. See
doc/zk-signature-aggregation.md.

Run: python3 tests/test_mldsa_butterfly_air.py
"""
import os, sys, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_bfly_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_params as P, mldsa_butterfly_air as BF

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

NQ = 4
Q = P.Q


def _zetas():
    from dilithium_py.polynomials.polynomials import PolynomialRing
    return PolynomialRing().ntt_zetas          # the real Dilithium twiddle table (bit-reversed powers of 1753)


# a spread of butterflies using REAL Dilithium zetas + coefficients near the edges
_Z = _zetas()
BFS = [(0, 12345, _Z[1]), (Q - 1, Q - 1, _Z[2]), (4190208, 7777, _Z[3]),
       (1, Q - 1, _Z[10]), (100, 200, _Z[64]), (Q - 1, 1, _Z[127])]
_PROOF = BF.prove(BFS, num_queries=NQ)


def t_matches_dilithium_butterfly():
    """out0 = (a + zeta*b) mod Q, out1 = (a - zeta*b) mod Q — exactly one to_ntt butterfly (dilithium reduces at
    the end; per-butterfly reduction is equivalent)."""
    got = BF.outputs(BFS)
    want = [((a + z * b) % Q, (a - z * b) % Q) for a, b, z in BFS]
    check("butterfly outputs match the Dilithium (a±zeta·b) mod Q", got == want)


def t_prove_verify():
    ok, why = BF.verify(_PROOF, BFS, num_queries=NQ)
    check(f"batch of NTT butterflies proves + verifies ({why})", ok)


def t_tampered_input_rejected():
    bad = list(BFS)
    bad[2] = (bad[2][0], (bad[2][1] + 1) % Q, bad[2][2])
    ok, _ = BF.verify(_PROOF, bad, num_queries=NQ)
    check("a tampered butterfly input is rejected", not ok)


def t_first_stage_over_a_real_poly():
    """Reproduce dilithium's FIRST NTT stage (l=128, zeta=zetas[1]) as 128 butterflies and check the gadget
    proves the exact (coeffs[j]±zeta·coeffs[j+128]) results the reference computes."""
    import random
    random.seed(42)
    coeffs = [random.randrange(Q) for _ in range(256)]
    z1 = _Z[1]
    bfs = [(coeffs[j], coeffs[j + 128], z1) for j in range(128)]
    want = [((coeffs[j] + z1 * coeffs[j + 128]) % Q, (coeffs[j] - z1 * coeffs[j + 128]) % Q) for j in range(128)]
    check("first-stage (128-butterfly) outputs match the reference", BF.outputs(bfs) == want)
    ok, why = BF.verify(BF.prove(bfs, num_queries=NQ), bfs, num_queries=NQ)
    check(f"first-stage 128-butterfly batch proves + verifies ({why})", ok)


if __name__ == "__main__":
    t_matches_dilithium_butterfly()
    t_prove_verify()
    t_tampered_input_rejected()
    t_first_stage_over_a_real_poly()
    print("\nALL PASS — the NTT butterfly gadget matches Dilithium" if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
