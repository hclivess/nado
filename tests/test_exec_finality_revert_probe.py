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

from execnode.execnode import finality_reverted, probe_height

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


# ---- the probe must actually be wired into the loop --------------------------------------------------
def t_the_loop_runs_the_probe_and_resets_on_it():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "execnode.py"), encoding="utf8").read()
    assert "divergence_polls += 1" in src, "the probe counter is not advanced in the tail loop"
    assert "if divergence_polls >= DIVERGENCE_PROBE_POLLS:" in src, "the probe is never reached"
    assert "if finality_reverted(state.block_hashes, _probe, _pb):" in src, \
        "the loop no longer acts on the probe"
    assert "_reset_states_to_genesis(" in src, "a detected finality revert no longer recovers"
    # It must NOT be nested inside the cursor>finalized guard — that nesting is the bug being fixed.
    probe_at = src.index("divergence_polls += 1")
    inversion_at = src.index("if state.cursor > finalized:")
    assert probe_at < inversion_at, "the probe sits inside the inversion guard it exists to bypass"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "FINALITY REVERTS ARE DETECTED AND RECOVERED")
sys.exit(1 if FAILS else 0)
