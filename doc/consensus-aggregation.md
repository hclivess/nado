# Consensus-load aggregation — scaling L1 into the mainstream

> **Status: IMPLEMENTED** (live on alphanet-6). The two shipped pieces of the scaling envelope from
> [scaling-analysis.md](scaling-analysis.md) §A/§B/#1: a **native ML-DSA verify backend** (constant-factor,
> the immediate win) and the **merged committee-gated epoch duty** (the asymptotic fix, O(N)→O(seats)).
> Companion to [mining.md](mining.md) (selection), the FFG/RANDAO design, and
> [dividend-fraud-proof.md](dividend-fraud-proof.md) (the same committee-vs-quorum trade).

## 1. The wall

NADO's per-epoch consensus cost was **O(N) messages × non-aggregatable PQ signature × pure-Python verify**,
with N = bonded-validator count. Concretely, every bonded validator broadcast **three** full ML-DSA-signed
transactions per epoch — FFG `attest`, RANDAO `commit`, RANDAO `reveal` — so ~**3N** pure-consensus txs
competed with user payments for block space, and each was verified individually by every node in pure Python
(~15 ms/verify). At 10 000 validators that is 30 000 overhead txs/epoch before a single user tx, and the
verify cost alone saturates the chain. Two independent multipliers, attacked independently below.

PQ signatures **cannot aggregate** (BLS-style compression needs pairings, which are not post-quantum — and
NADO correctly chose PQ). So the fix is not "compress N signatures into one" but "**require far fewer than N
signatures**, and verify each one fast."

---

## 2. Native ML-DSA verify backend (the constant factor) — `native/mldsa44`, `nado_pq_native.py`

Signature **verification dominates block validation** — it is the chain's single biggest CPU cost. The
pure-Python `dilithium-py` backend is correct and dependency-free (it keeps "runs on a phone / a 386" true and
cross-validates with the browser light-miner), but slow. So verification is now pluggable:

| backend | verify | sign+keygen | when |
|---|---|---|---|
| `dilithium-py` (pure-Python, default) | ~15.6 ms | ~65 ms | phones, browsers, any host with no toolchain |
| **native Rust (`native/mldsa44`)** | **~0.28 ms** (**~55×**) | ~1.1 ms (~59×) | validators / full nodes that build it |

