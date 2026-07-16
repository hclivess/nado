"""
CALLS COMMITMENT (execnode/stark/calls_commit.py) — the O(1) public input for an epoch's calls. The K ordered
calls collapse to ONE field element (a merkle_node hash chain over the call leaves), so a settlement verifier
holds (calls_commitment, pre_root, post_root) instead of every call. Because it is exactly membership.py's fold
with the call leaves as siblings, it is PROVABLE + FOLDABLE.

Checks: the native commitment equals a membership fold of IV through the leaves; the in-circuit proof folds to
that same commitment and verifies (default + RECURSION backend, foldable); order matters (reordered calls ⇒
different commitment); and a wrong commitment / call count is rejected.

Run: python3 tests/test_calls_commit.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import calls_commit as CC, membership as MB, alghash, field as F, backend as B

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 8
CALLS = [{"cid": "c" * 64, "method": "bump", "caller": "ndoAAAA" + "A" * 41, "args": []},
         {"cid": "c" * 64, "method": "bump", "caller": "ndoAAAA" + "A" * 41, "args": []},
         {"cid": "d" * 64, "method": "put", "caller": "ndoBBBB" + "B" * 41, "args": [7, 9]}]


def t_commitment_is_a_membership_fold():
    c = CC.calls_commitment(CALLS, cursor=200, timestamp=5)
    ls = CC.leaves(CALLS, cursor=200, timestamp=5)
    assert c == MB.merkle_root_from_path(alghash.IV, ls, [0] * len(ls)), "commitment must equal the IV→leaves fold"


def t_order_matters():
    a = CC.calls_commitment(CALLS, 200, 5)
    b = CC.calls_commitment(list(reversed(CALLS)), 200, 5)
    assert a != b, "reordering the calls must change the commitment"


def t_in_circuit_proof_verifies():
    proof, commit = CC.prove_calls_commitment(CALLS, cursor=200, timestamp=5, num_queries=NQ)
    assert commit == CC.calls_commitment(CALLS, 200, 5), "proved commitment must equal the native one"
    ok, why = CC.verify_calls_commitment(proof, commit, len(CALLS), num_queries=NQ)
    assert ok, f"calls-commitment proof must verify: {why}"
    # soundness: wrong commitment or wrong call count rejected
    assert not CC.verify_calls_commitment(proof, (commit + 1) % F.P, len(CALLS), num_queries=NQ)[0], "wrong commitment"
    assert not CC.verify_calls_commitment(proof, commit, len(CALLS) + 1, num_queries=NQ)[0], "wrong call count"


def t_foldable_recursion_backend():
    proof, commit = CC.prove_calls_commitment(CALLS, 200, 5, num_queries=NQ, backend=B.RECURSION)
    ok, why = CC.verify_calls_commitment(proof, commit, len(CALLS), num_queries=NQ, backend=B.RECURSION)
    assert ok, f"RECURSION-committed calls-commitment must verify (foldable): {why}"


if __name__ == "__main__":
    check("native commitment == IV→leaves membership fold", t_commitment_is_a_membership_fold)
    check("call order changes the commitment", t_order_matters)
    check("in-circuit proof verifies (+ soundness)", t_in_circuit_proof_verifies)
    check("provable + verifiable under RECURSION backend (foldable)", t_foldable_recursion_backend)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
