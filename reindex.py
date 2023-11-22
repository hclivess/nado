# checks are not included, should be run only on self data

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

while block:
    print(block)

    block_ends = get_block_ends_info(logger=logger)
    block = get_block(block=block["child_hash"])

    if block["block_number"] > 0:
        sorted_transactions = sort_list_dict(block["block_transactions"])

        index_transactions(block=block,
                           sorted_transactions=sorted_transactions,
                           logger=logger,)

        change_balance(address=block["block_creator"],
                       amount=block["block_reward"],
                       logger=logger
                       )

        increase_produced_count(address=block["block_creator"],
                                amount=block["block_reward"],
                                logger=logger
                                )

        totals = get_totals(block=block)

        index_totals(produced=totals["produced"],
                     fees=totals["fees"],
                     burned=totals["burned"],
                     block_height=block["block_number"])

    set_latest_block_info(latest_block=block, logger=logger)
