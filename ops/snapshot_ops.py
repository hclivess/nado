"""
Bulk state-snapshot sync over P2P.

Instead of replaying every block from genesis (O(chain height), unbounded as the
network ages), a joining/behind node downloads a verified snapshot of account
state at a recent checkpoint height C and then replays only the short C..tip tail.

The snapshot is the FULL consensus state at height C — every kv_ops.SNAPSHOT_DBS sub-DB
(account docs incl. registered/fidelity, totals, meta replay-guards + finalized floor,
recerts/recert_by_epoch, bond_since, commits/reveals, attestations, unbonds, aliases,
htlcs, settlements, treasury). Carrying the WHOLE state (not just balances) is what lets
a snapshot-synced node derive the SAME producer set and validate the C+1..tip tail. It is
split into deterministic chunks so it can be fetched in parallel, and carries a `state_root`
(a blake2b Merkle root over the (db,key,value) entries) so *any* peer re-derives the
identical root from its own DB — which is what lets a joiner accept a snapshot only when a
quorum agrees on its hash (or, for a lone donor, only a trusted operator seed).

The block + tx HISTORY indexes are intentionally NOT part of the snapshot — they are
explorer/history only and are rebuilt by replaying the tail. Snapshots verify against the
chain by anchoring to the block hash at C and replaying the tail through normal validation.
"""
import hashlib
import os
import shutil

from ops import codec

from ops.data_ops import get_home
from ops import kv_ops

# how many state entries (db, key, value triples) go into one transferable chunk
CHUNK_ROWS = int(os.environ.get("NADO_SNAPSHOT_CHUNK_ROWS", "25000"))
# checkpoints are captured at heights that are multiples of this (a checkpoint is only ADVERTISED once
# finalized, so it is always reorg-safe — no separate finality margin needed). Smaller = joiners see a
# fresher checkpoint sooner (shorter tail replay) at the cost of more frequent captures.
CHECKPOINT_INTERVAL = int(os.environ.get("NADO_SNAPSHOT_INTERVAL", "1000"))


def _blake2b(data: bytes) -> str:
    """32-byte blake2b hex digest — the ONE hash used for state roots and manifest hashes, so every node
    derives identical commitments"""
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def _leaf(triple) -> bytes:
    """canonical, length-framed encoding of one state entry (db_name:str, key:bytes, value:bytes) so no
    db/key/value byte pattern can collide with another entry's field boundary."""
    name, key, value = triple
    return codec.pack([name, key, value])


def merkle_root(triples) -> str:
    """deterministic blake2b Merkle root over the FULL consensus state. `triples` MUST already be in
    canonical sorted order (caller sorts). Every honest node re-derives the identical root from its own DB."""
    leaves = [hashlib.blake2b(_leaf(t), digest_size=32).digest() for t in triples]
    if not leaves:
        return _blake2b(b"")
    while len(leaves) > 1:
        if len(leaves) % 2:
            leaves.append(leaves[-1])  # duplicate last for odd counts
        leaves = [hashlib.blake2b(leaves[i] + leaves[i + 1], digest_size=32).digest()
                  for i in range(0, len(leaves), 2)]
    return leaves[0].hex()


def read_state(home=None):
    """The FULL consensus state as a canonical sorted list of (db_name, key_bytes, value_bytes) triples —
    every kv_ops.SNAPSHOT_DBS sub-DB: account docs (incl. registered/fidelity), totals, the deterministic
    meta replay-guards + finalized floor, recerts/recert_by_epoch (open-lane lease), bond_since (bonded
    ramp), commits/reveals (RANDAO beacon), attestations (FFG), unbonds, aliases, htlcs, settlements,
    treasury. This is exactly what a snapshot-synced node needs to derive the SAME producer set and validate
    the C+1..tip tail. Block + tx HISTORY indexes are excluded (the tail replay rebuilds them)."""
    kv_ops.init_env(home)
    triples = []
    for name in kv_ops.SNAPSHOT_DBS:
        for k, v in kv_ops.iter_db_pairs(name):
            triples.append((name, k, v))
    triples.sort(key=lambda t: (t[0], t[1], t[2]))
    return triples


