# Scaling analysis — will NADO scale, and the fixes

**Status: analysis + change log.** Grounded in the code as of commit-time. Verdict:
NADO scales fine **as a lean settlement base at modest validator counts**, and the
separate execution layer (`doc/execution-layer.md`) is the correct throughput answer —
but a deliberately lean L1 still has **two structural walls**, plus several **fixable
implementation bottlenecks**. The distinction is everything: implementation bottlenecks
are optimizations; structural ones need design changes.

## Verdict in one line

For what NADO is today — fair-launch, phone-mineable, low-TPS, modest validator set — it
holds up. As a design meant for high throughput **or a large validator set** in its
current configuration, **no** — and the binding constraint is the product of three things:
**non-aggregatable PQ signatures × O(N) per-epoch on-chain consensus messages × pure-Python
crypto.**

---

## Implementation bottlenecks (fixable without design change)

### 1. Pure-Python ML-DSA — the single biggest throughput cost — ✅ seam SHIPPED
`Curve25519.py` ran ML-DSA-44 via `dilithium-py` (pure Python); signature *verification*
dominates block validation. Native ML-DSA is a 10–100× win — but a blind swap would (a)
break the deliberate "runs on anything / a phone / a 386" pure-Python design goal, and (b)
hit an **interop trap**: the chain (node + browser `@noble/post-quantum`) signs with ML-DSA
**internal** (no context wrapping), while standard native APIs (e.g. liboqs/`oqs`) wrap a
domain-separation context — producing signatures that **won't cross-verify**.

**Shipped:** a **pluggable backend** in `Curve25519.py`. Default = pure-Python (unchanged,
so phones keep working and the suite stays green). An operator can set
`NADO_PQ_NATIVE_MODULE=<module>` to a native ML-DSA exposing the FIPS-204 *internal*
primitives; it is adopted **only if it passes a startup interop self-test** (cross-verify
against pure-Python both directions), else it falls back loudly. This buys the speed where a
native lib is available **without** sacrificing the pure-Python default or risking a
consensus split. The production path (a native lib exposing *internal* functions, or a
coordinated node+browser migration to external+fixed-ctx ML-DSA) is documented in the
module header.

### 2. O(N²) mempool merge — ✅ FIXED
`memserver.merge_transaction` built `transaction_pool.copy() + tx_buffer.copy() +
user_tx_buffer.copy()` on **every** call just to length-check the cap → O(N) per tx, O(N²)
under flood. **Fixed:** the cap check is now an O(1) sum of the three lengths; the combined
view is built lazily (and without the redundant per-pool `.copy()`, since `+` already yields
a fresh list) only once a tx clears the cheap rejects and actually needs membership /
single-spend. Already-present txs now return a benign `{"result": True, "Already present"}`
(was an implicit `None`), aligning with the fee-exempt-`register` (PoSW recert) "already present =
success" handling.

### 3. Binary wire/storage encoding for signatures — ASSESSED, mostly already handled
ML-DSA-44 carries `public_key` (1312 B) + `signature` (2420 B) per tx, stored as **hex** in
the canonical body (~7.5 KB hex/tx). But: block bodies are already `zstd(msgpack)`
(`ops/block_ops.py`) and block transport uses msgpack, so **zstd already recovers most of
the hex 2× at rest and on the wire**. The remaining win — raw bytes in the *canonical* tx
body — is **consensus-bound** (the txid hashes the body) and browser-reproducibility-bound,
so changing it is a real consensus change for modest marginal benefit. **Recommendation: do
not change the canonical encoding;** the cheap win is already in place.

### 4. Idle-account GC — see `doc/rolling-mode-and-da.md` (consensus-critical)
Idle-account GC is unimplemented (the placeholder `GC_IDLE_EPOCHS` constant was removed as dead code); presence itself is now self-bounding — the old per-epoch
heartbeat rows are gone, replaced by the PoSW **recert lease** (`recerts` / `recert_by_epoch`), which
a node must renew each `POSW_LEASE_EPOCHS` or lapse — but idle **account-row** GC is still not wired.
Pruning an account row changes the **state root**, so it must be deterministic and applied identically
by every node *inside block processing* — not a local maintenance sweep, which would fork
the chain. It is therefore designed (not blind-wired) as the state-pruning section of
`doc/rolling-mode-and-da.md`.

---

## Structural bottlenecks (need design, not just optimization)

