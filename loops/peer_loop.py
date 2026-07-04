import asyncio
import threading
import time
import traceback

from compounder import compound_get_status_pool
from config import get_timestamp_seconds
from config import test_self_port
from loops.consensus_loop import change_trust
from ops.peer_ops import announce_me, get_list_of_peers, load_ips, check_save_peers, \
    dump_trust
from ops.peer_ops import get_public_ip, update_local_ip, check_ip, subnet_diversity_ok
from ops.peer_ops import seed_default_peers


class PeerClient(threading.Thread):
    """thread which handles peers because timeouts take long"""

    def __init__(self, memserver, consensus, logger):
        threading.Thread.__init__(self)
        self.logger = logger
        self.logger.info(f"Starting Peer Client")
        self.memserver = memserver
        self.consensus = consensus
        self.duration = 0
        self.heavy_refresh_timer = 0

    def sniff_buffered_peers(self):
        """gets peers from buffer and adds them to routine"""
        result = check_save_peers(peers=self.memserver.peer_buffer,
                                  logger=self.logger,
                                  fails=self.memserver.purge_peers_list,
                                  unreachable=self.memserver.unreachable)

        for entry in result["success"]:
            if entry in self.memserver.peer_buffer:
                self.memserver.peer_buffer.remove(entry)
            if (entry not in self.memserver.peers
                    and len(self.memserver.peers) < self.memserver.peer_limit
                    and subnet_diversity_ok(entry, self.memserver.peers)):  # eclipse cap (#18 step 8)
                self.memserver.peers.append(entry)

    def sniff_peers_and_producers(self):
        """gets peers of peers and adds them to routines"""
        candidates = get_list_of_peers(
            ips=self.memserver.peers,
            port=self.memserver.port,
            fail_storage=self.memserver.purge_peers_list,
            logger=self.logger)

        check_save_peers(peers=candidates,
                         logger=self.logger,
                         fails=self.memserver.purge_peers_list,
                         unreachable=self.memserver.unreachable)

        for peer in candidates:
            if check_ip(peer):
                if peer not in self.memserver.unreachable:
                    if (peer not in self.memserver.peers
                            and len(self.memserver.peers) < self.memserver.peer_limit
                            and subnet_diversity_ok(peer, self.memserver.peers)):  # eclipse cap (#18 step 8)
                        self.memserver.peers.append(peer)

    def disconnect_peer(self, entry):
        if entry in self.memserver.peers:
            self.memserver.peers.remove(entry)

        if entry not in self.memserver.unreachable.keys():
            self.memserver.unreachable[entry] = get_timestamp_seconds()

    def purge_peers(self) -> None:
        """put purge_peers_list into effect and empty it"""

        for entry in self.memserver.purge_peers_list:
            self.disconnect_peer(entry)

            self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                     peer=entry,
                                                     value=-1)

            if entry in self.consensus.status_pool.keys():
                self.consensus.status_pool.pop(entry)

            if entry in self.consensus.transaction_hash_pool.keys():
                self.consensus.transaction_hash_pool.pop(entry)

            if entry in self.consensus.block_hash_pool.keys():
                self.consensus.block_hash_pool.pop(entry)

            # self.logger.warning(f"Cannot connect to {entry}")
            self.memserver.purge_peers_list.remove(entry)

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()
                self.sniff_peers_and_producers()
                self.sniff_buffered_peers()

                if len(self.memserver.peers) < self.memserver.min_peers:
                    self.logger.info("No peers, reloading from drive")
                    seed_default_peers(self.logger, getattr(self.memserver, "ip", None))   # bake-in bootstrap seed if drive is empty
                    self.memserver.peers = asyncio.run(load_ips(fail_storage=self.memserver.purge_peers_list,
                                                                unreachable=self.memserver.unreachable,
                                                                logger=self.logger,
                                                                port=self.memserver.port))

                if 0 or 1 in self.memserver.periods:
                    self.memserver.merge_remote_transactions(user_origin=False)

                for peer, ban_time in self.memserver.unreachable.copy().items():
                    timeout = 3600 + ban_time - get_timestamp_seconds()
                    if timeout < 0:
                        self.memserver.unreachable.pop(peer)
                        self.logger.info(f"Restored {peer} because it has been banned for too long")

                if get_timestamp_seconds() > self.heavy_refresh_timer + self.memserver.heavy_refresh_interval:
                    """heavy refresh triggered"""

                    self.logger.info("Heavy refresh initiated")
                    self.heavy_refresh_timer = get_timestamp_seconds()

                    announce_me(
                        targets=self.memserver.peers,
                        port=self.memserver.port,
                        my_ip=self.memserver.ip,
                        logger=self.logger,
                        fail_storage=self.memserver.purge_peers_list
                    )

                    check_save_peers(peers=self.memserver.peers,
                                     logger=self.logger,
                                     fails=self.memserver.purge_peers_list,
                                     unreachable=self.memserver.unreachable)

                    dump_trust(logger=self.logger,
                               pool_data=self.consensus.trust_pool)

                    update_local_ip(ip=asyncio.run(get_public_ip(logger=self.logger)),
                                    logger=self.logger)

                    self.memserver.can_mine = test_self_port(self.memserver.ip, self.memserver.port)

                candidates = asyncio.run(
                    compound_get_status_pool(
                        ips=self.memserver.peers,
                        port=self.memserver.port,
                        logger=self.logger,
                        fail_storage=self.memserver.purge_peers_list,
                        compress="msgpack",
                        semaphore=asyncio.Semaphore(50)
                    )
                )

                for key, value in candidates.items():
                    if value['protocol'] >= self.memserver.protocol:
                        self.consensus.status_pool[key]=value

                        self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                 peer=key,
                                                                 value=1)
                    else:
                        self.logger.error(f"Protocol of {key} too low: {value['protocol']}")

                        self.memserver.ban_peer(key)
                        self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                 peer=key,
                                                                 value=-1)

                self.purge_peers()
                self.duration = get_timestamp_seconds() - start
                time.sleep(1)

            except Exception as e:
                self.logger.error(f"Error in peer loop: {e} {traceback.print_exc()}")
                time.sleep(1)
                # raise #test
