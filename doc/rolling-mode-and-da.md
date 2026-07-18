# Rolling mode & data availability — design note

**Status: DESIGN ONLY. Nothing here is built** (except where it says "already exists").
Rolling mode lets a node keep only the **state plus a window of recent epochs** and drop
older block history, so NADO stays **phone-mineable under adoption** — a phone can never
hold full history. The moment nodes prune, they create a **data-availability (DA)
obligation**, and (this being a PQ chain) the DA commitments must themselves be
post-quantum. This note designs both, and folds in the consensus-critical **idle-account
GC** (scaling item #4).

The guiding distinction, kept crisp throughout:

| Thing | Kept by a rolling node? | Why |
|---|---|---|
| **State** (accounts: balance/bonded/produced, KV indices) | **Always** | It's what every new block validates against |
| **Block history** (past block bodies / txs) | Only the last *K* epochs | Needed only for the rollback window + serving peers |
| **Data availability** | Guaranteed for a window, then offloaded | The obligation that pruning creates |

Rolling mode prunes **history**, never **state**.

---

## 1. What NADO already has (the substrate is mostly here)

- **Finality.** `FINALITY_DEPTH = 30`; `finalized_height` advances monotonically
  (`incorporate_block` → `max(prev, tip − FINALITY_DEPTH)`), and rollback **refuses** to
  cross it. So a node provably never needs block bodies below the finalized height to
  *validate* — only to *serve* or *re-audit*.
- **State snapshots.** `ops/snapshot_ops.py` already produces a **state-only** snapshot
  (`accounts.db`: acc_index + totals_index) at a finalized checkpoint height C, chunked,
  with a blake2b **Merkle `state_root`**, accepted only on **80% peer quorum**, anchored to
  the block hash at C, then the short C..tip tail is replayed through normal validation.
  `transactions.db` is explicitly **not** consensus-critical (explorer/history, rebuildable).
- **Block bodies are already separable.** Stored as `zstd(codec)` records in append-only
  segment files under `blocks/` (see `ops/segment_store.py`; ~300 files/year instead of one
  file per block); the LMDB KV is a **derived, rebuildable index**, including the body locators.

**A snapshot is already a pruned state.** Rolling mode is mostly: *keep making snapshots,
keep the last K epochs of bodies, drop the rest, and define who still has the old data.*

---

## 2. Rolling mode (L1 history pruning)

### 2.1 The retention window — IMPLEMENTED (Phase 1)
`protocol.HISTORY_RETENTION_BLOCKS` (default **100 800** ≈ 1 week at 6 s blocks; config /
`NADO_HISTORY_RETENTION_BLOCKS` overridable) sets how many recent block **bodies** a rolling
node keeps. Below that, finalized **bodies** are UNREFERENCED (their segment locators dropped)
and whole segment files are reclaimed once every body in them is gone — blob-bearing bodies are
copied forward first (contract history); the **state**, and the tiny **number↔hash indexes**,
always stay.

**Retention-floor invariant (correctness-critical) — the audit refined this.** The design
first guessed the floor was ≈ `FINALITY_DEPTH`; the actual audit of every historical
`get_block*` call (done before implementing) found it is **`REWARD_WINDOW` (100)**, deeper
than finality:
- `get_block_reward` reads `cumulative_fees` from the block at **`tip − REWARD_WINDOW`** — and
  today reads it by loading that whole **body**. So bodies must be retained past
  `REWARD_WINDOW`, or the reward calc forks.
- Rollback re-reads bodies within `FINALITY_DEPTH (30)` of the tip.
- The beacon (~2 epochs) and FFG (`_FFG_LOOKBACK_EPOCHS = 8` → 480 blocks) read only **hashes**
  via `get_block_hash_by_number`, which hits the **`block_by_num` index, not bodies** — so
  keeping the index (always) satisfies them regardless of body pruning.
- Most other "lookbacks" read **state**, not bodies (a `withdraw` checks the KV pending-unbond
  record, not the 1440-block-old bond body — `BOND_UNLOCK_DELAY = 1440` does **not** force body
  retention).

So the **body** floor = `max(retention, REWARD_WINDOW + FINALITY_DEPTH + 1)`.
`block_ops.prune_block_bodies` enforces that floor internally, so even a misconfigured tiny
`retention` can never corrupt the reward calc or a legal rollback. Pruning **keeps the index**
(beacon/FFG still resolve) and is incremental via a `pruned_below` meta watermark. A future
optimization — index `cumulative_fees` by height to decouple `get_block_reward` from the body —
would let the floor drop to `FINALITY_DEPTH`; not needed at a 10 000-block window.

**Earliest-block-pointer maintenance (part of pruning — a fix).** Dropping the oldest bodies means
the recorded **earliest block** can point at a body that no longer exists on disk. `prune_block_bodies`
therefore **advances the earliest-block pointer** (`block_ends` → `set_earliest_block_info`) to the
earliest *retained* body (height `end`, the first block at/above `pruned_below`, which is never
pruned) in the same pass. This closes a bug where the pointer was left dangling: `get_block_ends_info`
would try to load the pruned earliest body, `load_block_from_hash` returned `False`, and every
`/status` (which reads `earliest_block["block_hash"]`) then **403'd — stalling the execution node and
wallet connection**. As a defensive backstop, `get_block_ends_info` also recovers a dangling pointer
by walking up from the `pruned_below` watermark to the first retained body (falling back to the latest
block, which is always kept), so `memserver.earliest_block` is **always** a real dict.

**Status:** implemented + unit-tested (`tests/test_rolling_prune.py`): prunes below the window,
keeps indexes, respects the safety floor, idempotent/incremental. Gated by the `archive` node
role (§2.2) which **defaults to keep-everything**, so this is opt-in with zero behaviour change
until a node sets `archive=false` / `NADO_ARCHIVE=0`.

### 2.2 Node tiers
- **Rolling (pruned) node — the default at scale.** State + last K epochs + finalized
  headers. Bootstraps from a snapshot, never from genesis.
- **Archive node — opt-in.** Retains full history (or a configured range). Serves deep
  history and bootstrap data. This is the Ethereum post-EIP-4444 model: most nodes prune;
  a smaller set voluntarily archives.

### 2.3 Bootstrap = weak subjectivity
A joining rolling node trusts a **recent finalized, signed checkpoint** (the snapshot
`state_root` at C, accepted on quorum) instead of verifying from genesis. This is a
deliberate, standard trust shift already implied by finality. The roadmap item
"snapshot-bootstrap binding to a finalized signed checkpoint" (whitepaper §8) is exactly the
hardening this needs: bind the snapshot to a finalized, validator-signed checkpoint hash so
the 80% quorum can't be gamed by a colluding minority.

---

## 3. Idle-account GC (scaling item #4) — consensus-critical state pruning

**IMPLEMENTED** (`ops/gc_ops.py`): deterministic, in-block, revert-safe. Two watermarked sweeps
run inside the first block of each epoch's write txn — trivially-empty account docs whose lease
lapsed > `GC_IDLE_EPOCHS` (1000) ago are deleted (schemaless extras like `public_key`/`kem_pub`
exempt an account permanently); recert rows older than `RECERT_HISTORY_EPOCHS` (10 000) drop by
whole epoch buckets, ordered so rows outlive the account sweep that reads them. Weight safety: a
continuous recert run crossing the retention horizon necessarily exceeds `FIDELITY_CAP`, so
`open_shares(fidelity_at_epoch(E))` is byte-identical with or without the pruned rows for every E
still served (`/get_open_weights` refuses older epochs; cold exec nodes bootstrap from a settled
checkpoint via `NADO_EXEC_BOOTSTRAP` instead of genesis replay). Rollback restores everything from
the node-local `gc_revert` record. Presence itself is
now self-bounding — the old per-epoch heartbeat rows are gone, replaced by the PoSW **recert lease**
(`recerts` / `recert_by_epoch`), which lapses if not renewed each `POSW_LEASE_EPOCHS` — yet the free
OPEN lane's fee-exempt `register` (recert) txs still create permanent **account** state that never
expires, an unbounded growth vector.

**Why it cannot be a local sweep:** deleting an account row changes the **state root**. If
nodes pruned independently, their roots would diverge → chain fork. So idle-account GC must
be **deterministic and applied identically by every node inside block processing**, and the
pruned set must be reflected in the snapshot `state_root`. Design:

- **Predicate (must be exact and total-order-deterministic):** prune an account iff
  `balance == 0` **and** `bonded == 0` **and** no pending unbond **and** registry-only
  **and** last-activity epoch `< current_epoch − GC_IDLE_EPOCHS`. Never prune anything with
  value, stake, or a pending obligation.
- **When:** at deterministic epoch boundaries, as an ordered pass folded into the block's
  state transition (so it's in the committed state root and is revert-symmetric, like
  every other state mutation).
- **Re-creation:** a pruned address that later re-appears is just a fresh `register` — must
  be deterministic and indistinguishable from a never-seen address.
- **Status: SHIPPED** (`ops/gc_ops.py`): the predicate above runs as an ordered epoch-boundary
  pass folded into the committed state root, revert-symmetric, with its own test file — GC
  determinism, revert symmetry, snapshot-root agreement, and "never prunes a valued/staked/pending
  account" all covered.

---

## 4. Securing data availability

Pruning splits DA into **two very different difficulty tiers.** Conflating them is the
classic mistake.

### 4.1 Tier 1 — L1 consensus history (EASY; finality already does the heavy lifting)
Why would anyone need a pruned old block? (a) New-node bootstrap → solved by the **state
snapshot**, no history needed. (b) Independent re-derivation of state by someone who refuses
to trust the snapshot → weak-subjectivity audit. (c) Serving peers.

For **consensus safety**, none of this needs cryptographic DA: **finality already guarantees
the finalized state can't be reverted.** What's needed is only the *social* ability to
fetch/audit old data, provided by **≥1 reachable archive node + the snapshot quorum** — the
EIP-4444 model. Be honest about the trust assumption: this is **best-effort archival, not a
cryptographic availability guarantee**, and the security rests on finality + weak
subjectivity, not on DA. That's an acceptable, standard trade — and it's cheap.

### 4.2 Tier 2 — execution-layer blobs (HARD; this is where real DA crypto is needed)
The execution layer (`doc/execution-layer.md`) posts **opaque blobs** into L1 blocks for
ordering + availability. If L1 keeps blobs only for a retention window, the data must be
provably **reconstructable** within that window — this is the genuine DA problem:

- **Erasure coding.** Reed–Solomon-encode each block's blob data with a (configurable, e.g.
  2×) expansion and distribute coded chunks across the validator set so **any ~50% of
  chunks reconstruct the whole**. A node storing only its assigned chunks contributes to
  reconstructability without holding everything — phone-friendly.
