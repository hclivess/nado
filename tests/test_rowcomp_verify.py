"""
Row-mode in-circuit composition spot-check (execnode/stark/rowcomp_verify.py) against REAL row-committed
proofs (stark.prove(..., row_commit=True)): the opened query ROWS are authenticated in-circuit under the row
tree via multi-chunk sponge absorption (hashn frame + LABS chunk absorbs) chained into the Merkle node path
(witness sibling + direction pinned by IACC), and the composition recomputed from the carried row equals the
FRI layer-0 target. W=1 (single chunk) and W=10 (multi-chunk) both bind; false layer-0, wrong row root, and a
wrong query index are rejected.
(Run: python3 tests/test_rowcomp_verify.py — a few slow alghash2 proofs.)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, stark, backend as B, rowcomp_verify as RC, air_ir
from execnode.stark.transcript import Transcript, DOMAIN_STARK

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

T, SEED = 8, 123
BND = [(0, 0, SEED)]


def _points(proof, transitions, boundaries):
    """Row-mode comp points from a row-committed single-phase STARK proof (what recursive_verify derives)."""
    W, N, blowup, Tn = proof["W"], proof["N"], proof["blowup"], proof["T"]
    gT = F.primitive_root_of_unity(Tn); wN = F.primitive_root_of_unity(N)
    last = F.pw(gT, Tn - 1)
    t = Transcript(DOMAIN_STARK, backend=B.RECURSION)
    for r in proof["row_roots"]:
        t.absorb(r)
    alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]
    pts = []
    for q, op in zip(proof["fri"]["queries"], proof["openings"]):
        lo = q["idx"] % (N // 2)
        x = F.mul(stark.OFF, F.pw(wN, lo))
        z = F.mul(F.sub(F.pw(x, Tn), 1), F.inv(F.sub(x, last)))
        bnd = [(int(val) % F.P, F.inv(F.sub(x, F.pw(gT, row)))) for (row, _c, val) in boundaries]
        pts.append({"cur": op["cur"], "nxt": op["nxt"], "cur_paths": op["cur_paths"],
                    "nxt_paths": op["nxt_paths"], "cur_index": lo, "nxt_index": (lo + blowup) % N,
                    "roots": proof["row_roots"], "path_lens": [N.bit_length() - 1],
                    "per": [], "chal": [], "alphas": alphas, "invZ": F.inv(z), "bnd": bnd,
                    "layer0": q["steps"][0]["lo"]})
    return pts


def _col():
    col = [SEED]
    for _ in range(T - 1):
        col.append(F.mul(col[-1], col[-1]))
    return col


TRANS1 = [lambda c, n, p: F.sub(n[0], F.mul(c[0], c[0]))]
W10 = 10
TRANS10 = [lambda c, n, p: F.sub(n[0], F.mul(c[0], c[0]))] + \
          [(lambda i: lambda c, n, p: F.sub(c[i], F.add(c[0], i)))(i) for i in range(1, W10)]

_P1 = stark.prove([[v] for v in _col()], TRANS1, BND, max_degree=2, num_queries=2,
                  backend=B.RECURSION, row_commit=True)
_PROG1 = air_ir.build_program(TRANS1, 1, 0, 0)
_CP1, _PUB1 = RC.prove_comp(_PROG1, 1, 0, BND, _points(_P1, TRANS1, BND), num_queries=4)

_P10 = stark.prove([[v] + [F.add(v, i) for i in range(1, W10)] for v in _col()], TRANS10, BND,
                   max_degree=2, num_queries=2, backend=B.RECURSION, row_commit=True)
_PROG10 = air_ir.build_program(TRANS10, W10, 0, 0)
_CP10, _PUB10 = RC.prove_comp(_PROG10, W10, 0, BND, _points(_P10, TRANS10, BND), num_queries=4)


def t_w1_binds():
    ok, why = RC.verify_comp(_CP1, _PROG1, 1, 0, BND, _PUB1)
    assert ok, why


def t_false_layer0_rejected():
    bad = copy.deepcopy(_PUB1)
    bad["points_public"][0]["layer0"] = (bad["points_public"][0]["layer0"] + 1) % F.P
    assert not RC.verify_comp(_CP1, _PROG1, 1, 0, BND, bad)[0]


def t_wrong_root_rejected():
    bad = copy.deepcopy(_PUB1)
    bad["points_public"][0]["roots"][0][0] = (bad["points_public"][0]["roots"][0][0] + 1) % F.P
    assert not RC.verify_comp(_CP1, _PROG1, 1, 0, BND, bad)[0]


def t_w10_multichunk_binds():
    ok, why = RC.verify_comp(_CP10, _PROG10, W10, 0, BND, _PUB10)
    assert ok, why


def t_wrong_index_rejected():
    bad = copy.deepcopy(_PUB10)
    bad["points_public"][1]["cur_index"] ^= 1
    assert not RC.verify_comp(_CP10, _PROG10, W10, 0, BND, bad)[0]


if __name__ == "__main__":
    check("W=1 row-mode composition binds a real row-committed proof", t_w1_binds)
    check("false layer-0 target rejected", t_false_layer0_rejected)
    check("wrong row root rejected", t_wrong_root_rejected)
    check("W=10 multi-chunk row absorption binds", t_w10_multichunk_binds)
    check("wrong query index rejected (IACC direction binding)", t_wrong_index_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
