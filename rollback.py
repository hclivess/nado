from account_ops import change_balance, increase_produced_count
from block_ops import load_block_from_hash, set_latest_block_info, unindex_block
from transaction_ops import unindex_transactions


def rollback_one_block(logger, lock, block) -> dict:
    """successful execution mandatory"""
    with lock:

        previous_block = load_block_from_hash(
            block_hash=block["parent_hash"], logger=logger)

        if previous_block:
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

            unindex_transactions(block, logger=logger)
            unindex_block(block, logger=logger)

            return previous_block

        else:
            return block
