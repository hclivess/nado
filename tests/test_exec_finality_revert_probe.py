"""The exec layer must notice when L1 reverts a block it already applied as FINAL.

WHY THIS FILE EXISTS. The exec node applies ONLY finalized blocks, so its stale-exec guard assumed
`cursor > finalized` was the only way its state could belong to a dead chain. Two things break that:

  * L1 CAN rewind below its own finality floor — core_loop.reanchor_candidates passes floor=0 for
    ESCALATED wedge recovery, by design.
  * The guard compares at min(max_applied, finalized). If the re-anchor lands BELOW the fork point that
    comparison sits below it too, the hashes agree, and it declares the state healthy while every block
    applied above the fork came from the abandoned chain. Then L1 rebuilds past the cursor, the inversion
    disappears, and the guard never runs again — permanent, silent, wrong balances served to users, with
    settling quietly refusing (maybe_settle won't post a proof that can't reproduce its own root).

So the probe must be standing rather than inversion-triggered, and must look HIGH rather than low.

THE OTHER HALF IS NOT LETTING IT MISFIRE. This predicate drives an automatic wipe-and-cold-replay, and on
2026-08-03 a guard that read MISSING INFORMATION as evidence destroyed this node's live state and all 25
deployed contracts. Every "I don't know" case is asserted to be a non-event here, deliberately, and there
are more of those tests than of the positive case.

Run: python3 tests/test_exec_finality_revert_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("NADO_ALLOW_PYTHON_KERNELS", "1")
# Importing execnode runs module-level init that READS state/DA/fold-cache paths relative to CWD. Point
# them at a throwaway dir so running this suite from the repo root can never read or touch the LIVE exec
# state — the same hazard that wedged prod when a test imported node modules against the real data dir.
_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp_finality_probe")
os.makedirs(_TMP, exist_ok=True)
os.environ.setdefault("NADO_EXEC_STATE", os.path.join(_TMP, "exec_state.json"))
os.environ.setdefault("NADO_EXEC_DA", os.path.join(_TMP, "exec_da"))

from execnode.execnode import (finality_reverted, probe_height, recovery_available, linkage_broken,
                               ckpt_keep, rewind_target,
                               CKPT_FINE, CKPT_FINE_SPAN, CKPT_COARSE, CKPT_COARSE_SPAN)

FAILS = []

OURS = {100: 0xAAAA, 200: 0xBBBB, 300: 0xCCCC}


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


# ---- which height we ask about -----------------------------------------------------------------------
def t_probes_the_highest_applied_block():
    """Low probes are the blindness being fixed: below the fork point both chains agree."""
    assert probe_height(OURS, 500) == 300, "probe must ask about the HIGHEST applied block"


def t_probe_is_capped_at_l1s_tip():
    """L1 cannot answer for heights it has not rebuilt after a re-anchor."""
    assert probe_height(OURS, 200) == 200
    assert probe_height(OURS, 250) == 0, "250 was never applied by us — nothing to compare"


def t_no_probe_when_there_is_nothing_to_ask():
    assert probe_height({}, 500) == 0, "empty state must not probe"
    assert probe_height(OURS, 0) == 0, "unknown tip must not probe"
    assert probe_height(OURS, -1) == 0, "nonsense tip must not probe"


# ---- the positive case: a proven disagreement --------------------------------------------------------
def t_detects_a_reverted_finalized_block():
    assert finality_reverted(OURS, 300, {"block_hash": "dddd"}) is True, \
        "a different hash at a height we applied as FINAL is a finality revert"


def t_detects_it_through_the_wrapped_reply_shape():
    """/get_block_number answers both bare and {"block": {...}}-wrapped; both must be read."""
    assert finality_reverted(OURS, 300, {"block": {"block_hash": "dddd"}}) is True


def t_agreement_is_not_divergence():
    assert finality_reverted(OURS, 300, {"block_hash": "cccc"}) is False, "same hash must be healthy"
    assert finality_reverted(OURS, 300, {"block_hash": "0xCCCC"}) is False, "0x prefix must still parse equal"


# ---- ABSENCE OF INFORMATION IS NEVER DIVERGENCE (the 2026-08-03 lesson) -------------------------------
def t_a_restarting_l1_is_not_divergence():
    assert finality_reverted(OURS, 300, None) is False, "no reply must never wipe state"
    assert finality_reverted(OURS, 300, {}) is False, "empty reply must never wipe state"


def t_a_pruned_body_is_not_divergence():
    """A rolling L1 serves {block_number} with no hash — that is silence, not disagreement."""
    assert finality_reverted(OURS, 300, {"block_number": 300}) is False


def t_a_malformed_reply_is_not_divergence():
    for reply in ({"block_hash": None}, {"block_hash": ""}, {"block_hash": "not-hex"},
                  {"block": None}, {"block_hash": 12345}, "a string", []):
        assert finality_reverted(OURS, 300, reply) is False, f"{reply!r} must not be read as divergence"


def t_a_height_we_never_applied_is_not_divergence():
    assert finality_reverted(OURS, 999, {"block_hash": "dddd"}) is False
    assert finality_reverted({}, 300, {"block_hash": "dddd"}) is False
    assert finality_reverted(None, 300, {"block_hash": "dddd"}) is False


# ---- ZERO-GAP DETECTORS: parent linkage on every apply, checkpoint hash on every status ----------------
def t_linkage_break_is_caught_on_the_very_next_block():
    """The block about to be applied must chain onto the one we applied last."""
    assert linkage_broken(OURS, 301, {"parent_hash": "dddd"}) is True, "a block not chaining onto ours is a break"
    assert linkage_broken(OURS, 301, {"parent_hash": "cccc"}) is False, "a block chaining onto ours is fine"


def t_linkage_absence_of_information_is_not_a_break():
    assert linkage_broken(OURS, 301, {}) is False
    assert linkage_broken(OURS, 301, {"parent_hash": None}) is False
    assert linkage_broken(OURS, 301, {"parent_hash": "not-hex"}) is False
    assert linkage_broken(OURS, 999, {"parent_hash": "dddd"}) is False, "we never applied 998 — nothing to compare"
    assert linkage_broken(OURS, 301, "garbage") is False
    assert linkage_broken({}, 301, {"parent_hash": "dddd"}) is False


def t_the_status_snapshot_hash_is_never_used_as_a_block_hash():
    """/status snapshot_hash is the snapshot PAYLOAD hash, not the block hash at snapshot_height. A detector
    comparing the two fired on every poll on a healthy node (2026-08-17 20:41, right after deploy) and
    marked it stranded. Pin its absence."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "execnode.py"), encoding="utf8").read()
    loop = src[src.index("async def tail_loop"):]
    assert "snapshot_disagrees" not in src, "the snapshot_hash-as-block-hash detector is back"
    assert 'status.get("snapshot_hash")' not in loop and "status[\"snapshot_hash\"]" not in loop


