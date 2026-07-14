"""
VM2 execution AIR (execnode/stark/vm_circuit.py): a real contract call (randomness, division, storage,
conditional payout, sponge hashing, caller context) proves and verifies WITHOUT re-execution, replay_io
reaches the interpreter's exact state, and every statement tamper — forged log values/order, wrong args,
wrong caller, patched code, bad geometry — is rejected. Reverted calls are unprovable.

Run: python3 tests/test_vm2_circuit.py            (~1 min: two proofs at reduced query count,
                                                   soundness comes from the statement checks not queries)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, alghash, vm_circuit
from execnode import vm2, vm2asm

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 8                                                    # reduced FRI queries: fast tests, same machinery

# contract 1 — dice: roll from a pinned block hash, count plays, pay on a correct guess
DICE = {"play": vm2asm.assemble("""
    movi r3 50
    bhash r4 r3
    lo32 r4
    movi r5 6
    divmod r4 r5
    movi r6 1
    sload r3 r6
    movi r4 1
    add r3 r4
    sstore r6 r3
    eq r7 r0
    jnz r7 @win
    movi r0 0
    ret r0
win:
    pay r1 r2
    movi r0 1
    ret r0
""")}
BH = {50: 123456789123456789}
ROLL = (123456789123456789 & 0xFFFFFFFF) % 6
CALLER, ARGS, ST0 = 777777, [ROLL, 4242, 100], {1: 6}

# contract 2 — commit-reveal check + caller-stamped store (exercises HASH/REQUIRE/CTX)
REVEAL = {"reveal": vm2asm.assemble("""
    hash r3 <- r0 r1
    eq r3 r2
    require r3
    ctx r4 caller
    movi r5 7
    sstore r5 r4
    movi r6 1
    ret r6
""")}

_cache = {}
def _dice_proof():
    if "dice" not in _cache:
        _cache["dice"] = vm_circuit.prove_call(DICE, "play", CALLER, ARGS, ST0, cursor=60,
                                               block_hashes=BH, num_queries=NQ)
    return _cache["dice"]

def _verify(io=None, code=DICE, method="play", caller=CALLER, args=ARGS, proof=None, **kw):
    p, io0, ret, st1 = _dice_proof()
    return vm_circuit.verify_call(proof or p, code, method, caller, args, io if io is not None else io0,
                                  cursor=kw.pop("cursor", 60), num_queries=NQ, **kw)

def t1_dice_proves_and_replays():
    proof, io, ret, st1 = _dice_proof()
    assert ret == 1 and st1 == {1: 7}
    ok, why = _verify()
    assert ok, f"honest call must verify: {why}"
    ok2, ret2, st2, payouts, chain = vm2.replay_io(io, ST0)  # the verifier's application path
    assert ok2 and ret2 == 1 and st2 == st1 and payouts == [(4242, 100)]
    assert chain == [(vm2.IO_BHASH, 50, 123456789123456789 % F.P)]

def t2_forged_payout_rejected():
    _, io, _, _ = _dice_proof()
    forged = [list(e) for e in io]
    for e in forged:
        if e[0] == vm2.IO_PAY:
            e[2] = 100_000                               # pay yourself more
    ok, _ = _verify(io=[tuple(e) for e in forged])
    assert not ok, "inflated payout must be rejected"

def t3_forged_read_rejected():
    _, io, _, _ = _dice_proof()
    forged = [list(e) for e in io]
    for e in forged:
        if e[0] == vm2.IO_SLOAD:
            e[2] = 999                                   # claim different pre-state
    ok, _ = _verify(io=[tuple(e) for e in forged])
    assert not ok, "forged storage read must be rejected"

def t4_reordered_or_truncated_log_rejected():
    _, io, _, _ = _dice_proof()
    swapped = list(io); swapped[1], swapped[2] = swapped[2], swapped[1]
    ok, _ = _verify(io=swapped)
    assert not ok, "reordered log must be rejected"
    ok, _ = _verify(io=io[1:])
    assert not ok, "truncated log must be rejected"

def t5_wrong_args_rejected():
    ok, _ = _verify(args=[(ROLL + 1) % 6, 4242, 100])
    assert not ok, "different args (boundary pins) must be rejected"

def t6_patched_code_rejected():
    patched = {"play": [list(i) for i in DICE["play"]]}
    patched["play"][0][3] = 51                           # roll from a different height
    ok, _ = _verify(code=patched)
    assert not ok, "patched program (fetch table) must be rejected"

def t7_bad_geometry_rejected():
    p, io, _, _ = _dice_proof()
    bad = dict(p); bad["T"] = 1024
    ok, _ = _verify(proof=bad)
    assert not ok
    bad = dict(p); bad["W"] = vm_circuit.W_TOTAL - 1
    ok, _ = _verify(proof=bad)
    assert not ok

def t8_reveal_binds_caller_and_hash():
    secret, salt = 31337, 99
    cm = alghash.hashn([secret, salt])
    proof, io, ret, st1 = vm_circuit.prove_call(REVEAL, "reveal", CALLER, [secret, salt, cm], {},
                                                num_queries=NQ)
    assert ret == 1 and st1 == {7: CALLER}
    ok, why = vm_circuit.verify_call(proof, REVEAL, "reveal", CALLER, [secret, salt, cm], io,
                                     num_queries=NQ)
    assert ok, f"honest reveal must verify: {why}"
    ok, _ = vm_circuit.verify_call(proof, REVEAL, "reveal", 111111, [secret, salt, cm], io,
                                   num_queries=NQ)
    assert not ok, "wrong caller (CTX constant) must be rejected"

def t9_reverted_call_unprovable():
    try:
        vm_circuit.prove_call(REVEAL, "reveal", CALLER, [1, 2, 3], {}, num_queries=NQ)  # bad commitment
        raise AssertionError("reverted call must not prove")
    except ValueError:
        pass

def t10_log_shape_pinned():
    _, io, _, _ = _dice_proof()
    ok, _ = _verify(io=io + [(vm2.IO_RET, 1, 0)])        # second RET
    assert not ok
    ok, _ = _verify(io=io[:-1])                          # no RET
    assert not ok
    ok, _ = _verify(io=[])
    assert not ok


if __name__ == "__main__":
    check("dice call proves, verifies, replays to identical state", t1_dice_proves_and_replays)
    check("forged payout rejected", t2_forged_payout_rejected)
    check("forged storage read rejected", t3_forged_read_rejected)
    check("reordered/truncated log rejected", t4_reordered_or_truncated_log_rejected)
    check("wrong args rejected", t5_wrong_args_rejected)
    check("patched code rejected", t6_patched_code_rejected)
    check("bad geometry rejected", t7_bad_geometry_rejected)
    check("reveal binds caller + alghash commitment", t8_reveal_binds_caller_and_hash)
    check("reverted call unprovable", t9_reverted_call_unprovable)
    check("io log shape pinned (exactly one RET, last)", t10_log_shape_pinned)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
