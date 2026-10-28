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
   4. ~~A REVERTING call cannot be proven yet.~~ Done 2026-10-27 (section 5): every one of zkvm2's 13 revert paths has
      a row that proves it.
   5. Not checked here, by design: BHASH and BEACON values (L1's chain reads), SLOAD values (the storage component),
      and ABAL values and asset overspends (the records half).
   6. As for the tree component, a dishonest witness is refused by the prover's own constraint check here. FRI
      catching a prover that skips that check is not exercised separately.
4. The records ops of 2.2 point 3 as a component, and the forgery suite of 2.4 against the prototype verifier.

## 5. The span settlement: a stateless replay with a Stwo VM proof (2026-10-27)

`execnode/settle_b2.py`, with `execnode/block_apply.py` and `execnode/csmt_partial.py`. This replaces the plan of 2.1,
where storage, records and the calls fold would each be bound inside the circuit, with a smaller and safer split:

- **The Stwo proof covers only contract execution**, the one part of a span that is expensive to redo: every call ran on
  zkvm2 and produced exactly its io log in its step count (section 4 step 3, `vm_air.rs`). A call may run up to 131,070
  steps; everything else a span does is a few dictionary updates.
- **Everything else is replayed by the verifier, through the exec node's own code.** The block dispatch moved out of
  `execnode/execnode.py` into `execnode/block_apply.py` unchanged, and the exec node and the verifier both call it. The
  verifier runs it on a `WitnessState`: an `ExecState` whose maps hold only the entries the span touched (the
  OPENINGS), each authenticated by a compressed-tree proof against a half of the pre root. A second implementation of
  the transition is how a prover and a chain come to disagree (CLAUDE.md: re-deriving is a second implementation, with
  its own bugs), so there is none.
- **A contract call does not run the VM in the replay.** The oracle takes the call's io log and step count from the
  witness and checks every io entry the VM reads against the replayed state: SLOAD values, ABAL values and asset
  overspends, BHASH and BEACON values against what L1 itself says the call could read at that height. It applies the
  SSTOREs, and adds the call to the VM statement. The code, args and context in that statement are the replay's own
  (the code from the authenticated code leaf, the args from the block), never the prover's. The statement is then
  checked against the one Stwo proof.
- **The post root** is the pre root with the replay's net leaf changes applied to a partial tree (`csmt_partial`): the
  paths the proofs reveal, every other subtree an opaque hash. A delete that collapses a sibling leaf needs that
  sibling's preimage, which the prover supplies and the verifier hashes.
- **Missing a witness entry is never a skip.** Reading an entry that is not opened raises `Unprovable`, a BaseException,
  so no `except Exception` in the transition can turn "the witness lacks a key" into "the transaction was skipped", which
  would settle a root the chain never had. The absent marker raises the same way if it ever reaches the transition as a
  value. It did once during development, as a TypeError the transition turned into two skipped calls. The run count
  and the root caught it, and the marker now fails loudly.
- **The prover is the same replay.** It applies the span to a copy of the full state (recording each VM run through a
  `trace` hook on `runtimes._ZkVM.run`), replays on a WitnessState whose source is the real pre-state (which records
  exactly the openings), proves the VM statement, and runs the verifier on its own bundle before returning it. A span the
  verifier would refuse is found unprovable before anything is submitted.

The cost of the split is that the verifier does work linear in the span (the replay) and the witness travels with the
proof. Both are small next to the VM proof: on the span below the witness is 57 KB of JSON and the replay takes ~0.1 s.
The tree circuit of step 2 is not used here. It is the way to a constant-size settlement when that matters, and nothing
in this format stops a later version from proving the tree updates instead of replaying them.

**Measured** on a 239-block span played through the real transition
(`tests/test_a_stwo_settlement_of_a_span_replays_the_exec_transition_and_refuses_forgeries.py`):
- the span holds a tictactoe game to a win and its payout, a dice bet bound to an epoch beacon and settled from it,
  RANDAO reveals, six asset ops on an asset created before the span, an emit, a bridge withdrawal, the L1 claim that
  garbage-collects an older one, a deploy, transfer_contract and lock, the dividend accrual across an epoch boundary and
  a collect_dividend;
- 9 VM runs, 1,251 steps, 39 openings. Prove 6.8 s, verify 0.11 s, VM proof 1.18 MB, witness 57 KB;
- the verifier lands on exactly the exec node's post root;
- refused, each for its own reason: an opening's value; an opening claimed absent; an opening dropped; a slot; the
  contract code; a tree proof; the pre halves swapped; an SLOAD value; an SSTORE value (the Stwo proof); a step count
  (the Stwo proof); a VM run dropped or added; the VM proof corrupted, or another span's; a BEACON value the chain does
  not hold; a call's argument changed in the block; a transaction removed from a block; the claimed post root;
- the partial tree lands on `csmt.Tree`'s root for 400 random write batches, including inserts beside deep shared
  prefixes and collapsing deletes, and refuses an opening that does not hash to its node.

**What a span cannot carry yet** (`Unprovable`, named in the message; such a span settles by the quorum, as every span
does today):
1. ~~A reverting call.~~ **Proven since 2026-10-27**, see "Reverting calls" below.
2. **Below `EXEC_ADDR_ROOT_HEIGHT`, a payout to an address registered before the span.** A PAY resolves its payee
   digest through `zk_addrs`, and a payee the registry lacks makes the chain revert the call, so the registry decides
   outcomes. No root committed it, and a prover-supplied preimage would have let a proof pay where the chain did not.
   From the gate (the first live gen-29 gate, exec cursor) every entry is a record (`exec_root_b2.T_ADDR`, positioned
   by the digest, valued by the address). The replay then reads the registry like any other ledger, and a payout to an
   address registered long before the span proves (test section 5). A span crossing the gate is unprovable: the root at
   the gate inserts the whole registry, which no witness carries, and the verifier refuses it outright rather than
   compute a root without that insert.
3. **Creating an asset.** `asset_create` refuses an existing id, and an asset's leaf key includes its metadata digest,
   so no single leaf shows that an id is absent.
4. **The shielded pools, private calls, deliveries INTO this namespace, non-integer storage (KVX).** Their state is
   committed as digests or lists, not one leaf per entry.
5. **A span crossing `EXEC_CARRY_ROOT_HEIGHT`.** The gate's first root inserts the dividend carry record, which no
   witness opens. L1 also refuses a span starting below the gate, since it has no carry of its own (see "The dividend
   carry in the exec root" below).

**One encoding per proof (2026-10-27).** Stwo's FRI last layer carries a size field beside its coefficients that the
transcript does not cover, so a proof had more than one byte encoding. `native/stwo_settle` refuses anything but the
canonical field. `native/stwo_js` maps every encoding to the canonical one where its verifier already treated them
alike, and refuses the rest, which it always refused. Old and new libraries were measured on the same encodings with the
same verdicts, so this is not a consensus change.

The test build helpers had a related problem. `tests/_stwo_js_build.py` and `tests/_stwo_settle_build.py` copy the crate
and build it in a shared target dir. Cargo judged freshness by the PREVIOUS copy's paths and mtimes, so it could link
another tree's library: a test of the live checkout's verifier ran a worktree's newer one. Each build now stamps a
sha256 of its sources and drops the crate's fingerprints when the stamp changes.

**Reverting calls (2026-10-27).** A revert has to be proven, or a prover could claim one to drop a call's effects, and
its step count too, since a reverted call's steps count against the block budget. zkvm2 reverts in 13 ways
(`zkvm2.REVERT_KINDS`, which records the kind in the run's meter for the prover). A call the statement says reverts
ends in a REVERT row (`vm_air.rs` module comment):
- REQUIRE, DIVMOD, DIVMODW and ASEL on a zero operand, through the zero test;
- NOTB, RANGE and ARG outside their small range: either the high limbs' sum has an inverse, or the low limb minus the
  bound is range-checked;
- a pc past the method's end (equal to the program's length, from the table: jumps stay inside, so only a fall-through
  gets there);
- the step budget (clk is GAS_LIMIT).

The row emits END_REVERT, carrying the kind and the gas, in place of a next state. Four kinds depend on state the
circuit does not hold: an asset PAY or ABURN beyond the holding, and a BHASH or BEACON the chain does not hold yet. For
those the row emits the step's io entry, and the oracle accepts the revert only if that entry fails exactly as zkvm2
fails it. The replay discards a reverted call's writes, refunds its escrow and charges its steps, through the exec node's
own code.

Measured (`tests/test_a_stwo_proof_of_contract_execution_proves_its_io_log_and_refuses_forgeries.py` section 6):
- one reverting call per kind, the range kinds from both sides, proven and verified;
- 103 forged statements refused, 52 of them about a revert: its kind, a return claimed, its step count, its io entry;
- ten dishonest provers that claim a revert where the instruction does not fail, one per kind the circuit judges, all
  refused;
- the free-cell probe on revert rows: 112,500 perturbations, none harmful;
- an out-of-gas call (131,070 steps) proves in 36.7 s and verifies in 0.22 s, at 19 GB peak memory. The block step
  budget bounds how many of those a block holds.

In the span test a tictactoe move out of turn reverts inside the span. A span whose only call reverts lands on the exec
node's root with the call value back in its sender's balance. The oracle refuses a PAY, ABURN, BHASH or BEACON revert
whose entry does not fail.

**The shadow run (`tools/settle_b2_shadow.py`, 2026-10-27): G8's two weeks of off-chain proofs.** It proves every
span between two of the exec node's settled snapshots (`exec_state.json~stash~<ns>~<cursor>.json`), verifies each proof
as L1 would, and compares the verified root with the exec node's own root at the span's end. It only reads the
snapshots and GETs blocks and accrual inputs, and it writes nothing but its results file. One JSON line per span:
proven, unprovable (and why), refused or mismatch (each a bug), skipped.

The first run, against the live chain (exec cursors 4920 to 5220):
- **Two spans proven** on exactly the exec node's root. Each was 60 blocks with dividend accrual and no contract call:
  the live chain is quiet. Prove 0.4 s, verify 5 ms, 49 KB witness.
- **Three spans skipped**, which exposed an exec-node bug: a stash did not always hold the state of its own label. A
  quorum settle attests the latest epoch-boundary pair, but the stash serialized the LIVE state after the submit's
  await. 2 of the 6 stashes on disk were at another cursor (4980 held 4981, 5220 held 5223). Both a joiner, which
  verifies a stash against its pair, and this prover depend on that match. Fixed in `execnode/execnode.py`:
  `_record_boundary` serializes the state in the same step that records the boundary root, and `_stash_payload` stashes
  only a payload at the attested pair, never a mismatched one
  (`tests/test_a_settle_stash_hashes_to_its_own_cursor_and_root.py`).

**The node's verifier builds on stable Rust (2026-10-27).** A node builds every crate with stable cargo. The settlement
crate was nightly-only because its verifier recomputed a per-statement preprocessed commitment (the TAB table: programs,
call data), which takes Stwo's prover machinery. The table is now not a column at all:
- the proof states each table row's multiplicity;
- the transcript fixes them before any lookup challenge is drawn;
- the verifier adds `m / (a - row)` for each row as a public LogUp term. With the multiplicities fixed first, the sum
  vanishes only if every looked-up tuple is a table row.

The remaining preprocessed columns, the XOR tables and the range column, are constant, so their root is pinned
(`vm_air::PREPROCESSED_ROOT`). The prover, the trace generation and the old path prototype sit behind a `prover` feature
(nightly). The default build is the verifier plus a C entry point (`ffi.rs`, bound by
`execnode/stark/stwo_settle_native.py`). `ops/self_update` builds it on every node as an OPTIONAL crate: built and
reported, required by nothing until the settlement gate.

Measured: all VM and span tests pass on the new circuit, and four mutations of a proof's multiplicities are refused.
Verify is faster without the recomputed commitment (79 real calls: 124 to 53 ms; the 239-block span: 0.11 to 0.03 s).
`tests/test_the_stwo_settle_verifier_builds_on_stable_without_the_prover.py` covers the node's path:
- the library builds on stable, and no package in that build has Stwo's prover feature on;
- the pinned root is the one the prover recomputes;
- an honest proof verifies through ctypes, and forged statements and proof bytes are refused;
- `settle_b2.verify_span` with no prover binary verifies a real span on the exec node's root.

**G8's L1 side, built DORMANT (2026-10-28).** `protocol.STWO_SETTLE_HEIGHT = (1 << 62) if CHAIN_GENERATION == 29 else 1`.
Below it nothing the live chain does changes (both replays of blocks 0..10533 IDENTICAL); from it:

- **The settle field.** A `settle` may carry `stwo`: the DA commitment of the bundle (witness ~50 KB plus, when the span
  has calls, a ~1.2 MB VM proof, ~2.3 MiB as JSON — far over the 64 KiB transaction cap, so it always rides DA, k-of-n,
  like the deleted Goldilocks `proof_da`). `proof` / `proof_da` stay refused at every height. Below the gate `stwo` is
  IGNORED, not refused: a settle's `data` keys were never constrained, so a settle carrying `stwo` validated before G8
  existed, and refusing it on shipping would tighten validation at no agreed height (an updated node refusing what an
  older one accepts splits the update wave — CLAUDE.md rule 3). Ignored, it validates and applies bare, as before; the
  rule changes only at STWO_SETTLE_HEIGHT, which the operator sets at the fleet's adoption block.
- **PREREQUISITE before setting the gate — the dividend carry, now committed in the exec root (2026-10-28).** As first
  built, L1 read the span start's carry from the `dc` of the last epoch-boundary exec summary, which
  `loops/core_loop._accrual_effects` writes only when that boundary block's records are derivable, reading the previous
  boundary's `dc` as its carry-in. That chain BROKE on the live chain: see "The dividend carry in the exec root" below.
  The carry is now a record of the exec root from `protocol.EXEC_CARRY_ROOT_HEIGHT`, which must be at or below
  STWO_SETTLE_HEIGHT.
- **Validation** (`ops/transaction_ops._stwo_settle_check`), the checks of the deleted branch that are not
  Goldilocks-specific: the default namespace only; the span starts at or above `EXEC_CARRY_ROOT_HEIGHT` (structural, a
  function of the justified tip alone, so it binds at every depth); the span EXTENDS the justified settled tip exactly (the replay starts
  from `latest_settled`, never from a pre-state the prover names; the first settlement of a namespace is by quorum);
  non-empty, at most `SETTLE_PROOF_MAX_SPAN` blocks, wholly below the carrying block; the blocks are L1's own
  (`block_ops.get_block_number`), never the transaction's; `settle_b2.verify_span` with the Chain L1 derives itself; the
  proven post root must be the settle's `state_root`. A blob not in DA, a span block or block hash this node does not hold,
  a missing native verifier or an out-of-memory DEFER the block (`ProofUnavailable`), never reject it. A block more than
  `FINALITY_DEPTH` below the known tip is judged on structure only (`SETTLE_PROOF_DEPTH_GATED`). The verdict is memoised
  on (commitment, span, root, the block hash at the cursor, the rules) — the bytes and the chain context, never the
  claims — so a pooled settle is verified once; node-local outcomes are never memoised. It runs in the validating thread
  (mempool admission is already `asyncio.to_thread`), single-flight per bundle and one at a time process-wide.
- **Apply** (`ops/account_ops`, the settle branch): a settle carrying `stwo` from the gate records
  `settlement_proof_put`; revert `settlement_proof_del` (a refcount: the exact inverse). `settlement_justified` already
  honours the marker, so the root is justified with no quorum.
- **The Chain from L1's state** (`ops/settle_chain.py`), each rule the closed form of the exec node's bookkeeping for a
  from-genesis node: BHASH(k) in block h is readable iff `max(0, h - 20000) <= k <= h - 1` (the ring keeps the newest
  20,000 entries; block 0 is recorded); BEACON(e) in block h iff `lo <= e <= F` with `F = (h - 1) // 60`, `lo = 2`, or
  `F - 4000` once that is positive, and every epoch of `[lo, e]` final at F under `ExecState.exec_beacon_at` with
  `kv_ops.reveals_for_epoch` (a reveal for epoch x lands only in epoch x - 1, so L1's set is complete); accrual of E =
  `(dividend_inflow_get(E), the committed epoch_weights_get(E), else weights_at_epoch(E))` — what `/get_open_weights`
  serves the exec node. The carry at the span's start is NOT an L1 input: from `EXEC_CARRY_ROOT_HEIGHT` it is the pre
  root's record (`Chain.div_carry` is None), and below it `l1_chain` refuses the span. (As first built it was the `dc`
  of the exec summary at block `(sc // 60) * 60`; see below for why that is gone.) **Equality measured** on the live
  chain, blocks 0..10533 (an L1 replay kept in a throwaway HOME against a from-genesis exec replay of the same blocks):
  every BHASH window and value, every BEACON epoch from -1 to two past the final one at every block (961,410 reads), the
  carry at every cursor and all 175 epochs' accrual inputs: zero differences, and the check reports a shifted window, a
  shifted beacon height or a shifted carry.
- **The exec node** (`execnode._stwo_settle_bundle`, in `maybe_settle` after the holds): from the gate it proves the span
  from the justified tip to its newest unattested epoch boundary, from the stash at the tip, publishes the bundle to its
  DA store and submits the settle with `stwo` through the existing publish hold, pending record and resubmit path. With
  no `vm_settle` prover (`$NADO_STWO_VM_SETTLE`, default `~/.cache/nado-stwo-settle-target/release/vm_settle`), a span
  with no contract call still proves; a span with calls, an unprovable span, a timeout or a DA failure settles bare.
- **The shadow run checks the derivation too**: every span gains `chain_eq` (L1's Chain from `GET /settle_chain_inputs`
  against `reference_chain`), with `chain_diff` naming any difference.

**The dividend carry in the exec root (`protocol.EXEC_CARRY_ROOT_HEIGHT`, 2026-10-28).** The carry chain in the exec
summaries broke on betanet-10, exactly as feared, and was then unrecoverable.

*Measured root cause.* A snapshot of the relay's state at 12000 (`/get_snapshot_chunk`, GETs only) holds 960 `execsum:`
rows (11041..12000, the retention window `EXEC_SUMMARY_RETENTION`). Every boundary row is `{"inert":1,"calls":{},"rd":0}`,
with no `dc`. A scan of every boundary block 60..12360 finds exactly one with a transaction `block_records_effects`
cannot derive: block 10860, a `collect_dividend` blob (an hourly auto-collect that happened to land on a boundary). A
from-genesis replay of the live blocks through `tools/replay_chain.py` (throwaway HOME) reproduces it: `dc` at every
boundary up to 10800 (`{"rd":1,"dc":16}` at 10800), then `{"inert":0,"rd":0}` at 10860 and `{"inert":1,"rd":0}`, no `dc`,
at 10920. Every later boundary takes `_accrual_effects`' early return (`prev.get("dc") is None`), which logs nothing,
which is why the node logs show no accrual failure. Not a snapshot bootstrap (the relay applied every block from
genesis; no purge or re-anchor since 05:59 on 2026-10-27) and not a swallowed exception. The fleet-wide probe of 60..12240
found no `dc` anywhere because summaries below the retention window are pruned and everything above 10860 has none. The
earlier "all 175 boundaries carry `dc`" was true of blocks 0..10533, the range the G8 replay covered.

*The fix.* From the gate's exec cursor the exec state's `div_carry` is a record of the exec root: the `T_COUNTER` record
named `"div_carry"` (`exec_root_b2.CARRY_COUNTER`), valued by the exact integer, absent when zero. It is a new name in the
counter family, not a new tag, and `COUNTERS` stays frozen: the record enters `records_projection` only from the gate,
so every root before it is unchanged (both replays of 0..10533 identical). Then:
- `settle_b2.WitnessState.div_carry` is the witness's counter from the gate: the accrual opens it against the pre root (a
  forged value fails the leaf check, a dropped opening is Unprovable, a carry claimed absent is refused), and the new
  value is a leaf change the post root carries. Below the gate it is `Chain.div_carry`, which only the exec node's own
  bookkeeping supplies (the prover, the shadow run, tests).
- A span crossing the gate is unprovable and refused by the verifier. The gate's first root inserts the record, which no
  witness opens.
- `ops/settle_chain`: L1 supplies no carry (`Chain.div_carry` is None) and `l1_chain` refuses a span starting below the
  gate (`carry_refusal`, a function of the start cursor alone). The exec-summary path is deleted rather than kept for
  spans below the gate. On the live chain it could never succeed again, since every boundary after 10860 lacks `dc` and
  no boundary can regain one. On a reroll the gate is 1. Keeping it would leave a consensus path that is dead
  everywhere. `/settle_chain_inputs` keeps `div_carry` (always null) and sets `refused` below the gate. The shadow run's
  `chain_eq` still compares every read and accrual there.
- `execnode._stwo_settle_bundle` settles bare when the justified tip is below the gate.
- **A memoised root must move at the gate.** The exec node caches its root on mutations (`ExecState._touch`), and a
  block that mutates nothing at the gate would keep the previous cursor's root while a cold projection (a restart, a
  stash check, the prover) commits the record. `block_apply.close` touches the state at `exec_root_b2.projection_gate_at`.
  (`EXEC_ADDR_ROOT_HEIGHT` had the same shape: measured, the memoised root at cursors 8500..8519 lacked the registry that a
  cold projection commits, until the accrual at 8520 touched the state. Settled boundary roots were unaffected. It is
  already behind the tip and left as it is, so no replay moves; SCHEDULED_CLEANUPS.md.)
