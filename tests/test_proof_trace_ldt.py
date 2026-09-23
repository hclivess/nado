"""PROOF_TRACE_LDT_HEIGHT: the trace columns are low-degree tested with the composition.

Security review 2026-09-23, finding P1 (doc/security-review-2026-09-23.md §5). Only the composition polynomial
entered FRI, so a witness column with no boundary constraint was an ARBITRARY function on the coset and any gadget
of the form A(x)·w(x) = B(x) was satisfiable pointwise by w := B/A. This file BUILDS that forgery on a toy AIR —
a column `v` with v(0) = 0 pinned, an "inverse witness" column `w`, and the constraint v·w − 1 = 0, which no honest
trace satisfies (0 has no inverse) — by writing w's LDE as the pointwise inverse of v's LDE instead of interpolating
a trace, and shows it VERIFYING under the pre-gate rules and refused at the gate. Also: honest proofs verify on
both sides of the gate (the format flips with it), the native prover agrees with the Python one bit for bit under
the new rule, the fold refuses under it, and the rule is a pure function of the block height.

Run: python3 tests/test_proof_trace_ldt.py
"""
import os
import sys
import tempfile
import traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-traceldt-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from execnode.stark import stark, fri, field as F, merkle, backend as _backend, extf as ext2
from execnode.stark.transcript import Transcript, DOMAIN_STARK

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


GATE = int(P.PROOF_TRACE_LDT_HEIGHT)
LEGACY, STRICT = stark.RULES_LEGACY, stark.RULES_STRICT
PRE = STRICT._replace(trace_ldt=False)          # every earlier pin on, only this gate off
T_TOY, NQ = 16, 8

# the inverse-witness gadget: v * w == 1 on every row; v is pinned to 0 at row 0, so no honest w exists
TRANS = [lambda cur, nxt, per: F.sub(F.mul(cur[0], cur[1]), 1)]
BND = [(0, 0, 0)]


def _honest_ok_trace():
    """A trace that DOES satisfy the gadget (v = 1, w = 1 everywhere) with its own boundary, for the honest cases."""
    return [[1, 1] for _ in range(T_TOY)], [(0, 0, 1)]


