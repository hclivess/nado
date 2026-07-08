# Consensus hardening plan (#15–#18) — locked design + ordered implementation

**Status:** design locked 2026-06-30 (vetted by a 3-architect + synthesis design pass).
**Implementation progress (steps 1–8 now all landed except the post-launch eclipse ops; testnet-stage alpha):**
- The **SQLite → LMDB migration (#21)** is **DONE** (`ops/kv_ops.py`); the `get_finalized_height` /
  meta accessors are KV calls.
- **Step 1 — finality floor (#17): DONE.** `FINALITY_DEPTH=30`, persisted monotonic
  `finalized_height`, `rollback_one_block` raises `FinalityViolation`.
- **Step 2 — grind-proof `cumulative_weight` header: DONE** (carried + verified as-of-parent).
- **Step 3 — objective heaviest-`cumulative_weight` fork-choice: DONE** (peer-IP plurality removed
  from the security path; trust demoted to advisory).
- **Step 4 — beacon fail-loud: DONE** (silent `GENESIS_BEACON` fallback removed).
- **Step 5 — pubkey-once (#19) + detached OPTIONAL winner signature (#15): DONE**, now **INCLUDING the
  equivocation-slashing action (step 5C) for BOTH offence types:** a fee-exempt `slash` tx carrying a
  proof burns `SLASH_BOND_PENALTY` (= `B_MIN`, one share) of the offender's **bonded** stake. The
  proof is either **(a) block-authorship** — two conflicting winner signatures at one height+parent
  (`verify_equivocation_proof`, `block_ops.py`) — or **(b) FFG-attestation** — two conflicting `attest`
  txs for one `target_epoch` with different `target_hash`
  (`verify_attestation_equivocation_proof`, `transaction_ops.py`); `resolve_slash` unifies them.
  Replay-guarded one-per-(offender, height) via a `meta` slash marker (attestation slashes namespaced
  above real block heights); revert-symmetric; burned, not paid to the reporter (anyone may report; the
  proof is the anti-spam). `apply_slash` (`account_ops.py`), validation + `reflect_transaction` slash
  branch. **This punishes equivocation, not Sybil-ness** (Sybil = open-lane `OPEN_BPS` cap + locked
  bonded shares, separately).
- **Step 6 — FFG objective finality (#6): DONE — and now ENFORCED (matches the design body below).**
  Bonded validators emit one `attest` tx per epoch for the epoch checkpoint; a checkpoint JUSTIFIES at
  strictly **>2/3** of the **active** bonded shares (`attesting*FFG_DEN > total*FFG_NUM`,
  `FFG_NUM=2`/`FFG_DEN=3`) and FINALIZES on two-consecutive-justified (`ffg_finalized_checkpoint`).
  On-chain `UNIQUE(validator, epoch)` (attestation index + meta marker) prevents on-chain double-voting
  (cross-fork double-votes are now slashable, Step 5). Exposed as **`/status.ffg_finalized`**. The
  finalized checkpoint is **folded into the enforced rollback floor** in `incorporate_block`:
  `finalized_height = max(prev, tip − FINALITY_DEPTH, ffg_finalized)`, so a >2/3-attested checkpoint is
  **objectively un-reorgable** (`rollback_one_block` refuses to cross it) — no longer merely observed.
  **INACTIVITY LEAK:** the justify-quorum DENOMINATOR is `active_shares` — bonded validators that
  attested *some* checkpoint within the last `INACTIVITY_WINDOW = 3` epochs, NOT all bonded stake — so a
  dark validator is leaked from the finality quorum (its **vote** lapses, **bond untouched**) and a live
  attesting majority always finalizes. Because FFG is layered on the always-advancing time-based depth
  floor (the liveness guarantee) and normally *trails* it, FFG **can never stall the chain** and does not
  speed confirmations; it is the objective/long-range finality on top of the fast subjective floor.
- **Step 7 — commit-reveal RANDAO (#7): DONE.** Bonded validators `commit` a secret's hash in epoch
  E-2 and `reveal` it in E-1's FINALIZED window; `epoch_beacon` now mixes the finalized anchor with
  the revealed secrets (`compute_beacon(GENESIS_BEACON, [anchor] + secrets)`) so no single anchor-
  producer controls the beacon, falling back to the anchor-only value with zero reveals (liveness).
  **Differs from Step 7's design body:** it KEEPS the anchor and is non-recursive (not
  `compute_beacon(epoch_beacon(E-1), …)`), which keeps it snapshot-safe and the reveals immutable when
  the beacon is first needed.
- **Step 8 — eclipse hardening: PARTIAL (the rest is post-launch).** Live: the `/announce_peer` rate-
  limit **and** the per-/16 subnet-diversity cap. **Still genuinely planned/post-launch:** ASN-level
  (vs /16) peer diversity, pinned anchor outbound slots + a multi-seed bootstrap list, and snapshot-
  bootstrap binding to a finalized signed checkpoint.

**Honest caveats.** FFG (#6) and RANDAO (#7) are unit-tested for correctness, but their multi-node
EPOCH-CROSSING behaviour is only LIGHTLY exercised empirically — the core loop's ~10 s/block cadence
makes crossing the 120+ blocks needed to observe a full justify→finalize and a commit→reveal cycle
slow. They engage as the chain crosses epochs. NADO remains a **testnet-stage alpha, not mainnet-
launched** (so there is no hardfork concern — mainnet isn't live). The detail below is the **locked
design**; where a per-step body still reads as "planned" or sketches a different shape than what
shipped (Steps 6 and 7 above), the status block here and the code are authoritative.

**Sequencing constraint (historical):** steps 1–3 read/write committed state via the index layer
that the SQLite→LMDB migration (#21) replaced. The KV migration landed FIRST, so these steps run on
the KV'd `main` (the `get_finalized_height` / meta accessors are KV calls, not `index.db` rows).

## Chosen design — why convergence holds

Winner: **signature-free, beacon-independent chain-weight fork-choice + monotonic finality floor**,
grafting FFG objective finality, detached-winner-signature slashing, commit-reveal, and eclipse
hardening for the later steps.

- **Fork-choice weight:** header integer `cumulative_weight = parent.cumulative_weight + W(B)`, where
  `W(B) = total_shares(get_bonded_registry as-of-B's-parent)` = Σ over bonded identities of
  `min(bonded, BOND_CAP)//B_MIN`, capped per-identity at `MAX_SHARES`. Committed INSIDE the block-hash
  preimage (like the existing `cumulative_fees`), recomputed in `rebuild_block`, verified as-of-parent
  in `verify_block`.
- It is the **TOTAL registry weight, not the slot winner's share** → BEACON-INDEPENDENT, so a proposer
  cannot grind the beacon to inflate fork weight; removes self-bond-private-fork leverage.
- **Peer IPs / trust / uptime contribute exactly 0 weight** → a Sybil fleet of zero-bond IPs can never
  reorg honest nodes (the 51%/rollback-by-Sybil fix).
- **Canonical tip** = argmax `cumulative_weight` among tips whose chain CONTAINS our finalized block;
  switch only on STRICTLY-GREATER weight (first-seen on ties; fresh-node tie-break = lowest cumulative
  block_hash). Authorship-gating (`validate_block_producer` fail-closed re-derivation) restricts WHO
  can extend; the finality floor + strictly-greater + first-seen converge the small unfinalized window.
- **Win-offline preserved:** block validity is pure deterministic winner re-derivation + hash binding,
  NEVER conditioned on the winner being online or signing. The winner signature (#15) is a DETACHED,
  OPTIONAL field OUTSIDE the hash preimage — excluded from hash, weight, validity, reward — used only
  for portable equivocation-slashing proofs / optional checkpoint attestations.
- **Light:** integer-only, browser-reproducible; no per-block ML-DSA in the consensus path (FFG step
  adds ~1 sig / 60 blocks, lazily verified).

Convergence holds because fork-choice is a pure deterministic integer function of held blocks (not
peer votes), win-offline guarantees no slot stalls (the prior failure was divergence-by-omission), the
weight is grind-proof + beacon-independent, and the monotonic floor caps the disagreement window below
EPOCH_LENGTH so honest forks self-heal.

## Ordered steps (lowest-risk first; each independently testnet-gated)

### Step 1 — Persisted monotonic finalized_height floor + rollback refusal (risk: low, reversible)
Files: `rollback.py`, `loops/core_loop.py`, `memserver.py`, `ops/account_ops.py`, `config.py`, `protocol.py`, `nado.py`
- `config.py`: add `finality_depth=30` beside `max_rollbacks`. `protocol.py`: `FINALITY_DEPTH` constant.
- `ops/account_ops.py`: `get_finalized_height()` / `set_finalized_height(h)` backed by a meta row
  (KV meta key after #21), default 0.
- `memserver.py`: load `self.finalized_height` at startup; assert `max_rollbacks < finality_depth <
  EPOCH_LENGTH` (10 < 30 < 60).
- `incorporate_block` (core_loop ~610, AFTER `set_latest_block_info` commits): `new = max(finalized,
  block_number - finality_depth)`; if `new > current`, persist + update memserver (monotonic;
  crash-safe since recomputable as max).
- `rollback.py`: add `FinalityViolation` beside `MissingParentError`; in `rollback_one_block`, after
  loading `previous_block`, raise it if `previous_block['block_number'] < get_finalized_height()`.
- `core_loop.py:511` emergency_mode: add `except FinalityViolation` arm mirroring `MissingParentError`
  (log, reset rollbacks=0, break → forward resync only).
- **Fix the leak:** `rollbacks <= max_rollbacks` → `<`; increment the counter even under
  `force_sync_ip`; the finalized floor is the hard cap, the counter only rate-limits a burst.
- Expose `finalized_height` in `/status` (nado.py).
- **Gate:** drive an emergency reorg deeper than finality_depth on a multi-node net: every node raises
  FinalityViolation, refuses to roll below tip-30, never spins/crashes, resyncs forward, balances
  revert-symmetric; marker monotonic across induced reorgs AND restart; honest reorgs (≤10) never hit
  the floor; SOLO (min_peers==0) still produces.

### Step 2 — Add grind-proof cumulative_weight header (carry + verify only, NO fork-choice change) + as-of-parent re-verify guard (risk: low, reversible)
Files: `ops/block_ops.py`, `ops/mining_ops.py`, `ops/account_ops.py`, `loops/core_loop.py`
- `ops/mining_ops.py`: `total_shares(bonded_registry)` = Σ `min(bonded,BOND_CAP)//B_MIN` capped at
  `MAX_SHARES`, integer-only.
- `construct_block`: add `cumulative_weight = parent_cumulative_weight + total_shares(get_bonded_registry
  as-of-parent)` INSIDE the hashed block_message (next to cumulative_fees).
- `rebuild_block` (core_loop:541): recompute from local committed parent, discard any peer value.
- `verify_block` (core_loop:685): assert `block.cumulative_weight == parent.cumulative_weight +
  total_shares(as-of-parent)`.
- As-of-parent re-verify guard: on rollback/snapshot re-verify, reset the tip to the block's parent
  before deriving winner+weight.
- Regenerate block-hash test fixtures, browser light-miner weight calc, snapshot manifests in lockstep
  (pre-launch format break allowed).
- **Gate:** every node computes IDENTICAL cumulative_weight at each height; verify_block accepts
  canonical, rejects tampered weight; weight monotonically non-decreasing = running sum of total bonded
  shares; browser light-miner reproduces identical weights.

### Step 3 — Replace IP-plurality fork-choice with deterministic strictly-heaviest cumulative_weight; demote trust to advisory (risk: medium, NOT reversible)
Files: `loops/consensus_loop.py`, `loops/core_loop.py`, `ops/peer_ops.py`, `ops/block_ops.py`
- Remove `get_pool_majority`/`get_majority` from the security path.
- `consensus_loop.refresh_hashes`: fetch competing tips' headers, locally compute cumulative_weight;
  canonical = argmax weight among tips whose chain CONTAINS our finalized block; switch only on
  STRICTLY-GREATER (first-seen on ties; fresh-node tie-break = lowest cumulative block_hash).
- `minority_block_consensus` (core_loop:310): rewrite from 'tip != majority hash' to 'a strictly-heavier
  valid chain descending from our finalized block exists'.
- `qualifies_to_sync` (peer_ops:378): replace `peer_trust>=median` with 'peer advertises a tip whose
  locally-recomputed weight is heaviest AND descends from our finalized block'. `change_trust` →
  advisory transport-quality hint only.
- **Gate:** a Sybil fleet of zero-bond IPs advertising a low-weight tip CANNOT reorg honest nodes; a
  genuinely heavier bonded chain IS adopted; 3+ node net with churn converges to one tip from divergent
  starts within a few blocks; equal-weight grind can't flip incumbent; SOLO still produces.

### Step 4 — Beacon fail-loud: remove silent GENESIS_BEACON fallback (risk: medium, reversible)
Files: `ops/block_ops.py`, `memserver.py`, `protocol.py`
- `epoch_beacon` (block_ops:213): remove `if not anchor: return GENESIS_BEACON`; a missing anchor (which
  finality guarantees exists for epoch≥2) must raise/halt loud, never silently substitute. Keep the E-1
  anchor (already buried > finality_depth when it governs).
- **Gate:** all nodes derive identical epoch beacon from the finalized anchor; a node missing the anchor
  HALTS instead of substituting; no divergent producer set at an epoch boundary.

### Step 5 — Pubkey-once in committed state + detached OPTIONAL ML-DSA winner signature + equivocation slashing (risk: medium, reversible) [also closes #19]
Files: `ops/account_ops.py`, `ops/transaction_ops.py`, `ops/block_ops.py`, `loops/core_loop.py`, `Curve25519.py`
- Store each identity's ML-DSA pubkey once in the account doc next to bonded/fidelity (read as-of-parent,
  deleted on rollback = revert-symmetric).
- Add OPTIONAL signature field OUTSIDE the hash preimage (beside block_penalty/block_timestamp) = winner
  ML-DSA over `blake2b([chain_id, height, parent_hash, block_hash])`; `rebuild_block` drops it; never
  enters block_hash, cumulative_weight, validity, or reward. `verify_block` checks present sigs with
  `Curve25519.verify()==True` (never equality).
- Two same-slot/same-parent signed blocks = portable equivocation proof → revert-symmetric bond/fidelity
  slash.
- **Gate:** an OFFLINE winner's relay-built UNSIGNED block still accepted, credited by address, full
  weight; detached sig provably excluded from hash+weight; two signed conflicting blocks dock
  bond/fidelity revert-symmetrically.

### Step 6 — Objective FFG-lite finality: bonded checkpoint attestations advance finalized_height at >2/3 bonded shares (risk: high, NOT reversible)
Files: `ops/attestation_ops.py` (new), `ops/account_ops.py`, `loops/consensus_loop.py`, `loops/core_loop.py`, `rollback.py`, `Curve25519.py`
- Checkpoint at each epoch-boundary block. Bonded validators broadcast ~1 ML-DSA attestation/epoch
  (source→target), stored in a revert-symmetric `attestation_index` (UNIQUE(validator,epoch)).
- Checkpoint justifies when attesting bonded shares > 2/3 of total bonded shares; finalizes on
  two-consecutive-justified → advance the SAME monotonic finalized_height marker (replaces Phase-A tip-K
  time-based advance). Double-vote/surround slashable (revert-symmetric).
- Cache verified (validator,checkpoint); verify lazily only for tips under active comparison.
- **Gate:** with ≥2/3 honest bonded stake a checkpoint justifies only at >2/3 and finalizes on
  two-consecutive-justified, advancing past tip-30; no node finalizes two conflicting checkpoints;
  partitioned node reconverges on heal; with <1/3 offline stake liveness holds; ML-DSA verify ~1/60.

### Step 7 — Wire full bonded-only commit-reveal RANDAO (risk: high, NOT reversible)
Files: `ops/transaction_ops.py`, `ops/account_ops.py`, `ops/block_ops.py`, `ops/mining_ops.py`, `loops/core_loop.py`
- Fee-exempt reserved recipients `commit` and `reveal` (bonded senders only), bound to an explicit
  target epoch (commit in E-2 window, reveal in E-1; UNIQUE(address,target_epoch)); reveal must satisfy
  `verify_reveal(recorded_commitment, secret)`. Route via reflect_transaction to revert-symmetric
  commit_index/reveal_index (modeled on the then-existing heartbeat_index — heartbeats have since been
  removed and presence is now the PoSW recert lease, but the revert-symmetric DUPSORT index pattern is
  unchanged; GC only above finalized_height).
- Rewrite `epoch_beacon` → `compute_beacon(epoch_beacon(E-1), sorted(valid revealed secrets for E))`;
  `compute_beacon([])` still advances (liveness). Withholder → deterministic revert-symmetric fidelity
  dock.
- **Gate:** anchor producer can't grind selection; all nodes derive identical beacon from sorted
  reveals; replay across epochs rejected; withholder slashed and reverts; zero-reveal epoch advances;
  commit/reveal indexes revert exactly across a reorg spanning the reveal window.

### Step 8 — Eclipse hardening (risk: medium, reversible)
Files: `nado.py`, `ops/peer_ops.py`, `loops/peer_loop.py`, `ops/snapshot_ops.py`, `genesis.py`, `config.py`, `loops/core_loop.py`
- Rate-limit `/announce_peer` (reuse submit_transaction limiter) + cap distinct peers per source/subnet
  per window. IP/-16-or-ASN diversity buckets with hard caps in check_ip/peer admission for both the 24
  live slots and stored peer files. Pinned anchor outbound slots + multi-seed list replacing the single
  genesis IP. Bind snapshot bootstrap to a finalized signed checkpoint (height, state_root) in
  config/genesis: `agree_snapshot` must match it (>2/3 bonded-attestation weight); keep import_snapshot's
  sha256/merkle as necessary-not-sufficient. (announce_peer rate-limit subset is independently shippable
  earlier.)
- **Gate:** single-origin announce flood can't fill 24 slots or evict pinned anchors; fresh node
  bootstraps only to snapshot matching the hardcoded finalized checkpoint, rejects a self-consistent
  Sybil snapshot; removing trust-median gate doesn't harm liveness under partial reachability.

## Constants introduced
- `FINALITY_DEPTH = 30` (10 = max_rollbacks < 30 < 60 = EPOCH_LENGTH < 180 = `POSW_LEASE_EPOCHS`, the
  presence-recert lease that superseded the old `PRESENCE_WINDOW*EPOCH` heartbeat window).
- `MAX_SHARES` per-identity weight cap for total_shares.
