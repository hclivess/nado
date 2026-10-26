# Economics & supply

> **SUPERSEDED — read [tokenomics.md](tokenomics.md), [treasury.md](treasury.md), and
> [bond-elastic-emission.md](bond-elastic-emission.md) instead.** This early doc described a
> now-abandoned model (a key-controlled treasury seeded with a 100M premine, and a fee-weighted
> `REWARD_CAP` block reward). The live design is the opposite on both points — a *keyless* treasury,
> *zero* premine, and *flat bond-elastic* emission. The core sections below have been corrected to the
> live model, but the canonical economics docs are the three linked above.

All amounts are integers in **raw** units; **1 NADO = 10,000,000,000 raw** (`DENOMINATION`).

## No premine; the treasury is a keyless account

There is **no premine at all** — genesis mints **zero** coins (`TREASURY_GENESIS = 0`). Every coin in
existence was minted as a block reward. The treasury is a **keyless reserved account** (`TREASURY_ADDRESS
= "treasury"` — no key, no founder, no multisig), distinct from the genesis producer address:

- it holds **no genesis seed**, and
- **accrues 10%** of every block reward, spendable only by a **2/3 bonded-stake quorum vote** (see
  [treasury.md](treasury.md)), with idle balance **burned each period**.

A brand-new, zero-coin miner earns spendable coins from block 1 via the flat base subsidy — so the chain
bootstraps with no seed and no faucet-bond (the faucet is a prize bank, not an onboarding tap).

## Block reward — flat base, bond-elastic multiplier

The reward is a **flat base subsidy scaled by a bond-elastic multiplier** — a pure function of
the current bonded ratio (NOT a fee average, and there is no `REWARD_CAP`). It is **recomputed and
enforced** by every node (`block_ops.get_block_reward`) and is deterministic from committed state,
so full nodes and snapshot/pruned nodes always agree. Full derivation:
[bond-elastic-emission.md](bond-elastic-emission.md).

```
minted = BASE_SUBSIDY * m(r) // 1        # m(r) ∈ [m_min, 1], r = bonded / total_supply
```

- `BASE_SUBSIDY = 1e9 raw (0.1 NADO)` — since `m(r) ≤ 1`, this is the **MAX** emission per block;
  the floor `m_min·BASE_SUBSIDY ≈ 0.015 NADO` is the perpetual disinflationary tail.
- `m(r)` (`bond_elastic_mult_bps`, tuned `M_MIN=0.15, k=4`) shrinks emission as the bonded ratio
  rises — a more-secured chain mints less ("super hard money"). Fee-independent.
- Enforced in `core_loop.verify_block`: a block whose `block_reward` ≠ the deterministic value is
  rejected. `rebuild_block` recomputes it from committed state, so a peer can never inject an
  inflated reward.

## The reward split (canonical)

Every block reward `R` is split three ways, by the lane of the block (`reward_ops.credit_block_reward`):

| lane | producer | presence-dividend pool | treasury | function |
|---|---|---|---|---|
| open | 20 % (`OPEN_TIP_BPS = 2000`) | 70 % (the exact remainder) | 10 % (`TREASURY_BPS = 1000`) | `split_open_block_reward` |
| bonded | 50 % (the exact remainder) | 40 % (`BONDED_DIVIDEND_BPS = 4000`) | 10 % (`TREASURY_BPS = 1000`) | `split_bonded_block_reward` |

`BPS_DENOM = 10000`. Two parts are floors and the third is the **remainder**, so the three credits sum to exactly `R`
(never three independent floors that could lose a unit). The dividend credit is also recorded as the epoch's
inflow (`/get_dividend_inflow`), which the execution node distributes over that epoch's weights.

- `incorporate_block` applies the credits and `rollback_one_block` reverses them with the **identical** integers — so
  the two paths can never drift and drive a balance negative (which would wedge the core thread).
- The producer's `produced` counter tracks **its own cut** (the open-lane tip or the bonded producer share), i.e. what
  it actually earned. `totals.produced` tracks the **full** emission `R`.
- `protocol.split_block_reward` (a plain 90/10 producer/treasury split) is no longer called by the reward path.

## Fees

- A transaction's `fee` is **always debited from the sender** (the old `> 111111` activation
  gate is gone — this is a fresh chain).
- Fees are **destroyed** (credited to no one), counted into `totals.fees`, subtracted from
  supply, and committed into each block's `cumulative_fees` (a header counter; the reward does not read it).
- A **minimum fee** `MIN_TX_FEE = 1000 raw` is enforced in consensus (`validate_transaction`).
  It is a *deterministic integer floor* — deliberately **not** the byte-size "base fee"
  (`get_byte_size = sys.getsizeof(repr(...))` is non-deterministic and unsafe as a consensus
  rule).

## No burn

The burn mechanic (the `burn` recipient, the per-account `burned` counter, and burn-to-bribe)
has been **removed entirely**. `validate_address("burn")` is now `False`, so a tx to `burn` is
rejected. Note this is distinct from fee destruction: **fees are still destroyed** — that is
the fee mechanic that funds the elastic reward, not "burn".

## Supply accounting (`/get_supply`)

```
total_supply = TREASURY_GENESIS + produced - fees
circulating  = total_supply - treasury_balance
```

- `produced` = sum of all block rewards minted (full `R`, i.e. producer + treasury cuts).
- `fees` = sum of all fees (destroyed).
- The treasury balance is counted as **non-circulating** (it is the protocol/owner reserve).
- There is no `reserve`/`reserve_spent`/`burned` — those are gone.
