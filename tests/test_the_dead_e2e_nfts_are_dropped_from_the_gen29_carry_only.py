"""The two e2e NFTs stuck in the deleted test wallet are left out of the gen-29 -> 30 carry, and nothing else is
(tools/carry.DEAD_E2E_ASSETS, operator decision 2026-11-04: "exclude those tests from reroll ... just this once").

Pins:
  0. CLEANUP TRIPWIRE: the exception exists only while CHAIN_GENERATION == 29. The reroll commit bumps the generation,
     this fails, and the constant, drop_dead_e2e_assets and their two calls are deleted in that same commit (operator:
     "make sure to clean up this rule after reroll", "we dont want any dead code anywhere"). Then delete this test too.
  1. at generation 29 both records and their holdings are dropped; every other asset (the third e2e NFT, bought by a
     real account, included) carries unchanged;
  2. at any other generation nothing is dropped;
  3. if either has moved out of the dead wallet, or gained an allowance, the carry REFUSES instead of dropping it;
  4. the real carry builder (exec_assets_doc) and the dry run (carry.main) both apply it.

Run: python3 tests/test_the_dead_e2e_nfts_are_dropped_from_the_gen29_carry_only.py
"""
import _harness
HOME = _harness.isolate("nado-test-dead-e2e-")
import inspect

from protocol import CHAIN_GENERATION
from tools import carry
from tools import alphanet6_carryforward as C

fails = 0


def check(name, good, detail=""):
    global fails
    print(("PASS  " if good else "FAIL  ") + name + ("" if good else f": {detail}"))
    fails += 0 if good else 1


if CHAIN_GENERATION != 29:
    check("the one-time e2e drop is deleted once the gen-29 reroll is done", not hasattr(carry, "DEAD_E2E_ASSETS"),
          f"CHAIN_GENERATION is {CHAIN_GENERATION}: delete DEAD_E2E_HOLDER, DEAD_E2E_ASSETS, drop_dead_e2e_assets, their "
          "calls in tools/carry.main and tools/alphanet6_carryforward.exec_assets_doc, this test, and its "
          "SCHEDULED_CLEANUPS.md entry")
    raise SystemExit(1 if fails else 0)

D1, D2 = carry.DEAD_E2E_ASSETS
DEAD = carry.DEAD_E2E_HOLDER
REAL = "14348275803089253232631290249893876937652749846956764330161337850638398891927"   # the e2e NFT a real account bought
BUYER = "6c29de76c487be78f3af402f892fe80c0eb7d9a9d92093f1ac"
rec = lambda: {"dec": 0, "issuer": "8989bff323ebf069dd441fb6b858226e4b9e64ecfae1fd2d24", "mintable": False,
               "name": "NADO e2e #1", "seed": 1, "supply": 1, "sym": "NFT", "uri": "ipfs://x"}
assets = {D1: rec(), D2: rec(), REAL: rec()}
abal = {D1: {DEAD: 1}, D2: {DEAD: 1}, REAL: {BUYER: 1}}

a, b, l = carry.drop_dead_e2e_assets(assets, abal, {}, 29)
check("at gen 29 both dead-wallet NFTs are dropped, records and holdings", D1 not in a and D2 not in a
      and D1 not in b and D2 not in b, sorted(a))
check("the e2e NFT a real account bought carries", a.get(REAL) == assets[REAL] and b.get(REAL) == {BUYER: 1})
check("the inputs are not mutated", D1 in assets and D1 in abal)

a, b, l = carry.drop_dead_e2e_assets(assets, abal, {}, 30)
check("at any other generation nothing is dropped", a == assets and b == abal)


def refuses(f):
    try:
        f()
    except carry.Refused as e:
        return str(e)
    return ""


moved = dict(abal, **{D1: {BUYER: 1}})
check("one that left the dead wallet refuses (it carries; it is not dropped)",
      "no longer only in the dead test wallet" in refuses(lambda: carry.drop_dead_e2e_assets(assets, moved, {}, 29)))
check("one with an allowance refuses", "no longer" in refuses(
    lambda: carry.drop_dead_e2e_assets(assets, abal, {D2: {DEAD: {"x": 1}}}, 29)))
check("absent ones are a no-op", carry.drop_dead_e2e_assets({REAL: rec()}, {REAL: {BUYER: 1}}, {}, 29)[0] == {REAL: rec()})

doc = C.exec_assets_doc({"assets": assets, "abal": abal, "allow": {}})
check("the carry builder (exec_assets_doc) applies it", D1 not in doc["assets"] and D2 not in doc["abal"]
      and doc["abal"].get(REAL) == {BUYER: "1"}, sorted(doc["assets"]))
check("the dry run (carry.main) applies it", "drop_dead_e2e_assets(" in inspect.getsource(carry.main))

print("ALL PASS — the dead e2e NFTs leave the gen-29 carry, nothing else does" if not fails else f"{fails} FAILED")
raise SystemExit(1 if fails else 0)
