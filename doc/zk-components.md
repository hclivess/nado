# NADO zk components — the complete map

**Status: reference. Current as of 2026-08-04, chain `betanet-15`.**

Every zero-knowledge / proof-system component in the tree, what it does, where it lives, and — the part
that matters most — **whether it is actually load-bearing in production right now**. Sizes are `wc -l` of
the shipped source; numbers labelled *measured* were taken on this box against production state, not
estimated.

The companion docs go deep on individual subsystems; this one exists so you can see the whole surface at
once and tell live code from capability from research. If a doc and this table disagree about status,
**check the code** — `protocol.py` and `execnode/stark/*` are the source of truth.

> New to the vocabulary? [`zk-glossary.md`](zk-glossary.md) defines every term used below.

---

## 0. The honest summary

NADO has a **complete, working STARK stack** — field, FRI, AIR, recursion, an execution zkVM, a shielded
pool — and all of it is post-quantum (hash-based; no elliptic curves, no trusted setup). Three things use
it in production today:

| Uses proofs in production | How |
|---|---|
| **Shielded pool** (private transfers) | join-split STARK verified on the exec layer; proof published to DA, tx carries the commitment |
| **Provable games** | every zkVM call is provable; contract state settles into the L1-committed root |
| **Block authorization** | ML-DSA detached evidence (`mldsa_block_auth.py`) |

And one thing does **not** work yet, despite being fully implemented and switched on:

> **Trustless settlement — settling the exec root on a validity proof instead of a bonded quorum — has
> never completed end-to-end.** The consensus rule is live and unconditional
> (`SETTLE_PROOF_TRUSTLESS = True`) and the prover produces correct proofs that pass their self-checks.
> What has never happened is a settle transaction carrying a proof landing on chain and a peer verifying
> it. §14 documents exactly where it stops.

Measured directly from the exec node's journal (33 064 lines, 2026-08-01 → 08-06):

| | count |
|---|---|
| proofs built, self-checks passed, tx constructed | **89** |
| **accepted on chain** (`SETTLE-WITH-PROOF … → L1`) | **0** |
| published to DA | 0 |
| refused by L1 | **85** — `HTTP 413, Maximum request body size 8388608 exceeded` |

Zero proof builds appear before 2026-08-01. Note what this says and does not say: **the self-check was
never the historical blocker — size was.** 89 proofs passed their self-checks and were submitted, and
every one bounced off the 8 MiB cap at 97.30–97.45 MiB. The `PRE MISMATCH` self-check failures in §14
are a *later* condition, not the long-standing one.

> Evidence discipline, since this bit twice: "no such line in the log" is not "it never happened" when
> the log line was only added recently. The `BUILT` line (§14) is newer than the behaviour it reports, so
> its first appearance on 2026-08-04 was the first appearance of the *line*, not of a passing self-check.

Everything else in this document is either live, or explicitly labelled capability/research/removed.

---

## 1. Arithmetic core

The bottom of the stack. Everything above is built from these.

| Component | File | Lines | Status | Notes |
|---|---|---|---|---|
| Goldilocks field | `execnode/stark/field.py` | 152 | **LIVE** | p = 2⁶⁴ − 2³² + 1 = 18446744069414584321. Chosen for fast reduction (2⁶⁴ ≡ 2³²−1, 2⁹⁶ ≡ −1) |
| Extension field GF(p^d) | `execnode/stark/extf.py` | 351 | **LIVE** | Needed for soundness: challenges drawn from the base field alone are too few. Measured 2.8× base-field proving cost — the Rust arena is base-field only |
| Merkle commitment | `execnode/stark/merkle.py` | 77 | **LIVE** | The polynomial-commitment primitive |
| Fiat–Shamir transcript | `execnode/stark/transcript.py` | 79 | **LIVE** | Makes the interactive protocol non-interactive |
| Soundness calculator | `execnode/stark/soundness.py` | 316 | **LIVE** | What the FRI parameters *actually* buy, rather than what they are assumed to buy |

**FRI parameters (protocol strength):** `NUM_QUERIES = 320`, `FRI_BLOWUP = 2`, `GRIND_BITS = 18` →
≈ 320 × 0.4 + 18 ≈ **146 provable bits** (Johnson bound). Blowup 2 buys only 0.4 bits per query, which is
precisely why 320 queries are needed — and why the proof is large (§7).

