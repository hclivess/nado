"""
SPARSE-ROOT settlement (execnode/stark/settlement_sparse.py) — the state-root-binding integration end-to-end. A
real zkVM epoch is proven with its exec proof AND a bound state-transition proof; the verifier confirms
pre_root → post_root over the SPARSE alghash storage root WITHOUT replaying the io or re-merkleizing the whole
state, and the resulting root serves withdrawal-membership exits too.

Checks: the bound epoch verifies; its sparse_post_root equals an INDEPENDENT full re-projection (replay the io,
sparse_root the result) — so the transition really is the epoch's; a withdrawal proves membership (and a wrong
value is rejected); and a tampered transition root is rejected.

Run: python3 tests/test_settlement_sparse.py     (~seconds: a couple of small epoch proofs)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import settlement_sparse as SS, storage_tree as ST, exec_state_bind as ESB
from execnode import zkvm, zkvmasm

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ, DEPTH = 8, 16
COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
STORE = {"put": zkvmasm.assemble("ctx r1 caller\n movi r2 5\n sstore r2 r1\n movi r0 1\n ret r0")}
ALICE = "ndoAAAA" + "A" * 41
CID_C, CID_S = "c" * 64, "d" * 64


def _pre():
    return {CID_C: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"},
            CID_S: {"code": STORE, "storage": {"slots": {}}, "runtime": "zkvm"}}


def _replay_post(bundle):
    """Independent full re-projection: replay the io against pre_contracts to get post_contracts (what
    verify_epoch does), then sparse_root it — the value the bound transition must reach."""
    post = copy.deepcopy(bundle["pre_contracts"])
    segs, cur = [], []
    for e in bundle["io"]:
        cur.append(e)
        if e[0] == zkvm.IO_RET:
            segs.append(cur); cur = []
    for call, seg in zip(bundle["calls"], segs):
        c = post[call["cid"]]
        slots = {int(k): int(v) for k, v in (c["storage"].get("slots") or {}).items()}
        ok, _ret, new_slots, _p, _ch = zkvm.replay_io(seg, slots)
        assert ok
        c["storage"] = {"slots": {str(k): v for k, v in sorted(new_slots.items())}}
    return post


CALLS = [{"cid": CID_C, "method": "bump", "caller": ALICE, "args": []},
         {"cid": CID_C, "method": "bump", "caller": ALICE, "args": []},
         {"cid": CID_S, "method": "put", "caller": ALICE, "args": []}]
_BUNDLE = SS.prove_bound_epoch(_pre(), CALLS, cursor=200, num_queries=NQ, depth=DEPTH)


def t_bound_epoch_verifies():
    ok, why, post_root = SS.verify_bound_epoch(_BUNDLE, num_queries=NQ)
    assert ok, f"bound epoch must verify with no replay: {why}"
    assert post_root == _BUNDLE["sparse_post_root"]


def t_post_root_matches_full_reprojection():
    """The sparse transition's post_root equals an independent whole-state re-projection — so binding the
    transition to the io is equivalent to (but far cheaper than) the old replay + re-merkleize."""
    post = _replay_post(_BUNDLE)
    assert SS.sparse_root(post, DEPTH) == _BUNDLE["sparse_post_root"], "sparse transition != full re-projection"


def t_withdrawal_membership():
    """The settled sparse root serves exit proofs: COUNTER slot 0 is now 2 (two bumps); prove it's a member."""
    post = _replay_post(_BUNDLE)
    store = ST.SparseStore(DEPTH, SS.sparse_projection(post, DEPTH))
    root = store.root()
    assert root == _BUNDLE["sparse_post_root"]
    key = ESB.slot_key(CID_C, 0, DEPTH)
    sibs = store.path(key)
    assert SS.verify_withdrawal(root, CID_C, 0, 2, sibs, DEPTH), "COUNTER slot 0 == 2 must prove membership"
    assert not SS.verify_withdrawal(root, CID_C, 0, 3, sibs, DEPTH), "a wrong value must be rejected"


def t_tampered_transition_rejected():
    bad = copy.deepcopy(_BUNDLE)
    bad["sparse_post_root"] = (int(bad["sparse_post_root"]) + 1) % (2**61)
    ok, _why, _ = SS.verify_bound_epoch(bad, num_queries=NQ)
    assert not ok, "a tampered sparse post_root must be rejected"


if __name__ == "__main__":
    check("bound epoch verifies (no replay, no whole-state merkle)", t_bound_epoch_verifies)
    check("sparse post_root == independent full re-projection", t_post_root_matches_full_reprojection)
    check("withdrawal membership against the settled sparse root", t_withdrawal_membership)
    check("tampered transition root rejected", t_tampered_transition_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
