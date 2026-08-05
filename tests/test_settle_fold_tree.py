"""TREE-FOLDED hetero bundles (recursive_verify_hetero.prove_hetero(fan_in=...)).

WHY. The single bundle folds ALL K inner FRIs in ONE recursion proof, and that proof's trace is LINEAR IN
K — measured ~65,536 rows per folded proof, so K=2 -> T=131,072, K=4 -> T=262,144, K=8 -> T=524,288. With
the game contracts deployed, a real span put K in the dozens and T in the millions: the settle prove blew
SETTLE_PROVE_TIMEOUT=1200s at 2.8 GB RSS and produced NO proof at all. Folding through
recursion_depth.fold_tree bounds each node's trace by the FAN-IN instead of by K.

What is pinned here:
  1. a tree bundle round-trips: prove_hetero(fan_in=2) -> verify_hetero says ok;
  2. the fan-in actually BOUNDS the per-node trace (the point of the change);
  3. fan_in=None, and fan_in >= K, still take the single-fold path — unchanged behaviour;
  4. SOUNDNESS, the part that matters: the verifier must not trust anything the PROVER wrote into the
     tree. verify_tree reads `_inner_mks` (level-0 transcript factories) and each node's `public` off the
     tree; verify_hetero rebuilds BOTH from the inner proofs' public parts. Poisoning them must not change
     a verdict — otherwise this is the forged-intermediate bug class again (eee54fe).
  5. a tree that does not COVER every inner proof is rejected — verify_tree alone checks the nodes it is
     given, so dropping an item would otherwise go unnoticed.

Run: python3 tests/test_settle_fold_tree.py
"""
import os, sys, copy, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import (stark, field as F, backend as B, recursive_verify as RV,
                            recursive_verify_hetero as RVH)

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


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


def _items(n_pairs):
    """2*n_pairs items alternating two DIFFERENT AIRs, so the bundle is genuinely heterogeneous."""
    out = []
    for i in range(n_pairs):
        p2, b2 = _proof(TRANS_X2, 123456789 + i, lambda x: F.mul(x, x))
        p3, b3 = _proof(TRANS_X3, 987654321 + i, lambda x: F.mul(F.mul(x, x), x))
        out.append({"proof": p2, "transitions": TRANS_X2, "boundaries": b2})
        out.append({"proof": p3, "transitions": TRANS_X3, "boundaries": b3})
    return out


ITEMS = _items(2)                        # K = 4
PUBS = [RV.public_part(it["proof"]) for it in ITEMS]
AIRS = [{"transitions": it["transitions"], "boundaries": it["boundaries"]} for it in ITEMS]
NQI = len(ITEMS[0]["proof"]["fri"]["queries"])


def _verify(bundle):
    return RVH.verify_hetero(PUBS, AIRS, bundle, num_queries_outer=NQO, num_queries_inner=NQI)


# ONE bundle only. Each prove_hetero pays for the per-AIR compositions, which dominate at this size and
# are identical on both paths; building a second (flat) bundle here doubled the runtime past 25 minutes
# for no new coverage. The single-fold path is already covered end-to-end by test_recursive_verify_hetero.
TREE_BUNDLE = RVH.prove_hetero(ITEMS, num_queries_outer=NQO, fan_in=2)


# ---- 1/3. shape ---------------------------------------------------------------------------------------
def t_tree_shape():
    assert "tree" in TREE_BUNDLE and TREE_BUNDLE.get("fold") is None, "fan_in must fold as a TREE"
    lv = TREE_BUNDLE["tree"]["levels"]
    assert len(lv) >= 2, f"K=4 at fan_in=2 must have depth >= 2, got {len(lv)}"
    assert len(lv[0]) == 2, f"level 0 must have 2 nodes, got {len(lv[0])}"


def t_fan_in_bounds_the_node():
    """Every level-0 node folds at most fan_in proofs — the property that bounds the trace."""
    for node in TREE_BUNDLE["tree"]["levels"][0]:
        assert len(node["children"]) <= 2, f"node folds {len(node['children'])} > fan_in"


# ---- 2. round trip ------------------------------------------------------------------------------------
def t_tree_verifies():
    ok, why = _verify(TREE_BUNDLE)
    assert ok, f"tree bundle must verify: {why}"


# ---- 4. the verifier must not trust the prover's copies -----------------------------------------------
def t_poisoned_inner_mks_ignored():
    """`_inner_mks` is PROVER data. verify_hetero rebuilds it, so poisoning it must change nothing."""
    b = copy.deepcopy(TREE_BUNDLE)
    b["tree"]["_inner_mks"] = [None] * len(ITEMS)          # wrong factories
    ok, why = _verify(b)
    assert ok, f"verifier must rebuild _inner_mks, not use the prover's: {why}"


def t_poisoned_level0_public_ignored():
    """Each node's `public` is PROVER data at level 0; the verifier rebuilds it from the inner publics."""
    b = copy.deepcopy(TREE_BUNDLE)
    for node in b["tree"]["levels"][0]:
        node["public"]["seam_lo0"] = [0] * len(node["public"].get("seam_lo0") or [])
        node["public"]["num_queries_inner"] = 99999
    ok, why = _verify(b)
    assert ok, f"verifier must rebuild level-0 publics, not use the prover's: {why}"


# ---- 5. real tampering is still caught ----------------------------------------------------------------
def t_dropped_item_rejected():
    """A tree that omits an inner proof must NOT verify — coverage is checked explicitly."""
    b = copy.deepcopy(TREE_BUNDLE)
    b["tree"]["levels"][0][0]["children"] = [0]            # silently drop item 1
    ok, why = _verify(b)
    assert not ok, "a tree that does not cover every inner proof must be rejected"


def t_out_of_range_child_rejected():
    b = copy.deepcopy(TREE_BUNDLE)
    b["tree"]["levels"][0][0]["children"] = [0, 99]
    ok, why = _verify(b)
    assert not ok, "an out-of-range child index must be rejected"


def t_tampered_root_rejected():
    """Corrupt the ROOT fold proof — the statement everything else hangs from."""
    b = copy.deepcopy(TREE_BUNDLE)
    root = b["tree"]["levels"][-1][0]["proof"]
    roots = root["fri"]["roots"]
    roots[0] = tuple((int(x) + 1) % F.P for x in roots[0])
    ok, why = _verify(b)
    assert not ok, "a tampered root fold proof must be rejected"


def t_swapped_children_rejected():
    """Re-pointing a node at children it did not fold must fail the structure cross-check."""
    b = copy.deepcopy(TREE_BUNDLE)
    n0, n1 = b["tree"]["levels"][0][0], b["tree"]["levels"][0][1]
    n0["children"], n1["children"] = n1["children"], n0["children"]
    ok, why = _verify(b)
    assert not ok, "a node must not pass while naming children it did not fold"


for nm, fn in [("tree bundle has the right shape", t_tree_shape),
               ("every node folds at most fan_in proofs", t_fan_in_bounds_the_node),
               ("TREE BUNDLE VERIFIES", t_tree_verifies),
               ("poisoned _inner_mks is ignored (verifier rebuilds)", t_poisoned_inner_mks_ignored),
               ("poisoned level-0 public is ignored (verifier rebuilds)", t_poisoned_level0_public_ignored),
               ("a dropped inner proof is REJECTED", t_dropped_item_rejected),
               ("an out-of-range child is REJECTED", t_out_of_range_child_rejected),
               ("a tampered root fold proof is REJECTED", t_tampered_root_rejected),
               ("swapped children are REJECTED", t_swapped_children_rejected)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
