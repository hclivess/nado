# Bond-elastic emission → super hard money (DRAFT)

Status: **draft / prototype on betanet, tune, lock for mainnet genesis.** Consensus-critical monetary
policy (hardfork-level). Not yet implemented.

## Goal: the hardest money we can coherently build

Advanced tech does not pump a token — supply discipline and value accrual do (see STRK: best-in-class STARKs,
−98% price, killed by insider unlocks and a token that captured no usage). NADO already removes the *supply
attack* (no premine, no VC cliffs — every coin mined). This design makes NADO **net-deflationary under real
usage** — strictly harder than Bitcoin, which only *disinflates* to a fixed cap and never shrinks.

Three stacked hardness layers, all driven by the network's own success:

1. **Bond-elastic minting** — the more the network bonds (conviction), the less it mints. `m(r)` below.
2. **Fee destruction** — every transaction fee is *destroyed* (already live: `totals.fees`, subtracted from
   `total_supply`). Usage burns supply.
3. **Perpetual tail, NO hard cap** — a small floor emission continues forever so producers are always paid;
   the treasury self-burn (already live) adds more destruction on top.

Net per-block supply change = `minted − burned`. With (1)+(2), that goes **negative** as soon as there is
real fee activity — so NADO deflates under usage while never starving security. Hardness without a cliff.

## Layer 1 — bond-elastic multiplier `m(r)`

```
r        = bonded_supply / circulating_supply            # 0..1, committed state, lagged (see Determinism)
m(r)     = M_MIN + (1 - M_MIN) * exp(-k * r)             # bounded convex; m(0)=1, m(∞)->M_MIN
minted   = clamp( m(r) * fee_weighted_subsidy , m(r)*BASE_SUBSIDY , REWARD_CAP )
```

`fee_weighted_subsidy` is today's reward (fee-weighted avg over `REWARD_WINDOW`=100 blocks, floor
`BASE_SUBSIDY`=0.1, cap `REWARD_CAP`=0.5). `m(r)` scales it, **uniformly across both lanes** (open + bonded).

Parameters (starting point — tune on betanet): `M_MIN = 0.20`, `k = 3.0`, ratio lag = 1 finalized epoch.

| bonded r | m(r) | minted floor/block (no fees) |
|---:|---:|---:|
| 0%  | 1.00 | 0.1000 |
| 10% | 0.79 | 0.0793 |
| 20% | 0.64 | 0.0639 |
| 30% | 0.53 | 0.0525 |
| **~39% (equilibrium)** | **0.45** | **~0.045** |
| 50% | 0.38 | 0.0379 |
| 60% | 0.33 | 0.0332 |
| 70% | 0.30 | 0.0298 |
| 100% (unreachable) | 0.24 | 0.0240 |

`m(0)=1`: at genesis nobody can bond (no coins yet — fair launch), so emission starts at full base — max
distribution to zero-coin open-lane miners exactly when it should. Convex `exp` rewards the first bonders and
drops into scarcity fast. Bounded `[M_MIN,1]` never boosts above base and never hits zero.

## Layer 2 — the money table: net issuance (deflation)

Fees are destroyed, so per block: `net = m(r)·fee_weighted_subsidy − fees`. **Negative = supply shrinks.**

| fees/block → | 0.00 | 0.05 | 0.10 | 0.20 | 0.30 | 0.50 | 1.00 |
|---|---:|---:|---:|---:|---:|---:|---:|
| **r=0%**  (m=1.00) | +0.100 | +0.050 | 0.000 | 0.000 | 0.000 | 0.000 | −0.500 |
| **r=20%** (m=0.64) | +0.064 | +0.014 | −0.036 | −0.072 | −0.108 | −0.180 | −0.680 |
| **r=39%** (m=0.45) | +0.045 | −0.005 | −0.055 | −0.110 | −0.166 | −0.276 | −0.776 |
| **r=60%** (m=0.33) | +0.033 | −0.017 | −0.067 | −0.134 | −0.200 | −0.334 | −0.834 |

Read it: NADO is inflationary **only at near-zero usage** (the bootstrap phase). The instant real fees appear
it turns **deflationary**, and **bonding deepens the burn** (lower `m` → less minted against the same fees).

**Deflation crossover** — fees/block above which supply shrinks:

| bonded r | m(r) | net turns negative above |
|---:|---:|---:|
| 0%  | 1.00 | 0.1000 NADO/block |
| 20% | 0.64 | 0.0639 |
| 39% | 0.45 | 0.0448 |
| 60% | 0.33 | 0.0332 |

## Layer 3 — perpetual tail, NO hard supply cap

