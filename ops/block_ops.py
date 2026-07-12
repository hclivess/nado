import json
import os
import time

from ops import codec
import aiohttp
from .account_ops import get_bonded_registry, get_open_registry, fetch_totals
from config import get_timestamp_seconds, get_config, hostport
from .data_ops import average, get_home, is_hex_hash
from hashing import blake2b_hash_link, blake2b_hash
from signatures import sign as _sign_message, verify as _verify_message, unhex as _unhex
from .address_ops import proof_sender, make_address
from . import kv_ops
from . import segment_store
from .mining_ops import (select_producer_two_lane, lane_of, epoch_of, compute_beacon,
                         total_bonded_shares, block_fork_weight, beacon_commitment)
from protocol import (CHAIN_ID, REWARD_WINDOW, BASE_SUBSIDY, GENESIS_BEACON, EPOCH_LENGTH,
                      B_MIN, TREASURY_GENESIS, BOND_ELASTIC_MULT_BPS, BLOCK_TIMESTAMP_DRIFT)
import zstandard as zstd

# Block bodies are stored as zstd(codec(block)) (#14) — ops/codec.py is a compact portable JSON
# container (it replaced msgpack, which cannot hold >64-bit ints), and zstd recovers the ~2x redundancy
# of hex signature/pubkey strings — important once post-quantum (ML-DSA) sigs bloat blocks. This is purely LOCAL/non-consensus (the block HASH is over
# canonical_bytes, never the stored file), so it can change with no fork. Genesis is also stored
# this way (genesis.make_genesis calls save_block).
# python-zstandard's ZstdCompressor/ZstdDecompressor are NOT thread-safe — a single instance shared across
# the node's threads (mining, peer sync, consensus, API disk-reads) corrupts memory and SEGVs backend_c.so.
# Give each thread its OWN context (cheap; reused within the thread, which is safe).
import threading as _threading
_zstd_tls = _threading.local()

def _zc():
    c = getattr(_zstd_tls, "c", None)
    if c is None:
        c = _zstd_tls.c = zstd.ZstdCompressor(level=3)
    return c

def _zd():
    d = getattr(_zstd_tls, "d", None)
    if d is None:
        d = _zstd_tls.d = zstd.ZstdDecompressor()
    return d


def _pack_block(block) -> bytes:
    """local zstd(codec) block-body encoding — non-consensus, see module note (#14)."""
    return _zc().compress(codec.pack(block))


def _unpack_block(raw: bytes):
    """inverse of _pack_block for locally-stored (trusted) block files."""
    return codec.unpack(_zd().decompress(raw))


# Bounded decompress for the zstd block-sync WIRE payload (get_blocks_after/before). max_output_size caps a
# decompression bomb from an untrusted peer (a tiny frame that expands to gigabytes); a full sync batch of
# real data is a few MB (SYNC_BATCH_BYTES bounds the serve side), so 64 MiB is a generous ceiling.
_ZSTD_WIRE_MAX = 64 << 20

# Block-sync batch bounds, shared by the serve side (nado.py blocks_after/before: hard count cap + byte
# budget so a fat-block batch stays far under the client's _ZSTD_WIRE_MAX bomb cap) and the pull side
# (core_loop emergency sync asks for SYNC_BATCH_MAX; an old peer capped at 100 simply returns fewer —
# the puller never assumes a full batch). Mostly-empty ML-DSA blocks are ~7 KB, so 500 is ~3.5 MB typical.
SYNC_BATCH_MAX = 500
SYNC_BATCH_BYTES = 8 << 20

# Hard cap on the RAW (still-compressed) bytes we will buffer from a peer's block-sync response before
# decoding. The serve side bounds a batch to SYNC_BATCH_BYTES compressed; 2x that is generous headroom for
# framing while still stopping a hostile donor from streaming multi-GB into response.read() (pre-decode OOM,
# which _ZSTD_WIRE_MAX does NOT prevent — it only bounds the DECOMPRESSED side of an already-buffered body).
_SYNC_WIRE_CAP = 2 * SYNC_BATCH_BYTES


def _unpack_wire(body: bytes):
    """decode a peer's zstd block-sync wire payload under the decompression-bomb cap (_ZSTD_WIRE_MAX above).
    Uses the STREAMING bounded decompress: ZstdDecompressor.decompress(max_output_size=...) ignores that
    cap whenever the frame declares its content size (nado's compressor does), allocating the declared
    size up front — so a tiny frame claiming gigabytes would OOM us. Streaming bounds peak allocation."""
    from ops.net_ops import bounded_zstd_decompress
    return codec.unpack(bounded_zstd_decompress(body, _ZSTD_WIRE_MAX))



def bond_elastic_mult_bps() -> int:
    """Bond-elastic emission multiplier in basis points (super hard money — doc/bond-elastic-emission.md).
    The more the network bonds (ratio r = bonded / total_supply), the less is minted; combined with fee
    destruction this makes NADO net-deflationary under usage, with a perpetual tail so security never dies.

    Reads COMMITTED state (bonded registry + cumulative totals). This is deterministic for the SAME reason
    verify_block already recomputes cumulative_weight from live get_bonded_registry(): during sequential
    incorporation the committed state IS the block's parent state, and a snapshot node carries full state
    as-of its checkpoint — so every node type computes the identical multiplier. Integer-only (a runtime
    float could fork on last-ULP differences); the curve lives in the hardcoded BOND_ELASTIC_MULT_BPS table."""
    bonded = total_bonded_shares(get_bonded_registry()) * B_MIN
    t = fetch_totals() or {}
    supply = TREASURY_GENESIS + t.get("produced", 0) - t.get("fees", 0)
    if supply <= 0 or bonded <= 0:
        return BOND_ELASTIC_MULT_BPS[0]                 # r=0 -> full emission (bootstrap / genesis)
    pct = (bonded * 100) // supply
    return BOND_ELASTIC_MULT_BPS[min(100, pct)]


def get_block_reward():
    """FLAT base subsidy scaled by the BOND-ELASTIC multiplier — super hard money (doc/bond-elastic-emission.md).

        reward = BASE_SUBSIDY * m(bonded_ratio)          # m in (~0.24, 1], integer bps

    NO fee-weighted upside and NO ceiling. Fees are DESTROYED, so an emission that rose with fees would mint
    MORE exactly when more is being burned — softening the deflation. Flat mint + fee burn + bond suppression
    is strictly harder money. Because m <= 1:
        MAX emission/block = BASE_SUBSIDY (0.1 NADO, at bonded ratio 0),
        MIN emission/block = m_min * BASE_SUBSIDY (~0.024 NADO) — the perpetual tail; production never
        drops to zero, so there is no security cliff (and no hard cap).
    Deterministic: bond_elastic_mult_bps() reads committed parent state, the same basis verify_block already
    uses to recompute cumulative_weight, so full and snapshot/pruned nodes agree."""
    return BASE_SUBSIDY * bond_elastic_mult_bps() // 10000


