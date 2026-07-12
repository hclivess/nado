# Economics & supply

All amounts are integers in **raw** units; **1 NADO = 10,000,000,000 raw** (`DENOMINATION`).

## No premine; the treasury is the genesis address

There is **no personal premine**. The single genesis mint goes to the **treasury**, which —
per the project owner — **is the genesis address itself** (a normal, key-controlled address,
not a keyless label):

```
TREASURY_ADDRESS = ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b803280
```

This is the legacy genesis public-key body re-checksummed under the new canonical hashing
(see [determinism-and-chain-id.md](determinism-and-chain-id.md)); it is derived in
`protocol.py` as `_GENESIS_BODY + blake2b_hash(_GENESIS_BODY, size=2)` so it always validates.

The treasury:
- is **seeded at genesis** with `TREASURY_GENESIS = 1e18 raw = 100,000,000 NADO`, and
- **accrues 10%** of every block reward thereafter.

### Why a genesis seed at all?

A chain with literally zero coins cannot bootstrap: no coins ⇒ no fees ⇒ the fee-weighted
reward is 0 forever ⇒ no coins are ever minted, and nobody can post a mining bond. The seed
breaks that cycle. Because the treasury is key-controlled, **the seed is effectively a founder
allocation** — set `TREASURY_GENESIS = 0` for a pure no-coins start (and provide another
bootstrap, e.g. a faucet, instead).

## Block reward — fee-weighted, elastic, capped

The reward is a pure function of recent fee activity and is **recomputed and enforced** by
every node (it is not merely range-checked). It is anchored to the block's **own ancestry**
(not the verifier's tip) so full nodes and snapshot/pruned nodes always agree.

Each block header carries `cumulative_fees` — the running total of all fees up to and
including that block. The reward for the child of `parent` is the average fee per block over
the last `REWARD_WINDOW` blocks:

```
reward = (cumFee[parent] - cumFee[parent_height - REWARD_WINDOW]) // REWARD_WINDOW
reward = min(max(reward, 0), REWARD_CAP)
```

- `REWARD_WINDOW = 100`, `REWARD_CAP = 5e9 raw (0.5 NADO)`.
- Implemented in `block_ops.get_block_reward(parent_block, logger)` — **one indexed lookback**
  (`get_block_number(height-100)`), not a 100-block file walk.
- Enforced in `core_loop.verify_block`: a block whose `block_reward` ≠ the deterministic value
  is rejected. `rebuild_block` recomputes the reward + `cumulative_fees` from the local tip, so
  a peer can never inject an inflated reward.
- The old `fee_over_blocks` (buggy: it summed the last block N times) was replaced by `recommended_fee` - the tip block's mean fee, computed in memory for `/get_recommended_fee`.

## The 90/10 split (canonical)

Every block reward `R` is split between the producer and the treasury:

```python
def split_block_reward(R):
    producer_cut = R * (BPS_DENOM - TREASURY_BPS) // BPS_DENOM   # 90%
    treasury_cut = R - producer_cut                              # exact remainder (10%)
    return producer_cut, treasury_cut
```

`TREASURY_BPS = 1000` (10.00%), `BPS_DENOM = 10000`. The treasury gets the **remainder**, so
the two credits sum to exactly `R` (never two independent floors that could lose a unit).

- `incorporate_block` credits `producer_cut` to the block creator and `treasury_cut` to the
  treasury, and `rollback_one_block` reverses with the **identical** integers — so the two
  paths can never drift and drive a balance negative (which would wedge the core thread).
- The producer's `produced` counter (the penalty/anti-monopoly metric) tracks its **90% cut**,
  i.e. what it actually earned. `totals.produced` tracks the **full** emission `R`.

## Fees

- A transaction's `fee` is **always debited from the sender** (the old `> 111111` activation
  gate is gone — this is a fresh chain).
- Fees are **destroyed** (credited to no one), counted into `totals.fees`, subtracted from
  supply, and committed into each block's `cumulative_fees` (which drives the reward above).
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
