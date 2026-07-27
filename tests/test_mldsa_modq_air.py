"""
ML-DSA-44 verify AIR — sub-circuit 2: the mod-Q multiply-reduce gadget c = a*b mod Q
(execnode/stark/mldsa_modq_air.py). The arithmetic atom for the NTT + A·z - c·t1. See
doc/zk-signature-aggregation.md.

Validates: the proven products equal direct a*b mod Q (incl. edge cases at 0 / 1 / Q-1, where a*b approaches
Q^2 < 2^46 and must not wrap Goldilocks); a batch proves+verifies; a tampered public factor is rejected; a
claimed product that isn't a*b mod Q is unprovable by an honest prover.

Run: python3 tests/test_mldsa_modq_air.py
"""
import os, sys, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_modq_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_params as P, mldsa_modq_air as MQ

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

NQ = 4
Q = P.Q

# a deterministic spread of factor pairs incl. the worst case (Q-1)*(Q-1) ~ 2^46 and the identities
PAIRS = [(0, 12345), (1, Q - 1), (Q - 1, Q - 1), (2, 4190209), (7777, 8888),
         (4190208, 4190208), (Q - 1, 1), (123456, 654321)]
_PROOF = MQ.prove(PAIRS, num_queries=NQ)


def t_products_match_direct():
    got = MQ.products(PAIRS)
    want = [(a % Q) * (b % Q) % Q for a, b in PAIRS]
    check("proven products equal direct a*b mod Q", got == want)
    # the worst-case product really is near Q^2 and below the Goldilocks prime (no wrap)
    check("(Q-1)^2 < Goldilocks P (no wraparound)", (Q - 1) * (Q - 1) < ((1 << 64) - (1 << 32) + 1))


def t_prove_verify():
    ok, why = MQ.verify(_PROOF, PAIRS, num_queries=NQ)
    check(f"batch of mod-Q products proves + verifies ({why})", ok)


def t_tampered_factor_rejected():
    bad = list(PAIRS)
    bad[3] = (bad[3][0] + 1, bad[3][1])       # change one public factor -> boundary no longer matches the trace
    ok, _ = MQ.verify(_PROOF, bad, num_queries=NQ)
    check("a tampered public factor is rejected", not ok)


def t_wrong_product_unprovable():
    """The gadget computes the canonical c internally; a proof is bound to the exact (a,b). Verifying the proof
    against a pair whose product differs from what was proven must fail (there is no valid trace for it)."""
    # take the proof of PAIRS and try to pass it off for a different pair set (same length)
    other = [(p[0], (p[1] + 1) % Q) for p in PAIRS]
    ok, _ = MQ.verify(_PROOF, other, num_queries=NQ)
    check("a proof cannot be reused for different factors", not ok)


def t_single_and_identity():
    for pr in ([(6, 7)], [(1, Q - 1)], [(0, 0)]):
        ok, why = MQ.verify(MQ.prove(pr, num_queries=NQ), pr, num_queries=NQ)
        check(f"pair {pr} proves+verifies ({why})", ok)


if __name__ == "__main__":
    check("params: Q is 23-bit", (Q - 1).bit_length() == 23 and Q == 8380417)
    t_products_match_direct()
    t_prove_verify()
    t_tampered_factor_rejected()
    t_wrong_product_unprovable()
    t_single_and_identity()
    print("\nALL PASS — mod-Q multiply-reduce is sound over Goldilocks" if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
