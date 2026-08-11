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

**State proofs are the ZK line; signature aggregation is not.** Settlement-by-proof went live at the
betanet-14 reroll (`SETTLE_PROOF_RECURSIVE`): an epoch is proven as ONE zkVM trace and L1 verifies it in
**~0.3 s independent of the call count**, replacing re-execution. That is the asymmetry ZK exists for —
re-running ten thousand contract calls is expensive, checking a proof that they ran is not.

Signature aggregation was built far enough to measure and then **removed** (2026-07-31). Proving the
butterfly half of ONE ML-DSA signature cost 7.11 min, produced a 1.87 MB proof and took 6.98 s to verify,
against a 2420-byte signature that verifies natively in 120.4 µs — ~770x the size, ~58,000x the verify.
Break-even needed ~116 signatures for size against a batch cap near 7. Full post-mortem, including two
forgery-class bugs it uncovered and the prover speed-ups that outlived it, in
[`doc/zk-signature-aggregation.md`](doc/zk-signature-aggregation.md).

The rule to carry forward: **prove what is expensive to REDO, not what is cheap to CHECK.** The remaining
ZK work therefore sits on the state-proof line — proving execution, and (separately) the shielded pool,
where inputs are hidden by construction so there is no cheaper alternative to compete with.

### 2026-08-06 — a settle proof LANDED, and what that changed

Block **43153** settled `exec_cursor 42876` on a STARK validity proof: a peer verified it in 114.5 s, all
four nodes agree on the block hash, it is final at depth 71, and `/get_settled` returns the proven root.
Until this point the honest status was "the prover produces correct proofs and none has ever landed".

**The reason it took so long is worth recording, because it was not one bug.** Six independent failures
were stacked, each individually fatal, so fixing any one of them changed nothing observable:

1. **All three peers were missing `libgoldilocks.so`** — with no Python fallback since betanet-14, no peer
   could verify a settle proof under any circumstances. `self_update` rebuilt only crates whose *sources
   changed*, and a box that has never built a crate has unchanged sources forever. Invisible from outside:
   L1 keeps producing blocks and `/status` stays 200.
2. **The fold's prover trace was linear in K** (~65,536 rows per folded proof). Now folded through
   `recursion_depth.fold_tree`, bounding it at T=131,072 for any K.
3. **DA could not deliver it** — only one node in the fleet runs `nado-exec`, so k=4/n=8 erasure coding had
   exactly one provider.
