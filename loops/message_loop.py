import gc

import psutil
import threading
import time
import traceback
import gc


class MessageClient(threading.Thread):
    """thread which displays output messages and logs them"""

    def __init__(self, memserver, consensus, core, peers, logger):
        threading.Thread.__init__(self)
        self.logger = logger
        self.logger.info(f"Starting Message Client")
        self.memserver = memserver
        self.consensus = consensus
        self.core = core
        self.peers = peers

    def is_all_fine(self):

        if len(self.memserver.peers) < 10:
            return {"result":False, "flag": "Not enough peers"}
        if self.memserver.latest_block["block_hash"] != self.consensus.majority_block_hash:
            return {"result":False, "flag": "Outside block hash majority"}
        if self.memserver.since_last_block > self.memserver.block_time:
            return {"result": False, "flag": "Block target too far"}
        if not self.memserver.can_mine:
            return {"result": False, "flag": "Ports closed"}
        return {"result": True}

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                self.logger.info(f"Mode: {self.memserver.mode} "
                                 f"({self.memserver.since_last_block}s / {self.memserver.block_time}s block)")

                self.logger.info(
                    f"Block Hash Agreement: {int(self.consensus.block_hash_pool_percentage)}% ({len(self.consensus.block_hash_pool)} members)"
                )
                self.logger.info(
                    f"Transaction Hash Agreement: {int(self.consensus.transaction_hash_pool_percentage)}%"
                )

                self.logger.debug(
                    f"Transactions: {len(self.memserver.transaction_pool)}tp < {len(self.memserver.tx_buffer)}tb < {len(self.memserver.user_tx_buffer)}ub")
                self.logger.debug(f"Linked Peers: {len(self.memserver.peers)}")
                self.logger.warning(f"Emergency Mode: {self.memserver.emergency_mode}")
                self.logger.warning(f"Current Block: {self.memserver.latest_block['block_number']} - {self.memserver.latest_block['block_hash']}")


                self.logger.warning(
                    f"Seconds since last block: {self.memserver.since_last_block}"
                )

                self.logger.warning(f"Unreachable: {len(self.memserver.purge_peers_list)} >>> {len(self.memserver.unreachable)}")
                self.logger.warning(f"Forced sync: {self.memserver.force_sync_ip}")

                fine = self.is_all_fine()
                if fine["result"]:
                    self.logger.debug(f"=== NODE IS OK! ===")
                else:
                    self.logger.error(f"!!! NODE IS NOT OK: {fine['flag']} !!!")

                self.logger.info(f"Loop durations: Core: {self.core.duration}; "
                                 f"Consensus: {self.consensus.duration}; "
                                 f"Peers: {self.peers.duration}")

                self.logger.info(f"Open files: {len(psutil.Process().open_files())}")
                # NOTE: removed the periodic `muppy.get_objects()` heap walk — it is a
                # stop-the-world GIL-bound full-heap traversal that (a) starves the Tornado
                # /status handler and (b) fatally trips CPython's GC ("PyObject_GC_Track:
                # object already tracked", _asyncio.FutureIter) under live asyncio load,
                # crashing the node. gc counts below are cheap and safe.
                gc_counts = gc.get_count()
                self.logger.info(f"GC counts: {gc_counts}")

                # Backstop-persist the off-chain message pool (~every 10s) so even a hard crash that skips
                # the SIGTERM save loses at most one interval of undelivered DMs. No-op while the pool is empty.
                try:
                    mp = self.memserver.message_pool
                    if mp.messages or mp.prekeys:
                        mp.save(self.memserver.message_pool_path)
                except Exception as e:
                    self.logger.error(f"Message pool save failed: {e}")

                time.sleep(10)
            except Exception as e:
                self.logger.error(f"Error in message loop: {e} {traceback.print_exc()}")
                time.sleep(1)
