"""
FFG-lite objective finality (#6): justify/finalize epoch CHECKPOINTS from bonded attestations.

A checkpoint is the first block of an epoch, block E*EPOCH_LENGTH. Bonded validators ATTEST the current
epoch's checkpoint (one attestation per validator per epoch — uniqueness enforced by the attestation
index, so no on-chain double-vote). A checkpoint JUSTIFIES when the attesting bonded shares exceed
FFG_NUM/FFG_DEN of the total bonded shares, and FINALIZES with slashable-stake backing once it AND its
child checkpoint are both justified (two-consecutive).

SAFETY NOTE: this is an ADDITIONAL, observable, *accountable* finality signal. It does NOT replace the
time-based finality floor (#17 step 1), which is usually deeper and guarantees liveness (finalized_height
keeps advancing even if attestations stall). So FFG can never stall the chain — it only records the
stronger, stake-attested finality point that is FOLDED INTO the enforced floor (core_loop.incorporate_block:
# finalized_height = max(depth floor, ffg_finalized)) so it is objectively un-reorgable, plus exposed in /status.

Pure, deterministic, integer-only over committed state.
"""
from ops import kv_ops
from ops.account_ops import get_bonded_registry
from ops.mining_ops import total_bonded_shares, selection_shares
from protocol import FFG_NUM, FFG_DEN, EPOCH_LENGTH

# how many epochs back to scan for a finalizable checkpoint (finality is fresh; a small window suffices)
_FFG_LOOKBACK_EPOCHS = 8


def checkpoint_justified(epoch: int, checkpoint_hash: str, bonded_registry: dict) -> bool:
    """True when the DUTY-COMMITTEE SEATS attesting (epoch, checkpoint_hash) STRICTLY EXCEED
    FFG_NUM/FFG_DEN of the epoch's total committee seats (doc/consensus-aggregation.md). The
    committee (mining_ops.duty_committee over beacon(epoch)) replaces the old whole-registry
    denominator + inactivity leak: seats are stake-weighted draws, so the seat quorum converges on
    the stake quorum while bounding the per-epoch consensus load to O(seats) at ANY validator
    count; resampling every epoch IS the inactivity handling (a dark seat blocks only its own
    epoch's justification, and FFG stays additive — the depth floor still advances). Deterministic:
    committee + attestations derive from committed state. Integer comparison, no floats."""
    from ops.block_ops import duty_committee_for_epoch
    try:
        committee = duty_committee_for_epoch(epoch)
    except Exception:
        return False                        # beacon anchor unavailable -> cannot justify (fail closed)
    total = sum(committee.values())
    if total == 0:
        return False
    attested = {v for v, h in kv_ops.attestations_for_epoch(epoch)
                if h == checkpoint_hash and v in bonded_registry}
    attesting = sum(seats for v, seats in committee.items() if v in attested)
    return attesting * FFG_DEN > total * FFG_NUM


def ffg_finalized_checkpoint(current_epoch: int) -> int:
    """Highest epoch E (< current_epoch) whose checkpoint AND its child (E+1) are BOTH justified — its
    checkpoint block E*EPOCH_LENGTH is FINALIZED with stake backing. Returns that block height, or 0.
    Uses the current committed bonded registry (deterministic; v1 bonds are stable across the chain)."""
    from ops.block_ops import get_block_hash_by_number
    reg = get_bonded_registry()
    if total_bonded_shares(reg) == 0:
        return 0
    floor = max(0, current_epoch - _FFG_LOOKBACK_EPOCHS)
    e = current_epoch
    while e > floor:
        h_e = get_block_hash_by_number(e * EPOCH_LENGTH)
        h_child = get_block_hash_by_number((e + 1) * EPOCH_LENGTH)
        if (h_e and h_child
                and checkpoint_justified(e, h_e, reg)
                and checkpoint_justified(e + 1, h_child, reg)):
            return e * EPOCH_LENGTH
        e -= 1
    return 0
