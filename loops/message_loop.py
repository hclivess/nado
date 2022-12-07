import threading
import time

from block_ops import get_latest_block_info


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
        if len(self.memserver.peers) > 10:
            if self.memserver.latest_block["block_hash"] == self.consensus.majority_block_hash:
                if self.memserver.since_last_block < self.memserver.block_time:
                    return True
        return False

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                self.logger.info(f"Period: {self.memserver.period}")

                # self.logger.debug(f"Block Hash Pool: {self.consensus.block_hash_pool}")
                self.logger.debug(
                    f"My Block Hash: {self.memserver.latest_block['block_hash']}"
                )
                self.logger.debug(
                    f"Majority Block Hash: {self.consensus.majority_block_hash}"
                )

                # self.logger.debug(f"Transaction Pool: {self.consensus.transaction_hash_pool}")
                self.logger.debug(
                    f"My Transaction Pool Hash: {self.memserver.transaction_pool_hash}"
                )
                self.logger.debug(
                    f"Majority Transaction Pool Hash: {self.consensus.majority_transaction_pool_hash}"
                )

                # self.logger.debug(f"Block Producer Pool: {self.consensus.block_producers_hash_pool}")
                self.logger.debug(
                    f"My Block Producer Hash: {self.memserver.block_producers_hash}"
                )
                self.logger.debug(
                    f"Majority Block Producer Hash: {self.consensus.majority_block_producers_hash}"
                )

                self.logger.info(
                    f"Block Hash Agreement: {self.consensus.block_hash_pool_percentage}%"
                )

                self.logger.info(
                    f"Transaction Hash Agreement: {self.consensus.transaction_hash_pool_percentage}%"
                )
                self.logger.info(
                    f"Block Producer Agreement: {self.consensus.block_producers_hash_pool_percentage}%"
                )

                self.logger.debug(
                    f"Transaction pool: {len(self.memserver.transaction_pool)} + {len(self.memserver.tx_buffer)} + {len(self.memserver.user_tx_buffer)}")
                self.logger.debug(f"Active Peers: {len(self.memserver.peers)}")
                self.logger.debug(f"Block Producers: {len(self.memserver.block_producers)}")
                self.logger.warning(f"Emergency Mode: {self.memserver.emergency_mode}")

                self.logger.warning(
                    f"Seconds since last block: {self.memserver.since_last_block}"
                )

                self.logger.warning(f"Buffer protection: {self.memserver.buffer_lock.locked()}")
                self.logger.warning(f"Unreachable: {len(self.memserver.unreachable)}")

                if self.is_all_fine():
                    self.logger.info(f"=== NODE IS OK! ===")

                self.logger.info(f"Loop durations: Core: {self.core.duration}; "
                                 f"Consensus: {self.consensus.duration}; "
                                 f"Peers: {self.peers.duration}")

                time.sleep(10)
            except Exception as e:
                self.logger.error(f"Error in message loop: {e}")
                time.sleep(1)