- **Data Availability Sampling (DAS).** Light clients / phones verify availability by
  random-sampling a few chunks against a commitment in the block header; if the samples are
  available, the whole is (whp) reconstructable. **The commitment MUST be post-quantum** —
  a **Merkle / FRI (hash-based) vector commitment, NOT KZG.** KZG is pairing-based and would
  re-introduce a quantum-breakable primitive into a PQ chain (`doc/quantum-resistance-and-
  vms.md`). This is the single most important DA design constraint for NADO.
- **Availability challenge window.** During retention, anyone can challenge "chunk *i*
  unavailable"; failure to produce it marks the block unavailable **before finalization**
  (or penalizes the responsible party). After the window + finalization + a reconstruction
  guarantee, blob bodies may be dropped.
- **External DA / pinning fallback.** Allow anchoring blob data to an external DA layer or
  pinning to archive nodes for data needing longevity beyond the protocol window.

Full 2D-DAS is heavy; for NADO's stage, **1D Reed–Solomon + hash-based sampling + a challenge
window + voluntary archival** is the right weight — real reconstructability without a
research-grade DA stack. The PQ proof-of-availability ties to the same hash-based backend the
execution-layer research recommends (`doc/execution-layer-vm-research.md`).

---

## 5. Why this keeps NADO phone-mineable

