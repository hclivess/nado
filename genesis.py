from account_ops import create_account
from block_ops import save_block, set_latest_block_info
from data_ops import get_home
from dircheck import make_folder
from hashing import blake2b_hash_link
from log_ops import get_logger
from peer_ops import save_peer
from config import create_config


def make_folders():
    make_folder(f"{get_home()}/blocks/block_numbers")
    make_folder(f"{get_home()}/accounts")
    make_folder(f"{get_home()}/peers")
    make_folder(f"{get_home()}/private", strict=False)
    make_folder(f"{get_home()}/transactions")
    make_folder(f"{get_home()}/index")
    make_folder(f"{get_home()}/index/producer_sets")


def make_genesis(address, balance, ip, port, timestamp, logger):
    create_config(ip=ip)

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
    }

    create_account(address=address, balance=balance)

    save_peer(ip=ip,
              address=address,
              port=port,
              peer_trust=1000000000)

    save_block(block_message=genesis_block_message,
               logger=logger)
    set_latest_block_info(block_message=genesis_block_message,
                          logger=logger)


if __name__ == "__main__":
    logger = get_logger(file=f"{get_home()}/genesis.log")

    input("Not supposed to be run directly, continue?\n")
    make_folders()
    make_genesis(
        address="ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b",
        balance=1000000000000000000,
        ip="78.102.98.72",
        port=9173,
        timestamp=1669852800,
        logger=logger,
    )
