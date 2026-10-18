# Storage deposits (design, 2026-10-18)

**Why.** Contract storage is unpriced: a call may create new slots limited only by gas, so the exec state can grow by up to
~2M slots per block, permanently, for L1 fees (audit 2026-09-24 #14, confirmed 2026-10-18). The cross-rollup inbox has the
same shape. Operator decisions 2026-10-18: a refundable **storage deposit** per slot, and free games are **sponsored by the
game** (its deposit pool), so free play stays free.

## Rule (from `STORAGE_DEPOSIT_HEIGHT`, gated `H if CHAIN_GENERATION == 28 else 1`)

- `STORAGE_SLOT_DEPOSIT` raw locks per live (non-zero) storage slot. Proposed 1,000,000 raw (0.0001 NADO): an honest game
  writing ~20 slots locks 0.002 NADO; 10 million junk slots lock 1,000 NADO.
- After an applied call, `delta` = slots that became non-zero − slots that became zero.
  - `delta > 0`: `delta × D` is taken from the **caller's** exec balance; whatever it cannot cover comes from the
    contract's **deposit pool**. If both together cannot cover it, the call reverts (escrow refunded, nothing applied) —
    the same shape as the step budget.
  - `delta < 0`: `|delta| × D` is released from the contract's held deposits (capped at what it holds) to the **caller**
    who freed the slots, so cleaning up pays.
  - The contract records `deposit_held` (locked for its live slots) and `deposit_pool` (sponsorship). Both enter the exec
    root beside the contract's meta, and are absent while zero (empty is absent), so no root moves before the first deposit.
- New exec ops: `sponsor` (anyone moves exec balance into a contract's pool) and `unsponsor` (the deployer takes back pool
  not held). The faucet funds the official free games' pools.
- Slots that existed before the gate hold no deposit: freeing them releases nothing beyond what the contract holds.

## What it touches

- `execnode/state.py` call path (after the step-budget checks, all-or-nothing with the payouts), the two new ops, exec root
  records (`execnode/exec_root.py`), snapshot (`to_dict`/`_restore`, empty is absent).
- **Settlement prover**: a span whose calls move deposits is unprovable (raise), like a reverted call — the records half
  cannot derive deposit movements today; the Stwo settlement statement (doc/stwo-migration.md §9, option R) designs them in.
- **Reroll carry** (`tools/alphanet6_carryforward.py`, `execnode/exec_genesis.py`): pools and held deposits are value —
  they carry with their contract, and the conservation check counts them.
- **Clients**: the dApp SDK surfaces "free play sponsored — pool low" and a deposit line in confirms; the wallet shows a
  game's pool. 16 languages.
- **Tests under both rule sets**: below the gate unchanged; at it, delta charged caller-first then pool, revert when
  uncovered, release to the freeing caller, sponsor/unsponsor bounds, root and snapshot round trips, carry conservation,
  the prover refusing a deposit-moving span.

## Open before building

- The exact `STORAGE_SLOT_DEPOSIT` (0.0001 NADO proposed).
- The initial pool top-up for each official free game, from the faucet.
