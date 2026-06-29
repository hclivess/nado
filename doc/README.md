# NADO relaunch documentation

This `doc/` set describes the NADO **relaunch** — a coordinated set of consensus, economic,
storage and determinism changes implemented directly as the new genesis behaviour (there is
no live network, so there are **no fork-activation gates**; the code *is* the new rules).

It also records the multi-agent **security review** that motivated much of this work and the
**SQLite-replacement** decision.

> Units: **1 NADO = 10,000,000,000 raw** (`DENOMINATION = 1e10`). All on-chain amounts are
> integers in raw units. `to_readable_amount` divides by `1e10`.

## Documents

| Doc | Contents |
|-----|----------|
| [economics.md](economics.md) | No premine, the treasury (= genesis address), fee-weighted elastic reward, the 90/10 split, fees, supply accounting |
| [mining.md](mining.md) | Bonded-registry mining (the open/mobile/botnet-safe redesign): bond/unbond, split-neutral selection, RANDAO beacon, fidelity, the browser miner — and exactly what is implemented vs. pending |
| [storage.md](storage.md) | The consolidated `index.db`, atomic `incorporate_block`, per-thread connections, the transaction context manager, snapshot sync, the "stuck node" fixes, and why we keep SQLite |
| [determinism-and-chain-id.md](determinism-and-chain-id.md) | Canonical hashing (audit M14), chain-id binding (M3), txid/signature scheme, address derivation, browser reproducibility |
| [security-review.md](security-review.md) | The reviewed findings, what this relaunch fixes, what remains open, and the DB recommendation |
| [protocol-constants.md](protocol-constants.md) | Reference table of every constant in `protocol.py` (values, meaning, which are provisional) |

## Implementation status (at a glance)

| Stage | Scope | Status |
|------|-------|--------|
| **S1** | Canonical hashing (M14), chain-id (M3), `protocol.py`, min-fee | ✅ implemented & unit-tested |
| **S2a** | "Stuck node" disk-I/O fixes (per-thread conn, atomic writes, no spin loops) | ✅ implemented & unit-tested |
| **S2b** | Consolidate to one `index.db`; crash-atomic `incorporate_block`/rollback | ✅ implemented & unit-tested |
| **S3** | No premine → treasury; fee-weighted elastic reward; 90/10 split; remove compat gates | ✅ implemented & unit-tested |
| **(burn)** | Remove burn mechanics entirely | ✅ implemented & unit-tested |
| **S4.1** | Bond/unbond transactions + `bonded` stake state | ✅ implemented & unit-tested |
| **S4.2** | Split-neutral selection math + commit-reveal RANDAO beacon (`ops/mining_ops.py`) | ✅ implemented & unit-tested |
| **S4.3** | Wire bonded selection + beacon into live block production/verification; fail-closed authorship; heartbeats/fidelity; consensus-pool reweight; faucet | ⏳ **not yet implemented** — needs a multi-node testnet |
| **S4b** | Browser light-miner reference client | ⏳ **not yet implemented** |

"Unit-tested" = verified by `tests/test_s*.py` under a venv + temporary `$HOME` (no live
network). The S4.3 integration and the browser client are deliberately **not** written yet
because they are networked/consensus-live and require a multi-node testnet to trust.

## Running the tests

System `pip` is PEP-668 locked, so use a venv with the **minimal** deps (the full
`requirements.txt` includes heavy build-only packages — `pandas`, `nuitka`,
`customtkinter` — that are not needed and may fail to build):

```bash
python3 -m venv venv
./venv/bin/pip install cryptography tornado aiohttp msgpack requests coloredlogs ordered-set zstandard psutil pympler
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
- `ops/sqlite_ops.py` — the per-thread connection pool + `transaction()` context manager.
- `loops/core_loop.py` — the node state machine; `incorporate_block`/`verify_block`.
- `rollback.py`, `genesis.py`, `reindex_fast.py`, `ops/snapshot_ops.py`.