---

## 2. Algebraic hashes

A STARK that verifies another STARK must hash *inside* a circuit, so the hash has to be cheap in field
operations. Blake2b is not; these are.

| Component | File | Lines | Status | Notes |
|---|---|---|---|---|
| alghash (v1) | `execnode/stark/alghash.py` | 87 | **LIVE** | First-generation in-circuit hash |
| **alghash2** | `execnode/stark/alghash2.py` | 426 | **LIVE** | The recursion-layer hash. Wide sponge over Goldilocks: WIDTH 12, RATE 8, CAPACITY 4, α = 7, 54 rounds |
| Backend selection | `execnode/stark/backend.py` | 167 | **LIVE** | `BLAKE2B` / `ALGHASH2` / `RECURSION`. The Rust arena covers `alghash2` and `recursion` only |
| alghash2 in-VM | `execnode/stark/zkvm_alghash2.py` | 87 | capability | The in-VM STARK verifier route |

**alghash2 is post-quantum.** It is a hash, so there is no Shor target. 256-bit capacity gives 128-bit
classical collision resistance and 128-bit Grover preimage resistance (~2⁸⁵ under Brassard–Høyer–Tapp, and
that needs 2⁸⁵ QRAM). Algebraic degree 7⁵⁴ ≈ 2¹⁵¹·⁶.

> **Backend default is load-bearing.** `BLAKE2B` was once the default and silently put the entire prover
> in Python — 12+ minutes at 75% of a core, starving L1 into a re-anchor. Fixed in `7afb5728`; the
> default is now `ALGHASH2`, which the Rust arena covers.

---

## 3. STARK proving

| Component | File | Lines | Status | Notes |
|---|---|---|---|---|
| STARK prover/verifier | `execnode/stark/stark.py` | 669 | **LIVE** | Prove a trace satisfies its AIR. Dispatches to the native arena |
| FRI | `execnode/stark/fri.py` | 332 | **LIVE** | Low-degree proximity test — the engine underneath every proof |
| Constraint IR | `execnode/stark/air_ir.py` | 372 | **LIVE** | Traces AIR closures into a flat hash-consed DAG |
| LogUp | `execnode/stark/logup.py` | 85 | **LIVE** | Log-derivative lookup/permutation argument — the memory-checking machinery |

---

## 4. Execution proofs (the zkVM)

| Component | File | Lines | Status | Notes |
|---|---|---|---|---|
| zkVM | `execnode/zkvm.py` | 521 | **LIVE** | The field-native VM every contract runs on — the only runtime |
| zkVM execution AIR | `execnode/stark/vm_circuit.py` | 1182 | **LIVE** | Proves "running public program `code` on this input yields this output". The largest single circuit |
| Exec state root | `execnode/exec_root.py` | 210 | **LIVE** | `state_root = rnode(kv half, records half)`, two depth-256 sparse trees |

Doc: [`zk-execution-proofs.md`](zk-execution-proofs.md). **25 contracts run on this today** (verified
live on chain): the game suite plus faucet, lending, reserve and sovereign.

---

## 5. Privacy — the shielded pool

| Component | File | Lines | Status |
|---|---|---|---|
| Shielded pool state machine | `execnode/shielded.py` | 317 | **LIVE** |
| Join-split AIR | `execnode/stark/joinsplit.py` | 120 | **LIVE** |
| 1-in/1-out circuit | `execnode/stark/joinsplit_circuit.py` | 386 | **LIVE** |
| 2-output circuit | `execnode/stark/joinsplit2.py` | 410 | **LIVE** |
| Transfer verifier seam | `execnode/stark/joinsplit_transfer.py` | 77 | **LIVE** |
| Merkle membership AIR | `execnode/stark/membership.py` | 184 | **LIVE** |

Doc: [`privacy.md`](privacy.md). **This is the one place where the full proof→DA→commitment→verify loop
already works in production** — which is why it is the reference implementation for the settlement
transport that does not (§7).

---

## 6. State-root binding and settlement proving

Proving *that the exec state root moved correctly* — the machinery a validity-settled rollup needs.

