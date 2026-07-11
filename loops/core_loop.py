import asyncio
import sys
import threading
import time
import traceback

from config import get_timestamp_seconds
from ops.account_ops import get_totals, index_totals, get_bonded_registry, get_open_registry, set_finalized_height, get_finalized_height, get_account
from ops.block_ops import (
    knows_block,
    get_blocks_after,
    SYNC_BATCH_MAX,
    get_from_single_target,
    get_block_candidate,
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
    block_content_hash,
    index_block_number,
    sign_block,
    verify_block_signature,
    get_block_hash_by_number,
    prune_block_bodies,
    randao_eligible_bonded,
)
from ops.mining_ops import select_producer_two_lane, epoch_of, total_bonded_shares, block_fork_weight
from ops import kv_ops
from protocol import CHAIN_ID, BASE_SUBSIDY, MIN_TX_FEE, BOND_CAP, AUTO_BOND_MIN_RAW
from ops.data_ops import shuffle_dict, sort_list_dict, get_byte_size
from ops.peer_ops import check_ip, qualifies_to_sync, get_remote_status
from ops import snapshot_ops
from ops.pool_ops import cull_buffer
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
from protocol import EPOCH_LENGTH, FINALITY_DEPTH, REWARD_WINDOW

# How often (seconds) emergency mode logs "Could not find a syncable peer". The loop still retries every
# ~1s, but a lone/bootstrap node with no reachable donor would otherwise flood the log once/sec.
NO_SYNCABLE_LOG_INTERVAL = 30

# Minimum seconds between seed-anchored RE-ANCHOR attempts. A wedged node (stuck on a minority fork below
# its snapshot/finality floor) re-imports a seed's snapshot to recover; bound the retry so a persistently
# failing import can't hammer the seed every pass.
REANCHOR_COOLDOWN = 30
WEDGE_OVERRIDE_SECS = 45   # after a heavier tip fails verification, mint our own chain this long before re-chasing


def peer_claims_heavier_tip(statuses, our_weight, have_peers, rejected_tips):
    """The caught-up production gate's predicate, extracted for direct testing (Sybil-stall guard).
    True (= do NOT mint, we may be behind) when we have peers but no statuses yet, or when any peer
    advertises a strictly heavier tip that is NOT in rejected_tips. A rejected tip is one we already
    tried and failed to sync a valid heavier chain for — counting it would let a Sybil's bogus
    weight advertisement suppress production indefinitely."""
    if have_peers and not statuses:
        return True
    return any(s.get("latest_block_weight", 0) > our_weight
               and s.get("latest_block_hash") not in rejected_tips
               for s in statuses)


def minority_consensus(majority_hash, sample_hash):
    """True when a pool majority exists and OUR sample hash differs from it — i.e. we are in the
    minority for that pool and should converge toward the majority. No majority yet (quorum not
    formed, e.g. a lone/bootstrap node) counts as NOT minority, so a solo node never replaces its
    own pool. Used for the tx-pool reconcile only — chain fork-choice is weight-based, not this."""
    if not majority_hash:
        return False
    elif sample_hash != majority_hash:
        return True
    else:
        return False


def old_block(block):
    """True when the block's committed timestamp is more than a day in the past. Reporting only
    (flags a sync-replayed historical block in produce_block's log) — NOT a validity rule; the
    consensus timestamp check is valid_block_timestamp."""
    if block["block_timestamp"] < get_timestamp_seconds() - 86400:
        return True
    else:
        return False


