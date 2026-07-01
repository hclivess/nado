"""
Schemaless key-value index for NADO (LMDB / MDBX data model), replacing the SQLite index.

Per doc/storage-kv-migration.md: ONE memory-mapped, ACID, single-writer LMDB env with named
sub-DBs. Account/state records are *schemaless msgpack documents* (no columns, no DDL) so adding
a field needs no migration. This module encapsulates ALL key-encoding (8-byte big-endian ints) and
value (de)serialization (msgpack) so call-sites never touch raw bytes.

ATOMICITY: a whole block mutation (account docs + tx index + block index + totals + heartbeats)
commits in ONE env.begin(write=True) via the write_txn() context manager -> crash-atomic, directly
replacing the SQLite transaction() context (closes the LO-1/CO-4 window). LMDB is single-writer +
copy-on-write, so a crash mid-block leaves the block UNapplied, never half-applied.

DETERMINISM: LMDB stores keys (and DUPSORT dups) in sorted byte order, so range scans
(block_by_num iteration, heartbeats "epoch > E-PRESENCE_WINDOW", tx_by_* ordered-by-block history)
are deterministic and identical across nodes — required because get_open_registry and tx history
feed consensus selection.

The KV store is a DERIVED, rebuildable index. Block bodies stay zstd(msgpack) files under blocks/
and consensus hashing stays canonical_bytes — neither is touched here.
"""
import os
import struct
import threading

import lmdb
import msgpack

from .data_ops import get_home

# --- env / schema configuration ------------------------------------------------------------------

# 16 GiB virtual address reservation (spec). LMDB has a fixed map_size (its only wart); set it large
# and bump if a MDB_MAP_FULL ever surfaces. With writemap=False a full map raises lmdb.MapFullError
# on put/commit (the write txn aborts cleanly) — it surfaces as an error and NEVER corrupts.
MAP_SIZE = 16 * 1024 * 1024 * 1024

# named sub-DBs and their flags, EXACTLY per the spec table.
#   accounts          address(utf8)            -> msgpack({balance,produced,bonded,registered,fidelity,...})
#   totals            b"totals"                -> msgpack({produced,fees})
#   block_by_num      block_number(8B BE)      -> block_hash(utf8)
#   block_by_hash     block_hash(utf8)         -> block_number(8B BE)
#   tx                txid(utf8)               -> msgpack({block_number,sender,recipient})
#   tx_by_sender      sender(utf8)             -> block_number(8B BE)||txid(utf8)   [DUPSORT]
#   tx_by_recipient   recipient(utf8)          -> block_number(8B BE)||txid(utf8)   [DUPSORT]
#   heartbeats        epoch(8B BE)             -> address(utf8)                     [DUPSORT]
#   meta              key(utf8)                -> msgpack(int)   (e.g. finalized_height)
#   attestations      target_epoch(8B BE)      -> "validator|target_hash"            [DUPSORT]  (FFG #6)
#   commits           "sender|target_epoch"    -> commitment                                   (RANDAO #7)
#   reveals           target_epoch(8B BE)      -> secret                            [DUPSORT]  (RANDAO #7)
#   unbonds           address                  -> msgpack({amount, release_block})         (unbond delay)
_PLAIN_DBS = ("accounts", "totals", "block_by_num", "block_by_hash", "tx", "meta", "commits", "unbonds", "hb_revert")
_DUP_DBS = ("tx_by_sender", "tx_by_recipient", "heartbeats", "attestations", "reveals")

# account doc fields that default to 0 when missing on read (schemaless: extra fields pass through).
ACCOUNT_FIELDS = ("balance", "produced", "bonded", "registered", "fidelity", "last_hb_epoch")

_TOTALS_KEY = b"totals"

# one env per env-path (a node has exactly one; tests may use several HOMEs). Guarded so the first
# touch from any of the many Tornado reader threads opens it exactly once. Sub-DB handles are kept
# in a parallel dict (the lmdb Environment is a C type that rejects arbitrary attributes).
_envs = {}
_dbhandles = {}
_envs_lock = threading.Lock()

