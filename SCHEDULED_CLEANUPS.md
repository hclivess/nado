# Scheduled cleanups — code that becomes deletable at a known chain height

Compatibility gates, activation branches and migration shims that are **correct today and dead later**.
Each entry names the height at which it may go, and — more importantly — **why it cannot go before that**,
because in every case the early cleanup is the tempting one.

Grep `SCHEDULED-CLEANUP` in the tree to find the corresponding code.

**Rule for this file:** an entry is removed only when the code is. If a genesis reroll happens, re-read
every entry — epoch/height numbering restarts and an activation constant that was 2 days out can land
weeks into the new chain, silently leaving the old behaviour live until then.

---


## 2026-09-02 — gen-24 DIV_CARRY_METER_EPOCH (300): delete at the gen-25 reroll

`protocol.DIV_CARRY_METER_EPOCH = 300 if CHAIN_GENERATION == 24 else 0`, read by
`execnode/stark/records_bind.dividend_accrual_effects` (the one accrual rule; `state.accrue_dividend_epoch`
applies its effects). Epochs 0-193 of betanet-6 carried the whole dividend inflow while every identity was on
probation; epoch 194 paid the backlog (113.29 NADO) to the single identity out of probation. From epoch 300 a
backlog releases at most max(inflow, DIV_CARRY_RELEASE_FLOOR) per epoch. **Cannot go early**: the fleet's exec
nodes must all switch at the same epoch or their records halves stop binding. Pinned by
tests/test_div_carry_meter.py. At gen 25 the expression is 0 and the pre-gate branch is dead — delete the
constant's gate, the `epoch is None` old-rule branch and this entry together.

## 2026-09-02 — gen-24 POSW_ENTRY_COUNT_HEIGHT (1636): delete at the gen-25 reroll

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
