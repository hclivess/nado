# Protocol constants reference (`protocol.py`)

Single source of truth for all consensus-critical protocol/economic/mining constants. Every
node must agree on these. `protocol.py` is a leaf module (imports only `hashing`) so anything
can import it without a cycle.

## Identity & denomination

| Constant | Value | Meaning |
|----------|-------|---------|
| `CHAIN_ID` | `"nado-relaunch-1"` | Bound into every signed tx + block body (anti cross-chain replay, M3) |
| `DENOMINATION` | `10_000_000_000` | 1 NADO in raw units (`to_readable_amount` divides by this) |
| `GENESIS_TIMESTAMP` | `1669852800` | Genesis block timestamp |

## Treasury & reserved addresses

| Constant | Value | Meaning |
|----------|-------|---------|
| `GENESIS_ADDRESS` / `TREASURY_ADDRESS` | `ndo18c3afa…b803280` | The genesis address = the treasury (key-controlled); derived `_GENESIS_BODY + blake2b_hash(_GENESIS_BODY, size=2)` |
| `TREASURY_GENESIS` | `1_000_000_000_000_000_000` (1e18 = 100M NADO) | Bootstrap allocation minted to the treasury at genesis. **Set 0 for a pure no-coins start.** |
| `RESERVED_RECIPIENTS` | `{"bond", "unbond"}` | Keyless protocol pseudo-recipients. (No `burn` — removed.) |

## Reward & fees

| Constant | Value | Meaning |
|----------|-------|---------|
| `TREASURY_BPS` / `BPS_DENOM` | `1000` / `10000` | Treasury share = 10.00% of each block reward |
| `REWARD_WINDOW` | `100` | Trailing blocks averaged for the elastic reward |
| `REWARD_CAP` | `5_000_000_000` (0.5 NADO) | Max reward per block |
| `MIN_TX_FEE` | `1000` raw | Deterministic consensus minimum fee (anti-spam) |
| `split_block_reward(R)` | fn | Returns `(producer_cut, treasury_cut)` summing to exactly `R` (90/10) |

## Mining (PROVISIONAL — simulate before locking)

These gate the S4 bonded-mining mechanism. Values are placeholders pending economic simulation.

| Constant | Value | Meaning |
|----------|-------|---------|
| `B_MIN` | `1_000_000_000_000` (100 NADO) | Capital per selection share / minimum bond to be eligible |
| `BOND_CAP` | `100_000_000_000_000` (10k NADO) | Max effective bond per identity (variance cap) |
| `MAX_SHARES` | `100` (`BOND_CAP // B_MIN`) | Max selection shares one identity can hold (anti-whale) |
| `BOND_UNLOCK_DELAY` | `1440` blocks | Lock/cooldown after an unbond (anti-grind) |
| `EPOCH_LENGTH` | `60` slots | Blocks per RANDAO beacon epoch |
| `FAUCET_STARTER_BOND` | `B_MIN` | Treasury-funded starter bond for a fresh address (onboarding) |
| `FIDELITY_CAP` | `1000` | Fidelity score ceiling; weight ramps to full at this value |
| `FIDELITY_GAIN` | `1` | Fidelity gained per epoch present |
| `FIDELITY_DECAY` | `2` | Fidelity lost per epoch absent (continuity costs more to fake than to keep) |

## Block header fields (set in `construct_block`)

Beyond the legacy fields, every block now carries:
- `cumulative_fees` — running total of all fees up to and including this block (drives the
  reward; lets full **and** pruned/snapshot nodes recompute it from headers).
- `chain_id` — the chain identifier (M3).

## Account schema (`acc_index`)

`(address TEXT, balance INTEGER, produced INTEGER, bonded INTEGER)`, UNIQUE on `address`.
`totals_index` = `(produced INTEGER, fees INTEGER)`. (No `burned` — removed.)
</content>
