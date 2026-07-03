"""
Execution-layer SETTLEMENT (Phase 2): derive the canonical SETTLED execution-layer state root from bonded
validators' settlement attestations. A (exec_cursor, state_root) is SETTLED when the bonded shares
attesting it strictly exceed SETTLE_NUM/SETTLE_DEN of the total bonded shares — the same stake-quorum
shape as FFG-lite finality (ops/attestation_ops). Pure, deterministic, integer-only over committed state.

This module IS the pluggable verifier seam. settlement_justified() is the single predicate L1 uses to
accept an execution-layer state root. Phase-2a implements it as a bonded-stake quorum; Phase-2b can
replace it with verification of ONE succinct validity proof (a STARK over the blob→state transition)
behind the exact same signature — nothing else in L1 changes.
"""
from ops import kv_ops
from ops.account_ops import get_bonded_registry
from ops.mining_ops import total_bonded_shares, selection_shares
from protocol import SETTLE_NUM, SETTLE_DEN


def settlement_justified(cursor: int, state_root: str, bonded_registry: dict) -> bool:
    """True when the bonded shares attesting (cursor, state_root) STRICTLY EXCEED SETTLE_NUM/SETTLE_DEN of
    the total bonded shares. Integer comparison (attesting*SETTLE_DEN > total*SETTLE_NUM) — no floats."""
    total = total_bonded_shares(bonded_registry)
    if total == 0:
        return False
    attesting = 0
    for validator, root in kv_ops.settlements_for_cursor(cursor):
        if root == state_root and validator in bonded_registry:
            attesting += selection_shares(bonded_registry[validator]["bonded"])
    return attesting * SETTLE_DEN > total * SETTLE_NUM


def latest_settled():
    """The (exec_cursor, state_root) with the HIGHEST cursor currently justified by the bonded quorum, or
    (-1, None) if none. DERIVED (not a stored watermark) so it is revert-safe — rolling back a settle tx
    removes its attestation and this recomputes. Uses the current committed bonded registry."""
    reg = get_bonded_registry()
    if total_bonded_shares(reg) == 0:
        return (-1, None)
    best = (-1, None)
    for cursor in kv_ops.settlement_cursors():
        if cursor <= best[0]:
            continue
        seen = set()
        for _v, root in kv_ops.settlements_for_cursor(cursor):
            if root in seen:
                continue
            seen.add(root)
            if settlement_justified(cursor, root, reg):
                best = (cursor, root)
                break
    return best


def _vote_activated(info: dict, current_epoch: int) -> bool:
    """A validator's bonded stake counts toward a treasury vote only once it has AGED
    TREASURY_VOTE_ACTIVATION_EPOCHS (anti flash/exchange capture). bond_since == 0 is genesis/fully-aged."""
    from protocol import TREASURY_VOTE_ACTIVATION_EPOCHS
    bs = int(info.get("bond_since", 0) or 0)
    return bs == 0 or (current_epoch - bs) >= TREASURY_VOTE_ACTIVATION_EPOCHS


def treasury_justified(pid: str, bonded_registry: dict, current_epoch: int) -> bool:
    """True when the ACTIVATED bonded shares that voted to approve treasury proposal `pid` STRICTLY EXCEED
    SETTLE_NUM/SETTLE_DEN of the total ACTIVATED bonded shares — the identical 2/3 stake quorum shape as
    settlement/finality (approving*SETTLE_DEN > total*SETTLE_NUM, integer-only). The electorate is bonded
    stake that has aged past TREASURY_VOTE_ACTIVATION_EPOCHS, so freshly-bonded stake neither approves NOR
    dilutes the vote. Sole authorization for a treasury_execute payout; the bonded lane IS the multisig.
    (doc/treasury.md §3.3)"""
    voters = set(kv_ops.treasury_voters(pid))
    total, approving = 0, 0
    for validator, info in bonded_registry.items():
        if not _vote_activated(info, current_epoch):
            continue                                            # fresh stake: outside the electorate entirely
        w = selection_shares(info["bonded"])
        total += w
        if validator in voters:
            approving += w
    if total == 0:
        return False
    return approving * SETTLE_DEN > total * SETTLE_NUM
