import asyncio
import threading
import time
import traceback

import peer_ops
from block_ops import save_block_producers
from compounder import compound_get_status_pool
from config import get_timestamp_seconds
from data_ops import set_and_sort
from peer_ops import announce_me, get_list_of_peers, store_producer_set, load_ips, update_peer, dump_peers, dump_trust
from peer_ops import get_public_ip, update_local_ip, ip_stored, check_ip


class PeerClient(threading.Thread):
    """thread which handles peers because timeouts take long"""

    def __init__(self, memserver, consensus, logger):
        threading.Thread.__init__(self)
        self.logger = logger
        self.logger.info(f"Starting Peer Client")
        self.memserver = memserver
        self.consensus = consensus
        self.duration = 0
        self.heavy_refresh = 0

    def merge_and_sort_peers(self) -> None:
        """abstract from status pool"""
        for peer_ip in self.memserver.peer_buffer.copy():
            if peer_ip not in self.memserver.peers and peer_ip not in self.memserver.unreachable and len(
                    self.memserver.peers) < self.memserver.peer_limit:
                self.memserver.peers.append(peer_ip)
                self.logger.info(f"{peer_ip} connected")

                self.memserver.peers = set_and_sort(self.memserver.peers)
                self.memserver.peer_buffer.clear()

    def sniff_peers_and_producers(self):
        candidates = get_list_of_peers(
            fetch_from=self.memserver.peers,
            port=self.memserver.port,
            failed=self.memserver.purge_peers_list,
            logger=self.logger)

        dump_peers(candidates, logger=self.logger)

        for peer in candidates:
            if check_ip(peer):
                if peer not in self.memserver.unreachable:
                    if peer not in self.memserver.peers and len(self.memserver.peers) < self.memserver.peer_limit:
                        self.memserver.peers.append(peer)

                    if peer not in self.memserver.block_producers and ip_stored(peer):
                        self.memserver.block_producers.append(peer)
                        self.logger.warning(f"Added {peer} to block producers")
                        """address is sniffed before block is produced"""

                        update_peer(ip=peer,
                                    logger=self.logger,
                                    value=get_timestamp_seconds(),
                                    peer_file_lock=self.memserver.peer_file_lock)

        self.merge_and_sort_peers()

        self.memserver.block_producers = set_and_sort(self.memserver.block_producers)
        store_producer_set(self.memserver.block_producers)
        save_block_producers(self.memserver.block_producers)

    def disconnect_peer(self, entry):
        if entry in self.memserver.peers:
            self.memserver.peers.remove(entry)

        if entry not in self.memserver.unreachable.keys():
            self.memserver.unreachable[entry] = get_timestamp_seconds()

    def purge_peers(self) -> None:
        """put purge_peers_list into effect and empty it"""

        for entry in self.memserver.purge_peers_list:
            self.disconnect_peer(entry)

            if entry in self.memserver.block_producers:
                self.memserver.block_producers.remove(entry)
                # self.logger.warning(f"Removed {entry} from block producers")

            if entry in self.consensus.trust_pool.keys():
                if self.consensus.trust_pool[entry]:
                    self.consensus.trust_pool[entry] -= 1000

            if entry in self.consensus.status_pool.keys():
                self.consensus.status_pool.pop(entry)

            if entry in self.consensus.block_producers_hash_pool.keys():
                self.consensus.block_producers_hash_pool.pop(entry)

            if entry in self.consensus.transaction_hash_pool.keys():
                self.consensus.transaction_hash_pool.pop(entry)

            if entry in self.consensus.block_hash_pool.keys():
                self.consensus.block_hash_pool.pop(entry)

            # self.logger.warning(f"Cannot connect to {entry}")
            self.memserver.purge_peers_list.remove(entry)

            # delete_peer(entry, logger=self.logger)

        # self.memserver.peers = me_to(self.memserver.peers)
        # self.memserver.block_producers = me_to(self.memserver.block_producers)

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()

                if len(self.memserver.peers) < self.memserver.min_peers:
                    self.logger.info("No peers, reloading from drive")
                    self.memserver.unreachable.clear()
                    self.memserver.peers = asyncio.run(load_ips(fail_storage=self.memserver.purge_peers_list,
                                                                logger=self.logger,
                                                                port=self.memserver.port))

                if self.memserver.period in [0, 1]:
                    self.purge_peers()
                    self.memserver.merge_remote_transactions(user_origin=False)
                    self.sniff_peers_and_producers()

                for peer, ban_time in self.memserver.unreachable.copy().items():
                    timeout = 3600 + ban_time - get_timestamp_seconds()
                    if timeout < 0:
                        self.memserver.unreachable.pop(peer)
                        self.logger.info(f"Restored {peer} because it has been banned for too long")

                if get_timestamp_seconds() > self.heavy_refresh + 360:
                    self.heavy_refresh = get_timestamp_seconds()

                    announce_me(
                        targets=self.memserver.block_producers,
                        port=self.memserver.port,
                        my_ip=self.memserver.ip,
                        logger=self.logger,
                        fail_storage=self.memserver.purge_peers_list,
                    )

                    dump_peers(peers=self.memserver.peers, logger=self.logger)

                    dump_trust(logger=self.logger,
                               peer_file_lock=self.memserver.peer_file_lock,
                               pool_data=self.consensus.trust_pool)

                    update_local_ip(ip=asyncio.run(get_public_ip(logger=self.logger)),
                                    logger=self.logger,
                                    peer_file_lock=self.memserver.peer_file_lock)

                self.consensus.status_pool = asyncio.run(
                    compound_get_status_pool(
                        ips=self.memserver.peers,
                        port=self.memserver.port,
                        logger=self.logger,
                        fail_storage=self.memserver.purge_peers_list,
                        compress="msgpack"
                    )
                )

                self.duration = get_timestamp_seconds() - start
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in peer loop: {e} {traceback.print_exc()}")
                time.sleep(1)
                # raise #test
