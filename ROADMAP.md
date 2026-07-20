# NADO roadmap — building the demand machine

> **Purpose.** This document takes an outside analysis of *where Solana's app revenue actually comes
> from* (Q1 2026, $342.2M in app revenue) and turns it into a build plan for NADO. It is a **strategy
> and sequencing** doc: what we have, what the revenue-generating chains have that we don't, in what
> order to build it, and which parts we deliberately refuse to copy.
>
> Status legend used throughout: **BUILT** (in code, tested) · **PARTIAL** (some of it exists) ·
> **DESIGN** (doc only, no code) · **ABSENT** (nothing).

---

## 0. The finding, in one paragraph

Of Solana's $342.2M Q1 2026 app revenue, **~78% is three flavors of the same thing — speculative
token trading**: launchpads ($144M, 42%; Pump.fun alone $124.7M), trading terminals/bots ($79M;
Axiom alone $42.4M), and wallet swap widgets ($49.6M; Phantom $23.4M). All seven apps that cleared
$100M cumulative revenue across 2025 are trading infrastructure. DEXs/AMMs (Jupiter ~$14–16M,
Raydium, Orca, Meteora ~$9M) are the plumbing beneath that flow. Lending (Kamino, Save, Drift),
liquid staking (Jito, Sanctum, Marinade), and RWA (BUIDL, >$2B market cap) are real but an order of
magnitude smaller in fees.

**The conclusion for us:** a chain's economy is not bootstrapped by having *applications*. It is
bootstrapped by having **assets people want to trade** and **the shortest possible path between a
user and a trade**. When this document was written NADO had 21 deployed contracts and no tradeable asset
other than NADO itself. Phase 1 below has since closed the chain half of that gap; everything downstream
of it is still open.

---

## 1. Honest gap analysis — the Solana machine vs. NADO today

| Layer | Solana Q1'26 | NADO status | Blocker |
|---|---|---|---|
| **Fungible asset primitive** | SPL token | **BUILT** (was ABSENT) — state-level ledger committed in the settled root, derived ids a contract computes in-circuit, 5 zkVM opcodes, asset-denominated call value ([`doc/assets.md`](doc/assets.md)). Open: wallet UI, settlement-by-proof | Keystone. Was blocking everything below. |
| **Launchpad** | $144M (42%) — Pump.fun, Bags, LetsBonk | **ABSENT** | Needs asset primitive |
| **Trading terminals** | $79M — Axiom, Photon, BullX, GMGN, Trojan | **ABSENT** — no charts, no indexer, no price history | Needs markets + indexer |
| **Wallet swaps** | $49.6M — Phantom | **PARTIAL** — wallet has send/receive/stake/deploy/HTLC lock, but the "swap" UI is a raw HTLC lock/claim/refund form: no pair, no price, no counterparty discovery | Needs AMM + router |
| **AMM / DEX** | Raydium, Orca, Meteora, Pumpswap | **DESIGN** — `doc/dex-bridge.md` specifies an on-chain order book + atomic VM swap; zero lines of it implemented | Needs asset primitive |
| **Aggregator/router** | Jupiter, $812B routed in 2025 | **ABSENT** | Needs ≥2 venues |
| **Liquid staking** | Jito, Sanctum, Marinade | **ABSENT** — bonding is BUILT (`bond`/`unbond`, `B_MIN`, slashing, bond-elastic emission) but there is no derivative token, no delegation | Needs asset primitive + delegation |
| **Lending** | Kamino, Save, Drift, Sentora | **ABSENT** — no collateral/liquidation/interest code, and **no oracle** except the app-specific sports resolver | Needs assets + oracle |
| **Stablecoin** | USDC/USDT rails | **DESIGN** — `doc/stablecoin.md` (nUSD, CDP + stability pool + stake-secured oracle), explicitly "nothing here is implemented" | Needs assets + oracle |
| **RWA** | >$2B, +43% QoQ | **ABSENT** | Needs everything above + counterparties |
| **Bridge / on-ramp** | CEX listings + wrapped everything | **PARTIAL** — HTLC atomic swap is BUILT and tested on the NADO leg (`tests/test_htlc.py`, 9 tests); no counterparty-chain client, no order book, no listing | The real gate on all demand |
| **MEV / block engine** | Jito | **N/A by design** — fees are burned, there is no priority-fee auction | See §2 |