### A. PQ signatures don't aggregate
Ethereum compresses thousands of attestations into one BLS signature. **ML-DSA has no
aggregation** — every attestation/recert/vote is a full ~3.7 KB signature, stored and
verified individually. PQ security and BLS-style compression are fundamentally at odds, and
NADO correctly chose PQ. There is no drop-in fix; the escape is §B.

### B. Consensus emits O(N) on-chain messages per epoch — the real design fix (#2)
Confirmed in `loops/core_loop.py`: every bonded validator broadcasts **1 attestation + 1
commit + 1 reveal per epoch** (`update_ffg_and_attest`, `maybe_randao`). So with N bonded
validators, **~3N full PQ-signed transactions of pure consensus overhead per epoch**, each
pure-Python-verified, all competing for the same block space as user payments. At 10k bonded
validators that's 30k+ overhead txs/epoch before a single user tx. **O(N) messages ×
non-aggregatable PQ sig × pure-Python verify** is the scaling envelope.

(The OPEN lane is **no longer** a per-epoch cost. The old per-epoch heartbeat tx was removed:
OPEN-lane presence is now a renewable PoSW **recert lease** (`register` tx), renewed only once per
`POSW_LEASE_EPOCHS` (≈ 1 day), so the open-lane message load amortizes to ≈ N_open / `POSW_LEASE_EPOCHS`
per epoch — negligible next to the bonded ~3N. The dominant O(N)-per-epoch term is the bonded
attest/commit/reveal set.)

**The design fix — aggregate the per-epoch consensus load** instead of posting N messages:
- **Presence/attestation root.** Collect recert/attestation signatures off-chain within an epoch;
  commit a **single root** (Merkle root of present/attesting validators + their stake)
  per epoch on-chain, instead of N individual txs. Validators gossip their signed
  presence to an aggregator role; the block commits the root; the heavy per-sig
  verification moves off the critical block-validation path.
- **Or a succinct proof of the threshold.** A single STARK/SNARK proving *"≥⅔ of bonded
  stake attested checkpoint X"* — one proof per epoch replaces N attestation txs. This is
  **the same proving machinery the execution-layer research explores** (`doc/execution-
  layer-vm-research.md`), and is arguably **more valuable applied here, to L1 consensus
  overhead, than to contracts.** It must be PQ-sound (hash-based, no pairing wrapper) — same
  constraint as Phase-2 settlement.
- **Aggregation tier for ML-DSA.** Since ML-DSA can't aggregate natively, the proof-of-
  threshold approach is the PQ-compatible substitute for BLS aggregation: prove the set of
  valid signatures once, rather than verify N of them on every node.

This is the one genuine architecture investment for scale. It is a **consensus change** and
warrants its own design doc + tests before shipping — flagged here, not implemented.

### C. Unbounded free-lane state — see §4 / `doc/rolling-mode-and-da.md`
OPEN-lane `register` (PoSW recert) txs are fee-exempt and create permanent account state (the recert
lease itself lapses, but the account row persists). Bounding it is idle-account GC
(consensus-critical) + rolling history pruning.

---

## What's already fine

- Block cadence is config-driven (`block_time` default 6 s, `EPOCH_LENGTH=60`) — headroom,
  not a bottleneck.
- LMDB single-atomic-`write_txn` per block is a sound commit model (no write-amplification
  pathology); block bodies are `zstd(msgpack)`.
- Snapshot bootstrap exists (`snapshot_ops`, state-only `accounts.db` + Merkle `state_root`,
  80% peer quorum) so new nodes don't replay from genesis — the seed of rolling mode.
- The execution-layer plan correctly means L1 never has to be a high-TPS machine.

## Priority order

1. **Native ML-DSA** — seam shipped (#1); install an interop-correct native backend for the
   10–100× verify win on full nodes.
2. **Attack the O(N) consensus load** (§B / #2) — the real design fix; presence-root now,
   succinct PQ proof-of-threshold later.
3. ~~Binary encoding (#3)~~ — already handled by zstd; canonical change not worth the
   consensus risk.
4. **Idle-account GC + rolling history pruning** (#4 / §C) — `doc/rolling-mode-and-da.md`.
5. **Mempool O(N²)** — fixed (#5).

> Cross-references: `doc/execution-layer.md`, `doc/execution-layer-vm-research.md`,
> `doc/rolling-mode-and-da.md`, `doc/quantum-resistance-and-vms.md`, `Curve25519.py`
> (PQ backend seam), `loops/core_loop.py` (per-epoch consensus txs).
