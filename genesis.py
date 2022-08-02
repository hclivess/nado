from block_ops import save_block, set_latest_block_info
from config import create_config
from dircheck import make_folder
from hashing import blake2b_hash_link
from logs import get_logger
from peers import save_peer
from transaction_ops import create_account
from config import get_timestamp_seconds


def make_folders():
    make_folder("blocks/block_numbers")
    make_folder("accounts")
    make_folder("peers")
    make_folder("private", strict=False)
    make_folder("transactions")
    make_folder("index")
    make_folder("index/producer_sets")


def make_genesis(address, balance, ip, port, timestamp, logger):
    create_config()

    block_transactions = []
    block_hash = blake2b_hash_link(link_from=None, link_to=block_transactions)

    genesis_block_message = {
        "block_number": 0,
        "parent_hash": None,
        "block_ip": ip,
        "block_creator": address,
        "block_hash": block_hash,
        "block_timestamp": timestamp,
        "block_transactions": block_transactions,
    }

    create_account(address=address, balance=balance)

    save_peer(ip=ip,
              address=address,
              port=port,
              peer_trust=1000000000,
              last_seen=get_timestamp_seconds())

    save_block(block_message=genesis_block_message, logger=logger)
    set_latest_block_info(block_message=genesis_block_message)


if __name__ == "__main__":
    logger = get_logger(file="genesis.log")

    input("Not supposed to be run directly, continue?\n")
    make_folders()
    make_genesis(
        address="ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b",
        balance=1000000000000000,
        ip="89.176.130.244",
        port=9173,
        timestamp=1657829259,
        logger=logger,
    )
