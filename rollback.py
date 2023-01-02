import os
import time

import msgpack

from account_ops import reflect_transaction, change_balance, increase_produced_count
from block_ops import load_block_from_hash, set_latest_block_info
from data_ops import get_home
from sqlite_ops import DbHandler


def rollback_one_block(logger, lock, block_message) -> dict:
    """successful execution mandatory"""
    with lock:
        while True:
            try:
                previous_block = load_block_from_hash(
                    block_hash=block_message["parent_hash"], logger=logger
                )
                break
            except Exception as e:
                logger.error(f"Failed to load previous block: {e}")

        while True:
            try:

                txs_to_unindex = []
                for transaction in block_message["block_transactions"]:
                    txs_to_unindex.append(transaction["txid"])
                    reflect_transaction(transaction, revert=True, logger=logger)

                tx_handler = DbHandler(db_file=f"{get_home()}/index/transactions.db")
                tx_handler.db_executemany("DELETE FROM tx_index WHERE txid = ?", (txs_to_unindex,))
                tx_handler.close()
                break

            except Exception as e:
                logger.error(f"Failed to unindex transactions: {e}")

        while True:
            try:
                change_balance(
                    address=block_message["block_creator"],
                    amount=-block_message["block_reward"],
                    logger=logger
                )

                increase_produced_count(address=block_message["block_creator"],
                                        amount=block_message["block_reward"],
                                        revert=True,
                                        logger=logger
                                        )
                break
            except Exception as e:
                logger.error(f"Failed to adjust account: {e}")

        while True:
            try:
                set_latest_block_info(block=previous_block,
                                      logger=logger)
                break
            except Exception as e:
                logger.error(f"Failed to adjust account: {e}")

        while True:
            try:
                block_handler = DbHandler(db_file=f"{get_home()}/index/blocks.db")
                block_handler.db_execute(
                    "DELETE FROM block_index WHERE block_number = ?", (block_message['block_number'],))
                block_handler.close()

                block_data = f"{get_home()}/blocks/{block_message['block_hash']}.block"
                break
            except Exception as e:
                logger.error(f"Failed to unindex block: {e}")

            while os.path.exists(block_data):
                try:
                    os.remove(block_data)
                except Exception as e:
                    logger.error(f"Failed to remove {block_data}: {e}, retrying")

        return previous_block
