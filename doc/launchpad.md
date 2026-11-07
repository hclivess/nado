# Launchpad — a fair launch with an instant market, on our own machinery

> **Status: DESIGN — nothing here is built.** This is the plan for [ROADMAP Phase 3](../ROADMAP.md#phase-3--launchpad-the-42).
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
| price chart, markets table, live price sampling | **yes** — `static/dex.js`, `ops/dex_prices.py` (sampler inside `nado.py`) | curves sampled too |
| cross-chain BTC/ETH/SOL swaps (HTLC order book) | **yes, ours only** — `execnode/games/otc.py`, [`dex-bridge.md`](dex-bridge.md) | unchanged |
| bonding-curve market for a new coin | no | **yes** |
| "create a coin" that is tradeable at once, fair by construction | no — issuing (`asset_create`) and seeding a pool are separate, by hand | **yes** |
| graduation to a pool whose liquidity can never be pulled | no | **yes** |
| launch feed; image and description per coin | no — an asset has only a 128-char `uri` | **yes** |
| a creator's share of trading fees | no — `dex.py` gives 100 % of its 30 bps to liquidity providers | **operator's decision** (§6) |

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
pays NADO, `sell` pays the coin; both take `minOut` and a deadline, like `dex.py`'s swaps.

**Graduate.** When the curve has sold its sellable portion, it graduates — permissionlessly and deterministically,
by whichever trade crosses the threshold. **There are no cross-contract calls** (ROADMAP Phase 2), so the curve cannot
seed a `dex.py` pool. Instead the same contract switches from virtual to *real* reserves and goes on as a
constant-product pool. Nobody holds shares in it, so its liquidity is **locked forever by construction** — the
"LP burned" property launchpads promise, here without a promise. The DEX lists graduated curves beside its own pools.

**After graduation**, the coin's market is that pool, and anyone can still open an ordinary `dex.py` pool for it too.

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

- The protocol takes nothing. The contract exposes **`feeBps()` and `feeSink()`** as views, and the wallet shows them
  before signing. A hidden fee is a bug.
- Default sink is **burn**. A creator share, if the operator wants one, is explicit, capped and shown (§6).
- **No admin and no authority:** no address can pause, drain or re-price a curve. The creator cannot withdraw curve
  reserves; only graduation changes the market, and only into the locked pool.
- A creation fee, burned, to price spam (§6).
- Full trade history readable on-chain; the coin page shows the creator's own holding from the first block.

## 5. The UI (in the DEX)

A **Launch** tab in `static/dex.html` / `static/dex.js`:

- **feed:** new coins, coins near graduation, graduated — one `/exec/view` index read per poll (the full-storage-per-
  poll rule), never the curve's whole storage;
- **create:** name, symbol, supply (bounded), description, image link → the two-step flow above, with the fee lines;
- **coin page:** price chart (the existing sampler extended to curves), the curve's progress bar to graduation, buy and
  sell with slippage, recent trades, the fair-launch badge with what it proves;
- every string in all 17 languages (the `static/i18n/*.json` sources + `tools/build_i18n.py`).

## 6. Decisions for the operator (before any code)

1. **Creator share:** none (everything burned or kept in the pool), or a capped share (e.g. at most 0.5 % of each
   curve trade)? `dex.py` today pays no one but its liquidity providers.
2. **Curve fee** (e.g. 1 %) and its split; the **fee after graduation** (stays in the locked pool, deepening it, or
   burned).
3. **Creation fee** (burned) — the spam price.
4. **Graduation threshold** — how much of the supply the curve sells first.
5. **Images:** where a coin's picture lives (the asset's `uri` pointing off-chain, or hosted by us — which makes us a
   moderator of what is shown).

## 7. Plan and size

| step | what | done when |
|---|---|---|
| L0 | the decisions in §6 | answered |
| L1 | `curve.py` contract: `launch`, `buy`, `sell`, graduation, post-graduation swaps, views (`feeBps`, `feeSink`, an index), the carry rules (`dex.py`'s CARRY_STORAGE note) | proves under the zkVM |
| L2 | tests: unit, a **differential** check (a Python model ≡ the zkVM trace ≡ the page's quote math), and an adversarial suite hunting drain, rounding, first-buyer capture, dust and griefing | all green |
| L3 | the Launch tab, the create flow, the coin page; 17 languages | walked as a user, through the real stamper |
| L4 | betanet: a live e2e script (`scripts/live/_launch_e2e.py`, the `_pets_e2e.py` pattern) — create, buy, sell, graduate, trade the pool, with tiny real amounts; a written adversarial review | conserved to the unit, reviewed |
| L5 | listing the curves in the DEX markets and, later, the router (ROADMAP Phase 4) | — |

**Size:** about 1–2 weeks with tests. The contract is the risk, not the UI. **The coins are real:** no path that moves
funds ships before it has been run end to end (ROADMAP §12).
