# Protocol constants reference (`protocol.py`)

Single source of truth for all consensus-critical protocol/economic/mining constants. Every
node must agree on these. `protocol.py` is a leaf module (imports only `hashing`) so anything
can import it without a cycle.

## Identity & denomination

| Constant | Value | Meaning |
|----------|-------|---------|
| `CHAIN_ID` | `"alphanet-6"` | Bound into every signed tx + block body (anti cross-chain replay, M3); changes at every reroll |
| `DENOMINATION` | `10_000_000_000` | 1 NADO in raw units (`to_readable_amount` divides by this) |
| `GENESIS_TIMESTAMP` | `1784257440` | Genesis block timestamp (alphanet-6) |

## Treasury & reserved addresses

| Constant | Value | Meaning |
|----------|-------|---------|
| `GENESIS_ADDRESS` | `ndo27f2870…9384ea` | The genesis producer address; derived `_GENESIS_BODY + blake2b_hash(_GENESIS_BODY, size=2)` |
| `TREASURY_ADDRESS` | `"treasury"` | **Keyless** reserved account (no key, no founder, ≠ genesis address) that accrues the 10% treasury tax |
| `TREASURY_GENESIS` | `0` | **No premine** — genesis mints zero coins; every coin was a block reward |
| `RESERVED_RECIPIENTS` | 28 names — `bond`, `unbond`, `withdraw`, `register`, `slash`, `attest`, `commit`, `reveal`, `duty`, `alias`, `blob`, `settle`, `bridge`(+`_withdraw`), `dividend`(+`_withdraw`), `htlc`(+`_lock`/`_claim`/`_refund`), `shield`/`unshield`, `treasury`(+`_vote`/`_execute`), `msgkey`, `xmsg`, `faucet` | Keyless protocol pseudo-recipients (never a sender) |

## Reward & fees

| Constant | Value | Meaning |
|----------|-------|---------|
| `TREASURY_BPS` / `BPS_DENOM` | `1000` / `10000` | Treasury share = 10.00% of each block reward |
| `REWARD_WINDOW` | `100` | Rollback/prune safety window (the reward is bond-elastic, NOT fee-averaged) |
| `BASE_SUBSIDY` | `1_000_000_000` (0.1 NADO) | Flat base subsidy; `reward = BASE_SUBSIDY·m(r)`, so this is the **max**/block (no `REWARD_CAP` — removed). See bond-elastic-emission.md |
| `MIN_TX_FEE` | `1000` raw | Deterministic consensus minimum fee (anti-spam) |
| `split_block_reward(R)` | fn | Returns `(producer_cut, treasury_cut)` summing to exactly `R` (90/10) |

## Mining (PROVISIONAL — simulate before locking)

These gate the S4 bonded-mining mechanism (live on alphanet-6).

| Constant | Value | Meaning |
|----------|-------|---------|
| `B_MIN` | `100_000_000_000` (10 NADO) | Capital per selection share / minimum bond to be eligible |
| `BOND_CAP` | `10_000_000_000_000` (1,000 NADO) | Max effective bond per identity (variance cap) |
| `MAX_SHARES` | `100` (`BOND_CAP // B_MIN`) | Max selection shares one identity can hold (anti-whale) |
| `BOND_UNLOCK_DELAY` | `1440` blocks | Lock/cooldown after an unbond (anti-grind) |
| `EPOCH_LENGTH` | `60` slots | Blocks per RANDAO beacon epoch |
| `POSW_LEASE_EPOCHS` | `240` (~1 day) | OPEN-lane presence lease — an identity re-proves PoSW within this window to stay eligible |
| `FIDELITY_CAP` | `30` | Fidelity score ceiling; weight ramps to full at this value |
| `FIDELITY_GAIN` | `1` | Fidelity gained per continuous recert (a lapse RESETS the streak; there is no `FIDELITY_DECAY` constant) |

## Block header fields (set in `construct_block`)

Beyond the legacy fields, every block now carries:
- `cumulative_fees` — running total of all fees up to and including this block (drives the
  reward; lets full **and** pruned/snapshot nodes recompute it from headers).
- `chain_id` — the chain identifier (M3).

## Account state (the `accounts` KV doc)

State is a schemaless **LMDB** key-value store (`ops/kv_ops.py`), not SQLite. The `accounts`
sub-DB maps `address` → a **schemaless msgpack document** `{balance, produced, bonded, registered,
fidelity, …}` (no columns / no DDL — adding a field needs no migration). Totals live in the
`totals` sub-DB as `{produced, fees}`. (No `burned` — removed.) See
[storage-kv-migration.md](storage-kv-migration.md) for the full sub-DB schema.
