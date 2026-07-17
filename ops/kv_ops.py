"""
Schemaless key-value index for NADO (LMDB / MDBX data model), replacing the SQLite index.

Per doc/storage-kv-migration.md: ONE memory-mapped, ACID, single-writer LMDB env with named
sub-DBs. Account/state records are *schemaless codec documents* (ops/codec.py JSON — no columns, no
DDL) so adding a field needs no migration. This module encapsulates ALL key-encoding (8-byte
big-endian ints) and value (de)serialization (the codec) so call-sites never touch raw bytes.

ATOMICITY: a whole block mutation (account docs + tx index + block index + totals + heartbeats)
commits in ONE env.begin(write=True) via the write_txn() context manager -> crash-atomic, directly
replacing the SQLite transaction() context (closes the LO-1/CO-4 window). LMDB is single-writer +
copy-on-write, so a crash mid-block leaves the block UNapplied, never half-applied.

DETERMINISM: LMDB stores keys (and DUPSORT dups) in sorted byte order, so range scans
(block_by_num iteration, heartbeats "epoch > E-PRESENCE_WINDOW", tx_by_* ordered-by-block history)
are deterministic and identical across nodes — required because get_open_registry and tx history
feed consensus selection.

The KV store is a DERIVED, rebuildable index. Block bodies are zstd(codec) records in append-only
segment files under blocks/ (ops/segment_store.py; the hash->locator `block_loc` sub-DB here is
NODE-LOCAL and snapshot-excluded, and records are self-describing so it stays rebuildable) —
consensus hashing stays canonical_bytes, untouched by any of this.
"""
import os
import struct
import threading

import lmdb
from ops import codec

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
_PLAIN_DBS = ("accounts", "totals", "block_by_num", "block_by_hash", "tx", "meta", "commits", "unbonds", "hb_revert", "aliases", "htlcs", "bond_since", "bond_since_revert", "treasury_proposals", "msgkey_revert", "block_loc", "gc_revert")
_DUP_DBS = ("tx_by_sender", "tx_by_recipient", "attestations", "reveals", "settlements", "recerts", "recert_by_epoch", "treasury_votes")

# CONSENSUS STATE a snapshot carries: every sub-DB EXCEPT the block-body + tx HISTORY (explorer-only,
# rebuilt by replaying the C+1..tip tail). This is the FULL producer-selection + validation state — account
# docs (balance/produced/bonded/registered/fidelity), totals, the deterministic meta replay-guards +
# finalized floor, recerts/recert_by_epoch (open-lane lease), bond_since (bonded ramp), commits/reveals
# (RANDAO beacon), attestations (FFG), unbonds, aliases, htlcs, settlements, treasury — so a snapshot-synced
# node derives the SAME producer set on tail replay. Sorted for a canonical, cross-node state root.
#
# block_by_num / block_by_hash (the number<->hash INDEX, not the block bodies) ARE carried: a snapshot-synced
# node must resolve get_block_hash_by_number for beacon anchors ((epoch-1)*EPOCH_LENGTH), FFG epoch
# boundaries and PoSW anchors that sit BEFORE the snapshot height — which the C+1..tip tail replay never
# rebuilds. Without them epoch_beacon raises "finalized anchor #N missing" and the node can't produce/verify.
# This mirrors rolling mode (which likewise ALWAYS keeps num<->hash and drops only bodies). The heavy tx
# history + block BODIES stay out; the recent bodies a node still needs (the rollback window +
# serving peers; REWARD_WINDOW kept as margin) are backfilled in loops/core_loop.snapshot_bootstrap.
_HISTORY_DBS = frozenset(("tx", "tx_by_sender", "tx_by_recipient"))
# NODE-LOCAL sub-DBs — NEVER snapshot-carried (leaking them would fork the canonical state root):
#   block_loc — segment-store locators + per-segment live counters (another node's segments differ)
#   gc_revert — idle-GC rollback records keyed by height (ops/gc_ops.py): purely local rollback
#               support, pruned lazily below the finalized height with no determinism requirement
_LOCAL_DBS = frozenset(("block_loc", "gc_revert"))
SNAPSHOT_DBS = tuple(sorted(set(_PLAIN_DBS + _DUP_DBS) - _HISTORY_DBS - _LOCAL_DBS))

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

# COMMITTED-WRITE GENERATION: bumped once per committed write (outermost write_txn or a standalone
# _write). Read-side caches (account_ops.get_bonded_registry) key on this: unchanged generation ==
# byte-identical committed state, so a cached derivation is exact, and ANY commit — block
# incorporation, rollback, snapshot restore, genesis — invalidates. Lock-guarded so two threads
# committing back-to-back can never merge into one bump (a lost bump would leave a cache stale).
_write_gen = 0
_write_gen_lock = threading.Lock()


def _bump_write_gen():
    global _write_gen
    with _write_gen_lock:
        _write_gen += 1


def write_generation() -> int:
    """Monotonic committed-state version (see _write_gen). Cheap cache key for derived reads."""
    return _write_gen


def in_write_txn() -> bool:
    """True while THIS thread holds an open write_txn — derived-read caches must bypass themselves
    then, because in-txn reads see the block's own uncommitted mutations."""
    return getattr(_local, "wtxn", None) is not None


def env_path(home=None):
    """Filesystem dir of the LMDB env for `home` (index/state under the node home) — the _envs cache key."""
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
            max_dbs=32,          # headroom over the named sub-DBs (_PLAIN_DBS + _DUP_DBS, now 17)
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
    """Inverse of be8: decode an 8-byte big-endian unsigned int."""
    return struct.unpack(">Q", b)[0]


def _dup_tx_value(block_number: int, txid: str) -> bytes:
    """tx_by_sender / tx_by_recipient dup value: block_number(8B BE)||txid. Sorts by block (BE)
    then txid, and makes the rollback delete key UNAMBIGUOUS (exact dup written on apply)."""
    return be8(block_number) + txid.encode()


def _split_dup_tx_value(v: bytes):
    """Inverse of _dup_tx_value: (block_number, txid)."""
    return un_be8(v[:8]), v[8:].decode()


def _pack(doc) -> bytes:
    """codec-encode a stored value (same content always yields the same bytes, which
    revert-symmetry and the state root depend on)."""
    return codec.pack(doc)


