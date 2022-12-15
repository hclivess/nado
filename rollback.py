import os
import time

import msgpack

from account_ops import reflect_transaction, change_balance, increase_produced_count
from block_ops import load_block_from_hash, get_latest_block_info, set_latest_block_info
from data_ops import get_home
from transaction_ops import unindex_transaction


def rollback_one_block(logger, lock) -> dict:
    with lock:
        block_message = get_latest_block_info(logger=logger)

        try:
            previous_block = load_block_from_hash(
                block_hash=block_message["parent_hash"], logger=logger
            )

            for transaction in block_message["block_transactions"]:
                unindex_transaction(transaction, logger)
                reflect_transaction(transaction, revert=True)

            change_balance(
                address=block_message["block_creator"],
                amount=-block_message["block_reward"],
            )

            increase_produced_count(address=block_message["block_creator"],
                                    amount=block_message["block_reward"],
                                    revert=True)

            set_latest_block_info(block_message=previous_block,
                                  logger=logger)

            with open(f"{get_home()}/blocks/block_numbers/index.dat", "wb") as outfile:
                msgpack.pack({"last_number": previous_block["block_number"]}, outfile)

            try:
                os.remove(f"{get_home()}/blocks/block_numbers/{block_message['block_number']}.dat")
            except Exception as e:
                logger.error(f"Error deleting block number information: {e}")

            try:
                os.remove(f"{get_home()}/blocks/{block_message['block_hash']}.block")
            except Exception as e:
                logger.error(f"Error deleting block data: {e}")

            logger.info(f"Rolled back {block_message['block_hash']} successfully")

            return previous_block

        except Exception as e:
            logger.error(f"Failed to remove block {block_message['block_hash']}")
            raise
