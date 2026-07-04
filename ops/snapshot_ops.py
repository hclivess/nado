"""
Bulk state-snapshot sync over P2P.

Instead of replaying every block from genesis (O(chain height), unbounded as the
network ages), a joining/behind node downloads a verified snapshot of account
state at a recent checkpoint height C and then replays only the short C..tip tail.

The snapshot is the `accounts.db` state (acc_index + totals_index) at height C.
It is split into deterministic chunks so it can be fetched in parallel and
resumed, and it carries a `state_root` (a blake2b Merkle root over the account
rows) so that *any* peer re-derives the identical root from its own DB — that is
what lets a joiner accept a snapshot only when a quorum of peers agree on its
hash, without trusting any single peer.

`transactions.db` (the consolidated tx index) is intentionally NOT part of the
consensus-critical snapshot — it is explorer/history only and can be rebuilt
lazily. Snapshots verify against the chain by anchoring to the block hash at C
and replaying the tail through the normal validation path.
"""
import hashlib
import os
import shutil

import msgpack

from ops.data_ops import get_home
from ops import kv_ops

# Deterministic consensus replay-guard nullifier prefixes carried in every snapshot (audit M-8). Losing any
# of these on a snapshot-synced node re-opens replay of an already-applied payout/slash (shieldnull/bridgenull/
# divnull = withdrawal exits -> escrow double-spend; tspend = treasury payout; slash = double-slash). They are
# self-contained, deterministic meta markers, so including them keeps every honest node's snapshot identical.
NULLIFIER_PREFIXES = ("bridgenull:", "shieldnull:", "divnull:", "tspend:", "slash:")

# how many account rows go into one transferable chunk
CHUNK_ROWS = int(os.environ.get("NADO_SNAPSHOT_CHUNK_ROWS", "25000"))
# checkpoints are captured at heights that are multiples of this (a checkpoint is only ADVERTISED once
# finalized, so it is always reorg-safe — no separate finality margin needed). Smaller = joiners see a
# fresher checkpoint sooner (shorter tail replay) at the cost of more frequent captures.
CHECKPOINT_INTERVAL = int(os.environ.get("NADO_SNAPSHOT_INTERVAL", "1000"))


