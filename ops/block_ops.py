import json
import os
import time

import msgpack
import requests
import aiohttp
from .account_ops import get_bonded_registry, get_open_registry
from config import get_timestamp_seconds, get_config
from .data_ops import average, get_home, is_hex_hash
from hashing import blake2b_hash_link, blake2b_hash
from Curve25519 import sign as _sign_message, verify as _verify_message, unhex as _unhex
from .address_ops import proof_sender, make_address
from . import kv_ops
from .mining_ops import select_producer_two_lane, lane_of, epoch_of, compute_beacon, total_bonded_shares
from protocol import CHAIN_ID, REWARD_WINDOW, REWARD_CAP, BASE_SUBSIDY, GENESIS_BEACON, EPOCH_LENGTH
import zstandard as zstd

# Block bodies are stored as zstd(msgpack(block)) (#14): msgpack is a compact portable container,
# and zstd recovers the ~2x redundancy of hex signature/pubkey strings — important once post-quantum
# (ML-DSA) sigs bloat blocks. This is purely LOCAL/non-consensus (the block HASH is over
# canonical_bytes, never the stored file), so it can change with no fork. Genesis is also stored
# this way (genesis.make_genesis calls save_block).
_ZSTD_C = zstd.ZstdCompressor(level=3)
_ZSTD_D = zstd.ZstdDecompressor()


def _pack_block(block) -> bytes:
    return _ZSTD_C.compress(msgpack.packb(block))


def _unpack_block(raw: bytes):
    return msgpack.unpackb(_ZSTD_D.decompress(raw), raw=False)


# Bounded decompress for the zstd block-sync WIRE payload (get_blocks_after/before). max_output_size caps a
# decompression bomb from an untrusted peer (a tiny frame that expands to gigabytes); 100 blocks of real
# data is only a few MB, so 64 MiB is a generous ceiling.
_ZSTD_WIRE_MAX = 64 << 20


def _unpack_wire(body: bytes):
    return msgpack.unpackb(_ZSTD_D.decompress(body, max_output_size=_ZSTD_WIRE_MAX), raw=False)



def get_block_reward(parent_block):
    """Fee-weighted elastic block reward, computed as a PURE function of the block's own
    ancestry (NOT the verifier's tip), so a full node and a snapshot/pruned node agree on it
    and neither rejects the other's blocks. Every block header carries `cumulative_fees`, the
    running total of fees burned up to and including that block; the reward for the child of
    `parent_block` is the average fee per block over the last REWARD_WINDOW blocks:

        reward = (cumFee[parent] - cumFee[parent_height - REWARD_WINDOW]) // REWARD_WINDOW

    capped at REWARD_CAP. This is one indexed lookback (get_block_number) instead of the old
    REWARD_WINDOW-deep block-file walk on every call (audit: tip-anchored walk would fork
    snapshot nodes and was a hot-path perf regression; the old fee_over_blocks was also buggy)."""
    end_cumfee = parent_block.get("cumulative_fees", 0)
    lookback_height = parent_block["block_number"] - REWARD_WINDOW
    if lookback_height < 0:
        start_cumfee = 0
    else:
        start_block = get_block_number(lookback_height)
        start_cumfee = start_block.get("cumulative_fees", 0) if start_block else 0

    reward = (end_cumfee - start_cumfee) // REWARD_WINDOW
    # Floor at BASE_SUBSIDY (flat fair-launch emission): with no premine a brand-new chain has no
    # fees, so the elastic term is 0 — the subsidy lets a zero-coin OPEN-lane miner earn REAL coins
    # from block 1, which then circulate and pay fees. The fee-weighted term rises ON TOP up to cap.
    if reward < BASE_SUBSIDY:
        reward = BASE_SUBSIDY
    if reward > REWARD_CAP:
        reward = REWARD_CAP
    return reward


def valid_block_timestamp(new_block):
    new_timestamp = new_block["block_timestamp"]
    if new_timestamp > get_timestamp_seconds():
        return False
    else:
        return True