4. **The size caps were knobs, not consensus.** `MAX_TX_BODY` (1 MiB, aiohttp's default) was the real
   limit — and `SETTLE_INLINE_MAX` (7 MiB) already exceeded it. Nothing in consensus bounds tx or block
   size. The proof now rides **inline**, in a 126.6 MiB block.
5. **Gossip timeouts of 5 s / 15 s** sized for kilobyte transactions.
6. **The landing runway** (60 blocks) was shorter than the ~8-minute transfer of an exact-landing tx.

Full evidence and the measurements in [`doc/settle-proof-transport.md`](doc/settle-proof-transport.md) §6.

**Still open, and it gates the next step:** the landed proof was **unfolded** (`calls=0`). A span containing
a call the chain skips or reverts is currently unprovable *at all* — `vm_circuit.prove_epoch_calls` refuses
to prove a reverting execution — so on a busy chain proof-carrying settlement still falls back to the bonded
quorum. `calls_commit.block_calls` already documents the intended semantics ("the proof's state transition
treats a skip/revert as a no-op"), so the implementation contradicts its own design. Fixing it means either
the AIR proves reverting executions, or the verifier can re-derive which calls were no-ops — a
prover-supplied flag would be forgeable. Folded proof SIZE also remains unmeasured, and `prove_transition`
now dominates at ~126 s per state update.

### The state-proof line: what is left

**1. Full-state composition — the ceiling on everything below it.** `settlement_proofs` proves the **zkVM
projection only**. The bridge, dividend and shielded families still settle by their own paths, so there is no
single proof of a whole state transition. Until that exists, "one proof settles the block" is only true of
part of the block, and there is no complete object to merge or fold.

*Progress:* the records half — the other half of `rnode(kv_root, rec_root)` — is now both **provable**
(`execnode/stark/records_transition.py`) and **bound** (`execnode/stark/records_bind.py`, the records
analogue of `exec_state_bind`: derive the update set from committed data, require the transition to prove
exactly that set). Derivation covers the bridge deposit, the faucet/treasury mirror and the presence-dividend
accrual — the last one mattering out of proportion because it accrues with *no transaction at all*, which is
why the settle branch can currently only refuse any span crossing an epoch boundary. Shielded/field
transfers, asset movements, allowances, xmsg and the withdrawal records are still `Unbindable`.

The binding compares derived against proven updates for **exact equality**, so a missing derivation refuses
the span and falls back to quorum — it can cost coverage, never soundness. That is what makes the remaining
effect families landable one at a time instead of as one flag day. `block_records_inert` stays exactly as
strict as it is until they do, and relaxing it is a consensus change that rides a reroll.

**2. State merging** ([`doc/state-merge.md`](doc/state-merge.md)) — how proofs compose once they exist.
*Sequential* merge is live (the K→1 fold: chain segments, `A.roots[-1] == B.roots[0]`, keys may overlap).
*Parallel* merge is implemented (`execnode/stark/state_merge.py`, `tests/test_state_merge.py`): two
transitions proven from the SAME pre-root over disjoint keys, composed into one. Parallel is what lets
proving spread across machines, which is the enabler for off-chain bulking with on-chain reuptake.

**3. One hash for everything provable.** A proof can only be FOLDED if its hash is the algebraic one — the
in-circuit verifier speaks `alghash2` and nothing else. So any proof committed under `blake2b` is
structurally excluded from composition, no matter how fast it is. That makes the backend choice an
*architectural* question rather than a performance one: the shielded pool proving under `blake2b` cannot ever
join a full-state proof.

**Why this ordering.** (3) decides whether (1) is even reachable, and (1) decides whether (2) has anything to
operate on. Measured basis for the whole line: `prove_epoch_calls` verify is **flat at ~0.11 s** and proof
size **constant at 1263 KB** while calls go 1 → 8.
- A real "build your first dApp" guide (we still don't have one — see Track D).

**Exit criteria:** a user creates an asset in the wallet in under 60 seconds, sends it to a friend,
and both see it in their balance list. *(Chain half met: `tests/test_assets.py` covers supply
conservation, revert symmetry, authority, the settled-root effect, and the differential
interpreter-vs-proof-vs-replay check our money-code rule demands. Wallet half outstanding.)*

---

## Phase 2 — AMM (the venue)

**Goal:** a constant-product pool contract so any asset has a price and a NADO pair.

> **The runtime gap this phase will hit: there are no cross-contract calls.** A zkVM call runs exactly one
> contract — `selfd`, storage and the escrowed value are per-call periodic columns in the AIR, so there is
> no frame to switch. A single pool contract does not need one (assets compose natively now, which is the
> point of putting them in the ledger rather than in a contract). A **router** does: best-execution across
> venues means calling pool A then pool B atomically. Solana's equivalent is CPI; ours would be a `CALL`
> opcode plus a call-frame vocabulary in the io log and per-frame context in the circuit. That is a
> project in its own right, not a line item — so Phase 2 ships single-pool swaps, and Phase 4's router is
> where the design has to be settled. Until then a multi-hop route is two transactions and not atomic,
> which is a real UX and MEV cost worth naming rather than discovering.

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

**Exit criteria:** a token launched, traded, and graduated end-to-end on betanet; a written
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

### Track F — Zero-knowledge / proof system

Full map, with measured numbers and per-component status:
[`doc/zk-components.md`](doc/zk-components.md).

| Item | Status | Note |
|---|---|---|
| Goldilocks field, FRI, STARK, AIR IR, LogUp | **BUILT** | `NUM_QUERIES=320`, blowup 2, 18 grind bits → ~146 provable bits (Johnson) |
| alghash2 (in-circuit hash) | **BUILT** | Wide sponge, WIDTH 12 / RATE 8 / CAPACITY 4, α=7, 54 rounds. Post-quantum: 128-bit collision + Grover preimage |
| Execution zkVM + its AIR | **BUILT** | The only contract runtime; **25 contracts live on chain** |
| Shielded pool (join-split, membership) | **BUILT** | The **one** place the full proof→DA→commitment→verify loop already works in production |
| Recursion (in-circuit STARK/FRI verify, FS, fold-of-folds) | **BUILT** | O(1) verify side; live on the consensus path since betanet-14 |
| K→1 fold | **BUILT, never run** | Needs contract calls to fold; an idle chain has none, so the node falls through to the unfolded prove |
| State-root binding (sparse tree, calls/records commitment) | **BUILT** | Depth-256 sparse Merkle over alghash2 |
| Rust prover crates | **BUILT** | `starkprove` (2 222 lines), `alghash2`, `starkcompose`, `mldsa44`. **Rust-only, no fallback** — a Python path shadowing a Rust one is invisible degradation |
| DA transport (k-of-n + commitment + defer) | **BUILT** | Availability ≠ validity: unresolved defers, never rejects |
| **Trustless settlement, end to end** | **NOT WORKING** | Rule is live and unconditional; **zero proof-carrying settles have ever completed**. Current stop: `PRE MISMATCH` — the stashed pre-state does not reproduce L1's justified root |
| Signature aggregation | **REMOVED** | Built, measured, deleted 2026-07-31 — post-mortem kept deliberately |
| Program obfuscation (Diamond iO) | **RESEARCH** | Nothing implemented, scheduled, or promised |

**Open work, in the order the measurements justify:**

1. **Land one proof-carrying settle and have a peer verify it.** Everything else here is capability until
   that happens once. A blob that only exists on the producing box proves nothing to anyone.
2. **Prove cadence vs. prove time.** A prove takes ~250 s while the settle cadence is 30 blocks (~180 s),
   so a new conforming span arrives before the previous prove finishes and hits the in-flight guard. With
   the epoch re-anchor in place a span may safely run up to 59 blocks — roughly one proof per epoch.
3. **Rust port of `ops/da.py`** — now 0.428 s/MiB in Python after the algorithmic fix; Rust would take a
   118 MiB proof from ~50 s to ~1–2 s.
4. **Proving cost.** `sparse_projection` is the largest stage (137–158 s of a 240–270 s prove), and inside
   it `SparseStore.root()` is 65.8 s. But it is **kernel-bound, not seam-bound** — native `permute12` is
   26.9 µs of the 35.4 µs `rnode` call — so porting the tree walk buys only ~24%. A Toeplitz-Karatsuba
   MDS could cut the permutation ~1.8× without changing the hash, but that is consensus-critical and
   **time is not the binding constraint**. Do this last.

### Track G — Signature-scheme agility (more post-quantum, never less)

Today the chain is single-scheme: ML-DSA-44 everywhere, dispatched through the one chokepoint
(`signatures.py` — `sign`/`verify`/`from_private_key`/`generate_keydict`; every consumer imports those
four and nothing else). The goal is user choice among **post-quantum** schemes with ML-DSA-44 as the
default. Pre-quantum schemes (Ed25519, secp256k1) are explicitly out: the weakest offered scheme is the
chain's effective security floor, and PQ-throughout is a differentiator we don't sell back for
convenience.

**Why the architecture makes this cheap:** consensus checks `verify(sig, pk, msg) == True` and never
compares or hashes signature bytes (only the txid is recomputed, over the body *excluding* the
signature), so schemes with different signature shapes perturb nothing. Pubkey-once already binds each
address to one on-chain pubkey; the scheme becomes one more thing that binding fixes.

**Design (settled 2026-08-10):**
- `signatures.py` becomes a registry (`{alg_id: backend}`); the four public functions grow an `alg`
  parameter defaulting to `"mldsa44"`. Callers don't change until they offer the choice.
- **Optional `alg` field on the tx, absent = mldsa44.** Absence-as-default keeps every existing tx
  byte-identical — txids, block hashes, genesis root untouched, **no reroll**. The field rides in
  `canonical_bytes`, so the txid commits it and the signature binds it for free.
- **Scheme bound at pubkey-once:** the first tx from an address establishes `(public_key, alg)` in the
  account record; `validate_origin` dispatches on the bound alg thereafter and rejects mismatches. No
  address-format change — `make_address` stays a pubkey truncation (cross-scheme address grinding is
  2^168, a non-issue), and the network learns an address's scheme exactly when it learns its pubkey.
  Belt-and-suspenders: pubkey sizes are disjoint across the roster (1312/1952/2592/32 bytes), so
  ambiguity is structurally impossible even without the tag — but the tag ships; length-sniffing is the
  `startswith(ADDRESS_PREFIX)` class of discriminator betanet-14 already removed.
- **Validators, blocks, attestations, shielded, forum stay ML-DSA-44.** User key choice only; the
  consensus-critical surfaces remain single-scheme.
- **Multisig:** optional per-member `alg` in the descriptor, default mldsa44 — new descriptors only.
- Per-scheme: the interop self-test pattern and the native-required rule (`_fallback`) carry over.
  Fee-by-byte-size already prices large signatures — no special-casing.

**Phase G1 — ML-DSA-65 / ML-DSA-87 (near-free).** All three stacks already contain them as parameter
sets of libraries in the tree: `dilithium_py` exports `ML_DSA_65`/`ML_DSA_87` with the same
`_*_internal` methods; the RustCrypto `ml-dsa` crate behind `nado_pq_native` has all three; the browser's
`@noble/post-quantum` bundle exports `ml_dsa65`/`ml_dsa87` in the same internal-mode convention already
cross-validated for 44. Same 32-byte seed model, no new conventions. NIST categories 3 and 5 for the
cost of plumbing — and it shakes out the multi-scheme dispatch on the easiest case.

**Phase G2 — SLH-DSA-128s (the diversity win).** Bigger lattice parameters don't hedge a structured-
lattice break; hash-based SLH-DSA (FIPS 205) does — it's the one addition that changes the security
story rather than the knob settings. Support exists in all three stacks, but it's real new code with a
real interop trap: keygen wants three seed components, so one deterministic 32-byte-seed → key
expansion must be defined and pinned identically in Python, Rust, and JS (extend the per-scheme interop
self-test; this is exactly the bug class it exists for). ~7.8 KB signatures pay their own block space
via the byte-size fee.

**Skip Falcon/FN-DSA:** FIPS 206 not final, thin library support, and floating-point signing is
precisely the cross-implementation determinism hazard this codebase keeps paying for.

**Deployment rule:** the whole fleet must carry the dispatch code *before* the first tagged tx is
submitted — an old node sees a new-scheme tx as "Invalid signature", which is a manufactured mempool
split. One push, no live experiments in flight.

**Cost split, honestly:** node-side (registry, `alg` field, pubkey-once storage, tests) is small; the
larger half is the browser wallet/light-miner parity and multisig UI. Note for Track F: each scheme
added is another verification circuit if in-circuit signature verification is ever revisited — decide
the roster before that build starts, not after.

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
   the `_*_e2e.py` pattern and is proven on betanet before it's called done.
3. **Upgrade in place, no legacy paths.** Betanet has no activation gates; consensus changes go live.
4. **Close the whole usability loop** — ids, results, feedback, history, search, i18n, routes. A
   half-wired swap is worse than no swap.
5. **No hidden fees, no admin keys, no authority.** If a design needs a privileged address to work,
   it is the wrong design — that is the one thing that makes NADO worth choosing over the chain this
   roadmap is learning from.

### Why settle-with-proof is not submittable (measured 2026-08-03)

A settle-with-proof carrying **one** segment serialises to **97.30 MiB**, against an 8 MiB submit cap.
That is the whole reason the validity-proof path has never run in production, on any generation,
whatever the consensus flags said.

Where the bytes are, measured rather than assumed (`prove_settlement_sparse`, one call, toy depth):

| field | NUM_QUERIES=2 | NUM_QUERIES=8 |
|---|---|---|
| `segment.proof.openings` | 0.574 MiB | 2.295 MiB |
| `segment.transition` | 0.278 MiB | 0.750 MiB |
| `segment.pre_contracts` | ~0 | ~0 (1.6 MiB with 25 real contracts) |
| **total** | **0.892 MiB** | **3.166 MiB** |

FRI openings scale **linearly with the query count** (4× queries → 4.0× openings), and protocol strength
is `NUM_QUERIES = 320` (`execnode/stark/fri.py`). That extrapolates to the ~97 MiB observed live.

So the payload is **O(queries), not O(state)** — and `pre_contracts`, the obvious suspect, is ~1.6 MiB of
97. The succinct `verify_bound_epoch_replay` path (in-circuit membership instead of shipping state) is
therefore *not* the fix; it would save under 2%.

The two real levers:

1. **Fewer queries for the same security** — raise the FRI blowup factor and lean on grinding. 320 queries
   implies a low blowup; standard parameterisations reach comparable security at 40–80. This is a
   consensus change and rides a reroll.
2. **Publish the proof to DA and carry only its commitment on chain** — what a rollup normally does, and
   the plumbing already exists (`/da/publish`, `exec_da`, and the shielded path already submits this way).

Note the K→1 fold does not help here: with a single segment there is nothing to collapse, and the fold's
own cost is separately prohibitive (5h07m at 492% CPU without completing, 2026-08-02).

#### Can the query lever alone fix it? No — measured, and it is not close.

FRI parameters today: `FRI_BLOWUP = 2` (fixed — `stark.prove` always passes 2), `NUM_QUERIES = 320`,
`GRIND_BITS = 18`, giving the documented `320 × 0.4 + 18 ≈ 146 bits provable (Johnson)`. Blowup 2 buys only
**0.4 provable bits per query**, which is exactly why 320 are needed.

Raising the blowup buys bits per query, so fewer queries reach the same 146 bits. Best realistic case is
blowup 16 at ~64–80 queries. Measured payload, one call, toy depth:

| NUM_QUERIES | openings | total tx |
|---|---|---|
| 2 | 0.574 MiB | 0.892 MiB |
| 8 | 2.295 MiB | 3.166 MiB |
| 64 | 18.364 MiB | **24.385 MiB** |
| 320 (protocol) | — | ~97 MiB (observed live) |

Perfectly linear at **0.381 MiB per query**.

**The binding constraint is not the 8 MiB HTTP cap — it is the BLOCK.** A full block is ~256 KiB
(`transaction_pool_max_bytes` comment: "4 MiB (>> 256 KiB block …)"; a produced block logged 71,163 bytes),
and `MAX_BLOB_BYTES_PER_BLOCK` is 1 MiB. So:

* today's proof is **~380× an entire block**;
* the best query/blowup reparameterisation still gives 24 MiB, **~95× a block**.

A 4–6× reduction cannot close a 380× gap. **The proof can never ride inside a block**, at any FRI
parameters, so publishing it to DA and carrying only a commitment is not an optimisation — it is the only
available architecture. The codebase already does exactly this for shielded proofs
(`/da/publish` + `proof_da` + `da_fetch`, `execnode.py`: "the caller publishes it to /da/publish and
submits an L1 blob carrying only the commitment").

The open question is therefore not *whether* to use DA but **when the proof is fetched**: a settle proof is
re-verified by every node on block APPLY (and on fresh sync), so a naive DA reference makes block
validation block on a ~100 MiB retrieval. That is the design problem to solve next — not proof size.

#### Update 2026-08-04 — DA transport is built; the blocker moved

That "design problem to solve next" is **solved and shipped**. Availability is not validity, so a proof we
cannot fetch **defers** the block rather than rejecting it — three outcomes, not two (verified → accept,
resolved-and-bad → reject, unresolved → defer). Rejecting on unavailability would split the chain along
*who happens to hold shards*, since the justified `(exec_cursor, exec_root)` sits in the L1 header;
deferral is fork-free because every node applies the same rule, and the wait is bounded by
`SETTLE_PROOF_DEPTH_GATED` (past `FINALITY_DEPTH` the proof is not consulted at all, so a withholder can
only make us wait). Tests: `tests/test_settle_proof_da_defer.py`.

Four further blockers were found and fixed by running it, not reading it:

| | |
|---|---|
| **Cadence** | The settle cadence left the justified tip at an arbitrary offset, so spans straddled the 60-block dividend epoch boundary — **95 of 128 observed skips**, making a proof structurally impossible. The stale comment claimed straddling spans re-anchored the tip; they never did. Fixed by re-anchoring on epoch entry (`fde96f46`) |
| **Silence** | A prove completed and *nothing* followed it — no publish, no error, no settle. There was no log line at all between the prove and the publish, so "finished and vanished" was indistinguishable from "still running" (`966f5c31`) |
| **Root/records skew** | `state_root = rnode(kv, records)`, but the root was captured at cursor C while the records half was recomputed later from a live state the detached tail had advanced — two roots that were never simultaneously true (`6a903a09`) |
| **DA encode** | `ops.da.encode` ran at ~15 s/MiB, so erasure-coding one 118 MiB proof took **~30 minutes**. Algorithmic, not the language: a full modular exponentiation in the innermost loop, ~141 million per proof, recomputing Lagrange coefficients that are *constants*. Hoisted to a cached generator matrix: **15.08 → 0.428 s/MiB (35×)**, bit-identical (`08945e50`) |

**Current status: still not landed.** Measured over 33 064 journal lines (2026-08-01 → 08-06): **89
proofs built and submitted, 0 accepted, 85 refused** with `HTTP 413, Maximum request body size 8388608
exceeded` at 97.30–97.45 MiB. Zero proof-carrying settles have ever completed.

Note what that says: **the self-check was never the historical blocker — size was.** 89 proofs passed
their self-checks and bounced off the 8 MiB cap. The `PRE MISMATCH` self-check failures seen on 08-04
(pre-state does not reproduce L1's justified root; post side exact) are a *later* condition, not the
long-standing one. See [`doc/zk-components.md`](doc/zk-components.md) §0 and §14.

Note also that the **query lever is not needed to be the answer** — the K→1 fold would make the payload
smaller, but it has never run: it needs contract calls to fold and the chain has been idle, so the exec
node deliberately falls through to the unfolded prove.
