# Decentralized exchange & bridge — no authority, no custodian

> **Status: DESIGN, building on BUILT primitives.** The trustless cross-chain leg (HTLC atomic swaps) and
> the on-chain contract VM this order book runs on are already implemented and tested — HTLCs in
> [`htlc.md`](htlc.md) (`tests/test_htlc.py`), the stack-VM + escrow in [`exec-instructions.md`](exec-instructions.md)
> and the example game contracts (`execnode/games/*.py`). This note specifies the layer *above* them:
> a **decentralized order book, matching, atomic settlement, and cross-chain verification** with **no bridge
> operator, no multisig federation, no custodian, and no privileged relayer**. Security comes only from
> cryptography (hashlock/timelock), each chain's own consensus, and the exec layer's determinism.

---

## 0. The one design decision that makes it authority-free

Almost every "bridge" you have heard of has an authority, because a bridge that mints **wrapped** assets
(wBTC on chain X) must have *someone* holding the real BTC and attesting to it: a custodian, a multisig
federation, or an MPC committee. That someone is the authority — and the thing that gets hacked.

**NADO's bridge does not wrap and does not custody.** It is a **swap bridge**: it never creates a
representation of a foreign asset; it *matches two people who each already hold the real asset on their
respective chains and swaps them atomically.* No coin ever leaves its native chain into someone's custody.
The only "bridge state" is escrow that each chain holds under a hashlock/timelock that **only its owner or a
timeout can release** — there is nothing for an operator to run away with, because there is no operator.

Two asset classes, two mechanisms, both authority-free:

| swap | mechanism | atomicity from |
|---|---|---|
| **cross-chain** (NADO ↔ BTC / ETH / LTC / any HTLC chain) | **HTLC atomic swap**, coordinated by an on-chain **order book** (§3–§6) | matching hashlock on both chains + timelock ordering |
| **intra-NADO** (exec-layer asset ↔ asset, L1 NADO ↔ exec token, cross-namespace/rollup) | **atomic VM swap** — one deterministic transaction moves both legs (§7) | a single exec-layer state transition (no HTLC needed) |

Everything below specifies these two, the discovery/order layer that turns raw swaps into a usable exchange,
the failure/timeout paths, the incentives, and the attack surface.

---

## 1. Goals and non-goals

**Goals**
- **No authority.** No address, key, quorum, or committee can freeze funds, censor a completed swap, or
  seize escrow. Every escrow releases to exactly one of {the rightful claimant with the secret, the original
  owner after a timeout}.
- **Atomic.** A swap either completes on both sides or refunds on both sides. Never one-sided.
- **Permissionless.** Anyone can post an order, fill an order, run a matcher UI, or run a watchtower/relayer.
  None of these roles is privileged; they are races anyone may enter.
- **Verifiable client-side.** A light client (the wallet) can verify every step it depends on — it never
  trusts a server's word for a balance, a fill, or a preimage.

**Non-goals (explicitly out of scope, by design)**
- **No wrapped/pegged assets.** No wBTC, no custodied representation. (A trust-*minimised* peg via SPV light
  clients + a bonded optimistic challenge is sketched in §11 as a possible future, and flagged as an order of
  magnitude more complex; the pure no-authority path is atomic swaps.)
- **No off-chain order relay as the source of truth.** Order *discovery* may use gossip/relays for latency,
  but the **binding** order book is on-chain (an exec-layer contract), so no relay can forge, hide, or
  reorder a binding order.
- **No shared liquidity pool that a swap can drain.** Each escrow is bound to one swap; there is no pooled
  honeypot.

---

## 2. Building blocks that already exist

The design is thin because NADO already ships the hard parts.

- **HTLC transactions** ([`htlc.md`](htlc.md)) — `htlc_lock` / `htlc_claim` / `htlc_refund` over the keyless
  `HTLC_ESCROW` pseudo-account. Hashlock is **SHA-256** (the cross-chain lingua franca — BTC/ETH use it, so
  the *same* hashlock works on both sides), timelock is an absolute NADO height in
  `[h+HTLC_MIN_TIMELOCK, h+HTLC_MAX_TIMELOCK]`. Every guard is enforced and revert-symmetric. The lock's
  **txid is the swap id**.
- **The stack-VM + value escrow** ([`exec-instructions.md`](exec-instructions.md)) — deterministic
  contracts with `VALUE` escrow into `bridge[cid]` and `PAY` payouts that can never exceed escrow. The order
  book is an ordinary `zkvm` contract, exactly like the games (`execnode/games/*.py`); nothing new
  in the VM is required.
