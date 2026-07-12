import asyncio
import threading

from config import get_timestamp_seconds, get_config
from hashing import blake2b_hash
from ops.account_ops import get_account, get_finalized_height
from ops.block_ops import get_block_ends_info
from ops.data_ops import sort_list_dict, get_home
from ops.key_ops import load_keys
from ops.message_pool import MessagePool
from ops.transaction_ops import (
    validate_single_spending,
    validate_transaction,
    sort_transaction_pool,
    validate_txid

)
from ops import kv_ops   # tx-index oracle: an already-mined txid can never re-enter the mempool
from versioner import read_version


class MemServer:
    """storage thread for core.py, also accessed by most other threads, serves mostly as data storage"""

    def __init__(self, logger):
        """Assemble the node's ENTIRE shared runtime state in one place: keys, config (env vars
        override config.dat for every headless knob), tx/message pools, pacing state, and the
        persisted safety floors (finalized_height). Constructed ONCE at startup and then shared by
        every loop thread. Cross-config invariants — notably max_rollbacks < finality_depth <
        EPOCH_LENGTH, which makes the epoch-beacon anchor un-reorgable — are asserted HERE so a
        mis-set config fails loudly at boot instead of silently disabling a protection later."""
        self.logger = logger
        self.logger.info("Starting MemServer")

        self.purge_peers_list = []

        self.start_time = get_timestamp_seconds()
        self.keydict = load_keys()
        self.config = get_config()
        self.protocol = self.config["protocol"]
        self.private_key = self.keydict["private_key"]
        self.public_key = self.keydict["public_key"]
        self.address = self.keydict["address"]
        self.server_key = self.config["server_key"]
        # MEMPOOL LOCK (audit): transaction_pool is read-modify-REPLACED by the core loop while HTTP
        # executor threads and the peer loop append via merge_transaction — an append landing between
        # another thread's snapshot-read and list reassignment was silently LOST (a wallet got "Success"
        # for a tx that then never existed). Every mutation must hold this lock; reads of a single list
        # reference (e.g. hashing a .copy()) stay lock-free.
        # SINGLE MEMPOOL (2026-07): the old three-tier user_tx_buffer -> tx_buffer -> transaction_pool
        # cascade is collapsed to ONE pool. A submitted tx is validated and enters transaction_pool
        # directly (no staged promotion), and a tx already MINED (its txid is in the on-chain tx-index)
        # can never re-enter — merge_transaction, the producer filter, and verify_block all reject an
        # already-mined txid, so an IDENTICAL transaction (same content -> same txid) is impossible to
        # reintroduce or re-mine. A tx that misses its max_block simply expires; the wallet re-submits a
        # fresh tx (new nonce -> new txid) on the user's action, never silently re-injected.
        self.mempool_lock = threading.RLock()
        self.transaction_pool = []
        self.message_pool = MessagePool()   # off-chain E2E message pool (doc/messaging.md); never block-bound
        # PERSIST the message pool across restarts — it is off-chain + ephemeral, so a plain node restart
        # (systemctl restart / redeploy) otherwise silently dropped every undelivered DM + published prekey.
        self.message_pool_path = f"{get_home()}/message_pool.dat"
        try:
            self.message_pool.load(self.message_pool_path, get_timestamp_seconds())
        except Exception:
            pass   # a corrupt/absent pool file is fine — a fresh empty pool is always valid
        self.peer_buffer = []
        self.ip = self.config["ip"]
        self.port = self.config["port"]
        self.terminate = False
        self.heavy_refresh_interval = 360

        # Target seconds between blocks (local production pacing — NOT consensus; verify only checks
        # timestamp <= now). Default 10s. All nodes on a network should agree on this so the chain keeps a
        # steady cadence; keep it identical across the mesh (ideally promote to a protocol constant later).
        self.block_time = self.config.get("block_time") or 10
        self.mode = "init"   # production pacing state (core_loop._mode): init | building | produce
        self.since_last_block = 0

        self.unreachable = {}
        self.peers = []

        self.transaction_pool_hash = None
        self.upcoming_block_hash = None   # hash of the NEXT block's tx set (mature subset) — the determinism signal
        self.reported_uptime = self.get_uptime()

        self.emergency_mode = False

        self.version = read_version()
        block_ends_info = get_block_ends_info(logger=logger)
        self.latest_block = block_ends_info["latest_block"]
        self.earliest_block = block_ends_info["earliest_block"]
        # MEMPOOL CAPS (LOCAL policy, non-consensus — get_byte_size is a rough sys.getsizeof(repr) estimate).
        # These were ONE fused constant (150000) that meant "150k txs" in the accept gate but "150000 BYTES"
        # (~146 KB) in cull_buffer — and 146 KB is SMALLER than one block's blob budget (MAX_BLOB_BYTES_PER_BLOCK
        # = 256 KB), so cull evicted blob txs before a block could ever fill to 256 KB. Split into:
        #   transaction_pool_max_txs   — the count gate (how many txs the mempool may hold), and
        #   transaction_pool_max_bytes — the cull byte budget: MUST exceed a full block's blobs (so a block can
        #                                always fill) and stay under MAX_PEER_BODY (8 MiB, the /transaction_pool
        #                                fetch cap) so the pool stays transferable between peers. 4 MiB = 16
        #                                full blocks of blobs, well under the 8 MiB wire cap.
        self.transaction_pool_max_txs = 150000
        self.transaction_pool_max_bytes = 4 * 1024 * 1024      # 4 MiB (>> 256 KiB block, << 8 MiB peer body)
        self.force_sync_ip = None
        self.rollbacks = 0
        self.can_mine = False

        _mp = self.config.get("min_peers")  # respect an explicit 0 (solo mode); `or 5` would force 5
        self.min_peers = 5 if _mp is None else _mp
        self.peer_limit = self.config.get("peer_limit") or 24
        self.max_rollbacks = self.config.get("max_rollbacks") or 10
        # ENFORCED FINALITY (#17, security step 1): a persisted monotonic finalized_height floor that
        # rollback_one_block REFUSES to cross (FinalityViolation). The ordering invariant below makes
        # the epoch-beacon anchor un-reorgable (a live epoch's anchor can never be reorged out) and
        # bounds 51%/long-range rollback. It fails loudly at startup so a mis-set config can't silently
        # disable the protection. (Stake-weighted fork-choice that bounds reorg COST is steps 2-3.)
        from protocol import EPOCH_LENGTH, FINALITY_DEPTH
        self.finality_depth = self.config.get("finality_depth") or FINALITY_DEPTH
        assert self.max_rollbacks < self.finality_depth < EPOCH_LENGTH, (
            f"need max_rollbacks ({self.max_rollbacks}) < finality_depth ({self.finality_depth}) "
            f"< EPOCH_LENGTH ({EPOCH_LENGTH}) for enforced-finality safety")
        # in-memory mirror of the persisted floor (advanced by core_loop.incorporate_block)
        self.finalized_height = get_finalized_height()
        # FFG (#6): the stake-attested finalized checkpoint height (observability; <= finalized_height,
        # which is the deeper time-based floor that bounds rollback). Updated by core_loop.maybe_attest.
        self.ffg_finalized = 0
        # RANDAO (#7): this validator's locally-held secrets {target_epoch: secret}, committed in E-2
        # and revealed in E-1. In-memory only (a secret never revealed after a restart is simply a
        # wasted commit — harmless; the beacon falls back to the anchor + other validators' reveals).
        self.randao_secrets = {}
        # Fast bootstrap is snapshot sync (ops/snapshot_ops.py) — quorum/checkpoint-gated, never a
        # validation-skipping bypass. Do NOT add one (it enables forged-tx injection).
        # AUTO-BOND (non-consensus): route this % of newly-mined spendable earnings straight into
        # bonded stake, unattended (core_loop.maybe_auto_bond). Defaults to AUTO_BOND_DEFAULT_PERCENT
        # (80) when unset — a fresh node joins the bonded lane hands-free; 0 = off. Source order:
        # NADO_AUTO_BOND_PERCENT env (handy for headless/systemd) overrides config["auto_bond_percent"].
        import os as _os
        from protocol import AUTO_BOND_DEFAULT_PERCENT as _AB_DEFAULT
        _ab = _os.environ.get("NADO_AUTO_BOND_PERCENT")
        if _ab is None:
            _ab = self.config.get("auto_bond_percent", _AB_DEFAULT)
        try:
            self.auto_bond_percent = max(0, min(100, int(_ab)))
        except (TypeError, ValueError):
            self.auto_bond_percent = _AB_DEFAULT

        # AUTO-COLLECT the presence dividend, unattended (core_loop.maybe_auto_collect) — DEFAULT ON. Only an
        # OPEN-lane member accrues one, so a bonded-only node is a no-op. NADO_AUTO_COLLECT env overrides config.
        def _flag(env, cfg, default):
            """Boolean knob resolved env var > config[cfg] > default; '0'/'false'/'no'/'off'
            (any case) mean False, anything else True — so systemd Environment= lines and
            hand-edited config values both behave predictably."""
            v = _os.environ.get(env)
            v = self.config.get(cfg, default) if v is None else v
            return str(v).strip().lower() not in ("0", "false", "no", "off")
        self.auto_collect_dividend = _flag("NADO_AUTO_COLLECT", "auto_collect_dividend", True)
        # AUTO-REGISTER + renew the open-lane PoSW lease, unattended — DEFAULT OFF (opt-in: a headless node does
        # not silently join the open lane). NADO_AUTO_REGISTER=1 (or config auto_register:true) turns it on.
        self.auto_register = _flag("NADO_AUTO_REGISTER", "auto_register", False)

        # ROLLING MODE (non-consensus): archive=True (default) keeps ALL block bodies; False runs a
        # pruned/rolling node that drops bodies older than history_retention_blocks (state + indexes
        # kept). NADO_ARCHIVE=0/false selects rolling mode headless. See doc/rolling-mode-and-da.md.
        from protocol import HISTORY_RETENTION_BLOCKS as _HRB
        _arch = _os.environ.get("NADO_ARCHIVE")
        if _arch is not None:
            self.archive = _arch.strip().lower() not in ("0", "false", "no", "off")
        else:
            self.archive = bool(self.config.get("archive", True))
        try:
            _hrb = int(_os.environ.get("NADO_HISTORY_RETENTION_BLOCKS")
                       or self.config.get("history_retention_blocks", 0) or 0)
        except (TypeError, ValueError):
            _hrb = 0
        self.history_retention_blocks = _hrb if _hrb > 0 else _HRB

        # IP-DIVERSITY registration cap (non-consensus): max distinct OPEN-lane addresses one source IP
        # may register through this node per hour (0 = off). See ops/ratelimit.allow_registration.
        try:
            self.max_registrations_per_ip = int(_os.environ.get("NADO_MAX_REG_PER_IP")
                                                 or self.config.get("max_registrations_per_ip", 64))
        except (TypeError, ValueError):
            self.max_registrations_per_ip = 64
        try:
            self.max_registrations_window = float(_os.environ.get("NADO_MAX_REG_WINDOW")
                                                  or self.config.get("max_registrations_window", 7200))
        except (TypeError, ValueError):
            self.max_registrations_window = 7200.0

    def ban_peer(self, peer):
        """Queue a misbehaving/unreachable peer for purge (deduplicated against both the purge list
        and the already-unreachable set). Seed peers are EXEMPT — never exiled, always retried —
        because they are the weak-subjectivity anchor (see below)."""
        # Operator seeds are the weak-subjectivity anchor — NEVER exile them. A transient blip (e.g. the
        # seed restarting) would otherwise drop it into the 1-hour unreachable ban, its heavy tip vanishes
        # from the pool, and the node falls back to whatever stalled/forked peer is left. A seed is always
        # retried instead.
        from ops.peer_ops import seed_peers
        if peer in seed_peers():
            return
        if peer not in self.purge_peers_list and peer not in self.unreachable:
            self.purge_peers_list.append(peer)

    # HASH CACHES for the two per-second consensus signals below. Key = the pool LIST OBJECT itself
    # (the cache keeps a live reference, so CPython can never recycle its id) + its length: every
    # pool mutation either REASSIGNS self.transaction_pool (merge_transaction's post-append sort,
    # purge, drain, cull — a new object) or changes its LENGTH in place (block-inclusion evict), so
    # (same object, same length) proves the tx set is unchanged and the cached hash is exact. This
    # turns the old O(pool)·sort + canonical-serialize EVERY SECOND into O(1) between pool changes —
    # the whole-mempool rehash was the classic hot-loop serialization cost at mempool scale.
    _pool_hash_cache = None            # (pool_obj, len, hash)
    _upcoming_hash_cache = None        # (pool_obj, len, parent_hash, kv_write_gen, hash)

    def get_transaction_pool_hash(self) -> [str, None]:
        """blake2b of the SORTED transaction pool (None when empty). Sorting first makes the hash
        canonical — two nodes holding the same tx set report the same hash regardless of arrival
        order — which is what lets the consensus loop majority-vote on pool hashes instead of
        shipping full pools around. Hashes a copy so a concurrent merge can't mutate mid-sort.
        Cached per pool object+length (see cache note above) — a pure function of the tx set."""
        pool = self.transaction_pool
        if not pool:
            return None
        cached = self._pool_hash_cache
        if cached is not None and cached[0] is pool and cached[1] == len(pool):
            return cached[2]
        snapshot = pool.copy()
        pool_hash = blake2b_hash(sort_transaction_pool(snapshot))
        self._pool_hash_cache = (pool, len(snapshot), pool_hash)
        return pool_hash

    def get_upcoming_block_hash(self):
        """blake2b of the NEXT block's content ON TOP OF OUR TIP: parent hash + next height + the mature,
        target-height tx subset (match_transactions_target). This is EXACTLY what block determinism / the
        fast-forward depend on — two nodes at the same tip agree here iff they will build the identical
        next block, INCLUDING an empty one (a produced block always has a hash). Unlike the whole-pool
        hash it excludes immature (min_block not reached) and future-targeted txs that won't be in the
        next block. parent+height make it tip-specific, so nodes on a different tip correctly don't match.
        NEVER None (an empty next block still hashes) — so a peer's absence of eligible txs is a real,
        comparable signal, not a null that poisons the majority.
        Cached per (pool object+length, tip hash, committed-write generation): the match also reads
        the on-chain mined-txid index, and the write generation invalidates on ANY commit, so the
        cache can never outlive the state it was derived from."""
        from ops.block_ops import match_transactions_target
        parent = self.latest_block
        pool = self.transaction_pool
        cached = self._upcoming_hash_cache
        key = (len(pool), parent["block_hash"], kv_ops.write_generation())
        if cached is not None and cached[0] is pool and cached[1:4] == key:
            return cached[4]
        next_height = parent["block_number"] + 1
        matched = match_transactions_target(transaction_list=pool.copy(),
                                            block_number=next_height, logger=self.logger) if pool else []
        if matched is False:                              # a match error -> treat as empty
            matched = []
        upcoming = blake2b_hash([parent["block_hash"], next_height, sort_transaction_pool(matched)])
        self._upcoming_hash_cache = (pool, *key, upcoming)
        return upcoming

    def get_uptime(self) -> int:
        """Whole seconds this node process has been up (NOT system uptime) — refreshed into
        reported_uptime by the core loop and shared with peers via /status."""
        return get_timestamp_seconds() - self.start_time

    # per-peer/per-pass bound on bodies fetched during set reconciliation; the server side caps a
    # /transactions_by_id request at the same figure. The remainder arrives on the next 1s pass.
    _RECONCILE_MAX_IDS = 1000

    def merge_remote_transactions(self, user_origin=False, skip_pool_peers=()) -> None:
        """MEMPOOL SET RECONCILIATION (replaces the full-pool download): for each peer whose
        advertised pool hash differs from ours (skip_pool_peers filters the identical ones), fetch
        its txid LIST (/transaction_ids, ~64B/tx), diff against what we hold + what is already
        MINED, and fetch ONLY the missing bodies (/transactions_by_id). The old path re-downloaded
        every divergent peer's ENTIRE pool every second — O(peers × pool) bandwidth for mostly-known
        data; this is O(peers × ids) + O(genuinely missing bodies), a ~100x cut with ~7KB ML-DSA
        txs. Each missing txid is claimed from ONE peer per pass (no duplicate downloads)."""
        pool_peers = [p for p in self.peers if p not in skip_pool_peers]
        if pool_peers:
            missing = asyncio.run(self._fetch_missing_remote_txs(pool_peers))
            if missing:
                self.merge_transactions(missing, user_origin)

    async def _fetch_missing_remote_txs(self, pool_peers) -> list:
        """ids from all divergent peers in parallel -> per-peer want-lists (deduped across peers,
        mined txids excluded) -> parallel bounded body fetches. Best-effort: a peer that fails or
        predates /transaction_ids is skipped this pass."""
        from compounder import compound_get_tx_ids, post_txs_by_id
        semaphore = asyncio.Semaphore(50)
        ids_by_peer = await compound_get_tx_ids(pool_peers, self.port, self.logger, semaphore)
        if not ids_by_peer:
            return []
        local = {t.get("txid") for t in self.transaction_pool}
        claimed = set()
        plans = []
        for peer, ids in ids_by_peer.items():
            want = []
            for i in ids:
                if (isinstance(i, str) and len(i) <= 64 and i not in local and i not in claimed
                        and kv_ops.tx_get(i) is None):        # already MINED -> never re-fetch (the old flood)
                    want.append(i)
                    if len(want) >= self._RECONCILE_MAX_IDS:
                        break
            if want:
                claimed.update(want)
                plans.append((peer, want))
        if not plans:
            return []
        batches = await asyncio.gather(*[
            post_txs_by_id(peer, self.port, want, self.logger, self.purge_peers_list, semaphore)
            for peer, want in plans])
        out = []
        for batch in batches:
            if isinstance(batch, list):
                out.extend(batch)
        return out


    def merge_transaction(self, transaction, user_origin=False) -> dict:
        """warning, can get stuck if not efficient"""
        # AUDIT FIX: a malicious peer can serve a /transaction_pool list with a malformed entry; the
        # pre-validation field accesses below (sender, max_block) would KeyError/TypeError and abort
        # the whole merge batch. Reject malformed txs up front so the rest of the batch still merges.
        if (not isinstance(transaction, dict) or "sender" not in transaction
                or not isinstance(transaction.get("max_block"), int)
                or isinstance(transaction.get("max_block"), bool)):
            return {"result": False, "message": "Malformed transaction"}

        # Anti-DoS: hard-cap the mempool so a flood (incl. fee-exempt register/heartbeat spam) cannot
        # grow it unbounded and OOM the node. Pairs with the per-IP HTTP rate limiter. The lane cap
        # already stops spam from buying extra block share; this stops it taking the node down.
        # PERF: O(1) length check on the single pool — a flood already at the cap is rejected in O(1).
        if len(self.transaction_pool) >= self.transaction_pool_max_txs:
            return {"result": False, "message": "Mempool full"}

        # CHEAP BOUNDS FIRST (audit): the two integer max_block compares run before the LMDB
        # get_account read — a stale re-gossiped tx (the most common reject under load, since peers
        # re-serve their whole pool every second) must not cost a DB hit to reject.
        # `<=` (was `<`): the drain promotes only max_block STRICTLY greater than the tip
        # (merge_buffer block_min < target), so a tx targeting the current tip was acknowledged
        # "Success", could never be mined, and silently aged out — reject it up front instead.
        if transaction["max_block"] <= self.latest_block["block_number"]:
            msg = {"result": False,
                   "message": f"Target block too low"}
            return msg

        elif transaction["max_block"] > self.latest_block["block_number"] + 360:
            msg = {"result": False,
                   "message": f"Target block too high"}
            return msg

        # AT-MOST-ONCE (2026-07): a txid ALREADY MINED (recorded in the on-chain tx-index by an ancestor
        # block) can never re-enter the mempool. A txid hashes the tx content, so an IDENTICAL transaction
        # has an identical txid — reintroducing/replaying the same transaction is impossible at the entry
        # point. Checked EARLY (one indexed read, before the account read + txid recompute): a re-gossiped
        # already-mined tx is the exact flood the old bug produced. A genuine re-send is a NEW tx (fresh
        # nonce -> fresh txid) the wallet builds on the user's action; it is not blocked here.
        elif isinstance(transaction.get("txid"), str) and kv_ops.tx_get(transaction["txid"]) is not None:
            return {"result": False, "message": "Already mined"}

        # OPEN-lane onboarding: register/heartbeat are fee-exempt ENTRY txs — a brand-new zero-coin
        # address has no on-chain account YET (registration is what creates it), so they must bypass
        # the empty-account anti-spam gate. (register is PoW-gated and heartbeat requires registered=1
        # in validate_transaction, so this opens no spam hole.) Spending txs still need a funded account.
        elif transaction.get("recipient") not in ("register", "heartbeat") \
                and not get_account(transaction["sender"], create_on_error=False):
            msg = {"result": False,
                   "message": f"Empty account"}
            return msg

        elif not validate_txid(transaction, logger=self.logger):  # always enforced (compat gate gone)
            msg = {"result": False,
                   "message": f"Invalid txid"}
            return msg
        # NOTE: the old byte-size validate_base_fee gate is removed: get_byte_size is
        # sys.getsizeof(repr(...)) and is non-deterministic, so it is unsafe as a fee rule.
        # The deterministic MIN_TX_FEE floor is enforced in validate_transaction below.

        else:
            if transaction in self.transaction_pool:
                # Idempotent: already pooled (e.g. a re-gossiped heartbeat) — a benign success, not an
                # error (matches the "already present" handling clients now expect).
                return {"message": "Already present", "result": True}
            try:
                validate_transaction(transaction=transaction,
                                     logger=self.logger,
                                     block_height=self.latest_block["block_number"])
            except Exception as e:
                msg = {"result": False,
                       "message": f"Could not merge remote transaction: {e}"}
                return msg
            else:
                try:
                    validate_single_spending(transaction_pool=self.transaction_pool, transaction=transaction)

                    # mutation tail under the mempool lock: the membership re-check and the append+sort
                    # must be atomic vs the core loop's drain/production swaps and vs sibling
                    # merge_transaction calls on other threads (double-accept / lost-append races).
                    with self.mempool_lock:
                        if transaction not in self.transaction_pool:
                            self.transaction_pool.append(transaction)
                            self.transaction_pool = sort_list_dict(self.transaction_pool)

                except Exception as e:
                    msg = f"Remote transaction failed to validate: {e}"
                    self.logger.info(msg)
                    self.purge_txs_of_sender(transaction["sender"])
                    return {"message": msg,
                            "result": False}

            return {"message": "Success", "result": True}

    def merge_transactions(self, transactions, user_origin=False) -> None:
        """Merge a whole remote batch one tx at a time through merge_transaction, which contains its
        own failures — so a single malformed/invalid entry from a malicious peer can never abort the
        rest of the batch. Per-tx results are deliberately discarded (gossip is best-effort)."""
        for transaction in transactions:
            self.merge_transaction(transaction, user_origin)

    def purge_txs_of_sender(self, sender) -> None:
        """remove all transactions of sender to prevent possible double spending attempt"""
        """of sender sending different txs to different nodes both exhausting balance"""
        # AUDIT FIX: was `for tx in pool: pool.remove(tx)` — removing while iterating shifts the
        # index and SKIPS the element after every hit, so adjacent same-sender txs (the exact
        # double-spend shape this guard exists for) half-survived the purge. Rebuild the pool under
        # the mempool lock instead.
        with self.mempool_lock:
            self.transaction_pool = [t for t in self.transaction_pool if t["sender"] != sender]
