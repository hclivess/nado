import asyncio
import sys
import threading
import time
import traceback

from config import get_timestamp_seconds
from loops.consensus_loop import change_trust
from ops.account_ops import increase_produced_count, change_balance, get_totals, index_totals, get_bonded_registry, get_open_registry, set_finalized_height, get_finalized_height, get_account
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
    sign_block,
    verify_block_signature,
    get_block_hash_by_number,
    prune_block_bodies,
)
from ops.data_ops import get_home
from ops.mining_ops import select_producer, select_producer_two_lane, epoch_of, total_bonded_shares
from ops import kv_ops
from protocol import split_block_reward, TREASURY_ADDRESS, CHAIN_ID, REWARD_CAP, MIN_TX_FEE, BOND_CAP, AUTO_BOND_MIN_RAW
from ops.data_ops import set_and_sort, shuffle_dict, sort_list_dict, get_byte_size, sort_occurrence, dict_to_val_list
from ops.peer_ops import update_local_address, ip_stored, check_ip, qualifies_to_sync, announce_me, get_remote_status
from ops import snapshot_ops
from ops.pool_ops import merge_buffer, cull_buffer
from ops.transaction_ops import remove_outdated_transactions
from ops.transaction_ops import (
    to_readable_amount,
    validate_transaction,
    validate_all_spending, index_transactions, assert_unique_reserved, assert_block_blob_cap
)
import secrets as _secrets
from rollback import rollback_one_block, MissingParentError, FinalityViolation
from ops.reward_ops import credit_block_reward, apply_treasury_burn
from ops.transaction_ops import (construct_attestation_tx, construct_commit_tx, construct_reveal_tx,
                                 construct_bond_tx, construct_blob_tx, construct_register_tx)
