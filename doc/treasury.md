# NADO treasury — a distribution & governance plan (deploy it, don't hoard it)

> **Status: DRAFT / policy proposal.** NADO already *funds* a treasury (10% of every block reward, both
> lanes, accruing to the genesis address — no premine). It has **no distribution or governance framework
> yet**. This doc proposes one, modelled on the treasuries that kept 2014-era projects alive for a decade
> (Dash, Decred, Zcash, Polkadot, Monero-CCS) — and against the ones that died. Numbers here are **tunable
> starting points**, not final consensus values.

## 0. The thesis (and the Bismuth lesson)

A treasury is not a war chest to *protect* — it is fuel to *burn on growth*. The coins that are still
relevant a decade after launch are, without exception, the ones that **spent their treasury continuously** on
development, marketing, integrations and liquidity. The ones that pumped once and faded either had no
recurring funding at all (the 2017 ICO cohort: ~46% dead, raised-then-drifted) **or had a treasury and sat on
it.** Bismuth had the funding and under-deployed it; the result was a technically-fine chain that went quiet.

So the single most important property of this policy is a **structural bias toward spending** — an
anti-hoard mechanism wired into the protocol, not into good intentions. Everything else (governance,
accountability, diversification) is about spending *well*, but the first job is to spend *at all*.

The two failure modes to tune between:

| Failure | What it looks like | Who did it |
|---|---|---|
| **Hoard-and-stagnate** | Treasury accumulates, nothing ships, coin pumps once → irrelevance | Bismuth; Zcash's NU6 lockbox (12% accruing with *no* agreed way to spend) |
| **Overspend-and-burn** | Huge marketing outlay, ~zero attributable ROI, runway panic | Polkadot H1-2024: ~$87M spent, $37M on marketing, vs ~$1.09M revenue |

NADO's history points at the first one, so this policy leans toward forcing deployment — but with hard
accountability rails so it never becomes the second.

## 1. What NADO has today

- **Funding:** `TREASURY_BPS = 1000` (10.00%) of every block reward, **both lanes**, credited on-L1 to
  `TREASURY_ADDRESS = GENESIS_ADDRESS` (`ops/reward_ops.py`). Fair launch: `TREASURY_GENESIS = 0`, no premine
  — it fills purely block-by-block, exactly like Dash/Decred.
- **Custody:** a single **founder-controlled** ML-DSA (post-quantum) address. Fully centralized today.
- **Governance:** none. No proposals, no voting, no spend rules, no reporting, no anti-hoard leak.
- **A natural electorate already exists:** the **bonded ("savings") lane** — holders with *locked,
  slashable* stake. That is NADO's structural equivalent of Decred tickets / Dash masternodes: skin in the
  game, already tracked with weight + fidelity, already wired into the settlement quorum machinery.

This is a blank canvas with good bones. The plan below turns the founder wallet into a governed, accountable,
self-emptying treasury without a hard fork on day one.

## 2. What the survivors actually did (and the lessons NADO copies)

**Dash** — 10% (now 20%) of block reward; **masternodes** vote monthly; approved proposals paid in a
**superblock**; unspent budget is **never minted** (use-it-or-lose-it). *Kept it relevant by* funding Dash
Core Group, aggressive marketing, merchant adoption. *Weakness:* plutocratic, self-dealing (masternodes voted
themselves a bigger cut), and famously weak ROI accountability ("nearly zero" measurable return, no contracts,
proposals "drop off the radar").

**Decred** — 10% treasury; spending gated **in consensus** by stakeholder **ticket votes** on `tspend`
transactions, under a **rate limit** (spend per ~24-day window ≤ trailing ~4.8-month average + 50%). *Kept it
relevant by* a **contractor model** (monthly invoices, DCC clearance) funding DCRDEX, wallets, Politeia,
marketing — genuinely self-sustaining. *Weakness:* low turnout (~25-31%), slow throughput, and a **consensus
bug in the spend-limit code once froze the entire treasury to ~0.15 DCR for months** (test everything).

