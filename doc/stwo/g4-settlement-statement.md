# G4: the generation-29 settlement statement (doc/stwo-migration.md 9.5)

Started 2026-10-20. Under option R (section 7, item 7) the reroll ships with the bonded quorum settling the exec root and
the proof branch refused; Stwo settlement turns on later by a gen-29 gate. What the reroll must FREEZE is therefore the
statement — what a proof claims about a span and in which formats — together with a Stwo prototype that proves it. This
document is that statement. It is written against what today's Goldilocks settle proof binds (mapped 2026-10-20 with
file:line references; the summary is section 1) so nothing it checks today is lost.

## 1. What today's settle proof binds (generation 28)

L1 (`ops/transaction_ops.py` `_validate_settle`, proof branch) checks, in order:

- the cursor and the tip: the proof's cursor is the tx's; a namespace's first settlement comes from the quorum; the
  claimed pre root composes to the settled tip and the claimed post root to the tx's `state_root`;
- chain reads: every BHASH/BEACON value in the proof's io equals the finalized chain
  (`settle_chain_reads_check`; pinned by `tests/test_a_settle_proof_cannot_swap_a_chain_read.py` since 2026-10-20 — the
  suite had no negative test of it before);
- records-frozen spans may not cross an epoch boundary and may not PAY;
- calldata: the span's segments partition (tip, cursor], and each segment's calls commitment equals the fold of the
  per-block call leaves L1 persisted at incorporate time (`calls_commit.verify_calls_bound_to_summaries`);
- the STARK (`settlement_sparse.verify_settlement_sparse`): per segment the execution proof over the public calls; the
  calls commitment recomputed; the pre-state contracts pinned to the pre KV root (slots, code and meta leaves); the
  per-contract io re-derived from the authenticated io (the prover's copy is ignored); the net updates DERIVED by the
  verifier and required to equal the transition proof's; segment j's post is segment j+1's pre;
- assets: metadata preimages accepted only against their committed leaf; balances read from a pinned records pre-state;
- records: effects derived from block bodies (deposits, faucet donations, value-call escrows, the dividend accrual) and
  from the proof's io (PAY), folded with a running non-negative balance, and the records transition proof must equal them.

What it cannot prove: a span containing `collect_dividend`, `bridge_withdraw`, a shield/unshield or an xmsg. The new
withdrawal leaf's POSITION includes a nonce from an exec-state counter that no root commits, and the block-body
derivation has no exec state. Measured: 17 of 22 attempts in a week were never submitted for this reason.

## 2. The generation-29 statement

### 2.1 Public inputs (every one supplied or checked natively by L1)

| input | source |
|---|---|
| `ns`, `prev_cursor`, `cursor` | the settled tip and the tx |
| `pre_root` | the settled tip's root, `exec_root_b2` format (BLAKE2s, compressed trees) |
| `post_root` | the tx's `state_root` |
| `calls` | the BLAKE2s fold (2.3) of the call leaves L1 persisted for blocks (prev_cursor, cursor], in block-then-tx order |
| `chain_reads` | the (kind, key, value) list in io order, each bound to the finalized chain by L1 (values unreduced: 256-bit words) |
| `body_effects` | the records effects L1 derives from block bodies (deposits, donations, escrows, the dividend accrual), per block |

### 2.2 The relation the proof establishes

Starting from `pre_root`, for each block of the span in order:

1. its calls run on the gen-29 VM (`execnode/zkvm2.py`) with the public fields of their leaves (contract, method, caller
   digest, args, value, asset, cursor, timestamp), in tx order, each producing the io log the VM semantics define;
2. every SLOAD equals the current tree value at `exec_root_b2.slot_key`, every SSTORE updates it (zero = delete), every
   PAY and asset effect moves the records half, each through a compressed-tree path (`execnode/csmt.py`) against the
   current root;
3. the records-moving ops the gen-28 statement could not carry run IN ORDER with the calls: `collect_dividend` reads the
   caller's `T_DIV_BAL` leaf and the `dw_nonce` counter leaf (`T_COUNTER`, committed in the gen-29 root since
   2026-10-20), deletes the balance, increments the counter and inserts the withdrawal leaf at
   `record_key(T_DIV_WD, addr, nonce)`; `bridge_withdraw` likewise with `T_BRIDGE_BAL` and `wd_nonce`; unshield exits
   with `uw_nonce`; xmsg emits with `outbox_seq`;
