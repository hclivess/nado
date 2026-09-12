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

`tests/test_gate_reroll_transfer.py` pins both halves of every line: that the gen-25 value still equals what the live
chain uses (a reroll edit must never change live consensus) and that the reroll value is the documented one. A new
gate added without a branch fails that test.

### The ledger (gen 25, betanet-7)

Live from genesis at the next reroll (`else 1`): `DEVICE_ATTEST_HEIGHT`, `DEVICE_BIND_HEIGHT`,
`DEVICE_BIND_STRICT_HEIGHT`, `DEVICE_BIND_PERMANENT_HEIGHT`, `DEVICE_REBIND_INSTANT_HEIGHT`,
`DEVICE_ATTEST_TPM_ANY_AAGUID_HEIGHT`, `DEVICE_ATTEST_EK_HEIGHT`,
`DEVICE_ATTEST_EK_SHORT_HEIGHT`, `DEVICE_ATTEST_EK_ROOTS_V2_HEIGHT`, `DEVICE_ATTEST_EK_PROVEN_HEIGHT`, `DEVICE_ATTEST_EK_READY_HEIGHT`, `DEVICE_BIND_DEVKEY_ALL_EPOCH`, `BOND_ATTEST_OPTIONAL_HEIGHT`,
`POOL_RETIRE_HEIGHT`,
`BOND_CURVE_RETIRE_HEIGHT`, `OPEN_LANE_EXCLUDE_RETIRE_HEIGHT`.

Never, delete the path (`else 0`): `BOND_DEVICE_CAP_HEIGHT`, `BOND_WEIGHT_CURVE_HEIGHT`, `POOL_HEIGHT`,
`OPEN_LANE_EXCLUDE_BONDED_HEIGHT`.

From epoch 0 (`else 0` = always on): `DIVIDEND_ATTESTED_EPOCH`, `DIVIDEND_WEIGHT_CAP_V2_EPOCH`,
`DIV_CARRY_METER_EPOCH`.

### What the cleanup deletes

With the four "never" gates at 0 the savings lane is plain stake with no device, no pools and no exclusion, so:

- `mining_ops.bonded_producer_registry` collapses to `return bonded_registry`;
- `mining_ops.open_lane_draw_registry` collapses to `return open_registry`;
- `mining_ops.bond_weight` and `bond_knee` lose their last caller;
- `reward_ops._pool_split`, the `pool` / `delegate` / `undelegate` transactions, the `pool_*` account fields, the
  `pool_revert` DB and `/pools` all go;
- the retire gates themselves become vacuous and go with them.

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
6. Run the carry-forward tool `--write`; confirm Δ = 0.
7. Edit: `CHAIN_ID`, `GENESIS_TIMESTAMP`, **`CHAIN_GENERATION`** — the last is THE purge trigger; forgetting it means
   nothing purges. Delete `private/genesis_alloc.dat`. No gate edits are needed (see above).
8. `tests/test_genesis_alloc_format.py`, `tests/test_gate_reroll_transfer.py` (update its generation), commit.
9. `systemctl start nado` — the node self-purges on the generation mismatch. Check `/get_supply` equals the carry
   total, then push and kick the `/update` wave so the fleet purges too.
10. Start exec and watchtower, then `python3 -m execnode.games.redeploy` (confirms via a provisional view, needs no
    finality), `_fund_faucet.py <NADO>`, and any manual refunds.
11. Follow-up commit: the cleanup above.

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

Verify unification by comparing a block hash at a **common height**, never by comparing tips.
