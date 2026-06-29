# Storage, crash-safety, and the "stuck node" fixes

## Decision: keep SQLite, fix how it is used

The multi-agent review's verdict was decisive: the engine is not the bottleneck. At one block
per `block_time` with point-lookup reads and a single writer thread + many readers, WAL-mode
SQLite is exactly the right fit — and it is stdlib (zero-dependency), inspectable with the
`sqlite3` CLI, and runs on a hobbyist box, which matches NADO's ethos. LMDB/RocksDB/DuckDB
would inherit the same architecture work while forfeiting SQL and pure-Python deployability.
So we kept SQLite and fixed the **usage**.

## One consolidated `index.db`

All index tables now live in a single database, `index/index.db`:

| table | columns |
|-------|---------|
| `acc_index` | `address, balance, produced, bonded` (UNIQUE on address) |
| `totals_index` | `produced, fees` (single row) |
| `tx_index` | `txid, block_number, sender, recipient` |
| `block_index` | `block_hash, block_number` |

(Block **bodies** remain one msgpack file per hash under `blocks/`.) Consolidation is what
lets the entire `incorporate_block` mutation commit in **one transaction**.

## Per-thread connections + a transaction context manager

`ops/sqlite_ops.py`:
- `DbHandler` reuses **one connection per (thread, db_file)** via `threading.local`, applying
  the PRAGMAs (`WAL`, `synchronous=NORMAL`, `busy_timeout`, `temp_store=MEMORY`) **once** at
  creation. The old handler opened a new connection and re-ran 4 PRAGMAs on **every** query,
  then closed it — the connect/teardown dominated each tiny lookup and piled onto the write
  lock under load (a real "node gets stuck" contributor). `close()` is now a no-op on the
  shared connection (use `close_thread_connections()` on thread teardown).
- `transaction(db_file)` is a **re-entrant** context manager. Inside it, `_run` defers the
  per-statement commit; the outermost context commits once on success or rolls back on any
  exception. `db_change()` returns `rowcount` for guarded UPDATEs.

## Crash-atomic block application (audit LO-1 / CO-4)

`incorporate_block` (`loops/core_loop.py`):

1. **Files first** (idempotent, safe to redo): `save_block`, then `update_child_in_latest_block`.
2. **One transaction** over *all* state: `index_transactions` (tx index + balances), the 90/10
   reward split, `increase_produced_count`, `index_totals`, and the `block_index` "applied"
   marker (`block_ops.index_block_number`).
3. **Tip pointer last**, *after* the commit: `set_latest_block_info` writes `block_ends.dat`.

So a crash mid-apply leaves the block **un**applied (the `block_index` marker only exists if
the whole transaction committed), and `block_already_indexed` lets the replay re-apply it
cleanly — instead of the old behaviour where a crash between balance writes and the tip update
**double-credited** the reward on restart. `rollback_one_block` is wrapped in the same
transaction (all reversals atomic), with the tip advanced after the commit.

Balance writes are a **single guarded UPDATE** (`change_balance`/`increase_produced_count`/
`change_bonded`): `UPDATE ... SET col = col + ? WHERE address = ? AND col + ? >= 0`, checking
`rowcount == 1`. This removes the old SELECT-then-UPDATE read-modify-write (the ~296× write
amplification + a race) and enforces the non-negative invariant atomically — fail-closed, with
no retry loop that could wedge the single block-processing thread.

## "Stuck node" fixes (S2a)

Every unbounded/blocking disk operation that could wedge the core thread was fixed:

- `set_latest_block_info` / `set_earliest_block_info` → atomic `_update_block_ends`
  (temp file + fsync + `os.replace`). The old write-then-**read-back-and-compare**
  `while not old_hash == new_hash` loop could spin forever; it is gone.
- `save_block` → bounded retries + atomic rename, then **raise** (the old `while True` spun
  forever on a full disk). `update_child_in_latest_block` no longer a no-sleep spinner.
- `rollback_one_block` → raises `MissingParentError` when the parent block is missing (e.g. a
  snapshot-bootstrapped node rolling back past its checkpoint), instead of crashing on
  `False['block_hash']` and then spinning; `core_loop` catches it and triggers a resync.
- Peer files written atomically (`peer_ops._atomic_write_json`) so a crash mid-write can't
  leave a corrupt peer file.

## Snapshot sync

`ops/snapshot_ops.py` lets a joining node download verified account state at a checkpoint and
replay only the short tail. After consolidation, **import is a transactional row-replace** on
`index.db` (`DELETE FROM acc_index; INSERT …; replace totals`) instead of swapping a standalone
`accounts.db` file. The verified `state_root` (a blake2b Merkle root over the rows) now
includes the `bonded` column, so a snapshot commits mining stake too. `reindex_fast.py` rebuilds
the consolidated index byte-identically from the block files and is the migration path.

## Migration

There is no live network; `reindex_fast.rebuild_from_blocks` wipes `index/` and rebuilds the
consolidated `index.db` from the block files (it mirrors `incorporate_block`: fees-always, the
90/10 split, treasury, bond/unbond, no burn). `reindex.py` is the older, slower reference path
(also updated). `GENESIS_CHILD_HASH` in `reindex_fast.py` must be regenerated once the
relaunched genesis + block 1 exist (the old value predates canonical hashing).