def _forge(rules):
    """stark.prove, step by step, with column 1's LDE replaced by the POINTWISE inverse of column 0's LDE — a
    function on the coset that is no polynomial of degree < T. Every other step is honest: real commitments,
    real transcript, real composition (which is identically zero, since v·w − 1 = 0 at every coset point), real
    FRI. Mirrors stark.prove's Python body under `rules`."""
    T, W = T_TOY, 2
    max_degree = 2
    blowup = stark._blowup(max_degree); N = blowup * T
    gT = F.primitive_root_of_unity(T)
    v_col = [3 + i for i in range(T)]; v_col[0] = 0            # v(0) = 0: the boundary the honest prover cannot dodge
    v_poly = F.interpolate(v_col)
    v_lde = stark._coset_evaluate(v_poly, N, stark.OFF)
    w_lde = [F.inv(x) for x in v_lde]                           # the forgery: w := 1/v pointwise
    col_lde = [v_lde, w_lde]
    x_lde = F.domain(N, stark.OFF)
    deg_bound = stark._next_pow2(max_degree) * T
    b = _backend.DEFAULT
    t = Transcript(DOMAIN_STARK, backend=b)
    stark.absorb_aux(t, None, rules)
    stark.absorb_statement(t, None)
    if rules.round2:
        stark.absorb_air(t, stark.air_digest(T, W, blowup, len(TRANS), BND, []))
    col_roots, col_mlayers = [], []
    for c in range(W):
        root, ml = merkle.commit(col_lde[c], b)
        col_roots.append(root); col_mlayers.append(ml); t.absorb(root)
    ext = stark.ext_challenges_active(b)
    alphas = [(t.challenge_ext() if ext else t.challenge()) for _ in range(len(TRANS) + len(BND))]
    cp = stark._composition(T, W, N, blowup, gT, col_lde, [], x_lde, TRANS, BND, alphas, None, ext_alphas=ext)
    beta = stark.trace_batch_beta(t, rules, ext)
    if beta is not None:
        stark.trace_batch_add(cp, col_lde, W, N, beta, ext)
    fri_proof = fri.prove(cp, stark.OFF, N // deg_bound, NQ, transcript=t, backend=b, ext=ext)
    openings = []
    for q in fri_proof["queries"]:
        lo = q["idx"] % (N // 2); nxt = (lo + blowup) % N
        openings.append({"lo": lo, "cols": [{"cur": col_lde[c][lo], "cur_path": merkle.open_at(col_mlayers[c], lo),
                                             "nxt": col_lde[c][nxt], "nxt_path": merkle.open_at(col_mlayers[c], nxt)}
                                            for c in range(W)]})
    return {"T": T, "W": W, "N": N, "blowup": blowup, "deg_bound": deg_bound, "boundaries": BND,
            "fri": fri_proof, "openings": openings, "col_roots": col_roots}


def t_rules_pure_in_height():
    assert not stark.rules_for_height(GATE - 1).trace_ldt and stark.rules_for_height(GATE).trace_ldt
    assert stark.rules_for_height(None).trace_ldt and stark.current_rules().trace_ldt, "unset = strict"
    assert stark.Rules(True, True, True, True).trace_ldt is False, "a four-field Rules names the pre-gate format"
    assert stark.RULES_STRICT.trace_ldt and not stark.RULES_LEGACY.trace_ldt
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read()
    assert "PROOF_TRACE_LDT_HEIGHT = 216000 if CHAIN_GENERATION == 25 else 1" in src


def t_honest_proofs_verify_under_their_own_rules_and_the_format_flips():
    tr, bnd = _honest_ok_trace()
    proofs = {}
    for name, rules in (("pre", PRE), ("ldt", STRICT)):
        with stark.with_rules(rules):
            pf = stark.prove(tr, TRANS, bnd, max_degree=2, num_queries=NQ)
            ok, why = stark.verify(pf, TRANS, bnd, max_degree=2, num_queries=NQ)
            assert ok, f"honest proof under {name}: {why}"
            proofs[name] = pf
    with stark.with_rules(STRICT):
        assert not stark.verify(proofs["pre"], TRANS, bnd, max_degree=2, num_queries=NQ)[0], "an old-format proof is refused at the gate"
    with stark.with_rules(PRE):
        assert not stark.verify(proofs["ldt"], TRANS, bnd, max_degree=2, num_queries=NQ)[0], "a new-format proof is refused below it"


def t_forgery_is_ACCEPTED_below_the_gate():
    """THE FINDING, REPRODUCED: v(0) = 0 is pinned, the gadget says v·w = 1 everywhere, and the proof verifies."""
    with stark.with_rules(PRE):
        forged = _forge(PRE)
        ok, why = stark.verify(forged, TRANS, BND, max_degree=2, num_queries=NQ)
        assert ok, f"under the pre-gate rules the pointwise-inverse forgery verified: {why}"


def t_forgery_is_refused_at_the_gate():
    with stark.with_rules(STRICT):
        forged = _forge(STRICT)                      # built with the batch term too: only the low-degree test refuses it
        ok, why = stark.verify(forged, TRANS, BND, max_degree=2, num_queries=NQ)
        assert not ok and "low-degree" in why, why
    ok, why = stark.verify(forged, TRANS, BND, max_degree=2, num_queries=NQ)      # the default context is strict
    assert not ok, why


def t_honest_trace_with_a_real_inverse_still_verifies():
    """The batch must not refuse an honest inverse witness: v nonzero on the trace, w its real inverse."""
    v = [3 + i for i in range(T_TOY)]
    tr = [[x, F.inv(x)] for x in v]
    with stark.with_rules(STRICT):
        pf = stark.prove(tr, TRANS, [(0, 0, 3)], max_degree=2, num_queries=NQ)
        ok, why = stark.verify(pf, TRANS, [(0, 0, 3)], max_degree=2, num_queries=NQ)
        assert ok, why


def t_native_prover_agrees_with_python_under_the_rule():
    from execnode.stark import stark_native as SN
    if not SN.available():
        print("      (native prover unavailable here: skipped)"); return
    from execnode.stark import backend as B
    tr, bnd = _honest_ok_trace()
    per0 = [i % 4 for i in range(T_TOY)]
    per_trans = [lambda cur, nxt, per: F.sub(F.mul(cur[0], cur[1]), 1),
                 lambda cur, nxt, per: F.mul(per[0], F.sub(cur[0], cur[1]))]
    with stark.with_rules(STRICT):
        want = stark.prove(tr, per_trans, bnd, periodic=[per0], max_degree=2, num_queries=NQ, backend=B.ALGHASH2)
        got = SN.prove(tr, per_trans, bnd, periodic=[per0], max_degree=2, num_queries=NQ, backend=B.ALGHASH2)
        assert got["fri"]["roots"] == want["fri"]["roots"] and got["fri"]["final"] == want["fri"]["final"], \
            "the arena's batch term differs from Python's"
        assert got["col_roots"] == want["col_roots"] and got["fri"]["pow"] == want["fri"]["pow"]
        ok, why = stark.verify(got, per_trans, bnd, periodic=[per0], max_degree=2, num_queries=NQ, backend=B.ALGHASH2)
        assert ok, why


def t_fold_refuses_under_the_rule():
    from execnode.stark import recursive_verify as RV
    with stark.with_rules(STRICT):
        ok, why = RV.verify([], TRANS, BND, {})
        assert not ok and "trace low-degree" in why, why
        try:
            RV.prove([], TRANS, BND)
            assert False, "prove must refuse"
        except NotImplementedError:
            pass


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
