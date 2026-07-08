# NADO consensus security audit (2026-06-30, pre-mainnet alpha)

A deep adversarial audit was run across six attack surfaces (fork-choice/51%/rollback/finality;
Sybil/two-lane/selection; slashing/equivocation/unbond; RANDAO/FFG/beacon; tx-validation/pubkey-once;
KV atomicity/eclipse/DoS), with each finding verified against the code. NADO was **testnet-stage
alpha with no value at stake** at audit time. The exploitable findings below are **all fixed** (unit-
tested); the remaining items are documented residuals / future hardening.

## Fixed (exploitable)

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | **In-block duplicate reserved txs** — validation checked uniqueness only vs PARENT state, and block assembly did no dedup. Duplicate `withdraw`s in one block drained K×B_MIN from a single unbond (**slash-escape + chain-halt**); duplicate `slash` over-burned/halted (triggers organically from two honest reporters); duplicate `heartbeat`/`reveal` collapsed in DUPSORT then a reorg over-deleted the shared row → **registry/beacon desync fork** + fidelity farming. | CRITICAL/HIGH | `reserved_uniqueness_key` + `dedupe_reserved` (block assembly drops dups) + `assert_unique_reserved` (verify_block rejects dups), plus cross-block guards: `heartbeat_present` and reveal-secret uniqueness in validation. One root fix for all of these. |
| 2 | **Fork-choice same-length wedge** — `cumulative_weight` is content-independent, so two honest tips at one height tie; `minority_block_consensus` switched only on strictly-GREATER weight and never used the lowest-hash tie-break → equal-weight forks wedged forever (the empirical testnet churn). | CRITICAL (liveness) | `minority_block_consensus` now switches whenever the global-best tip by `(weight DESC, hash ASC)` isn't ours — the deterministic tie-break every node computes identically, so they converge on the lowest-hash tip. (Verified to converge cleanly at realistic block times.) |
| 3 | **`quick_sync` skipped signature + spending validation** for old blocks → a malicious sync peer could inject forged unsigned transfers. | HIGH (opt-in) | `verify_block` now **always** runs `validate_transactions_in_block` (the quick_sync bypass is removed). |
| 4 | **Unauthenticated advertised `latest_block_weight`** — a single Sybil peer advertising a huge weight forced honest nodes into emergency-mode + wasteful rollbacks (DoS). | HIGH | A bounded, auto-cleared `rejected_tips` exclusion: a tip we tried-and-failed to obtain a valid heavier chain for is excluded from the heaviest computation for a window, so a bogus weight can't loop us. |
| 5 | **Heavy unauthenticated endpoints unthrottled** (`/mining_status` full account scan, `/get_transactions_of_account`, `/get_blocks_after/before`). | MED | Per-IP rate limits added to all four. |
| 6 | **`/get_blocks_before` dead** (`parent_hash=["parent_hash"]` literal) — backward sync always returned empty. | LOW | Fixed to `parent["parent_hash"]`. |
| 7 | **`merge_transaction` unguarded field access** — a malformed gossiped tx aborted the whole merge batch. | LOW | Up-front malformed-tx guard (dict + `sender` + int `target_block`). |
| 8 | **Honest re-signer self-equivocation** — a validator that signed a block, got reorged, and re-signed a different block at the same height could be slashed by a connected adversary. | MED | The node now only ever signs a STRICTLY-higher height (`last_signed_height`), so it never self-equivocates. |
| 9 | **Eclipse cap bypassed on the disk-reload path** — `load_ips` rebuilt the peer set with no /16 filter. | MED | `subnet_diversity_ok` now also gates the reload path. |

## Confirmed sound (audited, no change needed)

- The **atomic incorporate/rollback** window (one write txn; file writes idempotent and ordered; tip +
  `finalized_height` advance after the commit, monotonic, crash-conservative).
- The **finalized-height floor** is monotonic and enforced on every rollback path including force-sync;
  `max_rollbacks(10) < FINALITY_DEPTH(30) < EPOCH_LENGTH(60)` asserted at startup; no below-floor reorg.
- The RANDAO **reveal-immutability bound** (`E*EPOCH_LENGTH - FINALITY_DEPTH - 1`) is exactly tight —
  the `-1` is load-bearing; a `max_rollbacks`-deep reorg cannot change a finalized reveal set.
- **FFG now advances the rollback floor but can never stall the chain.** A finalized checkpoint is folded
  in as `finalized_height = max(prev, tip − FINALITY_DEPTH, ffg_finalized)`, making a >2/3-attested
  checkpoint objectively un-reorgable; because it is layered on the always-advancing depth floor (the
  liveness guarantee) and its quorum uses the *active* bonded set (inactivity leak), a stalled or absent
  attester set never wedges finality. Exposed at `/status.ffg_finalized`.
- **Equivocation-proof unforgeability** (two distinct-message ML-DSA sigs; no malleability/single-sig
  reuse) and **no innocent-victim spoof** (offender = `make_address(pubkey)`; ~168-bit address grind).
- **Detached signature is outside the block hash** (attach/remove/grind can't change hash/weight/reward).
- **Pubkey-once binding** (`proof_sender` always binds key→sender; stored key only used for its own
  sender), **full-body/replay binding** (txid recompute + chain_id + target_block + epoch), the tx
  secondary indexes, lane-split population-independence, empty-lane fail-closed fallback, integer
  determinism, and path-traversal guards.

## Documented residuals / future hardening (NOT exploitable for theft or a fork)

- **RANDAO has no withholder/reveal-censorship penalty.** A producer controlling/suppressing `m`
  reveals has up to `2^m` grinding combinations; with zero reveals the beacon falls back to the
  finalized anchor (anchor-grindable). Defeated whenever ≥1 honest secret is revealed after the anchor.
  Adding a withholder fidelity dock + a minimum-reveal rule is future work.
- **FFG slashable-stake backing: CLOSED (no longer a residual).** FFG is now enforced (its finalized
  checkpoint folds into the rollback floor, above), and **attestation-equivocation slashing is live**:
  two conflicting attestations for one epoch (same `target_epoch`, different `target_hash`) form a
  portable proof (`verify_attestation_equivocation_proof`) that burns `SLASH_BOND_PENALTY` of bonded
  stake via the same `slash` path as block-authorship equivocation (`resolve_slash`). The per-epoch
  uniqueness marker still blocks on-chain double-voting; cross-fork double-voting is now punished.
- **The bonded `MAX_SHARES` cap is per-identity, not aggregate** — sharding capital above `BOND_CAP`
  across addresses recovers full proportional weight. The bonded lane is therefore capital-proportional
  ("pay-to-win") by design; the cap limits single-address variance, not aggregate stake.
- **Registration / fee-exempt state growth** — `register` writes a permanent account doc; `GC_IDLE_EPOCHS`
  is defined but not yet wired, and the registration PoW does not bind `target_block`. Bounded today by
  the lane cap (share), per-IP rate limit, mempool cap, and the in-block one-register-per-sender dedup,
  but idle-account GC + per-sender mempool occupancy caps are future work.
- **`FIDELITY_DECAY` is unused** (absent identities keep accumulated fidelity); bounded by the open-lane
  ceiling.
- **Snapshot bootstrap** trusts an 80%-of-peers quorum with no hardcoded-checkpoint cross-check
  (weak-subjectivity). A hardcoded finalized checkpoint is future eclipse hardening.

All exploitable findings are fixed and unit-tested (`tests/test_inblock_uniqueness_audit.py` + the
existing consensus suite). The residuals are economic/grinding/operational hardening appropriate to
schedule before mainnet launch, not theft or fork vectors in the current code.
