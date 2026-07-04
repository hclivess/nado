# NADO Tokenomics

A single-page reference for NADO's monetary policy. Every number here is a live protocol
constant — see `protocol.py` (and the linked deep-dives) for the authoritative source. This
document is descriptive; the code is canonical.

Related deep-dives: [economics.md](economics.md) (emission + supply accounting),
[treasury.md](treasury.md) (governance), [presence-dividend.md](presence-dividend.md)
(open-lane redistribution), [mining.md](mining.md) (the two lanes), [governance.md](governance.md).

---

## At a glance

| Property | Value |
|---|---|
| Ticker / unit | **NADO** |
| Smallest unit | **1 NADO = 10¹⁰ raw** (10 decimals) |
| Premine | **None** — `TREASURY_GENESIS = 0`, no pre-funded balances |
| Launch | Fair: open-lane mining + a base subsidy earn real coins from block 1 |
| Emission | Elastic per-block reward, **floored** and **capped** (see below) |
| Per-block reward | **0.1 NADO** (floor) … **0.5 NADO** (cap) |
| Max supply | **Uncapped** — perpetual tail emission at ≥ the base subsidy |
| Reward split | **90 %** block producer · **10 %** treasury |
| Block lanes | **30 %** open (permissionless) · **70 %** bonded (staked) |
| Fees | **Destroyed** (not paid to the producer); drive the elastic reward |
| Treasury | Keyless account, fills from the 10 % cut, bonded-quorum governed |

---

## 1. Denomination

The base unit is **raw**; the display unit is **NADO**.

```
1 NADO = 10_000_000_000 raw   (10 decimals; DEC = 10**10)
```

All consensus arithmetic is integer raw — there are no floats anywhere in the signed/hashed
payload (see `hashing.canonical_bytes`). Reference amounts:

| Constant | Raw | NADO |
|---|---|---|
| `MIN_TX_FEE` | 1 000 | 0.0000001 |
| `BASE_SUBSIDY` | 1 000 000 000 | 0.1 |
| `REWARD_CAP` | 5 000 000 000 | 0.5 |
| `ALIAS_REGISTRATION_FEE` | 10 000 000 | 0.001 |
| `B_MIN` (one bonded share) | 1 000 000 000 000 | 100 |
| `BOND_CAP` (per identity) | 100 000 000 000 000 | 10 000 |

## 2. Fair launch — no premine

`TREASURY_GENESIS = 0`. There is **no** genesis allocation, no founder premine, no pre-funded
treasury. The chain starts at zero coins and mints them into existence one block at a time.
The treasury is a **keyless reserved account** (`TREASURY_ADDRESS = "treasury"`) that can only
ever be *credited by the protocol* (its 10 % per-block cut) and *spent by bonded-quorum vote* —
nobody holds its key. A zero-coin miner in the **open lane** earns real coins from block 1,
which then circulate and pay fees; there is no capital requirement to start.

## 3. Emission — elastic, floored, capped

The block reward is a **pure function of recent fee activity**, recomputed and enforced by
every node (not merely range-checked), anchored to the block's own ancestry so full nodes and
snapshot/pruned nodes always agree (`block_ops.get_block_reward`).

```
reward = (cumFee[parent] − cumFee[parent_height − REWARD_WINDOW]) // REWARD_WINDOW
reward = clamp(reward, BASE_SUBSIDY, REWARD_CAP)
```

- `REWARD_WINDOW = 100` — the reward tracks the trailing-100-block average fee.
- `BASE_SUBSIDY = 0.1 NADO` — the floor. With no premine a new chain has no fees, so the
  elastic term is 0 and the subsidy carries emission. This is the fair-launch engine.
- `REWARD_CAP = 0.5 NADO` — the ceiling. As usage (and fees) rise, the reward rises **on top of**
  the subsidy up to this cap, then stops.

**Supply is uncapped but rate-bounded.** Emission never falls below the base subsidy, so NADO
has a perpetual (disinflationary-by-ratio) tail rather than a hard cap. As an order of
magnitude, at a ~60 s block cadence the floor is ~1 440 blocks/day × 0.1 = **~144 NADO/day**;
at the cap, ~720 NADO/day. (Block cadence is a network parameter, so treat these as
illustrative — emission is defined **per block**, not per day.)

