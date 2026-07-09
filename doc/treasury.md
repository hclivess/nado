# NADO treasury — a distribution & governance plan (deploy it, don't hoard it)

> **Status: DRAFT / policy proposal.** NADO already *funds* a treasury (10% of every block reward, both
> lanes, accruing to the genesis address — no premine). It has **no distribution or governance framework
> yet**. This doc proposes one, drawing on both the treasuried projects that endured (Dash, Decred, Zcash,
> Polkadot) **and** the treasury-less ones that endured (Bitcoin, Litecoin, Dogecoin, Monero) — and on the
> ones in both camps that died. Numbers here are **tunable starting points**, not final consensus values.

## 0. The thesis (stated honestly)

**A treasury is neither necessary nor sufficient for a coin to stay relevant** — and this doc should not
pretend otherwise. There are decade-long survivors with *no* protocol treasury (Bitcoin, Litecoin, Dogecoin,
Monero, Ethereum), and there are treasuried coins that died anyway. "Relevant coins have treasuries" is a
biased, non-causal observation, not a law (§2.5 lays out the counter-examples and the confounders).

The defensible claim is narrower and conditional: **the one variable a project actually controls is sustained
funded development + distribution, and for a *late, fair-launch, no-premine, no-VC* chain a protocol-native
treasury is the only self-sustaining mechanism available to fund it.** NADO cannot reconstruct Bitcoin's
first-mover Lindy effect or Dogecoin's meme lottery; it *can* choose to have an internal, continuous funding
source for the work that keeps a chain alive. That is a rational bet under NADO's constraints — not a guarantee.

The cost is explicit and must be owned: the treasury is a **~10% tax on emission** (dilution of miners +
stakers) in exchange for that funding mechanism. So the policy has exactly two jobs — **(1) make sure the money
is actually deployed** (the Bismuth failure was hoarding it; a 10% tax that funds nothing is pure dilution),
and **(2) make sure it is deployed well and cannot be captured.** Everything below serves those two.

The two failure modes to tune between:

| Failure | What it looks like | Who did it |
|---|---|---|
| **Hoard-and-stagnate** | Treasury accrues, nothing ships → the 10% is pure dilution, coin fades | Bismuth; Zcash's NU6 lockbox (12% accruing with *no* agreed way to spend) |
| **Overspend-and-burn** | Huge marketing outlay, ~zero attributable ROI, runway panic | Polkadot H1-2024: ~$87M spent, $37M on marketing, vs ~$1.09M revenue |

NADO's history points at the first, so this policy leans toward forcing deployment (quorum-gated + a self-burn)
— but with hard accountability rails so it never becomes the second.

## 1. What NADO has today

- **Funding:** `TREASURY_BPS = 1000` (10.00%) of every block reward, **both lanes**, credited on-L1 to
  `TREASURY_ADDRESS = GENESIS_ADDRESS` (`ops/reward_ops.py`). Fair launch: `TREASURY_GENESIS = 0`, no premine
  — it fills purely block-by-block, exactly like Dash/Decred.
- **Custody:** a single **founder-controlled** ML-DSA (post-quantum) address. Fully centralized today.
- **Governance:** none. No proposals, no voting, no spend rules, no reporting, no anti-hoard leak.
- **A natural electorate already exists:** the **bonded ("savings") lane** — holders with *locked,
  slashable* stake. That is NADO's structural equivalent of Decred tickets / Dash masternodes: skin in the
  game, already tracked with weight + fidelity, already wired into the settlement quorum machinery.

