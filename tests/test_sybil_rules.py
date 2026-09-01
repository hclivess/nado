"""SYBIL RULES (2026-09-01; protocol "SYBIL RULES", doc/ip-spoofing-and-sybil.md §Probation).

Gen-23-keyed activation at SYBIL_RULES_HEIGHT (block 86 400 = epoch 1440), THE rule from block 0 of gen 24+:
  1. probation: dividend_weight == 0 (== ABSENT from the epoch's weight set) until the first timely renewal
     (fidelity < PROBATION_FIDELITY);
  2. probation: open_shares == 1 (never 0) until then, the normal 2..10 curve after;
  3. the flood difficulty baseline is capped by the 14-day trailing rate, so a burst cannot become its own
     baseline; the honest steady state is unchanged;
  4. the relay's per-IP registration budget counts ENTRIES only (renewals exempt) and defaults to 8/h;
  5. the wallet says, next to the lease countdown, that a saved seed phrase renews nothing.
Pins the byte-identity of every rule BEFORE the activation epoch (old and new nodes must agree until then),
the exact behaviour after it, the gate's self-disarm at the next generation, and the wiring by source."""
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
    check("gen 24+", P.CHAIN_GENERATION >= 24)
    check("probation is unconditional", P.on_probation(1, 0) and not P.on_probation(2, 0))


def t2_probation_weights():
    import protocol as P
    from ops.mining_ops import open_shares
    E0, E1 = -1, 0
    check("from activation: probation identities weigh 0 (absent) for the dividend",
          [P.dividend_weight(f, E1) for f in (None, 0, 1)] == [0, 0, 0])
    check("from activation: the first timely renewal ends probation (fidelity 2 -> weight 2, linear to 30)",
          P.dividend_weight(2, E1) == 2 and P.dividend_weight(10, E1) == 10 and P.dividend_weight(30, E1) == 30)
    check("from activation: open weight 1 on probation, never 0, 2+bonus after",
          [open_shares(f, E1) for f in (None, 0, 1, 2, 30)] == [1, 1, 1, 2, 10])
    check("legacy display call (no epoch) keeps the un-gated curve", open_shares(0) == 2)
    check("on_probation predicate", P.on_probation(1, E1) and not P.on_probation(2, E1))


def t3_weights_at_epoch_omits_probation():
    d = tempfile.mkdtemp(prefix="nado-sybil-")
    os.environ["HOME"] = d
    from ops import kv_ops
    kv_ops.close_all(); kv_ops.init_env()
    import protocol as P
    from ops.dividend_ops import weights_at_epoch
    E = 400 + 10
    a, b = "a" * 46, "b" * 46
    kv_ops.recert_put(a, E - 1)                                 # fresh: one recert -> fidelity 1 -> probation
    kv_ops.recert_put(b, E - 1 - P.FIDELITY_MIN_GAP_EPOCHS)     # renewed timely -> fidelity 2
    kv_ops.recert_put(b, E - 1)
    w = weights_at_epoch(E)
    check("probation identity ABSENT from the committed weight set (exec floors listed weights to 1)", a not in w and w.get(b) == 2, w)   # linear: fidelity 2 -> weight 2
    kv_ops.close_all()


def t4_difficulty_baseline():
    import protocol as P
    from ops import reg_difficulty as R
    orig = R._memo_count
    counts = {}
    R._memo_count = lambda e: counts.get(e, 0)
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
    seg = nado[nado.index("def _ip_registration_rejection"):nado.index("def _ip_registration_rejection") + 2500]
    check("per-IP budget: entries only", "is_entry_registration(" in seg and "return None" in seg.split("is_entry_registration(")[1][:200])
    check("per-IP budget default 8", 'self.config.get("max_registrations_per_ip", 8)' in ms)
    check("live open weights omit probation", "if w > 0:" in nado[nado.index("async def get_open_weights"):nado.index("async def duty_committee")])
    check("wallet: lease truth next to the countdown", "a saved seed phrase does not renew anything" in js)
    check("wallet: probation explained where the fidelity number is", '"wal.probation"' in js)
    dops = open(os.path.join(ROOT, "ops", "dividend_ops.py")).read()
    check("dividend replay uses the epoch-aware weight", "dividend_weight(fidelity_at_epoch(addr, epoch), epoch)" in dops)


if __name__ == "__main__":
    for name in ("t1_gate_expression", "t2_probation_weights", "t3_weights_at_epoch_omits_probation", "t4_difficulty_baseline", "t5_wiring"):
        try:
            globals()[name]()
        except Exception:
            import traceback; traceback.print_exc(); _fails.append(name)
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
