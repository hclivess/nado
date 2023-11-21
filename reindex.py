# checks are not included, should be run only on self data

from ops.data_ops import sort_list_dict
from ops.transaction_ops import index_transactions
from ops.account_ops import change_balance, increase_produced_count, get_totals, index_totals
from ops.block_ops import get_block_ends_info, get_block
from genesis import make_genesis
from ops.log_ops import get_logger, logging

logger = get_logger(file="reindex.log", logger_name="reindex_logger")

genesis_block_hash = ""
blocks = []
logger = None
block_height = None

make_genesis(
    address="ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b",
    balance=1000000000000000000,
    ip="78.102.98.72",
    port=9173,
    timestamp=1669852800,
    logger=logger,
)

block = True
while block:
    block_ends = get_block_ends_info(logger=logger)
    block_current = block_ends["latest_block"]
    block = get_block(block=block_current)["child_hash"]
    blocks.append(block)

    sorted_transactions = sort_list_dict(block["block_transactions"])

    index_transactions(block=block,
                       sorted_transactions=sorted_transactions,
                       logger=logger,
                       block_height=block_height)

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

print(blocks)
