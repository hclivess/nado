"""
STATE-side io tie (execnode/stark/state_io_tie.py) — the last leg: every io_replay step lands at the tree
position slot_key(cid, slot) PROVEN in-circuit (slot_key_air), so the bound io columns provably drive the state
transition without the verifier recomputing the position hash.

Checks: the positions of a real io_replay verify against their in-circuit slot_key derivations; a step forced to
a different position is rejected.

Run: python3 tests/test_state_io_tie.py   (a few small slot_key sponge proofs)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import (state_io_tie as ST, io_replay as IR, storage_tree as STree, exec_state_bind as ESB,
                            backend as B, field as F)
from execnode import zkvm

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

D, NQ = 8, 8
CID = "e" * 64
CID_IO = [(CID, zkvm.IO_SLOAD, 0, 100), (CID, zkvm.IO_SSTORE, 0, 111), (CID, zkvm.IO_SSTORE, 5, 0)]
bk = B.ALGHASH2


def _replay_steps():
    store = STree.SparseStore(D, {ESB.slot_key(CID, 0, D): 100, ESB.slot_key(CID, 5, D): 200})
    bundle = IR.prove_io_replay(store, CID_IO, D, num_queries=NQ)
    return bundle["steps"]


def t_positions_tie():
    steps = _replay_steps()
    positions = ST.prove_positions(CID_IO, D, num_queries=NQ, backend=bk)
    assert len(positions) == len(steps), "one position per storage step"
    ok, why = ST.verify_positions(positions, steps, D, num_queries=NQ, backend=bk)
    assert ok, f"positions must tie to the replay steps: {why}"


def t_wrong_position_rejected():
    steps = _replay_steps()
    positions = ST.prove_positions(CID_IO, D, num_queries=NQ, backend=bk)
    bad = copy.deepcopy(steps)
    bad[1]["key"] = (int(bad[1]["key"]) + 1) % (1 << D)          # move a step off its proven slot_key
    ok, _ = ST.verify_positions(positions, bad, D, num_queries=NQ, backend=bk)
    assert not ok, "a step at a position != its proven slot_key(cid, slot) must be rejected"


if __name__ == "__main__":
    check("io_replay positions tie to in-circuit slot_key", t_positions_tie)
    check("step off its proven slot_key rejected", t_wrong_position_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
