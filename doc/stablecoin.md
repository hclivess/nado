# NADO native stablecoin — design draft (`nUSD`)

**Status:** design draft for discussion. Nothing here is implemented. Naming (`nUSD`) is a placeholder.

**Goal (owner's brief).** A NADO-native stablecoin that is *state-of-the-art*, *reliable*, and runs
**without any intervention or interference** — i.e. no admin key, no upgrade multisig, no trusted price
operator, no discretionary "emergency" levers. It must hold value autonomously and survive its own
worst day without a human in the loop.

This doc (1) states the non-negotiables, (2) audits whether the execution node can host it, (3) surveys
the state of the art and picks the design that fits NADO, (4) specifies the architecture, and (5) lists
exactly what has to be built. The hard parts — the oracle, black-swan bad debt, and bootstrap — are
called out honestly, because a stablecoin doc that only lists the happy path is how pegs die.

---

## 1. Non-negotiable requirements

| # | Requirement | Consequence for the design |
|---|---|---|
| R1 | **No admin / no governance keys** | Parameters are fixed at genesis or moved only by the *same 2/3 bonded-stake quorum* that already settles state — never a founder key or multisig. Immutable-by-default (Liquity model), not upgradeable-by-default. |
| R2 | **No trusted price operator** | The price feed must be *decentralized and stake-secured* (validator-attested, slashable), not a Chainlink/operator dependency. |
| R3 | **Autonomous liquidations** | Liquidations must clear **without keepers or auctions being reliably online** — a passive **stability pool** absorbs them instantly, so the system self-heals even if nobody is watching. |
| R4 | **Post-quantum** | Reuse NADO's existing ML-DSA signatures + hash-based zk-STARKs; introduce **no** pairing/EC-based crypto (would break the PQ property). |
| R5 | **Deterministic & re-derivable** | Peg logic runs in the execution layer, whose state root is bonded-quorum-settled on L1 — every node re-derives identical state (same guarantee the shielded pool has). |
| R6 | **Solvency-first** | The coin must **always** be backed. Under-collateralized positions are closed *before* they go bad; residual bad debt is socialized deterministically, never left to accrue silently. |

The single hardest requirement is **R2**: a coin pegged to an *external* unit (USD) fundamentally needs an
external price signal. You cannot conjure USD/NADO on-chain. "Without interference" therefore means *not a
trusted operator* — the best achievable is **decentralized + stake-secured + slashable**, which §5 builds.
If the owner will accept a **non-fiat reference** (peg to a basket, or a RAI-style self-referential target),
oracle reliance drops sharply — see §4.3.

---

## 2. Can the execution node host it? — capability audit

The execution layer (`doc/execution-layer.md`) is a deterministic VM (`execnode/vm.py`) replaying ordered
L1 `blob` payloads, with a bonded-quorum-settled `state_root` and a bridge for value in/out
(`SHIELD_ESCROW` / `BRIDGE_ESCROW` patterns). What it gives us for free is real: **deterministic replay,
L1-ordered execution, quorum settlement, a value-escrow bridge, and an existing bonded-stake + slashing
substrate.** What the *VM* cannot do is the problem.

| Stablecoin needs | VM today (`execnode/vm.py`) | Verdict |
|---|---|---|
| Collateral-ratio / interest math | **No `DIV`** opcode; only `ADD SUB MUL` | ✗ blocker — can't compute `debt·PRECISION/collateral` |
| Iterate positions for liquidation | **No loops / no jumps** — linear programs only | ✗ blocker |
| Time-based accrual, oracle staleness | **No block height/timestamp** injected into `run()` | ✗ blocker |
| Custody NADO collateral; mint/burn the coin | VM only mutates its own `storage` maps — **cannot move coins or mint** | ✗ blocker — needs L1 escrow + a new balance/asset |
| Read a price | **No oracle primitive** | ✗ blocker |
| Compose (call an oracle/AMM contract) | **No cross-contract calls** | ✗ limiting |
| Fixed-point precision | ints are unbounded (good) but no rounding/`DIV` | partial |
| Per-user auth | `CALLER` = the blob tx's L1 sender (ML-DSA-authenticated) | ✓ usable |
| Gas / DoS bound | `GAS_LIMIT` step counter | ✓ |

**Conclusion: the exec node is *not* enough as-is, and the VM is the wrong vehicle.** Forcing a CDP into
this VM would require adding `DIV`, loops, block context, an oracle opcode, cross-contract calls, and native
value custody — at which point you've built a second, less-audited EVM. NADO's own precedent points the
other way: the **shielded pool, bridge, HTLC, and treasury are all native protocol modules**, not VM
contracts, precisely because they touch value and need custody + settlement. The stablecoin belongs in the
**same class**: a native, immutable execution-layer module, written in host code (Python, exact-integer,
fully tested), settled by the bonded quorum — reusing the escrow/settlement/slashing plumbing that already
exists.

(The VM stays useful for *non-value* user logic and can later be given a read-only `PRICE`/`ORACLE` opcode
and `DIV` so third parties can build *around* the stablecoin — but the peg engine itself must be native.)

---

## 3. State of the art — what to copy, what to avoid

| Design | Mechanism | Fit for NADO |
|---|---|---|
| **Liquity v1 (LUSD)** | Immutable, **zero governance**, 110% min collateral ratio, redemptions arbitrage the floor to ~$1, **Stability Pool** absorbs liquidations instantly, one-time borrow fee | **Best base.** The only major stablecoin that is genuinely *governance-free and autonomous* — exactly R1/R3. |
| **Liquity v2 (BOLD)** | Adds **user-set interest rates**, multi-collateral, redemption ordering by rate | Adopt the **user-set rate** idea (market-driven, no governance to set a rate). |
| **crvUSD (LLAMMA)** | **Soft liquidation**: collateral is continuously converted across a specialized AMM band as price falls, avoiding hard liquidation cliffs | Adopt the *concept* (gentler liquidations), but LLAMMA needs deep AMM liquidity NADO won't have at launch — defer. |
| **RAI / Reflexer** | **Non-pegged**, floating *redemption price* steered by an autonomous **PID controller**; "ungovernance" | Adopt the **PID controller** as optional damping (§4.3); the *no-USD-target* variant removes half the oracle problem. |
| **DAI (MakerDAO)** | Over-collateralized but **governance-heavy**, RWA/USDC-backed | **Reject the model** — governance and centralized collateral violate R1. |
| **UST / pure algorithmic** | Mint/burn a volatile sister token, no collateral | **Reject.** Reflexive death-spiral; "reliable" rules this out categorically. |
| **Ethena (USDe)** | Delta-neutral: spot collateral + short perps on **CEXes** | **Reject.** Depends on centralized exchanges and custodians — the opposite of R1/R2. |

**Verdict:** base the design on **Liquity** (immutable, governance-free, stability-pool liquidations),
graft **Liquity-v2 user-set rates**, keep **RAI's PID** as an optional stabilizer, and replace Liquity's
external oracle with a **NADO-native staked oracle** (§5) — that oracle is the real innovation and the thing
that earns "no interference."

---

## 4. Architecture

### 4.1 One-liner

`nUSD` is an **immutable, over-collateralized CDP** native to the execution layer. Users lock **NADO** as
collateral and mint `nUSD` against it; the coin is kept near its target by **redemption arbitrage** (a hard
floor) and a **minimum collateral ratio** (a ceiling), with under-water positions absorbed instantly by a
**Stability Pool**. There are no admin keys and no upgrade path; the only "governance" is the existing 2/3
bonded-stake quorum, and only over a tightly bounded parameter set.

### 4.2 Core objects (native exec-layer state, in the settled `state_root`)

- **Trove** (per borrower): `{owner, collateral_NADO, debt_nUSD, interest_rate}`. Mirrors a Liquity trove.
- **Collateral escrow**: a keyless `nusd_collateral` account (same pattern as `SHIELD_ESCROW`) holding all
  locked NADO. Deposits move NADO in via an L1 `nusd_open`/`nusd_adjust` reserved recipient; withdrawals
  prove against the settled root (same machinery as `unshield`/`bridge_withdraw`).
- **Stability Pool**: `nUSD` deposited by holders that stands ready to absorb liquidations, earning the
  liquidated collateral at a discount. Passive — no keeper needed (R3).
- **nUSD balances**: an execution-layer asset (a `storage` map committed in the root); bridgeable to an L1
  spendable balance via a `nusd_withdraw` reserved recipient, exactly like an unshield exit.
- **Oracle state**: the current stake-weighted median price + last-good-price + a per-round deviation guard
  (§5).

### 4.3 Peg mechanism — pick one target model

Two viable targets; the owner chooses. Both use the same collateral/liquidation machinery.

1. **Hard-ish USD peg (Liquity-style, recommended for familiarity).**
   - **Floor ($1):** anyone may **redeem** 1 `nUSD` for $1-worth of NADO from the *riskiest* troves. If
     `nUSD < $1`, redemption is profitable → buy-and-redeem pressure pushes it back up. Autonomous, no
     intervention.
   - **Ceiling (~$1.10):** minting requires ≥ **MCR** (e.g. 110%) collateral, so `nUSD` is always
     over-backed; borrowers arbitrage a premium by minting and selling.
   - **Needs a NADO/USD price** (the oracle, §5).

2. **Self-referential target (RAI-style, minimal-oracle).**
   - No USD target; a **redemption price** floats and a **PID controller** nudges it to *dampen* `nUSD`'s
     own market volatility. Still needs a NADO/USD price for collateral valuation, but **not** a USD *peg*
     oracle, and it is inherently un-governable. Trade-off: `nUSD` is "stable-ish," not exactly $1 —
     harder to market, easier to defend.

**Recommendation:** ship **Model 1** (hard peg) because "a dollar" is what users want and Liquity proved it
holds without governance; keep **Model 2's PID** as an *optional damping term* on the redemption fee so the
peg is smoother under stress. Do **not** ship a pure-algorithmic (uncollateralized) variant.

### 4.4 Lifecycle (all as L1 reserved-recipient blob txs, ML-DSA-signed, replayed by exec nodes)

- `nusd_open(collateral, debt, rate)` — lock NADO, mint `nUSD`, create a trove; **REQUIRE** resulting ratio
  ≥ MCR at the current oracle price. Exact-integer, native code (no VM `DIV` problem).
- `nusd_adjust` — add/withdraw collateral, mint/repay debt; re-check MCR.
- `nusd_close` — repay all debt, unlock collateral.
- `nusd_deposit_sp` / `nusd_withdraw_sp` — join/leave the Stability Pool.
- `nusd_redeem(amount)` — burn `nUSD`, receive NADO from the lowest-ratio troves at the oracle price (the
  $1 floor).
- `nusd_liquidate(trove)` — permissionless; if a trove is below MCR, its debt is cancelled against the
  Stability Pool and its collateral distributed to depositors (gas-refunded caller as incentive). If the
  Pool is empty, **redistribution** spreads the debt+collateral across other troves (Liquity's backstop) so
  the system never carries un-absorbed bad debt (R6).

Because this is native host code, interest accrual, ratios, and the median all use exact `int` arithmetic
with a fixed `PRECISION` (e.g. `1e18`) and explicit rounding — the things the VM literally cannot express.

---

## 5. The oracle — the crux of "no intervention"

A fiat peg needs an external price; the goal is to source it **without a trusted operator**. NADO already
has the perfect substrate: a **bonded validator set** that stake-weighted-votes on the settled state root
every round, with **slashing** for equivocation. Extend it into a price oracle:

- **Report:** each settlement round, a bonded validator includes a signed `price_NADO_USD` (its own
  observation from public markets) alongside its state attestation. No new actor, no new trust.
- **Aggregate:** the protocol takes the **stake-weighted median** of reports from validators totalling
  ≥ 2/3 of bonded stake (the same quorum that finalizes state). Median resists up to <50%-by-stake liars.
- **Bound (circuit breaker):** the accepted price may move at most `MAX_ORACLE_DEVIATION` per round (e.g.
  ±5%); larger real moves take several rounds. This caps oracle-manipulation profit and flash-crash damage.
- **Slash:** a validator whose report is outside a tolerance band of the accepted median is **slashed**
  (reuse `SLASH_BOND_PENALTY`) — lying costs stake, so honest reporting is the equilibrium.
- **Fallback:** if < 2/3 stake reports in a round, hold the **last good price** and **widen the MCR/redemption
  bands** (fail *safe*, toward over-collateralization) until quorum returns. The system degrades to
  "conservative," never to "unbacked."
- **Staleness:** minting/redemption is paused (borrowers can still repay/add collateral) if the price is
  older than `MAX_ORACLE_AGE` rounds — autonomously, by rule, not by an operator.

This is the state-of-the-art *decentralized-oracle-as-consensus* pattern (cf. Terra's pre-collapse oracle
votes, Chainlink OCR, UMA's optimistic oracle) but reusing NADO's own stake+slashing — so there is **no
external dependency to compromise or shut off**. Its honest limit: it assumes the *bonded majority is
economically honest*, the same assumption already securing finality and the treasury. It does **not** defend
against a >2/3-stake cartel — but such an adversary already controls the chain, so the stablecoin is not the
weakest link.

---

## 6. Reliability & attack analysis (the worst day)

- **Oracle manipulation:** bounded by stake-weighted median + per-round deviation cap + slashing. Attacker
  needs >1/3 stake merely to stall, >1/2 to bias within the band. Profit is capped by
  `MAX_ORACLE_DEVIATION`.
- **Collateral crash (black swan):** MCR (110%+) + instant Stability-Pool absorption + redistribution
  backstop means positions close *before* going underwater; a gap-down beyond one round's deviation cap is
  the residual risk, mitigated by a conservative MCR and a small **protocol surplus buffer** funded by
  borrow/redemption fees (auto-accrued, not spent by anyone).
- **Stability Pool empty:** falls back to trove **redistribution** (debt never orphaned); an emergency
  **Recovery Mode** (Liquity) raises the effective MCR when the *system-wide* ratio dips, all by rule.
- **Congestion / no keepers:** liquidations are permissionless *and* the Stability Pool is passive, so no
  live actor is required (R3). Redemptions are individually profitable, so arbitrage is self-motivating.
- **Post-quantum:** all auth is ML-DSA; all commitments are hash-based; **no** new EC/pairing crypto (R4).
  A private variant reuses the existing STARK shielded pool (§8).
- **Bootstrap (the honest weak point):** a new stablecoin has thin liquidity and no Stability-Pool depth on
  day one, so early liquidations may redistribute rather than absorb, and the peg is loose until a market
  exists. Mitigations: a conservative launch MCR (e.g. 150%→110% only after depth builds), a treasury-seeded
  initial Stability-Pool deposit (a one-time *quorum* action, disclosed), and caps on total `nUSD` minted
  per epoch during ramp. This is a real limitation, not hand-waved.

---

## 7. What has to be built (exec node is not enough → these are the deltas)

1. **Native `nusd` module** (like `execnode/shielded_field.py` + `execnode/state.py` handlers): trove store,
   Stability Pool, redemption/liquidation engine, interest accrual — exact-integer host code, heavily
   property-tested (invariant: `Σ debt ≤ Σ collateral·price/MCR`, `total nUSD == Σ trove debt + SP`).
2. **L1 reserved recipients + escrow**: `nusd_open/adjust/close/redeem/liquidate/deposit_sp/withdraw_sp`
   and a keyless `nusd_collateral` escrow, plus a `nusd_withdraw` exit proven against the settled root —
   all mirroring the existing `shield`/`unshield`/`bridge` plumbing (`ops/transaction_ops.py`,
   `ops/account_ops.py`, `protocol.py` `RESERVED_RECIPIENTS`).
3. **Staked oracle** (§5): a `price_report` field in the settlement attestation, stake-weighted median +
   deviation guard + slashing + fallback, committed into the exec `state_root`.
4. **Client**: a Trove/Stability-Pool tab in the interface (like the Quorum/Shield tabs), 16-lang, with
   liquidation-risk display.
5. **(Optional) VM extensions** for third-party composability only: read-only `PRICE`/`ORACLE` opcode and a
   `DIV` opcode — *not* required for the peg engine itself.
6. **Immutability**: parameters (MCR, fees, deviation cap, PID gains) fixed in `protocol.py`; adjustable
   *only* via the bonded quorum and within hard-coded bounds — never a founder key (R1).

---

## 8. NADO's unique edge — a *private, post-quantum* stablecoin

NADO already ships a hash-based zk-STARK shielded pool. Once `nUSD` exists as an exec-layer asset, it can be
**shielded exactly like NADO** — `nUSD` notes in the same commitment tree, spent with the same join-split
proofs. That yields a **post-quantum, privacy-preserving, autonomous stablecoin** — a combination nothing in
the market has. It should be a stated Phase-2 goal, not an afterthought. (Blocked on the `alghash`
width/audit fix first — see the security notes — since the shielded pool must be sound before it carries a
dollar-denominated asset.)

---

## 9. Open decisions for the owner

1. **Target model:** hard USD peg (§4.3-1, recommended) vs RAI-style self-referential (§4.3-2, less oracle,
   harder to market).
2. **Collateral:** NADO-only at launch (simplest, but reflexive — collateral and gas are the same asset) vs
   multi-collateral later. NADO-only is honest for v1; document the reflexivity risk.
3. **Interest:** user-set rate (Liquity v2, no governance) vs a fixed protocol rate.
4. **Launch MCR & ramp caps** — conservative start, tighten as Stability-Pool depth grows.
5. **Oracle band / slashing tolerance** — the trade-off between manipulation resistance and false-slash risk.
6. **Whether the treasury seeds the initial Stability Pool** (a disclosed one-time quorum action) to make the
   bootstrap peg credible.

---

### Bottom line

The execution node gives us the settlement, escrow, and stake+slashing rails — but **not** the VM
expressiveness — to host a stablecoin, so it must be a **native, immutable module**, not a contract. The
reliable, no-intervention design is a **Liquity-style over-collateralized CDP with stability-pool
liquidations and a stake-secured validator oracle**, optionally damped by a RAI PID, and eventually
shielded for post-quantum privacy. The genuinely hard, non-negotiable engineering is the **oracle** (§5) and
the **bootstrap** (§6) — everything else is well-trodden. Recommend prototyping the native module +
oracle against a testnet fork before committing to parameters.