**What we have that they don't** (and should not throw away):
21 provable game contracts on a permissionless zkVM (`execnode/games/`, 788 KB — banked games with a
real 1% edge, two parimutuel markets, a full NFT with marketplace and escrowed bids in `pets.py`), a
shielded pool, post-quantum signatures throughout, HTLC without a custodian, a working forum, and a
faucet. That is a *product* layer with no *market* layer under it.

---

## 2. The design tension we must resolve first

Solana's machine is **rake**. Every dollar in §0 is somebody's cut of somebody else's trade.

NADO's design is the opposite on purpose:
- **Protocol fees are destroyed**, credited to no one (`ops/account_ops.py:41-42`); block reward is
  flat and bond-elastic, explicitly *not* fee-weighted.
- **Apps are rake-free by convention** — `bet.py` "never mints, never profits"; holdem "no house, no
  dealer"; pets' mint/train/build fees are **burned**, not captured; banked games' edge accrues to
  whichever *user* opened the table, not to us.
- **No authority** — no address can freeze, censor, or seize.

We are not abandoning that. The resolution, and it should be treated as a standing rule for
everything in this roadmap:

> **The protocol takes nothing. Apps may charge, must declare it on-chain, and the default
> app fee split is `burn` — not a company treasury.**

Concretely:
1. **No protocol rake, ever.** No treasury cut of exec-layer calls. Treasury stays emission-funded.
2. **Every fee-charging contract exposes `feeBps()` and `feeSink()` as ABI view methods**, and the
   wallet/explorer renders them before the user signs. A hidden rake is a bug.
