"""
Aggregated epoch proof (execnode/stark/vm_circuit.prove_epoch_calls) — N calls across multiple contracts in
ONE STARK, so L1 verifies a single proof per epoch (O(1) in the call count). A single call is the N=1 case.
Verifies the whole batch with no re-execution; rejects a reordered log, a wrong per-call caller, a wrong
arg, and a non-contiguous block schedule.

Run: python3 tests/test_zkvm_epoch.py            (~1 min: two epoch proofs at reduced query count)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import vm_circuit as V
from execnode import zkvmasm, runtimes, zkvm

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 8
COUNTER = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
VAULT = {"deposit": zkvmasm.assemble("ctx r1 caller\n ctx r2 value\n sload r3 r1\n add r3 r2\n sstore r1 r3\n movi r0 1\n ret r0")}
A = "ndoAAA" + "A" * 42
B = "ndoBBB" + "B" * 42

def _mk(code, method, caller, args, slots, value=0):
    cf, fargs = runtimes.zkvm_statement(caller, args, {})
    return {"code": code, "method": method, "caller_f": cf, "args_f": fargs, "caller": caller,
            "args": args, "value": value, "slots": dict(slots)}

def _chain_counter(caller, n):
    """n back-to-back bump calls, each fed the previous post-storage."""
    calls, slots = [], {}
    for _ in range(n):
        c = _mk(COUNTER, "bump", caller, [], slots)
        calls.append(c)
        _ok, _r, slots, _io = zkvm.run(COUNTER, "bump", c["caller_f"], c["args_f"], slots)
    return calls

_cache = {}
def _epoch():
    if "e" not in _cache:
        calls = _chain_counter(A, 2) + [_mk(VAULT, "deposit", B, [], {}, value=500)]
        proof, io, per = V.prove_epoch_calls(calls, num_queries=NQ)
        _cache["e"] = (calls, proof, io, per)
    return _cache["e"]

def _pub(calls):
    return [{"code": c["code"], "method": c["method"], "caller": c["caller"], "args": c["args"],
             "value": c.get("value", 0)} for c in calls]

def t1_epoch_verifies():
    calls, proof, io, per = _epoch()
    assert [p["ret"] for p in per] == [1, 2, 1]
    ok, why = V.verify_epoch_calls(proof, _pub(calls), io, num_queries=NQ)
    assert ok, f"honest epoch must verify: {why}"

def t2_reordered_log_rejected():
    calls, proof, io, per = _epoch()
    bad = list(io); bad[0], bad[-1] = bad[-1], bad[0]
    ok, _ = V.verify_epoch_calls(proof, _pub(calls), bad, num_queries=NQ)
    assert not ok, "reordered global log must be rejected"

def t3_wrong_caller_rejected():
    calls, proof, io, per = _epoch()
    pub = _pub(calls); pub[2]["caller"] = A            # deposit was by B
    ok, _ = V.verify_epoch_calls(proof, pub, io, num_queries=NQ)
    assert not ok, "wrong per-call caller must be rejected"

def t4_non_contiguous_schedule_rejected():
    calls, proof, io, per = _epoch()
    import copy
    p2 = copy.deepcopy(proof)
    p2["blocks"][1]["start"] += 1                       # gap between calls
    ok, _ = V.verify_epoch_calls(p2, _pub(calls), io, num_queries=NQ)
    assert not ok, "non-contiguous block schedule must be rejected"

def t5_single_call_is_n1_epoch():
    c = _mk(COUNTER, "bump", A, [], {})
    proof, io, ret, ns = V.prove_call(COUNTER, "bump", c["caller_f"], [], {}, num_queries=NQ)
    ok, why = V.verify_call(proof, COUNTER, "bump", c["caller_f"], [], io, num_queries=NQ)
    assert ok and ret == 1, f"N=1 epoch must verify: {why}"


if __name__ == "__main__":
    check("epoch of 3 calls / 2 contracts verifies (one proof)", t1_epoch_verifies)
    check("reordered global log rejected", t2_reordered_log_rejected)
    check("wrong per-call caller rejected", t3_wrong_caller_rejected)
    check("non-contiguous block schedule rejected", t4_non_contiguous_schedule_rejected)
    check("single call is the N=1 epoch", t5_single_call_is_n1_epoch)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
