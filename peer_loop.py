import asyncio
import threading
import time

from block_ops import save_block_producers
from compounder import compound_get_status_pool
from config import get_timestamp_seconds
from data_ops import set_and_sort
from peers import announce_me, get_list_of_peers, store_producer_set, load_ips, update_peer, delete_old_peers, dump_peers


class PeerClient(threading.Thread):
    """thread which handles poors because timeouts take long"""

    def __init__(self, memserver, consensus, logger):
        threading.Thread.__init__(self)
        self.logger = logger
        self.logger.info(f"Starting Peer Client")
        self.memserver = memserver
        self.consensus = consensus
        self.duration = 0

    def merge_and_sort_peers(self) -> None:
        """abstract from status pool"""
        for peer_ip in self.memserver.peer_buffer.copy():
            if peer_ip not in self.memserver.peers:
                self.memserver.peers.append(peer_ip)

        self.memserver.peers = set_and_sort(self.memserver.peers)
        self.memserver.peer_buffer.clear()

    def sniff_peers_and_producers(self):
        candidates = get_list_of_peers(
            fetch_from=self.memserver.peers,
            failed=self.memserver.purge_peers_list,
            logger=self.logger)

        dump_peers(candidates, logger=self.logger)

        for peer in candidates:
            if peer not in self.memserver.peers:
                self.memserver.peers.append(peer)
            if peer not in self.memserver.block_producers:
                self.memserver.block_producers.append(peer)
                self.logger.warning(f"Added {peer} to block producers")

            update_peer(ip=peer,
                        logger=self.logger,
                        value=get_timestamp_seconds())

        self.merge_and_sort_peers()

        self.memserver.block_producers = set_and_sort(self.memserver.block_producers)
        store_producer_set(self.memserver.block_producers)
        save_block_producers(self.memserver.block_producers)

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()

                if self.memserver.period in [0, 1]:
                    self.memserver.merge_remote_transactions(user=False)
                    self.sniff_peers_and_producers()
                    delete_old_peers(logger=self.logger,
                                     older_than=get_timestamp_seconds()-3600)

                announce_me(
                    targets=self.memserver.peers,
                    logger=self.logger,
                    fail_storage=self.memserver.purge_peers_list,
                )

                if len(self.memserver.peers) < self.memserver.min_peers:
                    self.logger.info("No peers, reloading from drive")
                    self.memserver.unreachable.clear()
                    self.memserver.peers = load_ips()

                self.consensus.status_pool = asyncio.run(
                    compound_get_status_pool(
                        self.memserver.peers,
                        logger=self.logger,
                        fail_storage=self.memserver.purge_peers_list,
                    )
                )

                self.duration = get_timestamp_seconds() - start
                time.sleep(1)
            except Exception as e:
                self.logger.info(f"Error: {e}")