**Zcash** — 20% dev fund split by protocol to ECC / Foundation / **Major Grants**; **committee + advisory
panel** governance; **quarterly reports + clawback** for violations; a **4-year sunset** forcing
re-ratification. *Weakness:* naming fixed beneficiaries in code invites "who deserves it" fights; the NU6
**lockbox hoards 12% with no disbursement mechanism** — the anti-pattern.

**Polkadot** — treasury fed by inflation + fees + slashes; **on-chain referenda** (OpenGov) per spend;
**bounties** delegate recurring programs to curators; **proposal bond** slashed on rejection; and the headline
anti-hoard device: **a fixed % of unspent treasury is BURNED every spend period** (1%/period Polkadot,
0.2%/period Kusama) so idle capital actively shrinks. *Weakness:* "spend before it burns" can drive rushed,
low-ROI proposals.

**Monero (CCS)** — not a block-reward treasury, but the **accountability gold standard**: milestone
proposals, **nothing paid upfront**, funds held in **multisig escrow** and released per accepted milestone,
every tx public. This is the delivery discipline NADO adopts on top of a block-reward treasury.

### The distilled principles NADO adopts

1. **Fund from the continuous block-reward stream** (already done) — never a lump sum. ✅
2. **Wire in anti-hoard spending pressure from day one** (Polkadot burn). *This is the Bismuth fix.*
3. **Gate spending on milestones with escrow; pay nothing upfront** (Monero CCS).
4. **Custody in multisig with timelocks + per-window spend caps** (Decred rate limit; Build-Finance was drained because it had none).
5. **Vote with time-locked, slashable stake — the bonded lane — with an activation delay** (Decred tickets + Hive's anti-flash-capture lock).
6. **Real quorum + supermajority** (Decred: 20% turnout, 60% approval) to block whale capture at low turnout.
7. **Separate the plumbing (fixed in code) from the recipients (kept flexible)** — Polkadot ages better than Zcash's named beneficiaries.
8. **Mandate transparency: public proposals, deliverable reports, clawback** (Zcash), plus on-chain traceability.
9. **Diversify to runway before you need it** — hold operating runway in a stable/liquid form, keep the native token as governance core not payroll; the #1 DAO killer is a 100%-native treasury force-sold in a bear market (Status: $95M→$53M).
10. **Keep the exit hatch: credible fork-ability** (Steem→Hive). Open code, wide stake distribution.
11. **Don't couple the whole scheme to a declining subsidy or an opaque founder** — vest the founder role transparently; add a sunset that re-ratifies the policy.

## 3. NADO's plan

### 3.1 Allocation — where deployed funds go (targets, not rigid)

Percentages are of **deployed** budget per period; the reserve line is the diversified runway that is *not*
deployed. These are starting targets to tune from observed results.

| Bucket | Target | What it buys |
|---|---:|---|
| **Core protocol & wallet dev** | 30% | node, exec layer, prover, interface, audits, PQ maintenance |
| **Growth & marketing** | 20% | content, listings PR, ambassadors, events — **ROI-throttled** (see §3.4) |
| **Integrations & liquidity** | 20% | exchange/wallet integrations, market-making, bridges, payment rails |
| **Ecosystem grants** | 15% | third-party builders, tooling, research (compete-and-report) |
| **Infrastructure & ops** | 10% | seed relays, explorers, public RPC, faucets, CI, monitoring |
| **Community & bounties** | 5% | bug bounties, translations, docs, support, moderation |

Marketing and integrations are deliberately large: the survivors' edge was **distribution**, and under-marketing
is precisely the Bismuth mistake. But every marketing dollar is gated by attribution (§3.4).

### 3.2 Anti-hoard — the core mechanism (the Bismuth fix)

Two workable designs; NADO should ship **one** and can migrate later:

- **(Recommended, minimal-change) Idle-treasury decay + burn.** Each *spend period* (proposal below: **8,640
  blocks ≈ ~1 day** at alpha block time; a monthly ≈ 30-day period is the mainnet target), after payouts, burn
  a fixed fraction of the treasury balance **above a runway target** `R_target`:

  ```
  burn = BURN_BPS/10000 × max(0, treasury_balance − R_target)      # R_target = N periods of avg deployment
  ```

  Start `BURN_BPS ≈ 100` (1%/period, Polkadot's value) and `R_target ≈ 12` periods of runway. Idle capital
  above ~a year of runway visibly shrinks, so hoarding has a cost and governance is pressured to deploy — but
  a sensible runway is never punished. Keeps the existing "mint-to-address" accrual; adds only a periodic burn
  in the reward/settlement path.

- **(Alternative, larger change) Withhold-don't-mint (Dash model).** Stop crediting the 10% to a standing
  balance; instead only *mint* treasury coins when a proposal is actually paid, up to a per-period cap. Cleanest
  possible anti-hoard (nothing ever accumulates), but a deeper consensus change to the reward split + a
  superblock-style payout. Recommended as a **Phase-2** migration if the burn proves too weak.

Either way the property is the same and non-negotiable: **an un-deployed treasury does not just sit there.**

### 3.3 Governance — who decides, in phases (progressive decentralization)

Legitimacy is earned by *giving power away on a visible schedule* — the opposite of the Zcash founder-reward
optics problem. Each phase is a real milestone, announced up front.

- **Phase 0 — Steward (now → mainnet).** Founder-held, but immediately: (a) move custody to a **published
  multisig** (not a single key); (b) publish **this policy** + a public treasury address dashboard; (c) turn
  on the **anti-hoard burn** so even the bootstrap phase cannot hoard; (d) every spend gets a **public
  proposal + a deliverable report**, Monero-CCS style, **paid only on milestone completion from escrow**. No
  upfront payments, ever — including to the founder.
- **Phase 1 — Advisory + public proposals.** A small **grants review committee** (with conflict-of-interest
  caps like Zcash's MGRC) vets public proposals; the community discusses on a Politeia-style forum whose
  record is **hash-anchored to L1** (tamper-evident without putting every comment on-chain). Multisig still
  executes, now bound to committee recommendations.
- **Phase 2 — On-chain bonded-lane voting.** Treasury spends become **`treasury_spend` transactions gated by a
  vote of the bonded ("savings") lane** — NADO's tickets. Vote weight = bonded weight; **newly-bonded weight
  must age `VOTE_ACTIVATION_EPOCHS` before it can vote** (Hive's anti-flash/anti-exchange-capture lock). A
  spend passes only with **≥ QUORUM_BPS turnout AND ≥ APPROVAL_BPS yes** (start 20% / 60%, Decred's bar). The
  **Decred rate limit** applies in consensus: total spends in any window ≤ trailing-average + 50%, so no
  passed proposal can drain the vault.
- **Phase 3 — Autonomous.** The multisig is retired; the treasury is a fully on-chain account spendable only
  by passing `treasury_spend` votes under the rate limit + burn. Founder power is fully vested away.

The bonded lane as electorate is deliberate: it reuses the **skin-in-the-game, slashable, already-weighted**
class and the existing settlement/quorum plumbing — and it keeps *consensus* rule-changes **out** of the money
vote (money votes fund work; they never change protocol rules).

### 3.4 Accountability & anti-capture rails (apply from Phase 0)

- **Milestone escrow, nothing upfront.** Funds released only on **accepted deliverables** (Monero CCS). Every
  grant has a public scope, named recipient, milestones, budget, and a completion report; **clawback** on
  non-delivery or license/CoI violation (Zcash).
- **Proposal bond.** A `treasury_spend`/grant request posts a bond (≈5% of the ask), **slashed if rejected**,
  refunded if approved — cheap spam filter (Polkadot).
- **Spend caps + timelock + multisig.** Per-proposal cap; a timelock delay between approval and payout so the
  community can react; multisig custody until Phase 3 (Build-Finance was emptied for lack of exactly this).
- **Rate limit in consensus (Phase 2+).** Trailing-average + 50% ceiling — drain-resistant. ⚠ **Test it
  exhaustively**: Decred's rate-limit code *froze its whole treasury for months* over a one-line
  bootstrap-vs-history bug. Consensus spend limits are powerful and unforgiving.
- **Diversification rule, pre-committed.** Codify holding **1–2 years of operating runway in a stable/liquid
  form** (as/when NADO has liquidity or a stable venue), converting on a **schedule/rules basis while price is
  healthy** — never improvised in a panic (the community always calls stablecoin sales "heresy," so pre-commit
  the rule). Native token stays the governance core, not payroll.
- **ROI throttle on marketing.** Scale ad/influencer spend only *after* attribution shows return — the explicit
  guard against Polkadot's $37M-for-1.5%-coverage outcome.
- **Radical transparency.** Public treasury dashboard, quarterly reports (plan / execution / finances), all
  payouts on-chain and traceable. A neutral "did it deliver?" tracker (Dash Watch was the idea; Dash's lack of
  teeth was the failure).
- **Fork-ability preserved.** Open code + wide stake distribution so capture is never final (Steem→Hive).

### 3.5 Draft parameters (all tunable; set in `protocol.py` when implemented)

| Param | Draft value | Note |
|---|---|---|
| `TREASURY_BPS` | 1000 (10%) | unchanged; matches Dash/Decred |
| `TREASURY_BURN_BPS` | 100 (1% / period) | idle-treasury burn above runway (Polkadot value) |
| `TREASURY_RUNWAY_TARGET` | ~12 periods of avg deployment | balance below this is never burned |
| `TREASURY_SPEND_PERIOD` | ~30 days (blocks) | payout/burn cadence (superblock analogue) |
| `TREASURY_WINDOW_CAP` | trailing avg + 50% | Decred-style consensus rate limit (Phase 2) |
| `QUORUM_BPS` / `APPROVAL_BPS` | 2000 / 6000 | 20% turnout, 60% yes (Decred) |
| `VOTE_ACTIVATION_EPOCHS` | ~ a few days | bonded weight must age before it can vote (anti-flash-capture) |
| `PROPOSAL_BOND_BPS` | 500 (5%) | slashed on rejection |

## 4. Rollout

1. **Now (docs + custody):** publish this policy; move the treasury to a **published multisig**; stand up a
   public treasury dashboard; commit to **milestone-escrow, no-upfront** spending and public reporting.
2. **Anti-hoard first:** implement the **idle-treasury burn** (`TREASURY_BURN_BPS` above `RUNWAY_TARGET`) —
   the smallest change that structurally prevents the Bismuth outcome. Ship + test in isolation.
3. **Public proposals + committee** (Phase 1), forum record L1-anchored.
4. **On-chain `treasury_spend` voting by the bonded lane** (Phase 2): quorum + supermajority + activation
   delay + **consensus rate limit** — with exhaustive tests *before* real funds flow (remember Decred).
5. **Retire the multisig** (Phase 3) once on-chain governance is proven.

## 5. Open decisions for the owner

- **Burn vs withhold-don't-mint** for anti-hoard (§3.2) — recommend the burn now, migrate later if weak.
- **Electorate:** bonded-lane stake-weighted (recommended, reuses existing plumbing) vs a hybrid with a
  one-address-one-vote component to soften plutocracy.
- **Founder vesting:** publish the schedule on which founder/steward control is handed to governance — doing
  this *transparently and early* is what separates a credible fair-launch treasury from a "cash grab" narrative.
- **Diversification venue:** NADO has no native stable; decide what "runway in a liquid form" means in practice
  (OTC, a bridged stable, or simply a disciplined DCA-out policy) before the treasury is large.
