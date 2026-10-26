# Protocol constants reference (`protocol.py`)

Single source of truth for all consensus-critical protocol/economic/mining constants. Every
node must agree on these. `protocol.py` is a leaf module (imports only `hashing`) so anything
can import it without a cycle.

## Identity & denomination

| Constant | Value | Meaning |
|----------|-------|---------|
| `CHAIN_ID` | `"betanet-9"` | Bound into every signed tx + block body (anti cross-chain replay, M3); changes at every reroll |
| `DENOMINATION` | `10_000_000_000` | 1 NADO in raw units (`to_readable_amount` divides by this) |
| `GENESIS_TIMESTAMP` | `1790668583` | Genesis block timestamp (betanet-9, gen 28) |

## Treasury & reserved addresses

| Constant | Value | Meaning |
|----------|-------|---------|
| `GENESIS_ADDRESS` | `b7a08de8351e3af97f6f2bbcb19f2a8c722abad81c3460caf9` | The genesis producer address; a pinned literal (`make_address` of the founder key under address format 2 — it can no longer be derived from `_GENESIS_BODY`, which is that key's format-1 body) |
| `TREASURY_ADDRESS` | `"treasury"` | **Keyless** reserved account (no key, no founder, ≠ genesis address) that accrues the 10% treasury tax |
| `TREASURY_GENESIS` | `0` | **No premine** — genesis mints zero coins; every coin was a block reward |
| `RESERVED_RECIPIENTS` | 42 names — `auth`, `bond`, `unbond`, `withdraw`, `register`, `pool`, `delegate`, `undelegate`, `slash`, `attest`, `commit`, `reveal`, `duty`, `alias`, `blob`, `settle`, `bridge`(+`_withdraw`), `dividend`(+`_withdraw`), `htlc`(+`_lock`/`_claim`/`_refund`), `invite`(+`_lock`/`_claim`/`_refund`), `shield`/`unshield`, `treasury`(+`_vote`/`_execute`), `msgkey`, `xmsg`, `faucet`, `tpm_enrol`/`tpm_challenge`/`tpm_commit`/`tpm_reveal`/`tpm_ready`, `legacy_claim` | Keyless protocol pseudo-recipients (never a sender) |

## Reward & fees

| Constant | Value | Meaning |
|----------|-------|---------|
| `TREASURY_BPS` / `BPS_DENOM` | `1000` / `10000` | Treasury share = 10.00% of each block reward |
| `REWARD_WINDOW` | `100` | Rollback/prune safety window (the reward is bond-elastic, NOT fee-averaged) |
| `BASE_SUBSIDY` | `1_000_000_000` (0.1 NADO) | Flat base subsidy; `reward = BASE_SUBSIDY·m(r)`, so this is the **max**/block (no `REWARD_CAP` — removed). See bond-elastic-emission.md |
| `MIN_TX_FEE` | `1000` raw | Deterministic consensus minimum fee (anti-spam) |
| `split_block_reward(R)` | fn | Returns `(producer_cut, treasury_cut)` summing to exactly `R` (90/10) |

## Mining (PROVISIONAL — simulate before locking)

These gate the S4 bonded-mining mechanism (live on betanet-9).

| Constant | Value | Meaning |
|----------|-------|---------|
| `B_MIN` | `100_000_000_000` (10 NADO) | Capital per selection share / minimum bond to be eligible |
| ~~`BOND_CAP`~~ / ~~`MAX_SHARES`~~ | removed 2026-08-25 | Weight is linear in stake (`bonded // B_MIN`); the per-key cap never bound a whale with two keys |
| `BONDED_DIVIDEND_BPS` | `4000` | Bonded block's dividend cut (40 %; 20 % before betanet-5); producer 50 %, treasury 10 %. Levied on the block, not the key |
| `DIVIDEND_WEIGHT_MAX` | `FIDELITY_CAP` (30) | Nominal top of the linear dividend weight; the live weight is `dividend_weight(f) = min(f, DIVIDEND_WEIGHT_CAP_V2)` with `DIVIDEND_WEIGHT_CAP_V2 = 15` (the convex `1..25` curve is gone) |
| `BOND_UNLOCK_DELAY` | `14400` blocks (~1 day at 6 s) | Lock/cooldown after an unbond (anti-grind) |
| `EPOCH_LENGTH` | `60` slots | Blocks per RANDAO beacon epoch |
| `POSW_LEASE_EPOCHS` | `360` (36 h) | OPEN-lane presence lease — an identity renews (re-attests its device) within this window to stay eligible; the name predates the retirement of PoSW at gen 25 |
| `FIDELITY_CAP` | `30` | Fidelity score ceiling; weight ramps to full at this value |
| `FIDELITY_GAIN` | `1` | Fidelity gained per continuous recert (a lapse HALVES the streak, never below 1; there is no `FIDELITY_DECAY` constant) |

## Block header fields (set in `construct_block`)

Beyond the legacy fields, every block now carries:
- `cumulative_fees` — running total of all fees up to and including this block (kept in the
  header; the reward itself is bond-elastic and has no fee term).
- `chain_id` — the chain identifier (M3).

## Account state (the `accounts` KV doc)

State is a schemaless **LMDB** key-value store (`ops/kv_ops.py`), not SQLite. The `accounts`
sub-DB maps `address` → a **schemaless msgpack document** `{balance, produced, bonded, registered,
fidelity, …}` (no columns / no DDL — adding a field needs no migration). Totals live in the
`totals` sub-DB as `{produced, fees}`. (No `burned` — removed.) See
[storage-kv-migration.md](storage-kv-migration.md) for the full sub-DB schema.