4. the block's `body_effects` apply at the block's end (the accrual at its boundary block, as L1 orders it today);

and the root after the last block equals `post_root`.

### 2.3 Formats frozen at the reroll

- the exec root, positions and values: `execnode/exec_root_b2.py` (incl. `T_COUNTER`);
- the tree: `execnode/csmt.py` (compressed, canonical, one BLAKE2s compression per node);
- the VM: `execnode/zkvm2.py` (256-bit wrapping word, BLAKE2s accumulator);
- the call leaf: today's persisted leaf (`calls_commit.call_leaf` / `event_leaf`, a 256-bit BLAKE2b digest of the
  canonical call, with gen-29 address digests);
- the calls fold (new): `c_0 = 32 zero bytes; c_i = BLAKE2s(c_{i-1} || leaf_i)` with its own personalization, so the
  circuit proves the fold with the same Blake component as everything else;
- the circuit's maximum tree path depth: beyond feasible key grinding (around 80), not the typical 18-28
  (doc/stwo/g1-tree-shape.md section 5).

### 2.4 Soundness: the suite the new verifier must refuse

Ported from today's settle tests (each line one refusal; today's file in brackets):

- a first settlement by proof; a pre root not extending the tip; a post root other than the tx's; a cursor mismatch
  [test_settle_with_proof];
- a swapped, unfinalized, missing or out-of-range chain read [test_a_settle_proof_cannot_swap_a_chain_read];
- an extra SSTORE in the claimed io; a tampered transition; a pre-state slot outside the pin; a phantom pre-state record
  hiding an in-span deploy [test_settle_cid_io_binding, test_settlement_sparse, test_settle_pre_contracts_exported];
- swapped upgrade code, a forged event sender, a forged pre-state deployer, a transition without the event's updates
  [test_exec_root_v2];
- a lied SLOAD, an update-count mismatch [test_exec_state_bind];
- a changed arg, method, caller or cursor; injected, dropped or reordered calls; a fabricated or missing commitment;
  segments not covering the span; a missing summary; the span cap [test_da_binding, test_exec_summary_binding];
- a RET split not matching the calls; an unterminated log; a frozen proof with PAY [test_pay_binding];
- a forged or omitted asset metadata preimage; an unpinned records pre-state; an ABAL read disagreeing with the pinned
  ledger [test_asset_settle_l1, test_asset_ops_settle_by_proof];
- a records move with no effect, effects disagreeing with the transition, a wrong amount, a dropped effect
  [test_records_bound_settle, test_records_bind];
- NEW for the ops 2.2 point 3 adds: a withdrawal leaf at a nonce other than the committed counter + 1; an amount other
  than the committed balance; a counter not incremented; a balance not deleted.

## 3. Next steps

1. The calls fold (2.3) as code beside today's, with its test (dormant, like the rest of gen 29).
2. A Stwo prototype of the compressed-tree path update (one row per level, BLAKE2s compression with the `NADOcsN1` /
   `NADOcsL1` personalizations, key-bit ordering, the variable depth up to the circuit maximum), on the round and XOR
   components `native/stwo_js` already uses; measured against the G1 numbers.
3. The VM step component for `zkvm2` (the CPU row, the storage and io buses by lookup, the BLAKE2s accumulator).
4. The records ops of 2.2 point 3 as a component, and the forgery suite of 2.4 against the prototype verifier.
