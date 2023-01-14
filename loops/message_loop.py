import threading
import time
import traceback
import asyncio

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
            return False
        if self.memserver.latest_block["block_hash"] != self.consensus.majority_block_hash:
            return False
        if self.memserver.since_last_block > self.memserver.block_time:
            return False
        if not self.memserver.can_mine:
            return False
        return True

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                self.logger.info(f"Period: {self.memserver.period}")

                self.logger.info(
                    f"Block Hash Agreement: {int(self.consensus.block_hash_pool_percentage)}%"
                )
                self.logger.info(
                    f"Transaction Hash Agreement: {int(self.consensus.transaction_hash_pool_percentage)}%"
                )
                self.logger.info(
                    f"Block Producer Agreement: {int(self.consensus.block_producers_hash_pool_percentage)}%"
                )

                self.logger.debug(
                    f"Transactions: {len(self.memserver.transaction_pool)}tp/{len(self.memserver.tx_buffer)}tb/{len(self.memserver.user_tx_buffer)}ub")
                self.logger.debug(f"Linked Peers: {len(self.memserver.peers)}")
                self.logger.debug(f"Block Producers: {len(self.memserver.block_producers)}")
                self.logger.warning(f"Emergency Mode: {self.memserver.emergency_mode}")
                self.logger.warning(f"Current Block: {self.memserver.latest_block['block_number']} / {self.memserver.latest_block['block_hash']}")

                self.logger.warning(
                    f"Seconds since last block: {self.memserver.since_last_block}"
                )

                self.logger.warning(f"Unreachable: {len(self.memserver.unreachable)}")
                self.logger.warning(f"Forced sync: {self.memserver.force_sync_ip}")

                if self.is_all_fine():
                    self.logger.info(f"=== NODE IS OK! ===")

                self.logger.info(f"Loop durations: Core: {self.core.duration}; "
                                 f"Consensus: {self.consensus.duration}; "
                                 f"Peers: {self.peers.duration}")

                time.sleep(10)
            except Exception as e:
                self.logger.error(f"Error in message loop: {e} {traceback.print_exc()}")
                time.sleep(1)
