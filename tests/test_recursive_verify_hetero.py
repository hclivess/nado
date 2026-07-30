"""
Heterogeneous recursion (execnode/stark/recursive_verify_hetero.py) — fold proofs of DIFFERENT AIRs into ONE
bundle (one FRI fold + one composition per distinct AIR). The composition primitive the O(1) settlement assembly
and authoritative depth need (fold exec + replay + binding, or fold-AIR + comp-AIR together).

Checks: an x² proof and an x³ proof (different AIRs) fold into one bundle that verifies from public parts;
claiming the WRONG AIR for a proof is rejected by that group's composition; a tampered fold seam is rejected.

Run: python3 tests/test_recursive_verify_hetero.py
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import (stark, field as F, backend as B, recursive_verify as RV,
                            recursive_verify_hetero as RVH, extf as ext2)

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

T, NQ, NQO, MD = 8, 2, 2, 3
TRANS_X2 = [lambda c, n, p: F.sub(n[0], F.mul(c[0], c[0]))]
TRANS_X3 = [lambda c, n, p: F.sub(n[0], F.mul(F.mul(c[0], c[0]), c[0]))]


def _proof(trans, seed, step):
    col = [seed % F.P]
    for _ in range(T - 1):
        col.append(step(col[-1]))
    p = stark.prove([[v] for v in col], trans, [(0, 0, seed % F.P)], max_degree=MD, num_queries=NQ,
                    backend=B.RECURSION)
    return p, [(0, 0, seed % F.P)]


P2, B2 = _proof(TRANS_X2, 123456789, lambda x: F.mul(x, x))
P3, B3 = _proof(TRANS_X3, 987654321, lambda x: F.mul(F.mul(x, x), x))
ITEMS = [{"proof": P2, "transitions": TRANS_X2, "boundaries": B2},
         {"proof": P3, "transitions": TRANS_X3, "boundaries": B3}]
BUNDLE = RVH.prove_hetero(ITEMS, num_queries_outer=NQO)
PUBS = [RV.public_part(P2), RV.public_part(P3)]
AIRS = [{"transitions": TRANS_X2, "boundaries": B2}, {"transitions": TRANS_X3, "boundaries": B3}]


def t_hetero_verifies():
    ok, why = RVH.verify_hetero(PUBS, AIRS, BUNDLE, num_queries_outer=NQO, num_queries_inner=NQ)
    assert ok, f"heterogeneous bundle must verify: {why}"


def t_wrong_air_rejected():
    bad_airs = [{"transitions": TRANS_X3, "boundaries": B2}, {"transitions": TRANS_X3, "boundaries": B3}]  # lie about P2
    ok, _ = RVH.verify_hetero(PUBS, bad_airs, BUNDLE, num_queries_outer=NQO, num_queries_inner=NQ)
    assert not ok, "claiming the wrong AIR for a proof must be rejected"


def t_tampered_seam_rejected():
    bad = copy.deepcopy(PUBS)
    bad[0]["layer0"][0] = _bump(bad[0]["layer0"][0])
    ok, _ = RVH.verify_hetero(bad, AIRS, BUNDLE, num_queries_outer=NQO, num_queries_inner=NQ)
    assert not ok, "a tampered layer-0 seam must be rejected"


# --- a tiny TWO-PHASE ROW-committed AIR (z = running sum of β·a) folded WITH a column proof --------------
# This is the shape that matters for the fold-layer binding: the exec proof is row-committed two-phase, the
# replay/binding proofs are column — they must fold into ONE shared-transcript bundle.
# β IS AN EXTENSION ELEMENT whenever the live challenge field is one, so the accumulator it drives is too and
# is carried as DEGREE base columns. The base-only version did F.mul(chal[0], ...) with chal[0] a tuple,
# which Python turns into tuple-repetition and then a TypeError several frames away. Derived from the live
# authority and extf.DEGREE so it tracks the field instead of pinning one.
_EXT = stark.ext_challenges_active(B.RECURSION)
D_AZ = ext2.DEGREE if _EXT else 1
Z0 = 1                                                                          # aux limbs at columns 1..D


def _c_az(c, n, p, ch):
    if not _EXT:
        return F.sub(n[Z0], F.add(c[Z0], F.mul(ch[0], c[0])))
    cur = tuple(c[Z0 + i] for i in range(D_AZ))
    nxt = tuple(n[Z0 + i] for i in range(D_AZ))
    return ext2.sub_f(nxt, ext2.add_f(cur, ext2.mul_f(ch[0], c[0])))


TRANS_AZ = [_c_az]                                                              # z' = z + β·a
BND_AZ = [(0, Z0 + i, 0) for i in range(D_AZ)]                                  # EVERY limb of z pinned at 0


def _aux_az():
    def build(trace, chal):
        g = chal[0]
        if not _EXT:
            z = [0]
            for i in range(len(trace) - 1):
                z.append(F.add(z[-1], F.mul(g, trace[i][0])))
            return [z]
        acc, outs = ext2.ZERO, [[0] for _ in range(D_AZ)]
        for i in range(len(trace) - 1):
            acc = ext2.add(acc, ext2.mul(g, trace[i][0]))
            for k in range(D_AZ):
                outs[k].append(acc[k])
        return outs                                                             # D aux columns, length T
    return {"num_challenges": 1, "num_aux": D_AZ, "build": build}


def _bump(v):
    """Perturb a seam value by one in whatever field it lives in. `int(v) + 1` was written for a scalar and
    RAISES on a tuple — and a tamper test that raises still satisfies a naive assert-not-ok, so it would have
    quietly stopped testing anything the moment the seam became extension-valued."""
    if isinstance(v, tuple):
        return ((v[0] + 1) % F.P,) + tuple(v[1:])
    return (int(v) + 1) % F.P


def _row_two_phase_proof():
    a = [(i * 13 + 5) % F.P for i in range(T)]
    p = stark.prove([[v] for v in a], TRANS_AZ, BND_AZ, max_degree=MD, num_queries=NQ, backend=B.RECURSION,
                    row_commit=True, aux_spec=_aux_az())
    return p


def _col_x2_md():
    col = [42]
    for _ in range(T - 1):
        col.append(F.mul(col[-1], col[-1]))
    p = stark.prove([[v] for v in col], TRANS_X2, [(0, 0, 42)], max_degree=MD, num_queries=NQ, backend=B.RECURSION)
    return p, [(0, 0, 42)]


def t_row_twophase_plus_column_fold():
    """A ROW-committed TWO-PHASE proof and a COLUMN single-phase proof fold into ONE bundle and re-verify —
    the mixed-mode fold the exec(row/2-phase)+replay(col) binding rides on."""
    pr = _row_two_phase_proof()
    pc, bc = _col_x2_md()
    items = [{"proof": pr, "transitions": TRANS_AZ, "boundaries": BND_AZ, "num_challenges": 1, "num_aux": D_AZ},
             {"proof": pc, "transitions": TRANS_X2, "boundaries": bc}]
    bundle = RVH.prove_hetero(items, num_queries_outer=NQO)
    pubs = [RV.public_part(pr), RV.public_part(pc)]
    airs = [{"transitions": TRANS_AZ, "boundaries": BND_AZ, "num_challenges": 1, "num_aux": D_AZ},
            {"transitions": TRANS_X2, "boundaries": bc}]
    ok, why = RVH.verify_hetero(pubs, airs, bundle, num_queries_outer=NQO, num_queries_inner=NQ)
    assert ok, f"mixed row-two-phase + column bundle must verify: {why}"
    # soundness: a tampered seam on the row proof is caught
    bad = copy.deepcopy(pubs)
    bad[0]["layer0"][0] = _bump(bad[0]["layer0"][0])
    ok2, _ = RVH.verify_hetero(bad, airs, bundle, num_queries_outer=NQO, num_queries_inner=NQ)
    assert not ok2, "a tampered row-proof seam must be rejected"


if __name__ == "__main__":
    check("two different AIRs fold into one bundle + verify", t_hetero_verifies)
    check("wrong AIR for a proof rejected", t_wrong_air_rejected)
    check("tampered fold seam rejected", t_tampered_seam_rejected)
    check("row two-phase + column fold into one bundle", t_row_twophase_plus_column_fold)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
