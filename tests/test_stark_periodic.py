"""
STRUCTURED periodic columns (execnode/stark/stark.py — _per_expand/_per_evaluator): the succinct-verifier core.
A periodic column given as {"period": p, "base": [p values], "sparse": [(row, val)]} must (1) produce a proof
BYTE-IDENTICAL to passing the expanded dense column — the structured form is representation, not protocol —
and (2) verify interchangeably with the dense form, while the verifier evaluates it in O(period + #sparse) per
query instead of an O(T) interpolation. Tampering the base pattern or a sparse value must be rejected: the
periodic is part of the AIR the VERIFIER asserts.
(Run: python3 tests/test_stark_periodic.py)
"""
import os, sys, json, time, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, stark, backend as B

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

T = 16
PAT = [3, 1, 4, 1]
DENSE = [PAT[i % 4] for i in range(T)]; DENSE[5] = 999
STRUCT = {"period": 4, "base": PAT, "sparse": [(5, 999)]}
TRANS = [lambda c, n, p: F.sub(n[0], F.add(F.mul(c[0], c[0]), p[0]))]   # x' = x^2 + per0
SEED = 7
BND = [(0, 0, SEED)]


def _trace():
    col = [SEED]
    for i in range(T - 1):
        col.append(F.add(F.mul(col[-1], col[-1]), DENSE[i]))
    return [[v] for v in col]


def t_byte_identical():
    pd = stark.prove(_trace(), TRANS, BND, periodic=[DENSE], max_degree=4, num_queries=4, backend=B.RECURSION)
    ps = stark.prove(_trace(), TRANS, BND, periodic=[STRUCT], max_degree=4, num_queries=4, backend=B.RECURSION)
    assert json.dumps(pd, sort_keys=True, default=str) == json.dumps(ps, sort_keys=True, default=str), \
        "structured and dense periodic must prove byte-identically"
    for form in (DENSE, STRUCT):
        ok, why = stark.verify(pd, TRANS, BND, periodic=[form], max_degree=4, num_queries=4, backend=B.RECURSION)
        assert ok, why


def t_tampered_rejected():
    p = stark.prove(_trace(), TRANS, BND, periodic=[DENSE], max_degree=4, num_queries=4, backend=B.RECURSION)
    bad_base = {"period": 4, "base": [3, 1, 4, 2], "sparse": [(5, 999)]}
    bad_sparse = {"period": 4, "base": PAT, "sparse": [(5, 998)]}
    for bad in (bad_base, bad_sparse):
        ok, _ = stark.verify(p, TRANS, BND, periodic=[bad], max_degree=4, num_queries=4, backend=B.RECURSION)
        assert not ok, "a tampered structured periodic must reject"


def t_verify_cost_t_independent():
    """The whole point: verifier periodic work must not grow with T. Prove at two trace sizes 16× apart with a
    pure 16-periodic column and compare verify times — the structured form must not scale anywhere near the
    trace-length ratio (the dense form's interpolation does)."""
    base16 = list(range(1, 17))
    times = {}
    for Tn in (64, 1024):
        col = [SEED]
        for i in range(Tn - 1):
            col.append(F.add(F.mul(col[-1], col[-1]), base16[i % 16]))
        trace = [[v] for v in col]
        per = {"period": 16, "base": base16, "sparse": []}
        pr = stark.prove(trace, TRANS, BND, periodic=[per], max_degree=4, num_queries=8, backend=B.RECURSION)
        t0 = time.perf_counter()
        ok, why = stark.verify(pr, TRANS, BND, periodic=[per], max_degree=4, num_queries=8, backend=B.RECURSION)
        times[Tn] = time.perf_counter() - t0
        assert ok, why
    ratio = times[1024] / times[64]
    assert ratio < 8, f"verify time grew {ratio:.1f}x over a 16x trace growth — periodic path is not succinct"


if __name__ == "__main__":
    check("dense vs structured: byte-identical proofs, interchangeable verify", t_byte_identical)
    check("tampered structured periodic rejected", t_tampered_rejected)
    check("verify cost independent of trace length (16x growth)", t_verify_cost_t_independent)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
