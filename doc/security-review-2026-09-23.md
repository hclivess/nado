# Security review — contracts, execution layer, settlement, shielded pool, STARK (2026-09-23)

Requested by the operator ("review all contracts", then "review our stark implementation and zkvm").
Method: eleven independent read-only reviews, one per subsystem, each briefed with the machine model and the
bug classes this codebase has already paid for; every finding that could be reproduced without a long prove
was then reproduced by hand on an isolated in-memory `ExecState` (never the live database). "Reproduced"
below means exactly that. "Traced" means the reviewer's instruction-level trace was spot-checked at the
lines cited but not executed. Nothing was changed, committed or run against the live node beyond read-only
GETs. Live measurements are as of exec cursor ~201,400 / L1 height ~201,500.

The one-paragraph verdict: the contracts are visibly post-audit — every historically fixed bug class holds
and is pinned — but three cross-boundary defects (a value the layer escrows in one currency and the
contract pays in another; a storage key whose id half was never bounded outside `open`; a chain clock the
OTC contract compares against foreign wall-clock deadlines) are exploitable today. The proof system's
soundness holds where it was reviewed, but the join-split "zero-knowledge" proof publishes the spending
key and every amount, the shielded exit path accepts an empty proof, and the settlement binding lets a
bonded settler settle a root honest nodes do not hold.

---

## 1. Contracts (execnode/games, 30 modules, 27 deployed)

### Critical — reproduced

**C1. An asset-denominated call value drains native escrow (every value-taking contract; 25 of 27).**
`execnode/state.py:1183-1216`: a `call` blob may carry `asset`; the layer escrows that asset into the
contract's asset ledger, then hands the contract `value` through `CTX_VALUE` with no currency tag. Every
game reads `value`, stores it, and later `PAY`s native NADO from the contract's shared native holding.
Reproduced: mint a token (`asset_create`, supply 1e9), `coinflip.open(2)` with `value=500, asset=<token>`,
`cancel(2)` — received 500 native NADO that another player had escrowed. Not yet used on mainnet (no contract
holds a foreign asset). Only `dex`, `otc`, `reserve` read `ACTX` and they compare it; every native-only
method in them requires `in_asset() == 0`, so an opt-in gate breaks nothing.
Fix: exec-layer, before the escrow at `state.py:1201` — refuse asset value unless the method's code reads
`ACTX` (or a deploy flag). This is an exec-state-transition rule: gate it on an exec cursor with the
`if CHAIN_GENERATION == 25 else 1` branch and confirm no historical asset-valued call into a non-ACTX
contract exists before choosing the cursor. See also §2 F1.

**C2. Thirteen contracts never bound the id to 32 bits; a large id addresses another field's storage.**
A slot is `field·2^32 + id` (`zkvmasm.py:86-88`, no mask). In the five banked games (`dice`, `roulette`,
`slots`, `mines`, `blackjack`) only `_lib.open_table` checks `id < 2^32`; `fund`, `bet`, `spin`, `deal`,
`settle`, `reclaim`, `pick`, `resolve`, `cashout`, `reap`, `hit`, `stand`, `draw`, `reveal`, `close` do not.
Reproduced on dice: as the player, `fund(9·2^32 + 88)[38]` moved my own bet's settle height `gh[88]` from
102 to 140 (choose a winning height after the fact); as a stranger, `bet(7·2^32 + 88, 3, 50)[1]` set
`gd[88]`, after which the victim's `settle`/`reclaim` and the banker's `close` revert forever (`tc` stuck).
In the seven board games (`tictactoe`, `connect4`, `reversi`, `chess`, `stormhold`, `scrapline`, `hexholm`)
the gap is in `open` itself (`battleship` alone has the guard). Reproduced on tictactoe: a stranger's
`open(5·2^32 + 42)[1]` set `sd[42] = 1` on a live 2,000-raw game; `move`, `abort`, `resign` all revert,
pot stranded. `autogame.begin` has the same hole with no coins behind it. No aliased slot exists in live
storage today (the high field ids in `bet`, `hamster`, `autogame`, `faucet` are hash-derived keys by design).
Fix: the four-line bound from `open_table` at the top of every id-taking method in the thirteen contracts,
a test asserting every SSTORE in a call's io log stays inside the method's own field set, then in-place
`upgrade` of all thirteen (deployer key). For new code: a `slot` macro form that range-checks the key.

### High — traced, measurement verified

