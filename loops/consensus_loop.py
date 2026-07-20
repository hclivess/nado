import threading
import time
import traceback

from config import get_timestamp_seconds
from ops.peer_ops import (
    get_majority,
    percentage,
    seed_peers,
)
from ops.pool_ops import get_from_pool

# A tip we FAIL to obtain is benched, doubling each failure up to TIP_BENCH_MAX_S. The first bench is short
# so an ordinary transient fetch failure barely delays a REAL heavier tip; the cap is what stops an
# unreachable chain from owning the donor pool forever.
TIP_BENCH_BASE_S = 12
TIP_BENCH_MAX_S = 600
TIP_BENCH_FORGET_S = 1800
# Consecutive failures against a LONE peer's chain before that peer leaves fork choice entirely. Three is
# deliberately more than a blip: benching a peer is how the node stops chasing an unobtainable fork, and it
# is also how the node could go blind to a real chain, so it must never fire on a transient fetch error.
PEER_BENCH_AFTER = 3
# PEER benches escalate far beyond the tip cap. 2026-07-20: four stranded old-code peers (git-less, each a
# LONE holder of a distinct fork with pre-difficulty-fix INFLATED weight) rotated through the 600s cap and
# put the node through 272 emergency entries in 4h, pinning finality ~45 behind tip. A permanently-broken
# chain re-fails the moment its bench expires, so the cap is the only thing that decides steady-state churn:
# 2h ≈ two flaps per wreck per day. Safe for real chains twice over: multiple holders never peer-strike at
# all (see below), and a lone-bridge peer that heals is retried within 2h worst-case, then a SUCCESS stops
# the striking and TIP_BENCH_FORGET_S clears its slate.
PEER_BENCH_MAX_S = 7200


def get_pool_majority(pool):
    """Plurality hash of a fully-populated peer pool, or None while the pool is empty or ANY entry
    is still None — a half-formed quorum must not elect a premature majority that would trigger a
    pool replacement. Plurality is peer-count-based, so it is kept for the tx/producer pools ONLY;
    chain fork-choice uses the Sybil-resistant cumulative-weight path instead."""
    if pool and None not in pool.values():
        majority_hash = get_majority(pool)
        return majority_hash
    else:
        return None


def get_pool_percentage(pool, majority_pool_hash):
    """Share (%) of pool entries agreeing with the given majority hash. Returns 100 while the pool
    is empty or still partially populated — an unformed quorum reads as full agreement, never as
    dissent (the percentage gates force_sync release and health reporting, not fork-choice)."""
    if pool and None not in pool.values():
        pool_percentage = percentage(majority_pool_hash, sorted(pool.values()))
        return pool_percentage
    else:
        return 100