- **The L1↔exec bridge and namespaces** ([`rollups-and-settlement.md`](rollups-and-settlement.md)) — moving
  NADO between L1 and the exec layer, and isolating independent execution layers ("rollups") by namespace.
  Intra-NADO swaps (§7) settle here.
- **Deterministic finality + the inclusion delay** ([`../protocol.py`](../protocol.py) `TX_INCLUSION_DELAY`,
  and the block-timing note) — a tx is only block-eligible once it has propagated to every producer, so all
  nodes hold the same mempool and there is no ordering ambiguity a matcher could exploit (§9, front-running).
- **Post-quantum signatures** (ML-DSA-44) — every NADO-side action is PQ-signed; the foreign leg uses that
  chain's own signature scheme.

---

## 3. Architecture — three layers

```
  ┌──────────────────────────────────────────────────────────────────────┐
  │  L3  DISCOVERY (permissionless, non-binding)                          │
  │      gossip / relays / the wallet's Swap tab — latency only.          │
  │      Anyone can run one; none is trusted.                             │
  ├──────────────────────────────────────────────────────────────────────┤
  │  L2  ORDER BOOK (binding, on-chain exec-layer contract `otc`)         │
  │      post_order · fill · cancel · expire.  Deterministic matching.    │
  │      Holds the NADO-side intent + escrow reference; the source of     │
  │      truth for "who agreed to swap what with whom".                   │
  ├──────────────────────────────────────────────────────────────────────┤
  │  L1  SETTLEMENT (atomic, trustless)                                   │
  │      cross-chain → HTLC legs on NADO + the foreign chain (§6)         │
  │      intra-NADO  → one atomic VM swap (§7)                            │
  └──────────────────────────────────────────────────────────────────────┘
```

The **only** binding, consensus-enforced state is L2 (the order book contract) and L1 (the escrows). L3 is a
convenience: if every relay vanished, a user could still read the order book straight from `/exec/contract`
and settle from the wallet. That is what "no authority" means operationally — remove every optional actor and
the system still clears.

---

## 4. The order book contract (`otc`) — concrete VM design

> **Naming (2026-08-26):** the design originally called this contract `dex`. That name is now taken: a
> constant-product **AMM** shipped as `execnode/games/dex.py` (the ROADMAP Phase-2 venue for intra-NADO
> NADO↔asset pairs). The cross-chain order book is a different contract and is named **`otc`** throughout —
> maker/taker swaps against a foreign chain, no pooled liquidity, no shared honeypot.

An ordinary `zkvm` contract (see [`exec-instructions.md`](exec-instructions.md)), authored + differentially verified against the real VM in `tests/otc_contract_test.py` (**shipped** — 53 asserts,
both kinds end to end). All money moves through the contract's `VALUE`/`PAY` escrow; **no method is gated on
any admin address** — the contract has no owner. State is slot-keyed and fully enumerable;
`execnode/games/otc.py` is the schema of record.

### 4.1 Order kinds

- **`ASK_NADO`** — maker offers NADO (escrowed in the contract now) for a foreign asset. The maker is the
  *hashlock originator* (generates the secret) → gets the **longer** timelock.
- **`BID_NADO`** — maker offers a foreign asset for NADO; the NADO side is provided by the taker. Symmetric.
- **`SWAP_INTRA`** — maker offers exec-layer asset A for asset B, settled by a single atomic VM swap (§7);
  no HTLC, no foreign chain.

### 4.2 Storage schema (implemented)

Slot-keyed by order id `o` (a client-chosen random int < 2^32) — **fully enumerable** (slot 0 holds the
count, a LIST field the ids; no hash-keyed cells), which is what makes both the storage view and the reroll
attribution (§4.4) possible without any off-chain index.

| field | key | meaning |
|---|---|---|
| `mk` 1 | `o` | 1 = order exists |
| `kind` 2 | `o` | 1 = `ASK_NADO` (maker gives NADO) · 2 = `BID_NADO` (maker wants NADO) |
| `maker` 3 | `o` | maker (caller digest) |
| `esc` 4 | `o` | LIVE NADO escrow, raw — the maker's for an ASK, the taker's once a BID fills |
| `namt` 5 | `o` | the NADO side amount, raw |
| `wch` 6 / `wamt` 7 / `wadr` 8 | `o` | foreign chain / amount / maker's receiving address (string digests) |
| `hsha` 9 | `o` | `SHA-256(s)` — the FOREIGN leg's hashlock (digest of the 64-hex string) |
| `hvm` 10 | `o` | `alghash(limbs(s))` — THIS contract's hashlock (see the dual hashlock below) |
| `expn` 11 | `o` | NADO-side refund height `T` — fill/settle require `cursor < expn`, expire requires `≥` |
| `expf` 12 | `o` | the foreign leg's deadline, **opaque** (see §6.3 note below) |
| `st` 13 | `o` | 1 open → 2 filled → 3 settled / 4 refunded / 5 cancelled |
| `taker` 14 / `tadr` 15 / `fref` 16 | `o` | taker digest / taker's foreign address / foreign HTLC txid-outpoint |
| `s0..s4` 20–24 | `o` | the revealed preimage limbs, stored at settle so the counterparty reads them from a view |

