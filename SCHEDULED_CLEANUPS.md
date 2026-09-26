# Scheduled cleanups — code that becomes deletable at a known chain height

Compatibility gates, activation branches and migration shims that are **correct today and dead later**.
Each entry names the height at which it may go, and — more importantly — **why it cannot go before that**,
because in every case the early cleanup is the tempting one.

Grep `SCHEDULED-CLEANUP` in the tree to find the corresponding code.

**Rule for this file:** an entry is removed only when the code is. If a genesis reroll happens, re-read
every entry — epoch/height numbering restarts and an activation constant that was 2 days out can land
weeks into the new chain, silently leaving the old behaviour live until then.

---


## 2026-09-26 — owed after the betanet-8 (gen 27) cleanup

- **`EK_ENROL_ROOTS_AT_HEIGHT = 1400 if CHAIN_GENERATION == 27 else 1`** (Intel V2-root chips enrol, f524cb0a): the first
  gen-27 gate. At the next reroll it is 1 — inline it as unconditional (keep `>= 1` where height 0 reaches it).
- **Exec-layer `>= 1` helpers keep dead legacy branches** (slice 2, 9c6bf717): the `ExecState.rules_*` helpers, the
  exec root layout and the legacy field-pool checks under `rules_r2()` still branch on height 0, which no real block
  reaches. Deletable only with a replay proving height 0 never reaches them — a cleanup, not owed by a reroll.
- **A settle proof whose span starts at exec cursor 0 may not match the settled genesis root**: the exec genesis root at
  cursor 0 is the v1 layout, a proof starting there uses v2 (found by the slice-2 agent; same on the old code; betanet-8
  is past cursor 0, so it bites only the first settle after the NEXT reroll). Investigate before that reroll.
- **Seven tests fail identically on old and new code, unrelated to the gates**: autogame_model (run path),
  test_auto_bond, test_emergency_rollback_gating, test_mining_status_lanes_memo, test_own_ips_and_sync_corrob and
  test_pay_binding (stale source greps), test_settle_fold_tree (times out). Fix or delete each; a red test nobody reads
  is how the lend page stayed broken from 2026-08-02 to 2026-09-26.
- **install.sh's root→account migration branch** says to delete it by mainnet; it is also what install-timers.sh
  undid (doc/jobs.md). Delete with the next installer pass once no root install remains.

## 2026-09-24 — the K->1 fold stays REFUSED: SETTLE_PROOF_RECURSIVE is already True, so lifting the refusal is live

**Corrected 2026-09-24.** This entry used to say `SETTLE_PROOF_RECURSIVE` is False and activation needs a reroll. It is
**True** (protocol.py, set at alphanet-14), and L1 honours a `recursive` bundle in a settle proof: `verify_settlement_
sparse` skips the per-segment exec proof and calls `recursive_verify.verify`. The ONLY thing keeping the fold out of
consensus is `_refuse_trace_ldt` (every block >= 1 — its gates PROOF_TRACE_LDT_HEIGHT and PROOF_QUERY_FULL_HEIGHT were
inlined at the betanet-8 cleanup, 9c6bf717).
Deleting it deploys a rule relaxation with no gate, on the next /update wave.

Owed before the refusal may go, IN THIS ORDER:
1. the fold must implement every live proof rule: draw beta in `_fs` and add the SHIFTED batch of the opened row
   (`stark.trace_batch_shift`) to the comp AIRs' expected layer-0 value; open at `stark.query_pos` and compare with
   `stark.fri_claim` (the full-domain rule) — the comp AIRs and the arena's fold kernels all assume the lower half;
2. the two fold forgeries of review 2026-09-24 stay closed (both fixed 2026-09-24: inner geometry pinned via
   `max_degree`, transition-bundle boundaries rebuilt from public data) — keep their tests green;
