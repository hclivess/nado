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
                            recursive_verify_hetero as RVH)

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
    bad[0]["layer0"][0] = (int(bad[0]["layer0"][0]) + 1) % F.P
    ok, _ = RVH.verify_hetero(bad, AIRS, BUNDLE, num_queries_outer=NQO, num_queries_inner=NQ)
    assert not ok, "a tampered layer-0 seam must be rejected"


if __name__ == "__main__":
    check("two different AIRs fold into one bundle + verify", t_hetero_verifies)
    check("wrong AIR for a proof rejected", t_wrong_air_rejected)
    check("tampered fold seam rejected", t_tampered_seam_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
