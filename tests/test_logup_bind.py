"""
LogUp multiset-equality (execnode/stark/logup_bind.py) — the in-circuit binding primitive. Proves two lists of
3-tuples are the same multiset (order-independent), the mechanism that will bind the exec proof's storage writes
to the state-transition's updates in-circuit.

Checks: equal multisets (incl. reordered + repeats) verify; unequal multisets are rejected; a tampered tuple is
rejected; and it proves/verifies under the RECURSION backend (foldable).

Run: python3 tests/test_logup_bind.py
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import logup_bind as LB, field as F, backend as B

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 8


def _rand_tuples(n, seed):
    random.seed(seed)
    return [(random.randrange(F.P), random.randrange(F.P), random.randrange(F.P)) for _ in range(n)]


def t_equal_multiset_verifies():
    A = _rand_tuples(6, 1)
    B = list(reversed(A))                          # same multiset, different order
    proof = LB.prove_multiset_eq(A, B, num_queries=NQ)
    ok, why = LB.verify_multiset_eq(proof, expect_n=len(A), num_queries=NQ)
    assert ok, f"equal multisets must verify: {why}"


def t_repeats_ok():
    A = [(1, 2, 3), (1, 2, 3), (4, 5, 6)]
    B = [(4, 5, 6), (1, 2, 3), (1, 2, 3)]          # same multiset with a repeat
    proof = LB.prove_multiset_eq(A, B, num_queries=NQ)
    assert LB.verify_multiset_eq(proof, expect_n=3, num_queries=NQ)[0]


def t_unequal_rejected():
    A = _rand_tuples(5, 2)
    B = list(A); B[0] = (B[0][0] ^ 1, B[0][1], B[0][2])   # one tuple differs
    try:
        proof = LB.prove_multiset_eq(A, B, num_queries=NQ)
    except Exception:
        return                                     # prover may already fail to satisfy the boundary — acceptable
    ok, _ = LB.verify_multiset_eq(proof, expect_n=5, num_queries=NQ)
    assert not ok, "unequal multisets must be rejected"


def t_tampered_rejected():
    A = _rand_tuples(6, 3)
    B = list(A)
    proof = LB.prove_multiset_eq(A, B, num_queries=NQ)
    # tamper a committed opening -> composition spot-check fails
    q = proof["openings"][0]["cols"][LB.A0]
    q["cur"] = (int(q["cur"]) + 1) % F.P
    ok, _ = LB.verify_multiset_eq(proof, expect_n=6, num_queries=NQ)
    assert not ok, "a tampered committed cell must be rejected"


def t_recursion_backend():
    A = _rand_tuples(4, 4)
    B = list(A)
    proof = LB.prove_multiset_eq(A, B, num_queries=NQ, backend=B if False else None)  # default first
    assert LB.verify_multiset_eq(proof, expect_n=4, num_queries=NQ)[0]
    from execnode.stark import backend as BK
    proof2 = LB.prove_multiset_eq(A, B, num_queries=NQ, backend=BK.RECURSION)
    ok, why = LB.verify_multiset_eq(proof2, expect_n=4, num_queries=NQ, backend=BK.RECURSION)
    assert ok, f"RECURSION-committed multiset-eq must verify (foldable): {why}"


if __name__ == "__main__":
    check("equal multiset (reordered) verifies", t_equal_multiset_verifies)
    check("repeats handled", t_repeats_ok)
    check("unequal multisets rejected", t_unequal_rejected)
    check("tampered committed cell rejected", t_tampered_rejected)
    check("provable + verifiable under RECURSION backend (foldable)", t_recursion_backend)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