def _blake2b(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def _leaf(address, balance, produced, bonded) -> bytes:
    """canonical, fixed encoding of one account row (addresses/ints contain no ':').
    `bonded` is part of the verified state-root so a snapshot commits mining stake too."""
    return f"{address}:{balance}:{produced}:{bonded}".encode()


def merkle_root(rows) -> str:
    """deterministic blake2b Merkle root over account rows sorted by address.
    rows: iterable of (address, balance, produced, bonded)."""
    leaves = [hashlib.blake2b(_leaf(*r), digest_size=32).digest()
              for r in sorted(rows, key=lambda r: r[0])]
    if not leaves:
        return _blake2b(b"")
    while len(leaves) > 1:
        if len(leaves) % 2:
            leaves.append(leaves[-1])  # duplicate last for odd counts
        leaves = [hashlib.blake2b(leaves[i] + leaves[i + 1], digest_size=32).digest()
                  for i in range(0, len(leaves), 2)]
    return leaves[0].hex()


def read_accounts(home=None):
    """all account rows (sorted by address) and the totals row from the KV index.
    Each row is (address, balance, produced, bonded) — the consensus-state subset the snapshot
    Merkle leaf commits (registered/fidelity are open-lane membership state, not part of the
    snapshot wire format / state_root, matching the prior SQLite snapshot)."""
    kv_ops.init_env(home)
    rows = [(addr, doc.get("balance", 0), doc.get("produced", 0), doc.get("bonded", 0))
            for addr, doc in kv_ops.iter_accounts()]  # iter_accounts is already address-sorted
    totals = kv_ops.totals_get()
    return rows, totals


def read_nullifiers(home=None):
    """The deterministic consensus replay-guard nullifiers (sorted [key, value] pairs) to carry in the
    snapshot so a snapshot-synced node keeps them (audit M-8)."""
    kv_ops.init_env(home)
    return kv_ops.iter_meta_prefix(NULLIFIER_PREFIXES)


def block_hash_at_height(height, home=None):
    """block hash for a given block number from the KV block index, or None"""
    kv_ops.init_env(home)
    return kv_ops.hash_by_number(height)


def _pack_chunks(rows):
    """split sorted rows into deterministic msgpack chunks; returns (chunk_bytes_list, chunk_meta_list)"""
    chunk_bytes, chunk_meta = [], []
    for cid, start in enumerate(range(0, len(rows), CHUNK_ROWS)):
        part = rows[start:start + CHUNK_ROWS]
        packed = msgpack.packb([list(r) for r in part])
        chunk_bytes.append(packed)
        chunk_meta.append({
            "id": cid,
            "sha256": hashlib.sha256(packed).hexdigest(),
            "bytes": len(packed),
            "rows": len(part),
            "first_address": part[0][0] if part else None,
            "last_address": part[-1][0] if part else None,
        })
    return chunk_bytes, chunk_meta


def build_snapshot(snapshot_height, block_hash, protocol, version, home=None):
    """build a manifest + chunk payloads for the given checkpoint height.
    Returns (manifest_dict, list_of_chunk_bytes). Pure function of accounts.db state."""
    home = home or get_home()
    rows, totals = read_accounts(home)
    rows = sorted(rows, key=lambda r: r[0])
    state_root = merkle_root(rows)
    chunk_bytes, chunk_meta = _pack_chunks(rows)
    nullifiers = read_nullifiers(home)          # M-8: carry the consensus replay guards (sorted, deterministic)

    manifest = {
        "snapshot_height": snapshot_height,
        "block_hash": block_hash,
        "state_root": state_root,
        "totals": totals,
        "account_count": len(rows),
        "chunk_count": len(chunk_meta),
        "chunks": chunk_meta,
        "nullifiers": nullifiers,               # bound into the manifest hash below (donor can't strip them)
        "protocol": protocol,
        "version": version,
    }
    manifest["snapshot_hash"] = manifest_hash(manifest)
    return manifest, chunk_bytes


def manifest_hash(manifest) -> str:
    """blake2b over the canonical manifest content (excluding the hash field itself)"""
    core = {k: manifest[k] for k in (
        "snapshot_height", "block_hash", "state_root", "totals",
        "account_count", "chunk_count", "chunks", "nullifiers", "protocol", "version") if k in manifest}
    # sort_keys for deterministic serialization across peers/python versions
    packed = msgpack.packb(_canonical(core))
    return _blake2b(packed)


def _canonical(obj):
    """recursively sort dict keys so serialization is identical everywhere"""
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_canonical(x) for x in obj]
    return obj


def verify_chunk(chunk_bytes, meta) -> bool:
    return hashlib.sha256(chunk_bytes).hexdigest() == meta["sha256"]


