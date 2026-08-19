import asyncio
import json
import os
import sys
import threading
import time
import traceback

from config import get_timestamp_seconds, get_config
from ops.account_ops import get_totals, index_totals, get_bonded_registry, get_open_registry, set_finalized_height, get_finalized_height, get_hard_finality, set_hard_finality, get_account
from ops.block_ops import (
    knows_block,
    get_blocks_after,
    SYNC_BATCH_MAX,
    get_block_candidate,
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
    prune_tx_history_window,
    randao_eligible_bonded,
)
from ops.mining_ops import select_producer_two_lane, epoch_of, block_fork_weight
from ops import kv_ops
from ops import fork_resolution
from protocol import CHAIN_ID, BASE_SUBSIDY, MIN_TX_FEE, BOND_CAP, AUTO_BOND_MIN_RAW, AUTO_COLLECT_MIN_RAW, \
    AUTO_MIN_FEE_MULTIPLE, \
    TX_INCLUSION_DELAY, TX_TARGET_MARGIN, RESERVED_TX_MARGIN, DUTY_TX_MARGIN, FLEX_TX_MIN_MARGIN, \
    DUTY_WINDOW_ACTIVATION
from ops.data_ops import shuffle_dict, sort_list_dict, get_byte_size, get_home
from ops.peer_ops import check_ip, qualifies_to_sync, get_remote_status
from ops import snapshot_ops
from ops.pool_ops import cull_buffer
from ops.transaction_ops import remove_outdated_transactions
from ops.transaction_ops import (
    to_readable_amount,
    validate_transaction,
    validate_all_spending, index_transactions, assert_unique_reserved, assert_block_blob_cap, SpendingLedger, ProofUnavailable)
import secrets as _secrets
from rollback import rollback_one_block, MissingParentError, FinalityViolation
from ops.reward_ops import credit_block_reward, apply_treasury_burn
from ops.transaction_ops import (construct_duty_tx,
                                 construct_bond_tx, construct_blob_tx, construct_register_tx,
                                 construct_dividend_withdraw_tx)
from ops.attestation_ops import ffg_finalized_checkpoint
from ops.mining_ops import beacon_commitment
from protocol import EPOCH_LENGTH, FINALITY_DEPTH, FINALITY_HARD_BACKSTOP, REWARD_WINDOW

# ARCHIVE SELF-REPAIR cadence (seconds): how often an archive node whose history does not reach genesis
# looks for a peer that reaches deeper and starts a background fill (_maybe_refill_archive). Only while a
# gap exists; a whole archive costs nothing here.
ARCHIVE_REFILL_EVERY = 600

# How often (seconds) emergency mode logs "Could not find a syncable peer". The loop still retries every
# ~1s, but a lone/bootstrap node with no reachable donor would otherwise flood the log once/sec.
NO_SYNCABLE_LOG_INTERVAL = 30
# Seconds a strictly-better-but-unheld tip must PERSIST before we call it a fork and enter emergency
# mode. Below this it is ordinary propagation lag (see minority_block_consensus). ~half a block.
MINORITY_GRACE_S = 5

# How often (seconds) to log + telemetry-count an emergency-mode entry. emergency_mode() is re-entered
# ~1/s while behind; without this throttle "Entering/Looping emergency mode" spammed the journal and a
# single continuous episode inflated the emergency counter by hundreds. A periodic heartbeat is enough.
_EMERGENCY_LOG_EVERY = 20
# How often (seconds) to emit the per-sub-DB STATE DIVERGENCE fingerprint + count a reject. The fingerprint
# is a FULL extra state walk and the counter rewrites a JSON file; a diverged node retries ~1/s against every
# peer, so unthrottled this amplifies the wedge it is meant to diagnose.
_DIVERGENCE_LOG_EVERY = 20

# Minimum seconds between seed-anchored RE-ANCHOR attempts. A wedged node (stuck on a minority fork below
# its snapshot/finality floor) re-imports a seed's snapshot to recover; bound the retry so a persistently
# failing import can't hammer the seed every pass.
REANCHOR_COOLDOWN = 30
# Consecutive DEAD_FORK verdicts before the floor-crossing re-anchor is allowed. _fork_state() is cached
# for FORK_STATE_TTL_S and costs direct peer probes, so this is several independent measurements, not a
# tight spin: a transient misreading cannot reach the escalation, while a genuine wedge (which persists for
# as long as nobody intervenes) reaches it in well under a minute instead of never.
DEAD_FORK_ESCALATE_AFTER = 3



# NO AUTOMATED OPERATION MAY SPEND MORE THAN HALF THE SPENDABLE BALANCE IN ONE ACTION.
#
# Operator rule, and a hard ceiling rather than a heuristic: an unattended path may never put more than 50%
# of what the node can spend behind a single transaction. Not for today's numbers (every automated tx here
# is a rounding error against any node's balance) but because these paths size themselves from EARNINGS,
# and an earnings model that is wrong — or a balance that collapsed while a loop kept running — must not be
# able to empty an account with nobody watching.
#
# SPEND MEANS OUTFLOW, AND AUTO-BOND IS NOT ONE. An earlier revision applied this to auto-bond's
# amount+fee, which was a scoping error with a real consequence: auto-bond takes a percentage of NEWLY
# MINED coins, and for a fresh node new earnings ARE most of the balance — so at a high auto-bond percent
# the ceiling would have silently refused the bond on exactly the nodes trying to reach BOND_CAP, quietly
# turning a 99% setting into ~50%. Bonding moves coins between the owner's own columns and returns after
# the unbond timelock; a fee is gone. So the ceiling governs fees, and auto-bond is governed instead by a
# LIQUIDITY RESERVE: it must leave enough behind to keep paying for things.
AUTO_SPEND_MAX_FRACTION = 2          # 1/2 of the spendable balance


def auto_spend_allowed(balance, committed):
    """True if an unattended path may commit `committed` raw (amount + fee) against `balance` raw."""
    return committed > 0 and balance > 0 and committed <= balance // AUTO_SPEND_MAX_FRACTION


def majority_on_our_canonical(majority_hash, get_block_fn, canonical_hash_at_fn):
    """CORROBORATED DEPTH FINALITY predicate, extracted for direct testing. True when the peer-majority tip
    hash lies ON OUR CANONICAL CHAIN (it is our tip or one of its ancestors — peers lagging a healthy
    producer by a block still corroborate it). False when we don't have that block (we are behind another
    chain) or when we have it only as an orphan (it is on a different fork). The depth-based finality floor
    must only advance under this corroboration: a node producing alone on a minority fork otherwise
    self-finalizes it (max(prev, tip - FINALITY_DEPTH)) and becomes permanently unable to reorg back — the
    partition wedge. Two KV reads; no network."""
    blk = get_block_fn(majority_hash)
    if not blk:
        return False
    return canonical_hash_at_fn(blk["block_number"]) == majority_hash


def _same_network(st, min_protocol):
    """A status only counts toward weight comparisons if the peer speaks OUR protocol. A foreign-protocol
    peer is a DIFFERENT NETWORK (no backward compat on this chain): its chain weight is meaningless here,
    yet before this gate a protocol-2 straggler's heavier dead fork could both steal a re-anchor (observed
    live 2026-07-18: donor 103.236.77.164, protocol 2, snapshot 49000) and suppress our block production.
    Peer ADMISSION already enforces this; these fork-choice inputs must enforce it identically."""
    return st.get("protocol", 0) >= min_protocol


def root_probe_candidates(latest_block, finalized_block, earliest_block):
    """The blocks _root_known_to offers a candidate donor, in dial order. PURE, so the ORDER and the
    MEMBERSHIP can be tested without a fleet — see tests/test_root_probe_candidates.py.

    tip       -> the fast-forward precondition (donor can extend us from our latest hash)
    finalized -> the REORG precondition (donor shares our immutable prefix). Without this a forked node
                 can never select a donor at all: its tip is unknown to the majority BY DEFINITION of
                 being forked, so the reorg leg it needs is unreachable.
    earliest  -> full-sync-from-root, kept last because it is unsatisfiable on a snapshot-bootstrapped
                 network (every peer's history starts above it).

    Falsy entries are dropped, and duplicates are collapsed so a node whose tip IS its finalized block
    costs one dial, not two."""
    out, seen = [], set()
    for block in (latest_block, finalized_block, earliest_block):
        if not block:
            continue
        try:
            key = (block["block_hash"], block["block_number"])
        except (KeyError, TypeError):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(block)
    return out


def reanchor_candidates(peers, statuses, our_weight, floor, min_protocol=None):
    """Weight-selected RE-ANCHOR candidates, extracted for direct testing: (weight, snapshot_height,
    snapshot_hash, ip) for every SAME-PROTOCOL peer advertising a chain STRICTLY heavier than ours whose
    snapshot sits above `floor`. Normal wedge recovery passes the local finality floor; ESCALATED recovery
    (an escalated wedge recovery) passes 0 — any snapshot on the heavier chain
    qualifies, because a floor that keeps pinning us to a lighter chain is itself the fault being
    recovered from."""
    if min_protocol is None:
        from config import get_protocol
        min_protocol = get_protocol()
    cands = [(st["latest_block_weight"], st["snapshot_height"], st["snapshot_hash"], ip)
             for ip, st in zip(peers, statuses)
             if st and st.get("latest_block_weight") is not None
             and st.get("snapshot_hash") and st.get("snapshot_height") is not None
             and _same_network(st, min_protocol)
             and st["latest_block_weight"] > our_weight
             and st["snapshot_height"] > floor]
    # QUORUM, NOT THE BIGGEST INTEGER. latest_block_weight is peer-ASSERTED and unverifiable at this point,
    # so taking max() let ONE responder dictate the checkpoint we adopt wholesale — and the tail we then
    # "re-verify" is verified against the state we just imported from that peer, so balances, the bonded
    # registry and the finality floor all become attacker-defined. Require the same agreement the
    # fresh-joiner path requires: at least SNAPSHOT_MIN_PEERS distinct peers advertising the IDENTICAL
    # (height, hash). Weight only ranks candidates that already have corroboration.
    from ops.snapshot_ops import SNAPSHOT_MIN_PEERS
    try:
        from ops.peer_ops import seed_peers
        seeds = set(seed_peers() or ())
    except Exception:
        seeds = set()
    agree = {}
    for w, h, sh, ip in cands:
        agree.setdefault((h, sh), set()).add(ip)
    # A LONE corroborator is accepted only when it is an operator SEED — the same weak-subjectivity
    # exception snapshot_bootstrap already makes for a lone donor. Without it this deadlocks recovery on a
    # SMALL fleet: with N nodes each node has N-1 peers, so on a 2-node network no (height, hash) can ever
    # reach two distinct advertisers and re-anchor could never fire again — removing the wedge-recovery path
    # entirely and leaving only the drastic purge+resync escape. Requiring 2 ANONYMOUS peers is also weak on
    # its own (an attacker just runs two), so the seed anchor is what actually carries the security here.
    def _ok(key):
        ips = agree[key]
        return len(ips) >= SNAPSHOT_MIN_PEERS or bool(ips & seeds)
    return [c for c in cands if _ok((c[1], c[2]))]


def peer_claims_heavier_tip(statuses, our_weight, have_peers, rejected_tips, min_protocol=None,
                            benched=None):
    """The caught-up production gate's predicate, extracted for direct testing (Sybil-stall guard).
    True (= do NOT mint, we may be behind) when we have peers but no statuses yet, or when any peer
    advertises a strictly heavier tip that is NOT in rejected_tips. A rejected tip is one we already
    tried and failed to sync a valid heavier chain for — counting it would let a Sybil's bogus
    weight advertisement suppress production indefinitely.

    `benched` is the set of TIP HASHES belonging to peers whose whole chain is currently out of fork
    choice (consensus_loop.reject_tip). A long-forked peer still mining publishes a new hash every
    block, so rejected_tips alone — keyed by hash — never catches up with it."""
    if have_peers and not statuses:
        return True
    if benched:
        statuses = [s for s in statuses if s.get("latest_block_hash") not in benched]
    if min_protocol is None:
        from config import get_protocol
        min_protocol = get_protocol()
    return any(s.get("latest_block_weight", 0) > our_weight
               and s.get("latest_block_hash") not in rejected_tips
               and _same_network(s, min_protocol)
               for s in statuses)


def old_block(block):
    """True when the block's committed timestamp is more than a day in the past. Reporting only
    (flags a sync-replayed historical block in produce_block's log) — NOT a validity rule; the
    consensus timestamp check is valid_block_timestamp."""
    if block["block_timestamp"] < get_timestamp_seconds() - 86400:
        return True
    else:
        return False


def isolation_holds(agree, disagree, quorum):
    """True when this node is ALONE among everyone who answered: a real quorum disagrees and NOT ONE peer
    agrees. Deliberately counts only answers — a peer that stayed silent is not evidence of agreement, and
    treating it as such is what let one unreachable peer veto a lone forker's recovery indefinitely."""
    return (not agree) and len(disagree or ()) >= int(quorum)


def isolation_since(prev_since, alone_now, now):
    """Start/keep/clear the continuous-isolation clock. Any single probe that finds an agreeing peer RESETS
    it — the override is meant to fire only on isolation that has held unbroken, so a transient partition
    (which clears within a probe or two) can never accumulate toward it."""
    if not alone_now:
        return None
    return prev_since if prev_since is not None else now


def lighter_than_disagreeing(our_weight, disagree_peers, status_pool):
    """(we_are_strictly_lighter, heaviest_disagreeing_weight) — the dead-fork escape's SYMMETRY BREAKER.

    A purge is only safe if at most ONE side of a split can ever perform it. Quorum cannot decide that: on
    both sides of a 2-2 split a node truthfully sees a majority of its non-self peers disagreeing, so a
    quorum rule tuned to fire on one side fires on both, both wipe, and the fleet ends up on parallel chains
    (observed live 2026-07-28). Weight decides it, exactly as fork choice does everywhere else — the lighter
    side yields and the heavier side stays put.

    STRICTLY lighter, and an unknown peer weight counts as 0 (i.e. not heavier): ties and missing data must
    resolve to "nobody purges". Staying wedged is recoverable on the next probe; a mutual purge is not.
    Pure, so the symmetric case is testable without a node — see tests/test_dead_fork_tiebreak.py."""
    heaviest = 0
    for peer in (disagree_peers or []):
        status = (status_pool or {}).get(peer)
        if not isinstance(status, dict):
            continue
        try:
            heaviest = max(heaviest, int(status.get("latest_block_weight", 0) or 0))
        except (TypeError, ValueError):
            continue                                  # a peer advertising garbage weight is simply unknown
    try:
        ours = int(our_weight or 0)
    except (TypeError, ValueError):
        ours = 0
    return heaviest > ours, heaviest


FORCE_SYNC_MAX_S = 900   # a pinned sync donor is a RECOVERY tool, never a permanent mode
CHECKPOINT_CATCHUP_EVERY = 25   # while advertising NO checkpoint, capture this often (not 1000)