# per-thread active write transaction (set by write_txn()). When present, every helper reads AND
# writes through it so a read-modify-write inside a block sees the block's own uncommitted changes
# (e.g. two txs from one sender, or the producer credit after a tx debit) and the whole block is
# one atomic unit. When absent (a Tornado read path, or a standalone genesis write) each helper uses
# its own short transaction.
_local = threading.local()


def env_path(home=None):
    return os.path.join(home or get_home(), "index", "state")


def get_env(home=None):
    """Open (once) and return the LMDB env for `home`, with all named sub-DBs created.
    Sub-DB handles are stashed on the env as `_nado_dbs`."""
    path = env_path(home)
    env = _envs.get(path)
    if env is not None:
        return env
    with _envs_lock:
        env = _envs.get(path)
        if env is not None:
            return env
        os.makedirs(path, exist_ok=True)
        env = lmdb.open(
            path,
            map_size=MAP_SIZE,
            max_dbs=16,          # headroom over the 8 named sub-DBs
            subdir=True,
            readahead=False,     # random point lookups dominate
            writemap=False,      # safe: a full map raises MapFullError (no corruption), per spec
            metasync=True,
            sync=True,           # durable commits -> the crash-atomic guarantee
            max_readers=512,     # many Tornado reader threads
        )
        dbs = {}
        # open_db creates the sub-DB on first call; the DUPSORT flag is persisted and must be
        # passed consistently on every later open.
        for name in _PLAIN_DBS:
            dbs[name] = env.open_db(name.encode())
        for name in _DUP_DBS:
            dbs[name] = env.open_db(name.encode(), dupsort=True)
        _dbhandles[path] = dbs
        _envs[path] = env
        return env


def _dbs():
    get_env()  # ensure opened
    return _dbhandles[env_path()]


def init_env(home=None):
    """Open the env + sub-DBs (replaces SQLite CREATE TABLE DDL). Idempotent."""
    get_env(home)


def close_all():
    """Close every cached env (test teardown). After this, get_env reopens lazily."""
    with _envs_lock:
        for env in _envs.values():
            try:
                env.close()
            except Exception:
                pass
        _envs.clear()
        _dbhandles.clear()


# --- key / value encoding (the ONLY place that touches raw bytes) ---------------------------------

def be8(n: int) -> bytes:
    """8-byte big-endian unsigned: preserves numeric order under LMDB's bytewise key sort."""
    return struct.pack(">Q", int(n))


def un_be8(b: bytes) -> int:
    return struct.unpack(">Q", b)[0]


def _dup_tx_value(block_number: int, txid: str) -> bytes:
    """tx_by_sender / tx_by_recipient dup value: block_number(8B BE)||txid. Sorts by block (BE)
    then txid, and makes the rollback delete key UNAMBIGUOUS (exact dup written on apply)."""
    return be8(block_number) + txid.encode()


def _split_dup_tx_value(v: bytes):
    return un_be8(v[:8]), v[8:].decode()


def _pack(doc) -> bytes:
    return msgpack.packb(doc, use_bin_type=True)


def _unpack(raw: bytes):
    return msgpack.unpackb(raw, raw=False)


# --- transaction plumbing -------------------------------------------------------------------------

class _WriteTxn:
    """Group ALL of a block's mutations into ONE atomic env.begin(write=True). Re-entrant (mirrors
    the old sqlite transaction() depth): a nested `with write_txn()` reuses the outer txn and only
    the outermost commits (on success) or aborts (on any exception). This is what makes
    incorporate_block / rollback_one_block all-or-nothing."""

    def __enter__(self):
        depth = getattr(_local, "wdepth", 0)
        if depth == 0:
            _local.wtxn = get_env().begin(write=True)
        _local.wdepth = depth + 1
        return _local.wtxn

    def __exit__(self, exc_type, exc, tb):
        _local.wdepth -= 1
        if _local.wdepth == 0:
            txn = _local.wtxn
            _local.wtxn = None
            if exc_type is None:
                txn.commit()
            else:
                txn.abort()
        return False  # never suppress