def _unpack(raw: bytes):
    """Decode codec bytes written by _pack."""
    return codec.unpack(raw)


# --- transaction plumbing -------------------------------------------------------------------------

class _WriteTxn:
    """Group ALL of a block's mutations into ONE atomic env.begin(write=True). Re-entrant (mirrors
    the old sqlite transaction() depth): a nested `with write_txn()` reuses the outer txn and only
    the outermost commits (on success) or aborts (on any exception). This is what makes
    incorporate_block / rollback_one_block all-or-nothing."""

    def __enter__(self):
        """Open the env write txn only at depth 0; nested entries just bump the depth and reuse it."""
        depth = getattr(_local, "wdepth", 0)
        if depth == 0:
            _local.wtxn = get_env().begin(write=True)
        _local.wdepth = depth + 1
        return _local.wtxn

    def __exit__(self, exc_type, exc, tb):
        """Outermost exit commits on success / aborts on any exception; inner exits only decrement.
        Never suppresses the exception — the caller must see the failure that voided the block."""
        _local.wdepth -= 1
        if _local.wdepth == 0:
            txn = _local.wtxn
            _local.wtxn = None
            if exc_type is None:
                txn.commit()
                _bump_write_gen()
            else:
                txn.abort()
        return False  # never suppress


def write_txn():
    """The atomic-block context manager: `with write_txn():` makes every kv helper inside it read and
    write through ONE LMDB write txn (crash-atomic, re-entrant — see _WriteTxn)."""
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
        result = fn(txn)
    _bump_write_gen()
    return result


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
    """Raw account doc via the CALLER's txn (so read-modify-writes see the block's own uncommitted
    state), or None if the address has no row. No field defaulting — that's get_account's job."""
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
    """Global running totals {produced, fees} (zeros before totals_seed) — feeds emission/reward math."""
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
    """Overwrite totals with absolute values (snapshot import / reindex). Block apply/rollback must use
    the delta form totals_add to stay revert-symmetric."""
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
    """meta key of the one-slash-per-(offender, height) marker."""
    return f"slash:{address}:{int(height)}"


def slash_exists(address: str, height: int) -> bool:
    """True if (offender, height) was already slashed — the replay guard that stops a re-broadcast
    slashing proof from punishing the same offense twice."""
    return meta_get_int(_slash_key(address, height), 0) == 1


def slash_record(address: str, height: int):
    """Mark (offender, height) slashed (apply-side; atomic with the penalty inside the block txn)."""
    meta_set_int(_slash_key(address, height), 1)


def slash_clear(address: str, height: int):
    """Revert slash_record exactly (rollback deletes the marker so a re-applied block can re-slash)."""
    meta_del(_slash_key(address, height))


# --- FFG attestations (#6): tally per (epoch, checkpoint) + one-per-(validator, epoch) uniqueness ---

def _attest_unique_key(validator: str, epoch: int) -> str:
    """meta key of the one-attestation-per-(validator, epoch) uniqueness marker."""
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


# --- Execution-layer settlement (Phase 2): tally per (exec_cursor, state_root) + one-per-(validator,cursor) ---

def _settle_key(ns: str, cursor: int) -> bytes:
    """DUPSORT key for the settlements db: namespace + NUL + big-endian cursor. The fixed 8-byte cursor
    tail lets settlement_cursors() split ns from cursor by prefix. Namespacing lets many rollups settle
    to L1 independently under one bonded quorum."""
    return ns.encode() + b"\x00" + be8(cursor)


def _settle_unique_key(ns: str, validator: str, cursor: int) -> str:
    """meta key of the one-settlement-per-(ns, validator, exec_cursor) uniqueness marker."""
    return f"settle:{ns}:{validator}:{int(cursor)}"


def settlement_exists(ns: str, cursor: int, validator: str) -> bool:
    """True if `validator` already attested a settlement for (ns, exec_cursor) (one-per-validator guard)."""
    return meta_get_int(_settle_unique_key(ns, validator, cursor), 0) == 1


def settlement_put(ns: str, cursor: int, validator: str, state_root: str):
    """Record a bonded validator's settlement attestation of (ns, exec_cursor, state_root)."""
    def _do(txn):
        txn.put(_settle_key(ns, cursor), f"{validator}|{state_root}".encode(), db=_dbs()["settlements"], dupdata=True)
    _write(_do)
    meta_set_int(_settle_unique_key(ns, validator, cursor), 1)


def settlement_del(ns: str, cursor: int, validator: str, state_root: str):
    """Revert settlement_put exactly (rollback): delete the DUPSORT row + the uniqueness marker."""
    def _do(txn):
        txn.delete(_settle_key(ns, cursor), f"{validator}|{state_root}".encode(), db=_dbs()["settlements"])
    _write(_do)
    meta_del(_settle_unique_key(ns, validator, cursor))


def _settle_proof_key(ns: str, cursor: int, state_root: str) -> str:
    """meta key of the on-chain VALIDITY-PROOF marker. A `settle`-with-proof tx whose recursion proof
    verified DETERMINISTICALLY at block-validation records (ns, cursor, state_root) as proven. This is the
    committed-state replacement for the old node-local proof cache: settlement_justified reads it, so a
    validity-proven root justifies WITHOUT a bonded quorum and IDENTICALLY on every node (no fork). Stored
    as an integer REFCOUNT (not a bool) so it is revert-symmetric even if two validators land a proof for
    the same (ns, cursor, root) in one block — deleting one leaves the marker set while the other stands."""
    return f"settleproof:{ns}:{int(cursor)}:{state_root}"


def settlement_proven(ns: str, cursor: int, state_root: str) -> bool:
    """True iff an on-chain settle-with-proof committed a VERIFIED recursion proof for exactly
    (ns, cursor, state_root). Pure committed-state read — the cryptography ran once, at the settling
    block's validation; every node just reads the same marker."""
    return meta_get_int(_settle_proof_key(ns, cursor, state_root), 0) > 0


def settlement_proof_put(ns: str, cursor: int, state_root: str):
    """Mark (ns, cursor, state_root) validity-PROVEN on-chain (a settle-with-proof tx applied). Refcount++."""
    k = _settle_proof_key(ns, cursor, state_root)
    meta_set_int(k, meta_get_int(k, 0) + 1)


