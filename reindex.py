# checks are not included, should be run only on self data

from ops.data_ops import sort_list_dict
from ops.transaction_ops import index_transactions
from ops.account_ops import change_balance, increase_produced_count, get_totals, index_totals

blocks = []
logger = None
block_height = None

for block in blocks:
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
