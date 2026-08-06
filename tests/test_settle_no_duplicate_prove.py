"""Only ONE proof-carrying settle may be in flight at a time.

MEASURED 2026-08-06 13:12:06-13:13:42 — three proves and three 8.92 MiB transactions in 96 seconds:

    [settle-prove] cursor=46892 ... total 11.7s   ->  "span→46892: 1 segment(s), tx 8.92 MiB"
    [settle-prove] cursor=46893 ... total 13.3s   ->  "span→46893: 1 segment(s), tx 8.92 MiB"
    [settle-prove] cursor=46897 ... total 11.9s   ->  "span→46897: 1 segment(s), tx 8.92 MiB"

all for the SAME root 1b00b000dd28252d. Only one can ever land: the moment one is justified the others fail
"pre_root must extend the settled tip". That is ~27 MiB of gossip and 3x the prove CPU for one settlement.

THE HOLD ALREADY EXISTED AND DID NOT COVER THIS. It reads `if proof is None and (...)`, so it suppressed a
redundant BARE settle but never a redundant PROOF — the loop proved FIRST and then skipped the hold. That
was invisible while a prove took 300+ s, because `_settle_proving` covered the whole window; 1affffac took
a prove to ~12 s and the gap opened. A guard that only fires on the cheap path is not a guard.

THE SECOND HALF MATTERS AS MUCH AS THE FIRST. Declining to prove is only correct if the same pass also
declines to settle BARE. Otherwise the pass that notices the pending proof has landed would fall straight
through to a bare settle, and every landed proof would be followed by a bare one — quietly halving the
proof rate, the opposite of the intent.

Run: python3 tests/test_settle_no_duplicate_prove.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SRC = open(os.path.join(ROOT, "execnode", "execnode.py")).read()

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def t_the_prove_is_gated_on_no_pending_proof():
    assert "_pend_hold = _settle_pending.get(ns) is not None" in SRC, \
        "the loop must record whether a proof-carrying settle is already pending"
    assert "if not _pend_hold:\n                    proof = await _build_settlement_proof(" in SRC, \
        "_build_settlement_proof must not run while a proof is pending its landing block"


def t_the_hold_also_covers_the_declined_pass():
    assert "or _pend_active or _pend_hold)" in SRC, \
        "the bare-settle hold must include _pend_hold, or a landed proof is followed by a bare settle"


def t_only_one_build_call_exists():
    """A second call site would route around the gate."""
    assert SRC.count("await _build_settlement_proof(") == 1, \
        "there must be exactly one _build_settlement_proof call site for the gate to be sufficient"


def t_pending_is_always_released():
    """The gate can only be safe if the pending entry is cleared on every outcome — landed, resubmitted,
    or given up — otherwise a stuck entry would stop proving forever."""
    assert SRC.count("_settle_pending.pop(ns, None)") >= 4, \
        "the resolution block must release the pending entry on every failure path"
    assert "GIVING " in SRC and "SETTLE_RESUBMIT_MAX_S" in SRC, \
        "there must be a bounded give-up path so a pending entry cannot wedge the prover"


def t_the_measurement_is_recorded():
    i = SRC.index("_pend_hold = _settle_pending.get(ns) is not None")
    ctx = SRC[max(0, i - 1800):i]
    assert "46892" in ctx and "8.92 MiB" in ctx, \
        "the three-duplicate-proves measurement must be recorded beside the gate"
    assert "pre_root must extend the settled tip" in ctx, \
        "the comment must say WHY only one can land"


for nm, fn in [("the prove is gated on no pending proof", t_the_prove_is_gated_on_no_pending_proof),
               ("the hold also covers the declined pass", t_the_hold_also_covers_the_declined_pass),
               ("only one _build_settlement_proof call site", t_only_one_build_call_exists),
               ("the pending entry is always released", t_pending_is_always_released),
               ("the measurement is recorded beside the gate", t_the_measurement_is_recorded)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
