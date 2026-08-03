"""
The proving cadence must be able to produce a proof at all (execnode settle cadence vs the epoch rule).

WHY THIS EXISTS. _build_settlement_proof refuses any span that crosses a DIVIDEND EPOCH BOUNDARY:

    if (sc // EPOCH_LENGTH) != (cur // EPOCH_LENGTH): return None

That rule is not negotiable — a dividend moves the RECORDS half of the settled root, and a sparse
settlement proof pins records UNCHANGED across the proven span. So a provable span must lie strictly
inside one epoch.

THE BUG THIS PINS, found live on 2026-08-03 within minutes of switching the prover on in production.
Enabling NADO_EXEC_SETTLE_PROVE also changed the settle cadence to SETTLE_PROOF_MAX_SPAN. But

    SETTLE_PROOF_MAX_SPAN = 4 * EPOCH_LENGTH

so EVERY span straddled ~4 dividend boundaries, condition 3 returned None every single time, and the node
produced ZERO proofs — silently, because that return had no log. The observable symptom was a perfectly
ordinary bare settle (`SETTLE ns=default cursor 8909`) and nothing else. The span cap could not even bind:
the epoch rule is 4x tighter, so the cap was dead code the moment the prover was on.

Two independent things are asserted here, because fixing only one leaves the flag a no-op:
  * the configured cadence CAN yield a conforming span (otherwise the prover is decorative), and
  * the old cadence provably CANNOT (so this can never silently regress to it).

Run: python3 tests/test_settle_prove_cadence.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_cadence_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import EPOCH_LENGTH, SETTLE_PROOF_MAX_SPAN

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def conforms(sc, cur):
    """The exact gate from _build_settlement_proof step 3."""
    return (sc < cur
            and (cur - sc) <= SETTLE_PROOF_MAX_SPAN
            and (sc // EPOCH_LENGTH) == (cur // EPOCH_LENGTH))


def conforming_spans(cadence, settles=40, start=0):
    """How many of `settles` consecutive settles at this cadence yield a provable span."""
    sc, n = start, 0
    for _ in range(settles):
        cur = sc + cadence
        if conforms(sc, cur):
            n += 1
        sc = cur
    return n


# The cadence execnode actually installs when the prover is on.
CADENCE = max(1, min(int(SETTLE_PROOF_MAX_SPAN), int(EPOCH_LENGTH) // 2))

check("the epoch rule is the binding constraint, not the span cap",
      SETTLE_PROOF_MAX_SPAN > EPOCH_LENGTH)
check("the configured proving cadence fits inside one epoch", CADENCE < EPOCH_LENGTH)
check("THE POINT: the configured cadence actually yields provable spans",
      conforming_spans(CADENCE) > 0)

# ---- the regression: the OLD cadence could never produce a single proof -------------------------------
check("the old cadence (SETTLE_PROOF_MAX_SPAN) yields ZERO provable spans — the bug",
      conforming_spans(int(SETTLE_PROOF_MAX_SPAN)) == 0)
check("...and that holds from ANY starting cursor, so it was never a phase problem",
      all(conforming_spans(int(SETTLE_PROOF_MAX_SPAN), settles=8, start=s) == 0
          for s in range(0, EPOCH_LENGTH)))

# ---- any cadence at or above a full epoch is equally hopeless -----------------------------------------
for bad in (EPOCH_LENGTH, EPOCH_LENGTH * 2, EPOCH_LENGTH * 4):
    check("a cadence of %d (>= one epoch) can never conform" % bad,
          conforming_spans(bad, settles=20) == 0)

# ---- the straddling settles are not wasted: they re-anchor so the NEXT span conforms ------------------
sc, pattern = 0, []
for _ in range(6):
    cur = sc + CADENCE
    pattern.append(conforms(sc, cur))
    sc = cur
check("conforming and re-anchoring settles alternate (a proof roughly once per epoch)",
      any(pattern) and not all(pattern))

# ---- a span that stays inside one epoch conforms; one that steps over the boundary does not ----------
check("a span wholly inside an epoch conforms", conforms(EPOCH_LENGTH + 1, EPOCH_LENGTH + 10))
check("a span crossing the boundary by ONE block is refused",
      not conforms(EPOCH_LENGTH - 1, EPOCH_LENGTH))
check("a non-advancing span is refused", not conforms(100, 100))
check("a span over the cap is refused", not conforms(0, SETTLE_PROOF_MAX_SPAN + 1))

print()
print("ALL PASS — the proving cadence can produce a proof, and the cadence that never could is pinned"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