def check_target_match(transaction_list, block_number, logger):
    try:
        for transaction in transaction_list:
            if transaction["target_block"] != block_number:
                return False
        return True
    except Exception as e:
        logger.error(f"Error when checking transaction target block: {e}")
        return False


def match_transactions_target(transaction_list, block_number, logger):
    try:
        matched_txs = []

        for transaction in transaction_list:
            if transaction["target_block"] == block_number:
                matched_txs.append(transaction)

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
    winner = select_producer_two_lane(open_registry, bonded_registry, beacon, slot=block_number)
    if winner is None:
        logger.error("No eligible producer (open+bonded empty / bonded slot skipped); skipping block")
        return None
    logger.info(f"Block {block_number} producer [{lane_of(block_number, beacon)} lane]: {winner} "
                f"(open:{len(open_registry)} bonded:{len(bonded_registry)})")

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
        block_reward=get_block_reward(parent_block=latest_block),
        parent_cumulative_fees=latest_block.get("cumulative_fees", 0),
        parent_cumulative_weight=latest_block.get("cumulative_weight", 0),
        block_weight=total_bonded_shares(bonded_registry),  # as-of-parent (registry read above)
    )
    return block


def fee_over_blocks(logger, number_of_blocks=250):
    """returns average fee over last x blocks"""
    last_block = get_block_ends_info(logger=logger)["latest_block"]

    if last_block["block_number"] < number_of_blocks:
        number_of_blocks = last_block["block_number"]

    fees = []
    for number in range(0, number_of_blocks):
        for transaction in last_block["block_transactions"]:
            fees.append(transaction["fee"])
    if fees:
        return average(fees)
    else:
        return 0


def get_transaction_pool_demo():
    """use for demo only"""
    config = get_config()
    ip = config["ip"]
    port = config["port"]
    tx_pool_message = requests.get(f"http://{ip}:{port}/transaction_pool?compress=msgpack", timeout=5).text
    tx_pool_dict = msgpack.unpackb(tx_pool_message)
    return tx_pool_dict


def get_block(block):
    """return a block by its hash"""
    # SECURITY: `block` reaches here from the unauthenticated /get_block?hash= arg;
    # validate it is a real block hash so it can't traverse to arbitrary *.block paths
    # (also collapses the missing-vs-malformed responses into one 'not found').
    if not is_hex_hash(block):
        return False
    block_path = f"{get_home()}/blocks/{block}.block"
    if os.path.exists(block_path):
        with open(block_path, "rb") as file:
            block = _unpack_block(file.read())
        return block
    else:
        return False