| Component | File | Lines | Status | Notes |
|---|---|---|---|---|
| Sparse Merkle storage tree | `execnode/stark/storage_tree.py` | 237 | **LIVE** | Depth 256 (`EXEC_TREE_DEPTH`), alghash2 nodes. **Measured hot spot** — see below |
| Merkle-update AIR | `execnode/stark/merkle_update.py` | 181 | **LIVE** | In-circuit tree update |
| State transition proof | `execnode/stark/state_transition.py` | 87 | **LIVE** | |
| Calls commitment | `execnode/stark/calls_commit.py` | 344 | **LIVE** | Binds the epoch's calls |
| Sparse-root settlement | `execnode/stark/settlement_sparse.py` | 460 | **LIVE** | `prove_bound_epoch` / `verify_bound_epoch` — the top-level settlement prover |
| Exec-state binding | `execnode/stark/exec_state_bind.py` | 93 | **LIVE** | |
| Records binding | `execnode/stark/records_bind.py` | 326 | **LIVE** | `SETTLE_PROOF_RECORDS`, live since the betanet-15 reroll |
| Records transition | `execnode/stark/records_transition.py` | 134 | **LIVE** | |
| Single-bundle aggregation | `execnode/stark/settlement_aggregate.py` | 55 | capability | |
| O(1)-shaped bound epoch | `execnode/stark/bound_epoch_o1.py` | 84 | capability | |

**Measured proving cost** (production state: 25 contracts, 7 780 zkVM storage slots, empty call span):

| stage | time |
|---|---|
| `sparse_projection` | 137–158 s |
| `prove_epoch` | 100–124 s |
| `prove_transition` | 0.0 s |
| **total** | **240–270 s** |

Two things worth knowing, both of which contradict what was previously assumed here:

1. **`sparse_projection` dominates**, not `prove_epoch`. An earlier note claimed it was free (0.0 s) and
   said not to optimise it — that measurement came from an *empty-state fixture*. On production shape it
   is the single largest stage.
2. Inside it, `SparseStore.root()` is **65.8 s standalone**: 1 892 408 `rnode` calls (~243 per leaf — the
   singleton folds through 256 empty levels). But the seam is *not* the cost. Measured, native
   `permute12` is **26.92 µs** of the **35.41 µs** `rnode` call, so the kernel dominates and porting the
   tree walk to Rust would buy only ~24%.

---

## 7. Recursion — O(1) verification

Verifying a proof inside a proof, so an epoch verifies in constant time. Doc: [`zk-recursion.md`](zk-recursion.md).

| Component | File | Lines | Status |
|---|---|---|---|
| Recursion core | `execnode/stark/recursion.py` | 972 | **LIVE** (`SETTLE_PROOF_RECURSIVE`) |
| In-circuit STARK verify | `execnode/stark/recursive_verify.py` | 381 | **LIVE** |
| Heterogeneous recursion | `execnode/stark/recursive_verify_hetero.py` | 224 | **LIVE** |
| In-circuit FRI verify + fold | `execnode/stark/fri_verify.py` | 728 | **LIVE** |
| Composition spot-check | `execnode/stark/comp_verify.py` | 464 | **LIVE** |
| Row-committed composition check | `execnode/stark/rowcomp_verify.py` | 551 | **LIVE** |
| Recursion depth (fold-of-folds) | `execnode/stark/recursion_depth.py` | 159 | **LIVE** |
| Recursion depth, authoritative | `execnode/stark/recursion_authdepth.py` | 108 | **LIVE** |
| In-circuit Fiat–Shamir sponge | `execnode/stark/fs_incircuit.py` | 138 | **LIVE** |
| FS step (one challenge) | `execnode/stark/fs_step.py` | 168 | **LIVE** |
| FS chain (whole transcript) | `execnode/stark/fs_chain.py` | 114 | **LIVE** |
| DEEP out-of-domain evaluation | `execnode/stark/deep_eval.py` | 101 | **LIVE** |
| LogUp multiset equality | `execnode/stark/logup_bind.py` | 205 | **LIVE** |
| In-circuit io replay | `execnode/stark/io_replay.py` | 102 | **LIVE** |
| Fold-layer io binding | `execnode/stark/io_bind.py` | 79 | **LIVE** |
| In-circuit `slot_key` | `execnode/stark/slot_key_air.py` | 88 | **LIVE** |
| State-side io tie | `execnode/stark/state_io_tie.py` | 80 | **LIVE** |
| State merge | `execnode/stark/state_merge.py` | 165 | **LIVE** |