def _pack_chunks(triples):
    """split sorted state triples into deterministic msgpack chunks; returns (chunk_bytes_list, chunk_meta_list)"""
    chunk_bytes, chunk_meta = [], []
    for cid, start in enumerate(range(0, len(triples), CHUNK_ROWS)):
        part = triples[start:start + CHUNK_ROWS]
        packed = codec.pack([[n, k, v] for (n, k, v) in part])
        chunk_bytes.append(packed)
        chunk_meta.append({
            "id": cid,
            "sha256": hashlib.sha256(packed).hexdigest(),
            "bytes": len(packed),
            "rows": len(part),
        })
    return chunk_bytes, chunk_meta


def build_snapshot(snapshot_height, block_hash, protocol, version, home=None):
    """build a manifest + chunk payloads committing the FULL consensus state at the given checkpoint height.
    Returns (manifest_dict, list_of_chunk_bytes). Pure function of the state DB."""
    home = home or get_home()
    triples = read_state(home)
    state_root = merkle_root(triples)
    chunk_bytes, chunk_meta = _pack_chunks(triples)

    manifest = {
        "snapshot_height": snapshot_height,
        "block_hash": block_hash,
        "state_root": state_root,
        "entry_count": len(triples),
        "chunk_count": len(chunk_meta),
        "chunks": chunk_meta,
        "protocol": protocol,
        "version": version,
    }
    manifest["snapshot_hash"] = manifest_hash(manifest)
    return manifest, chunk_bytes


def manifest_hash(manifest) -> str:
    """blake2b over the canonical manifest content (excluding the hash field itself)"""
    core = {k: manifest[k] for k in (
        "snapshot_height", "block_hash", "state_root", "entry_count",
        "chunk_count", "chunks", "protocol", "version") if k in manifest}
    # sort_keys for deterministic serialization across peers/python versions
    packed = codec.pack(_canonical(core))
    return _blake2b(packed)


def _canonical(obj):
    """recursively sort dict keys so serialization is identical everywhere"""
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_canonical(x) for x in obj]
    return obj


def verify_chunk(chunk_bytes, meta) -> bool:
    """per-chunk integrity gate: downloaded bytes are UNTRUSTED until they match the sha256 pinned in the
    (hash-verified) manifest — a donor can't substitute chunk content without failing here"""
    return hashlib.sha256(chunk_bytes).hexdigest() == meta["sha256"]


def import_snapshot(manifest, chunk_bytes_list, home=None, logger=None):
    """Verify the chunks against the manifest, recompute the state_root locally, assert it equals the
    manifest, then atomically replace the ENTIRE consensus state (kv_ops.SNAPSHOT_DBS). Block + tx history
    indexes are left untouched — the caller replays the C+1..tip tail, which rebuilds them.

    Returns True on success. A donor cannot feed corrupted state without failing either a per-chunk sha256
    or the recomputed state_root, and it can only write into the allowed SNAPSHOT_DBS sub-DBs."""
    home = home or get_home()

    # 1) manifest self-consistency
    if manifest.get("snapshot_hash") != manifest_hash(manifest):
        _log(logger, "error", "snapshot manifest hash mismatch")
        return False
    if len(chunk_bytes_list) != manifest["chunk_count"]:
        _log(logger, "error", "snapshot chunk count mismatch")
        return False

    # 2) per-chunk integrity + reassembly into (db, key, value) triples, restricted to allowed sub-DBs
    allowed = set(kv_ops.SNAPSHOT_DBS)
    triples = []
    for meta, cb in zip(manifest["chunks"], chunk_bytes_list):
        if not verify_chunk(cb, meta):
            _log(logger, "error", f"snapshot chunk {meta['id']} sha256 mismatch")
            return False
        for row in codec.unpack(cb):
            if (not isinstance(row, (list, tuple)) or len(row) != 3 or row[0] not in allowed
                    or not isinstance(row[1], (bytes, bytearray))
                    or not isinstance(row[2], (bytes, bytearray))):
                _log(logger, "error", "snapshot chunk holds a malformed / out-of-scope state entry")
                return False
            triples.append((row[0], bytes(row[1]), bytes(row[2])))

    # 3) recompute the state root over the canonical order and compare
    triples.sort(key=lambda t: (t[0], t[1], t[2]))
    if len(triples) != manifest["entry_count"]:
        _log(logger, "error", "snapshot entry_count mismatch")
        return False
    if merkle_root(triples) != manifest["state_root"]:
        _log(logger, "error", "snapshot state_root mismatch after reassembly")
        return False

    # 4) atomically replace the WHOLE consensus state (all SNAPSHOT_DBS) in ONE write txn
    kv_ops.init_env(home)
    with kv_ops.write_txn() as txn:
        kv_ops.restore_snapshot_state(triples, txn)
    _log(logger, "info",
         f"Imported snapshot height {manifest['snapshot_height']} "
         f"({manifest['entry_count']} state entries, state_root {manifest['state_root'][:16]}...)")
    return True


