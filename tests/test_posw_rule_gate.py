"""POSW_ENTRY_COUNT_HEIGHT — the gen-24 flood-counting rule gate (protocol.py, ops/reg_difficulty.entries_only_at).

THE INCIDENT (2026-09-02). 84d122f3 switched the registration-difficulty flood counter from every register tx
to ENTRIES only and shipped it ungated at 17:12 UTC on 2026-09-01, 1600 blocks into betanet-6. The fleet had
validated every earlier registration under the old rule — block 871's proof encodes 160M steps (5 x 32) where
the new rule computes 128M (4 x 32) — so a from-genesis replay rejected block 871 and this node (purged after
an unrelated peer-loop crash) could not rejoin the network. Replaying blocks 0..3600 against every proof's
Fiat-Shamir set found the last old-rule registration at block 1608 and the first new-rule one at 1636.

Pinned here: the gate is generation-keyed (gen 24 = 1636, anything else 0), validation passes the LANDING
height, the two rules count what they claim (renewals in / out) on a fake index, the memo separates them, and
the anchor-epoch windows are unchanged by the rule.
Run: python3 tests/test_posw_rule_gate.py
"""
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


import protocol as P
from ops import kv_ops
import ops.account_ops as AO
from ops import reg_difficulty as R

check("gate is generation-keyed: 1636 on gen 24, 0 elsewhere",
      P.POSW_ENTRY_COUNT_HEIGHT == (1636 if P.CHAIN_GENERATION == 24 else 0), P.POSW_ENTRY_COUNT_HEIGHT)
check("the expression self-disarms (no bare height)",
      "POSW_ENTRY_COUNT_HEIGHT = 1636 if CHAIN_GENERATION == 24 else 0" in open(os.path.join(ROOT, "protocol.py")).read())
src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
check("validation passes the LANDING height to required_posw_t", "landing_height=block_height)" in src)
check("display paths (no landing height) get today's rule", R.entries_only_at(None) is True)
if P.CHAIN_GENERATION == 24:
    check("a block below the gate is validated under the old rule", R.entries_only_at(1635) is False)
    check("the gate block itself is validated under the new rule", R.entries_only_at(1636) is True)

# ---- fake index: epoch E-1 holds one newcomer, one renewal (recert at E-2), one lapse re-entry
by_addr = collections.defaultdict(list)
by_epoch = collections.defaultdict(set)
def put(a, e):
    by_epoch[e].add(a); by_addr[a].append(e); by_addr[a].sort()
kv_ops.recert_addresses_in_epoch = lambda e: sorted(by_epoch.get(int(e), ()))
kv_ops.recert_count_in_window = lambda lo, hi: sum(len(by_epoch.get(e, ())) for e in range(max(0, lo), hi + 1))
kv_ops.recert_epochs = lambda a, upto_epoch=None: [e for e in by_addr.get(a, []) if upto_epoch is None or e <= upto_epoch]
kv_ops.env_path = lambda: "mem-gate-test"
AO.get_hard_finality = lambda: 0
E = 1000
put("renewer", E - 2); put("renewer", E - 1)
put("lapsed", E - 1 - P.POSW_LEASE_EPOCHS - 5); put("lapsed", E - 1)
put("newcomer", E - 1)
R._count_memo.clear()
check("old rule counts every register tx in the epoch (3)", R._window_count(E - 1, E - 1, entries_only=False) == 3)
check("new rule counts entries only (2: renewal excluded)", R._window_count(E - 1, E - 1, entries_only=True) == 2)
check("the memo keeps the two rules apart",
      R._memo_count(E - 1, False) == 3 and R._memo_count(E - 1, True) == 2)
# a flood of 100 fresh identities in epoch E-1 vs 100 RENEWALS: only the rule decides the multiplier
for i in range(100):
    put(f"fresh{i}", E - 1)
R._count_memo.clear()
m_old, m_new = R.difficulty_multiplier(E, entries_only=False), R.difficulty_multiplier(E, entries_only=True)
check("fresh identities raise the multiplier under both rules", m_old > 1 and m_new > 1, (m_old, m_new))
for i in range(100):
    put(f"ren{i}", E - 1 - 30); put(f"ren{i}", E - 1)      # first recert OUTSIDE the 20-epoch window, inside the lease
R._count_memo.clear()
m_old2, m_new2 = R.difficulty_multiplier(E, entries_only=False), R.difficulty_multiplier(E, entries_only=True)
check("100 renewals raise the OLD multiplier and leave the NEW one alone", m_old2 > m_old and m_new2 == m_new,
      (m_old, m_old2, m_new, m_new2))
if P.CHAIN_GENERATION == 24:
    check("required_posw_t follows the landing height",
          R.required_posw_t(E, "renewer", landing_height=1635) == P.POSW_T * m_old2
          and R.required_posw_t(E, "renewer", landing_height=1636) == P.POSW_T * m_new2)

print()
print("ALL POSW-RULE-GATE CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
sys.exit(1 if _fails else 0)