**The K→1 fold is implemented and switched on but has never actually run**, because it needs contract
calls to fold and the chain has been idle: `settlement_sparse` raises on an empty call span, so the
exec node deliberately falls through to the unfolded prove (`fold skipped … no exec calls to fold`).
The fold is an upgrade to a proof we want either way — never a precondition for producing one.

---

## 8. Native acceleration (Rust)

**Policy: Rust-only, no fallback.** A Python path shadowing a Rust one is invisible degradation, so the
guard fail-stops rather than silently degrading. Doc: [`rust-only-proving.md`](rust-only-proving.md).

| Crate | Lines | Covers |
|---|---|---|
| `native/starkprove` | 2 222 | The holistic prover: persistent LDE arena, `sp_fold`, `sp_fri_size`, `sp_lde_column`, `sp_reset` |
| `native/alghash2` | 388 | `permute12`, `hashn`, `merkle_commit`, `rmerkle_commit`, `grind`, `merkle_verify_paths` |
| `native/starkcompose` | 172 | Composition |
| `native/mldsa44` | 103 | ML-DSA-44 post-quantum signatures |

| Binding | File | Lines |
|---|---|---|
| Native guard | `execnode/stark/native_guard.py` | 142 |
| Holistic prover binding | `execnode/stark/stark_native.py` | 619 |
| Native Goldilocks NTT | `execnode/stark/goldilocks_native.py` | 107 |

Three rules learned the hard way, each of which cost a wrong diagnosis:

- **Read the crate, not the docstring.** `native_guard.py`'s "no Rust counterpart exists" list was wrong.
- **A guard above a dispatch blocks the native path too** (`944a01b6` → `ea8dbcd5`).
- **Verify via `/proc/PID/maps`**, never CPU load. A mapped `.so` is evidence; a busy core is not.
- **Rebuild after touching `native/*/src/*.rs`** — a stale `.so` fail-stops `nado-exec`, and
  `Restart=always` hides it behind "exec node unreachable".

**`native/alghash2` has no sparse-tree function.** It exports dense Merkle commits only, so
`SparseStore` walks the tree from Python one `rnode` at a time. Per §6 that is kernel-bound, so this is a
~24% opportunity, not the 30× it looks like.

---

## 9. Transport — proof size and data availability

The binding constraint on validity settlement is **size**, and it is not close.

| Quantity | Value |
|---|---|
| Settle-with-proof, one segment | **97–118 MiB** (measured live) |
| L1 submit cap | 8 MiB |
| `MAX_BLOB_BYTES_PER_BLOCK` | 1 MiB |
| A full block | ~256 KiB |

The proof is **~380× an entire block**. Payload is O(queries), not O(state) — perfectly linear at
0.381 MiB/query — so even the best FRI reparameterisation (blowup 16, ~64 queries) still gives ~24 MiB,
~95× a block. **A 4–6× reduction cannot close a 380× gap.** Publishing to DA and carrying only a
commitment is therefore not an optimisation; it is the only available architecture.

| Component | File | Lines | Status |
|---|---|---|---|
| Erasure coding + commitment | `ops/da.py` | 196 | **LIVE** |
| DA store (shards + proofs) | `ops/da_store.py` | 148 | **LIVE** |

DA is k-of-n Reed–Solomon (k=4, n=8 for settle proofs) with a hash-based, index-bound Merkle commitment;
`da_fetch` collects k+1 verified shards and checks the commitment round-trip.

> **Measured 2026-08-04:** `da.encode` ran at **~15 s/MiB**, so encoding a 118 MiB proof took **~30
> minutes** — which is why a proof that passed its self-checks produced no publish for as long as anyone
> watched. The cause was algorithmic, not the language: `_encode_stripe` → `_lagrange_eval` → `_inv(a) =
> pow(a, P−2, P)`, a full modular exponentiation in the innermost loop, ~141 million of them per proof —
> even though the encode's interpolation points are fixed, making those Lagrange coefficients constants.
> Hoisted to a cached (k, n) generator matrix in `08945e50`: **15.08 → 0.428 s/MiB (35×)**, bit-identical
> (same commitment, same shard bytes), verified against the original implementation kept as an oracle in
> `tests/test_da_encode_matrix.py`.

