"""
Bind the state transition to the epoch's writes (execnode/stark/exec_state_bind.py) — state-root binding
piece (b). net_updates derives the NET (key, old, new) change of every touched (cid, slot) from the epoch's io
(SLOAD/SSTORE), and bind_and_verify requires the transition proof to prove EXACTLY those and nothing else — so
a valid bound transition provably IS the epoch's storage transition, not an arbitrary one.

Checks: net_updates picks the right changed slots (skips read-only + net-unchanged); a bound transition
verifies; and binding REJECTS a tampered io (different write), a lied SLOAD, and a transition whose updates
don't match the io.

Run: python3 tests/test_exec_state_bind.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import (exec_state_bind as ESB, state_transition as SX, storage_tree as ST, field as F)

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

D, NQ = 8, 8
CID1, CID2 = "a" * 64, "b" * 64
IO_SLOAD, IO_SSTORE = 1, 2


def _setup():
    # pre-state (cid,slot)->value; sparse store keyed by slot_key
    pre_map = {(CID1, 0): 100, (CID1, 5): 200, (CID2, 3): 300}
    keys = {ESB.slot_key(c, s, D): v for (c, s), v in pre_map.items()}
    assert len(keys) == len(pre_map), "test key collision — repick slots"
    store = ST.SparseStore(D, dict(keys))
    pre_get = lambda cid, slot: pre_map.get((str(cid), int(slot)), 0)
    # io: write (CID1,0)=111 ; read (CID1,5)=200 (unchanged) ; delete (CID2,3) ; write fresh (CID2,7)=999
    cid_io = [(CID1, IO_SSTORE, 0, 111), (CID1, IO_SLOAD, 5, 200), (CID2, IO_SSTORE, 3, 0), (CID2, IO_SSTORE, 7, 999)]
    fresh_key = ESB.slot_key(CID2, 7, D)
    assert fresh_key not in keys, "test fresh-slot collision — repick"
    return store, pre_get, cid_io, pre_map


def t_net_updates_selects_changes():
    store, pre_get, cid_io, pre_map = _setup()
    net = ESB.net_updates(pre_get, cid_io, D)
    # changed: (CID1,0) 100->111, (CID2,3) 300->0, (CID2,7) 0->999 ; NOT (CID1,5) (read-only)
    want = [(ESB.slot_key(CID1, 0, D), 100, 111),
            (ESB.slot_key(CID2, 3, D), 300, 0),
            (ESB.slot_key(CID2, 7, D), 0, 999)]
    assert net == want, f"net_updates wrong: {net}"


def t_bound_transition_verifies():
    store, pre_get, cid_io, pre_map = _setup()
    net = ESB.net_updates(pre_get, cid_io, D)
    pre_root = store.root()
    tr = SX.prove_transition(store, [(k, n) for (k, _o, n) in net], num_queries=NQ)
    post_root = store.root()
    ok, why = ESB.bind_and_verify(tr, pre_root, post_root, pre_get, cid_io, D, num_queries=NQ)
    assert ok, f"bound transition must verify: {why}"


def t_binding_rejects_tampering():
    store, pre_get, cid_io, pre_map = _setup()
    net = ESB.net_updates(pre_get, cid_io, D)
    pre_root = store.root()
    tr = SX.prove_transition(store, [(k, n) for (k, _o, n) in net], num_queries=NQ)
    post_root = store.root()

    # (1) tampered io — a different write value ⇒ derived net writes differ ⇒ binding rejects
    bad_io = [(CID1, IO_SSTORE, 0, 222)] + cid_io[1:]
    assert not ESB.bind_and_verify(tr, pre_root, post_root, pre_get, bad_io, D, num_queries=NQ)[0], "tampered io"

    # (2) lied SLOAD — read (CID1,5) claims 999 (pre is 200) ⇒ net_updates raises ⇒ binding rejects
    lied_io = [cid_io[0], (CID1, IO_SLOAD, 5, 999)] + cid_io[2:]
    assert not ESB.bind_and_verify(tr, pre_root, post_root, pre_get, lied_io, D, num_queries=NQ)[0], "lied read"

    # (3) transition whose updates don't match the io (fewer writes) ⇒ binding rejects
    short_io = cid_io[:1] + cid_io[1:2]     # only the first write + the read
    assert not ESB.bind_and_verify(tr, pre_root, post_root, pre_get, short_io, D, num_queries=NQ)[0], "count mismatch"


if __name__ == "__main__":
    check("net_updates selects exactly the changed slots", t_net_updates_selects_changes)
    check("bound transition verifies", t_bound_transition_verifies)
    check("binding rejects tampered io / lied read / mismatch", t_binding_rejects_tampering)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
