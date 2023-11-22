# Import necessary modules here
import time
import os
import os.path
import shutil
from ops.data_ops import sort_list_dict, get_home, make_folder
from ops.transaction_ops import index_transactions
from ops.account_ops import change_balance, increase_produced_count, get_totals, index_totals
from ops.block_ops import get_block_ends_info, get_block, set_latest_block_info, update_child_in_latest_block
from genesis import make_genesis, create_indexers
from ops.log_ops import get_logger, logging
from ops.sqlite_ops import DbHandler

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
account_balances = {}  # Dictionary to track account details

def update_account_details(account, amount, is_produced=False, is_burned=False):
    """Update the details of an account including balance, produced, and burned amounts."""
    if account not in account_balances:
        account_balances[account] = {'balance': 0, 'produced': 0, 'burned': 0}

    if is_produced:
        account_balances[account]['produced'] += amount
    elif is_burned:
        account_balances[account]['burned'] += amount
    else:
        account_balances[account]['balance'] += amount

block_count = 0  # Initialize a counter to keep track of the number of processed blocks

while block:
    block_ends = get_block_ends_info(logger=logger)

    if not block["child_hash"]:
        break
    block = get_block(block=block["child_hash"])

    if block["block_number"] > 0:
        sorted_transactions = sort_list_dict(block["block_transactions"])
        blocks_data.extend(block)
        if sorted_transactions:
            for transaction in sorted_transactions:
                sender = transaction['sender']
                recipient = transaction['recipient']
                amount = transaction['amount']

                # Update balances for each transaction
                if recipient == "burn":
                    # If recipient is "burn", the transaction is considered burned
                    update_account_details(sender, -amount, is_burned=True)
                else:
                    update_account_details(sender, -amount)
                    update_account_details(recipient, amount)

            transaction_data.append({"data": sorted_transactions[0],
                                     "block_number": block["block_number"]})

        totals = get_totals(block=block)
        totals_data.extend(totals)

        # Credit block reward to block creator and update produced amount
        update_account_details(block["block_creator"], block["block_reward"], is_produced=True)

        block_count += 1

    if block_count % 5000 == 0:
        # Perform batch operations here after every 5000 loops
        if block_count % 5000 == 0:
            # Perform batch operations here after every 500 loops

            print(len(blocks_data))
            print(len(transaction_data))
            print(len(totals_data))

            # index txs

            txs_to_index = []
            print(transaction_data)
            for transaction in transaction_data:
                print("transaction", transaction)
                print(transaction["data"])
                print(transaction["block_number"])
                txs_to_index.append((transaction["data"]['txid'],
                                     transaction["block_number"],
                                     transaction["data"]['sender'],
                                     transaction["data"]['recipient']))

            # ADD REFLECTION

            height_db = 666
            db_path = f"{get_home()}/index/transactions/block_range_{height_db}.db"
            if not os.path.exists(db_path):
                with DbHandler(db_file=db_path) as tx_handler:
                    tx_handler.db_execute(
                        query="CREATE TABLE tx_index(txid TEXT, block_number INTEGER, sender TEXT, recipient TEXT)")
                    tx_handler.db_execute(query="CREATE INDEX seek_index ON tx_index(txid, sender, recipient)")
            with DbHandler(db_file=db_path) as tx_handler:
                tx_handler.db_executemany("INSERT INTO tx_index VALUES (?,?,?,?)", txs_to_index)

            # index txs

            # Clear the data storage variables after batch processing
            blocks_data.clear()
            transaction_data.clear()
            totals_data.clear()

            print(f"Batch processing after {block_count} loops")

# Print final account details
print("Final Account Details:")
for account, details in account_balances.items():
    print(f"Account {account}: Balance {details['balance']}, Produced {details['produced']}, Burned {details['burned']}")