def agree_snapshot(statuses, min_peers=2, threshold=0.8):
    """Decide whether a super-majority of peers agree on one snapshot.

    statuses: list of peer /status dicts (None for unreachable peers).
    Returns {snapshot_height, snapshot_hash, votes, responders} for the agreed
    snapshot, or None. This is the Sybil-resistance gate: a joining node only
    accepts a (height, hash) that >= `threshold` of responding peers advertise,
    so a single malicious peer can't feed it a forged state. Pure function."""
    votes = {}
    responders = 0
    for s in statuses:
        if not s:
            continue
        responders += 1
        h = s.get("snapshot_hash")
        height = s.get("snapshot_height")
        if h and height is not None:
            votes[(height, h)] = votes.get((height, h), 0) + 1
    if responders < min_peers or not votes:
        return None
    (best_height, best_hash), count = max(votes.items(), key=lambda kv: kv[1])
    if count / responders >= threshold:
        return {"snapshot_height": best_height, "snapshot_hash": best_hash,
                "votes": count, "responders": responders}
    return None


async def fetch_block(target, port, block_hash, timeout=15):
    """fetch a single block dict from a peer by hash, or None"""
    import aiohttp
    from ops.net_ops import read_capped, unpack_zstd_peer, MAX_PEER_BODY
    from config import hostport
    url = f"http://{hostport(target, port)}/get_block?hash={block_hash}&compress=zstd"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(url) as r:
                if r.status != 200:
                    return None
                block = unpack_zstd_peer(await read_capped(r, MAX_PEER_BODY))   # bomb-capped zstd wire
                return block if isinstance(block, dict) else None
    except Exception:
        return None