Fees themselves are **destroyed**, not paid to the producer — so higher usage raises *everyone's*
reward through the elastic term rather than enriching one miner. See [economics.md](economics.md).

## 4. The 90 / 10 split

Every block reward `R` is split producer / treasury, with the treasury taking the exact
remainder so the two credits always sum to `R`:

```
producer_cut = R × (BPS_DENOM − TREASURY_BPS) // BPS_DENOM   # 90 %
treasury_cut = R − producer_cut                              # 10 %
```

`TREASURY_BPS = 1000` (10.00 %), `BPS_DENOM = 10000`.

## 5. Two lanes and the presence dividend

Each epoch's `EPOCH_LENGTH = 60` slots are split by a beacon-keyed permutation into:

- an **OPEN lane** — `OPEN_BPS = 3000` (**30 %**, `K_OPEN = 18` slots/epoch): permissionless,
  zero capital, one renewable registration PoW (a *presence lease*). This is the Sybil-bounded
  fair-mining lane.
- a **BONDED lane** — the remaining **70 %**: selection weight proportional to locked stake.

The 90/10 producer/treasury split still holds on the **total** reward, but the producer's 90 %
is redistributed differently per lane to reward *presence* over *capital*:

| Lane | Producer | Treasury | Dividend pool |
|---|---|---|---|
| **Open** block | `OPEN_TIP_BPS = 20 %` | 10 % | **70 %** (the rest) |
| **Bonded** block | 70 % | 10 % | `BONDED_DIVIDEND_BPS = 20 %` |

The **DIVIDEND_POOL** (`"dividend"`, a keyless L1 account) accrues the redistributed share.
It is paid out off-L1 by the execution node to the **currently-present open miners**, weighted
by fidelity, and **collected on demand** (a provable claim settled against the state root). So
open miners earn both their block tips *and* a continuous share of the dividend pool — including
a slice funded by the bonded lane. Full mechanics: [presence-dividend.md](presence-dividend.md).

## 6. Bonded staking (the savings lane)

Locking stake buys **producer-selection shares** in the bonded lane:

- `B_MIN = 100 NADO` — capital per selection share. Bonded stake is *refundable locked stake*,
  **not** spendable balance.
- `BOND_CAP = 10 000 NADO` → `MAX_SHARES = 100` — a per-identity variance cap so a whale can't
  monopolise the bonded lane.
- `BOND_RAMP_EPOCHS = 30` — a fresh bond's selection weight ramps linearly 0 → full over ~30
  epochs (stake-weighted bond age), giving the network reaction time against a sudden takeover.
- `BOND_UNLOCK_DELAY = 1440 blocks` — after an `unbond` request the stake stays locked (and
  slashable) for this delay before `withdraw` can claim it. This closes the instant-unbond
  slash-escape.
- **Slashing**: `SLASH_BOND_PENALTY = B_MIN` (one share) is **burned** from an identity proven to
  have equivocated (two conflicting signatures at one height). Burned, not redistributed.

Yield is not a fixed APY — a bonded miner earns the bonded-lane block rewards it is selected to
produce (70 % of `R` per bonded block it makes), which depends on its share of total bonded
stake and the current reward. Early-network yields are high and fall as more stake bonds; the
wallet's Savings tab estimates a live figure.

## 7. Treasury

The treasury is the protocol/owner reserve, filled **only** by the 10 % per-block cut (no
premine). It is spent by **bonded-quorum governance**, not by any individual:

- Bonded validators **propose** a spend and **vote**; a proposal executes once it clears a
  **2/3** approval-share quorum (`settle_num/settle_den`).
- `TREASURY_MAX_SPEND_BPS = 2500` — any single proposal may spend **at most 25 %** of the
  *current* treasury balance, bounding blast radius.
- `TREASURY_VOTE_ACTIVATION_EPOCHS` — a delay before a newly-bonded identity's vote counts
  (alpha value low; raise to ~180 ≈ 1 day for mainnet).
- **Anti-hoard self-burn**: every `TREASURY_SPEND_PERIOD = 10800` blocks, `TREASURY_BURN_BPS =
  100` (**1 %**) of the balance above `TREASURY_RUNWAY_FLOOR` is burned, so an idle treasury
  can't simply be hoarded. Governance details: [treasury.md](treasury.md).