def valid_block_timestamp(new_block):
    """Consensus gate: a block's timestamp may lie at most BLOCK_TIMESTAMP_DRIFT seconds in the
    FUTURE of the local clock. That is the ONLY timestamp rule — block_timestamp sits OUTSIDE the
    hash preimage (construct_block hashes it as None), so a producer can stamp wall-clock without
    changing the block hash. The drift window exists because clocks skew between HONEST nodes: with
    zero tolerance, a producer 1 s ahead of a validator got its block rejected, and the production
    clamp (max(now, parent_ts)) propagated one fast clock's stamp to every following producer —
    "Invalid block timestamp" with no attacker anywhere."""
    new_timestamp = new_block["block_timestamp"]
    if new_timestamp > get_timestamp_seconds() + BLOCK_TIMESTAMP_DRIFT:
        return False
    else:
        return True


def _lands_flexibly(transaction):
    """True if a tx has NO landing-block-dependent protocol timing, so it may be included in ANY block up to
    its max_block (a plain EXPIRY window) instead of one exact height. Value transfers, `blob` (exec-layer,
    applied in L1 order regardless of which block), and bridge in/out simply apply when included. Everything
    else — epoch-timed RANDAO (commit/reveal/attest), release-timed bond/unbond, PoW-anchored register, settle,
    governance — keeps EXACT landing so its timing invariants hold. max_block still bounds the tx's life
    (mempool gate: tip < max_block < tip+360), so an unincluded tx still expires and can't be replayed."""
    r = transaction.get("recipient")
    return r in ("blob", "bridge", "bridge_withdraw") or (isinstance(r, str) and r.startswith("ndo"))


def check_target_match(transaction_list, block_number, logger):
    """Verification-side gate: EVERY transaction in the block must target exactly this block number
    (max_block binds a tx to one height, so it cannot be replayed into a different block).
    Fails CLOSED — a malformed transaction returns False, never a pass."""
    try:
        for transaction in transaction_list:
            tb = transaction["max_block"]
            if _lands_flexibly(transaction):
                # eligible window [min_block, max_block] (see match_transactions_target): too-early is as
                # invalid as expired, so no producer can front-run a tx before it has propagated.
                if block_number < transaction.get("min_block", 0) or block_number > tb:
                    return False
            elif tb != block_number:             # timing-critical: must land at exactly max_block
                return False
        return True
    except Exception as e:
        logger.error(f"Error when checking transaction target block: {e}")
        return False


def match_transactions_target(transaction_list, block_number, logger):
    """Producer-side pool filter — the assembly mirror of check_target_match: keep only txs targeting
    this block number, drop duplicate reserved txs and cap blobs to the per-block byte budget, i.e.
    pre-apply everything verify_block will enforce so an honest producer never assembles a block its
    peers must reject. False on error."""
    try:
        from ops import kv_ops
        matched_txs = []
        seen = set()

        for transaction in transaction_list:
            tb = transaction["max_block"]
            txid = transaction.get("txid")
            # AT-MOST-ONCE (2026-07): never re-select a txid already mined (in the on-chain tx-index) or
            # already picked for THIS candidate. A flexibly-landing tx is otherwise eligible for every
            # block up to its max_block; without this it was re-included (and re-applied) each block —
            # the bridge-deposit double-credit. verify_block enforces the same rule for remote blocks.
            if txid in seen or kv_ops.tx_get(txid) is not None:
                continue
            if _lands_flexibly(transaction):
                # INCLUSION DELAY: a flexibly-landing tx becomes eligible only from its sender-set
                # min_block (default 0). Set to submit_tip + a couple blocks by wallets, this guarantees
                # the tx has gossiped to EVERY producer before any of them may include it — so all nodes
                # hold the identical mature tx set at each height and build byte-identical blocks (the
                # deterministic fast-forward then always hits). min_block is in the signed txid, so every
                # node agrees on the eligibility window; absent -> 0 keeps historical blocks valid.
                if transaction.get("min_block", 0) <= block_number <= tb:   # [min_block, max_block]
                    matched_txs.append(transaction)
                    seen.add(txid)
            elif tb == block_number:             # timing-critical: exact landing
                matched_txs.append(transaction)
                seen.add(txid)

        # AUDIT FIX: drop duplicate reserved txs (e.g. two withdraws of one unbond, two heartbeats of
        # one epoch) so an honest producer never assembles a block verify_block would reject.
        from ops.transaction_ops import dedupe_reserved, cap_block_blobs
        # DA cap: keep blob txs only up to the per-block byte budget so the assembled block passes
        # assert_block_blob_cap (excess blobs wait for a later block).
        return cap_block_blobs(dedupe_reserved(matched_txs), logger)
    except Exception as e:
        logger.error(f"Error when matching transactions to target block: {e}")
        return False


def get_block_candidate(
        transaction_pool, logger, latest_block
):
    """Deterministically assemble the NEXT block on top of latest_block. Every honest node must
    build the IDENTICAL candidate from committed parent state: the two-lane draw (open registry +
    RANDAO-gated bonded registry under the epoch beacon) picks the SAME winner everywhere, the tx
    set is the pool subset targeting this height (deduped, blob-capped), and construct_block sorts
    by txid — so the network converges on one hash even when the winner is offline (win-offline).
    Only the timestamp is local (outside the hash preimage). Returns None when no lane has an
    eligible producer; the caller skips the slot."""
    block_number = latest_block["block_number"] + 1

    # S4.4 TWO-LANE: select the producer from the OPEN registry (registered+present, zero-coin) and
    # the BONDED registry (locked stake) per the lane this slot falls in (lane_of). The split is a
    # beacon permutation of slot indices, so the open lane is exactly OPEN_BPS of blocks regardless
    # of identity count (Sybil bound). Every node computes the SAME winner deterministically from
    # committed parent state and builds the identical block crediting the winner ADDRESS. block_ip
    # is set to the winner address so the hashed body is identical per node.
    epoch = epoch_of(block_number)
    beacon = epoch_beacon(epoch)
    open_registry = get_open_registry(epoch)
    bonded_registry = get_bonded_registry()
    # RANDAO gate (pass-through while RANDAO_ENFORCED is off — reveals are optional). The full
    # registry always backs block_fork_weight below (withholding must not move fork-choice).
    eligible_bonded = randao_eligible_bonded(bonded_registry, epoch)
    winner = select_producer_two_lane(open_registry, eligible_bonded, beacon, slot=block_number)
    if winner is None:
        logger.error("No eligible producer (open+bonded empty / bonded slot skipped); skipping block")
        return None
    logger.info(f"Block {block_number} producer [{lane_of(block_number, beacon)} lane]: {winner} "
                f"(open:{len(open_registry)} bonded:{len(eligible_bonded)}/{len(bonded_registry)})")

    targeted_transactions = match_transactions_target(transaction_list=transaction_pool.copy(),
                                                      block_number=block_number,
                                                      logger=logger)

    block = construct_block(
        # Wall-clock, kept monotonic (>= parent). The old `parent + block_time` was anchored to the
        # genesis epoch, so block times drifted from real time (froze near genesis) — breaking the
        # explorer's dates + the since_last_block timing heuristic. valid_block_timestamp only requires
        # <= now, so this is safe.
        block_timestamp=max(get_timestamp_seconds(), latest_block["block_timestamp"]),
        block_number=block_number,
        parent_hash=latest_block["block_hash"],
        creator=winner,
        transaction_pool=targeted_transactions,
        block_reward=get_block_reward(),
        parent_cumulative_fees=latest_block.get("cumulative_fees", 0),
        parent_cumulative_weight=latest_block.get("cumulative_weight", 0),
        chain_id=CHAIN_ID,   # informational label on new blocks (not hashed); a rename shows up here
        block_weight=block_fork_weight(bonded_registry, block_number),  # as-of-parent (registry read above)
    )
    return block


