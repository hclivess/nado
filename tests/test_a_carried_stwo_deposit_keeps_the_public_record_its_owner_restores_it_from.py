"""A Stwo deposit note carried across a reroll keeps the PUBLIC record its owner restores it from, and the exec genesis
document has one reading of every amount (review 2026-10-12; tools/alphanet6_carryforward.stwo_deposit_records /
exec_shield_doc, execnode/exec_genesis.py, execnode/execnode.py h_stwo_carried_deposits).

A wallet restores a deposit note from its recovery phrase by reading its own shield transactions (amount, owner, rho) and
re-deriving the owner from its spend key and that rho. The carry kept the commitments but not those transactions, so on
the new chain a carried deposit note could not be found (tests/test_every_stwo_deposit_is_restorable_from_the_recovery_
phrase.mjs, check 4). Pins, on the real carry helpers, the real genesis loader and the real HTTP handler (throwaway HOME):
  1. stwo_deposit_records keeps (depositor, amount, owner, rho) for every Stwo deposit whose note is carried, once per
     commitment; a wide-pool deposit, a deposit the exec layer refused (no carried commitment) and a malformed one are
     not kept; a record the OLD chain's own exec genesis carried is kept again (a note carried twice);
  2. exec_shield_doc writes them as `stwo_deposits`, and the exec genesis loads them;
  3. the loader refuses a record whose commit(amount, owner, rho) is not a carried commitment, two records for one
     commitment, a record with other keys, and a float or bool amount;
  4. the loader refuses a float or bool stwo_value / pool_fees (int(1.9) == 1, int(True) == 1: one document, two
     readings), and still takes ints and decimal strings;
  5. GET /exec/stwo_carried_deposits?addr= serves exactly that depositor's records (amount and rho as strings), all of
     them without addr, and [] when the document is for another generation.
Run: python3 tests/test_a_carried_stwo_deposit_keeps_the_public_record_its_owner_restores_it_from.py
"""
import os, sys, json, tempfile, asyncio
_T = tempfile.mkdtemp(prefix="nado-test-stwo-carried-deps-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
GEN_FILE = os.path.join(_T, "exec_genesis.json")
os.environ["NADO_EXEC_GENESIS"] = GEN_FILE
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from execnode import exec_genesis as EG, shielded_stwo as SP
import tools.alphanet6_carryforward as C
import execnode.execnode as EN

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A, B = "ndo_alice_depositor", "ndo_bob_depositor"
oa, ob = SP.owner_of("a1" * 32), SP.owner_of("b2" * 32)


def dep(sender, amount, owner, rho, pool="stwo"):
    data = {"field": True, "owner": owner, "rho": str(rho), "cm": "00" * 32}
    if pool:
        data["pool"] = pool
    return {"txid": f"t{sender}{rho}", "sender": sender, "recipient": "shield", "amount": amount, "data": data}


txs = [dep(A, 5, oa, 11), dep(A, 7, oa, 12), dep(B, 9, ob, 13),
       dep(A, 3, oa, 14),                       # refused by the exec layer: its note was never made
       dep(B, 4, ob, 15, pool=None),            # a wide-pool deposit (no tag): not a Stwo note
       dep(B, 6, "XY" * 32, 16),                # malformed owner
       dict(dep(A, 5, oa, 11), txid="dup")]     # the same note twice (a re-broadcast): one record
prev = [{"addr": B, "amount": "21", "owner": ob, "rho": "99"}]          # carried by the old chain's own exec genesis
cms = [SP.commit(5, oa, 11), SP.commit(7, oa, 12), SP.commit(9, ob, 13), SP.commit(21, ob, 99), SP.commit(4, ob, 15)]
recs = C.stwo_deposit_records(txs, prev, cms)
want = sorted([{"addr": A, "amount": "5", "owner": oa, "rho": "11"}, {"addr": A, "amount": "7", "owner": oa, "rho": "12"},
               {"addr": B, "amount": "9", "owner": ob, "rho": "13"}, {"addr": B, "amount": "21", "owner": ob, "rho": "99"}],
              key=lambda x: (x["addr"], x["owner"], int(x["rho"])))
check("1. every carried Stwo deposit keeps its public record, once; refused, wide and malformed deposits do not, and a "
      "record carried by the old genesis is kept again", recs == want, recs)

snap = {"stwo_value": "42", "pool_fees": "0", "stwo_pool": {"commitments": cms, "nullifiers": []}}
sdoc = C.exec_shield_doc(snap, 42, recs)
check("2. exec_shield_doc writes them as stwo_deposits", sdoc.get("stwo_deposits") == recs, sdoc.get("stwo_deposits"))
check("...and writes none when there are none", "stwo_deposits" not in C.exec_shield_doc(snap, 42, []))


def write_gen(extra, generation=None):
    json.dump({"generation": P.CHAIN_GENERATION if generation is None else generation, "contracts": {}, "bridge": {},
               **extra}, open(GEN_FILE, "w"))
    EG._CACHE.clear()


def refused(extra):
    write_gen(extra)
    try:
        EG.load()
        return ""
    except ValueError as e:
        return str(e)


write_gen(json.loads(json.dumps(sdoc)))
check("...and the exec genesis loads them", EG.load()["stwo_deposits"] == recs, EG.load().get("stwo_deposits"))

bad = dict(recs[0], amount="6")
why = refused(dict(sdoc, stwo_deposits=[bad]))
check("3. a record that names no carried commitment is refused", "no carried commitment" in why, why)
why = refused(dict(sdoc, stwo_deposits=[recs[0], dict(recs[0])]))
check("...two records for one commitment are refused", "two carried deposit records" in why, why)
why = refused(dict(sdoc, stwo_deposits=[dict(recs[0], nsk="00" * 32)]))
check("...a record with other keys is refused (nothing but the public record is ever carried)", "must be" in why, why)
for amt in (5.0, True):
    why = refused(dict(sdoc, stwo_deposits=[dict(recs[0], amount=amt)]))
    check(f"...an amount of {amt!r} is refused", "integer or a decimal string" in why, why)

for key in ("stwo_value", "pool_fees"):
    for v in (42.0, 41.9, True):
        why = refused(dict(sdoc, **{key: v}))
        check(f"4. {key} = {v!r} is refused (one document, one reading)", "integer or a decimal string" in why, why)
write_gen(dict(sdoc, stwo_value=42, pool_fees=0))
check("...an int stwo_value / pool_fees still loads", EG.load()["stwo_value"] == 42)


def serve(addr):
    class _R:
        query = {"addr": addr} if addr else {}
    loop = asyncio.new_event_loop()
    try:
        return json.loads(loop.run_until_complete(EN.h_stwo_carried_deposits(_R())).body)["deposits"]
    finally:
        loop.close()


write_gen(json.loads(json.dumps(sdoc)))
check("5. /exec/stwo_carried_deposits?addr= serves exactly that depositor's records",
      serve(A) == [r for r in recs if r["addr"] == A] and serve(B) == [r for r in recs if r["addr"] == B], (serve(A), serve(B)))
check("...amount and rho as decimal strings (a JSON number above 2^53 rounds in a wallet)",
      all(isinstance(r["amount"], str) and isinstance(r["rho"], str) for r in serve(None)))
check("...every record without addr, none for a stranger", serve(None) == recs and serve("ndo_nobody") == [])
write_gen(json.loads(json.dumps(sdoc)), generation=P.CHAIN_GENERATION - 1)
check("...and nothing from a document for another generation", serve(A) == [] and serve(None) == [])

print("ALL PASS — a carried Stwo deposit keeps the public record its owner restores it from" if not fails
      else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
