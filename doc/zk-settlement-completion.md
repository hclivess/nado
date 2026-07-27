# Trustless STARK settlement — completion checklist

Status as of the 2026-07-27 code sweep (8-agent survey + manual verification of the load-bearing claims).
This is the *code-grounded* companion to `zk-recursion.md` / `zk-execution-proofs.md`: what is actually
built and wired **today**, and the exact ordered steps left to make a STARK validity proof — not the
bonded quorum — the settlement authority.

## TL;DR

The **verifier / acceptance side is essentially done and hardened.** The **prover side does not run in
production**, and the acceptance branch is **commented out** behind a stale rationale. Turning trustless
settlement on is a bounded prover-loop + a two-line flip + a reroll — *not* new cryptography. The O(1)
recursion fold is a separate, optional performance layer (built, not wired); native per-segment verify is
already trustless, just not succinct.

## What is DONE and WIRED (verified)

- **Settle-with-proof validation** — `ops/transaction_ops.py:981-1079`. When a `settle` tx carries a
  `proof`, **every node verifies it deterministically at block-validation** and it is comprehensively
  hardened:
  - **Prune-safe** — binds to the committed per-block **exec summaries** (`kv_ops.exec_summary_get`), never
    to block bodies, so a pruned node and an archive node validate identically (`:1049-1056`). This is the
    fix for the fork that broke the previous attempt.
  - **Quorum-first** — a proof may only *extend* an already-settled tip; the first settlement in a
    namespace must be by quorum (`:1008-1013`). This bounds the summary window to `(settled_cursor, cursor]`
    and is what makes it prune-safe.
  - **Records-bound** — rejects any span crossing an epoch boundary (presence-dividend accrual is a records
    write, invisible to a body scan) (`:1062-1068`), and rejects any in-proof `IO_PAY` (bridge payouts move
    records) (`:1069-1075`).
  - **Chain-randomness sound** — every BHASH/BEACON the proof reads is bound to *this node's finalized
    chain* (`:1024-1048`), so a prover cannot settle a state built on attacker-chosen dice/beacon values.
  - **DA-bound** — `calls_commit.verify_calls_bound_to_summaries(proof, ns, tip_cursor, cursor,
    exec_summary_get, SETTLE_PROOF_MAX_SPAN)` (`:1076-1079`); span fence `SETTLE_PROOF_MAX_SPAN = 240`
    (`protocol.py:521`) enforced.
  - **Protocol-parameter verify** — `SS.verify_settlement_sparse(proof, depth=EXEC_TREE_DEPTH)` at the
    protocol query strength, never the bundle's own word (`:1015-1018`).
- **Apply side** — the proven marker is written at apply (`kv_ops.settlement_proven` set via
  `account_ops`), revert-safe.
- **Prover primitives** — `execnode/stark/settlement_sparse.py:220 prove_settlement_sparse(...)`,
  `execnode/settlement_proofs.py prove_settlement_o1/verify_settlement_o1`, the full FRI/AIR/VM-circuit
  stack, and the native Rust prover (`libnado_starkprove`, ~5× faster / 4.5× less memory) all exist and are
  unit-tested.

## What is NOT wired (the actual remaining work)

1. **No prover runs in production.** `execnode/execnode.py:239` posts `construct_settle_tx(keys, st.cursor,
   st.state_root(), target, ns=ns)` — **no `proof=` argument** — so every settlement today is a bare bonded
   attestation. `prove_settlement_sparse` / `prove_settlement_o1` have **zero non-test callers**.
2. **The acceptance branch is disabled.** `ops/settlement_ops.py:58-59` — the
   `if kv_ops.settlement_proven(ns, cursor, state_root): return True` fast-path is **commented out**, so no
   proof can justify a root without quorum, even if one were posted.
3. **The disabling docstring is STALE.** `settlement_ops.py:46-57` lists blockers (1) prune-safety and
   (2) records-binding as open — **both are closed** in `transaction_ops.py:1049-1075` (verified above).
   Only (3), the prover-emission constraint, is genuinely open, and it is a *prover* item, not a
   consensus-safety hole (the validator already rejects non-conforming proofs).