def _dividend_epoch_for(height):
    """The dividend epoch this block accrues, or None. Thin wrapper so the hook reads clearly and the
    boundary arithmetic lives in ONE place (records_bind.epoch_accrual_due), next to the accrual it mirrors."""
    from execnode.stark.records_bind import epoch_accrual_due
    from protocol import EPOCH_LENGTH
    return epoch_accrual_due(height, EPOCH_LENGTH)


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
        self.last_auto_vote_epoch = -1
        # anti-spam backoff for the emergency-mode "Could not find a syncable peer" retry (fires every ~1s
        # while no donor is reachable — a persistent normal state on a lone/bootstrap node).
        self._last_no_syncable_log = 0
        # cooldown for the seed-anchored RE-ANCHOR (wedge recovery): re-importing a seed's snapshot is
        # expensive, so a wedged node attempts it at most once per this interval rather than every ~1s pass.
        self._last_reanchor_ts = 0
        # once-per-new-block throttle for the periodic duties in normal_mode (FFG/RANDAO/auto-*).
        self._last_duty_height = -1
        # DONOR CACHE for get_peer_to_sync_from: (peer, required_hash) of the last selected sync donor.
        # While the donor still advertises the current heaviest hash, it is re-verified with one
        # knows_block dial instead of a full pool re-scan every ~1s emergency pass.
        self._sync_donor = (None, None)
        self._last_sync_donor_ip = None   # donor dialled for THIS attempt; cleared when none qualifies
        self._minority_since = None       # first pass we saw a better-but-unheld tip (grace window)
        # LOG-ONCE guard for _candidate_pool: txids already surfaced as "Candidate excludes…" so the
        # same lingering pool tx (chiefly stale/duplicate RANDAO commit-reveal + attest txs that sit in
        # the mempool until they age out of their epoch window) is not re-logged every candidate pass.
        self._excluded_logged = set()

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

    def _accrual_effects(self, epoch, height, base_effects):
        """Append epoch `epoch`'s presence-dividend accrual to a block's derived records effects.

        Returns (effects, derivable, carry_out). Any missing or refused input yields (None, False, None) —
        the block then rides the bonded quorum, which is always correct, just slower. This must never raise
        into incorporate_block: a settlement optimisation may not be able to stop a block from applying.
        """
        try:
            from execnode.stark.records_bind import dividend_accrual_effects
            from protocol import EPOCH_LENGTH
            if int(epoch) == 0:
                carry_in = 0                      # the first accrual starts from an empty carry
            else:
                prev = kv_ops.exec_summary_get(int(height) - int(EPOCH_LENGTH))
                if not prev or prev.get("dc") is None:
                    return None, False, None      # no chain to continue -> quorum
                carry_in = int(prev["dc"])
            inflow = int(kv_ops.dividend_inflow_get(int(epoch)) or 0)
            from ops.dividend_ops import weights_at_epoch
            weights = weights_at_epoch(int(epoch)) or {}
            eff, carry_out = dividend_accrual_effects(inflow, weights, carry_in)
            return list(base_effects or []) + list(eff), True, int(carry_out)
        except Exception as e:
            self.logger.info(f"dividend accrual not derivable at height {height} (epoch {epoch}): {e} "
                             f"— this block rides the bonded quorum")
            return None, False, None

    def _genesis_cold_start_blocked(self, peers) -> bool:
        """Refuse to mint THE FIRST BLOCK of a chain while we are merely early rather than actually alone.

        This closes the race that split betanet-13 (see protocol.GENESIS_QUIET_S). At a reroll every node
        purges and restarts, but not simultaneously; the first one back finds an empty peer table and, if the
        operator set min_peers = 0, happily mines a solo chain from the shared genesis. Four minutes of head
        start was enough to carry it past the finality depth, after which the split was permanent.

        Every other production gate is blind here BY CONSTRUCTION, which is why this needs its own check:
        peer_claims_heavier_tip cannot find a heavier tip when the whole fleet is at height 0, and the
        min_peers gate is exactly the one an operator turns off to allow solo production.

        The distinction that matters is between "no peers configured" (genuinely standalone — produce) and
        "peers configured, none reached yet" (early — wait). Only height 0 is gated: once a single block
        exists, fork choice and the caught-up gate govern normally and this returns False forever after.

        Bounded by GENESIS_QUIET_S so a truly isolated node is never bricked, only delayed once."""
        try:
            if int((self.memserver.latest_block or {}).get("block_number", 0) or 0) != 0:
                return False                      # the chain has started; this gate is over for good
            from protocol import GENESIS_QUIET_S, GENESIS_QUIET_MIN_PEERS
            from ops.peer_ops import seed_peers
            if len(peers) >= GENESIS_QUIET_MIN_PEERS:
                return False                      # the mesh is up — start together, which is the whole point
            _me = {self.memserver.ip, get_config().get("ip")} - {None}
            if not [p for p in seed_peers() if p not in _me]:
                return False                      # no seeds configured: a standalone node, not an early one
            waited = get_timestamp_seconds() - self.memserver.start_time
            if waited >= GENESIS_QUIET_S:
                self.logger.warning(
                    f"GENESIS QUIET PERIOD expired after {int(waited)}s with {len(peers)} peer(s) — producing "
                    f"the first block anyway. If other nodes are merely slow to restart, this is how a reroll "
                    f"splits; if we really are alone, this is correct.")
                return False                      # never brick a node that is genuinely by itself
            self.logger.info(
                f"genesis quiet period: {len(peers)}/{GENESIS_QUIET_MIN_PEERS} peers after {int(waited)}s of "
                f"{GENESIS_QUIET_S}s — not minting block 1 yet (a reroll restarts nodes minutes apart; the "
                f"node that starts alone builds the fork).")
            return True
        except Exception as e:
            # A gate that throws must not stop block production on a healthy chain.
            self.logger.warning(f"genesis cold-start check failed, allowing production: {e}")
            return False

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
            # ASSIGN ONLY ON CHANGE. The property setter bumps pool_gen, which is the cache key for
            # get_transaction_pool_hash() and get_upcoming_block_hash(). Reassigning unconditionally
            # (twice) on every pass invalidated both caches ~2x/second even when nothing had changed,
            # so neither cache ever hit under load — the exact opposite of their purpose.
            with self.memserver.mempool_lock:
                pool = self.memserver.transaction_pool
                if pool:
                    # ... and (3) EVICT EXPIRED txs (max_block behind the tip) HERE, every pass — not
                    # only after producing a block ourselves. Eviction lived solely on the own-production
                    # path, so a node that rarely wins slots NEVER evicted: measured 2026-08-18 as one
                    # node re-serving an hour-dead claim to the whole fleet every reconcile (and hoarding
                    # 54 expired bonds), a permanent pool-divergence pump.
                    _tip_now = self.memserver.latest_block["block_number"]
                    kept = [t for t in pool if kv_ops.tx_get(t.get("txid")) is None
                            and t.get("max_block", 0) > _tip_now]
                    culled = cull_buffer(buffer=kept, limit=self.memserver.transaction_pool_max_bytes)
                    if len(culled) != len(pool):
                        self.memserver.transaction_pool = culled

            # MEMPOOL CONVERGENCE is handled entirely off this loop now: PUSH gossip delivers a new tx
            # to peers the instant it is accepted (ops/gossip.py, nado._gossip_worker), and the
            # txid-diff pull reconcile (peer_loop -> memserver.merge_remote_transactions) is the ~1s
            # backstop for anything a push missed. The old once-per-block full-pool UNION here
            # (replace_transaction_pool) re-downloaded a divergent peer's whole pool and is retired.

            # PERIODIC DUTIES, throttled to once per NEW BLOCK (audit): they depend only on chain
            # state (epoch windows, registries, balances), which changes exactly when the tip
            # advances — yet they ran every ~1s pass, costing 3+ full account-table scans per second
            # (ffg_finalized + two bonded-registry membership probes) on every node, forever.
            _tip_h = self.memserver.latest_block["block_number"]
            if _tip_h != self._last_duty_height:
                self._last_duty_height = _tip_h
                # FFG (#6): refresh the committee-attested finalized checkpoint.
                self.update_ffg_and_attest()
                # MERGED EPOCH DUTY (doc/consensus-aggregation.md): if we hold a committee seat,
                # one tx carries FFG attest + RANDAO commit/reveal for this epoch.
                self.maybe_epoch_duty()
                # AUTO-BOND (opt-in): unattended-compound a % of newly-mined earnings into bonded stake.
                self.maybe_auto_bond()
                self.maybe_auto_collect()
                self.maybe_auto_register()
                self.maybe_auto_vote()
                # ROLLING MODE (opt-in): on a pruned node, drop block bodies older than the retention window.
                self.maybe_prune_history()
                # ARCHIVE REFILL: advance earliest_block as the background canonical-chain fill (after a
                # re-anchor) lands deeper bodies. The fill thread never writes block_ends itself — that
                # file is core-thread-only — so it reports and this tick commits.
                self._maybe_advance_earliest()
                # ARCHIVE SELF-REPAIR: an archive whose history stops short of genesis fills the gap from a
                # peer that reaches deeper, without waiting for a re-anchor to trigger it.
                self._maybe_refill_archive()
                # CONSERVATION INVARIANTS (ops/invariants.py): supply is a closed system, so any "coins from
                # thin air" bug — the class this codebase has hit ~10 times — must break one of them. Runs
                # in the node so it needs no external step, throttled hard because it scans the account
                # table. LOGS, never halts: a false positive must not stop the chain.
                self.maybe_check_invariants()

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
                # PRODUCTIVE-FORK SELF-CHECK. Everything below reasons about being BEHIND; nothing here ever
                # asked "is the chain I am happily EXTENDING the one everyone else is on?". A node that forks
                # and keeps MINING is invisible to all three recovery routes at once: it is the heaviest tip
                # so minority_block_consensus never reports out-of-consensus, it therefore never enters the
                # emergency loop where _maybe_escape_dead_fork lives, and its tip is never frozen so the
                # escape's stall gate would refuse anyway. Observed live 2026-07-28: 208.87.242.141 forked at
                # h5627 and mined 600+ blocks alone, FFG frozen, for hours — no local route could heal it and
                # an operator had to purge the box by hand. Needing a human IS the defect.
                #
                # The check itself is the existing AUTHORITATIVE one (stranded_below_finality via
                # _maybe_escape_dead_fork): it asks peers DIRECTLY over HTTP for their hash at OUR finalized
                # height — no status pool, no advertised weights, no ffg, none of which a forked or hostile
                # peer can be trusted on. It acts only when a QUORUM disagrees and NOBODY agrees with us, and
                # it is rate-limited to one probe per DEAD_FORK_COOLDOWN_S, so a healthy node pays one cheap
                # probe round per 30 min and exits immediately.
                # DISABLED 2026-07-28, RE-ENABLED the same day once the symmetry was broken. Firing the
                # escape from normal_mode makes every node evaluate it continuously, and DEAD_FORK_QUORUM=2
                # is only half of a 4-node fleet's 3 non-self peers: in a 2-2 split BOTH pairs saw "2
                # disagree, none agree", so BOTH purged, resynced from whichever peer answered first — often
                # each other — and built PARALLEL chains. Observed live: the fleet went from one chain to two
                # sharing only genesis.
                #
                # The escape now requires a THIRD confirmation that the disagreeing majority is strictly
                # HEAVIER than us (see _maybe_escape_dead_fork), so exactly one side of a split can ever
                # purge and a mutual wipe is impossible. That is the precondition this comment used to ask
                # for, and it is a stronger one than a quorum tweak: no quorum value can distinguish the two
                # sides of a symmetric split, because both sides genuinely hold a majority against the other.
                #
                # Without this caller a productive fork is invisible to every recovery route at once — which
                # is exactly what happened next: local and .141 sat on two dead branches for hours on
                # 2026-07-28 with a perfectly correct probe (stranded, 2 disagree, 0 agree) that nothing was
                # allowed to act on. Needing a human IS the defect.
                if self._maybe_escape_dead_fork():
                    return
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
                    rejected_tips=self.consensus.rejected_tips,
                    benched=self._benched_tip_hashes())

                # MINORITY-FORK PRODUCTION GATE. The heavier-tip gate above cannot see the fork case that
                # actually persists: production is DETERMINISTIC (same winner both sides, different tx set),
                # so after a mempool split BOTH branches advance every slot at near-equal weight — neither
                # side ever sees "heavier", and both extend their forks for hours (observed 2026-08-17/18,
                # splits at 62655 and 62895). The measured verdict CAN see it, so never extend a branch it
                # says is not the majority's.
                #
                # Cost discipline: the verdict walk is ~40 hash probes, so it must never run on the healthy
                # path. Trigger only when the peer majority's tip hash differs from OURS (gossip, free) and
                # that mismatch has PERSISTED (same 5 s hysteresis as minority_block_consensus — every block
                # boundary mismatches for the propagation second). Then consult the cached verdict:
                # POSITIVE evidence only — REORG/DEAD_FORK suppresses this slot; UNKNOWN/BEHIND never block
                # production (ignorance must not halt a partitioned node, and the probe's seeds-first
                # headcount resolves an even split toward the seeded side). Per-node suppression cannot
                # stall the network: production is replicated — any node on the majority branch builds the
                # identical canonical block.
                _maj_hash = self.consensus.majority_block_hash
                _on_minority = False
                if _maj_hash and _maj_hash != self.memserver.latest_block["block_hash"]:
                    _now_g = get_timestamp_seconds()
                    if getattr(self, "_prod_minority_since", None) is None:
                        self._prod_minority_since = _now_g
                    elif _now_g - self._prod_minority_since >= MINORITY_GRACE_S:
                        _vs = self._fork_state()
                        _tie_ours = (int(self.consensus.heaviest_block_weight or 0) == int(
                                         self.memserver.latest_block.get("cumulative_weight", 0))
                                     and self._tie_break_ours(_maj_hash) is True)
                        if _vs in (fork_resolution.REORG, fork_resolution.DEAD_FORK) and not _tie_ours:
                            _on_minority = True
                            if _now_g - getattr(self, "_last_minority_suppress_log", 0.0) >= _EMERGENCY_LOG_EVERY:
                                self._last_minority_suppress_log = _now_g
                                self.logger.warning(f"Production suppressed: measured fork state is {_vs} — "
                                                    f"refusing to extend a minority branch")
                else:
                    self._prod_minority_since = None

                # min_peers == 0 enables SOLO production (a single node mints without a peer mesh) —
                # used for a stable single-node relay/demo where multi-node fork-choice churn is undesirable.
                #
                # POOL WARM-UP GATE: a freshly restarted node's pool is EMPTY, and deterministic
                # production turns "my pool differs" straight into a same-height fork — every deploy
                # wave seeded forks this way (blob h67007, bond h68376, duty h68345, all restart-window).
                # Don't mint until the pool has reconciled once with a peer (peer_loop sets pool_warmed
                # after its first completed merge_remote_transactions pass). Liveness-safe: warmed is
                # forced True when there are no peers to reconcile with (solo mode) or 60 s after start
                # (a mute mesh must not stall a producer forever).
                if (not self.memserver.pool_warmed
                        and (not peers or self.memserver.get_uptime() > 60)):
                    self.memserver.pool_warmed = True
                    if peers:
                        self.logger.warning("Pool warm-up window expired unreconciled — producing anyway")
                if (len(peers) >= self.memserver.min_peers
                        and not self._genesis_cold_start_blocked(peers)
                        and not self.memserver.force_sync_ip
                        and self.memserver.pool_warmed
                        and not _on_minority):
                    block_candidate = get_block_candidate(logger=self.logger,
                                                          transaction_pool=self._candidate_pool(),
                                                          latest_block=self.memserver.latest_block
                                                          )

                    # S4.3: get_block_candidate returns None when no bonded identity is eligible
                    # (empty registry / total_shares == 0). Skip this round rather than crash.
                    #
                    # DETERMINISTIC FAST-FORWARD (fixes block gaps >> block_time on a healthy multi-producer
                    # mesh): production is byte-identical across nodes — same parent + same mempool -> same
                    # block_hash (the timestamp is OUTSIDE the hashed preimage). So being one block behind a
                    # peer does NOT require fetching that block: we can rebuild it. The old gate refused to
                    # mint whenever ANY peer advertised a heavier tip (_peer_ahead), so nodes serialised on
                    # each other's tips and the network crawled at propagation speed instead of the block_time
                    # pacing. Now: when a peer is ahead we still build the next block, and if its hash matches
                    # a tip a peer already advertises it IS the canonical next block — incorporate our own
                    # identical copy (no fetch). Only when our build matches NO advertised tip (genuine
                    # mempool divergence, or we are >1 block behind) do we hold off and let emergency sync
                    # fetch the canonical chain — so fork-safety is unchanged.
                    if block_candidate is not None:
                        behind = _peer_ahead and block_candidate["block_hash"] not in \
                            set(self.consensus.block_hash_pool.copy().values())
                        if behind:
                            # can't reconstruct the canonical tip from our own mempool -> defer to sync
                            self.logger.debug("Behind on an un-reconstructable tip; deferring to sync")
                        else:
                            # #15 step 5: sign only when LEADING (not _peer_ahead). If WE are the selected
                            # winner, attach the detached authorship signature; a relay (or a fast-forward
                            # catch-up copy) leaves it unsigned — still valid (win-offline). Not signing a
                            # fast-forward copy avoids any same-height authorship edge case while behind.
                            if (not _peer_ahead
                                    and self.memserver.address == block_candidate["block_creator"]
                                    and block_candidate["block_number"] > self.last_signed_height):
                                sign_block(block_candidate, self.memserver.private_key, self.memserver.public_key)
                                self.last_signed_height = block_candidate["block_number"]
                            self.produce_block(block=block_candidate,
                                               remote=False,
                                               remote_peer=None)

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

    def _finalized_block_ref(self):
        """{block_hash, block_number} at our finality floor, or None. Our immutable prefix — the one part
        of our chain that ANY peer we could legitimately reorg toward must also carry."""
        try:
            from ops.block_ops import get_block_hash_by_number
            h = int(self.memserver.finalized_height)
            if h <= 0:
                return None
            bh = get_block_hash_by_number(h)
            return {"block_hash": bh, "block_number": h} if bh else None
        except Exception:
            return None

    def _root_known_to(self, peer) -> bool:
        """the ONE network check of donor selection: can this peer actually serve us blocks?

        It asks first about the block the sync leg will ask FROM — our TIP — because that is the
        precondition _fast_forward_from documents ("the donor knows our tip, so pull the gap from it"):
        get_blocks_after is keyed off our latest hash, so a donor carrying our tip on ITS canonical chain
        can extend us.

        It used to probe our EARLIEST block instead, which is unsatisfiable on a snapshot-bootstrapped
        network and wedged this node in a re-anchor loop: after a re-anchor our earliest is whatever the
        body backfill reached (a couple of hundred blocks behind the snapshot), and the other peers are
        snapshot-bootstrapped too, so none of them has a body that deep. Every donor failed the gate ->
        "ran out of options" -> "wedged behind a heavier chain" -> re-anchor to the same snapshot ->
        repeat, parked at one height while the chain moved on.

        OUR FINALIZED BLOCK IS THE MIDDLE FALLBACK, and it is what makes a REORG donor selectable at all.
        The tip probe is a FAST-FORWARD precondition, but the reorg leg is DEFINED by the donor not knowing
        our tip (_rollback_one_for_reorg: "the donor does NOT know our tip, so our chain has diverged").
        So on a genuine fork the tip probe must fail, and if earliest is also unsatisfiable the gate
        excludes precisely the donors the reorg needs — donor selection returns None, and the node never
        rolls back even one block. Measured on betanet-15 2026-08-03: 185.100.232.131 forked at h=7143 and
        sat 431 blocks behind for over an hour with its height rising monotonically and never once dropping.
        Its tip was unknown to the majority (it was forked) and its earliest block (2735) was below the
        majority's snapshot-bootstrapped history, so every donor failed and no rollback was ever attempted.

        Accepting a donor that holds our FINALIZED block is the right criterion for that leg: the finality
        floor is immutable on our side, so any chain we may legitimately reorg onto contains it, and
        knows_block checks CANONICALITY (height -> hash on the peer's own chain) — a donor whose chain does
        NOT contain our immutable prefix still answers False. So this accepts strictly more donors than
        before, never fewer, and the "donor knows a tip it cannot extend" bait the gate exists to stop
        remains closed. Ordering is cost discipline: a healthy node matches on the tip and never dials
        the rest."""
        def _knows(block):
            if not block:
                return False
            try:
                return asyncio.run(knows_block(
                    target_peer=peer, port=self.memserver.port,
                    hash=block["block_hash"], number=block["block_number"], logger=self.logger))
            except (KeyError, TypeError):
                return False
        for block in root_probe_candidates(self.memserver.latest_block,
                                           self._finalized_block_ref(),
                                           self.memserver.earliest_block):
            if _knows(block):
                return True
        return False

    def _fetch_sync_batch(self, peer, from_hash):
        """pull one forward-sync batch (up to SYNC_BATCH_MAX blocks after from_hash) from the donor.
        Falsy on ANY failure — never raises, so it is safe to run in the emergency loop's prefetch
        thread (asyncio.run spins a private event loop per call, thread-safe)."""
        try:
            batch = asyncio.run(get_blocks_after(
                target_peer=peer,
                from_hash=from_hash,
                count=SYNC_BATCH_MAX,
                logger=self.logger))
            # RECORD HOW FAR THE CHAIN IS KNOWN TO REACH. This is the only honest source of "is the block
            # I am about to apply DEEP?": every measure derived from local state is ~0 during a sequential
            # sync, because the node's own tip IS the block it is applying. A fetched batch proves chain
            # exists above its own tail, so its tail height is a lower bound on the real tip — which is
            # exactly what the depth gate on settle-proof verification needs (protocol.SETTLE_PROOF_DEPTH_GATED).
            try:
                if batch:
                    top = max(int(b["block_number"]) for b in batch)
                    if top > getattr(self, "_known_tip_height", 0):
                        self._known_tip_height = top
            except Exception:
                pass                                   # a malformed batch is the caller's problem, not ours
            return batch
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

    def _clear_sync_donor(self):
        """Forget the donor we dialled. MUST run whenever selection yields none, or _last_sync_donor_ip
        keeps a STALE ip from an earlier cycle: reject_tip would then filter holders to a peer that does
        not hold the current tip, holders becomes empty, and NOBODY is struck — silently reintroducing the
        wedge where a lone stale forker owns the donor pool and never accumulates strikes."""
        self._last_sync_donor_ip = None

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
            # #16 step 3: sync toward the OBJECTIVELY heaviest advertised tip (by cumulative_weight,
            # lowest-hash tie-break), NOT the most-advertised one (which a Sybil peer-set could
            # dominate). tip_weights includes our own tip. We only ever target the single canonical
            # (heaviest) tip — syncing toward a lighter, non-canonical tip would contradict fork-choice.
            distinct_hashes = [h for h in set(source_pool_copy.values()) if h is not None]

            # (no "No hashes to sync from" log here: it fires every ~1s core-loop pass whenever no peer has
            # advertised a tip — a persistent normal WAITING state on a lone/bootstrap node, already visible
            # in the periodic status line. When empty we just fall through and return None.)
            if not distinct_hashes:
                return None
            heaviest_hash = min(distinct_hashes,
                                key=lambda h: (-self.consensus.tip_weights.get(h, -1), h))

            # DONOR CACHE: reuse the previously selected donor while it still advertises the current
            # heaviest hash and passes the in-memory gate. Liveness is NOT assumed — the root-knowledge
            # dial re-runs (one round-trip), so a died-since donor falls through to a fresh scan instead
            # of being handed to emergency_mode, where a false knows_block(tip) would suggest a reorg.
            cached_peer, cached_hash = self._sync_donor
            if cached_peer is not None and cached_hash == heaviest_hash:
                if (self._donor_gate_passes(cached_peer, heaviest_hash, source_pool_copy)
                        and self._root_known_to(cached_peer)):
                    return cached_peer
                self._sync_donor = (None, None)

            for peer in shuffle_dict(source_pool_copy):
                if not self._donor_gate_passes(peer, heaviest_hash, source_pool_copy):
                    continue

                # in-memory gate passed -> the single network check (can this donor serve our root?)
                try:
                    if self._root_known_to(peer):
                        if peer != cached_peer:
                            self.logger.info(f"Selected sync donor {peer} for tip {heaviest_hash[:12]}")
                        self._sync_donor = (peer, heaviest_hash)
                        self._last_sync_donor_ip = peer   # attribute a later fetch failure to THIS peer
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
        # AUDIT FIX (same-length fork wedge): heaviest_block_hash is the GLOBAL best tip by
        # (cumulative_weight DESC, block_hash ASC) over all advertised tips INCLUDING our own. The old
        # code switched only on strictly-GREATER weight, so two honest tips at the same height (equal
        # content-independent weight, different hash) wedged forever. Switch whenever the canonical tip
        # is not ours — i.e. it is heavier, OR equal-weight with a lower hash (the deterministic
        # tie-break every node computes identically, so they all converge on the lowest-hash tip).
        if hh == self.memserver.latest_block["block_hash"]:
            """our tip IS the canonical (heaviest weight, lowest-hash tie-break) -> do not switch"""
            self._minority_since = None
            return False
        if get_block(hh):
            """we already hold the canonical tip locally; normal incorporation adopts it"""
            self._minority_since = None
            return False
        # STABLE TIE-BREAK (equal weight). Weight increments are content-independent, so a same-height
        # split is a PERMANENT exact tie — and the lowest-TIP-hash rule below the grace window re-rolled
        # every block, flipping which side should switch faster than any reorg could finish (the
        # hours-long see-saws at 62655/62895). Resolve ties at the FIRST DIVERGENT block instead
        # (_tie_break_ours): permanent, computed identically by both sides, so exactly one side switches.
        # True -> our branch is canonical: never switch. None (no evidence) -> don't switch either, but
        # keep the grace timer running so evidence arriving later acts immediately. False -> fall through
        # to the grace window and switch.
        if int(self.consensus.heaviest_block_weight or 0) == int(
                self.memserver.latest_block.get("cumulative_weight", 0)):
            _tb = self._tie_break_ours(hh)
            if _tb is True:
                self._minority_since = None
                return False
            if _tb is None:
                if self._minority_since is None:
                    self._minority_since = get_timestamp_seconds()
                return False
        # GRACE WINDOW — the fork-choice above is right, but "a better tip exists that we do not hold yet"
        # is ALSO what every normal block looks like for the second between a peer advertising it and the
        # gossip delivering it. Without hysteresis that transient reads as a fork: measured 51 emergency
        # entries an hour on a healthy 2-node fleet, each one "We are out of consensus" -> "Entering
        # emergency mode" -> "No heavier valid tip remains" ~1s later, with ZERO actual rollbacks and the
        # chain advancing at block time the whole time. Pure noise that buried real events and, per the
        # h4260 post-mortem, rollback storms are the one thing that has actually corrupted state here.
        #
        # A genuine fork persists, so a few seconds of patience costs nothing; propagation lag resolves
        # itself. Safe to defer because returning False does NOT make us mint: normal_mode's caught-up
        # gate independently refuses to produce while any peer advertises an unrejected heavier tip, so
        # during the grace we simply wait for the block instead of tearing down into sync/reorg.
        now = get_timestamp_seconds()
        if self._minority_since is None:
            self._minority_since = now
            return False
        if (now - self._minority_since) < MINORITY_GRACE_S:
            return False
        """a strictly-better tip (heavier, or equal-weight + lower hash) has PERSISTED -> sync toward it"""
        return True

    def snapshot_bootstrap(self, force_reanchor: bool = False, allow_below_floor: bool = False) -> bool:
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
        is simply orphaned in the block store — never referenced.

        allow_below_floor=True (reserved for operator recovery; the fork-state machine never sets it,
        consecutive failed attempts): the heavier chain's advertised snapshots all sit BELOW our finality
        floor — the exact geometry that used to wedge a node for as long as the donors' snapshot cadence
        lagged (observed live: a self-finalized minority fork pinned until a peer crossed the floor ~25 min
        later). A wedge that persists across multiple weight-selected attempts proves the floor itself is on
        a minority fork, so the floor restriction is dropped: weight is the only objective ordering left
        (under partition even FFG is subjective — the inactivity leak lets each side quorum its own branch).
        Every tail block after the import is still fully re-verified, so a fabricated weight hint cannot be
        extended into an accepted chain."""
        if self.memserver.latest_block["block_number"] != 0 and not force_reanchor:
            return False   # genesis-only for normal bootstrap; force_reanchor re-anchors an established node
        try:
            # AN ARCHIVE NODE MUST NOT SHORTCUT ITS WAY PAST THE HISTORY IT EXISTS TO KEEP.
            #
            # A fresh bootstrap backfills only REWARD_WINDOW + 2*EPOCH_LENGTH + FINALITY_DEPTH bodies behind
            # the anchor and nothing older, ever. Taking it with archive=true produces a node that keeps
            # everything from its snapshot FORWARD, holds nothing before it, and advertises node_type
            # "archive" to peers that read that as "can serve history". Convenient, and a lie — and the
            # operator has no reason to suspect it, because the node syncs fast and looks healthy.
            #
            # `archive: true` is an explicit, deliberate setting. Honour it: refuse the shortcut and say
            # what a real archive costs. This is deliberately NOT the default posture — rolling nodes take
            # the snapshot path as before, which is the whole point of having it.
            if getattr(self.memserver, "archive", False) and not force_reanchor:
                self.logger.error("=" * 78)
                self.logger.error("ARCHIVE NODE: REFUSING SNAPSHOT BOOTSTRAP.")
                self.logger.error("  A snapshot carries STATE, not history — this node would start with a")
                self.logger.error("  few hundred blocks of bodies and never obtain the chain before them,")
                self.logger.error("  while telling peers it is an archive. That is not an archive.")
                self.logger.error("  For a true archive, either:")
                self.logger.error("    * sync from genesis (leave it running; it needs a peer that still")
                self.logger.error("      serves deep bodies — rolling nodes do not), or")
                self.logger.error("    * copy an existing archive node's data directory, or")
                self.logger.error("    * set \"archive\": false to run as a rolling node instead.")
                self.logger.error("=" * 78)
                return False

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
            # CHAIN-ID GATE: a peer on a DIFFERENT chain must NEVER be a snapshot / re-anchor donor. A node
            # stranded on a prior generation (after a reroll) advertises a valid-looking, much-heavier
            # snapshot from its OLD chain; without this a fresh node adopts that cross-chain snapshot
            # (mislabelled as ours) and ends up with a broken store — tip set, zero block bodies. chain_id is
            # informational for block LINKAGE, but it IS the network's identity, so a donor whose chain_id
            # isn't ours is dropped BEFORE any quorum / weight selection — the same gate the sync-donor path
            # already applies ("Chain of X is not <ours>"). Observed live during the betanet-11 reroll: a
            # stranded seed on betanet-10 poisoned a fresh node's bootstrap to a phantom 6000-block tip.
            statuses = [s if (isinstance(s, dict) and s.get("chain_id") == CHAIN_ID) else None for s in raw]
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
                # TWO-FLOOR: the re-anchor floor is the HARD floor, escalated or not. A snapshot below the
                # depth floor but above the quorum floor is a legal landing point — that geometry used to
                # force escalation, which then passed 0 and could cross ANY floor, which is how archives got
                # truncated and the exec layer stranded. Crossing the hard floor is never recovery: it would
                # adopt a chain conflicting with a checkpoint a >2/3 bonded quorum signed — joining an
                # equivocation. When FFG has not finalized yet, hard is 0 and this degenerates to the old
                # escalated behaviour; `allow_below_floor` survives only as the escalation LABEL.
                floor = get_hard_finality()
                cand = reanchor_candidates(peers, statuses, our_weight, floor)
                if not cand:
                    self.logger.info("Re-anchor: no peer advertises a strictly-heavier chain with a snapshot "
                                     f"above {'the HARD floor (ESCALATED)' if allow_below_floor else 'our finality floor'};"
                                     " staying put")
                    return False
                # RANK BY CORROBORATION, NOT BY THE UNVERIFIED NUMBER. latest_block_weight is peer-asserted
                # and unverifiable here, so max() let an attacker echo a seed's real (height, hash) with a
                # fabricated 10**30 weight and thereby choose BOTH when we re-anchor and whom we fetch from.
                # Prefer a seed as the source, then the most-corroborated (height, hash), then weight.
                try:
                    from ops.peer_ops import seed_peers as _sp
                    _seeds = set(_sp() or ())
                except Exception:
                    _seeds = set()
                _support = {}
                for _w, _h, _sh, _ip in cand:
                    _support.setdefault((_h, _sh), set()).add(_ip)
                _, target_height, target_hash, source = max(
                    cand, key=lambda c: (c[3] in _seeds, len(_support[(c[1], c[2])]), c[0]))
                if allow_below_floor and target_height <= self.memserver.finalized_height:
                    self.logger.warning(f"ESCALATED re-anchor: crossing the local finality floor "
                                        f"{self.memserver.finalized_height} down to snapshot height "
                                        f"{target_height} — local floors were on a minority fork")
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
                agreed = snapshot_ops.agree_snapshot(
                    statuses, min_peers=(1 if lone_donor else snapshot_ops.SNAPSHOT_MIN_PEERS), threshold=0.8,
                    seed_ips=peers)   # aligned with `statuses`; lets the quorum require seed corroboration
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

            # 3) PROBE BEFORE COMMIT: the donor must prove it can EXTEND its own snapshot before we
            # touch ANY local state — serve the anchor block AND at least one block after it. A donor
            # advertising a checkpoint it cannot extend (a dead fork's snapshot — the live wedge that
            # pinned a fresh joiner at 13000) is refused while our current identity is fully intact,
            # so a poisoned or inconsistent donor can never trade our working state for a dead end.
            anchor = asyncio.run(
                snapshot_ops.fetch_block(source, self.memserver.port, manifest["block_hash"]))
            if (not anchor or anchor.get("block_hash") != manifest["block_hash"]
                    or anchor.get("block_number") != target_height):
                self.logger.warning("Snapshot donor cannot serve its own checkpoint block; refusing pre-import")
                return False
            if not asyncio.run(get_blocks_after(target_peer=source, from_hash=anchor["block_hash"],
                                                count=1, logger=self.logger)):
                self.logger.warning("Snapshot donor cannot extend its own checkpoint (no block after the "
                                    "anchor) — dead-end snapshot refused pre-import")
                return False

            # CAPTURE OUR OWN CHAIN'S INDEX BEFORE IT IS REPLACED. import_snapshot drops block_by_num /
            # block_by_hash and repopulates them from the donor's payload, and that payload is WINDOWED
            # ([C-INDEX_RETENTION_NUM, C]) — so an archive's deep index would be gone after this line, from
            # any donor. It is also how the canonical restore below finds the fork point (where old and
            # new agree) and re-derives every deep row the import throws away. Cheap: 144 B/height.
            _old_index = dict(kv_ops.block_by_num_items())

            # 4) COMMIT: replace the carried consensus state. import_snapshot verifies every chunk
            # sha256 + the re-derived state_root BEFORE its write txn, so a failure here still leaves
            # the old identity fully intact.
            if not snapshot_ops.import_snapshot(manifest, chunks, logger=self.logger):
                return False

            # ...and retire the abandoned identity: every artifact NOT carried by the snapshot dies
            # with the chain it described (tx history, GC reverts, our own checkpoints) — EXCEPT block
            # bodies, which are reconciled against the adopted chain just below rather than wiped, because
            # most of them are the canonical chain itself. See adopt_new_identity and ops/canonical_restore.
            snapshot_ops.adopt_new_identity(logger=self.logger)

            save_block(anchor, logger=self.logger)
            set_latest_block_info(latest_block=anchor, logger=self.logger)
            self.memserver.latest_block = anchor

            # import_snapshot overwrote the persisted finality floor with the donor's, but the in-memory copy
            # was left at its genesis-time value (0). Refresh it so incorporate_block computes the next floor
            # from the real base and /status stops advertising finalized_height=0 until the first tail block.
            self.memserver.finalized_height = get_finalized_height()

            # (The old HISTORY-INDEX PURGE (2026-07-16 wedge fix) and pre-reanchor CHECKPOINT drop that
            # lived here are both subsumed by adopt_new_identity above: nothing of the abandoned chain
            # survives the identity change, so there is nothing left to purge case by case.)

            # CANONICAL-CHAIN RESTORE (ops/canonical_restore). The fork that forced this was above the
            # finality floor, so every block below the fork point is COMMON to both chains — the majority
            # chain's own history, which we were serving a minute ago. It is kept, not re-fetched: a body's
            # hash covers its bytes, so a body on the adopted chain IS vouched for by the new identity. Fork
            # bodies are unreferenced. Deep index rows the windowed import dropped are re-put. What is
            # canonical and absent is fetched from the donor: ALL of it on an archive node (an archive must
            # come out of recovery with every canonical block it went in with — and, if it was truncated
            # before, this is where it gets its history back), the rollback window on a rolling one.
            try:
                oldest = self._restore_canonical_chain(_old_index, anchor, source)
            except Exception as e:
                # The identity has already changed above; a fault here must not leave the node without an
                # earliest pointer or wedge the recovery. Fall back to "history from the anchor" — no worse
                # than the old behaviour, and the retained bodies are still there for the periodic archive
                # refill (_maybe_refill_archive) to reconcile on its next pass.
                self.logger.error(f"Canonical restore failed ({e}); history pointer set to the anchor and the "
                                  f"archive refill will retry")
                oldest = anchor
            set_earliest_block_info(earliest_block=oldest, logger=self.logger)
            self.memserver.earliest_block = oldest

            # RE-PUBLISH the snapshot we just adopted as OUR OWN checkpoint, immediately.
            #
            # adopt_new_identity() drops every checkpoint (they described the abandoned chain), and new
            # ones are only written at CHECKPOINT_INTERVAL boundaries — so a node that re-anchors
            # advertises NO snapshot for up to a full interval. If that node is on the heaviest chain,
            # nobody can re-anchor ONTO it, and the network cannot converge on the chain fork-choice
            # actually wants: observed live with the heaviest peer sitting at snapshot_height=None while
            # every other node bounced between the lighter forks that did publish one.
            #
            # We just fetched, verified and materialised exactly this state, so we can serve it onward
            # at zero cost. Best-effort: failing to re-publish costs future donors a target, never this
            # node's own sync.
            try:
                snapshot_ops.persist_checkpoint(height=target_height, block_hash=anchor["block_hash"],
                                                protocol=self.memserver.protocol,
                                                version=self.memserver.version)
                self.logger.warning(f"Re-published the adopted snapshot as our own checkpoint at "
                                    f"{target_height} — this node can now be re-anchored to")
            except Exception as e:
                self.logger.error(f"Could not re-publish the adopted checkpoint (non-fatal): {e}")
            # (NameError regression 2026-08-18: this line referenced a variable deleted in a refactor,
            # so the except below treated every SUCCESSFUL bootstrap as failed and full-synced instead.)
            self.logger.warning(f"Snapshot bootstrap complete at height {target_height}; "
                                f"history floor {oldest}; replaying tail")
            return True

        except Exception as e:
            self.logger.error(f"Snapshot bootstrap failed, falling back to full sync: {e}")
            return False

    def _depth_floor_corroborated(self) -> bool:
        """Whether the depth-based finality floor may advance right now: the visible network's majority tip
        must lie ON OUR CANONICAL CHAIN (majority_on_our_canonical — our tip or a recent ancestor of it,
        so peers lagging a healthy producer by a block still corroborate). No peers reporting = solo /
        bootstrap: nothing to disagree with, advance as before. A Sybil can only WITHHOLD corroboration
        (delaying our floor — the safe direction, it merely widens the honest-reorg window); it can never
        use this to force a floor onto a fork."""
        pool = self.consensus.block_hash_pool
        if not pool:
            return True
        # THE OBJECTIVE TIP, NOT THE PLURALITY. This used to consult `majority_block_hash`, which
        # consensus_loop.py itself documents as "the Sybil-swingable plurality … replaced [for] the BLOCK
        # chain [by] OBJECTIVE heaviest-cumulative_weight fork-choice … (Plurality is kept for the tx-pool /
        # block-producer pools, WHICH ARE NOT THE CHAIN FORK-CHOICE)". Whether our chain may finalize is a
        # chain decision, so it had no business reading the one signal peer IPs can swing.
        #
        # What that cost, observed live on 2026-07-20: seven peers advertising seven DISTINCT tips, six of
        # them on chains we do not even hold blocks for. "Majority" was therefore a ONE-VOTE plurality (14%)
        # belonging to a peer on a foreign chain, so corroboration failed and this node's finality floor sat
        # frozen for hours while its tip advanced normally — and any single peer could have done that to any
        # node, deliberately, by advertising a tip nobody shares.
        #
        # `heaviest_block_hash` is the right input and needs no new machinery: it is argmax over
        # cumulative_weight, it already EXCLUDES rejected tips and benched peers, and it always includes our
        # own tip. The guard's purpose survives intact — a node alone on a minority fork still sees a
        # strictly heavier foreign chain as heaviest and still refuses to self-finalize — while a lone forker
        # advertising an unobtainable heavier tip is benched out of the computation, exactly as fork choice
        # already treats it.
        heaviest = self.consensus.heaviest_block_hash
        if not heaviest:
            return True
        if not majority_on_our_canonical(heaviest, get_block, get_block_hash_by_number):
            return False
        # SOMEONE ELSE HAS TO SAY IT. The check above asks "is the heaviest tip on our chain", and for a node
        # ALONE ON A FORK the answer is trivially yes — it mines every slot unopposed, so its own tip IS the
        # heaviest and it corroborates itself. That is precisely the wedge this predicate exists to prevent,
        # and it failed open in exactly that case.
        #
        # Observed live, betanet-13 h5924 (2026-07-29): .131 built a block for the same winner, same parent,
        # same state_root, 4s earlier and without a blob tx whose min_block was that very height. It then
        # mined alone, stayed heaviest, corroborated its own depth floor up to 5974 — 50 blocks PAST the fork
        # — and became unable to roll back and rejoin. The other three had the same fork point below their
        # floor too, so nothing could reorg and the only exit left was the data-destroying dead-fork purge.
        # Had the floor stayed below 5924 on the isolated side, that node could simply have rolled back and
        # resynced the 3-node chain: a plain reorg, no purge, no lost chain data.
        #
        # So corroboration now means what the word means — an INDEPENDENT peer advertising a tip on our
        # canonical chain. Our own tip is not evidence about our own tip.
        #
        # Failing this only FREEZES the floor, which is the safe direction (it widens the honest-reorg
        # window and nothing else), and a Sybil could already achieve that by withholding corroboration.
        # HEAVIER-FOREIGN-CLAIM VETO (2026-07-30, restored + hardened; complements the independence rule
        # below, it does not replace it). Independent corroboration stops a LONE forker self-finalizing,
        # but a minority CLIQUE corroborates itself: two nodes on the same lighter branch each advertise
        # an on-chain tip for the other, so both floors advance — observed live on betanet-14 while the
        # strictly-heavier solo chain sat plainly advertised in their status pools (~92k vs ~65k weight),
        # cementing 60+ blocks of a branch fork choice says must lose. Any peer claiming strictly MORE
        # cumulative weight on a tip that is not on our canonical chain — or whose tip we cannot even
        # locate this pass (the pools refresh on different cadences; an unanswerable heavier claim is the
        # LEAST corroborated case, not a pass) — freezes the floor. Freezing is the safe direction; a
        # liar merely delays our finality and its tip re-benches on the next failed fetch.
        _our_w = int((self.memserver.latest_block or {}).get("cumulative_weight", 0) or 0)
        for _peer, _w in (self.consensus.weight_pool or {}).copy().items():
            if not isinstance(_w, int) or _w <= _our_w:
                continue
            _t = self.consensus.block_hash_pool.get(_peer)
            if _t is None or not majority_on_our_canonical(_t, get_block, get_block_hash_by_number):
                return False
        _me = {self.memserver.ip, get_config().get("ip")} - {None}
        for _peer, _hash in self.consensus.block_hash_pool.copy().items():
            if _peer in _me or not _hash:
                continue
            if majority_on_our_canonical(_hash, get_block, get_block_hash_by_number):
                return True
        return False

    def _fork_state(self):
        """Measured fork state (ops/fork_resolution.resolve), cached for FORK_STATE_TTL_S.

        Costs ~log2(depth) direct peer probes, so it is NOT run every pass — but it is the only input here
        that cannot be blinded the way consensus.status_pool can (a collapsed peer set or a wrong bench).
        Returns UNKNOWN on any failure, which every caller must treat as "change nothing"."""
        from protocol import FORK_STATE_TTL_S
        try:
            now = get_timestamp_seconds()
            cached = getattr(self, "_fork_state_cache", None)
            if cached and now - cached[0] < FORK_STATE_TTL_S:
                return cached[1]["state"]
            from ops.peer_ops import seed_peers, probe_block_hash_signed
            from ops.block_ops import get_block_hash_by_number
            from ops.account_ops import get_finalized_height
            # SEEDS FIRST. The verdict here is a per-IP headcount (fork_resolution.majority_hash), and it
            # gates the re-anchor path — so if attacker-held slots crowd the operator seeds out of the [:8]
            # window they dictate the verdict. memserver.peers came first, so on a node with >=8 peers the
            # seeds were sliced off entirely. _maybe_escape_dead_fork already orders seeds first; match it.
            # NEVER PROBE OURSELVES. This node's config ip can BE a seed (it is: 38.242.201.206 is
            # DEFAULT_SEED_PEERS[0]), so seeds-first would otherwise guarantee our own IP in slot 0 — we
            # would answer our own fork-state question with our own hash and count it in the tally.
            # ops/peer_ops.py:285 already applies exactly this carve-out to the dial set; mirror it here.
            _me = {get_config().get("ip")} - {None}
            peers = [p for p in dict.fromkeys(list(seed_peers()) + list(self.memserver.peers))
                     if p not in _me][:8]
            if not peers:
                return fork_resolution.UNKNOWN
            tip = self.memserver.latest_block["block_number"]
            # HARD floor, not depth (two-floor model): classify() calls a fork DEAD (unrecoverable by
            # rollback) only below what rollback actually refuses to cross. Using the depth floor here is
            # what turned every >45-block fork into a floor-crossing "wedge recovery"; above the hard floor
            # the verdict is now REORG and the ordinary rollback leg handles it.
            from ops.account_ops import get_hard_finality as _ghf
            verdict = fork_resolution.resolve(
                our_hash_at=get_block_hash_by_number,
                tip=tip, finalized=_ghf(), peers=peers,
                probe=lambda peer, h: self._memo_probe(peer, h, tip))
            self._fork_state_cache = (now, verdict)   # FULL verdict: the reorg leg needs the ancestor too
            self.logger.info(f"Fork state: {verdict['state']} (ancestor={verdict['ancestor']}, "
                             f"tip={tip}, probes={verdict['probes']})")
            return verdict["state"]
        except Exception as e:
            self.logger.warning(f"fork-state probe failed: {e}")
            return fork_resolution.UNKNOWN

    def _fork_verdict(self):
        """The full measured verdict {state, ancestor, ...} behind _fork_state(), same cache. The reorg
        leg is gated on this rather than on one donor's word — see emergency_mode."""
        state = self._fork_state()
        cached = getattr(self, "_fork_state_cache", None)
        if cached and isinstance(cached[1], dict):
            return cached[1]
        return {"state": state, "ancestor": None}

    def _rec_fail(self, why, **detail):
        """Like _rec but PERSISTENT: failures land in their own /status field ("recovery_fail") that the
        phase stream does not overwrite — a failure frame lived ~3 s before the next phase clobbered it,
        unpollable from outside."""
        try:
            self.memserver.recovery_fail = {"why": why, "at": get_timestamp_seconds(),
                                            "tip": self.memserver.latest_block.get("block_number"), **detail}
        except Exception:
            pass

    def _rec(self, phase, **detail):
        """Publish the recovery state machine's current step to /status ("recovery" field). Two nodes
        (.26/.28, 2026-08-18) sat wedged behind opaque restarts with no shell access — the only readable
        surface was their status page, so the recovery path now narrates itself there: verdicts, adoption
        steps, refusals, and the last swallowed exception. Costs a dict assignment."""
        try:
            self.memserver.recovery_debug = {"phase": phase, "at": get_timestamp_seconds(),
                                             "tip": self.memserver.latest_block.get("block_number"),
                                             **detail}
        except Exception:
            pass

    def _memo_probe(self, peer, h, tip):
        """probe_block_hash_signed with a 90 s (peer, height) memo. A verdict round is ~46 probes and the
        binary search re-asks the same heights every FORK_STATE_TTL_S — unmemoized, each emergency pass
        burned ~65 s of serial probing, the core loop hit 140 s/pass, and the whole fleet starved each
        other's event loops into timeouts (the 2026-08-18 09:00 freeze). Answers are immutable facts about
        committed heights, so a short memo is safe; it dies with the verdict cache."""
        from ops.peer_ops import probe_block_hash_signed
        now = time.monotonic()
        memo = getattr(self, "_probe_memo", None)
        if memo is None or now - memo[0] > 90:
            memo = (now, {})
            self._probe_memo = memo
        key = (peer, int(h))
        if key in memo[1]:
            return memo[1][key]
        r = probe_block_hash_signed(peer, h, port=self.memserver.port, timeout=3, tip_hint=tip)
        memo[1][key] = r
        return r

    def _inline_tip_swap(self):
        """ONE-BLOCK TIE FAST PATH (2026-08-19). Every organic fork this week was a single divergent
        block that self-heals — but healing went through full emergency recovery (verdict probing,
        donor selection, mode churn), freezing finality for minutes over a paper cut (30 min at 14:20,
        which is also what pushed the exec layer visibly behind L1). When the measured verdict already
        says REORG with the ancestor exactly ONE below our tip, the entire fix is: fetch the sibling
        branch, verify it, roll back one block, apply — which is precisely _adopt_branch(tip-1), the
        tested possession-before-rollback path. Run it INLINE from check_mode and skip emergency mode
        entirely; production and duty flow continue on the very next pass, so finality never freezes.
        Anything deeper (ancestor < tip-1, UNKNOWN/BEHIND verdicts, refused rollbacks) falls through
        to the existing machinery unchanged. Fork-choice is untouched: minority_block_consensus has
        already decided WE are the yielding side before this runs — this only changes how cheaply the
        yield happens."""
        try:
            v = self._fork_verdict()
            tip = int(self.memserver.latest_block["block_number"])
            if v.get("state") != fork_resolution.REORG or v.get("ancestor") != tip - 1:
                return False
            adopted = self._adopt_branch(tip - 1)
            if adopted is True:
                self._fork_state_cache = None      # the tip this verdict described no longer exists
                self._rec("inline_tip_swap", h=tip)
                self.logger.warning(f"One-block split at {tip} resolved inline — emergency skipped")
                return True
            return False
        except Exception as e:
            self.logger.info(f"Inline tip swap declined: {e}")
            return False

    def _adopt_heaviest_pairwise(self):
        """THE NO-MAJORITY ESCAPE (fork_resolution.pairwise_ancestor doc): a multi-way scatter gives every
        node an UNKNOWN verdict, UNKNOWN correctly never reverts, and the fleet deadlocks — each branch
        producing alone. Weight still exists without a majority: find the common ancestor with the ONE
        peer advertising the strictly-heaviest tip and possession-adopt its branch. Returns the same
        tri-state as _adopt_branch (True adopted / False nothing usable / None escalate)."""
        try:
            hh = self.consensus.heaviest_block_hash
            hw = int(self.consensus.heaviest_block_weight or 0)
            our_w = int(self.memserver.latest_block.get("cumulative_weight", 0))
            if not hh or hw <= our_w:
                return False
            src = next((ip for ip, st in self.consensus.status_pool.copy().items()
                        if isinstance(st, dict) and st.get("latest_block_hash") == hh), None)
            if not src:
                # stale-hash race (see _adopt_branch): take the strictly-heaviest advertiser instead
                best_w, src = our_w, None
                for ip, st in self.consensus.status_pool.copy().items():
                    if isinstance(st, dict):
                        try:
                            w = int(st.get("latest_block_weight") or 0)
                        except (TypeError, ValueError):
                            continue
                        if w > best_w and st.get("latest_block_hash"):
                            best_w, src = w, ip
                if not src:
                    return False
            from ops.account_ops import get_hard_finality
            from ops.block_ops import get_block_hash_by_number
            tip = int(self.memserver.latest_block["block_number"])
            anc = fork_resolution.pairwise_ancestor(
                get_block_hash_by_number, tip,
                lambda h: (lambda r: r[0] if isinstance(r, tuple) else r)(self._memo_probe(src, h, tip)),
                floor=get_hard_finality())
            if anc is None or anc >= tip:
                return False
            self.logger.warning(f"No probe majority but {src} advertises a strictly-heavier branch "
                                f"(w {hw} > {our_w}); pairwise ancestor {anc} — attempting adoption")
            return self._adopt_branch(anc)
        except Exception as e:
            self.logger.warning(f"pairwise adoption failed: {e}")
            return False

    def _tie_break_ours(self, hh):
        """STABLE equal-weight fork choice, wired to the measured verdict: True = our branch is canonical,
        False = theirs is, None = no evidence either way (which never switches or suppresses anything).

        Weight increments are content-independent, so a same-height split is a PERMANENT exact tie — and
        the old lowest-TIP-hash tie-break re-rolled every block, flipping the verdict faster than any
        reorg could complete (the hours-long see-saws at 62655/62895). The FIRST DIVERGENT block
        (ancestor+1) never changes as branches grow: both sides compute one permanent winner
        (fork_resolution.tie_winner) and exactly one side reorgs, once. Ours is a local index read;
        theirs is one probe of a peer advertising `hh`, cached per-ancestor for FORK_STATE_TTL_S."""
        from protocol import FORK_STATE_TTL_S
        try:
            v = self._fork_verdict()
            anc = v.get("ancestor")
            if v.get("state") != fork_resolution.REORG or anc is None:
                return None
            ours = get_block_hash_by_number(anc + 1)
            if not ours:
                return None
            now = time.monotonic()
            cached = getattr(self, "_tie_theirs_cache", None)
            if cached and cached[0] == anc and now - cached[2] < FORK_STATE_TTL_S:
                theirs = cached[1]
            else:
                from ops.peer_ops import probe_block_hash
                theirs = None
                for ip, st in self.consensus.status_pool.copy().items():
                    if isinstance(st, dict) and st.get("latest_block_hash") == hh:
                        theirs = probe_block_hash(ip, anc + 1, port=self.memserver.port)
                        if theirs:
                            break
                self._tie_theirs_cache = (anc, theirs, now)
            if not theirs or theirs == ours:
                return None
            return fork_resolution.tie_winner(ours, theirs) == "ours"
        except Exception as e:
            self.logger.warning(f"tie-break probe failed: {e}")
            return None

    def _reapply_local_branch(self, old_tip):
        """Restore OUR branch from the local store after a failed adoption: the bodies were never deleted
        (they are content-addressed), so walk old_tip's parent chain down to the current (rolled-back) tip
        and re-apply forward through the one canonical apply path. Best-effort — a partial restore leaves
        the node lower but consistent, and ordinary sync continues from there."""
        try:
            chain = []
            b = old_tip
            while isinstance(b, dict) and b.get("block_number", 0) > self.memserver.latest_block["block_number"]:
                chain.append(b)
                b = get_block(b.get("parent_hash")) or None
            for blk in reversed(chain):
                if not self.produce_block(block=blk, remote=True, remote_peer=None):
                    break
            self.logger.warning(f"Re-applied our own branch back to {self.memserver.latest_block['block_number']} "
                                f"after a failed adoption")
        except Exception as e:
            self.logger.error(f"local branch re-apply failed: {e}")

    def _adopt_branch(self, anc):
        """POSSESSION-BEFORE-ROLLBACK: never revert a real block until the competing branch is HELD and
        pre-verified. The old order (roll toward the ancestor, then hope a donor serves the better chain)
        made disruption free: any advertisement that survived the verdict probes cost us real rollbacks
        and churn even when nothing valid was ever served. Now the branch is fetched FIRST — walked by
        parent_hash from the advertised tip down to the measured ancestor, each block checked for content
        hash and linkage, the claimed weight checked against ours — and only then do we roll to the
        ancestor and apply it through the one canonical apply path (produce_block -> verify_block, which
        re-derives and ENFORCES everything the pre-check cannot know without state). A branch that fails
        mid-apply costs the attacker a benched tip and us seconds: our own bodies are still in the store
        and _reapply_local_branch restores them.

        Returns True (adopted), False (nothing usable — caller waits/strikes), or None (rollback refused:
        budget/floor — caller escalates to the re-anchor ladder, exactly as before)."""
        hh = self.consensus.heaviest_block_hash
        our_w = self.memserver.latest_block.get("cumulative_weight", 0)
        src = next((ip for ip, st in self.consensus.status_pool.copy().items()
                    if isinstance(st, dict) and st.get("latest_block_hash") == hh), None)
        if not src:
            # THE STALE-HASH RACE. heaviest_block_hash is derived from gossip, and on a 6 s chain every
            # peer has advertised a NEWER tip by the time this scan runs — so the exact-hash lookup missed,
            # adoption returned False, and the next pass raced the same way. Observed live 2026-08-18: the
            # .26/.28 pair sat ONE BLOCK off the majority chain for 15+ minutes, failing this lookup every
            # pass. The branch matters, not the momentary tip: fall back to the strictly-heaviest
            # advertising peer and walk from ITS current tip — possession + full validation vet whatever
            # branch it actually serves.
            best_w, best_ip, best_tip = int(our_w), None, None
            for ip, st in self.consensus.status_pool.copy().items():
                if not isinstance(st, dict):
                    continue
                try:
                    w = int(st.get("latest_block_weight") or 0)
                except (TypeError, ValueError):
                    continue
                if w > best_w and st.get("latest_block_hash"):
                    best_w, best_ip, best_tip = w, ip, st["latest_block_hash"]
            if best_ip is None:
                return False
            src, hh = best_ip, best_tip
        if not hh:
            return False
        anc_hash = get_block_hash_by_number(anc)
        if not anc_hash:
            return False
        from ops.block_ops import block_content_hash
        from protocol import FINALITY_HARD_BACKSTOP
        self._rec("adopt_fetching", src=src, start=str(hh)[:12])
        staged, cur = [], hh
        for _ in range(FINALITY_HARD_BACKSTOP + EPOCH_LENGTH):
            # RESTART-PROOF RATCHET: bodies are content-addressed, so persist every fetched block
            # immediately and check the LOCAL store first on the next attempt. The .26/.28 pair was
            # restart-looping (cause on their boxes, not reachable from here), and every restart threw
            # away a half-finished 300-block staged walk — the fetch could never outlive the process.
            # Now each short life fetches what is still missing and the walk completes across lives.
            b = get_block(cur) or None
            if not isinstance(b, dict):
                b = asyncio.run(snapshot_ops.fetch_block(src, self.memserver.port, cur))
                if not isinstance(b, dict) or b.get("block_hash") != cur:
                    self._rec_fail("donor stopped serving", at_hash=str(cur)[:12], src=src)
                    self.logger.info(f"Branch adoption: {src} stopped serving its own branch at {cur[:12]}")
                    self._reject_heaviest_tip()
                    return False
                try:
                    if b.get("block_number", 0) != 0 and block_content_hash(b) != b["block_hash"]:
                        raise ValueError("content hash mismatch")
                except Exception as e:
                    self._rec_fail(f"forged/corrupt: {e}", src=src)
                    self.logger.warning(f"Branch adoption: {src} served a forged/corrupt block ({e}) — benching")
                    self._reject_heaviest_tip()
                    return False
                save_block(b, logger=self.logger)          # the ratchet: survives our next restart
            staged.append(b)
            ph = b.get("parent_hash")
            if ph == anc_hash:
                break
            if not ph or int(b.get("block_number", 0)) <= int(anc):
                self._rec_fail("walk missed the ancestor", ancestor=int(anc), src=src)
                self._reject_heaviest_tip()
                return False                       # walk missed the measured ancestor — inconsistent branch
            cur = ph
        else:
            # DEEP CATCH-UP: the branch from the advertised tip to our ancestor is longer than the staging
            # cap — not an illegal reorg, just a long absence (OUR side of the fork is still bounded by the
            # hard floor; THEIR side is however far the majority ran while we were away). Possession of the
            # whole branch is impractical here, and unnecessary: the ROLL part is still small
            # (ancestor-bounded, verdict-backed by the multi-peer hash probes — the substantiation the
            # free-rollback fix actually requires), and everything after it is ordinary forward sync with
            # full per-block validation. Roll to the ancestor, drop the spent verdict, and let the next
            # pass's donor flow fast-forward from the common chain (knows_block at the ancestor is True on
            # every majority donor).
            self.logger.warning(f"Branch adoption: majority branch longer than the staging cap — rolling to "
                                f"the measured ancestor {anc} and continuing by forward sync")
            self.memserver.rollbacks = 0
            while self.memserver.latest_block["block_number"] > anc:
                if self._rollback_one_for_reorg(ancestor=anc):
                    return None                    # budget/floor refused: escalate (re-anchor)
            self._fork_state_cache = None
            return False                           # not adopted here — the donor flow finishes the job
        staged.reverse()
        if int(staged[-1].get("cumulative_weight", 0)) <= int(our_w):
            self._rec_fail("possession disproved the weight claim", src=src)
            self._reject_heaviest_tip()
            return False                           # possession disproved the advertisement
        # FORK FORENSICS: this is the one moment both branches are in hand — ours still referenced,
        # theirs staged. Record the FIRST divergent block's difference (the fork's seed) before the roll
        # deletes our side's locators. Answers "what actually forks this chain" with data instead of
        # theory: divergent tx sets point at propagation (which tx, which kind), identical tx sets point
        # at ordering/creator/timestamp. Appended to ~/nado/fork_diffs.jsonl + the latest on /status.
        try:
            import json as _json
            from ops.data_ops import get_home as _gh
            for _blk in staged:
                _n = int(_blk.get("block_number", -1))
                _oh = get_block_hash_by_number(_n)
                _ob = get_block(_oh) if _oh else None
                if not isinstance(_ob, dict) or _ob.get("block_hash") == _blk.get("block_hash"):
                    continue
                _sig = lambda b: sorted((t.get("recipient"),
                                         (t.get("data") or {}).get("op") if isinstance(t.get("data"), dict) else None,
                                         str(t.get("txid"))[:16])
                                        for t in (b.get("block_transactions") or []))
                _so, _st = _sig(_ob), _sig(_blk)
                _d = {"at": get_timestamp_seconds(), "h": _n, "anc": int(anc), "src": src}
                if _so != _st:
                    _d["only_ours"] = [list(t) for t in _so if t not in _st][:6]
                    _d["only_theirs"] = [list(t) for t in _st if t not in _so][:6]
                else:
                    _d.update({"same_txs": len(_so), "creator_ours": str(_ob.get("block_creator"))[:12],
                               "creator_theirs": str(_blk.get("block_creator"))[:12],
                               "ts_ours": _ob.get("block_timestamp"), "ts_theirs": _blk.get("block_timestamp")})
                self.memserver.last_fork_diff = _d
                with open(f"{_gh()}/fork_diffs.jsonl", "a") as _f:
                    _f.write(_json.dumps(_d) + "\n")
                break                                    # the first divergent block is the seed
        except Exception:
            pass
        old_tip = self.memserver.latest_block
        self._rec("adopt_rolling", src=src, staged=len(staged), to=int(anc))
        self.memserver.rollbacks = 0
        while self.memserver.latest_block["block_number"] > anc:
            if self._rollback_one_for_reorg(ancestor=anc):
                self._rec("adopt_roll_refused", to=int(anc))
                return None                        # budget/floor refused mid-burst: escalate (re-anchor)
        self._rec("adopt_applying", src=src, staged=len(staged))
        for blk in staged:
            if not self.produce_block(block=blk, remote=True, remote_peer=src):
                rej = getattr(self.memserver, "last_block_reject", None) or {}
                if "our state diverged from the producer" in str(rej.get("error", "")):
                    # NOT the donor's fault — OUR committed state is corrupt at a parent whose HASH we
                    # agree on (the h4260 rollback-asymmetry class: hours of roll-and-remine cycles left
                    # residue no rollback can fix, observed on .26/.28 with three different state roots at
                    # one agreed block). No branch will ever validate on top of a wrong state DB, so
                    # striking donors is self-harm: ESCALATE to the re-anchor ladder — a snapshot import
                    # replaces the state wholesale (quorum-vouched), and canonical restore keeps our
                    # bodies. Restore our branch first so we stay self-consistent until it lands.
                    self._rec_fail("own state corrupt at agreed parent — escalating to re-anchor",
                                   height=blk.get("block_number"))
                    self.logger.error(f"Branch adoption: our L1 state is CORRUPT at agreed parent "
                                      f"{int(anc)} ({rej.get('error', '')[:120]}) — re-anchoring to a "
                                      f"quorum snapshot")
                    self._reapply_local_branch(old_tip)
                    return None
                self._rec_fail("block failed full validation",
                          height=blk.get("block_number"), src=src)
                self.logger.warning(f"Branch adoption: block {blk.get('block_number')} from {src} failed "
                                    f"full validation — restoring our own branch")
                self._reapply_local_branch(old_tip)
                self._reject_heaviest_tip()
                return False
        self._fork_state_cache = None              # the tip this verdict described no longer exists
        self.logger.warning(f"Adopted the measured majority branch: rolled to {anc}, applied "
                            f"{len(staged)} block(s) from {src}, tip now "
                            f"{self.memserver.latest_block['block_number']}")
        return True

    def _maybe_escape_dead_fork(self) -> bool:
        """LAST-RESORT AUTORECOVERY: purge + resync when the node is provably stranded on a minority fork
        AT OR BELOW its own finality floor.

        Every other recovery path assumes the finalized prefix is sound. When it is not, they all fail
        together: rollback refuses to cross the floor, re-anchor needs a snapshot ABOVE a floor that is on
        the wrong chain, and _heavier_chain_exists() — which gates re-anchor — reads the status pool and
        skips benched peers, so a collapsed peer set or a wrong bench makes the true chain invisible.
        Observed live 2026-07-20: our finalized 19988 hashed 7c7a7c08 while the network had eb9d6de8; the
        node sat wedged 40+ minutes through a restart AND a force_sync, and only scripts/purge_resync.sh
        moved it. A human had to notice. That is the gap this closes.

        ALSO CALLED FROM normal_mode (the productive-fork case): a node that forks and keeps MINING never
        stalls, is always the heaviest tip, and so never reaches the emergency loop where this used to be the
        only caller. It was invisible to every recovery route at once (.141, 2026-07-28).

        DELIBERATELY PARANOID, because the remedy destroys chain-derived data:
          * only if peers we ask DIRECTLY (seed set + known peers — not the status pool, not benching)
            report a different hash at OUR finalized height,
          * only if NOBODY agrees with us: one agreeing peer means we are merely poorly connected, and
            wiping then would be far worse than staying wedged,
          * only if those disagreeing peers are strictly HEAVIER than us. Weight is NOT used to decide that
            a fork exists — the direct probe above does that, and weight is exactly the signal that misled
            every earlier recovery ladder. It is used only to decide WHICH SIDE of an already-proven fork
            yields, because without a tie-break both sides of a symmetric split purge each other into
            parallel chains. Asked directly too (peer_tip_weight), never via the status pool.
          * only every DEAD_FORK_COOLDOWN_S, and never when the operator has opted out.
        private/ (keys, config) is never touched — purge_chain_data drops chain-derived data only."""
        from protocol import (DEAD_FORK_STALL_S, DEAD_FORK_COOLDOWN_S, DEAD_FORK_QUORUM,
                              DEAD_FORK_ALONE_S)
        try:
            if self.memserver.config.get("auto_escape_dead_fork", True) is False:
                return False
            now = get_timestamp_seconds()
            if now - getattr(self, "_last_dead_fork_check", 0) < DEAD_FORK_COOLDOWN_S:
                return False
            # NOT gated on a frozen tip any more. "Still moving" was taken to mean "healthy", but a node
            # alone on a fork MOVES FASTEST of all — it mines every slot unopposed. That reading is exactly
            # what let .141 mine 600+ blocks on a dead branch while this check declined to even ask
            # (2026-07-28). A stalled tip is one symptom of a dead fork, never its definition; the honest
            # definition is the probe below (a quorum of peers serving a different block at OUR finalized
            # height, and nobody agreeing with us), which is just as true of a node that is producing.
            # DEAD_FORK_COOLDOWN_S already bounds this to one probe per 30 min, so dropping the stall
            # precondition costs a healthy node one cheap probe round per cooldown and nothing else.
            _stalled = self.memserver.since_last_block >= DEAD_FORK_STALL_S

            from ops.peer_ops import seed_peers, stranded_below_finality, peer_tip_weight
            from ops.account_ops import get_hard_finality
            from ops.block_ops import get_block_hash_by_number
            # TWO-FLOOR: probe at the HARD floor — the deepest point this node refuses to move. The depth
            # floor is crossable now, so disagreement there is an ordinary REORG for the rollback leg, not
            # grounds for the destructive purge. hard == 0 means no immutable prefix exists yet: every
            # divergence is reachable by rollback or re-anchor, so there is nothing to escape from.
            height = get_hard_finality()
            if height <= 0:
                return False
            ours = get_block_hash_by_number(height)
            if not ours:
                return False
            # Ask the operator seed set FIRST (the weak-subjectivity anchor) plus whatever peers we know.
            # NEVER PROBE OURSELVES — _fork_state() already carves this out and it is even more critical here.
            # This node's own IP can BE a seed (208.87.242.141 is in DEFAULT_SEED_PEERS), so seeds-first puts
            # us in the probe set, we answer our own question with our own hash, that lands in `agree`, and
            # "ANY peer agreeing means our prefix is not provably abandoned" vetoes the purge FOREVER. That is
            # precisely why .141 — a seed — could not self-heal even once every other blind spot was fixed
            # (2026-07-28): it was the one node whose peer list contained itself.
            _me = {self.memserver.ip, get_config().get("ip")} - {None}
            peers = [p for p in dict.fromkeys(list(seed_peers()) + list(self.memserver.peers))
                     if p not in _me][:12]
            stranded, detail = stranded_below_finality(ours, height, peers, quorum=DEAD_FORK_QUORUM,
                                                       port=self.memserver.port)
            # ONLY a probe that actually HEARD from peers consumes the full cooldown. An inconclusive round
            # — nobody answered, which is the normal state for the first pass after boot, before the peer
            # table is warm — must not lock this out for 30 minutes. That is exactly what happened to .141:
            # it finally received the fix, ran one check at startup with no peers yet, and would have stayed
            # forked for another half hour on a cooldown it never really used. Retry inconclusive rounds in
            # a minute; a round that got real answers keeps the full rate limit.
            _answered = bool(detail.get("agree") or detail.get("disagree"))
            self._last_dead_fork_check = now if _answered else (now - DEAD_FORK_COOLDOWN_S + 60)
            # PUBLISH THE VERDICT. A node that declines to heal itself must be able to SAY WHY from the
            # outside — /log is authenticated and journalctl needs a shell, so a remote operator was left
            # guessing which of the six preconditions vetoed (that guessing is what stretched the .141
            # incident). This is diagnostics only; nothing reads it back.
            self.memserver.dead_fork_probe = {
                "at": now, "height": height, "ours": str(ours)[:16], "stranded": bool(stranded),
                "agree": list(detail.get("agree") or []), "disagree": list(detail.get("disagree") or []),
                "unknown": list(detail.get("unknown") or []), "answered": _answered,
                "peers_asked": len(peers), "stalled": bool(_stalled),
            }
            if not stranded:
                return False
            # SECOND, INDEPENDENT CONFIRMATION before destroying chain data: the measured fork state must
            # ALSO say DEAD_FORK. Two different probes have to agree that the divergence is below the
            # finality floor, so a single bad answer can never trigger a purge.
            _fs = self._fork_state()
            try:
                self.memserver.dead_fork_probe["fork_state"] = str(_fs)
            except Exception:
                pass
            if _fs != fork_resolution.DEAD_FORK:
                self.logger.warning(f"dead-fork suspected but the measured fork state says {_fs} — not purging")
                return False
            # THIRD CONFIRMATION — ONLY THE LIGHTER SIDE YIELDS. This is what made the check unsafe to run
            # continuously: in a SYMMETRIC split both sides see "a quorum disagrees and nobody agrees", so
            # BOTH purge, both resync from whoever answers first (often each other), and the fleet ends up on
            # parallel chains sharing only genesis. That is the purge storm that forced the normal_mode
            # caller to be disabled on 2026-07-28, and no amount of quorum tuning fixes it — 2 of 3 non-self
            # peers IS a majority on both sides of a 2-2 split.
            #
            # Weight breaks the symmetry the way fork choice already does everywhere else: the lighter side
            # yields, the heavier side stays put, so EXACTLY ONE side of any split purges. Equal weight, or a
            # peer whose weight we do not know, means nobody moves — the safe direction, because staying
            # wedged is recoverable by the next probe while a mutual purge is not.
            #
            # Not a trust hole: a peer that lies about its weight only induces a purge if a QUORUM of peers
            # tells the same lie AND serves a different block at our finalized height, and the resync that
            # follows validates every block it accepts — a liar with no real heavier chain cannot be synced
            # from. This reads the same advertised cumulative_weight fork choice already acts on.
            _ours_w = int((self.memserver.latest_block or {}).get("cumulative_weight", 0) or 0)
            _we_are_lighter, _their_w = lighter_than_disagreeing(
                _ours_w, detail.get("disagree"),
                {p: {"latest_block_weight": peer_tip_weight(p, port=self.memserver.port)}
                 for p in (detail.get("disagree") or [])})
            try:
                self.memserver.dead_fork_probe["our_weight"] = _ours_w
                self.memserver.dead_fork_probe["their_weight"] = _their_w
            except Exception:
                pass
            # UNANIMOUS ISOLATION OVERRIDES WEIGHT. The weight tie-break exists to stop BOTH halves of an
            # even split purging each other; it is not a claim that the heavier chain is the right one. When
            # EVERY peer we know disagrees and not one agrees, there is no symmetry left to break — we are
            # simply alone, and being alone is decisive however much work our branch carries. A lone miner on
            # a fork is the FASTEST chain there is (it wins every slot unopposed), so "heavier" is exactly
            # what a stranded node looks like.
            #
            # Observed live 2026-07-28 on betanet-13: 185.100.232.5 rerolled ~4 minutes ahead of the others,
            # built its own chain from the shared genesis, and sat at tip 273 / weight 88725 against three
            # agreeing nodes at ~217 / 70525. Its probe correctly said stranded, 3 disagree, 0 agree — and the
            # weight rule I had just added vetoed the purge because the isolated node was the heavy one. The
            # three-node side is the one that can reach an attestation quorum and finalize; the lone heavy
            # branch never can.
            #
            # The storm case this still guards is a SILENT partner: 2 of 3 peers disagreeing while our own
            # partner fails to answer is not unanimity, so weight still decides there and only one side moves.
            _known_peers = [p for p in peers]
            _dis = list(detail.get("disagree") or [])
            _unanimous = bool(_known_peers) and len(_dis) >= len(_known_peers) and not detail.get("agree")
            try:
                self.memserver.dead_fork_probe["unanimous"] = _unanimous
            except Exception:
                pass
            # SUSTAINED ISOLATION IS DECISIVE, even when we are heavier and one peer stayed silent.
            #
            # `_unanimous` demands that EVERY peer we asked disagrees, so a single peer that fails to answer
            # makes it permanently False — and a lone forker is always the heavy side, because it wins every
            # slot unopposed. Both escape hatches then shut at once and the node forks forever. Measured live
            # on betanet-15 (2026-08-03): node .131 sat at stranded=True, fork_state=dead_fork, agree=[],
            # disagree=2, peers_asked=3 -> unanimous False -> vetoed on weight, for hours, lead widening.
            #
            # Time breaks that deadlock without weakening the storm guard. In a symmetric split each side
            # still has partners that AGREE with it, so `agree == []` is never true there; a transient
            # partition clears within a probe or two; only a genuine strand persists. Requiring the SAME
            # isolated verdict continuously for DEAD_FORK_ALONE_S turns "I might be alone" into "I have been
            # alone for an hour", which is decisive however much work our branch carries.
            _alone_now = isolation_holds(detail.get("agree"), _dis, DEAD_FORK_QUORUM)
            self._dead_fork_alone_since = isolation_since(
                getattr(self, "_dead_fork_alone_since", None), _alone_now, now)
            _alone_for = (now - self._dead_fork_alone_since) if self._dead_fork_alone_since else 0
            try:
                self.memserver.dead_fork_probe["alone_for_s"] = int(_alone_for)
            except Exception:
                pass
            _sustained = bool(self._dead_fork_alone_since) and _alone_for >= DEAD_FORK_ALONE_S

            if not _we_are_lighter and not _unanimous and not _sustained:
                self.logger.warning(
                    f"DEAD FORK confirmed at {height}, but our chain is NOT the lighter one "
                    f"(ours={_ours_w} theirs={_their_w}) and the disagreement is not unanimous "
                    f"({len(_dis)}/{len(_known_peers)} peers) — not purging. The lighter side of an even "
                    f"split is the side that yields. Alone for {int(_alone_for)}s of "
                    f"{DEAD_FORK_ALONE_S}s needed to override on isolation alone.")
                return False
            if _sustained and not _we_are_lighter and not _unanimous:
                self.logger.error(
                    f"DEAD FORK at {height}: continuously ISOLATED for {int(_alone_for)}s — "
                    f"{len(_dis)} peer(s) disagree, NONE agree, across every probe in that window. Our branch "
                    f"is heavier (ours={_ours_w} theirs={_their_w}), which is exactly what a lone forker "
                    f"looks like. A peer that never answers must not veto recovery forever. Purging.")
            if _unanimous and not _we_are_lighter:
                self.logger.error(
                    f"DEAD FORK at {height}: every one of the {len(_known_peers)} peers we know disagrees and "
                    f"none agree. Our branch is HEAVIER (ours={_ours_w} theirs={_their_w}) — which is what a "
                    f"lone forker always looks like, since it mines every slot unopposed. Purging anyway: "
                    f"weight measures work, agreement measures consensus.")
            self.logger.error("=" * 78)
            self.logger.error(f"DEAD FORK ({'tip frozen' if _stalled else 'STILL MINING — productive fork'}): "
                              f"our FINALIZED block {height} is {str(ours)[:16]}… but "
                              f"{len(detail['disagree'])} peers have a different block there and NONE agree.")
            self.logger.error("Finality refuses to roll back across it, so no local recovery can work. "
                              "Purging chain-derived data and resyncing. private/ (keys) is untouched.")
            self.logger.error("=" * 78)
            from ops.data_ops import purge_chain_data, stamp_chain_generation
            purge_chain_data(logger=self.logger)
            stamp_chain_generation()
            self.memserver.terminate = True       # ask every loop to drain
            # ...and then ACTUALLY GO. The flag alone is not enough: the aiohttp server keeps serving on the
            # main thread, so the process stayed alive with its chain PURGED FROM DISK but still resident in
            # memory, cheerfully answering /status with a tip it could no longer serve a single block of
            # (observed live 2026-07-28 — it even ran its periodic update check eight seconds after logging
            # "bye"). That zombie is worse than either running or stopped: peers fork-choose against a chain
            # nobody can hand them, and the purge that was supposed to heal the node instead poisoned them.
            # /terminate already hard-exits for precisely this reason; match it. The delay lets these log
            # lines flush before the process disappears.
            self.logger.error("Purge complete — exiting so systemd restarts us into a clean resync.")
            threading.Timer(1.0, lambda: os._exit(0)).start()
            return True
        except Exception as e:
            self.logger.warning(f"dead-fork escape check failed: {e}")
            return False

    def _maybe_reanchor(self) -> bool:
        """WEDGE RECOVERY, driven by the MEASURED fork state (ops/fork_resolution) — not inferred.

        This replaces the old ladder (_heavier_chain_exists -> weight comparison -> escalation counter ->
        _rejoin_by_rollback -> _common_ancestor), all of which is DELETED. That ladder inferred the fork
        state from weights, donor behaviour and bench state, and on 2026-07-20 every rung mis-fired at once:
        the node was ~500 blocks BEHIND on the CORRECT chain, weights truthfully said "they are heavier",
        the inference concluded "we are forked", it rolled back into a snapshot with no history beneath it
        ("Parent None ... is not on disk"), aborted, re-anchored, and looped for 40+ minutes across a
        restart. _heavier_chain_exists() was additionally gated on consensus.status_pool minus BENCHED
        peers, so a collapsed peer set (it fell to ONE) left nothing to act on at all.

        Now there is one input — the highest height where our hash equals the majority's — and one action
        per state. Hash equality at a height is a fact; weight comparison is a heuristic that cannot tell
        "behind" from "forked", which is the exact distinction that mattered.

            BEHIND / UNKNOWN  do nothing here. Ordinary forward sync handles being short, and an
                              unestablished majority must never move a node.
            REORG             forked ABOVE the finality floor -> re-anchor by weight. The rollback this
                              implies is legal, so no floor override is needed and none is passed.
            DEAD_FORK         forked AT/BELOW the floor -> finality forbids the rollback, so no local
                              remedy exists; hand to the purge+resync escape.

        Returns True iff the chain identity changed (caller resumes on the new chain)."""
        state = self._fork_state()
        if state in (fork_resolution.BEHIND, fork_resolution.UNKNOWN, fork_resolution.SYNCED):
            # UNKNOWN MUST NOT CLEAR THE DEAD-FORK STREAK. _fork_state() returns UNKNOWN on any measurement
            # FAILURE — "we could not determine it", not "we are healthy". A wedged node flaps between
            # DEAD_FORK and UNKNOWN as probes succeed or fail, so clearing on UNKNOWN would mean the streak
            # never reaches the escalation threshold and the remedy never fires. Only a positive healthy
            # verdict clears it.
            if state != fork_resolution.UNKNOWN:
                self._dead_fork_streak = 0
            return False
        if state == fork_resolution.DEAD_FORK:
            # ESCALATE TO A FLOOR-CROSSING RE-ANCHOR BEFORE THE DESTRUCTIVE ESCAPE.
            #
            # snapshot_bootstrap already implements allow_below_floor for precisely this geometry, and its
            # docstring reserves it for "operator recovery ... consecutive failed attempts" — but NOTHING
            # ever passed True, so the escalation was dead code and the only route out of DEAD_FORK was the
            # purge escape. That escape deliberately requires that NOBODY agrees with us, to stop both
            # halves of a symmetric split from wiping each other (observed: the fleet went from one chain to
            # two sharing only genesis). Correct, and it leaves this case wedged forever:
            #
            #   observed live 2026-08-04 — a 2-2 split at h20352. Branch A (this node + 185.100.232.131)
            #   stalled at 20371 with weight 6,791,252; branch B (.141 + .210) advancing at 20447 with
            #   weight 6,817,624. Rollbacks exhausted 40/40; rollback refused because the fork ancestor
            #   (20352) sits below our own sticky finality floor (20371, persisted and monotonic, so a
            #   restart does not lower it); and the purge escape was vetoed because .131 AGREED with us —
            #   both nodes on the same dead branch, each vetoing the other's recovery indefinitely.
            #
            # WEIGHT ALREADY BREAKS THE SYMMETRY, which is what makes this safe without the "nobody agrees"
            # precondition: snapshot_bootstrap(force_reanchor=True) selects by STRICTLY-heaviest cumulative
            # weight, so only the lighter side can ever find a donor and act. A mutual wipe is impossible by
            # construction, and unlike the purge escape this is NON-DESTRUCTIVE: the heavier chain's
            # snapshot is imported over our forked state, our fork's blocks are simply orphaned in the
            # store, and every tail block after the import is fully re-verified.
            #
            # Gated on CONSECUTIVE dead-fork verdicts (what the docstring asks for) so a transient
            # misreading can never trigger it, and on the same cooldown as an ordinary re-anchor.
            self._dead_fork_streak = getattr(self, "_dead_fork_streak", 0) + 1
            if self._dead_fork_streak >= DEAD_FORK_ESCALATE_AFTER:
                _now = get_timestamp_seconds()
                if _now - self._last_reanchor_ts >= REANCHOR_COOLDOWN:
                    self._last_reanchor_ts = _now
                    self.logger.warning(
                        f"DEAD FORK persisted {self._dead_fork_streak} consecutive checks — the finality "
                        f"floor itself is on a minority fork; re-anchoring onto the strictly-heaviest "
                        f"chain BELOW the floor (non-destructive: our fork's blocks are orphaned, every "
                        f"imported tail block is re-verified)")
                    if self.snapshot_bootstrap(force_reanchor=True, allow_below_floor=True):
                        self.memserver.rollbacks = 0
                        self._fork_state_cache = None     # identity changed; the cached verdict is stale
                        self._dead_fork_streak = 0
                        return True
            return self._maybe_escape_dead_fork()
        self._dead_fork_streak = 0                        # not dead-forked: the streak must not persist
        now = get_timestamp_seconds()
        if now - self._last_reanchor_ts < REANCHOR_COOLDOWN:
            return False                                  # a failing import must not hammer peers
        self._last_reanchor_ts = now
        self.logger.warning("Forked above the finality floor — re-anchoring by weight onto the majority chain")
        if self.snapshot_bootstrap(force_reanchor=True, allow_below_floor=False):
            # Chain identity changed under us: reset the rollback burst counter so the fresh tail sync
            # starts clean. rejected_tips is deliberately NOT cleared — it is rebuilt from per-tip
            # deadlines each consensus pass, so a chain we repeatedly failed to obtain stays benched.
            self.memserver.rollbacks = 0
            self._fork_state_cache = None                 # identity changed; the cached verdict is stale
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
        # THROTTLE the entry/loop logs + the telemetry: emergency_mode() is RE-ENTERED every ~1s while
        # behind, so logging "Entering/Looping emergency mode" per entry spammed the journal once/second
        # and made a genuine event impossible to spot. Emit (and count) at most once per _EMERGENCY_LOG_EVERY
        # seconds — a continuous episode leaves a periodic heartbeat, distinct episodes each get their own.
        now = time.time()
        # An EPISODE is a run of entries not separated by more than _EMERGENCY_LOG_EVERY of calm. Count and
        # log once per episode: counting every re-entry would score one continuous hour as ~3600 "entries",
        # while counting only throttled heartbeats would score three distinct 5s-apart episodes as one.
        _prev = getattr(self, "_last_emergency_log", 0.0)
        self._last_emergency_log = now
        if (now - _prev) >= _EMERGENCY_LOG_EVERY:
            # NOT a warning, and NOT "rolling back": entering this loop only means a better tip was
            # advertised that we do not hold. The overwhelmingly common outcome is that the block arrives
            # a pass later and we leave without touching a thing — measured today: 75 entries, 0
            # rollbacks, 0 state-root rejects. Claiming "rolling back / resyncing" on every entry made a
            # healthy node look like it was in a rollback storm and buried the days when it really was
            # (2026-07-26: 3113 rollbacks, 29 root rejects). Actual rollbacks log at WARNING where they
            # happen; this is the evaluation, so it is INFO and says only what it knows.
            self.logger.info("Behind an advertised tip we do not hold — evaluating sync/reorg")
            try:
                from ops import rollback_stats
                rollback_stats.record_emergency()
            except Exception:
                pass
        self.memserver.rollbacks = 0            # fresh burst: per-burst rollback rate limit (see docstring)
        if self.snapshot_bootstrap():
            self.logger.warning("State bootstrapped from snapshot; continuing with tail sync")
        try:
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
                # VERDICT FIRST, DONOR SECOND. When the measured verdict is REORG with a known ancestor,
                # roll toward the ancestor WITHOUT consulting any donor. Observed live (2026-08-17 23:06,
                # a real two-sided split at 62655): donor selection keys off the heaviest ADVERTISED tip,
                # which flip-flops between the split's sides as both advance — a same-fork donor "knows"
                # our tip, fast-forward re-inflates the very fork we just rolled back, and each pass burns
                # a 5 s knows_block round-trip, throttling recovery to ~1 rollback a minute on a 12-block
                # fork. The verdict already IS the decision; the donor only matters once we are at the
                # ancestor and need the majority chain fetched.
                verdict = self._fork_verdict()
                vstate = verdict.get("state")
                _anc = verdict.get("ancestor")
                self._rec("verdict", state=str(vstate), ancestor=_anc)
                if (vstate == fork_resolution.REORG and _anc is not None
                        and int(self.memserver.latest_block["block_number"]) > int(_anc)):
                    # POSSESSION BEFORE ROLLBACK: fetch + pre-verify the competing branch, and only then
                    # revert anything (see _adopt_branch — the free-rollback vector dies here: an
                    # advertisement that cannot be substantiated with a held, hash-consistent, heavier
                    # branch costs us NOTHING but the fetch, and the tip gets benched).
                    adopted = self._adopt_branch(_anc)
                    self._rec("adopt_reorg_result", result=repr(adopted), ancestor=_anc)
                    if adopted is None:
                        # rollback refused mid-adoption (budget/floor): the fork is deeper than the leg
                        # can serve — escalate exactly as the old give-up path did.
                        if self._maybe_reanchor():
                            self.logger.warning("Re-anchored from seed snapshot; continuing with tail sync")
                            continue
                        break
                    if adopted:
                        continue
                    time.sleep(1)
                    continue
                if vstate == fork_resolution.DEAD_FORK:
                    if self._maybe_reanchor() or self._maybe_escape_dead_fork():
                        self.logger.warning("Re-anchored from seed snapshot; continuing with tail sync")
                        continue
                    time.sleep(1)
                    continue
                if vstate == fork_resolution.UNKNOWN:
                    # NO PROBE MAJORITY (multi-way scatter): the pairwise weight escape — see
                    # _adopt_heaviest_pairwise. Without this, UNKNOWN + no donor froze the node for as
                    # long as the scatter lasted (35 min observed), while it benched the very tips it
                    # needed. Possession + full validation keep the safety story identical.
                    adopted = self._adopt_heaviest_pairwise()
                    self._rec("adopt_pairwise_result", result=repr(adopted))
                    if adopted is None:
                        if self._maybe_reanchor():
                            self.logger.warning("Re-anchored from seed snapshot; continuing with tail sync")
                            continue
                        break
                    if adopted:
                        continue
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
                    elif self._maybe_reanchor() or self._maybe_escape_dead_fork():
                        self.logger.warning("Re-anchored from seed snapshot; continuing with tail sync")
                    elif vstate == fork_resolution.UNKNOWN:
                        # NO evidence + no donor: benching the heaviest tip here starves the recovery of
                        # the very branch it needs (observed: one honest leader tip excluded per pass for
                        # 35 minutes). The pairwise escape above is the exit; just wait.
                        time.sleep(1)
                    else:
                        # STRIKE THE HEAVIEST TIP even though we never got as far as fetching from it.
                        # Donor selection only considers peers advertising the HEAVIEST tip, so a lone
                        # forker with an inflated weight owns the donor pool: it cannot serve us, no fetch
                        # is ever attempted, no failure is ever recorded, and the tip therefore stays
                        # heaviest forever while the healthy peers — perfectly good donors for the chain we
                        # are actually on — are never even considered. Observed live: our tip 17000 was on
                        # the majority's canonical chain and they were 76 blocks ahead, yet the node sat
                        # still because the only "qualified" donor was the 3500-block-stale fork. Failing
                        # to find any donor for a tip IS a failure to obtain it, and must count as one.
                        self._reject_heaviest_tip()
                    time.sleep(1)
                else:
                    block_hash = self.memserver.latest_block["block_hash"]
                    known_block = asyncio.run(knows_block(
                        target_peer=peer,
                        port=self.memserver.port,
                        hash=block_hash,
                        number=self.memserver.latest_block["block_number"],
                        logger=self.logger))

                    if known_block:
                        self._donor_unanswered = 0
                        self.logger.info(f"{peer} knows block {block_hash}")
                        ended = self._fast_forward_from(peer=peer, from_hash=block_hash)
                        # blocks may have been adopted either way — the cached verdict describes a tip
                        # that no longer exists; a stale REORG must never drive a rollback of the chain
                        # we just fetched.
                        self._fork_state_cache = None
                        if ended:
                            break
                    elif known_block is None:
                        # THE DONOR COULD NOT ANSWER — timeout, momentarily behind us (404), malformed.
                        # This used to be indistinguishable from "our tip is not on its chain" and went
                        # straight to the ROLLBACK leg, converting every donor blip into a reverted real
                        # block (2026-08-17: 2,609 rollbacks, 20 exhausted 40-block bursts, on a healthy
                        # chain). A peer that cannot attest either way is evidence of NOTHING; retry, and
                        # only after several consecutive non-answers strike the tip so a permanently mute
                        # donor pool cannot pin us here.
                        self._donor_unanswered = getattr(self, "_donor_unanswered", 0) + 1
                        if self._donor_unanswered >= 3:
                            self._donor_unanswered = 0
                            self.logger.info(f"Donors cannot attest our tip either way ({peer} et al.) — "
                                             f"striking the advertised tip, not our chain")
                            self._reject_heaviest_tip()
                        time.sleep(1)
                    else:
                        # POSITIVE mismatch on one donor's word, with a non-REORG verdict. Two honest
                        # explanations, and striking was wrong for both (observed live on .28, 2026-08-18:
                        # striking the LEADER tips emptied the peer-ahead production gate, the node won the
                        # next slot, re-mined a one-block fork from its divergent mempool, and looped —
                        # rolling to the ancestor and re-forking every few slots, forever):
                        #   * a stale BEHIND verdict + blocks we SELF-MINED above its ancestor since it was
                        #     cached — our tip is a fresh fork block; adopt the majority branch from the
                        #     ancestor exactly like a REORG (possession + full validation as always);
                        #   * genuinely BEHIND with this one donor lagging/forked — rotate donors, and
                        #     leave the heavier tips alone so the caught-up gate keeps us from minting.
                        self._donor_unanswered = 0
                        _anc2 = verdict.get("ancestor")
                        if (vstate == fork_resolution.BEHIND and _anc2 is not None
                                and int(self.memserver.latest_block["block_number"]) > int(_anc2)):
                            adopted = self._adopt_branch(_anc2)
                            self._rec("adopt_selffork_result", result=repr(adopted), ancestor=_anc2)
                            if adopted is None:
                                if self._maybe_reanchor():
                                    self.logger.warning("Re-anchored from seed snapshot; continuing with tail sync")
                                    continue
                                break
                            if adopted:
                                continue
                            time.sleep(1)
                        elif vstate == fork_resolution.BEHIND:
                            # ONE donor refusing our tip while BEHIND is a lagging/forked donor — rotate.
                            # But REPEATED positive refusals from DISTINCT donors contradict the verdict:
                            # a stake-weighted majority_hash can be won at our own tip height by our own
                            # partisans in a same-height split (4v5, h67961, 2026-08-18 — the seat-heavy
                            # side outvoted the headcount side, classified BEHIND with ancestor == tip,
                            # and parked forever while the other branch ran away: the "heavier branch"
                            # never EXTENDS a tip it does not contain, so forward sync can never link).
                            # Measurement beats the verdict: resolve pairwise against the heaviest
                            # advertiser exactly like the no-majority escape.
                            self._behind_refusals = getattr(self, "_behind_refusals", set())
                            self._behind_refusals.add(peer)
                            if len(self._behind_refusals) >= 3:
                                self._behind_refusals = set()
                                self.logger.warning("BEHIND verdict contradicted by 3 distinct donors "
                                                    "positively refusing our tip — resolving pairwise "
                                                    "against the heaviest advertiser")
                                self._rec("behind_contradicted", donors=3)
                                adopted = self._adopt_heaviest_pairwise()
                                self._fork_state_cache = None
                                if adopted is None:
                                    if self._maybe_reanchor():
                                        self.logger.warning("Re-anchored from seed snapshot; continuing "
                                                            "with tail sync")
                                        continue
                                    break
                                if adopted:
                                    continue
                            self.logger.info(f"Tip mismatch from {peer} while BEHIND — rotating donors, "
                                             f"leaving the heavier tips unbenched")
                            time.sleep(1)
                        else:
                            self.logger.info(f"Tip mismatch from {peer} but measured fork state disagrees — "
                                             f"not rolling back; striking the tip instead")
                            self._reject_heaviest_tip()
                            time.sleep(1)

        except Exception as e:
            self.logger.info(f"Error: {e}")
            self._rec("emergency_exception", error=str(e)[:160])
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
                # a lying/broken peer. Reject the tip or we loop on it forever. If a strictly-heavier
                # chain exists this can also mean OUR tip is a dead end no donor extends (a fork all
                # honest peers abandoned) — try the re-anchor jump (cooldown-limited internally)
                # instead of only excluding tips one by one until the pool runs dry.
                self.logger.info(f"No newer blocks found from {peer}")
                self._reject_heaviest_tip()
                if self._maybe_reanchor():
                    self.logger.warning("Re-anchored from seed snapshot; continuing with tail sync")
                    return False
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
                        rejected = True
                        break

                prefetch_thread.join()
                if rejected:
                    return True
                # A batch from this donor VERIFIED AND APPLIED — the only honest healing signal there
                # is. A peer struck while briefly down (update-wave restart) is rehabilitated on first
                # service instead of sitting out an escalated bench; for a lone seed bridge that bench
                # meant coasting adrift on our own fork for its whole lifetime (observed live: 70+
                # blocks within the hour of shipping the 2h bench).
                self.consensus.peer_fetch_succeeded(peer)
                new_blocks = prefetch.get("batch")
            return False

        except Exception as e:
            self.logger.error(f"Failed to get blocks after {from_hash} from {peer}: {e}")
            self._reject_heaviest_tip()
            return True

    def _rollback_one_for_reorg(self, ancestor=None) -> bool:
        """REORG leg of emergency sync: the MEASURED verdict says our chain diverged (see emergency_mode
        — one donor's word no longer reaches here) — revert ONE block (reinserting its txs into the
        mempool; revert symmetry: a reorg must re-mine user transactions, never drop them) and let the
        next pass retry the donor one block deeper. Returns True when the emergency pass should END: the
        per-burst rollback budget is exhausted, no local parent remains (snapshot-bootstrapped node), the
        finality floor refused the reorg — each rejects the tip so we don't spin on it — or the tip has
        reached the verdict's common ANCESTOR and the donor still disagrees, which means the verdict is
        stale or the donor is lying, and rolling PAST the proven ancestor is pure loss either way (the old
        leg probed blindly one block at a time and could burn the whole 40-block budget on a bad donor)."""
        if ancestor is not None and int(self.memserver.latest_block["block_number"]) <= int(ancestor):
            self.logger.warning(f"Reorg leg reached the measured common ancestor {ancestor} and the donor "
                                f"still disagrees — refusing to roll deeper; striking the tip")
            self.memserver.rollbacks = 0
            self._reject_heaviest_tip()
            return True
        if self.memserver.rollbacks >= self.memserver.max_rollbacks:
            self.logger.error(
                f"Rollbacks exhausted ({self.memserver.rollbacks}/{self.memserver.max_rollbacks})")
            self.memserver.rollbacks = 0
            self._reject_heaviest_tip()
            return True

        # capture the tip's txs BEFORE reverting so a reorg re-mines them instead of dropping them.
        reverted_txs = self.memserver.latest_block.get("block_transactions", []) or []
        try:
            # depth = this block's 1-based position in the current burst (rollbacks done so far + 1),
            # so the reorg telemetry records the deepest single reorg run of the day, not just totals.
            self.memserver.latest_block = rollback_one_block(logger=self.logger,
                                                             block=self.memserver.latest_block,
                                                             depth=self.memserver.rollbacks + 1)
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
            # DO NOT BENCH THE TIP HERE. _reject_heaviest_tip() is the Sybil-stall / weight-DoS guard: it
            # exists for a peer that ADVERTISES a heavier chain it cannot actually serve. A FinalityViolation
            # is the opposite situation — the chain is real and genuinely heavier, and the failure is OURS
            # (we may not legally roll back across our own finalized prefix). Benching it conflates the two
            # and is actively harmful: rejected_tips feeds fork-choice, so the heavier chain goes INVISIBLE,
            # _fork_state() degrades from DEAD_FORK to UNKNOWN ("ancestor=None"), and every recovery route
            # keyed on knowing a heavier chain exists — including the floor-crossing re-anchor above — is
            # disarmed. The node then blinds itself to the exact chain it needs.
            #
            # Observed live 2026-08-04: after the 2-2 split at h20352 the finality refusal repeated until
            # "Excluding unreachable heavier-advertised tip e43691b2b7a1 (weight-DoS guard, failure #4)",
            # after which fork state read `unknown (ancestor=None, probes=159)` and the node sat wedged with
            # every remedy silently unreachable. This is the "a wrong bench makes the true chain invisible"
            # failure the snapshot_bootstrap docstring warns about, reached from the other direction.
            #
            # Leaving it visible costs a re-entry into emergency_mode per pass, which is already rate-limited
            # and is exactly what lets the DEAD_FORK verdict form and the escalation fire.
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

    def _benched_tip_hashes(self):
        """Tip hashes currently advertised by peers whose chain is benched (see consensus.reject_tip).
        Resolved fresh each call from the live status pool, because the whole point is that a benched
        peer's hash CHANGES every block — a cached set would go stale immediately."""
        try:
            return {h for p, h in self.consensus.block_hash_pool.copy().items()
                    if h and self.consensus.tip_source_benched(p)}
        except Exception:
            return set()

    def _reject_heaviest_tip(self):
        """AUDIT FIX (weight-DoS): exclude the advertised-heaviest tip we just FAILED to obtain a valid
        heavier chain for, so a peer advertising a bogus huge cumulative_weight cannot keep looping us
        into emergency-mode/rollback. The exclusion is bounded + auto-cleared (consensus_loop), so a
        transiently-unreachable REAL heavier tip is retried later."""
        hh = self.consensus.heaviest_block_hash
        if hh and hh != self.memserver.latest_block["block_hash"]:
            # Pass the donor we actually dialled (when known) so the strike lands on the peer that failed
            # to serve, not on every honest peer advertising the same tip — see consensus_loop.reject_tip.
            n = self.consensus.reject_tip(hh, donor_ip=self._last_sync_donor_ip)
            self.logger.warning(f"Excluding unreachable heavier-advertised tip {hh[:12]} "
                                f"(weight-DoS guard, failure #{n})")
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
        pool = self.memserver.transaction_pool.copy()
        selected = []
        # ONE ledger for the whole pass. This used to be validate_all_spending(selected + [tx]) per tx,
        # which re-derived the entire accepted prefix every time and made the loop O(P^3) — 20.6 s at
        # P=800, once a second, on this thread. ledger.add() only commits a tx that passes, so a
        # rejected one leaves the running totals exactly as re-deriving from `selected` did.
        ledger = SpendingLedger()
        for tx in pool:
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
                ledger.add(tx)
            except Exception as e:
                # LOG-ONCE per txid: these exclusions recur on every ~1s candidate pass (a lingering
                # duplicate/stale tx is re-validated and re-excluded each time), so logging one line per
                # tx per block buries the log. Surface each excluded txid once; the prune below re-arms
                # it if the same id ever leaves the pool and returns.
                txid = tx.get("txid")
                if txid not in self._excluded_logged:
                    self.logger.info(f"Candidate excludes pool tx {str(txid)[:16]}: {e}")
                    self._excluded_logged.add(txid)
                continue
            selected.append(tx)
        # keep the log-once set bounded and self-healing: drop ids no longer in the pool (mined or aged
        # out) so a genuinely fresh occurrence of the same id logs again.
        self._excluded_logged &= {tx.get("txid") for tx in pool}
        return selected

    def _reserved_tx_pending(self, recipient, target_epoch):
        """True if our own reserved tx for this epoch is already waiting in the pool. Without this
        check the ~1s core loop mints a fresh duplicate (new nonce -> new txid) every iteration
        until the first copy is mined; the stragglers then fail validation in later candidates and
        poison block production. A `duty` tx has no top-level target_epoch — it is keyed by the
        epoch its max_block lands in."""
        # .copy(): other threads append to the live lists; iterating a snapshot avoids skipped
        # elements (a false negative here mints the duplicate this guard exists to prevent).
        for tx in self.memserver.transaction_pool.copy():
            if tx.get("recipient") != recipient or tx.get("sender") != self.memserver.address:
                continue
            if recipient == "duty":
                if epoch_of(tx.get("max_block", 0)) == target_epoch:
                    return True
            elif isinstance(tx.get("data"), dict) and tx["data"].get("target_epoch") == target_epoch:
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
            block_reward=get_block_reward(),
            parent_cumulative_fees=parent.get("cumulative_fees", 0),
            parent_cumulative_weight=parent.get("cumulative_weight", 0),
            block_weight=block_fork_weight(bonded_registry, block_number),
            # preserve the REMOTE block's own chain_id label (informational, not hashed) so the rebuilt
            # block stays byte-identical to what the peer sent; the hash is chain_id-invariant either way.
            chain_id=block.get("chain_id", CHAIN_ID),
            # PASS THE COMMITTED STATE + EXEC ROOTS THROUGH (do NOT recompute them here). The deterministic
            # rebuild re-derives winner/reward/weight to catch forgery, but state_root / exec_root /
            # exec_cursor are the producer's committed claims and must survive the rebuild UNCHANGED so an
            # honest block's reconstructed hash still equals its claimed hash. Whether those claims match OUR
            # state is a SEPARATE question, enforced explicitly in verify_block — conflating it with the hash
            # check would mislabel a state divergence as a "forged/corrupt block".
            state_root=block.get("state_root"),
            exec_root=block.get("exec_root"),
            exec_cursor=block.get("exec_cursor"))

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

        # Body write FIRST (idempotent, safe to redo on replay): the fsynced segment record +
        # locator must exist before block_index references it. The parent's child pointer is no
        # longer persisted — child_hash is DERIVED from the number->hash index at read time
        # (block_ops._stamp_child), which the append-only segment store requires and which stays
        # correct across reorgs by construction.
        save_block(block, self.logger)

        # ATOMIC state mutation: tx index + balances + treasury + produced + totals + the
        # block_index 'applied' marker all commit together or not at all, so a crash mid-apply
        # leaves the block UNapplied (and block_already_indexed lets the replay re-apply it
        # cleanly) instead of double-crediting the reward (audit LO-1/CO-4).
        with kv_ops.write_txn():
            index_transactions(block=block,
                               sorted_transactions=sorted_transactions,
                               logger=self.logger)

            # EXEC SUMMARY (settle-with-proof binding, kv_ops.exec_summary_put): derive the call leaves +
            # the records-inertness bit from the body HERE, where the body is present by definition, so the
            # settle branch never has to re-read a prunable body (a snapshot re-anchor wipes bodies
            # wholesale, so no depth fence can make that read fleet-safe). Commits atomically with the
            # block; reverted in rollback_one_block. Not in any block hash preimage.
            try:
                from execnode.stark.calls_commit import block_summary
                from protocol import EXEC_SUMMARY_RETENTION, SETTLE_PROOF_RECORDS
                _inert, _calls = block_summary(block)
                _h = block["block_number"]
                # RECORDS-HALF EFFECTS (SETTLE_PROOF_RECORDS): derived HERE, for the same reason the call
                # leaves are — this is the one place the body is present by definition. Without it the
                # settle branch has no prune-safe way to know WHICH records a span moved, only the `inert`
                # boolean saying THAT some did, and a boolean cannot be bound against. Gated because it
                # changes what is written into `meta`, which feeds the L1 state root; see protocol.py.
                _rec, _derivable, _dcarry = (None, None, None)
                if SETTLE_PROOF_RECORDS:
                    from execnode.stark.records_bind import block_records_effects
                    _rec, _derivable = block_records_effects(block)
                    # PRESENCE-DIVIDEND ACCRUAL — the LAST records movement that was not derivable, and the
                    # single largest reason a span was refused: measured over one day on betanet-15, "span
                    # crosses a dividend epoch boundary" was 55 of 146 refusals. It moves records on a
                    # boundary block with NO transaction at all, so the tx scan above can never see it.
                    #
                    # It IS derivable, because the accrual is a pure function of COMMITTED L1 state:
                    # dividend_inflow_get(E) and weights_at_epoch(E), which is exactly what the exec node
                    # reads over HTTP before calling state.accrue_dividend_epoch. The one input that is not
                    # on L1 is the exec node's carried sub-unit remainder, so we chain it ourselves: each
                    # boundary stores its own carry-out in its exec summary and reads the previous
                    # boundary's as carry-in.
                    #
                    # STORED IN THE SUMMARY ITSELF, deliberately — not in a new meta row. exec_summary_put
                    # already commits inside this atomic write txn and rollback_one_block already reverts
                    # it, so the carry chain inherits an EXACT rollback inverse. A separate accumulator
                    # would have needed its own, and "rollback_one_block is not the inverse of
                    # incorporate_block for a meta row" is precisely what corrupted the L1 root at h4260.
                    #
                    # FAILS CLOSED at every edge: a missing previous summary (fresh snapshot anchor, GC),
                    # a weights_at_epoch that refuses because idle-GC pruned the recert rows it replays, or
                    # any other error marks the block non-derivable and it rides the bonded quorum.
                    _E = _dividend_epoch_for(_h)
                    if _derivable and _E is not None:
                        _rec, _derivable, _dcarry = self._accrual_effects(_E, _h, _rec)
                kv_ops.exec_summary_put(_h, _inert, _calls, records=_rec, derivable=_derivable,
                                        div_carry=_dcarry)
                # O(1) rolling GC: drop the one height falling out of the retention window. These live in
                # the `meta` sub-DB, which IS snapshot-carried, so an unbounded set would grow with chain
                # length and bloat every snapshot. Nothing a proof could use is lost — a span reaching
                # further back than SETTLE_PROOF_MAX_SPAN is refused by the cap anyway. The dropped height
                # is far below the reorg window, so rollback never needs to restore it.
                if _h > EXEC_SUMMARY_RETENTION:
                    # JOURNAL then prune, so rollback_one_block can restore it. Without this the pair
                    # put(h)+del(h-RETENTION) here vs a lone del(h) on rollback punched a PERMANENT hole in
                    # the summary window on every reorg — which makes settle-with-proof validation reject a
                    # block this node's peers accept, and makes two honest nodes hold different execsum sets.
                    _old_h = _h - EXEC_SUMMARY_RETENTION
                    kv_ops.execsum_revert_put(_h, _old_h, kv_ops.exec_summary_get(_old_h))
                    kv_ops.exec_summary_del(_old_h)
            except Exception as e:
                # HONEST CAVEAT: swallowing is only safe because block_summary is a PURE function of the
                # body, so a genuine (deterministic) failure hits every node identically and the DA binding
                # fails-closed identically — no fork. A NON-deterministic failure (OOM) would leave one node
                # refusing a settle-with-proof its peers accept -> fork.
                #
                # Precise gate: only a NON-DETERMINISTIC (resource) failure can fork, and only once trustless
                # settlement is ON. A DETERMINISTIC failure (a pure-function bug in block_summary) hits every
                # node identically -> all lack the summary -> a proof over that span fails-CLOSED on every
                # node -> the settle-with-proof is uniformly rejected and the bonded quorum settles that span
                # -> safe. Swallowing it is correct (never halt the chain on a uniform bug). A MemoryError is
                # the one failure that differs between nodes (one OOMs, a peer does not), which would leave
                # the OOM node lacking a summary its peers hold -> it rejects a proof they accept -> fork. So
                # ONLY that case, and ONLY under the flag, is FAIL-STOP: re-raise, abort the block, and let
                # the node re-sync (getting the summary on replay) instead of silently diverging. See
                # settlement_justified's docstring + doc/zk-settlement-completion.md.
                from protocol import SETTLE_PROOF_TRUSTLESS
                self.logger.error(f"exec summary for block {block.get('block_number')} failed: {e}")
                if SETTLE_PROOF_TRUSTLESS and isinstance(e, MemoryError):
                    raise

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

            # IDLE-ACCOUNT GC (consensus, doc in ops/gc_ops.py): at epoch boundaries, sweep
            # long-lapsed empty account docs + ancient recert rows — fixed position in the txn so
            # every node mutates identically; revert-safe via the node-local gc_revert record.
            from ops.gc_ops import apply_idle_gc
            gc_stats = apply_idle_gc(block["block_number"], self.logger)
            if gc_stats["accounts"] or gc_stats["rows"]:
                self.logger.info(f"Idle GC at block {block['block_number']}: "
                                 f"{gc_stats['accounts']} empty account(s), {gc_stats['rows']} recert row(s)")

            index_block_number(block)  # the applied marker, atomic with the state above

        # Advance the tip pointer file only AFTER the atomic state commit. A crash before this
        # just leaves a stale tip that re-syncs forward; block_already_indexed prevents re-apply.
        set_latest_block_info(latest_block=block, logger=self.logger)

        # ENFORCED FINALITY (#17 step 1, two-floor model since 2026-08-17): advance BOTH persisted floors.
        # `finalized_height` (depth) keeps its cadence for everything latency-sensitive; `hard_finality`
        # (FFG quorum + wide backstop) is what rollback refuses to cross. Crash-conservative as before: a
        # crash between the block commit above and these writes leaves the floors one behind (never
        # ahead) and they re-advance on the next block.
        # The floor is the DEEPER (higher) of two guarantees: the CORROBORATED time/depth floor
        # (tip - finality_depth, advanced only while the peer-majority tip lies on OUR canonical chain —
        # see _depth_floor_corroborated: a node producing alone on a minority fork must never self-finalize
        # it, which is how a partition wedged a node permanently below its own floor), and the FFG
        # checkpoint (block E*EPOCH_LENGTH that a >2/3 bonded-seat quorum attested, it AND its child —
        # OBJECTIVE, accountable, slashable).
        #
        # HISTORY: an earlier formula folded ffg into finalized_height itself, where — as its own comment
        # eventually measured — ffg_final <= tip - 60 < depth_final = tip - [45..59] meant the FFG term
        # could NEVER win the max() and quorum finality was purely observational. The enforced floor was a
        # 45-block local observation, and treating THAT as un-crossable is what turned every deeper fork
        # into a floor-crossing wedge recovery (2026-08-17: eight in one day, two archive truncations).
        # Now FFG is the un-crossable floor and depth is cadence, which is what each actually is. The old
        # warning stands and is honoured: FFG enforcement is gated on _depth_floor_corroborated (a real
        # liveness/partition signal), never on heaviest_block_hash.
        # TWO-FLOOR ADVANCE (protocol.FINALITY_HARD_BACKSTOP doc). finalized_height keeps its depth cadence
        # — it feeds the exec layer, pruning, snapshots and status, and its latency must not move — but it
        # is no longer what rollback refuses to cross. The UN-CROSSABLE floor is hard_finality: the
        # FFG-finalized checkpoint (>2/3 bonded seats attested it AND its child — reverting it means
        # slashable equivocation) folded with the wide liveness backstop (tip - FINALITY_HARD_BACKSTOP), so
        # a stalled committee bounds reorg exposure at an hour instead of unbinding it entirely. The old
        # formula folded ffg into finalized_height where, as its own comment measured, it could NEVER win
        # the max() — quorum finality was observational. Now it is the thing rollback enforces.
        depth_final = block["block_number"] - self.memserver.finality_depth
        ffg_final = int(getattr(self.memserver, "ffg_finalized", 0) or 0)
        backstop_final = block["block_number"] - FINALITY_HARD_BACKSTOP
        if not self._depth_floor_corroborated():
            # UNCORROBORATED TIP (minority side of a partition, or solo on a fork): NO floor may advance.
            # FFG's justification denominator applies an INACTIVITY LEAK (INACTIVITY_WINDOW = 3 epochs), so
            # on the minority side of a partition lasting >3 epochs the absent majority validators leak OUT
            # of the denominator, the minority's own committee becomes >2/3 of the "active" stake, and it
            # FFG-finalizes its OWN fork. hard_finality is the enforced, un-crossable floor, so on heal that
            # node could never roll back to rejoin the canonical chain — a self-inflicted permanent wedge.
            # The gate matters MORE now that the ffg term is load-bearing, not less.
            depth_final = 0
            ffg_final = 0
            backstop_final = 0
        # READ THE PERSISTED FLOOR, not the memserver mirror: rollback_one_block now legally LOWERS
        # finalized_height when a reorg crosses the depth floor, and max()ing against a stale high mirror
        # here would resurrect the old branch's floor one block later, silently re-raising what the
        # rollback just lowered. The mirror is refreshed below either way.
        prev_depth = get_finalized_height()
        new_final = max(prev_depth, depth_final)
        if new_final > prev_depth:
            set_finalized_height(new_final)
        self.memserver.finalized_height = new_final
        prev_hard = get_hard_finality()
        new_hard = max(prev_hard, ffg_final, backstop_final)
        if new_hard > prev_hard:
            set_hard_finality(new_hard)

        # lazy NODE-LOCAL cleanup: idle-GC revert records below finality can never be needed
        # (rollback refuses to cross the floor). Epoch boundaries only — negligible either way.
        if block["block_number"] % EPOCH_LENGTH == 0:
            from ops.gc_ops import prune_local_revert_records
            prune_local_revert_records(self.memserver.finalized_height)
            try:
                kv_ops.execsum_revert_prune(self.memserver.finalized_height)
                kv_ops.attest_memo_prune(self.memserver.finalized_height // EPOCH_LENGTH - 2)
            except Exception:
                pass

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
        if n <= 0:
            return
        # A node with NO checkpoint cannot be re-anchored to, which is how the heaviest chain ends up
        # unreachable and the network fails to converge on it. So the interval is the NORMAL cadence, not
        # the only trigger: if we are currently advertising nothing, take one as soon as a height is
        # safely final, rather than waiting up to a full interval.
        if n % snapshot_ops.CHECKPOINT_INTERVAL != 0:
            # A node advertising NO checkpoint cannot be re-anchored to, which is how the heaviest chain
            # becomes unreachable and the network stops converging on it. So the interval is the normal
            # cadence, not the only trigger: while we have nothing to offer, capture far more often.
            # (A capture is only ADVERTISED once its height is final — latest_final_checkpoint_height —
            # so taking one at the tip is safe; a reorged-away capture is simply never published.)
            try:
                if snapshot_ops.list_checkpoint_heights():
                    return
            except Exception:
                return
            if n % CHECKPOINT_CATCHUP_EVERY != 0:
                return
        try:
            snapshot_ops.persist_checkpoint(height=n, block_hash=block["block_hash"],
                                            protocol=self.memserver.protocol,
                                            version=self.memserver.version)
            self.logger.warning(f"State checkpoint captured at height {n} (rolling-node sync)")
        except Exception as e:
            self.logger.error(f"State checkpoint at height {n} failed (non-fatal): {e}")

    def update_ffg_and_attest(self):
        """FFG (#6): refresh the committee-attested finalized checkpoint (folded into the enforced
        finality floor by incorporate_block). Attestation EMISSION lives in maybe_epoch_duty — the
        merged per-epoch duty tx (doc/consensus-aggregation.md). Best-effort; never raises."""
        try:
            epoch = epoch_of(self.memserver.latest_block["block_number"])
            self.memserver.ffg_finalized = ffg_finalized_checkpoint(epoch)
        except Exception as e:
            self.logger.error(f"FFG refresh failed: {e}")

    def maybe_epoch_duty(self):
        """MERGED EPOCH DUTY (doc/consensus-aggregation.md): if this validator holds a seat in the
        current epoch's duty committee, broadcast ONE fee-exempt `duty` tx carrying every section
        still due — FFG attest (this epoch X), RANDAO commit (X+2), RANDAO reveal (X+1) — under a
        single ML-DSA signature (replaces the three separate attest/commit/reveal txs: 3N -> N,
        and the committee bounds N to O(DUTY_COMMITTEE_SEATS) at any validator count). RETRIED
        while windows last: an on-chain section stops being offered, so a raced duplicate section
        just fails validation harmlessly. Secrets live in memserver.randao_secrets (in-memory: an
        unrevealed secret after a restart is a wasted commit, harmless). Best-effort; never raises."""
        try:
            me = self.memserver.address
            if me not in get_bonded_registry():
                return  # only bonded validators carry duties
            latest = self.memserver.latest_block
            X = epoch_of(latest["block_number"])
            from ops.block_ops import duty_committee_for_epoch
            if me not in duty_committee_for_epoch(X):
                return  # no seat this epoch — the committee is resampled from beacon(X+1) next epoch
            if self._reserved_tx_pending("duty", X):
                return  # our duty tx is already in flight — don't mint a duplicate every loop
            kd = self.memserver.keydict

            # the merged tx lands exactly at max_block; every section's window must admit it.
            reveal_hi = (X + 1) * EPOCH_LENGTH - FINALITY_DEPTH - 1
            epoch_hi = (X + 1) * EPOCH_LENGTH - 1
            # PROPAGATION HEADROOM (see RESERVED_TX_MARGIN): tip+5 gave the duty tx ~30s to reach every
            # producer, and a producer that has it builds a different block than one that does not — this
            # forked betanet-12 at h12605. Aim further ahead, but never past a deadline a due section
            # needs: the epoch always, and the RANDAO reveal window when a reveal is actually pending.
            # The reveal clamp applies ONLY while that deadline is still ahead of us — otherwise a
            # long-passed reveal_hi would drag max_block below the tip and suppress the whole duty tx
            # (attest and commit included), which tip+5 never did.
            _e_reveal = X + 1
            _secret_due = self.memserver.randao_secrets.get(_e_reveal)
            _reveal_due = bool(_secret_due and kv_ops.commit_get(me, _e_reveal) is not None
                               and _secret_due not in kv_ops.reveals_for_epoch(_e_reveal))
            _hi = epoch_hi
            if _reveal_due and reveal_hi > latest["block_number"]:
                _hi = min(epoch_hi, reveal_hi)
            # WINDOWED DUTY (DUTY_WINDOW_ACTIVATION): land anywhere in [tip+8, deadline] instead of
            # exactly at one height. The exact landing was the last organic fork class — a producer
            # one gossip-hop ahead included its own duty and split the fleet (every 2026-08-19 seed).
            # min_block gives the tx a full inclusion delay to reach every producer; max_block keeps
            # every deadline clamp, so the section semantics (all bound to max_block) are unchanged.
            # Builder-side height gate only: validation accepts windowed duties from deploy, so the
            # mixed-version window during the update wave can never reject a block.
            _windowed = latest["block_number"] + 1 >= DUTY_WINDOW_ACTIVATION
            if _windowed:
                min_block = latest["block_number"] + TX_INCLUSION_DELAY
                max_block = _hi
                if min_block > max_block:
                    return  # epoch tail — duties resume next epoch
            else:
                min_block = 0
                max_block = min(latest["block_number"] + DUTY_TX_MARGIN, _hi)
                if max_block <= latest["block_number"]:
                    return  # epoch tail — duties resume next epoch

            attest = commit = reveal = None
            if X >= 1 and not kv_ops.attestation_exists(X, me):
                checkpoint_hash = get_block_hash_by_number(X * EPOCH_LENGTH)
                if checkpoint_hash:
                    # EQUIVOCATION SELF-PROTECTION. target_hash is re-read from the local tip on every
                    # pass while our attestation has not landed, so a reorg that rewrites this epoch's
                    # checkpoint would make us sign a SECOND attestation for the SAME epoch with a
                    # DIFFERENT hash. Both are gossiped; together they are a valid, unforgeable
                    # equivocation proof and anyone can slash our bond for a reorg we did not cause. The
                    # mempool guard below cannot prevent it (the first tx leaves the pool when max_block
                    # passes, and a restart forgets it entirely), so consult a PERSISTED memo instead.
                    _prev = kv_ops.attest_memo_get(X)
                    if _prev is not None and _prev != checkpoint_hash:
                        # Already signed a different hash for this epoch: attesting again is slashable.
                        # Skip the attest section — the commit/reveal sections below are unaffected, and
                        # we simply sit out this epoch's vote rather than sign a self-slashing pair.
                        self.logger.warning(
                            f"Epoch {X}: NOT re-attesting — already signed checkpoint {_prev[:12]}… and the "
                            f"local checkpoint is now {checkpoint_hash[:12]}… (a reorg rewrote it). Signing "
                            f"both would be a slashable equivocation against ourselves.")
                    else:
                        if _prev is None:
                            # WRITE BEFORE SIGN: a crash after this costs at most a skipped attestation;
                            # a crash after signing but before the write would let us re-sign a different
                            # hash — the exact slashable event this guards.
                            kv_ops.attest_memo_put(X, checkpoint_hash)
                        attest = {"target_epoch": X, "target_hash": checkpoint_hash}
            e_commit = X + 2
            if kv_ops.commit_get(me, e_commit) is None:
                secret = self.memserver.randao_secrets.get(e_commit) or _secrets.token_hex(32)
                self.memserver.randao_secrets[e_commit] = secret
                commit = {"target_epoch": e_commit, "commitment": beacon_commitment(secret)}
                # PERSIST (atomic replace) + prune to epochs that can still be revealed (>= X+1). A
                # restart between commit and reveal used to waste the commit — routine now that update
                # waves restart the whole fleet; see memserver.randao_secrets for the load side.
                try:
                    self.memserver.randao_secrets = {e: s for e, s in self.memserver.randao_secrets.items()
                                                     if e >= X + 1}
                    _rs_path = f"{get_home()}/private/randao_secrets.json"
                    with open(_rs_path + ".tmp", "w") as _rs:
                        json.dump({str(k): v for k, v in self.memserver.randao_secrets.items()}, _rs)
                    os.replace(_rs_path + ".tmp", _rs_path)
                except Exception as _e:
                    self.logger.warning(f"could not persist RANDAO secrets: {_e}")
            e_reveal = X + 1
            secret = self.memserver.randao_secrets.get(e_reveal)
            if (secret and kv_ops.commit_get(me, e_reveal) is not None
                    and max_block <= reveal_hi
                    and secret not in kv_ops.reveals_for_epoch(e_reveal)):
                reveal = {"target_epoch": e_reveal, "secret": secret}

            if not (attest or commit or reveal):
                return  # every duty already on-chain
            tx = construct_duty_tx(kd, max_block, attest=attest, commit=commit, reveal=reveal,
                                   min_block=min_block)
            result = self.memserver.merge_transaction(tx, user_origin=True)
            if result and result.get("result"):
                self.logger.info(f"Epoch duty {X}: attest={bool(attest)} commit={bool(commit)} "
                                 f"reveal={bool(reveal)} (ffg_finalized={self.memserver.ffg_finalized})")
        except Exception as e:
            self.logger.error(f"Epoch duty failed: {e}")

    def _restore_canonical_chain(self, old_index, anchor, source):
        """Reconcile our retained block bodies against the chain we just adopted, and refill what is
        canonical and missing. Returns the block that history is now contiguous from (the new earliest).

        Thin executor over ops/canonical_restore.plan — the decision is pure and tested there; this walks
        its answer against LMDB, the segment store and the donor. Ordering is chosen so an interruption at
        any point leaves a strictly-better state than before it ran:
          1. re-put the deep index rows the windowed import dropped (restores get_block_number depth);
          2. resolve any UNDETERMINED range (fork deeper than the donor's index window) by parent-hash
             walk from the lowest named block, fetching from the donor as needed;
          3. fetch the missing canonical bodies within the ROLLBACK WINDOW synchronously — the core loop
             needs those before it validates another block;
          4. unreference fork bodies: only a body at a height whose canonical hash we can NAME, and which
             differs, is ever removed. A body we cannot place is kept — deleting history on the strength
             of "I can't prove it" is the failure this exists to end;
          5. on an ARCHIVE node, hand the deep remainder (everything else canonical-and-missing, then the
             unnamed chain below our lowest index row, walked by parent_hash down to genesis) to a
             background thread. Tens of thousands of fetches must not stall block production, and the
             result is the same: the archive comes back whole, or as whole as any donor can make it —
             and whatever is still missing is re-requested at the next re-anchor, because the plan is
             recomputed from what is actually on disk every time."""
        from ops import canonical_restore as CR
        from ops.block_ops import get_block_number as _gbn
        archive = bool(getattr(self.memserver, "archive", False))
        C = int(anchor.get("block_number", 0))
        new_index = {h: bh for h, bh in kv_ops.block_by_num_items() if h <= C}
        has_body = lambda bh: kv_ops.block_loc_get(bh) is not None
        p = CR.plan(old_index, new_index, C, has_body)
        for n in p.notes:
            self.logger.warning(f"Canonical restore: {n}")
        self.logger.warning(f"Canonical restore: anchor {C}, fork point {p.fork_point}, imported index floor "
                            f"{p.new_floor}; {p.kept} local bodies canonical, {len(p.missing)} missing, "
                            f"{len(p.reput)} deep index rows to re-put"
                            + (f", undetermined {p.undetermined}" if p.undetermined else ""))

        # 1. deep index rows
        if p.reput:
            n = kv_ops.block_index_put_many(p.reput)
            self.logger.warning(f"Canonical restore: re-put {n} deep number<->hash rows the import dropped")

        # 2. undetermined range: walk parent_hash down from the lowest NAMED block. Each step names one
        #    more height; a local body serves the walk, otherwise the donor does. Stops at the first
        #    height whose hash equals our old index (that IS the fork point — everything below is ours),
        #    or when neither we nor the donor have the body.
        canonical = dict(p.canonical)
        missing = list(p.missing)
        if p.undetermined:
            lo, hi = p.undetermined
            cur_h = hi + 1
            cur_hash = canonical.get(cur_h)
            walked = 0
            while cur_hash and cur_h > lo:
                body = get_block(cur_hash) or None
                if not body:
                    body = asyncio.run(snapshot_ops.fetch_block(source, self.memserver.port, cur_hash))
                    if body and body.get("block_hash") == cur_hash:
                        save_block(body, logger=self.logger)
                    else:
                        self.logger.warning(f"Canonical restore: cannot resolve block {cur_h - 1} — neither we "
                                            f"nor the donor hold block {cur_h}; deeper chain stays as it was")
                        break
                ph = body.get("parent_hash")
                if not ph:
                    break
                cur_h -= 1
                canonical[cur_h] = ph
                walked += 1
                if not has_body(ph):
                    missing.append((cur_h, ph))
                if old_index.get(cur_h) == ph:
                    for h, bh in old_index.items():          # the fork point: our own index is authoritative below
                        if h < cur_h:
                            canonical[h] = bh
                            if not has_body(bh):
                                missing.append((h, bh))
                    p.fork_point = cur_h
                    self.logger.warning(f"Canonical restore: fork point {cur_h} found by parent-hash walk after "
                                        f"{walked} steps; old index adopted below it")
                    break
                cur_hash = ph
            deep = sorted((h, bh) for h, bh in canonical.items() if p.new_floor is not None and h < p.new_floor)
            if deep:
                kv_ops.block_index_put_many(deep)

        # 3. the rollback window, synchronously
        tail_depth = REWARD_WINDOW + 2 * EPOCH_LENGTH + FINALITY_DEPTH
        missing = sorted(set(missing), reverse=True)
        near = [(h, bh) for h, bh in missing if h >= C - tail_depth]
        deep_missing = [(h, bh) for h, bh in missing if h < C - tail_depth]
        fetched = 0
        for h, bh in near:
            body = asyncio.run(snapshot_ops.fetch_block(source, self.memserver.port, bh))
            if body and body.get("block_hash") == bh:
                save_block(body, logger=self.logger)
                fetched += 1
            else:
                self.logger.warning(f"Canonical restore: donor {source} lacks block {h} inside the rollback "
                                    f"window; deeper lookbacks may skip until tail sync")
                break

        # 4. unreference fork bodies — precisely: a body is removed iff we can NAME the canonical block at
        #    its height and it is a different one. Anything we cannot place stays.
        canon_hashes = set(canonical.values())
        purged = 0
        for bh in kv_ops.block_loc_hashes():
            if bh in canon_hashes or bh == anchor.get("block_hash"):
                continue
            body = get_block(bh) or None
            bn = int(body.get("block_number", -1)) if body else -1
            if bn in canonical:
                kv_ops.block_loc_del(bh)
                purged += 1
        self.logger.warning(f"Canonical restore: {fetched}/{len(near)} rollback-window bodies fetched, "
                            f"{purged} fork bodies unreferenced, {len(deep_missing)} deep canonical bodies "
                            f"still missing" + (" — refilling in the background" if archive else
                                                " (rolling node: below retention, not fetched)"))

        # 5. archive: the deep remainder, in the background
        floor = CR.contiguous_floor(canonical, has_body, C)
        lowest_named = min(canonical) if canonical else C
        if archive:
            self._start_deep_fill(source, deep_missing, lowest_named, canonical.get(lowest_named))
        else:
            self._start_tx_reindex()
        return _gbn(floor) or anchor

    def _start_deep_fill(self, source, deep_missing, lowest_named, lowest_named_hash):
        """ARCHIVE: fetch every deep canonical body we can name, then EXTEND the chain downward past our
        lowest index row by parent_hash — that is how a previously-truncated archive gets heights back that
        no index we hold can name any more (this box: 0..6999 after today's imports). Every learned
        (height, hash) is index-put so get_block_number resolves it. Runs in a thread: it is tens of
        thousands of fetches on a truncated archive and must not stall the core loop. Reports progress via
        self._deep_fill_progress; the core loop tick commits earliest_block from it. Ends by starting the
        tx-history reindex, which needs the bodies to exist first."""
        if getattr(self, "_deep_fill_thread", None) and self._deep_fill_thread.is_alive():
            self.logger.warning("Canonical restore: a deep fill is already running; the new plan will be "
                                "picked up at the next re-anchor")
            return
        self._deep_fill_progress = {"fetched": 0, "extended": 0, "done": False, "lowest": lowest_named}

        def _run():
            fetched = failed = 0
            for h, bh in deep_missing:                                # highest first, as planned
                try:
                    body = asyncio.run(snapshot_ops.fetch_block(source, self.memserver.port, bh))
                except Exception:
                    body = None
                if body and body.get("block_hash") == bh:
                    save_block(body, logger=self.logger)
                    fetched += 1
                    self._deep_fill_progress["fetched"] = fetched
                    if fetched % 1000 == 0:
                        self.logger.warning(f"Archive refill: {fetched}/{len(deep_missing)} deep bodies fetched "
                                            f"(at block {h})")
                else:
                    failed += 1
                time.sleep(0.01)
            # extend below the lowest height any index can name, by parent_hash, to genesis
            extended = 0
            cur_h, cur_hash = lowest_named, lowest_named_hash
            while cur_hash and cur_h > 0:
                body = get_block(cur_hash) or None
                if not body:
                    break                                             # the chain of custody is broken here
                ph = body.get("parent_hash")
                if not ph:
                    break
                cur_h -= 1
                if kv_ops.block_loc_get(ph) is None:
                    try:
                        nb = asyncio.run(snapshot_ops.fetch_block(source, self.memserver.port, ph))
                    except Exception:
                        nb = None
                    if not nb or nb.get("block_hash") != ph:
                        self.logger.warning(f"Archive refill: donor {source} lacks block {cur_h}; the archive "
                                            f"is contiguous from {cur_h + 1} — re-requested at the next re-anchor")
                        cur_h += 1
                        break
                    save_block(nb, logger=self.logger)
                kv_ops.block_index_put_many([(cur_h, ph)])
                extended += 1
                self._deep_fill_progress["extended"] = extended
                self._deep_fill_progress["lowest"] = cur_h
                if extended % 1000 == 0:
                    self.logger.warning(f"Archive refill: extended {extended} blocks below the index floor "
                                        f"(at block {cur_h})")
                cur_hash = ph
                time.sleep(0.01)
            self._deep_fill_progress["done"] = True
            self.logger.warning(f"Archive refill finished: {fetched} deep bodies fetched ({failed} unavailable "
                                f"from {source}), chain extended {extended} blocks down to {cur_h}")
            self._start_tx_reindex()

        self._deep_fill_thread = threading.Thread(target=_run, name="archive-refill", daemon=True)
        self._deep_fill_thread.start()

    def _maybe_refill_archive(self):
        """ARCHIVE SELF-REPAIR, without waiting for a re-anchor. If this is an archive node and its history
        does not reach genesis, find a peer whose does — or reaches deeper than ours — and start the same
        background deep fill the re-anchor path uses, walking parent_hash down from our earliest block.

        This is how the archive this box lost on 2026-08-17 (0..56734) comes back: rolling peers still hold
        those bodies until their retention window passes block 0 (~2026-08-20), and after that only another
        archive would. It cannot be done from outside the process (two writers on the live LMDB), so the
        node does it itself. Throttled to one attempt per ARCHIVE_REFILL_EVERY seconds while a gap exists,
        nothing at all otherwise, and never two fills at once."""
        # STATE THE GATES, ONCE. The first deployment of this method produced no output for two full
        # throttle windows and there was no way to tell WHICH silent early-return was taken — the exact
        # "log line instead of a mechanism" failure, inverted: a mechanism with no evidence it runs.
        eb = self.memserver.earliest_block if isinstance(self.memserver.earliest_block, dict) else None
        cur = int((eb or {}).get("block_number") or 0)
        if not getattr(self, "_refill_gates_logged", False):
            self._refill_gates_logged = True
            self.logger.warning(f"Archive refill armed: archive={getattr(self.memserver, 'archive', False)} "
                                f"earliest={cur} peers={len(list(self.memserver.peers))} "
                                f"interval={ARCHIVE_REFILL_EVERY}s")
        if not getattr(self.memserver, "archive", False):
            return
        if cur <= 0:
            return
        if getattr(self, "_deep_fill_thread", None) and self._deep_fill_thread.is_alive():
            return
        now = time.time()
        if now - getattr(self, "_last_refill_try", 0.0) < ARCHIVE_REFILL_EVERY:
            return
        try:
            peers = list(self.memserver.peers)
            if not peers:
                # DO NOT consume the throttle slot on "nothing to try": at boot the peer list is empty for
                # the first seconds, and burning the slot here silently pushed the first real attempt 10
                # minutes out (observed 2026-08-17 20:45 — the refill logged nothing for its first window).
                return
            self._last_refill_try = now

            async def _statuses(ips):
                return await asyncio.gather(*[get_remote_status(ip, logger=self.logger) for ip in ips],
                                            return_exceptions=True)
            raw = asyncio.run(_statuses(peers))
            cands = []
            for ip, st in zip(peers, raw):
                if not isinstance(st, dict) or st.get("chain_id") != CHAIN_ID:
                    continue
                try:
                    pe = int(st.get("earliest_block_height", 10 ** 12))
                except (TypeError, ValueError):
                    continue
                if pe < cur:
                    cands.append((pe, ip))
            if not cands:
                self.logger.info(f"Archive refill: history starts at {cur} and no peer reaches deeper; will retry")
                return
            cands.sort()
            depth, source = cands[0]
            self.logger.warning(f"Archive refill: history starts at {cur}; peer {source} reaches {depth} — "
                                f"filling {cur - max(depth, 0)} blocks in the background")
            self._start_deep_fill(source, [], cur, eb.get("block_hash"))
        except Exception as e:
            self.logger.error(f"Archive refill attempt failed: {e}")

    def _maybe_advance_earliest(self):
        """Core-loop tick: if the background refill has landed deeper bodies, move earliest_block down to
        the new contiguous floor. block_ends.dat is written by the core thread only, so the fill thread
        never touches it. Cheap: a few locator lookups per tick, nothing when no fill is running."""
        prog = getattr(self, "_deep_fill_progress", None)
        if not prog:
            return
        try:
            cur = int((self.memserver.earliest_block or {}).get("block_number") or 0) \
                if isinstance(self.memserver.earliest_block, dict) else 0
            if cur <= 0:
                if prog.get("done"):
                    self._deep_fill_progress = None
                return
            from ops.block_ops import get_block_number as _gbn
            h = cur
            # walk down through what is now present, contiguously
            while h > 0:
                nh = kv_ops.hash_by_number(h - 1)
                if not nh or kv_ops.block_loc_get(nh) is None:
                    break
                h -= 1
            if h < cur:
                blk = _gbn(h)
                if blk:
                    set_earliest_block_info(earliest_block=blk, logger=self.logger)
                    self.memserver.earliest_block = blk
                    self.logger.warning(f"Archive refill: history now contiguous from block {h} (was {cur})")
            if prog.get("done"):
                self._deep_fill_progress = None
        except Exception as e:
            self.logger.error(f"advance-earliest failed: {e}")

    def _start_tx_reindex(self):
        """Rebuild the tx-history index from the canonical bodies on disk, in a background thread,
        resumably. adopt_new_identity wipes tx history because rows for FORK blocks would make the
        at-most-once replay gate reject a legitimate tx that was in both a fork block and its canonical
        replacement — but rows for canonical blocks are correct, and they are what
        /get_transactions_of_account (the thing a user's "where is my money" is answered from) reads.
        Idempotent (tx_index_put is insert-or-ignore) and bounded per step; a marker file makes it resume
        after a restart. Recipient is resolved against the CURRENT alias table, as incorporate does."""
        import json as _json
        from ops.data_ops import get_home
        from ops.block_ops import get_block_number as _gbn
        marker = f"{get_home()}/index/tx_reindex.json"
        if getattr(self, "_tx_reindex_thread", None) and self._tx_reindex_thread.is_alive():
            return
        try:
            start = int(_json.load(open(marker)).get("next", 0))
        except Exception:
            start = 0
        top = int(get_finalized_height() or 0)

        def _run():
            from ops import alias_ops
            h = start
            done = 0
            while h <= top and not getattr(self, "_stop_reindex", False):
                blk = _gbn(h)
                if blk:
                    for tx in blk.get("block_transactions") or []:
                        try:
                            recip = alias_ops.resolve_alias(tx["recipient"]) or tx["recipient"]
                            kv_ops.tx_index_put(txid=tx["txid"], block_number=h, sender=tx["sender"],
                                                recipient=recip)
                        except Exception:
                            pass
                h += 1
                done += 1
                if done % 2000 == 0:
                    try:
                        _json.dump({"next": h}, open(marker, "w"))
                    except Exception:
                        pass
                    time.sleep(0.05)      # yield the write lock to the core loop
            try:
                import os as _os
                if h > top:
                    if _os.path.exists(marker):
                        _os.remove(marker)
                else:
                    _json.dump({"next": h}, open(marker, "w"))
            except Exception:
                pass
            self.logger.warning(f"tx-history reindex: {done} blocks indexed ({start}..{h - 1})")

        self._tx_reindex_thread = threading.Thread(target=_run, name="tx-reindex", daemon=True)
        self._tx_reindex_thread.start()

    def maybe_prune_history(self):
        """ROLLING MODE (non-consensus, opt-in): on a pruned node (memserver.archive == False), delete
        block BODIES and TX-HISTORY rows finalized below their retention windows. STATE + the
        number<->hash indexes are kept,
        so the node keeps validating and serving the beacon/FFG lookbacks. Rolling is now the DEFAULT
        (config.py "archive": False); ARCHIVE nodes skip this entirely. Best-effort + incremental (a meta watermark bounds per-call work); never raises
        into the core loop. See doc/rolling-mode-and-da.md and block_ops.prune_block_bodies."""
        if getattr(self.memserver, "archive", False):     # default matches config.py / memserver
            return
        try:
            finalized = get_finalized_height()
            retention = getattr(self.memserver, "history_retention_blocks", 0)
            prune_block_bodies(finalized, retention, self.logger)
            # TX HISTORY, the other half of rolling mode. Bodies plateau once pruned, but the tx index
            # never did — at 20 tx/block it is ~97% of a ten-year footprint. Its own retention knob
            # (tx_history_retention_blocks) is floored in prune_tx_history_window so a small setting
            # cannot open a replay hole. 0 keeps the floor; archive nodes never reach this code.
            prune_tx_history_window(
                finalized, getattr(self.memserver, "tx_history_retention_blocks", 0), self.logger)
            # THE NUMBER<->HASH INDEX, the last store that grew forever in every mode (144 B/block,
            # ~7 GiB/decade — the dominant term once bodies and tx history are pruned). Its depth is a
            # PROTOCOL rule, not this node's choice: the snapshot payload carries [C-N, C] by the same
            # constants, so rows below the window are outside the snapshot identity and dropping them here
            # cannot move snapshot_hash. Archive nodes never reach this code and keep the full index.
            from protocol import INDEX_RETENTION_NUM, INDEX_RETENTION_HASH
            dropped = kv_ops.prune_index_window(finalized, INDEX_RETENTION_NUM, INDEX_RETENTION_HASH)
            if dropped["num"] or dropped["hash"]:
                self.logger.info(f"Index prune: dropped {dropped['num']} height->hash and "
                                 f"{dropped['hash']} hash->height rows below the retention window")
        except Exception as e:
            self.logger.error(f"Rolling-mode prune failed: {e}")

    def maybe_auto_bond(self):
        """AUTO-BOND (non-consensus, opt-in): if the operator set memserver.auto_bond_percent > 0, route
        that percentage of this node's NEWLY-MINED spendable earnings straight into bonded stake — fully
        unattended auto-compounding of the bonded lane. Best-effort; never raises into the core loop.

        EARNINGS ARE MINED COINS, NOT INCOMING COINS. This measured the rise in our spendable BALANCE,
        which is not the same thing and silently swept up every other credit the account received: a
        transfer someone sent us, a faucet payout, a bridge deposit — and, worst of all, a matured
        `withdraw`, i.e. the coins the operator had just deliberately taken OUT of savings. Unbond half
        your stake and 24h later the withdraw lands, reads as a balance gain, and 99% of it goes straight
        back into savings behind another 24h timelock. The operator's own instruction to leave the lane
        was undone by the compounder, once per unbond, forever.

        `produced` is the consensus counter of what this address actually MINED (open + bonded block
        rewards; increase_produced_count is revert-symmetric, so it tracks reorgs). It moves only when we
        win a slot, which is exactly the "newly-mined earnings" this feature claims to compound. Received
        coins do not touch it, so they can no longer be locked up by a background loop that was never
        asked to touch them.

        We throttle to at most one auto-bond per epoch (a bond isn't per-block unique-keyed, so we self-
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
            mined = int(acc.get("produced", 0)) if acc else 0
            if self.auto_bond_baseline is None:
                self.auto_bond_baseline = mined         # first observation: only FUTURE mining bonds
                return
            if bonded >= BOND_CAP:
                self.auto_bond_baseline = mined         # already at the weight cap — nothing to gain
                return
            gain = mined - self.auto_bond_baseline
            if gain <= 0:
                self.auto_bond_baseline = mined         # nothing mined since (or a reorg took some back)
                return
            to_bond = (gain * int(pct)) // 100
            # never bond past the cap (no extra weight), and never bond what we can't pay the fee for
            to_bond = min(to_bond, BOND_CAP - bonded)
            if to_bond < AUTO_BOND_MIN_RAW or balance < to_bond + MIN_TX_FEE:
                return                                  # accrue (don't rebaseline) until it's worth a tx
            # LIQUIDITY RESERVE, not the half-ceiling (see the module note): bonding is not an outflow,
            # but a node still has to be able to pay fees afterwards — collect_dividend, a treasury
            # vote — and bonded coins are behind a 24h timelock. Never bond the node broke.
            if balance - (to_bond + MIN_TX_FEE) < AUTO_COLLECT_MIN_RAW:
                to_bond = balance - MIN_TX_FEE - AUTO_COLLECT_MIN_RAW      # bond what we can, keep the reserve
                if to_bond < AUTO_BOND_MIN_RAW:
                    return
            # tip+2 gave this tx ~12s to reach every producer before its landing block was built. Blocks are
            # deterministic, so producers that had not seen it yet assembled a DIFFERENT block — an auto-bond
            # minted right after a node restart forked betanet-12 at h12506. See RESERVED_TX_MARGIN.
            max_block = self.memserver.latest_block["block_number"] + RESERVED_TX_MARGIN
            tx = construct_bond_tx(self.memserver.keydict, to_bond, MIN_TX_FEE, max_block)
            self.memserver.merge_transaction(tx, user_origin=True)
            self.last_auto_bond_epoch = epoch
            # Consume only the slice of the mined gain this bond actually covers. When nothing clamped,
            # that is the whole gain; when the cap or the liquidity reserve cut `to_bond` down, the
            # remainder stays claimable on a later pass instead of being written off. The baseline can
            # only ever move FORWARD over mined coins, so a received or withdrawn credit never enters it.
            self.auto_bond_baseline += min(gain, (to_bond * 100) // int(pct))
            self.logger.info(
                f"Auto-bond: bonding {to_bond} raw ({pct}% of {gain} newly MINED) into the bonded lane "
                f"(max_block {max_block})")
        except Exception as e:
            self.logger.warning(f"Auto-bond skipped: {e}")

    def _exec_get(self, path):
        """GET a JSON view from THIS BOX's exec node (localhost:NADO_EXEC_PORT) — the accrual oracle for
        auto-collect. None on any failure (no exec node running here is a normal configuration)."""
        import json as _json
        import os as _os
        import urllib.request as _rq
        try:
            port = int(_os.environ.get("NADO_EXEC_PORT", "9273"))
            with _rq.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
                return _json.loads(r.read(1_000_000))
        except Exception:
            return None

    class _ExecView:
        """Duck-typed stand-in for ExecState built from /exec/accounting's aggregate totals — the shape
        ops/invariants.py reads. The exec node serves only TOTALS (no per-address detail, nothing private),
        so the L1 node reconciles escrows against it without holding exec state or seeing into the pool."""
        def __init__(self, d):
            g = lambda k: int(d.get(k, 0) or 0)
            self.bridge = {"_total": g("bridge_credited")}
            self.withdrawals = {"_total": {"amount": g("bridge_pending")}}
            self.pool_value = g("pool_value")
            self.pool_fees = g("pool_fees")
            self.unshield_withdrawals = {"_total": {"amount": g("unshield_pending")}}
            self.dividend = {"_total": g("dividend_accrued")}
            self.dividend_withdrawals = {"_total": {"amount": g("dividend_pending")}}
            self.div_carry = g("div_carry")

    def maybe_check_invariants(self):
        """CONSERVATION INVARIANTS (ops/invariants.py) — reconcile supply against emission and every escrow
        against what the exec layer says it owes. Roughly ten separate mint/drain bugs have shipped here,
        all of the same shape: a value that was proven or validated but never authorised against a
        conservation rule. These make the CLASS self-announcing rather than the instance findable.

        Runs inside the node (no external step — everything ships with the node) once per
        INVARIANT_CHECK_BLOCKS, because it scans the whole account table. The result is cached on the
        memserver so `/invariants` can serve it without rescanning.

        NEVER raises and NEVER halts. An invariant is a detector, not a consensus rule: a false positive
        that stopped block production would be a worse bug than the one it was hunting. A violation is a
        loud ERROR log — the operator's signal to stop trusting balances until it is explained."""
        from protocol import INVARIANT_CHECK_BLOCKS
        try:
            height = self.memserver.latest_block["block_number"]
            if height % INVARIANT_CHECK_BLOCKS:
                return
            from ops import invariants, kv_ops
            from ops.account_ops import get_account
            # Pull the exec layer's AGGREGATE owed-value figures from this box's exec node. Without it only
            # the L1 supply invariant can run — and the escrow checks (including the shielded one, the
            # whole point) would silently not execute. check_all reports those as skipped rather than
            # letting a bare ok=true imply they passed.
            acct = self._exec_get("/exec/accounting")
            exec_state = self._ExecView(acct) if acct else None
            self.memserver.exec_state_view = exec_state
            ok, results = invariants.check_all(kv_ops.iter_accounts, kv_ops.totals_get(),
                                               get_account, exec_state)
            self.memserver.invariant_report = {"height": height, "ok": ok, "checks": results}
            if not ok:
                for r in results:
                    if not r.get("ok"):
                        self.logger.error(f"CONSERVATION INVARIANT VIOLATED at height {height}: {r}")
        except Exception as e:
            # A detector that takes the node down defeats its own purpose.
            self.logger.warning(f"invariant check skipped: {e}")

    def maybe_auto_collect(self):
        """AUTO-COLLECT (default on, memserver.auto_collect_dividend): once per epoch, sweep this node's
        accrued presence dividend — but only when the sweep is worth its fee. The LOCAL exec node is the
        accrual oracle: we read our exact accrued balance and only send the fee-burning `collect_dividend`
        blob once it reaches AUTO_COLLECT_MIN_RAW (10,000x the fee). The old path swept BLIND whenever
        `registered` was set — a fresh registrant (or an already-swept epoch) burned MIN_TX_FEE for the
        exec node to answer "skip: no accrued dividend". No local exec node -> never spend blind.

        Also AUTO-CLAIMS: `collect_dividend` only moves the accrual into a provable withdrawal — the coins
        land on L1 via a fee-exempt `dividend_withdraw` Merkle proof once the exec root SETTLES. The browser
        wallet auto-claims for its user (interface.js claimPendingDividends); a headless node previously
        never did, stranding every auto-collected sweep in pending forever. Claim first, then sweep, so one
        epoch's duty pass drains both sides. Keyed on the exec view, not the `registered` flag — a lapsed
        member with leftover accrual still gets swept. Best-effort; never raises into the core loop."""
        if not getattr(self.memserver, "auto_collect_dividend", True):
            return
        # NEVER while our consensus view is suspect: the min_block propagation guard below is computed
        # from OUR tip, and in emergency/recovery that tip is stale — min_block = stale_tip + 8 can
        # already be in the past network-wide, which is zero protection. A collect blob emitted mid
        # catch-up seeded fork h67088 (fork_diffs.jsonl #6, 2026-08-18) exactly this way. The sweep is
        # discretionary; it can always wait for the next healthy epoch.
        if self.memserver.emergency_mode:
            return
        try:
            epoch = epoch_of(self.memserver.latest_block["block_number"])
            if self.last_auto_collect_epoch == epoch:
                return
            self.last_auto_collect_epoch = epoch        # one probe per epoch, reachable or not
            d = self._exec_get(f"/exec/dividend?address={self.memserver.address}")
            if d is None:
                return                                  # no accrual oracle -> unknown amount -> don't burn a fee blind
            # dividend_withdraw lands FLEXIBLY (proof-gated, at-most-once) — a generous window so it doesn't
            # expire before inclusion and re-gossip-flood the network with "Target block too low".
            max_block = self.memserver.latest_block["block_number"] + TX_TARGET_MARGIN
            # (1) CLAIM collected-but-unclaimed withdrawals whose proof matches the SETTLED root (fee-exempt,
            # so always worth sending; an unsettled one just waits for a later epoch).
            pending = d.get("pending") or []
            if pending:
                from ops.settlement_ops import latest_settled
                _cur, settled_root = latest_settled()
                for w in pending:
                    pr = self._exec_get(f"/exec/dividend_proof?nonce={w['nonce']}")
                    if not pr or not settled_root or pr.get("state_root") != settled_root:
                        continue                        # proof must be against the SETTLED root; retry next epoch
                    tx = construct_dividend_withdraw_tx(
                        self.memserver.keydict, int(w["amount"]), str(w["nonce"]), pr["proof"], max_block,
                        min_block=self.memserver.latest_block["block_number"] + FLEX_TX_MIN_MARGIN)
                    self.memserver.merge_transaction(tx, user_origin=True)
                    self.logger.info(
                        f"Auto-collect: claimed settled dividend withdrawal of {w['amount']} raw "
                        f"(nonce {w['nonce']}, max_block {max_block})")
            # (2) SWEEP the accrued balance once it dwarfs the fee; below the floor it keeps accruing fee-free.
            accrued = int(d.get("accrued", 0))
            if accrued < AUTO_COLLECT_MIN_RAW:
                return
            # blob lands FLEXIBLY: min_block (tip + TX_INCLUSION_DELAY) guarantees it has gossiped to
            # every producer before any may include it (identical mempools -> identical blocks — the
            # fork/reorg guard), and the wider max gives it a real landing window past the delay.
            _tip = self.memserver.latest_block["block_number"]
            tx = construct_blob_tx(self.memserver.keydict, {"op": "collect_dividend"},
                                   _tip + TX_TARGET_MARGIN, MIN_TX_FEE,
                                   min_block=_tip + FLEX_TX_MIN_MARGIN)
            self.memserver.merge_transaction(tx, user_origin=True)
            self.logger.info(
                f"Auto-collect: swept presence dividend of {accrued} raw (fee {MIN_TX_FEE}, "
                f"window [{_tip + FLEX_TX_MIN_MARGIN}, {_tip + TX_TARGET_MARGIN}])")
        except Exception as e:
            self.logger.info(f"Auto-collect skipped: {e}")

    def maybe_auto_vote(self):
        """AUTO-VOTE 'yes' on open treasury proposals paying a WHITELISTED recipient (memserver.auto_vote,
        allow-list memserver.auto_vote_allow, default ["faucet"]). Throttled to once per epoch.

        WHY THE NODE AND NOT JUST THE WALLET: treasury quorum is counted in BONDED SHARES. The browser
        wallet has auto-voted since the feature shipped, but measured on betanet-2, 108 of 117 open miners
        hold ZERO shares — their votes count for nothing — while all 42 shares sit with 9 bonded node
        operators whose software never voted at all. Quorum is 28 of 42, so it was unreachable by
        construction: the treasury accumulated 109 NADO and paid out nothing, ever, because the only
        parties with weight had no way to say yes. Whitelisting is meaningless unless that side votes.

        SAFETY IS THE WHITELIST, NOT THE FLAG. A listed recipient is the only thing this will ever approve,
        and the shipped default is the reserved `faucet` escrow — keyless and impossible to redirect — so
        the default behaviour cannot move treasury funds to any individual's address. A vote carries a
        small anti-spam fee, so this refuses to guess: it votes only on proposals it can see it has NOT
        already voted on, mirroring the wallet's `voted` rule (which is 'has cast a vote, yes OR no', so a
        deliberate `no` is never flipped to yes)."""
        if not getattr(self.memserver, "auto_vote", False):
            return
        allow = [a for a in (getattr(self.memserver, "auto_vote_allow", None) or [])]
        if not allow:
            return                                   # an empty list means "approve anything" — never here
        try:
            from ops import kv_ops
            from ops.transaction_ops import construct_treasury_vote_tx
            from ops.account_ops import get_bonded_registry
            epoch = epoch_of(self.memserver.latest_block["block_number"])
            if getattr(self, "last_auto_vote_epoch", None) == epoch:
                return
            self.last_auto_vote_epoch = epoch
            me = self.memserver.address
            if me not in get_bonded_registry():       # no shares -> our vote carries no weight; skip the fee
                return
            # NEVER SPEND MORE THAN THE NODE CAN AFFORD. A treasury vote carries MIN_TX_FEE, and this is the
            # only automated path that pays a fee without a value it is unlocking to compare against
            # (auto_bond and auto_collect each guard on AUTO_MIN_FEE_MULTIPLE x their own fee). Governance
            # participation has no per-tx payout, so the guard is the same dust floor applied to the
            # BALANCE: a node whose spendable balance is not worth many thousands of fees has no business
            # burning them on votes. Today every voter is far above this; it matters the day one is not.
            _bal = int((get_account(me) or {}).get("balance", 0))
            if _bal < AUTO_COLLECT_MIN_RAW or not auto_spend_allowed(_bal, MIN_TX_FEE):
                return
            # And bound a single pass: a burst of proposals must not drain a node in one epoch. Whatever is
            # left is picked up next epoch — votes are only refused, never lost.
            _budget = max(1, _bal // (MIN_TX_FEE * AUTO_MIN_FEE_MULTIPLE))
            _cast = 0
            h = self.memserver.latest_block["block_number"]
            for pid, spend in kv_ops.treasury_proposals_all():
                expiry = int(spend.get("expiry", 0))
                if h > expiry or kv_ops.treasury_executed_exists(pid):
                    continue                          # expired or already paid
                if str(spend.get("recipient", "")).lower() not in allow:
                    continue                          # not whitelisted -> a human decides
                if any(v.lower() == me.lower() for v in kv_ops.treasury_voters(pid)):
                    continue                          # already voted (yes OR no) -> never re-cast
                tx = construct_treasury_vote_tx(self.memserver.keydict, spend.get("recipient"),
                                                int(spend.get("amount", 0)), spend.get("memo", ""),
                                                spend.get("nonce"), h + RESERVED_TX_MARGIN,
                                                expiry, choice="yes")
                self.memserver.merge_transaction(tx, user_origin=True)
                self.logger.info(f"Auto-vote: YES on {pid[:12]}… → {spend.get('recipient')} "
                                 f"({int(spend.get('amount', 0)) / 1e10:.4f} NADO, whitelisted)")
                _cast += 1
                if _cast >= _budget:
                    self.logger.info(f"Auto-vote: fee budget reached ({_cast} this epoch); the rest wait "
                                     f"for the next one")
                    break
        except Exception as e:
            self.logger.info(f"Auto-vote skipped: {e}")

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
            # THE LEASE GUARD READ A FIELD THAT DOES NOT EXIST. `reg_epoch` is not stored on the account —
            # it is an ENRICHMENT the HTTP handler adds (nado.py: data["reg_epoch"] = recert_latest(addr)).
            # The raw doc this loop reads has no such key, so `acc.get("reg_epoch", -1)` was ALWAYS -1, the
            # `reg_ep >= 0` test was always False, and the guard NEVER fired: this node re-registered every
            # single epoch — 240x more often than the once-per-lease it documents.
            #
            # It was not harmless. A recert is +1 fidelity (there was no minimum spacing until
            # FIDELITY_MIN_GAP_EPOCHS), so auto-registering nodes ran their fidelity to 366-379 in 1.6 days
            # while browser miners sat at 1 — weight 10 vs 2, i.e. 5x the open-lane selection AND 5x the
            # presence-dividend share. That is the reward gap users reported. It also burned ~240s/day of
            # PoSW per node instead of ~1s, spammed ~240 register txs/day each, and inflated the
            # registration-difficulty baseline (which is why the anti-flood multiplier sat at 1x).
            #
            # Read the recert index directly — the same source the enrichment uses.
            if acc and int(acc.get("registered", 0)) == 1:
                from ops import kv_ops as _kv
                reg_ep = int(_kv.recert_latest(self.memserver.address))
                if reg_ep >= 0 and epoch < reg_ep + POSW_LEASE_EPOCHS - 10:   # still well inside the lease
                    self.last_auto_register_epoch = epoch
                    return
            from ops import posw
            from ops.block_ops import get_block_hash_by_number
            from protocol import POSW_T, POSW_TARGET_MARGIN
            # tip+4 was 24 s to prove AND land. Fine for a renewal (POSW_T at ~2M h/s here is under a
            # second), impossible for this node's FIRST registration, which owes the entry multiplier —
            # 32x the rate requirement, 31 s of proving at today's 2x. The node was quietly relying on
            # having registered back when the multiplier was 1. Use the same budget every other prover
            # gets; `register` lands at exactly max_block, so a wider target costs only latency.
            max_block = self.memserver.latest_block["block_number"] + POSW_TARGET_MARGIN
            anchor = get_block_hash_by_number(max(0, max_block - POSW_ANCHOR_OFFSET))
            if not anchor:
                return
            # strict v2 requirement — the one and only difficulty mode
            # Mint at the FULL consensus requirement — rate multiplier AND entry multiplier. Using only
            # the rate part would under-work every first registration and have it rejected by every node.
            from ops.reg_difficulty import required_posw_t as _req_t
            req_t = _req_t(epoch_of(max(0, max_block - POSW_ANCHOR_OFFSET)), self.memserver.address)
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
            # by txid, not by deep dict comparison: the txid IS the content hash, so it identifies the
            # tx exactly, and `list.remove(dict)` was an O(n) full-body compare per straggler.
            _mined_ids = {t.get("txid") for t in already_mined}
            transactions[:] = [t for t in transactions if t.get("txid") not in _mined_ids]
            block["block_transactions"] = [t for t in block["block_transactions"]
                                           if t.get("txid") not in _mined_ids]

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
            # Evict every included tx from the pool in ONE pass so a just-included tx is never
            # re-selected next round. This was `if transaction in pool: pool.remove(transaction)` per
            # tx — O(B x P) FULL-DICT comparisons on the block thread (at B=150, P=600 that is 90,000
            # deep dict __eq__ calls per block), and worse, an IN-PLACE mutation that never bumped
            # pool_gen. memserver documents that every in-place mutation site must bump it by hand;
            # this one didn't, so _txid_set_cache and _pool_hash_cache went stale and
            # get_transaction_pool_hash() kept advertising a pool hash that still contained the txs we
            # had just mined — polluting transaction_hash_pool_percentage, a consensus VOLATILITY
            # signal, for up to a second after every block. Rebuilding and reassigning goes through the
            # property setter, which bumps pool_gen, so both caches invalidate correctly.
            included_txids = {t.get("txid") for t in transactions}
            with self.memserver.mempool_lock:
                pool = self.memserver.transaction_pool
                kept = [t for t in pool if t.get("txid") not in included_txids]
                if len(kept) != len(pool):
                    self.memserver.transaction_pool = kept

            for transaction in transactions:
                try:
                    # block_height = the block being validated (N) so a register tx's epoch check
                    # epoch_of(N) matches how apply_register records it (index_transactions applies
                    # with block["block_number"]); account STATE for spending/producer checks is
                    # still parent state (this block is not yet incorporated).
                    # DEEP = this block is already buried under FINALITY_DEPTH of chain we KNOW exists
                    # (learned from a sync batch's tail — see _fetch_sync_batch). Only the expensive
                    # settle-proof verification consults it; every structural check runs regardless.
                    # Our OWN candidate block is never deep: `remote` is False there and we are at the tip.
                    _deep = bool(remote) and (
                        int(getattr(self, "_known_tip_height", 0)) - int(block["block_number"])
                        > FINALITY_DEPTH)
                    validate_transaction(transaction=transaction,
                                         logger=logger,
                                         block_height=block["block_number"],
                                         deep=_deep)
                except ProofUnavailable:
                    # THE THIRD OUTCOME: not valid, not invalid — NOT YET. A DA-published settle proof we do
                    # not hold says nothing about whether this block is good, so we must neither accept it
                    # nor reject it, and above all must not punish the peer that sent it. Propagate so the
                    # whole block is deferred and retried on a later pass, by which time the shards will
                    # normally have spread (da_fetch pulls k+1 from across the network).
                    #
                    # Every node applies this identically, so deferral cannot fork the fleet — a DA outage
                    # costs liveness, never safety. And the wait is bounded: past FINALITY_DEPTH the depth
                    # gate stops consulting the proof at all, so a proof that never arrives degrades to the
                    # accumulated-weight path instead of stalling this node forever.
                    raise
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
                    _bad = transaction.get("txid")
                    block["block_transactions"] = [t for t in block["block_transactions"]
                                                   if t.get("txid") != _bad]

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

    def _record_reject(self, block, ours, theirs, layer="L1"):
        """Log a state-root divergence with OUR per-sub-DB fingerprint and count it in the daily telemetry.
        Purely diagnostic and fully best-effort — it must NEVER affect the refusal that follows. Throttled
        (see _DIVERGENCE_LOG_EVERY): the fingerprint is a full extra state walk and record_reject rewrites
        the stats file, while a diverged node retries ~1/s against every peer."""
        now = time.time()
        if (now - getattr(self, "_last_divergence_log", 0.0)) < _DIVERGENCE_LOG_EVERY:
            return
        self._last_divergence_log = now
        try:
            from ops.snapshot_ops import per_db_roots
            fp = " ".join(f"{n}={r[:8]}({c})" for n, (r, c) in sorted(per_db_roots().items()))
            self.logger.error(f"STATE DIVERGENCE ({layer}) @block {block['block_number']} "
                              f"(ours {str(ours)[:16]} vs producer {str(theirs)[:16]}) — our per-DB roots: {fp}")
        except Exception:
            pass
        try:
            from ops import rollback_stats
            rollback_stats.record_reject()
        except Exception:
            pass

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
            expected_reward = get_block_reward()
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

            # STATE-ROOT BINDING (L1): re-derive OUR as-of-parent L1 state root (tip == parent here, the same
            # committed state the producer hashed over) and ENFORCE equality with the block's committed root.
            # This is what binds L1 STATE to consensus: a node whose account/producer state diverged from the
            # producer's — a non-deterministic apply, a rollback-path bug, silent corruption — rejects the
            # block HERE instead of extending it and carrying a different state that only surfaces, with no
            # tiebreak, at snapshot sync (the betanet-7 h76000 split). A rejected block just forks off and
            # loses fork-choice; it can never become a silent state fork. DIVERGENCE IS FATAL BY DESIGN — a
            # halted node is recoverable, a node that climbs on diverged state is silent poison.
            from ops.snapshot_ops import l1_state_root
            from protocol import STATE_ROOT_UNENFORCED_FROM, STATE_ROOT_ENFORCED_AGAIN_AT
            our_state_root = l1_state_root()   # consensus subset only — block storage excluded (determinism)
            # REPAIR WINDOW (protocol.STATE_ROOT_UNENFORCED_FROM/_ENFORCED_AGAIN_AT). Over one bounded span
            # the committed root included a node-local disk-retention watermark, so those roots encode how
            # far ONE node had pruned and are unverifiable by construction — an archive node never held the
            # value at all. Comparing against them wedges every honest node forever, so the comparison (and
            # only the comparison) is suspended across the span. Everything else on this path still runs:
            # hash chain, signature, cumulative weight, tx validity, per-tx state transitions.
            _bn = int(block.get("block_number") or 0)
            _unenforced = STATE_ROOT_UNENFORCED_FROM <= _bn < STATE_ROOT_ENFORCED_AGAIN_AT
            if _unenforced and block.get("state_root") != our_state_root:
                if not getattr(self, "_repair_window_logged", False):
                    self._repair_window_logged = True
                    self.logger.warning(
                        f"STATE-ROOT REPAIR WINDOW: accepting block {_bn} whose committed root "
                        f"{str(block.get('state_root'))[:16]} differs from ours {our_state_root[:16]}. "
                        f"Roots in [{STATE_ROOT_UNENFORCED_FROM}, {STATE_ROOT_ENFORCED_AGAIN_AT}) carried a "
                        f"node-local prune watermark and cannot be re-derived by anyone. Full enforcement "
                        f"resumes at {STATE_ROOT_ENFORCED_AGAIN_AT}.")
            elif block.get("state_root") != our_state_root:
                # DIAGNOSTIC (no consensus effect): dump OUR per-sub-DB root fingerprint + count the reject.
                # Comparing this one line against another node's at the same height localizes the divergence
                # to the exact sub-DB immediately (the betanet-8 wedge needed a replay harness for this).
                # THROTTLED: a diverged node re-enters emergency ~1/s and retries every peer, and the
                # fingerprint costs a FULL extra state walk + a stats file rewrite — unthrottled it amplifies
                # the very wedge it reports. One report per _DIVERGENCE_LOG_EVERY seconds is plenty to diagnose.
                self._record_reject(block, our_state_root, str(block.get("state_root")))
                raise ValueError(
                    f"Block {block['block_number']} state_root {str(block.get('state_root'))[:16]} != our "
                    f"as-of-parent L1 state {our_state_root[:16]} — our state diverged from the producer; "
                    f"refusing to extend (would fork state while agreeing on the block body)")

            # STATE-ROOT BINDING (L2): enforce the committed L1-JUSTIFIED settled exec (cursor, root) equals
            # ours as-of-parent. Pure read of on-chain settlement attestations (⊂ state_root), so it agrees
            # whenever state_root does — it makes the L2 settled root a FIRST-CLASS, reorg-consistent header
            # value (a relay cannot ship a block claiming a settled root that isn't justified as-of-parent),
            # and gives L2 divergence its own named error rather than only surfacing at an exit claim.
            from ops.settlement_ops import settled_header_commitment
            our_exec_cursor, our_exec_root = settled_header_commitment()
            if block.get("exec_root") != our_exec_root or block.get("exec_cursor") != our_exec_cursor:
                # count/report L2 divergence too — the rejects series documents "L1/L2 root" mismatches
                self._record_reject(block, f"{our_exec_cursor}/{our_exec_root}",
                                    f"{block.get('exec_cursor')}/{block.get('exec_root')}", layer="L2")
                raise ValueError(
                    f"Block {block['block_number']} L2 settled (cursor={block.get('exec_cursor')}, "
                    f"root={str(block.get('exec_root'))[:16]}) != our as-of-parent "
                    f"(cursor={our_exec_cursor}, root={our_exec_root[:16]}) — L2 settlement view diverged; "
                    f"refusing to extend")

            # AUDIT FIX: reject a block containing duplicate reserved txs (in-block uniqueness) —
            # closes the K-withdraw bond drain / slash-escape / chain-halt, duplicate-slash over-burn,
            # and heartbeat/reveal DUPSORT desync forks.
            assert_unique_reserved(block["block_transactions"])

            # AUTHORIZATION COMMITMENT (signature aggregation). Recompute (auth_root, auth_count) from the
            # block's OWN transactions and enforce equality with what it committed inside its hash preimage.
            # This is the statement an aggregate validity proof attests, so it must be DERIVED and never
            # accepted: a prover free to choose the root would choose one covering fewer checks than the
            # block demands, and "these zero authorizations are valid" is a proof of nothing.
            #
            # BE HONEST ABOUT WHAT THIS ADDS. Because the commitment lives inside the hash preimage and
            # rebuild_block recomputes it from the block's own tx list, a block claiming the wrong root
            # already fails the rebuilt-hash check — so on the ordinary path this is redundant. It is kept
            # for two reasons: it gives the failure its own name instead of an opaque hash mismatch, and it
            # holds on any path that reaches verify_block without a full rebuild. It is a pure function of
            # committed block data, so unlike state_root a mismatch here means the BLOCK is malformed or
            # forged — never that our state drifted.
            from execnode.stark import mldsa_block_auth as _auth
            _r, _c = _auth.auth_commitments(block)
            if int(block.get("auth_count", -1)) != _c or int(block.get("auth_root", -1)) != int(_r):
                raise ValueError(
                    f"Block {block['block_number']} authorization commitment "
                    f"(root={str(block.get('auth_root'))[:16]}, count={block.get('auth_count')}) != "
                    f"recomputed (root={str(_r)[:16]}, count={_c}) — the block's committed signature "
                    f"workload does not match its own transactions")

            # DETACHED EVIDENCE, when the producer shipped an envelope. Absent -> the per-tx signatures
            # below ARE the evidence (what every block ships today). Present -> it is checked against the
            # commitment we just recomputed, with the key coming from OUR PUBKEY-ONCE resolution and never
            # from the envelope. A present-but-invalid envelope is a forgery signal and rejects the block;
            # it can never CHANGE block identity, because it lives outside the hash preimage.
            if block.get("block_auth_evidence") is not None:
                from ops.block_ops import check_block_auth_evidence
                _ok, _why = check_block_auth_evidence(block)
                if not _ok:
                    raise ValueError(f"Block {block['block_number']} authorization evidence rejected: {_why}")

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
            # remote diagnosis (/status "last_block_reject"): WHY this node refused a block its peers
            # accepted — the .26/.28 pair rejected the majority's 64916 through six opaque False returns
            # before this field existed.
            try:
                self.memserver.last_block_reject = {
                    "height": block.get("block_number") if isinstance(block, dict) else None,
                    "hash": str(block.get("block_hash"))[:16] if isinstance(block, dict) else None,
                    "error": str(e)[:200], "at": get_timestamp_seconds()}
            except Exception:
                pass
            time.sleep(1)
            return False

    def init_hashes(self):
        """Seed the shared transaction-pool hash before the first pass so the pool-minority reconcile
        (and peers polling our status) compare against a real value, never a stale/unset one."""
        self.memserver.transaction_pool_hash = (
            self.memserver.get_transaction_pool_hash()
        )
        self.memserver.upcoming_block_hash = self.memserver.get_upcoming_block_hash()

    def check_mode(self):
        """Decide the next pass's mode: emergency (sync/reorg) when the objective fork-choice says a
        strictly-better tip exists (minority_block_consensus) OR an operator forced a sync; normal
        otherwise. Also releases force_sync_ip once we agree with >80% of peers on a fresh tip —
        the forced donor has served its purpose and normal fork-choice takes back over."""
        if self.minority_block_consensus():
            # ONE-BLOCK FAST PATH first: a same-height split with a common parent is a paper cut —
            # swap the single block inline (see _inline_tip_swap) instead of dragging the node
            # through emergency recovery and freezing finality. Deeper divergence falls through.
            if self._inline_tip_swap():
                self.memserver.emergency_mode = False
            else:
                self.memserver.emergency_mode = True
                self.logger.warning("We are out of consensus")
        elif self.memserver.force_sync_ip:
            self.memserver.emergency_mode = True
            self.logger.warning("Forced sync switched to emergency mode")
        else:
            self.memserver.emergency_mode = False

        # RELEASE the forced donor once it has done its job. The old condition also required a FRESH block
        # (since_last_block < block_time), which is unreachable in the very situation force-sync is used
        # for: a pinned donor keeps us in emergency mode, emergency mode does not produce, and with the
        # chain stalled no fresh block ever arrives — so the pin never lifts and our own producer stays
        # switched off. Agreement with >80% of peers is the real signal that fork-choice can take over;
        # and a pin is dropped after FORCE_SYNC_MAX_S regardless, so a recovery tool can never become a
        # permanent handbrake on production.
        if self.memserver.force_sync_ip:
            if self.consensus.block_hash_pool_percentage > 80:
                self.logger.info("Forced sync released — back in agreement with the peer majority")
                self.memserver.force_sync_ip = None
                self._force_sync_since = None
            else:
                if not getattr(self, "_force_sync_since", None):
                    self._force_sync_since = get_timestamp_seconds()
                elif get_timestamp_seconds() - self._force_sync_since > FORCE_SYNC_MAX_S:
                    self.logger.warning("Forced sync expired after %ds — releasing so this node can produce again"
                                        % FORCE_SYNC_MAX_S)
                    self.memserver.force_sync_ip = None
                    self._force_sync_since = None

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
