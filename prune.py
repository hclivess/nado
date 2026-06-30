from glob import glob
from os import remove

from ops.block_ops import get_block_ends_info, set_latest_block_info, set_earliest_block_info
from ops.data_ops import get_home
from ops.log_ops import get_logger
from ops import kv_ops

logger = get_logger(file="prune.log", logger_name="prune_logger")
input("Please make sure node is not running before continuing... Press any key when ready.\n")

kv_ops.init_env(get_home())

block_ends = get_block_ends_info(logger=logger)

block_number_to_keep = block_ends["latest_block"]["block_number"]
block_hash_to_keep = block_ends["latest_block"]["block_hash"]

# --- prune the transaction index: drop every tx not in the kept block (primary + DUPSORT
#     secondaries; tx_index_del removes the exact dups using the indexed body's sender/recipient) ---
logger.info("Pruning transaction index")
with kv_ops.write_txn():
    for txid, body in kv_ops.iter_tx_index():
        if body["block_number"] != block_number_to_keep:
            kv_ops.tx_index_del(txid=txid, block_number=body["block_number"],
                                sender=body["sender"], recipient=body["recipient"])

# --- prune the block number<->hash index: keep only the kept block ---
logger.info("Pruning block index")
with kv_ops.write_txn():
    for number, block_hash in kv_ops.iter_block_numbers():
        if number != block_number_to_keep:
            kv_ops.block_index_del(block_number=number, block_hash=block_hash)

logger.info("Pruning blocks")
block_files = glob(f"{get_home()}/blocks/*.block")

for file in block_files:
    if block_hash_to_keep not in file:
        remove(file)

set_latest_block_info(block_ends["latest_block"], logger=logger)
set_earliest_block_info(block_ends["latest_block"], logger=logger)

logger.info("Finished successfully")