from ops.attestation_ops import ffg_finalized_checkpoint
from ops.mining_ops import beacon_commitment
from protocol import EPOCH_LENGTH, FINALITY_DEPTH

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
        self.consecutive = 0
        self.snapshot_attempted = False
        # AUDIT FIX (honest-signer guard): the highest block height we've attached our detached winner
        # signature to. We only ever sign a STRICTLY-higher height, so after a reorg + re-produce we
        # never sign a second, different block at a height we already signed (which a connected
        # adversary could otherwise harvest into a self-equivocation slashing proof against us).
        self.last_signed_height = -1
        # AUTO-BOND (non-consensus, opt-in via memserver.auto_bond_percent): bond a % of newly-mined
        # spendable earnings each epoch. baseline = last balance we've accounted for; throttled to one
        # auto-bond per epoch (bond isn't per-block unique-keyed, so we self-limit).
        self.last_auto_bond_epoch = -1
        self.auto_bond_baseline = None
        # AUTO-COLLECT (default on) + AUTO-REGISTER (opt-in): sweep the presence dividend, and keep the open-lane
        # PoSW lease alive, hands-free. Throttled to one of each per epoch (see maybe_auto_collect/register).
        self.last_auto_collect_epoch = -1
        self.last_auto_register_epoch = -1

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

            # FFG (#6): refresh the stake-attested finalized checkpoint + (if bonded) attest this epoch.
            self.update_ffg_and_attest()
            # RANDAO (#7): (if bonded) commit a secret for epoch+2 and reveal epoch+1's in its window.
            self.maybe_randao()
            # AUTO-BOND (opt-in): unattended-compound a % of newly-mined earnings into bonded stake.
            self.maybe_auto_bond()
            self.maybe_auto_collect()
            self.maybe_auto_register()
            # ROLLING MODE (opt-in): on a pruned node, drop block bodies older than the retention window.
            self.maybe_prune_history()

            if 3 in self.memserver.periods:
                block_producers = self.memserver.block_producers.copy()
                peers = self.memserver.peers.copy()
                """make copies to avoid errors in case content changes"""

                # min_peers == 0 enables SOLO production (a single node mints without a peer mesh) —
                # used for a stable single-node relay/demo where multi-node fork-choice churn is
                # undesirable. With min_peers >= 1 the normal peer+producer-set gate applies.
                if (len(peers) >= self.memserver.min_peers
                        and (block_producers or self.memserver.min_peers == 0)
                        and not self.memserver.force_sync_ip):
                    block_candidate = get_block_candidate(block_producers=block_producers,
                                                          block_producers_hash=self.memserver.block_producers_hash,
                                                          logger=self.logger,
                                                          transaction_pool=self.memserver.transaction_pool.copy(),
                                                          latest_block=self.memserver.latest_block,
                                                          block_time=self.memserver.block_time
                                                          )

                    # S4.3: get_block_candidate returns None when no bonded identity is eligible
                    # (empty registry / total_shares == 0). Skip this round rather than crash.
                    if block_candidate is not None:
                        # #15 step 5: if WE are the selected winner (we hold block_creator's key),
                        # attach the detached authorship signature. A relay building this block for an
                        # OFFLINE winner cannot (no key) and leaves it unsigned — still valid (win-offline).
                        if (self.memserver.address == block_candidate["block_creator"]
                                and block_candidate["block_number"] > self.last_signed_height):
                            sign_block(block_candidate, self.memserver.private_key, self.memserver.public_key)
                            self.last_signed_height = block_candidate["block_number"]
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
            # #16 step 3: order candidate tips by OBJECTIVE cumulative_weight (heaviest first), NOT by
            # peer-count occurrence — so we sync toward the heaviest valid chain, not the most-advertised
            # one (which a Sybil peer-set could dominate). tip_weights includes our own tip.
            distinct_hashes = [h for h in set(source_pool_copy.values()) if h is not None]
            sorted_hashes = sorted(
                distinct_hashes,
                key=lambda h: (-self.consensus.tip_weights.get(h, -1), h)
            )[:self.memserver.cascade_limit]
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
                                                                  memserver_protocol=self.memserver.protocol,
                                                                  known_tree=known_tree,
                                                                  unreachable_list=self.memserver.unreachable.keys(),
                                                                  peer_hash=value,
                                                                  required_hash=hash_candidate)
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
        """OBJECTIVE fork-choice (#16/#17 step 3): we are out of sync ONLY when some peer advertises a
        tip whose cumulative_weight is STRICTLY GREATER than ours and we don't already hold that block.
        Equal or lower weight -> keep our tip (first-seen on ties). Peer IPs / trust carry NO weight, so
        a Sybil peer-set cannot trigger a reorg; and even a heavier advertisement is only acted on by
        fetching the blocks, which verify_block re-derives + enforces (a lie is rejected) and the
        finality floor refuses to reorg below. Replaces the Sybil-swingable plurality majority_block_hash."""
        hh = self.consensus.heaviest_block_hash
        if hh is None:
            """not ready (no tip weights collected yet)"""
            return False
        # AUDIT FIX (same-length fork wedge): heaviest_block_hash is the GLOBAL best tip by
        # (cumulative_weight DESC, block_hash ASC) over all advertised tips INCLUDING our own. The old
        # code switched only on strictly-GREATER weight, so two honest tips at the same height (equal
        # content-independent weight, different hash) wedged forever. Switch whenever the canonical tip
        # is not ours — i.e. it is heavier, OR equal-weight with a lower hash (the deterministic
        # tie-break every node computes identically, so they all converge on the lowest-hash tip).
        if hh == self.memserver.latest_block["block_hash"]:
            """our tip IS the canonical (heaviest weight, lowest-hash tie-break) -> do not switch"""
            return False
        if get_block(hh):
            """we already hold the canonical tip locally; normal incorporation adopts it"""
            return False
        """a strictly-better tip (heavier, or equal-weight + lower hash) exists -> sync toward it"""
        return True

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
                        if self.memserver.rollbacks < self.memserver.max_rollbacks:
                            try:
                                self.memserver.latest_block = rollback_one_block(logger=self.logger,
                                                                                 block=self.memserver.latest_block)
                            except MissingParentError as e:
                                # we have run out of local history to roll back through (e.g.
                                # a snapshot-bootstrapped node). Abort the cascade and let the
                                # next emergency cycle resync (snapshot/full) instead of spinning.
                                self.logger.error(f"Rollback aborted, resync required: {e}")
                                self.memserver.rollbacks = 0
                                self._reject_heaviest_tip()
                                break
                            except FinalityViolation as e:
                                # the reorg would cross the finalized-height floor (a deep / long-range
                                # rollback). REFUSE it — the finalized prefix is immutable — and resync
                                # forward only. This is the hard 51%/rollback cap (#17).
                                self.logger.error(f"Rollback refused (finality): {e}")
                                self.memserver.rollbacks = 0
                                self._reject_heaviest_tip()
                                break

                            # ALWAYS count the rollback (even under force_sync_ip): the finalized floor
                            # is the hard safety cap; this counter only rate-limits a single burst, so a
                            # forced sync can no longer roll back unboundedly (closes the force_sync leak).
                            self.memserver.rollbacks += 1
                            self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                     peer=peer,
                                                                     value=-1)
                        else:
                            self.logger.error(
                                f"Rollbacks exhausted ({self.memserver.rollbacks}/{self.memserver.max_rollbacks})")
                            self.memserver.rollbacks = 0
                            self._reject_heaviest_tip()
                            break

                    self.logger.info(f"Maximum reached cascade depth: {self.memserver.cascade_depth}")

        except Exception as e:
            self.logger.info(f"Error: {e}")
            raise

    def _reject_heaviest_tip(self):
        """AUDIT FIX (weight-DoS): exclude the advertised-heaviest tip we just FAILED to obtain a valid
        heavier chain for, so a peer advertising a bogus huge cumulative_weight cannot keep looping us
        into emergency-mode/rollback. The exclusion is bounded + auto-cleared (consensus_loop), so a
        transiently-unreachable REAL heavier tip is retried later."""
        hh = self.consensus.heaviest_block_hash
        if hh and hh != self.memserver.latest_block["block_hash"]:
            self.consensus.rejected_tips.add(hh)
            self.logger.warning(f"Excluding unreachable heavier-advertised tip {hh[:12]} (weight-DoS guard)")

    def rebuild_block(self, block):
        # Reconstruct the block deterministically from the LOCAL tip + the block's tx set: the winner
        # (creator/block_ip) and reward/cumulative_fees are RECOMPUTED from local parent state, so a
        # peer cannot misattribute the producer or inject an inflated reward — only a block matching
        # the canonical reconstruction is incorporated. (Producer-signature AUTHENTICATION is
        # deferred to the coordinated security milestone: winner-only signing both fights the
        # peer-majority fork-choice AND would break 'win while asleep', so it needs stake-weighted
        # fork-choice + finality + an offline-win/relay-delegation decision. See #15/#16/#17.)
        parent = self.memserver.latest_block
        block_number = parent["block_number"] + 1
        _epoch = epoch_of(block_number)
        bonded_registry = get_bonded_registry()  # as-of-parent (tip == parent here)
        winner = select_producer_two_lane(get_open_registry(_epoch), bonded_registry,
                                          epoch_beacon(_epoch), slot=block_number)
        return construct_block(
            # Wall-clock, monotonic (>= parent) — see ops/block_ops.py; fixes frozen genesis-anchored times.
            block_timestamp=max(get_timestamp_seconds(), parent["block_timestamp"]),
            block_number=block_number,
            parent_hash=parent["block_hash"],
            block_ip=winner,
            creator=winner,
            transaction_pool=block["block_transactions"],
            block_producers_hash=block["block_producers_hash"],
            block_reward=get_block_reward(parent_block=parent, logger=self.logger),
            parent_cumulative_fees=parent.get("cumulative_fees", 0),
            parent_cumulative_weight=parent.get("cumulative_weight", 0),
            block_weight=total_bonded_shares(bonded_registry))

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
        with kv_ops.write_txn():
            index_transactions(block=block,
                               sorted_transactions=sorted_transactions,
                               logger=self.logger)

            # LANE-AWARE reward (doc/presence-dividend.md): bonded block = 90/10 winner-take-all; open block =
            # producer tip + DIVIDEND_POOL (redistributed off-L1) + treasury. Single source (ops.reward_ops)
            # shared with rollback_one_block + reindex, so the three paths subtract identical integers.
            credit_block_reward(block, logger=self.logger)
            # Anti-hoard self-burn (doc/treasury.md §3.2): at period boundaries, destroy a slice of the idle
            # treasury. Runs in this same write txn, so it's atomic with the reward + reverts with the block.
            apply_treasury_burn(block, logger=self.logger)

            totals = get_totals(block=block)  # produced = full reward = total emission
            index_totals(produced=totals["produced"],
                         fees=totals["fees"],
                         block_height=block["block_number"])

            index_block_number(block)  # the applied marker, atomic with the state above

        # Advance the tip pointer file only AFTER the atomic state commit. A crash before this
        # just leaves a stale tip that re-syncs forward; block_already_indexed prevents re-apply.
        set_latest_block_info(latest_block=block, logger=self.logger)

        # ENFORCED FINALITY (#17 step 1): advance the persisted monotonic finalized-height floor. A
        # block at height H finalizes everything at/below H - finality_depth; rollback_one_block then
        # REFUSES to cross it. Monotonic (max), recomputable, and crash-conservative: a crash between
        # the block commit above and this write leaves the floor one behind (never ahead) and it
        # re-advances on the next block — it can never finalize something that wasn't committed.
        new_final = max(self.memserver.finalized_height,
                        block["block_number"] - self.memserver.finality_depth)
        if new_final > self.memserver.finalized_height:
            set_finalized_height(new_final)
            self.memserver.finalized_height = new_final

    def update_ffg_and_attest(self):
        """FFG (#6): refresh the stake-attested finalized checkpoint (observability) and, if we are a
        bonded validator who hasn't attested the current epoch, broadcast our attestation. Best-effort:
        it NEVER raises into the core loop and never blocks production; FFG is an additive accountability
        signal, not the liveness-critical finality (that stays the time-based floor)."""
        try:
            latest = self.memserver.latest_block
            epoch = epoch_of(latest["block_number"])
            self.memserver.ffg_finalized = ffg_finalized_checkpoint(epoch)
            if epoch < 1:
                return  # epoch 0's checkpoint is genesis; nothing to attest yet
            if self.memserver.address not in get_bonded_registry():
                return  # only bonded validators attest
            if kv_ops.attestation_exists(epoch, self.memserver.address):
                return  # already attested this epoch (one per validator per epoch)
            checkpoint_hash = get_block_hash_by_number(epoch * EPOCH_LENGTH)
            if not checkpoint_hash:
                return
            target_block = min(latest["block_number"] + 5, (epoch + 1) * EPOCH_LENGTH - 1)
            if target_block <= latest["block_number"]:
                return  # at the epoch's final block -> attest next epoch instead
            tx = construct_attestation_tx(self.memserver.keydict, epoch, checkpoint_hash, target_block)
            result = self.memserver.merge_transaction(tx, user_origin=True)
            if result and result.get("result"):
                self.logger.info(f"FFG: attested epoch {epoch} ckpt {checkpoint_hash[:12]} "
                                 f"(ffg_finalized={self.memserver.ffg_finalized})")
        except Exception as e:
            self.logger.error(f"FFG update/attest failed: {e}")

    def maybe_randao(self):
        """RANDAO (#7): a bonded validator COMMITS a fresh secret for epoch current+2 (we are in its
        E-2) and REVEALS the secret it committed for epoch current+1 (we are in its E-1 finalized
        window). Best-effort; never raises into the core loop. Secrets live in memserver.randao_secrets
        (in-memory: an unrevealed secret after a restart is just a wasted commit, harmless)."""
        try:
            if self.memserver.address not in get_bonded_registry():
                return  # only bonded validators participate in the beacon
            latest = self.memserver.latest_block
            current_epoch = epoch_of(latest["block_number"])
            kd = self.memserver.keydict

            # COMMIT for epoch current+2 (we are in its E-2), once
            e_commit = current_epoch + 2
            if (e_commit not in self.memserver.randao_secrets
                    and kv_ops.commit_get(self.memserver.address, e_commit) is None):
                target_block = min(latest["block_number"] + 5, (current_epoch + 1) * EPOCH_LENGTH - 1)
                if target_block > latest["block_number"]:
                    secret = _secrets.token_hex(32)
                    self.memserver.randao_secrets[e_commit] = secret
                    tx = construct_commit_tx(kd, e_commit, beacon_commitment(secret), target_block)
                    self.memserver.merge_transaction(tx, user_origin=True)

            # REVEAL for epoch current+1 (we are in its E-1 finalized window), if we hold its secret
            e_reveal = current_epoch + 1
            secret = self.memserver.randao_secrets.get(e_reveal)
            if secret and kv_ops.commit_get(self.memserver.address, e_reveal) is not None:
                lo = current_epoch * EPOCH_LENGTH
                hi = e_reveal * EPOCH_LENGTH - FINALITY_DEPTH - 1
                target_block = latest["block_number"] + 5
                if lo <= target_block <= hi and secret not in kv_ops.reveals_for_epoch(e_reveal):
                    tx = construct_reveal_tx(kd, e_reveal, secret, target_block)
                    self.memserver.merge_transaction(tx, user_origin=True)
        except Exception as e:
            self.logger.error(f"RANDAO commit/reveal failed: {e}")

    def maybe_prune_history(self):
        """ROLLING MODE (non-consensus, opt-in): on a pruned node (memserver.archive == False), delete
        block BODIES finalized below the retention window. STATE + the number<->hash indexes are kept,
        so the node keeps validating and serving the beacon/FFG lookbacks. Archive nodes (default) skip
        this entirely. Best-effort + incremental (a meta watermark bounds per-call work); never raises
        into the core loop. See doc/rolling-mode-and-da.md and block_ops.prune_block_bodies."""
        if getattr(self.memserver, "archive", True):
            return
        try:
            finalized = get_finalized_height()
            retention = getattr(self.memserver, "history_retention_blocks", 0)
            prune_block_bodies(finalized, retention, self.logger)
        except Exception as e:
            self.logger.error(f"Rolling-mode prune failed: {e}")

    def maybe_auto_bond(self):
        """AUTO-BOND (non-consensus, opt-in): if the operator set memserver.auto_bond_percent > 0, route
        that percentage of this node's NEWLY-MINED spendable earnings straight into bonded stake — fully
        unattended auto-compounding of the bonded lane. Best-effort; never raises into the core loop.

        Earnings = the increase in our own spendable balance since the last accounted-for baseline. We
        throttle to at most one auto-bond per epoch (a bond isn't per-block unique-keyed, so we self-
        limit to avoid spamming the mempool), accumulate below the AUTO_BOND_MIN_RAW dust floor instead
        of emitting fee-dominated dust txs, and STOP once bonded >= BOND_CAP (extra bond buys no weight,
        so locking more would just freeze coins for nothing)."""
        pct = getattr(self.memserver, "auto_bond_percent", 0)
        if not pct or pct <= 0:
            return
        try:
            epoch = epoch_of(self.memserver.latest_block["block_number"])
            if self.last_auto_bond_epoch == epoch:
                return                                  # already auto-bonded this epoch
            acc = get_account(self.memserver.address)
            balance = int(acc.get("balance", 0)) if acc else 0
            bonded = int(acc.get("bonded", 0)) if acc else 0
            if self.auto_bond_baseline is None:
                self.auto_bond_baseline = balance       # first observation: only FUTURE earnings bond
                return
            if bonded >= BOND_CAP:
                self.auto_bond_baseline = balance       # already at the weight cap — nothing to gain
                return
            gain = balance - self.auto_bond_baseline
            if gain <= 0:
                self.auto_bond_baseline = balance       # balance fell (a prior bond/send landed) — rebaseline
                return
            to_bond = (gain * int(pct)) // 100
            # never bond past the cap (no extra weight), and never bond what we can't pay the fee for
            to_bond = min(to_bond, BOND_CAP - bonded)
            if to_bond < AUTO_BOND_MIN_RAW or balance < to_bond + MIN_TX_FEE:
                return                                  # accrue (don't rebaseline) until it's worth a tx
            target_block = self.memserver.latest_block["block_number"] + 2
            tx = construct_bond_tx(self.memserver.keydict, to_bond, MIN_TX_FEE, target_block)
            self.memserver.merge_transaction(tx, user_origin=True)
            self.last_auto_bond_epoch = epoch
            # account for the gain now; the bond+fee will reduce balance in a later block (negative
            # delta, harmlessly rebaselined). Optimistic baseline = expected post-bond spendable.
            self.auto_bond_baseline = balance - to_bond - MIN_TX_FEE
            self.logger.info(
                f"Auto-bond: bonding {to_bond} raw ({pct}% of {gain} new earnings) into the bonded lane "
                f"(target_block {target_block})")
        except Exception as e:
            self.logger.warning(f"Auto-bond skipped: {e}")

    def maybe_auto_collect(self):
        """AUTO-COLLECT (default on, memserver.auto_collect_dividend): once per epoch, sweep this node's accrued
        presence dividend into a provable collection (a `collect_dividend` blob the exec node settles). Only
        OPEN-lane members accrue a dividend, so we skip unless we're registered — a bonded-only node has nothing
        to collect and would just burn the dust fee. Best-effort; never raises into the core loop."""
        if not getattr(self.memserver, "auto_collect_dividend", True):
            return
        try:
            epoch = epoch_of(self.memserver.latest_block["block_number"])
            if self.last_auto_collect_epoch == epoch:
                return
            acc = get_account(self.memserver.address)
            if not acc or int(acc.get("registered", 0)) != 1:
                return                                  # not an open-lane member -> nothing accrues
            target_block = self.memserver.latest_block["block_number"] + 2
            tx = construct_blob_tx(self.memserver.keydict, {"op": "collect_dividend"}, target_block, MIN_TX_FEE)
            self.memserver.merge_transaction(tx, user_origin=True)
            self.last_auto_collect_epoch = epoch
            self.logger.info(f"Auto-collect: swept presence dividend (target_block {target_block})")
        except Exception as e:
            self.logger.info(f"Auto-collect skipped: {e}")

    def maybe_auto_register(self):
        """AUTO-REGISTER (opt-in, default off, memserver.auto_register): keep this node present in the OPEN lane
        hands-free — register when absent, and renew the PoSW lease inside its tail. OFF by default so a headless
        node doesn't silently join (and Sybil-load) the open lane; ON = 'mine the free lane from this box too'.
        Computes the ~2 s sequential PoSW inline, throttled to at most once per epoch. Best-effort."""
        if not getattr(self.memserver, "auto_register", False):
            return
        try:
            from protocol import POSW_S, POSW_K, POSW_ANCHOR_OFFSET, POSW_LEASE_EPOCHS
            epoch = epoch_of(self.memserver.latest_block["block_number"])
            if self.last_auto_register_epoch == epoch:
                return
            acc = get_account(self.memserver.address)
            if acc and int(acc.get("registered", 0)) == 1:
                reg_ep = int(acc.get("reg_epoch", -1))
                if reg_ep >= 0 and epoch < reg_ep + POSW_LEASE_EPOCHS - 10:   # still well inside the lease
                    self.last_auto_register_epoch = epoch
                    return
            from ops import posw
            from ops.block_ops import get_block_hash_by_number
            from ops.reg_difficulty import required_posw_t
            target_block = self.memserver.latest_block["block_number"] + 4
            anchor = get_block_hash_by_number(max(0, target_block - POSW_ANCHOR_OFFSET))
            if not anchor:
                return
            req_t = required_posw_t(epoch_of(max(0, target_block - POSW_ANCHOR_OFFSET)))
            proof = posw.prove(posw.challenge_bytes(self.memserver.address, anchor), T=req_t, S=POSW_S, k=POSW_K)
            tx = construct_register_tx(self.memserver.keydict, target_block, proof)
            self.memserver.merge_transaction(tx, user_origin=True)
            self.last_auto_register_epoch = epoch
            self.logger.info(f"Auto-register: (re)joined the open lane (target_block {target_block}, PoSW T={req_t})")
        except Exception as e:
            self.logger.info(f"Auto-register skipped: {e}")

    def validate_transactions_in_block(self, block, logger, remote_peer, remote):
        transactions = sort_list_dict(block["block_transactions"])

        # target-block matching enforced from block 1
        if not check_target_match(transactions, block["block_number"], logger=logger):
            self.logger.error("Transactions mismatch target block")
            raise ValueError("Transactions mismatch target block")

        # DATA-AVAILABILITY cap (doc/execution-layer.md §3.3): reject a block carrying more blob bytes
        # than phones can be expected to download/relay. Fail-closed like the other block-set checks.
        try:
            assert_block_blob_cap(transactions)
        except Exception as e:
            self.logger.error(f"Block exceeds per-block blob cap: {e}")
            if remote:
                self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                         peer=remote_peer, value=-1)
            raise

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
                    # block_height = the block being validated (N) so a register tx's epoch check
                    # epoch_of(N) matches how apply_register records it (index_transactions applies
                    # with block["block_number"]); account STATE for spending/producer checks is
                    # still parent state (this block is not yet incorporated).
                    validate_transaction(transaction=transaction,
                                         logger=logger,
                                         block_height=block["block_number"])
                except Exception as e:
                    self.logger.error(f"Failed to validate transaction during block preparation: {e}")
                    if remote:
                        # a peer's block with an invalid tx is rejected wholesale (penalise the peer).
                        self.consensus.trust_pool = change_trust(trust_pool=self.consensus.trust_pool,
                                                                 peer=remote_peer,
                                                                 value=-1)
                        raise
                    # OWN block assembly: DROP the invalid tx and keep building. One bad mempool tx (e.g. a
                    # lingering duplicate `attest`/`reveal`, or a tx that turned invalid since it entered the
                    # pool) must NEVER abort our whole block — that stalls production until the tx clears
                    # (observed ~70-135s freezes). Removed from the pools above; drop it from the block set
                    # too. Safe in the account model: removing a tx only REDUCES spending, never invalidates
                    # the remaining txs.
                    if transaction in block["block_transactions"]:
                        block["block_transactions"].remove(transaction)

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
        epoch = epoch_of(block_number)
        winner = select_producer_two_lane(get_open_registry(epoch),
                                          get_bonded_registry(),
                                          epoch_beacon(epoch),
                                          slot=block_number)
        if winner is None:
            raise ValueError("No eligible producer for this block (fail-closed)")
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

            # FORK-CHOICE WEIGHT (#16/#17 step 2): recompute cumulative_weight from the LOCAL parent +
            # the as-of-parent bonded registry and enforce equality (like block_reward). A relay cannot
            # forge a heavier chain: a block whose committed cumulative_weight != the deterministic
            # value is rejected. (get_bonded_registry() here is parent state — the block is not yet
            # incorporated — the same as-of-parent assumption validate_block_producer documents; once
            # in-block bond txs land, the rollback/snapshot re-verify path must reset the tip to the
            # block's parent before this runs.)
            parent_weight = self.memserver.latest_block.get("cumulative_weight", 0)
            expected_weight = parent_weight + total_bonded_shares(get_bonded_registry())
            if block.get("cumulative_weight") != expected_weight:
                raise ValueError(
                    f"Block cumulative_weight {block.get('cumulative_weight')} != deterministic "
                    f"{expected_weight} (parent {parent_weight} + as-of-parent bonded shares)")

            # AUDIT FIX: reject a block containing duplicate reserved txs (in-block uniqueness) —
            # closes the K-withdraw bond drain / slash-escape / chain-halt, duplicate-slash over-burn,
            # and heartbeat/reveal DUPSORT desync forks.
            assert_unique_reserved(block["block_transactions"])

            # ALWAYS validate signatures + spending (never skipped for synced/old blocks) — else a
            # malicious sync peer could feed forged, unsigned transfers that reflect would still apply.
            # Fast bootstrap = snapshot sync instead.
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

            # #15 step 5: verify a present detached winner signature on the ORIGINAL block BEFORE the
            # deterministic rebuild drops it. Absent -> accepted (win-offline). Present-but-invalid
            # (wrong signer or bad sig) -> rejected as a forgery. The sig is off the consensus path
            # (not in the hash/weight), so this never affects which block is canonical — it only
            # refuses a tampered authorship claim and underpins equivocation slashing.
            if not verify_block_signature(block):
                raise ValueError("Invalid detached winner block signature")

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

    def run(self) -> None:
        self.init_hashes()
        update_local_address(logger=self.logger)

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

        self.logger.info("Termination code reached, bye")
        sys.exit(0)
