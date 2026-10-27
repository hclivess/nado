"""An identity absent at the reroll keeps its carried fidelity in the dividend (gen 28's
CARRY_FIDELITY_ALL_HEIGHT, inlined in G9: every epoch >= 0).

OUR BUG (found 2026-10-10). The carry wrote every identity's fidelity into its account, and the live apply
(account_ops.apply_register) continued from it, so the open-lane draw saw the carried value. The dividend replay
(dividend_ops.fidelity_at_epoch) seeded it only for identities PRESENT at the reroll (an epoch-0 recert), so the 32
identities absent at the gen-28 reroll were paid as newcomers: account fidelity 16, dividend fidelity 12.

Pins, on the real tables (throwaway HOME) with a scripted carry, driving the REAL live apply:
  1. from epoch 0, the replay of an absent carried identity equals the account field the live apply wrote, after its
     first recert (a lapse from the carried value) and after a continuous renewal;
  2. a negative epoch still replays 0 (the inlined gate's `epoch >= 0` is kept);
  3. an absent carried identity with no recert yet replays 0, never its bare carried value;
  4. an identity present at the reroll and a fresh identity are unaffected.
The pre-gate half (below 160020 an absent identity replayed as a newcomer) is retired in G9: generation 28's rules.

Run: python3 tests/test_an_identity_absent_at_the_reroll_keeps_its_carried_fidelity.py
"""
import json, logging, os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-absent-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import protocol as P
os.makedirs(os.path.join(os.environ["HOME"], "nado", "private"), exist_ok=True)
ABSENT, SILENT, PRESENT, FRESH = "a" * 46, "b" * 46, "c" * 46, "d" * 46
carry_file = os.path.join(os.environ["HOME"], "carry.json")
json.dump({"generation": P.CHAIN_GENERATION, "present": [PRESENT]}, open(carry_file, "w"))
os.environ["NADO_GENESIS_CARRY"] = carry_file
alloc_file = os.path.join(os.environ["HOME"], "alloc.json")
json.dump([{"address": ABSENT, "fidelity": 12, "balance": 0}, {"address": SILENT, "fidelity": 9, "balance": 0},
           {"address": PRESENT, "fidelity": 15, "balance": 0}], open(alloc_file, "w"))
os.environ["NADO_GENESIS_ALLOC"] = alloc_file
from ops import kv_ops
kv_ops.close_all(); kv_ops.init_env()
from ops import account_ops as A, dividend_ops as D
D._CARRIED[0] = D._CARRIED_ABSENT[0] = None
log = logging.getLogger("t")

import _harness
_report = _harness.Report()
check = _report.check


G = 0                                                     # the first epoch the rule judges: every epoch since gen 29
check("the gate is deleted (gen 28's CARRY_FIDELITY_ALL_HEIGHT, inlined in G9)", not hasattr(P, "CARRY_FIDELITY_ALL_HEIGHT"))

# genesis as the carry writes it: every carried account holds its fidelity; only PRESENT gets the epoch-0 lease
with kv_ops.write_txn():
    A.create_account(ABSENT, fidelity=12)
    A.create_account(SILENT, fidelity=9)
    A.create_account(PRESENT, fidelity=15)
    A.create_account(FRESH)
    kv_ops.recert_put(PRESENT, 0)
# The absent identity comes back in an early epoch, then renews continuously.
r1 = max(1, G - 3)
r2 = r1 + P.FIDELITY_MIN_GAP_EPOCHS
with kv_ops.write_txn():
    A.apply_register(ABSENT, r1, log)
    A.apply_register(FRESH, r1, log)
after_first = kv_ops.get_account(ABSENT)["fidelity"]
with kv_ops.write_txn():
    A.apply_register(ABSENT, r2, log)
after_renew = kv_ops.get_account(ABSENT)["fidelity"]

check("the live apply continued from the carried value (a lapse halves it)", after_first == P.fidelity_step(12, False, r1 + 1, r1),
      after_first)
check("a negative epoch replays 0, never the carried value", D.fidelity_at_epoch(ABSENT, -1) == 0,
      D.fidelity_at_epoch(ABSENT, -1))
check("its replay equals the live apply's account field after its first recert",
      D.fidelity_at_epoch(ABSENT, max(G, r1)) == after_first, (D.fidelity_at_epoch(ABSENT, max(G, r1)), after_first))
check("...and after a continuous renewal", D.fidelity_at_epoch(ABSENT, max(G, r2)) == after_renew,
      (D.fidelity_at_epoch(ABSENT, max(G, r2)), after_renew))
check("an absent carried identity with no recert replays 0, never its bare carried value",
      D.fidelity_at_epoch(SILENT, max(G, r2)) == 0, D.fidelity_at_epoch(SILENT, max(G, r2)))
check("an identity present at the reroll is unaffected (its epoch-0 lease carries it)",
      D.fidelity_at_epoch(PRESENT, max(G, r2)) == 15, D.fidelity_at_epoch(PRESENT, max(G, r2)))
check("a fresh identity is unaffected", D.fidelity_at_epoch(FRESH, max(G, r2)) == kv_ops.get_account(FRESH)["fidelity"],
      (D.fidelity_at_epoch(FRESH, max(G, r2)), kv_ops.get_account(FRESH)["fidelity"]))
E = max(G, r2)
w = D.weights_at_epoch(E)
scale = P.REFERRAL_SCALE                    # every epoch's weights are scaled (REFERRAL_HEIGHT, inlined in G9)
check("the dividend weight follows the carried fidelity", w.get(ABSENT) == scale * P.dividend_weight(after_renew, E),
      (w.get(ABSENT), scale, after_renew))

kv_ops.close_all()
print("ALL PASS — an identity absent at the reroll keeps its carried fidelity" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
