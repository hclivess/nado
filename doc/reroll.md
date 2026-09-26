# Reroll runbook and the gate ledger

A **reroll** restarts the chain from a fresh genesis (new `CHAIN_ID`, `GENESIS_TIMESTAMP` and
`CHAIN_GENERATION`), carrying balances forward. This document is the procedure, the failure modes that have actually
happened, and — since 2026-09-09 — the rule that makes the *code* cleanup mechanical instead of archaeological.

## The gate rule

**Every consensus gate is written `<live height> if CHAIN_GENERATION == <gen> else <x>`.** Never a bare height.

A bare height silently survives a reroll: `POOL_HEIGHT = 6000` on a fresh chain means the rule is off for the first
6,000 blocks of a chain that was supposed to start with it. Writing the branch instead means a reroll needs no edit at
all — bump `CHAIN_GENERATION` and every rule lands where a fresh chain wants it:

| `else` value | meaning on the fresh chain | what the cleanup does |
|---|---|---|
| `1` | live from block 1 (or epoch 0) | delete the branch, inline the rule as unconditional |
| `0` | the feature never turns on | delete the gate **and its code path** |

`tests/test_gate_reroll_transfer.py` pins both halves of every live line: that the live value still equals what the
chain uses (a reroll edit must never change live consensus) and that the reroll value is the documented one. A new
gate added without a branch fails that test, and so does a cleaned-up gate that comes back.

**Inlining an `else 1` gate is not deleting the comparison.** A rule "live from block 1" is still OFF at height 0, and
height 0 is reachable: genesis, mempool admission while the tip is genesis, the exec state at cursor -1/0, a tx whose
own `max_block` is 0. Wherever such a caller can reach the check, the cleanup keeps `>= 1` (the gate's own value) so
no verdict moves; only where the height is provably >= 1 does the comparison go.

### The ledger (gen 27, betanet-8)

Live gates, keyed `== 27` — live from block 1 at the next reroll: `EK_ENROL_ROOTS_AT_HEIGHT` (1400),
`ZK_HARDEN_HEIGHT` (zk audit 2026-09-26: ARG-bus tags, settle pre_contracts shape, no NOP, wide pool depth 48).
`DEVICE_ATTEST_HEIGHT` is a plain `1`, not generation-keyed.

**Every gen-25 gate is gone** (both cleanup slices below). Inlined as unconditional rules after the betanet-8 reroll
(slice 2), with `>= 1` kept only where height 0 can reach the check: `DEVICE_BIND_HEIGHT`, `DEVICE_BIND_STRICT_HEIGHT`,
`DEVICE_BIND_PERMANENT_HEIGHT`, `DEVICE_REBIND_INSTANT_HEIGHT`, `DEVICE_BIND_PERMANENT_EK_HEIGHT`,
`DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT`, `DEVICE_ATTEST_TREZOR_SERIAL_OPTIONAL_HEIGHT`, `DEVICE_ATTEST_EK_HEIGHT`,
`DEVICE_ATTEST_EK_SHORT_HEIGHT`, `DEVICE_ATTEST_EK_ROOTS_V2_HEIGHT`, `DEVICE_ATTEST_EK_PROVEN_HEIGHT`,
`DEVICE_ATTEST_EK_READY_HEIGHT`, `TX_AT_MOST_ONCE_STRICT_HEIGHT`, `PROOF_BIND_HEIGHT`, `EXEC_RULES_V2_HEIGHT`,
`PROOF_BLOCK_SELECTOR_HEIGHT`, `REVIEW_R2_HEIGHT`, `PROOF_TRACE_LDT_HEIGHT`, `PROOF_FIXED_CID_HEIGHT`,
`PRIVACY_PAUSE_HEIGHT`, `PROOF_QUERY_FULL_HEIGHT`, `ADDRESS_KEY_BIND_HEIGHT`, `SETTLE_ANCHOR_HEIGHT`,
`SLASH_DEDUP_HEIGHT`, `EXEC_CTX_CURRENT_HEIGHT`, `EXEC_ROOT_V2_HEIGHT`, `SHIELD_WIDE_HEIGHT`; and the from-epoch-0
gates `LEASE_V2_EPOCH` (with `protocol.lease_v2_at`), `DIVIDEND_ATTESTED_EPOCH`, `DIVIDEND_WEIGHT_CAP_V2_EPOCH`,
`DIV_CARRY_METER_EPOCH`.

Re-anchored, not gated: `CHAIN_CLOCK_CADENCE_DS` (60 on gen 25 = exactly `h*6`; 64 since, a plain value). At every reroll
**measure** the outgoing chain's cadence from its own block timestamps (`(ts[tip] - ts[1]) / (tip - 1)`, and the
last ~10,000 blocks separately) and set the next value to the recent figure in deciseconds; the accumulated
lag resets with the new `GENESIS_TIMESTAMP`. Gen 25 ran 6.69 s overall and 6.5 s recently against a clock that
assumed 6, which is where the 40 h TIME lag came from.

