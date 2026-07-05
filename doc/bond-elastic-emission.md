# Bond-elastic emission → super hard money

Status: **IMPLEMENTED + TUNED (final).** Consensus-critical monetary policy (hardfork-level); live in
`ops/block_ops.get_block_reward` with the tuned constants `M_MIN=0.15, k=4, BASE_SUBSIDY=0.1`. Freeze
these into mainnet genesis; betanet is a live sanity check, not a tuning round.

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
r        = bonded_supply / total_supply                  # 0..1, committed state (see Determinism)
m(r)     = M_MIN + (1 - M_MIN) * exp(-k * r)             # bounded convex; m(0)=1, m(∞)->M_MIN
minted   = BASE_SUBSIDY * m(r)                            # FLAT base scaled by m; fee-INDEPENDENT, no cap
```

Emission is a **flat** `BASE_SUBSIDY` (0.1 NADO) scaled by `m(r)`, applied **uniformly to both lanes**
(open + bonded). There is **no fee-weighted term and no ceiling** — `REWARD_CAP` is removed. Fees are
destroyed, so raising the mint with fees would print more exactly when more is burned, softening the
deflation. Since `m(r) <= 1`, **`BASE_SUBSIDY` is the MAX emission/block** and `m_min·BASE_SUBSIDY` (~0.024)
the min (perpetual tail). Implemented as an integer bps multiply: `reward = BASE_SUBSIDY * m_bps // 10000`.

**TUNED (final): `M_MIN = 0.15`, `k = 4.0`, `BASE_SUBSIDY = 0.1 NADO`.** Chosen against explicit criteria —
`M_MIN` sets the perpetual security tail (0.15 ⇒ ~0.0166 NADO/block ≈ 52,000 NADO/yr forever at 10s, a credible
floor without being generous), `k=4` makes emission at the ~40% self-limiting equilibrium ~0.033/block
(hard) with a responsive-but-not-violent early curve (10% bonded ⇒ ~28% emission cut). `BASE_SUBSIDY` is a
pure scale/units choice (max emission + distribution rate); 0.1 NADO/block = 144/day max is a sound
distribution rate, so the *curve* carries the hardness, not the base.

| bonded r | m(r) | minted/block (flat, fee-independent) |
|---:|---:|---:|
| 0%  | 1.00 | 0.1000 ← MAX emission/block |
| 10% | 0.72 | 0.0720 |
| 20% | 0.53 | 0.0532 |
| 30% | 0.41 | 0.0406 |
| **~39% (equilibrium)** | **0.33** | **~0.0329** |
| 50% | 0.27 | 0.0265 |
| 60% | 0.23 | 0.0227 |
| 70% | 0.20 | 0.0202 |
| 100% (unreachable) | 0.17 | 0.0166 ← perpetual tail |

`m(0)=1`: at genesis nobody can bond (no coins yet — fair launch), so emission starts at full base — max
distribution to zero-coin open-lane miners exactly when it should. Convex `exp` rewards the first bonders and
drops into scarcity fast. Bounded `[M_MIN,1]` never boosts above base and never hits zero.

## Layer 2 — the money table: net issuance (deflation)

Emission is flat (`minted = BASE_SUBSIDY·m(r)`), fees are destroyed, so per block: `net = BASE·m(r) − fees`.
**Negative = supply shrinks.**

| fees/block → | 0.00 | 0.05 | 0.10 | 0.20 | 0.50 | 1.00 |
|---|---:|---:|---:|---:|---:|---:|
| **r=0%**  (mint 0.100) | +0.100 | +0.050 | 0.000 | −0.100 | −0.400 | −0.900 |
| **r=20%** (mint 0.053) | +0.053 | +0.003 | −0.047 | −0.147 | −0.447 | −0.947 |
| **r=39%** (mint 0.033) | +0.033 | −0.017 | −0.067 | −0.167 | −0.467 | −0.967 |
| **r=60%** (mint 0.023) | +0.023 | −0.027 | −0.077 | −0.177 | −0.477 | −0.977 |

Read it: NADO is inflationary **only at near-zero usage** (the bootstrap phase). The instant real fees appear
it turns **deflationary** — and because the mint is flat (capped at `BASE·m`), every extra unit of fee is a
net burn. Bonding deepens it further (lower `m` → less minted). Harder than the fee-weighted variant, which
softened deflation by minting more when fees rose.