This is a blank canvas with good bones. The plan below turns the founder wallet into a **stake-governed**,
accountable, self-emptying treasury — coins leave it **only** when the bonded stakeholders vote yes, and they
vote **right inside the NADO interface**. No multisig, no admin key, no external governance portal.

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
4. **No privileged custody — the bonded-stake quorum *is* the multisig.** The treasury is a reserved on-chain account spendable only by a passing stake-weighted vote, reusing the primitive NADO already runs (`settlement_justified`, the 2/3-bonded quorum that settles exec roots). Keep timelocks + per-window spend caps so no single passing vote can drain it (Decred's rate limit; Build-Finance was drained for lack of exactly this).
5. **Vote with time-locked, slashable stake — the bonded lane — with an activation delay** (Decred tickets + Hive's anti-flash-capture lock).
6. **Real quorum + supermajority** (Decred: 20% turnout, 60% approval) to block whale capture at low turnout.
7. **Separate the plumbing (fixed in code) from the recipients (kept flexible)** — Polkadot ages better than Zcash's named beneficiaries.
8. **Mandate transparency: public proposals, deliverable reports, clawback** (Zcash), plus on-chain traceability.
9. **Diversify to runway before you need it** — hold operating runway in a stable/liquid form, keep the native token as governance core not payroll; the #1 DAO killer is a 100%-native treasury force-sold in a bear market (Status: $95M→$53M).
10. **Keep the exit hatch: credible fork-ability** (Steem→Hive). Open code, wide stake distribution.
11. **Don't couple the whole scheme to a declining subsidy or an opaque founder** — vest the founder role transparently; add a sunset that re-ratifies the policy.

### 2.5 The honest case: counter-examples, confounders, and why NADO still picks a treasury

*A treasury does not cause relevance.* Two facts kill the naive "survivors have treasuries" argument, and the
policy is stronger for conceding them up front:

- **No-treasury survivors exist.** Bitcoin and Litecoin (first-mover + Lindy / network effects), **Dogecoin**
  (a meme + celebrity attention, with ~zero funded development for years), Ethereum (funded from a *premine
  sale*, not a protocol treasury), and **Monero** (no block-reward treasury — funded by *voluntary* CCS
  donations + an ideological contributor base). Relevance plainly does **not require** a treasury.
- **Treasuried coins died too.** Many chains had a 10% treasury and are gone. A treasury is plainly **not
  sufficient** either.

*And the treasury "successes" are confounded.* Dash is the case most cited for "a treasury keeps even a weak
product alive," but its early distribution was an **instamine** (~1.9M DASH in the first ~2 days from a bug — a
de-facto premine that concentrated supply), and it had a **prominent promoter (Roger Ver)** for a period. Dash's
longevity is over-determined; the treasury is *a* plausible contributor, not an isolated cause. Symmetrically,
Bitcoin/Litecoin/Doge's survival is over-determined by first-mover timing and memetics that a 2026 launch cannot
reproduce.

So the correct question is **not** "do treasuries cause success?" (biased sample, uncontrolled confounders,
unanswerable) but a **decision under NADO's actual constraints**:

> Given a chain that is *late* (no first-mover Lindy), *fair-launch* (no premine/instamine war chest), *no-VC*,
> and *without a meme lottery ticket* — which of the observed funding mechanisms is even **available** to pay
> for sustained development + distribution?

Down the list: first-mover/Lindy — unavailable (we're late). Meme/celebrity — unbuyable and unreliable (Doge).
Premine / foundation endowment — contrary to the fair-launch ethos (NADO chose `TREASURY_GENESIS = 0`). VC —
unavailable/unwanted. Voluntary donations (Monero-CCS) — *possible*, but it works for Monero because of a rare
ideological donor base; fragile and hard to reconstruct on demand. **What's left is a protocol-native treasury.**
It is not "the thing that makes coins win" — it is *the only self-refilling funding lever a fair-launch latecomer
can actually pull.*

That is the honest, objective framing, and it is a stronger argument than the biased one it replaces. We are
**not** claiming a treasury guarantees relevance. We are claiming: (a) sustained funded development/distribution
is the one success factor a project controls; (b) the treasury is the only mechanism available to *us* to fund
it; and (c) the two things that make treasuries backfire — **capture** and **hoarding** — are exactly what the
quorum-gating (§3.3) and the self-burn (§3.2) neutralize. Under those constraints, funding the treasury is
positive-EV with a bounded, engineered downside; *not* funding it leaves a fair-launch latecomer with no way to
pay for the work that every survivor — treasuried or not — needed someone to pay for.

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
  blocks ≈ ~14.4 hours** at the 6 s alpha block time; a monthly ≈ 30-day period is the mainnet target), after payouts, burn
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

### 3.3 Governance — bonded stakeholders vote, in the NADO interface

**No multisig, no founder keys, no committee gatekeeper as the mechanism.** The treasury is spent by a
**stake-weighted vote of the bonded ("savings") lane**, using the quorum primitive NADO *already runs*:
`settlement_justified` — a thing is authorized when the bonded shares attesting it exceed `SETTLE_NUM/SETTLE_DEN`
(2/3) of total bonded stake. A treasury spend is that primitive pointed at the treasury:

1. **Propose** — anyone posts a `treasury_spend` proposal `{recipient, amount, milestone, memo}` (with the
   anti-spam bond). It shows up in the interface for everyone to see.
2. **Vote** — bonded stakers **sign approve/reject** — the identical keyless, fee-exempt attestation NADO uses
   for `settle`/`attest`, PQ-signed with the key already in their wallet.
3. **Execute** — once the attesting bonded shares cross the bar (and the timelock elapses), L1 moves `amount`
   from `TREASURY_ADDRESS` to `recipient`. Integer-deterministic, revert-symmetric, entirely on-chain.

**Voting happens in the NADO interface — that is the whole point.** A new **Quorum tab** (§3.6) makes casting
a treasury vote as easy as sending a coin: open the app, see the open proposals and their live tallies, tap
approve/reject. No CLI, no external governance site, no seed-phrase gymnastics — the same one-tap, PQ-signed
experience as mining or staking. *Governance you must leave the wallet to do is governance nobody does* —
Decred's chronic ~25-31% turnout is partly a UX tax — so NADO's edge is that **the voter and the wallet are the
same screen.**

**Vote weight = bonded stake, with an activation delay.** Newly-bonded weight must age `VOTE_ACTIVATION_EPOCHS`
before it can vote (Hive's fix against flash-borrowed / exchange-custodied capture). The bonded lane is the
right electorate: skin-in-the-game, slashable, already weighted, already wired into the quorum plumbing — and
it keeps *consensus* rule-changes **out** of the money vote (money votes fund work; they never change protocol
rules).

**Threshold (pick one, §5):** reuse **2/3 bonded** (one mental model with settlement/finality) — or a
**quorum + supermajority** (≥ `QUORUM_BPS` turnout AND ≥ `APPROVAL_BPS` yes) if spends should require broad
participation, not just a supermajority by stake. v1 recommendation: 2/3, revisit with data.

**Progressive decentralization is about SCOPE, not custody** — there is no privileged key to ever hand over:
- **Bootstrap:** stake-quorum spending is live from day one with **conservative caps**, and the founder acts
  only as a *proposer, never a spender* — the founder cannot move a coin unless the stake votes yes.
- **Maturing:** widen the per-window cap + proposal scope as turnout grows; optionally add a lightweight
  **grants-review** convention (off-chain vetting, forum record hash-anchored to L1) to raise proposal quality
  — advisory only; the stake vote is always the authority.
- **Steady state:** a fully autonomous, stake-governed account under the rate limit + anti-hoard burn.

### 3.4 Accountability & anti-capture rails (apply from Phase 0)

- **Milestone escrow, nothing upfront.** Funds released only on **accepted deliverables** (Monero CCS). Every
  grant has a public scope, named recipient, milestones, budget, and a completion report; **clawback** on
  non-delivery or license/CoI violation (Zcash).
- **Proposal bond.** A `treasury_spend`/grant request posts a bond (≈5% of the ask), **slashed if rejected**,
  refunded if approved — cheap spam filter (Polkadot).
- **Spend caps + timelock (no privileged keys).** A per-proposal cap and per-window rate limit, plus a timelock
  between a vote passing and the payout so the community can react to a bad proposal. There is no multisig or
  admin key to compromise — the *only* way coins leave the treasury is a passing stake vote (Build-Finance was
  drained precisely because one passed proposal could empty an un-capped vault).
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
| `TREASURY_WINDOW_CAP` | trailing avg + 50% | Decred-style consensus rate limit on total spends per window |
| `QUORUM_BPS` / `APPROVAL_BPS` | 2000 / 6000 | 20% turnout, 60% yes (Decred) |
| `VOTE_ACTIVATION_EPOCHS` | ~ a few days | bonded weight must age before it can vote (anti-flash-capture) |
| `PROPOSAL_BOND_BPS` | 500 (5%) | slashed on rejection |

### 3.6 The Quorum tab (in the NADO interface)

Voting is a first-class wallet feature, not an afterthought — *governance you have to leave the wallet to do is
governance nobody does.* A **Quorum** tab sits beside Wallet / Mine / Savings / Shield / Explorer:

- **Everyone (no stake needed) sees:** the live treasury balance + inflow rate, the anti-hoard burn countdown,
  the full spend history, and every **open proposal with its live tally** — attesting stake vs the quorum bar,
  and time left.
- **Bonded stakers, in one tap:** submit a proposal (posts the bond) and **sign approve / reject** on open
  ones. The tab shows their own bonded weight and exactly how much more stake is needed to reach quorum, then
  PQ-signs the attestation with the wallet key — the same flow as casting a `settle`/`attest`.
- **Accessibility is the whole edge:** if voting isn't as easy as sending a coin, turnout dies (Decred's
  ~25-31%). Localized in all 16 languages like the rest of the interface.

### 3.7 Maintainer grant — the founder's reward is *governed*, not hard-coded

The maintainer/founder takes **no protocol-level cut** and holds **no key to the treasury**. There is no
hard-coded founder tax on the block reward; the treasury stays a keyless `treasury` account and `TREASURY_GENESIS`
stays `0`. Instead, ongoing maintenance is compensated **exactly like any other spend** — a recurring
`treasury_spend` proposal to a **published maintainer address**, re-approved each period by the same **2/3 bonded
quorum** (§3.3), and drawn from the *Core protocol & wallet dev* bucket (§3.1).

- **Guideline size:** about **1% of treasury inflow** — roughly one-tenth of the 10% block-reward cut — as a
  *target*, not a rule. The quorum sets the actual number and can raise, cut, or end it by vote.
- **Why votable beats hard-coded:** for a chain whose entire pitch is credible fairness, a perpetual un-cancellable
  founder tax is the most expensive thing you can add (the Zcash founder-reward lesson, §5). Routing the same ~1%
  through a vote keeps every "no premine / keyless treasury / not a founder" guarantee intact — *even the
  maintainer's pay is community-approved and can be revoked.*
- **Mechanically it already works:** the maintainer address (the genesis address) can only receive treasury coins
  via a passing quorum vote — the founder is a **proposer, never a spender** (§5). A maintainer grant is just that
  path, on a schedule, disclosed here.

## 4. Rollout

1. **Now — doc + model (this change).** Lock the **stake-quorum** model (no multisig); publish the policy + a
   public treasury dashboard; commit to milestone-escrow, no-upfront spending and public reporting.
2. **Anti-hoard burn.** Implement the idle-treasury burn (`TREASURY_BURN_BPS` above `RUNWAY_TARGET`) — the
   smallest change that structurally prevents the Bismuth outcome. Ship + test in isolation.
3. **`treasury_spend` proposal → bonded-stake attestation → execute**, reusing `settlement_justified` + the
   `slash` primitive, with the rate-limit / cap / timelock / activation-delay guardrails. ⚠ Built carefully
   with exhaustive tests and an adversarial review *before real funds flow* — a one-line bug in Decred's
   spend-limit code froze its treasury for months.
4. **The Quorum tab** in the NADO interface — propose + vote in one tap, localized, live tallies.
5. **Widen scope** (caps, an optional grants-review convention) as turnout grows; the treasury then runs
   autonomously under quorum + rate limit + burn. There is no multisig to "retire" — there never was one.

## 5. Open decisions for the owner

- **Threshold model:** reuse **2/3 bonded** (recommended — one primitive with settlement/finality) vs a
  Decred-style **quorum + supermajority** (turnout floor + 60% yes) if broad participation should be required.
- **Burn vs withhold-don't-mint** for anti-hoard (§3.2) — recommend the burn now, migrate later if weak.
- **Electorate breadth:** bonded-stake-weighted only (recommended, reuses the plumbing) vs a hybrid giving
  non-bonded holders or open-lane miners a smaller voice, to soften plutocracy.
- **Founder role — DECIDED:** the founder is a *proposer, never a spender*. The maintainer reward is a
  **recurring, quorum-approved grant** (§3.7), **not** a protocol-level cut — guideline ~1% of treasury inflow,
  votable and revocable by the bonded quorum. The treasury address's coins move **only** via a passing stake
  vote. That transparency is what separates a credible fair launch from a "cash grab" (the Zcash founder-reward
  lesson).
- **Diversification venue:** NADO has no native stable; decide what "runway in a liquid form" means in practice
  (OTC, a bridged stable, or a disciplined DCA-out policy) before the treasury is large.
