"""From EXEC_BUDGET_V2_HEIGHT a reverting (or raising) exec call counts its steps against the block's execution
budget, so a block of calls that burn GAS_LIMIT and revert can no longer make every exec node execute without bound
(execnode/state.py ExecState._charge_reverted_steps; audit 2026-09-24 #13, confirmed 2026-10-18).

EXEC_BLOCK_STEP_BUDGET (F4) bounded what applied calls cost, but a revert returned before its steps were counted: the
budget only ever saw calls that succeeded. Shown under both rule sets, on the real ExecState and zkVM: one block below
the gate, any number of burn-then-revert calls leave the budget untouched and a heavy call still applies; at the gate
the same reverts fill the budget and the next heavy call is refused as "budget exhausted" (escrow refunded).

Run: python3 tests/test_reverting_calls_count_against_the_block_execution_budget.py
"""
import _harness
HOME = _harness.isolate("nado-test-budget-reverts-")
import os
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import tempfile
import protocol as P
from execnode.state import ExecState
from execnode import zkvmasm, zkvm

T = _harness.Report()
GATE = 3000
P.EXEC_BUDGET_V2_HEIGHT = GATE
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
st, cid = block(GATE - 1)
r = [call(st, cid, "burnrev", i) for i in range(REVERTS)]
T.check("below the gate the calls revert", all("revert" in x for x in r), r[:2])
T.check("...and leave the block budget untouched (the pre-gate behaviour)", st._block_steps == 0, st._block_steps)
T.check("...so a heavy call still applies after them", call(st, cid, "burn", 0).endswith("-> ok"))
st, cid = block(GATE)
bal0 = st.bridge[ALICE]
r = [call(st, cid, "burnrev", i) for i in range(REVERTS)]
T.check("at the gate the reverts are charged their executed steps", st._block_steps >= REVERTS * PER - PER, (st._block_steps, REVERTS * PER))
x = call(st, cid, "burn", 0)
T.check("...so the next heavy call is refused as budget exhausted", "budget exhausted" in x, x)
T.check("...and every reverted call's escrow came back", st.bridge[ALICE] == bal0, (st.bridge[ALICE], bal0))
st, cid = block(GATE)
st._charge_reverted_steps(None)
T.check("a RAISING call is charged the most one call may execute (GAS_LIMIT)", st._block_steps == zkvm.GAS_LIMIT, st._block_steps)
T.done("ALL PASS — reverting calls count against the block execution budget")