class CoreClient(threading.Thread):
    """thread which takes control of basic mode switching, block creation and transaction pools operations"""

    def __init__(self, memserver, consensus, logger):
        """Wire the loop to the shared memserver/consensus state and zero the per-node guards and
        throttles the inline comments document (last-signed height, auto-* per-epoch baselines,
        log backoffs, reconcile timer)."""
        threading.Thread.__init__(self)
        self.duration = 0
        self.logger = logger
        self.logger.info(f"Starting Core")
        self.memserver = memserver
        self.consensus = consensus
        self.run_interval = 1
        self.consecutive = 0
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
        # anti-spam backoff for the emergency-mode "Could not find a syncable peer" retry (fires every ~1s
        # while no donor is reachable — a persistent normal state on a lone/bootstrap node).
        self._last_no_syncable_log = 0
        # cooldown for the seed-anchored RE-ANCHOR (wedge recovery): re-importing a seed's snapshot is
        # expensive, so a wedged node attempts it at most once per this interval rather than every ~1s pass.
        self._last_reanchor_ts = 0
        # WEDGE-OVERRIDE (2026-07-11): when fast-forward onto a strictly-heavier tip repeatedly FAILS
        # VERIFICATION (its chain extends our own tip with an invalid block — e.g. one that replays an
        # already-mined tx), the node used to re-enter emergency forever and NEVER mint, freezing on one
        # height. We never adopt the invalid block (safety holds), but we must keep making progress on OUR
        # valid chain. After such a failure we set this timestamp: until it passes, minority_block_consensus
        # ignores the heavier-but-unverifiable tip so normal_mode mints. Advancing our own tip changes the
        # sync topology (the peer no longer extends our tip) and routes to the reorg/re-anchor path.
        self._wedge_override_until = 0
        # throttle the once-per-block-interval consensus mempool reconcile (normal_mode).
        self._last_reconcile = 0
        # once-per-new-block throttle for the periodic duties in normal_mode (FFG/RANDAO/auto-*).
        self._last_duty_height = -1
        # DONOR CACHE for get_peer_to_sync_from: (peer, required_hash) of the last selected sync donor.
        # While the donor still advertises the current heaviest hash, it is re-verified with one
        # knows_block dial instead of a full pool re-scan every ~1s emergency pass.
        self._sync_donor = (None, None)

    def _mode(self):
        """Local production pacing (block_time is NOT consensus — verify only checks timestamp <= now, and
        there is no min-inter-block rule). Replaces the old [0,1,2,3] "period" state machine, whose
        hard-coded 10/20/40s gates assumed ~60s blocks and, at a low block_time, both mispaced production
        AND time-sliced the mempool merges (a tx arriving late in the interval could age out — tx loss).
        Now: mempool draining is CONTINUOUS (see normal_mode), and this only decides WHEN to mint:
            init     -> first block_time of uptime, don't mint yet
            produce  -> block_time elapsed since the last block -> mint
            building -> waiting out the current interval"""
        bt = self.memserver.block_time
        self.memserver.since_last_block = get_timestamp_seconds() - self.memserver.latest_block["block_timestamp"]
        if self.memserver.reported_uptime < bt:
            return "init"
        return "produce" if self.memserver.since_last_block >= bt else "building"

    def normal_mode(self):
        """The caught-up per-second pass. Keeps the single mempool within its byte budget (submitted
        txs already enter transaction_pool directly in merge_transaction — no staged buffer cascade),
        reconciles the pool with the peer majority at most once per block interval, and
        runs the best-effort periodic duties (FFG attest, RANDAO, auto-bond/collect/register,
        rolling-mode prune). Minting happens ONLY in the 'produce' pacing slot (block_time pacing
        is NOT consensus) and only past three gates: enough peers (min_peers == 0 permits solo
        production), no operator-forced sync, and the CAUGHT-UP gate (peer_claims_heavier_tip) —
        never mint while any peer advertises an unrejected heavier tip, or we build a divergent
        chain whose finalized tip can no longer be rolled back to reconcile."""
        try:
            self.memserver.reported_uptime = self.memserver.get_uptime()
            mode = self._mode()
            self.memserver.mode = mode

            # SINGLE MEMPOOL (2026-07): submitted txs enter transaction_pool DIRECTLY in merge_transaction,
            # so the old per-second user_tx_buffer -> tx_buffer -> transaction_pool cascade is gone. Each
            # pass: (1) EVICT any tx already MINED (its txid is in the on-chain tx-index) — at-most-once means
            # it can never be re-included, so keeping it only bloats the pool and empties block candidates
            # (the zombie cleanup for a tx that mined but reverted at the exec layer, or that a lagging peer
            # re-gossiped); (2) keep the pool within its byte budget for the peer-transferable fetch.
            with self.memserver.mempool_lock:
                if self.memserver.transaction_pool:
                    self.memserver.transaction_pool = [
                        t for t in self.memserver.transaction_pool
                        if kv_ops.tx_get(t.get("txid")) is None]
                    self.memserver.transaction_pool = cull_buffer(
                        buffer=self.memserver.transaction_pool,
                        limit=self.memserver.transaction_pool_max_bytes)

            # CONSENSUS MEMPOOL RECONCILE — at most once per block interval: if our pool hash is in the
            # minority vs peers, replace it (last-effort convergence). Time-gated (replaces the old
            # period-2 + replaced_this_round flag dance).
            now = get_timestamp_seconds()
            if now - self._last_reconcile >= self.memserver.block_time:
                self._last_reconcile = now
                if minority_consensus(majority_hash=self.consensus.majority_transaction_pool_hash,
                                      sample_hash=self.memserver.transaction_pool_hash):
                    self.replace_transaction_pool()
                    self.memserver.transaction_pool_hash = self.memserver.get_transaction_pool_hash()

            # PERIODIC DUTIES, throttled to once per NEW BLOCK (audit): they depend only on chain
            # state (epoch windows, registries, balances), which changes exactly when the tip
            # advances — yet they ran every ~1s pass, costing 3+ full account-table scans per second
            # (ffg_finalized + two bonded-registry membership probes) on every node, forever.
            _tip_h = self.memserver.latest_block["block_number"]
            if _tip_h != self._last_duty_height:
                self._last_duty_height = _tip_h
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

            if mode == "produce":
                peers = self.memserver.peers.copy()
                """make copies to avoid errors in case content changes"""

                # CAUGHT-UP GATE (fork-while-syncing fix): never MINT while ANY peer advertises a HEAVIER tip
                # than ours — we are behind and must SYNC (fetch the canonical blocks), not build our own.
                # Minting here (win-offline relay production for the slot's winner) forks: our locally-built
                # block takes a wall-clock timestamp that differs from the canonical block's, so its hash
                # diverges; once our divergent tip finalizes we can no longer roll back to reconcile ("Rollback
                # refused (finality)"), wedging the node oscillating between two tips. This is checked FRESH
                # from status_pool (each peer's advertised latest_block_weight) rather than the lagging
                # emergency_mode/heaviest_block_hash, which are None until the weight pool fills — the window
                # that let a behind node mint 100+ divergent blocks.
                _our_w = self.memserver.latest_block.get("cumulative_weight", 0)
                # .copy(): the peer loop admits/pops status_pool entries concurrently — iterating the
                # live dict raises "dictionary changed size during iteration" and costs the whole
                # production pass (every OTHER status_pool iteration in the codebase already copies).
                _statuses = [v for v in self.consensus.status_pool.copy().values() if isinstance(v, dict)]
                # BEHIND if any peer advertises a heavier tip — OR we have peers but haven't learned their
                # tips yet (status_pool still empty right after startup/snapshot import). The latter closes
                # the window that let a just-synced node mint 100+ divergent blocks before it knew it was
                # behind. A solo node (no peers) has no statuses and mints normally.
                # SYBIL-STALL GUARD: a tip in rejected_tips (advertised heavier but we FAILED to obtain a
                # valid heavier chain for it) must not count — otherwise 2 forked-away clients advertising
                # a bogus weight keep this gate closed FOREVER (emergency sync fails, excludes the tip,
                # returns here, and the raw status still says "heavier" -> the whole network stops minting).
                # rejected_tips auto-clears every ~30s (consensus_loop), so a REAL heavier tip that merely
                # blipped is re-honoured on the next advertisement.
                _peer_ahead = peer_claims_heavier_tip(
                    statuses=_statuses, our_weight=_our_w, have_peers=len(peers) > 0,
                    rejected_tips=self.consensus.rejected_tips)

                # min_peers == 0 enables SOLO production (a single node mints without a peer mesh) —
                # used for a stable single-node relay/demo where multi-node fork-choice churn is undesirable.
                if (len(peers) >= self.memserver.min_peers
                        and not self.memserver.force_sync_ip
                        and not _peer_ahead):
                    block_candidate = get_block_candidate(logger=self.logger,
                                                          transaction_pool=self._candidate_pool(),
                                                          latest_block=self.memserver.latest_block
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

                        # same lost-update race as the drain above: snapshot-filter-reassign must be
                        # atomic vs concurrent merge_transaction appends (mempool lock). Drops txs whose
                        # max_block deadline has passed — an expired tx is NOT re-injected; the wallet
                        # re-submits a fresh one on the user's action (Re-open), never silently.
                        with self.memserver.mempool_lock:
                            self.memserver.transaction_pool = remove_outdated_transactions(
                                self.memserver.transaction_pool.copy(),
                                self.memserver.latest_block["block_number"])
                    else:
                        self.logger.warning("No eligible bonded producer this round; skipping production")

                # (no log for the "below min_peers / forced-sync in progress" case: it's a persistent normal
                # WAITING state that fires every ~1s loop, and the node's status is already in the periodic
                # message-loop line — logging it per iteration is pure spam.)

        except Exception as e:
            self.logger.info(f"Error: {e}")
            raise

    def _root_known_to(self, peer) -> bool:
        """the ONE network check of donor selection: does the peer serve our root (earliest) block?
        This is what makes a donor able to full-sync us; dialed only for peers that already passed
        every in-memory check."""
        return asyncio.run(knows_block(
            target_peer=peer,
            port=self.memserver.port,
            hash=self.memserver.earliest_block["block_hash"],
            logger=self.logger))

    def _fetch_sync_batch(self, peer, from_hash):
        """pull one forward-sync batch (up to SYNC_BATCH_MAX blocks after from_hash) from the donor.
        Falsy on ANY failure — never raises, so it is safe to run in the emergency loop's prefetch
        thread (asyncio.run spins a private event loop per call, thread-safe)."""
        try:
            return asyncio.run(get_blocks_after(
                target_peer=peer,
                from_hash=from_hash,
                count=SYNC_BATCH_MAX,
                logger=self.logger))
        except Exception as e:
            self.logger.error(f"Failed to fetch sync batch after {from_hash} from {peer}: {e}")
            return None

    def _donor_gate_passes(self, peer, required_hash, source_pool) -> bool:
        """The full IN-MEMORY donor gate (no network I/O), shared by the cache-revalidation and
        full-scan paths of get_peer_to_sync_from: not queued for purge, a routable non-self IP,
        and qualifies_to_sync (advertises required_hash, reachable, protocol high enough). A peer
        whose status hasn't been fetched yet is simply not qualified (protocol -1) — the old
        KeyError path BANNED it."""
        if peer in self.memserver.purge_peers_list:  # queued for purge; peer_loop flushes ~1/s
            return False
        if not check_ip(peer):
            return False
        peer_protocol = self.consensus.status_pool.get(peer, {}).get("protocol", -1)
        return qualifies_to_sync(peer=peer,
                                 peer_protocol=peer_protocol,
                                 memserver_protocol=self.memserver.protocol,
                                 unreachable_list=self.memserver.unreachable.keys(),
                                 peer_hash=source_pool.get(peer),
                                 required_hash=required_hash)["result"]

    def get_peer_to_sync_from(self, source_pool):
        """peer to synchronize pool when out of sync, critical part
        candidate tips are ordered by OBJECTIVE cumulative_weight (heaviest first); we return the first
        reachable peer advertising the heaviest tip that qualifies_to_sync.
        hash_pool argument is the pool to sort and sync from (block, tx, block producer pools).

        Cost discipline (this runs every ~1s in emergency mode): the in-memory gate
        (_donor_gate_passes) runs FIRST, and the single network round-trip (knows_block on our
        root) is dialed only for peers that passed it — the old code dialed EVERY pool peer per
        candidate hash, 5s timeout each. The last selected donor is cached: while it still
        advertises the current heaviest hash, we re-verify it with that one dial and return,
        instead of re-scanning (and re-logging) the whole pool each pass."""

        if self.memserver.force_sync_ip:
            """force sync"""
            return self.memserver.force_sync_ip

        source_pool_copy = source_pool.copy()
        source_pool_copy.pop(self.memserver.ip, None)
        """do not sync from self"""

        try:
            # #16 step 3: order candidate tips by OBJECTIVE cumulative_weight (heaviest first), NOT by
            # peer-count occurrence — so we sync toward the heaviest valid chain, not the most-advertised
            # one (which a Sybil peer-set could dominate). tip_weights includes our own tip.
            distinct_hashes = [h for h in set(source_pool_copy.values()) if h is not None]
            sorted_hashes = sorted(
                distinct_hashes,
                key=lambda h: (-self.consensus.tip_weights.get(h, -1), h)
            )[:self.memserver.cascade_limit]

            # (no "No hashes to sync from" log here: it fires every ~1s core-loop pass whenever no peer has
            # advertised a tip — a persistent normal WAITING state on a lone/bootstrap node, already visible
            # in the periodic status line. When empty we just fall through and return None.)
            if not sorted_hashes:
                return None

            # DONOR CACHE: reuse the previously selected donor while it still advertises the current
            # heaviest hash and passes the in-memory gate. Liveness is NOT assumed — the root-knowledge
            # dial re-runs (one round-trip), so a died-since donor falls through to a fresh scan instead
            # of being handed to emergency_mode, where a false knows_block(tip) would suggest a reorg.
            cached_peer, cached_hash = self._sync_donor
            if cached_peer is not None and cached_hash == sorted_hashes[0]:
                if (self._donor_gate_passes(cached_peer, cached_hash, source_pool_copy)
                        and self._root_known_to(cached_peer)):
                    self.memserver.cascade_depth = 1
                    return cached_peer
                self._sync_donor = (None, None)

            for depth, hash_candidate in enumerate(sorted_hashes, start=1):
                """go from the heaviest advertised tip to the lightest one"""
                self.memserver.cascade_depth = depth

                for peer in shuffle_dict(source_pool_copy):
                    if not self._donor_gate_passes(peer, hash_candidate, source_pool_copy):
                        continue

                    # in-memory gate passed -> the single network check (can this donor serve our root?)
                    try:
                        if self._root_known_to(peer):
                            if peer != cached_peer:
                                self.logger.info(f"Selected sync donor {peer} for tip "
                                                 f"{hash_candidate[:12]} (candidate depth {depth})")
                            self._sync_donor = (peer, hash_candidate)
                            return peer
                        self.logger.debug(f"{peer} not qualified for sync: our root hash is unknown to them")
                    except Exception as e:
                        self.logger.info(f"Peer {peer} error: {e}")
                        self.memserver.ban_peer(peer)

            self.logger.debug("Ran out of options when picking a sync donor")
            return None

        except Exception as e:
            self.logger.info(f"Failed to get a peer to sync from: hash_pool: {source_pool_copy} error: {e}")
            return None

    def minority_block_consensus(self):
        """OBJECTIVE fork-choice (#16/#17 step 3): we are out of sync ONLY when some peer advertises a
        tip whose cumulative_weight is STRICTLY GREATER than ours and we don't already hold that block.
        Equal or lower weight -> keep our tip (first-seen on ties). Peer IPs carry NO weight, so
        a Sybil peer-set cannot trigger a reorg; and even a heavier advertisement is only acted on by
        fetching the blocks, which verify_block re-derives + enforces (a lie is rejected) and the
        finality floor refuses to reorg below. Replaces the Sybil-swingable plurality majority_block_hash."""
        hh = self.consensus.heaviest_block_hash
        if hh is None:
            """not ready (no tip weights collected yet)"""
            return False
        # WEDGE-OVERRIDE: a strictly-heavier tip whose chain we just PROVED unverifiable (invalid block
        # extending our tip) must not keep us out of consensus — we can't adopt it, so mint our own valid
        # chain for a window instead of re-entering emergency forever. Bounded + self-expiring; a genuinely
        # heavier VALID chain never trips this (it fast-forwards cleanly and never sets the timestamp).
        if get_timestamp_seconds() < self._wedge_override_until:
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
        """Reconcile toward a sync-qualified peer's transaction pool when ours hashed into the MINORITY
        (normal_mode's once-per-interval convergence). MERGE, not wholesale replace: UNION the peer's txs
        into ours (dedup by txid, cull to the byte limit), the same way the 3-level buffer pipeline
        (user_tx_buffer -> tx_buffer -> transaction_pool) and the peer-gossip merge already union incoming
        txs. Wholesale replace was the crutch's flaw: a node that had just accepted a user's tx (so its pool
        went minority) would ADOPT a peer pool WITHOUT that tx and silently DROP it before it could gossip
        out. A union can never lose a local tx, and both sides still converge to the same set after a
        reconcile round. Mempool convergence only — NOT chain fork-choice (a block is validated from its OWN
        tx set via rebuild_block, so pool agreement is a latency optimisation, never a correctness gate).
        Best-effort: no qualifying peer, an empty peer pool, or a failed fetch simply keeps our pool intact."""
        sync_from = self.get_peer_to_sync_from(source_pool=self.consensus.block_hash_pool)
        if not sync_from:
            return
        peer_pool = self.replace_pool(peer=sync_from, key="transaction_pool")
        if not peer_pool:                     # empty peer pool or a fetch failure -> nothing to merge
            return
        with self.memserver.mempool_lock:
            local = self.memserver.transaction_pool
            seen = {tx.get("txid") for tx in local}
            merged = local + [tx for tx in peer_pool if tx.get("txid") not in seen]
            self.memserver.transaction_pool = cull_buffer(merged, self.memserver.transaction_pool_max_bytes)

    def replace_pool(self, peer, key):
        """replace pool (block, tx) when out of sync to prevent forking"""
        self.logger.info(f"Replacing {key} from {peer}")

        suggested_pool = asyncio.run(get_from_single_target(
            key=key,
            target_peer=peer,
            logger=self.logger))

        if suggested_pool:
            return suggested_pool
        else:
            self.logger.info(f"Could not replace {key} from {peer}")

    def snapshot_bootstrap(self, force_reanchor: bool = False) -> bool:
        """For a fresh node (still at genesis), bulk-download verified account state from peers instead of
        replaying the entire chain. Strictly additive and fully guarded: it runs ONLY while latest_block is
        genesis and ANY failure returns False so the normal block-by-block replay proceeds — it can never
        disrupt an established node or a re-org. It is RETRIED from the emergency loop until a donor advertises
        a finalized checkpoint. Anti-Sybil: a >=2-responder super-majority must agree the (height,hash); a
        LONE donor is accepted only when it is an operator seed (weak subjectivity). Peer downloads are
        size-capped (ops/net_ops) and the manifest is self-hash-validated before allocation (fetch_snapshot).

        force_reanchor=True — WEDGE RECOVERY for an ESTABLISHED node. A node whose snapshot/finality floor
        sits on a minority fork can NEVER reach the divergence point by rollback (it is below the floor), and
        no honest canonical donor can serve its forked root — so normal fast-forward AND reorg are both dead
        ends. In that state we re-import the heaviest chain's snapshot over our forked state and tail-sync.
        The checkpoint is chosen by OBJECTIVE cumulative WEIGHT (not by identity/plurality): the snapshot of
        the peer on the strictly-heaviest chain, above our finality floor. A lighter fork majority can never
        win a weight comparison regardless of headcount, so it can no longer pin us — which is what the old
        count-based agree_snapshot allowed. Everything below the new earliest block (our dead fork's blocks)
        is simply orphaned in the block store — never referenced."""
        if self.memserver.latest_block["block_number"] != 0 and not force_reanchor:
            return False   # genesis-only for normal bootstrap; force_reanchor re-anchors an established node
        try:
            peers = list(self.memserver.peers)
            if len(peers) < 1:
                return False

            # 1) collect peers' advertised snapshots; require a super-majority (Sybil gate)
            async def _statuses(ips):
                """Poll every candidate donor's status concurrently; exceptions are returned in-line
                (return_exceptions) so one dead peer can't sink the whole quorum sample."""
                return await asyncio.gather(*[get_remote_status(ip, logger=self.logger) for ip in ips],
                                            return_exceptions=True)
            raw = asyncio.run(_statuses(peers))
            statuses = [s if isinstance(s, dict) else None for s in raw]
            responders = [ip for ip, s in zip(peers, statuses) if s]

            from ops.peer_ops import seed_peers
            _seeds = set(seed_peers())

            if force_reanchor:
                # RE-ANCHOR: pick the checkpoint by OBJECTIVE cumulative WEIGHT, not by identity. Re-anchor
                # onto the snapshot advertised by the peer on the heaviest chain that is strictly heavier than
                # ours AND above our finality floor. This is what fixes the minority-fork wedge WITHOUT giving
                # any peer a privileged vote: a lighter fork majority can never win a weight comparison no
                # matter how many nodes it has, so plurality (the old agree_snapshot count) can no longer pin
                # us — while a genuinely heavier honest chain always does. Advertised weight is a HINT (a
                # Sybil can inflate it); the wipe is bounded by the wedged-precondition + REANCHOR_COOLDOWN,
                # and every tail block after the import is re-verified by verify_block, so a bogus checkpoint
                # cannot be extended and the real heaviest chain re-triggers.
                our_weight = self.memserver.latest_block.get("cumulative_weight", 0)
                cand = [(st["latest_block_weight"], st["snapshot_height"], st["snapshot_hash"], ip)
                        for ip, st in zip(peers, statuses)
                        if st and st.get("latest_block_weight") is not None
                        and st.get("snapshot_hash") and st.get("snapshot_height") is not None
                        and st["latest_block_weight"] > our_weight
                        and st["snapshot_height"] > self.memserver.finalized_height]
                if not cand:
                    self.logger.info("Re-anchor: no peer advertises a strictly-heavier chain with a snapshot "
                                     "above our finality floor; staying put")
                    return False
                _, target_height, target_hash, source = max(cand)
                self.logger.warning(f"Re-anchoring to heaviest-chain peer {source} snapshot at height "
                                    f"{target_height} (weight-selected)")
            else:
                # WEAK SUBJECTIVITY / anti-Sybil. import_snapshot only proves the donor's manifest is INTERNALLY
                # consistent (per-chunk sha256 + a locally re-derived state_root == manifest) — it does NOT prove
                # the state matches the real PoW chain. So a single unauthenticated donor must not be able to
                # dictate a fresh node's initial state. Require a >=2-responder super-majority in general; permit a
                # LONE donor only when it is a baked-in operator seed (DEFAULT_SEED_PEERS) — the weak-subjectivity
                # anchor a fresh node already relies on to bootstrap at all (classic weak-subjectivity checkpoint).
                lone_donor = len(responders) < 2
                if lone_donor and not any(ip in _seeds for ip in responders):
                    self.logger.info("Single snapshot donor is not an operator seed; using full sync")
                    return False
                agreed = snapshot_ops.agree_snapshot(statuses, min_peers=(1 if lone_donor else 2), threshold=0.8)
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
                # for a lone donor, the fetch source itself MUST be an operator seed (not just any responder
                # that happened to echo the hash) — otherwise a non-seed peer could serve the payload.
                if lone_donor and source not in _seeds:
                    self.logger.info("Single-donor snapshot source is not an operator seed; using full sync")
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
            set_latest_block_info(latest_block=anchor, logger=self.logger)
            self.memserver.latest_block = anchor

            # import_snapshot overwrote the persisted finality floor with the donor's, but the in-memory copy
            # was left at its genesis-time value (0). Refresh it so incorporate_block computes the next floor
            # from the real base and /status stops advertising finalized_height=0 until the first tail block.
            self.memserver.finalized_height = get_finalized_height()

            # BACKFILL the recent block BODIES the C+1..tip tail replay can NOT rebuild. block_by_num/hash
            # arrived in the snapshot, so HASH lookbacks (beacon anchor (epoch-1)*EPOCH_LENGTH, FFG/PoSW
            # epoch boundaries) already resolve — but a few lookbacks read the block BODY just behind C,
            # notably get_block_reward's cumulative_fees at (C - REWARD_WINDOW). Without those bodies the very
            # first produced/verified block C+1 crashes ("anchor #N missing" / reward lookback). Walk back by
            # parent_hash from the anchor, fetching + saving each body. Bounded + best-effort (a pruned donor
            # may lack the deepest ones; we stop cleanly and set earliest to the oldest we actually got).
            tail_depth = REWARD_WINDOW + 2 * EPOCH_LENGTH + FINALITY_DEPTH
            oldest, filled = anchor, 0
            for _ in range(tail_depth):
                ph = oldest.get("parent_hash")
                if not ph or int(oldest.get("block_number", 0)) <= 0:
                    break
                body = asyncio.run(snapshot_ops.fetch_block(source, self.memserver.port, ph))
                if not body or body.get("block_hash") != ph:
                    self.logger.warning(f"Snapshot body backfill stopped at height "
                                        f"{int(oldest.get('block_number', 0)) - 1} ({filled}/{tail_depth} "
                                        f"bodies) — donor lacks it; deeper lookbacks may skip until tail sync")
                    break
                save_block(body, logger=self.logger)
                oldest, filled = body, filled + 1
            set_earliest_block_info(earliest_block=oldest, logger=self.logger)
            self.memserver.earliest_block = oldest
            self.logger.warning(f"Snapshot bootstrap complete at height {target_height}; "
                                f"backfilled {filled} recent bodies behind C; replaying tail")
            return True

        except Exception as e:
            self.logger.error(f"Snapshot bootstrap failed, falling back to full sync: {e}")
            return False

    def _heavier_chain_exists(self) -> bool:
        """True if ANY peer advertises a chain STRICTLY heavier than our tip. This is the objective trigger
        for a re-anchor — the heaviest valid chain wins, with no privileged voter. Weight units match
        refresh_heaviest_tip (advertised latest_block_weight vs our cumulative_weight)."""
        our_weight = self.memserver.latest_block.get("cumulative_weight", 0)
        for st in self.consensus.status_pool.copy().values():
            if isinstance(st, dict) and (st.get("latest_block_weight") or 0) > our_weight:
                return True
        return False

    def _maybe_reanchor(self) -> bool:
        """WEDGE RECOVERY. Called from the emergency loop when normal sync cannot make progress — the donor
        can't serve our (forked) root, or the reorg leg hit a floor it can't cross. If a strictly-heavier
        chain exists, our snapshot/finality floor is on a minority fork: re-import that heavier chain's
        snapshot (weight-selected, see snapshot_bootstrap) and tail-sync onto it. Rate-limited
        (REANCHOR_COOLDOWN) so a failing import can't hammer peers. Returns True iff we re-anchored (caller
        then resumes the loop on the new chain)."""
        if not self._heavier_chain_exists():
            return False
        now = get_timestamp_seconds()
        if now - self._last_reanchor_ts < REANCHOR_COOLDOWN:
            return False
        self._last_reanchor_ts = now
        self.logger.warning("Wedged behind a strictly-heavier chain and normal sync cannot reconcile "
                            "(our snapshot/finality floor is on a minority fork) — re-anchoring by weight")
        if self.snapshot_bootstrap(force_reanchor=True):
            # our chain identity changed under us: drop stale fork-choice exclusions and the rollback burst
            # counter so the fresh tail sync starts clean.
            self.consensus.rejected_tips = set()
            self.memserver.rollbacks = 0
            return True
        return False

    def emergency_mode(self):
        """BEHIND-mode loop (entered when fork-choice says a strictly-better tip exists, or under
        operator force_sync_ip): pick a donor advertising the heaviest tip, then either FAST-FORWARD
        (donor knows our tip -> fetch the gap and produce_block each block) or REORG (donor doesn't
        -> roll back one block and retry, REINSERTING the reverted txs into the mempool — revert
        symmetry: a reorg must re-mine user transactions, never drop them). Being-behind is
        RE-EVALUATED every pass, because check_mode only runs BETWEEN emergency entries — a heavier
        tip that vanishes or gets rejected mid-loop must exit here, not spin forever. Every failure
        path calls _reject_heaviest_tip() (Sybil-stall/weight-DoS guard: a bogus advertised weight
        must not re-enter us indefinitely). Rollback depth is rate-limited per burst (max_rollbacks)
        and hard-capped by the finality floor (FinalityViolation -> refuse, resync forward only).
        A still-at-genesis node that no donor can full-serve retries snapshot bootstrap from here."""
        self.logger.warning("Entering emergency mode")
        # fresh burst: rollbacks is the PER-BURST rate limit (docstring above), but it was only ever
        # reset on the abort paths — a successful 4-deep reorg left it at 4 forever, so a later
        # legitimate deep reorg exhausted the cap early. Each emergency entry starts a new burst.
        self.memserver.rollbacks = 0
        if self.snapshot_bootstrap():
            self.logger.warning("State bootstrapped from snapshot; continuing with tail sync")
        try:
            self.logger.warning("Looping emergency mode")
            while self.memserver.emergency_mode and not self.memserver.terminate:
                # RE-EVALUATE being-behind every pass (the consensus thread refreshes tips concurrently;
                # check_mode only runs BETWEEN emergency entries). Without this, a heavier-advertised tip
                # that vanishes or gets rejected mid-loop (Sybil disconnects, tip excluded) left the node
                # spinning in "Could not find a syncable peer" FOREVER — emergency_mode is only ever
                # cleared by check_mode, which this loop never reaches. force_sync is operator-driven
                # and exempt (it syncs regardless of the weight comparison).
                if not self.minority_block_consensus() and not self.memserver.force_sync_ip:
                    self.logger.info("No heavier valid tip remains; leaving emergency mode")
                    break
                peer = self.get_peer_to_sync_from(source_pool=self.consensus.block_hash_pool)
                if not peer:
                    now = get_timestamp_seconds()
                    if now - self._last_no_syncable_log >= NO_SYNCABLE_LOG_INTERVAL:
                        self._last_no_syncable_log = now
                        self.logger.info("Could not find a syncable peer")
                    # A fresh node whose root (genesis) no peer can serve — because every donor is a
                    # rolling/pruned node — can never full-sync forward. Retry snapshot bootstrap until a
                    # donor advertises a finalized checkpoint, then tail-sync from there.
                    if self.memserver.latest_block["block_number"] == 0 and self.snapshot_bootstrap():
                        self.logger.warning("State bootstrapped from snapshot; continuing with tail sync")
                    # ESTABLISHED node, no donor can serve our root: we are on a minority fork whose root no
                    # honest canonical peer holds. If a strictly-heavier chain exists, re-anchor onto it (the
                    # only exit — normal fast-forward/reorg both require a donor that knows our root).
                    elif self._maybe_reanchor():
                        self.logger.warning("Re-anchored from seed snapshot; continuing with tail sync")
                    time.sleep(1)
                else:
                    block_hash = self.memserver.latest_block["block_hash"]
                    known_block = asyncio.run(knows_block(
                        target_peer=peer,
                        port=self.memserver.port,
                        hash=block_hash,
                        logger=self.logger))

                    if known_block:
                        self.logger.info(f"{peer} knows block {block_hash}")
                        if self._fast_forward_from(peer=peer, from_hash=block_hash):
                            break
                    elif self._rollback_one_for_reorg():
                        # the reorg leg gave up: rollback budget spent, no local parent left (snapshot floor),
                        # or the finality floor refused it. If a strictly-heavier chain exists this is a
                        # deep/minority fork we must re-anchor out of, rather than exit and re-mine our losing
                        # fork (which would only advance our floor and cement the wedge).
                        if self._maybe_reanchor():
                            self.logger.warning("Re-anchored from seed snapshot; continuing with tail sync")
                            continue
                        break

                    self.logger.info(f"Maximum reached cascade depth: {self.memserver.cascade_depth}")

        except Exception as e:
            self.logger.info(f"Error: {e}")
            raise

    def _fast_forward_from(self, peer, from_hash) -> bool:
        """FAST-FORWARD leg of emergency sync: the donor knows our tip, so pull the gap from it in
        pipelined batches — the NEXT batch (keyed off the current batch's tail hash) downloads in a
        background thread while the CPU verifies the current one. Sync is verify-bound, so the
        download rides for free. Returns True when the emergency pass should END (the tip was
        rejected: a block failed verification, the donor served nothing, or the fetch errored) and
        False when this donor's chain was consumed cleanly — the outer loop then re-evaluates
        being-behind and re-picks a donor."""
        try:
            new_blocks = self._fetch_sync_batch(peer=peer, from_hash=from_hash)
            if not new_blocks:
                # peer advertised heavier + claims to know our tip, then serves NOTHING —
                # a lying/broken peer. Reject the tip or we loop on it forever.
                self.logger.info(f"No newer blocks found from {peer}")
                self._reject_heaviest_tip()
                return True

            while new_blocks and not self.memserver.terminate:
                prefetch = {}
                prefetch_thread = threading.Thread(
                    target=lambda tail=new_blocks[-1]["block_hash"]: prefetch.update(
                        batch=self._fetch_sync_batch(peer=peer, from_hash=tail)),
                    daemon=True)
                prefetch_thread.start()

                rejected = False
                for block in new_blocks:
                    if self.memserver.terminate:
                        break
                    if not self.produce_block(block=block, remote=True, remote_peer=peer):
                        # INVALID/FORGED sync block (verify failed): the advertised heavier tip is
                        # not backed by a valid chain — exclude it, or this loop re-enters forever
                        # on the same bad advertisement (Sybil-stall). Auto-cleared, so a transient
                        # failure on a REAL heavier chain is retried in ~30s. (produce_block also
                        # returns False when interrupted by shutdown — don't reject the tip then.)
                        if not self.memserver.terminate:
                            self._reject_heaviest_tip()
                            # this heavier tip's chain is UNVERIFIABLE to us (a bad block extends our tip).
                            # Grant a mint window on our own valid chain so we don't freeze here forever.
                            self._wedge_override_until = get_timestamp_seconds() + WEDGE_OVERRIDE_SECS
                            self.logger.warning(f"Heavier tip's chain failed verification at block "
                                                f"{str(block.get('block_number'))} — minting our own valid "
                                                f"chain for {WEDGE_OVERRIDE_SECS}s (never adopting the bad block)")
                        rejected = True
                        break

                prefetch_thread.join()
                if rejected:
                    return True
                new_blocks = prefetch.get("batch")
            return False

        except Exception as e:
            self.logger.error(f"Failed to get blocks after {from_hash} from {peer}: {e}")
            self._reject_heaviest_tip()
            return True

    def _rollback_one_for_reorg(self) -> bool:
        """REORG leg of emergency sync: the donor does NOT know our tip, so our chain has diverged —
        revert ONE block (reinserting its txs into the mempool; revert symmetry: a reorg must
        re-mine user transactions, never drop them) and let the next pass retry the donor one block
        deeper. Returns True when the emergency pass should END: the per-burst rollback budget is
        exhausted, no local parent remains to roll back through (snapshot-bootstrapped node), or
        the finality floor refused the reorg — each rejects the tip so we don't spin on it."""
        if self.memserver.rollbacks >= self.memserver.max_rollbacks:
            self.logger.error(
                f"Rollbacks exhausted ({self.memserver.rollbacks}/{self.memserver.max_rollbacks})")
            self.memserver.rollbacks = 0
            self._reject_heaviest_tip()
            return True

        # capture the tip's txs BEFORE reverting so a reorg re-mines them instead of dropping them.
        reverted_txs = self.memserver.latest_block.get("block_transactions", []) or []
        try:
            self.memserver.latest_block = rollback_one_block(logger=self.logger,
                                                             block=self.memserver.latest_block)
        except MissingParentError as e:
            # we have run out of local history to roll back through (e.g. a snapshot-bootstrapped
            # node). Abort the cascade and let the next emergency cycle resync (snapshot/full)
            # instead of spinning.
            self.logger.error(f"Rollback aborted, resync required: {e}")
            self.memserver.rollbacks = 0
            self._reject_heaviest_tip()
            return True
        except FinalityViolation as e:
            # the reorg would cross the finalized-height floor (a deep / long-range rollback).
            # REFUSE it — the finalized prefix is immutable — and resync forward only. This is
            # the hard 51%/rollback cap (#17).
            self.logger.error(f"Rollback refused (finality): {e}")
            self.memserver.rollbacks = 0
            self._reject_heaviest_tip()
            return True

        # REINSERT the reverted block's txs into the mempool. Blind reinsertion is safe:
        # remove_outdated_transactions (at production) drops any whose target block is now in the
        # past, validate_transaction (candidate build) drops any now-invalid, and merge_transaction
        # dedups so live copies aren't doubled.
        for _tx in reverted_txs:
            try:
                self.memserver.merge_transaction(_tx, user_origin=True)
            except Exception:
                pass

        # ALWAYS count the rollback (even under force_sync_ip): the finalized floor is the hard
        # safety cap; this counter only rate-limits a single burst, so a forced sync can no longer
        # roll back unboundedly (closes the force_sync leak).
        self.memserver.rollbacks += 1
        return False

    def _reject_heaviest_tip(self):
        """AUDIT FIX (weight-DoS): exclude the advertised-heaviest tip we just FAILED to obtain a valid
        heavier chain for, so a peer advertising a bogus huge cumulative_weight cannot keep looping us
        into emergency-mode/rollback. The exclusion is bounded + auto-cleared (consensus_loop), so a
        transiently-unreachable REAL heavier tip is retried later."""
        hh = self.consensus.heaviest_block_hash
        if hh and hh != self.memserver.latest_block["block_hash"]:
            self.consensus.rejected_tips.add(hh)
            self.logger.warning(f"Excluding unreachable heavier-advertised tip {hh[:12]} (weight-DoS guard)")
        # the donor that fed us this tip just failed — drop it from the donor cache so the next
        # get_peer_to_sync_from pass re-scans instead of re-serving it (sorted_hashes does not
        # consult rejected_tips, so the cache key alone would not miss).
        self._sync_donor = (None, None)

    def _candidate_pool(self):
        """Pre-validate pool txs against the NEXT height before they enter OUR OWN block candidate.
        construct_block hashes the tx set immediately, and save_block refuses any block whose content
        no longer matches its hash (the anti-fork invariant) — so an invalid pool tx (e.g. a stale
        duplicate attest/reveal) dropped later in verify_block mutates the block AFTER hashing and
        costs us the whole production slot (observed 120-230s block gaps of consecutive refused
        candidates). Excluded txs stay in the pool: one that turns valid later still gets its chance,
        the rest age out via remove_outdated_transactions. The incremental validate_all_spending pass
        keeps the aggregate per-account spend of the SELECTED set within balance, so verify_block's
        whole-block spending check cannot abort our own candidate either."""
        next_height = self.memserver.latest_block["block_number"] + 1
        selected = []
        for tx in self.memserver.transaction_pool.copy():
            try:
                # AT-MOST-ONCE (halt fix 2026-07-11): an ALREADY-MINED txid must never enter our own
                # candidate. verify_block would drop it — but only AFTER construct_block hashed the set,
                # mutating the block post-hash so save_block refuses it and we wedge on this height
                # forever (a sync donor re-injecting the mined tx via "Replacing transaction_pool" made
                # the node stall on one block number indefinitely). Skip it here so the candidate hash is
                # correct from the start. Same tx-index oracle verify_block/the pool-cull already use.
                if kv_ops.tx_get(tx.get("txid")) is not None:
                    continue
                validate_transaction(transaction=tx, logger=self.logger, block_height=next_height)
                validate_all_spending(transaction_pool=selected + [tx])
            except Exception as e:
                self.logger.info(f"Candidate excludes pool tx {str(tx.get('txid'))[:16]}: {e}")
                continue
            selected.append(tx)
        return selected

    def _reserved_tx_pending(self, recipient, target_epoch):
        """True if our own reserved tx (attest/commit/reveal) for this epoch is already waiting in a
        pool/buffer. Without this check the ~1s core loop mints a fresh duplicate (new nonce -> new
        txid) every iteration until the first copy is mined; the stragglers then fail validation in
        later candidates ('already attested/revealed this epoch') and poison block production."""
        # .copy(): other threads append to the live lists; iterating a snapshot avoids skipped
        # elements (a false negative here mints the duplicate this guard exists to prevent).
        for tx in self.memserver.transaction_pool.copy():
            if (tx.get("recipient") == recipient
                    and tx.get("sender") == self.memserver.address
                    and isinstance(tx.get("data"), dict)
                    and tx["data"].get("target_epoch") == target_epoch):
                return True
        return False

    def rebuild_block(self, block):
        """Deterministically reconstruct a block from OUR local tip + the incoming block's tx set and
        its OWN committed timestamp: winner, reward, cumulative fees and fork weight are all
        RE-DERIVED from parent state, so only a block matching the canonical reconstruction can be
        incorporated — a peer cannot misattribute the producer, inflate the reward, or forge weight
        (produce_block then enforces rebuilt hash == claimed hash). Also reused for our OWN candidate
        after verification drops an invalid tx. NEVER stamp wall-clock time here — see the inline
        timestamp note: doing so forked every catching-up node onto a private chain."""
        # Reconstruct the block deterministically from the LOCAL tip + the block's tx set: the winner
        # (block_creator) and reward/cumulative_fees are RECOMPUTED from local parent state, so a
        # peer cannot misattribute the producer or inject an inflated reward — only a block matching
        # the canonical reconstruction is incorporated. (Producer-signature AUTHENTICATION is
        # deferred to the coordinated security milestone: winner-only signing both fights the
        # peer-majority fork-choice AND would break 'win while asleep', so it needs stake-weighted
        # fork-choice + finality + an offline-win/relay-delegation decision. See #15/#16/#17.)
        parent = self.memserver.latest_block
        block_number = parent["block_number"] + 1
        _epoch = epoch_of(block_number)
        bonded_registry = get_bonded_registry()  # as-of-parent (tip == parent here)
        # RANDAO gate (pass-through while RANDAO_ENFORCED is off — reveals are optional); the FULL
        # registry always feeds block_fork_weight below (withholding must not move fork-choice).
        winner = select_producer_two_lane(get_open_registry(_epoch),
                                          randao_eligible_bonded(bonded_registry, _epoch),
                                          epoch_beacon(_epoch), slot=block_number)
        return construct_block(
            # CRITICAL: use the INCOMING block's OWN timestamp, NOT our wall-clock. rebuild_block
            # deterministically reconstructs a REMOTE block to re-derive the winner/reward/weight (anti-forgery),
            # but the timestamp is the producer's committed field and is validated separately
            # (valid_block_timestamp, must be <= now). Stamping wall-clock here made the rebuilt hash diverge
            # from the canonical block for any HISTORICAL block (rebuilt long after it was minted), so a
            # catching-up node forked into a parallel chain and wedged ("out of consensus" / "Rollback refused
            # (finality)"). Using the block's own timestamp makes the rebuild byte-identical -> hashes agree.
            block_timestamp=block["block_timestamp"],
            block_number=block_number,
            parent_hash=parent["block_hash"],
            creator=winner,
            transaction_pool=block["block_transactions"],
            block_reward=get_block_reward(parent_block=parent),
            parent_cumulative_fees=parent.get("cumulative_fees", 0),
            parent_cumulative_weight=parent.get("cumulative_weight", 0),
            block_weight=block_fork_weight(bonded_registry, block_number),
            # preserve the REMOTE block's own chain_id label (informational, not hashed) so the rebuilt
            # block stays byte-identical to what the peer sent; the hash is chain_id-invariant either way.
            chain_id=block.get("chain_id", CHAIN_ID))

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
                         fees=totals["fees"])

            index_block_number(block)  # the applied marker, atomic with the state above

        # Advance the tip pointer file only AFTER the atomic state commit. A crash before this
        # just leaves a stale tip that re-syncs forward; block_already_indexed prevents re-apply.
        set_latest_block_info(latest_block=block, logger=self.logger)

        # ENFORCED FINALITY (#17 step 1): advance the persisted monotonic finalized-height floor. A
        # block at height H finalizes everything at/below H - finality_depth; rollback_one_block then
        # REFUSES to cross it. Monotonic (max), recomputable, and crash-conservative: a crash between
        # the block commit above and this write leaves the floor one behind (never ahead) and it
        # re-advances on the next block — it can never finalize something that wasn't committed.
        # The floor is the DEEPER (higher) of two guarantees: the always-advancing time/depth floor
        # (tip - finality_depth, subjective but live), and the FFG checkpoint (block E*EPOCH_LENGTH that a
        # >2/3 bonded-stake quorum attested — OBJECTIVE, accountable, slashable). Folding FFG in makes a
        # stake-finalized checkpoint UN-REORGABLE (rollback_one_block refuses to cross finalized_height),
        # so remote sync can never adopt a heavier chain that conflicts with it — the safety FFG was built
        # for, now enforced instead of merely observed. FFG normally trails the depth floor, so on a healthy
        # synced node this is the depth floor; it binds when FFG is ahead (e.g. a shallow finality_depth, or
        # a node catching up whose depth floor hasn't advanced yet).
        new_final = max(self.memserver.finalized_height,
                        block["block_number"] - self.memserver.finality_depth,
                        int(getattr(self.memserver, "ffg_finalized", 0) or 0))
        if new_final > self.memserver.finalized_height:
            set_finalized_height(new_final)
            self.memserver.finalized_height = new_final

        # ROLLING-NODE SYNC: at each checkpoint interval, persist a verified snapshot of state@N.
        # The write txn above has committed and no later block is applied yet, so accounts.db == state@N
        # here — the checkpoint is correct by construction (no historical-state derivation). /status
        # advertises it only once finalized (reorg-safe); rollback_one_block drops checkpoints above tip.
        self.maybe_checkpoint_state(block)

    def maybe_checkpoint_state(self, block):
        """At each CHECKPOINT_INTERVAL boundary, persist a verified snapshot of state@N for
        rolling-node sync. Correct by construction ONLY at its call site (end of incorporate_block:
        the write txn for block N has committed and no later block is applied, so accounts.db IS
        state@N). Best-effort and non-fatal — a failed checkpoint costs future donors a snapshot,
        never the block."""
        n = block["block_number"]
        if n <= 0 or n % snapshot_ops.CHECKPOINT_INTERVAL != 0:
            return
        try:
            snapshot_ops.persist_checkpoint(height=n, block_hash=block["block_hash"],
                                            protocol=self.memserver.protocol,
                                            version=self.memserver.version)
            self.logger.warning(f"State checkpoint captured at height {n} (rolling-node sync)")
        except Exception as e:
            self.logger.error(f"State checkpoint at height {n} failed (non-fatal): {e}")

    def update_ffg_and_attest(self):
        """FFG (#6): refresh the stake-attested finalized checkpoint and, if we are a bonded validator who
        hasn't attested the current epoch, broadcast our attestation. The checkpoint is now FOLDED INTO the
        enforced finality floor (see incorporate_block: finalized_height = max(depth floor, ffg_finalized)),
        so a >2/3-stake-attested checkpoint is objectively un-reorgable — not merely observed. Best-effort:
        it NEVER raises into the core loop and never blocks production; the depth floor remains the liveness
        guarantee, FFG is the stronger objective floor layered on top (usually trailing it)."""
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
            if self._reserved_tx_pending("attest", epoch):
                return  # our attestation is already in flight — don't mint a duplicate every loop
            checkpoint_hash = get_block_hash_by_number(epoch * EPOCH_LENGTH)
            if not checkpoint_hash:
                return
            max_block = min(latest["block_number"] + 5, (epoch + 1) * EPOCH_LENGTH - 1)
            if max_block <= latest["block_number"]:
                return  # at the epoch's final block -> attest next epoch instead
            tx = construct_attestation_tx(self.memserver.keydict, epoch, checkpoint_hash, max_block)
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

            # COMMIT for epoch current+2 (we are in its E-2). RETRIED while the window lasts: the
            # old single-shot guard (skip once the secret existed in randao_secrets) meant a commit
            # tx that missed its exact max_block was never re-issued — the validator silently sat
            # out the whole epoch, weakening the beacon (and forfeiting production rights whenever
            # RANDAO_ENFORCED is on; participation is voluntary under the current policy). Reusing
            # the stored secret keeps the commitment identical, so a raced duplicate is simply
            # rejected by validation ("Already committed for this epoch").
            e_commit = current_epoch + 2
            if (kv_ops.commit_get(self.memserver.address, e_commit) is None
                    and not self._reserved_tx_pending("commit", e_commit)):
                max_block = min(latest["block_number"] + 5, (current_epoch + 1) * EPOCH_LENGTH - 1)
                if max_block > latest["block_number"]:
                    secret = self.memserver.randao_secrets.get(e_commit) or _secrets.token_hex(32)
                    self.memserver.randao_secrets[e_commit] = secret
                    tx = construct_commit_tx(kd, e_commit, beacon_commitment(secret), max_block)
                    self.memserver.merge_transaction(tx, user_origin=True)

            # REVEAL for epoch current+1 (we are in its E-1 finalized window), if we hold its secret
            e_reveal = current_epoch + 1
            secret = self.memserver.randao_secrets.get(e_reveal)
            if secret and kv_ops.commit_get(self.memserver.address, e_reveal) is not None:
                lo = current_epoch * EPOCH_LENGTH
                hi = e_reveal * EPOCH_LENGTH - FINALITY_DEPTH - 1
                max_block = latest["block_number"] + 5
                if (lo <= max_block <= hi
                        and secret not in kv_ops.reveals_for_epoch(e_reveal)
                        and not self._reserved_tx_pending("reveal", e_reveal)):
                    tx = construct_reveal_tx(kd, e_reveal, secret, max_block)
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
            max_block = self.memserver.latest_block["block_number"] + 2
            tx = construct_bond_tx(self.memserver.keydict, to_bond, MIN_TX_FEE, max_block)
            self.memserver.merge_transaction(tx, user_origin=True)
            self.last_auto_bond_epoch = epoch
            # account for the gain now; the bond+fee will reduce balance in a later block (negative
            # delta, harmlessly rebaselined). Optimistic baseline = expected post-bond spendable.
            self.auto_bond_baseline = balance - to_bond - MIN_TX_FEE
            self.logger.info(
                f"Auto-bond: bonding {to_bond} raw ({pct}% of {gain} new earnings) into the bonded lane "
                f"(max_block {max_block})")
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
                # throttle this probe too: without setting the epoch marker, a bonded-only node
                # re-read its own account from the KV store every ~1s pass forever, for nothing.
                self.last_auto_collect_epoch = epoch
                return                                  # not an open-lane member -> nothing accrues
            max_block = self.memserver.latest_block["block_number"] + 2
            tx = construct_blob_tx(self.memserver.keydict, {"op": "collect_dividend"}, max_block, MIN_TX_FEE)
            self.memserver.merge_transaction(tx, user_origin=True)
            self.last_auto_collect_epoch = epoch
            self.logger.info(f"Auto-collect: swept presence dividend (max_block {max_block})")
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
            max_block = self.memserver.latest_block["block_number"] + 4
            anchor = get_block_hash_by_number(max(0, max_block - POSW_ANCHOR_OFFSET))
            if not anchor:
                return
            req_t = required_posw_t(epoch_of(max(0, max_block - POSW_ANCHOR_OFFSET)))
            proof = posw.prove(posw.challenge_bytes(self.memserver.address, anchor), T=req_t, S=POSW_S, k=POSW_K)
            tx = construct_register_tx(self.memserver.keydict, max_block, proof)
            self.memserver.merge_transaction(tx, user_origin=True)
            self.last_auto_register_epoch = epoch
            self.logger.info(f"Auto-register: (re)joined the open lane (max_block {max_block}, PoSW T={req_t})")
        except Exception as e:
            self.logger.info(f"Auto-register skipped: {e}")

    def validate_transactions_in_block(self, block, logger, remote_peer, remote):
        """CONSENSUS validation of the block's tx set against PARENT state at the block's own height:
        target-block match, per-block blob DA cap, whole-block aggregate spending, reserved-tx rules,
        then per-tx validity — all fail-closed for a peer's block. The critical remote/own asymmetry
        on a bad tx: a REMOTE block containing ANY invalid tx is rejected WHOLESALE (a peer never gets
        partial acceptance of a forged set), while OUR OWN candidate silently DROPS the offender and
        keeps building — one stale mempool tx must never cost the whole production slot, and removal
        only REDUCES spending so the survivors stay valid (produce_block then rebuilds + re-hashes).
        Side effect: the block's txs are evicted from the local pools/buffers so they aren't re-mined.
        Runs inside verify_block, strictly BEFORE incorporation, so all account reads are as-of-parent."""
        transactions = sort_list_dict(block["block_transactions"])

        # target-block matching enforced from block 1
        if not check_target_match(transactions, block["block_number"], logger=logger):
            self.logger.error("Transactions mismatch target block")
            raise ValueError("Transactions mismatch target block")

        # AT-MOST-ONCE INCLUSION (2026-07, consensus): a txid may be mined in AT MOST ONE block, ever.
        # (1) no duplicate txid WITHIN this block; (2) no txid already recorded in the on-chain tx-index
        # by an ANCESTOR block (index is written on incorporate, which is strictly AFTER this check, so
        # tx_get can only see ancestors — never this block itself). A txid hashes the tx content, so this
        # makes re-including an IDENTICAL transaction impossible. Fail-closed for a REMOTE block (a peer's
        # block replaying a mined tx is rejected wholesale); for OUR OWN candidate the offender is dropped
        # below. This is the fix for the bridge-deposit double-credit (a flexibly-landing tx was otherwise
        # re-included in every block up to its max_block). Deterministic: the tx-index is a pure function
        # of committed ancestor state, identical on every node — same class as validate_all_spending.
        seen_txids = set()
        already_mined = []
        for t in transactions:
            txid = t.get("txid")
            if txid in seen_txids:
                self.logger.error(f"Duplicate txid {str(txid)[:16]} within block {block['block_number']}")
                raise ValueError("Duplicate transaction within block")
            seen_txids.add(txid)
            if kv_ops.tx_get(txid) is not None:
                already_mined.append(t)
        if already_mined:
            if remote:
                self.logger.error(f"Block {block['block_number']} replays {len(already_mined)} already-mined tx(s)")
                raise ValueError("Block contains an already-mined transaction")
            # OWN candidate: drop the already-mined stragglers (they linger in the pool until evicted
            # below) and keep building; produce_block rebuilds + re-hashes the reduced set.
            for t in already_mined:
                if t in transactions:
                    transactions.remove(t)
                if t in block["block_transactions"]:
                    block["block_transactions"].remove(t)

        # DATA-AVAILABILITY cap (doc/execution-layer.md §3.3): reject a block carrying more blob bytes
        # than phones can be expected to download/relay. Fail-closed like the other block-set checks.
        try:
            assert_block_blob_cap(transactions)
        except Exception as e:
            self.logger.error(f"Block exceeds per-block blob cap: {e}")
            raise

        try:
            validate_all_spending(transaction_pool=transactions)
        except Exception as e:
            self.logger.error(f"Failed to validate spending during block preparation: {e}")
            raise

        else:
            for transaction in transactions:

                # Evict from the single pool so a just-included tx is never re-selected next round.
                if transaction in self.memserver.transaction_pool:
                    self.memserver.transaction_pool.remove(transaction)

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
                        # a peer's block with an invalid tx is rejected wholesale.
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
        # RANDAO gate (consensus): verification draws over the same eligible set production uses
        # (the full registry while RANDAO_ENFORCED is off; the revealed-for-epoch subset when on).
        winner = select_producer_two_lane(get_open_registry(epoch),
                                          randao_eligible_bonded(get_bonded_registry(), epoch),
                                          epoch_beacon(epoch),
                                          slot=block_number)
        if winner is None:
            raise ValueError("No eligible producer for this block (fail-closed)")
        if block.get("block_creator") != winner:
            raise ValueError(
                f"Block creator {block.get('block_creator')} is not the selected winner {winner}")

    def verify_block(self, block, remote, remote_peer=None):
        """this function has critical checks and must raise a failure/halt if there is one"""
        # todo move exceptions lower (as in rollback) and avoid rising here directly
        try:
            self.logger.warning(f"Preparing block")

            if not valid_block_timestamp(new_block=block):
                raise ValueError(f"Invalid block timestamp {block['block_timestamp']}")

            # chain_id is INFORMATIONAL only (no longer in block_hash / signature / weight): a block is bound
            # to THIS chain by its parent-hash linkage back to our unique genesis, so a foreign or pre-reboot
            # block can never link in regardless of its chain_id label. We therefore do NOT gate consensus on
            # it — gating on the live CHAIN_ID constant is exactly what used to break sync-from-genesis after
            # a rename. (Cross-CHAIN transaction replay is still prevented by the per-tx chain_id check.)

            # The reward is RECOMPUTED from the block's parent ancestry and enforced for
            # equality (not merely range-checked): a synced block whose reward != the
            # deterministic value is rejected, closing the old "claim any reward <= cap" mint.
            # Cheap range pre-check first (also stops a negative reward wedging change_balance).
            reward = block.get("block_reward")
            # max legit reward is BASE_SUBSIDY (emission is BASE_SUBSIDY * m(r), m<=1). Cheap range guard
            # before change_balance; the exact-match check below is the real validation.
            if not isinstance(reward, int) or isinstance(reward, bool) or reward < 0 or reward > BASE_SUBSIDY:
                raise ValueError(f"Invalid block reward {reward!r}")
            expected_reward = get_block_reward(parent_block=self.memserver.latest_block)
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
            expected_weight = parent_weight + block_fork_weight(get_bonded_registry(),
                                                                block["block_number"])
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
                claimed_hash = block.get("block_hash")
                try:
                    block = self.rebuild_block(block)
                except Exception as e:
                    raise ValueError(f"Failed to reconstruct block {e}")
                # HASH-CONSISTENCY INVARIANT (anti-fork): the deterministic reconstruction must reproduce the
                # peer's CLAIMED block_hash exactly. If it doesn't, the block LIES about its hash — either a
                # forgery or a corrupted/half-reorged block (e.g. a body whose parent_hash was rewritten
                # without re-hashing). REJECT it loudly instead of silently rebuilding it to a different hash,
                # which would fork this node onto a private chain and wedge it out of consensus. Every honest
                # node computes the same hash from the same content, so a legitimate block always passes.
                if block["block_hash"] != claimed_hash:
                    raise ValueError(
                        f"Block {block['block_number']} hash mismatch: content hashes to "
                        f"{block['block_hash'][:16]} but peer claims {str(claimed_hash)[:16]} — refusing "
                        f"(forged or corrupt block; would fork us)")

            verified_block = self.verify_block(block, remote=remote, remote_peer=remote_peer)

            # BELT (own blocks only): if verify_block still dropped a tx from OUR candidate after
            # construct_block hashed it, the stored hash no longer matches the content and save_block
            # would refuse the block (anti-fork invariant), wasting the slot. Rebuild deterministically
            # from the surviving tx set — same parent + timestamp -> same winner/reward/weight, only
            # the tx set + cumulative_fees + hash change — and re-sign. Re-signing the same height is
            # safe: the abandoned candidate never left this process (nothing is broadcast before
            # incorporation), so no equivocation proof can exist against us.
            if not remote and block_content_hash(block) != block["block_hash"]:
                self.logger.warning("Own candidate mutated during verification "
                                    "(invalid tx dropped); rebuilding + re-hashing")
                block = self.rebuild_block(block)
                if self.memserver.address == block["block_creator"]:
                    sign_block(block, self.memserver.private_key, self.memserver.public_key)
                verified_block = sort_list_dict(block["block_transactions"])

            if self.memserver.latest_block["block_creator"] == block["block_creator"]:
                self.consecutive += 1
            else:
                self.consecutive = 0

            self.incorporate_block(block=block, sorted_transactions=verified_block)
            self.memserver.latest_block = block

            gen_elapsed = get_timestamp_seconds() - gen_start

            # the producer is identified by the winner ADDRESS (block_creator) alone
            if self.memserver.address == block['block_creator'] and block['block_reward'] > 0:
                self.logger.warning(f"$$$ Congratulations! You won! $$$")

            self.logger.warning(f"Block hash: {block['block_hash']}")
            self.logger.warning(f"Block number: {block['block_number']}")
            self.logger.warning(f"Winner: {block['block_creator']}")
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
        """Seed the shared transaction-pool hash before the first pass so the pool-minority reconcile
        (and peers polling our status) compare against a real value, never a stale/unset one."""
        self.memserver.transaction_pool_hash = (
            self.memserver.get_transaction_pool_hash()
        )

    def check_mode(self):
        """Decide the next pass's mode: emergency (sync/reorg) when the objective fork-choice says a
        strictly-better tip exists (minority_block_consensus) OR an operator forced a sync; normal
        otherwise. Also releases force_sync_ip once we agree with >80% of peers on a fresh tip —
        the forced donor has served its purpose and normal fork-choice takes back over."""
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
        """Thread entry: once per run_interval, re-evaluate our consensus position (check_mode) and
        dispatch to normal_mode (caught up: drain mempool + maybe mint) or emergency_mode (behind:
        sync/reorg). Exceptions are contained per pass — the core loop must outlive any single
        failure until terminate is set."""
        self.init_hashes()

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
                self.logger.error(f"Error in core loop: {e} {traceback.format_exc()}")
                time.sleep(1)
                # raise #test

        self.logger.info("Termination code reached, bye")
        sys.exit(0)
