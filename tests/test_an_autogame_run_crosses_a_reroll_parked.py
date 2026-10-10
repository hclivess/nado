"""An Autogame run crosses a reroll when it is parked, and marches on the new chain (autogame.carry_rebase).

A live run's next terrain is BHASH(lh) of the OLD chain. Carried raw, the new chain would not reach that height for
days, so the run could not even commit its next answers. A run whose dice are already scheduled (RNH != 0) has
answers chosen against old-chain terrain, so it cannot be re-pinned fairly: it blocks the carry until advanced.

Pins, on the REAL autogame contract (throwaway HOME):
  1. a run with a leg in flight blocks the carry, naming the run;
  2. once the leg resolves and the run parks, the contract carries (policy "keep");
  3. on the new chain the parked run commits its next answers and advances a leg from new-chain hashes (raw: it
     could not commit, the terrain height being an old-chain one);
  4. a finished run is left exactly as it was.

Run: python3 tests/test_an_autogame_run_crosses_a_reroll_parked.py
"""
import os, sys, json, tempfile, time
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-autogame-carry-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from execnode.state import ExecState
from execnode.games import autogame as G
import tools.alphanet6_carryforward as C

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A, B = "ndoA" + "a" * 44, "ndoB" + "b" * 44
_n = [0]


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": m, "args": args}
    if value:
        p["value"] = value
    return st.apply_blob(p, who, f"{m}-{_n[0]}")


def hashes(st, salt, lo, hi):
    st.block_hashes = {h: (h * 2_654_435_761 + salt) % (1 << 61) for h in range(lo, hi)}


old = ExecState(os.path.join(H, "old.json"))
old.cursor, old.block_ts = 150_000, int(time.time())
hashes(old, 3, 140_000, 160_000)
code = G.build()
old.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": G.ABI, "nonce": "n"}, A, "d")
cid = old.contract_id(A, code, "n")
rd = lambda st, f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str((f << 32) + k), 0))

call(old, cid, A, "begin", [7])
call(old, cid, B, "begin", [8])
call(old, cid, B, "retire", [8])                                  # a finished run: history
old.cursor = rd(old, G.RLH, 7)
r = call(old, cid, A, "commit", [7, 0])
check("setup: run 7 committed its answers (dice scheduled)", rd(old, G.RNH, 7) != 0, r)
why = G.carry_in_flight(old.contracts[cid]["storage"])
check("1. a run with a leg in flight blocks the carry, naming the run", why == ["run 7 has a leg in flight"], why)
C.CARRY_BLOCKERS.clear()
check("...so the contract would reset", C.carry_policy(cid, old.contracts[cid]) == "reset")

old.cursor = rd(old, G.RNH, 7) + 1
r = call(old, cid, A, "advance", [7])
check("setup: the leg resolves on the old chain and the run parks", rd(old, G.RNH, 7) == 0 and rd(old, G.RLG, 7) == 1, r)
check("2. a parked run carries", G.carry_in_flight(old.contracts[cid]["storage"]) == []
      and C.carry_policy(cid, old.contracts[cid]) == "keep")
TIP = old.cursor
gen, _ = C.exec_genesis_doc({cid: old.contracts[cid]}, {}, tip=TIP)
raw = json.loads(json.dumps(old.contracts[cid]))

def new_chain(rec):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "new.json"))
    st.contracts[cid] = json.loads(json.dumps(rec))
    st.cursor, st.block_ts = 10, int(time.time())
    hashes(st, 99, 0, 2000)
    return st

new = new_chain(gen[cid])
r1 = call(new, cid, A, "commit", [7, 0])
check("3. on the new chain the parked run commits its next answers", rd(new, G.RNH, 7) != 0, r1)
new.cursor = rd(new, G.RNH, 7) + 1
r2 = call(new, cid, A, "advance", [7])
check("...and advances a leg from the new chain's hashes", rd(new, G.RLG, 7) == 2 and rd(new, G.RNH, 7) == 0, r2)
rawst = new_chain(raw)
call(rawst, cid, A, "commit", [7, 0])
check("...where raw storage could not even commit (its terrain height is an old-chain one)", rd(rawst, G.RNH, 7) == 0)
check("4. a finished run is left exactly as it was",
      all(gen[cid]["storage"]["slots"].get(str((f << 32) + 8)) == raw["storage"]["slots"].get(str((f << 32) + 8))
          for f in range(1, 30)))

print("ALL PASS — an Autogame run crosses a reroll parked" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