def recommended_fee(latest_block) -> int:
    """Integer mean fee of the TIP block's transactions (0 when it carried none) — the wallet fee
    hint served by /get_recommended_fee. Pure in-memory read of the caller's latest block: the old
    fee_over_blocks helper claimed a 250-block average but only ever re-read the tip's tx list 250
    times over, while ALSO re-loading block bodies from disk on every API call."""
    fees = [t["fee"] for t in latest_block.get("block_transactions", [])]
    return average(fees) if fees else 0


def _stamp_child(block):
    """Stamp the DERIVED child pointer onto a loaded block: child = the CANONICAL block at height+1
    (number->hash index). The old model persisted child_hash into the parent's stored body
    (update_child_in_latest_block rewrote the file), which the append-only segment store forbids —
    and deriving is strictly MORE reorg-correct: a stored pointer kept naming a rolled-back orphan
    until its replacement arrived, while the index always names the live canonical child (or None
    at the tip). The forward sync walk (/get_blocks_after) and the explorer read this field."""
    try:
        block["child_hash"] = kv_ops.hash_by_number(block["block_number"] + 1)
    except Exception:
        block["child_hash"] = None
    return block


def _load_body(block_hash: str):
    """Verified block dict from the segment store via the hash->locator index, or None. Every
    failure mode (no locator, deleted segment, crc/hash mismatch) is a clean miss."""
    loc = kv_ops.block_loc_get(block_hash)
    if loc is None:
        return None
    payload = segment_store.read(loc[0], loc[1], loc[2], block_hash)
    if payload is None:
        return None
    return _stamp_child(_unpack_block(payload))


def migrate_block_store(logger) -> int:
    """One-time, idempotent startup migration into the append-only SEGMENT store: sweep any legacy
    per-file bodies (flat blocks/*.block AND sharded blocks/<hhh>/*.block) into segments, indexing
    each hash->locator, then delete the file. Batched (append N -> one fsync via the store's
    per-record fsync -> one locator txn -> unlink N) and crash-safe: a file is deleted only AFTER
    its locator committed, so a crash re-migrates at most the current batch (duplicate records are
    inert garbage; the locator always points at the newest copy). Also repairs a torn segment tail
    (segment_store.init) on every boot."""
    segment_store.init()
    root = f"{get_home()}/blocks"
    moved = 0
    batch = []                                   # [(path, hash, seg, off, ln)]

    def _flush():
        nonlocal moved
        if not batch:
            return
        with kv_ops.write_txn():
            for _p, h, seg, off, ln in batch:
                kv_ops.block_loc_put(h, seg, off, ln)
        for p, _h, _s, _o, _l in batch:
            try:
                os.remove(p)
            except OSError as e:
                logger.warning(f"migrate: could not remove {p}: {e}")
        moved += len(batch)
        batch.clear()

    try:
        entries = []
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(".block"):
                    entries.append(entry.path)
                elif entry.is_dir() and len(entry.name) == 3:          # shard dir from the interim layout
                    with os.scandir(entry.path) as sub:
                        entries.extend(e.path for e in sub if e.is_file() and e.name.endswith(".block"))
    except FileNotFoundError:
        return 0
    for path in entries:
        h = os.path.basename(path)[:-6]
        if not is_hex_hash(h):
            continue
        try:
            with open(path, "rb") as f:
                payload = f.read()
        except OSError as e:
            logger.warning(f"migrate: could not read {path}: {e}")
            continue
        seg, off, ln = segment_store.append(h, payload)
        batch.append((path, h, seg, off, ln))
        if len(batch) >= 512:
            _flush()
    _flush()
    # sweep now-empty shard dirs from the interim layout
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_dir() and len(entry.name) == 3:
                    try:
                        os.rmdir(entry.path)
                    except OSError:
                        pass
    except FileNotFoundError:
        pass
    if moved:
        logger.warning(f"Block store migrated to append-only segments: {moved} body file(s) folded "
                       f"into blocks/seg-*.dat (locators in LMDB block_loc)")
    return moved


def get_block(block):
    """return a block by its hash"""
    # SECURITY: `block` reaches here from the unauthenticated /get_block?hash= arg;
    # validate it is a real block hash so a malformed value can never resolve to a body
    # (also collapses the missing-vs-malformed responses into one 'not found').
    if not is_hex_hash(block):
        return False
    body = _load_body(block)
    return body if body is not None else False


def get_block_number(number):
    """block dict by HEIGHT via the number->hash index; False if unindexed, pruned, or unreadable."""
    try:
        block_hash = kv_ops.hash_by_number(number)
        if not block_hash:
            return False
        return get_block(block_hash)
    except Exception:
        return False


def get_block_hash_by_number(number):
    """block hash for a block number from the block index, or None (no block-file read)."""
    try:
        return kv_ops.hash_by_number(number)
    except Exception:
        return None


