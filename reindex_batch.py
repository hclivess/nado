# Import necessary modules here
from ops.data_ops import sort_list_dict
from ops.transaction_ops import index_transactions
from ops.account_ops import change_balance, increase_produced_count, get_totals, index_totals
from ops.block_ops import get_block_ends_info, get_block, set_latest_block_info, update_child_in_latest_block
from genesis import make_genesis, create_indexers
from ops.log_ops import get_logger, logging
import os
import os.path
import shutil

from ops.data_ops import get_home, make_folder

to_wipeout = ["index"]

def delete(to_wipeout):
    for folder in to_wipeout:
        print(f"Removing {folder}")
        path = f"{get_home()}/{folder}"
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"Removed {path}")

delete(to_wipeout)
make_folder(f"{get_home()}/index")
make_folder(f"{get_home()}/index/transactions")
create_indexers()

logger = get_logger(file="reindex.log", logger_name="reindex_logger")

genesis_block_hash = ""
blocks = []

make_genesis(
    address="ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b",
    balance=1000000000000000000,
    ip="78.102.98.72",
    port=9173,
    timestamp=1669852800,
    logger=logger,
)

block_ends = get_block_ends_info(logger=logger)
print(block_ends["latest_block"])

update_child_in_latest_block(child_hash="3abbfe409d446d997fbf65767c97e3f59ecb943d61a000240432e1627187966b",
                             logger=logger,
                             parent=block_ends["latest_block"])

first_block = block_ends["latest_block"]
block = first_block

# Initialize data storage variables
blocks_data = []
transaction_data = []
totals_data = []

block_count = 0  # Initialize a counter to keep track of the number of processed blocks

while block:
    print(block)

    block_ends = get_block_ends_info(logger=logger)
    block = get_block(block=block["child_hash"])

    if block["block_number"] > 0:
        sorted_transactions = sort_list_dict(block["block_transactions"])
        blocks_data.append(block)
        transaction_data.append(sorted_transactions)
        totals = get_totals(block=block)
        totals_data.append(totals)

        block_count += 1  # Increment the block count

    if block_count % 5000 == 0:
        # Perform batch operations here after every 500 loops
        for i in range(len(blocks_data)):
            block = blocks_data[i]
            sorted_transactions = transaction_data[i]
            totals = totals_data[i]

            index_transactions(block=block,
                               sorted_transactions=sorted_transactions,
                               logger=logger)

            change_balance(address=block["block_creator"],
                           amount=block["block_reward"],
                           logger=logger
                           )

            increase_produced_count(address=block["block_creator"],
                                    amount=block["block_reward"],
                                    logger=logger
                                    )

            index_totals(produced=totals["produced"],
                         fees=totals["fees"],
                         burned=totals["burned"],
                         block_height=block["block_number"])

        # Clear the data storage variables after batch processing
        blocks_data.clear()
        transaction_data.clear()
        totals_data.clear()

        print(f"Batch processing after {block_count} loops")

# No remaining code provided in the original question.
