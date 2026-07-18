"""
SOUNDNESS of the verifier-authoritative in-circuit COMPOSITION spot-check (execnode/stark/comp_verify.py). It
proves, inside one recursion STARK, that trace-column openings are Merkle-authenticated under committed column
roots AND recompute the AIR composition (via the constraint-IR) to a PUBLIC layer-0 target. Guards that: an
honest point verifies; a verifier handed a FALSE layer-0 target rejects it (composition-binding is authoritative);
and a lying opening (a value not in the committed tree) is rejected by the in-circuit membership. The AIR here is
the 1-column x^2 demo, but the code path (air_ir program evaluated in-circuit) is identical for the W=106
execution AIR — only W and the program differ.
(Run: python3 tests/test_comp_verify.py — a few slow alghash2 proofs.)
"""
import os, sys, random, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, air_ir, comp_verify as CV
from execnode.stark.recursion import rmerkle_commit, rmerkle_path

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

P = F.P
SEED = 123456789 % P
# x^2 AIR: transition x_nxt - x_cur^2 (must use F.* so air_ir traces it); one boundary col0@row0 == SEED
TRANS = [lambda c, n, p: F.sub(n[0], F.mul(c[0], c[0]))]
BND = [(0, 0, SEED)]
W = 1
PROG = air_ir.build_program(TRANS, W, 0, 0)


def _commit_column(n=8, seed=1):
    random.seed(seed)
    vals = [random.randrange(P) for _ in range(n)]
    root, layers = rmerkle_commit(vals)
    return vals, root, layers


def _reference_cp(val_cur, val_nxt, alphas, invZ, bnd):
    """Mirror comp_verify.check_c / air_ir.compose_python for the x^2 AIR at one point."""
    outs = air_ir.eval_program_point(PROG, [val_cur], [val_nxt], [], [])
    acc = alphas[0] * outs[0] % P
    cp = acc * invZ % P
    (bval, invd) = bnd[0]
    cp = (cp + alphas[1] * ((val_cur - bval) % P) * invd) % P
    return cp


def _make_point(vals, layers, root, q_cur, q_nxt, val_cur=None, val_nxt=None):
    vc = vals[q_cur] if val_cur is None else val_cur
    vn = vals[q_nxt] if val_nxt is None else val_nxt
    alphas = [11111 % P, 22222 % P]                 # At, Ab
    invZ = 33333 % P
    bnd = [(SEED, 44444 % P)]                        # (boundary target, 1/(x-pt))
    cp = _reference_cp(vc, vn, alphas, invZ, bnd)
    point = {"cur": [(vc, q_cur, rmerkle_path(layers, q_cur))],
             "nxt": [(vn, q_nxt, rmerkle_path(layers, q_nxt))],
             "per": [], "chal": [], "alphas": alphas, "invZ": invZ, "bnd": bnd, "layer0": cp}
    return point, root


def t_honest():
    vals, root, layers = _commit_column()
    point, root = _make_point(vals, layers, root, 1, 3)
    proof, public = CV.prove_comp(PROG, W, BND, [point], [root], num_queries=4)
    ok, why = CV.verify_comp(proof, PROG, W, BND, public)
    assert ok, f"honest composition spot-check must verify: {why}"


def t_false_layer0_rejected():
    vals, root, layers = _commit_column()
    point, root = _make_point(vals, layers, root, 1, 3)
    proof, public = CV.prove_comp(PROG, W, BND, [point], [root], num_queries=4)
    assert CV.verify_comp(proof, PROG, W, BND, public)[0]
    bad = copy.deepcopy(public)
    bad["points_public"][0]["layer0"] = (bad["points_public"][0]["layer0"] + 1) % P
    ok, _ = CV.verify_comp(proof, PROG, W, BND, bad)
    assert not ok, "a verifier handed a false layer-0 target must reject (composition binding is authoritative)"


def t_lying_opening_rejected():
    """Prover claims an opened value NOT in the committed tree (with the real path). The in-circuit membership
    forces the leaf to hash to the committed root, so the recursion proof cannot satisfy its boundaries."""
    vals, root, layers = _commit_column()
    fake = (vals[1] + 7) % P
    point, root = _make_point(vals, layers, root, 1, 3, val_cur=fake)   # layer0 recomputed for the lie
    proof, public = CV.prove_comp(PROG, W, BND, [point], [root], num_queries=4)
    ok, _ = CV.verify_comp(proof, PROG, W, BND, public)
    assert not ok, "a value not in the committed column tree must be rejected by membership"


def t_binds_real_stark_proof():
    """comp_verify binds a GENUINE stark.prove(x^2, backend=RECURSION) proof: every FRI query's Merkle-opened
    trace columns recompute (in-circuit, via air_ir) to that query's REAL FRI layer-0 value — exactly the
    stark.verify composition spot-check, done inside a recursion proof. The trace<->constraints half of an
    in-circuit STARK verifier, run against a real proof rather than hand-built values."""
    from execnode.stark import stark, backend as B
    from execnode.stark.transcript import Transcript, DOMAIN_STARK
    b = B.RECURSION
    Tn, NQ_IN = 8, 2
    colv = [SEED]
    for _ in range(Tn - 1):
        colv.append(F.mul(colv[-1], colv[-1]))          # v_{i+1} = v_i^2
    trace = [[colv[i]] for i in range(Tn)]
    proof = stark.prove(trace, TRANS, BND, max_degree=8, num_queries=NQ_IN, backend=b)
    assert stark.verify(proof, TRANS, BND, max_degree=8, num_queries=NQ_IN, backend=b)[0], "inner proof must verify"
    N, blowup, col_roots = proof["N"], proof["blowup"], proof["col_roots"]
    nt, nb = len(TRANS), len(BND)
    t = Transcript(DOMAIN_STARK, backend=b)             # one-phase AIR: absorb col roots, draw nt+nb alphas
    for r in col_roots:
        t.absorb(r)
    alphas = [t.challenge() for _ in range(nt + nb)]
    x_dom = F.domain(N, stark.OFF)
    gT = F.primitive_root_of_unity(Tn)
    last = F.pw(gT, Tn - 1)
    points = []
    for q, op in zip(proof["fri"]["queries"], proof["openings"]):
        lo = q["idx"] % (N // 2)
        nxt = (lo + blowup) % N
        cols = op["cols"]
        x = x_dom[lo]
        z = F.mul(F.sub(F.pw(x, Tn), 1), F.inv(F.sub(x, last)))
        bnd = [(val, F.inv(F.sub(x, F.pw(gT, row)))) for (row, _c, val) in BND]
        points.append({"cur": [(cols[c]["cur"], lo, cols[c]["cur_path"]) for c in range(W)],
                       "nxt": [(cols[c]["nxt"], nxt, cols[c]["nxt_path"]) for c in range(W)],
                       "per": [], "chal": [], "alphas": alphas, "invZ": F.inv(z), "bnd": bnd,
                       "layer0": q["steps"][0]["lo"]})
    rproof, public = CV.prove_comp(PROG, W, BND, points, col_roots, num_queries=4)
    ok, why = CV.verify_comp(rproof, PROG, W, BND, public)
    assert ok, f"composition binding of a real STARK proof must verify: {why}"


if __name__ == "__main__":
    check("honest composition spot-check verifies", t_honest)
    check("false layer-0 target rejected (authoritative binding)", t_false_layer0_rejected)
    check("lying opening rejected by in-circuit membership", t_lying_opening_rejected)
    check("binds a REAL stark.prove(x^2) proof's trace to its FRI layer-0 values", t_binds_real_stark_proof)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