def prune_block_bodies(finalized_height: int, retention: int, logger) -> int:
    """ROLLING MODE (doc/rolling-mode-and-da.md): unreference block BODIES (drop their segment-store
    locators) for FINALIZED heights older than the retention window, while KEEPING the number<->hash
    index (so the beacon/FFG hash lookbacks via get_block_hash_by_number still resolve) and STATE
    (never touched). Segment FILES are reclaimed wholesale once every body in them is unreferenced;
    blob-bearing bodies are copied forward into the active segment first (contract history).

    Correctness floor: the deepest consensus read of a historical BODY today is rollback, which
    re-reads bodies within FINALITY_DEPTH of the tip (the old get_block_reward lookback at
    tip-REWARD_WINDOW no longer exists — emission is flat * bond-elastic from committed state, and
    REWARD_WINDOW survives only as extra margin here). We NEVER prune within
    max(retention, REWARD_WINDOW+FINALITY_DEPTH+1) of the finalized height — even a misconfigured tiny
    `retention` cannot break a legal rollback. Returns the number of files pruned.

    Idempotent + incremental: a `pruned_below` watermark (meta) records the height under which bodies
    are already gone, so each call scans only the new delta; per-call work is capped so enabling this on
    a long chain never stalls the loop (the rest prunes on later ticks). Monotonic — finalized_height
    only rises and pruned heights are far below any rollback window, so bodies are never wrongly removed."""
    from protocol import FINALITY_DEPTH, HISTORY_RETENTION_BLOCKS
    retention = int(retention) if retention and int(retention) > 0 else HISTORY_RETENTION_BLOCKS
    floor = REWARD_WINDOW + FINALITY_DEPTH + 1                 # hard safety floor, independent of config
    eff_retention = max(retention, floor)
    prune_below = int(finalized_height) - eff_retention
    if prune_below <= 0:
        return 0
    start = kv_ops.meta_get_int("pruned_below", 0)
    if start >= prune_below:
        return 0
    end = min(prune_below, start + 4000)                      # bound per-call work (first enable on a long chain)
    pruned = 0
    kept_blob = 0
    for h in range(start, end):
        bh = kv_ops.hash_by_number(h)                         # index is kept -> still resolvable after prune
        if not bh:
            continue
        loc = kv_ops.block_loc_get(bh)
        if loc is None:
            continue                                          # already unreferenced
        # CONTRACT-DATA SAFETY (2026-07-11): the execution node reads `blob` payloads (contract
        # deploys/calls) DIRECTLY out of block bodies as it tails finalized blocks. If a blob-bearing
        # body is pruned before a lagging / cold-starting exec node consumes it, that contract data is
        # gone forever (the exec tail skips body-less blocks). So NEVER prune a body that carries a
        # blob tx — COPY IT FORWARD into the active segment instead (locator repoints, old segment is
        # unpinned), keeping the full contract history replayable while whole old segments still GC.
        # (Bodies are loaded only during pruning, which is incremental + bounded; blob blocks are rare.)
        try:
            body = load_block_from_hash(bh, logger)
            if body and any(t.get("recipient") == "blob" for t in body.get("block_transactions", [])):
                if loc[0] != segment_store.active_segment():   # already in the active segment -> nothing to do
                    payload = segment_store.read(loc[0], loc[1], loc[2], bh)
                    if payload is None:
                        continue                               # can't read it -> never touch it (fail-safe)
                    seg, off, ln = segment_store.append(bh, payload)
                    kv_ops.block_loc_put(bh, seg, off, ln)     # repoint; old segment's live count drops
                kept_blob += 1
                continue
        except Exception:
            continue                                           # can't inspect it -> never delete it (fail-safe)
        if kv_ops.block_loc_del(bh):
            pruned += 1
    kv_ops.meta_set_int("pruned_below", end)                  # advance past gap heights too (idempotent, monotonic)
    # WHOLE-SEGMENT GC: a segment whose live-locator count reached zero holds only unreferenced
    # garbage — reclaim the file. The ACTIVE segment is never deleted (segment_store refuses).
    reclaimed = 0
    try:
        active = segment_store.active_segment()
        live = kv_ops.seg_live_counts()                       # segments with >0 live locators
        for name in os.listdir(f"{get_home()}/blocks"):
            if not (name.startswith("seg-") and name.endswith(".dat")):
                continue
            seg = int(name[4:-4], 16)
            if seg != active and live.get(seg, 0) == 0 and segment_store.delete_segment(seg):
                reclaimed += 1
    except Exception as e:
        logger.warning(f"prune: segment GC pass failed (non-fatal): {e}")
    # Keep the earliest-block pointer at the earliest RETAINED body (height `end`, which is NOT pruned), so
    # get_block_ends_info never loads a pruned body (which returns False and 403s /status).
    neh = kv_ops.hash_by_number(end)
    if neh:
        try:
            _update_block_ends({"earliest_block": neh}, logger=logger)
        except Exception as e:
            logger.warning(f"prune: earliest-pointer update failed: {e}")
    if pruned or kept_blob or reclaimed:
        logger.info(f"Rolling mode: unreferenced {pruned} block bodies below height {end} "
                    f"(retention {eff_retention}, finalized {finalized_height}); carried {kept_blob} "
                    f"blob-bearing bodies forward (contract history); reclaimed {reclaimed} dead "
                    f"segment file(s); all indexes + state kept.")
    return pruned


def epoch_beacon(epoch):
    """Per-epoch, grind-resistant selection beacon (S4.3).

    Epochs 0-1 use the fixed GENESIS_BEACON (no finalized prior epoch exists yet). For epoch>=2
    the beacon chains GENESIS_BEACON with the hash of the FIRST block of the immediately-preceding
    epoch ((epoch-1)*EPOCH_LENGTH) -- a block that is >= EPOCH_LENGTH blocks behind the first slot
    this beacon governs, so it is deeply finalized and is NOT the grindable parent hash (audit M6).
    The per-slot rotation comes from select_producer hashing [beacon, slot].

    INVARIANT: max_rollbacks < FINALITY_DEPTH < EPOCH_LENGTH (enforced in memserver, #17 step 1), so
    the anchor block is FINALIZED before any epoch it governs goes live and can never be reorged out
    from under that epoch (otherwise the whole epoch's winners would flip). The full on-chain
    commit-reveal RANDAO (mining_ops.compute_beacon over revealed secrets) is the hardening step.

    FAIL-LOUD (#18 step 4): the old code SILENTLY substituted GENESIS_BEACON when the anchor was
    missing locally. That is a consensus split — a node lacking the (finalized) anchor would draw a
    DIFFERENT producer set for the whole epoch than synced nodes. Since finality guarantees the anchor
    exists for any node properly synced past it, a missing anchor means THIS node is not adequately
    synced; we now RAISE instead of substituting, so the block is skipped (the caller resyncs) rather
    than the node forking onto a divergent beacon."""
    if epoch < 2:
        return GENESIS_BEACON  # genuinely no finalized prior epoch yet (not a fallback)
    anchor = get_block_hash_by_number((epoch - 1) * EPOCH_LENGTH)
    if not anchor:
        raise ValueError(
            f"epoch_beacon: finalized anchor block #{(epoch - 1) * EPOCH_LENGTH} for epoch {epoch} is "
            f"missing locally — refusing to substitute GENESIS_BEACON (would fork the producer set); "
            f"this node must resync")
    # COMMIT-REVEAL RANDAO (#7 step 7): mix the finalized anchor with the bonded validators' REVEALED
    # secrets for this epoch, so no single anchor-producer controls the beacon. Secrets are committed
    # in epoch E-2 and revealed in E-1's FINALIZED window (validation bounds the reveal's max_block
    # to <= E*EPOCH_LENGTH - FINALITY_DEPTH - 1), so they are immutable when this beacon is first needed
    # (block E*EPOCH_LENGTH) -> deterministic + grind-resistant. With zero reveals the beacon falls back
    # to the anchor-only value (liveness); compute_beacon re-sorts, so input order is irrelevant.
    secrets = kv_ops.reveals_for_epoch(epoch)
    return compute_beacon(GENESIS_BEACON, [anchor] + secrets)