Never, delete the path (`else 0`): none left. `BOND_DEVICE_CAP_HEIGHT`, `BOND_WEIGHT_CURVE_HEIGHT`, `POOL_HEIGHT` and
`OPEN_LANE_EXCLUDE_BONDED_HEIGHT` (with the derived `OPEN_LANE_EXCLUDE_BONDED_EPOCH`) and their `else 1` retire twins
`BOND_ATTEST_OPTIONAL_HEIGHT`, `POOL_RETIRE_HEIGHT`, `BOND_CURVE_RETIRE_HEIGHT`, `OPEN_LANE_EXCLUDE_RETIRE_HEIGHT` were
deleted with their code after the betanet-8 reroll (below); `tests/test_gate_reroll_transfer.py` pins them as deleted.

### What the cleanup deletes

**Done for the savings-lane gates after the betanet-8 reroll (gen 27).** With the four "never" gates at 0 the savings
lane is plain stake with no device, no pools and no exclusion, so:

- `mining_ops.bonded_producer_registry` collapses to `return bonded_registry`;
- `mining_ops.open_lane_draw_registry` collapses to `return open_registry`;
- `mining_ops.bond_weight` and `bond_knee` lose their last caller;
- `reward_ops._pool_split`, the `pool` / `delegate` / `undelegate` transactions, the `pool_*` account fields, the
  `pool_revert` DB and `/pools` all go;
- the retire gates themselves become vacuous and go with them.

Three things deliberately stayed, because deleting them would have changed gen-27 behaviour: `pool`, `delegate` and
`undelegate` remain in `RESERVED_RECIPIENTS` with their per-block uniqueness key, and `validate_transaction` still
refuses them with the message the gen-25 branch raised at `POOL_HEIGHT = 0` ("staking pools are not enabled yet") —
falling through to the generic path would turn a refused tx into an accepted one. `/mining_status` keeps the fields
wallets read, at their fixed gen-27 values (`bond_attest_required: false`, `bond_plain: true`,
`open_excluded_bonded`); `bond_cap_active`, `pools_retired`, `bond_device_cap`, `bond_knee` and the delegation view
went. `tests/test_savings_lane_is_plain_stake.py` pins all of it.

**Slice 2, done after the betanet-8 reroll (gen 27): the `else 1` and from-epoch-0 gates.** Each constant and its gen-25
branch went; the rule is unconditional. What was kept, and why:

