import time

from ops.account_ops import change_balance, increase_produced_count, index_totals, get_totals
from ops.block_ops import load_block_from_hash, set_latest_block_info, unindex_block
from ops.transaction_ops import unindex_transactions


def rollback_one_block(logger, block) -> dict:
    """successful execution mandatory"""
    while True:
        try:
            previous_block = load_block_from_hash(
                block_hash=block["parent_hash"], logger=logger)

            set_latest_block_info(block=previous_block,
                                  logger=logger)

            change_balance(
                address=block["block_creator"],
                amount=block["block_reward"],
                revert=True,
                logger=logger
            )

            increase_produced_count(address=block["block_creator"],
                                    amount=block["block_reward"],
                                    revert=True,
                                    logger=logger
                                    )

            totals = get_totals(block=block, revert=True)

            index_totals(produced=totals["produced"],
                         fees=totals["fees"],
                         burned=totals["burned"],
                         block_height=block["block_number"])

            unindex_transactions(block=block,
                                 logger=logger,
                                 block_height=block['block_number'])

            unindex_block(block, logger=logger)

            logger.info(f"Rolled back {block['block_hash']} successfully")

            return previous_block

        except Exception as e:
            logger.error(f"Retrying rollback due to: {e}")
            time.sleep(1)
