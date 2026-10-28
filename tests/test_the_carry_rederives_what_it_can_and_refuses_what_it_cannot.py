"""The carry re-derives everything it can recompute and REFUSES — never guesses, never resets — what does not check out
(tools/carry.py, doc/stwo/g5-carry.md). Operator rule 2026-10-20: everything is carried, losslessly; so state the carry
cannot account for is a refusal that names it.

From generation 29 on every generation runs one VM, one hash and one address digest, so the carry re-encodes nothing.
(The gen-28 -> gen-29 halves of this test — hash keys re-derived under the new hash, owner-keyed fields re-keyed, the
CARRY_WORDS rule for large values, asset ids remapped — were retired in G9 slice 3b with the field VM and the v1 -> v2
path they exercised. The game-level v2 -> v2 refusals are pinned by the tests/test_*cross*_a_reroll* and
test_a_carried_contract_plays_exactly_as_it_would_have_without_the_carry.py tests.)

Pins, on the real game modules (throwaway HOME):
  1. a registry entry that is not its own string's digest REFUSES (the carry re-derives the registry, it never trusts
     it), and an honest registry carries as it is;
  2. a contract whose code is no module's build REFUSES, and a module with no carry rule refuses only when it holds
     storage — an empty one carries, as its build;
  3. an asset record that is not its own id's preimage REFUSES, a balance of an asset with no record REFUSES, and honest
     records, balances and allowances carry under their own ids;
  4. a contract at rest carries with every slot an int, the same keys and the same code — nothing re-encoded.

Run: python3 tests/test_the_carry_rederives_what_it_can_and_refuses_what_it_cannot.py
"""
import _harness
HOME = _harness.isolate("nado-test-carry-refuses-")
import json

from execnode.runtimes import zkvm_addr_digest
from execnode.state import asset_id
from execnode.games import faucet, coinflip
from tools import carry

T = _harness.Report()
OWNER = "ndoOWNER"
D = zkvm_addr_digest(OWNER)
reg = {str(D): OWNER}


def refuses(fn):
    try:
        fn()
        return None
    except carry.Refused as e:
        return str(e)


# 1. the registry
msg = refuses(lambda: carry.digest_map({str(D + 1): OWNER}))
T.check("1. a registry entry that is not its string's digest refuses", msg is not None and OWNER in msg, msg)
dmap, newreg = carry.digest_map(reg)
T.check("1. ...and the honest registry carries as it is", newreg == reg and dmap == {D: D}, (dmap, newreg))

# 2. code and carry rules
msg = refuses(lambda: carry.carry_contract("x" * 32, {"code": {"m": [["RET", 0, 0, 0]]}, "storage": {}}, 0))
T.check("2. a contract whose code is no module's build refuses", msg is not None and "no game module" in msg, msg)
cf = {"code": json.loads(json.dumps(coinflip.build())), "abi": coinflip.ABI, "deployer": OWNER, "runtime": "zkvm",
      "storage": {"slots": {"0": 1}}}
# coinflip has its carry hooks (G5 2c); with them hidden it stands for any module that declares no rule, so this
# property does not depend on which modules still lack one
_hooks = {a: getattr(coinflip, a) for a in ("carry_in_flight", "carry_rebase", "CARRY_STORAGE") if hasattr(coinflip, a)}
for a in _hooks:
    delattr(coinflip, a)
try:
    msg = refuses(lambda: carry.carry_contract("c" * 32, cf, 0))
    T.check("2. a module with no carry rule refuses when it holds storage", msg is not None and "no carry rule" in msg, msg)
    rec, _ = carry.carry_contract("c" * 32, dict(cf, storage={}), 0)
finally:
    for a, v in _hooks.items():
        setattr(coinflip, a, v)
T.check("2. ...and carries when it holds none, as its build",
        rec["code"] == json.loads(json.dumps(coinflip.build())) and rec["storage"].get("slots", {}) == {}, rec.get("storage"))

# 3. assets
aid = asset_id(OWNER, 3)
assets = {str(aid): {"issuer": OWNER, "seed": 3, "sym": "TOK"}}
amap = carry.asset_map(assets)
a2, b2, l2 = carry.carry_assets(assets, {str(aid): {OWNER: 5}}, {str(aid): {OWNER: {"x": 1}}}, amap)
T.check("3. honest asset records, balances and allowances carry under their own ids",
        amap == {aid: aid} and list(a2) == list(b2) == list(l2) == [str(aid)] and b2[str(aid)] == {OWNER: 5}
        and a2 == assets)
msg = refuses(lambda: carry.asset_map({str(aid + 1): {"issuer": OWNER, "seed": 3}}))
T.check("3. a record that is not its id's preimage refuses", msg is not None, msg)
msg = refuses(lambda: carry.carry_assets(assets, {str(aid + 7): {OWNER: 5}}, {}, amap))
T.check("3. a balance of an asset with no record refuses", msg is not None and str(aid + 7) in msg, msg)

# 4. a contract at rest
fc = {"code": json.loads(json.dumps(faucet.build())), "abi": faucet.ABI, "deployer": OWNER, "runtime": "zkvm",
      "storage": {"slots": {str(faucet.DONATED): "7", str(1 << 200): "1"}}}
rec, n = carry.carry_contract("faucet", fc, 0)
T.check("4. a contract at rest carries unchanged: int slots, same keys, same code, same abi and owner",
        rec["storage"]["slots"] == {str(faucet.DONATED): 7, str(1 << 200): 1} and rec["code"] == fc["code"]
        and rec["abi"] == fc["abi"] and rec["deployer"] == OWNER and n == {"slots": 2, "module": "faucet"},
        (rec["storage"], n))
out, reg2, counts = carry.carry_contracts({"faucet": fc}, reg, 0)
T.check("4. ...and carry_contracts returns it with the checked registry", out["faucet"] == rec and reg2 == reg)
T.done("ALL PASS — the carry re-derives what it can and refuses what it cannot")