The Rust crate is a thin `cdylib` over the audited RustCrypto [`ml-dsa`](https://crates.io/crates/ml-dsa)
implementation, exposing exactly the three **FIPS 204 *internal*-mode** primitives the seam expects
(`keygen_internal`, `sign_internal`, `verify_internal` — **no context/domain wrapping**, matching
dilithium-py and the browser's `@noble/post-quantum`). It is bound by `ctypes` (stdlib, no pyo3), the same
pattern as the Rust Goldilocks prover in `wasm/goldilocks`.

**Consensus safety is unconditional.** `signatures.py` adopts a native backend ONLY after a startup **interop
self-test**: it cross-verifies the candidate against the pure-Python signer in *both* directions and checks
that seeded keygen is byte-identical (addresses derive from the public key). Any mismatch, import error, or
missing library → it logs loudly and stays pure-Python. So a wrong, stale, or absent build can never split
consensus — it simply doesn't accelerate. The signature *bytes* need not match across backends (ML-DSA is
hedged/randomized); consensus only ever checks `verify()==True`.

**Enable it:** `scripts/install.sh` asks interactively (or `--pq-native`), offers to install Rust via rustup,
builds it, verifies the self-test passes, and only then bakes `NADO_PQ_NATIVE_MODULE=nado_pq_native` into the
systemd unit. By hand: `scripts/build_pq_native.sh` then set that env var. Interop is pinned by
`tests/test_pq_native.py` (byte-identical seeded keygen + both-direction cross-verify vs dilithium-py).

This is a constant factor — it lowers the *slope* of the O(N) verify cost by ~55×, buying headroom, but the
asymptotics need §3.

---

## 3. Merged, committee-gated epoch duty (the asymptotics) — `duty` tx + `DUTY_COMMITTEE_SEATS`

Two changes collapse **3N → O(seats)**, constant in N:

### 3a. Merge the three duties into one signed tx (3N → N)

A validator's whole per-epoch participation — FFG `attest` (epoch X), RANDAO `commit` (X+2), RANDAO `reveal`
(X+1) — now rides in **one** fee-exempt `duty` transaction under a **single** ML-DSA signature, instead of
three. The three validation windows all overlap for the entire epoch except its last `FINALITY_DEPTH+1`
blocks, so one landing block satisfies all of them. Each section is validated by *exactly* the same field
rules as its historical single-duty form (shared `_validate_{attest,commit,reveal}_fields` helpers), and
applied/reverted through the identical KV mutations — so the merge changes packaging, never semantics.

`construct_duty_tx(keydict, max_block, attest=…, commit=…, reveal=…)` builds it; `core_loop.maybe_epoch_duty`
emits whichever sections are still due, once per epoch.

### 3b. A beacon-sampled committee posts them (N → O(seats))

Only a **duty committee** of `DUTY_COMMITTEE_SEATS = 128` seats may post duties in an epoch. Seats are
`DUTY_COMMITTEE_SEATS` independent **stake-weighted draws with replacement**, keyed `(beacon(X), "duty:X:i")`
— the *same* deterministic weighted-draw discipline as producer selection (`mining_ops.duty_committee`,
mirroring `_weighted_draw`). So:

- **Expected seats ∝ stake.** A validator with fraction *f* of bonded stake expects *128·f* seats.
- **Consensus load is O(128), constant in N.** At 16 or 16 000 validators, ≤128 duty txs per epoch.
- **The seat quorum converges on the stake quorum.** FFG justification counts **seats**:
  `attesting_seats · FFG_DEN > active_seats · FFG_NUM` (`attestation_ops.checkpoint_justified`, where
  `active_seats` is the leaked denominator of the next bullet). Because seats are stake-proportional, a
  2/3-seat supermajority *is* a ~2/3-stake supermajority. For an adversary holding < 1/3 of bonded stake,
  P(≥ 2/3 of 128 sampled seats) is cryptographically negligible (Chernoff) — the standard committee-security
  argument. With few validators, every share-holder lands seats and behavior matches the old full-set quorum.
- **Grind-resistant + known in advance.** Epoch X's committee derives from `beacon(X)`, which is fixed before
  X begins (the epoch-beacon anchor is deeply finalized; the RANDAO reveals mixed in are immutable when X
  starts). So membership is deterministic and known exactly when duties come due, and no producer can grind
  it.
- **Inactivity leak, now over seats.** FFG justification counts attesting seats against the seats held by
  **recently-active** committee members (those who attested within `INACTIVITY_WINDOW` epochs) — seats of
  members dark for the whole window leak from the denominator, so a live attesting supermajority always
  finalizes instead of being frozen by bonded-but-absent stake (the same liveness guarantee FFG had before
  the committee, seat-quantized; members active-but-idle this epoch still dilute, keeping the bar a real 2/3
  of participating stake). FFG also stays additive — the time/depth finality floor advances regardless
  (`incorporate_block`), so liveness never hinges on any single committee.

### 3c. Backward compatibility — none at runtime, full for history

Per alphanet's **no-legacy-tolerance** policy: the historical `attest`/`commit`/`reveal` recipients stay
**consensus-valid forever** (genesis sync must replay the blocks that contain them), but the mempool
**refuses new ones** — every honest validator emits the merged `duty`. Block-level uniqueness is enforced
across both forms: a `duty`-carried attest and a bare `attest` for the same `(sender, epoch)` (or two reveals
of one secret) can never share a block, in either order (`reserved_uniqueness_keys` emits one key per duty
section, matching the historical single-duty keys). Attestation-equivocation slashing sees through duty txs
too (the proof opener extracts the `attest` section), so a double-vote is punishable whether it was posted as
a bare attest or inside a duty.

---

## 4. Net effect

| | before | after |
|---|---|---|
| consensus txs / epoch | ~3N (attest+commit+reveal per validator) | ≤ `DUTY_COMMITTEE_SEATS` (128), constant in N |
| signature verify (validator) | ~15.6 ms (pure-Python) | ~0.28 ms (native Rust, self-test-gated) |
| FFG quorum basis | all bonded stake (+ inactivity leak) | committee seats (stake-proportional; resampled per epoch) |

Both are shipped and tested (`tests/test_duty_committee.py`, `tests/test_ffg_step6.py`,
`tests/test_pq_native.py`). Together they move L1 from "linear consensus overhead, slow verify" to "constant
committee overhead, fast verify" — the architecture investment scaling into the mainstream needs.

## 5. What remains

- **Succinct proof-of-threshold (the further step).** A single PQ-sound STARK proving *"≥2/3 of the committee
  attested checkpoint X"* would replace even the ≤128 attestation txs with one proof — the same proving
  machinery as Phase-2 settlement / the execution layer, applied to L1 consensus overhead. The committee
  already bounds the cost to a constant, so this is an optimization, not a wall; it lands behind the same
  seam if/when the prover is built.
- **Native backend distribution.** Today operators build the `.so` locally (install.sh automates it).
  Shipping prebuilt per-platform artifacts would remove even that step for validators without a toolchain.