async def fetch_snapshot(target, port, logger=None, concurrency=8, timeout=120):
    """download a peer's snapshot manifest then all chunks in parallel.
    Returns (manifest, chunk_bytes_list) or (None, None) on failure."""
    import aiohttp
    from ops.net_ops import read_capped, unpack_zstd_peer, MAX_PEER_BODY, MAX_SNAPSHOT_TOTAL, MAX_SNAPSHOT_ACCOUNTS
    from config import hostport
    base = f"http://{hostport(target, port)}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(f"{base}/get_snapshot_manifest?compress=zstd") as r:
                if r.status != 200:
                    _log(logger, "info", f"No snapshot manifest from {target} (HTTP {r.status})")
                    return None, None
                manifest = unpack_zstd_peer(await read_capped(r, MAX_PEER_BODY))

            # VALIDATE the manifest BEFORE allocating anything sized by its (untrusted) fields. A lone donor
            # under weak-subjectivity could otherwise advertise a huge chunk_count/entry_count and OOM us
            # before the per-chunk sha256 / state_root checks (which only run later, in import_snapshot) fire.
            # The manifest body is already byte-capped above; verify its self-hash so the chunk meta (bytes,
            # rows) is trustworthy, then bound the totals we are about to allocate/download.
            if not isinstance(manifest, dict) or manifest.get("snapshot_hash") != manifest_hash(manifest):
                _log(logger, "warning", f"Snapshot manifest from {target} failed self-hash — rejecting")
                return None, None
            chunk_meta = manifest.get("chunks")
            # entry_count = number of (db, key, value) state triples; each chunk's "rows" must sum to it.
            # (The full-consensus-state snapshot supersedes the old accounts-only "account_count" field.)
            cc, ec = manifest.get("chunk_count"), manifest.get("entry_count")
            if not (isinstance(chunk_meta, list) and isinstance(cc, int) and cc == len(chunk_meta)
                    and isinstance(ec, int) and 0 <= ec <= MAX_SNAPSHOT_ACCOUNTS
                    and sum(int(m.get("rows", 0)) for m in chunk_meta) == ec):
                _log(logger, "warning", f"Snapshot manifest from {target} has inconsistent counts — rejecting")
                return None, None
            total = sum(int(m.get("bytes", 0)) for m in chunk_meta)
            if not (0 <= total <= MAX_SNAPSHOT_TOTAL):
                _log(logger, "warning", f"Snapshot from {target} exceeds size ceiling ({total} bytes) — rejecting")
                return None, None

            chunks = [None] * cc
            height = manifest["snapshot_height"]     # pin chunks to the manifest we just fetched
            sem = __import__("asyncio").Semaphore(concurrency)

            async def _one(cid):
                """fetch chunk `cid` under the concurrency semaphore, read-capped to chunk_meta[cid]['bytes']
                (trusted because the manifest passed its self-hash) — the donor can't over-feed us"""
                async with sem:
                    async with session.get(f"{base}/get_snapshot_chunk?id={cid}&height={height}") as cr:
                        if cr.status != 200:
                            raise IOError(f"chunk {cid} HTTP {cr.status}")
                        # manifest is hash-verified, so chunk_meta[cid]['bytes'] is a trusted cap for this read
                        chunks[cid] = await read_capped(cr, int(chunk_meta[cid].get("bytes", 0)))

            await __import__("asyncio").gather(*(_one(i) for i in range(cc)))
            return manifest, chunks
    except Exception as e:
        _log(logger, "error", f"Failed to fetch snapshot from {target}: {e}")
        return None, None


def _log(logger, level, msg):
    """log at `level` if a logger was passed (falling back to .info for unknown levels); silent no-op
    without one, so library callers and tests need not wire up logging"""
    if logger:
        getattr(logger, level, logger.info)(msg)


# --------------------------------------------------------------------------------------------------
# PERSISTENT STATE CHECKPOINTS (rolling-node sync).
#
# A node captures a snapshot of its account state at each checkpoint height C at the MOMENT it
# incorporates block C — so accounts.db == state@C by construction (no historical-state derivation,
# nothing to get wrong). The snapshot (manifest + chunks) is written under snapshots/<C>/ and is
# advertised in /status ONLY once C is finalized (reorg-safe), so a joiner can bulk-import verified
# state@C and then replay only the short C+1..tip tail. Every honest node produces the identical
# deterministic checkpoint, which is what lets a joiner accept one on a super-majority quorum.
# --------------------------------------------------------------------------------------------------

def _snap_dir(home=None):
    """root of the persisted checkpoints (snapshots/<height>/ per checkpoint)"""
    return f"{home or get_home()}/snapshots"


def _ckpt_path(height, home=None):
    """directory of the checkpoint at `height`; int() sanitizes a peer-supplied height (no path traversal)"""
    return f"{_snap_dir(home)}/{int(height)}"


def list_checkpoint_heights(home=None):
    """persisted checkpoint heights on disk, ascending (ignores in-progress .tmp dirs)"""
    d = _snap_dir(home)
    if not os.path.isdir(d):
        return []
    heights = []
    for name in os.listdir(d):
        if name.endswith(".tmp"):
            continue
        try:
            heights.append(int(name))
        except ValueError:
            pass
    return sorted(heights)