class ConsensusClient(threading.Thread):
    """thread to control peer pools, consensus and refreshing of values"""

    def __init__(self, memserver, logger):
        """Set up the peer-keyed pools (status / block-hash / tx-hash), the plurality outputs, and
        the objective weight-based fork-choice state (tip_weights, heaviest_block_hash, and the
        bounded rejected_tips exclusion) documented inline. Other threads read these fields
        directly, so everything observable is initialized before the thread starts."""
        threading.Thread.__init__(self)
        self.duration = 0
        self.logger = logger

        self.logger.info(f"Starting Consensus Manager")

        self.memserver = memserver

        self.block_hash_pool = {}
        self.status_pool = {}
        self.transaction_hash_pool = {}
        self.upcoming_block_hash_pool = {}   # SAME-TIP peers only -> advertised NEXT-block tx-set hash (rebuilt fresh per pass)

        self.majority_block_hash = None
        self.majority_transaction_pool_hash = None
        self.majority_upcoming_block_hash = None

        # #16/#17 step 3: OBJECTIVE heaviest-cumulative_weight fork-choice (replaces the Sybil-swingable
        # plurality majority_block_hash for the BLOCK chain). Peer IPs contribute ZERO weight; only the
        # grind-proof, on-chain-verified cumulative_weight decides the canonical tip. (Plurality is kept
        # for the tx-pool / block-producer pools, which are not the chain fork-choice.)
        self.weight_pool = {}            # {peer: advertised tip cumulative_weight}
        self.tip_weights = {}            # {tip_hash: best advertised weight for that hash (incl. ours)}
        self.heaviest_block_hash = None  # canonical tip = argmax weight (ties: lowest hash)
        self.heaviest_block_weight = None
        # AUDIT FIX (weight-DoS): tips we tried to sync to (because their ADVERTISED cumulative_weight
        # looked heaviest) but could NOT actually obtain a valid heavier chain for. Excluded from the
        # heaviest computation for a bounded window, so a peer advertising a bogus huge weight cannot
        # loop us into emergency-mode/rollback. Auto-cleared periodically so a transiently-unreachable
        # REAL heavier tip is retried.
        self.rejected_tips = set()
        self._reject_clear_counter = 0
        # BACKOFF state for benched tips. A tip we repeatedly fail to obtain is one nothing can serve; the
        # flat ~12s bench meant the node spent every window chasing it and never synced the best chain it
        # COULD reach. Observed live: a single-node fork stayed heaviest while a four-node chain was kept
        # out of the donor pool for being lighter, so the node sat still for hours.
        self._tip_strikes = {}      # tip hash -> consecutive failures to obtain it
        self._tip_until = {}        # tip hash -> monotonic deadline while it stays benched
        self._peer_strikes = {}     # peer -> consecutive failures to obtain the chain IT advertises
        self._peer_until = {}       # peer -> monotonic deadline while its whole chain is out of fork choice
        self._heavy_holders = {}    # heaviest tip hash -> (advertisers, pool size) AT SELECTION TIME (see
                                    # refresh_heaviest_tip: failure-time attribution loses a rotating tip)

        self.transaction_hash_pool_percentage = 0
        self.upcoming_block_hash_pool_percentage = 0
        self.block_hash_pool_percentage = 0

    def reject_tip(self, tip_hash):
        """Bench an advertised-heavier tip we just failed to obtain, with exponential backoff. Repeated
        failures mean nothing can serve that chain, so the node must stop spending every window on it and
        get on with syncing the heaviest chain it can actually reach.

        Benching the HASH alone is not enough against the case that actually happens: a peer that forked
        long ago and is still mining its own branch publishes a NEW tip hash every block, so per-hash
        strikes never accumulate — each pass sees a brand-new "heaviest" tip, spends a full sync window
        failing to obtain it, and re-wedges. Every failure therefore also strikes the ADVERTISING PEERS,
        and while a peer is benched none of its tips enter fork choice at all."""
        if not tip_hash:
            return
        n = self._tip_strikes.get(tip_hash, 0) + 1
        self._tip_strikes[tip_hash] = n
        self._tip_until[tip_hash] = time.monotonic() + min(TIP_BENCH_BASE_S * (2 ** (n - 1)), TIP_BENCH_MAX_S)
        self.rejected_tips.add(tip_hash)
        # Striking the PEER is the strong move, so it is reserved for the shape that actually needs it: a
        # LONE fork. If several peers advertise this tip it is a chain the network holds and our failure to
        # fetch it says more about us than about them — benching those peers would make the node ignore the
        # real chain for minutes, which is a far worse failure than the one being fixed. A single peer
        # advertising a tip nobody else has, repeatedly unobtainable, is the moving-target forker.
        # The strike count has to live on the PEER, not the hash: the forker's hash is new every block, so a
        # per-hash counter is stuck at 1 forever and would never reach the threshold.
        holders = [p for p, h in self.block_hash_pool.copy().items() if h == tip_hash]
        pool_n = len(self.block_hash_pool)
        if not holders:
            # RACE FIX (observed live 2026-07-20): an actively-MINING forker's hash rotates every block,
            # so by the time the fetch fails NOBODY advertises the failed hash anymore — failure-time
            # attribution found no one, every exclusion sat at "failure #1" forever, and the churn never
            # ended. Fall back to who advertised it when fork choice SELECTED it (refresh_heaviest_tip).
            holders, pool_n = self._heavy_holders.get(tip_hash, ((), 0))
            holders = list(holders)
        # MINORITY-CLUSTER GUARD (was: lone holder only). The honest-peers hypothesis — "several peers
        # hold this tip, so failing to fetch it says more about us than about them" — only holds when
        # they actually are the network. A TWO-node cluster mining a shared fork sailed straight through
        # the lone-holder test and churned emergency mode indefinitely. Strike every advertiser when they
        # are a strict minority of the pool; a majority-held tip still never peer-strikes.
        #
        # OPERATOR SEEDS ARE EXEMPT (bitten live within an hour of shipping the escalated bench): during
        # a fleet update wave the seed restarted, its STALE pool status kept advertising a tip nothing
        # could serve for ~a minute, it was the ONLY peer on the real chain — lone holder — and the 2h
        # bench then locked this node onto its own slower fork, 70+ blocks adrift. Seeds are already the
        # weak-subjectivity anchor (snapshot_bootstrap) and are never kept unreachable-benched
        # (peer_loop); fork choice must not be able to go blind to them either.
        seeds = seed_peers()
        holders = [p for p in holders if p not in seeds]
        if holders and (len(holders) == 1 or len(holders) * 2 < max(pool_n, 2)):
            for p in holders:
                self._peer_strikes[p] = pn = self._peer_strikes.get(p, 0) + 1
                if pn >= PEER_BENCH_AFTER:
                    self._peer_until[p] = time.monotonic() + min(
                        TIP_BENCH_BASE_S * (2 ** (pn - PEER_BENCH_AFTER)), PEER_BENCH_MAX_S)
        return n

    def peer_fetch_succeeded(self, peer):
        """A block fetch from `peer` actually WORKED — the only honest healing signal there is. Clear its
        strikes and bench so a peer that was struck while briefly down (restart, update wave) is fully
        rehabilitated the moment it serves again, instead of sitting out the rest of an escalated bench."""
        self._peer_strikes.pop(peer, None)
        self._peer_until.pop(peer, None)

    def tip_source_benched(self, peer):
        """Is this peer's advertised chain currently excluded from fork choice? (see reject_tip)"""
        return self._peer_until.get(peer, 0) > time.monotonic()

    def refresh_hashes(self):
        """make sure our node knows the current state of affairs quickly"""

        self.memserver.since_last_block = get_timestamp_seconds() - self.memserver.latest_block["block_timestamp"]

        get_from_pool(source="transaction_pool_hash",
                      target=self.transaction_hash_pool,
                      pool=self.status_pool)
        get_from_pool(source="latest_block_hash",
                      target=self.block_hash_pool,
                      pool=self.status_pool)

        # UPCOMING pool is TIP-ANCHORED and rebuilt FRESH each pass: the upcoming hash embeds the
        # peer's parent (tip) hash, so an entry is only comparable to ours when the SAME status
        # snapshot advertises OUR tip. Without this filter a forked or merely 1-2s-stale peer's
        # hash still entered the pool and, on a small mesh (1-2 peers = a 'majority' of one),
        # produced a GUARANTEED mismatch — observed as a full-pool "Replacing transaction_pool"
        # fetch every single block interval against a cross-fork peer, forever, every tx of which
        # was then rejected ("Target block too low"). Rebuilding fresh (not get_from_pool's
        # update-in-place) also drops purged/departed peers, which the old in-place projection
        # kept as permanently stale majority voters.
        _our_tip = self.memserver.latest_block["block_hash"]
        self.upcoming_block_hash_pool = {
            peer: st.get("upcoming_block_hash")
            for peer, st in self.status_pool.copy().items()
            if isinstance(st, dict) and st.get("latest_block_hash") == _our_tip
        }

        # majorities FIRST, percentages second: computing the percentages against the previous
        # pass's majority graded the OLD winner for one pass after every majority flip (the
        # percentage gates force_sync release + health reporting — a one-second-late gate, free fix).
        self.majority_block_hash = get_pool_majority(self.block_hash_pool)
        self.majority_transaction_pool_hash = get_pool_majority(
            self.transaction_hash_pool
        )
        # UPCOMING-BLOCK agreement: the plurality NEXT-block tx-set hash across peers AT OUR TIP (the
        # pool above admits only same-tip statuses). This is what block determinism / the fast-forward
        # actually depend on — the mempool reconcile targets THIS (not the whole-pool hash), so nodes
        # converge on the next block's content, ignoring immature/future txs that won't be in it.
        # Cross-tip/stale peers are excluded at admission, so a mismatch here means same-tip peers
        # genuinely hold a different next-block tx set — the only case worth a reconcile.
        self.majority_upcoming_block_hash = get_pool_majority(self.upcoming_block_hash_pool)

        self.block_hash_pool_percentage = get_pool_percentage(
            self.block_hash_pool, self.majority_block_hash
        )

        self.transaction_hash_pool_percentage = get_pool_percentage(
            self.transaction_hash_pool, self.majority_transaction_pool_hash
        )

        self.upcoming_block_hash_pool_percentage = get_pool_percentage(
            self.upcoming_block_hash_pool, self.majority_upcoming_block_hash
        )

        self.refresh_heaviest_tip()

    def refresh_heaviest_tip(self):
        """OBJECTIVE fork-choice (#16/#17 step 3): compute the heaviest-cumulative_weight tip across
        all advertised peer tips PLUS our own. Defensive .get() (a peer mid-restart may omit the
        field). The advertised weight is only a HINT for which peer to sync from — verify_block
        re-derives and ENFORCES the weight on the real blocks, so a peer cannot lie its way to a
        heavier chain; and the finality floor stops it reorging our finalized prefix."""
        # AUDIT FIX (weight-DoS): clear the transient rejection window periodically so a real heavier
        # tip we briefly couldn't fetch is retried (and a bogus one is only excluded for a bounded time).
        # 12 passes (~12s ≈ 2 block times at 6s blocks), was 30: a single transient fetch failure
        # benched the REAL heavier tip for ~5 blocks — nearly half the finality-depth healing window
        # a forked node has to reorg back before its divergent prefix finalizes and wedges it.
        # Rebuild the bench from the per-tip deadlines. Doing it every pass (rather than clearing wholesale
        # on a counter) also means a re-anchor cannot silently reset the backoff: a tip that has failed ten
        # times stays benched across chain-identity changes, which is exactly when it used to come straight
        # back and re-wedge us.
        now_m = time.monotonic()
        self.rejected_tips = {h for h, until in self._tip_until.items() if until > now_m}
        for h in [h for h, until in self._tip_until.items() if until <= now_m - TIP_BENCH_FORGET_S]:
            self._tip_until.pop(h, None); self._tip_strikes.pop(h, None)   # long gone: forget the strikes too
        for p in [p for p, until in self._peer_until.items() if until <= now_m - TIP_BENCH_FORGET_S]:
            self._peer_until.pop(p, None); self._peer_strikes.pop(p, None)  # a peer that healed gets a clean slate

        weight_pool = {}
        for peer, status in self.status_pool.copy().items():
            if isinstance(status, dict) and status.get("latest_block_weight") is not None:
                weight_pool[peer] = status["latest_block_weight"]
        self.weight_pool = weight_pool

        # tip_weights: best advertised weight per distinct tip hash, INCLUDING our own tip so we never
        # switch away from an equal-or-heavier local chain (first-seen on ties). Excludes rejected tips.
        tip_weights = {}
        for peer, tip_hash in self.block_hash_pool.copy().items():
            w = weight_pool.get(peer)
            # a benched PEER contributes nothing: it forked long ago and mints a fresh unobtainable tip
            # every block, so excluding only the hash we last failed on would let the next one back in
            if tip_hash is None or w is None or tip_hash in self.rejected_tips or self.tip_source_benched(peer):
                continue
            if tip_hash not in tip_weights or w > tip_weights[tip_hash]:
                tip_weights[tip_hash] = w
        our_hash = self.memserver.latest_block["block_hash"]
        our_weight = self.memserver.latest_block.get("cumulative_weight", 0)
        if our_hash not in tip_weights or our_weight > tip_weights[our_hash]:
            tip_weights[our_hash] = our_weight
        self.tip_weights = tip_weights

        if tip_weights:
            # heaviest weight wins; deterministic lowest-hash tie-break (matters only for a fresh node
            # with no incumbent — an equal-weight peer never displaces our tip, see minority_block_consensus).
            self.heaviest_block_hash = sorted(tip_weights, key=lambda h: (-tip_weights[h], h))[0]
            self.heaviest_block_weight = tip_weights[self.heaviest_block_hash]
            # Record WHO advertised the winner NOW (plus the pool size for the minority test). A failed
            # fetch strikes advertisers via reject_tip, but a mining forker's hash has rotated out of the
            # pool by then — attribution must come from selection time. Bounded keep-last window.
            hh = self.heaviest_block_hash
            self._heavy_holders[hh] = (
                tuple(p for p, h in self.block_hash_pool.copy().items() if h == hh),
                len(self.block_hash_pool))
            while len(self._heavy_holders) > 64:
                self._heavy_holders.pop(next(iter(self._heavy_holders)))

    def run(self) -> None:
        """Thread entry: once per second, re-hash our own tx pool and re-derive the whole consensus
        view (pool majorities + heaviest tip) via refresh_hashes. Exceptions are contained per pass
        — the fork-choice inputs must keep refreshing for the life of the process, since the core
        loop's caught-up gate and emergency exit both read them concurrently."""
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()

                self.memserver.transaction_pool_hash = self.memserver.get_transaction_pool_hash()
                self.memserver.upcoming_block_hash = self.memserver.get_upcoming_block_hash()

                self.refresh_hashes()

                self.duration = get_timestamp_seconds() - start
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in consensus loop: {e} {traceback.format_exc()}")
                time.sleep(1)
                # raise  # test
