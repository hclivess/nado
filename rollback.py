import json
import os

from block_ops import load_block, get_latest_block_info, set_latest_block_info
from transaction_ops import unindex_transaction
from account_ops import reflect_transaction, change_balance, increase_produced_count


def rollback_one_block(logger, lock):
    with lock:
        block_message = get_latest_block_info(logger=logger)

        try:
            previous_block = load_block(
                block_hash=block_message["parent_hash"], logger=logger
            )

            for transaction in block_message["block_transactions"]:
                unindex_transaction(transaction)
                reflect_transaction(transaction, revert=True)

            change_balance(
                address=block_message["block_creator"],
                amount=-block_message["block_reward"],
            )

            increase_produced_count(address=block_message["block_creator"], revert=True)

            set_latest_block_info(previous_block)

            with open(f"blocks/block_numbers/index.dat", "w") as outfile:
                json.dump({"last_number": previous_block["block_number"]}, outfile)

            os.remove(f"blocks/block_numbers/{block_message['block_number']}.dat")
            os.remove(f"blocks/{block_message['block_hash']}.block")

            logger.info(f"Rolled back {block_message['block_hash']} successfully")

        except Exception as e:
            logger.error(f"Failed to remove block {block_message['block_hash']}")
            raise
