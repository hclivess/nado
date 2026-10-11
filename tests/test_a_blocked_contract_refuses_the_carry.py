"""A contract the carry cannot keep because something is in flight REFUSES the carry, unless the operator passes
--allow-blockers (tools/alphanet6_carryforward.refuse_blockers).

Found 2026-10-11 (review): a blocked contract (a banked table with an open bet, a run with a leg in flight, ...) fell
back to "reset" with only a printed NOT CARRIED line, and its pot went through attribute_pot — for the digest-slot
banked games, to the deployer of record — while the tool wrote the genesis anyway. Unless someone read the printout,
players' open bets and the bankroll landed on the operator.

Pins:
  1. a dice table with an open bet puts the contract in CARRY_BLOCKERS (reset), and the carry refuses, naming it and
     the way out (settle on the old chain, or --allow-blockers);
  2. with --allow-blockers the same blockers pass (the reset and its printed attribution are accepted deliberately);
  3. with nothing blocked there is nothing to refuse;
  4. build() refuses AFTER it prints the NOT CARRIED / MANUAL REFUND attribution and BEFORE it returns anything main()
     could write.

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

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def refuses(blockers, argv):
    try:
        C.refuse_blockers(blockers, argv)
        return None
    except SystemExit as e:
        return str(e)


DICE = "d" * 32
contract = {"code": json.loads(json.dumps(dice.build())), "abi": {}, "deployer": "ndoO" + "o" * 44, "runtime": "zkvm",
            "upgradable": True,
            # a table with an open bet: index count 1, table 5 at dice.TLIST, committed liability tc != 0
            "storage": {"slots": {"0": 1, str((dice.TLIST << 32) + 0): 5, str((4 << 32) + 5): 100}}}
C.CARRY_BLOCKERS.clear()
check("setup: a table with an open bet makes the contract reset", C.carry_policy(DICE, contract) == "reset"
      and C.CARRY_BLOCKERS.get(DICE) == ["table 5 has open bets"], C.CARRY_BLOCKERS)
msg = refuses(C.CARRY_BLOCKERS, ["alphanet6_carryforward.py", "--l1-tip", "100", "--write"])
check("1. the carry refuses while a contract is blocked, naming it and the way out",
      msg is not None and DICE[:16] in msg and "table 5 has open bets" in msg and "--allow-blockers" in msg, msg)
check("2. --allow-blockers accepts the reset deliberately",
      refuses(C.CARRY_BLOCKERS, ["x", "--write", "--allow-blockers"]) is None)
check("3. with nothing blocked there is nothing to refuse", refuses({}, ["x", "--write"]) is None)

src = open(os.path.join(ROOT, "tools", "alphanet6_carryforward.py")).read()
b = src[src.index("def build():"):src.index("\ndef ", src.index("def build():") + 1)]
i_ref = b.index("refuse_blockers(CARRY_BLOCKERS, sys.argv)")
check("4. build() refuses after printing the pot attribution (NOT CARRIED, MANUAL REFUND) ...",
      b.index("NOT CARRIED") < i_ref and b.index("MANUAL REFUND") < i_ref)
check("...and before it returns the allocation main() writes", i_ref < b.index("return out"))
print("ALL PASS — a blocked contract refuses the carry" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