3. a height gate `... if CHAIN_GENERATION == 27 else 1` for the relaxation (at the fleet's adoption block), registered
   in the GATE LEDGER.
Pinned by tests/test_proof_trace_ldt.py (`fold refuses under the rule`) and tests/test_fold_hardening.py.

## 2026-09-02 — gen-24 POSW_ENTRY_COUNT_HEIGHT (1636): delete at the gen-25 reroll — STILL OWED

**Status 2026-09-26:** the gate is dead (`protocol.POSW_ENTRY_COUNT_HEIGHT = 0` since gen 25, pinned by
tests/test_gen25_retirements.py) but the NAME is still imported by `ops/reg_difficulty.py`, and tests/test_posw_rule_gate.py
no longer exists. Owed: delete the constant, `entries_only_at`, the `entries_only` parameters and this entry together.

`protocol.POSW_ENTRY_COUNT_HEIGHT = 1636 if CHAIN_GENERATION == 24 else 0`, read by
`ops/reg_difficulty.entries_only_at(landing_height)`. The entries-only flood counting (84d122f3) was pushed at
17:12 UTC on 2026-09-01 with betanet-6 already 1600 blocks old and NO gate; every registration the fleet had
validated before its update carries a proof for the OLD all-register-txs rule (block 871: 160M = 5x32 under
the old rule vs 128M = 4x32 under the new), so a from-genesis replay under the new rule rejected block 871 and
no fresh node could sync (this box, 2026-09-02 12:14 UTC). Replaying blocks 0..3600 against the proofs: the
last old-rule registration landed at 1608 (17:13:17 UTC), the first new-rule one at 1636 (17:16:37); the gate
sits at the first proven new-rule block. **Cannot go early**: it is what makes gen-24 history replayable.
Pinned by tests/test_posw_rule_gate.py. At the gen-25 reroll the expression is 0 and the old branch is dead —
delete the constant, `entries_only_at`, the `entries_only` parameters and this entry together.

## 2026-09-01 — gen-23 SYBIL RULES gate: RETIRED at the betanet-6 (gen 24) reroll (2026-09-01)

Probation, the 14-day-capped difficulty baseline and account authentication are unconditional from block 0 of
betanet-6; `tests/test_sybil_rules.py` t1 asserts no gate name survives. Nothing scheduled.

## STATE-ROOT ROW GROWTH — RESOLVED 2026-08-20 (root retention window, live on betanet-4)

Resolved without a reroll and without a height gate: `ops/snapshot_ops._root_triples` commits only the
last `ROOT_RETENTION_EPOCHS` (60) epochs of the epoch-growing families (RANDAO commits/reveals, FFG
attestations, att:/divnull:/settle: guards, settlement attestations, recert_by_epoch). The reference
epoch is the max committed `epochw:<E>` row — a pure function of state, rollback-symmetric by
construction, nothing deleted (readers keep full history). The rule engages by arithmetic at reference
epoch 60 (betanet-4 block ~3600); until then old and new code compute identical roots. Per-block root
work is now O(window), permanently. Test: tests/test_root_retention_window.py. Nothing left to delete
here — the entry stays only as the record of why the families are windowed.

## 2026-08-25 — gen-22 dividend-rules gate: RETIRED at the betanet-5 (gen 23) reroll

The generation-keyed gate (`DIVIDEND_RULES_HEIGHT = 72_000 if CHAIN_GENERATION == 22 else 0`) that carried the
convex dividend curve, the halving lapse and the 40 % bonded levy for the last hours of gen 22 was deleted in
the reroll commit; `tests/test_dividend_rules.py` asserts no such gate exists. Nothing scheduled.

## Account authentication — activation expression (nothing to delete)

`protocol.AUTH_ACTIVE = CHAIN_GENERATION >= 24 or NADO_AUTH_FORCE`. It is an expression, not a gate: on gen 23 the
`auth` recipient is refused and no account can hold a config; on gen 24+ it is live from block 0. After the gen-24
reroll the `>= 24` half is a tautology and MAY be simplified to `True` — optional, cosmetic. Never set
`NADO_AUTH_FORCE` on a validator.
