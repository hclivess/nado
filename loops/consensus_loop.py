import threading
import time

from block_ops import get_since_last_block, save_block_producers
from config import get_timestamp_seconds
from peer_ops import (
    load_peer,
    update_peer,
    dump_peers,
    me_to,
    get_majority,
    percentage,
    get_average_int,
)


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
        return 0


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

        dump_peers(logger=self.logger, peers=self.memserver.peers)
        self.memserver.block_producers = me_to(self.memserver.block_producers)
        save_block_producers(self.memserver.block_producers)

    """
    def add_block_producers(self):
        producers = load_block_producers()
        if producers:
            self.memserver.block_producers = producers
        else:
            get_list_of_block_producers(
                fetch_from=self.memserver.block_producers,
                logger=self.logger,
                fail_storage=self.memserver.purge_producers_list,
            )
    """

    def reward_pool_consensus(self, pool, majority_pool) -> None:
        try:
            for peer in self.trust_pool.copy().keys():
                if peer in pool.keys():
                    if pool[peer] == majority_pool:
                        self.trust_pool[peer] += 1
                    else:
                        self.trust_pool[peer] -= 1
                    update_peer(
                        ip=peer,
                        key="peer_trust",
                        value=self.trust_pool[peer],
                        logger=self.logger,
                        peer_file_lock=self.memserver.peer_file_lock
                    )
        except Exception as e:
            self.logger.info(f"Failed to update trust: {e}")

    def add_peers_to_trust_pool(self) -> None:
        for peer in self.memserver.peers.copy():
            peer_trust = load_peer(ip=peer,
                                   key="peer_trust",
                                   logger=self.logger,
                                   peer_file_lock=self.memserver.peer_file_lock)
            if peer not in self.trust_pool.keys():
                self.trust_pool[peer] = peer_trust

    def get_from_status_pool(self, source, target):
        for item in self.status_pool.copy().items():
            target[item[0]] = item[1][source]

    def purge_block_producers(self) -> None:
        for entry in self.memserver.purge_producers_list:
            self.memserver.block_producers.remove(entry)

    def refresh_hashes(self):
        """make sure our node knows the current state of affairs quickly"""

        self.memserver.since_last_block = get_since_last_block(logger=self.logger)

        self.get_from_status_pool(source="transaction_pool_hash",
                                  target=self.transaction_hash_pool)
        self.get_from_status_pool(source="latest_block_hash",
                                  target=self.block_hash_pool)
        self.get_from_status_pool(source="block_producers_hash",
                                  target=self.block_producers_hash_pool)

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

        dump_peers(peers=self.memserver.peers, logger=self.logger)

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()

                # self.add_block_producers()

                self.add_peers_to_trust_pool()
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

                # inject_peer(peer="5.5.5.5", target_pool=self.memserver.peers)  # test
                # inject_peer(peer="127.0.0.1", target_pool=self.memserver.peers)  # test
                # self.logger.info(self.purge_peers_list) # test

                self.refresh_hashes()

                self.duration = get_timestamp_seconds() - start
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in consensus loop: {e}")
                time.sleep(1)
                # raise  # test
