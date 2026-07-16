"""
O(1)-shaped BOUND EPOCH (execnode/stark/bound_epoch_o1.py) — the assembled fully-succinct binding: the verifier
checks the exec proof in O(#calls) (verify_epoch_o1, committed periodic tables, no io-log rebuild) AND binds the
exec's COMMITTED io to the state replay's io columns with the DEEP out-of-domain binding (io_bind, O(polylog)) —
no public io, no re-execution.

Checks: an honest epoch + a replay that applies the SAME io verifies through the whole chain; a replay whose io
diverges from the exec's committed io is rejected (the binding catches it, the verifier never seeing the log).

Run: python3 tests/test_bound_epoch_o1.py   (one committed-periodic epoch proof + the DEEP binding)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import bound_epoch_o1 as BE, vm_circuit as VC, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 4
CID = "e" * 64
CODE = {"main": [["MOVI", 0, 0, 7], ["SSTORE", 0, 0, 0], ["MOVI", 1, 0, 5], ["SSTORE", 1, 0, 0],
                 ["RET", 0, 0, 0]]}
CALLS = [{"code": CODE, "method": "main", "caller": 1, "args": [], "slots": {}}]


def _cid_io():
    calls = [VC._norm_call(c) for c in CALLS]
    _tr, _T, _bl, _pr, epoch_io, _pc = VC.build_epoch_trace(calls)
    return [(CID, int(e[0]), int(e[1]), int(e[2])) for e in epoch_io]


def t_bound_epoch_o1_verifies():
    bundle = BE.prove_bound_epoch_o1(CALLS, _cid_io(), num_queries=NQ)
    ok, why = BE.verify_bound_epoch_o1(bundle, num_queries=NQ)
    assert ok, f"O(1)-shaped bound epoch must verify: {why}"


def t_divergent_replay_io_rejected():
    """A replay that applies a DIFFERENT io than the exec committed is rejected — the DEEP binding fails and the
    verifier never re-derived the log to notice by itself."""
    cid_io = _cid_io()
    cid_io[0] = (cid_io[0][0], cid_io[0][1], cid_io[0][2], (cid_io[0][3] + 999) % F.P)   # change a value
    bundle = BE.prove_bound_epoch_o1(CALLS, cid_io, num_queries=NQ)
    ok, _ = BE.verify_bound_epoch_o1(bundle, num_queries=NQ)
    assert not ok, "a replay io diverging from the exec's committed io must be rejected"


if __name__ == "__main__":
    check("exec verify O(#calls) + io binding assembled + verifies", t_bound_epoch_o1_verifies)
    check("divergent replay io rejected (bound, no public log)", t_divergent_replay_io_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
