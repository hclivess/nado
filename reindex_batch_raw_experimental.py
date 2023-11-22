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
import sqlite3

to_wipeout = ["index"]

def batch_insert_blocks(blocks_data):
    db_path = f"{get_home()}/index/blocks.db"

    # Prepare data for insertion
    insert_data = [(block["block_hash"], block["block_number"]) for block in blocks_data]

    with sqlite3.connect(db_path) as conn:
        try:
            cursor = conn.cursor()
            cursor.executemany("INSERT INTO block_index (block_hash, block_number) VALUES (?, ?)", insert_data)
            conn.commit()
        except sqlite3.Error as e:
            print(f"An error occurred during batch insert: {e}")



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

update_child_in_latest_block(
    child_hash="3abbfe409d446d997fbf65767c97e3f59ecb943d61a000240432e1627187966b",
    logger=logger,
    parent=block_ends["latest_block"]
)

first_block = block_ends["latest_block"]
block = first_block

blocks_data = []
transaction_data = []
totals_data = []
account_balances = {}


def batch_process_transactions(transaction_data):
    txs_to_index = []
    for transaction in transaction_data:
        txs_to_index.append((transaction["data"]['txid'],
                             transaction["block_number"],
                             transaction["data"]['sender'],
                             transaction["data"]['recipient']))

    # Database handling logic
    height_db = 666  # Adjust this value as needed
    db_path = f"{get_home()}/index/transactions/block_range_{height_db}.db"
    if not os.path.exists(db_path):
        with DbHandler(db_file=db_path) as tx_handler:
            tx_handler.db_execute(
                query="CREATE TABLE tx_index(txid TEXT, block_number INTEGER, sender TEXT, recipient TEXT)")
            tx_handler.db_execute(query="CREATE INDEX seek_index ON tx_index(txid, sender, recipient)")
    with DbHandler(db_file=db_path) as tx_handler:
        tx_handler.db_executemany("INSERT INTO tx_index VALUES (?,?,?,?)", txs_to_index)

def insert_aggregated_totals(account_balances):
    total_produced = sum(details['produced'] for details in account_balances.values())
    total_fees = sum(details['fees'] for details in account_balances.values())
    total_burned = sum(details['burned'] for details in account_balances.values())

    db_path = f"{get_home()}/index/accounts.db"
    try:
        conn = sqlite3.connect(db_path)
        conn.execute('INSERT INTO totals_index (produced, fees, burned) VALUES (?, ?, ?)',
                     (total_produced, total_fees, total_burned))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()

def update_account_details(account, amount, is_produced=False, is_burned=False, fee=0):
    if account not in account_balances:
        account_balances[account] = {'balance': 0, 'produced': 0, 'burned': 0, 'fees': 0}

    # Update balance for all accounts
    if not is_burned:  # prevent doubling (stupid logic here, burns are called twice)
        account_balances[account]['balance'] += amount
        account_balances[account]['fees'] += fee

    if is_produced:
        account_balances[account]['produced'] += amount
    if is_burned:
        account_balances[account]['burned'] += amount


block_count = 0

while block["block_number"] < 4000:
    block_ends = get_block_ends_info(logger=logger)

    if not block["child_hash"]:
        break
    block = get_block(block=block["child_hash"])

    if block["block_number"] > 0:
        sorted_transactions = sort_list_dict(block["block_transactions"])
        blocks_data.append(block)
        if sorted_transactions:
            for transaction in sorted_transactions:
                sender = transaction['sender']
                recipient = transaction['recipient']
                amount = transaction['amount']
                fee = transaction['fee'] if block["block_number"] > 111111 else 0

                # Deduct fee from sender's account and amount
                update_account_details(sender, -amount - fee)

                # Credit amount to recipient's account
                update_account_details(recipient, amount)

                # If recipient is "burn", mark the amount as burned for the sender
                if recipient == "burn":
                    update_account_details(sender, amount, is_burned=True)

                transaction_data.append({"data": sorted_transactions[0],
                                         "block_number": block["block_number"]})

        totals = get_totals(block=block)
        totals_data.extend(totals)

        # Credit block reward to block creator
        update_account_details(block["block_creator"], block["block_reward"], is_produced=True)

        block_count += 1

    if block_count % 5000 == 0:
        # Perform batch operations here after every 5000 loops
        batch_process_transactions(transaction_data)
        batch_insert_blocks(blocks_data)
        blocks_data.clear()
        transaction_data.clear()
        totals_data.clear()
        print(f"Batch processing after {block_count} loops")

# Perform batch operations at the end
batch_process_transactions(transaction_data)
batch_insert_blocks(blocks_data)
blocks_data.clear()
transaction_data.clear()
totals_data.clear()
print(f"Batch processing until {block_count} loops")


# Function to save account details to the database
def save_account_details(account_balances):
    db_path = f"{get_home()}/index/accounts.db"
    try:
        conn = sqlite3.connect(db_path)
        conn.execute('''CREATE TABLE IF NOT EXISTS acc_index
                        (account TEXT PRIMARY KEY, balance INT, produced INT, burned INT)''')
        for account, details in account_balances.items():
            cur = conn.cursor()
            cur.execute('SELECT balance, produced, burned FROM acc_index WHERE address = ?', (account,))
            row = cur.fetchone()
            if row:
                new_balance = row[0] + details['balance']
                new_produced = row[1] + details['produced']
                new_burned = row[2] + details['burned']
                cur.execute('UPDATE acc_index SET balance = ?, produced = ?, burned = ? WHERE address = ?',
                            (new_balance, new_produced, new_burned, account))
            else:
                cur.execute('INSERT INTO acc_index (address, balance, produced, burned) VALUES (?, ?, ?, ?)',
                            (account, details['balance'], details['produced'], details['burned']))
            conn.commit()
    except sqlite3.Error as e:
        print(e)
        raise
    finally:
        if conn:
            conn.close()


save_account_details(account_balances)
insert_aggregated_totals(account_balances)
