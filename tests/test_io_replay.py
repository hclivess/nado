"""
IN-CIRCUIT io replay (execnode/stark/io_replay.py) — the state half of the in-circuit statement rebuild. It
proves pre_root → post_root by processing the epoch's io directly in-circuit (SLOAD = membership, SSTORE =
merkle-update), chained, so the state transition is bound to the exact io the epoch proof proved — no native
net-update derivation, no whole-state merkle.

Checks: a small io replay verifies and its post_root matches a native storage_tree application; a SLOAD of the
wrong value fails (the membership can't fold to the current root); and a tampered chain root is rejected.

Run: python3 tests/test_io_replay.py   (a handful of small membership/update STARKs)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import io_replay as IR, storage_tree as ST, exec_state_bind as ESB, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

D, NQ = 8, 8
CID = "e" * 64
IO_SLOAD, IO_SSTORE = 1, 2


def _store():
    return ST.SparseStore(D, {ESB.slot_key(CID, 0, D): 100, ESB.slot_key(CID, 5, D): 200})


def _apply_native(store, cid_io):
    for (cid, kind, slot, value) in cid_io:
        if kind == IO_SSTORE:
            store.set(ESB.slot_key(cid, slot, D), value)
    return store.root()


def t_replay_verifies_and_matches():
    store = _store()
    pre_root = store.root()
    cid_io = [(CID, IO_SLOAD, 0, 100),           # read the committed 100
              (CID, IO_SSTORE, 0, 111),          # write 0 -> 111
              (CID, IO_SSTORE, 5, 0)]            # clear slot 5
    expect_post = _apply_native(ST.SparseStore(D, dict(store.values)), cid_io)
    bundle = IR.prove_io_replay(store, cid_io, D, num_queries=NQ)   # mutates `store` to post-state
    post_root = store.root()
    assert post_root == expect_post, "replay post_root must match native application"
    ok, why = IR.verify_io_replay(bundle, pre_root, post_root, num_queries=NQ)
    assert ok, f"io replay must verify: {why}"


def t_lied_read_rejected():
    store = _store()
    pre_root = store.root()
    # SLOAD claims slot 0 == 999, but the committed value is 100 ⇒ the membership can't fold to pre_root
    cid_io = [(CID, IO_SLOAD, 0, 999)]
    bundle = IR.prove_io_replay(ST.SparseStore(D, dict(store.values)), cid_io, D, num_queries=NQ)
    ok, _ = IR.verify_io_replay(bundle, pre_root, pre_root, num_queries=NQ)
    assert not ok, "a SLOAD of the wrong value must be rejected"


def t_tampered_chain_rejected():
    store = _store()
    pre_root = store.root()
    cid_io = [(CID, IO_SSTORE, 0, 111), (CID, IO_SSTORE, 5, 222)]
    bundle = IR.prove_io_replay(store, cid_io, D, num_queries=NQ)
    post_root = store.root()
    bad = copy.deepcopy(bundle)
    bad["roots"][1] = (int(bad["roots"][1]) + 1) % F.P            # break the chain
    ok, _ = IR.verify_io_replay(bad, pre_root, post_root, num_queries=NQ)
    assert not ok, "a tampered chain root must be rejected"


if __name__ == "__main__":
    check("in-circuit replay verifies + post_root matches native", t_replay_verifies_and_matches)
    check("lied SLOAD rejected (membership can't fold)", t_lied_read_rejected)
    check("tampered chain root rejected", t_tampered_chain_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