# memo for randao_eligible_bonded: {(epoch, sorted-secrets-tuple): {opened commitments}} — reveals
# for an epoch are FINALIZED before its first slot (reveal window ends EPOCH_LENGTH*E - FINALITY_DEPTH - 1),
# so during epoch E the set is immutable; keying by the secret tuple makes the memo self-correcting
# anyway (an E-1 reorg that removes a reveal changes the key). Bounded to one entry.
_randao_elig_memo = {}


def randao_eligible_bonded(bonded_registry: dict, epoch: int) -> dict:
    """RANDAO participation gate for the bonded-lane producer draw (consensus). With
    RANDAO_ENFORCED off (current policy — see protocol.py), revealing is OPTIONAL and this is a
    pass-through: the draw runs over the FULL bonded registry, and reveals only strengthen the
    beacon when someone chooses to contribute.

    When RANDAO_ENFORCED is on, epoch E only admits bonded identities that REVEALED their
    committed secret for E — no reveal, no production rights that epoch (the withholding penalty
    the RANDAO design deferred: the last revealer's 1-bit reveal/withhold choice then forfeits an
    epoch of bonded rewards instead of being free). Deterministic: reveals/commits are committed
    parent state, finalized before epoch E begins, so every node filters identically at any time
    (replay included). Epochs 0-1 are exempt (no commit window exists for them — validation
    requires target_epoch >= 2). An ALL-withheld epoch filters to {} which
    select_producer_two_lane treats as an empty bonded lane -> open-lane fallback: liveness is
    never at stake. FFG/settlement/treasury quorums intentionally stay on the FULL registry —
    finality must not hinge on beacon participation. Fork weight (block_fork_weight) also stays on
    the FULL registry, else withholding would manipulate fork-choice."""
    from protocol import RANDAO_ENFORCED
    if not RANDAO_ENFORCED or epoch < 2 or not bonded_registry:
        return bonded_registry
    secrets = tuple(sorted(kv_ops.reveals_for_epoch(epoch)))
    memo_key = (epoch, secrets)
    revealed = _randao_elig_memo.get(memo_key)
    if revealed is None:
        revealed = {beacon_commitment(s) for s in secrets}
        _randao_elig_memo.clear()
        _randao_elig_memo[memo_key] = revealed
    return {a: info for a, info in bonded_registry.items()
            if kv_ops.commit_get(a, epoch) in revealed}


def mining_status(address, latest_block_number, block_time):
    """Two-lane mining snapshot for the wallet's 'expected time to mine' + selection visualization.
    Pure read of committed state. Weights are integer/deterministic; the time ESTIMATE uses floats
    (display only, never consensus). For the slot after the tip: reports the lane split, each lane's
    total weight + size, and `address`'s open/bonded weight, then derives expected blocks/seconds
    between wins from this identity's share of each lane."""
    from .mining_ops import open_shares, selection_shares
    from protocol import K_OPEN
    next_block = latest_block_number + 1
    epoch = epoch_of(next_block)
    beacon = epoch_beacon(epoch)
    open_reg = get_open_registry(epoch)
    bonded_reg = get_bonded_registry()
    from .mining_ops import bond_ramp_weight
    # apply the producer-selection ramp to the DISPLAY weights too, so a freshly-bonded miner's "expected
    # time to mine" honestly reflects that its bonded weight ramps up over BOND_RAMP_EPOCHS (consensus draw
    # is the source of truth; this just keeps the estimate consistent with it).
    def _bwt(info):
        """display-side bonded weight: selection shares with the bond-age ramp applied (mirrors the consensus draw)"""
        return bond_ramp_weight(selection_shares(info["bonded"], info.get("fidelity")),
                                info.get("bond_since"), epoch)
    total_open = sum(open_shares(i.get("fidelity")) for i in open_reg.values())
    total_bonded = sum(_bwt(i) for i in bonded_reg.values())
    my_open = open_shares(open_reg[address]["fidelity"]) if address in open_reg else 0
    my_bonded = _bwt(bonded_reg[address]) if address in bonded_reg else 0
    open_frac = K_OPEN / EPOCH_LENGTH
    bonded_frac = (EPOCH_LENGTH - K_OPEN) / EPOCH_LENGTH
    expected_wins_per_block = 0.0
    if total_open:
        expected_wins_per_block += open_frac * (my_open / total_open)
    if total_bonded:
        expected_wins_per_block += bonded_frac * (my_bonded / total_bonded)
    expected_blocks = (1.0 / expected_wins_per_block) if expected_wins_per_block > 0 else None
    return {
        "epoch": epoch, "beacon": beacon, "next_block": next_block,
        "epoch_length": EPOCH_LENGTH, "k_open": K_OPEN, "block_time": block_time,
        "open_registry_size": len(open_reg), "total_open_weight": total_open,
        "bonded_registry_size": len(bonded_reg), "total_bonded_shares": total_bonded,
        "address": address, "registered_present": address in open_reg,
        "my_open_weight": my_open, "my_bonded_shares": my_bonded,
        "expected_blocks_between_wins": expected_blocks,
        "expected_seconds_between_wins": (expected_blocks * block_time) if expected_blocks else None,
    }


def block_already_indexed(block_hash):
    """True if this exact block was already incorporated (its hash is in the block index).
    Used to make incorporate_block idempotent against a re-fetched / replayed block."""
    try:
        return kv_ops.block_hash_indexed(block_hash)
    except Exception:
        return False


def load_block_from_hash(block_hash: str, logger):
    """load a block body by hash, returning False instead of raising — sync and block-ends paths
    probe for bodies that may legitimately be absent (rolling-mode pruned). The hash is validated
    so a peer-supplied value can never resolve outside the locator index; the segment read is
    crc+hash verified, so a corrupt record is a clean miss, never junk."""
    # SECURITY: reachable from the unauthenticated /get_blocks_after / /get_blocks_before hash arg.
    if not is_hex_hash(block_hash):
        return False
    try:
        body = _load_body(block_hash)
        return body if body is not None else False
    except Exception as e:
        logger.info(f"Failed to load block {block_hash}: {e}")
        return False




