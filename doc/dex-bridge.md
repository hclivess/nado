# Decentralized exchange & bridge — no authority, no custodian

> **Status: DESIGN, building on BUILT primitives.** The trustless cross-chain leg (HTLC atomic swaps) and
> the on-chain contract VM this order book runs on are already implemented and tested — HTLCs in
> [`htlc.md`](htlc.md) (`tests/test_htlc.py`), the stack-VM + escrow in [`exec-instructions.md`](exec-instructions.md)
> and the example game contracts (`execnode/contracts/*.json`). This note specifies the layer *above* them:
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
  book is an ordinary `stackvm` contract, exactly like the games (`execnode/contracts/*.json`); nothing new
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
  │  L2  ORDER BOOK (binding, on-chain exec-layer contract `dex`)         │
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

## 4. The order book contract (`dex`) — concrete VM design

An ordinary `stackvm` contract (see [`exec-instructions.md`](exec-instructions.md)), authored + differentially
verified against the real VM in `tests/test_dex_contract.py` exactly like `tests/test_bet_contract.py`. All
money moves through the contract's `VALUE`/`PAY` escrow; **no method is gated on any admin address** — the
contract has no owner. State is `{map: {key: int|str}}`; keys are `"|"`-namespaced (`key2`).

### 4.1 Order kinds

- **`ASK_NADO`** — maker offers NADO (escrowed in the contract now) for a foreign asset. The maker is the
  *hashlock originator* (generates the secret) → gets the **longer** timelock.
- **`BID_NADO`** — maker offers a foreign asset for NADO; the NADO side is provided by the taker. Symmetric.
- **`SWAP_INTRA`** — maker offers exec-layer asset A for asset B, settled by a single atomic VM swap (§7);
  no HTLC, no foreign chain.

### 4.2 Storage schema (keyed by order id `o` = `randId()`)

