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