def get_block_number(number):
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
    """ROLLING MODE (doc/rolling-mode-and-da.md): delete block BODY files (blocks/<hash>.block) for
    FINALIZED heights older than the retention window, while KEEPING the number<->hash index (so the
    beacon/FFG hash lookbacks via get_block_hash_by_number still resolve) and STATE (never touched).

    Correctness floor (from the audit): the deepest consensus read of a historical BODY is
    get_block_reward, which loads the block at tip-REWARD_WINDOW for its cumulative_fees; rollback
    re-reads bodies within FINALITY_DEPTH of the tip. So we NEVER prune within
    max(retention, REWARD_WINDOW+FINALITY_DEPTH+1) of the finalized height — even a misconfigured tiny
    `retention` cannot corrupt the reward calc or a legal rollback. Returns the number of files pruned.

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
    home = get_home()
    pruned = 0
    for h in range(start, end):
        bh = kv_ops.hash_by_number(h)                         # index is kept -> still resolvable after prune
        if not bh:
            continue
        path = f"{home}/blocks/{bh}.block"
        if os.path.exists(path):
            try:
                os.remove(path)
                pruned += 1
            except OSError as e:
                logger.warning(f"prune: could not remove {path}: {e}")
    kv_ops.meta_set_int("pruned_below", end)                  # advance past gap heights too (idempotent, monotonic)
    # Keep the earliest-block pointer at the earliest RETAINED body (height `end`, which is NOT pruned), so
    # get_block_ends_info never loads a pruned body (which returns False and 403s /status).
    neh = kv_ops.hash_by_number(end)
    if neh:
        try:
            _update_block_ends({"earliest_block": neh}, logger=logger)
        except Exception as e:
            logger.warning(f"prune: earliest-pointer update failed: {e}")
    if pruned:
        logger.info(f"Rolling mode: pruned {pruned} block bodies below height {end} "
                    f"(retention {eff_retention}, finalized {finalized_height}); indexes + state kept.")
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
    # in epoch E-2 and revealed in E-1's FINALIZED window (validation bounds the reveal's target_block
    # to <= E*EPOCH_LENGTH - FINALITY_DEPTH - 1), so they are immutable when this beacon is first needed
    # (block E*EPOCH_LENGTH) -> deterministic + grind-resistant. With zero reveals the beacon falls back
    # to the anchor-only value (liveness); compute_beacon re-sorts, so input order is irrelevant.
    secrets = kv_ops.reveals_for_epoch(epoch)
    return compute_beacon(GENESIS_BEACON, [anchor] + secrets)


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
    # SECURITY: reachable from the unauthenticated /get_blocks_after / /get_blocks_before
    # hash arg; validate so it can't read arbitrary *.block paths off disk.
    if not is_hex_hash(block_hash):
        return False
    try:
        with open(f"{get_home()}/blocks/{block_hash}.block", "rb") as infile:
            return _unpack_block(infile.read())
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
        "chain_id": block["chain_id"],
    }
    return blake2b_hash_link(link_from=block["parent_hash"], link_to=preimage)


def save_block(block: dict, logger):
    # SECURITY: a synced block's hash is peer-supplied; refuse to write outside blocks/
    if not is_hex_hash(block.get("block_hash")):
        logger.warning(f"Refusing to save block with invalid hash {block.get('block_hash')!r}")
        return False

    # HASH-CONSISTENCY INVARIANT (anti-fork, storage choke point): NEVER persist a block whose stored hash
    # does not match its own content. A half-completed reorg or a forged block could otherwise land on disk
    # and get chained onto, forking every honest node that later re-derives the true hash (the "stuck /
    # rolls back and forth" wedge). Genesis (block 0) is hashed differently (over timestamp+[] only), skip it.
    _hashed = ("block_number", "parent_hash", "block_creator", "block_transactions", "block_reward",
               "cumulative_fees", "cumulative_weight", "chain_id")
    if block.get("block_number", 0) != 0 and all(k in block for k in _hashed):
        expected = block_content_hash(block)
        if expected != block["block_hash"]:
            logger.error(f"Refusing to save hash-INCONSISTENT block #{block.get('block_number')}: its content "
                         f"hashes to {expected[:16]} but block_hash={str(block.get('block_hash'))[:16]} "
                         f"(forged or corrupt) — this would fork the chain")
            raise ValueError(f"hash-inconsistent block #{block.get('block_number')} refused")
    path = f"{get_home()}/blocks/{block['block_hash']}.block"
    tmp_path = f"{path}.tmp"

    # pack once, write to a temp file, fsync, then atomically rename into place. os.replace
    # is atomic so a reader never sees a half-written block. Bounded retries: the old
    # `while True` spun forever on a persistent error (full disk / permissions), silently
    # wedging the caller; after the cap we raise so the node fails loudly and can restart.
    last_error = None
    for _ in range(60):
        try:
            packed = _pack_block(block)
            with open(tmp_path, "wb") as outfile:
                outfile.write(packed)
                outfile.flush()
                os.fsync(outfile.fileno())
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            last_error = e
            logger.warning(f"Failed to save block {block['block_hash']} due to {e}")
            time.sleep(0.5)
    raise RuntimeError(f"Could not save block {block['block_hash']} after retries: {last_error}")


def get_block_ends_info(logger):
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
    # Delete both directions of the number<->hash mapping. Called inside the rollback write txn
    # (kv_ops uses the active txn), so an error propagates and aborts the WHOLE rollback rather than
    # leaving it half-reverted — no infinite retry loop is needed or correct under LMDB.
    kv_ops.block_index_del(block_number=block['block_number'], block_hash=block['block_hash'])

    block_data = f"{get_home()}/blocks/{block['block_hash']}.block"
    # bounded + backed off: the old inner loop had no sleep and never gave up,
    # so a permission error / open handle spun a CPU at 100% forever.
    for _ in range(10):
        if not os.path.exists(block_data):
            break
        try:
            os.remove(block_data)
            break
        except FileNotFoundError:
            break
        except Exception as e:
            logger.error(f"Failed to remove {block_data}: {e}")
            time.sleep(1)


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
    _update_block_ends({"earliest_block": earliest_block["block_hash"]}, logger=logger)
    return earliest_block


def set_latest_block_info(latest_block: dict, logger):
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
):
    """timestamp is approximate so hash matches across the network"""

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
        "chain_id": CHAIN_ID,
    }
    block_hash = blake2b_hash_link(link_from=parent_hash, link_to=block_message)
    block_message.update(block_hash=block_hash)
    block_message.update(block_timestamp=block_timestamp)
    return block_message


# --- detached winner authorship signature (#15 step 5) -------------------------------------------
# The signature authenticates that the SELECTED winner endorsed this specific block. It is DETACHED
# and OPTIONAL: stored OUTSIDE the hash preimage (so it never enters block_hash / cumulative_weight /
# validity / reward), and absent on a relay-built block for an OFFLINE winner (win-offline preserved).
# Only the winner, holding its own key, can produce a valid one. Two valid signatures by the same
# winner over two different blocks at the same height+parent are a portable EQUIVOCATION proof (slash).

def _block_sig_message_fields(block_number, parent_hash, block_hash) -> bytes:
    """The exact bytes a winner signs to authenticate a block: blake2b(chain_id, height, parent_hash,
    block_hash). Field-based so an equivocation proof can reconstruct it without a full block dict."""
    return _unhex(blake2b_hash([CHAIN_ID, block_number, parent_hash, block_hash]))


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
    the selected winner could sign) AND the ML-DSA signature must verify (Curve25519.verify()==True,
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
    try:
        url_construct = f"http://{target_peer}:{port}/get_block?hash={hash}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                if response.status == 200:
                    return True
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to check block {hash} from {target_peer}: {e}")
        return False


def update_child_in_latest_block(child_hash, logger, parent):
    """the only method to save block except for creation to avoid read/write collision"""
    # save_block is now bounded + atomic and raises on persistent failure; the old
    # `while True` here had NO sleep, so any persistent error pinned a CPU at 100% forever.
    parent["child_hash"] = child_hash
    return save_block(parent, logger=logger)


async def get_blocks_after(target_peer, from_hash, logger, count=50, compress="zstd"):
    try:
        url_construct = f"http://{target_peer}:{get_config()['port']}/get_blocks_after?hash={from_hash}&count={count}&compress={compress}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                code = response.status

                if code == 200 and compress == "zstd":
                    return _unpack_wire(await response.read())
                elif code == 200 and compress == "msgpack":
                    read = response.read()
                    return msgpack.unpackb(await read)
                elif code == 200:
                    text = response.text()
                    return json.loads(await text)["blocks_after"]
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to get blocks after {from_hash} from {target_peer}: {e}")


async def get_blocks_before(target_peer, from_hash, logger, count=50, compress="zstd"):
    try:
        url_construct = f"http://{target_peer}:{get_config()['port']}/get_blocks_before?hash={from_hash}&count={count}&compress={compress}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                code = response.status

                if code == 200 and compress == "zstd":
                    return _unpack_wire(await response.read())
                elif code == 200 and compress == "msgpack":
                    read = response.read()
                    return msgpack.unpackb(await read)
                elif code == 200:
                    text = response.text()
                    return json.loads(await text)["blocks_before"]
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to get blocks before {from_hash} from {target_peer}: {e}")
        return False


async def get_from_single_target(key, target_peer, logger) -> list:  # todo add msgpack support
    """obtain from a single target, returns list"""

    try:
        url_construct = f"http://{target_peer}:{get_config()['port']}/{key}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                text = response.text()
                code = response.status

                if code == 200:
                    return json.loads(await text)[key]
                else:
                    return []

    except Exception as e:
        logger.error(f"Failed to get {key} from {target_peer}: {e}")
        return []