**Deflation crossover** — fees/block above which supply shrinks:

| bonded r | m(r) | net turns negative above |
|---:|---:|---:|
| 0%  | 1.00 | 0.1000 NADO/block |
| 20% | 0.53 | 0.0532 |
| 39% | 0.33 | 0.0329 |
| 60% | 0.23 | 0.0227 |

## Layer 3 — perpetual tail, NO hard supply cap

**We deliberately reject a hard cap.** A fixed cap (or a halving schedule that drives the subsidy to zero)
recreates Bitcoin's unsolved *security-cliff*: once the block subsidy ends, producers depend entirely on fees,
and if fees are ever low, security collapses. NADO keeps a **perpetual tail** (Monero's exact reasoning) so a
block is *always* worth producing.

The tail is automatic from Layer 1: the reward floor is `m(r) · BASE_SUBSIDY`, and `m(r) ≥ M_MIN`, so:

```
perpetual security floor ≈ m_min · BASE_SUBSIDY = 0.166 · 0.1 = 0.0166 NADO/block, FOREVER
                         = ~52,000 NADO/yr minimum emission (block_time=10s) — the chain never dies of zero subsidy
                         (M_MIN=0.15 is the r→∞ asymptote; 0.0166 is the reachable min at 100% bonded)
```

Hardness does **not** come from ending emission — it comes from **burning more than that tail** once the
network is used. Fees destroyed + treasury self-burn routinely exceed ~0.017/block under any real activity,
so net supply falls (see Scenarios). Supply is *unbounded in principle* but *shrinking in practice* — the
ideal: no cliff, no cap anxiety, yet net-deflationary.

## Harder than Bitcoin (without the cliff)

| property | Bitcoin | Monero | NADO (this design) |
|---|---|---|---|
| premine / insiders | none | none | none |
| supply cap | 21M hard | none (tail) | **none (tail)** — deliberate, avoids the security cliff |
| tail emission | → 0 (cliff risk) | flat 0.6/blk | **`m(r)·BASE`, floored ~0.0166/blk (~52,000/yr @10s)** |
| fees | paid to miner (recycled) | paid to miner | **destroyed** |
| net supply at maturity | asymptotes to cap (never falls) | mild perpetual inflation | **falls** (deflationary under usage) |
| tightening driver | fixed schedule | none | usage (fee burn) **+** conviction (bonding) |

## Scenarios

Per-block and annualized net issuance at **block_time = 10s ⇒ 3,153,600 blocks/yr**. Flat mint:
`net = BASE·m(r) − fees`; negative = **supply shrinks**. (Treasury self-burn adds *more* destruction on top —
not shown.) Per-block figures are cadence-independent; the `/YEAR` column scales linearly with block_time.

| scenario | fees/blk | bonded r | m(r) | mint/blk | burn/blk | net/blk | **net / YEAR (10s)** |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — Dormant / bootstrap | 0.00 | 5% | 0.85 | 0.0846 | 0.000 | +0.0846 | **+266,770** |
| B — Early growth | 0.05 | 20% | 0.53 | 0.0532 | 0.050 | +0.0032 | **+10,069** |
| C — Adopted | 0.20 | 40% | 0.32 | 0.0322 | 0.200 | −0.1678 | **−529,296** |
| D — Bull / high-usage | 0.50 | 55% | 0.24 | 0.0244 | 0.500 | −0.4756 | **−1,499,795** |
| E — Mania | 1.00 | 60% | 0.23 | 0.0227 | 1.000 | −0.9773 | **−3,081,979** |

Reading it: **A/B (bootstrap)** — mild net emission distributes coins and keeps the lights on when there's no
usage yet (this is *why* the tail exists). **C→E (adoption)** — supply actively shrinks, harder the more NADO
is used and bonded. The system is inflationary only while nobody is using it, and deflationary exactly when it
matters.

**How the tuning was chosen.** Two knobs trade off perpetual security (the tail) against hardness (low
equilibrium emission). Grid of `tail/yr` (min emission, forever) vs `emission@40%/yr` (gross emission at the
self-limiting equilibrium — lower = harder), `BASE=0.1`:

(NADO/yr at block_time=10s; relative ranking is cadence-independent.)

| M_MIN | k | tail/yr (security) | emit@40%/yr (hardness) | 10%-bond emission cut |
|---:|---:|---:|---:|---:|
| 0.10 | 4 | 36,733 | 88,842 | 30% |
| **0.15** | **4** | **52,214** | **101,424** | **28%** ← chosen |
| 0.20 | 3 | 75,631 | 139,061 | 21% (original draft) |
| 0.20 | 4 | 67,690 | 114,005 | 26% |
| 0.15 | 5 | 49,110 | 83,580 | 33% |

`M_MIN=0.15, k=4` is the knee: ~27% harder than the 0.2/k3 draft, a **credible** ~52,000 NADO/yr forever
tail (vs a too-thin ~37,000 at 0.10), and a firm-but-not-violent early response (28% cut at 10% bonded).

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

`r` is a pure function of **committed state**: `total_bonded_shares·B_MIN` (bonded — the same measure as
`cumulative_weight`) over `total_supply` (`TREASURY_GENESIS + produced − fees` from `totals`). It is read
from the **committed parent state at incorporation**, which is deterministic for the exact reason
`verify_block` already recomputes `cumulative_weight` from live `get_bonded_registry()`: during sequential
incorporation the committed state *is* the block's parent state, and a snapshot node carries full state
as-of its checkpoint — so every node type computes the identical multiplier. It is quantized to whole-percent
buckets and looked up in a **hardcoded integer table** (no runtime float — a last-ULP `math.exp` diff could
fork). Anti-grind: bonding *lowers* the briber's own reward (m shrinks) and a single actor barely moves the
global ratio, and `BOND_RAMP_EPOCHS`(30) + unbonding friction blunt any bond→mine→unbond attempt. (An
optional finalized-epoch lag on `r` could be added for extra caution; not currently needed.)

## Implementation (shipped)

```python
# protocol.py: BOND_ELASTIC_MULT_BPS = [10000, 9764, ... 2398]   # 101 ints, m(pct) in bps, hardcoded

# ops/block_ops.py
def bond_elastic_mult_bps() -> int:
    bonded = total_bonded_shares(get_bonded_registry()) * B_MIN
    t = fetch_totals() or {}
    supply = TREASURY_GENESIS + t.get("produced", 0) - t.get("fees", 0)
    if supply <= 0 or bonded <= 0:
        return BOND_ELASTIC_MULT_BPS[0]                 # r=0 -> full emission (bootstrap)
    return BOND_ELASTIC_MULT_BPS[min(100, (bonded * 100) // supply)]

def get_block_reward(parent_block=None):
    return BASE_SUBSIDY * bond_elastic_mult_bps() // 10000   # flat base, scaled; no fee term, no cap

# verify_block range guard tightened: a block reward > BASE_SUBSIDY is invalid (m<=1).
# genesis.py: carried-forward balances+bonded are added to totals so total_supply is accurate.
# Fee destruction + treasury self-burn already exist (ops/reward_ops); net issuance = reward − fees_destroyed.
```

## Locked decisions

- **Params are FINAL:** `M_MIN=0.15`, `k=4`, `BASE_SUBSIDY=0.1`. Frozen into mainnet genesis. Betanet only
  validates that the live bonded ratio / net issuance behave as modelled — it is not a tuning round.
- **Cadence: `block_time = 10s`** (default). Emission is per-*block*, so coins/day = `BASE · 86400/block_time`
  = **864 NADO/day max** at 10s (315,360/yr), tail ~52,000/yr. block_time is the emission-*rate* lever
  (jointly with BASE); it is local pacing, not consensus, but all nodes must run the same value. The
  per-block hardness (curve, deflation crossover) is cadence-independent — only throughput scales.
- **Denominator:** `total_supply` = `TREASURY_GENESIS + produced − fees` (treasury included; it is a tiny,
  self-burning fraction and excluding it would only make the ratio jitter with treasury flows).
- **NO hard cap, NO halving-to-zero** — rejected (security cliff). Perpetual tail ~0.0166 NADO/block.
- Bonded measure = `total_bonded_shares · B_MIN` (same as `cumulative_weight`); equilibrium self-limits
  ~40% via the `OPEN_BPS`=30% siphon. Raising the equilibrium (lower `OPEN_BPS`) trades against fair-launch
  reach and is a *separate* lane decision, out of scope here.
