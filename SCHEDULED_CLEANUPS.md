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


## 2026-10-28 — the legacy BLAKE2b pool is still LIVE: close `shielded_transfer` at a gate, then delete it (G9 slice 5)

G9 slice 5 deleted the field, wide and shielded-contract pools, but NOT `execnode/shielded.py`: the transparent
`shielded_transfer` blob op still applies on generation 29. L1 orders any blob, and a transfer with no inputs and value-0
outputs balances (0 + 0 == 0 + 0), so any sender can append zero-value notes to the legacy pool (and later spend them),
moving shield_root and every exec root after it (tests/test_shielded_exec.py t2). No value can enter — the legacy
shield is skipped at every height — but deleting the op would change the root such a blob produces, so it cannot be a
plain deletion. To remove it: a gate `LEGACY_TRANSFER_CLOSE_HEIGHT = <h> if CHAIN_GENERATION == 29 else 1` from which
the exec layer refuses the op (adopted by the whole fleet first), a measurement that the chain carries no
`shielded_transfer` below <h>, then delete shielded.py and pin shield_root / shield_nfset as constants beside
exec_root_b2.RETIRED_FIELD_ROOT. Not consensus-critical for value; owed for the G9 deletion to finish.

## 2026-10-27 — owed BEFORE the next reroll (gen 30): re-pin the carry's refusals for a v2 -> v2 carry

G9 slice 3 inlined BLAKE_EXEC_HEIGHT, and five tests that staged a gen-28 (v1 VM) exec state and carried it to gen 29
could no longer be built, so they were retired: test_a_carried_contract_plays_on_gen29_exactly_as_it_would_have_on_gen28,
test_amm_pools_and_reserve_vaults_carry_to_gen29_and_pay_exactly_as_on_gen28,
test_an_open_swap_a_taken_loan_or_a_live_game_refuses_the_carry_and_a_closed_one_crosses,
test_commit_reveal_tables_carry_at_rest_and_refuse_an_open_round,
test_battleship_hexholm_scrapline_carry_at_rest_and_sovereign_refuses. Their PROPERTIES still bind the gen-30 carry
(tools/carry.py; "the carry carries everything"): an open swap, a taken loan or a live game refuses the carry and a
closed one crosses; commit-reveal tables cross only at rest; a carried AMM pool / reserve vault pays exactly as before.
They are now pinned only for the v1 -> v2 path (test_the_carry_rederives_what_it_can_and_refuses_what_it_cannot).
CONSENSUS-ADJACENT (a wrong carry moves real balances): rewrite each as a v2 -> v2 carry of a live-shaped gen-29 exec
state and run them in the reroll rehearsal. Raise this loudly at the reroll if it is not done.

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
