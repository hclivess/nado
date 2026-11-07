# Launchpad — a fair launch with an instant market, on our own machinery

> **Status: BUILT (2026-11-07), in `execnode/games/dex.py`, upgraded in place** — operator: "create it now, i think by
> upgrading the existing dex contract and updating it in place, then adding functionalities to the gui". The Launch tab
> is in `static/dex.html`/`dex.js`. What changed from the plan below while building it is in §8. This is the plan for
> [ROADMAP Phase 3](../ROADMAP.md#phase-3--launchpad-the-42).
> **Revised the same day to NADO's philosophy, the vision kept** (operator: "design should be adopted to the nado
> philosophy with the vision kept"): §2a states how; the operator's open questions became decided principles, and
> only parameter values remain (§6).
> It was prompted on 2026-11-07 by a request to deploy
> [higherdotfun/launchpad-template](https://codeberg.org/higherdotfun/launchpad-template) ("maybe we could port it to
> dex? what does it have that the current dex doesnt?"). Every claim about our side cites the code it was read from.

---

## 0. Why not deploy the template

The template is a pump.fun-style launchpad **for Solana**: five Rust/Anchor 0.31.1 programs (bonding curve, PumpSwap
AMM, fees, "Mayhem", donation relay), a TypeScript SDK, a Fastify + Postgres indexer and a Next.js site. NADO has no
Solana runtime, so deployed as-is it would be a Solana launchpad with no connection to NADO. Also:

- the author describes it as unaudited and never run end to end, and parts are reconstructions (PumpSwap
  `create_config` is "static-only"; the fees and donation-relay crates are named `candidate` / `source_proposal`);
- its licence is MIT, but the vendored on-chain code keeps its own licences;
- Codeberg now shows a banner that crypto projects are no longer allowed there, so the repo may disappear.

**What we take from it is the product, not the code:** one-click "create a coin", a bonding curve that is the market
from the first block, graduation into a pool, a launch feed and a coin page with its curve's progress. The contract is
written for the zkVM in zkpy, beside `execnode/games/dex.py`.

## 1. What the DEX already has, and what this adds

| | today | after this |
|---|---|---|
| constant-product AMM, add/remove liquidity, slippage `minOut` | **yes** — `execnode/games/dex.py` | unchanged |
| price chart, markets table, live price sampling | **yes** — `static/dex.js`, `ops/dex_prices.py` (sampler inside `nado.py`) | curves charted from the exec node's trade index (`execnode/dex_trades.py`): every fill at its batch's one price, candles and recent trades on the coin card — BUILT 2026-11-07 |
| cross-chain BTC/ETH/SOL swaps (HTLC order book) | **yes, ours only** — `execnode/games/otc.py`, [`dex-bridge.md`](dex-bridge.md) | unchanged |
| bonding-curve market for a new coin | no | **yes** |
| "create a coin" that is tradeable at once, fair by construction | no — issuing (`asset_create`) and seeding a pool are separate, by hand | **yes** |
| graduation to a pool whose liquidity can never be pulled | no | **yes** |
| launch feed; image and description per coin | no — an asset has only a 128-char `uri` | **yes** |
| a creator's share of trading fees | no — `dex.py` gives 100 % of its 30 bps to liquidity providers | **no, by design** (§2a) |
| first-block sniping, priority, sandwiching | n/a — no curve | **impossible by design**: one uniform price per window (§2a) |

## 2. How it works on NADO

**Create (the creator's two steps, one flow in the UI).** A zkVM call carries exactly one asset (`dex.py` header), and
only a contract's *deployer* may create an asset issued *by* that contract ([`assets.md`](assets.md) §7). So:

1. the creator issues the coin themselves: `asset_create` with a **fixed supply** (`mintable = false`, the default);
2. the same flow calls `launch(...)` on the curve contract, **carrying the whole supply** as the call's value.

The contract cannot read an asset's total supply in-circuit, so fairness is stated from what the settled root proves:
the page shows a coin as a **fair launch** only when the ledger says `mintable == false` and the curve holds
`supply` (100 %). Anything else is shown as what it is. Both facts are provable against the settled root
([`assets.md`](assets.md) §2).

**Trade on the curve.** Constant product over *virtual* reserves: price starts low and rises as the curve sells. `buy`
pays NADO, `sell` pays the coin; both take a limit (`minOut`) and a deadline, like `dex.py`'s swaps — and both clear in
**batches at one price** (the opening window, then each block; §2a).

**Graduate.** When the curve has sold its sellable portion, it graduates — permissionlessly and deterministically,
by whichever trade crosses the threshold. **There are no cross-contract calls** (ROADMAP Phase 2), so the curve cannot
seed a `dex.py` pool. Instead the same contract switches from virtual to *real* reserves and goes on as a
constant-product pool. Nobody holds shares in it, so its liquidity is **locked forever by construction** — the
"LP burned" property launchpads promise, here without a promise. The DEX lists graduated curves beside its own pools.

**After graduation**, the coin's market is that pool, and anyone can still open an ordinary `dex.py` pool for it too.

## 2a. The NADO way — the same vision, none of the extraction

The vision is pump.fun's: **anyone launches a coin in one flow, it has a market from the first block, and when it has
proved demand it graduates into liquidity nobody can pull.** What NADO does not copy is the machine underneath it —
rake to the platform, a creator cut, snipers buying the first block, bundles, a team that can pause or delist. Each of
these follows from a principle the chain already lives by:

| pump.fun / the template | NADO | the principle it follows |
|---|---|---|
| platform fee on every trade | **none** — the contract never profits | "the protocol takes nothing" (ROADMAP §2); `dex.py`, `bet.py` and the banked games never profit |
| creator earns a cut of every trade | **no creator cut.** The creator earns what any early holder earns: they buy in the opening window at the same price as everyone else | no rake by convention; a launch is a market, not a royalty. (ROADMAP §2 would allow an explicit, capped creator share; this design does not use it — a holder's stake aligns the creator with the coin, a fee aligns them with churn) |
| trade fee to the platform | a small trade fee, **burned in NADO** — every launch's volume is a dividend to every NADO holder, paid by not diluting them | "the default sink is burn" (ROADMAP §2) |
| first block goes to whoever pays the most priority / grinds the earliest position | **an opening batch:** every buy placed in the first window (a few blocks) clears at **one uniform price** | leaderless assembly: no producer orders a block, and in-block order is by txid (`ops/block_ops.py`) — which is grindable, so first-in-block must be worth nothing; Track C's per-block batch auction, applied here |
| sandwiches and front-running during the curve's life | **every block a batch:** all of a block's buys and sells on a curve net against each other and clear at that block's single price | no priority-fee auction, no MEV lane (ROADMAP §2 item 5) — a uniform price per block leaves nothing to sandwich |
| per-wallet caps against bots | **none** — fairness comes from the uniform price, not from counting identities | per-identity rules are linear in identities and void (the sybil lessons of 2026-09) |
| free or near-free spam launches | a **creation fee, burned** — and the asset op itself is a paid transaction | no free repeatable transaction (2026-09-27) |
| the team can pause, delist, feature | **no admin, no pause, no curation.** The feed ranks by on-chain facts only (volume, holders, progress to graduation); hiding a coin is the viewer's own setting | no authority — "if a design needs a privileged address to work, it is the wrong design" (ROADMAP §12) |
| "LP burned" is a promise | the graduated pool has **no shares at all** — its liquidity cannot be withdrawn by anyone, by construction | provable, not promised |
| metadata on the team's server | the image is **content-addressed**: the asset's `uri` names its hash, the page shows the picture only if the bytes match. We host nothing and moderate nothing on chain | no authority; what a page shows is checkable |
| "fair launch" is a label | the badge is **what the settled root proves**: supply fixed (`mintable == false`) and 100 % of it in the curve at launch | provable state ([`assets.md`](assets.md) §2) |

**How the batches keep "instant".** A buy is one transaction, as before; its tokens arrive at the block's clearing —
the next block (~7 s), claimed or paid out by the first call that settles the batch. The coin page shows the order as
placed, then filled, with the price it cleared at. The contract settles a batch lazily and in bounded work: the first
call in a later block computes that batch's single price from its net flow (one curve evaluation, not one per order),
and each order is then claimable at that price — the call cost never grows with the number of traders.

## 3. The arithmetic (the part that decides whether it is provable)

Same discipline as `dex.py` (its ARITHMETIC note): reserves held in UNITs (10^8 raw), DIVMODW's divisor in `[1, 2^31)`
and quotient `< 2^32`, every growing quantity bounded below `2^31`, amounts **stated and verified by multiplication**,
`x·y` never formed. Consequences that shape the product:

- **supply ceiling:** a coin's supply in units must stay below 2^31 — about 2.1 billion whole tokens at 8 decimals
  (the template's 1 billion fits); the create form enforces it;
- **virtual reserves** are constants chosen so every intermediate in buy and sell stays in budget at every point of
  the curve, proved in the tests at the curve's two ends and at graduation;
- **dust and first-buyer capture:** the class `dex.py`'s `MIN_SEED` closed (review 2026-09-23) — a minimum trade, and
  rounding always in the pool's favour, never the trader's.

## 4. Fees and anti-rug rules (ROADMAP §2, standing)

- The protocol takes nothing and the creator takes nothing. The contract exposes **`feeBps()` and `feeSink()`** as
  views (`feeSink` = burn), and the wallet shows them before signing. A hidden fee is a bug.
- The curve's trade fee is **burned, in NADO**; after graduation the pool's 30 bps stays in the pool, as in `dex.py`,
  deepening the liquidity every holder trades against.
- **No admin and no authority:** no address can pause, drain or re-price a curve. The creator cannot withdraw curve
  reserves; only graduation changes the market, and only into the locked, share-less pool.
- The creation fee is burned.
- Full trade history readable on-chain; the coin page shows the creator's own holding from the first block, and the
  opening window's fills, all at one price.

## 5. The UI (in the DEX)

A **Launch** tab in `static/dex.html` / `static/dex.js`:

- **feed:** new coins, coins near graduation, graduated — one `/exec/view` index read per poll (the full-storage-per-
  poll rule), never the curve's whole storage;
- **create:** name, symbol, supply (bounded), description, image link → the two-step flow above, with the fee lines;
- **coin page:** price chart (the existing sampler extended to curves), the curve's progress bar to graduation, buy and
  sell with slippage, recent trades, the fair-launch badge with what it proves;
- every string in all 17 languages (the `static/i18n/*.json` sources + `tools/build_i18n.py`).

## 6. Parameters (proposed values; the principles in §2a are decided)

| parameter | proposal | why |
|---|---|---|
| curve trade fee | **1 %, burned** | enough to make wash-trading cost real NADO; all of it returns to every holder by burning |
| creation fee | **10 NADO, burned** | prices spam launches without pricing out a real one |
| opening window | **10 blocks (~70 s)** | long enough that being first is meaningless, short enough to feel live |
| graduation | **when 80 % of the supply has been sold** from the curve | the remainder and the NADO raised become the locked pool |
| virtual reserves | chosen so the curve's start and graduation prices are sane for a 1 billion supply and stay inside the arithmetic budget (§3) at both ends | proved by the tests |
| post-graduation fee | **30 bps, kept in the pool** (as `dex.py`) | no LPs to pay; the pool deepens |
| image | the asset `uri` = a content hash (+ where to fetch it); shown only on a hash match | nothing hosted or moderated by us |

## 7. Plan and size

| step | what | done when |
|---|---|---|
| L0 | the parameter values in §6 | confirmed |
| L1 | `curve.py` contract: `launch`, `buy`, `sell` into the current batch, lazy batch clearing at one price (the opening window, then per block), `claim`, graduation, post-graduation swaps, views (`feeBps`, `feeSink`, an index), the carry rules (`dex.py`'s CARRY_STORAGE note) | proves under the zkVM |
| L2 | tests: unit, a **differential** check (a Python model ≡ the zkVM trace ≡ the page's quote math), and an adversarial suite hunting drain, rounding, first-buyer capture, dust, griefing, and **ordering**: a ground-txid buy in the opening window or any block gets exactly the uniform price, and a sandwich around a buy earns nothing | all green |
| L3 | the Launch tab, the create flow, the coin page; 17 languages | walked as a user, through the real stamper |
| L4 | betanet: a live e2e script (`scripts/live/_launch_e2e.py`, the `_pets_e2e.py` pattern) — create, buy, sell, graduate, trade the pool, with tiny real amounts; a written adversarial review | conserved to the unit, reviewed |
| L5 | listing the curves in the DEX markets and, later, the router (ROADMAP Phase 4) | — |

**Size:** about 1–2 weeks with tests. The contract is the risk, not the UI. **The coins are real:** no path that moves
funds ships before it has been run end to end (ROADMAP §12).

## 8. As built (2026-11-07)

- **In the DEX contract, upgraded in place.** A launch is a pool with `KIND = 1`; its new fields (12–34) sit beside the
  pools', so every existing pool, position and share kept its slots. Graduation turns it into `KIND = 2`: a pool at the
  curve's own price with **no shares** — the existing `swapn`/`swapt` trade it; `join` refuses to seed it (or any curve),
  `exit` has nothing to withdraw. Methods: `prelaunch`, `launch(pid, units, vn)`, `buy`, `sell`, `settle`, `claim`.
- **The creator chooses the scale** (`vn` = the graduation target / 4, within `VN_MIN` 1 NADO .. `VN_MAX` ~671k NADO;
  the page's default target is 2,000 NADO). A fixed 500-NADO virtual reserve made every coin need a 2,000-NADO raise —
  wrong for a small community coin, and untestable live for a few NADO.
- **Batches.** The opening window (10 blocks) is one batch; after it each block is one. The first `buy`/`sell`/`claim`/
  `settle` in a later block clears the batch: buys and sells net at the curve's spot price, the remainder trades through
  the curve, every buyer gets one price and every seller another; a claim pays `amount · total // sum`. A batch closes
  when the cursor merely *differs* from its key, so a carried chain (cursor restarted lower) closes it.
- **Fees.** Native NADO has no burn address (removed from the protocol), so the NADO fees — the 10-NADO creation fee
  and 1 % of every buy — are **sealed**: the contract keeps them, no method pays them out, `FEEB` counts them in public.
  A sell's 1 % is burned in the coin (`ABURN`). The creator and the protocol take nothing.
- **Three approvals to launch.** Issue the coin (fixed supply), pay the fee (`prelaunch`, reserving the id), send the
  supply (`launch`) — the wallet's one-approval follow-up (`opts.then`) is value-free by design (wallet audit) and two of
  these carry value. The order strands nothing; the page reads each step's completion from the chain.
- **Images** are `ipfs://` links shown through the NFT host's gateway (content-addressed). Upload from the DEX page
  needs `/upload` and `/ipfs/` routed on dex.nadochain.com — an nginx change waiting for the operator's yes.
- **In-block ordering.** A gated reorder by `hash(set digest, txid)` was scoped (2026-11-07) and NOT shipped: the
  mempool is shared in a leaderless chain, so a sender can grind a txid against the known set (≈N tries to go first, N²
  to sandwich), and no in-block order stops a sandwich across two blocks. The operator chose batches instead: the
  ordinary AMM pools now clear one batch per block too (dex.py SWAPS, ROADMAP Track C), as the launchpad always did.
- **Tests:** `tests/test_the_dex_launchpad_clears_every_batch_at_one_price_and_graduates_into_locked_liquidity.py`
  (money: one price per batch vs an independent model, solvency, fees, graduation, carry); every launchpad method is
  proven by the Stwo prover (`tests/test_a_stwo_proof_of_contract_execution_…`, which records it);
  `tests/test_the_dex_launch_tab_quotes_what_the_contract_pays_and_speaks_every_language.mjs` (the page's quote equals
  the contract's payout; 17 languages); the live run is `scripts/live/_launch_e2e.py`.