**We deliberately reject a hard cap.** A fixed cap (or a halving schedule that drives the subsidy to zero)
recreates Bitcoin's unsolved *security-cliff*: once the block subsidy ends, producers depend entirely on fees,
and if fees are ever low, security collapses. NADO keeps a **perpetual tail** (Monero's exact reasoning) so a
block is *always* worth producing.

The tail is automatic from Layer 1: the reward floor is `m(r) · BASE_SUBSIDY`, and `m(r) ≥ M_MIN`, so:

```
perpetual security floor = M_MIN · BASE_SUBSIDY = 0.20 · 0.1 = 0.02 NADO/block, FOREVER
                         = ~10,512 NADO/yr minimum emission (60s blocks) — the chain can never die of zero subsidy
```

Hardness does **not** come from ending emission — it comes from **burning more than that tail** once the
network is used. Fees destroyed + treasury self-burn routinely exceed 0.02/block under any real activity, so
net supply falls (see Scenarios). Supply is *unbounded in principle* but *shrinking in practice* — the ideal:
no cliff, no cap anxiety, yet net-deflationary.

## Harder than Bitcoin (without the cliff)

| property | Bitcoin | Monero | NADO (this design) |
|---|---|---|---|
| premine / insiders | none | none | none |
| supply cap | 21M hard | none (tail) | **none (tail)** — deliberate, avoids the security cliff |
| tail emission | → 0 (cliff risk) | flat 0.6/blk | **`m(r)·BASE`, floored 0.02/blk** |
| fees | paid to miner (recycled) | paid to miner | **destroyed** |
| net supply at maturity | asymptotes to cap (never falls) | mild perpetual inflation | **falls** (deflationary under usage) |
| tightening driver | fixed schedule | none | usage (fee burn) **+** conviction (bonding) |

## Scenarios

Per-block and annualized net issuance (60s blocks ⇒ 525,600/yr). `net = m(r)·fee_weighted_subsidy − fees`;
negative = **supply shrinks**. (Treasury self-burn adds *more* destruction on top — not shown.)

| scenario | fees/blk | bonded r | m(r) | mint/blk | burn/blk | net/blk | **net / YEAR** |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — Dormant / bootstrap | 0.00 | 5% | 0.89 | 0.089 | 0.000 | +0.089 | **+46,703** |
| B — Early growth | 0.05 | 20% | 0.64 | 0.064 | 0.050 | +0.014 | **+7,308** |
| C — Adopted | 0.20 | 40% | 0.44 | 0.088 | 0.200 | −0.112 | **−58,767** |
| D — Bull / high-usage | 0.50 | 55% | 0.35 | 0.177 | 0.500 | −0.323 | **−169,863** |
| E — Mania | 1.00 | 60% | 0.33 | 0.166 | 1.000 | −0.834 | **−438,288** |

Reading it: **A/B (bootstrap)** — mild net emission distributes coins and keeps the lights on when there's no
usage yet (this is *why* the tail exists). **C→E (adoption)** — supply actively shrinks, harder the more NADO
is used and bonded. The system is inflationary only while nobody is using it, and deflationary exactly when it
matters.

**Parameter sensitivity** — net/yr in the "Adopted" scenario (fees 0.2, r 40%), varying `M_MIN` and `k`:

| | k=2.0 | k=3.0 | k=4.0 |
|---|---:|---:|---:|
| **M_MIN=0.1** | −52,098 | −66,113 | −75,507 |
| **M_MIN=0.2** | −46,309 | −58,767 | −67,117 |
| **M_MIN=0.3** | −40,521 | −51,421 | −58,728 |

Lower `M_MIN` and higher `k` = harder money (deeper burn) but a lower perpetual security floor — that's the
core tradeoff to tune on betanet. `M_MIN=0.2, k=3` is a balanced default.

## Why it self-regulates (equilibrium)

Emission splits: open lane `OPEN_BPS`=30% of slots, bonded lane 70% pro-rata to stake. A bonder's real yield
is `π·(0.70 − r)/r`, which goes **negative past r=0.70** (open lane siphons 30%), so bonding self-limits — a
"100% bonded" state cannot occur. Solving `real_yield(r)=h` for a ~3% hurdle gives a stable **~39% bonded**
equilibrium (2% → ~44%, 5% → ~33%); the feedback converges without oscillation (simulated). No griefing: a
whale over-bonding only burns its own yield and is capped by `BOND_CAP` (100 shares/identity).

## Fairness — reduction applies to the open lane too, on purpose

Fair-launch fairness is **access, not payout**: 30% of slots at zero capital, always. The open lane keeps 30%
of the pie forever; the pie shrinks only as the network matures and coins get scarce/valuable. Early
newcomers mine a big pie; late newcomers mine a small pie of an expensive coin. No lane carve-out needed.

## Determinism & anti-grind

`r` is a pure function of committed state (`total_bonded_shares·B_MIN` / `circulating_supply` from `totals`),
read **as of the last finalized epoch** — never the tip — mirroring how `get_block_reward` already reads
ancestry, so full and rolling/snapshot nodes agree. The epoch lag + `BOND_RAMP_EPOCHS`(30) + unbonding
friction defeat a bond→mine→unbond grind on the curve.

## Implementation sketch

```python
def bond_elastic_multiplier(bonded_ratio: float) -> float:
    m = M_MIN + (1.0 - M_MIN) * math.exp(-K_DECAY * bonded_ratio)
    return min(1.0, max(M_MIN, m))

# get_block_reward(parent):
#   r      = bonded_ratio_at_finalized_epoch()
#   mult   = bond_elastic_multiplier(r)
#   reward = int(mult * fee_weighted_subsidy)        # BASE_SUBSIDY stays flat -> perpetual tail (no halving)
#   return clamp(reward, int(mult * BASE_SUBSIDY), REWARD_CAP)   # floor >= M_MIN*BASE = perpetual security
# Fee destruction + treasury burn already exist (ops/reward_ops); net issuance = reward − fees_destroyed.
```

## Betanet plan

Ship in betanet genesis params, watch where the bonded ratio, net issuance, and burn actually settle, tune
`M_MIN` / `k` / halving cadence, then freeze for mainnet genesis.

## Open decisions

- `circulating_supply` denominator: include/exclude treasury + burned counter?
- `M_MIN` / `k`: set the perpetual security floor **and** the deflation depth (see sensitivity table).
- Tail floor level: is `0.02 NADO/block` enough perpetual security budget, or set `M_MIN`/`BASE` higher?
- NO hard cap and NO halving-to-zero (rejected — security cliff). Confirm we hold this line.
- Equilibrium bonded ratio target — raise it (lower `OPEN_BPS`) for more stake-security vs. fair-launch reach?
