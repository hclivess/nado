# Storage, crash-safety, and the "stuck node" fixes

## Current design: a schemaless LMDB key-value index

Derived state lives in a **single schemaless, memory-mapped, ACID key-value store (LMDB)** —
`ops/kv_ops.py` — which **replaced** the prior SQLite index (`index.db` / the old
`ops/sqlite_ops.py` connection pool, both removed). Account/state records are **schemaless
msgpack documents with no columns**, so adding a field — as the relaunch did with
`registered` / `fidelity` / `public_key` — needs **no DDL and no migration**. The engine choice,
the full sub-DB schema, and the migration rationale live in
**[storage-kv-migration.md](storage-kv-migration.md)**; this document is the short current-state
summary plus the crash-safety properties that carried over.

One LMDB environment (`index/state/`) holds these named sub-DBs:

| sub-DB | key | value | flags | replaces (old SQLite) |
|--------|-----|-------|-------|------------------------|
| `accounts` | `address` (utf8) | `msgpack({balance, produced, bonded, registered, fidelity, …})` | — | `acc_index` |
| `totals` | `b"totals"` | `msgpack({produced, fees})` | — | `totals_index` |
| `block_by_num` | `block_number` (8B BE) | `block_hash` | — | `block_index` (n→h) |
| `block_by_hash` | `block_hash` | `block_number` (8B BE) | — | `block_index` (h→n) |
| `tx` | `txid` | `msgpack({block_number, sender, recipient})` | — | `tx_index` |
| `tx_by_sender` | `sender` | `block_number(8B BE)‖txid` | `DUPSORT` | sender history |
| `tx_by_recipient` | `recipient` | `block_number(8B BE)‖txid` | `DUPSORT` | recipient history |
| `recerts` | `address` (utf8) | `epoch` (8B BE) | `DUPSORT` | (new — presence lease) |
| `recert_by_epoch` | `epoch` (8B BE) | `address` (utf8) | `DUPSORT` | (new — present-set scan) |
| `meta` | `key` (utf8) | `msgpack(int)` (e.g. `finalized_height`) | — | (new) |

**Presence is a PoSW recert lease, not a heartbeat.** The old `heartbeats` sub-DB
(`epoch → address`, DUPSORT) and the per-epoch heartbeat tx are **gone** (superseded). Presence is
now a renewable lease: a `register` tx carrying a fresh sequential PoSW grants OPEN-lane eligibility
for `POSW_LEASE_EPOCHS` (~1 day), recorded in **two** DUPSORT stores — `recerts` (`address → epoch`,
for `recert_latest`) and `recert_by_epoch` (`epoch → address`, so `get_open_registry` range-scans the
currently-leased set). To stay present a node renews (another PoSW recert) each period, else it lapses
out of the open registry. Continuity fidelity is measured over consecutive recerts (see
`doc/presence-dividend.md`).

**Other sub-DBs added since the initial cut-over** (same atomicity guarantee — every one is written
inside the single per-block `write_txn`): `attestations` + `commits` + `reveals` (FFG / RANDAO),
`settlements` (execution-layer settle), `aliases` (human-readable names), `unbonds` (bond-unlock
delay), `hb_revert` (fidelity revert records), `htlcs` (cross-chain HTLC swaps —
`doc/htlc.md`), and `bond_since` + `bond_since_revert` (the bonded-producer ramp —
`doc/takeover-resistance.md`).

8-byte big-endian integer keys preserve numeric order under LMDB's bytewise key sort, so range
scans (`block_by_num` iteration, the `recert_by_epoch` present-set window, `tx_by_*` ordered-by-block
history) are deterministic and identical across nodes — required because `get_open_registry` and
tx history feed consensus selection. `DUPSORT` gives auto-deduped multi-value keys, so one
recert per `(address, epoch)` is enforced for free.

(Block **bodies** live in append-only **segment files** — `blocks/seg-<n>.dat`, ~64 MB each,
`zstd(codec)` records addressed by a `hash -> (segment, offset, len)` locator in the node-LOCAL
`block_loc` sub-DB (excluded from snapshots; see `ops/segment_store.py`). Records are crc-guarded
and self-describing (they carry their block hash), so the locator index stays derived/rebuildable.
Crash safety mirrors the old per-file temp+fsync+rename: a record is appended + fsynced BEFORE its
locator commits, torn tails are truncated at startup, and deletion is by UNREFERENCING inside the
caller's write txn — whole segments are reclaimed once empty. Consensus hashing is over canonical
JSON, never the stored bytes, so none of this touches consensus.)

## Crash-atomic block application (audit LO-1 / CO-4)

`incorporate_block` (`loops/core_loop.py`) wraps **all** of a block's mutations — the tx index,
balance / treasury / produced / totals mutations, the presence recert record (and any of the other
sub-DB writes above), and the `block_by_*`
"applied" marker — in **one** `env.begin(write=True)` transaction (`kv_ops.write_txn()`,
re-entrant). LMDB is single-writer + copy-on-write, so a crash mid-apply leaves the block
**fully un-applied**, and `block_already_indexed` (the `block_by_hash` marker) lets the replay
re-apply it cleanly — instead of the old behaviour where a crash between balance writes and the
tip update **double-credited** the reward on restart. `rollback_one_block` runs in the same kind
of single write transaction (all reversals atomic), with the tip pointer (`block_ends.dat`)
advanced **after** the commit.

Account field writes go through `account_adjust` — a guarded read-modify-write that refuses to
drive a field below zero (returns `False`, leaves the doc unchanged) — so a bad/mismatched revert
fails **closed** instead of going negative. Because doc encoding is canonicalized (deterministic
field order), every revert returns a document **byte-identical** to its pre-apply state.

## "Stuck node" fixes (S2a)

Every unbounded/blocking disk operation that could wedge the core thread was fixed (these are
independent of the index engine and still apply):

- `set_latest_block_info` / `set_earliest_block_info` → atomic `_update_block_ends`
  (temp file + fsync + `os.replace`). The old write-then-**read-back-and-compare**
  `while not old_hash == new_hash` loop could spin forever; it is gone.
- `save_block` → bounded retries + atomic rename, then **raise** (the old `while True` spun
  forever on a full disk). `update_child_in_latest_block` is no longer a no-sleep spinner.
- `rollback_one_block` → raises `MissingParentError` when the parent block is missing (e.g. a
  snapshot-bootstrapped node rolling back past its checkpoint), and `FinalityViolation` when the
  reorg would cross the enforced finality floor; `core_loop` catches both and resyncs forward.
- Peer files written atomically (`peer_ops._atomic_write_json`) so a crash mid-write can't
  leave a corrupt peer file.

## Snapshot sync

`ops/snapshot_ops.py` lets a joining node download verified account state at a checkpoint and
replay only the short tail. Import is an atomic wholesale replace inside one LMDB write
transaction (`kv_ops.clear_accounts_and_totals` + `put_account` per row + totals), replacing the
old SQLite row-replace. The verified `state_root` (a blake2b Merkle root over the rows) includes
the `bonded` column, so a snapshot commits mining stake too. `reindex_fast.py` rebuilds the KV
index byte-identically from the block files and is the migration / repair path.

## Migration

There is no live network; `reindex_fast.rebuild_from_blocks` wipes the index and rebuilds the KV
store from the block files (mirroring `incorporate_block`: fees-always, the 90/10 split, treasury,
bond/unbond, no burn). The SQLite→LMDB cut-over itself is documented in
[storage-kv-migration.md](storage-kv-migration.md).