- `>= 1` (the gate's own value) where height 0 reaches the check: `validate_transaction` also runs at mempool
  admission with the tip's height, which is 0 on a genesis tip; a tx's own `max_block` may be 0; the exec node applies
  genesis from cursor -1, so `ExecState.rules_*`, `exec_state_bind.root_v2` (the exec root layout, which reaches
  the exec summaries in L1 `meta`) and the F3 call context keep `>= 1`; a settle cursor or a namespace's top attested
  cursor may be 0. Where the height is provably >= 1 — apply paths (genesis carries no transactions), a remote block
  (rebuilt at tip + 1), the challenger draw (behind the enrolment rule), enrolment records — the guard is gone.
- `stark.Rules` / `rules_at` / `with_rules` plumbing stays; `rules_for_height` returns `RULES_STRICT` for None or
  height >= 1 and `RULES_LEGACY` for height 0, exactly what the six gates computed.
- `epoch is None` stays in the lease helpers (`lease_epochs_for`, `recert_history_epochs`, `fidelity_step`), whose
  signatures still admit a legacy caller with no epoch. `records_bind.dividend_accrual_effects` lost its unmetered
  `epoch is None` branch with `DIV_CARRY_METER_EPOCH` (the SCHEDULED_CLEANUPS.md entry): every production caller passes
  an epoch >= 0.
- `/status` still serves `proof_rules` (every height 1) and `lease_v2_epoch` (0): the wallet reads them.
- `CHAIN_CLOCK_CADENCE_DS` is the plain `64`.

Proven by replaying the live betanet-8 chain from genesis through both trees (same state root as the live blocks at
every height) — see the slice-2 commit messages.

Do this in a **follow-up commit after** the reroll is live and verified, never in the same one — the reroll commit
must be reviewable as "new genesis, same rules".

## Runbook (as executed for gen 22, 23 and 24)

1. Audit exec state read-only over HTTP (`/exec/contracts`, `/exec/bridge`, `/exec/assets`).
2. Dry-run `tools/alphanet6_carryforward.py` against a **read-only LMDB copy**; it folds balances, bonded, dividends,
   pending withdrawals and the bridge, hard-asserts the shielded pool is EMPTY, and refuses unless supply conserves
   exactly (Δ = 0).
3. Rehearse the source edit on a throwaway worktree (symlink `native/` in).
4. Back up the data directory.
5. `systemctl stop nado-watchtower nado-exec nado` (a fixed-point snapshot).
6. **Drain the exec tail**: `python3 tools/exec_drain.py /root/nado/exec_state.json /root`. The exec node applies only
   finalized blocks, so at any stop it is ~45 blocks behind the tip, and those blocks hold real exec ops (dividend
   claims, deposits). The drain replays them with the exec node's own apply path and prints the tip.
7. Run the carry-forward tool `--write --l1-tip <that tip>`; confirm Δ = 0. It also records the identities PRESENT at
   the tip (a live lease); genesis leases exactly those, never every registered identity (see failure 6).
8. Edit: `CHAIN_ID`, `GENESIS_TIMESTAMP`, **`CHAIN_GENERATION`** — the last is THE purge trigger; forgetting it means
   nothing purges. Delete `private/genesis_alloc.dat`. No gate edits are needed (see above).
9. `tests/test_genesis_alloc_format.py`, `tests/test_gate_reroll_transfer.py` (update its generation), commit.
10. `systemctl start nado` — the node self-purges on the generation mismatch. Check `/get_supply` equals the carry
   total and the node's `open:N` log line equals the tip's live collector count, then push and kick the wave **from a
   fleet node** (`http://<fleet-ip>:9173/update?wave=true`, failure 7) so the fleet purges too. Confirm unification by
   one block hash at a common height across every node.
11. Start exec and watchtower, then `python3 -m execnode.games.redeploy` (confirms via a provisional view, needs no
    finality). It rewires EVERY `const CID` / `const <NAME>_CID` in static/ (the wallet's `RESERVE_CID` included) and
    the reward table, and verifies each resolves to a live contract; the live e2e scripts derive their ids and need
    nothing. Then `_fund_faucet.py <NADO>` with the faucet bank the carry refunded to the operator (betanet-8: 99.4),
    and the manual refunds the carry-forward printed (`scripts/nado_cli.py send <addr> <NADO> --memo …`).
12. Check `/status` → `jobs.problems` is empty (doc/jobs.md). The DEX price history resets itself on the new chain id.
13. Walk every page headless (every `static/*.html`, script errors and failed requests) — the betanet-8 walk found the
    wallet's reserve panel on a dead contract and the lend page broken since it was written.
14. Follow-up commits: the gate cleanup (done for gen 25 in two slices: e7a17f00, 9c6bf717 — replay the live chain
    through old and new code and require the same state root, as those did).

## Failure modes that have actually happened

1. **`CHAIN_GENERATION` not bumped** → nothing purges (fixed c3b5fb84).
2. **Generation marker absent** on a hand-installed layout → the node stamps instead of purging.
3. **Block-0 genesis checks are mute** on rolling/snapshot-booted nodes — they have no block 0 on disk.
4. **Snapshot re-infection**: purged nodes rebooted into the un-purged majority and adopted the old chain through
   quorum snapshots, which carry no genesis-descent proof — 7 of 10 nodes were back on the dead chain within minutes,
   and the old chain's weight froze the new chain's depth floor. The durable defence is the **height-vs-wallclock
   bound**: no chain of this genesis can be taller than about `2 × (now − GENESIS_TIMESTAMP) / BLOCK_TIME + 600`.
   Boot purges on-disk data over the bound, and status admission refuses peers advertising impossible heights or a
   mismatched `genesis_hash`.
5. **A splice edit can produce valid-but-wrong Python** (`f# comment` parses as a bare name): `py_compile` *and*
   import-smoke every edited module before restarting anything.
6. **Every registered identity leased at genesis** (betanet-8, gen 26): the open lane showed 79 collectors against 46
   live, because lapsed identities got a fresh lease and would have been drawn for slots they never fill. Caught before
   block 1 and re-rolled as gen 27. Before starting, check the node's `open:N` log line equals the tip's live count.
7. **The `/update` wave never leaves the push host**: the checkout you push from is already current, answers
   `up_to_date`, and only a node that actually UPDATED forwards the wave — and after a reroll its peer pool is empty
   anyway (every old-chain peer is refused). Kick two fleet nodes directly (`http://<ip>:9173/update?wave=true`).

Verify unification by comparing a block hash at a **common height**, never by comparing tips.