def settlement_proof_del(ns: str, cursor: int, state_root: str):
    """Revert settlement_proof_put exactly (rollback). Refcount--; clears the marker at zero."""
    k = _settle_proof_key(ns, cursor, state_root)
    n = meta_get_int(k, 0) - 1
    if n > 0:
        meta_set_int(k, n)
    else:
        meta_del(k)


def settlements_for_cursor(ns: str, cursor: int):
    """List (validator, state_root) settlement attestations recorded for (ns, cursor), DUPSORT order."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["settlements"]) as cur:
            if cur.set_key(_settle_key(ns, cursor)):
                for v in cur.iternext_dup(keys=False, values=True):
                    validator, state_root = v.decode().split("|", 1)
                    out.append((validator, state_root))
        return out
    return _read(_do)


def settlement_max_cursor(ns: str) -> int:
    """Highest exec cursor with at least one settlement attestation in `ns`, or -1. Range-seek on
    the (ns, cursor) key prefix — O(log n), never a full scan."""
    prefix = ns.encode() + b"\x00"
    def _do(txn):
        best = -1
        with txn.cursor(db=_dbs()["settlements"]) as cur:
            # seek just past the ns prefix space, then step back to the last key inside it
            if cur.set_range(prefix + b"\xff" * 8):
                if cur.prev_nodup() and cur.key().startswith(prefix) and len(cur.key()) == len(prefix) + 8:
                    best = int.from_bytes(cur.key()[len(prefix):], "big")
            elif cur.last():
                if cur.key().startswith(prefix) and len(cur.key()) == len(prefix) + 8:
                    best = int.from_bytes(cur.key()[len(prefix):], "big")
        return best
    return _read(_do)


def settlement_validators_since(ns: str, floor_cursor: int) -> set:
    """Validators with ANY settle attestation for `ns` at a cursor >= floor_cursor — the ACTIVE
    settler set for the settlement inactivity leak (protocol.SETTLE_ACTIVITY_CURSORS). Range scan
    from the floor key; O(attestations inside the window), independent of total history."""
    prefix = ns.encode() + b"\x00"
    start = prefix + be8(max(0, int(floor_cursor)))
    def _do(txn):
        out = set()
        with txn.cursor(db=_dbs()["settlements"]) as cur:
            if cur.set_range(start):
                for k, v in cur.iternext(keys=True, values=True):
                    if not k.startswith(prefix) or len(k) != len(prefix) + 8:
                        break
                    out.add(v.decode().split("|", 1)[0])
        return out
    return _read(_do)


def settlement_cursors(ns: str):
    """All exec_cursors in namespace `ns` that have at least one settlement attestation, ascending."""
    prefix = ns.encode() + b"\x00"
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["settlements"]) as cur:
            if cur.first():
                for k in cur.iternext_nodup(keys=True, values=False):
                    if k.startswith(prefix) and len(k) == len(prefix) + 8:
                        out.append(int.from_bytes(k[len(prefix):], "big"))
        return out
    return _read(_do)


# --- Registration PoSW recerts (renewable presence lease): DUPSORT address -> epoch, revert-safe like
# heartbeats (insert on apply, delete on rollback). Eligibility = a recert within POSW_LEASE_EPOCHS. ---

def recert_put(address: str, epoch: int):
    """Record a PoSW recert of `address` at `epoch` in BOTH indexes (apply-side, inside the block txn).
    DUPSORT treats an exact-dup put as a no-op, so replaying the same block is idempotent."""
    # Two revert-safe indexes: recerts (address -> epoch) for recert_latest, and recert_by_epoch
    # (epoch -> address) so get_open_registry can range-scan the currently-leased set (like heartbeats did).
    def _do(txn):
        txn.put(address.encode(), be8(int(epoch)), db=_dbs()["recerts"], dupdata=True)
        txn.put(be8(int(epoch)), address.encode(), db=_dbs()["recert_by_epoch"], dupdata=True)
    _write(_do)


def recert_del(address: str, epoch: int):
    """Revert recert_put exactly (rollback): delete the precise (address, epoch) dup from both indexes."""
    def _do(txn):
        txn.delete(address.encode(), be8(int(epoch)), db=_dbs()["recerts"])
        txn.delete(be8(int(epoch)), address.encode(), db=_dbs()["recert_by_epoch"])
    _write(_do)


def recert_addresses_after(floor_epoch: int):
    """Set of addresses with a recert in some epoch > floor_epoch — i.e. the OPEN-lane present set (a valid
    lease). Range-scan the epoch index from floor_epoch+1. This replaces heartbeat_addresses_after: presence
    IS a fresh PoSW recert, so there's no separate heartbeat mechanism (doc/presence-dividend.md §2.4)."""
    start = max(0, floor_epoch + 1)
    def _do(txn):
        addrs = set()
        with txn.cursor(db=_dbs()["recert_by_epoch"]) as cur:
            if cur.set_range(be8(start)):
                for _, v in cur.iternext(keys=True, values=True):
                    addrs.add(v.decode())
        return addrs
    return _read(_do)


def recert_count_in_window(lo_epoch: int, hi_epoch: int) -> int:
    """Number of recerts/registrations recorded in epochs [lo_epoch, hi_epoch] inclusive, from the
    recert_by_epoch index. NOT consensus-bound: the index is incrementally maintained and survives
    upgrades, so its counts can diverge across nodes — the registration-rate PoSW difficulty counts from
    the chain's blocks instead (ops/reg_difficulty.py v2, 2026-07-17 split postmortem)."""
    if hi_epoch < lo_epoch:
        return 0
    lo = max(0, lo_epoch)
    def _do(txn):
        n = 0
        with txn.cursor(db=_dbs()["recert_by_epoch"]) as cur:
            if cur.set_range(be8(lo)):
                for k, _v in cur.iternext(keys=True, values=True):
                    if un_be8(k) > hi_epoch:
                        break
                    n += 1
        return n
    return _read(_do)