Doc: [`settle-proof-transport.md`](settle-proof-transport.md), [`rolling-mode-and-da.md`](rolling-mode-and-da.md) (design only).

### Availability is not validity

A DA-published proof we cannot fetch must **defer** the block, never reject it. Three outcomes, not two:

| Outcome | Action |
|---|---|
| proof resolved and verified | accept |
| proof resolved and did **not** verify (or resolved to non-proof bytes) | reject |
| proof did not resolve | **defer** |

Rejecting on unavailability would split the chain along *who happens to hold shards*, since the justified
`(exec_cursor, exec_root)` goes in the L1 block header. Deferral is fork-free because every node applies
the same rule, and a DA outage costs liveness, never safety. The wait is bounded: past `FINALITY_DEPTH`
the proof is not consulted at all (`SETTLE_PROOF_DEPTH_GATED`), so a withholder can only make us wait.
This is the 4844/Celestia blob rule; the exec layer already implements it one level down for
`field_transfer`. Tests: `tests/test_settle_proof_da_defer.py`.

---

## 10. Consensus integration

| Constant (`protocol.py`) | Value | Meaning |
|---|---|---|
| `SETTLE_PROOF_TRUSTLESS` | `True` | A valid proof settles the root with **no bonded quorum** |
| `SETTLE_PROOF_RECURSIVE` | `True` | L1 honours a K→1 recursion bundle |
| `SETTLE_PROOF_RECORDS` | `True` | Records half is bound too (betanet-15 reroll) |
| `SETTLE_PROOF_DEPTH_GATED` | `True` | Proofs not consulted past `FINALITY_DEPTH` |
| `SETTLE_PROOF_MAX_SPAN` | 240 | 4 × `EPOCH_LENGTH` |
| `EXEC_TREE_DEPTH` | 256 | Full digest-width slot space; never needs a depth bump |
| `EPOCH_LENGTH` | 60 | Dividend epoch — **a proven span may not cross one** |
| `FINALITY_DEPTH` | 45 | |

**There are no ZK feature flags.** `SETTLE`, `SETTLE_PROVE` and `SETTLE_FOLD` were deleted in `74957663`;
proving is unconditional. The bare bonded-quorum attestation exists **only** as the degradation path when
a proof cannot be produced, and every degradation names its reason in the log.

The tightest rule in practice is the **epoch boundary**: a dividend moves the records half, and the proof
pins records unchanged across the span, so `sc // EPOCH_LENGTH` must equal `cur // EPOCH_LENGTH`. This
made proofs structurally impossible for a long time — 95 of 128 observed skips — until the settle cadence
was aligned to the epoch grid (`fde96f46`).

---

## 11. Post-quantum cryptography

Not zero-knowledge, but the same threat model, and the reason the proof stack is hash-based throughout.

| Component | Where | Status |
|---|---|---|
| ML-DSA-44 signatures | `native/mldsa44`, `nado_pq_native` | **LIVE** — every transaction |
| Block authorization + detached evidence | `execnode/stark/mldsa_block_auth.py` (211) | **LIVE** |
| ML-KEM-768 | on-chain messaging | **LIVE** |

No elliptic curves, no pairings, no trusted setup anywhere in the stack. Doc:
[`quantum-resistance-and-vms.md`](quantum-resistance-and-vms.md).

---

## 12. Browser prover

650 lines of JavaScript in `static/stark/` — `field`, `merkle`, `tree`, `fri`, `stark`, `transcript`,
`hashing`, `bhash`, `joinsplit2` — so a phone can produce a shielded-transfer proof with no install.
Tier A (JS/BigInt) is done and live. Doc: [`wasm-prover.md`](wasm-prover.md).

---

## 13. Research and removed

| Item | Doc | Status |
|---|---|---|
| Signature aggregation | [`zk-signature-aggregation.md`](zk-signature-aggregation.md) | **REMOVED 2026-07-31** — built, measured, deleted. Post-mortem kept deliberately |
| Program obfuscation (Diamond iO) | [`obfuscation-diamond-io.md`](obfuscation-diamond-io.md) | Research goal. Nothing implemented, scheduled, or promised |
| Rolling mode / DA sampling | [`rolling-mode-and-da.md`](rolling-mode-and-da.md) | Design only |

