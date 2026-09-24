"""The K->1 fold cannot be steered by the prover (review 2026-09-24, both forgeries reproduced before the fix).

SETTLE_PROOF_RECURSIVE is TRUE, and L1 honours a `recursive` bundle in a settle proof. Today only the refusal under the
trace low-degree rule keeps folds out of consensus (SCHEDULED_CLEANUPS.md), so these are judged under the rules of the
window where the fold still ran (round 2 on, trace_ldt off): whatever lifts the refusal later must not reopen them.

  1. PROVER-SUPPLIED BOUNDARIES. state_transition's bundle path passed tr["bnds"] to the fold, so the roots chain
     compared with the public post_root had no tie to what the folded proofs proved: an honest bundle with roots[-1]
     swapped verified. The boundaries are now rebuilt from the public updates and roots.
  2. UNPINNED INNER GEOMETRY. recursive_verify.verify never checked N == blowup*T: declaring T=8, blowup=4, N=64 made
     "the next row" g16, transitions linked only row pairs, and an x^2 chain "ended" at any value.

Also: the refusal covers the full-query rule; the heterogeneous verifier (no production caller) refuses under every
live rule; and the DEEP evaluation verifier refuses a coset offset that is not the protocol's.

Run: python3 tests/test_fold_hardening.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-fold-hardening-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import sys, copy, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from execnode.stark import (stark, field as F, backend as B, recursive_verify as RV, fri, merkle,
                            state_transition as SX, storage_tree as ST)
from execnode.stark.transcript import Transcript, DOMAIN_STARK

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

FOLD_ERA = stark.Rules(True, True, True, True, False)     # round 2 on, trace_ldt off: the fold still ran


def t_the_flag_is_on_and_the_refusal_covers_every_later_rule():
    assert P.SETTLE_PROOF_RECURSIVE is True, "the docs said off; if this changes, update SCHEDULED_CLEANUPS.md"
    with stark.with_rules(stark.RULES_STRICT._replace(trace_ldt=False)):      # full_query alone must refuse too
        ok, why = RV.verify([], [], [], {})
        assert not ok and "refused" in why, why


def t_transition_bundle_boundaries_come_from_public_data():
    D = 8
    random.seed(3)
    vals = {}
    while len(vals) < 20:
        vals[random.randrange(1 << D)] = random.randrange(1, F.P)
    store = ST.SparseStore(D, dict(vals))
    keys = list(vals)[:1] + [next(k for k in range(1 << D) if k not in vals)]
    updates = [(k, random.randrange(1, F.P)) for k in keys]
    pre_root = store.root()
    with stark.with_rules(FOLD_ERA):
        tr = SX.prove_transition(store, updates, num_queries=2, outer_queries=2, fold=True)
        assert "bundle" in tr
        post_root = store.root()
        ok, why = SX.verify_transition(tr, pre_root, post_root, num_queries=2, outer_queries=2)
        assert ok, f"the honest folded transition must still verify: {why}"
        fake = tuple((int(x) + 12345) % F.P for x in post_root)
        tr2 = copy.deepcopy(tr); tr2["roots"][-1] = fake
        ok, why = SX.verify_transition(tr2, pre_root, fake, num_queries=2, outer_queries=2)
        assert not ok, "THE FINDING: a swapped post root verified through the bundle"


def _geometry_forgery(N):
    TR = [lambda c, n, p: F.sub(n[0], F.mul(c[0], c[0]))]
    SEED, FAKE, T, BLOW, NQ = 123456789 % F.P, 424242, 8, 4, 2
    BND = [(0, 0, SEED), (T - 1, 0, FAKE)]
    b = B.RECURSION
    random.seed(1)
    s = [0] * 16
    for i in range(8):
        s[2 * i] = SEED if i == 0 else (FAKE if i == 7 else random.randrange(F.P))
        s[2 * i + 1] = F.mul(s[2 * i], s[2 * i])
    col_lde = [stark._coset_evaluate(F.interpolate(s), N, stark.OFF)]
    x_lde = F.domain(N, stark.OFF)
    t = Transcript(DOMAIN_STARK, backend=b)
    rules = stark.current_rules()
    stark.absorb_aux(t, None, rules); stark.absorb_statement(t, None)
    if rules.round2:
        stark.absorb_air(t, stark.air_digest(T, 1, BLOW, len(TR), BND, []))
    root, ml = merkle.commit(col_lde[0], b); t.absorb(root)
    ext = stark.ext_challenges_active(b)
    alphas = [(t.challenge_ext() if ext else t.challenge()) for _ in range(len(TR) + len(BND))]
    cp = stark._composition(T, 1, N, BLOW, F.primitive_root_of_unity(T), col_lde, [], x_lde, TR, BND, alphas, None,
                            ext_alphas=ext)
    fp = fri.prove(cp, stark.OFF, 2, NQ, transcript=t, backend=b, ext=ext)
    ops = []
    for q in fp["queries"]:
        lo = q["idx"] % (N // 2); nx = (lo + BLOW) % N
        ops.append({"lo": lo, "cols": [{"cur": col_lde[0][lo], "cur_path": merkle.open_at(ml, lo),
                                        "nxt": col_lde[0][nx], "nxt_path": merkle.open_at(ml, nx)}]})
    pf = {"T": T, "W": 1, "N": N, "blowup": BLOW, "deg_bound": N // 2, "boundaries": BND,
          "fri": fp, "openings": ops, "col_roots": [root]}
    return pf, TR, BND, NQ


def t_inner_geometry_is_pinned():
    with stark.with_rules(FOLD_ERA):
        pf, TR, BND, NQ = _geometry_forgery(64)
        assert not stark.verify(pf, TR, BND, max_degree=2, num_queries=NQ, backend=B.RECURSION)[0], "stark.verify pins it"
        bundle = RV.prove([pf], TR, [BND], num_queries_outer=4)
        for md in (None, 2):
            ok, why = RV.verify([RV.public_part(pf)], TR, [BND], bundle, num_queries_outer=4, num_queries_inner=NQ,
                                max_degree=md)
            assert not ok and "geometry" in why, f"THE FINDING: a N != blowup*T fold verified (max_degree={md}): {why}"


def t_the_heterogeneous_verifier_refuses_under_every_live_rule():
    from execnode.stark import recursive_verify_hetero as RH
    with stark.with_rules(stark.rules_for_height(P.PROOF_BIND_HEIGHT)):
        ok, why = RH.verify_hetero([], [], {})
        assert not ok and "refused" in why, why


def t_deep_eval_refuses_a_foreign_offset():
    from execnode.stark import deep_eval as DE
    proof = {"v": 0, "P_root": b"", "T": 8, "N": 32, "offset": (stark.OFF + 1) % F.P, "fri": {}, "P_open": []}
    ok, why = DE.verify_eval(proof, 5)
    assert not ok and "offset" in why, why


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
