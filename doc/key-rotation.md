# Key rotation — keep the address, change the signing key (account abstraction, minimal form)

Design proposal, 2026-08-25. Not implemented. Status: **architecture for review**.

**Framing.** This is account abstraction in its smallest useful form: an address stops being "the hash of
one key" and becomes an **account whose authorization policy is state** — today one key, after this a
current key plus an optional recovery key with a delay/veto rule. Every later policy (N-of-M, spending
limits, time-locks, a guardian set) is a change to the *policy evaluator* in §3, not to addresses,
transactions, or anything downstream. The design deliberately stops at the two-key policy: it is the
one that solves the actual problems (rotation, recovery) with a bounded consensus surface, and it leaves
the evaluator as the single place a richer policy would plug in.

## 0. What is true today

An address *is* its key. `make_address(pubkey)` = the first 42 hex of the ML-DSA public key + a 4-hex
checksum (`ops/address_ops.py`), and **every** authorization path re-derives that binding:

| path | check |
|---|---|
| transaction (`validate_origin`, `ops/transaction_ops.py`) | `proof_sender(pubkey, sender)` — the key must hash to the sender — then ML-DSA verify over the txid |
| block winner signature (`verify_block_signature`, `ops/block_ops.py`) | `proof_sender(pubkey, block_creator)` |
| attestation / duty / reveal / slash / treasury txs | the same `validate_origin` |
| detached auth evidence (`resolve_sender_pubkey`) | the pubkey stored on the account doc by PUBKEY-ONCE |

PUBKEY-ONCE stores the full public key on the account doc at the address's first transaction
(`public_key`, revert-journaled in `pubkey_revert`); later transactions may omit it and the node
recovers it from state. That is a *cache of the one key the address was derived from*, not a binding
that can move.

Consequence: a new key is a new address, and a new address loses everything keyed by the old one —
bonded stake and its ramp (`bond_since`), fidelity and the recert streak, the presence lease, aliases,
treasury votes, exec-layer state (bridge balance, game positions, dividend accrual, `zk_addrs`), and the
messaging identity. There is no way to recover a compromised key today, and no way to rotate
proactively without starting over.

## 1. Goals and the one non-goal

Goals:
1. **Rotate the signing key of an existing address** — proactively (hygiene, moving to a new device) or
   reactively (compromise) — keeping the address and everything keyed by it.
