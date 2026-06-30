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

import msgpack

from ops.data_ops import get_home
from ops import kv_ops

# how many account rows go into one transferable chunk
CHUNK_ROWS = int(os.environ.get("NADO_SNAPSHOT_CHUNK_ROWS", "25000"))
# finality margin: snapshot a height safely below any plausible re-org depth
FINALITY_MARGIN = int(os.environ.get("NADO_SNAPSHOT_FINALITY", "200"))
# checkpoints land on multiples of this
CHECKPOINT_INTERVAL = int(os.environ.get("NADO_SNAPSHOT_INTERVAL", "10000"))


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


def block_hash_at_height(height, home=None):
    """block hash for a given block number from the KV block index, or None"""
    kv_ops.init_env(home)
    return kv_ops.hash_by_number(height)


def choose_checkpoint_height(tip_height):
    """largest multiple of CHECKPOINT_INTERVAL that is <= tip - FINALITY_MARGIN"""
    safe = tip_height - FINALITY_MARGIN
    if safe < 0:
        return None
    return (safe // CHECKPOINT_INTERVAL) * CHECKPOINT_INTERVAL


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

    manifest = {
        "snapshot_height": snapshot_height,
        "block_hash": block_hash,
        "state_root": state_root,
        "totals": totals,
        "account_count": len(rows),
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
        "snapshot_height", "block_hash", "state_root", "totals",
        "account_count", "chunk_count", "chunks", "protocol", "version") if k in manifest}
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
    kv_ops.init_env(home)
    with kv_ops.write_txn() as txn:
        kv_ops.clear_accounts_and_totals(txn)   # empty accounts + reset totals to {0,0}
        for address, balance, produced, bonded in rows:
            kv_ops.put_account(address, {"balance": balance, "produced": produced, "bonded": bonded})
        t = manifest["totals"]
        kv_ops.totals_set(t["produced"], t["fees"])
    _log(logger, "info",
         f"Imported snapshot height {manifest['snapshot_height']} "
         f"({manifest['account_count']} accounts, state_root {manifest['state_root'][:16]}...)")
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
            sem = __import__("asyncio").Semaphore(concurrency)

            async def _one(cid):
                async with sem:
                    async with session.get(f"{base}/get_snapshot_chunk?id={cid}") as cr:
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
