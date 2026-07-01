# NADO relaunch documentation

This `doc/` set describes the NADO **relaunch** — a coordinated set of consensus, economic,
storage and determinism changes implemented directly as the new genesis behaviour (there is
no live network, so there are **no fork-activation gates**; the code *is* the new rules).

It also records the multi-agent **security review** that motivated much of this work and the
**storage migration** from the old SQLite index to a schemaless **LMDB** key-value store.

> Units: **1 NADO = 10,000,000,000 raw** (`DENOMINATION = 1e10`). All on-chain amounts are
> integers in raw units. `to_readable_amount` divides by `1e10`.

## Documents

| Doc | Contents |
|-----|----------|
| [whitepaper.md](whitepaper.md) | **Authoritative overview** — two-lane mining, economics, PQ crypto, LMDB storage, the security model with an explicit implemented-vs-planned split, and the full constants table |
| [economics.md](economics.md) | No premine, the treasury (= genesis address), fee-weighted elastic reward, the 90/10 split, fees, supply accounting |
| [mining.md](mining.md) | Bonded-registry mining (the open/mobile/botnet-safe redesign): bond/unbond, split-neutral selection, RANDAO beacon, fidelity, the browser miner — and exactly what is implemented vs. pending |
| [ip-spoofing-and-sybil.md](ip-spoofing-and-sybil.md) | **Fair distribution** of the open lane: why IP is out of consensus and spoofable, how Sybil skews (but can't enlarge) the free lane, and ranked ideas to tie one share to one real participant — incl. bonded-node sponsorship and the hash-based Proof of Sequential Work (Appendix A) |
| [reward-capture-theorem.md](reward-capture-theorem.md) | **Theorem** — the "one miner takes all the rewards" worst case: capture ≤ `20% + 80%·s`, so a free/Sybil attacker is capped at 20% and total monopoly requires owning ~all the stake. Proof, corollaries, and the five assumptions that hold it |
| [presence-dividend.md](presence-dividend.md) | **Design proposal** — smooth the open lane from a per-block jackpot into a fidelity-weighted *presence dividend*: split the open block reward into a small producer tip + a redistributed pool, accrued off-L1 on the execution layer and withdrawn in aggregate. `O(1)` on L1, Sybil-bounded by fidelity + the 20% cap, no dust bloat |
| [storage.md](storage.md) | The current schemaless **LMDB** key-value index (`ops/kv_ops.py`), atomic `incorporate_block`/rollback, snapshot sync, and the "stuck node" fixes |
| [storage-kv-migration.md](storage-kv-migration.md) | The SQLite → LMDB migration: engine decision (`py-lmdb`), the full sub-DB schema, atomicity, and the cut-over steps |
| [consensus-hardening-plan.md](consensus-hardening-plan.md) | The locked, ordered design for the consensus-security milestones (#15–#18); the first wave is implemented, the rest is planned |
| [determinism-and-chain-id.md](determinism-and-chain-id.md) | Canonical hashing (audit M14), chain-id binding (M3), txid/signature scheme, address derivation, browser reproducibility |
| [security-review.md](security-review.md) | The reviewed findings, what this relaunch fixes, and what remains open (historical audit snapshot) |
| [protocol-constants.md](protocol-constants.md) | Reference table of every constant in `protocol.py` (values, meaning, which are provisional) |

## Implementation status (at a glance)

| Stage | Scope | Status |
|------|-------|--------|
| **S1** | Canonical hashing (M14), chain-id (M3), `protocol.py`, min-fee | ✅ implemented & unit-tested |
| **S2a** | "Stuck node" disk-I/O fixes (per-thread conn, atomic writes, no spin loops) | ✅ implemented & unit-tested |
| **S2b** | Consolidate to one index DB; crash-atomic `incorporate_block`/rollback | ✅ implemented & unit-tested (the index store was later migrated SQLite → LMDB, see #21) |
| **S3** | No premine → treasury; fee-weighted elastic reward; 90/10 split; remove compat gates | ✅ implemented & unit-tested |
| **(burn)** | Remove burn mechanics entirely | ✅ implemented & unit-tested |
| **S4.1** | Bond/unbond transactions + `bonded` stake state | ✅ implemented & unit-tested |
| **S4.2** | Split-neutral selection math + commit-reveal RANDAO beacon (`ops/mining_ops.py`) | ✅ implemented & unit-tested |
| **S4.3 v1** | Bonded `select_producer` + epoch beacon wired into live production/verification; fail-closed authorship; testnet bonding | ✅ **implemented & testnet-validated** (3 nodes produce + converge via bonded mining) |
| **S4b** | Browser light-miner reference client + PySide6 wallet | ✅ implemented (`static/miner.*`, `pyside_wallet.py`) |
| **#21** | Schemaless **LMDB** key-value index replaces the SQLite `index.db` (`ops/kv_ops.py`; `ops/sqlite_ops.py` deleted) | ✅ implemented & testnet-validated (see [storage-kv-migration.md](storage-kv-migration.md)) |
| **#16/#17** | Objective stake-weighted heaviest-chain fork-choice + grind-proof `cumulative_weight` header + enforced finality floor (`FINALITY_DEPTH=30`, `FinalityViolation`) | ✅ implemented & testnet-validated |
| **#18 (partial)** | Fail-loud epoch beacon (silent `GENESIS_BEACON` fallback removed); `/announce_peer` rate-limit | ✅ implemented |
| **#15/#19 (partial)** | Detached **optional** winner block signature (off the hash/validity path); pubkey-once (`public_key` excluded from txid) | ✅ implemented |
| **Remaining hardening** | Equivocation/attestation slashing actions; FFG-lite >2/3-bonded finality; full on-chain commit-reveal RANDAO; broad eclipse hardening (ASN/subnet diversity, multi-seed bootstrap) | ⏳ planned (see [consensus-hardening-plan.md](consensus-hardening-plan.md)) |

"Unit-tested" = verified by `tests/test_s*.py` under a venv + temporary `$HOME` (no live
network). The S4.3 integration and the browser client are deliberately **not** written yet
because they are networked/consensus-live and require a multi-node testnet to trust.

## Running the tests

System `pip` is PEP-668 locked, so use a venv with the **minimal** deps (the full
`requirements.txt` includes heavy build-only packages — `pandas`, `nuitka`,
`customtkinter` — that are not needed and may fail to build):

```bash
python3 -m venv venv
./venv/bin/pip install cryptography tornado aiohttp msgpack requests coloredlogs ordered-set zstandard psutil pympler lmdb
for t in tests/test_s*.py; do ./venv/bin/python "$t"; done
```

Each test file creates its own throwaway `$HOME` and `index/` so it never touches a real node.
`nado.py` is the **server entrypoint** and is intentionally **not import-safe** — don't import
it in unit tests.

## Key source files

- `protocol.py` — single source of truth for all protocol/economic/mining constants + `split_block_reward`.
- `hashing.py` — `canonical_bytes` + the blake2b hash helpers.
- `ops/account_ops.py` — accounts, balances, bonded stake, totals.
- `ops/block_ops.py` — block construction, the fee-weighted reward, indexing, penalty.
- `ops/mining_ops.py` — bonded selection + RANDAO beacon (S4.2).
- `ops/transaction_ops.py` — tx validation, signing, spending checks.
- `ops/kv_ops.py` — the schemaless **LMDB** key-value index: env + named sub-DBs, key/value encoding, and the atomic `write_txn()` context (replaced the deleted `ops/sqlite_ops.py`).
- `loops/core_loop.py` — the node state machine; `incorporate_block`/`verify_block`.
- `rollback.py`, `genesis.py`, `reindex_fast.py`, `ops/snapshot_ops.py`.
