# Referrals and funded invite links

Live from `protocol.REFERRAL_HEIGHT` (one gate for both halves). Operator-approved 2026-10-06.

## What a user sees

1. **Invite a friend** (wallet): pick an amount — say 1 NADO — and the wallet makes a link. The amount leaves your
   balance into escrow now. Send the link to one person.
2. Your friend opens the link, creates a wallet and registers their phone or PC. Their first registration names you
   as their referrer, and the wallet claims the NADO you put in the link automatically.
3. For the next 30 days you earn **10 % of your friend's presence dividend** — while you are both present. They keep
   90 %, and they started with your gift instead of nothing.
4. A link nobody claims expires (7 days by default, at most 30). Your wallet offers to reclaim it.

## Why the reward is a slice, not a bonus

The first idea was a fidelity bump — a higher reward for whoever onboards someone. Any reward the **shared pool**
pays per onboarded identity is a per-identity rule, and per-identity rules are linear in the number of identities
(doc/device-attestation.md): a farm of N attested devices refers itself in a ring — device 1 onboards device 2,
2 onboards 3 — and every one of them collects the bump. Because the pool is fixed, the bump is paid by honest users who
did not refer anyone. It would have moved dividend from honest users to farms.

So the referrer's reward is cut from the **newcomer's own weight**:

* from the gate's epoch every dividend weight is scaled by `REFERRAL_SCALE` (10), so a 10 % slice is an integer;
* a newcomer inside its window pays `REFERRAL_SHARE` (1) × its base weight to its referrer and keeps the other 9;
* the total is exactly 10 × the old total, so every identity outside a referral keeps exactly its share;
* a ring of identities that all refer each other nets **zero** — each gives one slice and receives one.

The slice is cut from the newcomer's base weight only, never from what another referral moved, so it never
compounds: A ← B ← C pays one level per link.

## The rules (consensus)

| | rule | where |
|---|---|---|
| link | a `register` from the gate may carry `data = {"referrer": <keyed address ≠ sender>}`; anything else but `""` is refused | `transaction_ops.validate_register_referrer` |
| first only | the link is written only when: the tx carries a real device statement; the sender never recerted; its account has no device stamp; it has no link yet; and the device is bound to nobody (a device MOVING to a new address is not a newcomer) | `account_ops.referral_to_write` |
| storage | devbind row `referral:<newcomer>` → `[referrer, height]`; immutable; deleted only by the rollback of the block that wrote it | `kv_ops.referral_*` |
| window | `REFERRAL_EPOCHS` = 7200 epochs (30 days) from the link's epoch | `dividend_ops.referral_split` |
| presence | the referrer earns only in epochs it is itself in the weight set; otherwise the newcomer keeps the whole weight | same |
| one function | the committed `epochw` rows, the exec accrual and the live `/get_open_weights` all go through `referral_split` | same |

A link made after an epoch never changes that epoch, so a past epoch reconstructs identically whenever it is
recomputed.

## Funded invites (consensus)

A newcomer starts with nothing, not even the fee for a first transfer. The invite carries the start.

| tx | who | what |
|---|---|---|
| `invite_lock` | referrer | escrows `amount` in `INVITE_ESCROW` (`"invite"`) under a throwaway ML-DSA-44 key; data `{key, expiry}`; id = `blake2b(["invite-id-v1", CHAIN_ID, key])`; expiry `max_block + 1440 … + 432000` |
| `invite_claim` | newcomer | fee-exempt; data `{id, key, sig}`; `sig` is the LINK key's signature over `blake2b(["invite-claim-v1", CHAIN_ID, id, claimant])`; only an attested identity (device stamp + a recert); before expiry; not the referrer |
| `invite_refund` | referrer | fee-exempt; at or after expiry; returns the amount |

**Why a signature, not a hashlock.** A hashlock claim reveals its secret in the mempool, and anyone who sees it can
copy it into a claim of their own. The link key's signature names the claimant, so a copied claim cannot be
re-pointed at another address.

**The link** is `https://<wallet>/#invite=<32-byte seed hex>`. A browser never sends the `#fragment` to a server.
The seed is a throwaway made for this one link — it is never the wallet's own key and never derived from it.

**Not a farm target.** Nothing is minted: every coin a claim pays out was put in by the referrer, for a link they
chose to hand out.

**Storage:** `invite:<id>` rows in the `htlcs` DB, a list `[sender, amount, expiry, status, claimant]`, never a dict
(dict order would make two byte strings of one state). `htlc_all` skips the prefix and `htlc_get` refuses an id
carrying it, so an `htlc_claim` can never read an invite as a swap.

## Gate, reroll, endpoints

* `REFERRAL_HEIGHT = <h> if CHAIN_GENERATION == 28 else 1`. Before it every invite tx is refused and register `data`
  is not read. `"invite"` (the escrow) can never be paid directly — the names became reserved with the gate, and a
  reserved name with no branch would otherwise fall through to an ordinary transfer and be accepted where an older
  node refuses it.
* **Reroll:** the carry returns every open invite (and every open HTLC lock) to whoever funded it, debited from its
  escrow (`tools/alphanet6_carryforward.open_escrow_refunds`). Referral links are not carried; a 30-day window does
  not outlive a reroll in any meaningful way.
* `GET /invite?id=`, `GET /invites?address=`, `GET /referrals?address=`.
* The TPM helper registering its OWN address (`apps/nado-tpm-attest`, not the hand-back to a wallet) sends `data: ""`
  and so never names a referrer; the wallet path does.

Tests: `tests/test_invite_link_pays_only_the_named_claimant.py`, `tests/test_referral_slice_is_farm_neutral.py`,
`tests/test_reroll_refunds_open_invites_and_htlcs.py`, and the wallet tests that ship with the wallet half.
