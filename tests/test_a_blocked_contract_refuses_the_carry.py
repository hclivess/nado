"""A contract the carry cannot move because something is in flight REFUSES the carry — there is no reset to fall back
to and no flag that accepts one (tools/alphanet6_carryforward.exec_genesis -> tools/carry.carry_contracts).

Found 2026-10-11 (review): a blocked contract (a banked table with an open bet, a run with a leg in flight, ...) fell
back to "reset" with only a printed NOT CARRIED line, and its pot went through attribute_pot — for the digest-slot
banked games, to the deployer of record — while the tool wrote the genesis anyway. The fix then made it a refusal with
an --allow-blockers escape. Operator rule 2026-10-20 ("everything should be carried"): the reset path and the escape
are gone; a blocked contract is settled on the old chain and the carry runs again.

Pins (the real dice contract and the real carry, throwaway HOME):
  1. a dice table with an open bet: carry_policy says "blocked" with the reason recorded;
  2. the carry REFUSES, naming the contract and the reason, whatever the command line says;
  3. once the bet is settled (tc == 0) the same contract carries WITH its storage and its pot;
  4. the builder has no reset path left: no fresh-deploy storage, no pot refund, no --allow-blockers.

Run: python3 tests/test_a_blocked_contract_refuses_the_carry.py
"""
import os, sys, json, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-blockers-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.games import dice
import tools.alphanet6_carryforward as C
from tools import carry

import _harness
_report = _harness.Report()
check = _report.check

DICE = "d" * 32
contract = {"code": json.loads(json.dumps(dice.build())), "abi": {}, "deployer": "ndoO" + "o" * 44, "runtime": "zkvm",
            "upgradable": True,
            # a table with an open bet: index count 1, table 5 at dice.TLIST, committed liability tc != 0
            "storage": {"slots": {"0": 1, str((dice.TLIST << 32) + 0): 5, str((4 << 32) + 5): 100}}}
C.CARRY_BLOCKERS.clear()
check("1. a table with an open bet: the contract is blocked, the reason recorded",
      C.carry_policy(DICE, contract) == "blocked" and C.CARRY_BLOCKERS.get(DICE) == ["table 5 has open bets"],
      C.CARRY_BLOCKERS)
try:
    C.exec_genesis_doc({DICE: contract}, {DICE: 700})
    msg = None
except carry.Refused as e:
    msg = str(e)
check("2. the carry refuses, naming the contract and why", msg is not None and DICE in msg and "table 5 has open bets" in msg,
      msg)
settled = json.loads(json.dumps(contract))
settled["storage"]["slots"][str((4 << 32) + 5)] = 0
gen, kept = C.exec_genesis_doc({DICE: settled}, {DICE: 700})
check("3. settled, the same contract carries with its storage and its pot",
      gen[DICE]["storage"]["slots"] == {k: int(v) for k, v in settled["storage"]["slots"].items()} and kept == {DICE: 700},
      (gen[DICE]["storage"], kept))
src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py")).read()
check("4. the builder has no reset path: no fresh-deploy storage, no pot refund, no --allow-blockers",
      all(x not in src for x in ("def fresh_deploy_storage", "pot_refunds_for(", "--allow-blockers", "refuse_blockers(")))
print("ALL PASS — a blocked contract refuses the carry" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
