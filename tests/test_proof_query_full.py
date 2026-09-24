"""PROOF_QUERY_FULL_HEIGHT: queries check the whole domain, and the trace batch bounds every column to degree < T.

Review 2026-09-24 (doc/security-review-2026-09-24-zk.md), two forgeries, both REPRODUCED here under the rules that
were live, and both refused from the gate:

  1. HALF-DOMAIN. A query opened the trace at idx mod N/2 and compared the recomputed composition with FRI layer 0
     only there. FRI tests degree < N/2, and N/2 points always interpolate a polynomial of that degree, so a prover
     who ran an honest FRI over the interpolant of the TRUE composition's lower half passed every spot-check: any
     statement verified. Built below on a counter AIR claiming its last row is 999.
  2. DEGREE SLACK. The P1 batch bounded each column only by deg_bound = next_pow2(md)*T. With md = 4 the column
     f(x) = lam * x^(N/4) satisfies w^4 = 1 on the whole coset while its trace is the constant lam, lam^4 != 1:
     an unsatisfiable AIR verified.

Also: honest proofs verify on both sides (the format flips with the gate) across blake2b, alghash2, the recursion
backend in row mode and zero-knowledge mode; the native prover agrees with Python bit for bit under the new rule;
and the rule is a pure function of height.

Run: python3 tests/test_proof_query_full.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-query-full-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from execnode.stark import stark, fri, field as F, extf as E, backend as B

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

GATE = int(P.PROOF_QUERY_FULL_HEIGHT)
PRE, NEW = stark.rules_for_height(GATE - 1), stark.rules_for_height(GATE)


def _interp_eval(xs, ys, X):
    n = len(xs); w = []
    for i in range(n):
        d = 1
        for j in range(n):
            if j != i: d = F.mul(d, F.sub(xs[i], xs[j]))
        w.append(F.inv(d))
    out = []
    for x in X:
        if x in xs:
            out.append(ys[xs.index(x)]); continue
        l = 1
        for j in range(n): l = F.mul(l, F.sub(x, xs[j]))
        out.append(F.add(0, sum(F.mul(F.mul(l, F.mul(w[i], F.inv(F.sub(x, xs[i])))), ys[i]) for i in range(n)) % F.P))
    return out


def _half_domain_forgery(rules):
    """A counter trace (x_{i+1} = x_i + 1, x_0 = 0) and the FALSE boundary x_{T-1} = 999; FRI is run honestly on the
    interpolant of the true FRI input's LOWER HALF."""
    T = 8
    trans = [lambda c, n, p: F.sub(n[0], F.add(c[0], 1))]
    bnds = [(0, 0, 0), (T - 1, 0, 999)]
    trace = [[i] for i in range(T)]
    orig = fri.prove
    def forged(evals, offset, blowup=4, *a, **k):
        N = len(evals); dom = F.domain(N, offset); h = N // 2
        if not isinstance(evals[0], int):
            lim = [E.lift(v) for v in evals]
            per = [_interp_eval(dom[:h], [l[d] for l in lim[:h]], dom) for d in range(E.DEGREE)]
            new = [tuple(per[d][i] for d in range(E.DEGREE)) for i in range(N)]
        else:
            new = _interp_eval(dom[:h], evals[:h], dom)
        return orig(new, offset, blowup, *a, **k)
    with stark.with_rules(rules):
        fri.prove = forged
        try:
            pf = stark.prove(trace, trans, bnds, max_degree=2)
        finally:
            fri.prove = orig
        return stark.verify(pf, trans, bnds, max_degree=2)