**Maintainer grant (the founder's reward — governed, not hard-coded).** The maintainer/founder
takes **no protocol-level cut** and holds **no treasury key**; `TREASURY_GENESIS` stays `0` and
there is no founder tax on the block reward. Ongoing maintenance is funded like any other spend —
a **recurring `treasury_spend` proposal approved by the 2/3 bonded quorum**, guideline **~1 % of
treasury inflow** (≈ one-tenth of the 10 % cut), which the quorum can raise, cut, or end by vote.
So even the maintainer's pay is community-approved: "no premine / not a founder" holds, and the
reward is transparent rather than a hard-coded skim (treasury.md §3.7).

## 8. Fees

- A transaction's `fee` is **always debited from the sender**.
- Fees are **destroyed** (credited to no one), counted into `totals.fees`, subtracted from
  supply, and committed into each block's `cumulative_fees` — which is exactly what drives the
  elastic reward (§3). Usage funds emission collectively; it does not tip the producer.
- `MIN_TX_FEE = 1000 raw` is a deterministic integer anti-spam floor enforced in consensus.
- There is **no separate burn recipient** — a tx to `burn` is rejected. "Fee destruction" is the
  only sink.

## 9. Supply accounting (`/get_supply`)

```
total_supply = TREASURY_GENESIS + produced − fees        # = produced − fees  (TREASURY_GENESIS = 0)
circulating  = total_supply − treasury_balance
```

- `produced` = sum of every block reward minted (the full `R` = producer + treasury cuts).
- `fees` = sum of all fees ever destroyed.
- The treasury balance is counted as **non-circulating** (protocol reserve).

## 10. Non-emission pools (keyless escrow)

These reserved accounts hold user coins in escrow for execution-layer features; they are not
part of emission and hold no key:

| Account | Purpose |
|---|---|
| `SHIELD_ESCROW = "shield"` | Locks L1 coins backing the zk-STARK shielded pool ([privacy.md](privacy.md)) |
| `BRIDGE_ESCROW = "bridge"` | Locks L1 coins bridged to the execution layer |
| `HTLC_ESCROW = "htlc"` | Locks coins for cross-chain atomic swaps ([htlc.md](htlc.md)) |
| `DIVIDEND_POOL = "dividend"` | Accrues the presence dividend for open miners (§5) |

---

## Constants (canonical — `protocol.py`)

| Constant | Value | Meaning |
|---|---|---|
| `TREASURY_GENESIS` | 0 | No premine |
| `BASE_SUBSIDY` | 0.1 NADO | Per-block emission floor |
| `REWARD_CAP` | 0.5 NADO | Per-block emission cap |
| `REWARD_WINDOW` | 100 | Trailing blocks averaged for the elastic reward |
| `TREASURY_BPS` | 1000 (10 %) | Treasury cut of every block reward |
| `EPOCH_LENGTH` | 60 | Slots per epoch |
| `OPEN_BPS` | 3000 (30 %) | Open-lane share of slots (Sybil ceiling) |
| `OPEN_TIP_BPS` | 2000 (20 %) | Open producer's own cut of an open block |
| `BONDED_DIVIDEND_BPS` | 2000 (20 %) | Bonded block's contribution to the dividend pool |
| `B_MIN` | 100 NADO | Capital per bonded selection share |
| `BOND_CAP` / `MAX_SHARES` | 10 000 NADO / 100 | Per-identity bond & share cap |
| `BOND_RAMP_EPOCHS` | 30 | Fresh-bond selection-weight ramp |
| `BOND_UNLOCK_DELAY` | 1440 blocks | Post-unbond lock (slashable) |
| `SLASH_BOND_PENALTY` | `B_MIN` (100 NADO) | Burned per proven equivocation |
| `TREASURY_MAX_SPEND_BPS` | 2500 (25 %) | Max single proposal vs current balance |
| `TREASURY_SPEND_PERIOD` | 10 800 blocks | Self-burn cadence |
| `TREASURY_BURN_BPS` | 100 (1 %) | Self-burn of balance above the floor |
| `MIN_TX_FEE` | 1 000 raw | Consensus anti-spam fee floor |

> **Status:** testnet alpha (`chain_id = nado-relaunch-1`). Several parameters carry alpha
> values flagged for mainnet tuning (e.g. `TREASURY_VOTE_ACTIVATION_EPOCHS`,
> `TREASURY_RUNWAY_FLOOR`). Always read the current value from `protocol.py`.
