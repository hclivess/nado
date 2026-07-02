# HTLC — hash time-locked contracts for trustless cross-chain atomic swaps

> **Status: implemented** (consensus tx types + client Swap tab). Lets NADO atomic-swap with any chain that
> supports HTLCs (Bitcoin, Ethereum, Litecoin, …) — no bridge, no custodian, no trusted third party. Tests:
> `tests/test_htlc.py` (9 cases incl. every guard + byte-identical revert).

## 1. What an HTLC is

An HTLC escrows coins under **two** conditions:

- a **hashlock** — the coins are claimable by revealing a secret `preimage` such that
  `SHA-256(preimage) == hashlock`;
- a **timelock** — an absolute block height `expiry` after which, if unclaimed, the original sender can
  refund.

Whoever holds the secret can claim before `expiry`; otherwise the sender reclaims. Revealing the preimage to
claim **publishes it on-chain**, and that is the linchpin of a cross-chain swap: the same hashlock placed on
two chains lets each party unlock the other side with one secret.

**Why SHA-256 and not blake2b?** SHA-256 is the cross-chain *lingua franca* — Bitcoin and Ethereum HTLCs use
it — so the identical hashlock works on both sides of a swap. (NADO's own hashing stays blake2b; SHA-256 is
used only for the HTLC preimage.)

## 2. The three transactions

All three are keyless reserved recipients over a single escrow pseudo-account `HTLC_ESCROW = "htlc"`
(supply stays accounted — locked coins sit in escrow, never minted/destroyed):

| tx | who | effect | fee |
|---|---|---|---|
| `htlc_lock` | sender | move `amount`(+fee) from sender, lock `amount` in escrow, record `{claimant, hashlock, expiry, status:open}`. The lock **tx's txid is the swap id**. | pays a normal fee |
| `htlc_claim` | claimant | reveal `preimage`; if `SHA-256(preimage)==hashlock` **and** `height < expiry` **and** you are the claimant → escrow releases `amount` to you, and the preimage is recorded (published). | **fee-exempt** (a zero-balance claimant can claim) |
| `htlc_refund` | sender | after `expiry`, reclaim an **unclaimed** lock from escrow. | **fee-exempt** |

Validation enforces every guard (`ops/transaction_ops.py`): positive lock amount; hashlock is 32-byte hex;
`expiry ∈ [h + HTLC_MIN_TIMELOCK, h + HTLC_MAX_TIMELOCK]`; claimant ≠ sender; claim only by the claimant,
only before expiry, only with a preimage that hashes to the lock's hashlock; refund only by the sender, only
at/after expiry; and only against an **open** HTLC. State transitions are revert-symmetric (status
`open ↔ claimed/refunded` restored on rollback) and at most one claim-OR-refund per HTLC per block
(`reserved_uniqueness_key`).

## 3. A cross-chain atomic swap, step by step

Alice has NADO, Bob has (say) BTC; they want to swap without trusting each other or a bridge.

1. **Alice generates a secret** `s` (32 random bytes) and computes `H = SHA-256(s)`. She sends **only `H`** to
   Bob (never `s`).
2. **Alice locks on NADO**: `htlc_lock` with `claimant = Bob`, `hashlock = H`, `expiry = T₁`.
3. **Bob locks on Bitcoin** the agreed BTC with the **same** `H`, `claimant = Alice`, and a **shorter**
   timelock `T₂ < T₁` (Bob must be able to refund *after* Alice's window has already closed).
4. **Alice claims the BTC** by revealing `s` on Bitcoin — this publishes `s` on the Bitcoin chain.
5. **Bob reads `s`** from the Bitcoin chain and **claims the NADO** with `htlc_claim(s)` before `T₁`.

Either both legs complete, or both refund after expiry — never one-sided. The **timelock ordering matters**:
your refund must be strictly *later* than the counterparty's, so they can't refund their side and still claim
yours. (NADO is the longer timelock `T₁` in the example above.)

## 4. Constants

| constant | meaning |
|---|---|
| `HTLC_ESCROW = "htlc"` | keyless escrow pseudo-account holding all locked coins |
| `HTLC_MIN_TIMELOCK` (10) | expiry must be ≥ lock height + this (room for the claimant to act) |
| `HTLC_MAX_TIMELOCK` (1,000,000) | expiry ≤ lock height + this (bounds indefinitely-dangling escrow) |

## 5. Client (Swap tab)

The light-miner's **Swap** tab drives all three ops. Creating a lock generates a 32-byte secret via the
browser's WebCrypto and shows both the `hashlock` (to hand a counterparty) and the **secret** (which you must
save — it's the only way to claim/prove). It lists your swaps (as sender or claimant) with role, status, and
expiry, offers Claim/Refund at the right times, and — once a lock is claimed — surfaces the **revealed
preimage** so the counterparty can complete the mirrored lock on the other chain. Read endpoints:
`/get_htlc?id=…` and `/htlcs?address=…`.

## 6. Trust model

An HTLC needs no bridge, no custodian, and no new cryptographic assumption on NADO's side — just a SHA-256
hashlock (post-quantum-safe as a *hash* commitment) and NADO's deterministic block-height timelock. The only
counterparty risk is the standard HTLC one: pick your timelock so your refund is later than theirs, and don't
reveal the secret until you've claimed the far side.
