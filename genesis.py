import asyncio

from config import create_config
from hashing import blake2b_hash_link
from ops.account_ops import create_account
from ops.block_ops import save_block, set_latest_block_info, set_earliest_block_info
from ops.data_ops import get_home, make_folder
from ops.log_ops import get_logger
from ops.peer_ops import save_peer, get_public_ip
from ops.sqlite_ops import DbHandler
from protocol import CHAIN_ID, TREASURY_ADDRESS, TREASURY_GENESIS


def create_indexers():
    acc_handler = DbHandler(db_file=f"{get_home()}/index/accounts.db")
    # `bonded` = refundable stake locked for mining eligibility (S4); it is NOT spendable
    # balance and is tracked separately so split-neutral selection can weight by it.
    acc_handler.db_execute(query="CREATE TABLE IF NOT EXISTS acc_index(address TEXT, balance INTEGER, produced INTEGER, burned INTEGER, bonded INTEGER DEFAULT 0)")
    # UNIQUE so a concurrent get_account(create_on_error=True) race can't insert two rows
    acc_handler.db_execute(query="CREATE UNIQUE INDEX IF NOT EXISTS seek_index ON acc_index(address)")

    acc_handler.db_execute(query="CREATE TABLE IF NOT EXISTS totals_index(produced INTEGER, fees INTEGER, burned INTEGER)")
    acc_handler.db_execute("INSERT INTO totals_index VALUES (?,?,?)", (0,0,0,))
    acc_handler.close()

    # single consolidated transaction index (replaces the per-10k-block split dbs)
    tx_handler = DbHandler(db_file=f"{get_home()}/index/transactions.db")
    tx_handler.db_execute(
        query="CREATE TABLE IF NOT EXISTS tx_index(txid TEXT, block_number INTEGER, sender TEXT, recipient TEXT)")
    tx_handler.db_execute(query="CREATE UNIQUE INDEX IF NOT EXISTS idx_txid ON tx_index(txid)")
    tx_handler.db_execute(query="CREATE INDEX IF NOT EXISTS idx_sender ON tx_index(sender, block_number)")
    tx_handler.db_execute(query="CREATE INDEX IF NOT EXISTS idx_recipient ON tx_index(recipient, block_number)")
    tx_handler.close()

    block_handler = DbHandler(db_file=f"{get_home()}/index/blocks.db")
    block_handler.db_execute(
        query="CREATE TABLE IF NOT EXISTS block_index(block_hash TEXT, block_number INTEGER UNIQUE)")
    block_handler.db_execute(query="CREATE INDEX IF NOT EXISTS idx_block_hash ON block_index(block_hash)")
    block_handler.db_execute(query="CREATE INDEX IF NOT EXISTS idx_block_number ON block_index(block_number)")
    block_handler.close()


def make_folders():
    make_folder(f"{get_home()}/blocks")
    make_folder(f"{get_home()}/peers", strict=False)
    make_folder(f"{get_home()}/private", strict=False)
    make_folder(f"{get_home()}/index")
    make_folder(f"{get_home()}/index/producer_sets")

    create_indexers()


def make_genesis(address, balance, ip, port, timestamp, logger):
    config_ip = asyncio.run(get_public_ip(logger=logger))
    create_config(ip=config_ip)

    block_transactions = []
    block_hash = blake2b_hash_link(link_from=timestamp, link_to=block_transactions)

    genesis_block_message = {
        "block_number": 0,
        "parent_hash": None,
        "block_ip": ip,
        "block_creator": address,
        "block_hash": block_hash,
        "block_timestamp": timestamp,
        "block_transactions": block_transactions,
        "block_reward": 0,
        "cumulative_fees": 0,        # running total of fees burned up to and incl. this block
        "chain_id": CHAIN_ID,
    }

    # No personal premine: the founder address gets `balance` (0 at relaunch). The genesis
    # allocation is minted to the keyless protocol "treasury" address, which seeds the
    # onboarding faucet and accrues 10% of every block reward ("replace the premine WITH the
    # treasury"). Treasury is created first; if the founder address IS the treasury label it
    # would just be overwritten by INSERT OR IGNORE, but they are distinct by design.
    create_account(address=TREASURY_ADDRESS, balance=TREASURY_GENESIS)
    create_account(address=address, balance=balance)

    save_peer(ip=ip,
              address=address,
              port=port,
              peer_trust=50)

    save_block(block=genesis_block_message,
               logger=logger)

    set_earliest_block_info(earliest_block=genesis_block_message,
                            logger=logger)

    set_latest_block_info(latest_block=genesis_block_message,
                          logger=logger)



if __name__ == "__main__":
    logger = get_logger(file="genesis.log", logger_name="genesis_logger")

    input("Not supposed to be run directly, continue?\n")
    make_folders()
    make_genesis(
        address="ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b",
        balance=0,  # no personal premine; the genesis allocation goes to the treasury
        ip="78.102.98.72",
        port=9173,
        timestamp=1669852800,
        logger=logger,
    )
