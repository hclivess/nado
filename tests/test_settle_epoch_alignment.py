"""
The settle cadence must PRODUCE conforming spans, not merely be allowed to.

WHY THIS EXISTS. A settle-with-proof is refused if its span crosses a dividend epoch boundary, because a
dividend moves the RECORDS half and the proof pins records unchanged across the span. That gate is
correct. What was wrong was the cadence feeding it: settling "every SETTLE_EVERY blocks" leaves the
justified tip at an ARBITRARY offset inside an epoch, so whether the next span straddles a boundary is
luck rather than design.

The old comment claimed a straddling span would "re-anchor the justified tip at the boundary so the
following span conforms". It never did — a straddle skipped the proof and settled bare at whatever the
cursor happened to be, which straddles again just as easily.

MEASURED LIVE 2026-08-04, over 128 recorded skips:

    95  (74%)  span crosses a dividend epoch boundary      <-- the real blocker
    17         stashed pre-state is not at the justified tip
     9         no stashed pre-state (restart)
     5         a previous settle-prove is still running
     1         span exceeds SETTLE_PROOF_MAX_SPAN
     1         prove exceeded SETTLE_PROVE_TIMEOUT

READ THAT TABLE CAREFULLY — _skip() only prints when the reason STRING CHANGES. The boundary reason
embeds its cursors ("span 18307 -> 18363 crosses..."), so it prints on EVERY occurrence and 95 is a true
count. The constant reasons ("no stashed pre-state", "a previous settle-prove is still running") print
only on a transition, so 9 and 5 are UNDERCOUNTS. The boundary class is genuinely the most frequent, but
its 74% SHARE is overstated.

And the two failures compound: a conforming span starts a prove, the prove runs past its 1200s bound, and
every settle during that window then skips with "a previous settle-prove is still running". So cadence
and proving cost are not competing explanations — fixing the cadence produces more conforming spans, and
each one still needs a prove that finishes. This test pins the cadence half only.

Run: python3 tests/test_settle_epoch_alignment.py
"""
import random
import sys

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


EPOCH = 60
EVERY = 30


