import time

from ops.account_ops import change_balance, increase_produced_count, index_totals, get_totals
from ops.block_ops import load_block_from_hash, set_latest_block_info, unindex_block
from ops.data_ops import get_home
from ops.sqlite_ops import transaction
from ops.transaction_ops import unindex_transactions
from protocol import split_block_reward, TREASURY_ADDRESS


class MissingParentError(Exception):
    """The block we would roll back to is not on disk (e.g. a snapshot-bootstrapped node
    asked to roll back past its checkpoint, or a roll back at/below genesis). The caller
    must ABORT the rollback and trigger a fresh resync — the old code passed the resulting
    False into set_latest_block_info(False['block_hash']) inside a `while True: sleep(1)`,
    which both crashed and then spun the single core thread forever (audit item LO-2)."""


def rollback_one_block(logger, block) -> dict:
    """Revert the tip block and return the new tip (its parent).

    All reversals run in ONE transaction on index.db, so the rollback is all-or-nothing
    (mirrors the atomic incorporate path): a crash mid-rollback leaves the block fully applied,
    not half-reverted. We never spin and never crash on a missing parent (audit LO-2)."""
    previous_block = load_block_from_hash(block_hash=block["parent_hash"], logger=logger)
    if not previous_block:
        raise MissingParentError(
            f"Parent {block.get('parent_hash')} of {block.get('block_hash')} is not on disk; "
            f"cannot roll back — resync required")

    # Reverse the SAME canonical 90/10 split incorporate_block applied (so producer + treasury
    # balances and the produced metric return exactly to prior), the totals, and the indexes —
    # atomically. The tip pointer file is advanced LAST, only after the reversal commits.
    index_db = f"{get_home()}/index/index.db"
    with transaction(index_db):
        producer_cut, treasury_cut = split_block_reward(block["block_reward"])
        change_balance(address=block["block_creator"], amount=producer_cut, revert=True, logger=logger)
        if treasury_cut:
            change_balance(address=TREASURY_ADDRESS, amount=treasury_cut, revert=True, logger=logger)
        increase_produced_count(address=block["block_creator"], amount=producer_cut, revert=True, logger=logger)

        totals = get_totals(block=block, revert=True)
        index_totals(produced=totals["produced"], fees=totals["fees"],
                     block_height=block["block_number"])

        unindex_transactions(block=block, logger=logger, block_height=block['block_number'])
        unindex_block(block, logger=logger)

    set_latest_block_info(latest_block=previous_block, logger=logger)

    logger.info(f"Rolled back {block['block_hash']} successfully")
    return previous_block