Rolling mode is what *makes* phone-mining survive adoption: a phone keeps **state + K epochs
+ finalized headers**, does **DAS sampling** instead of storing blobs, bootstraps from a
**snapshot**, and never touches full history. Without it, state + history growth quietly
demotes phones to non-validating light clients — losing the identity. With it, the phone
stays a first-class participant at any chain age.

One honesty caveat: even pruned nodes relay recent blocks, and blobs grow block size, so the
execution-layer DA constraints (`MAX_BLOB_BYTES`, prunable bodies, phones skip blob bodies)
in `doc/execution-layer.md` §3.3 are part of the same budget — rolling mode and blob caps
must be designed together.

---

## 6. Phasing

1. **L1 history pruning (safe, do first).** `HISTORY_RETENTION_EPOCHS` + the
   historical-lookback audit + archive-node flag + weak-subjectivity bootstrap hardening.
   Leverages existing finality + snapshots; Tier-1 DA = archival. No new crypto.
2. **Idle-account GC (consensus change).** Deterministic, in-block, snapshot-root-bound,
   with its own test suite (§3).
3. **Execution-layer blob DA (live — the execution layer shipped).** Reed–Solomon + **hash-based
   (PQ) DAS** + challenge window + external-DA fallback (§4.2).

> Cross-references: `ops/snapshot_ops.py` (state snapshot + Merkle root + quorum),
> `ops/kv_ops.py` (block-body store + prune primitives + recert lease stores `recerts` /
> `recert_by_epoch` + `hb_revert_gc`), `protocol.py`
> (`FINALITY_DEPTH`, `GC_IDLE_EPOCHS`, `BOND_UNLOCK_DELAY`, `POSW_LEASE_EPOCHS`),
> `doc/execution-layer.md` (blob DA constraints), `doc/quantum-resistance-and-vms.md` (why DA
> commitments must be hash-based), `doc/scaling-analysis.md` (item #4 / §C).