| map | key | meaning |
|---|---|---|
| `mk` | `o` | 1 = order exists |
| `kind` | `o` | `ASK_NADO` / `BID_NADO` / `SWAP_INTRA` |
| `maker` | `o` | maker address |
| `give` | `o` | NADO (raw) escrowed by the maker for this order (0 for `BID_NADO`) |
| `want_chain` | `o` | foreign chain id (`btc`,`eth`,…) or an intra-NADO asset id |
| `want_amt` | `o` | amount of the wanted asset (string; foreign-chain native units) |
| `want_addr` | `o` | maker's receiving address on the foreign chain |
| `hashlock` | `o` | SHA-256 hashlock `H` the maker will use (bound at post time) |
| `expiry_n` | `o` | maker's NADO-side HTLC expiry height `T₁` (the LONGER lock) |
| `expiry_f` | `o` | the foreign-side expiry `T₂ < T₁` the taker MUST use (in that chain's height/time) |
| `state` | `o` | `open` → `filled` → `settled` / `refunded` / `cancelled` |
| `taker` | `o` | taker address (set on fill) |
| `swap_nado` | `o` | the NADO `htlc_lock` txid (the swap id) once locked |
| `min_block` | `o` | (inherited from every tx) inclusion-delay so fills can't be front-run — see §9 |

### 4.3 Methods (all permissionless; `//` = revert guard)

- **`post_order(o, kind, want_chain, want_amt, want_addr, hashlock, expiry_n, expiry_f)`** with `VALUE` =
  the maker's NADO for an `ASK_NADO` (0 otherwise).
  `// o is fresh; expiry_n ∈ [h+HTLC_MIN_TIMELOCK, h+HTLC_MAX_TIMELOCK]; expiry_f encodes a strictly shorter
  wall-clock window than expiry_n (§6.3); for ASK_NADO the escrowed VALUE == give.` The escrow is now held by
  the contract, releasable only back to the maker (cancel/expire) or forward into the settled swap.
- **`cancel(o)`** — maker only, only while `open`. Refunds `give` to the maker. `// state==open && caller==maker`.
- **`fill(o, taker_want_addr, foreign_lock_ref)`** — a taker commits to the other side. Records `taker`,
  flips `state open→filled`, and pins the **foreign leg reference** (the txid/outpoint of the taker's HTLC on
  the foreign chain, so the maker can verify it before revealing). `// state==open`. Fill is a *race*: the
  first valid fill wins; the inclusion delay + deterministic mempool (§9) make that race fair.
- **`settle_nado(o)`** — the party entitled to the NADO side calls this once the preimage is public. It
  simply forwards the maker's escrow into a NADO `htlc_lock` bound to `{claimant, hashlock, expiry_n}` — or,
  if you prefer to keep the HTLC outside the contract, `settle_nado` just releases escrow to the maker after
  verifying the foreign leg matured (see §6.4 variant). `// state==filled`.
- **`expire(o)`** — anyone, after `expiry_n`. Refunds an unsettled order's `give` to the maker and marks
  `refunded`. This is the no-authority safety valve: a stuck order always drains back to its owner, callable
  by anybody (a watchtower, the maker, a bot), never trapped. `// state∈{open,filled} && height≥expiry_n`.

Because the contract can **only** pay the maker (refund) or move escrow into a hashlock/timelock the maker
themselves parameterised, there is no method and no caller that can divert a swap. That is the whole point.

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

- **(A) Direct — Bob submits `s`.** Bob simply calls the settle with `s`; the contract checks
  `SHA-256(s)==H`. Bob learned `s` by watching Bitcoin. **This needs nothing from NADO about Bitcoin** — the
  preimage is self-authenticating. This is the default and is fully trustless (it is exactly how
  [`htlc.md`](htlc.md) §3 works). The order book just coordinates *discovery*; settlement is the raw HTLC.
- **(B) SPV-verified — for the reverse direction / added safety.** When NADO is the *shorter* leg and must
  confirm the foreign lock exists before Alice reveals, the wallet does light-client (SPV) verification of the
  foreign HTLC output *for the user's own decision to reveal* — it is never a consensus input on NADO, so it
  needs no trusted oracle. (A consensus-level foreign-chain verifier — a NADO-side BTC SPV client — is the
  §11 "trust-minimised peg" territory and is deliberately **not** required here.)

The key property: **the preimage is the bridge.** One 32-byte secret, published by the act of claiming,
unlocks the mirror escrow. No message needs to be *trusted* across chains — only *observed*.

---

## 7. Intra-NADO atomic swaps (no HTLC needed)

For assets that both live on NADO — two exec-layer tokens, an L1↔exec pair, or two rollup namespaces bridged
through L1 — atomicity is **free**: a single deterministic VM transaction moves both legs or reverts. No
hashlock, no timelock, no second chain.

- **`SWAP_INTRA` order** in the `dex` contract escrows asset A from the maker. `fill_intra(o)` with `VALUE` =
  asset B from the taker executes both `PAY`s in one method — maker gets B, taker gets A — atomically. If
  either leg can't be paid, the whole call reverts (the VM's all-or-nothing escrow settlement,
  [`exec-instructions.md`](exec-instructions.md) §3). This is a classic on-chain limit-order DEX; it can be
  extended to a constant-product AMM pool as a second contract if pooled liquidity is wanted (still
  authority-free — the pool is a contract, not a custodian).
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
- **Watchtower/relayer bounties (§10):** a maker/taker may attach a small NADO bounty to `expire()` and to a
  claim-relay, claimable by *whoever* performs the action first. This funds the permissionless safety roles
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
- **Non-refundable premium / collateral** — the second mover posts a small extra escrow that is forfeited to
  the first mover on a non-completion, pricing the option. Encoded in the `dex` contract, released by the
  same refund logic — no arbiter.
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

1. **No divertible escrow.** Every `dex`/HTLC escrow releases only to {claimant-with-preimage before expiry,
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
| **1** | `dex` order-book contract (`ASK_NADO`/`BID_NADO`): post/cancel/fill/expire + escrow, timelock-ordering guard | `tests/test_dex_contract.py` (author-in-test + differential-verify vs the VM, like `test_bet_contract.py`) |
| **2** | Cross-chain settle wiring: contract escrow → NADO `htlc_lock`/`htlc_claim`; wallet flow that generates `H`, posts, verifies the foreign HTLC (SPV read), reveals, and relays the preimage | `tests/test_dex_swap_e2e.py` (regtest BTC + local NADO) |
| **3** | `SWAP_INTRA` + `fill_intra` (atomic exec-layer asset↔asset) and the cross-namespace tunnel path | `tests/test_dex_intra.py` |
| **4** | Watchtower/relayer bounties + a reference permissionless relayer daemon (`scripts/dex_watchtower.py`, dry-run default like `bet_oracle.py`) | integration |
| **5 (optional, future)** | premium/collateral for the free option; L3 gossip discovery relay; a `bridge.nadochain.com` Swap dApp | — |

**File map (to build):** `execnode/contracts/dex.json` (+ `tests/test_dex_contract.py` as its source of
truth), `static/dex.{html,js}` (the Swap dApp, on the shared `nadodapp.js` SDK), `scripts/dex_watchtower.py`,
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
