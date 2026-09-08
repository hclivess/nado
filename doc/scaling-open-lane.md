# Scaling the open lane to millions of devices

*Design, 2026-09-09. Nothing here is implemented; each phase is gated and independently shippable.*

## Where the ceiling is today

| resource | today (30 devices) | cost model | practical ceiling |
|---|---|---|---|
| registrations | a few per hour | one `register` tx per device per lease (36 h); ~5-10 KB each (WebAuthn statement with a 3-4 certificate chain) | at ~200 registrations per block (~1-2 MB) and 19,059 blocks per 36 h: **~3-4 million leased devices** |
| the draw | microseconds | `mining_ops._weighted_draw` sorts the registry and walks it once **per block**; `open_lane_draw_registry` rebuilds the candidate map per block | O(N log N) per block in Python: **~10⁵ devices** before the draw is a visible fraction of the 6.8 s cadence |
| registry build | microseconds | `account_ops.get_open_registry` derives membership from the `recert_by_epoch` index once per epoch (cached in `_mining_status_lanes`) | O(N) per epoch: fine to 10⁷ |
| dividend accrual | trivial | the exec node folds fidelity weights once per epoch | O(N) per epoch: fine to 10⁷ |
| state | MB | one account row per identity, one `devbind` row per device | GB at 10⁷: fine |

Registrations bind first, the draw second. Everything else is comfortable to ten million.

## Phase 1 — fewer bytes per device-day (registration throughput)

**1a. Statement-free renewals for every class, not only hardware wallets.** Today a Ledger/Trezor binding renews
with a `register` that carries no statement (the `devbind` row is the proof, `DEVICE_BIND_PERMANENT_HEIGHT`). A phone or
TPM re-attests every renewal because its key rotates. Change: the *first* statement of a lease binds the device
certificate to the identity for `RENEW_WINDOW` renewals (say 7 days of 36 h leases); renewals inside the window carry
only a **signature by the same attested credential** over the chain's challenge — the credential's public key is
already in the `devbind` row, so the node verifies one ECDSA/ML-DSA signature instead of a certificate chain. A
renewal shrinks from ~5-10 KB to ~200 bytes. Rotation of the platform key ends the window naturally (the next
renewal fails the signature check and falls back to a full statement). Sybil surface unchanged: the certificate that
binds is still verified in full once per window, and the row still admits one identity per device.

**1b. Longer leases.** `POSW_LEASE_EPOCHS` 360 (36 h) → 1680 (7 days) once 1a is in: liveness detection then rests on
the renewal signature, not on re-attestation. Capacity multiplies by 4.7 on its own.

**1c. Certificate-chain deduplication.** Every Android statement of the same model carries the same two intermediate
certificates; a Windows chain the same Microsoft intermediate. A statement may reference an intermediate by its
SHA-256 when the chain has already been seen in a *finalized* block (`cert_index` DB, keyed by hash, filled at
incorporate, pruned never). The kernel receives the full chain either way; only the wire/block bytes shrink (~60 %).
Consensus-relevant: a reference to an unknown hash is a validation failure, so every node must hold the same index —
it is derived from finalized blocks only, which every node has.

Combined: ~200-byte renewals for 7-day leases → **~500 million device-days per day** of headroom at today's block
size; registrations stop being the bound.

## Phase 2 — an O(log N) draw

The draw must stay byte-identical on every node and in the browser (`_weighted_draw` is mirrored in JS for the
"expected time to mine" display; only the node's result is consensus).

**2a. Epoch-frozen registry with prefix sums.** Membership and fidelity change only at epoch boundaries (register
lands at `max_block`, fidelity is applied at apply time, but the *draw* already reads the registry "as of the parent
epoch"). Build the sorted address list and the cumulative weight array **once per epoch** (`_mining_status_lanes`
already caches the registry; extend the cache with `prefix: list[int]`). A block's draw is then
`bisect(prefix, hash % total)` — O(log N).

**2b. Same for the bonded lane.** Weight = stake, changes at every bond/unbond; keep a Fenwick tree keyed by the
sorted address index, updated at apply/revert (O(log N) each), total in O(1), draw in O(log N). The tree is
node-local derived state (rebuildable from accounts), never in the state root.

**2c. Determinism guard.** The bisect draw and the walk draw must agree on every historical block: ship 2a behind a
gate, and add `tests/test_draw_equivalence.py` that replays 10,000 random registries through both and asserts
identical winners. The walk stays in the code as the reference.

## Phase 3 — keep per-block work independent of N

- `open_lane_draw_registry` filters stakers (`bonded >= B_MIN`) out of the open draw per block: precompute the
  filtered list at the epoch boundary (it only changes with bond/unbond, which 2b already tracks).
- `/mining_status` and the wallet's lane counters read the cached prefix totals; no per-request walk.
- The identity log and `tools/identity_audit.py` are node-local and can stay O(N).

## What does not scale and is left alone on purpose

- **Emission.** 3,800 open blocks and ~124 NADO of dividend a day divided by ten million devices is dust; the lane's
  economics, not its code, decide how many devices are worth attesting. This document is about not falling over,
  not about making 24 million devices sensible.
- **The chain's own per-block cost** (verification, state root) is unchanged by any of this.

## Order of work and gates

1. Phase 2a + 2c (draw, ~2 days): no wire change, one gate `DRAW_PREFIX_HEIGHT`, replay proven by the equivalence test.
2. Phase 1a (statement-free renewals for leased classes, ~3 days): gate `RENEW_SIG_HEIGHT`; the kernel gains a
   "credential signature" verdict; the wallet signs renewals with the stored credential (WebAuthn `get()` instead of
   `create()` — still one tap, no attestation prompt).
3. Phase 1b (7-day leases): a constant change at the same gate as 1a.
4. Phase 1c (chain dedup, ~2 days): gate `CERT_REF_HEIGHT`, new `cert_index` DB.
5. Phase 2b/3 when the bonded registry or per-block filters show up in `py-spy`.

Trigger to start: the open registry passing ~10,000 devices, or register traffic passing ~10 % of block bytes.