# ---- REWIND CHECKPOINT LADDER --------------------------------------------------------------------------
def t_ladder_keeps_a_fine_rung_per_bucket_and_coarse_rungs_deeper():
    now = 100_000
    # batch-applied checkpoints that never land on exact multiples
    cs = [now - 120, now - 620, now - 1_120, now - 1_620, now - 2_120,     # fine buckets, one aged out
          now - 9_990, now - 19_990, now - 99_990, now - 100_990]           # coarse buckets, one aged out
    keep = ckpt_keep(cs, now)
    assert now - 120 in keep and now - 620 in keep and now - 1_120 in keep and now - 1_620 in keep
    assert now - 2_120 not in keep, "a fine checkpoint past CKPT_FINE_SPAN must age out"
    assert now - 9_990 in keep and now - 19_990 in keep and now - 99_990 in keep
    assert now - 100_990 not in keep, "a coarse checkpoint past CKPT_COARSE_SPAN must age out"


def t_ladder_keeps_the_one_nearest_the_rung_boundary():
    """Oldest per bucket, so every rung boundary has a checkpoint just above it — for any fork point
    there is one at or below it within a bucket. (Newest-per-bucket left a 15k hole: see the docstring.)"""
    now = 10_000
    keep = ckpt_keep([9_010, 9_090, 9_490], now)          # all in fine bucket 18
    assert 9_010 in keep, "the checkpoint nearest the rung boundary must survive"
    assert 9_490 in keep, "and the newest overall always does"
    assert 9_090 not in keep, "the middle one is redundant"


def t_ladder_gives_every_fork_point_a_checkpoint_within_one_bucket_below():
    """The property the ladder exists for. Simulate honest batch-applied checkpoints across the whole
    coarse span and check every fork point can rewind without a hole larger than a bucket."""
    now = 200_000
    cs = list(range(7, now, 137))                          # off-rung, dense
    keep = sorted(ckpt_keep(cs, now))
    for fp in range(now - CKPT_COARSE_SPAN + CKPT_COARSE, now, 3_331):
        below = [c for c in keep if c <= fp]
        assert below, f"no checkpoint at or below fork point {fp}"
        gap = fp - max(below)
        bucket = CKPT_FINE if now - fp <= CKPT_FINE_SPAN else CKPT_COARSE
        assert gap <= bucket + 137, f"fork point {fp}: nearest checkpoint {max(below)} is {gap} below (> {bucket})"


def t_ladder_never_keeps_the_future():
    """After a rewind, checkpoints ABOVE the cursor describe the dead chain."""
    keep = ckpt_keep([500, 1_000, 1_500, 2_000], 1_200)
    assert 1_500 not in keep and 2_000 not in keep
    assert 1_000 in keep


def t_ladder_always_keeps_the_newest_at_or_below_now():
    assert 777 in ckpt_keep([777], 100_000), "even an off-rung lone checkpoint survives"


def t_rewind_target_is_the_newest_common_checkpoint_at_or_below_the_fork():
    cks = {"default": [500, 1_000, 1_500, 2_000], "ns2": [500, 1_000, 2_000]}
    assert rewind_target(cks, 1_700) == 1_000, "1500 is not common to ns2; 1000 is the newest common"
    assert rewind_target(cks, 2_500) == 2_000
    assert rewind_target(cks, 400) is None, "nothing at or below a fork below every checkpoint"
    assert rewind_target({}, 1_000) is None
    assert rewind_target({"default": []}, 1_000) is None