2. **Recovery from a stolen hot key**, when the owner prepared for it.
3. No change to how addresses look, are derived for *new* accounts, or are referenced anywhere else
   (aliases, contracts, exec state, the wallet's HD derivation).

The non-goal, stated up front because every rotation design is measured against it:

> **A stolen key with no prior preparation cannot be reclaimed by any protocol rule.** The thief holds
> exactly what the owner holds. Any op the owner can sign, the thief can sign first, and a "cancel"
> the owner can sign, the thief can sign too. Delays only turn the race into a war of resubmission.
> The only asymmetry a protocol can enforce is one the owner created *before* the theft: a recovery
> key the thief does not have.

So the design has two tiers: a **recovery key** set in advance (real security), and a **delayed
self-rotation** that needs no preparation (hygiene only, and a veto window for the recovery key).

## 2. State

Three new fields on the account doc (schemaless msgpack; missing = unset). All of them are consensus
state and therefore inside the L1 state root by being in the `accounts` sub-DB (which is in
`SNAPSHOT_DBS`); no new sub-DB is needed for the live values.

| field | meaning |
|---|---|
| `auth_key` | the pubkey that currently authorizes this address. **Absent = the address-derived key** (today's behaviour), so no migration and no root change for existing accounts |
| `recovery` | blake2b hash of the recovery public key (the key itself stays off-chain until used); plus `since` height |
| `rekey_pending` | `{new_key_hash, effective, by}` — a delayed rotation waiting out its window; at most one per account |

One new **dupsort history** sub-DB, `auth_keys`: `address -> (height, pubkey)` for every key that ever
authorized the address, appended on each effective rotation. It exists for evidence that verifies
*against a past state* — an equivocation proof for a block signed with the previous key must still
verify after the key has moved. It is inside the root (it is state, not a journal). Bounded by
`AUTH_KEY_HISTORY_KEEP` entries per address (prune the oldest; a slash proof older than that window is
already unactionable by the finality floor).

Revert journals (outside the root, like `pubkey_revert` / `msgkey_revert` / `bond_since_revert`):
`rekey_revert` keyed by txid, holding the exact prior `(auth_key, recovery, rekey_pending)` triple, so
`rollback_one_block` restores state byte-for-byte — the block-4260 lesson: apply and rollback must be
exact inverses or the root diverges.

## 3. The single authorization primitive

Replace `proof_sender(pubkey, sender)` at every call site with one function:

```python
def proof_authorized(pubkey, sender, at_height=None) -> bool:
    """pubkey may act for sender if it is the address-derived key AND no rotation has replaced it,
    OR it is the account's current auth_key, OR (at_height given) it was the auth_key at that height."""
```

- Address-derived key: valid **until** the first rotation, after which it is just a former key.
  (Otherwise rotation would not revoke anything — the whole point of a compromise rotation.)
- `at_height` is used only by evidence verifiers (equivocation proofs, detached auth) and is
  answered from `auth_keys` history.
- PUBKEY-ONCE becomes "auth-key-once": `validate_origin` recovers the *current* `auth_key` (falling back
  to the stored `public_key` when unset), so rotated accounts keep the omit-the-key optimisation.

This is the entire consensus-side surface: one predicate, one storage field, one history table. Every
caller — tx validation, block signatures, attestations, duty, reveals, slash proofs, treasury votes,
the HTLC/bridge/dividend claims (they are all `validate_origin`) — inherits rotation by construction.
The exec layer needs **nothing**: it consumes L1-validated blobs and keys its state by address.

## 4. Operations

All are ordinary transactions to reserved recipients (like `bond`, `register`, `msgkey`), fee-paying
(never fee-exempt: a rotation storm must cost something), `chain_id`-bound, and subject to the usual
`min_block`/`max_block` landing rules. Each carries its extra material in `data`, which is inside the
signed body (`create_txid` commits everything but `public_key`).

### 4.1 `set_recovery` — prepare (the one that matters)

`data = {recovery_hash}`; signed by the current auth key.

- Takes effect after `RECOVERY_SET_DELAY` (1 day = `BOND_UNLOCK_DELAY`, 14,400 blocks). Immediate
  effect would let a thief who just stole the hot key install *their own* recovery key and lock the
  owner out for good. During the delay an **existing** recovery key may cancel it (`rekey_cancel`,
  §4.4). If none exists, the delay is only a visible warning window (the wallet shows "recovery key
  change pending" loudly) — it cannot stop a thief, per §1, but it stops a *silent* takeover.
- Replacing an existing recovery key follows the same delay and the same veto by the old one.
- Nothing about the recovery key is revealed until it is used; only its hash is on-chain. The wallet
  generates it as a **separate 24-word phrase** shown once and never stored alongside the hot seed.

### 4.2 `rekey` (recovery path) — reclaim

`data = {new_pubkey, recovery_pubkey, new_key_sig, current_key_sig?}`; **signed by the recovery key**
(`public_key` = the recovery pubkey; `validate_origin` accepts it because `blake2b(recovery_pubkey) ==
account.recovery`).

- `new_key_sig` is the new key's ML-DSA signature over the txid: **proof of possession**. Without it
  an owner could bind the address to a key they mistyped and brick it.
- **Two speeds, decided by what co-signs it** (this is the rule §6 arrives at — taking an account must
  need *both* secrets):
  - `current_key_sig` present (recovery + current key, a 2-of-2): **effective in the block it lands**.
    The proactive "I still hold everything, rotate now" case.
  - recovery key alone: enters `rekey_pending` with `effective = height + REKEY_DELAY`, and the
    **current** key may cancel it (and freeze, §4.4). A thief holding only the recovery phrase
    therefore cannot take the account. The owner who lost the hot key waits a day — acceptable,
    because the hot-key thief cannot cancel a recovery-signed rotation (§4.4 accepts a cancel of a
    recovery-signed rotation only from the *current* key if no freeze is active — and the thief's own
    attempts to rotate are self-path rotations the owner vetoes with recovery, which freezes them).
- On effect: `auth_key = new_pubkey`, `auth_keys` history appended, any pending cleared, and
  **`recovery` cleared** — a recovery key is single-use (using it reveals it). The wallet's recovery
  flow immediately queues a new `set_recovery`, which waits its day.
- The recovery key can never *spend*: it is accepted only for `rekey` and `rekey_cancel`.

### 4.3 `rekey` (self path) — rotate without preparation

`data = {new_pubkey, new_key_sig}`; signed by the current auth key.

- Enters `rekey_pending` with `effective = height + REKEY_DELAY` (1 day). At most one pending per
  account; a second `rekey` while one is pending is invalid (no queue to fight over).
- Becomes effective at the first block at/after `effective` in which **any** transaction from the
  account lands, or at epoch-boundary sweep — cheapest is: `validate_origin` promotes a matured
  pending rotation lazily on the account's next transaction (deterministic: it depends only on
  height and state). Until then the old key authorizes; after, only the new one.
- Why a delay at all if it cannot stop a thief? Because it gives the **recovery key** its veto window
  (§4.4), and because for the honest proactive case it lets the owner confirm the new device can sign
  (the pending tx itself proved possession) before the old key stops working.

### 4.4 `rekey_cancel`

`data = {}`; signed by the **recovery key** (recovery pubkey in `public_key`, hash-matched), OR by the
current auth key.

- Clears `rekey_pending` and a pending `set_recovery`.
- A cancel signed by the recovery key also sets a `rekey_freeze` until `height + REKEY_FREEZE`
  (7 days): no self-path `rekey` and no `set_recovery` may land during the freeze — only the
  recovery path (§4.2). This is what ends the war: once the owner has vetoed with the key the thief
  does not have, the thief's only remaining move is blocked, and the owner rotates via recovery at
  leisure. A cancel by the current key (no recovery key set) sets no freeze — it would just let the
  thief freeze the owner too.

## 5. What each subsystem sees

| subsystem | change |
|---|---|
| tx validation | `proof_sender` → `proof_authorized`; PUBKEY-ONCE recovers `auth_key` |
| block signatures, attestations, duty, RANDAO reveals | same predicate; a validator rotates its node key by signing `rekey` with the old `keys.dat`, installing the new one, and the node keeps producing under the same address, bond and ramp |
| slashing / equivocation proofs | verify with `at_height` from `auth_keys` history; a rotated-away key's past double-signs stay slashable |
| bonded registry, open registry, fidelity, aliases, treasury votes | keyed by address — untouched |
| exec layer (bridge, games, dividends, `zk_addrs`) | untouched; blobs are L1-validated |
| messaging (`msgkey`, prekeys) | separate identity KEM key; unaffected. The wallet should re-publish prekeys after a compromise rotation as hygiene, not as a protocol rule |
| PUBKEY-ONCE revert journal | extended by `rekey_revert`; `pubkey_revert` stays for the first-tx case |
| state root | `auth_key` / `recovery` / `rekey_pending` are account fields (already in the root); `auth_keys` is a new `SNAPSHOT_DBS` member — **a genesis-root change**, so this ships at a reroll or behind a generation-keyed gate that starts the DB empty |
| wallet (browser) | `rekey` derives the new key as the next HD child (`accountChildSeed`) so the seed phrase still recovers it; the recovery phrase is a separate seed; a "Security" panel shows key age, recovery-key status, pending rotations with loud warnings |
| desktop wallet / node `keys.dat` | a `rotate-key` CLI that signs `rekey`, waits for effect, then swaps `keys.dat` (keeps the old file as `keys.dat.retired.<height>`) |

## 6. Threat analysis

| scenario | outcome |
|---|---|
| **hot key stolen, recovery key set** | owner: `rekey_cancel` with recovery (freezes 7 d), then recovery-path `rekey` → thief's key is revoked immediately. Meanwhile the thief can *spend* the liquid balance with the hot key (nothing stops that anywhere) but bonded stake is behind the 1-day unbond delay, and an `unbond` + `withdraw` by the thief is visible and the owner's rotation lands before release. Net: liquid balance at risk for the reaction time, stake and identity saved |
| **hot key stolen, no recovery key** | unrecoverable by design (§1). The self-path `rekey` war is a stalemate; whoever moves coins first wins them. The wallet must say this plainly and nudge every new account to set a recovery key |
| **recovery phrase stolen, hot key safe** | thief can only start a *delayed* rotation (§4.2, recovery alone); the owner cancels it with the hot key and freezes. A thief holding *only* the hot key cannot take the account either (§4.4). Taking the account needs **both** secrets — the 2-of-2 shape §4.2 encodes |
| both stolen | game over, as with any 2-of-2 |
| typo / lost new key | proof of possession (`new_key_sig`) makes a mistyped key impossible to bind; a *lost* new key after rotation is the same as a lost key today — the recovery key still rotates it again (single-use, so the wallet re-arms it) |
| rotation spam / griefing | fee-paying, one pending per account, and only the account's own keys can act on it — nobody can rotate someone else |
| cross-chain replay | `chain_id` in the signed body, as for every tx |
| reorg through a rotation | `rekey_revert` restores the prior triple; `auth_keys` history row is deleted on revert (dupsort delete of the exact pair) |
| a rotated-away key signs a block later | `proof_authorized` without `at_height` rejects it; with `at_height` (evidence) it verifies only for heights it was valid, so old equivocations still slash |
| detached auth / aggregate evidence (`resolve_sender_pubkey`) | resolves `auth_key` (current) — evidence about the current head; historical evidence passes `at_height` |

## 7. Constants (draft)

| constant | draft | why |
|---|---|---|
| `REKEY_DELAY` | `BOND_UNLOCK_DELAY` (14,400 blocks ≈ 1 day) | same "network gets a day to notice" horizon as pulling stake |
| `RECOVERY_SET_DELAY` | same | installing a recovery key must be as slow as rotating |
| `REKEY_FREEZE` | 7 × 14,400 | long enough that the owner can rotate at leisure after a veto |
| `AUTH_KEY_HISTORY_KEEP` | 8 | evidence deeper than the finality floor is unactionable anyway |
| fees | ordinary base fee; `rekey` via recovery path is not fee-exempt either (the account has a balance or it has nothing worth reclaiming) |

## 8. Rollout

1. `auth_keys` is a new snapshot DB → a **genesis-root change**. Ship at the next reroll, or behind a
   generation-keyed gate (`H if CHAIN_GENERATION == 23 else 0`, the pattern in
   `doc/updates-and-rerolls.md`) with the DB simply empty before it — an empty dupsort DB contributes
   nothing to the root, so the gate only needs to guard the *ops*, not the storage.
2. Order of work: `proof_authorized` + tests that every former `proof_sender` call site now goes
   through it (a source assertion, like `test_dividend_rules` pins the gate) → account fields + revert
   journal + rollback symmetry test (`test_rollback_symmetry` gains a rotation case) → the four ops →
   block/attestation/slash paths with `at_height` → wallet Security panel → node `rotate-key` CLI.
3. Wallet default: on account creation, generate and show the recovery phrase and submit
   `set_recovery` as part of the first-transaction flow (it costs one fee and a day). Existing accounts
   get a one-time prompt.

## 9. Where this goes if it goes further (account abstraction proper)

The evaluator in §3 is the seam. Keeping it a pure function of `(account state, height, signatures
presented)` means richer policies are additive:

- **N-of-M** — `auth_keys` becomes a set with a threshold; `proof_authorized` counts valid signatures.
- **Spending limits / per-key roles** — a key may `bond`/`register` but not `send` above X per day;
  needs per-key metadata and a rolling counter (state growth: keep it to a fixed few fields).
- **Guardians / social recovery** — `recovery` points at other accounts' *current* auth keys (§9 below).
- **Session keys for games** — a short-lived key allowed only `blob` calls to listed contracts; the
  biggest UX win on the table and the one most exposed to state bloat, so it should be `max_block`-
  bounded and never persisted past expiry.

None of these change addresses, the exec layer, or the transaction envelope beyond what §4 adds
(`data` fields and extra signatures). What they do change is verification cost per transaction, which
is why the base design stops at two keys: one ML-DSA verify per tx today, at most two under this
proposal, and every step beyond that must justify its per-block CPU on a 6-second block time.

## 10. Open questions

- Should `set_recovery` be allowed to point at **another address's** current key (social recovery by a
  friend / a second device you already own) instead of a fresh phrase? Same mechanism, hash of their
  auth key; it makes recovery depend on their key hygiene. Cheap to allow; decide on product grounds.
- Whether a rotation should reset anything (it should not: the point is continuity). The only
  candidate is treasury-vote weight ageing (`bond_since` untouched, so no).
- Whether the exec layer wants to *know* (e.g. for a "key rotated" notice in games). It does not need
  to; an `/get_account` field suffices for UIs.
