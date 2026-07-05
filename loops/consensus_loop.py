import threading
import time
import traceback

from config import get_timestamp_seconds
from ops.peer_ops import (
    get_majority,
    percentage,
)
from ops.pool_ops import get_from_pool


def get_pool_majority(pool):
    if pool and None not in pool.values():
        majority_hash = get_majority(pool)
        return majority_hash
    else:
        return None


def get_pool_percentage(pool, majority_pool_hash):
    if pool and None not in pool.values():
        pool_percentage = percentage(majority_pool_hash, sorted(pool.values()))
        return pool_percentage
    else:
        return 100


class ConsensusClient(threading.Thread):
    """thread to control peer pools, consensus and refreshing of values"""

    def __init__(self, memserver, logger):
        threading.Thread.__init__(self)
        self.duration = 0
        self.logger = logger

        self.logger.info(f"Starting Consensus Manager")

        self.memserver = memserver

        self.block_hash_pool = {}
        self.status_pool = {}
        self.transaction_hash_pool = {}

        self.majority_block_hash = None
        self.majority_transaction_pool_hash = None

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

        self.transaction_hash_pool_percentage = 0
        self.block_hash_pool_percentage = 0

    def refresh_hashes(self):
        """make sure our node knows the current state of affairs quickly"""

        self.memserver.since_last_block = get_timestamp_seconds() - self.memserver.latest_block["block_timestamp"]

        get_from_pool(source="transaction_pool_hash",
                      target=self.transaction_hash_pool,
                      pool=self.status_pool)
        get_from_pool(source="latest_block_hash",
                      target=self.block_hash_pool,
                      pool=self.status_pool)

        self.block_hash_pool_percentage = get_pool_percentage(
            self.block_hash_pool, self.majority_block_hash
        )

        self.transaction_hash_pool_percentage = get_pool_percentage(
            self.transaction_hash_pool, self.majority_transaction_pool_hash
        )

        self.majority_block_hash = get_pool_majority(self.block_hash_pool)
        self.majority_transaction_pool_hash = get_pool_majority(
            self.transaction_hash_pool
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
        self._reject_clear_counter += 1
        if self._reject_clear_counter >= 30:
            self.rejected_tips = set()
            self._reject_clear_counter = 0

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
            if tip_hash is None or w is None or tip_hash in self.rejected_tips:
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

    def run(self) -> None:
        while not self.memserver.terminate:
            try:
                start = get_timestamp_seconds()

                self.memserver.transaction_pool_hash = self.memserver.get_transaction_pool_hash()

                self.refresh_hashes()

                self.duration = get_timestamp_seconds() - start
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in consensus loop: {e} {traceback.print_exc()}")
                time.sleep(1)
                # raise  # test
