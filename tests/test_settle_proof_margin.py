"""SETTLE_PROOF_TX_MARGIN must be sized from a MEASURED propagation time, and must stay in bounds.

A settle is an EXACT-LANDING tx (protocol.py:115 — it "lands at exactly max_block"), so this margin is not
slack: it is how long the exec node FREEZES settlement. It must hold every bare settle until the proven
span lands, or it would advance the justified tip past the span the proof covers and guarantee its refusal.
MEASURED on the cursor-46538 proof: submitted 12:35, next settle 12:55 — ~20 minutes of frozen settlement.

THE HISTORY, because both directions were mistakes at some point:
  * 60  — right when a settle shipped only a DA commitment.
  * 180 — right when 6f7b6a41 made the tx the ~120 MiB inline proof and propagation measured ~8 MINUTES;
          before the raise, a correct, fully propagated proof was still unlandable because the deadline had
          already passed.
  * 60  — right again after 1affffac made the proof 8.92 MiB. Re-measured 2026-08-06 13:12 on a live proof
          (cursor 46892) by polling each peer's own /transaction_pool until it held the tx:
          .131 +3.4 s, .210 +4.2 s, .141 +31.7 s, from 10 s after submit => ~42 s end to end.
          Block time the same minute: 6.0 s/block. 60 blocks = ~6 min = 8.6x the observed worst case.

The bounds below are what actually matters; the exact number is a judgement call the comment defends.

Run: python3 tests/test_settle_proof_margin.py
"""
import os
import re
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SRC = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
import protocol

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


def _margin():
    m = re.search(r"^SETTLE_PROOF_TX_MARGIN = (\d+)", SRC, re.M)
    assert m, "SETTLE_PROOF_TX_MARGIN not found"
    return int(m.group(1))


def t_margin_is_under_the_landing_window():
    """max_block is capped at admission by TX_LANDING_WINDOW; a margin at or above it means a peer whose
    tip is even slightly behind ours rejects the tx outright."""
    assert _margin() < protocol.TX_LANDING_WINDOW, \
        f"margin {_margin()} must stay under TX_LANDING_WINDOW {protocol.TX_LANDING_WINDOW}"
    assert _margin() <= protocol.TX_LANDING_WINDOW // 2, \
        "leave at least half the window as slack for a slightly-behind peer"


def t_margin_covers_the_measured_propagation():
    """~42 s measured end to end at 6.0 s/block => 7 blocks. Require a real multiple of that, because an
    exact-landing tx must be held by whoever produces THAT SPECIFIC block, and most producers cannot be
    polled from here (~18 distinct producers per 66 blocks; only 3 peers are reachable)."""
    measured_blocks = 7           # 42 s / 6.0 s per block, rounded up
    assert _margin() >= 5 * measured_blocks, \
        f"margin {_margin()} leaves too little headroom over the measured {measured_blocks} blocks"


def t_margin_does_not_silently_regress_to_the_120mib_era():
    """180 was correct only while the tx was ~120 MiB. Keeping it after 1affffac would freeze settlement
    for 18 minutes per proof for no reason."""
    assert _margin() != 180 or "120.31" not in SRC, \
        "the 180-block margin belongs to the 120 MiB proof; re-justify it against a fresh measurement"


def t_the_measurement_is_recorded_next_to_the_constant():
    """The value is a judgement call; the evidence must travel with it or the next change is a guess."""
    i = SRC.index("SETTLE_PROOF_TX_MARGIN =")
    ctx = SRC[max(0, i - 2600):i]
    assert "proppropagate" in ctx or "31.7" in ctx, \
        "the propagation measurement must be recorded beside the constant"
    assert "EXACT-LANDING" in ctx, \
        "the comment must say WHY the margin is a stall, not just slack"


def t_margin_is_only_applied_to_proof_carrying_settles():
    """A bare settle must keep its tight margin — widening it would stall the quorum path too. The margin
    now FOLLOWS THE PROOF: a records half gets SETTLE_PROOF_RECORDS_TX_MARGIN, a KV-only proof
    SETTLE_PROOF_TX_MARGIN, and a bare settle a small fixed runway (12; cursor quantization below it)."""
    import re
    m = re.search(r"_margin = \(\(SETTLE_PROOF_RECORDS_TX_MARGIN if _has_records else SETTLE_PROOF_TX_MARGIN\)\s*"
                  r"if \(proof is not None or proof_da\) else (\d+)\)", SRC)
    assert m, "the wide margin must apply ONLY when a proof (inline or DA) is attached"
    assert int(m.group(1)) < 60, f"a bare settle's runway ({m.group(1)}) must stay far below the proof margin"


for nm, fn in [("margin stays under TX_LANDING_WINDOW", t_margin_is_under_the_landing_window),
               ("margin covers the measured propagation with headroom", t_margin_covers_the_measured_propagation),
               ("margin is not the stale 120 MiB-era value", t_margin_does_not_silently_regress_to_the_120mib_era),
               ("the measurement is recorded beside the constant", t_the_measurement_is_recorded_next_to_the_constant),
               ("the wide margin applies only to proof-carrying settles", t_margin_is_only_applied_to_proof_carrying_settles)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
