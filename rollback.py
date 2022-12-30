import os
import time

import msgpack

from account_ops import reflect_transaction, change_balance, increase_produced_count
from block_ops import load_block_from_hash, set_latest_block_info
from data_ops import get_home
from transaction_ops import unindex_transaction
from sqlite_ops import DbHandler


def rollback_one_block(logger, lock, block_message) -> dict:
    #print("rollback triggered for", block_message)
    with lock:
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

            set_latest_block_info(block=previous_block,
                                  logger=logger)

            block_handler = DbHandler(db_file=f"{get_home()}/index/blocks.db")
            block_handler.db_execute(
                query=f"DELETE FROM block_index WHERE block_number = '{block_message['block_number']}'")
            block_handler.close()

            block_data = f"{get_home()}/blocks/{block_message['block_hash']}.block"
            while os.path.exists(block_data):
                try:
                    os.remove(block_data)
                except Exception as e:
                    logger.error(f"Failed to remove {block_data}: {e}, retrying")
                    time.sleep(1)

            logger.info(f"Rolled back {block_message['block_hash']} successfully")

        except Exception as e:
            logger.error(f"Failed to remove block {block_message['block_hash']}: {e}")

        finally:
            return previous_block
