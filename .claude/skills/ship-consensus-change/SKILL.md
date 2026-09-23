---
name: ship-consensus-change
description: Change a rule that decides whether a block or transaction is valid - validation, weights, pinned roots, draws, state. Use whenever nodes could disagree about the same block, because that disagreement is a fork.
---

# Shipping a change nodes must agree on

A consensus rule is anything that decides whether a block or transaction is **valid**: validation
branches, weights and draws, pinned roots, state layout, anything reaching a state root. If a node
running your change would accept a block that a node without it rejects, this is that kind of change.

Adding a vendor root is one. Restricting who may be drawn is one. So is "just widening" an accepted set —
more permissive is still different.

## 1. Gate it, keyed on the generation

```python
FEATURE_HEIGHT = 59400 if CHAIN_GENERATION == 25 else 1
```

Never a bare height: on a reroll it would leave the rule off for the chain's first 59,400 blocks.
`else 1` = live from block 1 on a fresh chain. `else 0` = never, and the code path is cleanup fodder.

## 2. Register it in all three places, or the test fails

- the **GATE LEDGER** comment in `protocol.py`
- `doc/reroll.md`
- the `REROLL` table in `tests/test_gate_reroll_transfer.py`

```bash
python3 tests/test_gate_reroll_transfer.py
```

It also pins that the live value never changed — a reroll edit must not move live consensus.

## 3. Make the rule a pure function of height

Validation must ask what was in force **at the block it is judging**, so a replay years from now reaches
the same verdict. Thread the height through rather than reading "now":

```python
def ek_roots_at(height) -> frozenset: ...          # pure function of height
verify_ek(chain, now, height=block_height)         # validation passes the block's height
verify_ek(chain, now)                              # advisory callers only; they grant nothing
```

No wall clocks, no network reads, no dict-order dependence, no floats. A certificate expiring mid-block
is otherwise valid on one node and expired on the next — a fork with no attacker involved.

## 4. Prove it at the boundary

Not "the tests pass" — show the rule differing across the gate and nowhere else:

```
roots below gate: 6      roots at gate: 7
drawn below: [a wallet]  drawn at/above: [only proven challengers]
```

Write a test named for the property, driving a synthetic chain. `tests/test_tpm_proven_draw.py` is the
model: it asserts across 300 enrolment ids that no ineligible address is *ever* seated, that a full set is
still drawn, that the degenerate case falls back rather than deadlocking, that old blocks replay under the
old rule, and that the draw is deterministic.

Include the **liveness** case. A rule that excludes everyone at genesis, or after a quiet period, wedges
the chain — eligibility earned by acting, where acting requires being chosen, is a deadlock.

## 5. End to end before committing

```bash
python3 scripts/testnet/run_testnet.py 4 240       # doc/testnet.md
python3 tests/test_no_undefined_names.py           # on the FINAL tree
```

## 6. Pick a height the fleet will reach *after* it has updated

Measure the cadence, choose a height far enough out for the `/update` wave, deploy, and confirm
uniformity **before** the gate fires. Use `deploy-and-verify`.

Gating late costs nothing. Gating early costs a fork.

## 7. When the rule is a PROOF VERIFIER rule (STARK, FRI, recursion, shielded)

Learned shipping P0 + A1 of the 2026-09-23 security review (`PROOF_BIND_HEIGHT`). A verifier pin is still a
validation rule: old nodes accept what new nodes refuse, so it forks exactly like a weight change.

- **The rules are a context, not a parameter.** `stark.verify` is reached through a dozen wrappers
  (vm_circuit, settlement_sparse, exec_state_bind, state_transition, merkle_update, recursive_verify,
  io_replay, appnote, joinsplit2). Do not thread a flag through them; wrap the CONSENSUS entry point:
  `with stark.rules_at(block_height):` in `ops/transaction_ops` (settle branch), `execnode._apply_block`
  (exec layer) and the settler. `stark.rules_for_height(h)` is the pure function; unset = STRICT, so a
  path that forgets refuses an honest old proof loudly instead of accepting a forged one silently.
- **Threads and children do not inherit it.** `asyncio.to_thread` copies the context; a bare `Thread`
  does not; `ops/proof_child.py` is a fresh interpreter and takes `rules` in its request. Enter the
  context INSIDE the worker body.
- **A transcript change is a FORMAT change.** The prover must switch on the same block the verifier does:
  the settler proves under `rules_at(L1 tip + 1)` (a settle is exact-landing above the tip), so at most one
  proof straddling the gate is wasted. A proof-only tightening (P0) has no prover side; a transcript
  change (A1) does — check `stark.prove`, `stark_native.prove` AND `recursive_verify._fs` absorb the same
  thing in the same position (`stark.absorb_statement` is the single encoder).
- **Never absorb a hex string under the alghash2 backend** — it hashes a `str` by its byte SUM (review
  P2). Absorb field lanes (`stark.statement_lanes`).
- **The verdict memo must key on the rules** as well as the bytes (`settle_verify_key(..., rules)`): the
  same proof is ok=True one block below the gate and refused at it.
- **Reproduce the forgery, do not trust the trace.** `tests/test_proof_bind_gate.py` builds the P0 forgery
  (a FRI over 2N interpolated through the composition's N spot-check values) and shows it ACCEPTED under
  the legacy rules and refused at the gate. A finding that only says "traced" is a finding you have not
  seen fail.
- **Test-suite traps for this area:** proving in Python needs `NADO_ALLOW_PYTHON_KERNELS=1` or every
  prove raises the Rust-only policy; the child verifier pins PROTOCOL query strength, so a test that
  lowers `fri.NUM_QUERIES` in-process needs `NADO_PROOF_VERIFY_INPROC=1`; a throwaway `git worktree` of
  HEAD (with the untracked `native/**/*.so` symlinked in) tells a pre-existing failure from yours.
- **The gate height must still be AHEAD at push time.** Tip 205,711 at 6.8 s/block when 208,000 was
  chosen (~4 h). If the push slips past it, move the gate before pushing — a gate in the past makes every
  node switch at its own update moment.

## 8. Exec-layer rules are consensus rules too

Every exec node computes the exec root and L1 settles it by quorum or proof, so a change to what a call
DOES (what is refused, what is refunded, what a transfer records) forks the exec root exactly like an L1
rule forks the chain. Learned shipping `EXEC_RULES_V2_HEIGHT` (C1/F2/Z2/S2 of the 2026-09-23 review).

- **Gate on the block being applied.** `execnode._apply_block` advances `cursor` to h only AFTER applying
  block h's blobs, so inside `apply_blob` the block is `cursor + 1` (`ExecState.rules_v2()`); the
  settlement prover stamps each call with `cursor = h` (`calls_commit.block_calls`), so `_run_call` gates
  on the call's own cursor and the two agree by construction.
- **Mirror every refusal in the prover.** A call the chain skips must be UNPROVABLE
  (`settlement_proofs._run_call` raises, the existing shape); a prover more permissive than the chain
  proves a transition the chain never applied and settles a root every honest node disagrees with.
- **Name the constant `*_HEIGHT`** so `tests/test_gate_reroll_transfer.py` sees it; register it in the
  GATE LEDGER and `doc/reroll.md`.
- **Show the legacy behaviour in the gate test, one block below the gate**, before showing the refusal at
  it: `tests/test_exec_rules_v2.py` books the worthless token as native value and records the unbacked
  exit under the old rules. A gate test that only shows the new rule has not demonstrated the hole.
- **L1 admission rules that mirror an exec rule** (typing `method` in the blob) use the SAME constant on
  `block_height`; the exec cursor is the L1 height, so one number gates both layers.
