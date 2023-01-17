import threading
import time
import traceback

from config import get_timestamp_seconds
from ops.block_ops import save_block_producers
from ops.peer_ops import (
    load_peer,
    me_to,
    get_majority,
    percentage,
    get_average_int,
    ip_stored
)
from ops.pool_ops import get_from_pool


def get_pool_majority(pool):
    if pool and None not in pool.values():
        majority_hash = get_majority(pool)
        return majority_hash
    else:
        return None


def get_pool_percentage(pool, majority_pool_hash):
    if pool and None not in pool.values():
        pool_percentage = percentage(majority_pool_hash, sorted(pool.values()))
        return pool_percentage
    else:
        return 100


class ConsensusClient(threading.Thread):
    """thread to control peer pools, consensus and trust, refreshing of values"""

    def __init__(self, memserver, logger):
        threading.Thread.__init__(self)
        self.duration = 0
        self.logger = logger

        self.logger.info(f"Starting Consensus Manager")

        self.memserver = memserver

        self.block_hash_pool = {}
        self.status_pool = {}
        self.trust_pool = {}
        self.transaction_hash_pool = {}
        self.block_producers_hash_pool = {}

        self.majority_block_hash = None
        self.majority_transaction_pool_hash = None
        self.majority_block_producers_hash = None

        self.average_trust = None

        self.transaction_hash_pool_percentage = 0
        self.block_producers_hash_pool_percentage = 0
        self.block_hash_pool_percentage = 0

        self.memserver.peers = me_to(self.memserver.peers)

        self.memserver.block_producers = me_to(self.memserver.block_producers)
        save_block_producers(self.memserver.block_producers)

    def reward_pool_consensus(self, pool, majority_pool) -> None:
        try:
            for peer in self.trust_pool.copy().keys():
                if peer in pool.keys():
                    if pool[peer] == majority_pool:
                        change_trust(consensus=self, peer=peer, value=3000)
                    else:
                        change_trust(consensus=self, peer=peer, value=-100)

        except Exception as e:
            self.logger.info(f"Failed to update trust: {e}")

    def add_peers_to_trust_pool(self) -> None:
        for peer in self.memserver.peers.copy():
            if ip_stored(peer):
                peer_trust = load_peer(ip=peer,
                                       key="peer_trust",
                                       logger=self.logger,
                                       peer_file_lock=self.memserver.peer_file_lock)
                if peer not in self.trust_pool.keys():
                    self.trust_pool[peer] = peer_trust

    def purge_block_producers(self) -> None:
        for entry in self.memserver.purge_producers_list:
            self.memserver.block_producers.remove(entry)

    def refresh_hashes(self):
        """make sure our node knows the current state of affairs quickly"""

        self.memserver.since_last_block = get_timestamp_seconds() - self.memserver.latest_block["block_timestamp"]

        get_from_pool(source="transaction_pool_hash",
                      target=self.transaction_hash_pool,
                      pool=self.status_pool)
        get_from_pool(source="latest_block_hash",
                      target=self.block_hash_pool,
                      pool=self.status_pool)
        get_from_pool(source="block_producers_hash",
                      target=self.block_producers_hash_pool,
                      pool=self.status_pool)

        self.block_hash_pool_percentage = get_pool_percentage(
            self.block_hash_pool, self.majority_block_hash
        )

        self.transaction_hash_pool_percentage = get_pool_percentage(
            self.transaction_hash_pool, self.majority_transaction_pool_hash
        )

        self.block_producers_hash_pool_percentage = get_pool_percentage(
            self.block_producers_hash_pool, self.majority_block_producers_hash
        )

        self.majority_block_hash = get_pool_majority(self.block_hash_pool)
        self.majority_transaction_pool_hash = get_pool_majority(
            self.transaction_hash_pool
        )
        self.majority_block_producers_hash = get_pool_majority(
            self.block_producers_hash_pool
        )

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()

                # self.add_block_producers()

                self.add_peers_to_trust_pool()

                if None not in self.trust_pool.values():
                    self.average_trust = get_average_int(
                        list_of_values=self.trust_pool.values()
                    )

                self.reward_pool_consensus(
                    self.block_hash_pool, self.majority_block_hash
                )

                self.reward_pool_consensus(
                    self.transaction_hash_pool, self.majority_transaction_pool_hash
                )

                self.memserver.transaction_pool_hash = self.memserver.get_transaction_pool_hash()
                self.memserver.block_producers_hash = self.memserver.get_block_producers_hash()

                self.refresh_hashes()

                self.duration = get_timestamp_seconds() - start
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in consensus loop: {e} {traceback.print_exc()}")
                time.sleep(1)
                # raise  # test


def change_trust(consensus, peer, value):
    if peer in consensus.trust_pool.keys():
        consensus.trust_pool[peer] += value