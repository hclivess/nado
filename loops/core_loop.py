import asyncio
import sys
import threading
import time
import traceback

from config import get_timestamp_seconds
from event_bus import EventBus
from loops.consensus_loop import change_trust
from ops.account_ops import increase_produced_count, change_balance, get_totals, index_totals, get_bonded_registry
from ops.block_ops import (
    knows_block,
    get_blocks_after,
    get_from_single_target,
    get_block_candidate,
    save_block_producers,
    update_child_in_latest_block,
    save_block,
    set_latest_block_info,
    set_earliest_block_info,
    get_block,
    construct_block,
    get_block_reward,
    epoch_beacon,
    check_target_match,
    valid_block_timestamp,
    block_already_indexed,
    index_block_number,
    pick_best_producer,
)
from ops.data_ops import get_home
from ops.mining_ops import select_producer, epoch_of
from ops.sqlite_ops import transaction
from protocol import split_block_reward, TREASURY_ADDRESS, CHAIN_ID, REWARD_CAP
from ops.data_ops import set_and_sort, shuffle_dict, sort_list_dict, get_byte_size, sort_occurrence, dict_to_val_list
from ops.peer_ops import load_trust, update_local_address, ip_stored, check_ip, qualifies_to_sync, announce_me, get_remote_status, get_producer_set
from ops import snapshot_ops
from ops.pool_ops import merge_buffer, cull_buffer
from ops.transaction_ops import remove_outdated_transactions
from ops.transaction_ops import (
    to_readable_amount,
    validate_transaction,
    validate_all_spending, index_transactions
)
from rollback import rollback_one_block, MissingParentError