def write_txn():
    return _WriteTxn()


def _read(fn):
    """Run fn(txn): inside the active write txn if one is open in this thread (so it sees the
    block's own uncommitted writes), else in a fresh short read-only txn."""
    active = getattr(_local, "wtxn", None)
    if active is not None:
        return fn(active)
    with get_env().begin(write=False) as txn:
        return fn(txn)


def _write(fn):
    """Run fn(txn): inside the active write txn if open (no commit here — the context commits),
    else in a fresh write txn committed on success."""
    active = getattr(_local, "wtxn", None)
    if active is not None:
        return fn(active)
    with get_env().begin(write=True) as txn:
        return fn(txn)


# --- accounts (schemaless docs) -------------------------------------------------------------------

def _normalize(body: dict) -> dict:
    """Canonical field order so the same doc content always serializes to the SAME bytes
    (deterministic -> revert returns a doc byte-identical to before). Extra/schemaless fields are
    appended in sorted order. `address` is the KEY, never stored in the value."""
    out = {f: int(body.get(f, 0)) for f in ACCOUNT_FIELDS}
    for k in sorted(body):
        if k not in ACCOUNT_FIELDS and k != "address":
            out[k] = body[k]
    return out


def _get_body(txn, address: str):
    raw = txn.get(address.encode(), db=_dbs()["accounts"])
    return _unpack(raw) if raw is not None else None


def get_account(address: str):
    """Return the account doc {address, balance, produced, bonded, registered, fidelity, ...} with
    missing fields defaulted to 0, or None if the address has never been touched. (No side effects:
    auto-creation of empty rows on a read would make the persisted account set non-deterministic
    across nodes — write paths create rows as needed.)"""
    body = _read(lambda txn: _get_body(txn, address))
    if body is None:
        return None
    acc = {"address": address}
    for f in ACCOUNT_FIELDS:
        acc[f] = body.get(f, 0)
    for k, v in body.items():
        if k not in acc:
            acc[k] = v
    return acc


def put_account(address: str, fields: dict):
    """Create-or-replace an account doc (used by create_account / snapshot import / reindex)."""
    def _do(txn):
        txn.put(address.encode(), _pack(_normalize(fields)), db=_dbs()["accounts"])
    _write(_do)


def create_account_if_absent(address: str, **fields):
    """INSERT-OR-IGNORE: write the doc only if the address has no row yet (idempotent seeding)."""
    def _do(txn):
        if txn.get(address.encode(), db=_dbs()["accounts"]) is None:
            txn.put(address.encode(), _pack(_normalize(fields)), db=_dbs()["accounts"])
    _write(_do)


def account_adjust(address: str, field: str, delta: int, floor_zero: bool = True) -> bool:
    """Read-modify-write one numeric field of an account doc (creating the doc with zero fields if
    absent). With floor_zero, refuse to drive the field below 0 (return False, leave doc unchanged)
    so a bad/mismatched revert fails closed instead of going negative. Runs in the active write txn
    so the new value reflects earlier mutations in the same block."""
    def _do(txn):
        body = _get_body(txn, address) or {}
        new_val = int(body.get(field, 0)) + delta
        if floor_zero and new_val < 0:
            return False
        body[field] = new_val
        txn.put(address.encode(), _pack(_normalize(body)), db=_dbs()["accounts"])
        return True
    return _write(_do)


def account_set(address: str, field: str, value: int):
    """Set one field to an absolute value (creating the doc if absent). Used for the registered
    flag (apply -> 1, revert -> 0)."""
    def _do(txn):
        body = _get_body(txn, address) or {}
        body[field] = int(value)
        txn.put(address.encode(), _pack(_normalize(body)), db=_dbs()["accounts"])
    _write(_do)


