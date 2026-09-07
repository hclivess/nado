"""SYBIL RULES after the gen-25 real-device reroll (protocol "SYBIL RULES", doc/device-attestation.md).

Gen 23/24 answered free-to-mint identities with probation (no dividend, open weight 1 until the first timely
renewal) and per-IP budgets. Gen 25 makes every identity an attested device, so those are RETIRED and this file
pins what replaced them:
  1. no activation gate survives, and `on_probation` is a name that always answers False;
  2. the dividend weight is ONE clean line over every fidelity level — fidelity 1 (the first lease) pays 1,
     linear to 30 — and open_shares is the plain 2..10 floor+bonus curve from the first lease;
  3. weights_at_epoch lists a day-one identity at weight 1 (only fidelity 0 is absent);
  4. the flood difficulty baseline statistics (ops/reg_difficulty) still cap by the 14-day trailing rate;
  5. the wallet says, next to the lease countdown, that a saved seed phrase renews nothing, and no per-IP
     budget or probation wording survives in the node or the wallet;
  6. the difficulty windows count ENTRIES, never renewals."""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def t1_gate_expression():
    """The gen-23 gate was retired at the gen-24 reroll: no gate name survives, the rules are unconditional."""
    import protocol as P
    src = open(os.path.join(ROOT, "protocol.py")).read()
    for name in ("SYBIL_RULES_HEIGHT", "SYBIL_RULES_EPOCH", "_GEN23_SYBIL_ACTIVATION"):
        check(f"{name} is gone", re.search(r"^\s*%s\b" % name, src, re.M) is None)
    check("gen 25+", P.CHAIN_GENERATION >= 25)
    check("probation retired: the name always answers False", not P.on_probation(1, 0) and not P.on_probation(0, 0) and not P.on_probation(1, 10**6))
    check("PROBATION_FIDELITY is gone", re.search(r"^\s*PROBATION_FIDELITY\b", src, re.M) is None)


def t2_clean_curve():
    """One line over every fidelity level, for the dividend and for the open-lane draw, from the first lease."""
    import protocol as P
    from ops.mining_ops import open_shares
    E1 = 0
    check("dividend: fidelity 1 pays 1 from the first lease, linear to 30, capped",
          [P.dividend_weight(f, E1) for f in (None, 0, 1, 2, 10, 30, 31)] == [0, 0, 1, 2, 10, 30, 30])
    check("dividend: every level 1..30 is on the line (no skipped level)",
          [P.dividend_weight(f, E1) for f in range(1, 31)] == list(range(1, 31)))
    check("dividend: the epoch never gates the curve", all(P.dividend_weight(1, e) == 1 for e in (0, 1, 400, 10**6)))
    check("open draw: floor+bonus from the first lease, epoch or not",
          [open_shares(f, E1) for f in (None, 0, 1, 2, 30)] == [2, 2, 2, 2, 10] and open_shares(0) == 2 and open_shares(1, 999) == 2)


def t3_weights_at_epoch_lists_day_one():
    d = tempfile.mkdtemp(prefix="nado-sybil-")
    os.environ["HOME"] = d
    from ops import kv_ops
    kv_ops.close_all(); kv_ops.init_env()
    import protocol as P
    from ops.dividend_ops import weights_at_epoch
    E = 400 + 10
    a, b = "a" * 46, "b" * 46
    kv_ops.recert_put(a, E - 1)                                 # fresh: one recert -> fidelity 1 -> weight 1
    kv_ops.recert_put(b, E - 1 - P.FIDELITY_MIN_GAP_EPOCHS)     # renewed timely -> fidelity 2 -> weight 2
    kv_ops.recert_put(b, E - 1)
    w = weights_at_epoch(E)
    check("a day-one identity is IN the committed weight set at weight 1; the renewed one at 2", w.get(a) == 1 and w.get(b) == 2, w)
    kv_ops.close_all()