4. **The O(1) fold is bypassed.** The live settle path re-verifies every segment natively (`transaction_ops
   .py:1017 → settlement_sparse.py:250` loops `verify_bound_epoch`), O(K). `verify_settlement_o1`
   (`settlement_proofs.py`) exists + is tested but has no non-test caller. This is a *performance* gap, not
   a trust gap.

---

## Track 1 — turn trustless settlement ON (the "minor steps")

Ordered. Each step names files, effort, whether it blocks trustless settlement, and a go/no-go test.

### 1.1 — Build a conforming prover loop  ·  effort: **major (bounded — no new crypto)**  ·  blocks: **yes**
`execnode/execnode.py` (the `maybe_settle` seam at `:239`).

Replace the bare `construct_settle_tx(...)` with: assemble the span `(settled_cursor, st.cursor]`, gather
`calls = calls_commit.block_calls(block, ns)` per block over the span, `pre_contracts` = the exec state at
the settled tip, `rec_hex` = the (unchanged) records half; call `prove_settlement_sparse(pre_contracts,
calls, cursor, rec_hex, timestamp, beacons)`; post `construct_settle_tx(..., proof=bundle)`. **Fall back to
the bare attestation** (the existing path) whenever the span does not conform — so this never regresses.

The span must satisfy the validator (all already enforced, so the prover must *match* them):
- within a single epoch (`tip_cursor // EPOCH_LENGTH == cursor // EPOCH_LENGTH`),
- `cursor - settled_cursor ≤ SETTLE_PROOF_MAX_SPAN (240)`,
- no `PAY` in any call's io,
- extends the real settled tip (never genesis — quorum settles the first).

**Go/no-go:** a producing exec node posts a settle tx with a `proof`; `validate_transaction` accepts it
against real committed summaries; the proof survives `verify_settlement_sparse` at protocol params.

### 1.2 — Make the prover's `calls_commitment` match L1's per-block fold  ·  effort: **moderate**  ·  blocks: **yes**
`execnode/stark/settlement_sparse.py` / `settlement_proofs.py` (prover) vs `calls_commit.py:96-97` (L1).

L1 folds the DA calldata **per block** (`cursor = block height`, `ts = 0`). The prover currently folds one
**epoch-wide** cursor/ts, so `segment.calls_commitment ≠ da_calls_commitment` and the binding gate rejects
it. **Simplest first cut: restrict the prover to single-block spans** (`cursor = height`, `ts = 0`), which
matches trivially and defers the multi-block fold. Widen to multi-block once per-block cursor/ts is threaded
through the segment fold.

**Go/no-go:** for a single-block span, `segment.calls_commitment == da_calls_commitment([block], ns)`, and
`verify_calls_bound_to_summaries` passes on a live proof.

### 1.3 — Represent skip/revert calls as no-ops in the bundle  ·  effort: **moderate**  ·  blocks: **only for spans with reverts**
L1's `block_calls` binds **all** `op=='call'` blobs including ones that skip/revert (`calls_commit.py:69-71`).
The prover must fold a reverting call as a no-op so a span containing one is still provable. Interim: **fence
spans to revert-free** (skip proving a span that contains a revert; fall back to quorum for it). Full: model
the revert as a no-op transition in the exec AIR.

**Go/no-go:** a span containing a reverting `call` either proves (revert-as-no-op) or is cleanly skipped to
the quorum path — never produces an invalid proof.

### 1.4 — Flip the switch  ·  effort: **trivial**  ·  blocks: **yes**
- Uncomment `ops/settlement_ops.py:58-59` (`if kv_ops.settlement_proven(...): return True`).
- Flip the guard `tests/test_seed_divergence.py:188-191` (it asserts the branch stays off — it is designed
  to fail the moment 1.4 lands and must change in the same commit).
- **Rewrite the stale docstring** `settlement_ops.py:46-57`: blockers (1) and (2) are closed
  (`transaction_ops.py:1049-1075`); state that (3) is a prover-emission constraint enforced at validation,
  not a safety hole.

