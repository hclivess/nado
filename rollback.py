
from ops.account_ops import (index_totals, get_totals, get_finalized_height, set_finalized_height,
                             get_hard_finality)
from ops.block_ops import load_block_from_hash, set_latest_block_info, unindex_block
from ops import kv_ops
from ops.transaction_ops import unindex_transactions
from ops.reward_ops import credit_block_reward, apply_treasury_burn


class MissingParentError(Exception):
    """The block we would roll back to is not on disk (e.g. a snapshot-bootstrapped node
    asked to roll back past its checkpoint, or a roll back at/below genesis). The caller
    must ABORT the rollback and trigger a fresh resync — the old code passed the resulting
    False into set_latest_block_info(False['block_hash']) inside a `while True: sleep(1)`,
    which both crashed and then spun the single core thread forever (audit item LO-2)."""


class FinalityViolation(Exception):
    """The reorg would revert a HARD-FINALIZED block (the new tip would fall at/below hard_finality —
    the FFG quorum checkpoint folded with the wide liveness backstop; see protocol.FINALITY_HARD_BACKSTOP).
    ENFORCED FINALITY (#17): that prefix is immutable, so we REFUSE the rollback rather than undo it.
    The caller aborts the cascade and resyncs forward only. This is what bounds 51%/long-range rollback:
    no amount of attacker chain weight can reorg below a floor a >2/3 bonded quorum signed.

    The DEPTH floor (finalized_height) no longer refuses anything: treating a 45-block local observation
    as immutable is what made every deep-but-legitimate reorg a floor-crossing 'wedge recovery' (2026-08-17:
    eight in one day, two archive truncations). Crossing it is legal above the hard floor, and this module
    lowers it as it crosses so the depth cadence re-derives on the new branch."""


def rollback_one_block(logger, block, depth: int = 1) -> dict:
    """Revert the tip block and return the new tip (its parent). `depth` is this block's position
    in the current reorg burst (1 for the tip, 2 for its parent, …) — passed straight to the reorg
    telemetry so the Stats tab can chart the deepest single reorg per day, not just the block total.

    All reversals run in ONE LMDB write transaction, so the rollback is all-or-nothing
    (mirrors the atomic incorporate path): a crash mid-rollback leaves the block fully applied,
    not half-reverted. We never spin and never crash on a missing parent (audit LO-2)."""
    previous_block = load_block_from_hash(block_hash=block["parent_hash"], logger=logger)
    if not previous_block:
        raise MissingParentError(
            f"Parent {block.get('parent_hash')} of {block.get('block_hash')} is not on disk; "
            f"cannot roll back — resync required")

    # ENFORCED FINALITY (#17, two-floor): never revert a HARD-finalized block. Reverting tip `block`
    # moves the tip to previous_block; if that parent is below the hard floor, `block` itself is inside
    # the quorum-signed immutable prefix -> refuse.
    # (previous_block.number < F  <=>  block.number <= F  <=>  block is within the immutable prefix.)
    hard = get_hard_finality()
    if previous_block["block_number"] < hard:
        raise FinalityViolation(
            f"Refusing to roll back block {block.get('block_number')} below hard finality "
            f"{hard} (new tip would be {previous_block['block_number']})")
    # Crossing the DEPTH floor is legal above the hard floor — but the floor must FOLLOW the tip down, or
    # (a) this same check on the next block in the cascade would compare against a stale high value if it
    # still used finalized_height, and (b) incorporate's max(prev, ...) would keep the old branch's depth
    # finality forever. Lower it to the new tip; it re-advances at depth cadence on the branch we land on.
    # Floored at `hard` for the invariant hard <= finalized at all times.
    finalized_height = get_finalized_height()
    if previous_block["block_number"] < finalized_height:
        set_finalized_height(max(hard, previous_block["block_number"]))

    # Reverse the SAME lane-aware split incorporate_block applied (so producer + treasury + DIVIDEND_POOL
    # balances and the produced metric return exactly to prior), the totals, and the indexes — atomically.
    # Single source (ops.reward_ops.credit_block_reward) shared with apply, so the two can never drift.
    with kv_ops.write_txn():
        # IDLE-GC revert FIRST (mirror of apply running last in incorporate): restores any account
        # docs / recert rows / watermarks the boundary block's sweep removed (ops/gc_ops.py). A
        # non-boundary block has no record and this is a no-op.
        from ops.gc_ops import revert_idle_gc
        revert_idle_gc(block["block_number"], logger)

        credit_block_reward(block, logger=logger, revert=True)
        apply_treasury_burn(block, logger=logger, revert=True)   # restore any anti-hoard burn at this height

        totals = get_totals(block=block, revert=True)
        index_totals(produced=totals["produced"], fees=totals["fees"])

        unindex_transactions(block=block, logger=logger, block_height=block['block_number'])
        # Mirror of incorporate_block's exec_summary_put — the summary is per-HEIGHT, and a reorg replaces
        # the block at that height, so a stale summary would describe the orphaned body's calls. Dropping it
        # here means the replacement block's own incorporate rewrites it (and a span over an un-summarised
        # height is refused rather than mis-bound).
        kv_ops.exec_summary_del(block["block_number"])
        # RESTORE the summary this block's application retention-pruned. incorporate_block does
        # put(h) AND del(h-RETENTION); reverting only the put leaves a permanent hole in the window,
        # which forks settle-with-proof block VALIDITY (validate_transaction reads every summary in a
        # proof span) and desynchronises the execsum set between honest nodes.
        _rev = kv_ops.execsum_revert_pop(block["block_number"])
        if _rev:
            _ph, _doc = _rev
            kv_ops.exec_summary_put(_ph, bool(_doc.get("inert")), _doc.get("calls") or {})
        unindex_block(block, logger=logger)

    set_latest_block_info(latest_block=previous_block, logger=logger)

    # ROLLING-NODE SYNC: discard any persisted state checkpoint above the new tip — it captured a state
    # that is being reverted. Advertised checkpoints are always finalized (and finality refuses this
    # rollback above the floor), so in practice this only clears a not-yet-final checkpoint.
    try:
        from ops import snapshot_ops
        snapshot_ops.drop_checkpoints_above(previous_block["block_number"])
    except Exception as e:
        logger.error(f"checkpoint cleanup on rollback failed (non-fatal): {e}")

    logger.info(f"Rolled back {block['block_hash']} successfully")

    # per-day reorg telemetry (ops/rollback_stats.py, /rollback_stats, the Stats-tab chart): count
    # this block and advance the day's max reorg depth to `depth`. Best effort: a failed count must
    # never fail the rollback that already committed above.
    try:
        from ops import rollback_stats
        rollback_stats.record(depth)
    except Exception:
        pass
    return previous_block
