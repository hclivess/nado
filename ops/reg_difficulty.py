"""
Registration-rate PoSW difficulty (doc/ip-spoofing-and-sybil.md) — CONSENSUS-BOUND.

The required PoSW work for a `register` scales with recent registration volume, so a sudden flood of identities
gets progressively more expensive. This is enforced in validate_transaction: every node recomputes the required
difficulty from the committed recert index and REJECTS a registration whose PoSW is below it. An attacker who
edits their own node to skip the client-side work simply produces proofs that every HONEST node rejects — the
difficulty is not a client courtesy, it is a validity rule.

Determinism: the difficulty is keyed off the FINALIZED PoSW ANCHOR epoch (the anchor is max_block −
POSW_ANCHOR_OFFSET, already ≥ FINALITY_DEPTH deep), so the recert counts it reads are settled and identical on
every node. Self-scaling: difficulty is the recent registration rate measured against a longer trailing-average
baseline (with a floor), so a normal-sized, healthy network sits at 1× and only abnormal bursts are throttled.
"""
from protocol import (POSW_T, POSW_DIFF_WINDOW, POSW_DIFF_TRAIL, POSW_DIFF_FLOOR, POSW_DIFF_MAX_MULT)
from ops import kv_ops


def difficulty_multiplier(anchor_epoch: int) -> int:
    """Integer PoSW multiplier for a registration anchored at `anchor_epoch`. 1× under normal load; rises as the
    recent registration rate exceeds the trailing-average baseline, capped at POSW_DIFF_MAX_MULT."""
    if anchor_epoch <= 0:
        return 1
    recent = kv_ops.recert_count_in_window(anchor_epoch - POSW_DIFF_WINDOW + 1, anchor_epoch)
    trail = kv_ops.recert_count_in_window(anchor_epoch - POSW_DIFF_TRAIL + 1, anchor_epoch)
    baseline = max(POSW_DIFF_FLOOR, trail * POSW_DIFF_WINDOW // POSW_DIFF_TRAIL)
    return min(POSW_DIFF_MAX_MULT, max(1, recent // baseline))


def required_posw_t(anchor_epoch: int) -> int:
    """The CONSENSUS number of sequential PoSW steps a registration anchored at `anchor_epoch` must prove =
    POSW_T × difficulty_multiplier. Recomputed by every node in validation and enforced against the proof."""
    return POSW_T * difficulty_multiplier(anchor_epoch)