def backfill_recert_by_epoch() -> int:
    """One-time, IDEMPOTENT migration. The recert_by_epoch (epoch->address) index was introduced AFTER the
    recerts (address->epoch) index already held rows, so on an existing chain it starts EMPTY — and
    get_open_registry reads recert_by_epoch, so any miner whose recert predates the index shows up as
    ABSENT even though its lease is valid (a permanent stuck-'absent'). Copy every (address, epoch) from
    recerts into recert_by_epoch; DUPSORT dedups exact pairs, so re-running is a no-op. Returns rows copied."""
    def _do(txn):
        rows = []
        with txn.cursor(db=_dbs()["recerts"]) as cur:          # key=address, value=be8(epoch)
            for k, v in cur:
                rows.append((bytes(v), bytes(k)))              # recert_by_epoch: key=be8(epoch), value=address
        rbe = _dbs()["recert_by_epoch"]
        for ekey, addr in rows:
            txn.put(ekey, addr, db=rbe, dupdata=True)          # exact-dup put is a silent no-op under DUPSORT
        return len(rows)
    return _write(_do)


def recert_latest(address: str) -> int:
    """The most recent recert epoch for `address` (DUPSORT values sort ascending, so the last dup is the
    max), or -1 if none. Used for the presence-lease eligibility check + revert (clear `registered` if
    no recert remains)."""
    def _do(txn):
        with txn.cursor(db=_dbs()["recerts"]) as cur:
            if cur.set_key(address.encode()):
                cur.last_dup()
                return un_be8(cur.value())
        return -1
    return _read(_do)