def t_a_rewind_never_lands_above_the_fork_point():
    """Rewinding to a checkpoint above the fork would keep dead-fork state — the whole point is to get below."""
    for fp in (999, 1_000, 1_001, 1_499):
        t = rewind_target({"default": [500, 1_000, 1_500]}, fp)
        assert t is not None and t <= fp, f"target {t} above fork point {fp}"


# ---- RECOVERY MUST ONLY EVER LAND SOMEWHERE BETTER ---------------------------------------------------
def t_a_complete_archive_permits_a_cold_replay():
    assert recovery_available({"earliest_block_height": 0}, "") == "archive"


def t_a_truncated_archive_does_not_permit_a_wipe():
    """This box today: earliest 56735. A reset would replay 56735+ onto an EMPTY state — every contract,
    every balance, the faucet — gone. That is the 2026-08-03 disaster; the wipe must not be offered."""
    assert recovery_available({"earliest_block_height": 56735}, "") == ""
    assert recovery_available({"earliest_block_height": 1}, "") == ""


def t_a_bootstrap_donor_permits_recovery_regardless_of_archive():
    assert recovery_available({"earliest_block_height": 56735}, "http://donor:9273") == "bootstrap"


def t_a_complete_archive_is_preferred_over_bootstrap():
    """Local truth first: the archive needs no third party."""
    assert recovery_available({"earliest_block_height": 0}, "http://donor:9273") == "archive"


def t_missing_or_garbage_status_permits_nothing():
    for st in (None, {}, {"earliest_block_height": None}, {"earliest_block_height": "x"}):
        assert recovery_available(st, "") == "", f"{st!r} must not authorise a wipe"


# ---- the probe must actually be wired into the loop, and wired to the ladder ---------------------------
def t_the_loop_runs_the_probe_and_recovers_through_the_ladder():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "execnode.py"), encoding="utf8").read()
    assert "divergence_polls += 1" in src, "the probe counter is not advanced in the tail loop"
    assert "if divergence_polls >= DIVERGENCE_PROBE_POLLS:" in src, "the probe is never reached"
    assert "if finality_reverted(state.block_hashes, _probe, _pb):" in src, \
        "the loop no longer acts on the probe"
    # It must NOT be nested inside the cursor>finalized guard — that nesting is the bug being fixed.
    probe_at = src.index("divergence_polls += 1")
    inversion_at = src.index("if state.cursor > finalized:")
    assert probe_at < inversion_at, "the probe sits inside the inversion guard it exists to bypass"
    # Both detectors route into ONE recovery routine.
    loop = src[src.index("async def tail_loop"):]
    assert "await _recover_from_revert(session, status, reason)" in loop, "the probe no longer recovers"
    assert "if linkage_broken(state.block_hashes, h, block):" in loop, "the per-block linkage check is gone"
    assert 'await _recover_from_revert(session, status, f"linkage break at {h}")' in loop
    assert "hash_only=1" in loop, "the probe no longer asks hash-only (blind below the body floor)"
    # The linkage check must sit BEFORE the block is applied.
    lk = loop.index("if linkage_broken(state.block_hashes, h, block):")
    ap = loop.index("if not await _apply_block(session, states, state, block, verbose=True):")
    assert lk < ap, "linkage is checked after the block was already applied"
    # The recovery ladder: rewind first; wipe only gated, keeping DA; no source -> STRANDED, not a wipe.
    rec = src[src.index("async def _recover_from_revert"):]
    rec = rec[:rec.index("\n# --- DA layer")]
    # the rewind sources include the settle stash since 162db69c, so pin the call SHAPE, not the old arg
    assert "rewind_target(" in rec and "_rewind_sources()" in rec and "_rewind_to(target)" in rec, \
        "rewind is not tried first (or no longer draws from ckpt+stash sources)"
    assert "can_replay = recovery_available(status, BOOTSTRAP)" in rec, "the wipe is no longer gated"
    assert "keep_da=True" in rec, "a finality-revert reset wipes the only DA store again"
    assert "STRANDED.update(" in rec, "the no-recovery-source case no longer records itself"
    assert rec.count("_reset_states_to_genesis(") == 1, "a reset outside the gate"
    assert rec.index("_rewind_to(target)") < rec.index("if can_replay:") < rec.index("_reset_states_to_genesis("), \
        "ladder order must be rewind -> gate -> reset"


def t_the_reset_keeps_da_when_asked():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "execnode.py"), encoding="utf8").read()
    assert "def _reset_states_to_genesis(reason=\"\", keep_da=False):" in src
    fn = src[src.index("def _reset_states_to_genesis("):]
    fn = fn[:fn.index("\ndef ", 10)]
    assert "if not keep_da:\n        _s.rmtree(DA_DIR" in fn, "DA is wiped unconditionally"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "FINALITY REVERTS ARE DETECTED AND RECOVERED")
sys.exit(1 if FAILS else 0)
