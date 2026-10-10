"""Hamster races, PvP boards and bet markets cross a reroll once nothing is in flight (their carry hooks).

  * hamster: a race neither settled nor voided rides old-chain block hashes and holds stakes — it blocks the carry;
    a settled race is at rest (claim reads only stakes and the result) and still pays on the new chain;
  * tictactoe (the PvP skeleton connect4/reversi/chess share): an open game races an old-chain deadline — it blocks
    the carry; a cancelled one is history;
  * the shared daily board: an unresolved day anchor re-pins to a new-chain block and resolves there;
  * bet: markets are TIME-based (wall-clock lock and deadline), so they carry as is — a bettor bets again on the new
    chain, the resolver resolves, and the winner claims the whole pot.

Run: python3 tests/test_races_boards_and_markets_cross_a_reroll_at_rest.py
"""
import os, sys, json, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-boards-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState
from execnode.games import hamster as HM, tictactoe as TT, bet as BT, _lib
import tools.alphanet6_carryforward as C

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A, B, R1 = "ndoA" + "a" * 44, "ndoB" + "b" * 44, "ndoR" + "r" * 44
_n = [0]
NOW = int(time.time())


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": m, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, who, f"{m}-{_n[0]}")


def deploy(st, mod):
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": "n"}, A, "d" + mod.__name__)
    return st.contract_id(A, code, "n")


def onto_new_chain(st, cid, tip):
    gen, kept = C.exec_genesis_doc({cid: st.contracts[cid]}, {cid: int(st.bridge.get(cid, 0))}, tip=tip)
    new = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "new.json"))
    new.contracts[cid] = json.loads(json.dumps(gen[cid]))
    if kept.get(cid):
        new.bridge[cid] = kept[cid]
    new.cursor, new.block_ts = 10, NOW
    new.block_hashes = {h: h * 7_000_003 + 5 for h in range(0, 5000)}
    for w in (A, B, R1):
        new.bridge[w] = 10 ** 12
    return new


rd = lambda st, cid, f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str((f << 32) + k), 0))


def old_chain():
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "old.json"))
    st.cursor, st.block_ts = 150_000, NOW
    st.block_hashes = {h: h * 1_000_003 + 9 for h in range(140_000, 160_000)}
    for w in (A, B, R1):
        st.bridge[w] = 10 ** 12
    return st


# ---- hamster ----------------------------------------------------------------------------------------------------
st = old_chain()
hc = deploy(st, HM)
U = HM.UNIT if hasattr(HM, "UNIT") else 10_000
call(st, hc, A, "open", [5])
st.cursor = rd(st, hc, HM.GH, 5)
call(st, hc, A, "bet", [5, 0], 5 * U)
call(st, hc, B, "bet", [5, 3], 4 * U)
why = HM.carry_in_flight(st.contracts[hc]["storage"])
check("hamster: an unsettled race blocks the carry, naming it", why == ["race 5 is not settled"], why)
st.cursor = rd(st, hc, HM.FH, 5)
r = call(st, hc, A, "settle", [5])
check("hamster: once settled the race is at rest and the contract carries",
      rd(st, hc, HM.SD, 5) == 1 and HM.carry_in_flight(st.contracts[hc]["storage"]) == []
      and C.carry_policy(hc, st.contracts[hc]) == "keep", r)
winner = rd(st, hc, HM.WN, 5) - 1
wallet = A if winner == 0 else B
pot = int(st.bridge.get(hc, 0))
new = onto_new_chain(st, hc, st.cursor)
b0 = int(new.bridge.get(wallet, 0))
r = call(new, hc, wallet, "claim", [5])
check("hamster: the winner of a settled race claims the whole pot on the new chain",
      int(new.bridge.get(wallet, 0)) - b0 == pot and pot == 9 * U, (r, int(new.bridge.get(wallet, 0)) - b0, pot))

# ---- tictactoe + the shared daily board ---------------------------------------------------------------------------
st = old_chain()
tc = deploy(st, TT)
call(st, tc, A, "open", [9], 10 ** 6)
check("tictactoe: an open game blocks the carry", TT.carry_in_flight(st.contracts[tc]["storage"]) == ["game 9 is open"])
call(st, tc, A, "cancel", [9])
DAY = NOW // 86400
call(st, tc, A, "anchor", [DAY])
pin = rd(st, tc, TT.A_H, DAY)
check("tictactoe: cancelled, the contract carries; the day's anchor is pinned on the old chain and unresolved",
      TT.carry_in_flight(st.contracts[tc]["storage"]) == [] and pin > 100_000 and rd(st, tc, TT.A_V, DAY) == 0, pin)
new = onto_new_chain(st, tc, st.cursor)
pin2 = rd(new, tc, TT.A_H, DAY)
check("daily board: the unresolved anchor re-pins to a new-chain block", _lib.CARRY_PIN_FLOOR <= pin2 < 100, pin2)
new.cursor = pin2 + 1
call(new, tc, A, "anchor", [DAY])
from execnode.stark import field as _F
check("...and resolves from the new chain's own block hash at that pin",
      rd(new, tc, TT.A_V, DAY) == new.block_hashes[pin2] % _F.P, (rd(new, tc, TT.A_V, DAY), new.block_hashes[pin2] % _F.P))

# ---- bet: TIME-based markets carry as is --------------------------------------------------------------------------
st = old_chain()
bc = deploy(st, BT)
lock = NOW + 3600
call(st, bc, A, "create_market", [3, 2, lock, lock + 7200, 1, 1, 1, 1, R1, 0, 0])
call(st, bc, A, "bet", [3, 1], 5 * BT.UNIT)
check("bet: carry-safe by declaration", C.carry_policy(bc, st.contracts[bc]) == "keep")
new = onto_new_chain(st, bc, st.cursor)
r1 = call(new, bc, B, "bet", [3, 0], 3 * BT.UNIT)
new.block_ts = lock + 1
r2 = call(new, bc, R1, "resolve", [3, 1])
a0 = int(new.bridge.get(A, 0))
r3 = call(new, bc, A, "claim", [3])
check("bet: on the new chain a market takes bets, resolves and pays the winner the whole pot",
      int(new.bridge.get(A, 0)) - a0 == 8 * BT.UNIT, (r1, r2, r3, int(new.bridge.get(A, 0)) - a0))

print("ALL PASS — races, boards and markets cross a reroll at rest" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