**The dual hashlock.** The zkVM's only in-circuit hash is the alghash sponge — there is no SHA-256 opcode —
while Bitcoin script can *only* check SHA-256. So the ONE 32-byte secret `s` binds two commitments at post
time: `H_sha = SHA-256(s)` locks the foreign HTLC and `H_vm = alghash.hashn(limbs(s))` locks the escrow
here, where `limbs(s)` splits `s` little-endian into five 52-bit field limbs (5×52 ≥ 256; each limb < 2^52
so every range gate stays inside the VM's LT window). Revealing `s` anywhere opens both. `preimage_limbs` /
`vm_hashlock` in `execnode/games/otc.py` are the single shared definition for wallet + tests.

**Timelock note (§6.3 in practice).** `expn` is enforced in-circuit (`[cursor+HTLC_MIN_TIMELOCK,
cursor+HTLC_MAX_TIMELOCK]`, mirroring the L1 HTLC bounds) and splits claim from refund exactly: settle needs
`cursor < expn`, expire needs `cursor ≥ expn`. `expf` lives on a chain whose clock this VM cannot observe, so
the §6.3 ordering invariant (foreign refund + claim margin strictly before `expn`) is verified by the
wallet/watchtower before it accepts a fill — the contract stores `expf` so both parties committed to the
same window, it never interprets it.

### 4.3 Methods (all permissionless; `//` = revert guard)

- **`post(o, kind, namt, wch, wamt, wadr, hsha, hvmHi, hvmLo, expn, expf)`** (the alghash hashlock
  rides as two 32-bit halves — a JS JSON number is exact only to 2^53 —) with `VALUE = namt` for an `ASK_NADO`
  (0 for a `BID_NADO` — the NADO side arrives with the taker's fill).
  `// o fresh; kind ∈ {1,2}; namt > 0 (range-gated < 2^62); every commitment non-zero; expn in the HTLC
  window; VALUE == (kind==ASK ? namt : 0).`
- **`cancel(o)`** — maker only, only while `open`. Refunds the escrow to the maker. `// state==open &&
  caller==maker`.
- **`fill(o, tadr, fref)`** with `VALUE = namt` for a `BID_NADO` — first valid taker wins (the tx inclusion
  delay + deterministic mempool make the race fair, §9). Pins the taker's foreign HTLC reference so the
  maker can verify that lock before revealing `s`. `// state==open && cursor < expn && VALUE matches kind.`
- **`settle(o, l0..l4)`** — **anyone** holding the preimage (the counterparty, a watchtower). `// state==
  filled && cursor < expn && alghash(l0..l4) == hvm (each limb < 2^52).` Pays the escrow to the recorded
  party, never the caller: ASK → taker, BID → maker. Submitting the limbs publishes `s` on NADO — for a BID
  that is exactly what hands the taker their claim on the foreign leg (and the limbs are stored in `s0..s4`).
- **`expire(o)`** — anyone, at/after `expn`. Drains an unsettled order's escrow back to whoever funded it
  (ASK → maker, filled BID → taker, intra → maker; asset escrows refund via APAY) and marks `refunded`. The
  no-authority safety valve: a stuck order is never trapped. `// state ∈ {open, filled} && cursor ≥ expn.`
- **`post_intra(o, giveAsset, giveAmt, wantAsset, wantAmt, expn)`** with `VALUE = giveAmt` of `giveAsset`
  (0 = native) — a SWAP_INTRA limit order (§7): both sides live on the exec layer, so no hashlock and no
  foreign chain. `// sides > 0; not NADO-for-NADO; the escrowed value matches the stated give side.`
- **`fill_intra(o)`** with `VALUE = wantAmt` of `wantAsset` — BOTH legs in one atomic call (taker's value →
  maker, maker's escrow → taker); either leg failing reverts everything. `open → settled` directly, no
  middle state, no free-option window. `// state==open && kind==intra && cursor < expn && VALUE matches.`
  (`fill()` correspondingly gates on the HTLC kinds — without that, a 0-value fill could flip an intra
  order to `filled` and freeze its escrow until expiry.)

Because the contract can **only** pay escrow back to its funder (cancel/expire) or forward to the recorded
counterparty against the preimage the maker themselves committed to, there is no method and no caller that
can divert a swap. That is the whole point.

### 4.4 Reroll survivability & venue

Every escrowed raw is **attributable on-chain**: orders are enumerable and each carries its funder and live
`esc`, so at a genesis reroll (doc/updates-and-rerolls.md) the carry-forward refunds every open/filled order
exactly to whoever funded it — `otc.escrow_refunds` is that attribution (the contract module owns its own
schema), and `tools/alphanet6_carryforward.py` routes any contract whose ABI carries `post/fill/settle/
expire` through it. Funds always survive a reroll; the *orders* do not carry (their expiry heights belong to
the dead chain, and the foreign leg falls back to its own refund path) — makers simply re-post.

**Venue:** the order book is a separate contract from the `dex` AMM (no shared state; separate audit and
upgrade surfaces) but the SAME user-facing exchange — the cross-chain book ships as a tab inside the
existing `static/dex.{html,js}` dApp on the shared `nadodapp.js` SDK, not as a second app.

---

## 5. Why the order book is on-chain and not a relay

A pure off-chain order relay (0x/Serum-style "post signed orders to a server") reintroduces an authority: the
relay can hide your order, show you a stale book, front-run your fill, or censor a maker. Putting the *binding*
book in an exec-layer contract removes all of that:

- **No hiding / censorship** — an order is a mined transaction; every node has it. A relay that drops it
  changes nothing.
- **No fake fills** — a fill is a mined `fill()`; the contract enforces first-valid-wins deterministically.
- **No reorder front-running** — fills carry the standard `min_block` inclusion delay and land in the
  deterministic shared mempool (block-timing note), so a matcher cannot reorder or sandwich them; every node
  builds the identical next block.

The cost is that posting/cancelling an order is a (cheap) transaction rather than a free API call. For a DEX
whose settlement is a multi-minute cross-chain swap, on-chain order latency is negligible, and the L3
gossip layer (§3) still gives instant *discovery*; only the *commitment* is on-chain.

---

## 6. Cross-chain atomic swap lifecycle (the bridge)

Alice holds **NADO**, wants **BTC**; Bob holds **BTC**, wants **NADO**. Neither trusts the other or any third
party. (`ASK_NADO` from Alice.)

### 6.1 Happy path

1. **Alice posts + escrows.** She picks a secret `s`, computes `H = SHA-256(s)`, and calls
   `post_order(ASK_NADO, want_chain=btc, want_amt, want_addr=<Alice BTC addr>, hashlock=H, expiry_n=T₁,
   expiry_f=T₂)` with `VALUE` = her NADO. Her NADO is now in the contract's escrow under `H`. She reveals
   **only `H`**.
2. **Bob fills + locks BTC.** Bob calls `fill(o, taker_want_addr=<Bob NADO addr>, foreign_lock_ref)` and, on
   Bitcoin, funds a P2(W)SH HTLC paying **Alice's BTC addr**, hashlock `H`, refund-to-Bob after `T₂`. `T₂` is
   *shorter* than `T₁`.
3. **Alice verifies Bob's BTC HTLC** (her wallet reads the Bitcoin chain — SPV or a full node she trusts *for
   her own safety only*, never for consensus) and **claims the BTC** by broadcasting the preimage `s` on
   Bitcoin before `T₂`. This **publishes `s`** on the Bitcoin chain.
4. **Bob reads `s`** from Bitcoin and **claims the NADO**: the contract's escrow is released by an
   `htlc_claim(s)`-style settle to Bob, because `SHA-256(s) == H` and `height < T₁`.

Both legs complete. Alice got BTC, Bob got NADO. No coin was ever custodied.

### 6.2 Failure paths — always refund, never one-sided

- **Bob never locks BTC** → Alice's NADO escrow sits `open`; after `T₁` anyone calls `expire(o)` → Alice
  refunded.
- **Alice never reveals `s`** (locked BTC exists) → Bob refunds his BTC after `T₂`; Alice's NADO refunds
  after `T₁`. Both whole.
- **Alice reveals `s` on BTC but Bob is offline** → Bob (or his watchtower, §10) still reads `s` from the
  public Bitcoin chain and claims the NADO any time before `T₁`. `s` is public the instant Alice spends.

### 6.3 The timelock-ordering invariant (non-negotiable)

`T₂` (foreign, taker's refund) **must** expire strictly *before* `T₁` (NADO, maker's refund), with enough
margin for the second claim to confirm:

```
   T₂  +  (claim-confirm margin on the foreign chain)   <   T₁
```

If it were reversed, Bob could refund his BTC after `T₂` *and* still claim the NADO before `T₁` — stealing
both. The contract **enforces** this at `post_order`/`fill`: `expiry_f`'s wall-clock deadline must be provably
earlier than `expiry_n`'s (heights → seconds via each chain's block time, with a safety buffer). This is the
single most important consensus check in the whole design.

### 6.4 How the NADO side learns the preimage (two variants, both authority-free)

The NADO chain must release Alice's escrow to Bob **only** once `s` is known. Two ways, pick per deployment:

- **(A) Direct — Bob submits `s`.** Bob simply calls `settle(o, limbs(s))`; the contract checks the
  alghash side of the dual hashlock, `alghash(limbs(s))==H_vm` (§4.2 — the VM has no SHA-256, so the one
  secret carries a hashlock in each chain's native hash; both were bound at post). Bob learned `s` by watching Bitcoin. **This needs nothing from NADO about Bitcoin** — the
  preimage is self-authenticating. This is the default and is fully trustless (it is exactly how
  [`htlc.md`](htlc.md) §3 works). The order book just coordinates *discovery*; settlement is the raw HTLC.
- **(B) SPV-verified — for the reverse direction / added safety.** When NADO is the *shorter* leg and must
  confirm the foreign lock exists before Alice reveals, the wallet does light-client (SPV) verification of the
  foreign HTLC output *for the user's own decision to reveal* — it is never a consensus input on NADO, so it
  needs no trusted oracle. (A consensus-level foreign-chain verifier — a NADO-side BTC SPV client — is the
  §11 "trust-minimised peg" territory and is deliberately **not** required here.)

The key property: **the preimage is the bridge.** One 32-byte secret, published by the act of claiming,
unlocks the mirror escrow. No message needs to be *trusted* across chains — only *observed*.

### 6.5 The foreign-leg templates (concrete)

Both templates use the **same 32-byte SHA-256 hashlock `H`** the NADO side bound at `post_order` — that is
the entire cross-chain interface.

**Bitcoin — P2WSH HTLC** (the standard swap script; one witness script, spendable two ways):

```
OP_IF
    OP_SHA256 <H> OP_EQUALVERIFY
    <claimant_pubkey> OP_CHECKSIG            # claim branch: reveal s with SHA256(s)=H
OP_ELSE
    <T2_locktime> OP_CHECKLOCKTIMEVERIFY OP_DROP
    <refund_pubkey> OP_CHECKSIG              # refund branch: only at/after T2 (absolute locktime)
OP_ENDIF
```

The claim spend's witness carries `s` — publishing it on Bitcoin is what lets the NADO side settle.
Confirmation margin: treat a BTC lock as real only at **≥ 2 confirmations** (~20 min), and budget the §6.3
inequality as `T₂(wall clock) + 6 BTC blocks < T₁(wall clock)` so the claim itself can confirm before the
NADO refund opens. Wallet-side verification is an SPV/Electrum/RPC read of the P2WSH outpoint — the user's
own decision input, never NADO consensus.

**Ethereum — minimal HTLC contract** (one contract serves every swap; ~40 lines, no owner, no upgrade path):

```solidity
struct Lock { address claimant; address refundee; uint256 amount; bytes32 H; uint256 deadline; }
mapping(bytes32 => Lock) locks;              // key: keccak256(H, claimant, refundee, deadline)

fund(claimant, H, deadline) payable          // escrows msg.value; deadline is T2 as a unix timestamp
claim(key, s)   require(sha256(s) == H && block.timestamp <  deadline)  -> pay claimant (s now public calldata)
refund(key)     require(block.timestamp >= deadline)                    -> pay refundee
```

ERC-20 swaps are the same contract with `transferFrom`/`transfer` instead of ETH value. Confirmation
margin: post-merge finality (~2 epochs, ~13 min) before treating the lock as real; the same §6.3 inequality
with Ethereum's clock.

> **Shipped (2026-08-26):** `scripts/HtlcEth.sol` (compiled to `scripts/HtlcEth.bin`) is the contract; `static/ethsign.js` signs it in-page and `scripts/otc_eth_leg.mjs` from a terminal (both proven end to end against a live EVM). In the dApp the ETH leg uses an **injected wallet** (MetaMask/EIP-1193 — the user's own funded account pays gas, the account model needs it) with the CLI shown as the fallback when no wallet is present. A single ownerless `HtlcEth` per EVM chain is reused via `ETH_HTLC[chainId]`. **DEPLOYED LIVE on Ethereum Sepolia (2026-08-26) at `0xCd8F71E75Bb37F438c49a8011ae4037da5A8968F`** (tx `0x7921bd2b…`, block 11572909) — the dApp's ETH leg is wired to it, so ETH↔NADO swaps run on real Sepolia today: connect an injected wallet on the Sepolia network, or drive it with `scripts/otc_eth_leg.mjs`.

Neither template is NADO consensus code: they are reference legs the wallet constructs and *reads*. The only
consensus-enforced piece remains the NADO-side escrow and the timelock-ordering check at
`post_order`/`fill`.

---

## 7. Intra-NADO atomic swaps (no HTLC needed)

For assets that both live on NADO — two exec-layer tokens, an L1↔exec pair, or two rollup namespaces bridged
through L1 — atomicity is **free**: a single deterministic VM transaction moves both legs or reverts. No
hashlock, no timelock, no second chain.

- **`SWAP_INTRA` order** in the `otc` contract escrows asset A from the maker. `fill_intra(o)` with `VALUE` =
  asset B from the taker executes both `PAY`s in one method — maker gets B, taker gets A — atomically. If
  either leg can't be paid, the whole call reverts (the VM's all-or-nothing escrow settlement,
  [`exec-instructions.md`](exec-instructions.md) §3). This is a classic on-chain limit-order DEX. Its pooled
  companion **already ships**: `execnode/games/dex.py` is the constant-product AMM (x·y=k, 30 bps entirely
  to LPs, no admin, no rake) for intra-NADO NADO↔asset pairs — still authority-free, the pool is a
  contract, not a custodian.
- **Cross-namespace / cross-rollup** swaps route through the L1 bridge
  ([`rollups-and-settlement.md`](rollups-and-settlement.md) "tunnels"): burn/lock in namespace X's exec state,
  mint/release in namespace Y, both proven against the shared L1 — again atomic within NADO's own consensus,
  no external authority.

Intra-NADO swaps are instant (one block), have no free-option problem, and are the recommended path whenever
both assets are already inside the NADO ecosystem. HTLC is only for genuinely *foreign* chains.

---

## 8. Fees and incentives — all permissionless

- **Maker/taker fees:** optional, and if charged they accrue to the swap's *counterparty pool* or are burned,
  **never to an operator** (there is none). A common choice: a tiny maker rebate funded by a taker fee, both
  expressed in the escrow and enforced by the contract — no privileged fee collector.
- **Watchtower/relayer bounties (§10) — IMPLEMENTED (`boost(o)`, 2026-08-26):** anyone may attach NADO to a
  live order; settle/`fill_intra` pay it to the caller, `expire` to the sweeper, cancel back to the maker.
  Claimable by *whoever* performs the action first. This funds the permissionless safety roles
  without appointing anyone. Because the bounty pays on a first-come race and only for a *correct* action
  (the contract verifies the preimage / the timeout), it cannot be gamed.
- **No native token requirement to bridge:** a zero-NADO-balance claimant can still `htlc_claim` (it is
  fee-exempt, [`htlc.md`](htlc.md) §2), so receiving NADO for the first time via a swap is possible without
  pre-funding — critical for genuine bridging *in*.

---

## 9. Ordering, MEV, and front-running

A DEX's worst non-custodial failure mode is ordering abuse: a matcher/miner reordering or sandwiching fills.
NADO's block pipeline removes the usual levers:

- **Deterministic shared mempool + inclusion delay** (`TX_INCLUSION_DELAY`, block-timing note): a fill is only
  block-eligible after it has gossiped to *every* producer, and every node then builds the byte-identical next
  block. There is no private mempool and no single sequencer to reorder around.
- **First-valid-wins is contract-enforced**, not matcher-decided: two fills for the same order in the same
  block are ordered deterministically (by txid) identically on every node, and the contract accepts exactly
  one.
- **No free reordering for producers:** the two-lane producer for a slot is fixed by the beacon draw; it
  cannot choose *which* eligible txs to include beyond the deterministic target-height/`min_block` rule, so it
  cannot insert itself ahead of a fill it just saw.

Residual, and honestly noted: a producer still *chooses among simultaneously-eligible* txs at the margin, and
cross-chain price moves during a swap window create the **free-option problem** below. NADO reduces MEV
structurally but does not claim to eliminate marginal ordering discretion.

### 9.1 The free-option problem (the real economic risk, not a bug)

In any HTLC swap the party who acts *second* holds a free option: they can wait, watch the price on the two
chains move during the timelock window, and only complete if it stayed favourable — walking (refunding) if it
didn't, at the cost of the counterparty's locked time. Mitigations, all authority-free, layered per risk
appetite:

- **Short, tight timelocks** — the shorter the window, the less optionality. `HTLC_MIN_TIMELOCK` sets the
  floor; the order book should default to the *shortest* safe `T₂/T₁` for the chains involved.
- **Non-refundable premium / collateral — IMPLEMENTED (`set_premium(o, amt)`, 2026-08-26):** the maker
  prices the option per order; the taker escrows it at fill (one value, split in storage), settle returns
  it, expire-after-fill forfeits it to the maker. Released by the same refund logic — no arbiter. Shown in
  the dApp as a \"good-faith deposit\".
- **Reputation (soft, off-chain)** — the L3 layer can surface completion rates; purely advisory, never a
  gate.
- **Prefer intra-NADO (§7)** — no window, no option, whenever both assets are on NADO.

The free option is inherent to trustless cross-chain swaps (it exists in Lightning submarine swaps, Bisq,
Comit, etc.); the honest claim is "priced and bounded", not "eliminated".

---

## 10. Watchtowers — permissionless, incentivised, optional

A swap's only liveness requirement is that *someone* claims/refunds before the relevant expiry. Neither party
needs to be online continuously:

- The **preimage is public** the instant it is used on either chain, so a claim-relay is a pure copy job:
  read `s` from chain A, submit the settle on chain B. Anyone can do it; the losing party's own watchtower or
  a bounty-hunting bot will.
- **`expire()` is permissionless**, so a stuck order always gets refunded even if the maker never returns.
- Watchtowers are **stateless and trustless**: they can only trigger the *correct* outcome (the contract
  verifies the preimage / the timeout); a malicious watchtower can do nothing but help. They are paid by the
  §8 bounties on a first-come basis.

This is the antithesis of a bridge validator set: there is no committee to bribe, no threshold to corrupt,
and being a watchtower requires no permission, stake, or identity.

---

## 11. What we deliberately do NOT build (and why)

- **Wrapped/pegged assets (wBTC-on-NADO).** Requires either custody (authority) or a NADO-side SPV light
  client of the foreign chain *plus* a bonded optimistic-fraud-proof challenge game to trustlessly verify
  foreign-chain state — an order of magnitude more code and a live security assumption (honest challengers +
  liveness). Atomic swaps deliver cross-chain value movement with **none** of that. If pegged assets are ever
  wanted, the design is: (a) a `btc-spv` exec contract verifying Bitcoin headers + Merkle inclusion, (b) a
  bonded minter with a challenge window, (c) fraud proofs that slash a lying minter. Flagged as **future,
  complex, and not authority-free in the same clean sense** — the bond/challenge model is trust-*minimised*,
  not trust-*less*.
- **A federation / MPC signer.** That *is* the authority we are avoiding.
- **A canonical off-chain sequencer.** Reintroduces censorship/reorder power; see §5.

---

## 12. Security invariants (the checklist a reviewer verifies)

1. **No divertible escrow.** Every `otc`/HTLC escrow releases only to {claimant-with-preimage before expiry,
   original owner at/after expiry}. No method, no caller, no admin can do otherwise. (Contract has no owner;
   HTLC guards are revert-symmetric.)
2. **Atomicity.** For a completed cross-chain swap, the preimage that unlocked leg A is exactly the preimage
   that unlocks leg B (same `H`); partial completion is impossible without publishing `s`, which enables the
   other side.
3. **Timelock ordering** (§6.3) is enforced at post/fill: `T₂ + margin < T₁`. This is the theft-prevention
   invariant.
4. **First-valid-fill determinism** — identical on every node (txid order + `min_block`); no double-fill.
5. **Refund liveness** — `expire()`/`htlc_refund` are permissionless and always eventually callable, so no
   swap can strand funds.
6. **Client-verifiable** — the wallet independently checks the order book (`/exec/contract`), the NADO escrow,
   and (for its own reveal decision) the foreign lock; it trusts no server for anything binding.
7. **Ordering-abuse bounded** — deterministic shared mempool + inclusion delay remove private-mempool MEV;
   the free option is priced (§9.1), not denied.

---

## 13. Phased implementation plan

| phase | deliverable | tests |
|---|---|---|
| **0 (done)** | HTLC tx types + client Swap tab | `tests/test_htlc.py` |
| **1 (done 2026-08-26)** | `otc` order-book contract (`ASK_NADO`/`BID_NADO`): post/cancel/fill/settle/expire + attributable escrow, dual hashlock, claim/refund window split, reroll attribution wired into the carry-forward | `tests/otc_contract_test.py` (author-in-test + differential-verify vs the real VM, 53 asserts) |
| **2 (legs done 2026-08-26)** | Foreign legs SHIPPED: `scripts/otc_btc_leg.py` (P2WSH HTLC builder/signer + CLI: address/claim/refund/extract, BIP143, no wallet dependency) and `scripts/HtlcEth.sol` (the one-contract ETH HTLC). The BTC leg is now FULLY AUTOMATIC in the dApp (2026-08-26): per-order swap keys generated in-browser (never typed, never leave the page), pubkeys ride the order's own address fields, every row derives the P2WSH address itself (`btcleg.js`) and offers Send-exactly/Copy/Verify, one-click Claim/Reclaim signs in-page (`btcsign.js` — BIP143 + RFC-6979 via vendored @noble/secp256k1, byte-identical to the Python leg) and broadcasts via the explorer, and Settle auto-reads the revealed secret from the claim witness. The explorer reads are the user's own decision input (§6.4 B), never consensus. the ETH leg is wired too (injected-wallet in the dApp + `scripts/otc_eth_leg.mjs` headless); `scripts/otc_btc_leg.py` / `otc_eth_leg.mjs` stay as the expert paths | `tests/test_otc_swap_e2e.py` — 15/15: regtest bitcoind + anvil + the real otc contract, ONE secret opens all three, both refund paths, both wrong-secret rejections |
| **3 (contract done 2026-08-26)** | `SWAP_INTRA` SHIPPED: `post_intra`/`fill_intra` — both legs (native↔asset or asset↔asset) in ONE atomic call, open→settled with no middle state; asset-aware cancel/expire refunds; `fill()` gained a kind gate (a 0-value HTLC fill could otherwise freeze an intra escrow until expiry). Cross-namespace tunnel path still open (routes through the L1 bridge, §7) | intra section of `tests/otc_contract_test.py` (72/72 total) |
| **4 (daemon done 2026-08-26)** | `scripts/otc_watchtower.py` SHIPPED — expire sweep (escrow always drains home, zero-escrow opens skipped) + BTC secret-scan settle relay (finds a revealed preimage in any claim witness and re-posts settle; payment goes to the recorded party, never the tower) + secrets-file settle; contract discovered by method shape, dry-run default, --submit/--loop for the daemon. On-chain BOUNTIES for towers remain phase 5 (§8) | `tests/test_otc_watchtower.py` (8/8) + live dry-run |
| **5 (bounties done 2026-08-26; rest future)** | `boost(o)` bounties SHIPPED (§8) — the watchtower sweeps paying work first. §9.1 premium/collateral SHIPPED too (`set_premium` — maker-priced per order, dApp \"good-faith deposit\"). The L3 gossip discovery relay is DROPPED as unnecessary — §5's whole argument is that the on-chain book IS the discovery layer, and it is live. Still future: a dedicated `bridge.nadochain.com` Swap dApp (cosmetic), ETH-leg automation (needs HtlcEth deployed on a real EVM chain — an operator decision, it costs gas) | bounty section of `tests/otc_contract_test.py` (83/83) |

**File map (to build):** `execnode/games/otc.py` (+ `tests/test_otc_contract.py` as its source of
truth), a cross-chain tab inside the existing `static/dex.{html,js}` exchange dApp (one venue: AMM + book, on the shared `nadodapp.js` SDK), `scripts/otc_watchtower.py`,
`website/nginx-bridge.nadochain.com.conf`, a card in `website/games.html`/the app catalog, and this doc.

---

## 14. How it compares

| bridge model | authority | worst-case loss | on NADO |
|---|---|---|---|
| Custodial (exchange) | the custodian | 100% (exit scam / hack) | rejected |
| Multisig / MPC federation | m-of-n signers | 100% if threshold corrupted | rejected |
| Optimistic (bonded + fraud proof) | honest challenger + liveness | bond-bounded, needs watchers | §11 future only |
| **HTLC atomic swap (this doc)** | **none** | **0 — refund on non-completion; only risk is a priced time-option** | **the design** |

The trade-off is explicit and, for a chain that already ships HTLCs and a deterministic exec VM, cheap: you
give up *wrapped assets* and *instant* cross-chain settlement, and in return you get a bridge with **no one to
trust and no one to hack** — value moves between chains by two people swapping the real thing, coordinated by
an ownerless contract and secured by one public secret.

---

*See also:* [`htlc.md`](htlc.md) (the settlement primitive) · [`exec-instructions.md`](exec-instructions.md)
(the VM the order book runs on) · [`rollups-and-settlement.md`](rollups-and-settlement.md) (bridge/tunnels,
namespaces) · [`exchange-integration.md`](exchange-integration.md) (the *centralised* counterpart — what this
design is the trustless alternative to).