def account_set_field(address: str, field: str, value):
    """Set a NON-integer schemaless field (e.g. the pubkey-once `public_key` hex string) on an
    existing-or-new account doc. _normalize passes extra fields through in sorted order."""
    def _do(txn):
        body = _get_body(txn, address) or {}
        body[field] = value
        txn.put(address.encode(), _pack(_normalize(body)), db=_dbs()["accounts"])
    _write(_do)


def account_del_field(address: str, field: str):
    """Remove a schemaless field from an account doc if present (revert-symmetric pubkey-once clear).
    No-op if the account or field is absent."""
    def _do(txn):
        body = _get_body(txn, address)
        if body is not None and field in body:
            del body[field]
            txn.put(address.encode(), _pack(_normalize(body)), db=_dbs()["accounts"])
    _write(_do)


def iter_accounts():
    """Yield (address:str, doc:dict) for every account, ordered by address (LMDB key sort ==
    bytewise == Python str sort for ASCII addresses). Used by snapshot read + reindex merge."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["accounts"]) as cur:
            for k, v in cur:
                body = _unpack(v)
                acc = {f: body.get(f, 0) for f in ACCOUNT_FIELDS}
                for kk, vv in body.items():
                    if kk not in acc:
                        acc[kk] = vv
                out.append((k.decode(), acc))
        return out
    return _read(_do)


# --- totals ---------------------------------------------------------------------------------------

def totals_get() -> dict:
    def _do(txn):
        raw = txn.get(_TOTALS_KEY, db=_dbs()["totals"])
        return _unpack(raw) if raw is not None else {"produced": 0, "fees": 0}
    t = _read(_do)
    return {"produced": t.get("produced", 0), "fees": t.get("fees", 0)}


def totals_seed():
    """Seed totals to {0,0} once (idempotent re-run), mirroring the old INSERT-once."""
    def _do(txn):
        if txn.get(_TOTALS_KEY, db=_dbs()["totals"]) is None:
            txn.put(_TOTALS_KEY, _pack({"produced": 0, "fees": 0}), db=_dbs()["totals"])
    _write(_do)


def totals_add(produced: int, fees: int):
    """Add signed deltas to totals (rollback passes NEGATIVE deltas -> revert-symmetric)."""
    def _do(txn):
        raw = txn.get(_TOTALS_KEY, db=_dbs()["totals"])
        t = _unpack(raw) if raw is not None else {"produced": 0, "fees": 0}
        t = {"produced": t.get("produced", 0) + produced, "fees": t.get("fees", 0) + fees}
        txn.put(_TOTALS_KEY, _pack(t), db=_dbs()["totals"])
    _write(_do)


def totals_set(produced: int, fees: int):
    def _do(txn):
        txn.put(_TOTALS_KEY, _pack({"produced": int(produced), "fees": int(fees)}), db=_dbs()["totals"])
    _write(_do)


# --- meta (small persisted scalars: finalized_height, ...) -----------------------------------------

def meta_get_int(key: str, default: int = 0) -> int:
    """Read a persisted integer scalar from the meta sub-DB (default when absent)."""
    def _do(txn):
        raw = txn.get(key.encode(), db=_dbs()["meta"])
        return int(_unpack(raw)) if raw is not None else default
    return _read(_do)


def meta_set_int(key: str, value: int):
    """Persist an integer scalar. Used for the monotonic finalized_height floor (#17)."""
    def _do(txn):
        txn.put(key.encode(), _pack(int(value)), db=_dbs()["meta"])
    _write(_do)


def meta_del(key: str):
    """Delete a meta scalar if present (revert-symmetric clears)."""
    def _do(txn):
        txn.delete(key.encode(), db=_dbs()["meta"])
    _write(_do)


# --- slashing replay guard (#15/#16 step 5C/6): one slash per (offender, height) ------------------

def _slash_key(address: str, height: int) -> str:
    return f"slash:{address}:{int(height)}"


def slash_exists(address: str, height: int) -> bool:
    return meta_get_int(_slash_key(address, height), 0) == 1


def slash_record(address: str, height: int):
    meta_set_int(_slash_key(address, height), 1)


def slash_clear(address: str, height: int):
    meta_del(_slash_key(address, height))


# --- FFG attestations (#6): tally per (epoch, checkpoint) + one-per-(validator, epoch) uniqueness ---

def _attest_unique_key(validator: str, epoch: int) -> str:
    return f"att:{validator}:{int(epoch)}"


def attestation_exists(epoch: int, validator: str) -> bool:
    """True if `validator` already has an attestation recorded for `epoch` (on-chain double-vote guard)."""
    return meta_get_int(_attest_unique_key(validator, epoch), 0) == 1


def attestation_put(epoch: int, validator: str, target_hash: str):
    """Record a bonded validator's attestation of checkpoint (epoch, target_hash). The DUPSORT row
    feeds the per-(epoch,checkpoint) tally; the meta marker enforces ONE attestation per validator per
    epoch (so a validator can never on-chain double-vote). Revert via attestation_del."""
    def _do(txn):
        txn.put(be8(epoch), f"{validator}|{target_hash}".encode(), db=_dbs()["attestations"], dupdata=True)
    _write(_do)
    meta_set_int(_attest_unique_key(validator, epoch), 1)


def attestation_del(epoch: int, validator: str, target_hash: str):
    """Revert attestation_put exactly (rollback): delete the precise DUPSORT row + the uniqueness marker."""
    def _do(txn):
        txn.delete(be8(epoch), f"{validator}|{target_hash}".encode(), db=_dbs()["attestations"])
    _write(_do)
    meta_del(_attest_unique_key(validator, epoch))


def attestations_for_epoch(epoch: int):
    """List (validator, target_hash) attestations recorded for `epoch`, in deterministic DUPSORT order."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["attestations"]) as cur:
            if cur.set_key(be8(epoch)):
                for v in cur.iternext_dup(keys=False, values=True):
                    s = v.decode()
                    validator, target_hash = s.split("|", 1)
                    out.append((validator, target_hash))
        return out
    return _read(_do)


# --- RANDAO commit-reveal (#7): one commit per (sender, target_epoch) + revealed secrets per epoch ---

def _commit_key(sender: str, target_epoch: int) -> bytes:
    return f"{sender}|{int(target_epoch)}".encode()


def commit_get(sender: str, target_epoch: int):
    """The commitment a bonded sender published for target_epoch (None if none)."""
    def _do(txn):
        v = txn.get(_commit_key(sender, target_epoch), db=_dbs()["commits"])
        return v.decode() if v is not None else None
    return _read(_do)


def commit_put(sender: str, target_epoch: int, commitment: str):
    def _do(txn):
        txn.put(_commit_key(sender, target_epoch), commitment.encode(), db=_dbs()["commits"])
    _write(_do)


def commit_del(sender: str, target_epoch: int):
    def _do(txn):
        txn.delete(_commit_key(sender, target_epoch), db=_dbs()["commits"])
    _write(_do)


def reveal_put(target_epoch: int, secret: str):
    """Record a revealed secret seeding target_epoch's beacon (DUPSORT auto-dedups identical secrets)."""
    def _do(txn):
        txn.put(be8(target_epoch), secret.encode(), db=_dbs()["reveals"], dupdata=True)
    _write(_do)


def reveal_del(target_epoch: int, secret: str):
    def _do(txn):
        txn.delete(be8(target_epoch), secret.encode(), db=_dbs()["reveals"])
    _write(_do)


def reveals_for_epoch(target_epoch: int):
    """Sorted list of revealed secrets seeding target_epoch's beacon (deterministic DUPSORT order)."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["reveals"]) as cur:
            if cur.set_key(be8(target_epoch)):
                for v in cur.iternext_dup(keys=False, values=True):
                    out.append(v.decode())
        return out
    return _read(_do)


# --- unbond delay (#unbond): one pending withdrawal per address {amount, release_block} ------------

def unbond_get(address: str):
    """The pending unbond {amount, release_block} for address, or None. The coins remain in `bonded`
    (slashable + weighted) until a matured `withdraw` moves them to spendable balance."""
    def _do(txn):
        raw = txn.get(address.encode(), db=_dbs()["unbonds"])
        return _unpack(raw) if raw is not None else None
    return _read(_do)


def unbond_put(address: str, amount: int, release_block: int):
    def _do(txn):
        txn.put(address.encode(), _pack({"amount": int(amount), "release_block": int(release_block)}),
                db=_dbs()["unbonds"])
    _write(_do)


def unbond_del(address: str):
    def _do(txn):
        txn.delete(address.encode(), db=_dbs()["unbonds"])
    _write(_do)


# --- block number <-> hash index ------------------------------------------------------------------

def block_index_put(block_number: int, block_hash: str):
    """INSERT-OR-IGNORE the number<->hash mapping in both directions. The applied marker that
    block_already_indexed checks; written INSIDE the incorporate txn so it commits atomically."""
    def _do(txn):
        bn = be8(block_number)
        bh = block_hash.encode()
        # idempotent: only write if not already present (matches INSERT OR IGNORE)
        if txn.get(bn, db=_dbs()["block_by_num"]) is None:
            txn.put(bn, bh, db=_dbs()["block_by_num"])
        if txn.get(bh, db=_dbs()["block_by_hash"]) is None:
            txn.put(bh, bn, db=_dbs()["block_by_hash"])
    _write(_do)


def block_index_del(block_number: int, block_hash: str):
    """Delete both directions of the mapping (rollback unindex)."""
    def _do(txn):
        txn.delete(be8(block_number), db=_dbs()["block_by_num"])
        txn.delete(block_hash.encode(), db=_dbs()["block_by_hash"])
    _write(_do)


def hash_by_number(block_number: int):
    def _do(txn):
        v = txn.get(be8(block_number), db=_dbs()["block_by_num"])
        return v.decode() if v is not None else None
    return _read(_do)


def number_by_hash(block_hash: str):
    def _do(txn):
        v = txn.get(block_hash.encode(), db=_dbs()["block_by_hash"])
        return un_be8(v) if v is not None else None
    return _read(_do)


def block_hash_indexed(block_hash: str) -> bool:
    """True if this exact block hash is in the index (idempotency guard for incorporate)."""
    return _read(lambda txn: txn.get(block_hash.encode(), db=_dbs()["block_by_hash"]) is not None)


# --- transaction index (primary + DUPSORT secondaries) --------------------------------------------

def tx_index_put(txid: str, block_number: int, sender: str, recipient: str):
    """Index one tx: primary (txid -> body) + the two DUPSORT secondaries (sender/recipient ->
    block||txid). INSERT-OR-IGNORE on the primary so (re)indexing is idempotent. DUPSORT dedups
    identical dups, so a replayed index is also a no-op on the secondaries."""
    def _do(txn):
        tdb = _dbs()["tx"]
        key = txid.encode()
        if txn.get(key, db=tdb) is None:
            txn.put(key, _pack({"block_number": block_number, "sender": sender,
                                "recipient": recipient}), db=tdb)
        dv = _dup_tx_value(block_number, txid)
        txn.put(sender.encode(), dv, db=_dbs()["tx_by_sender"], dupdata=True)
        txn.put(recipient.encode(), dv, db=_dbs()["tx_by_recipient"], dupdata=True)
    _write(_do)


def tx_index_del(txid: str, block_number: int, sender: str, recipient: str):
    """Revert tx_index_put EXACTLY: delete the primary and the precise dups written on apply
    (the block||txid encoding makes each dup key unambiguous)."""
    def _do(txn):
        txn.delete(txid.encode(), db=_dbs()["tx"])
        dv = _dup_tx_value(block_number, txid)
        txn.delete(sender.encode(), dv, db=_dbs()["tx_by_sender"])
        txn.delete(recipient.encode(), dv, db=_dbs()["tx_by_recipient"])
    _write(_do)


def tx_get(txid: str):
    def _do(txn):
        raw = txn.get(txid.encode(), db=_dbs()["tx"])
        return _unpack(raw) if raw is not None else None
    return _read(_do)


def _scan_dup_from(txn, db, key: str, min_block: int):
    """Yield (block_number, txid) dups for `key` with block_number >= min_block, ascending by
    (block, txid). Positions the cursor at the first dup >= block||'' via set_range_dup."""
    out = []
    with txn.cursor(db=db) as cur:
        if not cur.set_range_dup(key.encode(), be8(min_block)):
            return out
        # set_range_dup landed on the first dup of `key` with value >= be8(min_block); walk its dups.
        for v in cur.iternext_dup(keys=False, values=True):
            out.append(_split_dup_tx_value(v))
    return out


def tx_of_account(address: str, min_block: int, limit: int):
    """Account history UNION: merge the sender and recipient DUPSORT cursors (both ordered by
    block), restrict to block_number >= min_block, dedup by txid, order by block, take `limit`.
    Returns a list of (block_number, txid). Deterministic (LMDB sorts dups)."""
    def _do(txn):
        rows = _scan_dup_from(txn, _dbs()["tx_by_sender"], address, min_block)
        rows += _scan_dup_from(txn, _dbs()["tx_by_recipient"], address, min_block)
        seen = set()
        merged = []
        for bn, txid in rows:
            if txid not in seen:
                seen.add(txid)
                merged.append((bn, txid))
        merged.sort(key=lambda r: (r[0], r[1]))
        return merged[:limit]
    return _read(_do)


# --- heartbeats (DUPSORT presence index) ----------------------------------------------------------

def heartbeat_put(epoch: int, address: str):
    """Record a presence heartbeat. DUPSORT auto-dedups identical (epoch,address) -> one-per-
    (address,epoch) enforced for free (a duplicate is a silent no-op, never a second dup)."""
    def _do(txn):
        txn.put(be8(epoch), address.encode(), db=_dbs()["heartbeats"], dupdata=True)
    _write(_do)


def heartbeat_del(epoch: int, address: str):
    """Delete the exact (epoch,address) dup (rollback revert — unambiguous)."""
    def _do(txn):
        txn.delete(be8(epoch), address.encode(), db=_dbs()["heartbeats"])
    _write(_do)


def heartbeat_present(epoch: int, address: str) -> bool:
    """True if `address` already has a presence heartbeat recorded for `epoch`. AUDIT FIX: the DUPSORT
    store dedups the row but does NOT reject a second heartbeat tx, so validation must check this to
    enforce one-per-(address,epoch) (else fidelity is farmed + a reorg can over-delete the shared dup)."""
    def _do(txn):
        with txn.cursor(db=_dbs()["heartbeats"]) as cur:
            return cur.set_key_dup(be8(epoch), address.encode())
    return _read(_do)


def heartbeat_gc(max_epoch_inclusive: int):
    """Drop every heartbeat with epoch <= max_epoch_inclusive (anti-bloat GC). These rows are older
    than the presence window and outside any rollback window, so they are never read or reverted
    again. No-op when max_epoch_inclusive < 0."""
    if max_epoch_inclusive < 0:
        return

    def _do(txn):
        hdb = _dbs()["heartbeats"]
        ceiling = be8(max_epoch_inclusive)
        stale_keys = []
        with txn.cursor(db=hdb) as cur:
            if cur.first():
                for k in cur.iternext_nodup(keys=True, values=False):
                    if k > ceiling:
                        break
                    stale_keys.append(bytes(k))
        for k in stale_keys:
            txn.delete(k, db=hdb)  # deletes ALL dups for the key
    _write(_do)


def hb_revert_put(epoch: int, address: str, prev_epoch: int, net_delta: int):
    """FIDELITY DECAY (revert record): store the EXACT inverse of a heartbeat's fidelity update — the
    account's PREVIOUS last-seen epoch and the NET fidelity delta applied — keyed (epoch,address), plain
    KV. Rollback reads this to restore fidelity + last_hb_epoch byte-identically. Written inside the
    incorporate write txn (atomic with the heartbeat itself)."""
    def _do(txn):
        txn.put(be8(epoch) + address.encode(),
                _pack([int(prev_epoch), int(net_delta)]), db=_dbs()["hb_revert"])
    _write(_do)


def hb_revert_pop(epoch: int, address: str):
    """Read + DELETE the revert record for (epoch,address); returns (prev_epoch, net_delta) or None
    (None => nothing to invert, e.g. a heartbeat from before this feature). Runs in the active txn."""
    def _do(txn):
        key = be8(epoch) + address.encode()
        raw = txn.get(key, db=_dbs()["hb_revert"])
        if raw is None:
            return None
        txn.delete(key, db=_dbs()["hb_revert"])
        prev, net = _unpack(raw)
        return int(prev), int(net)
    return _write(_do)


def hb_revert_gc(max_epoch_inclusive: int):
    """Drop revert records with epoch <= max_epoch_inclusive — older than any rollback window, so never
    needed again (mirrors heartbeat_gc; NOT reverted). No-op when negative. Keys are be8(epoch)+address,
    so the 8-byte epoch prefix sorts first and we can stop at the ceiling."""
    if max_epoch_inclusive < 0:
        return

    def _do(txn):
        rdb = _dbs()["hb_revert"]
        ceiling = be8(max_epoch_inclusive)
        stale = []
        with txn.cursor(db=rdb) as cur:
            if cur.first():
                for k in cur.iternext(keys=True, values=False):
                    if bytes(k[:8]) > ceiling:
                        break
                    stale.append(bytes(k))
        for k in stale:
            txn.delete(k, db=rdb)
    _write(_do)


def heartbeat_addresses_after(floor_epoch: int):
    """Set of addresses with a heartbeat in some epoch STRICTLY GREATER than floor_epoch (i.e.
    epoch > floor_epoch). Range-scan from the first key >= floor_epoch+1 (clamped to 0) to the end.
    Used by get_open_registry's presence-window filter."""
    start = max(0, floor_epoch + 1)

    def _do(txn):
        addrs = set()
        with txn.cursor(db=_dbs()["heartbeats"]) as cur:
            if cur.set_range(be8(start)):
                for _, v in cur.iternext(keys=True, values=True):
                    addrs.add(v.decode())
        return addrs
    return _read(_do)


# --- maintenance helpers (prune) ------------------------------------------------------------------

def iter_block_numbers():
    """Yield (block_number:int, block_hash:str) for every indexed block, ascending."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["block_by_num"]) as cur:
            for k, v in cur:
                out.append((un_be8(k), v.decode()))
        return out
    return _read(_do)


def iter_tx_index():
    """Yield (txid:str, body:dict) for every indexed tx."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["tx"]) as cur:
            for k, v in cur:
                out.append((k.decode(), _unpack(v)))
        return out
    return _read(_do)


def clear_accounts_and_totals(txn=None):
    """Drop all account docs + reset totals (snapshot import replaces them wholesale)."""
    def _do(t):
        t.drop(_dbs()["accounts"], delete=False)   # empty the sub-DB, keep the handle
        t.put(_TOTALS_KEY, _pack({"produced": 0, "fees": 0}), db=_dbs()["totals"])
    if txn is not None:
        _do(txn)
    else:
        _write(_do)


def drop_tx_index():
    """Empty all three tx sub-DBs (reindex rebuild)."""
    def _do(txn):
        for name in ("tx", "tx_by_sender", "tx_by_recipient"):
            txn.drop(_dbs()[name], delete=False)
    _write(_do)
