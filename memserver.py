import asyncio
from threading import Lock

from account_ops import get_account
from block_ops import load_block_producers
from compounder import compound_get_list_of
from config import get_timestamp_seconds, get_config
from data_ops import set_and_sort, sort_list_dict
from hashing import blake2b_hash
from keys import load_keys
from transaction_ops import (
    validate_single_spending,
    validate_transaction,
    sort_transaction_pool,

)


class MemServer:
    """storage thread for core.py, also accessed by most other threads, serves mostly as data storage"""

    def __init__(self, logger):
        self.logger = logger
        self.logger.info("Starting MemServer")

        self.purge_peers_list = []
        self.purge_producers_list = []

        self.buffer_lock = Lock()
        self.peer_file_lock = Lock()

        self.start_time = get_timestamp_seconds()
        self.keydict = load_keys()
        self.config = get_config()
        self.protocol = self.config["protocol"]
        self.private_key = self.keydict["private_key"]
        self.public_key = self.keydict["public_key"]
        self.address = self.keydict["address"]
        self.server_key = self.config["server_key"]
        self.transaction_pool = []
        self.since_last_block = 0
        self.user_tx_buffer = []
        self.tx_buffer = []
        self.peer_buffer = []
        self.ip = get_config()["ip"]
        self.port = get_config()["port"]
        self.terminate = False
        self.producers_refresh_interval = 10

        self.block_time = 60
        self.period = None

        self.unreachable = {}
        self.peers = []

        self.transaction_pool_hash = None
        self.block_producers_hash = None

        self.reported_uptime = self.get_uptime()
        self.block_producers = load_block_producers()

        self.sync_mode = False
        self.waiting = 0
        self.min_peers = 2
        self.peer_limit = 24

    def get_transaction_pool_hash(self) -> [str, None]:
        if self.transaction_pool:
            sorted_transaction_pool = sort_transaction_pool(self.transaction_pool)
            transaction_pool_hash = blake2b_hash(sorted_transaction_pool)
        else:
            transaction_pool_hash = None
        return transaction_pool_hash

    def get_block_producers_hash(self) -> [str, None]:
        if self.block_producers:
            self.block_producers = set_and_sort(self.block_producers)
            producers_pool_hash = blake2b_hash(self.block_producers)
        else:
            producers_pool_hash = None
        return producers_pool_hash

    def get_uptime(self) -> int:
        return get_timestamp_seconds() - self.start_time

    def merge_remote_transactions(self, user_origin=False) -> None:
        """reach out to all peers and merge their transactions to our transaction pool"""
        remote_transactions = asyncio.run(
            compound_get_list_of(
                "transaction_pool",
                self.peers,
                logger=self.logger,
                fail_storage=self.purge_peers_list,
                compress="msgpack"
            )
        )
        self.merge_transactions(remote_transactions, user_origin)

    def merge_transaction(self, transaction, user_origin=False) -> dict:
        """warning, can get stuck if not efficient"""
        united_pools = self.transaction_pool.copy() + self.tx_buffer.copy() + self.user_tx_buffer.copy()

        with self.buffer_lock:
            if not get_account(transaction["sender"], create_on_error=False):
                msg = {"result": False,
                       "message": f"Empty account"}
                return msg

            elif transaction not in united_pools:
                try:
                    validate_transaction(transaction, logger=self.logger)
                except Exception as e:
                    msg = {"result": False,
                           "message": f"Could not merge remote transaction: {e}"}
                    # self.logger.info(msg) spam
                    #raise #test
                    return msg
                else:
                    try:
                        validate_single_spending(transaction_pool=united_pools, transaction=transaction)

                        if transaction not in self.transaction_pool:
                            if user_origin and transaction not in self.tx_buffer:
                                self.user_tx_buffer.append(transaction)
                                self.user_tx_buffer = sort_list_dict(self.user_tx_buffer)
                            elif transaction not in self.user_tx_buffer:
                                self.tx_buffer.append(transaction)
                                self.tx_buffer = sort_list_dict(self.tx_buffer)

                    except Exception as e:
                        msg = f"Remote transaction failed to validate: {e}"
                        self.logger.info(msg)
                        self.purge_txs_of_sender(transaction["sender"])
                        return {"message": msg,
                                "result": False}

                return {"message": "Success", "result": True}

    def merge_transactions(self, transactions, user_origin=False) -> None:
        for transaction in transactions:
            self.merge_transaction(transaction, user_origin)

    def purge_txs_of_sender(self, sender) -> None:
        """remove all transactions of sender to prevent possible double spending attempt"""
        """of sender sending different txs to different nodes both exhausting balance"""
        for transaction in self.transaction_pool:
            if transaction["sender"] == sender:
                self.transaction_pool.remove(transaction)

        for transaction in self.tx_buffer:
            if transaction["sender"] == sender:
                self.tx_buffer.remove(transaction)
