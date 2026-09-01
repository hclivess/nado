# Scheduled cleanups — code that becomes deletable at a known chain height

Compatibility gates, activation branches and migration shims that are **correct today and dead later**.
Each entry names the height at which it may go, and — more importantly — **why it cannot go before that**,
because in every case the early cleanup is the tempting one.

Grep `SCHEDULED-CLEANUP` in the tree to find the corresponding code.

**Rule for this file:** an entry is removed only when the code is. If a genesis reroll happens, re-read
every entry — epoch/height numbering restarts and an activation constant that was 2 days out can land
weeks into the new chain, silently leaving the old behaviour live until then.

---


## 2026-09-01 — gen-23 SYBIL RULES gate: delete at the gen-24 reroll (`SCHEDULED-CLEANUP` in protocol.py)

`SYBIL_RULES_HEIGHT = _GEN23_SYBIL_ACTIVATION if CHAIN_GENERATION == 23 else 0` activates probation (no dividend and
open weight 1 until the first timely renewal — `protocol.on_probation`, `dividend_weight(f, epoch)`,
`mining_ops.open_shares(f, epoch)`) and the 14-day-capped difficulty baseline (`reg_difficulty.difficulty_multiplier`)
at block 86 400 / epoch 1440 of betanet-5. **Why it cannot go before the reroll:** every committed `epochw:<E>` row
for E < 1440 was built with the un-gated curve and the dividend replay (`dividend_ops.weights_at_epoch`) must keep
re-deriving them byte-identically; the difficulty of every register anchored before 1440 likewise. At gen 24 the
expression is 0 from block 0: delete the gate, drop the `epoch >= SYBIL_RULES_EPOCH` branches, keep the rules
unconditional, and let `tests/test_sybil_rules.py` t1 assert the names are gone (the test_dividend_rules pattern).

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
