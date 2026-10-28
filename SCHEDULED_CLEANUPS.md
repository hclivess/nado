# Scheduled cleanups — code that becomes deletable at a known chain height

Compatibility gates, activation branches and migration shims that are **correct today and dead later**.
Each entry names the height at which it may go, and — more importantly — **why it cannot go before that**,
because in every case the early cleanup is the tempting one.

Live consensus gates are listed in the GATE LEDGER in `protocol.py` (pinned by `tests/test_gate_reroll_transfer.py`);
this file holds the other deferred deletions.

**Rule for this file:** an entry is removed only when the code is. If a genesis reroll happens, re-read
every entry — epoch/height numbering restarts and an activation constant that was 2 days out can land
weeks into the new chain, silently leaving the old behaviour live until then.

---


## 2026-10-28 — the dividend carry is committed in the exec root from EXEC_CARRY_ROOT_HEIGHT; owed: the dead `dc`, and the touch for EXEC_ADDR_ROOT_HEIGHT

WHAT HAPPENED. L1's Stwo settle verifier read a span's starting dividend carry from the `dc` of the boundary block's exec
summary, which loops/core_loop._accrual_effects chains from the previous boundary's `dc` and writes only when the
boundary block's records are derivable. MEASURED (2026-10-28, a snapshot of the relay at 12000 plus a from-genesis replay
of the live blocks): boundary 10860 carried a `collect_dividend` (not derivable), so it wrote no `dc`, and every later
boundary silently took the "no chain to continue" return. That return does not log, which is why nothing in the node logs
showed it. From 10860 on no Stwo settle could have landed. It was not a snapshot bootstrap and not a swallowed exception.

WHAT THIS DOES (CONSENSUS, exec root): `EXEC_CARRY_ROOT_HEIGHT = 30000 if CHAIN_GENERATION == 29 else 1`. From that exec
cursor `ExecState.div_carry` is the T_COUNTER record "div_carry" (exec_root_b2.CARRY_COUNTER). settle_b2 reads it from
the span's authenticated pre-state, ops/settle_chain supplies no carry and refuses spans starting below the gate, and a
span crossing the gate is unprovable. The exec-summary carry path is deleted. doc/stwo/g4-settlement-statement.md
section 5. The gate must fire, with every exec node updated, BEFORE STWO_SETTLE_HEIGHT is set (pinned:
tests/test_gate_reroll_transfer.py).

OWED:
1. At the next reroll (gen 30), delete the `dc` field from exec summaries: core_loop._accrual_effects' carry chain,
   exec_summary_put's `div_carry`, and tests/test_dividend_derivation.py's source pins. Nothing reads `dc` now. It cannot
   go earlier because `execsum:` rows are part of the snapshot state_digest (ops/snapshot_ops), so an updated node writing
   different summaries splits snapshot identity with a not-yet-updated one. The derived records (`rec`, `rd`) are
   likewise read by nothing since the Goldilocks settle branch went (G9). Audit them at the same reroll.
2. `EXEC_ADDR_ROOT_HEIGHT` (8500, already behind the tip) has the memoised-root shape this change fixes for the carry.
   MEASURED in a from-genesis exec replay of the live blocks: at cursors 8500..8519 the memoised root stayed 8499's
   (8e13071a…) while a cold projection of the same state commits the 240 registry records (cb2eff70…). Only the accrual
   at 8520 touched the state, and from there memo == cold (c43a8662…). So a warm exec node and one cold-started in that
   window held different roots for 20 cursors. Settled roots are epoch boundaries, where the two agree, so nothing
   settled was affected and the replays reproduce the warm root. It is not fixed here because naming 8500 in
   projection_gate_at now would move the replayed roots at 8500..8519. At the reroll, inline both gates (1 from gen 30,
   at which point the registry and the carry are empty, so the shape vanishes) or name both in projection_gate_at.

## 2026-10-27 — owed BEFORE the next reroll (gen 30): a pets building loses its unbanked production in the carry

The v2 -> v2 re-pins of the five retired gen-28 -> gen-29 carry tests landed 2026-10-28 (branch carry-v2):
tests/test_an_open_swap_a_taken_loan_or_a_live_game_refuses_a_reroll_carry_and_a_closed_one_crosses_it.py,
tests/test_commit_reveal_tables_cross_a_reroll_only_at_rest.py,
tests/test_amm_pools_and_reserve_vaults_carry_across_a_reroll_and_pay_exactly_as_before.py,
tests/test_battleship_hexholm_and_scrapline_cross_a_reroll_at_rest_and_a_sovereign_world_refuses_it.py and
tests/test_a_carried_contract_plays_exactly_as_it_would_have_without_the_carry.py — live-shaped zkvm2 states through
tools/carry.py (on a saved copy) and alphanet6_carryforward.exec_genesis into the real genesis loader. Every property
holds EXCEPT ONE, which the last test states and which FAILS until the carry is fixed:

**A building staffed before the tip loses the production it accrued and had not banked.** pets.carry_rebase writes
BSI (a building's since-block) as max(0, BSI - tip) = 0, so on the new chain _accrue counts from block 0 and the
(tip - BSI) blocks earned on the old chain — up to ACCRUE_CAP = 20000 blocks per building — are dropped. Measured:
farm staffed at old height 3006, carry at tip 5000, collect 900 blocks later: old chain 13 fodder, new chain 4. (The
retired gen-28 test hid it by carrying at tip = the staffing height, not at the state's cursor as build() does.)
CONSENSUS-ADJACENT (the carry moves owned resources): fix in pets (e.g. refuse while a staffed building has unbanked
production — collect() is permissionless — or bank it in the carry) and run the test in the reroll rehearsal. Raise
this loudly at the reroll if it is not done.

## 2026-09-26 — owed after the betanet-8 (gen 27) cleanup

- **Exec-layer `>= 1` helpers keep dead legacy branches** (slice 2, 9c6bf717): the `ExecState.rules_*` helpers, the
  exec root layout and the legacy field-pool checks under `rules_r2()` still branch on height 0, which no real block
  reaches. Deletable only with a replay proving height 0 never reaches them — a cleanup, not owed by a reroll.
  **Left 2026-09-30 (dead-code pass), not safe as a plain deletion:** height 0 IS reached — a fresh ExecState applies
  genesis at applying_height 0, and `exec_state_bind.root_v2(0)` is False, so the exec genesis root at cursor -1/0 is
  the v1 layout and "reaches the exec summaries in L1 `meta`" (root_v2's own docstring). Collapsing the helpers to
  True changes that root. tests/test_privacy_pause, test_shielded_wide, test_exec_rules_v2 and test_review_round2
  pin the height-0 answer. Only at a reroll, with the genesis exec root re-derived, or with a replay proving the
  cursor-0 root is never compared.
- **A settle proof whose span starts at exec cursor 0 may not match the settled genesis root**: the exec genesis root at
  cursor 0 is the v1 layout, a proof starting there uses v2 (found by the slice-2 agent; same on the old code; betanet-8
  is past cursor 0, so it bites only the first settle after the NEXT reroll). Investigate before that reroll.
  **Status 2026-09-30:** that reroll happened (betanet-9, gen 28). Measured read-only on the relay: `/exec/settlement`
  cursor 19690, last_settled_cursor 19681 — settlement advances on betanet-9. NOT checked: whether the first span
  (from cursor 0) carried a proof or degraded to a bare attestation; that needs the exec log of the first settle.
- **install.sh's root→account migration branch** says to delete it by mainnet; it is also what install-timers.sh
  undid (doc/jobs.md). Delete with the next installer pass once no root install remains.
  **Left 2026-09-30:** whether any fleet node still runs a root install cannot be measured from here (fleet operators
  give us no root); the branch stays until someone confirms it.

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
3. a height gate `<adoption height> if CHAIN_GENERATION == <the LIVE generation> else 1` for the relaxation (at the
   fleet's adoption block), registered in the GATE LEDGER. Key it on the generation that is live WHEN IT SHIPS (28 as of
   2026-10-10): a gate keyed on an older generation evaluates to its `else` branch — 1 — and ships the relaxation
   ungated from block 1.
Pinned by tests/test_proof_trace_ldt.py (`fold refuses under the rule`) and tests/test_fold_hardening.py.

## Account authentication — activation expression (nothing to delete)

`protocol.AUTH_ACTIVE = CHAIN_GENERATION >= 24 or NADO_AUTH_FORCE`. It is an expression, not a gate: on gen 23 the
`auth` recipient is refused and no account can hold a config; on gen 24+ it is live from block 0. After the gen-24
reroll the `>= 24` half is a tautology and MAY be simplified to `True` — optional, cosmetic. Never set
`NADO_AUTH_FORCE` on a validator. (Left as is 2026-09-30: cosmetic, and tests still drive the NADO_AUTH_FORCE recipe.)