# protocol cap on a block reward (mirrors get_block_reward's reward_cap)
MAX_BLOCK_REWARD = 5000000000


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
        self.consecutive = 0
        self.snapshot_attempted = False

    def get_period(self):
        """Enter every period at least period_counter times. Iterator is present in case node is stuck in phase 3.
        Routine should always start from 0 when node is initiated and be at 3 when enough time passed for block
        to be produced"""

        old_periods = self.memserver.periods
        self.memserver.since_last_block = get_timestamp_seconds() - self.memserver.latest_block["block_timestamp"]

        if self.memserver.reported_uptime < self.memserver.block_time:
            """init mode"""
            self.memserver.periods = [0, 1, 2]
            mode = "Initialization period..."

        elif self.memserver.since_last_block < self.memserver.block_time:
            """stable mode"""
            if 20 > self.memserver.since_last_block > 0 or self.consecutive > 0 or self.memserver.force_sync_ip:
                self.consecutive = 0
                self.memserver.periods = [0]
            elif 40 > self.memserver.since_last_block > 20:
                self.memserver.periods = [1]
            elif self.memserver.block_time > self.memserver.since_last_block > 40:
                self.memserver.periods = [2]
            elif self.memserver.since_last_block > self.memserver.block_time:
                self.memserver.periods = [3]
            self.memserver.switch_mode = {"mode": 2,
                                          "name": "Stable switch"}

        elif get_timestamp_seconds() - self.memserver.block_generation_age > 10:
            """generate a block if x seconds have passed"""
            self.memserver.periods = [3]
            self.memserver.switch_mode = {"mode": 1,
                                          "name": "Target catch up"}
        else:
            """do not generate block more than once per x seconds"""
            self.memserver.periods = [0, 1, 2]
            self.memserver.switch_mode = {"mode": 0,
                                          "name": "Quick switch"}

        if old_periods != self.memserver.periods:
            self.logger.debug(
                f"Switched to period {self.memserver.periods}; Mode: {self.memserver.switch_mode['name']}")

    def normal_mode(self):
        try:
            self.get_period()
            if 0 in self.memserver.periods and self.memserver.switch_mode["mode"] == 2:
                self.memserver.replaced_this_round = False

            if 0 in self.memserver.periods and self.memserver.user_tx_buffer:
                """merge user buffer to tx buffer inside 0 period"""
                buffered = merge_buffer(from_buffer=self.memserver.user_tx_buffer,
                                        to_buffer=self.memserver.tx_buffer,
                                        block_max=self.memserver.latest_block["block_number"] + 25,
                                        block_min=self.memserver.latest_block["block_number"])

                self.memserver.user_tx_buffer = buffered["from_buffer"]
                self.memserver.tx_buffer = buffered["to_buffer"]

            if 1 in self.memserver.periods and self.memserver.tx_buffer:
                """merge tx buffer to transaction pool inside 1 period"""
                buffered = merge_buffer(from_buffer=self.memserver.tx_buffer,
                                        to_buffer=self.memserver.transaction_pool,
                                        block_max=self.memserver.latest_block["block_number"] + 1,
                                        block_min=self.memserver.latest_block["block_number"])

                self.memserver.tx_buffer = cull_buffer(buffer=buffered["from_buffer"],
                                                       limit=self.memserver.transaction_buffer_limit)

                self.memserver.transaction_pool = cull_buffer(buffer=buffered["to_buffer"],
                                                              limit=self.memserver.transaction_pool_limit)

            if 2 in self.memserver.periods and not self.memserver.replaced_this_round:
                self.memserver.replaced_this_round = True

                if minority_consensus(
                        majority_hash=self.consensus.majority_transaction_pool_hash,
                        sample_hash=self.memserver.transaction_pool_hash):
                    """replace mempool in 2 period in case it is different from majority as last effort"""
                    self.replace_transaction_pool()
                    self.memserver.transaction_pool_hash = self.memserver.get_transaction_pool_hash()

                if minority_consensus(
                        majority_hash=self.consensus.majority_block_producers_hash,
                        sample_hash=self.memserver.block_producers_hash):
                    """replace block producers in peace period in case it is different from majority as last effort"""
                    self.replace_block_producers()
                    self.memserver.block_producers_hash = self.memserver.get_block_producers_hash()

            self.memserver.reported_uptime = self.memserver.get_uptime()

            if 3 in self.memserver.periods:
                block_producers = self.memserver.block_producers.copy()
                peers = self.memserver.peers.copy()
                """make copies to avoid errors in case content changes"""

                if len(peers) >= self.memserver.min_peers and block_producers and not self.memserver.force_sync_ip:
                    block_candidate = get_block_candidate(block_producers=block_producers,
                                                          block_producers_hash=self.memserver.block_producers_hash,
                                                          logger=self.logger,
                                                          event_bus=self.event_bus,
                                                          transaction_pool=self.memserver.transaction_pool.copy(),
                                                          latest_block=self.memserver.latest_block,
                                                          block_time=self.memserver.block_time
                                                          )

                    # S4.3: get_block_candidate returns None when no bonded identity is eligible
                    # (empty registry / total_shares == 0). Skip this round rather than crash.
                    if block_candidate is not None:
                        self.produce_block(block=block_candidate,
                                           remote=False,
                                           remote_peer=None)

                        self.memserver.block_generation_age = get_timestamp_seconds()

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
                        self.logger.warning("No eligible bonded producer this round; skipping production")

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

            if not sorted_hashes:
                self.logger.info(f"No hashes to sync from")

            else:
                for hash_candidate in sorted_hashes:
                    """go from the most common hash to the least common one"""

                    self.logger.info(f"Working with {hash_candidate} from a pool of {len(sorted_hashes)}")
                    self.memserver.cascade_depth = sorted_hashes.index(hash_candidate) + 1

                    for peer, value in shuffled_pool.items():
                        if peer not in self.memserver.purge_peers_list:  # sadly, the whole purge_peers() takes a prohibitively long time for some reason
                            try:
                                peer_trust = self.consensus.trust_pool[peer]
                                """load trust score"""

                                peer_protocol = self.consensus.status_pool[peer]["protocol"]
                                """get protocol version"""

                                known_block = asyncio.run(knows_block(
                                    target_peer=peer,
                                    port=self.memserver.port,
                                    hash=self.memserver.earliest_block["block_hash"],
                                    logger=self.logger))

                                if known_block:
                                    known_tree = True
                                else:
                                    known_tree = False

                                if not first_peer:
                                    if value == hash_candidate:
                                        first_peer = peer

                                if check_ip(peer):
                                    qualifies = qualifies_to_sync(peer=peer,
                                                                  peer_protocol=peer_protocol,
                                                                  peer_trust=peer_trust,
                                                                  memserver_protocol=self.memserver.protocol,
                                                                  known_tree=known_tree,
                                                                  unreachable_list=self.memserver.unreachable.keys(),
                                                                  median_trust=self.consensus.trust_median,
                                                                  peer_hash=value,
                                                                  required_hash=hash_candidate,
                                                                  promiscuous=self.memserver.promiscuous)
                                    if qualifies["result"]:
                                        self.logger.debug(f"{peer} qualified for sync")
                                        return peer
                                    else:
                                        self.logger.debug(f"{peer} not qualified for sync: {qualifies['flag']}")

                                        self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                                 peer=peer,
                                                                                 value=-1)
                            except Exception as e:
                                self.logger.info(f"Peer {peer} error: {e}")
                                self.memserver.ban_peer(peer)

                else:
                    self.logger.info(f"Ran out of options when picking trusted hash")
                    return None

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
            suggested_tx_pool = self.replace_pool(peer=sync_from, key="transaction_pool")

            if suggested_tx_pool:
                self.memserver.transaction_pool = suggested_tx_pool

    def replace_block_producers(self):
        sync_from = self.get_peer_to_sync_from(source_pool=self.consensus.block_hash_pool)
        """get peer which is in majority for the given hash_pool"""

        if sync_from:
            suggested_block_producers = self.replace_pool(
                peer=sync_from,
                key="block_producers")

            if suggested_block_producers:
                if self.memserver.ip not in suggested_block_producers:
                    self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                             peer=sync_from,
                                                             value=-1)
                    self.logger.info(f"Our node not present in suggested block producers from {sync_from}")
                    announce_me(
                        targets=[sync_from],
                        port=self.memserver.port,
                        my_ip=self.memserver.ip,
                        logger=self.logger,
                        fail_storage=self.memserver.purge_peers_list
                    )

                replacements = []
                for block_producer in suggested_block_producers:
                    if ip_stored(block_producer):
                        replacements.append(block_producer)
                    elif block_producer not in self.memserver.peer_buffer:
                        self.logger.info(f"{block_producer} not stored locally and will be probed")
                        self.memserver.peer_buffer.append(block_producer)
                    else:
                        self.logger.info(f"{block_producer} currently in buffer, aborting")
                        return

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
            self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                     peer=peer,
                                                     value=-1)
            self.logger.info(f"Could not replace {key} from {peer}")

    def snapshot_bootstrap(self) -> bool:
        """For a fresh node (still at genesis), bulk-download verified account state
        from peers instead of replaying the entire chain. Strictly additive and fully
        guarded: it runs at most once, only while latest_block is genesis, and ANY
        failure returns False so the normal block-by-block replay below proceeds. It
        therefore can never disrupt an established node or a re-org.

        NOTE: the multi-peer path needs validation on a live network with real peers;
        the deterministic build/verify/import and the quorum decision are unit-tested,
        but end-to-end bootstrap from live peers has not been exercised here."""
        if self.snapshot_attempted or self.memserver.latest_block["block_number"] != 0:
            return False
        self.snapshot_attempted = True
        try:
            peers = list(self.memserver.peers)
            if len(peers) < self.memserver.min_peers:
                return False

            # 1) collect peers' advertised snapshots; require a super-majority (Sybil gate)
            async def _statuses(ips):
                return await asyncio.gather(*[get_remote_status(ip, logger=self.logger) for ip in ips],
                                            return_exceptions=True)
            raw = asyncio.run(_statuses(peers))
            statuses = [s if isinstance(s, dict) else None for s in raw]
            agreed = snapshot_ops.agree_snapshot(statuses, min_peers=self.memserver.min_peers, threshold=0.8)
            if not agreed:
                self.logger.info("No snapshot quorum among peers; using full sync")
                return False

            target_hash = agreed["snapshot_hash"]
            target_height = agreed["snapshot_height"]
            self.logger.warning(
                f"Snapshot quorum at height {target_height} ({agreed['votes']}/{agreed['responders']} peers)")

            source = next((ip for ip, st in zip(peers, statuses)
                           if st and st.get("snapshot_hash") == target_hash), None)
            if not source:
                return False

            # 2) fetch, then verify against the quorum hash and re-derive the state root locally
            manifest, chunks = asyncio.run(
                snapshot_ops.fetch_snapshot(source, self.memserver.port, logger=self.logger))
            if not manifest or manifest.get("snapshot_hash") != target_hash:
                self.logger.warning("Fetched snapshot does not match the agreed hash")
                return False
            if not snapshot_ops.import_snapshot(manifest, chunks, logger=self.logger):
                return False

            # 3) anchor to block C so normal sync replays only the C..tip tail
            anchor = asyncio.run(
                snapshot_ops.fetch_block(source, self.memserver.port, manifest["block_hash"]))
            if (not anchor or anchor.get("block_hash") != manifest["block_hash"]
                    or anchor.get("block_number") != target_height):
                self.logger.warning("Could not anchor snapshot to its checkpoint block; using full sync")
                return False

            save_block(anchor, logger=self.logger)
            set_earliest_block_info(earliest_block=anchor, logger=self.logger)
            set_latest_block_info(latest_block=anchor, logger=self.logger)
            self.memserver.earliest_block = anchor
            self.memserver.latest_block = anchor
            self.logger.warning(f"Snapshot bootstrap complete at height {target_height}; replaying tail")
            return True

        except Exception as e:
            self.logger.error(f"Snapshot bootstrap failed, falling back to full sync: {e}")
            return False

    def emergency_mode(self):
        self.logger.warning("Entering emergency mode")
        if self.snapshot_bootstrap():
            self.logger.warning("State bootstrapped from snapshot; continuing with tail sync")
        try:
            self.logger.warning("Looping emergency mode")
            while self.memserver.emergency_mode and not self.memserver.terminate:
                peer = self.get_peer_to_sync_from(source_pool=self.consensus.block_hash_pool)
                if not peer:
                    self.logger.info("Could not find a suitably trusted peer")
                    time.sleep(1)
                else:
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
                                logger=self.logger
                            ))

                            if new_blocks:
                                for block in new_blocks:
                                    if not self.memserver.terminate:
                                        uninterrupted = self.produce_block(block=block,
                                                                           remote=True,
                                                                           remote_peer=peer)
                                        if not uninterrupted:
                                            break

                                    self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                             peer=peer,
                                                                             value=1)
                            else:
                                self.logger.info(f"No newer blocks found from {peer}")
                                break

                        except Exception as e:
                            self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                     peer=peer,
                                                                     value=-1)
                            self.logger.error(f"Failed to get blocks after {block_hash} from {peer}: {e}")
                            break

                    elif not known_block:
                        if self.memserver.rollbacks <= self.memserver.max_rollbacks:
                            try:
                                self.memserver.latest_block = rollback_one_block(logger=self.logger,
                                                                                 block=self.memserver.latest_block)
                            except MissingParentError as e:
                                # we have run out of local history to roll back through (e.g.
                                # a snapshot-bootstrapped node). Abort the cascade and let the
                                # next emergency cycle resync (snapshot/full) instead of spinning.
                                self.logger.error(f"Rollback aborted, resync required: {e}")
                                self.memserver.rollbacks = 0
                                break

                            if not self.memserver.force_sync_ip:
                                self.memserver.rollbacks += 1
                            self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                     peer=peer,
                                                                     value=-1)
                        else:
                            self.logger.error(
                                f"Rollbacks exhausted ({self.memserver.rollbacks}/{self.memserver.max_rollbacks})")
                            self.memserver.rollbacks = 0
                            break

                    self.logger.info(f"Maximum reached cascade depth: {self.memserver.cascade_depth}")

        except Exception as e:
            self.logger.info(f"Error: {e}")
            raise

    def rebuild_block(self, block):
        # todo add block size check?
        # Reconstruct the block deterministically from the LOCAL tip + the block's tx set.
        # reward and cumulative_fees are RECOMPUTED here (not copied from the peer), so a peer
        # cannot inject an inflated reward: the reconstructed hash only matches the network if
        # the canonical reward/cumfee were used.
        parent = self.memserver.latest_block
        block_number = parent["block_number"] + 1
        # S4.3: RECOMPUTE the winner (creator/block_ip) from the local parent state + beacon
        # rather than copying block_ip/block_creator from the peer, so a lying relay cannot
        # misattribute the reward or fork an honest node — the reconstructed block is canonical.
        winner = select_producer(get_bonded_registry(), epoch_beacon(epoch_of(block_number)), slot=block_number)
        return construct_block(
            block_timestamp=parent["block_timestamp"] + self.memserver.block_time,
            block_number=block_number,
            parent_hash=parent["block_hash"],
            block_ip=winner,
            creator=winner,
            transaction_pool=block["block_transactions"],
            block_producers_hash=block["block_producers_hash"],
            block_reward=get_block_reward(parent_block=parent, logger=self.logger),
            parent_cumulative_fees=parent.get("cumulative_fees", 0))

    def incorporate_block(self, block: dict, sorted_transactions: list):
        """successful execution mandatory, must not raise a failure"""
        # M4 idempotency: if this exact block was already incorporated (its hash is in
        # block_index), don't re-apply its balances/reward. Protects against the same
        # block being re-fetched during sync or replayed after a restart that had
        # already advanced the tip (which would otherwise double-credit the reward).
        if block_already_indexed(block["block_hash"]):
            self.logger.warning(f"Block {block['block_hash']} already incorporated; skipping (idempotent)")
            return

        self.logger.warning(f"Producing block")

        # File writes FIRST (idempotent, safe to redo on replay): the block body must exist
        # before block_index references it, and the parent's child pointer is idempotent.
        save_block(block, self.logger)
        update_child_in_latest_block(child_hash=block["block_hash"],
                                     logger=self.logger,
                                     parent=self.memserver.latest_block)

        # ATOMIC state mutation: tx index + balances + treasury + produced + totals + the
        # block_index 'applied' marker all commit together or not at all, so a crash mid-apply
        # leaves the block UNapplied (and block_already_indexed lets the replay re-apply it
        # cleanly) instead of double-crediting the reward (audit LO-1/CO-4).
        index_db = f"{get_home()}/index/index.db"
        with transaction(index_db):
            index_transactions(block=block,
                               sorted_transactions=sorted_transactions,
                               logger=self.logger)

            # canonical 90/10 split: producer gets the floor, treasury the exact remainder, so
            # the two credits sum to block_reward (single source: protocol.split_block_reward).
            # rollback_one_block reverses with the identical split, so they can never drift.
            producer_cut, treasury_cut = split_block_reward(block["block_reward"])
            change_balance(address=block["block_creator"], amount=producer_cut, logger=self.logger)
            if treasury_cut:
                change_balance(address=TREASURY_ADDRESS, amount=treasury_cut, logger=self.logger)

            # the producer's penalty metric tracks what it actually earned (its 90% cut)
            increase_produced_count(address=block["block_creator"], amount=producer_cut, logger=self.logger)

            totals = get_totals(block=block)  # produced = full reward = total emission
            index_totals(produced=totals["produced"],
                         fees=totals["fees"],
                         block_height=block["block_number"])

            index_block_number(block)  # the applied marker, atomic with the state above

        # Advance the tip pointer file only AFTER the atomic state commit. A crash before this
        # just leaves a stale tip that re-syncs forward; block_already_indexed prevents re-apply.
        set_latest_block_info(latest_block=block, logger=self.logger)

    def validate_transactions_in_block(self, block, logger, remote_peer, remote):
        transactions = sort_list_dict(block["block_transactions"])

        # target-block matching enforced from block 1 (the >20000 compat gate is gone)
        if not check_target_match(transactions, block["block_number"], logger=logger):
            self.logger.error("Transactions mismatch target block")
            raise ValueError("Transactions mismatch target block")

        try:
            validate_all_spending(transaction_pool=transactions)
        except Exception as e:
            self.logger.error(f"Failed to validate spending during block preparation: {e}")
            if remote:
                self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                         peer=remote_peer,
                                                         value=-1)
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
                    validate_transaction(transaction=transaction,
                                         logger=logger,
                                         block_height=self.memserver.latest_block["block_number"])
                except Exception as e:
                    self.logger.error(f"Failed to validate transaction during block preparation: {e}")
                    if remote:
                        self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                 peer=remote_peer,
                                                                 value=-1)
                    raise

    def validate_block_producer(self, block):
        """S4.3 FAIL-CLOSED authorship: recompute the deterministic BONDED winner for this height
        (from parent account state + the epoch beacon) and reject the block unless its
        block_creator equals that winner. block_creator is the address that actually receives the
        90/10 reward in incorporate_block, so binding it closes both the old fail-OPEN gap
        (unknown producer set -> allow) and the attacker-misattribution vector.

        This runs inside verify_block, strictly BEFORE incorporate_block, so get_bonded_registry()
        reflects PARENT state. v1 has no in-block bond txs, so the registry is constant across the
        chain; once bond txs land, the rollback/snapshot re-verify path must reset the tip to the
        block's parent before calling this (else it would read post-apply state)."""
        block_number = block["block_number"]
        winner = select_producer(get_bonded_registry(),
                                 epoch_beacon(epoch_of(block_number)),
                                 slot=block_number)
        if winner is None:
            raise ValueError("No eligible bonded producer for this block (fail-closed)")
        if block.get("block_creator") != winner:
            raise ValueError(
                f"Block creator {block.get('block_creator')} is not the selected winner {winner}")

    def verify_block(self, block, remote, remote_peer=None, is_old=False):
        """this function has critical checks and must raise a failure/halt if there is one"""
        # todo move exceptions lower (as in rollback) and avoid rising here directly
        try:
            self.logger.warning(f"Preparing block")

            if not valid_block_timestamp(new_block=block):
                raise ValueError(f"Invalid block timestamp {block['block_timestamp']}")

            # chain-id binds the block to this chain (anti cross-chain / pre-relaunch replay)
            if block.get("chain_id") != CHAIN_ID:
                raise ValueError(f"Wrong or missing chain id {block.get('chain_id')!r}")

            # The reward is RECOMPUTED from the block's parent ancestry and enforced for
            # equality (not merely range-checked): a synced block whose reward != the
            # deterministic value is rejected, closing the old "claim any reward <= cap" mint.
            # Cheap range pre-check first (also stops a negative reward wedging change_balance).
            reward = block.get("block_reward")
            if not isinstance(reward, int) or isinstance(reward, bool) or reward < 0 or reward > REWARD_CAP:
                raise ValueError(f"Invalid block reward {reward!r}")
            expected_reward = get_block_reward(parent_block=self.memserver.latest_block, logger=self.logger)
            if reward != expected_reward:
                raise ValueError(f"Block reward {reward} != deterministic {expected_reward}")

            self.validate_block_producer(block)

            if not is_old or not self.memserver.quick_sync:
                self.validate_transactions_in_block(block=block,
                                                    logger=self.logger,
                                                    remote_peer=remote_peer,
                                                    remote=remote)

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

            if self.memserver.latest_block["block_creator"] == block["block_creator"]:
                self.consecutive += 1
            else:
                self.consecutive = 0

            self.incorporate_block(block=block, sorted_transactions=verified_block)
            self.memserver.latest_block = block

            gen_elapsed = get_timestamp_seconds() - gen_start

            # block_ip is now the winner ADDRESS (S4.3), so identity is the address match alone
            if self.memserver.address == block['block_creator'] and block['block_reward'] > 0:
                self.logger.warning(f"$$$ Congratulations! You won! $$$")

            self.logger.warning(f"Block hash: {block['block_hash']}")
            self.logger.warning(f"Block number: {block['block_number']}")
            self.logger.warning(f"Winner: {block['block_creator']} of {block['block_ip']}")
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
        elif self.memserver.force_sync_ip:
            self.memserver.emergency_mode = True
            self.logger.warning("Forced sync switched to emergency mode")
        else:
            self.memserver.emergency_mode = False

        if self.consensus.block_hash_pool_percentage > 80 and self.memserver.since_last_block < self.memserver.block_time:
            self.memserver.force_sync_ip = None

    async def penalty_list_update_handler(self, event):
        self.memserver.penalties = event

    def run(self) -> None:
        self.init_hashes()
        update_local_address(logger=self.logger)
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

                # if self.memserver.since_last_block < self.memserver.block_time or self.memserver.force_sync_ip:
                time.sleep(self.run_interval)

            except Exception as e:
                self.logger.error(f"Error in core loop: {e} {traceback.print_exc()}")
                time.sleep(1)
                # raise #test

        self.event_bus.remove_listener('penalty-list-update', self.penalty_list_update_handler)

        self.logger.info("Termination code reached, bye")
        sys.exit(0)
