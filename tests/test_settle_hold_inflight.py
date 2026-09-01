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
# Anchored on the CONDITION'S PARTS, not on the whole line. It used to pin the exact literal
# "if proof is None and (_settle_proving or _pub_active or _pend_active):", which broke the day the hold was
# made STRICTLY STRONGER by adding `or _pend_hold` (2026-08-06, so the pass that declines to prove a second
# span does not fall through to a bare settle). A check that fails when the thing it guards gets better is
# testing the text, not the behaviour — so require each disjunct to be present instead.
# the disjunction now lives in its own `_hold = (...)` line, consumed by `if proof is None and _hold:`
_hold_line = next((l for l in src.splitlines() if l.strip().startswith("_hold = (")), "")
check("maybe_settle holds when a prove is in flight",
      all(part in _hold_line for part in ("_settle_proving", "_pub_active", "_pend_active"))
      and "if proof is None and _hold:" in src)
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

# ---- THE CEILING MUST EXCEED WHAT IT HOLDS FOR --------------------------------------------------------
# A self-expiring hold that expires DURING the pipeline hands the race straight back to the bare settles it
# exists to suppress. SETTLE_HOLD_MAX_S was SETTLE_SUBMIT_TIMEOUT_PROOF + 120 = 420 s, against a publish
# measured at 112-139 s followed by a submit budget of SETTLE_SUBMIT_TIMEOUT_PROOF (300 s) — up to ~439 s of
# pipeline under a 420 s ceiling. Observed live 2026-08-04, the block builder DROPPING the tx outright:
#     Candidate excludes pool tx 23e34dd950ea90cb: Settle proof pre_root must extend the settled tip
import re as _re
# the constant became env-overridable: `= int(os.environ.get("...", "1800"))` — read the default either way
_m = _re.search(r'^SETTLE_SUBMIT_TIMEOUT_PROOF = (?:int\(os\.environ\.get\([^,]+, "(\d+)"\)\)|(\d+))', src, _re.M)
_sub = int(_m.group(1) or _m.group(2))
_hold = eval(_re.search(r"^SETTLE_HOLD_MAX_S = (.+)$", src, _re.M).group(1),
             {"SETTLE_SUBMIT_TIMEOUT_PROOF": _sub})
PUBLISH_MEASURED = 139          # worst DA publish observed for a 118.57 MiB proof
check("the hold outlasts publish + the whole submit budget", _hold > PUBLISH_MEASURED + _sub)
check("...with real margin, not by a few seconds", _hold - (PUBLISH_MEASURED + _sub) >= 60)

# ---- ONE PIPELINE AT A TIME ---------------------------------------------------------------------------
# _settle_proving is cleared by the prove THREAD's done-callback, i.e. at "BUILT", while the publish and
# submit still lie ahead — so a SECOND prove started inside that window every cadence. Measured live, two
# BUILTs ~2 min apart on every cycle (21:47:40 / 21:49:57, then PUBLISHED 21:51:49, SETTLE 21:52:43). Both
# extend the SAME pre-state, so at most one could ever land: the second is a wasted 118 MiB proof and a
# wasted core, on the node that must also keep up with block production.
check("a second prove is refused while the previous proof is still publishing/submitting",
      "if _pub_active:" in src and "not starting a second prove that" in src)
check("...and that check reads the same publish hold the settle path uses",
      src.count("_settle_publishing\n                   and (time.time() - _settle_publishing) < SETTLE_HOLD_MAX_S") >= 1
      or src.count("(time.time() - _settle_publishing) < SETTLE_HOLD_MAX_S") >= 2)
check("the in-flight skip no longer claims it settles bare (the hold skips instead)",
      "settling bare until it finishes" not in src)

# ---- AN ACCEPTED PROOF-CARRYING SETTLE IS STILL RACING ------------------------------------------------
# A settle is an EXACT-LANDING tx: it lands at exactly max_block, so an ACCEPTED proof-carrying settle then
# WAITS IN THE MEMPOOL for minutes. The publish hold released at SUBMIT ("the attempt is over"), which is
# true of the submission and false of the transaction. Measured live 2026-08-04:
#     22:15:19 SETTLE-WITH-DA-PROOF cursor 24690   (settled tip 24660, pre_root correct, tx pooled,
#                                                   max_block 24829 — about five minutes away)
#     22:17:55 SETTLE ns=default                   <- a BARE settle carried the tip 24660 -> 24758
#     22:18:24 Candidate excludes pool tx 3492566cf165ec37: Settle proof pre_root must extend the settled tip
# The block builder then drops it from every candidate, so it never reaches a block at all.
check("an accepted proof-carrying settle is recorded as still pending", "_settle_pending[ns] = {" in src)
check("...and the hold covers it until it lands or expires", "_pend_active" in src
      and "or _pend_active" in src)
check("...resolved against L1, not assumed: landed = the tip reached its cursor",
      '_sc_now >= int(_pend["cursor"])' in src)
check("...expired = the height passed its landing block",
      '_h_now > int(_pend["max_block"])' in src)
check("a pending settle that cannot land eventually releases the tip rather than holding forever",
      "GIVING" in src and "releasing the tip" in src)
# THE REFUSED PATH RETRIES BARE, rebuilding tx and clearing `proof` while proof_da stays set — so the
# marker must key on what was ACTUALLY SUBMITTED or a bare attestation would register a hold.
check("the pending marker keys on the submitted tx, not the local proof flags",
      '_txd.get("proof") or _txd.get("proof_da")' in src)

