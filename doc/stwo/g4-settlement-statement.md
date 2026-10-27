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
- the tree path depth: ANY depth a 256-bit key allows. The path component (step 2 below) takes each write's shape
  (op, depths) as part of the statement and rebuilds its preprocessed columns from it, so no fixed circuit maximum
  exists to exceed. A ground key that shares a long prefix costs only rows in its own span, which is the grinder's
  bill (doc/stwo/g1-tree-shape.md section 5 had planned a fixed maximum of around 80; superseded 2026-10-20).

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

## 3. Proof parameters (2026-10-25)

Measured on the busiest real span (130 updates, 4,708 rows) with the batch prototype. Every configuration verified the
honest proof and refused all 16 forgeries. Security is Stwo's conjectured count, `pow_bits + log_blowup x n_queries`.

| config (pow, log blowup, queries, fold step) | bits | prove | verify | proof |
|---|---|---|---|---|
| 20, 2, 160, 1 (stwo_js's node config) | 340 | 13.3 s | 197 ms | 2.53 MB |
| 20, 2, 54, 1 | 128 | 12.1 s | 93 ms | 920 KB |
| **20, 2, 54, 4 (chosen)** | **128** | **11.9 s** | **87 ms** | **860 KB** |
| 20, 3, 36, 4 | 128 | 19.0 s | 134 ms | 605 KB |
| 27, 3, 23, 4 (StarkWare's Cairo proof, provably.fast) | 96 | 62.8 s | 149 ms | 412 KB |
| 26, 2, 35, 4 (StarkWare's recursion circuit) | 96 | 16.8 s | 81 ms | 584 KB |

- **Chosen: 128 bits, blowup 4, 54 queries, fold step 4.** The proof is 66% smaller, verify is 2.3x faster, and proving
  is slightly faster. 128 rather than 96 bits because these proofs settle balances. The cost of going to 96 bits would
  be about 30% more proof bytes, which is small.
- **Grinding stays at 20 bits.** 27 bits added ~50 s per proof here. StarkWare can afford it because provably.fast
  made their grinding kernel a SIMD one.
- About 70 ms of every verify time above is the preprocessed commitment being recomputed per statement (section 2.3).
  A fixed-shape circuit would remove it.
- **The live Stwo pool (native/stwo_js) still proves at 340 bits.** Moving it to the same config would shrink every
  private send's proof the same way, which matters most on phones. It is a consensus change, so it needs its own gate
  at the fleet's adoption block.
- **The provably.fast prover** (`starknet-innovation/proving`, the `mainnet-season` branch) is about 2x faster than
  upstream, with peak memory down from 13.9 to 1.13 GiB. Its proofs are byte-identical to upstream's by its own
  acceptance rule. So it is a prover-only swap: the node's verifier pin does not change. It is built on another
  upstream revision, so adopting it means moving both crates' Stwo pin, with the verifier re-checked against the
  forgery suites.

### 3a. The Stwo pin stays at 826591c (measured 2026-10-25; operator decision: "just keep our pin")

Upstream development left `starkware-libs/stwo` at the end of July 2026 (826591c, our pin, is that repository's last
commit) for `starkware-libs/proving`. Measured on a 130-update batch (3,486 rows), the same crate ported to each, every
build with Stwo's `parallel` feature, 5 interleaved rounds, medians:

| prover | 1 thread | 4 threads | verify (4 thr.) | peak memory |
|---|---|---|---|---|
| our pin, 826591c | 8.78 s | 3.79 s | 31 ms | 1.78 GiB |
| starkware-libs/proving (2026-10-15) | 9.05 s | 4.34 s | 34 ms | 1.78 GiB |
| provably.fast `mainnet-season` (2026-10-23) | 10.15 s | 4.37 s | 53 ms | 0.78-0.87 GiB |

All three gave the same roots, verified the honest proof and refused all 16 forgeries. Neither newer prover is faster on
a trace this small (their gains are on Cairo-sized traces); provably.fast halves peak memory, the reason to revisit it
when proving moves into phone wallets. Both newer versions commit every tree at an explicit lifting height that is
part of the proof, so moving `native/stwo_js` to either is a consensus change, not a library bump. The cheapest speed-up
needs no pin move: Stwo's `parallel` feature takes this batch from 8.8 s to 3.8 s on four threads.

## 4. Next steps

1. The calls fold (2.3) as code beside today's, with its test (dormant, like the rest of gen 29).
2. A Stwo prototype of the compressed-tree path update (one row per level, BLAKE2s compression with the `NADOcsN1` /
   `NADOcsL1` personalizations, key-bit ordering, the variable depth up to the circuit maximum), on the round and XOR
   components `native/stwo_js` already uses; measured against the G1 numbers.

   **v0 done (`native/stwo_settle`, 2026-10-20): one key update.** Upstream's BLAKE2s AIR (scheduler, rounds, XOR
   tables; vendored at stwo rev 826591c) plus `src/blake/path.rs`: each row of the path component consumes one scheduler
   compression by lookup (the scheduler gained a multiplicity column so only real rows are consumed), range-checks the
   message bytes through the xor8 table, and ties the digest to the next level's child half by the key bit. The old and
   new leaves share the siblings, so one proof binds `(key, vh_old, vh_new, old_root, new_root)`. The verifier recomputes
   the preprocessed commitment instead of trusting the proof's (upstream took it unchecked), mixes the config and the
   statement into the channel before any challenge, and returns errors instead of asserting.
   `tests/test_a_stwo_proof_of_a_tree_update_proves_csmt_roots_and_refuses_forgeries.py` drives it with real
   `csmt.Tree` updates: the proven roots equal csmt.py's, and forged new root, old root, key, new/old value hash and
   swapped roots are refused. Measured under the 340-bit config of the time (pow 20, blowup 4, 160 queries; section 3 replaced it):

   | depth | prove | verify | proof |
   |---|---|---|---|
   | 0 | 5.6 s | 72 ms | 2.50 MB |
   | 8 | 5.7 s | 73 ms | 2.48 MB |
   | 29 | 5.7 s | 147 ms | 2.50 MB |

   The cost is flat in depth because the fixed BLAKE2s tables (XOR 12/9/8/7/4) dominate a single update.

   **Batched (2026-10-20): K sequential updates in one trace.** Each update owns a block of rows; a preprocessed
   `settle_upd` column numbers them and every public tuple carries the number, so no row can lend its key, value or root
   to another update. Update i+1's siblings are against the tree update i left, and the verifier chains the roots
   natively (`root_new[i] == root_old[i+1]`, else `Chain`). The intermediate roots are public. That costs nothing
   in-circuit and lets an L1 check any of them. The test adds a batch of eight (one key twice, the deep key twice)
   and four batch forgeries: a consistent chain through a wrong intermediate root, a value moved between updates, a
   dropped update, and two updates reordered. All are refused. Measured on real `csmt.Tree` updates (50,000 keys,
   random keys, depth ~16-20):

   | updates | rows | prove | verify | proof | peak RSS |
   |---|---|---|---|---|---|
   | 1 | 26 | 5.6 s | 75 ms | 2.49 MB | — |
   | 4 | 112 | 5.9 s | 71 ms | 2.49 MB | — |
   | 32 | 1,128 | 7.3 s | 74 ms | 2.50 MB | 1.5 GB |
   | 130 (the busiest span) | 4,708 | 11.7 s | 155 ms | 2.50 MB | 2.6 GB |
   | 512 | 18,454 | 32 s | 90 ms | 2.64 MB | 7.2 GB |
   | 2,048 | 73,454 | 125 s | 242 ms | 2.82 MB | 25 GB |

   So the busiest measured span proves in ~12 s. The marginal cost at scale is ~61 ms per update, ~1.7 ms per
   compression row. That is about 5x the G1 planning figure of 0.33 ms per compression, and the gap is the next thing
   to cut. The path component is ~200 columns wide (message, state, byte splits for the digest XOR), and the rounds
   components run at log + 1..3. Memory, ~340 KB per row at 2,048, caps a single proof well before span sizes do. A
   span larger than ~500 updates should be split or the trace narrowed first.

   **Inserts and deletes (2026-10-20).** A compressed tree changes shape on both: an insert can split a neighbour's
   leaf into a chain, and a delete can collapse a lone neighbour upward. Soundness is by INDUCTION ON CANONICAL TREES.
   The first old root is L1's, and every op maps a canonical tree to the canonical tree of the new key set. The only
   freedom a prover has is the shape it claims, so each shape choice is pinned (the argument is at the top of
   `native/stwo_settle/src/blake/path.rs`):

   | op | old -> new at the key's walk | what pins it |
   |---|---|---|
   | UPDATE | leaf(k, vh_old) -> leaf(k, vh_new), same siblings | the old root |
   | INSERT_EMPTY | EMPTY at d -> leaf(k) | the old root (no hash is 32 zero bytes); an EMPTY start is constrained zero |
   | INSERT_SPLIT | leaf(k2) at da -> leaf(k) at db, EMPTY siblings between, leaf(k2) at db-1 | db-1 = the first bit where k and k2 differ (checked natively; k2 is public in this prototype) |
   | DELETE_EMPTY | leaf(k) at d -> EMPTY, sibling at d-1 internal | the sibling OPENED as node(l, r) by one compression: a leaf cannot be opened as a node |
   | DELETE_COLLAPSE | INSERT_SPLIT backwards | the sibling at da-1 is NONZERO (in-circuit): stopping beside an EMPTY is non-canonical |

   The layout puts two rows per depth, slot B on the deep side and slot A on the shallow side. Non-adjacent links
   (the split sibling, the opening) are LogUp tuples that one row emits +1 and another -1, so they cancel only when
   they agree. The test now drives a nine-write batch that holds all five ops from real `csmt.Tree` writes, plus the
   empty tree gaining two keys and losing both (every op at depth 0). It also tests a DISHONEST PROVER: six witnesses,
   each breaking one shape rule while every hash chain stays consistent, each on a single write so no root chain can
   catch it. Each is refused in-circuit (the prover's constraint check or the LogUp sum), and each has an honest
   control that verifies. Cost: an insert or delete is one write's rows plus one opening compression; the 9-write
   batch proves in 6.2 s.

   **Open in this component:**
   1. The keys are public here. In the settlement circuit they come from the records component by lookup, so the
      split depth's bit check (k and k2 agree down to db-1 and differ there) moves in-circuit. It needs a byte-to-bit
      table (2^11 rows) and the leaf's key bytes, which are already range-checked.
   2. The shape (op and depths per write) is public, so the preprocessed commitment is per statement, and the
      verifier recomputes it (~70 ms of the verify time). A fixed-shape circuit would let L1 pin one key. That is a
      later choice, which the frozen statement does not depend on.
   3. The VM hash's BIG-ENDIAN encoding (`zkvm2._absorb`: `h.to_bytes(32, "big")`, mirrored in `static/blake2s.js`,
      `nadodapp.js`, `dex.js` and the games) costs nothing in-circuit. A Blake-consuming row already splits every
      message and digest limb into range-checked bytes (path.rs sections 2 and 3), and big-endian is a different
      linear recombination of the same bytes. Checked while scoping the VM component, so the frozen encoding stays.
   4. A refusal by the prover's own consistency check (`ConstraintsNotSatisfied`) shows the constraint is violated.
      A prover that skips the check is caught by FRI, which this test does not exercise separately.
3. The VM step component for `zkvm2` (the CPU row, the storage and io buses by lookup, the BLAKE2s accumulator).

   **v1 done (2026-10-27): the execution of a list of calls, against a PUBLIC io log** (`native/stwo_settle`
   `src/blake/vm_air.rs`; the reference interpreter is `src/vm.rs`). The proof says that each call, run on zkvm2 with
   its method, args, CTX and ACTX values, produces exactly the stated io log and ends in RET after the stated number
   of steps. The values the VM reads from outside (SLOAD, BHASH, BEACON, ABAL) are the io log's own. That is the
   interface the storage and records components will consume by lookup, and here it is public, as the gen-28 settle
   proof's `cid_io` was. The soundness argument is at the top of `vm_air.rs`. In outline:
   - **One row per executed instruction.** The machine state (call, clk, pc, program, io count, r0..r7, the hash
     accumulator) is chained by LogUp rather than by adjacent rows. Each row consumes its state and produces the next.
     The verifier produces each call's start state and consumes its END tuple, which only a RET row emits. So a call's
     rows form a single path: a branch would need some state produced twice, and a cycle would need clk to wrap
     modulo p. Row order is free, so there are no offset masks.
   - **The tables the rows look up:**
     - the programs and the calls' data (CTX, ACTX and args), as preprocessed columns the verifier recomputes from the
       statement, as `path.rs`'s selectors;
     - a 16-bit range table;
     - upstream's BLAKE2s components, one compression per HABS row.
   - **Words are 16 limbs of 16 bits,** each range-checked where a row introduces it, so the limb equations hold over
     the integers:
     - ADD, SUB, EQ, LT and DIVMOD's `rem < rs` share one adder with a carry per limb;
     - MUL and DIVMOD use a byte convolution with 16-bit carries;
     - a word is zero iff its limbs sum to zero.

     Every constraint is degree 3 or less.

   `tests/test_a_stwo_proof_of_contract_execution_proves_its_io_log_and_refuses_forgeries.py` drives it on two sets
   of calls:
   - **Real calls:** 79 successful zkvm2 runs (17,034 steps) recorded while four gen-29 contract tests play
     tictactoe, bet, pets, dex and reserve.
   - **Synthetic calls,** covering what no game flow reaches: all 34 opcodes (NOP, RANGE, BEACON, AMINT, ABAL and
     ARENOUNCE appear in no game), each arithmetic op on the word's edges, and 33 random programs, with every result
     SSTOREd so the io log carries it.

   Results:
   - **The Rust reference agrees with zkvm2 on every call.**
   - **Every forged statement is refused:** 184 on the real set and 4,467 on the synthetic one, covering every io
     entry's value, key and kind; dropped, added and swapped entries; args; CTX and ACTX; the step count; the code;
     and calls swapped or dropped.
   - **Five dishonest provers are refused:**
     - a MUL off by one;
     - a taken JNZ falling through;
     - a stray register write;
     - a HABS state that is not the digest;
     - a flipped LT.
   - **The free-cell probe** perturbs every cell of sampled rows of each opcode, 674,000 perturbations in all. None
     that the row's constraints and lookups accept changes the row's state, io or table tuples. The cells that are
     free are exactly the ones that row never reads, such as a MUL byte on an ADD row, or an inverse when the tested
     word is zero.
   - **The test catches a broken circuit.** With MUL's operand binding deleted, `MUL:ab` shows up as a new free class
     and the test fails.

   Measured on this host (12 threads), node config (128 bits):

   | calls | steps | trace rows | prove | verify | proof | peak RSS |
   |---|---|---|---|---|---|---|
   | 3 (tictactoe) | 139 | 256 | 6.5 s | 75 ms | 1.11 MB | — |
   | 3 (synthetic, the edge program) | 2,343 | 4,096 | 6.2 s | 72 ms | 1.12 MB | — |
   | 79 (real) | 17,034 | 32,768 | 12.4-12.8 s | 100-112 ms | 1.11 MB | 3.3 GB |

   Most of the fixed ~6 s is the BLAKE2s XOR tables and the 2^16 range table, which every proof carries. A CPU row is
   881 columns wide, plus 164 interaction columns (secure-field, from 328 lookups). MUL, DIVMOD and HABS keep their operand bytes and compression in
   every row; moving them to their own components is the obvious cut when traces grow.

   **Open in this component:**
   1. The io log is public. Next, SLOAD and SSTORE go to the storage component (the path updates of step 2) by
      lookup, and PAY and the asset ops go to the records component.
   2. The code is public here, so the verifier is handed the programs. In the settlement statement they come from the
      pre-state: each contract's code leaf, authenticated against the pre root.
   3. The calls are public here. Next they are bound to L1's calls fold (2.3): the call leaf's contract, method,
      caller, args, value, asset, cursor and timestamp against the CTX, ACTX and arg tables.
   4. A REVERTING call cannot be proven yet. Its statement has to prove the failing condition (a REQUIRE on zero, a
      zero divisor, the gas limit, a pc off the end, an ARG out of range, an asset overspend), or a prover could claim
      a revert to drop a call's effects. Until then, a span with a reverted call cannot settle by proof.
   5. Not checked here, by design: BHASH and BEACON values (L1's chain reads), SLOAD values (the storage component),
      and ABAL values and asset overspends (the records half).
   6. As for the tree component, a dishonest witness is refused by the prover's own constraint check here. FRI
      catching a prover that skips that check is not exercised separately.
4. The records ops of 2.2 point 3 as a component, and the forgery suite of 2.4 against the prototype verifier.