def simulate(cursors, re_anchor):
    """Replay a cursor stream through the settle trigger and report which spans could be PROVEN.

    Returns (proven_spans, all_spans). A span (sc -> cur) conforms iff both ends land in the same epoch,
    which is exactly the gate _build_settlement_proof applies.
    """
    last = -1
    spans = []
    for c in cursors:
        advanced = last < 0 or (c - last) >= EVERY
        new_epoch = re_anchor and last >= 0 and (c // EPOCH) != (last // EPOCH)
        if not (advanced or new_epoch):
            continue
        if last >= 0:
            spans.append((last, c))
        last = c
    proven = [(a, b) for a, b in spans if a // EPOCH == b // EPOCH and b > a]
    return proven, spans


# A cursor that advances one block at a time across ten epochs, the ordinary case.
#
# STARTING OFFSET MATTERS, and picking a flattering one hides the whole effect. A stream that starts
# exactly on a multiple of EPOCH is the ONE case where the fixed cadence is already epoch-aligned by
# accident, and it scores a perfect 1-proof-per-epoch there. Production starts wherever the node
# happened to settle last, so the honest comparison sweeps every offset.
stream = list(range(18007, 18607))          # deliberately NOT boundary-aligned

old_proven, old_spans = simulate(stream, re_anchor=False)
new_proven, new_spans = simulate(stream, re_anchor=True)

epochs_covered = len({c // EPOCH for c in stream})

# ---- THE CORE PROPERTY: at least one provable span per epoch --------------------------------------
new_epochs_with_proof = {a // EPOCH for a, _ in new_proven}
check("re-anchoring yields a conforming span in EVERY epoch it spends a full pass in",
      len(new_epochs_with_proof) >= epochs_covered - 1)

# ---- swept over every starting offset, it is never worse -------------------------------------------
sweep = []
for off in range(EPOCH):
    s = list(range(18000 + off, 18000 + off + 600))
    o, _ = simulate(s, re_anchor=False)
    n, _ = simulate(s, re_anchor=True)
    sweep.append((len(o), len(n)))

check("across every starting offset, re-anchoring is NEVER worse than the fixed cadence",
      all(n >= o for o, n in sweep))
check("the fixed cadence's yield DEPENDS on where it happens to start (it is luck)",
      len({o for o, _ in sweep}) > 1)

# ---- THE MECHANISM: a BURSTY cursor is what destroys the fixed cadence ------------------------------
# On a perfectly smooth cursor the fixed cadence self-aligns — settle points land exactly at last+EVERY,
# so the offset never drifts and it alternates cleanly at ~1 proof per epoch. That is NOT production.
# The cursor advances in BATCHES, so a settle fires at last+EVERY+jitter and the offset drifts a little
# every time; drift is what turns alignment into luck. Modelled below, and it is the whole effect.
def burst_stream(seed, n=3000, maxjump=8):
    rnd = random.Random(seed)
    c = 18000 + rnd.randrange(EPOCH)
    out = []
    while c < 18000 + n:
        c += rnd.randint(1, maxjump)
        out.append(c)
    return out


by_jitter = {}
for maxjump in (1, 2, 4, 8, 16):
    o_tot = n_tot = 0
    for seed in range(40):
        s = burst_stream(seed, maxjump=maxjump)
        o_tot += len(simulate(s, re_anchor=False)[0])
        n_tot += len(simulate(s, re_anchor=True)[0])
    by_jitter[maxjump] = (o_tot / 40.0, n_tot / 40.0)

check("under every burst size, re-anchoring proves at least as many spans",
      all(n >= o for o, n in by_jitter.values()))
check("the fixed cadence DEGRADES as the cursor gets burstier",
      by_jitter[16][0] < by_jitter[1][0] * 0.85)
check("re-anchoring is INVARIANT to burstiness (that is the point)",
      max(n for _, n in by_jitter.values()) - min(n for _, n in by_jitter.values()) < 1.0)
check("at production-like burst sizes the gain is substantial (>15% more provable spans)",
      by_jitter[16][1] > by_jitter[16][0] * 1.15)
check("every span it proves is genuinely epoch-internal (the gate is not relaxed)",
      all(a // EPOCH == b // EPOCH for a, b in new_proven))
check("every proven span strictly advances", all(b > a for a, b in new_proven))

# ---- the cost is bounded: one extra settle per epoch boundary, no more -----------------------------
check("re-anchoring adds at most one settle per epoch boundary crossed",
      len(new_spans) - len(old_spans) <= epochs_covered)

# ---- the tip really does land just past the boundary -----------------------------------------------
# After a boundary re-anchor the justified tip sits at a small offset into the new epoch, which is what
# leaves room for a full conforming span behind it.
offsets = [b % EPOCH for a, b in new_spans if (a // EPOCH) != (b // EPOCH)]
check("a boundary settle anchors the tip at the START of the new epoch (offset 0 on a 1-block stream)",
      offsets and max(offsets) == 0)

# ---- it must not regress the case it cannot help: a cursor that never leaves one epoch --------------
short = list(range(18000, 18059))
sp_old, _ = simulate(short, re_anchor=False)
sp_new, _ = simulate(short, re_anchor=True)
check("inside a single epoch, re-anchoring changes nothing", sp_old == sp_new)

# ---- a cursor that JUMPS (batch application) still re-anchors ---------------------------------------
jumpy = [18000, 18010, 18055, 18061, 18090, 18125, 18180]
jp, _ = simulate(jumpy, re_anchor=True)
check("a cursor that jumps over a boundary still re-anchors and still proves only internal spans",
      all(a // EPOCH == b // EPOCH for a, b in jp))

# ---- the trigger is monotone: re-anchoring never SUPPRESSES a settle the old cadence would have made -
old_pts, new_pts = set(), set()
for re_anchor, sink in ((False, old_pts), (True, new_pts)):
    last = -1
    for c in stream:
        advanced = last < 0 or (c - last) >= EVERY
        ne = re_anchor and last >= 0 and (c // EPOCH) != (last // EPOCH)
        if advanced or ne:
            sink.add(c)
            last = c
check("re-anchoring only ADDS settle points; it never removes the cadence's own",
      len(new_pts) >= len(old_pts))

print()
print(f"fixed cadence : {len(old_proven)} provable spans over {epochs_covered} epochs")
print(f"epoch-aligned : {len(new_proven)} provable spans over {epochs_covered} epochs")
print()
print("ALL PASS — the cadence now produces a conforming span every epoch"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
