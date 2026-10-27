"""From block 1 a reverting (or raising) exec call counts its steps against the block's execution
budget, so a block of calls that burn GAS_LIMIT and revert can no longer make every exec node execute without bound
(execnode/state.py ExecState._charge_reverted_steps; audit 2026-09-24 #13, confirmed 2026-10-18).

EXEC_BLOCK_STEP_BUDGET (F4) bounded what applied calls cost, but a revert returned before its steps were counted: the
budget only ever saw calls that succeeded. Shown on the real ExecState and zkVM: burn-then-revert calls fill the budget
and the next heavy call is refused as "budget exhausted" (escrow refunded). EXEC_BUDGET_V2_HEIGHT (gen 28's gate) was
inlined in G9; the below-the-gate half is retired in G9: generation 28's rules.

Run: python3 tests/test_reverting_calls_count_against_the_block_execution_budget.py
"""
import _harness
HOME = _harness.isolate("nado-test-budget-reverts-")
import os
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import tempfile
import protocol as P
from execnode.state import ExecState
from execnode import zkvmasm, zkvm2 as zkvm

T = _harness.Report()
GATE = 3000                                                 # any applied height from 1 (EXEC_BUDGET_V2_HEIGHT, inlined in G9)
ALICE = "mldsa44" + "a" * 42
CODE = {
    "burn": zkvmasm.assemble("movi r1 60000\n movi r2 1\n loop:\n sub r1 r2\n jnz r1 @loop\n ret r0"),
    "burnrev": zkvmasm.assemble("movi r1 60000\n movi r2 1\n loop:\n sub r1 r2\n jnz r1 @loop\n movi r3 5\n notb r3 r3\n ret r0"),
}
m = {}
zkvm.run(CODE, "burnrev", 1, [], {}, meter=m)
PER = m["gas"]
REVERTS = int(P.EXEC_BLOCK_STEP_BUDGET) // PER + 1        # enough reverting steps to exhaust the budget


def block(h):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=HOME), "s.json"))
    st.cursor = h - 1
    st.bridge[ALICE] = 10 ** 9
    st.apply_blob({"op": "deploy", "code": CODE, "nonce": 1}, ALICE, "d")
    st._block_steps = 0                                     # the block starts (execnode._apply_block does this)
    return st, next(iter(st.contracts))


def call(st, cid, method, i):
    return st.apply_blob({"op": "call", "contract": cid, "method": method, "args": [], "value": 1}, ALICE, f"{method}{i}")


T.check("setup: the burn-then-revert call executes ~60k steps and reverts", 100_000 < PER < zkvm.GAS_LIMIT, PER)
# the below-the-gate half (reverts left the budget untouched) is retired in G9: generation 28's rules
st, cid = block(GATE)
bal0 = st.bridge[ALICE]
r = [call(st, cid, "burnrev", i) for i in range(REVERTS)]
T.check("the burn-then-revert calls revert", all("revert" in x for x in r), r[:2])
T.check("the reverts are charged their executed steps", st._block_steps >= REVERTS * PER - PER, (st._block_steps, REVERTS * PER))
x = call(st, cid, "burn", 0)
T.check("...so the next heavy call is refused as budget exhausted", "budget exhausted" in x, x)
T.check("...and every reverted call's escrow came back", st.bridge[ALICE] == bal0, (st.bridge[ALICE], bal0))
st, cid = block(GATE)
st._charge_reverted_steps(None)
T.check("a RAISING call is charged the most one call may execute (GAS_LIMIT)", st._block_steps == zkvm.GAS_LIMIT, st._block_steps)
T.done("ALL PASS — reverting calls count against the block execution budget")
