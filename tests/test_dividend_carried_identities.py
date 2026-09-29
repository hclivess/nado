"""Carried identities earn the dividend, at their carried fidelity (ops/dividend_ops).

OUR BUG (reroll commit 302215f2, betanet-8). The carry leased every carried identity with a recert at epoch 0 — the
marker the dividend rule uses to exclude never-attested genesis seeds — so every carried identity was present,
produced, and earned NO dividend until it re-registered (measured 2026-09-27: all 23 carried identities that had not
re-registered were missing from every committed weight set). And the replay behind the committed weights rebuilt
fidelity from gen-27 recerts only, so a carried veteran who renewed weighed like a newcomer.

Gen 27 fixed it from DIVIDEND_CARRY_EPOCH = 340; it held from epoch 0 on gen 28 and the gate was deleted after the
betanet-9 reroll, so the rule is exercised from epoch 0 (the carry's own lease) on.

Pins, on the real tables (throwaway HOME) with a scripted carry:
  1. a genesis SEED (epoch-0 recert, not in the carry) earns nothing, at epoch 0 or later;
  2. a CARRIED identity (epoch-0 recert, named present by the carry) earns from epoch 0, weighted by its carried
     fidelity;
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


check("the carry rule has no gate left", not hasattr(P, "DIVIDEND_CARRY_EPOCH"))
for a in (SEED, CARRIED, VETERAN):
    kv_ops.recert_put(a, 0)                            # the carry's lease (and a seed's genesis recert)
R = 1                                                  # the veteran renews, and a fresh identity registers, at epoch 1
kv_ops.recert_put(VETERAN, R)
kv_ops.recert_put(FRESH, R)

# Judged at epoch 0 the veteran's renewal and the fresh identity's first recert have not happened yet, so the
# renewal-dependent checks are judged at E = R, the first epoch that has seen the renewal; the carried-identity checks
# run at both.
E = R
at_zero, after = D.weights_at_epoch(0), D.weights_at_epoch(E)
check("a genesis seed earns nothing, at epoch 0 or later", SEED not in at_zero and SEED not in after, (at_zero, after))
check("a carried identity earns from epoch 0", CARRIED in at_zero and CARRIED in after, (at_zero, after))
check("...at its carried fidelity", at_zero.get(CARRIED) == P.dividend_weight(15, 0) and after.get(CARRIED) == P.dividend_weight(15, E),
      (at_zero.get(CARRIED), after.get(CARRIED), P.dividend_weight(15, 0)))
check("a carried veteran is carried at epoch 0 too", D.fidelity_at_epoch(VETERAN, 0) == 12, D.fidelity_at_epoch(VETERAN, 0))
live = P.fidelity_step(12, True, R - 0, R)             # what apply_register computed: continuing from the carried 12
check("a carried veteran who renewed replays to the live apply's fidelity, not a newcomer's",
      R <= E and D.fidelity_at_epoch(VETERAN, E) == live, (R, E, D.fidelity_at_epoch(VETERAN, E), live))
check("...and weighs accordingly", after.get(VETERAN) == P.dividend_weight(live, E), after.get(VETERAN))
check("a fresh identity is unaffected", after.get(FRESH) == P.dividend_weight(P.fidelity_step(0, False, R + 1, R), E),
      after.get(FRESH))

kv_ops.close_all()
print("ALL PASS — carried identities earn at their carried fidelity" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
