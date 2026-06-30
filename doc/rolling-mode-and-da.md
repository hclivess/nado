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
- **Block bodies are already separable.** Stored as `zstd(msgpack)` files under `blocks/`;
  the LMDB KV is a **derived, rebuildable index**. `kv_ops` already has prune primitives
  (block-by-num / block-by-hash delete, `heartbeat_gc`, `iter_block_numbers`).

**A snapshot is already a pruned state.** Rolling mode is mostly: *keep making snapshots,
keep the last K epochs of bodies, drop the rest, and define who still has the old data.*

---

## 2. Rolling mode (L1 history pruning)

### 2.1 The retention window
A new constant — `HISTORY_RETENTION_EPOCHS` (config-overridable) — sets how many recent
epochs of **full block bodies** a rolling node keeps. Below that, bodies are dropped; the
**state** (and the finalized headers) stay.

**Retention-floor invariant (correctness-critical):** the window must exceed the **deepest
historical-*block-body* lookback** any validation rule performs. Two facts make this floor
small:
- Most "lookbacks" read **state**, not old bodies. A `withdraw` checks the pending-unbond
  record in the **KV state** (`kv_ops.unbond_*`), not the 1440-blocks-old bond *body*; the
  RANDAO beacon and FFG checkpoints are **applied into state**, not re-read from bodies.
  `BOND_UNLOCK_DELAY = 1440` therefore does **not** force 1440 blocks of body retention.
- What *does* re-read bodies/headers is fork-choice / rollback (≤ `max_rollbacks`,
  `FINALITY_DEPTH = 30`) and a few epoch-anchor hash lookups (`get_block_hash_by_number` at
  epoch boundaries).

So the floor is ≈ `FINALITY_DEPTH` plus a safety margin — small. The retention window is
driven more by the **social/DA** need (giving syncing peers and auditors something to fetch)
than by consensus. Set it comfortably above the floor (e.g. tens of epochs) and make it a
dial. **An exact audit of every rule that calls `get_block*` on historical heights is a
prerequisite before enabling pruning** — flagged, not assumed.

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

`GC_IDLE_EPOCHS = 1000` is defined; heartbeat-row GC is wired, but idle **account-row** GC
is not. The free OPEN lane (`register`/`heartbeat` are fee-exempt) creates permanent account
state — an unbounded growth vector.

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
- **Tests before shipping:** GC determinism across nodes, revert symmetry, snapshot-root
  agreement after GC, and "never prunes a valued/staked/pending account." This is a
  consensus change and gets its own test file — hence designed here, **not** blind-wired.

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
3. **Execution-layer blob DA (when the execution layer ships).** Reed–Solomon + **hash-based
   (PQ) DAS** + challenge window + external-DA fallback (§4.2).

> Cross-references: `ops/snapshot_ops.py` (state snapshot + Merkle root + quorum),
> `ops/kv_ops.py` (block-body store + prune primitives + `heartbeat_gc`), `protocol.py`
> (`FINALITY_DEPTH`, `GC_IDLE_EPOCHS`, `BOND_UNLOCK_DELAY`, `PRESENCE_WINDOW`),
> `doc/execution-layer.md` (blob DA constraints), `doc/quantum-resistance-and-vms.md` (why DA
> commitments must be hash-based), `doc/scaling-analysis.md` (item #4 / §C).