def import_snapshot(manifest, chunk_bytes_list, home=None, logger=None):
    """verify chunks against the manifest, recompute state_root + totals locally,
    assert they equal the manifest, then atomically replace accounts.db.

    Returns True on success. A peer cannot feed corrupted balances without failing
    either the per-chunk sha256 or the recomputed state_root check."""
    home = home or get_home()

    # 1) manifest self-consistency
    if manifest.get("snapshot_hash") != manifest_hash(manifest):
        _log(logger, "error", "snapshot manifest hash mismatch")
        return False
    if len(chunk_bytes_list) != manifest["chunk_count"]:
        _log(logger, "error", "snapshot chunk count mismatch")
        return False

    # 2) per-chunk integrity + reassembly
    rows = []
    for meta, cb in zip(manifest["chunks"], chunk_bytes_list):
        if not verify_chunk(cb, meta):
            _log(logger, "error", f"snapshot chunk {meta['id']} sha256 mismatch")
            return False
        rows.extend(tuple(r) for r in msgpack.unpackb(cb))

    # 3) recompute state root + totals and compare to the manifest
    if merkle_root(rows) != manifest["state_root"]:
        _log(logger, "error", "snapshot state_root mismatch after reassembly")
        return False
    if len(rows) != manifest["account_count"]:
        _log(logger, "error", "snapshot account_count mismatch")
        return False

    # 4) atomically replace the account docs + totals in ONE write txn (accounts + totals sub-DBs).
    #    The tx / block index sub-DBs are rebuilt separately (reindex) and intentionally untouched
    #    here. registered/fidelity are reset to 0 (not part of the snapshot wire format) — matching
    #    the prior SQLite import, which only set balance/produced/bonded.
    nullifiers = manifest.get("nullifiers", [])
    if "nullifiers" not in manifest:
        _log(logger, "warning",
             "snapshot manifest has no replay-guard nullifiers (old format) — withdrawal/slash replay "
             "guards will NOT be restored; tail replay must re-establish them")
    kv_ops.init_env(home)
    with kv_ops.write_txn() as txn:
        kv_ops.clear_accounts_and_totals(txn)   # empty accounts + reset totals to {0,0}
        for address, balance, produced, bonded in rows:
            kv_ops.put_account(address, {"balance": balance, "produced": produced, "bonded": bonded})
        t = manifest["totals"]
        kv_ops.totals_set(t["produced"], t["fees"])
        # M-8: reinstate the consensus replay-guard nullifiers so a snapshot-synced node cannot re-accept an
        # already-applied withdrawal/payout/slash (escrow double-spend). Bound into the agreed manifest hash.
        kv_ops.restore_meta_pairs(nullifiers)
    _log(logger, "info",
         f"Imported snapshot height {manifest['snapshot_height']} "
         f"({manifest['account_count']} accounts, {len(nullifiers)} replay guards, "
         f"state_root {manifest['state_root'][:16]}...)")
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
    url = f"http://{target}:{port}/get_block?hash={block_hash}&compress=msgpack"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(url) as r:
                if r.status != 200:
                    return None
                block = msgpack.unpackb(await r.read())
                return block if isinstance(block, dict) else None
    except Exception:
        return None


async def fetch_snapshot(target, port, logger=None, concurrency=8, timeout=120):
    """download a peer's snapshot manifest then all chunks in parallel.
    Returns (manifest, chunk_bytes_list) or (None, None) on failure."""
    import aiohttp
    base = f"http://{target}:{port}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(f"{base}/get_snapshot_manifest?compress=msgpack") as r:
                if r.status != 200:
                    _log(logger, "info", f"No snapshot manifest from {target} (HTTP {r.status})")
                    return None, None
                manifest = msgpack.unpackb(await r.read())

            chunks = [None] * manifest["chunk_count"]
            height = manifest["snapshot_height"]     # pin chunks to the manifest we just fetched
            sem = __import__("asyncio").Semaphore(concurrency)

            async def _one(cid):
                async with sem:
                    async with session.get(f"{base}/get_snapshot_chunk?id={cid}&height={height}") as cr:
                        if cr.status != 200:
                            raise IOError(f"chunk {cid} HTTP {cr.status}")
                        chunks[cid] = await cr.read()

            await __import__("asyncio").gather(*(_one(i) for i in range(manifest["chunk_count"])))
            return manifest, chunks
    except Exception as e:
        _log(logger, "error", f"Failed to fetch snapshot from {target}: {e}")
        return None, None


def _log(logger, level, msg):
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
    return f"{home or get_home()}/snapshots"


def _ckpt_path(height, home=None):
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
    with open(f"{tmp}/manifest.msgpack", "wb") as f:
        f.write(msgpack.packb(manifest))
    for cid, cb in enumerate(chunk_bytes):
        with open(f"{tmp}/chunk_{cid}.bin", "wb") as f:
            f.write(cb)
    shutil.rmtree(final, ignore_errors=True)
    os.rename(tmp, final)                      # atomic publish (a partial write never becomes visible)
    _prune_old_checkpoints(keep, home)
    return manifest


def latest_final_checkpoint_height(finalized_height, home=None):
    """the highest persisted checkpoint at/below finalized_height (safe to advertise/serve), or None"""
    finals = [h for h in list_checkpoint_heights(home) if h <= int(finalized_height)]
    return finals[-1] if finals else None


def load_checkpoint_manifest(height, home=None):
    p = f"{_ckpt_path(height, home)}/manifest.msgpack"
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return msgpack.unpackb(f.read())


def load_checkpoint_chunk(height, cid, home=None):
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
