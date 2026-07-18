"""
The VM-2.0 capability pass — indexed args (ARG) + wide-divisor division (DIVMODW). Covers:
  · ARG semantics: dynamic-index load, out-of-range revert, MAX_ARGS boundary (1024 ok, 1025 refused)
  · a loop that sums N args through ARG (the variadic pattern packing hacks used to fake)
  · prove + verify of an ARG-using call, single and multi-call epoch (distinct args per call)
  · ARG SOUNDNESS negatives: a proof must NOT verify against a statement whose args were tampered with,
    truncated, or reordered — the args LogUp bus has to catch every one of these
  · DIVMODW semantics: pool-sized divisors (the parimutuel payout = stake*total//pool pattern), the
    q<2^32 / b<2^31 windows, remainder-in-r7, and a proven+verified DIVMODW call.

Run: python3 tests/test_zkvm_args.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode import zkvm, zkvmasm
from execnode.stark import vm_circuit as V, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 6
CALLER = 12345


def _run(code, args, **kw):
    return zkvm.run(code, "m", CALLER, args, {}, **kw)


# ---- native semantics --------------------------------------------------------------------------
def t_native_load():
    # m(idx, ...): return args[args[0]]  — a doubly-indirect load
    code = zkvmasm.assemble_contract({"m": "arg r1 r0\nret r1"})
    ok, ret, _, _ = _run(code, [3, 10, 20, 30, 40])
    assert ok and ret == 30, f"args[3] -> {ret}"
    ok, ret, _, _ = _run(code, [0, 99])
    assert ok and ret == 0, "args[0] is the index itself here"

def t_native_beyond_8():
    # load arg index 12 — impossible under the old register-only ABI
    code = zkvmasm.assemble_contract({"m": "movi r2 12\narg r1 r2\nret r1"})
    args = list(range(100, 120))
    ok, ret, _, _ = _run(code, args)
    assert ok and ret == 112

def t_native_oob_reverts():
    code = zkvmasm.assemble_contract({"m": "arg r1 r0\nret r1"})
    ok, ret, _, _ = _run(code, [5, 1, 2])           # index 5 >= len 3
    assert not ok, "out-of-range ARG must revert"

def t_max_args_boundary():
    code = zkvmasm.assemble_contract({"m": "movi r2 1023\narg r1 r2\nret r1"})
    args = list(range(zkvm.MAX_ARGS))               # exactly 1024
    ok, ret, _, _ = _run(code, args)
    assert ok and ret == 1023, "1024 args must execute"
    ok, _, _, _ = _run(code, args + [7])            # 1025
    assert not ok, "1025 args must be refused"

def t_loop_sum():
    # m(n, a1..an): sum args[1..n] via an ARG loop (r0 = n)
    asm = """
        movi r1 0        ; acc
        movi r2 1        ; i
    loop:
        mov r3 r0
        movi r4 1
        add r3 r4        ; n+1
        mov r4 r2
        lt r4 r3         ; i < n+1
        jnz r4 @body
        ret r1
    body:
        arg r5 r2
        add r1 r5
        movi r4 1
        add r2 r4
        jmp @loop
    """
    code = zkvmasm.assemble_contract({"m": asm})
    vals = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47]   # 12 args to sum — over the old cap
    ok, ret, _, _ = _run(code, [len(vals)] + vals)
    assert ok and ret == sum(vals), f"{ret} != {sum(vals)}"
    return code, vals


# ---- prove + verify ------------------------------------------------------------------------------
def _prove_ok(code, args, expect_ret):
    proof, io, ret, _ = V.prove_call(code, "m", CALLER, args, {}, num_queries=NQ)
    assert ret == expect_ret, f"prover ret {ret} != {expect_ret}"
    ok, why = V.verify_call(proof, code, "m", CALLER, args, io, num_queries=NQ)
    assert ok, f"verify: {why}"
    return proof, io

def t_prove_arg_call():
    code, vals = t_loop_sum()
    _prove_ok(code, [len(vals)] + vals, sum(vals))

def t_prove_epoch_two_calls():
    # two calls, same program, DIFFERENT args — the bus must not cross-contaminate (PC_CALL tag)
    code, vals = t_loop_sum()
    a1 = [3, 100, 200, 300]
    a2 = [4, 5, 6, 7, 8]
    calls = [{"code": code, "method": "m", "caller": "epoch", "args": a1, "slots": {}},
             {"code": code, "method": "m", "caller": "epoch", "args": a2, "slots": {}}]
    proof, epoch_io, per_call = V.prove_epoch_calls(calls, num_queries=NQ)
    assert per_call[0]["ret"] == 600 and per_call[1]["ret"] == 26
    ok, why = V.verify_epoch_calls(proof, calls, epoch_io, num_queries=NQ)
    assert ok, f"epoch verify: {why}"


# ---- soundness negatives: the args bus must reject every statement mismatch ----------------------
def t_sound_tampered_value():
    code, vals = t_loop_sum()
    args = [len(vals)] + vals
    proof, io = _prove_ok(code, args, sum(vals))
    bad = list(args); bad[5] += 1                    # one arg off by one
    ok, _ = V.verify_call(proof, code, "m", CALLER, bad, io, num_queries=NQ)
    assert not ok, "tampered arg value MUST fail verification"

def t_sound_truncated_args():
    code, vals = t_loop_sum()
    args = [len(vals)] + vals
    proof, io = _prove_ok(code, args, sum(vals))
    ok, _ = V.verify_call(proof, code, "m", CALLER, args[:6], io, num_queries=NQ)
    assert not ok, "truncated args MUST fail verification"

def t_sound_reordered_args():
    code, vals = t_loop_sum()
    args = [len(vals)] + vals
    proof, io = _prove_ok(code, args, sum(vals))
    bad = list(args); bad[3], bad[9] = bad[9], bad[3]   # same multiset, different indexing
    ok, _ = V.verify_call(proof, code, "m", CALLER, bad, io, num_queries=NQ)
    assert not ok, "reordered args MUST fail verification (the bus binds the INDEX)"

def t_sound_cross_call_args():
    # swap the two calls' args in the statement: same union of tuples per call index? No — call tags differ.
    code, _ = t_loop_sum()
    a1, a2 = [2, 10, 20], [2, 30, 40]
    calls = [{"code": code, "method": "m", "caller": "epoch", "args": a1, "slots": {}},
             {"code": code, "method": "m", "caller": "epoch", "args": a2, "slots": {}}]
    proof, epoch_io, _ = V.prove_epoch_calls(calls, num_queries=NQ)
    swapped = [dict(calls[0], args=a2), dict(calls[1], args=a1)]
    ok, _ = V.verify_epoch_calls(proof, swapped, epoch_io, num_queries=NQ)
    assert not ok, "cross-call arg swap MUST fail (PC_CALL tags the bus per call)"


# ---- DIVMODW: wide-divisor division (pro-rata pool splits) ---------------------------------------
def t_dmw_native():
    # m(a, b): return a // b, remainder checked via r7
    code = zkvmasm.assemble_contract({"m": "divmodw r1 r2\nmov r3 r7\nsstore r3 r3\nret r1"})
    # wait — r1 is dest but a is in... args: r0=unused, r1=a, r2=b (divmodw d s: d=a then d=q)
    ok, ret, st, io = zkvm.run(code, "m", CALLER, [0, 10**13 + 7, 2_000_000_001], {})
    assert ok and ret == (10**13 + 7) // 2_000_000_001, f"q wrong: {ret}"

def t_dmw_parimutuel():
    # THE pattern this op exists for: payout = stake * total // pool (pool-sized divisor, one op)
    code = zkvmasm.assemble_contract({"m": "mov r3 r0\nmul r3 r1\ndivmodw r3 r2\nret r3"})
    stake, total, pool = 300, 1500, 800                    # the old bet-contract test's market 1
    ok, ret, _, _ = zkvm.run(code, "m", CALLER, [stake, total, pool], {})
    assert ok and ret == stake * total // pool == 562
    stake, total, pool = 123_456_789, 987_654_321, 400_000_000    # big pools
    ok, ret, _, _ = zkvm.run(code, "m", CALLER, [stake, total, pool], {})
    assert ok and ret == stake * total // pool

def t_dmw_windows():
    code = zkvmasm.assemble_contract({"m": "divmodw r1 r2\nret r1"})
    ok, _, _, _ = zkvm.run(code, "m", CALLER, [0, 100, (1 << 31) + 1], {})  # divisor beyond the window
    assert not ok, "divisor > 2^31 must revert"
    ok, _, _, _ = zkvm.run(code, "m", CALLER, [0, 100, 1 << 31], {})        # b == 2^31 is the inclusive edge
    assert ok, "divisor == 2^31 (window edge) must be accepted — interpreter and AIR agree here"
    ok, _, _, _ = zkvm.run(code, "m", CALLER, [0, 100, 0], {})           # divide by zero
    assert not ok, "divisor 0 must revert"
    ok, _, _, _ = zkvm.run(code, "m", CALLER, [0, (1 << 33) * 3, 2], {}) # quotient too wide
    assert not ok, "quotient >= 2^32 must revert"
    ok, ret, _, _ = zkvm.run(code, "m", CALLER, [0, ((1 << 32) - 1) * ((1 << 31) - 1), (1 << 31) - 1], {})
    assert ok and ret == (1 << 32) - 1, "max q * max b must pass"

def t_dmw_rem_r7():
    code = zkvmasm.assemble_contract({"m": "divmodw r1 r2\nmov r1 r7\nret r1"})   # return remainder
    ok, ret, _, _ = zkvm.run(code, "m", CALLER, [0, 10**12 + 17, 999_999_937], {})
    assert ok and ret == (10**12 + 17) % 999_999_937
    # remw macro form
    code2 = zkvmasm.assemble_contract({"m": "remw r1 r2\nret r1"})
    ok, ret2, _, _ = zkvm.run(code2, "m", CALLER, [0, 10**12 + 17, 999_999_937], {})
    assert ok and ret2 == ret, "remw macro must equal manual form"

def t_dmw_proves():
    code = zkvmasm.assemble_contract({"m": "mov r3 r0\nmul r3 r1\ndivmodw r3 r2\nret r3"})
    args = [123_456_789, 987_654_321, 400_000_000]
    _prove_ok(code, args, args[0] * args[1] // args[2])


if __name__ == "__main__":
    check("ARG: dynamic-index load", t_native_load)
    check("ARG: index beyond the old 8-register ABI", t_native_beyond_8)
    check("ARG: out-of-range index reverts", t_native_oob_reverts)
    check("ARG: MAX_ARGS boundary (1024 ok / 1025 refused)", t_max_args_boundary)
    check("ARG: loop-sum over 12 args", lambda: (t_loop_sum(), None)[1])
    check("prove/verify: ARG call proves", t_prove_arg_call)
    check("prove/verify: 2-call epoch with distinct args", t_prove_epoch_two_calls)
    check("SOUNDNESS: tampered arg value rejected", t_sound_tampered_value)
    check("SOUNDNESS: truncated args rejected", t_sound_truncated_args)
    check("SOUNDNESS: reordered args rejected", t_sound_reordered_args)
    check("SOUNDNESS: cross-call arg swap rejected", t_sound_cross_call_args)
    check("DIVMODW: wide-divisor quotient", t_dmw_native)
    check("DIVMODW: parimutuel payout pattern (stake*total//pool)", t_dmw_parimutuel)
    check("DIVMODW: q/b windows enforced (2^32 / 2^31)", t_dmw_windows)
    check("DIVMODW: remainder in r7 + remw macro", t_dmw_rem_r7)
    check("DIVMODW: proves + verifies", t_dmw_proves)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
