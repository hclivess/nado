import threading
import time

from block_ops import (
    knows_block,
    get_blocks_after,
    get_from_single_target,
    get_latest_block_info,
    get_since_last_block,
    get_block_candidate,
    save_block_producers,
    valid_block_gap,
    update_child_in_latest_block,
    save_block,
    set_latest_block_info,
    get_block
)
from config import get_timestamp_seconds, get_config
from data_ops import set_and_sort, shuffle_dict, sort_list_dict, get_byte_size, sort_occurence, dict_to_val_list
from peers import load_trust, adjust_trust, save_peer, get_remote_peer_address, update_local_address
from pool_ops import merge_buffer
from rollback import rollback_one_block
from transaction_ops import (
    incorporate_transaction,
    change_balance,
    to_readable_amount,
    validate_transaction,
    validate_all_spending,
)


def minority_consensus(majority_hash, sample_hash):
    if not majority_hash:
        return False
    elif sample_hash != majority_hash:
        return True
    else:
        return False


class CoreClient(threading.Thread):
    """thread which takes control of basic mode switching, block creation and transaction pools operations"""

    def __init__(self, memserver, consensus, logger):
        threading.Thread.__init__(self)
        self.duration = 0
        self.logger = logger
        self.logger.info(f"Starting Core")
        self.memserver = memserver
        self.consensus = consensus
        self.run_interval = 1

    def update_periods(self):
        old_period = self.memserver.period
        self.memserver.since_last_block = get_since_last_block(logger=self.logger)

        if 20 > self.memserver.since_last_block > 0:
            self.memserver.period = 0
        elif 40 > self.memserver.since_last_block > 20:
            self.memserver.period = 1
        elif self.memserver.block_time > self.memserver.since_last_block > 40:
            self.memserver.period = 2
        elif self.memserver.since_last_block > self.memserver.block_time:
            self.memserver.period = 3

        if old_period != self.memserver.period:
            self.logger.info(f"Switched to period {self.memserver.period}")

    def normal_mode(self):
        try:
            self.update_periods()

            if self.memserver.period == 0 and self.memserver.user_tx_buffer:
                """merge user buffer inside 0 period"""
                buffered = merge_buffer(from_buffer=self.memserver.user_tx_buffer,
                                        to_buffer=self.memserver.tx_buffer)

                self.memserver.user_tx_buffer = buffered["from_buffer"]
                self.memserver.tx_buffer = buffered["to_buffer"]

            if self.memserver.period == 1 and self.memserver.tx_buffer:
                """merge node buffer inside 1 period"""
                buffered = merge_buffer(from_buffer=self.memserver.tx_buffer,
                                        to_buffer=self.memserver.transaction_pool)

                self.memserver.tx_buffer = buffered["from_buffer"]
                self.memserver.transaction_pool = buffered["to_buffer"]

            if self.memserver.period == 2 and minority_consensus(
                    majority_hash=self.consensus.majority_transaction_pool_hash,
                    sample_hash=self.memserver.transaction_pool_hash):
                """replace mempool in 2 period in case it is different from majority as last effort"""
                self.replace_transaction_pool()

            if self.memserver.period == 2 and minority_consensus(
                    majority_hash=self.consensus.majority_block_producers_hash,
                    sample_hash=self.memserver.block_producers_hash):
                """replace block producers in peace period in case it is different from majority as last effort"""
                self.replace_block_producers()

            self.memserver.reported_uptime = self.memserver.get_uptime()

            if self.memserver.period == 3:
                if self.memserver.peers and self.memserver.block_producers:
                    block_candidate = get_block_candidate(block_producers=self.memserver.block_producers,
                                                          block_producers_hash=self.memserver.block_producers_hash,
                                                          logger=self.logger,
                                                          transaction_pool=self.memserver.transaction_pool.copy(),
                                                          peer_file_lock=self.memserver.peer_file_lock
                                                          )
                    self.produce_block(block=block_candidate)

                else:
                    self.logger.warning("Criteria for block production not met")

        except Exception as e:
            self.logger.info(f"Error: {e}")
            raise

    def process_remote_block(self, block_message, remote_peer):
        """for blocks received by syncing that are not constructed locally"""
        self.produce_block(block=block_message,
                           remote=True,
                           remote_peer=remote_peer)

    def get_peer_to_sync_from(self, hash_pool):
        """peer to synchronize pool when out of sync, critical part
        not based on majority, but on trust matching until majority is achieved, hash pool
        is looped by occurrence until a trusted peer is found with one of the hashes"""
        try:
            sorted_hashes = sort_occurence(dict_to_val_list(hash_pool))

            shuffled_pool = shuffle_dict(hash_pool)
            participants = len(shuffled_pool.items())

            me = get_config()["ip"]
            if me in shuffled_pool:
                shuffled_pool.pop(me)
                """do not sync from self"""

            for hash_candidate in sorted_hashes:
                """go from the most common hash to the least common one"""
                for peer, value in shuffled_pool.items():
                    """pick random peer"""
                    peer_trust = load_trust(logger=self.logger,
                                            peer=peer,
                                            peer_file_lock=self.memserver.peer_file_lock)
                    """load trust score"""

                    if self.consensus.average_trust <= peer_trust and participants > 2:
                        if value == hash_candidate:
                            return peer

                    elif value == hash_candidate:
                        return peer

            else:
                self.logger.info("Ran out of options when picking trusted hash")
                return None

        except Exception as e:
            self.logger.info(f"Failed to get a peer to sync from: hash_pool: {hash_pool} error: {e}")
            return None

    def minority_block_consensus(self):
        """loads from drive to get latest info"""
        if not self.consensus.majority_block_hash:
            """if not ready"""
            return False
        elif get_block(self.consensus.majority_block_hash) and self.memserver.peers:
            """we are not out of sync when we know the majority block"""
            return False
        elif get_latest_block_info(logger=self.logger)["block_hash"] != self.consensus.majority_block_hash:
            return True
        else:
            return False

    def replace_transaction_pool(self):
        sync_from = self.get_peer_to_sync_from(hash_pool=self.consensus.transaction_hash_pool)
        if sync_from:
            self.memserver.transaction_pool = self.replace_pool(
                peer=sync_from,
                key="transaction_pool")

    def replace_block_producers(self):
        sync_from = self.get_peer_to_sync_from(hash_pool=self.consensus.block_producers_hash_pool)
        suggested_block_producers = self.replace_pool(
            peer=sync_from,
            key="block_producers")

        if suggested_block_producers:
            if get_config()["ip"] not in suggested_block_producers:
                adjust_trust(trust_pool=self.consensus.trust_pool,
                             entry=sync_from,
                             value=-25,
                             logger=self.logger,
                             peer_file_lock=self.memserver.peer_file_lock)

            for block_producer in suggested_block_producers:
                if block_producer != get_config()["ip"]:
                    address = get_remote_peer_address(sync_from, logger=self.logger)
                    if address:
                        save_peer(ip=block_producer,
                                  address=address,
                                  port=get_config()["port"],
                                  last_seen=get_timestamp_seconds())
                    else:
                        suggested_block_producers.pop(block_producer)
                        self.logger.error(f"{block_producer} not added to block producers")

            self.memserver.block_producers = set_and_sort(suggested_block_producers)
            save_block_producers(self.memserver.block_producers)

    def replace_pool(self, peer, key):
        """when out of sync to prevent forking"""
        self.logger.info(f"{key} out of sync with majority at critical time, replacing from trusted peer")

        suggested_pool = get_from_single_target(
            key=key,
            target_peer=peer,
            logger=self.logger)

        if suggested_pool:
            return suggested_pool
        else:
            adjust_trust(trust_pool=self.consensus.trust_pool,
                         entry=peer,
                         value=-50,
                         logger=self.logger,
                         peer_file_lock=self.memserver.peer_file_lock)

    def sync_mode(self):
        self.logger.warning("Entering sync mode")

        try:
            peer = self.get_peer_to_sync_from(
                hash_pool=self.consensus.block_hash_pool)

            if not peer:
                self.logger.info("Could not find suitably trusted peer")
            else:
                while self.memserver.sync_mode:

                    if knows_block(
                            peer,
                            hash=get_latest_block_info(logger=self.logger)["block_hash"],
                            logger=self.logger,
                    ):
                        self.logger.info(
                            f"{peer} knows block {get_latest_block_info(logger=self.logger)['block_hash']}"
                        )

                        new_blocks = get_blocks_after(
                            target_peer=peer,
                            from_hash=get_latest_block_info(logger=self.logger)[
                                "block_hash"
                            ],
                            count=50,
                            logger=self.logger,
                        )
                        if new_blocks:
                            for block in new_blocks:
                                self.process_remote_block(block, remote_peer=peer)

                        else:
                            self.logger.info(f"No newer blocks found from {peer}")
                            break

                    else:
                        rollback_one_block(logger=self.logger, lock=self.memserver.buffer_lock)
                        adjust_trust(
                            entry=peer,
                            value=-100,
                            logger=self.logger,
                            trust_pool=self.consensus.trust_pool,
                            peer_file_lock=self.memserver.peer_file_lock
                        )

                self.consensus.refresh_hashes()
                # self.replace_block_producers(peer=peer)

        except Exception as e:
            self.logger.info(f"Error: {e}")
            raise

    def incorporate_block(self, block):
        transactions = sort_list_dict(block["block_transactions"])
        try:
            for transaction in transactions:
                incorporate_transaction(
                    transaction=transaction,
                    block_hash=block["block_hash"])

            update_child_in_latest_block(block["block_hash"], self.logger)
            save_block(block, self.logger)
            set_latest_block_info(block_message=block)
            change_balance(address=block["block_creator"],
                           amount=block["block_reward"])

        except Exception as e:
            self.logger.error(f"Failed to incorporate block: {e}")
            raise

    def validate_transactions_in_block(self, block, logger, remote_peer, remote):

        transactions = sort_list_dict(block["block_transactions"])

        try:
            validate_all_spending(transaction_pool=transactions)
        except Exception as e:
            self.logger.error(f"Failed to validate spending during block production: {e}")
            if remote:
                adjust_trust(trust_pool=self.memserver.transaction_pool,
                             entry=remote_peer,
                             value=-10,
                             logger=self.logger,
                             peer_file_lock=self.memserver.peer_file_lock)
        else:
            for transaction in transactions:

                if transaction in self.memserver.transaction_pool:
                    self.memserver.transaction_pool.remove(transaction)

                if transaction in self.memserver.user_tx_buffer:
                    self.memserver.user_tx_buffer.remove(transaction)

                if transaction in self.memserver.tx_buffer:
                    self.memserver.tx_buffer.remove(transaction)

                try:
                    validate_transaction(transaction, logger=logger)
                except Exception as e:
                    self.logger.error(f"Failed to validate transaction during block production: {e}")
                    if remote:
                        adjust_trust(trust_pool=self.consensus.trust_pool,
                                     entry=remote_peer,
                                     value=-10,
                                     logger=self.logger,
                                     peer_file_lock=self.memserver.peer_file_lock)

    def produce_block(self, block, remote=False, remote_peer=None) -> None:
        with self.memserver.buffer_lock:
            try:
                gen_start = get_timestamp_seconds()
                self.logger.warning(f"Producing block")

                self.validate_transactions_in_block(block=block,
                                                    logger=self.logger,
                                                    remote_peer=remote_peer,
                                                    remote=remote)

                if not valid_block_gap(logger=self.logger,
                                       new_block=block,
                                       gap=self.memserver.block_time):

                    self.logger.info("Block gap too tight")
                    if remote:
                        adjust_trust(
                            entry=remote_peer,
                            value=-25,
                            logger=self.logger,
                            trust_pool=self.consensus.trust_pool,
                            peer_file_lock=self.memserver.peer_file_lock
                        )

                self.incorporate_block(block)

                gen_elapsed = get_timestamp_seconds() - gen_start
                self.logger.warning(f"Block hash: {block['block_hash']}")
                self.logger.warning(f"Block number: {block['block_number']}")
                self.logger.warning(f"Winner IP: {block['block_ip']}")
                self.logger.warning(f"Winner address: {block['block_creator']}")
                self.logger.warning(
                    f"Block reward: {to_readable_amount(block['block_reward'])}"
                )
                self.logger.warning(
                    f"Transactions in block: {len(block['block_transactions'])}"
                )
                self.logger.warning(f"Remote block: {remote}")
                self.logger.warning(f"Block size: {get_byte_size(block)} bytes")
                self.logger.warning(f"Production time: {gen_elapsed}")
            except Exception as e:
                self.logger.warning(f"Block production skipped due to {e}")

            self.consensus.refresh_hashes()

    def init_hashes(self):
        self.memserver.transaction_pool_hash = (
            self.memserver.get_transaction_pool_hash()
        )
        self.memserver.block_producers_hash = self.memserver.get_block_producers_hash()

    def check_mode(self):
        if self.minority_block_consensus():
            self.memserver.sync_mode = True
            self.logger.warning("We are out of consensus")
        else:
            self.memserver.sync_mode = False

    def run(self) -> None:
        self.init_hashes()
        update_local_address(logger=self.logger,
                             peer_file_lock=self.memserver.peer_file_lock)

        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()
                self.check_mode()

                if not self.memserver.sync_mode:
                    self.normal_mode()
                else:
                    self.sync_mode()

                self.duration = get_timestamp_seconds() - start
                time.sleep(self.run_interval)
            except Exception as e:
                self.logger.error(f"Error in core loop: {e}")
                time.sleep(1)

        self.logger.info("Termination code reached, bye")
