from account_ops import change_balance, increase_produced_count
from block_ops import load_block_from_hash, set_latest_block_info, unindex_block
from transaction_ops import unindex_transactions


def rollback_one_block(logger, lock, block) -> dict:
    """successful execution mandatory"""
    with lock:
        while True:
            try:
                previous_block = load_block_from_hash(
                    block_hash=block["parent_hash"], logger=logger
                )
                set_latest_block_info(block=previous_block,
                                      logger=logger)
                break
            except Exception as e:
                logger.error(f"Failed to set to previous block: {e}")

        while True:
            try:
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
                break
            except Exception as e:
                logger.error(f"Failed to adjust account: {e}")

        unindex_transactions(block)
        unindex_block(block)

        return previous_block
