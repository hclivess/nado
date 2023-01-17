import asyncio
from threading import Lock

from compounder import compound_get_list_of
from config import get_timestamp_seconds, get_config
from hashing import blake2b_hash
from ops.account_ops import get_account
from ops.block_ops import load_block_producers, get_latest_block_info
from ops.data_ops import set_and_sort, sort_list_dict
from ops.key_ops import load_keys
from ops.transaction_ops import (
    validate_single_spending,
    validate_transaction,
    sort_transaction_pool,

)
from versioner import read_version


class MemServer:
    """storage thread for core.py, also accessed by most other threads, serves mostly as data storage"""

    def __init__(self, logger):
        self.logger = logger
        self.logger.info("Starting MemServer")
        self.genesis_timestamp = 1669852800

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
        self.ip = self.config["ip"]
        self.port = self.config["port"]
        self.terminate = False
        self.producers_refresh_interval = 10


        self.block_time = 60
        self.period = 0

        self.unreachable = {}
        self.peers = []
        self.penalties = {}

        self.transaction_pool_hash = None
        self.block_producers_hash = None

        self.reported_uptime = self.get_uptime()
        self.block_producers = load_block_producers()

        self.emergency_mode = False

        self.version = read_version()
        self.latest_block = get_latest_block_info(logger=logger)
        self.transaction_pool_limit = 150000
        self.transaction_buffer_limit = 1500000
        self.cascade_depth = 0
        self.force_sync_ip = None
        self.rollbacks = 0
        self.can_mine = False

        self.min_peers = self.config.get("min_peers") or 5
        self.peer_limit = self.config.get("peer_limit") or 24
        self.max_rollbacks = self.config.get("max_rollbacks") or 10
        self.cascade_limit = self.config.get("cascade_limit") or 1
        self.promiscuous = True if self.config.get("promiscuous") is True else False
        self.quick_sync = True if self.config.get("quick_sync") is True else False

    def get_transaction_pool_hash(self) -> [str, None]:
        if self.transaction_pool:
            sorted_transaction_pool = sort_transaction_pool(self.transaction_pool.copy())
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
        remote_pool_transactions = asyncio.run(
            compound_get_list_of(
                key="transaction_pool",
                entries=self.peers,
                port=self.port,
                logger=self.logger,
                fail_storage=self.purge_peers_list,
                compress="msgpack",
                semaphore=asyncio.Semaphore(50)
            )
        )
        self.merge_transactions(remote_pool_transactions, user_origin)

        remote_buffer_transactions = asyncio.run(
            compound_get_list_of(
                key="transaction_buffer",
                entries=self.peers,
                port=self.port,
                logger=self.logger,
                fail_storage=self.purge_peers_list,
                compress="msgpack",
                semaphore=asyncio.Semaphore(50)
            )
        )

        self.merge_transactions(remote_buffer_transactions, user_origin)


    def merge_transaction(self, transaction, user_origin=False) -> dict:
        """warning, can get stuck if not efficient"""
        united_pools = self.transaction_pool.copy() + self.tx_buffer.copy() + self.user_tx_buffer.copy()

        with self.buffer_lock:
            if not get_account(transaction["sender"], create_on_error=False):
                msg = {"result": False,
                       "message": f"Empty account"}
                return msg

            elif transaction["target_block"] < self.latest_block["block_number"]:
                msg = {"result": False,
                       "message": f"Target block too low"}
                return msg

            elif transaction["target_block"] > self.latest_block["block_number"] + 360:
                msg = {"result": False,
                       "message": f"Target block too high"}
                return msg

            elif transaction not in united_pools:
                try:
                    validate_transaction(transaction, logger=self.logger)
                except Exception as e:
                    msg = {"result": False,
                           "message": f"Could not merge remote transaction: {e}"}
                    # self.logger.info(msg) spam
                    # raise #test
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
