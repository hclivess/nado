"""The gen-29 carry re-derives every gen-28 encoding it can explain, and REFUSES — never guesses, never resets — what it
cannot (tools/carry.py, doc/stwo/g5-carry.md). Operator rule 2026-10-20: everything is carried, losslessly; so a slot the
carry cannot account for is a refusal that names it, not a slot silently kept in a format the new VM will never read.

Pins, on the real game modules (throwaway HOME):
  1. a faucet paid-marker H(idx, day, rank) is re-derived to zkvm2.hash_words over the same preimage (a dropped or
     stale marker would let that placement be paid twice), and the operator's donation tally is kept verbatim;
  2. a marker outside the enumerated domain REFUSES the carry, naming the slot;
  3. autogame's OWNRUN cell ((51 * 2^32 + owner digest) mod P) is re-keyed over the owner's new digest, and a committed
     answer word (CARRY_WORDS) is kept verbatim;
  4. a value >= 2^32 that is no registry digest and not declared in CARRY_WORDS REFUSES (an unregistered owner, or a
     hash-derived value nobody checked);
  5. a registry entry that is not its own string's gen-28 digest REFUSES (the carry re-derives the registry, it never
     trusts it);
  6. a contract whose code is no module's gen-28 build REFUSES, and a module with no carry rule refuses only when it
     holds storage — an empty one carries;
  7. an asset id is recomputed from its (issuer, seed) under the new hash — the records, balances and allowances
     re-keyed, and a contract slot holding the id remapped with them; a record that is not its id's preimage refuses;
  8. the same-ISA carry (every carry after gen 29) re-encodes nothing.

Run: python3 tests/test_the_carry_rederives_what_it_can_and_refuses_what_it_cannot.py
"""
import _harness
HOME = _harness.isolate("nado-test-carry-refuses-")
import json

from execnode import zkvm2
from execnode.runtimes import zkvm_addr_digest
from execnode.state import asset_id
from execnode.games import faucet, autogame, dice, coinflip
from tools import carry

T = _harness.Report()
P = carry.P
OWNER = "ndoOWNER"
reg = {str(zkvm_addr_digest(OWNER, False)): OWNER}
dmap, newreg = carry.digest_map(reg)
d_old, d_new = zkvm_addr_digest(OWNER, False), zkvm_addr_digest(OWNER, True)
H1 = carry.V1Hash()


def refuses(fn):
    try:
        fn()
        return None
    except carry.Refused as e:
        return str(e)


# 1-2. the faucet's markers
mk = H1((9, 20728, 1))
st = {"slots": {str(faucet.DONATED): 963750000000, str(mk): 1}}
out, n = carry.reencode_storage(faucet, st, dmap, H1)
T.check("1. a faucet marker is re-derived under the new hash; the donation tally is kept",
        out["slots"] == {str(faucet.DONATED): 963750000000, str(zkvm2.hash_words([9, 20728, 1])): 1}
        and n["key_rehashed"] == 1 and n["value_kept_word"] == 1, (out, n))
stray = H1((40, 20728, 1))
msg = refuses(lambda: carry.reencode_storage(faucet, {"slots": {str(stray): 1}}, dmap, H1))
T.check("2. a marker outside the enumerated domain refuses, naming the slot", msg is not None and str(stray) in msg, msg)

# 3. autogame: an owner-keyed cell and a committed answer word
rid = 251596310
word = 2199828578304
st = {"slots": {"0": 1, str((autogame.RLIST << 32) + 0): rid, str(((autogame.OWNRUN << 32) + d_old) % P): rid,
                str((autogame.RCW << 32) + rid): word}}
out, n = carry.reencode_storage(autogame, st, dmap, H1)
T.check("3. OWNRUN is re-keyed over the owner's new digest; the answer word is kept",
        out["slots"].get(str(((autogame.OWNRUN << 32) + d_new) % (1 << 256))) == rid
        and out["slots"].get(str((autogame.RCW << 32) + rid)) == word and n["key_owner"] == 1, (out, n))

