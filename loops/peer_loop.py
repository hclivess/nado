import asyncio
import threading
import time
import traceback

from compounder import compound_get_status_pool
from config import get_timestamp_seconds
from config import test_self_port
from ops.peer_ops import announce_me, get_list_of_peers, load_ips, check_save_peers
from ops.peer_ops import get_public_ip, update_local_ip, check_ip, subnet_diversity_ok
from ops.peer_ops import seed_default_peers, seed_peers
from protocol import CHAIN_ID

# How often (seconds) a node BELOW min_peers re-seeds + reloads peers from drive. The peer loop still spins
# ~1/s for status/tx work, but the "No peers, reloading from drive" retry is throttled to this so a peerless
# node (solo/bootstrap, or one that can't yet reach the network) doesn't flood the log every second.
PEERLESS_RELOAD_INTERVAL = 15

# How long (seconds) an ordinary unreachable peer is benched before it is retried. Operator seeds are
# exempt (retried every cycle). Was 3600 — a single blip exiled a peer for an hour, which on a small mesh
# could strand a node with no dialable peers; 5 min still throttles a genuinely dead peer cheaply.
UNREACHABLE_COOLDOWN = 300


class PeerClient(threading.Thread):
    """thread which handles peers because timeouts take long"""

    def __init__(self, memserver, consensus, logger):
        """Wire to the shared memserver/consensus state and zero the pacing timers, so the first
        pass immediately runs a heavy refresh and (if peerless) a seed/drive reload."""
        threading.Thread.__init__(self)
        self.logger = logger
        self.logger.info(f"Starting Peer Client")
        self.memserver = memserver
        self.consensus = consensus
        self.duration = 0
        self.heavy_refresh_timer = 0
        self._last_peerless_reload = 0   # backoff timer for the "no peers, reload from drive" retry (anti-spam)

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
        """Drop a peer from the active dial set and bench it in unreachable, timestamped for the
        UNREACHABLE_COOLDOWN retry. Idempotent: an already-benched peer keeps its ORIGINAL bench
        time, so repeated purge passes cannot extend the cooldown indefinitely."""
        if entry in self.memserver.peers:
            self.memserver.peers.remove(entry)

        if entry not in self.memserver.unreachable.keys():
            self.memserver.unreachable[entry] = get_timestamp_seconds()

    def purge_peers(self) -> None:
        """put purge_peers_list into effect and empty it. Iterates a SNAPSHOT and removes processed
        entries afterwards: the old in-place `for entry in list: list.remove(entry)` shifted the
        iteration index and SKIPPED every other queued peer per pass — and other threads (core loop
        ban_peer, network helpers' fail_storage) append to the live list concurrently, so it must
        never be the iteration target. An entry queued mid-flush simply survives to the next pass."""
        for entry in set(self.memserver.purge_peers_list):
            self.disconnect_peer(entry)

            # pop(x, None) instead of check-then-pop: races with concurrent pool writers otherwise
            self.consensus.status_pool.pop(entry, None)
            self.consensus.transaction_hash_pool.pop(entry, None)
            self.consensus.block_hash_pool.pop(entry, None)

            while entry in self.memserver.purge_peers_list:
                self.memserver.purge_peers_list.remove(entry)

    def run(self) -> None:
        """Thread entry, ~1/s: grow the dial set from gossip (subnet-diversity capped against
        eclipse), merge peers' gossiped txs into the mempool EVERY pass (continuous, mirroring the
        local drain in core_loop.normal_mode), un-bench cooled-down unreachable peers (operator
        seeds immediately — they are the anchor), run the periodic heavy refresh (announce, peer
        health, public-IP + self-port probe -> can_mine), and pull every peer's status into
        consensus.status_pool. Status admission is fail-closed on protocol AND chain_id: a foreign
        chain's tip weight in the pools would flip the caught-up gate and minority_block_consensus,
        stalling production against blocks verify_block can only reject. Failures accumulate in
        purge_peers_list and are flushed at the end of each pass."""
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()
                self.sniff_peers_and_producers()
                self.sniff_buffered_peers()

                # BACKOFF (anti-spam): when we're persistently below min_peers, don't re-seed + reload the
                # drive + log "No peers" every single second — a peerless node (e.g. a solo/bootstrap or one
                # that can't yet reach the network) would otherwise flood the log ~once/sec. Retry at most
                # every PEERLESS_RELOAD_INTERVAL seconds; a reload that finds peers ends the loop naturally.
                if len(self.memserver.peers) < self.memserver.min_peers:
                    now = get_timestamp_seconds()
                    if now - self._last_peerless_reload >= PEERLESS_RELOAD_INTERVAL:
                        self._last_peerless_reload = now
                        self.logger.info("No peers, reloading from drive")
                        seed_default_peers(self.logger, getattr(self.memserver, "ip", None))   # bake-in bootstrap seed if drive is empty
                        self.memserver.peers = asyncio.run(load_ips(fail_storage=self.memserver.purge_peers_list,
                                                                    unreachable=self.memserver.unreachable,
                                                                    logger=self.logger,
                                                                    port=self.memserver.port))

                # merge peers' gossiped txs into the mempool EVERY pass (continuous, like the local drain in
                # core_loop.normal_mode) — no phase gating, so remote txs never stall waiting for a slot.
                # (Was `if 0 or 1 in periods`, itself a bug parsing to `if 1 in periods`.)
                # PREFILTER (audit): a peer advertising the SAME transaction_pool_hash as ours has
                # nothing new in its pool — skip that full-pool download (buffers still fetched).
                _our_pool_hash = self.memserver.transaction_pool_hash
                _same_pool = {p for p, h in self.consensus.transaction_hash_pool.copy().items()
                              if h == _our_pool_hash}
                self.memserver.merge_remote_transactions(user_origin=False, skip_pool_peers=_same_pool)

                _seeds = set(seed_peers())
                for peer, ban_time in self.memserver.unreachable.copy().items():
                    # operator seeds are the anchor: never keep them benched — retry immediately. Ordinary
                    # peers cool down for UNREACHABLE_COOLDOWN (was 3600s: a single blip benched a peer for a
                    # WHOLE HOUR, brutal on a small mesh; 5 min still throttles a truly dead peer cheaply).
                    if peer in _seeds or (get_timestamp_seconds() - ban_time) > UNREACHABLE_COOLDOWN:
                        self.memserver.unreachable.pop(peer)
                        self.logger.info(f"Restored {peer} to the dial set")

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
                    if value['protocol'] < self.memserver.protocol:
                        self.logger.error(f"Protocol of {key} too low: {value['protocol']}")
                        self.memserver.ban_peer(key)
                    elif value.get('chain_id') != CHAIN_ID:
                        # WRONG CHAIN (or a pre-chain_id node that doesn't advertise one): NEVER admit
                        # its status — a foreign chain's tip weight in the pools flips the caught-up
                        # gate (_peer_ahead) and minority_block_consensus, stalling production and
                        # looping emergency sync against blocks verify_block can only reject.
                        self.logger.error(f"Chain of {key} is not {CHAIN_ID}: {value.get('chain_id')}")
                        self.memserver.ban_peer(key)
                    else:
                        self.consensus.status_pool[key]=value

                self.purge_peers()
                self.duration = get_timestamp_seconds() - start
                time.sleep(1)

            except Exception as e:
                self.logger.error(f"Error in peer loop: {e} {traceback.format_exc()}")
                time.sleep(1)
                # raise #test
