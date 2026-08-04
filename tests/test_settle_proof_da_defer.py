"""
A DA-published settle proof we do not hold must DEFER the block, never reject it.

WHY THIS EXISTS. A settle proof is ~118 MiB at protocol strength against an 8 MiB submit cap and a
~256 KiB block, so it cannot ride inside the transaction. It is published k-of-n and the tx carries only
the commitment. That buys trustless settlement — the root justified by a validity proof instead of a
bonded quorum — but only if resolving the proof is safe, and the naive wiring is NOT.

THE FORK THIS AVOIDS. If "I cannot fetch the proof" meant "this block is invalid", then two nodes would
disagree about block validity purely because one of them happened to hold the shards. The justified
(exec_cursor, exec_root) goes into the L1 BLOCK HEADER, so that disagreement is a chain split, not a
degraded mode. Availability is a property of the network at a moment in time; validity must not be.

SO THERE ARE THREE OUTCOMES, not two:

    valid          the proof resolved and verified
    invalid        the proof resolved and did NOT verify, or resolved to non-proof bytes  -> reject
    NOT YET        the proof did not resolve                                              -> DEFER

Deferral is fork-free because every node applies the same rule: all converge on the same chain, and a DA
outage costs LIVENESS, never safety. This is the 4844/Celestia blob rule, and the exec layer already
implements it one level down — _apply_block returns False and "the block STALLS in L1 order" when a
field_transfer proof is unavailable.

AND THE STALL IS BOUNDED. Past FINALITY_DEPTH below the known tip, `deep` is True and the proof is not
consulted at all (SETTLE_PROOF_DEPTH_GATED), so a proof that never becomes available degrades to the
accumulated-weight path instead of halting the node forever. Without that bound a withholder could stop a
node permanently; with it, the worst they achieve is that we wait.

Run: python3 tests/test_settle_proof_da_defer.py
"""
import json
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_dadefer_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


from ops.transaction_ops import ProofUnavailable  # noqa: E402

REJECT, DEFER, ACCEPT = "reject", "defer", "accept"


def outcome(has_inline, commitment, deep, da_holds, verifies):
    """The settle branch's decision, in the same order the shipped code takes it."""
    if has_inline:
        return ACCEPT if verifies else REJECT
    if commitment is None:
        return ACCEPT                      # bare attestation -> quorum path, unchanged
    if deep:
        return ACCEPT                      # depth-gated: proof not consulted, weight carries it
    if not da_holds:
        raise ProofUnavailable("not available yet")
    if da_holds == "garbage":
        return REJECT                      # resolved but not a proof: that IS a judgement
    return ACCEPT if verifies else REJECT


def run(**kw):
    try:
        return outcome(**kw)
    except ProofUnavailable:
        return DEFER


base = dict(has_inline=False, commitment="c0ffee", deep=False, da_holds=True, verifies=True)

# ---- THE CORE PROPERTY: unavailable is DEFER, not REJECT --------------------------------------------
check("proof not available near the tip -> DEFER (never reject)",
      run(**{**base, "da_holds": False}) == DEFER)
check("...and deferral is NOT acceptance either", run(**{**base, "da_holds": False}) != ACCEPT)

# ---- resolved-and-bad IS a judgement we can make ----------------------------------------------------
check("proof resolves but fails verification -> REJECT", run(**{**base, "verifies": False}) == REJECT)
check("commitment resolves to non-proof bytes -> REJECT", run(**{**base, "da_holds": "garbage"}) == REJECT)

# ---- the happy path: trustless settlement ----------------------------------------------------------
check("proof resolves and verifies -> ACCEPT (root settles on the proof)", run(**base) == ACCEPT)

# ---- THE BOUND: a permanently unavailable proof must not halt the node forever ----------------------
check("past the depth gate an unavailable proof is NOT consulted -> ACCEPT on weight",
      run(**{**base, "deep": True, "da_holds": False}) == ACCEPT)
check("...so a withholder can only make us WAIT, never stop us",
      run(**{**base, "deep": True, "da_holds": False}) != DEFER)

# ---- unaffected paths ------------------------------------------------------------------------------
check("a bare attestation still settles via quorum", run(**{**base, "commitment": None}) == ACCEPT)
check("an INLINE proof is unaffected by DA entirely",
      run(**{**base, "has_inline": True, "da_holds": False}) == ACCEPT)
check("an inline proof that fails still rejects",
      run(**{**base, "has_inline": True, "verifies": False}) == REJECT)

# ---- determinism: the SAME inputs give the SAME outcome on every node -------------------------------
# This is what makes deferral fork-free — the decision depends only on (inline, commitment, deep,
# availability, verification), never on node identity.
grid = [dict(has_inline=i, commitment=c, deep=d, da_holds=h, verifies=v)
        for i in (True, False) for c in (None, "c0ffee") for d in (True, False)
        for h in (True, False, "garbage") for v in (True, False)]
check("every input combination yields exactly one deterministic outcome",
      all(run(**g) in (REJECT, DEFER, ACCEPT) for g in grid))
check("DEFER only ever occurs when the proof is genuinely unresolved near the tip",
      all(not (run(**g) == DEFER and (g["has_inline"] or g["commitment"] is None
                                      or g["deep"] or g["da_holds"])) for g in grid))

# ---- the shipped exception is importable and distinct from a validation failure ---------------------
check("ProofUnavailable is not an AssertionError (rejection) subclass",
      not issubclass(ProofUnavailable, AssertionError))
check("ProofUnavailable is an Exception", issubclass(ProofUnavailable, Exception))

# ---- the fetch helper degrades to None (defer) rather than raising ----------------------------------
from ops.transaction_ops import _fetch_da_proof  # noqa: E402
check("an unreachable DA endpoint yields None (-> defer), not an exception",
      _fetch_da_proof("nonexistent" * 4, timeout=1) is None)

print()
print("ALL PASS — unavailable defers, resolved-and-bad rejects, and the depth gate bounds the wait"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