def block_content_hash(block: dict) -> str:
    """Recompute a block's hash from its CONTENT exactly as construct_block does: transactions sorted by
    txid, and block_hash / child_hash / block_timestamp excluded from the hashed preimage. A block whose
    stored block_hash != this is hash-INCONSISTENT (a forgery, or a block corrupted by a half-completed
    reorg that rewrote a hashed field — e.g. parent_hash — without re-hashing)."""
    txs = sorted(block.get("block_transactions", []), key=lambda t: t["txid"])
    preimage = {
        "block_number": block["block_number"], "block_hash": None, "parent_hash": block["parent_hash"],
        "block_creator": block["block_creator"], "block_timestamp": None, "block_transactions": txs,
        "child_hash": None, "block_reward": block["block_reward"],
        "cumulative_fees": block["cumulative_fees"], "cumulative_weight": block["cumulative_weight"],
        "chain_id": None,   # NON-HASHED (see construct_block): genesis-hash + parent linkage identify the
                            # chain, so a CHAIN_ID change never alters a block hash or breaks genesis sync.
    }
    return blake2b_hash_link(link_from=block["parent_hash"], link_to=preimage)


def save_block(block: dict, logger):
    """Persist a block body into the append-only SEGMENT store (ops/segment_store.py) — the single
    storage choke point, where the HASH-CONSISTENCY invariant is enforced: the (peer-supplied) hash
    must be a real hex hash, and a non-genesis block whose content does not hash to its own
    block_hash is REFUSED with a raise — persisting a forged or reorg-corrupted body and chaining
    onto it would fork every honest node that later re-derives the true hash. Crash-safe, same
    contract as the old temp+fsync+os.replace file: the record is APPENDED and FSYNCED before its
    LMDB locator commits, so a reader can never resolve a half-written body (a crash between the
    two leaves inert unreferenced bytes). Re-saving a hash appends a fresh record and repoints the
    locator (last-write-wins, mirroring the old file overwrite). Bounded retries then raise, so a
    persistent error (full disk, permissions) fails LOUDLY instead of silently wedging the caller."""
    # SECURITY: a synced block's hash is peer-supplied; refuse anything that isn't a real hex hash.
    if not is_hex_hash(block.get("block_hash")):
        logger.warning(f"Refusing to save block with invalid hash {block.get('block_hash')!r}")
        return False

    # HASH-CONSISTENCY INVARIANT (anti-fork, storage choke point): NEVER persist a block whose stored hash
    # does not match its own content. A half-completed reorg or a forged block could otherwise land on disk
    # and get chained onto, forking every honest node that later re-derives the true hash (the "stuck /
    # rolls back and forth" wedge). Genesis (block 0) is hashed differently (over timestamp+[] only), skip it.
    _hashed = ("block_number", "parent_hash", "block_creator", "block_transactions", "block_reward",
               "cumulative_fees", "cumulative_weight")   # chain_id is NON-hashed (informational)
    if block.get("block_number", 0) != 0 and all(k in block for k in _hashed):
        expected = block_content_hash(block)
        if expected != block["block_hash"]:
            logger.error(f"Refusing to save hash-INCONSISTENT block #{block.get('block_number')}: its content "
                         f"hashes to {expected[:16]} but block_hash={str(block.get('block_hash'))[:16]} "
                         f"(forged or corrupt) — this would fork the chain")
            raise ValueError(f"hash-inconsistent block #{block.get('block_number')} refused")

    # child_hash is DERIVED at read time from the number->hash index (_stamp_child) — normalize it
    # to None in the stored record so the append-only store never carries a stale pointer.
    stored = dict(block)
    stored["child_hash"] = None

    last_error = None
    for _ in range(60):
        try:
            payload = _pack_block(stored)
            seg, off, ln = segment_store.append(block["block_hash"], payload)   # fsynced
            kv_ops.block_loc_put(block["block_hash"], seg, off, ln)             # then referenced
            return True
        except Exception as e:
            last_error = e
            logger.warning(f"Failed to save block {block['block_hash']} due to {e}")
            time.sleep(0.5)
    raise RuntimeError(f"Could not save block {block['block_hash']} after retries: {last_error}")


def get_block_ends_info(logger):
    """Load the chain ends as FULL block dicts: {"earliest_block", "latest_block"} resolved from the
    hash pointers in index/block_ends.dat. ROLLING-MODE recovery: the recorded earliest BODY may
    have been pruned, so on a failed load walk up from the pruned_below watermark to the earliest
    RETAINED body (last resort: the latest block) and repair the pointer — earliest_block must
    ALWAYS come back as a real dict, or every /status call 403s and stalls the exec node + wallet
    connection. Returns None on failure (logged)."""
    try:
        with open(f"{get_home()}/index/block_ends.dat", "r") as ends_file:
            block_ends = json.load(ends_file)

            latest_block = load_block_from_hash(block_hash=block_ends["latest_block"],
                                                logger=logger)
            earliest_block = load_block_from_hash(block_hash=block_ends["earliest_block"],
                                                  logger=logger)

            # ROLLING MODE: the recorded earliest BODY may have been pruned, so load_block_from_hash
            # returns False. Recover to the earliest RETAINED body via the pruned_below watermark (bodies
            # at/above it are kept) so memserver.earliest_block is ALWAYS a real dict — otherwise every
            # /status (earliest_block["block_hash"]) 403s, which stalls the exec node + wallet connection.
            if not earliest_block:
                floor_h = kv_ops.meta_get_int("pruned_below", 0)
                for h in (floor_h, floor_h + 1, floor_h + 2):
                    bh = kv_ops.hash_by_number(h)
                    cand = load_block_from_hash(block_hash=bh, logger=logger) if bh else None
                    if cand:
                        earliest_block = cand
                        break
                if not earliest_block:
                    earliest_block = latest_block          # last resort — the latest body is always kept
                if earliest_block and earliest_block.get("block_hash"):
                    try:
                        _update_block_ends({"earliest_block": earliest_block["block_hash"]}, logger=logger)
                    except Exception:
                        pass

            block_ends = {"earliest_block": earliest_block,
                          "latest_block": latest_block}

            return block_ends

    except Exception as e:
        logger.info(f"Failed to get block ends info: {e}")


