import asyncio
import threading
import time

from block_ops import save_block_producers
from compounder import compound_get_status_pool
from config import get_timestamp_seconds
from data_ops import set_and_sort
from peer_ops import announce_me, get_list_of_peers, store_producer_set, load_ips, update_peer, dump_peers, adjust_trust


class PeerClient(threading.Thread):
    """thread which handles poors because timeouts take long"""

    def __init__(self, memserver, consensus, logger):
        threading.Thread.__init__(self)
        self.logger = logger
        self.logger.info(f"Starting Peer Client")
        self.memserver = memserver
        self.consensus = consensus
        self.duration = 0
        self.last_announced = get_timestamp_seconds()

    def merge_and_sort_peers(self) -> None:
        """abstract from status pool"""
        for peer_ip in self.memserver.peer_buffer.copy():
            if peer_ip not in self.memserver.peers and peer_ip not in self.memserver.unreachable:
                self.memserver.peers.append(peer_ip)
                self.logger.info(f"{peer_ip} connected")

        self.memserver.peers = set_and_sort(self.memserver.peers)
        self.memserver.peer_buffer.clear()

    def sniff_peers_and_producers(self):
        candidates = get_list_of_peers(
            fetch_from=self.memserver.peers,
            failed=self.memserver.purge_peers_list,
            logger=self.logger)

        dump_peers(candidates, logger=self.logger)

        for peer in candidates:
            if peer not in self.memserver.unreachable:
                """the only way to remove self from unreachable is by announce"""
                if peer not in self.memserver.peers and len(self.memserver.peers) < 8:
                    self.memserver.peers.append(peer)
                if peer not in self.memserver.block_producers:
                    self.memserver.block_producers.append(peer)
                    self.logger.warning(f"Added {peer} to block producers")

                    update_peer(ip=peer,
                                logger=self.logger,
                                value=get_timestamp_seconds(),
                                peer_file_lock=self.memserver.peer_file_lock)

        self.merge_and_sort_peers()

        self.memserver.block_producers = set_and_sort(self.memserver.block_producers)
        store_producer_set(self.memserver.block_producers)
        save_block_producers(self.memserver.block_producers)

    def purge_peers(self) -> None:
        """put purge_peers_list into effect and empty it"""

        for entry in self.memserver.purge_peers_list:
            if entry in self.memserver.peers:
                self.memserver.peers.remove(entry)
            if entry not in self.memserver.unreachable:
                self.memserver.unreachable.append(entry)
            if entry in self.memserver.block_producers:
                self.memserver.block_producers.remove(entry)  # experimental
                self.logger.warning(f"Removed {entry} from block producers")

            adjust_trust(entry=entry,
                         value=-1000,
                         logger=self.logger,
                         trust_pool=self.consensus.trust_pool,
                         peer_file_lock=self.memserver.peer_file_lock)

            if entry in self.consensus.status_pool.keys():
                self.consensus.status_pool.pop(entry)

            if entry in self.consensus.block_producers_hash_pool.keys():
                self.consensus.block_producers_hash_pool.pop(entry)

            if entry in self.consensus.transaction_hash_pool.keys():
                self.consensus.transaction_hash_pool.pop(entry)

            if entry in self.consensus.block_hash_pool.keys():
                self.consensus.block_hash_pool.pop(entry)

            self.logger.warning(f"Disconnected from {entry}")
            self.memserver.purge_peers_list.remove(entry)

            # delete_peer(entry, logger=self.logger)

        # self.memserver.peers = me_to(self.memserver.peers)
        # self.memserver.block_producers = me_to(self.memserver.block_producers)

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()

                if self.memserver.period in [0, 1]:
                    self.purge_peers()
                    self.memserver.merge_remote_transactions(user=False)
                    self.sniff_peers_and_producers()

                if get_timestamp_seconds() > self.last_announced + 360:
                    self.last_announced = get_timestamp_seconds()
                    announce_me(
                        targets=self.memserver.block_producers,
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
                        compress="msgpack"
                    )
                )

                self.duration = get_timestamp_seconds() - start
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in peer loop: {e}")
                time.sleep(1)
                # raise #test