**C3. OTC BID timelocks are checked in a clock 39.7 h behind wall time.** `otc.py:188-195, 266-272` compare
`chain_clock(expn)` (= `GENESIS_TIMESTAMP + h·6`) with `expf`, a wall-clock foreign deadline (BTC
`nLockTime`, ETH/SOL deadline). Measured: lag 142,808 s at height 201,391, effective cadence 6.709 s, growing
~2.5 h/day. A BID maker posts `expf` that is already in the wall-clock past; the contract and the wallet's
guard (`dex.js:1509`, same clock) both approve; the taker locks NADO; the maker refunds the foreign leg at
once and claims the taker's NADO with the secret. ASKs are safe for the same reason, but wallet-default ASK
deadlines cannot complete. The contract cannot enforce this soundly with an unboundedly lagging `TIME`; the
taker's wallet must size its own L1 lock from `Date.now()` plus a cadence UPPER bound, and the in-circuit
check is advisory until `chain_clock` is re-anchored (gated consensus change).

**C4. A pet in a live battle can be sold or transferred.** `pets.py:259, 272, 282, 305` (transfer, list,
buy, accept_offer) never check the `EX` lock that `release` (`:428`) and `combine` (`:399`) do. A
two-account seller lists the losing pet mid-battle; the buyer pays; `resolve_battle` reassigns the pet to
the winner's owner. Fix: the same `EX` guard at the four sites.

**C5. Lifecycle and trust.** All 27 contracts report `upgradable: True`, none locked, deployer of every one
is the relay's own key (`state.py:1165, 1474-1477`); `/exec/contracts` omits the flag. `deployer`,
`upgradable`, `zk_addrs` are not in the exec root (`exec_root.py:94-160`), contrary to
`doc/exec-instructions.md:558`; bootstrap/repair adopt them from any peer on a root-only check
(`execnode.py:2843-2932`). A call whose `method` is not a string is debited then raises past the refund
closure (`state.py:1173, 1210, 1217`; `zkvm.py:210`); coins stay in the contract. Faucet `defund` allowance
is `DONATED − DEFUNDED` while `reward` never reduces `DONATED`, so it can take back others' donations by the
amount already paid out. Sovereign's single global ply counter is cheaply denied (~2e-6 NADO/block for 95 %).

### Medium

- Every banked game's horizon reclaim (`dice.reclaim`, `roulette.reclaim`, `slots.claim`, `mines.reap`,
  `blackjack.reap` phases 1/3/4) refunds a bet whose losing outcome was public for 18,000 blocks; nothing but
  the player settles, so a loser waits ~34 h and gets the stake back — a free option. The tests
  (`t_dice_reclaim`, `t_roulette_reclaim`, `t_blackjack_reap`) pin the refund as correct. Decide: forfeit to
  the pot on the player-must-act states, or make a non-player settler a hard requirement.
- OTC `bind(o, any-non-zero)` returns the taker's bond immediately and makes `release` impossible
  (`otc.py:341-360`); a taker locks a maker's foreign funds for two fees. Return the bond at settle/expire.
- DEX: no minimum seed liquidity (`dex.py:146-161`), first-provider share inflation against later joiners;
  `join` token side rounds in the joiner's favour (`:163`).
- Tic-tac-toe, connect-four, reversi anchor the abort deadline at `join` and `move` never refreshes it; a
  losing player aborts for a symmetric refund after ~34 min. Chess/stormhold refresh it correctly.
- Slots: a winning spin above ~3,518 NADO stake cannot settle (`pay = gs·m2/2`, quotient window 2^48,
  `slots.py:363`); blackjack cannot reveal a natural for stakes in [11,259, 18,765] NADO (`:139`). Losses
  settle. Lend/reserve: an unbounded duration/notice makes `repay`/`default`/`release` RANGE-revert forever
  (`lend.py:142`, `reserve.py:72`). Hamster parimutuel strands rounding dust (no sweep). Bet `bclaim` refunds
  the book on a tote auto-void, opposite to its comment (`bet.py:306-309`). Chess move log is unbounded.

### Sound
`coinflip`, `battleship`, `holdem` (commit/reveal binding, side pots, permissionless reclaim), `farkle`
(the three historic fixes hold and are pinned), `pool`, `hamster`'s book, `lend` and `reserve` otherwise,
`_lib.daily_anchor`, autogame's fairness fence and mists rule, pets' escrow and homestead accounting. Every
`pay` in all 30 modules traces to its own zeroed field; no order/pool/market/table can pay from another's
escrow except through C1/C2.

---

## 2. Execution layer and zkVM interpreter (execnode/zkvm.py, zkvmasm.py, zkpy.py, runtimes.py, state.py)

- **F1 = C1** (asset value). **F2 = C5's method-type strand**, reproduced: `method: ["bet"]` → `TypeError`
  at `zkvm.py:210`, before `run`'s `try`; `state.py:1705` catches it as "skip" with the escrow kept. Fix at
  three sites: type `method` at `state.py:1176`; wrap the run in a refund-on-any-exception; type `method` in
  L1 blob admission (`transaction_ops.py:1783`, a validation rule → height-gated).