# 4. an undeclared large value
msg = refuses(lambda: carry.reencode_storage(dice, {"slots": {str((dice.GG << 32) + 1): 1 << 40}}, dmap, H1))
T.check("4. an undeclared value >= 2^32 refuses", msg is not None and "CARRY_WORDS" in msg, msg)
out, _ = carry.reencode_storage(dice, {"slots": {str((dice.GA << 32) + 1): d_old}}, dmap, H1)
T.check("4. ...while an owner digest stored as a value is remapped", out["slots"] == {str((dice.GA << 32) + 1): d_new}, out)

# 5. a registry the carry cannot re-derive
msg = refuses(lambda: carry.digest_map({str(d_old + 1): OWNER}))
T.check("5. a registry entry that is not its string's digest refuses", msg is not None and OWNER in msg, msg)
T.check("5. ...and the honest registry is re-keyed by the new digest", newreg == {str(d_new): OWNER} and dmap == {d_old: d_new})

# 6. code and carry rules
msg = refuses(lambda: carry.carry_contract("x" * 32, {"code": {"m": [["RET", 0, 0, 0]]}, "storage": {}}, dmap, 0))
T.check("6. a contract whose code is no module's gen-28 build refuses", msg is not None and "no game module" in msg, msg)
cf = {"code": json.loads(json.dumps(coinflip.build("v1"))), "abi": coinflip.ABI, "deployer": OWNER, "runtime": "zkvm",
      "storage": {"slots": {"0": 1}}}
msg = refuses(lambda: carry.carry_contract("c" * 32, cf, dmap, 0))
T.check("6. a module with no carry rule refuses when it holds storage", msg is not None and "no carry rule" in msg, msg)
rec, _ = carry.carry_contract("c" * 32, dict(cf, storage={}), dmap, 0)
T.check("6. ...and carries when it holds none, as its v2 build",
        rec["code"] == json.loads(json.dumps(coinflip.build("v2"))) and rec["storage"].get("slots", {}) == {}, rec.get("storage"))

# 7. assets
old_aid, new_aid = asset_id(OWNER, 3, False), asset_id(OWNER, 3, True)
assets = {str(old_aid): {"issuer": OWNER, "seed": 3, "sym": "TOK"}}
amap = carry.asset_map(assets)
a2, b2, l2 = carry.carry_assets(assets, {str(old_aid): {OWNER: 5}}, {str(old_aid): {OWNER: {"x": 1}}}, amap)
T.check("7. an asset id is recomputed from (issuer, seed); records, balances and allowances re-keyed",
        amap == {old_aid: new_aid} and list(a2) == list(b2) == list(l2) == [str(new_aid)] and b2[str(new_aid)] == {OWNER: 5})
out, _ = carry.reencode_storage(dice, {"slots": {str((dice.GG << 32) + 2): old_aid}}, dmap, H1, amap)
T.check("7. ...and a contract slot holding the id is remapped with it", out["slots"] == {str((dice.GG << 32) + 2): new_aid}, out)
msg = refuses(lambda: carry.asset_map({str(old_aid + 1): {"issuer": OWNER, "seed": 3}}))
T.check("7. a record that is not its id's preimage refuses", msg is not None, msg)

# 8. the same-ISA carry
idm, idreg = carry.digest_map(reg, "v1", "v1")
fc = {"code": json.loads(json.dumps(faucet.build("v1"))), "abi": faucet.ABI, "deployer": OWNER, "runtime": "zkvm",
      "storage": {"slots": {str(faucet.DONATED): "7", str(mk): "1"}}}
rec, n = carry.carry_contract("faucet", fc, idm, 0, src="v1", dst="v1")
T.check("8. the same-ISA carry re-encodes nothing (ints, same keys, same code)",
        idm == {d_old: d_old} and idreg == reg and rec["storage"]["slots"] == {str(faucet.DONATED): 7, str(mk): 1}
        and rec["code"] == fc["code"] and n["key_rehashed"] == n["value_remapped"] == 0, (rec["storage"], n))
T.done("ALL PASS — the carry re-derives what it can and refuses what it cannot")