3. **Default sink is burn.** A burned fee is a dividend to every holder, paid pro-rata by not
   diluting them — the no-authority analogue of "revenue." Where a creator cut makes sense (a
   launchpad creator's share), it is explicit, capped, and visible.
4. **The chain metric we optimize is not "app revenue," it is `fees burned + volume settled`.**
   See §10. Copying Solana's *numbers* would mean copying its extraction; we copy its *machine*
   and let the value land on holders instead of on an app company.
5. **No priority-fee auction, no MEV lane.** But note: today a block producer still chooses intra-block
   ordering, so sandwiching an AMM would be possible. Fair ordering becomes a *requirement* the moment
   an AMM exists — see Track C.

---

## 3. Critical path (the one-sentence version)

> **Asset primitive → AMM → launchpad → router → wallet swap → terminal.**
> Everything else (LST, lending, stablecoin, RWA) hangs off that spine and is worth an order of
> magnitude less. Nothing on the spine can start before the asset primitive exists.

---

## Phase 1 — The asset primitive (the keystone) — **LEDGER + OPCODES BUILT**

**Goal:** anyone can create a fungible asset on the exec layer, hold it, and transfer it, with the
wallet and explorer treating it as a first-class thing.

> **Status.** The chain half is done and tested — see [`doc/assets.md`](doc/assets.md) and
> `tests/test_assets.py` (16 checks, incl. one real proof). Built: the state-level ledger, committed in
> the settled root; derived asset ids (`hashn([issuer_digest, seed])`) a contract can compute in-circuit;
> five zkVM opcodes (`ASEL`/`AMINT`/`ABURN`/`ABAL`/`ACTX`) with AIR constraints and assembler + zkpy
> wrappers; asset-denominated call value with exact refund-on-revert; all-or-nothing staging across the
> native and asset ledgers; the blob ops and `/exec/assets`. Two gaps still open and named:
> **settlement-by-proof for asset calls** (the epoch prover refuses them rather than proving something
> false), and the **wallet/explorer UI**.
>
> One AIR bug this shook out and is worth remembering: `_LOAD_OPS` in `vm_circuit.py` was documentation
> while the register-hold constraint hardcoded its own copy of the list. A load op missing from the
> hardcoded copy is *silently unprovable* — every proof of a program using it fails composition with no
> hint why. It is now derived from the one list.

**The design decision that was made:** contract-level standard vs. state-level primitive.

- *Option A — a standard contract* (ERC-20 shaped, one deploy per asset, balances in contract
  storage). Zero consensus change, ships fastest, matches how `pets.py` already implements a full
  NFT + marketplace inside one contract. Downside: every asset is a separate cid, cross-contract
  composition means calls into other contracts, and the wallet must discover assets by indexing.
- *Option B — a state-level asset ledger* (`state.assets[(asset_id, addr)]`, with `mint`/`transfer`
  blob ops next to the existing `deploy/call/bridge_withdraw/field_transfer`). Composes natively with
  `PAY`, makes wallet/explorer support trivial, and lets an AMM move both legs in one transition
  (which `doc/dex-bridge.md` §7 already calls the "atomic VM swap"). Downside: touches
  `execnode/state.py` op dispatch and the settled-root layout, i.e. a state-format change.

**Chosen: B.** The exec state root is sparse and already carries multiple namespaces; adding an asset
ledger now is far cheaper than retrofitting one after liquidity has settled into a hundred mutually
incompatible token contracts. Full rationale and the resulting design: [`doc/assets.md`](doc/assets.md).

**Deliverables**
- ~~`execnode/state.py`: `assets` ledger + `asset_create`/`asset_transfer`/`asset_burn`/`asset_mint`/
  `asset_renounce` blob ops, supply conserved and staged all-or-nothing with the native ledger.~~ **done**
- ~~zkVM: an asset-aware pay path so contracts can escrow and settle non-native assets — the single most
  important VM change in this roadmap.~~ **done** — `ASEL` publishes the asset and binds the instruction
  after it (a 2-register instruction cannot carry asset+to+amount), enforced at the deploy gate *and* in
  the verifier's log replay, because an unpaired `PAY` moves NADO where the contract meant to move a token.
- ~~Metadata: name/ticker/decimals, immutable after create; **no admin key by default**, opt-in mint
  authority that can be permanently renounced (mirroring the existing `lock` op's one-way model).~~ **done**
- ~~Indexer: asset registry endpoint (`/exec/assets`, `/exec/asset?id=`) alongside `/exec/contracts`.~~ **done**
- ~~Docs: `doc/assets.md`.~~ **done**
- **Wallet: asset list, per-asset balance, send/receive, the same status lifecycle every game uses.** ← next
- **Explorer: asset pages, holder lists, supply.**
- **Settlement by proof for asset calls** — give `settlement_proofs._run_call` a shadow asset ledger and
  let `verify_epoch` replay with `with_assets=True`. The AIR needs nothing more; it already proves the io
  log that carries every asset effect.
- A real "build your first dApp" guide (we still don't have one — see Track D).

**Exit criteria:** a user creates an asset in the wallet in under 60 seconds, sends it to a friend,
and both see it in their balance list. *(Chain half met: `tests/test_assets.py` covers supply
conservation, revert symmetry, authority, the settled-root effect, and the differential
interpreter-vs-proof-vs-replay check our money-code rule demands. Wallet half outstanding.)*

---

## Phase 2 — AMM (the venue)

**Goal:** a constant-product pool contract so any asset has a price and a NADO pair.

**Deliverables**
- `execnode/games/`-style contract `amm.py` (it belongs in a new `execnode/apps/` — see Track D):
  `createPool`, `addLiquidity`, `removeLiquidity`, `swapExactIn`, `swapExactOut`.
- LP position as a Phase-1 asset (so LP tokens are themselves transferable and composable).
- Fee: **default 30 bps, declared via `feeBps()`, split LP / burn** — LPs must be paid or there is no
  liquidity; the protocol's share is burn, not treasury.
- Slippage limits and deadline (`target_block`-bound) on every swap — non-negotiable given 6s blocks.
- Reads: pool reserves, price, and a `/exec/view` shape the frontend can poll without pulling full
  storage (we have a documented full-storage-per-poll ceiling — respect the cap/delegate/index/memoize
  rules from the games-scaling work).
- Frontend: `static/swap.html` + `swapdapp.js` built on `nadodapp.js`, with the standard
  confirming→confirmed lifecycle and a real `settleInflight` landed function.

**Exit criteria:** live E2E script (`_amm_e2e.py`, same pattern as `_pets_e2e.py`) creates a pool,
swaps both directions, adds/removes liquidity, and proves reserves and fees conserve exactly.

---

## Phase 3 — Launchpad (the 42%)

**Goal:** the Pump.fun analogue — one-click asset creation with an instant market, no listing, no
liquidity bootstrap problem.

**Mechanic** (well-proven, and it maps cleanly onto primitives we already have):
1. Creator pays a small fee, names a token; supply is minted onto a **bonding curve** contract.
2. Anyone buys/sells against the curve — the curve *is* the market, so there is liquidity from block
   one and no LP required.
3. At a market-cap threshold the token **graduates**: curve reserves are deposited into a Phase-2 AMM
   pool and the **LP is permanently locked/burned** (this is what makes a launchpad not a rug).
4. Fees: creation fee, and a trade fee on the curve. Split: **burn + creator**, both declared,
   creator share capped, all visible pre-signature.

**Anti-rug rules baked into the contract, not the UI** — these are our differentiator vs. every
launchpad that lets a deployer drain:
- No mint authority after creation (renounced at create, enforced by the Phase-1 primitive).
- Creator cannot withdraw curve reserves — only graduation moves them, and only into a locked pool.
- Graduation is permissionless and deterministic (anyone can trigger it once the threshold is met).
- Full trade history readable on-chain; the explorer shows creator holdings from block one.

**Exit criteria:** a token launched, traded, and graduated end-to-end on alphanet; a written
adversarial review specifically hunting for the drain paths (the banked-solvency and field-wrap class
of bug we've already been bitten by twice — treat the curve math as money code).

---

## Phase 4 — Router + wallet swap widget (the 49.6%)

**Goal:** Phantom's lesson — *the wallet is the highest-converting trading surface on any chain,*
because it is where the user already is and already holds the balance.

**Deliverables**
- Router contract/library: best-execution across curve pools and AMM pools, multi-hop through NADO as
  the base pair, one atomic transition (no partial fills).
- **Swap card in `static/interface.html`**, next to Send/Receive — pair selector, price, price impact,
  slippage, one confirm. Same signing path, same status lifecycle.
- Swap inside the games' background-signing flow, so a player short on an asset can top up without
  leaving the game (we already have hidden-iframe value-free signing; a swap has value, so it takes
  the wallet redirect — make that round-trip graceful).
- Price feed endpoint for every frontend (`/exec/prices`), derived from pool reserves, with the
  provisional-read cost lesson applied: incremental tail, no root computation on provisional reads.

**Exit criteria:** a user swaps NADO→asset in the wallet in three taps, and every game page can show
an asset's NADO price without a full-storage poll.

---

## Phase 5 — Indexer, charts, and the terminal layer (the $79M)

Axiom is worth $42.4M/quarter for *execution and routing UX*, not custody. That's a front-end
business built on public state. The prerequisite is not consensus work — it's **an indexer**.

**Reality check on latency:** NADO blocks are 6s (`config.py:119`) with finality at depth 45
(`protocol.py:469`, ~4.5 min). We will never win a sniping-latency race against 400ms slots, and we
should not pretend to. What we can offer instead, and should build the terminal *around*:
- **Deterministic finality** — a fill is final, not probabilistically final.
- **No priority-fee auction** — nobody outbids you into the front of the block (contingent on Track C
  fair ordering landing before real AMM volume).
- **Provable execution** — every fill is attested by the zkVM proof pipeline. No other retail trading
  venue can say a trade was *proven* correct, not just observed.

**Deliverables**
- Indexer service (sibling to `forum/server.py`): trades, OHLCV candles, holder counts, new-launch
  feed, per-address P&L. Reads exec state; no new trust.
- `static/terminal.html`: launch feed, chart, one-click buy/sell, portfolio, watchlist, i18n via the
  `merge_games.py` T_GAMES pipeline.
- Public read API so third parties can build competing terminals — a plural terminal layer is what
  made this category worth $79M, and it costs us nothing to enable.

---

## Phase 6 — Liquid staking

Bonding is BUILT (`bond`/`unbond`, `B_MIN` = 10 NADO, `BOND_CAP`, slashing, `BOND_UNLOCK_DELAY`) but
bonded capital is **frozen and non-composable**, and `B_MIN` plus the unlock delay prices out small
holders. A liquid staking token fixes both and is the standard second-order demand driver (Jito,
Sanctum, Marinade).

**Deliverables**
- Delegation: let an address bond *on behalf of* a pool without handing over spend authority
  (consensus-adjacent — design carefully against the takeover-resistance analysis already in `doc/`).
- `stNADO` as a Phase-1 asset, exchange-rate accruing (not rebasing — rebasing breaks every integer
  balance assumption we have).
- Slashing pass-through and an honest, documented worst case.
- Unbonding queue + an AMM pool for instant exit at a market discount.

**Note the second-order effect:** emission is bond-elastic — a higher bonded ratio *lowers* emission.
Liquid staking will raise the bonded ratio structurally. That is good for hardness and must be
modeled in `doc/bond-elastic-emission.md` before shipping, not after.

---

## Phase 7 — Lending, stablecoin, RWA (the long tail)

Smaller in fees, but this is what makes a chain a *financial system* instead of a casino, and it's
what survives when a meta ends. Order matters — all three need an **oracle**, which we do not have.

1. **Oracle first.** `doc/stablecoin.md` already sketches a stake-secured oracle; that design is the
   prerequisite for both lending and nUSD. Build it standalone, with slashing, and let the sports
   resolver in `scripts/bet_oracle.py` migrate onto it.
2. **Lending** — over-collateralized NADO/stNADO/asset markets; utilization-curve rates; liquidation
   auctions. Kamino's lesson: TVL concentrates in *one* lender, so being early matters more than
   being clever.
3. **Stablecoin (nUSD)** — the CDP design in `doc/stablecoin.md`, implemented, with the stability pool.
4. **RWA** — realistically post-listing and post-counterparty. Track it, don't staff it yet.

---

## Cross-cutting tracks (run in parallel with the phases)

### Track A — On-ramp and liquidity (the actual gate)
None of the above generates a cent if a person cannot get NADO. Today: mine it, or the faucet.
- Finish the **decentralized order book + HTLC cross-chain swap** from `doc/dex-bridge.md` — this is
  our authority-free on-ramp (BTC/LTC/ETH ↔ NADO), and the NADO leg is already built and tested.
- Counterparty-chain light clients and a watchtower/relayer role anyone can run.
- CEX/custodian integration: `doc/exchange-integration.md` is written and honest about the lift (the
  PQ signer is the real work). Package a reference adapter so a listing is an afternoon, not a quarter.
- Fiat is out of scope; the realistic path is BTC/ETH ↔ NADO atomic swaps plus one listing.

### Track B — Throughput and cost
`BLOB_MAX_BYTES = 512 KB`, `MAX_BLOB_BYTES_PER_BLOCK = 1 MB`, 6s blocks. A trading chain's load
profile is many tiny calls, not few large ones — the opposite of the game contracts that set these
limits. Before Phase 5 volume: measure calls/block, batch calls into one blob, and revisit whether the
flat `MIN_TX_FEE` per blob is the right shape when a blob carries 200 swaps. (Keep the fee burned.)

### Track C — Fair ordering / anti-MEV
The moment an AMM has real volume, block producers can sandwich it. "No MEV" is currently true only
because there's nothing to extract. Options to evaluate before Phase 2 ships to mainnet-scale volume:
deterministic intra-block ordering (e.g. by tx hash), per-block batch auctions with a uniform clearing
price, or encrypted mempool. **This is a consensus-level commitment and cheaper to make now than
after a sandwich bot exists.** Position it publicly as a feature — it is one.

### Track D — Developer surface
We are permissionless at the protocol level (`_apply_blob_inner` does zero sender checks on deploy;
cid = `H(deployer, code, nonce)`), but we have **no "build your first dApp" guide, no published SDK
package, and no versioned API**. The seven apps that made Solana's money were built by *other people*.
- Split `execnode/games/` → `execnode/apps/` with games and finance side by side; fix the known gap
  where `hamster` is missing from `deploy.py`'s `GAMES` list.
- Publish `nadodapp.js` as a real package with a version and a changelog.
- A quickstart: deploy a counter, call it from a webpage, in 15 minutes.
- Grants/bounties aimed squarely at the categories in §1 that we won't build ourselves.

### Track E — Keep the games
The existing app layer is not a distraction — it is 21 shipped, provable, *fun* products, and it is
demand of a kind Solana's numbers don't capture. Assets make it better: game-native tokens, tradeable
pets (already a full NFT + marketplace), tournament prize pools denominated in any asset. Every phase
above should ask "what does this give the games?"

---

## 10. What we measure

Because fees burn, "app revenue" is the wrong scoreboard. Ours:

| Metric | Definition | Why |
|---|---|---|
| **Fees burned / quarter** | Sum of destroyed fees | Our analogue of Chain GDP — value accruing to holders |
| **Volume settled / quarter** | Notional across all venues | Comparable to Solana's DEX volume |
| **Assets created / live** | Phase-1 creations, with a survival curve | Launchpad health |
| **Unique signing addresses / week** | Distinct signers | The only demand number that can't be faked by one whale |
| **Third-party contracts deployed** | Deploys not from us | Track D's only honest score |
| **Bonded ratio** | `bonded / supply` | Security, and it drives emission |
| **Time-to-first-trade** | New wallet → first swap | The Phantom lesson, quantified |

Publish these on a public dashboard from Phase 1 onward. A chain that reports its own numbers
honestly is rarer than it should be.

---

## 11. Sequencing summary

| # | Phase | Depends on | Why it's here |
|---|---|---|---|
| 1 | **Asset primitive** | — | Keystone — **chain half BUILT**; wallet UI + proof settlement open |
| 2 | **AMM** | 1 | Price discovery; the venue everything routes into |
| 3 | **Launchpad** | 1, 2 | 42% of app revenue on the reference chain |
| 4 | **Router + wallet swap** | 2, 3 | 15% of app revenue; highest-converting surface |
| 5 | **Indexer + terminal** | 2, 3 | 23% of app revenue; pure front-end leverage |
| 6 | **Liquid staking** | 1 | Unfreezes bonded capital; composability |
| 7 | **Lending / stablecoin / RWA** | 1, 6, oracle | Depth and durability past the meta |
| A | On-ramp / listing | — | **Runs from day one; gates everything** |
| B | Throughput | before 5 | Load profile changes shape |
| C | Fair ordering | **before 2 at scale** | Cheaper to commit now |
| D | Dev surface | continuous | Other people build the winners |
| E | Games | continuous | Already shipped; assets make them better |

---

## 12. Standing rules for everything in this document

1. **Money code is differential-verified three ways** before it touches an asset. Two fund-drain
   classes have already bitten us (banked-table solvency, field-wrap on static payout math); an AMM
   and a bonding curve are the same class of arithmetic with more zeroes attached.
2. **Bugs are caught by running code, not reading it.** Every phase ships with a live E2E script in
   the `_*_e2e.py` pattern and is proven on alphanet before it's called done.
3. **Upgrade in place, no legacy paths.** Alphanet has no activation gates; consensus changes go live.
4. **Close the whole usability loop** — ids, results, feedback, history, search, i18n, routes. A
   half-wired swap is worse than no swap.
5. **No hidden fees, no admin keys, no authority.** If a design needs a privileged address to work,
   it is the wrong design — that is the one thing that makes NADO worth choosing over the chain this
   roadmap is learning from.