def unindex_block(block, logger):
    """Rollback mirror of index_block_number + save_block: remove both directions of the
    number<->hash mapping AND the body's segment locator INSIDE the active rollback write txn — so
    a failure aborts the WHOLE rollback atomically (index/unindex must be exact inverses or a
    replayed block double-applies), and an aborted rollback RESTORES the body reference too. This
    is strictly stronger than the old best-effort file unlink, which could delete a body whose
    rollback then aborted. The unreferenced record bytes stay in the segment as inert garbage
    (whole-segment GC reclaims them); the orphan can never be served — every lookup goes through
    the locator."""
    kv_ops.block_index_del(block_number=block['block_number'], block_hash=block['block_hash'])
    kv_ops.block_loc_del(block['block_hash'])


def _update_block_ends(updates: dict, logger):
    """Atomically merge `updates` into index/block_ends.dat (temp file + fsync + os.replace).

    Replaces the old write-then-read-back-and-compare `while not old_hash == new_hash` spin:
    that inner loop never exited if the read-back didn't match (concurrent writer, fs cache,
    full disk), wedging the single block-processing thread forever. block_ends is written only
    by the core thread (genesis/snapshot/incorporate/rollback), so an atomic replace is safe
    and needs no readback. Bounded retries, then raise rather than hang."""
    path = f"{get_home()}/index/block_ends.dat"
    tmp = f"{path}.tmp"
    last_error = None
    for _ in range(30):
        try:
            current = {}
            if os.path.exists(path):
                with open(path, "r") as infile:
                    current = json.load(infile)
            current.update(updates)
            with open(tmp, "w") as outfile:
                json.dump(current, outfile)
                outfile.flush()
                os.fsync(outfile.fileno())
            os.replace(tmp, path)
            return current
        except Exception as e:
            last_error = e
            logger.info(f"Failed to update block_ends {updates}: {e}")
            time.sleep(0.5)
    raise RuntimeError(f"Could not persist block_ends {updates} after retries: {last_error}")


def set_earliest_block_info(earliest_block: dict, logger):
    """persist the earliest-block pointer (rolling-mode retention floor) into block_ends.dat; returns the block."""
    _update_block_ends({"earliest_block": earliest_block["block_hash"]}, logger=logger)
    return earliest_block


def set_latest_block_info(latest_block: dict, logger):
    """Advance the latest-block pointer in block_ends.dat (atomic replace via _update_block_ends)
    and re-put the number<->hash mapping. Shared by incorporate, rollback and genesis/snapshot; the
    'applied' source of truth stays the IN-TXN index_block_number marker, this pointer is just the
    fast path to the tip."""
    _update_block_ends({"latest_block": latest_block["block_hash"]}, logger=logger)

    # idempotent number<->hash mapping (already written inside the incorporate txn by
    # index_block_number; re-putting the same pair here is a no-op).
    kv_ops.block_index_put(block_number=latest_block['block_number'],
                           block_hash=latest_block['block_hash'])

    return latest_block


def index_block_number(block):
    """Insert the block's number<->hash mapping — the 'applied' marker that block_already_indexed
    checks. Called INSIDE the incorporate write txn so the marker commits ATOMICALLY with the
    balance/totals mutations: a crash either applies the whole block or none of it, so a replay
    on restart can never double-credit (audit LO-1/CO-4)."""
    kv_ops.block_index_put(block_number=block["block_number"], block_hash=block["block_hash"])


def construct_block(
        block_timestamp: int,
        block_number: int,
        parent_hash: str,
        creator: str,
        transaction_pool: list,
        block_reward: int,
        parent_cumulative_fees: int = 0,
        parent_cumulative_weight: int = 0,
        block_weight: int = 0,
        chain_id: str = None,
):
    """timestamp is approximate so hash matches across the network.

    chain_id is a NON-HASHED informational field (like block_timestamp / child_hash): it is stamped on the
    block for display + the peer handshake but is EXCLUDED from block_content_hash and the authorship
    signature. A chain is identified by its GENESIS HASH (unique via GENESIS_TIMESTAMP) and every block's
    parent-hash linkage back to it — so a foreign/pre-reboot block can never replay here (its parent_hash
    won't match our genesis). Keeping chain_id out of the hash is what makes 'sync from genesis always works'
    invariant to the CHAIN_ID constant: bumping it changes tx domain-separation + the network handshake
    (meaningful) but can NEVER retroactively change a block hash or break validation of historical blocks.
    (Transaction replay across chains is prevented separately by the per-tx chain_id.)"""
    if chain_id is None:
        chain_id = CHAIN_ID

    # CO-8: canonical in-block transaction order. Sort by txid so any two honest nodes that select
    # the SAME tx set produce the IDENTICAL block hash — they can no longer fork on ordering alone
    # (audit CO-8). Deterministic and integer/string-only (browser-reproducible).
    transaction_pool = sorted(transaction_pool, key=lambda t: t["txid"])

    block_fees = sum(transaction["fee"] for transaction in transaction_pool)

    block_message = {
        "block_number": block_number,
        "block_hash": None,
        "parent_hash": parent_hash,
        # block_creator = the winning producer ADDRESS (RELAUNCH-2: the old IP-era `block_ip` duplicate and
        # the vestigial `block_producers_hash` were removed from the block body — selection is fully
        # address-based via select_producer_two_lane, so neither field affected consensus).
        "block_creator": creator,
        "block_timestamp": None,
        "block_transactions": transaction_pool,
        "child_hash": None,
        "block_reward": block_reward,
        # running fee total committed in the header so the elastic reward is verifiable from
        # headers alone (see get_block_reward); chain_id binds the block to this chain.
        "cumulative_fees": parent_cumulative_fees + block_fees,
        # FORK-CHOICE WEIGHT (#16/#17 step 2): running sum of each block's total_bonded_shares
        # (as-of-its-parent). Committed INSIDE the hash preimage like cumulative_fees, recomputed in
        # rebuild_block and verified as-of-parent in verify_block, so a relay cannot forge it. Carried
        # + verified here; the fork-choice switch to argmax(cumulative_weight) lands in step 3.
        "cumulative_weight": parent_cumulative_weight + block_weight,
        "chain_id": None,          # EXCLUDED from the hash (see docstring); stamped as the real value below
    }
    block_hash = blake2b_hash_link(link_from=parent_hash, link_to=block_message)
    block_message.update(block_hash=block_hash)
    block_message.update(block_timestamp=block_timestamp)
    block_message.update(chain_id=chain_id)      # informational field, not part of block_hash
    return block_message


# --- detached winner authorship signature (#15 step 5) -------------------------------------------
# The signature authenticates that the SELECTED winner endorsed this specific block. It is DETACHED
# and OPTIONAL: stored OUTSIDE the hash preimage (so it never enters block_hash / cumulative_weight /
# validity / reward), and absent on a relay-built block for an OFFLINE winner (win-offline preserved).
# Only the winner, holding its own key, can produce a valid one. Two valid signatures by the same
# winner over two different blocks at the same height+parent are a portable EQUIVOCATION proof (slash).