---

## 14. Where trustless settlement actually stops

Kept explicit because this is the single most over-claimed part of the stack. Each of these was only
visible after the previous was fixed:

| Fix | What it was |
|---|---|
| `fde96f46` | **Cadence.** Spans straddled the 60-block dividend epoch boundary (95 of 128 skips), making proofs structurally impossible. Epoch-aligned re-anchor → spans started reaching the prover |
| `966f5c31` | **Silence.** A prove completed and nothing followed it — there was no log line between the prove and the publish, so "finished and vanished" was indistinguishable from "still running" |
| `6a903a09` | **Root/records skew.** `state_root = rnode(kv, records)`, but the root was captured at cursor C while the records half was recomputed later from a live state the detached tail had advanced — two roots that were never simultaneously true |
| `106276e7` | **The diagnostic.** "not conforming" named neither half, so three different bugs printed the same line |
| `08945e50` | **DA encode.** ~30 minutes to erasure-code one proof (§9) |

**Current blocker (2026-08-04, from the `106276e7` diagnostic):**

```
self-check FAILED span 19642->19672 — PRE MISMATCH: proof=2231ff74… justified=af2aba29… |
POST ok: proof=2231ff74… ours=2231ff74… | kv_pre=b84514fa… kv_post=b84514fa… calls=0
```

The **post** side is exact — replaying the span reproduces our own root. The **pre** side does not match
L1's justified root, i.e. the stashed pre-state does not reproduce the root L1 actually justified at that
cursor. That is where the work is.

### Ground rules this subsystem taught us

- **Read the code, not the comment.** Four load-bearing comments asserted behaviour that had stopped
  being true: the `SETTLE_EVERY` "re-anchor" that never re-anchored; "detaching cannot pile tasks up"
  (it bounds *proves*, not *tasks*); "the tail loop is single-task, so `st` does not advance" (false once
  settling was detached); and the native-guard list of missing Rust.
- **Benchmark against production shape.** An empty-state fixture misled three separate conclusions.
- **An unlogged path is an invisible path.** Instrument the *gap*, not just the endpoints.
- **An algorithmic fix can beat a language port** — hoisting one loop-invariant matrix gave 35× at zero
  risk, where the Rust port being planned would have given ~24% on the wrong stage.
- **When changing consensus-visible math, keep the old implementation as an oracle** and diff against it.

---

## 15. Doc index

| Doc | Covers |
|---|---|
| [`zk-glossary.md`](zk-glossary.md) | Every term in the proof stack, in plain language — **start here** |
| [`zk-execution-proofs.md`](zk-execution-proofs.md) | Proving contract execution (the zkVM AIR) |
| [`zk-recursion.md`](zk-recursion.md) | Recursion, O(1) verification, alghash2, the K→1 fold |
| [`zk-settlement-completion.md`](zk-settlement-completion.md) | Trustless settlement completion checklist |
| [`zk-signature-aggregation.md`](zk-signature-aggregation.md) | Post-mortem: built, measured, removed |
| [`privacy.md`](privacy.md) | The shielded pool |
| [`rust-only-proving.md`](rust-only-proving.md) | Why a hybrid prover is not a prover |
| [`settle-proof-transport.md`](settle-proof-transport.md) | Getting a settle-with-proof onto the chain |
| [`rolling-mode-and-da.md`](rolling-mode-and-da.md) | Rolling mode + DA sampling (design) |
| [`wasm-prover.md`](wasm-prover.md) | On-device proving in the browser |
| [`quantum-resistance-and-vms.md`](quantum-resistance-and-vms.md) | Why PQ lives in the proof system, not the VM |
| [`provable-practice.md`](provable-practice.md) | Provable practice runs / unforgeable leaderboards |
| [`obfuscation-diamond-io.md`](obfuscation-diamond-io.md) | Program obfuscation (research) |
| [`l2-settlement.md`](l2-settlement.md) | Settlement layer / scaling analysis |
| [`execution-layer.md`](execution-layer.md) | The execution layer end to end |
