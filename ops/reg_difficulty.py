"""
Registration-rate PoSW difficulty (doc/ip-spoofing-and-sybil.md) — CONSENSUS-BOUND, v2 (chain-derived).

The required PoSW work for a `register` scales with recent registration volume, so a sudden flood of identities
gets progressively more expensive. This is enforced in validate_transaction: every node recomputes the required
difficulty and REJECTS a registration whose PoSW does not prove it. An attacker who edits their own node to
skip the client-side work simply produces proofs that every HONEST node rejects — the difficulty is not a
client courtesy, it is a validity rule.

WHY v2 (2026-07-17 alphanet-6 split postmortem): v1 computed the multiplier from the LIVE recert_by_epoch
LMDB index and its window INCLUDED the anchor's own, still-filling epoch. Both silently broke the determinism
a validity rule requires:
  1. The index is incrementally maintained (insert on apply, delete on rollback) and SURVIVES upgrades — fleet
     nodes that kept pre-reroll rows computed an inflated trailing baseline and accepted 2× proofs, while a
     clean node's honest count demanded 3×. The clean nodes rejected the canonical block #2944 wholesale and
     wedged in emergency mode for 10+ hours re-excluding every tip the fleet advertised.
  2. Because the anchor epoch was still filling, a register landing between prove-time and land-time could
     raise the requirement and invalidate an honest in-flight proof (posw.verify is EXACT-T: over- or
     under-working both fail), randomly rejecting honest registrants.

v2 therefore derives counts by COUNTING `register` txs in the BLOCKS of COMPLETE epochs that end strictly
BEFORE the anchor block. Blocks are the chain itself — there is no side index to desync, no partial epoch to
race: the requirement is a pure function of (max_block, chain), identical on every node at any time with any
DB history. Self-scaling is unchanged: recent rate vs. a longer trailing-average baseline (floored), capped.

GRANDFATHER: a register with max_block at/below the "reg_difficulty_v2" fork height (fork.py — the
finalized past plus a fleet-deploy window)
is accepted with a proof at ANY multiplier 1..POSW_DIFF_MAX_MULT. This is what lets an upgraded node validate
the existing chain (which contains v1-divergent proofs) and stay in consensus with not-yet-upgraded peers
until the boundary; after it, every node computes the identical strict v2 value.
"""
import fork
from protocol import (POSW_T, POSW_S, POSW_K, POSW_ANCHOR_OFFSET, POSW_DIFF_WINDOW, POSW_DIFF_TRAIL,
                      POSW_DIFF_FLOOR, POSW_DIFF_MAX_MULT, EPOCH_LENGTH)

# (epoch, epoch-final block hash) -> register-tx count. Keyed by the epoch's LAST block hash, which commits
# (via parent linkage) to every block in the epoch — so a reorged epoch gets a different key and re-counts,
# and a stale entry can never be served for the wrong fork. Process-local; a cold process re-counts each
# epoch once (~EPOCH_LENGTH block reads) and then serves sums from here.
_epoch_count_cache = {}


def chain_register_count(epoch: int) -> int:
    """Number of `register` txs the CURRENT chain landed in `epoch`'s blocks — counted from the blocks
    themselves (ground truth), never from the recert index. Returns 0 for epochs before genesis or not
    (fully) present locally; consensus callers only ever pass epochs complete before a finalized anchor,
    which every synced node holds."""
    from ops.block_ops import get_block, get_block_hash_by_number
    if epoch < 0:
        return 0
    end_hash = get_block_hash_by_number((epoch + 1) * EPOCH_LENGTH - 1)
    if end_hash is None:
        return 0
    key = (epoch, end_hash)
    hit = _epoch_count_cache.get(key)
    if hit is not None:
        return hit
    n = 0
    for height in range(epoch * EPOCH_LENGTH, (epoch + 1) * EPOCH_LENGTH):
        block_hash = get_block_hash_by_number(height)
        block = get_block(block_hash) if block_hash else None
        if block:
            n += sum(1 for t in block.get("block_transactions", []) if t.get("recipient") == "register")
    if len(_epoch_count_cache) > 4096:   # bound: ~4k epochs ≈ 2 weeks of keys; a reorg only adds a few
        _epoch_count_cache.clear()
    _epoch_count_cache[key] = n
    return n


