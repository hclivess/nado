# Storage migration: SQLite index → schemaless key-value (MDBX-style)

**Goal:** replace the SQLite index with a *true key-value, no-columns* store so account/state records
are **schemaless documents** — adding a field (as we did with `registered`/`fidelity`) needs **no DDL,
no migration**. Stay embedded, memory-mapped, ACID, and lean (no server) — the "runs on a 386" rule.

## Engine decision: LMDB binding, MDBX model

| | MDBX engine | `mdbxpy` (Python binding) | LMDB (`py-lmdb`) |
|---|---|---|---|
| schemaless KV, embedded, ACID, mmap | ✅ (improved LMDB fork) | — | ✅ (MDBX's predecessor) |
| dynamic map growth | ✅ (real edge for an ever-growing chain) | — | ❌ (fixed `map_size` set upfront) |
| binding maturity | — | ❌ **threw `MDBX_EBADSIGN: memory corruption / double-free` on basic teardown**; sparse docs; inconsistent `DBI.put` vs `cursor.put` | ✅ battle-tested, ubiquitous, clean API |

**Decision: implement on `py-lmdb`.** It is the *same architecture and data model* MDBX provides
(MDBX = libmdbx, a fork of LMDB), with a safe binding. A memory-corrupting binding is unacceptable
under a ledger. `map_size` is the only LMDB wart (set it large, e.g. 16 GiB, and bump if needed);
revisit MDBX's auto-grow if/when a sound native binding exists. **Verified working** for every access
pattern below (account docs + dupsort range scans + dedup), zero errors.

## What does NOT change
- **Block bodies** stay as `zstd(msgpack(block))` files under `blocks/` (already documents).
- **Consensus hashing/serialization** stays `canonical_bytes` (sorted-key JSON) — untouched, so txids,
  signatures, and browser reproducibility are unaffected. The KV store is a *derived, rebuildable index*.

## KV schema (one LMDB env, named sub-DBs)

| sub-DB | key | value | flags | replaces |
|---|---|---|---|---|
| `accounts` | `address` (utf8) | `msgpack({balance, produced, bonded, registered, fidelity, …})` — **schemaless doc, no columns** | — | `acc_index` |
| `totals` | `b"totals"` | `msgpack({produced, fees})` | — | `totals_index` |
| `block_by_num` | `block_number` (8-byte big-endian) | `block_hash` | — | `block_index` (n→h) |
| `block_by_hash` | `block_hash` | `block_number` (8-byte BE) | — | `block_index` (h→n) |
| `tx` | `txid` | `msgpack({block_number, sender, recipient})` | — | `tx_index` (by txid) |
| `tx_by_sender` | `sender` | `block_number(8-byte BE)‖txid` | `DUPSORT` | `idx_sender` |
| `tx_by_recipient` | `recipient` | `block_number(8-byte BE)‖txid` | `DUPSORT` | `idx_recipient` |
| `heartbeats` | `epoch` (8-byte BE) | `address` | `DUPSORT` | `heartbeat_index` |

- **Big-endian integer keys** preserve numeric order for range scans (`block_by_num` iteration,
  `heartbeats` "epoch > E−PRESENCE_WINDOW", `tx_by_*` ordered-by-block history).
- **DUPSORT** gives multi-value keys with sorted, **auto-deduped** dups — so `heartbeats` enforces
  one-per-(address,epoch) for free, and `tx_by_sender` keeps history ordered by block.
- **Account history UNION** (`sender` OR `recipient`, ordered by block): merge the two dupsort cursors.
- **`get_open_registry(epoch)`**: range-scan `heartbeats` for keys `> epoch−PRESENCE_WINDOW`, collect
  addresses, intersect with `accounts` where `registered==1`, attach `fidelity`.

## Atomicity
`incorporate_block` / `rollback_one_block` wrap **all** mutations (account docs, tx index, block index,
totals, heartbeats) in **one** `env.begin(write=True)` transaction → ACID, crash-atomic — directly
replaces the SQLite `transaction()` context (closes the same LO-1/CO-4 window, arguably cleaner since
LMDB is single-writer + copy-on-write).

## Migration steps (consensus-critical — do with testnet validation)
1. New `ops/kv_ops.py`: LMDB env singleton + typed helpers (`get_account`/`put_account`/`del`,
   `index_tx`, `tx_of_account`, `block_num↔hash`, `totals`, `heartbeat_put/del/registry`, a
   `write_txn()` context). Encapsulate key-encoding (BE ints) + msgpack here.
2. Rewrite the SQL call-sites that read/write the index: `account_ops` (acc/totals/registry/register/
   heartbeat/fidelity), `transaction_ops` (tx index + history), `block_ops` (block index, mining_status),
   `genesis.create_indexers` (open the env + sub-DBs instead of DDL), `snapshot_ops` (read/import
   accounts), `reindex*.py`. Delete `sqlite_ops.py`.
3. Keep public function signatures identical so `core_loop`/handlers are largely untouched.
4. **Test:** unit (account doc round-trip + revert symmetry, dupsort heartbeat range, tx history UNION,
   atomic incorporate/rollback), **3-node testnet convergence**, and reindex byte-equivalence vs the
   per-block path.

## Risks to watch
- Secondary-index maintenance must be **exact on revert** (rollback deletes the precise dup written on
  apply) — the dupsort value encoding (`blocknum‖txid`, `address`) makes the delete key unambiguous.
- Iteration order is **deterministic** (LMDB sorts keys/dups) — required since `get_open_registry` and
  history feed consensus selection.
- `map_size` must be provisioned generously; a `MDB_MAP_FULL` mid-block must surface (not corrupt).