def _prune_old_checkpoints(keep, home=None):
    """drop all but the newest `keep` checkpoints — every node deterministically re-captures the same
    ones, so old checkpoints are pure disk weight, not history worth keeping. keep<=0 disables pruning."""
    if keep <= 0:
        return
    for h in list_checkpoint_heights(home)[:-keep]:
        shutil.rmtree(_ckpt_path(h, home), ignore_errors=True)


def persist_checkpoint(height, block_hash, protocol, version, home=None, keep=2):
    """Build a snapshot of the CURRENT account state (== state@height when called at the incorporation
    of block `height`) and atomically persist manifest + chunks under snapshots/<height>/. Keeps the
    newest `keep` checkpoints. Returns the manifest. Correct by construction — never derives past state."""
    home = home or get_home()
    manifest, chunk_bytes = build_snapshot(height, block_hash, protocol, version, home=home)
    final = _ckpt_path(height, home)
    tmp = final + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    with open(f"{tmp}/manifest.json", "wb") as f:
        f.write(codec.pack(manifest))
    for cid, cb in enumerate(chunk_bytes):
        with open(f"{tmp}/chunk_{cid}.bin", "wb") as f:
            f.write(cb)
    shutil.rmtree(final, ignore_errors=True)
    os.rename(tmp, final)                      # atomic publish (a partial write never becomes visible)
    _prune_old_checkpoints(keep, home)
    return manifest


def _checkpoint_is_canonical(height, home=None):
    """True iff the persisted checkpoint at `height` anchors to the block the CURRENT canonical chain
    has at that height. A checkpoint captured on a since-abandoned fork (the node later re-anchored
    away) stays on disk but must never be advertised or served: a fresh node bootstrapping onto it
    lands on a chain no donor can extend — wedged at birth (observed live: a donor advertised its
    dead fork's checkpoint 13000 while its canonical chain stood at 49k)."""
    manifest = load_checkpoint_manifest(height, home)
    if not isinstance(manifest, dict):
        return False
    return kv_ops.hash_by_number(height) == manifest.get("block_hash")


def latest_final_checkpoint_height(finalized_height, home=None):
    """the highest persisted checkpoint at/below finalized_height that anchors to the CURRENT
    canonical chain (safe to advertise/serve), or None. Fork-stale checkpoints are skipped."""
    finals = [h for h in list_checkpoint_heights(home) if h <= int(finalized_height)]
    for h in reversed(finals):
        if _checkpoint_is_canonical(h, home):
            return h
    return None


def drop_all_checkpoints(home=None):
    """delete every persisted checkpoint, returning how many were dropped. Used after a re-anchor:
    checkpoints captured on the abandoned identity are fork-stale — never advertised again thanks to
    the canonical filter, but pure disk weight at best and operator confusion at worst."""
    heights = list_checkpoint_heights(home)
    for h in heights:
        shutil.rmtree(_ckpt_path(h, home), ignore_errors=True)
    return len(heights)


def load_checkpoint_manifest(height, home=None):
    """the persisted manifest of checkpoint `height` (served over /get_snapshot_manifest and advertised in
    /status), or None if absent. Fetchers re-verify its self-hash, so no trust rides on this read."""
    p = f"{_ckpt_path(height, home)}/manifest.json"
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return codec.unpack(f.read())


def load_checkpoint_chunk(height, cid, home=None):
    """raw bytes of one persisted chunk (served verbatim to joiners over /get_snapshot_chunk), or None if
    missing. int() on the peer-supplied cid (like height in _ckpt_path) forecloses path traversal."""
    p = f"{_ckpt_path(height, home)}/chunk_{int(cid)}.bin"
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def drop_checkpoints_above(height, home=None):
    """On rollback: discard checkpoints whose height exceeds the new tip — they may reflect a state
    that is being reverted. (Advertised checkpoints are always finalized, so this only ever removes
    not-yet-final ones, keeping the on-disk set consistent with the chain.)"""
    for h in list_checkpoint_heights(home):
        if h > int(height):
            shutil.rmtree(_ckpt_path(h, home), ignore_errors=True)
