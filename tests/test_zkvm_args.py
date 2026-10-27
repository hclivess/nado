"""
The VM-2.0 capability pass — indexed args (ARG) + wide-divisor division (DIVMODW). Covers:
  · ARG semantics: dynamic-index load, out-of-range revert, MAX_ARGS boundary (1024 ok, 1025 refused)
  · a loop that sums N args through ARG (the variadic pattern packing hacks used to fake)
  · DIVMODW semantics: pool-sized divisors (the parimutuel payout = stake*total//pool pattern), full-word division
    with only a zero divisor reverting, remainder-in-r7.
(The field VM's q<2^32 / b<2^31 DIVMODW windows were pinned here until G9 slice 3b deleted that VM; zkvm2's DIVMODW is
DIVMOD over the whole 256-bit word.)
(The prove/verify cases and the args-bus soundness negatives retired in G9 with the Goldilocks exec AIR, vm_circuit.)

Run: python3 tests/test_zkvm_args.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# runs on zkvm2, the VM generation 29 runs every call on (the field VM, execnode/zkvm.py, went in G9 slice 3b)
from execnode import zkvm2 as zkvm, zkvmasm

import _harness
_report = _harness.Report()
check = _report.run

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


# ---- prove + verify, soundness negatives ----------------------------------------------------------
# prove_arg_call, prove_epoch_two_calls and the four args-bus SOUNDNESS negatives retired in G9: the exec AIR
# (execnode/stark/vm_circuit.py) and its args LogUp bus were deleted


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

def t_dmw_whole_word():
    code = zkvmasm.assemble_contract({"m": "divmodw r1 r2\nret r1"})
    ok, ret, _, _ = zkvm.run(code, "m", CALLER, [0, 100, (1 << 31) + 1], {})   # a divisor past the field VM's window
    assert ok and ret == 0, "a wide divisor divides"
    ok, _, _, _ = zkvm.run(code, "m", CALLER, [0, 100, 0], {})                 # divide by zero
    assert not ok, "divisor 0 must revert"
    ok, ret, _, _ = zkvm.run(code, "m", CALLER, [0, (1 << 200) * 3, 1 << 100], {})   # a quotient past 2^32
    assert ok and ret == 3 << 100, "a wide quotient divides"
    ok, ret, _, _ = zkvm.run(code, "m", CALLER, [0, ((1 << 32) - 1) * ((1 << 31) - 1), (1 << 31) - 1], {})
    assert ok and ret == (1 << 32) - 1

def t_dmw_rem_r7():
    code = zkvmasm.assemble_contract({"m": "divmodw r1 r2\nmov r1 r7\nret r1"})   # return remainder
    ok, ret, _, _ = zkvm.run(code, "m", CALLER, [0, 10**12 + 17, 999_999_937], {})
    assert ok and ret == (10**12 + 17) % 999_999_937
    # remw macro form
    code2 = zkvmasm.assemble_contract({"m": "remw r1 r2\nret r1"})
    ok, ret2, _, _ = zkvm.run(code2, "m", CALLER, [0, 10**12 + 17, 999_999_937], {})
    assert ok and ret2 == ret, "remw macro must equal manual form"

# dmw_proves retired in G9: the exec AIR (execnode/stark/vm_circuit.py) was deleted


if __name__ == "__main__":
    check("ARG: dynamic-index load", t_native_load)
    check("ARG: index beyond the old 8-register ABI", t_native_beyond_8)
    check("ARG: out-of-range index reverts", t_native_oob_reverts)
    check("ARG: MAX_ARGS boundary (1024 ok / 1025 refused)", t_max_args_boundary)
    check("ARG: loop-sum over 12 args", lambda: (t_loop_sum(), None)[1])
    check("DIVMODW: wide-divisor quotient", t_dmw_native)
    check("DIVMODW: parimutuel payout pattern (stake*total//pool)", t_dmw_parimutuel)
    check("DIVMODW: the whole word, only a zero divisor reverts", t_dmw_whole_word)
    check("DIVMODW: remainder in r7 + remw macro", t_dmw_rem_r7)
    print("ALL PASS" if _report.fails == 0 else f"{_report.fails} FAILURES")
    sys.exit(1 if _report.fails else 0)
