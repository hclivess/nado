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


def t_the_pending_marker_is_recorded_before_the_lookup():
    """THE GATE HAD A HOLE ONE ROUND TRIP WIDE. MEASURED 2026-08-06 16:08:54-16:09:13: two proof-carrying
    settles 19 s apart for the same root (48582 then 48585, 7.19 MiB each), AFTER the gate shipped.

    _settle_publishing guards the publish/submit window and is cleared once the submit returns; the prove
    gate keys on _settle_pending, which was recorded only AFTER an awaited /get_settled. Between those two
    moments nothing held the tip, and a fresh prove started inside the gap. The fetch was for `pre_cursor`,
    which nothing needs immediately — so the marker goes down first and the value is filled in after.

    An unknown pre_cursor is SAFE: the resubmit path requires `_sc_now == int(_pend["pre_cursor"])`, which
    -1 can never satisfy, so it declines to resubmit rather than guessing."""
    i = SRC.index('_settle_pending[ns] = {"cursor": cur')
    j = SRC.index('/get_settled?ns={ns}"', i - 4000)
    assert j > i, "the pending marker must be recorded BEFORE the /get_settled lookup, not after"
    assert '"pre_cursor": -1' in SRC, "the marker must go down with a not-yet-known pre_cursor"
    assert '_settle_pending[ns]["pre_cursor"] =' in SRC, "pre_cursor must be filled in afterwards"


def t_the_hold_is_continuous_from_prove_to_submit():
    """THE THIRD AND ACTUAL FIX. Three guards cover the pipeline in sequence — _settle_proving (the prove),
    _settle_publishing (publish+submit), _settle_pending (the wait for the landing block). _settle_proving is
    cleared by the prove TASK's done-callback, but _settle_publishing was not set until the publish step, and
    between those two points sit the self-checks, the recursive self-verify and an awaited /get_latest_block.
    A concurrent maybe_settle pass landing in that gap sees ALL THREE clear and starts a second prove.

    MEASURED 2026-08-06 16:16:43-16:17:12, after both earlier attempts had shipped: the prove for 48650
    finished 16:16:43, its submit returned 16:17:05, and a prove for 48654 ran inside that 22-second window.
    Gating on _settle_pending (bd079982) and removing an awaited fetch before the marker (7b612e1e) could
    not help — the marker legitimately does not exist yet while the proof is still being submitted.

    Setting the publish hold the instant a proof exists makes the hold CONTINUOUS. Safe against a stall: the
    only `continue` between the set and the release is guarded by `proof is None`, and _pub_active bounds
    the flag by SETTLE_HOLD_MAX_S regardless."""
    i = SRC.index("proof = await _build_settlement_proof(")
    j = SRC.index('globals()["_settle_publishing"] = time.time()', i)
    k = SRC.index("if proof is None and (_settle_proving", i)
    assert j < k, "the publish hold must be taken BEFORE the bare-settle hold is evaluated"
    seg = SRC[i:j]
    assert "if proof is not None:" in seg, "the hold must be taken as soon as a proof exists"
    # STRIP COMMENTS BEFORE LOOKING FOR `await`. The first version of this check searched the raw segment
    # and matched the word "awaited" inside the explanatory comment right above the hold — the fifth checker
    # today that was wrong before the code was. Compare CODE, never prose.
    between = seg.split("if proof is not None:")[0].split("\n", 1)[1]
    code_only = "\n".join(l for l in between.splitlines() if not l.strip().startswith("#"))
    assert "await" not in code_only, \
        f"nothing may await between the prove returning and the hold being taken: {code_only!r}"


def t_the_pending_marker_is_RE_CHECKED_at_the_launch_point():
    """THE ACTUAL BUG, named by instrumentation after three fixes guessed wrong.

        17:47:37  SETTLE-WITH-PROOF cursor 49530                      <- marker recorded
        17:47:39  prove-gate span 49500->49534 LAUNCH — pending_cursor=49530 proving=False publishing=CLEAR

    The marker WAS set and a prove launched anyway, so the caller-side gate was never violated — it was
    STALE. `_pend_hold` is snapshotted at the top of a maybe_settle pass; _build_settlement_proof then
    spends seconds walking the span over HTTP before committing to anything, and a proof submitted inside
    that walk sets the marker after the snapshot was taken.

    bd079982 added the caller gate, 7b612e1e moved the marker earlier, d4c24872 made the publish hold
    continuous. None could help: the READ was stale, not the write. The check has to happen at the LAST
    moment before _settle_proving is set — the same reason _pub_active is re-evaluated there rather than
    trusted from the caller."""
    i = SRC.index("_pub_active = (_settle_publishing")
    j = SRC.index("_settle_proving = True", i)
    seg = SRC[i:j]
    assert "_settle_pending.get(ns) is not None" in seg, \
        "the pending marker must be RE-READ between the _pub_active check and _settle_proving = True"
    assert "pending-landing" in seg, "the re-check must skip with a named reason"


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
               ("the pending marker precedes the lookup", t_the_pending_marker_is_recorded_before_the_lookup),
               ("the hold is continuous from prove to submit", t_the_hold_is_continuous_from_prove_to_submit),
               ("the pending marker is RE-CHECKED at the launch point", t_the_pending_marker_is_RE_CHECKED_at_the_launch_point),
               ("the measurement is recorded beside the gate", t_the_measurement_is_recorded)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
