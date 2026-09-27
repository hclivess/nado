"""Carried identities earn the dividend, at their carried fidelity (protocol.DIVIDEND_CARRY_EPOCH; ops/dividend_ops).

OUR BUG (reroll commit 302215f2, betanet-8). The carry leased every carried identity with a recert at epoch 0 — the
marker the dividend rule uses to exclude never-attested genesis seeds — so every carried identity was present,
produced, and earned NO dividend until it re-registered (measured 2026-09-27: all 23 carried identities that had not
re-registered were missing from every committed weight set). And the replay behind the committed weights rebuilt
fidelity from gen-27 recerts only, so a carried veteran who renewed weighed like a newcomer.

Pins, on the real tables (throwaway HOME) with a scripted carry:
  1. a genesis SEED (epoch-0 recert, not in the carry) earns nothing, before and after the gate;
  2. a CARRIED identity (epoch-0 recert, named present by the carry) earns nothing before the gate — committed epochs
     stay as they were — and earns from the gate, weighted by its carried fidelity;
  3. a carried identity that renewed replays to the SAME fidelity the live apply computed (continuing from the carried
     value), not to a newcomer's;
  4. a fresh identity is unaffected.

Run: python3 tests/test_dividend_carried_identities.py
"""
import json, os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-divcarry-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
os.makedirs(os.path.join(os.environ["HOME"], "nado", "private"), exist_ok=True)
SEED, CARRIED, VETERAN, FRESH = "5" * 46, "6" * 46, "7" * 46, "8" * 46
carry_file = os.path.join(os.environ["HOME"], "carry.json")
json.dump({"generation": P.CHAIN_GENERATION, "present": [CARRIED, VETERAN]}, open(carry_file, "w"))
os.environ["NADO_GENESIS_CARRY"] = carry_file
json.dump([{"address": CARRIED, "fidelity": 15, "balance": 0}, {"address": VETERAN, "fidelity": 12, "balance": 0}],
          open(os.path.join(os.environ["HOME"], "nado", "private", "genesis_alloc.dat"), "w"))
from ops import kv_ops
kv_ops.close_all(); kv_ops.init_env()
from ops import dividend_ops as D
D._CARRIED[0] = None

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


G = P.DIVIDEND_CARRY_EPOCH
check("the gate is a real epoch on this generation, and 0 on the next", G >= 0)
for a in (SEED, CARRIED, VETERAN):
    kv_ops.recert_put(a, 0)
R = max(G - 5, 1)                                      # the veteran renews shortly before the gate
kv_ops.recert_put(VETERAN, R)
kv_ops.recert_put(FRESH, R)

before, after = (D.weights_at_epoch(G - 1) if G >= 1 else {}), D.weights_at_epoch(G)
check("a genesis seed earns nothing, before or after the gate", SEED not in before and SEED not in after, (before, after))
if G >= 1:
    check("before the gate a carried identity earns nothing (committed epochs stay as they were)", CARRIED not in before, before)
check("from the gate a carried identity earns", CARRIED in after, after)
check("...at its carried fidelity", after.get(CARRIED) == P.dividend_weight(15, G), (after.get(CARRIED), P.dividend_weight(15, G)))
live = P.fidelity_step(12, True, R - 0, R)             # what apply_register computed: continuing from the carried 12
check("a carried veteran who renewed replays to the live apply's fidelity, not a newcomer's",
      D.fidelity_at_epoch(VETERAN, G) == live, (D.fidelity_at_epoch(VETERAN, G), live))
check("...and weighs accordingly", after.get(VETERAN) == P.dividend_weight(live, G), after.get(VETERAN))
check("a fresh identity is unaffected", after.get(FRESH) == P.dividend_weight(P.fidelity_step(0, False, R + 1, R), G),
      after.get(FRESH))

kv_ops.close_all()
print("ALL PASS — carried identities earn at their carried fidelity" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