**Go/no-go:** with 1.1-1.3 producing a proof, `settlement_justified` returns `True` from the proof marker
with **zero** quorum attestations, and `latest_settled` advances by proof.

### 1.5 — Ship on a reroll  ·  effort: **deployment**  ·  blocks: **yes**
Making the sparse root THE consensus settled root is a genesis-level state-root-scheme change
(`zk-recursion.md:414-416`); it rides a `CHAIN_GENERATION` reroll, not a hot toggle. Trustless settlement
lands "present but active" at the reroll; the quorum path stays as the fallback for non-conforming spans.

---

## Track 2 — succinct O(1) verify (optional; performance, not trust)

Not required for *trustless* settlement — native per-segment verify is already trustless. This is what
shrinks the on-chain verify from O(K) to O(1) and the proof small enough to sit inside a normal tx.

- **2.1 Wire the built fold** · moderate · Replace the native segment loop (`transaction_ops.py:1017 →
  settlement_sparse.py:250`) with `verify_settlement_o1` (RV.verify), and have the prover emit
  `prove_settlement_o1` bundles. Both exist + are tested (`tests/test_settlement_o1.py`) with no non-test
  caller. Bind the FRI roots to the segment trace / state root first (`settlement_proofs.py:240-247` SCOPE
  note) so the per-segment verify can actually be dropped.
- **2.2 In-circuit Fiat–Shamir keystone** · major (real crypto) · Move FS challenge/position derivation
  inside the proof (`fs_step`/`fs_chain`/`fs_incircuit` exist but are test-only) so inner roots collapse to
  one committed public input — `recursive_verify.py:53/103` derive FS natively today.
- **2.3 Authoritative-depth O(1) frontier** · major (real crypto) · Per-level composition binding — the
  heterogeneous-AIR recursion step with a verifier-rebuilt schedule (`recursion_authdepth.py:18-27`,
  `zk-recursion.md:272-279`). The doc itself flags this as "not just wiring."
- **2.4 Rust throughput port for deep trees** · major (orthogonal to correctness) · level-1 fold measured
  ~19 min pure Python; W=106 bundle ~15 GB native. The native prover exists; deep-tree proving latency is
  the production prerequisite (`zk-recursion.md:427-429`).

---

## Track 3 — test coverage before flipping

- **3.1** Real-crypto settle e2e at **protocol** depth/queries through `validate_transaction → apply →
  justified`. Today `tests/test_settle_with_proof.py:202-244` (t10) is `NADO_HEAVY`-gated and patches
  `EXEC_TREE_DEPTH=8, NUM_QUERIES=2`; t1-t9 **stub** `verify_settlement_sparse` (`:52-57`).
- **3.2** A dedicated test for the *live* DA-binding gate `verify_calls_bound_to_summaries`
  (records-inert enforcement, missing-summary refusal, span cap, multi-segment) — `test_da_binding.py`
  covers the superseded `verify_calls_bound_to_da`, not the one consensus actually runs.
- **3.3** Promote the W=106 O(1) recursion bundle to a non-heavy e2e, or accept it as scheduled-only
  (`tests/test_settlement_o1.py:72-126` — full bundle only under `NADO_HEAVY`).

---

## Corrections this sweep found

- `ops/settlement_ops.py:46-57` docstring is **stale**: it lists prune-safety (1) and records-binding (2)
  as open blockers; both are implemented in `transaction_ops.py:1049-1075`. Update it in step 1.4.
- The `native ML-DSA`-style optionality applies here too: pure-Python settlement proving hit a ~40 GB
  memory wall at W=106; the native prover should be a **hard requirement** for `--exec-settle`, not a silent
  optional accelerator (`scripts/install.sh` builds it optional).

## The honest bottom line

Trustless STARK settlement in nado is **prover-limited, not verifier-limited**. The consensus-critical hard
part — a sound, prune-safe, DA-bound, chain-randomness-bound on-chain verifier — is built and hardened.
Track 1 (a conforming prover loop + the two-line flip + a reroll) is the minimal path and contains **no new
cryptography**; the single genuine crypto frontier left (Track 2.3) buys succinctness (O(1)), not trust, and
is not on the critical path to switching the quorum off.