- Rollback needs nothing new: the exec root is recomputed from state, and `div_carry` was always part of the exec state
  and its snapshots.

The `dc` written into exec summaries is now read by nothing. It stays until the next reroll because `execsum:` rows are
part of the snapshot `state_digest`, so changing what they hold would split snapshot identity across an update wave
(SCHEDULED_CLEANUPS.md).

Measured: `tests/test_a_stwo_settlement_of_a_span_replays_the_exec_transition_and_refuses_forgeries.py` section 7 (both
rule sets, the forgeries, the crossing span, the memoised root), `tests/test_a_stwo_settle_lands_proven_from_its_gate_and_l1_refuses_forged_spans.py`
(L1 holds no exec summary at all; both spans land proven; a forged or dropped carry opening and a span below the gate are
refused), and a live-data shadow check (the commit message): a real span of the live chain, replayed from genesis with
the gate forced low in the replay only, proves and verifies from the committed carry.

**What the operator does to turn it on.**
1. Install the shadow job (`deploy/units/nado-settle-shadow.service`, needs the explicit yes) and let it run two weeks:
   every span `proven` and `chain_eq: true`, nothing `refused`, `mismatch` or `error`.
2. Confirm every fleet node reports `native/stwo_settle` built (it is an optional crate; a node without it DEFERS blocks
   carrying a Stwo settle until they are deep) and that `EXEC_CARRY_ROOT_HEIGHT` has fired (the exec roots of every exec
   node agree past it: the settle quorum keeps settling) and lies at or below the height chosen.
3. Measure the cadence, pick a height the `/update` wave reaches first (CLAUDE.md rule 3), set `STWO_SETTLE_HEIGHT` to it
   (keyed `if CHAIN_GENERATION == 29`), push, and confirm `status_pool` uniform before it fires. Exec nodes that should
   prove need the `vm_settle` binary built with the nightly (`tests/_stwo_settle_build.py`), and the RAM: an out-of-gas
   call proves at ~19 GB.
4. After the gate: proofs land (`SETTLE-WITH-STWO-PROOF` in the exec log, `kv_ops.settlement_proven`), and the L1 verify
   time is measured on the slowest fleet node (the 9.5 exit test).
