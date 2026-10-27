"""One sender gets at most EXEC_SENDER_STEP_SHARE (a quarter) of a block's execution budget, so a sender that grinds its
txids to the front of a block cannot burn the budget every later call needs (execnode/state.py; gen 28's settlement
prover mirrored it in settlement_proofs.prove_epoch, deleted in G9; audit 2026-09-24 #18, operator 2026-10-18 "Per-sender share").

Shown under both rule sets on the real ExecState and zkVM: one block below EXEC_BUDGET_V2_HEIGHT a single sender's heavy
calls run until the whole block budget is gone; at the gate the same sender is stopped at its share (its call reverted,
escrow refunded) while another sender's call in the same block still applies; a sender's REVERTED steps count toward its
share too.

Run: python3 tests/test_one_sender_gets_at_most_a_quarter_of_a_blocks_execution_budget.py
"""
import _harness
HOME = _harness.isolate("nado-test-budget-share-")
import os
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import tempfile
import protocol as P
from execnode.state import ExecState
from execnode import zkvmasm, zkvm

T = _harness.Report()
GATE = 3000
P.EXEC_BUDGET_V2_HEIGHT = GATE
A, B = "mldsa44" + "a" * 42, "mldsa44" + "b" * 42
CODE = {"burn": zkvmasm.assemble("movi r1 60000\n movi r2 1\n loop:\n sub r1 r2\n jnz r1 @loop\n ret r0"),
        "burnrev": zkvmasm.assemble("movi r1 60000\n movi r2 1\n loop:\n sub r1 r2\n jnz r1 @loop\n movi r3 5\n notb r3 r3\n ret r0")}
m = {}
zkvm.run(CODE, "burn", 1, [], {}, meter=m)
PER = m["gas"]
FITS_SHARE = int(P.EXEC_SENDER_STEP_SHARE) // PER


def block(h):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=HOME), "s.json")); st.cursor = h - 1
    st.bridge[A] = st.bridge[B] = 10 ** 9
    st.apply_blob({"op": "deploy", "code": CODE, "nonce": 1}, A, "d")
    st._block_steps, st._block_steps_by = 0, {}
    return st, next(iter(st.contracts))


def call(st, cid, who, method, i):
    return st.apply_blob({"op": "call", "contract": cid, "method": method, "args": [], "value": 1}, who, f"{who[-1]}{method}{i}")


st, cid = block(GATE - 1)
r = [call(st, cid, A, "burn", i) for i in range(FITS_SHARE + 2)]
T.check("below the gate one sender's heavy calls run past a quarter of the block (the pre-gate behaviour)",
        all(x.endswith("-> ok") for x in r), [x[-40:] for x in r if not x.endswith("-> ok")][:1])
st, cid = block(GATE)
r = [call(st, cid, A, "burn", i) for i in range(FITS_SHARE)]
T.check(f"at the gate a sender runs its share ({FITS_SHARE} heavy calls)", all(x.endswith("-> ok") for x in r))
a0 = st.bridge[A]
x = call(st, cid, A, "burn", 99)
T.check("...its next call is refused as over its share, escrow refunded", "sender's share" in x and st.bridge[A] == a0, x)
y = call(st, cid, B, "burn", 0)
T.check("...while another sender's call in the same block still applies", y.endswith("-> ok"), y)
st, cid = block(GATE)
for i in range(FITS_SHARE):
    call(st, cid, A, "burnrev", i)                     # reverting calls
x = call(st, cid, A, "burn", 0)
T.check("a sender's REVERTED steps count toward its share too", "sender's share" in x, x)
# 'the prover refuses what the chain refused' case retired in G9: the Goldilocks settlement prover (settlement_proofs.prove_epoch) was deleted
T.done("ALL PASS — one sender gets at most a quarter of a block's execution budget")
