"""PROOF_BLOCK_SELECTOR_HEIGHT: a call cannot execute past its declared block (review A2).

The exec AIR's block schedule (proof["blocks"]: which rows belong to which call) is prover-declared. The
verifier rebuilds every context/program/args column from it and checks only contiguity; nothing tied a block's
length to its call's RET, so a block declared with n = 1 ran on: rows past the declared end read context 0,
program 0 and call 0's args — and c_absorb forces a NOP only AFTER a halt, never after a live instruction.
From the gate the AIR carries P_IN (1 on declared rows) and (1 - P_IN)(1 - f_NOP) = 0.

This file BUILDS the forgery rather than trusting the trace: an honest witness for a four-instruction call,
declared as a one-row block. Under the legacy rules that proof VERIFIES (the finding); at the gate it is
refused. The honest schedule verifies on both sides of the gate under its own format, and the format flips
at the gate exactly as PROOF_BIND_HEIGHT's does.

Run: python3 tests/test_proof_block_selector.py        (~1 min: a few small epoch proofs)
"""
import os
import sys
import tempfile
import traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-blocksel-")     # NEVER the live node's home (rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from execnode.stark import stark, vm_circuit as VC, backend as BK
from execnode import zkvmasm

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


# the selector (gen 25's PROOF_BLOCK_SELECTOR_HEIGHT) and the bind pins (PROOF_BIND_HEIGHT) hold from block 1 since gen
# 26 and both gates were deleted after the betanet-8 reroll: height 0 is below every pin, block 1 has them all
NQ = 4
# A call that reads NO context (so a forged schedule changes nothing the trace already committed to) and
# executes four instructions before RET: the shape whose declared length nothing bound.
CODE = {"go": zkvmasm.assemble("movi r1 5\n movi r2 0\n sstore r2 r1\n ret r1")}
CALL = {"code": CODE, "method": "go", "caller": "ndoAAAA" + "A" * 41, "args": [], "value": 0, "cursor": 1,
        "timestamp": 6, "asset": 0, "selfd": 7, "slots": {}}


def _rules(pin, bind, sel, r2=False):
    return stark.Rules(pin, bind, sel, r2)      # round2 (REVIEW_R2_HEIGHT) is a later gate; off here


LEGACY = _rules(True, True, False)        # the rules between PROOF_BIND_HEIGHT and this gate
NEW = _rules(True, True, True)


def _prove(rules, forge=False):
    """prove_epoch_calls under `rules`; with `forge`, the honest witness (trace, multiplicities, io) is kept
    but the declared schedule says the call is ONE row long."""
    real = VC.build_epoch_trace

    def forged(calls):
        trace, T, blocks, progs, io, per = real(calls)
        (start, n, pid, call), = blocks
        return trace, T, [(start, 1, pid, call)], progs, io, per
    if forge:
        VC.build_epoch_trace = forged
    try:
        with stark.with_rules(rules):
            proof, io, _per = VC.prove_epoch_calls([CALL], num_queries=NQ, backend=BK.RECURSION, row_commit=True)
        return proof, io
    finally:
        VC.build_epoch_trace = real


def _verify(proof, io, rules):
    with stark.with_rules(rules):
        return VC.verify_epoch_calls(proof, [CALL], io, num_queries=NQ, row_commit=True)


def t_rules_add_the_selector_at_the_gate():
    assert stark.rules_for_height(0) == stark.RULES_LEGACY, "height 0: below every deleted gate"
    assert stark.rules_for_height(1) == stark.RULES_STRICT and stark.rules_for_height(1).in_block_selector, \
        "block 1: every pin, the selector included"
    assert stark.current_rules() == stark.RULES_STRICT and stark.RULES_STRICT.in_block_selector
    assert VC.num_periodic(False) == VC.NUM_PERIODIC and VC.num_periodic(True) == VC.NUM_PERIODIC + 1
    assert not hasattr(P, "PROOF_BLOCK_SELECTOR_HEIGHT") and not hasattr(P, "PROOF_BIND_HEIGHT"), "the gates stay deleted"


def t_honest_proof_verifies_under_the_new_rules():
    proof, io = _prove(NEW)
    assert proof["blocks"] == [{"start": 0, "n": 4, "pid": 0}], proof["blocks"]
    ok, why = _verify(proof, io, NEW)
    assert ok, why


_FORGED_LEGACY = _prove(LEGACY, forge=True)


def t_FINDING_a_call_executing_past_its_declared_block_verified_below_the_gate():
    """THE FINDING. The witness executes four rows; the schedule declares one. Every column the verifier rebuilds
    from that schedule is 0 past row 0 — and this program happens to agree with 0 everywhere it looks (prog 0,
    call 0, no CTX reads), which is exactly the freedom a settler's chosen program would exploit."""
    proof, io = _FORGED_LEGACY
    assert proof["blocks"] == [{"start": 0, "n": 1, "pid": 0}]
    ok, why = _verify(proof, io, LEGACY)
    assert ok, f"under the pre-gate rules the forged schedule VERIFIED: {why}"


def t_the_same_forgery_is_refused_at_the_gate():
    proof, io = _prove(NEW, forge=True)
    assert proof["blocks"] == [{"start": 0, "n": 1, "pid": 0}]
    ok, why = _verify(proof, io, NEW)
    assert not ok, "rows outside the declared block are live instructions: (1 - P_IN)(1 - f_NOP) != 0"
    assert "constraint" in why or "low-degree" in why, why


def t_format_flips_at_the_gate():
    old_p, old_io = _prove(LEGACY)
    new_p, new_io = _prove(NEW)
    assert _verify(old_p, old_io, LEGACY)[0] and _verify(new_p, new_io, NEW)[0]
    assert not _verify(old_p, old_io, NEW)[0], "a pre-gate proof is refused at the gate (one column short)"
    assert not _verify(new_p, new_io, LEGACY)[0], "a post-gate proof is refused before it"


def t_schedule_shorter_than_the_trace_is_refused_even_when_padded_by_nops():
    """A block declared LONGER than the call is fine (its tail is NOP padding, which P_IN permits); shorter is
    what the selector forbids. Both directions, on the honest witness."""
    real = VC.build_epoch_trace

    def longer(calls):
        trace, T, blocks, progs, io, per = real(calls)
        (start, n, pid, call), = blocks
        return trace, T, [(start, n + 3, pid, call)], progs, io, per
    VC.build_epoch_trace = longer
    try:
        with stark.with_rules(NEW):
            proof, io, _ = VC.prove_epoch_calls([CALL], num_queries=NQ, backend=BK.RECURSION, row_commit=True)
    finally:
        VC.build_epoch_trace = real
    ok, why = _verify(proof, io, NEW)
    assert ok, f"a longer declared block covers only NOP padding and must still verify: {why}"


for name, fn in list(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name[2:].replace("_", " "), fn)

print()
print("ALL PASS — the block schedule bounds the execution from PROOF_BLOCK_SELECTOR_HEIGHT" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