def _block_sig_message_fields(block_number, parent_hash, block_hash) -> bytes:
    """The exact bytes a winner signs to authenticate a block: blake2b(height, parent_hash, block_hash).
    No chain_id: the block_hash is already unique to THIS chain (it descends from a unique genesis via
    parent_hash), so it can't be replayed onto another chain — and leaving chain_id out keeps signature
    verification, like block hashing, invariant to a CHAIN_ID constant change. Field-based so an
    equivocation proof can reconstruct it without a full block dict."""
    return _unhex(blake2b_hash([block_number, parent_hash, block_hash]))


def block_signature_message(block) -> bytes:
    """Bytes the winner signs over its block; binds the block's identity so a signature cannot be
    replayed onto another block or chain. Hex/int only."""
    return _block_sig_message_fields(block["block_number"], block["parent_hash"], block["block_hash"])


def verify_equivocation_proof(proof) -> tuple:
    """Verify a block-authorship EQUIVOCATION proof: the SAME identity validly signed TWO DIFFERENT
    blocks at the SAME height+parent (#15 step 5C). proof = {block_number, parent_hash, public_key,
    block_hash_a, signature_a, block_hash_b, signature_b}. Returns (offender_address, block_number)
    when valid, else None. Pure verification (no state); integer/hex only.

    Why this is unforgeable: only the identity holding the key can produce EITHER valid signature, so
    a valid proof is irrefutable evidence that identity double-authored a slot — there is no honest
    reason to sign two conflicting blocks for one slot."""
    try:
        if not isinstance(proof, dict):
            return None
        ha, hb = proof.get("block_hash_a"), proof.get("block_hash_b")
        pk = proof.get("public_key")
        bn, parent = proof.get("block_number"), proof.get("parent_hash")
        if not (ha and hb and pk and parent) or not isinstance(bn, int) or isinstance(bn, bool):
            return None
        if ha == hb:
            return None  # not conflicting — same block
        for bh, sig in ((ha, proof.get("signature_a")), (hb, proof.get("signature_b"))):
            if not sig or not _verify_message(signed=sig, public_key=pk,
                                              message=_block_sig_message_fields(bn, parent, bh)):
                return None
        return make_address(pk), bn
    except Exception:
        return None


def sign_block(block, private_key, public_key):
    """Attach the detached winner signature. Added AFTER block_hash (outside the preimage), so it does
    NOT change the hash. Caller must only call this when it IS the winner (holds block_creator's key)."""
    block["block_signature"] = {
        "public_key": public_key,
        "signature": _sign_message(private_key, block_signature_message(block)),
    }
    return block


def verify_block_signature(block) -> bool:
    """Verify the detached winner signature IF present. Absent -> True (optional; offline winner or a
    deterministically-rebuilt block). Present -> the signer's pubkey MUST hash to block_creator (only
    the selected winner could sign) AND the ML-DSA signature must verify (signatures.verify()==True,
    never equality). A present-but-invalid signature is a forgery/tamper signal and is REJECTED."""
    sig = block.get("block_signature")
    if not sig:
        return True
    pubkey = sig.get("public_key")
    signature = sig.get("signature")
    if not pubkey or not signature:
        return False
    if not proof_sender(public_key=pubkey, sender=block["block_creator"]):
        return False  # signer is not the selected winner for this slot
    return _verify_message(signed=signature, public_key=pubkey, message=block_signature_message(block))


async def knows_block(target_peer, port, hash, logger):
    """ask a peer whether it can serve a block (GET /get_block?hash=). False on non-200 AND on any
    network error — an unreachable peer just counts as not knowing, never as an error the caller
    must handle."""
    try:
        url_construct = f"http://{hostport(target_peer, port)}/get_block?hash={hash}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                if response.status == 200:
                    return True
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to check block {hash} from {target_peer}: {e}")
        return False


async def get_blocks_after(target_peer, from_hash, logger, count=50, compress="zstd"):
    """Fetch up to `count` blocks AFTER from_hash from a peer (forward sync). The default zstd wire
    is decoded through the bomb-capped _unpack_wire, so an untrusted peer cannot balloon a tiny
    frame into gigabytes. Falsy on any failure (non-200, timeout, bad payload) — the caller moves
    on to another peer. connect stays tight (a dead peer fails in 5s) while total allows a full
    SYNC_BATCH_MAX batch to transfer on a slow link."""
    from ops.net_ops import read_capped   # local import: keep net_ops off block_ops' import-time graph
    try:
        url_construct = f"http://{hostport(target_peer, get_config()['port'])}/get_blocks_after?hash={from_hash}&count={count}&compress={compress}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60, connect=5)) as session:
            async with session.get(url_construct) as response:
                code = response.status

                if code == 200 and compress == "zstd":
                    return _unpack_wire(await read_capped(response, _SYNC_WIRE_CAP))
                elif code == 200:
                    return json.loads((await read_capped(response, _SYNC_WIRE_CAP)).decode())["blocks_after"]
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to get blocks after {from_hash} from {target_peer}: {e}")


async def get_blocks_before(target_peer, from_hash, logger, count=50, compress="zstd"):
    """mirror of get_blocks_after for backward sync: up to `count` blocks BEFORE from_hash (walking
    toward genesis), same bomb-capped zstd wire decode, same tight-connect/long-total timeout split,
    falsy on any failure."""
    from ops.net_ops import read_capped   # local import: keep net_ops off block_ops' import-time graph
    try:
        url_construct = f"http://{hostport(target_peer, get_config()['port'])}/get_blocks_before?hash={from_hash}&count={count}&compress={compress}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60, connect=5)) as session:
            async with session.get(url_construct) as response:
                code = response.status

                if code == 200 and compress == "zstd":
                    return _unpack_wire(await read_capped(response, _SYNC_WIRE_CAP))
                elif code == 200:
                    return json.loads((await read_capped(response, _SYNC_WIRE_CAP)).decode())["blocks_before"]
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to get blocks before {from_hash} from {target_peer}: {e}")
        return False


async def get_from_single_target(key, target_peer, logger) -> list:
    """obtain from a single target over the bomb-capped zstd(codec) wire, returns list ([] on failure).
    The old JSON path also had NO body cap — a malicious peer could stream unbounded bytes."""
    from ops.net_ops import read_capped, unpack_zstd_peer, MAX_PEER_BODY

    try:
        url_construct = f"http://{hostport(target_peer, get_config()['port'])}/{key}?compress=zstd"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                if response.status == 200:
                    fetched = unpack_zstd_peer(await read_capped(response, MAX_PEER_BODY))
                    return fetched if isinstance(fetched, list) else []
                else:
                    return []

    except Exception as e:
        logger.error(f"Failed to get {key} from {target_peer}: {e}")
        return []



