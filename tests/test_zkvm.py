"""
zkVM (execnode/zkvm.py + zkvmasm.py): field-native semantics, the soundness windows (LT/DIVMOD/LO32) revert
exactly where the AIR would be unsatisfiable, the I/O log replays to the identical state WITHOUT execution,
and malformed code/logs are rejected.

Run: python3 tests/test_zkvm.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash
from execnode import zkvm, zkvmasm

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _run(text, args=(), storage=None, **kw):
    code = {"m": zkvmasm.assemble(text)}
    zkvm.validate_code(code)
    return zkvm.run(code, "m", kw.pop("caller", 7), list(args), storage or {}, **kw)

def t1_arithmetic():
    ok, ret, st, io = _run("movi r1 20\n add r0 r1\n movi r2 3\n mul r0 r2\n ret r0", args=[22])
    assert ok and ret == (22 + 20) * 3, (ok, ret)

def t2_hash_matches_alghash():
    ok, ret, st, io = _run("hash r2 <- r0 r1\n ret r2", args=[11, 12])
    assert ok and ret == alghash.hashn([11, 12]), "HASH macro must equal alghash.hashn"

def t3_compare_ops():
    ok, ret, *_ = _run("lt r0 r1\n ret r0", args=[5, 9])
    assert ok and ret == 1
    ok, ret, *_ = _run("lt r0 r1\n ret r0", args=[9, 5])
    assert ok and ret == 0
    ok, ret, *_ = _run("gte r0 r1\n ret r0", args=[9, 9])
    assert ok and ret == 1
    ok, ret, *_ = _run("eq r0 r1\n ret r0", args=[4, 4])
    assert ok and ret == 1
    ok, ret, *_ = _run("nez r0\n ret r0", args=[0])
    assert ok and ret == 0
    ok, *_ = _run("lt r0 r1\n ret r0", args=[F.P - 2, 5])     # outside the 63-bit window -> revert
    assert not ok, "LT beyond the window must revert"

def t4_divmod():
    ok, ret, st, io = _run("divmod r0 r1\n mov r2 r7\n ret r2", args=[1000003, 37])
    assert ok and ret == 1000003 % 37
    ok, ret, *_ = _run("divmod r0 r1\n ret r0", args=[1000003, 37])
    assert ok and ret == 1000003 // 37
    ok, *_ = _run("divmod r0 r1\n ret r0", args=[5, 0])                     # b = 0
    assert not ok
    ok, *_ = _run("divmod r0 r1\n ret r0", args=[5, 1 << 31])               # b too big
    assert not ok
    ok, *_ = _run("divmod r0 r1\n ret r0", args=[1 << 62, 3])               # q >= 2^32
    assert not ok

def t5_lo32():
    v = (0xDEADBEEF << 32) | 0xCAFEBABE
    ok, ret, *_ = _run("lo32 r0\n ret r0", args=[v])
    assert ok and ret == 0xCAFEBABE
    ok, ret, *_ = _run("lo32 r0\n ret r0", args=[F.P - 1])    # p-1 = (2^32-1)*2^32: hi tops out, lo = 0
    assert ok and ret == 0

def t6_storage_and_replay():
    src = ("movi r1 100\n sload r2 r1\n add r2 r0\n sstore r1 r2\n"
           "movi r3 777\n movi r4 5\n pay r3 r4\n ret r2")
    code = {"m": zkvmasm.assemble(src)}
    st0 = {100: 40}
    ok, ret, st1, io = zkvm.run(code, "m", 7, [2], st0)
    assert ok and ret == 42 and st1 == {100: 42}
    ok2, ret2, st2, payouts, chain = zkvm.replay_io(io, st0)   # the verifier path: NO execution
    assert ok2 and ret2 == 42 and st2 == st1 and payouts == [(777, 5)] and chain == []

def t7_replay_rejects():
    src = "movi r1 100\n sload r2 r1\n ret r2"
    code = {"m": zkvmasm.assemble(src)}
    ok, ret, st1, io = zkvm.run(code, "m", 7, [], {100: 9})
    ok2, *_ = zkvm.replay_io(io, {100: 8})                     # state moved -> read mismatch
    assert not ok2, "stale read must be rejected"
    ok3, *_ = zkvm.replay_io(io[:-1], {100: 9})                # missing RET
    assert not ok3
    ok4, *_ = zkvm.replay_io(io + [(zkvm.IO_RET, 0, 0)], {100: 9})   # trailing entry after RET
    assert not ok4

def t8_control_flow_and_gas():
    ok, ret, *_ = _run("jnz r0 @a\n movi r1 10\n jmp @end\na:\n movi r1 20\nend:\n ret r1", args=[1])
    assert ok and ret == 20
    ok, ret, *_ = _run("jnz r0 @a\n movi r1 10\n jmp @end\na:\n movi r1 20\nend:\n ret r1", args=[0])
    assert ok and ret == 10
    ok, *_ = _run("loop:\n jmp @loop")                        # infinite loop -> gas revert
    assert not ok
    ok, *_ = _run("movi r0 0\n require r0\n ret r0")          # REQUIRE 0 -> revert
    assert not ok

def t9_chain_randomness():
    ok, ret, st, io = _run("movi r1 50\n bhash r2 r1\n ret r2", block_hashes={50: 123456789})
    assert ok and ret == 123456789 and (zkvm.IO_BHASH, 50, 123456789) in io
    ok, *_ = _run("movi r1 50\n bhash r2 r1\n ret r2", block_hashes={})
    assert not ok, "missing block hash must revert"
    ok, ret, st, io = _run("movi r1 3\n beacon r2 r1\n ret r2", beacons={3: 42})
    assert ok and ret == 42

def t10_validate_code():
    for bad in ([["XX", 0, 0, 0]], [["MOVI", 9, 0, 0]], [["JMP", 0, 0, 99]], [["DIVMOD", 7, 1, 0]],
                [["MOVI", 0, 0, F.P]]):
        try:
            zkvm.validate_code({"m": bad}); raise AssertionError(f"{bad} must be rejected")
        except zkvm.ZkVMError:
            pass

def t11_witness_limbs():
    code = {"m": zkvmasm.assemble("divmod r0 r1\n ret r0")}
    ok, ret, st, io, steps = zkvm.run(code, "m", 7, [1000003, 37], {}, witness=True)
    assert ok and len(steps) == 2
    s = steps[0]
    q = sum(s["bl"][k] << (8 * k) for k in range(6))                 # 48-bit quotient
    bm1 = s["bl"][6] + (s["sl"][1] << 8)                             # b-1  (byte + 7-bit)
    rem = s["bl"][7] + (s["sl"][2] << 8)                             # rem
    assert q == 1000003 // 37 and bm1 == 36 and rem == 1000003 % 37, "witness limbs must recompose"
    assert all(0 <= b < 256 for b in s["bl"]) and all(0 <= x < 128 for x in s["sl"])


if __name__ == "__main__":
    check("arithmetic", t1_arithmetic)
    check("HASH macro == alghash.hashn", t2_hash_matches_alghash)
    check("compare ops + window revert", t3_compare_ops)
    check("DIVMOD semantics + soundness bounds", t4_divmod)
    check("LO32 canonical split", t5_lo32)
    check("storage + payout io round-trips through replay_io", t6_storage_and_replay)
    check("replay_io rejects stale read / missing RET / trailing entries", t7_replay_rejects)
    check("control flow + gas + REQUIRE", t8_control_flow_and_gas)
    check("BHASH/BEACON chain randomness", t9_chain_randomness)
    check("validate_code rejections", t10_validate_code)
    check("witness limbs recompose", t11_witness_limbs)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