- **F3 — the prover replays calls in a different context than the chain executed them.** `execnode.py`
  `_apply_block` applies every blob of block h, THEN sets `cursor = h`, `block_ts = chain_clock(h)`
  (`:2649-2652`). So every call in block h sees `CTX_CURSOR = h−1`, `CTX_TIME = chain_clock(h−1)`, and
  `BHASH(h)` unavailable. `calls_commit.block_calls` stamps each call `cursor = h` (`:91-115`) and
  `settlement_proofs._run_call` replays with it. An honest settle proof for any span containing a call that
  reads cursor/time therefore proves a transition the chain did not apply (root mismatch, cannot settle);
  197 sites in the games read them. Fix: stamp `h−1`/`chain_clock(h−1)` in `block_calls`, or set the context
  before the loop (a live semantic change → cursor-gated).
- **F4 — execution is unmetered.** Only `GAS_LIMIT` per call; no per-block budget; flat `MIN_TX_FEE`.
  Measured 0.5 µs/step bare, 3.9 µs/step hash loop, 1.45 ms fixed per call (dict rebuild in
  `runtimes.py:151-152`). One 1 MiB block of cheap calls ≈ 2 h of exec CPU. Fix: drop the per-call dict
  rebuild; deterministic per-block cumulative step budget in `apply_blob`.
- F5 registry (`zk_addrs`) is money-routing state outside the root, overwrite semantics, mutated before the
  run. F6 any string arg becomes a payable key (typo strands coins). F7 runtime name stored raw. F8
  constructor effects dropped. F9 self-pay not the no-op the VM assumes. F10 only JSON `false` locks.
  F11 DIVMOD accepts `b == 2^15` (docs say `<`; the AIR decomposes `b−1`, interpreter is right).
- Sound: opcode freeze and `validate_code`; LT-needs-RANGE static check cannot be evaded by control flow;
  every window reverts where the AIR would be unsatisfiable; revert is all-or-nothing; `total_pay` vs
  holding; `zkpy` allocator excludes the register-clobber class; determinism of every `run` input.

---

## 3. Settlement binding (settlement_sparse, records_bind, calls_commit, transaction_ops settle branch)

