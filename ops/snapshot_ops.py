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
import sqlite3

import msgpack

from ops.data_ops import get_home

# how many account rows go into one transferable chunk
CHUNK_ROWS = int(os.environ.get("NADO_SNAPSHOT_CHUNK_ROWS", "25000"))
# finality margin: snapshot a height safely below any plausible re-org depth
FINALITY_MARGIN = int(os.environ.get("NADO_SNAPSHOT_FINALITY", "200"))
# checkpoints land on multiples of this
CHECKPOINT_INTERVAL = int(os.environ.get("NADO_SNAPSHOT_INTERVAL", "10000"))


def _blake2b(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def _leaf(address, balance, produced, burned) -> bytes:
    """canonical, fixed encoding of one account row (addresses/ints contain no ':')"""
    return f"{address}:{balance}:{produced}:{burned}".encode()


def merkle_root(rows) -> str:
    """deterministic blake2b Merkle root over account rows sorted by address.
    rows: iterable of (address, balance, produced, burned)."""
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
    """all account rows (sorted by address) and the totals row from accounts.db"""
    home = home or get_home()
    con = sqlite3.connect(f"{home}/index/accounts.db")
    try:
        rows = con.execute(
            "SELECT address, balance, produced, burned FROM acc_index ORDER BY address").fetchall()
        totals_row = con.execute("SELECT produced, fees, burned FROM totals_index").fetchone()
    finally:
        con.close()
    totals = {"produced": totals_row[0], "fees": totals_row[1], "burned": totals_row[2]} if totals_row \
        else {"produced": 0, "fees": 0, "burned": 0}
    return rows, totals


def block_hash_at_height(height, home=None):
    """block hash for a given block number from blocks.db, or None"""
    home = home or get_home()
    con = sqlite3.connect(f"{home}/index/blocks.db")
    try:
        row = con.execute(
            "SELECT block_hash FROM block_index WHERE block_number = ?", (height,)).fetchone()
    finally:
        con.close()
    return row[0] if row else None


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

    # 4) atomically build a fresh accounts.db and swap it in
    tmp_path = f"{home}/index/accounts.snapshot.tmp"
    final_path = f"{home}/index/accounts.db"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    con = sqlite3.connect(tmp_path)
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("CREATE TABLE acc_index(address TEXT, balance INTEGER, produced INTEGER, burned INTEGER)")
        con.execute("CREATE INDEX seek_index ON acc_index(address)")
        con.execute("CREATE TABLE totals_index(produced INTEGER, fees INTEGER, burned INTEGER)")
        con.executemany("INSERT INTO acc_index VALUES (?,?,?,?)", rows)
        t = manifest["totals"]
        con.execute("INSERT INTO totals_index VALUES (?,?,?)", (t["produced"], t["fees"], t["burned"]))
        con.commit()
    finally:
        con.close()
    os.replace(tmp_path, final_path)
    _log(logger, "info",
         f"Imported snapshot height {manifest['snapshot_height']} "
         f"({manifest['account_count']} accounts, state_root {manifest['state_root'][:16]}...)")
    return True


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
