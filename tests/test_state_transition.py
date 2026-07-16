"""
State TRANSITION proof (execnode/stark/state_transition.py) — the batch layer of state-root binding. A batch of
K storage writes is proven as K chained in-circuit merkle-updates: the per-update roots chain pre_root ->
post_root, and every update re-verifies. This is what lets a settlement verifier confirm a whole epoch's state
transition WITHOUT replaying it.

DEFAULT (fast): native mode — K RECURSION-committed merkle-update proofs + the chain check; cross-checked
against storage_tree (post_root == full rebuild), and soundness (broken chain, tampered proof, wrong public
pre/post all rejected). NADO_HEAVY=1 also folds the K proofs K->1 via recursive_verify (the O(1) enabler; slow
— the recursion throughput wall) and verifies the transition through that single bundle.

Run: python3 tests/test_state_transition.py   (NADO_HEAVY=1 python3 … for the K->1 fold)
"""
import os, sys, copy, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import state_transition as SX, storage_tree as ST, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

D, NQ, HEAVY = 8, 8, os.environ.get("NADO_HEAVY") == "1"


def _setup(seed, k_updates):
    random.seed(seed)
    vals = {}
    while len(vals) < 20:
        vals[random.randrange(1 << D)] = random.randrange(1, F.P)
    store = ST.SparseStore(D, dict(vals))
    keys = list(vals)[:k_updates - 1] + [next(k for k in range(1 << D) if k not in vals)]  # incl. a fresh slot
    updates = [(k, random.randrange(1, F.P)) for k in keys]
    return store, updates


def t_transition_verifies_and_matches_rebuild():
    store, updates = _setup(1, 3)
    pre_root = store.root()
    ref = ST.SparseStore(D, dict(store.values))
    tr = SX.prove_transition(store, updates, num_queries=NQ)          # mutates `store` to post-state
    post_root = store.root()
    for k, v in updates:
        ref.set(k, v)
    assert post_root == ref.root(), "post_root must equal a full rebuild with the writes applied"
    assert tr["roots"][0] == pre_root and tr["roots"][-1] == post_root, "roots must chain pre->post"
    ok, why = SX.verify_transition(tr, pre_root, post_root, num_queries=NQ)
    assert ok, f"transition must verify: {why}"


def t_soundness():
    store, updates = _setup(2, 3)
    pre_root = store.root()
    tr = SX.prove_transition(store, updates, num_queries=NQ)
    post_root = store.root()
    # wrong public pre/post rejected
    assert not SX.verify_transition(tr, (pre_root + 1) % F.P, post_root, num_queries=NQ)[0], "wrong pre_root"
    assert not SX.verify_transition(tr, pre_root, (post_root + 1) % F.P, num_queries=NQ)[0], "wrong post_root"
    # broken chain: corrupt an intermediate root -> a proof no longer authenticates its (pre,post)
    bad = copy.deepcopy(tr)
    bad["roots"][1] = (bad["roots"][1] + 1) % F.P
    assert not SX.verify_transition(bad, pre_root, post_root, num_queries=NQ)[0], "broken chain must be rejected"
    # tampered proof (corrupt a committed cell) rejected
    bad2 = copy.deepcopy(tr)
    q = bad2["proofs"][0]["openings"][0]["cols"][0]
    q["cur"] = (int(q["cur"]) + 1) % F.P
    assert not SX.verify_transition(bad2, pre_root, post_root, num_queries=NQ)[0], "tampered proof must be rejected"


def t_k_to_1_fold():
    """OPT-IN (NADO_HEAVY=1): fold the K update proofs into ONE recursion bundle (recursive_verify) and verify
    the whole transition through that single bundle — the O(1) collapse."""
    if not HEAVY:
        print("SKIP  K->1 fold of the transition (set NADO_HEAVY=1; minutes — recursion throughput wall)")
        return
    store, updates = _setup(3, 2)
    pre_root = store.root()
    tr = SX.prove_transition(store, updates, num_queries=2, outer_queries=2, fold=True)
    post_root = store.root()
    assert "bundle" in tr
    ok, why = SX.verify_transition(tr, pre_root, post_root, num_queries=2, outer_queries=2)
    assert ok, f"transition must verify through the K->1 bundle: {why}"


if __name__ == "__main__":
    check("batch transition verifies + post_root == full rebuild", t_transition_verifies_and_matches_rebuild)
    check("soundness: wrong pre/post, broken chain, tampered proof rejected", t_soundness)
    check("K->1 fold of the transition (opt-in)", t_k_to_1_fold)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