def t4_difficulty_baseline():
    import protocol as P
    from ops import reg_difficulty as R
    orig = R._memo_count
    counts = {}
    R._memo_count = lambda e, *a: counts.get(e, 0)     # (epoch, entries_only)
    try:
        A = P.POSW_DIFF_TRAIL_LONG + 5
        # steady state: 3 registrations every epoch for 14 days -> 2-day rate == 14-day rate -> multiplier 1
        for e in range(A - P.POSW_DIFF_TRAIL_LONG - 1, A):
            counts[e] = 3
        check("honest steady state: 1x", R.difficulty_multiplier(A) == 1)
        # a 3-day burst at 10/epoch on top of a 14-day history of 3/epoch
        for e in range(A - 720, A):
            counts[e] = 10
        m_new = R.difficulty_multiplier(A)
        # what the OLD rule (2-day trail only) would say: the burst IS the baseline
        recent = 10 * P.POSW_DIFF_WINDOW
        old_baseline = max(P.POSW_DIFF_FLOOR, (10 * P.POSW_DIFF_TRAIL) * P.POSW_DIFF_WINDOW // P.POSW_DIFF_TRAIL)
        m_old = min(P.POSW_DIFF_MAX_MULT, max(1, recent // old_baseline))
        check("old rule normalised a 3-day burst to 1x", m_old == 1, m_old)
        check("new rule: the 14-day rate caps the baseline, burst pays the multiplier", m_new > m_old, (m_old, m_new))
        long_rate = (3 * (P.POSW_DIFF_TRAIL_LONG - 720) + 10 * 720) * P.POSW_DIFF_WINDOW // P.POSW_DIFF_TRAIL_LONG
        check("new multiplier == recent // min(2-day, 14-day) baseline", m_new == min(P.POSW_DIFF_MAX_MULT, recent // max(P.POSW_DIFF_FLOOR, long_rate)), m_new)
    finally:
        R._memo_count = orig


def t5_wiring():
    nado = open(os.path.join(ROOT, "nado.py")).read()
    ms = open(os.path.join(ROOT, "memserver.py")).read()
    js = open(os.path.join(ROOT, "static", "interface.js")).read()
    check("no per-IP registration budget survives in the node", "max_registrations_per_ip" not in ms and "allow_registration(" not in nado)
    check("live open weights list only positive weights (fidelity 0 absent)", "if w > 0:" in nado[nado.index("async def get_open_weights"):nado.index("async def duty_committee")])
    check("wallet: lease truth next to the countdown", "a saved seed phrase does not renew itself" in js)
    check("wallet: no probation wording is shown any more", 'i18("wal.probation' not in js)
    dops = open(os.path.join(ROOT, "ops", "dividend_ops.py")).read()
    check("dividend replay uses the epoch-aware weight", "dividend_weight(fidelity_at_epoch(addr, epoch), epoch)" in dops)


def t6_entries_only_counting():
    """The difficulty windows count ENTRIES (no lease in the previous POSW_LEASE_EPOCHS), never renewals."""
    d = tempfile.mkdtemp(prefix="nado-entries-")
    os.environ["HOME"] = d
    from ops import kv_ops
    kv_ops.close_all(); kv_ops.init_env()
    import protocol as P
    from ops import reg_difficulty as R
    a, b, c = "a" * 46, "b" * 46, "c" * 46
    E = 1000
    kv_ops.recert_put(a, E - 100)                       # a: entered earlier ...
    kv_ops.recert_put(a, E)                             # ... renews at E (gap 100 <= lease) -> NOT an entry
    kv_ops.recert_put(b, E - P.POSW_LEASE_EPOCHS - 1)   # b: lapsed lease ...
    kv_ops.recert_put(b, E)                             # ... re-enters at E -> entry
    kv_ops.recert_put(c, E)                             # c: brand new -> entry
    check("register count at E is 3 (all recerts)", kv_ops.recert_count_in_window(E, E) == 3)
    check("entry count at E is 2 (renewal excluded, lapse re-entry + newcomer counted)", R.chain_entry_count(E) == 2)
    check("addresses_in_epoch lists the three", sorted(kv_ops.recert_addresses_in_epoch(E)) == [a, b, c])
    check("empty epoch -> 0", R.chain_entry_count(E + 1) == 0 and R.chain_entry_count(-5) == 0)
    kv_ops.close_all()


if __name__ == "__main__":
    for name in ("t1_gate_expression", "t2_clean_curve", "t3_weights_at_epoch_lists_day_one", "t4_difficulty_baseline", "t5_wiring", "t6_entries_only_counting"):
        try:
            globals()[name]()
        except Exception:
            import traceback; traceback.print_exc(); _fails.append(name)
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