def _degree_slack_forgery(rules):
    """w^4 = 1 on every row with w(0) = lam, lam^4 != 1: unsatisfiable. The column is lam * x^(N/4) on the coset,
    which the unshifted batch admits (degree N/4 = 2T < deg_bound = 4T)."""
    T, MD = 8, 4
    N = stark._blowup(MD) * T
    lam = F.inv(F.pw(stark.OFF, N // 4))
    assert F.pw(lam, 4) != 1
    trans = [lambda c, n, p: F.sub(F.pw(c[0], 4), 1)]
    bnds = [(0, 0, lam)]
    orig = stark._coset_evaluate
    def forged_lde(poly, n, off):
        if n == N and len(poly) <= T and poly and poly[0] == lam and all(v == 0 for v in poly[1:]):
            return [F.mul(lam, F.pw(x, N // 4)) for x in F.domain(N, off)]
        return orig(poly, n, off)
    with stark.with_rules(rules):
        stark._coset_evaluate = forged_lde
        try:
            pf = stark.prove([[lam] for _ in range(T)], trans, bnds, max_degree=MD)
        finally:
            stark._coset_evaluate = orig
        return stark.verify(pf, trans, bnds, max_degree=MD)


def t_rules_are_pure_in_height():
    assert not PRE.full_query and NEW.full_query
    assert stark.rules_for_height(None).full_query and stark.current_rules().full_query, "unset = strict"
    assert stark.Rules(True, True, True, True, True).full_query is False, "a five-field Rules is the pre-gate format"
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read()
    assert "PROOF_QUERY_FULL_HEIGHT = 228500 if CHAIN_GENERATION == 25 else 1" in src


def t_half_domain_forgery_verifies_below_the_gate_and_is_refused_at_it():
    ok, why = _half_domain_forgery(PRE)
    assert ok, f"THE FINDING: below the gate the forgery must still verify (replay), got {why}"
    ok, why = _half_domain_forgery(NEW)
    assert not ok, "at the gate a half-domain forgery must be refused"


def t_degree_slack_forgery_verifies_below_the_gate_and_is_refused_at_it():
    ok, why = _degree_slack_forgery(PRE)
    assert ok, f"THE FINDING: below the gate the unsatisfiable AIR verified, got {why}"
    ok, why = _degree_slack_forgery(NEW)
    assert not ok, "at the gate the shifted batch must refuse a column of degree >= T"


def _counter(T=16):
    trans = [lambda c, n, p: F.sub(n[0], F.add(c[0], 1))]
    return [[i, i * i % F.P] for i in range(T)], trans, [(0, 0, 0)]


def t_honest_proofs_verify_under_their_own_rules_and_the_format_flips():
    tr, trans, bnds = _counter()
    for name, back in (("blake2b", B.BLAKE2B), ("alghash2", B.ALGHASH2)):
        made = {}
        for label, rules in (("pre", PRE), ("new", NEW)):
            with stark.with_rules(rules):
                pf = stark.prove(tr, trans, bnds, max_degree=2, backend=back)
                ok, why = stark.verify(pf, trans, bnds, max_degree=2, backend=back)
                assert ok, f"{name} honest proof under {label}: {why}"
                made[label] = pf
        with stark.with_rules(NEW):
            assert not stark.verify(made["pre"], trans, bnds, max_degree=2, backend=back)[0], f"{name}: old format refused at the gate"
        with stark.with_rules(PRE):
            assert not stark.verify(made["new"], trans, bnds, max_degree=2, backend=back)[0], f"{name}: new format refused below it"


def t_upper_half_queries_really_happen():
    """The fix only means something if queries land in the upper half and are checked there."""
    tr, trans, bnds = _counter()
    with stark.with_rules(NEW):
        pf = stark.prove(tr, trans, bnds, max_degree=2)
    N = pf["N"]
    assert any(op["lo"] >= N // 2 for op in pf["openings"]), "no query opened the upper half"


def t_row_commit_and_zero_knowledge_modes_verify_under_the_new_rule():
    tr, trans, bnds = _counter()
    with stark.with_rules(NEW):
        pf = stark.prove(tr, trans, bnds, max_degree=2, backend=B.RECURSION, row_commit=True)
        ok, why = stark.verify(pf, trans, bnds, max_degree=2, backend=B.RECURSION, row_commit=True)
        assert ok, f"row mode: {why}"
        import random
        zk = stark._next_pow2(2)
        trz = [row + [random.randrange(F.P) for _ in range(zk)] for row in tr]
        pf = stark.prove(trz, trans, bnds, max_degree=2, zk=zk)
        ok, why = stark.verify(pf, trans, bnds, max_degree=2, zk=zk)
        assert ok, f"zk mode: {why}"


def t_native_prover_agrees_with_python_under_the_new_rule():
    from execnode.stark import stark_native as SN
    if not SN.available():
        print("      (native prover unavailable here: skipped)"); return
    T = 16
    tr = [[1, 1] for _ in range(T)]
    per0 = [i % 4 for i in range(T)]
    trans = [lambda cur, nxt, per: F.sub(F.mul(cur[0], cur[1]), 1),
             lambda cur, nxt, per: F.mul(per[0], F.sub(cur[0], cur[1]))]
    bnds = [(0, 0, 1)]
    with stark.with_rules(NEW):
        want = stark.prove(tr, trans, bnds, periodic=[per0], max_degree=2, num_queries=8, backend=B.ALGHASH2)
        got = SN.prove(tr, trans, bnds, periodic=[per0], max_degree=2, num_queries=8, backend=B.ALGHASH2)
        assert got["fri"]["roots"] == want["fri"]["roots"] and got["fri"]["final"] == want["fri"]["final"], \
            "the arena's shifted batch differs from Python's"
        assert [op["lo"] for op in got["openings"]] == [op["lo"] for op in want["openings"]], "opening positions differ"
        ok, why = stark.verify(got, trans, bnds, periodic=[per0], max_degree=2, num_queries=8, backend=B.ALGHASH2)
        assert ok, why


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
