"""
While a proof is in flight, a BARE settle must not advance the justified tip.

WHY THIS EXISTS. L1 accepts a settle proof for span sc->cur only while the justified tip is STILL sc:

    "Settle proof pre_root must extend the settled tip"

Every bare attestation advances that tip. So bare-settling while our OWN prove is running moves the target
the proof is aiming at, and guarantees the proof is refused the instant it arrives — a race a node runs
against itself and always loses.

OBSERVED LIVE 2026-08-04, and it was the last thing between the pipeline and a proof-carrying settle:

    17:10:02  BUILT span 21660->21690                                   prove   67.5 s
    17:12:21  PUBLISHED to DA 118.57 MiB k=4/n=8                        publish  139 s
    17:14:39  not accepted: "pre_root must extend the settled tip"      verify    94 s

The proof VERIFIED — it cleared the DA fetch, the parse and the full cryptographic check. It was refused
because bare settles had carried the tip from 21660 to 21720 during the ~300 s (~50 blocks) the pipeline
took, against a 30-block settle cadence. No proof can win that race while the prover keeps moving the tip.

THE COST IS REAL AND IS THE POINT: holding means the settled tip stops advancing for the length of one
pipeline (~5 min), bounded by SETTLE_PROVE_TIMEOUT and released by the same done-callback that clears the
in-flight guard. Bridge exits see a staler tip for that window. The way to shrink the window is a faster
pipeline (the K→1 fold, the DA and verifier ports) — not more bare settles, which cannot coexist with a
proof by construction.

Run: python3 tests/test_settle_hold_inflight.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_hold_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


HELD, BARE, WITH_PROOF = "held", "bare", "with-proof"


def outcome(proof_built, prove_in_flight):
    """maybe_settle's decision, in the order the shipped code takes it."""
    if proof_built:
        return WITH_PROOF               # a proof we just built rides the settle
    if prove_in_flight:
        return HELD                     # holding the tip for the proof still being built
    return BARE                         # nothing in flight: settle bare for liveness


# ---- THE CORE PROPERTY -------------------------------------------------------------------------------
check("a prove in flight HOLDS the settle instead of settling bare",
      outcome(proof_built=False, prove_in_flight=True) == HELD)
check("...so the justified tip cannot move past the span being proven",
      outcome(proof_built=False, prove_in_flight=True) != BARE)

# ---- LIVENESS IS PRESERVED WHEN NOTHING IS IN FLIGHT --------------------------------------------------
check("no prove in flight -> a bare settle still goes out (liveness path intact)",
      outcome(proof_built=False, prove_in_flight=False) == BARE)
check("a freshly built proof rides the settle, it is not held",
      outcome(proof_built=True, prove_in_flight=True) == WITH_PROOF)
check("...and also when nothing else is in flight",
      outcome(proof_built=True, prove_in_flight=False) == WITH_PROOF)

# ---- THE RACE THIS PREVENTS, MODELLED ----------------------------------------------------------------
def tip_after(pipeline_blocks, cadence_blocks, hold):
    """Where the justified tip ends up while a proof for the CURRENT tip is in flight."""
    tip = 0
    if not hold:
        tip += (pipeline_blocks // cadence_blocks) * cadence_blocks
    return tip


PIPE, CAD = 50, 30          # ~300 s of pipeline against a 30-block cadence, as measured
check("WITHOUT the hold the tip moves during the pipeline (the proof is refused)",
      tip_after(PIPE, CAD, hold=False) > 0)
check("WITH the hold the tip is exactly where the proof expects it",
      tip_after(PIPE, CAD, hold=True) == 0)
check("the hold matters precisely because the pipeline outlasts the cadence", PIPE > CAD)

# ---- the shipped code must actually do it ------------------------------------------------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "execnode", "execnode.py")).read()
check("maybe_settle holds when a prove is in flight",
      "if proof is None and (_settle_proving or _pub_active):" in src)
# THE HOLD MUST SPAN PUBLISH AND SUBMIT, NOT JUST THE PROVE. _settle_proving is cleared by the prove
# THREAD's done-callback, so it goes False at "BUILT" while ~230 s of publish (139 s) and inline L1
# verification (94 s) still lie ahead. Bare settles resumed in that window and walked the tip forward:
# observed live 2026-08-04, two proofs built from pre-state 21780 while the settled tip reached 21840.
check("the hold also covers publish+submit, not just the prove",
      "_settle_publishing" in src and 'globals()["_settle_publishing"] = time.time()' in src)
check("...and is released when the attempt ends",
      'globals()["_settle_publishing"] = 0.0' in src)
check("...and SELF-EXPIRES, so a stuck hold cannot stop settlement forever",
      "SETTLE_HOLD_MAX_S" in src)
check("...and says so rather than skipping silently", "settle HELD ns=" in src)
check("the hold is released by the same guard that tracks the prove thread",
      "_clear_settle_proving" in src and "_settle_proving = False" in src)

print()
print("ALL PASS — a node no longer races its own proof by moving the tip out from under it"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