# ---- ONE SHOT AT AN EXACT LANDING BLOCK IS A COIN FLIP ------------------------------------------------
# A settle is EXACT-LANDING (ops/block_ops._lands_flexibly deliberately excludes it), so it can only be
# included by whoever produces exactly its max_block. This validator wins ~19% of blocks (measured: 5 of 26,
# against ~14 distinct producers), and no OTHER producer can realistically include a proof-carrying settle —
# that would mean fetching 118 MiB from DA and verifying it (~21.7 s) inside a ~6 s slot.
#
# OBSERVED 2026-08-04: cursor 24870 submitted 22:33:26 for max_block 25014, NEVER excluded (the tip was
# held, pre_root stayed valid) — block 25014 was simply produced by 5828bf2e…, not us. ~5 minutes of
# proving lost to a slot lottery.
check("a missed landing block is RESUBMITTED rather than abandoned", "RESUBMITTED for" in src)
check("...reusing the proof already published to DA (an ~8 KB tx, not a reprove)",
      'proof=None, proof_da=_pend["proof_da"]' in src)
check("...only while the pre-state it proves is still the justified tip",
      '_sc_now == int(_pend["pre_cursor"])' in src)
check("...and NEVER for an inline proof, which would rebuild as a BARE settle",
      '_pend.get("proof_da")' in src)
check("retries are bounded so a proof that can never land cannot stall settlement",
      "SETTLE_RESUBMIT_MAX" in src and "GIVING" in src)
# BOUNDED BY TIME, NOT BY A COUNT. The first cut allowed 6 attempts and live they were consumed in about
# two minutes — each retry targets latest+2, so an attempt is only ~3 blocks (~18 s):
#     22:57 missed 25197 -> attempt 2 ... 22:59 missed 25210 -> attempt 6/6, then it would give up.
# The retry is nearly free (proof and DA blob reused, ~8 KB tx); what costs anything is holding the
# justified tip still. So the budget is time, which at ~18 s/attempt is ~30 shots (~0.2% miss vs 27%).
import re as _re2
_rsec = int(_re2.search(r"^SETTLE_RESUBMIT_MAX_S = (\d+)", src, _re2.M).group(1))
_rmax = int(_re2.search(r"^SETTLE_RESUBMIT_MAX = (\d+)", src, _re2.M).group(1))
check("the retry budget is a TIME bound, not an attempt count", "SETTLE_RESUBMIT_MAX_S" in src
      and "_held_for < SETTLE_RESUBMIT_MAX_S" in src)
# SIZED FROM THE MEASURED ATTEMPT RATE. Retries are CADENCE-driven, not miss-driven — one goes out on the
# next maybe_settle poll — so the real spacing is ~45 s, not the ~18 s first assumed: live, cursor 25230
# reached attempt 13 at 594s/600s. With a MEASURED 19.3% block share (301 blocks: 58 ours, 56 producers),
# 600 s bought P(miss) = 0.807^13 ~ 6%, and that cycle lost the flip after ~5 minutes of proving.
# The ceiling only binds in the tail (expected time to land ~234 s), so a bigger one is nearly free.
check("the budget allows enough ~45s attempts to make a miss unlikely", _rsec / 45 >= 20)
check("...with a count backstop far above what the time bound allows", _rmax > _rsec / 45)
check("the hold start is recorded so the budget is measurable", '"first_submitted": time.time()' in src)
# 0.81^6 ~ 0.28: still possible to miss, which is why GIVING UP must exist rather than retry forever.
check("the pending record carries what a rebuild needs",
      '"root": root' in src and '"pre_cursor"' in src and '"attempts": 1' in src)

# ---- A THROTTLE MUST DEDUPE ON THE CONDITION, NOT ON THE SENTENCE -------------------------------------
# _skip is documented as "rate-limited per (ns, reason) so a standing condition says so once, not once per
# settle". It compared the whole FORMATTED reason, and several reasons embed the moving cursor
# ("span 25399 -> 25496 crosses a dividend epoch boundary"), so the string differed on every poll and the
# standing condition logged every poll. Measured live: 25 identical epoch-boundary lines in one cycle.
check("_skip dedupes on a stable condition class", "def _skip(reason, cls=None):" in src
      and "_key = cls or reason" in src)
for _cls in ("epoch-boundary", "stale-stash", "no-advance", "span-cap"):
    check(f"...and the value-carrying skip '{_cls}' names one", f'cls="{_cls}"' in src)

# ---- A HOLD THAT CANNOT SUCCEED MUST NOT COST LIVENESS -----------------------------------------------
# MEASURED 2026-08-04: "GIVING UP after 44 attempt(s) over 1217s". 44 misses at our measured 19.3% block
# share is P ~ 1e-4 — not luck. A settle carrying proof_da is never ADMITTED by peers: _fetch_da_proof is
# bounded at 8s while a peer needs ~118 MiB from the single DA node plus ~4.4s decode and ~21.7s verify
# (~36s). After 15 minutes of gossip our pool held it and ALL THREE PEERS HELD ZERO. And since every node
# deterministically builds the WINNER's block, when we win, a peer's candidate — built from a pool without
# our tx — is what gets adopted ("Remote block: True", 0 txs).
# So the 1200s hold bought nothing and delayed settlement 20 minutes per cycle. Detect the real condition.
check("the hold gives up early if the tx never reached the peers",
      "has NOT " in src and "PROPAGATED to any of" in src)
check("...after a grace period, checked once", "SETTLE_PROPAGATION_GRACE_S" in src
      and 'prop_checked' in src)
check("...only for a DA-carried proof (an inline one propagates normally)",
      '_pend.get("proof_da") and not _pend.get("prop_checked")' in src)
check("...and a failed probe never stalls settlement", "must never stall settlement" in src)
check("the peer probe uses aiohttp, not a blocking fetch on the event loop",
      "aiohttp, NOT urllib" in src)

print()
print("ALL PASS — a node no longer races its own proof by moving the tip out from under it"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