def recert_epochs(address: str, upto_epoch: int = None) -> list:
    """ALL recert epochs for `address`, ascending (optionally only those <= upto_epoch). The full PoSW-lease
    history — used to reconstruct fidelity AS OF a past epoch (dividend fraud-proof, doc/dividend-fraud-proof.md):
    fidelity is a deterministic function of this immutable, revert-safe recert sequence, so any node can replay
    the exact ramp the live apply_register applied. Values sort ascending under DUPSORT."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["recerts"]) as cur:
            if cur.set_key(address.encode()):
                for v in cur.iternext_dup(keys=False, values=True):
                    e = un_be8(v)
                    if upto_epoch is not None and e > upto_epoch:
                        break                                   # ascending -> the rest are all > upto_epoch
                    out.append(e)
        return out
    return _read(_do)


# --- Bridge withdrawal nullifiers (Phase 2): each (addr, nonce) exit may be claimed on L1 at most once ---

def bridge_nullifier_exists(ns: str, addr: str, nonce: str) -> bool:
    """True if the (ns, addr, nonce) bridge exit was already claimed (double-claim replay guard). Namespaced
    so two rollups that reuse the same (addr, nonce) — near-certain with per-rollup sequential nonces — can
    each claim their own settled exit against the shared escrow without colliding."""
    return meta_get_int(f"bridgenull:{ns}:{addr}:{nonce}", 0) == 1


def bridge_nullifier_put(ns: str, addr: str, nonce: str):
    """Burn the (ns, addr, nonce) bridge-exit nullifier (apply-side, atomic with the exit)."""
    meta_set_int(f"bridgenull:{ns}:{addr}:{nonce}", 1)


def bridge_nullifier_del(ns: str, addr: str, nonce: str):
    """Revert bridge_nullifier_put exactly (rollback un-burns the nullifier)."""
    meta_del(f"bridgenull:{ns}:{addr}:{nonce}")


# --- Cross-rollup message (xmsg) nullifiers: each (from_ns, seq) message may be delivered on L1 at most once ---

def xmsg_nullifier_exists(from_ns: str, seq: int) -> bool:
    """True if the (from_ns, seq) cross-domain message was already delivered (replay guard)."""
    return meta_get_int(f"xmsgnull:{from_ns}:{int(seq)}", 0) == 1


def xmsg_nullifier_put(from_ns: str, seq: int):
    """Burn the (from_ns, seq) xmsg nullifier (apply-side, atomic with the delivery record)."""
    meta_set_int(f"xmsgnull:{from_ns}:{int(seq)}", 1)


def xmsg_nullifier_del(from_ns: str, seq: int):
    """Revert xmsg_nullifier_put exactly (rollback un-burns the nullifier)."""
    meta_del(f"xmsgnull:{from_ns}:{int(seq)}")


# --- Per-epoch DIVIDEND inflow: the total credited to DIVIDEND_POOL during each epoch, so the execution
# node distributes a DETERMINISTIC, epoch-bound amount (over weights_at_epoch) instead of a live pool-balance
# delta. Revert-symmetric (a rolled-back block subtracts its credit). Makes accrual a pure function of the
# finalized block stream. ---

def dividend_inflow_add(epoch: int, amount: int, revert: bool = False):
    """Accumulate (revert=False) or reverse (revert=True) the DIVIDEND_POOL inflow credited during `epoch`."""
    k = f"divinflow:{int(epoch)}"
    meta_set_int(k, meta_get_int(k, 0) + (-int(amount) if revert else int(amount)))


def dividend_inflow_get(epoch: int) -> int:
    """Total dividend inflow credited during `epoch` (0 if none)."""
    return meta_get_int(f"divinflow:{int(epoch)}", 0)


# --- Shielded-pool UNSHIELD nullifiers: each (addr, nonce) unshield exit is claimable on L1 exactly once ---
def shield_nullifier_exists(addr: str, nonce: str) -> bool:
    """True if the (addr, nonce) unshield exit was already claimed (double-claim replay guard)."""
    return meta_get_int(f"shieldnull:{addr}:{nonce}", 0) == 1


def shield_nullifier_put(addr: str, nonce: str):
    """Burn the (addr, nonce) unshield nullifier (apply-side, atomic with the exit)."""
    meta_set_int(f"shieldnull:{addr}:{nonce}", 1)


def shield_nullifier_del(addr: str, nonce: str):
    """Revert shield_nullifier_put exactly (rollback un-burns the nullifier)."""
    meta_del(f"shieldnull:{addr}:{nonce}")


# --- Presence-dividend collection nullifiers: each (addr, nonce) dividend claim is spendable on L1 once ---

def dividend_nullifier_exists(addr: str, nonce: str) -> bool:
    """True if the (addr, nonce) dividend claim was already spent (double-claim replay guard)."""
    return meta_get_int(f"divnull:{addr}:{nonce}", 0) == 1


def dividend_nullifier_put(addr: str, nonce: str):
    """Burn the (addr, nonce) dividend-claim nullifier (apply-side, atomic with the payout)."""
    meta_set_int(f"divnull:{addr}:{nonce}", 1)


def dividend_nullifier_del(addr: str, nonce: str):
    """Revert dividend_nullifier_put exactly (rollback un-burns the nullifier)."""
    meta_del(f"divnull:{addr}:{nonce}")


# --- Treasury governance (doc/treasury.md): bonded-validator votes on a treasury_spend proposal, keyed by the
# proposal id `pid`. DUPSORT pid -> validator, one vote per (validator, pid); mirrors the settlement helpers.
def treasury_vote_exists(pid: str, validator: str) -> bool:
    """True if `validator` already voted for proposal `pid` (one-vote-per-validator guard)."""
    return meta_get_int(f"tvote:{pid}:{validator}", 0) == 1


def treasury_vote_put(pid: str, validator: str, weight: int):
    """Record a bonded validator's approval vote for treasury proposal `pid`, with the ACTIVATED vote weight
    SNAPSHOTTED at vote time. treasury_justified sums these stored weights, so a validator that tops up its
    bond AFTER voting cannot inflate its approval (the anti-flash-capture guarantee)."""
    def _do(txn):
        txn.put(pid.encode(), validator.encode(), db=_dbs()["treasury_votes"], dupdata=True)
    _write(_do)
    meta_set_int(f"tvote:{pid}:{validator}", 1)
    meta_set_int(f"tvw:{pid}:{validator}", int(weight))


def treasury_vote_del(pid: str, validator: str):
    """Revert treasury_vote_put exactly (rollback): delete the DUPSORT row + the uniqueness + weight markers."""
    def _do(txn):
        txn.delete(pid.encode(), validator.encode(), db=_dbs()["treasury_votes"])
    _write(_do)
    meta_del(f"tvote:{pid}:{validator}")
    meta_del(f"tvw:{pid}:{validator}")


def treasury_vote_weight(pid: str, validator: str) -> int:
    """The ACTIVATED weight `validator` had when it voted for `pid` (snapshot; 0 if it wasn't activated then).
    A withdrawn / 'no' vote stores weight 0, so treasury_justified (which sums these) simply excludes it."""
    return meta_get_int(f"tvw:{pid}:{validator}", 0)


# A vote can be CHANGED/WITHDRAWN by re-voting (it overwrites). To revert that overwrite exactly, we stash the
# PRIOR (existed?, weight) keyed by the overwriting tx's txid, and restore it on rollback.
def treasury_vote_prev_put(txid: str, existed: bool, weight: int):
    """Stash the PRIOR vote state (existed?, snapshotted weight) under the overwriting vote-tx's txid,
    so rolling back a re-vote restores exactly what it replaced."""
    meta_set_int(f"tvprevE:{txid}", 1 if existed else 0)
    meta_set_int(f"tvprevW:{txid}", int(weight))


def treasury_vote_prev_get(txid: str):
    """The stashed prior vote state for txid as (existed: bool, weight: int); (False, 0) if no record."""
    return (meta_get_int(f"tvprevE:{txid}", 0) == 1, meta_get_int(f"tvprevW:{txid}", 0))


def treasury_vote_prev_del(txid: str):
    """Drop the stashed prior-vote record for txid (consumed on rollback)."""
    meta_del(f"tvprevE:{txid}"); meta_del(f"tvprevW:{txid}")


def treasury_voters(pid: str):
    """List of validator addresses that have voted to approve proposal `pid`, DUPSORT order."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["treasury_votes"]) as cur:
            if cur.set_key(pid.encode()):
                for v in cur.iternext_dup(keys=False, values=True):
                    out.append(v.decode())
        return out
    return _read(_do)


# --- executed-proposal nullifier: a pid pays out AT MOST ONCE (revert-safe, mirror of dividend_nullifier) ---
def treasury_executed_exists(pid: str) -> bool:
    """True if proposal `pid` already paid out (the at-most-once execution guard)."""
    return meta_get_int(f"tspend:{pid}", 0) == 1


def treasury_executed_put(pid: str):
    """Burn the executed-proposal nullifier for `pid` (apply-side, atomic with the payout)."""
    meta_set_int(f"tspend:{pid}", 1)


def treasury_executed_del(pid: str):
    """Revert treasury_executed_put exactly (rollback re-arms the proposal)."""
    meta_del(f"tspend:{pid}")


# --- anti-hoard self-burn: amount burned at a period-boundary block, stored so rollback restores it exactly ---
def treasury_burn_get(height: int) -> int:
    """Amount self-burned at boundary block `height` (0 if none) — read by rollback to re-credit exactly."""
    return meta_get_int(f"tburn:{height}", 0)


def treasury_burn_put(height: int, amount: int):
    """Record the anti-hoard amount burned at `height` (apply-side revert record)."""
    meta_set_int(f"tburn:{height}", int(amount))


def treasury_burn_del(height: int):
    """Drop the burn record for `height` (rollback, after the amount is restored)."""
    meta_del(f"tburn:{height}")


# --- proposal metadata index (NON-consensus, NOT in the state root): the spend content per pid, so the Quorum
# tab can list proposals. Written first-writer-wins on the first vote for a pid; a purely local display aid. ---
def treasury_proposal_put(pid: str, spend: dict):
    """INSERT-OR-IGNORE the spend content for `pid` (first vote wins) — display metadata for the
    Quorum tab; votes/weights/execution stay in the consensus helpers above."""
    def _do(txn):
        if txn.get(pid.encode(), db=_dbs()["treasury_proposals"]) is None:
            txn.put(pid.encode(), _pack(dict(spend)), db=_dbs()["treasury_proposals"])
    _write(_do)


def treasury_proposals_all():
    """All (pid, spend_doc) proposal-metadata rows in key order (Quorum tab listing)."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["treasury_proposals"]) as cur:
            for k, v in cur:
                out.append((k.decode(), _unpack(v)))
        return out
    return _read(_do)


# --- RANDAO commit-reveal (#7): one commit per (sender, target_epoch) + revealed secrets per epoch ---

def _commit_key(sender: str, target_epoch: int) -> bytes:
    """commits key "sender|target_epoch" — exactly one commitment slot per (sender, epoch)."""
    return f"{sender}|{int(target_epoch)}".encode()


def commit_get(sender: str, target_epoch: int):
    """The commitment a bonded sender published for target_epoch (None if none)."""
    def _do(txn):
        v = txn.get(_commit_key(sender, target_epoch), db=_dbs()["commits"])
        return v.decode() if v is not None else None
    return _read(_do)


def commit_put(sender: str, target_epoch: int, commitment: str):
    """Store sender's RANDAO commitment for target_epoch (apply-side; revert via commit_del)."""
    def _do(txn):
        txn.put(_commit_key(sender, target_epoch), commitment.encode(), db=_dbs()["commits"])
    _write(_do)


def commit_del(sender: str, target_epoch: int):
    """Revert commit_put exactly (rollback deletes the commitment slot)."""
    def _do(txn):
        txn.delete(_commit_key(sender, target_epoch), db=_dbs()["commits"])
    _write(_do)


def reveal_put(target_epoch: int, secret: str):
    """Record a revealed secret seeding target_epoch's beacon (DUPSORT auto-dedups identical secrets)."""
    def _do(txn):
        txn.put(be8(target_epoch), secret.encode(), db=_dbs()["reveals"], dupdata=True)
    _write(_do)


def reveal_del(target_epoch: int, secret: str):
    """Revert reveal_put exactly (rollback deletes the precise secret dup)."""
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
    """Create-or-replace the single pending unbond for `address` (unbond apply; rollback of a
    withdraw re-puts the doc it consumed)."""
    def _do(txn):
        txn.put(address.encode(), _pack({"amount": int(amount), "release_block": int(release_block)}),
                db=_dbs()["unbonds"])
    _write(_do)


def unbond_del(address: str):
    """Delete the pending unbond (matured withdraw apply, or rollback of the unbond tx)."""
    def _do(txn):
        txn.delete(address.encode(), db=_dbs()["unbonds"])
    _write(_do)


# --- bonded producer RAMP: stake-weighted bond age (epoch) per address. Absent => 0 (fully aged: existing
# and genesis-seeded stakes are full-weight; only a NEW bond via the bond tx sets a recent epoch and ramps).
def bond_since_get(address: str) -> int:
    """Bond-age epoch for `address`, defaulting the unset case to 0 (== fully aged, full weight).
    Use bond_since_get_raw when 'unset' must stay distinguishable (exact revert)."""
    def _do(txn):
        raw = txn.get(address.encode(), db=_dbs()["bond_since"])
        return un_be8(raw) if raw is not None else 0
    return _read(_do)


def bond_since_get_raw(address: str):
    """The stored bond-age epoch, or None if unset (needed to make revert exact — restore vs delete)."""
    def _do(txn):
        raw = txn.get(address.encode(), db=_dbs()["bond_since"])
        return un_be8(raw) if raw is not None else None
    return _read(_do)


def bond_since_many(addresses):
    """Batch-read {address: bond_since_epoch or None} in ONE read txn — used by get_bonded_registry so
    building the producer registry stays a single scan. None (unset) means a GENESIS-seeded or pre-existing
    stake, which the ramp treats as fully aged (full weight); only a bond TX sets a concrete epoch to ramp."""
    def _do(txn):
        db = _dbs()["bond_since"]
        out = {}
        for a in addresses:
            raw = txn.get(a.encode(), db=db)
            out[a] = un_be8(raw) if raw is not None else None
        return out
    return _read(_do)


def bond_since_put(address: str, epoch: int):
    """Set the bond-age epoch (a bond tx starts/refreshes the stake-weight ramp at its epoch)."""
    def _do(txn):
        txn.put(address.encode(), be8(int(epoch)), db=_dbs()["bond_since"])
    _write(_do)


def bond_since_del(address: str):
    """Delete the bond-age record, returning the address to the unset (fully aged) default —
    the exact revert when bond_since_revert_pop says there was no prior value."""
    def _do(txn):
        txn.delete(address.encode(), db=_dbs()["bond_since"])
    _write(_do)


def bond_since_revert_put(txid: str, prev):
    """Store the bond_since value that existed BEFORE a bond tx (prev=None => was unset), keyed by txid, so a
    rollback restores it exactly. prev is packed with msgpack so None survives round-trip."""
    def _do(txn):
        txn.put(txid.encode(), _pack(prev), db=_dbs()["bond_since_revert"])
    _write(_do)


def bond_since_revert_pop(txid: str):
    """Return the stored prior bond_since for txid (None if unset/missing) and delete the record."""
    def _do(txn):
        raw = txn.get(txid.encode(), db=_dbs()["bond_since_revert"])
        if raw is None:
            return None
        txn.delete(txid.encode(), db=_dbs()["bond_since_revert"])
        return _unpack(raw)
    return _write(_do)


# --- HTLC store (cross-chain atomic swaps): htlc_id -> {sender,claimant,amount,hashlock,expiry,status,...} ---
# One doc per lock, keyed by the lock tx's txid. Mutated in place by claim/refund (status open->claimed/
# refunded), which is revert-symmetric: the doc is self-describing so rollback restores the prior status.
def htlc_get(htlc_id: str):
    """The HTLC doc for `htlc_id` (the lock tx's txid), or None if no such lock."""
    def _do(txn):
        raw = txn.get(htlc_id.encode(), db=_dbs()["htlcs"])
        return _unpack(raw) if raw is not None else None
    return _read(_do)


def htlc_put(htlc_id: str, doc: dict):
    """Create-or-replace the HTLC doc (lock apply, claim/refund status flips, and their exact reverts —
    the self-describing doc carries the prior status)."""
    def _do(txn):
        txn.put(htlc_id.encode(), _pack(doc), db=_dbs()["htlcs"])
    _write(_do)


def htlc_del(htlc_id: str):
    """Delete the HTLC doc (rollback of the lock tx removes the lock it created)."""
    def _do(txn):
        txn.delete(htlc_id.encode(), db=_dbs()["htlcs"])
    _write(_do)


def htlc_all():
    """Every HTLC doc {id: doc} (read-only; for the /htlcs explorer + wallet listing). Bounded by the
    number of open swaps, which is small."""
    def _do(txn):
        out = {}
        with txn.cursor(db=_dbs()["htlcs"]) as cur:
            for k, v in cur:
                out[k.decode()] = _unpack(v)
        return out
    return _read(_do)


# --- alias registry (human-readable name -> owner address) ----------------------------------------

def alias_get(name: str):
    """Owner address for alias `name`, or None if unregistered. Deterministic KV read."""
    def _do(txn):
        raw = txn.get(name.encode(), db=_dbs()["aliases"])
        return raw.decode() if raw is not None else None
    return _read(_do)


def alias_put(name: str, owner: str):
    """Map alias `name` -> `owner` (register/transfer apply; rollback re-puts the prior owner —
    alias_ops needs no side record because the tx itself names it)."""
    def _do(txn):
        txn.put(name.encode(), owner.encode(), db=_dbs()["aliases"])
    _write(_do)


def alias_del(name: str):
    """Free alias `name` (unregister apply, or rollback of a register)."""
    def _do(txn):
        txn.delete(name.encode(), db=_dbs()["aliases"])
    _write(_do)


def aliases_of(owner: str):
    """All alias names currently owned by `owner` (explorer/wallet convenience; O(registry) scan)."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["aliases"]) as cur:
            for k, v in cur:
                if v.decode() == owner:
                    out.append(k.decode())
        return out
    return _read(_do)


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
    """Block hash at height `block_number`, or None if unindexed (beacon/FFG anchors resolve through this)."""
    def _do(txn):
        v = txn.get(be8(block_number), db=_dbs()["block_by_num"])
        return v.decode() if v is not None else None
    return _read(_do)



def block_hash_indexed(block_hash: str) -> bool:
    """True if this exact block hash is in the index (idempotency guard for incorporate)."""
    return _read(lambda txn: txn.get(block_hash.encode(), db=_dbs()["block_by_hash"]) is not None)


# --- block-body LOCATORS (segment store, ops/segment_store.py) -------------------------------------
# hash(hex utf8) -> ">IQI" (segment, offset, record_len) in the NODE-LOCAL `block_loc` sub-DB
# (excluded from snapshots — see _LOCAL_DBS). Per-segment LIVE-locator counters live in the SAME
# sub-DB under b"\x00seg:<n>" keys (the \x00 prefix can never collide with a hex-hash key) so a
# locator put/del and its counter move commit in ONE txn — rolling-mode GC deletes a segment file
# exactly when its live count reaches zero.

_LOC = struct.Struct(">IQI")


def _seg_key(seg: int) -> bytes:
    return b"\x00seg:" + be8(seg)


def _seg_adjust(txn, seg: int, delta: int):
    db = _dbs()["block_loc"]
    k = _seg_key(seg)
    raw = txn.get(k, db=db)
    n = (un_be8(raw) if raw is not None else 0) + delta
    if n > 0:
        txn.put(k, be8(n), db=db)
    else:
        txn.delete(k, db=db)


def block_loc_put(block_hash: str, seg: int, offset: int, length: int):
    """Point a block hash at its segment record (last-write-wins, mirroring the old file overwrite).
    Maintains the per-segment live counters atomically (old segment --, new segment ++)."""
    def _do(txn):
        db = _dbs()["block_loc"]
        key = block_hash.encode()
        old = txn.get(key, db=db)
        if old is not None:
            old_seg, _o, _l = _LOC.unpack(old)
            _seg_adjust(txn, old_seg, -1)
        txn.put(key, _LOC.pack(seg, offset, length), db=db)
        _seg_adjust(txn, seg, +1)
    _write(_do)


def block_loc_get(block_hash: str):
    """(segment, offset, record_len) for a block body, or None (absent/pruned)."""
    def _do(txn):
        raw = txn.get(block_hash.encode(), db=_dbs()["block_loc"])
        return _LOC.unpack(raw) if raw is not None else None
    return _read(_do)


def block_loc_del(block_hash: str) -> bool:
    """Unreference a block body (rollback / rolling-mode prune) — joins the caller's write txn, so
    a rollback abort restores the locator (STRICTLY better than the old best-effort file unlink).
    The segment bytes become inert garbage; whole-segment GC reclaims them. True if it existed."""
    def _do(txn):
        db = _dbs()["block_loc"]
        key = block_hash.encode()
        raw = txn.get(key, db=db)
        if raw is None:
            return False
        seg, _o, _l = _LOC.unpack(raw)
        txn.delete(key, db=db)
        _seg_adjust(txn, seg, -1)
        return True
    return _write(_do)


def seg_live_counts() -> dict:
    """{segment: live locator count} — rolling-mode GC deletes segment files whose count is gone."""
    def _do(txn):
        out = {}
        with txn.cursor(db=_dbs()["block_loc"]) as cur:
            if cur.set_range(b"\x00seg:"):
                for k, v in cur:
                    if not k.startswith(b"\x00seg:"):
                        break
                    out[un_be8(k[len(b"\x00seg:"):])] = un_be8(v)
        return out
    return _read(_do)


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


def index_drop_above(block_number: int) -> int:
    """Purge every HISTORY-index row recorded ABOVE `block_number`: tx primary, both tx DUPSORT
    secondaries, and both block-number indexes. RE-ANCHOR REPAIR: a snapshot re-import resets chain
    state to the checkpoint but (by design) does not ship history indexes — so rows this node wrote on
    its own ABANDONED fork above the checkpoint survive, and any tx the canonical chain re-mines then
    trips the at-most-once gate ("Block replays already-mined tx") on every tail block: a permanent
    sync/production wedge (2026-07-16). One write txn; returns rows removed."""
    def _do(txn):
        removed = 0
        with txn.cursor(db=_dbs()["tx"]) as cur:
            ok = cur.first()
            while ok:
                if _unpack(cur.value()).get("block_number", 0) > block_number:
                    ok = cur.delete()          # delete positions the cursor on the NEXT row
                    removed += 1
                else:
                    ok = cur.next()
        for name in ("tx_by_sender", "tx_by_recipient"):
            with txn.cursor(db=_dbs()[name]) as cur:
                ok = cur.first()
                while ok:
                    bn, _txid = _split_dup_tx_value(cur.value())
                    if bn > block_number:
                        ok = cur.delete()
                        removed += 1
                    else:
                        ok = cur.next()
        with txn.cursor(db=_dbs()["block_by_num"]) as cur:
            ok = cur.first()
            while ok:
                if un_be8(cur.key()) > block_number:
                    txn.delete(bytes(cur.value()), db=_dbs()["block_by_hash"])
                    ok = cur.delete()
                    removed += 1
                else:
                    ok = cur.next()
        return removed
    return _write(_do)


def tx_get(txid: str):
    """Primary tx-index doc {block_number, sender, recipient} for txid, or None — locates the block
    that carries the tx (get_transaction then reads the full tx from the block body)."""
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


def msgkey_revert_put(txid: str, prev_value):
    """MSGKEY (revert record): store the EXACT inverse of a msgkey update — the sender's PREVIOUS kem_pub
    (hex str) or None if it had none — keyed by txid, plain KV. Rollback reads this to restore kem_pub
    byte-identically. A record is ALWAYS written on apply (even when prev is None) so pop can distinguish
    'no prior key' (delete on revert) from 'no record' (legacy / double-revert guard)."""
    def _do(txn):
        txn.put(txid.encode(), _pack([prev_value]), db=_dbs()["msgkey_revert"])
    _write(_do)


def msgkey_revert_pop(txid: str):
    """Read + DELETE the msgkey revert record for txid. Returns (True, prev_value) where prev_value is the
    previous kem_pub hex str or None; returns (False, None) if no record exists. Runs in the active txn."""
    def _do(txn):
        key = txid.encode()
        raw = txn.get(key, db=_dbs()["msgkey_revert"])
        if raw is None:
            return (False, None)
        txn.delete(key, db=_dbs()["msgkey_revert"])
        (prev,) = _unpack(raw)
        return (True, prev)
    return _write(_do)


# --- maintenance helpers (prune) ------------------------------------------------------------------



def drop_tx_index():
    """Empty all three tx sub-DBs (reindex rebuild)."""
    def _do(txn):
        for name in ("tx", "tx_by_sender", "tx_by_recipient"):
            txn.drop(_dbs()[name], delete=False)
    _write(_do)


def iter_db_pairs(name):
    """Yield every (key_bytes, value_bytes) of sub-DB `name` in LMDB sorted order (DUPSORT yields each dup).
    Used to build a complete, canonical state snapshot."""
    env = get_env()
    db = _dbs()[name]
    with env.begin() as txn:
        with txn.cursor(db=db) as cur:
            for k, v in cur:
                yield bytes(k), bytes(v)


def restore_snapshot_state(triples, txn=None):
    """Wipe every SNAPSHOT_DBS sub-DB and repopulate from (db_name, key_bytes, value_bytes) triples — the
    snapshot-import primitive. DUPSORT dbs get dupdata puts. Runs inside the caller's write txn (atomic)."""
    dup = set(_DUP_DBS)
    def _do(t):
        for name in SNAPSHOT_DBS:
            t.drop(_dbs()[name], delete=False)     # empty, keep the handle
        for name, key, value in triples:
            t.put(key, value, db=_dbs()[name], dupdata=(name in dup))
    if txn is not None:
        _do(txn)
    else:
        _write(_do)


# --- idle-account GC support (ops/gc_ops.py — CONSENSUS sweeps, NODE-LOCAL revert records) ---------

def account_raw_get(address: str):
    """The FULL normalized account doc including schemaless extras (public_key, kem_pub, ...), or
    None if absent — the GC eligibility check must see extras, which get_account also passes through
    but this makes the None-vs-empty distinction explicit."""
    def _do(txn):
        raw = txn.get(address.encode(), db=_dbs()["accounts"])
        return _normalize(_unpack(raw)) if raw is not None else None
    return _read(_do)


def account_raw_put(address: str, body: dict):
    """Restore a GC'd account doc byte-identically (gc revert path)."""
    def _do(txn):
        txn.put(address.encode(), _pack(_normalize(body)), db=_dbs()["accounts"])
    _write(_do)


def account_del(address: str) -> bool:
    """Delete an account doc (idle-GC apply path; joins the block's write txn). True if it existed."""
    def _do(txn):
        return txn.delete(address.encode(), db=_dbs()["accounts"])
    return _write(_do)


def recert_bucket_addresses(epoch: int) -> list:
    """All addresses with a recert recorded AT `epoch`, in LMDB dup order (sorted -> deterministic
    on every node). The idle-GC candidate enumerator: an idle address's LATEST recert sits in some
    old bucket, so scanning each bucket exactly once (watermarked) visits every candidate."""
    def _do(txn):
        out = []
        with txn.cursor(db=_dbs()["recert_by_epoch"]) as cur:
            if cur.set_key(be8(int(epoch))):
                for v in cur.iternext_dup(keys=False, values=True):
                    out.append(v.decode())
        return out
    return _read(_do)


def recert_bucket_del(epoch: int) -> list:
    """Delete the WHOLE recert bucket at `epoch` from BOTH indexes (row-retention sweep). Returns
    the deleted (address, epoch) pairs for the gc revert record."""
    def _do(txn):
        pairs = []
        with txn.cursor(db=_dbs()["recert_by_epoch"]) as cur:
            if cur.set_key(be8(int(epoch))):
                for v in cur.iternext_dup(keys=False, values=True):
                    pairs.append(v.decode())
        for addr in pairs:
            txn.delete(addr.encode(), be8(int(epoch)), db=_dbs()["recerts"])
            txn.delete(be8(int(epoch)), addr.encode(), db=_dbs()["recert_by_epoch"])
        return [(addr, int(epoch)) for addr in pairs]
    return _write(_do)


def gc_revert_put(height: int, record: dict):
    """Persist the idle-GC revert record for the boundary block at `height` (NODE-LOCAL; commits
    inside the block's write txn, so it exists exactly iff the sweep's mutations committed)."""
    def _do(txn):
        txn.put(be8(int(height)), _pack(record), db=_dbs()["gc_revert"])
    _write(_do)


def gc_revert_pop(height: int):
    """Fetch + delete the revert record for `height` (rollback path), or None if the sweep at that
    height was a complete no-op (then the revert is too)."""
    def _do(txn):
        key = be8(int(height))
        raw = txn.get(key, db=_dbs()["gc_revert"])
        if raw is None:
            return None
        txn.delete(key, db=_dbs()["gc_revert"])
        return _unpack(raw)
    return _write(_do)


def gc_revert_prune(below_height: int) -> int:
    """Drop revert records below the finalized height — rollback can never reach them (NODE-LOCAL,
    so this needs no cross-node determinism). Returns rows dropped."""
    def _do(txn):
        n = 0
        with txn.cursor(db=_dbs()["gc_revert"]) as cur:
            if cur.first():
                while un_be8(cur.key()) < below_height:
                    if not cur.delete():
                        break
                    n += 1
                    if not cur.first():
                        break
        return n
    return _write(_do)