def _window_count(lo_epoch: int, hi_epoch: int) -> int:
    """Sum of chain_register_count over epochs [lo_epoch, hi_epoch] inclusive (negatives skipped)."""
    if hi_epoch < lo_epoch:
        return 0
    return sum(chain_register_count(e) for e in range(max(0, lo_epoch), hi_epoch + 1))


def difficulty_multiplier(anchor_epoch: int) -> int:
    """Integer PoSW multiplier for a registration anchored in `anchor_epoch`. 1× under normal load; rises as
    the recent registration rate exceeds the trailing-average baseline, capped at POSW_DIFF_MAX_MULT.
    Windows END at anchor_epoch − 1: every counted epoch is COMPLETE before the anchor block exists, so the
    prover (who needs the anchor hash) and every validator (whose chain contains the anchor) read identical,
    settled chain data — the requirement can never change between prove-time and land-time."""
    last = anchor_epoch - 1
    if last < 0:
        return 1
    recent = _window_count(last - POSW_DIFF_WINDOW + 1, last)
    trail = _window_count(last - POSW_DIFF_TRAIL + 1, last)
    baseline = max(POSW_DIFF_FLOOR, trail * POSW_DIFF_WINDOW // POSW_DIFF_TRAIL)
    return min(POSW_DIFF_MAX_MULT, max(1, recent // baseline))


def required_posw_t(anchor_epoch: int) -> int:
    """The CONSENSUS number of sequential PoSW steps a registration anchored in `anchor_epoch` must prove =
    POSW_T × difficulty_multiplier. Recomputed by every node in validation and enforced against the proof."""
    return POSW_T * difficulty_multiplier(anchor_epoch)


def proof_multiplier(challenge: bytes, proof: dict) -> int:
    """The multiplier this proof actually satisfies (posw.verify is exact-T, so scan m = 1..MAX), or 0 if it
    verifies at none. Used by the grandfather acceptance below the "reg_difficulty_v2" fork and by the
    interim mint mirror. Each verify attempt is O(k·S) hashes and garbage fails on the first opening, so the
    worst-case scan stays cheap."""
    from ops import posw
    for m in range(1, POSW_DIFF_MAX_MULT + 1):
        if posw.verify(challenge, proof, POSW_T * m, POSW_S, POSW_K):
            return m
    return 0


def _observed_multiplier(tip_height: int, scan_limit: int = 2000):
    """Multiplier of the most recent `register` tx the chain ACCEPTED (walking back from the tip), or None
    if none found/decodable in range. This is the one network-agreed difficulty value observable from the
    outside while v1 peers are still live — their private requirement (computed from their own DB history)
    cannot be known any other way."""
    from ops.block_ops import get_block, get_block_hash_by_number
    from ops import posw
    for height in range(tip_height, max(-1, tip_height - scan_limit), -1):
        block_hash = get_block_hash_by_number(height)
        block = get_block(block_hash) if block_hash else None
        if not block:
            continue
        for t in block.get("block_transactions", []):
            if t.get("recipient") == "register" and t.get("posw"):
                anchor = get_block_hash_by_number(max(0, t["max_block"] - POSW_ANCHOR_OFFSET))
                if not anchor:
                    continue
                return proof_multiplier(posw.challenge_bytes(t["sender"], anchor), t["posw"]) or None
    return None


def mint_multiplier(tip_height: int, max_block: int) -> int:
    """The multiplier OUR OWN prover should work at for a registration targeting `max_block`.
    Past the strict boundary this is the deterministic v2 requirement. Inside the grandfather window the
    un-upgraded majority still enforces exact-T at a requirement derived from their private v1 index state,
    so the only proof guaranteed to land is one MIRRORING the multiplier of the last register the chain
    accepted (falling back to v2 when the chain holds none in range)."""
    from ops.mining_ops import epoch_of
    anchor_epoch = epoch_of(max(0, max_block - POSW_ANCHOR_OFFSET))
    if fork.active("reg_difficulty_v2", max_block):
        return difficulty_multiplier(anchor_epoch)
    return _observed_multiplier(tip_height) or difficulty_multiplier(anchor_epoch)