- **S1 — HIGH. A deploy/upgrade inside a proven span is invisible to L1's binding but moves the KV half.**
  `calls_commit.block_calls` commits only `op == "call"` blobs (`:104-116`); `deploy`/`upgrade` are in the
  records-inert allowlist (`:150`); the KV transition is derived from io `net_updates` only, so a code-leaf
  change never appears; L1's post-root check is against the tx's own claim (`transaction_ops.py:1999`).
  A bonded settler (B_MIN 10 NADO, fee 0) deploys/upgrades in-span and settles a self-consistent root honest
  nodes do not hold; every honest proof afterwards fails tip extension. Corollary: an honest prover cannot
  settle any span containing a deploy/upgrade. Fix touches `meta` → reroll-class.
  > **Coded 2026-09-23 behind `EXEC_ROOT_V2_HEIGHT` (live 2^62; block 1 at the reroll).** Code events ride
  > `block_calls` as leaves (`calls_commit.event_leaf`), the verifier replays them over the pinned pre-state
  > (`exec_state_bind.apply_event` / `event_updates`, the chain's admission rules in one function) and requires
  > the code+meta leaf updates FIRST in the transition; a deploy's constructor is a proven VM unit
  > (`vm_units`). Also closed under the same gate, found while doing it: the prover stamped every call with
  > `timestamp=0` while the chain ran it with `chain_clock(h)`, so any TIME-reading call proved a transition
  > the chain never applied. `tests/test_exec_root_v2.py` drives the same blocks through `_apply_block` and
  > through the prover and asserts the roots are equal — and unequal below the gate.
- **S2 — HIGH. Solvency is enforced only by the prover.** Escrow affordability and PAY over-pay live in
  `settlement_proofs._run_call` (`:120-126, 150-151`); the verifier folds records effects
  `(cur + delta) % P` with no non-negativity (`records_bind.py:427-440`). A prover that drops the check
  settles a balance of `P − v`. Monetisation blocked today because withdrawals need a non-derivable op
  (quorum path), but the tip is poisoned. Fix: refuse a negative running balance in `net_records_updates`
  (all pre-values there are authenticated) and a value-call whose sender pre-balance < value.
- S3 verification-cost amplification: the full STARK verify and an O(state) `sparse_root` over a
  PROVER-CHOSEN `pre_contracts` run before the cheap tip/span/summary checks (`:1934-1994` vs `:1998,
  :2082`); fee-exempt, 192 MiB bodies, memo keyed on bytes only. Reorder: tip, span, summaries first.
- S4 a DA-carried settle is fully verified but never records the proven marker (`account_ops.py:241` checks
  `"proof" in data`; DA settles carry `proof_da`).
- S5 a node-local exception in `verify_settlement_sparse` (incl. `MemoryError`) is memoised as a
  cryptographic refutation (`:483-484`, memo at `transaction_ops.py:1968`) — a resource-axis fork.
- S6 `recursion_authdepth.verify_level` trusts prover-supplied `fold_public`/`comp_public` (not on the live
  path). S7 exec-root coverage gap (= C5).
- Sound: cid_io re-derived (2026-07 fix holds), memo keyed on bytes (2026-08 fix holds), fold order/K/roots
  in the verifier-built schedule, io order bound by the AIR's permutation bus, contiguous summaries, reorg
  revert of attestations/markers/summaries, BHASH reads bounded below finality.

---

## 4. Shielded pool (joinsplit2, joinsplit_circuit, shielded*.py)

Live state: 0 notes ever created this generation, `pool_value` 0, escrow 0.0001123 NADO. So nothing has
leaked or been drained yet; every finding below is a property of the code.

- **Z1 — CRITICAL, reproduced. The join-split proof is not zero-knowledge.** `nsk`, `rho_in`, `v_in`,
  `v_out1`, `v_out2` are written into every trace row (`joinsplit2.py:119`, held constant `:321-324`); a
  constant column's LDE is the constant, and every FRI query opens all columns (`stark.py:573-592`). Proved
  one 4-query transfer: `nsk` appears 8 times in the openings, as do rho and all three amounts. Since
  deposits publish `(owner, rho, amount)` on L1, an observer holds a complete spend witness for every
  unspent note of that owner, permanently (`nsk` is derived once from the L1 key). Fix: a masked/blinded
  trace (random padding rows or a mask polynomial per witness column) — a circuit change.
- **Z2 — CRITICAL, reproduced. The transparent `shielded_transfer` op accepts an empty "stark" bundle and
  records an unbacked exit.** `shielded.py:240-242` routes any `proof.stark` to `verify_transfer`;
  `joinsplit_transfer.py:54-77` with neither join-split key falls to "output well-formedness only", which is
  trivially true for `[]`; `state.py:1575-1610` then records `unshield_withdrawals[nonce] = {addr, amount}`
  for `public_value = −X`. Reproduced: one blob, `pool_value → −1,000,000`, exit recorded. Cost: one fee.
  Fix: refuse a bundle without a join-split proof (fail closed), and bound `−pv` by `MAX_EXIT_VALUE` here too.
- **Z3 — CRITICAL by design.** The note commitment is one 64-bit field element (`alghash.py:56-77`,
  "~2^32 collision"); ~2^33 sponge evaluations find two openings of one leaf → unshield up to escrow with no
  victim. `alghash2` (256-bit) exists and is not used by the pool.
- Z4 HIGH: the field pool truncates past 4,096 leaves (`shielded_field.py:14, 30-61, 90-93`); every later
  note is a permanent lock, every later transfer burns its input. Z5 HIGH (privacy): the L1 sender signs the
  blob, the claim DM carries `sender`, deposits are public — no sender anonymity even after Z1. Z6 nullifier
  binds sender-chosen `rho`, no duplicate-commitment guard (griefing lock). Z7 delegated-prover endpoints
  that accept `nsk` are still routed (`execnode.py:4495-4580`). Z8 transcript does not absorb the boundary
  statement; `(fee, public_value)` bound only as a difference. Z9 `withdraw_addr` unvalidated on the field path.

---

## 5. STARK core protocol and FRI (stark.py, fri.py, fri_verify.py, recursive_verify.py, native/starkprove)

- **P0 — CRITICAL, premise verified by reading; forgery traced, not executed. The FRI sub-proof's domain
  size is never tied to the STARK's.** `stark.verify` hands `proof["fri"]` to `fri.verify(...,
  expected_blowup=2)` with no `N` (`stark.py:689`); `fri.verify` reads `N`, `offset`, `blowup` from the
  sub-dict and checks only power-of-two and the blowup (`fri.py:224-232`); nothing in `stark.py`,
  `fri.py` or `recursive_verify.py` compares them to the STARK's `N`/`OFF`. The spot-checks bind FRI
  layer-0 values at `idx mod (N/2)` with the STARK's `N` (`stark.py:802-905`). Declaring
  `proof["fri"]["N"] = 2N` proves "degree < N" for a length-2N vector whose first N points are the
  pointwise composition and whose second half is never read — choose the second half so the whole vector is
  genuinely low-degree, and every fold, final layer, grind and opening is honest for ANY trace. Any
  statement (any settle post-root, any shielded transfer, any exec io log) becomes provable at honest cost.
  Reachable on the live block-apply path through `verify_settlement_sparse` and `shielded.verify_transfer`.
  Fix: in `stark.verify` reject unless `proof["fri"]["N"] == N` and `["offset"] == OFF`; pass
  `expected_N`/`expected_offset` into `fri.verify`; the same pins in `fri_verify._canonical_public`
  against the STARK part. A verifier-side rejection ⇒ validation-rule change ⇒ height-gated.
- **P1 — HIGH, structural, verified by reading. Trace columns are never low-degree tested and there is no
  DEEP/out-of-domain phase.** Only the composition `cp` enters FRI (`stark.py:570`); `stark.py` contains no
  OOD sampling. A witness column with no boundary constraint is an arbitrary function on the coset, so any
  gadget of the form `A(x)·w(x)` is satisfiable POINTWISE (`w := B/A`). The VM's inverse witness `WI`
  (`vm_circuit.py:32`) is used linearly by `c_jnz`, `c_nez`, `c_req` and `c_pc` (`:530-552`): setting
  `WI := 1/V_rs` pointwise makes a JNZ on zero jump and a failed REQUIRE pass, for any epoch whose programs
  execute no `LT` (`c_ltbit` is quadratic in `WI` and blocks the construction). The degree slack
  (`deg cp < next_pow2(md)·T`, `stark.py:686-690`) compounds it; the soundness figures in
  `doc/fri-parameters.md` and `soundness.py` assume the standard ALI theorem, which does not apply to this
  shape. Fix: batch the trace LDEs into FRI (random linear combination, or DEEP-ALI with an OOD point from
  GF(p³) and OOD trace values absorbed before the FRI challenges) and set the FRI degree bound to what the
  AIR needs.
- **P2 — HIGH on the shielded-contract path, verified by reading. The alghash2 transcript binds a string by
  its byte sum.** `backend.py:120-125` encodes `str` as `sum(bytes) % P`; `appnote_circuit` uses this
  backend and `shielded_state.py:411-421` passes `aux = str(withdraw_addr)` to bind the exit destination.
  An attacker grinds an address with the victim's byte sum (~2,400 classes), copies the proof, swaps the
  address. The main pool's BLAKE2B backend is length-prefixed and unaffected. Fix: length-prefixed lane
  encoding or absorb `hashn(bytes)`; consensus-changing.
- P3 MEDIUM (= A1's core-level statement): only `aux` and roots are absorbed; boundaries, periodic tables,
  `T`, `W`, `max_degree` and the AIR identity are not, and every proof type shares one transcript label.
  P4 LOW: Merkle path length not pinned to tree depth. P5 cost: verification is linear in proof bytes
  (~1 minute per 100 MiB bogus proof, native), no minutes-scale amplification beyond that; the settle path
  memoises by bytes. P6: no verify-side bypass flag; `NADO_ALLOW_PYTHON_KERNELS` only unlocks Python proving.
  `deep_eval`/`io_bind` draw `z` from the base field despite claiming an extension point (~47 bits, capability
  path only). Docs are stale on the arena's field support (now degree-generic, `EXT_DEGREE = 3`,
  challenges in GF(p³) not GF(p²)).
- Parameters: rate 1/2, 320 queries, radix-2 folding with one GF(p³) challenge per layer, final layer 2
  values constant, 18-bit grind before the query draw. Model soundness ≈ 156 bits provable / 176
  conjectured — matching `doc/fri-parameters.md`, not the stale numbers in `fri.py:31-32`. Effective
  soundness today: none until P0 is pinned; after that, no theorem covers the shape until P1 is fixed.
- Sound: commit-before-challenge order inside FRI, grind before indices, final-layer degree test, the
  `expected_ext` pin, Goldilocks reduction and every hash/transcript frame bit-consistent between Rust and
  Python, ext alphas drawn identically on both paths, verdict memo and `cid_io` lessons still hold.

## 6. zkVM execution AIR and lookup arguments (vm_circuit.py, air_ir.py, logup.py, appnote_circuit.py)

Context that sets severity: `SETTLE_PROOF_TRUSTLESS = True` (a proven root justifies with no quorum) and L1
never re-executes calls — the exec AIR is the whole gate.

- **A1 — CRITICAL, premise verified by reading; attack traced, not executed. The public statement is not in
  the Fiat–Shamir transcript.** `stark.prove`/`verify` absorb only an optional `aux`, committed-periodic
  roots, and the column roots (`stark.py:507-525`, `:660-677`). Both live verify sites
  (`settlement_sparse.py:152, 227`) call `verify_epoch_calls(proof, calls, io, num_queries, row_commit)`
  with no `aux` and no `commit_periodic`, so the io log, args table, program table and per-row context are
  REBUILT by the verifier and evaluated at query points that were fixed before the statement was chosen.
  `verify_epoch_o1`, which binds the table roots to `io_commitment`/`calls_commitment`, has no caller. The
  io-table constraint is degree 1 in the periodic values, so after an honest proof for log L1, presenting L2
  verifies iff a linear system of one equation per query (320) is satisfied — a settler with ≥320 free io
  entries of their own in the segment (one contract doing scratch `SSTORE`s) solves it and rewrites any
  victim entry: an arbitrary write to any contract's slot, or a `PAY` from any contract to the settler,
  attributed to the victim's cid by RET segmentation, with a proof L1 accepts. The recursive path rebuilds
  the same tables unabsorbed. `appnote_circuit.py:504-506` has the sharper boundary form: three
  prover-chosen public values pinned on one row share one denominator (two base equations, three unknowns).
  Fix: absorb a digest of the rebuilt statement through the existing `aux` hook at both `prove_epoch_calls`
  and `verify_epoch_calls` (or commit the epoch-data columns and bind their roots). Transcript change ⇒
  every proof format changes ⇒ consensus change.
- **A2 — CRITICAL, traced. The block schedule is prover-declared and nothing ties a block's length to its
  RET.** `epoch_statement` (`vm_circuit.py:1012-1031`) checks contiguity only; `build_periodic` fills the
  context/program/call columns only inside declared blocks (`:784, 816-823`), zero elsewhere; no selector
  forces rows outside a block to be NOPs. Declaring the last block with `n = 1` runs the call to its RET
  with `CTX → 0`, program 0 and call 0's args: deadline and owner checks against 0, or a settler's program
  executing on the victim's registers ending in `PAY attacker; RET`. Also unbound: the AIR admits one more
  step than `GAS_LIMIT`. Fix: a periodic in-block selector with `(1 − P_IN)·(1 − f_NOP) = 0`.
- **A3 — HIGH, traced.** Args-table padding rows `(call 0, index 0, value 0)` carry a free multiplicity
  (`:807`, `c_ga` `:608-610`, no `PT_ACT`); an `ARG rd, 0` in call 0 can load 0 instead of `args[0]`.
- **A4 — HIGH (storage binding).** Non-canonical `pre_contracts` keys (`"05"` vs `"5"`, cid aliases via
  `int(cid,16)`) alias the pre-root pin (`settlement_sparse.py:38-39, 173`): read-only slot values are
  unbound. Canonicalise or reject before the pin.
- A5 MEDIUM: the deposit statement never pins `VIN = 0` (`appnote_circuit.py:664-668`) — mints a note worth
  `delta + X`. A6 MEDIUM (completeness): a program containing `NOP` is executable but unprovable (the AIR
  treats NOP as the halt selector; the interpreter advances pc). A7 LOW: Rust alghash2 constants are
  hand-copied; eight offline "verifiers" take activity selectors from the proof; `MAX_DEGREE = 7` labels
  degree-8 constraints (safe only by blowup rounding); asset over-spend is interpreter-only.
- Sound (per opcode, given A1–A3 fixed): register hold/update, EQ/NEZ inverse witnesses, NOTB, LT/RANGE
  63/62-bit limb decompositions on the byte and 7-bit buses, DIVMOD/DIVMODW all four decompositions,
  LO32 canonicalisation, JMP/JNZ/REQUIRE, the 27 hash rounds with baked constants, io tuples bound in order
  by the permutation bus, padding after RET provably inert, LogUp challenges drawn after the multiplicity
  columns, degree ≤ 9 within the blowup.

---

## 7. Remediation order and ownership

**Before anything else — proof system, three verifier pins (validation rules, height-gated):** P0 (tie the
FRI domain to the STARK's), A1 (absorb the rebuilt statement into the transcript), A2 (in-block selector).

> **Status 2026-09-23 (evening): P0 and A1 are FIXED**, gated at `PROOF_BIND_HEIGHT = 208000` (gen 25; block 1
> at a reroll). P0: `stark.verify` and `fri.verify` pin `(N, offset)` to the STARK's, and `recursive_verify.verify`
> pins each inner `fri_public` the same way. A1: `vm_circuit.statement_digest` (the BUILT periodic tables +
> boundaries) is absorbed through `stark.absorb_statement` before the trace roots in `stark.prove`,
> `stark_native.prove`, `stark.verify` and the fold's `_fs` replay. Rules are a height-keyed context
> (`stark.rules_at`) entered by the L1 settle branch, the exec block apply and the settler (which proves for
> `L1 tip + 1`); the verdict memo and the child verifier carry them. `tests/test_proof_bind_gate.py` BUILDS the P0
> forgery (a FRI over 2N interpolated through the N spot-check values of a violated trace) and shows it ACCEPTED
> under the legacy rules — the finding is now reproduced, not traced. **A2 is FIXED too**, on its own gate
> `PROOF_BLOCK_SELECTOR_HEIGHT = 212000`: the exec AIR gains the periodic column `P_IN` (1 on declared rows) and
> the constraint `(1 - P_IN)(1 - f_NOP) = 0`, present under `rules.in_block_selector` on both prover and
> verifier (`vm_circuit.num_periodic`, `transitions(in_block)`, `build_periodic(in_block)`).
> `tests/test_proof_block_selector.py` builds the forgery — an honest four-row witness declared as a one-row
> block — and shows it VERIFYING under the pre-gate rules and refused at the gate. P1 remains a redesign.
Until P0 lands, `SETTLE_PROOF_TRUSTLESS` means a bonded settler can settle any root; the operator may
prefer to flip it off (quorum only) until the pin is deployed. P1 is a protocol redesign (trace LDT / DEEP)
and should be scheduled, not patched.


1. **Now, exec layer (code + tests, one deploy):** C1 asset gate; F2 method typing + refund-on-exception;
   Z2 fail-closed shielded bundle; S2 non-negativity in the records fold; S3 cheap checks first; S5 never
   memoise an exception. All are exec/L1 rules → each needs its cursor/height gate and the reroll branch.

   > **Status 2026-09-23 (later): DONE**, one gate `EXEC_RULES_V2_HEIGHT = 210000` (gen 25; block 1 at a
   > reroll). C1: `execnode/state.py` refuses asset value into a method whose program never executes ACTX
   > (`zkvm.method_reads_actx`), and `settlement_proofs._run_call` mirrors it at the call's own cursor. F2:
   > non-string `method` refused before the escrow, a VM exception refunds, L1 blob admission types `method`.
   > Z2: a `stark` bundle without `joinsplit`/`joinsplit2` is refused and an exit is bounded by
   > `MAX_EXIT_VALUE`. S2: `records_bind.net_records_updates(nonneg=True)` from the gate. S3: tip/root/chain-read/
   > calldata checks now precede the verify (claims first, then pinned to the proven halves). S5: `MemoryError`
   > re-raised at every verifier layer, never memoised. `tests/test_exec_rules_v2.py` shows C1 and Z2 OPEN
   > below the gate (the token booked as native value; the unbacked exit recorded) and closed at it.
2. **Now, contracts (code + tests; upgrade signed by the deployer key):** C2 id bounds in thirteen
   contracts; C4 pets `EX` guard; C3 wallet-side lock sizing from wall clock; the medium items as chosen.

   > **Status 2026-09-23 (later): C2 CODE DONE, upgrades pending the deployer key.** `_lib.id_guard` /
   > `_lib.guard_ids` prefix `movi r4 2^32; mov r5 r<id>; lt r5 r4; require r5` onto every id-taking method,
   > applied in each game's `build()` (fund/close carry it inline in `_lib`); autogame's six DSL methods start
   > with `m.require(m.arg(0) < 2^32)`; reversi's `move` also bounds the cell (< 65). Fourteen contracts, not
   > thirteen: **pool** splices tictactoe's `open` and had the identical hole. `tests/test_contract_id_bounds.py`
   > reproduces the finding on the unguarded code (an aliased `open` writes outside its field set), then shows
   > every guarded method reverting without a write for ids in [2^32, 2^62) and ≥ 2^62, and that honest calls
   > produce identical io logs before and after (r4/r5 are scratch everywhere). The ABI and field layout are
   > unchanged, so the wallets need nothing.
   >
   > The survey also found the same STRUCTURAL shape (bound at creation only, every later method unbounded) in
   > bet, hamster, pets, holdem, farkle, coinflip, lend, reserve (`vid` beyond `open`) and dex (`pool` args beyond
   > `open`/`fundn`); the review judged those sound because their guards compare content, and no payoff was
   > proven. Bounding them is the same one-line-per-method change; it is a scoping decision for the operator,
   > not done here. faucet and sovereign take no id argument.
   >
   > **To upgrade in place (the deployer key signs; one command per contract, same cid):**
   > ```
   > HOME=/root python3 -m execnode.games.deploy dice      --upgrade 230860957a7c1db403434ffb4a3969b3
   > HOME=/root python3 -m execnode.games.deploy roulette  --upgrade b47b6197939e85804ec647b1e6491c30
   > HOME=/root python3 -m execnode.games.deploy slots     --upgrade 42509ee496258eea278dd01d66a8eed8
   > HOME=/root python3 -m execnode.games.deploy mines     --upgrade 584783cc92f57b40b4c832b9b1f3242c
   > HOME=/root python3 -m execnode.games.deploy blackjack --upgrade d0be764f3da9c9cc6bb609280a887929
   > HOME=/root python3 -m execnode.games.deploy tictactoe --upgrade 266e44abb869209132fc7925a1315c5d
   > HOME=/root python3 -m execnode.games.deploy connect4  --upgrade b7cdf18106cf80c74fe423fd1da9032f
   > HOME=/root python3 -m execnode.games.deploy reversi   --upgrade 167d4fb3ae5c282bfdfcb846bba7b5a1
   > HOME=/root python3 -m execnode.games.deploy chess     --upgrade 2aa4f314876c71662bc3bb9c04177827
   > HOME=/root python3 -m execnode.games.deploy stormhold --upgrade 093708c95385df4d6123ee56117fcc14
   > HOME=/root python3 -m execnode.games.deploy scrapline --upgrade b062a72c3dbf5558f8ad4858b212d6ca
   > HOME=/root python3 -m execnode.games.deploy hexholm   --upgrade a9113e07ff9b990437d1e47543b60696
   > HOME=/root python3 -m execnode.games.deploy pool      --upgrade 043c6d95117ed222f3e95b1f2997fba9
   > HOME=/root python3 -m execnode.games.deploy autogame  --upgrade af66948ff14f81ace98d4fde619b8e74
   > ```
   > Then confirm on the exec node that each cid's code begins with the guard
   > (`/exec/contracts`, method `open`/`bet`/`begin`: first instruction `MOVI r4 4294967296` or `MOV r1 r0`).
   > Storage scan before upgrading: a table whose `gg` row already holds an oversized table id would keep it
   > (the settle-family methods read the id from storage); the review found no aliased slot in live storage.
3. **Lock the contracts** once upgraded, and move `deployer`/`upgradable`/`zk_addrs` into the root (reroll).
4. **Reroll-class:** S1 code-leaf binding; F3 prover context; Z1 masked trace; Z3 wide commitment; Z4 tree
   capacity; `chain_clock` re-anchoring for C3.

   > **Status 2026-09-23 (night): round 2 shipped behind `REVIEW_R2_HEIGHT = 214000`** (exec, L1 and proof rules
   > on one gate): Z6 duplicate commitments refused (both pools), Z9 the field path validates the exit address
   > before verifying, Z4 a full field pool refuses the deposit (was a silent drop), F7 runtime typed, F10 every
   > false-like `upgradable` locks, F8 constructor asset effects staged/committed, F4 a per-block execution budget
   > (`EXEC_BLOCK_STEP_BUDGET`, `zkvm.run(meter=)`, mirrored in `settlement_proofs.prove_epoch`), S4 a DA-carried
   > proof records the proven marker, A4 canonical `pre_contracts` keys, P2 `aux` as digest lanes, P3/Z8 the AIR
   > identity (`stark.air_digest`: T, total W, blowup, constraint count, boundaries, and the periodic tables when
   > no statement digest binds them) absorbed before the roots on every prover, verifier and fold replay, P4 opening
   > path lengths pinned. Z7: `/exec/prove_transfer{,2}` and `/exec/prove_call` are unrouted (the wallet proves
   > on-device; `static/stark/stark.js` carries the same round-2 prologue and reads the gate heights from
   > `/status.proof_rules`). C3 wallet: `static/dex.js` judges the foreign deadline by the wall clock with a
   > cadence bound (6 s / 8 s), at fill and again at lock. F3 is coded behind `EXEC_CTX_CURRENT_HEIGHT`
   > (live 2^62 = off until the reroll). `recursion_depth` (not on the live path) refuses its replay under round 2.
   > Contracts (second upgrade pass): C4 pets battle lock on transfer/list/buy/accept_offer; C2 bounds in the
   > nine remaining id-taking contracts; OTC bond retained until settle/expire/release; board-game abort deadline
   > refreshed on every move; slots/blackjack payout windows; chess move cap; lend/reserve duration bounds; DEX
   > minimum seed; bet's book settles on the recorded result; faucet prizes consume the operator's own donations.
   > STILL OPEN, all reroll-class or redesigns: S1 (code-leaf binding: needs the KV transition to carry code
   > leaves), Z1 (masked trace), Z3 (wide commitment), `chain_clock` re-anchoring, P1 (DEEP/trace LDT), sovereign's
   > global ply counter, hamster's dust sweep, and the banked-game reclaim "free option" (a design decision:
   > settle is permissionless, so a banker-side settler bot closes it operationally).

   > **Status 2026-09-23 (late): the reroll-class work begins.** `chain_clock` re-anchored per generation
   > (`CHAIN_CLOCK_CADENCE_DS`: 60 on gen 25 = exactly h*6, 65 next; 62d98f32, `/status.chain_clock` shows the
   > lag). **S1 + C5 + the prover TIME context coded behind `EXEC_ROOT_V2_HEIGHT`** (2^62 live, 1 at the
   > reroll): META leaf (deployer, lock flag, runtime) in the KV half, code events in the DA binding, the
   > verifier-derived code/meta transition, constructor-as-call, `chain_clock(h)` in the call leaf; the v2
   > upgrade rule names its runtime exactly, and the gen-25 faucet slot-7 seed is off from the gate (it wrote
   > storage from the records half, which no proof can derive). Gen-25 roots, leaves and summaries are
   > byte-unchanged (`tests/test_exec_root_v2.py`, `test_exec_root`, `test_settlement_sparse`, the DA-binding
   > and records suites). Remaining: Z3 wide commitment + Z1 masked trace, then P1.

Repro scripts used (scratch, not committed): `repro_contracts.py` (C1, C2 banked), `repro_ttt.py` (C2
board), `repro_shield.py` (Z2), `repro_zk.py` (Z1, `NADO_ALLOW_PYTHON_KERNELS=1`, 23 s prove).
