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
    # ONE consolidated index database so the whole incorporate_block mutation (balances, tx
    # index, block index, tip) commits in a SINGLE transaction -> crash-atomic (audit LO-1/CO-4).
    handler = DbHandler(db_file=f"{get_home()}/index/index.db")

    # accounts + totals. `bonded` = refundable stake locked for mining eligibility (S4); it is
    # NOT spendable balance and is tracked separately so split-neutral selection can weight by it.
    handler.db_execute("CREATE TABLE IF NOT EXISTS acc_index(address TEXT, balance INTEGER, produced INTEGER, bonded INTEGER DEFAULT 0)")
    # UNIQUE so a concurrent get_account(create_on_error=True) race can't insert two rows
    handler.db_execute("CREATE UNIQUE INDEX IF NOT EXISTS seek_index ON acc_index(address)")
    handler.db_execute("CREATE TABLE IF NOT EXISTS totals_index(produced INTEGER, fees INTEGER)")
    if not handler.db_fetch("SELECT 1 FROM totals_index LIMIT 1"):  # seed once (idempotent re-run)
        handler.db_execute("INSERT INTO totals_index VALUES (?,?)", (0, 0,))

    # single consolidated transaction index (replaces the per-10k-block split dbs)
    handler.db_execute("CREATE TABLE IF NOT EXISTS tx_index(txid TEXT, block_number INTEGER, sender TEXT, recipient TEXT)")
    handler.db_execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_txid ON tx_index(txid)")
    handler.db_execute("CREATE INDEX IF NOT EXISTS idx_sender ON tx_index(sender, block_number)")
    handler.db_execute("CREATE INDEX IF NOT EXISTS idx_recipient ON tx_index(recipient, block_number)")

    # block number <-> hash index
    handler.db_execute("CREATE TABLE IF NOT EXISTS block_index(block_hash TEXT, block_number INTEGER UNIQUE)")
    handler.db_execute("CREATE INDEX IF NOT EXISTS idx_block_hash ON block_index(block_hash)")
    handler.db_execute("CREATE INDEX IF NOT EXISTS idx_block_number ON block_index(block_number)")
    handler.close()


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

    # The genesis address IS the treasury (owner's decision): it holds the bootstrap allocation
    # and accrues the 10% per-block cut. Because this address is key-controlled, the seed balance
    # is effectively a founder allocation; pass balance=0 (TREASURY_GENESIS=0) for a no-coins start.
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
        address=TREASURY_ADDRESS,          # genesis address == treasury (canonical checksum)
        balance=TREASURY_GENESIS,          # bootstrap allocation minted to the genesis/treasury
        ip="78.102.98.72",
        port=9173,
        timestamp=1669852800,
        logger=logger,
    )
