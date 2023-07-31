import sqlite3
from glob import glob
from os import remove

from ops.block_ops import get_block_ends_info, set_latest_block_info, set_earliest_block_info
from ops.data_ops import get_home
from ops.log_ops import get_logger

logger = get_logger()
input("Please make sure node is not running before continuing... Press any key when ready.\n")

block_ends = get_block_ends_info(logger=logger)

block_number_to_keep = block_ends["latest_block"]["block_number"]
block_hash_to_keep = block_ends["latest_block"]["block_hash"]

for range_file in glob(f"{get_home()}/index/transactions/*db"):
    transactions_db = sqlite3.connect(range_file)
    transactions_c = transactions_db.cursor()
    logger.info(f"Pruning transaction index of {range_file}")
    transactions_c.execute("DELETE FROM tx_index WHERE block_number != ?", (block_number_to_keep,))
    transactions_db.commit()
    transactions_c.execute("VACUUM")
    transactions_db.commit()

logger.info("Pruning block index")
blocks_db = sqlite3.connect(f"{get_home()}/index/blocks.db")
blocks_db_c = blocks_db.cursor()
blocks_db_c.execute("DELETE FROM block_index WHERE block_number != ?", (block_number_to_keep,))
blocks_db.commit()
blocks_db_c.execute("VACUUM")
blocks_db.commit()

logger.info("Pruning blocks")
block_files = glob(f"{get_home()}/blocks/*.block")

for file in block_files:
    if block_hash_to_keep not in file:
        remove(file)

logger.info("Pruning producer sets")
set_files = glob(f"{get_home()}/index/producer_sets/*.dat")

for file in set_files:
    remove(file)

set_latest_block_info(block_ends["latest_block"], logger=logger)
set_earliest_block_info(block_ends["latest_block"], logger=logger)

logger.info("Finished successfully")
