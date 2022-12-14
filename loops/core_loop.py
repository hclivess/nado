import asyncio
import sys
import threading
import time
import traceback
from transaction_ops import remove_outdated_transactions

from account_ops import increase_produced_count, change_balance
from block_ops import (
    knows_block,
    get_blocks_after,
    get_from_single_target,
    get_block_candidate,
    save_block_producers,
    valid_block_gap,
    update_child_in_latest_block,
    save_block,
    set_latest_block_info,
    get_block,
    construct_block,
    valid_block_timestamp,
    check_target_match
)
from config import get_timestamp_seconds
from data_ops import set_and_sort, shuffle_dict, sort_list_dict, get_byte_size, sort_occurrence, dict_to_val_list
from event_bus import EventBus
from loops.consensus_loop import change_trust
from peer_ops import load_trust, update_local_address, ip_stored, check_ip, qualifies_to_sync
from pool_ops import merge_buffer
from rollback import rollback_one_block
from transaction_ops import (
    to_readable_amount,
    validate_transaction,
    validate_all_spending, index_transactions
)

def minority_consensus(majority_hash, sample_hash):
    if not majority_hash:
        return False
    elif sample_hash != majority_hash:
        return True
    else:
        return False


def old_block(block):
    if block["block_timestamp"] < get_timestamp_seconds() - 86400:
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
        self.event_bus = EventBus()

    def update_periods(self):
        old_period = self.memserver.period
        self.memserver.since_last_block = get_timestamp_seconds() - self.memserver.latest_block["block_timestamp"]

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
                """merge user buffer to tx buffer inside 0 period"""
                buffered = merge_buffer(from_buffer=self.memserver.user_tx_buffer,
                                        to_buffer=self.memserver.tx_buffer,
                                        limit=self.memserver.transaction_buffer_limit,
                                        block_max=self.memserver.latest_block["block_number"] + 25,
                                        block_min=self.memserver.latest_block["block_number"])

                self.memserver.user_tx_buffer = buffered["from_buffer"]
                self.memserver.tx_buffer = buffered["to_buffer"]

            if self.memserver.period == 1 and self.memserver.tx_buffer:
                """merge tx buffer to transaction pool inside 1 period"""
                buffered = merge_buffer(from_buffer=self.memserver.tx_buffer,
                                        to_buffer=self.memserver.transaction_pool,
                                        limit=self.memserver.transaction_pool_limit,
                                        block_max=self.memserver.latest_block["block_number"] + 1,
                                        block_min=self.memserver.latest_block["block_number"])

                self.memserver.tx_buffer = buffered["from_buffer"]
                self.memserver.transaction_pool = buffered["to_buffer"]

            if self.memserver.period == 2:

                if minority_consensus(
                        majority_hash=self.consensus.majority_transaction_pool_hash,
                        sample_hash=self.memserver.transaction_pool_hash):
                    """replace mempool in 2 period in case it is different from majority as last effort"""
                    self.replace_transaction_pool()

                if minority_consensus(
                        majority_hash=self.consensus.majority_block_producers_hash,
                        sample_hash=self.memserver.block_producers_hash):
                    """replace block producers in peace period in case it is different from majority as last effort"""
                    self.replace_block_producers()

            self.memserver.reported_uptime = self.memserver.get_uptime()

            if self.memserver.period == 3:
                block_producers = self.memserver.block_producers.copy()
                peers = self.memserver.peers.copy()
                """make copies to avoid errors in case content changes"""

                if peers and block_producers:
                    block_candidate = get_block_candidate(block_producers=block_producers,
                                                          block_producers_hash=self.memserver.block_producers_hash,
                                                          logger=self.logger,
                                                          event_bus=self.event_bus,
                                                          transaction_pool=self.memserver.transaction_pool.copy(),
                                                          peer_file_lock=self.memserver.peer_file_lock,
                                                          latest_block=self.memserver.latest_block
                                                          )

                    self.produce_block(block=block_candidate,
                                       remote=False,
                                       remote_peer=None)

                    self.memserver.transaction_pool = remove_outdated_transactions(
                        self.memserver.transaction_pool.copy(),
                        self.memserver.latest_block["block_number"])

                    self.memserver.tx_buffer = remove_outdated_transactions(
                        self.memserver.tx_buffer.copy(),
                        self.memserver.latest_block["block_number"])

                    self.memserver.user_tx_buffer = remove_outdated_transactions(
                        self.memserver.user_tx_buffer.copy(),
                        self.memserver.latest_block["block_number"])

                else:
                    self.logger.warning("Criteria for block production not met")

        except Exception as e:
            self.logger.info(f"Error: {e}")
            raise

    def get_peer_to_sync_from(self, source_pool):
        """peer to synchronize pool when out of sync, critical part
        not based on majority, but on trust matching until majority is achieved, hash pool
        is looped by occurrence until a trusted peer is found with one of the hashes
        hash_pool argument is the pool to sort and sync from (block, tx, block producer pools)"""

        first_peer = None

        if self.memserver.force_sync_ip:
            """force sync"""
            return self.memserver.force_sync_ip

        source_pool_copy = source_pool.copy()

        try:
            sorted_hashes = sort_occurrence(dict_to_val_list(source_pool_copy))[:self.memserver.cascade_limit]
            shuffled_pool = shuffle_dict(source_pool_copy)
            # participants = len(shuffled_pool.items())

            if self.memserver.ip in shuffled_pool:
                shuffled_pool.pop(self.memserver.ip)
                """do not sync from self"""

            for hash_candidate in sorted_hashes:
                """go from the most common hash to the least common one"""
                self.memserver.cascade_depth = sorted_hashes.index(hash_candidate) + 1

                for peer, value in shuffled_pool.items():
                    """pick random peer"""
                    peer_trust = load_trust(logger=self.logger,
                                            peer=peer,
                                            peer_file_lock=self.memserver.peer_file_lock)
                    """load trust score"""

                    peer_protocol = self.consensus.status_pool[peer]["protocol"]
                    """get protocol version"""

                    if not first_peer:
                        if value == hash_candidate:
                            first_peer = peer

                    if check_ip(peer):
                        if qualifies_to_sync(peer=peer,
                                             peer_protocol=peer_protocol,
                                             peer_trust=peer_trust,
                                             memserver_protocol=self.memserver.protocol,
                                             unreachable_list=self.memserver.unreachable.keys(),
                                             average_trust=self.consensus.average_trust,
                                             purge_list=self.memserver.purge_peers_list,
                                             peer_hash=value,
                                             required_hash=hash_candidate,
                                             promiscuous=self.memserver.promiscuous):
                            return peer
            else:
                self.logger.info(f"Ran out of options when picking trusted hash, using the first tested {first_peer}")
                time.sleep(1)
                return first_peer

        except Exception as e:
            self.logger.info(f"Failed to get a peer to sync from: hash_pool: {source_pool_copy} error: {e}")
            return None

    def minority_block_consensus(self):
        """loads from drive to get latest info"""
        if not self.consensus.majority_block_hash:
            """if not ready"""
            return False
        elif get_block(self.consensus.majority_block_hash) and self.memserver.peers:
            """we are not out of sync when we know the majority block"""
            return False
        elif self.memserver.latest_block["block_hash"] != self.consensus.majority_block_hash:
            """we are out of consensus and need to sync"""
            return True
        else:
            return False

    def replace_transaction_pool(self):
        sync_from = self.get_peer_to_sync_from(source_pool=self.consensus.block_hash_pool)
        """get peer which is in majority for the given hash_pool"""

        if sync_from:
            self.memserver.transaction_pool = self.replace_pool(
                peer=sync_from,
                key="transaction_pool")

    def replace_block_producers(self):
        sync_from = self.get_peer_to_sync_from(source_pool=self.consensus.block_hash_pool)
        """get peer which is in majority for the given hash_pool"""

        suggested_block_producers = self.replace_pool(
            peer=sync_from,
            key="block_producers")

        if suggested_block_producers:
            if self.memserver.ip not in suggested_block_producers:
                change_trust(self.consensus, peer=sync_from, value=-10000)
                self.logger.info(f"Our node not present in suggested block producers from {sync_from}")

            replacements = []
            for block_producer in suggested_block_producers:
                if ip_stored(block_producer):
                    replacements.append(block_producer)
                else:
                    self.logger.info(f"{block_producer} not added to block producers, because it is not locally stored")

            self.memserver.block_producers = set_and_sort(replacements)
            save_block_producers(self.memserver.block_producers)

    def replace_pool(self, peer, key):
        """replace pool (block, tx, block producers) when out of sync to prevent forking"""
        self.logger.info(f"Replacing {key} from {peer}")

        suggested_pool = asyncio.run(get_from_single_target(
            key=key,
            target_peer=peer,
            logger=self.logger))

        if suggested_pool:
            return suggested_pool
        else:
            change_trust(self.consensus, peer=peer, value=-10000)
            self.logger.info(f"Could not replace {key} from {peer}")

    def emergency_mode(self):
        self.logger.warning("Entering emergency mode")
        try:
            while self.memserver.emergency_mode and not self.memserver.terminate:
                peer = self.get_peer_to_sync_from(
                    source_pool=self.consensus.block_hash_pool)
                if not peer:
                    self.logger.info("Could not find a suitably trusted peer")
                    time.sleep(1)
                else:
                    with self.memserver.buffer_lock:
                        block_hash = self.memserver.latest_block["block_hash"]
                        known_block = asyncio.run(knows_block(
                            target_peer=peer,
                            port=self.memserver.port,
                            hash=block_hash,
                            logger=self.logger))

                        if known_block:
                            self.logger.info(
                                f"{peer} knows block {self.memserver.latest_block['block_hash']}"
                            )

                            try:
                                new_blocks = asyncio.run(get_blocks_after(
                                    target_peer=peer,
                                    from_hash=block_hash,
                                    count=50,
                                ))

                                if new_blocks:
                                    for block in new_blocks:
                                        if not self.memserver.terminate:
                                            uninterrupted = self.produce_block(block=block,
                                                                               remote=True,
                                                                               remote_peer=peer)
                                            if not uninterrupted:
                                                break


                                else:
                                    self.logger.info(f"No newer blocks found from {peer}")
                                    break

                            except Exception as e:
                                change_trust(self.consensus, peer=peer, value=-10000)
                                self.logger.error(f"Failed to get blocks after {block_hash} from {peer}: {e}")
                                break

                        elif not known_block:
                            if self.memserver.rollbacks <= self.memserver.max_rollbacks:
                                self.memserver.latest_block = rollback_one_block(logger=self.logger,
                                                                                 block=self.memserver.latest_block)
                                self.memserver.rollbacks += 1
                                change_trust(self.consensus, peer=peer, value=-100000)
                            else:
                                self.logger.error(f"Rollbacks exhausted")
                                self.memserver.rollbacks = 0
                                # self.memserver.purge_peers_list.append(peer)
                                break

                        self.logger.info(f"Maximum reached cascade depth: {self.memserver.cascade_depth}")

        except Exception as e:
            self.logger.info(f"Error: {e}")
            raise

    def rebuild_block(self, block):
        # todo add block size check?
        return construct_block(block_timestamp=block["block_timestamp"],
                               block_number=self.memserver.latest_block["block_number"] + 1,
                               parent_hash=self.memserver.latest_block["block_hash"],
                               block_ip=block["block_ip"],
                               creator=block["block_creator"],
                               transaction_pool=block["block_transactions"],
                               block_producers_hash=block["block_producers_hash"],
                               block_reward=block["block_reward"])

    def incorporate_block(self, block: dict, sorted_transactions: list):
        """successful execution mandatory, must not raise a failure"""
        self.logger.warning(f"Producing block")

        index_transactions(block=block,
                           sorted_transactions=sorted_transactions,
                           logger=self.logger)

        update_child_in_latest_block(child_hash=block["block_hash"],
                                     logger=self.logger,
                                     parent=self.memserver.latest_block)

        change_balance(address=block["block_creator"],
                       amount=block["block_reward"],
                       logger=self.logger
                       )

        increase_produced_count(address=block["block_creator"],
                                amount=block["block_reward"],
                                logger=self.logger
                                )

        save_block(block, self.logger)
        set_latest_block_info(block=block,
                              logger=self.logger)

    def validate_transactions_in_block(self, block, logger, remote_peer, remote):
        transactions = sort_list_dict(block["block_transactions"])

        if block["block_number"] > 20000:  # compat
            if not check_target_match(transactions, block["block_number"], logger=logger):
                self.logger.error(f"Transactions mismatch target block")
                raise

        try:
            validate_all_spending(transaction_pool=transactions)
        except Exception as e:
            self.logger.error(f"Failed to validate spending during block preparation: {e}")
            if remote:
                change_trust(self.consensus, peer=remote_peer, value=-1000)
            raise

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
                    self.logger.error(f"Failed to validate transaction during block preparation: {e}")
                    if remote:
                        change_trust(self.consensus, peer=remote_peer, value=-1000)
                    raise

    def verify_block(self, block, remote, remote_peer=None, is_old=False):
        """this function has critical checks and must raise a failure/halt if there is one"""
        # todo move exceptions lower (as in rollback) and avoid rising here directly
        try:
            self.logger.warning(f"Preparing block")

            if not valid_block_timestamp(new_block=block,
                                         old_block=self.memserver.latest_block):
                raise ValueError(f"Invalid block timestamp")

            if not is_old or not self.memserver.quick_sync:
                self.validate_transactions_in_block(block=block,
                                                    logger=self.logger,
                                                    remote_peer=remote_peer,
                                                    remote=remote)

            if not valid_block_gap(old_block=self.memserver.latest_block,
                                   new_block=block):

                self.logger.info("Block gap too tight")
                if remote:
                    change_trust(self.consensus, peer=remote_peer, value=-1000)

            sorted_transactions = sort_list_dict(block["block_transactions"])
            return sorted_transactions

        except Exception as e:
            self.logger.error(f"Block preparation failed due to: {e}")
            raise

    def produce_block(self, block, remote, remote_peer) -> bool:
        """This function returns boolean so node can decide whether to continue with sync"""
        try:
            gen_start = get_timestamp_seconds()
            is_old = old_block(block=block)

            if remote:
                try:
                    block = self.rebuild_block(block)
                except Exception as e:
                    raise ValueError(f"Failed to reconstruct block {e}")

            verified_block = self.verify_block(block, remote=remote, remote_peer=remote_peer, is_old=is_old)

            self.incorporate_block(block=block, sorted_transactions=verified_block)
            self.memserver.latest_block = block

            gen_elapsed = get_timestamp_seconds() - gen_start

            if self.memserver.ip == block['block_ip'] and self.memserver.address == block['block_creator'] and \
                    block['block_reward'] > 0:
                self.logger.warning(f"$$$ Congratulations! You won! $$$")

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
            self.logger.warning(f"Remote block: {remote} ({remote_peer})")
            self.logger.warning(f"Block size: {get_byte_size(block)} bytes")
            self.logger.warning(f"Production time: {gen_elapsed}")
            self.logger.warning(f"Old block: {is_old}")
            return True

        except Exception as e:
            self.logger.warning(f"Block production skipped due to: {e}")
            time.sleep(1)
            return False

    def init_hashes(self):
        self.memserver.transaction_pool_hash = (
            self.memserver.get_transaction_pool_hash()
        )
        self.memserver.block_producers_hash = self.memserver.get_block_producers_hash()

    def check_mode(self):
        if self.minority_block_consensus():
            self.memserver.emergency_mode = True
            self.logger.warning("We are out of consensus")
        else:
            self.memserver.emergency_mode = False

            if self.consensus.block_hash_pool_percentage > 80:
                self.memserver.force_sync_ip = None

    async def penalty_list_update_handler(self, event):
        self.memserver.penalties = event

    def run(self) -> None:
        self.init_hashes()
        update_local_address(logger=self.logger,
                             peer_file_lock=self.memserver.peer_file_lock)
        self.event_bus.add_listener('penalty-list-update', self.penalty_list_update_handler)

        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()
                self.check_mode()

                if not self.memserver.emergency_mode:
                    self.normal_mode()
                else:
                    self.emergency_mode()

                self.consensus.refresh_hashes()
                self.duration = get_timestamp_seconds() - start
                time.sleep(self.run_interval)
            except Exception as e:
                self.logger.error(f"Error in core loop: {e} {traceback.print_exc()}")
                time.sleep(1)
                # raise #test

        self.event_bus.remove_listener('penalty-list-update', self.penalty_list_update_handler)

        self.logger.info("Termination code reached, bye")
        sys.exit(0)
