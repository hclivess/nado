"""A banked game (slots, dice, roulette, mines, blackjack) crosses a reroll with its tables and bankroll once no bet is in
flight (_lib.banked_tables_in_flight, tools/alphanet6_carryforward.carry_policy).

A seat in flight refers to the OLD chain — its beacon epoch and heights — and can never settle on the new one, so a
table with open bets (committed liability tc != 0, the same test close() uses) blocks the carry and the contract falls
back to a reset with its pot refunded, exactly as before. Once every seat is settled on the old chain (settle is
permissionless) the storage is pure history plus bankroll and carries as is.

Pins, on the REAL slots contract (throwaway HOME):
  1. a spin in flight blocks the carry, naming the table;
  2. after the spin settles, the contract carries: same id, same storage, pot kept;
  3. on the new chain the banker closes the table and receives exactly the carried pot, and the settled spin can
     neither settle nor claim again;
  4. every banked game declares the check.

Run: python3 tests/test_a_banked_game_carries_once_no_bet_is_in_flight.py
"""
import os, sys, json, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-banked-carry-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["NADO_EXEC_GENESIS"] = os.path.join(H, "exec_genesis.json")
import protocol as P
from execnode.state import ExecState
from execnode import exec_genesis as EG
from execnode.games import slots, dice, roulette, mines, blackjack
import tools.alphanet6_carryforward as C

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


BANK, PLAYER = "ndoA" + "a" * 44, "ndoB" + "b" * 44
T, G, STAKE, ROLL = 5, 1000, 10_000, 5_000_000_000
_n = [0]


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    blob = {"op": "call", "contract": cid, "method": m, "args": args}
    if value is not None:
        blob["value"] = value
    return st.apply_blob(blob, who, f"{m}-{_n[0]}")


def rd(st, cid, f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))


st = ExecState(os.path.join(H, "old.json"))
st.cursor = 6000 + 17
code = slots.build()
st.bridge[BANK], st.bridge[PLAYER] = 10 ** 13, 10 ** 9
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": slots.ABI, "nonce": "n"}, BANK, "d")
cid = st.contract_id(BANK, code, "n")
call(st, cid, BANK, "open", [T], ROLL)
call(st, cid, PLAYER, "spin", [G, T], STAKE)

why = slots.carry_in_flight(st.contracts[cid]["storage"])
check("1. a spin in flight blocks the carry, naming its table", why == [f"table {T} has open bets"], why)
C.CARRY_BLOCKERS.clear()
check("...so the contract would reset (pot refunded as before)", C.carry_policy(cid, st.contracts[cid]) == "reset"
      and C.CARRY_BLOCKERS.get(cid) == why)

gb, gh = rd(st, cid, slots.GB, G), rd(st, cid, slots.GH, G)
st.beacons[gb] = (0x5EED << 200) + 7919
st.cursor = gh + 1
call(st, cid, BANK, "settle", [G])
check("the spin settled on the old chain", rd(st, cid, slots.GD, G) == 1)
check("2. with nothing in flight the contract carries", slots.carry_in_flight(st.contracts[cid]["storage"]) == []
      and C.carry_policy(cid, st.contracts[cid]) == "keep")
pot = int(st.bridge.get(cid, 0))
gen, kept = C.exec_genesis_doc({cid: st.contracts[cid]}, {cid: pot})
check("...same id, same storage, pot kept", list(gen) == [cid] and gen[cid]["storage"] == st.contracts[cid]["storage"]
      and kept == {cid: pot}, kept)
tp = rd(st, cid, slots.TP, T)
check("...and the pot is exactly the table's pot", pot == tp, (pot, tp))

json.dump({"generation": P.CHAIN_GENERATION, "contracts": gen, "bridge": {c: str(v) for c, v in kept.items()}},
          open(os.environ["NADO_EXEC_GENESIS"], "w"))
EG._CACHE.clear()
new = ExecState(os.path.join(H, "new.json"))
EG.apply(new)
new.cursor = 3                                          # a new chain: heights start again
before = int(new.bridge.get(BANK, 0))
call(new, cid, BANK, "close", [T])
check("3. on the new chain the banker closes the table and receives exactly the carried pot",
      int(new.bridge.get(BANK, 0)) - before == pot and int(new.bridge.get(cid, 0)) == 0, (int(new.bridge.get(BANK, 0)) - before, pot))
r1, r2 = call(new, cid, PLAYER, "settle", [G]), call(new, cid, PLAYER, "claim", [G])
check("...and the settled spin can neither settle nor claim again", rd(new, cid, slots.GD, G) == 1
      and int(new.bridge.get(cid, 0)) == 0, (r1, r2))

check("4. every banked game declares the in-flight check", all(hasattr(m, "carry_in_flight") for m in (slots, dice, roulette, mines, blackjack)))
print("ALL PASS — a banked game carries once no bet is in flight" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
