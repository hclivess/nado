# Stwo migration, and a reroll that carries everything

Status: **proposal of 2026-10-10, partly built (2026-10-26).** The Stwo shielded pool (§5.1) is live on gen 28
(`STWO_POOL_HEIGHT` 269000). The BLAKE2s exec root is built behind the dormant `BLAKE_EXEC_HEIGHT` and goes live at the
G7 reroll (generation 29); phase status is in §9.5. Each phase below starts with a measurement, and that measurement
decides whether the phase happens. The proving system and the reroll date are the operator's decisions.

Two plans live in one document because they depend on each other. Replacing the proof system changes the format of
every root the chain commits to, so it can only land at a reroll. And a reroll today drops game state, part of fidelity
and (by refusal) the shielded pool. So the migration needs a carry that loses nothing, and once that carry exists it
should be used for every reroll, not only this one.

---

## 1. Why: where our soundness failures came from

Every serious proving hole found in this repository was in code we wrote ourselves, and each one had passing tests:

| finding | what it allowed | where recorded |
|---|---|---|
| FRI queries only in the lower half of the domain | any statement verified (N/2 points always interpolate) | doc/security-review-2026-09-24-zk.md |
| degree bound one power of two too loose | a constraint could vanish on the coset while the trace violated it | same |
| prover-supplied intermediate `cid_io` | a forged exec root settled on L1 | memory: settle-verify-authenticate-intermediates, eee54fe |
| hand-rolled transcript replays | tests silently stopped testing anything at the round-2 prologue | .claude/skills/ship-consensus-change §12 |
| `air_digest` built from a prover-local width | every real proof refused (an outage, not a forgery) | same skill, §9 |
| prover ran every call at `timestamp=0`, chain at `chain_clock(h)` | an honest proof landed beside the chain | same skill, §10 |
| alghash (64-bit digest) as the note commitment | ~2^33 work to unshield the whole escrow | execnode/stark/znote.py header |
| alghash2 at 8 rounds ("demonstration" value) | interpolation-invertible at ~2^22.5 | execnode/stark/alghash2.py header |

None of these was a performance problem. They are what happens when a small team writes soundness-critical
cryptography from scratch: **17,611 lines of Python** in `execnode/stark/`, **2,927 lines of Rust** in
`native/starkprove`, `native/starkcompose` and `native/alghash2`, a JavaScript prover in `static/stark/` and
`static/shielded.js`, and our own hash (`alghash2`: width 12, x^7, 54 full rounds, a Cauchy MDS matrix, constants and
round count chosen by us). Each of these is a place a forgery can live, and a reviewer has to understand all of them.

Moving to a prover that many people are attacking in public removes most of that surface. Speed is a secondary benefit,
not the reason.

## 2. What Stwo is (sources at the end)

- StarkWare's Circle STARK prover and verifier, in Rust, **Apache-2.0**.
- **Production:** it is S-two, which proves every Starknet block (it replaced Stone) and powers SHARP.
- **Field:** Mersenne-31, p = 2^31 − 1, with the extension tower M31 → CM31 → QM31. QM31 (degree 4) is the field
  Fiat-Shamir challenges are drawn from. M31 has no large power-of-two multiplicative subgroup; the circle group over it
  has order p + 1 = 2^31, and that is what makes FFTs and FRI work.
- **Why the field matters for us:** an element fits a 32-bit lane, and reduction mod 2^31 − 1 is shifts and adds. The
  SIMD backend is the main execution path and targets AVX2, AVX-512, **NEON (phones)** and **WebAssembly SIMD (our
  wallet)**. Goldilocks needs 64-bit lanes, and our shielded proofs also run in a quadratic extension, which measured
  about 2.8× the cost of base-field work (memory: ext-field-proving-cost).
- **Constraint system:** an AIR framework (`constraint-framework` crate) with components, preprocessed and interaction
  columns, and built-in LogUp/GKR lookups. Reference circuits include Fibonacci, Poseidon, Blake and state machines.
- **Verifier:** a `no_std` crate. The `prover` feature gates all proving code, so the verifier we would embed in the
  node stays small.
- **Cairo:** `stwo-cairo` proves arbitrary Cairo programs. That is a second route for our contracts (section 5.3).
- **Audits:** the Stwo README says external reports will be linked as they are published. A zkSecurity report covers
  the **stwo-cairo verifier**. We should not describe the core prover as audited until a report says so.

## 3. What the provably.fast frontier shows

Read from the branch at tip `cb63e35` (2026-10-10), without building it. It is a monorepo of StarkWare's whole
proving stack (`starkware-libs/proving`, workspace 2.4.0): Stwo itself, stwo-cairo, stwo-circuits and the
proving utilities, **vendored as source** (`stwo = { path = "crates/stwo" }`, no git dependencies in `Cargo.lock`), built
on `nightly-2026-01-15`. The 16 "Promote … whole-proof record" commits on top (36cb4ba → cb63e35, 29 Sep–10 Oct 2026) are
the frontier. What it measures is the **privacy whole proof** (`crates/privacy_prove`: a Cairo proof, then a circuit
proof over it), which is the same kind of statement as our shielded transfer.

**How a record is accepted** (commit trailers `Frontier-Job`, `Frontier-Patch-SHA256`, `Frontier-Ratio`):

- it beats the current frontier on paired timing runs with a 95 % confidence interval;
- the patch adds no `unsafe` and no line that reaches the host, the clock or the network;
- the test corpus proves **byte-for-byte** like the pinned prover. Every optimization is bit-exact: the same proof,
  produced with less memory or time.

That last rule is the method worth copying: an optimization that changes no output bit cannot change soundness.

**Measured progression** (from the commit messages): peak memory 11.73 GB (896dc54) → 8.24 GiB (88f22f7) → 5.87
(754321f) → **2.11** (0e80cbf) → **1.81 GiB** (cb63e35). Time ranged from 0.51× to 0.94× of the pinned prover as
memory trades were taken; the latest is 0.807× (19.3 % faster).

The authors' announcement (2026-10) states the same result from their evaluator: peak memory **13.9 GiB → 2.1 GiB in
under two weeks without dropping below the original speed**, and a **Pixel 11 producing the full STARK proof of a real
Starknet mainnet transaction in 51 s using 2.41 GiB of RAM**. The repository's records agree with the parts it holds
(2.11 GiB at 0e80cbf, speed recovered afterwards). The 13.9 GiB baseline and the phone run come from their evaluator and
phone build, which are not in the repository. Their point about privacy is ours too: in most private-payment flows the
proof is made on a server that sees who pays whom and how much, and a phone-sized prover keeps that on the phone. Our
wallet already proves client-side; what Stwo would change is how fast and how small that proof is on a phone.

**Where the memory went** (all bit-exact):

- **Recompute instead of store.** No polynomial coefficients are kept: out-of-domain values are evaluated from a
  bit-reversed prefix of each evaluation with shared barycentric weights (754321f, −12 %). Lookup tables are generated
  from their formula (02c9df3). The "striped prover" (0e80cbf: `prover/pcs/mod.rs`, `vcs_lifted/prover.rs`,
  `component_prover.rs`) took 5.87 → 2.11 GiB (−64 %) at 1.83× the time, and later commits won the time back.
- **Sparse Merkle storage.** Only level 5 and up is stored; the aligned 32-leaf block is recomputed per query at
  decommitment (c38b7e2, 754321f).
- **Lifetimes.** The circuit's preprocessed tree is built after the Cairo proof, reusing its buffers (88f22f7, −18 %).
- **Allocation.** An mmap large-block cache, huge pages, `MADV_DONTNEED` on all-zero columns, u32 address columns
  (`prover/backend/simd/column.rs`; 7f9715f −16 %).
- **Arithmetic.** FFT phase fused with the transpose, IFFT scaling folded into the last pass, deferred reduction in the
  quotient, batch inversion of QM31 via base-field norms (~2×).

**Mobile:** NEON is tested in CI on ARM macOS, and Stwo's tests run on wasm32 with simd128. There is no Android build
script in the repository.

**Their soundness checklists, against our failures** (`.claude/skills/soundness-review-checklist`,
`fri-protocol`, `paper-implementation-divergence-log`):

| their invariant | our failure it would have caught |
|---|---|
| queries drawn over the **full** domain (`core/queries.rs`, mask `(1<<log_domain_size)-1`) | FRI queries in the lower half only |
| **strict** last-layer degree check (FRI-2) | degree bound one power of two too loose |
| every proof element bound into the transcript; prover and verifier run the same mix/draw sequence | prover-supplied `cid_io`; `air_digest` from a prover-local width |
| a known-answer test pinning the query stream across implementations (e580a50) | hand-rolled transcript replays drifting |
| test defaults unusable in production (the 13-bit `PcsConfig::default` was removed, 38c0183) | alghash2's 8-round "demonstration" value |

Their own divergence log still lists open items, notably **Poseidon2 placeholder constants** in the example AIR (009)
and an unvalidated LogUp in the Blake example (010). An outside codebase is not automatically right, and adopting it
means reading those logs, not trusting them.

## 4. Inventory: what changes for us

### 4.1 Statements we prove today

| statement | module | proved by | verified in consensus at |
|---|---|---|---|
| shielded join-split | `execnode/stark/joinsplit3.py`, `znote.py`; wallet `static/stark/joinsplit3.js` | the user's browser | exec apply (`execnode/execnode.py`, under `stark.rules_at`) |
| exec settlement (KV half, sparse) | `execnode/stark/settlement_sparse.py`, `storage_tree.py`, `exec_state_bind.py` | the settler, natively (`native/starkprove`) | L1 settle branch, `ops/transaction_ops.py` (`_settle_verify_lock`, `stark.rules_at(block_height)`), in a child process (`ops/proof_child.py`) |
| VM execution, records, recursion, folds | `vm_circuit.py`, `records_*.py`, `recursive_verify*.py`, `settlement_aggregate.py` | the settler | through the settlement bundle |

### 4.2 The hash is the hidden half of the migration

Every committed digest on the exec side is an **alghash2** digest: the exec root
(`alghash2.rnode(KV_ROOT, RECORDS_ROOT)`, `execnode/exec_root.py`), both depth-256 sparse trees, contract slot positions
(`exec_state_bind.slot_key`), and every shielded commitment, owner id and nullifier (`znote.py`). A Stwo circuit has to
prove these hashes in-circuit, so we choose between:

- **Recommended: replace alghash2 with Blake2s**, the hash Stwo's production circuits already prove (Blake G gates
  in `circuit_prover`, the Blake AIR in `examples`) and its default Merkle and channel hash. This swaps our second
  home-grown primitive for a standard one with decades of cryptanalysis behind it, and every digest changes once, at
  the reroll. Stwo has **no** production Poseidon2-over-M31: its one Poseidon2 AIR is an example with placeholder
  constants (their divergence log, item 009). If an algebraic hash is ever wanted for cheaper in-circuit Merkle paths,
  it has to come with published parameters and outside cryptanalysis, never constants we pick.
- Emulating Goldilocks alghash2 inside M31: 64-bit modular arithmetic built from 31-bit limbs. Expensive, and it keeps
  the parameters we chose ourselves.

**Addresses do not change.** An L1 address is a blake2b hash of the whole public key (format 2, `ops/address_ops`),
outside every proof. What changes is how a CONTRACT stores one: an owner/banker/bettor is `blake2b("zkvmaddr", addr)
mod P`, one 64-bit Goldilocks element (`execnode/runtimes.zkvm_addr_digest`), which no longer fits a 31-bit M31
element. The Stwo carry therefore re-encodes owner fields inside contract storage (a mechanical pass through the same
index walk the carry hooks use); users keep the same address, keys, pets and balances.

So the reroll re-hashes all public state (the carry does this, section 6). Shielded notes cannot be re-hashed, because
only their owners hold the openings; section 6.4 deals with that.

### 4.3 Where the verifier runs

Consensus verification moves from Python plus our native kernels to a Rust crate behind the same `native_guard` pattern
we already require (doc/rust-only-proving.md). The crate becomes consensus code, so:

- vendor or pin the exact Stwo source (the frontier repository vendors it in-tree; a crates.io version plus a
  checked `Cargo.lock.pinned` hash is the lighter option), and embed only the `no_std` verifier
  (`stwo::core::verifier::verify`, built without the `prover` feature; `ensure-verifier-no_std/` in the frontier
  repository is the proof that this builds);
- upgrading Stwo is a gated protocol change, like a pinned root;
- `stark.rules_at(height)` stays as the one switch at the three consensus entry points, so the old verifier answers
  for blocks below the gate (history replays) and the new one at and above it.

## 5. Phases

Every phase starts with a measurement, and its result decides whether the phase goes ahead.

### 5.0 Measure (no chain change)

1. Our join-split today: prove time and **peak memory** in the wallet on a real mid-range Android phone and an iPhone,
   and in desktop Chrome. Nobody has ever measured this.
2. The same statement (value conservation, owner = H(nsk), commitment, nullifier, Merkle membership at our depth) as a
   Stwo prototype in a scratch crate: native on the phone, and WASM in the same browsers.
3. Our settlement proof on the settler today, against a Stwo prototype of one representative epoch.

Decision: go ahead if Stwo is faster *and* smaller on the phone. If it is not, the soundness argument still stands, but
the wallet phase waits.

### 5.1 Shielded join-split on Stwo (first, while the pool is empty) — design

**Phase 0 result (2026-10-11, doc/stwo/phase0-results.md).** One join-split at depth 48: today's wallet prover takes
266 s and 3.5 GB in desktop Chrome and CRASHES a phone-class tab (4x CPU throttle) at both a 1 GiB and a 2 GiB heap.
A Stwo prototype of the same relation, made zero-knowledge (below), proves in 3.4-8.8 s with 218 MiB under the same
proxy (0.7-0.9 s native), verifies in 20 ms native, and its proof is 1.5 MB (36 MB today).

**No reroll is needed for this phase.** The pool is empty, so nothing has to migrate. A new pool enters the exec root
the way the wide pool did at SHIELD_WIDE_HEIGHT: digest records (`stwo_root`, `stwo_nfset`) that are ABSENT while the
pool is empty (exec_root.records_projection, "empty is absent"), so the projection is byte-identical on every node
until the first note exists, and the rule switches at an exec-rules height gate (`STWO_POOL_HEIGHT = H if
CHAIN_GENERATION == 28 else 1`, GATE LEDGER + doc/reroll.md + tests/test_gate_reroll_transfer.py). Settlement needs
no circuit change: the settle binding does not derive shielded-pool records today (`shield`/`unshield` are in
`records_bind._KNOWN_UNDERIVED`, so a span that touches a pool settles by quorum, not by proof), and the new pool's
deposit/spend effects join that list.

**The pieces.**

| piece | where | notes |
|---|---|---|
| circuit + ZK layer | `native/stwo_js` (Rust, Stwo pinned to one rev in `Cargo.lock.pinned`) | the phase-0 relation: 1 input, 2 outputs, owner = H(nsk), cm = H(value, owner, rho), nf = H(nsk, rho), depth-48 membership, 64-bit value conservation, root/nf/cm1/cm2/public value/fee + unshield destination bound in the transcript; H = BLAKE2s-256 |
| node verifier | the same crate, `prover` feature OFF, exposed through `native_guard` like every other kernel | consensus code: verify under `stark.rules_at(height)`; below the gate the call refuses |
| dispatcher | `execnode/stark/joinsplit_transfer.verify_transfer` | a new bundle key `stwo_js` beside `joinsplit3`; the old keys keep verifying history |
| pool | `execnode/shielded_stwo.py` (new), modelled on `shielded_wide.py` | BLAKE2s Merkle tree, depth 48 from its first note (no 12 -> 48 switch), anchors (the last 128 append roots + the closing root of every block that appended in the last 1024 blocks, `marks` in the exec root — review 2026-10-11), nullifier set |
| wallet prover | `static/vendor/stwo_js.wasm` + a Worker | content-versioned by ops/static_versions.py; seeded from `crypto.getRandomValues` per proof (the prototype refuses a reused seed); proves in a Worker, never the main thread |
| shielded address | `shieldAddr` in static/interface.js | owner = BLAKE2s(nsk) changes every zaddr — the wallet shows the new one; deposits to an old-format zaddr are refused from the gate |
| exits | unchanged | unshield records and their L1 claims are the same exit records; only the proof that creates them changes |

**The wallet side (built 2026-10-11, hidden until the gate).** The wallet reads `STWO_POOL_HEIGHT` from /protocol.js
(protocol.CLIENT_EXPORTS; a BigInt while dormant at 2^62) and switches to the Stwo pool when tip + 1 >= the gate — the
same tip + 1 rule as the wide pool and as the exec node's `/exec/field_leaves`, which from the gate serves the Stwo pool
(`"pool": "stwo"`, `"wide": false`, depth 48). Below the gate `static/stark/stwo_js.js` is never even downloaded.
- spend key: 256 bits under its OWN domain (blake2b over `shield-nsk-stwo-v1`, `DOMAIN_SHIELD_NSK_STWO`); owner =
  BLAKE2s(21, nsk). Recoverable from the same phrase. It was the wide key's v2 digest taken whole until review
  2026-10-11: a leaked wide witness would then have opened every Stwo note of the wallet (changed while the pool was
  dormant and empty, so no note exists under the old form).
- zaddr: `zaddr_` + base36 of the owner — marked, because a wide owner is also 256 bits and a note sent to the wrong
  pool's owner is unspendable; `parseShieldAddr` refuses the other pool's form. Stored notes carry `pool: "stwo"`.
- prover: `static/vendor/stwo_js.wasm` (ABI in `native/stwo_js/src/prover.rs`, "the wallet's WASM ABI": `stwo_seed`,
  `stwo_prove`, `stwo_verify_out`, `stwo_aux`), driven from a module Worker (`static/stark/stwo_worker.js`), one Worker
  per proof, seeded from `crypto.getRandomValues` inside the Worker; the WASM refuses an all-zero seed, a reused one and
  a prove without a fresh one, and the wallet verifies its own proof (the node's `verify_node`) before publishing.
  Measured: ~5.8 s per proof in Node, 4-6.5 s in headless Chromium (server CPU, one thread); proof ~2.9 MB (5.8 MB hex
  in the DA object, under the exec node's 16 MiB body cap).
- bundle (DA-published, then an L1 `field_transfer` blob carrying its commitment, exactly as the wide pool):
  `{"stark": {"stwo_js": {"proof": hex, "root", "nf", "cm_out1", "cm_out2": 64-hex, "unshield": "<u64>", "fee": "<u64>"}},
  "withdraw_addr": <only when unshield > 0>}` — a private transfer is bound to the empty destination.
- the shipped .wasm is a build product at a path nothing generates: `python3 tests/_stwo_js_build.py --ship` rebuilds it
  with the one pinned command (nightly-2026-01-15, wasm32 + simd128, three `--remap-path-prefix` so two machines build the
  same bytes — measured: a clean build in another directory is byte-identical) and prints the two sha256 pins that
  tests/test_the_shipped_stwo_wasm_is_a_build_of_the_committed_sources.py checks.
- DONE at the gate (was OPEN before it was set): from `STWO_POOL_HEIGHT` L1 admission
  (`transaction_ops.field_shield_check`) accepts any 64-hex owner (it no longer parses it as an alghash2 digest) and
  refuses a field deposit not tagged `"pool": "stwo"` — a wallet tab loaded before the gate builds a wide owner, which
  L1 cannot tell apart from a Stwo one, and the exec layer would put its coins under an owner nobody can spend.

**L1 linkage: who publishes, and which owner a deposit names (ZK review 2026-10-11, operator decisions; built
2026-10-12).** The proof hides the spent note and its owner, but two things around it did not:

- *Who publishes a spend — nodes relay spends, on by default on every node.* The wallet used to publish its spend in a
  `field_transfer` blob signed by its own account, tying every nullifier to that account
  (tests/test_a_stwo_spend_is_not_published_under_the_spenders_own_account.mjs). Now a PRIVATE spend is proved with
  `unshield` = the relay's fee and `withdraw_addr` = a relay node's address (the proof binds both, so the relay can be
  paid and cannot be paid more or redirected) and POSTed to that node's `/stwo/relay` (ops/stwo_relay.py). The node
  checks it before it spends anything — enabled (`"stwo_relay"`, default true in the code; `false` opts out), not in
  emergency mode, per-IP rate (12 per 10 min), a bounded in-flight set keyed by nullifier (64), the bundle through
  `shielded_stwo.parse_transfer` (the exec layer's own reading), the exec node's `/exec/stwo_spendable`
  (`ExecState.stwo_spend_refusal`, the apply path's own method), and the proof through `stwo_js_native.verify` — then
  publishes the bundle to its exec node's DA store and submits the blob signed with ITS OWN node key. The fee is one
  constant on every node, `STWO_RELAY_FEE_RAW` = 100 x MIN_TX_FEE (1e5 raw), so a relayed spend's public unshield does
  not tell relays apart; the node claims those exits on its auto-collect pass (`CoreClient._claim_relay_unshields`).
  `GET /stwo/relay_info` says whether a node relays right now (a node without the Stwo verifier library says no). The
  wallet asks its relay, home and the relay pool, shows the fee in the send confirmation, tries the next relay (with a
  fresh proof bound to that relay's address) when one fails, and NEVER falls back to signing a private spend itself — no
  relay is an error. A WITHDRAWAL (unshield to a public address) is still published by the account: its payout is
  public anyway and one proof binds one destination. Withdrawing to someone else's address shows a one-time notice that
  it links the payment to the account. No consensus change: to the exec layer a relayed spend is an ordinary unshield.
- *A fresh owner per deposit.* A deposit publishes `{owner, rho, cm}` next to the depositing account, and the owner was
  the wallet's one stable owner — the digest its zaddr encodes — so a zaddr named its account
  (tests/test_a_stwo_deposit_does_not_publish_the_owner_behind_the_wallets_zaddr.mjs). Deposit i is now owned by
  `ownerOf(nsk_i)`, `nsk_i = BLAKE2s-256("NADO/stwo/deposit-nsk/v1\0" || nsk || u64le(i))` (static/stark/stwo_js.js
  `depositNsk`; nsk = the wallet's Stwo spend key). The index is taken before the deposit is sent and never reused
  (interface.js `stwoDepositIndexTake`); the note stores it (`k`) and is spent with nsk_i (`noteNskWire`). A wallet
  restored on another device scans its own shield transactions for `ownerOf(nsk_0..)` until 20 indices in a row match
  nothing (`stwoRecoverDeposits`), recomputes each commitment, and marks the spent ones against the pool's whole spent
  set (`/exec/stwo_nullifiers`) locally. The zaddr for RECEIVING stays the stable owner (a payment's owner is inside its
  commitment, never published). Notes received by claim code or made as change cannot be found from the chain, as before.
- *Defence in depth: `stwo_value`.* The exec layer keeps the Stwo pool's own total (+amount per Stwo deposit,
  -(unshield + fee) per Stwo spend) and refuses, before any mutation, a spend that exits more than it — so even a proof
  the verifier wrongly accepts cannot take more than went into the Stwo pool, nor the frozen wide pool's value that
  `pool_value` still counts. In the snapshot and the exec root (`stwo_value` digest record), zero is absent.

**Toolchains (measured 2026-10-11).** Stwo pins `nightly-2026-01-15`, and fleet nodes build native crates on whatever
stable cargo they have, without our root. The split that works: the WALLET prover (WASM) is built here, on nightly, and
shipped as a file; the NODE verifier is Stwo with `default-features = false, features = ["std"]` (no `prover`), which
builds on stable rustc 1.95 (72 s, measured 2026-10-11). Still to check before coding: that the ZK verify
tail (stwo_zk `verify_js`) also builds on stable, and the OLDEST rustc on the fleet (Stwo's edition needs a recent
compiler; nodes do not report theirs — add it to /status first, and refuse loudly in `_build_crates` if too old,
never fail-stop the exec node).

**Gates on value.** Deposits into the new pool were refused until the zero-knowledge argument was written and reviewed.
The operator decided (2026-10-11) that the review is ours alone ("you are the only one who will review it"): three
adversarial reviewers, each counting only what they reproduced — soundness (no forgery: every post-proof mutation, every
PcsConfig field, both cheating provers, 3,400 fuzzed proofs refused; tests/test_stwo_js_every_post_proof_mutation_and_
cheat_is_refused.py), zero knowledge (the proof's openings measured against the witness, doc/stwo/zk-argument.md
corrected; tests/test_a_stwo_proof_reveals_nothing_about_its_witness.py — L4 and L3b rest on the earlier zkcheck runs)
and integration (anchor window, pool rebuild cost, a tagged deposit below the gate — all fixed with tests). The two
L1 leaks the ZK review found are closed: spends go through node relays (ops/stwo_relay.py), each deposit has a fresh
owner. `STWO_POOL_HEIGHT` = 269000. No deposit cap: the operator's decision (2026-10-11).

**The carry (2026-10-12, branch `stwo-carry`).** A reroll carries the Stwo pool, so holders never unshield for it (a
forced unshield publishes every holder's amount and destination). Its notes are BLAKE2s and survive the Goldilocks
retirement unchanged. What crosses (tools/alphanet6_carryforward `exec_shield_doc`, execnode/exec_genesis.py, genesis.py):
- **The exec genesis document** carries `stwo_pool` = the commitments IN ORDER (a note's leaf position is part of its
  spend witness) and the nullifier set (sorted), plus `stwo_value` and `pool_fees`. A fresh exec layer loaded from it
  has the old `stwo_root`, `stwo_nfset` and `stwo_value` records, so an old note spends against the carried root, and
  an already-spent note stays spent. `pool_value` starts equal to `stwo_value`.
- **Block marks restart EMPTY.** They are [old-chain height, note count] pairs: on the new chain those heights name
  other blocks, a mark above the new tip makes the first append raise, and an old mark would stay "recent" for as long
  as the new chain is shorter. Without marks, the anchors a spend may name are the carried tree's root and its append
  window (rebuilt from the commitments). A wallet with a spend in flight at the reroll re-proves against the carried
  root. The carried root differs from the old exec root only by the `stwo_marks` record. A document naming marks is
  refused.
- **SHIELD_ESCROW keeps backing the notes.** After the pending unshield exits are folded out of it, the escrow must
  hold at least `stwo_value` + the old `pool_fees`, or the carry refuses: an unbacked note would carry. The surplus
  (fees burned in-pool plus stranded deposits; 1,123,000 raw on betanet-9, locked since an earlier generation) is
  carried as the new layer's `pool_fees`. It stays locked in SHIELD_ESCROW exactly as before, and no coin moves, so
  Δ = 0. L1 genesis refuses an allocation whose SHIELD_ESCROW is not `stwo_value + pool_fees`, so the shielded
  invariant (ops/invariants.check_shielded) is exact from block 0.
- **Still refused:** notes in the legacy, field, wide or app-note pools, and any `pool_value` that `stwo_value` does not
  explain (`exec_value_the_carry_would_drop`).
- Tests: tests/test_the_stwo_pool_crosses_a_reroll_with_its_root_and_spent_set.py (roots, escrow, L1 genesis) and
  tests/test_an_old_stwo_note_spends_on_the_new_chain_and_a_spent_one_stays_spent.py (a real Stwo proof made against
  the old pool applies on the new chain; the same proof after an old-chain spend is refused as a double-spend).

**GATE BLOCKERS (review 2026-10-11) — BOTH RESOLVED before `STWO_POOL_HEIGHT` was set (2026-10-12):**
1. **Output rho is free, so a payer can make a note its owner cannot spend ("faerie gold").** The AIR constrains an
   output row's domain tag, value and padding (lib.rs `s_out1`/`s_out2`: m[0..2], m[13..15]) but not its rho (m[11..12]),
   and nf = H(23, nsk, rho) does not depend on the note's position. A sender pays one owner twice with the SAME rho and
   different values: the two commitments differ (so the duplicate-cm check passes), both land in the pool, and they share
   one nullifier — the recipient credits two payments and can spend one. The fix changes the circuit (derive an output's
   rho from the input's nullifier and the output index, or bind nf to the leaf position), so it needs the AIR change, a
   new `NODE_PREPROCESSED_ROOT` if a selector moves, and a re-shipped WASM built with the pinned nightly
   (tests/_stwo_js_build.py --ship).
   **Resolved for the receiver in the wallet (2026-10-11):** a Stwo wallet counts received notes by NULLIFIER
   (interface.js `shieldDuplicateNote`, every receive path): a note whose nullifier it already holds is refused with a
   translated reason, so a payment is credited once and nobody is paid in a note they cannot spend. The circuit change
   above stays the clean fix and can ship later behind its own gate; the wallet rule is what makes the gate safe now.
2. **The gate freezes every wide-pool note with no way out.** From the gate `apply_field_transfer` accepts only a
   `stwo_js` bundle, so a joinsplit3 spend or unshield of a wide note is refused forever, while the wide pool keeps taking
   deposits until the gate. The wide pool is empty today (0 notes at 2026-10-11); any deposit before the gate would be
   coins nobody can move — against "the coins are real". Before setting the gate: close wide deposits ahead of it (an L1
   admission gate on `shield`) AND either keep wide spends/unshields valid after it or prove the pool empty at the gate.
   **Resolved:** `WIDE_DEPOSIT_CLOSE_HEIGHT` (175000) refuses every wide deposit, and the Stwo gate (269000) was set only
   after the close fired with the wide pool measured empty — nothing exists to freeze.

**Tests (each in the same commit as its code).**
- forgeries refused AT the gate and impossible below it: wrong root, fee + 1, changed unshield destination, inflating
  witness, a claimed-sum shift between components, a forged lookup (the phase-0 negatives, against the node verifier);
- the wallet's WASM proof verifies in the node (the joinsplit3 cross-check pattern), and a reused seed is refused;
- empty is absent: the exec root is unchanged by the code until the first note;
- history: every joinsplit3 bundle in the chain still verifies (replay).
### 5.2 Settlement on Stwo

Prove the exec transition (KV half and records) with Stwo components. This is the larger job: our VM AIR
(`vm_circuit.py`) and the record and slot machinery get rewritten as components with LogUp buses. Our fold and
recursion layers (`recursive_verify*`, `settlement_aggregate`) are replaced by Stwo's own recursion, not ported.

### 5.3 Alternative route for contracts: Cairo

`stwo-cairo` proves any Cairo program. Rewriting our games as Cairo programs would replace our VM circuit with a VM that
others maintain and audit (the zkSecurity verifier report covers exactly this). It costs every contract and the game
clients' cross-checks, and it changes the developer story. Decide this before 5.2 starts, because it changes what 5.2
builds.

### 5.4 Retire `execnode/stark`

Once nothing below the gate needs re-verification (archive nodes keep the old verifier for history, see 4.3), delete the
Python prover, `native/starkprove`, `native/starkcompose`, `native/alghash2` and `static/stark/`. That is about 20,000
lines that can no longer hold a forgery.

## 6. The carry: a reroll that loses nothing (permanent)

### 6.1 What a reroll carries today, and what it drops

`tools/alphanet6_carryforward.py` plus `doc/reroll.md`:

| carried | dropped or refunded |
|---|---|
| L1 balances and bonded stake (Δ = 0 enforced) | nothing in contract state: every contract carries by id with all its storage and its pot, or the carry refuses (since 2026-10-20, doc/stwo/g5-carry.md) |
| uncollected dividends, user bridge balances, pending exits (folded into L1) | **open HTLC locks** (refunded to the funder; open invites carry since 2026-10-25) |
| device bindings, aliases, account-auth config | **the legacy, field, wide and app-note pools**: the carry *refuses* if they are not empty (the Stwo pool carries since 2026-10-12, §5.1 "The carry") |
| fidelity of every carried identity (until `CARRY_FIDELITY_ALL_HEIGHT` only those present at the reroll: 47 of the 79 with fidelity at gen 28) | nothing since the fix of 6.3 |

### 6.2 Exec state carries as a genesis snapshot

- The carry writes the drained exec state to `genesis_data/exec_genesis.json`. Every node loads it at cursor −1, so the
  new chain starts from identical bytes. Its root, recomputed under the new hash (4.2), is a **pinned constant**, like
  the genesis allocation. The first settle proves forward from it.
- **Contracts keep their ids.** No redeploy and no frontend rewiring, which removes the "forgot to redeploy" failure
  (memory: reroll-requires-contract-redeploy) by construction. Code changes stay in-place `--upgrade` calls.
- **Pots stay in the L1 bridge escrow** instead of being refunded. Δ = 0 then covers them as well.
- **At rest vs in flight.** Contract storage refers to heights of the old chain (seat deadlines, `BEACON(gb)`
  epochs, HTLC timelocks, vault notice, pet epochs). On a new chain those heights mean something else: a deadline at
  150,000 locks funds for about 12 days, and a seat waiting on a block hash the new chain never has can never resolve
  (memory: bhash-prune-fundlock-bug-class). So each game module declares a carry hook:

  ```python
  def carry(storage) -> (kept_storage, refunds)   # refunds: {address: raw}; in-flight items leave storage
  ```

  At-rest state (bankroll, pets, nations, scores, settled balances) is kept. In-flight state (open hands, pending
  seats, open HTLCs) is refunded to whoever funded it. `otc.escrow_refunds` is already this shape. **As built
  (operator rule 2026-10-20) the carry refuses instead:** a contract with something in flight (`carry_in_flight`) or
  with storage and no carry rule refuses the whole carry (tools/carry.py); nothing is reset or refunded in its place.
- **Re-keying** is needed only when the address format changes, as it did at gen 28. Then each hook also maps the
  addresses inside its storage, with `tools/rekey_v2.py`'s mapping.
- Exec state is small: 5.7 MB in total, 27 contracts whose storage totals about 35 KB.

### 6.3 Fidelity carries for every identity, not just the present ones

Today two code paths read fidelity, and for carried identities absent at the reroll they disagree:

- the **live apply** (`account_ops.apply_register`) continues from the account field, which the carry wrote. The first
  recert on the new chain is a lapse, `max(1, carried // 2)`. This field feeds the **open-lane block draw**
  (`block_ops`, `open_shares`);
- the **dividend replay** (`dividend_ops.fidelity_at_epoch`) seeds the carried value only from an epoch-0 recert, which
  only present identities have. Every absent identity replays as a newcomer. This feeds **the dividend**
  (`weights_at_epoch`).

Measured 2026-10-10 at epoch 2578 (`/get_account` against `/get_open_weights`):

| identity | carried | account fidelity | dividend weight (×10) |
|---|---|---|---|
| b3bef70b… | 11 | 16 | 120 |
| 3f662106… | 9 | 15 | 120 |
| 3c0c735c… | 12 | 15 | 100 |

This is **our bug**, the same class as 302215f2. Its fix (a344f923) covered present identities only. The permanent rule:
a carried identity's first recert on the new chain continues from its carried value through `fidelity_step` as a
lapse, whether or not it was present, in **both** paths, so `fidelity_at_epoch == account.fidelity` for every identity.
Fixed on the live chain from `CARRY_FIDELITY_ALL_HEIGHT` (block 160,020, epoch 2667): from that epoch the replay
starts an absent carried identity from its carried value. No back-pay (operator, 2026-10-10): earlier epochs keep their
weights. The permanent carry tool must keep both paths seeded from the same value.

### 6.4 The shielded pool

- **If the pool is empty at the switch** (it is today): the new pool starts empty under the new hash, and nothing moves.
  This is the reason 5.1 goes first.
- **If it is not empty**: owners must move their notes themselves, because nobody else can open them. Keep the old
  join-split verifier for **one** transaction type: a migration spend that proves an old note against the frozen
  carried old root and nullifier set, and creates a note in the new pool. The old verifier's exposure is then bounded by
  the old pool's escrow, and it never closes on unclaimed notes. Funds are never burned, which matches the rule that
  the coins are real.

### 6.4b Status (2026-10-10)

Built on branch `carry`: §6.2 (every contract by id; storage and pot for carry-safe games; hooks for slots, dice,
roulette, mines, blackjack, pets, autogame, hamster, tictactoe, connect4, reversi, chess, bet, the faucet and the daily
boards), exec assets, the refusal of every shielded pool (not only the legacy one), and §6.3 live (CARRY_FIDELITY_ALL_HEIGHT).
Since 2026-10-20 every contract carries with all of its storage and its pot, or the carry refuses (tools/carry.py,
doc/stwo/g5-carry.md). The Stwo pool carries since 2026-10-12 (§5.1 "The carry"); the older pools are still refused
unless empty. See
doc/reroll.md "What crosses a reroll".

### 6.5 Making it permanent

- One tool, `tools/carry.py`, replaces the per-generation `alphanet*_carryforward.py` scripts. It is versioned, it is
  what the runbook runs, and it is the only way genesis data is produced.
- **Test: "a reroll loses nothing"**, run on the real chain read-only at every release, not only at a reroll:
  - Δ = 0 including contract pots and every escrow;
  - every account, identity, device binding, alias, auth config and contract survives;
  - `fidelity_at_epoch(a, first epoch) == account.fidelity(a)` for every carried identity;
  - the snapshot root recomputed by a fresh node equals the pinned constant;
  - one carried game (a pet, a nation) is playable on a loopback testnet started from the carried genesis;
  - every in-flight item is refunded to its funder, and nothing is refunded twice.
- `doc/reroll.md` becomes: drain, carry, check, start. The "redeploy contracts" step disappears.

## 7. Decisions for the operator

1. Adopt Stwo for the shielded join-split, after the 5.0 measurement?
2. ~~Replace alghash2 with Blake2s~~ — decided 2026-10-11: all of Goldilocks retires (alghash, alghash2, our STARK
   stack, the wide pool, the wallet prover) at a reroll; the plan is §9.
3. ~~Contracts: hand-written Stwo components (5.2), or Cairo programs proven by stwo-cairo (5.3)?~~ — decided
   2026-10-18 by the operator: **Route A**, our zkVM rewritten as Stwo components (§9.4: ~8-12k lines of Rust, the
   zkpy/zkasm tools and the 29 contracts keep their source form, re-audited for field-wrap arithmetic). We keep owning
   the constraint half of the soundness risk, so every component ships with forgery tests against the node verifier
   (the 2026-10-11 review pattern) before any gate uses it.
4. ~~Fix the fidelity divergence on the live chain~~ — fixed from 160,020, no back-pay (2026-10-10).
5. When to reroll: §5.1 (private payments) needs none — an exec-rules gate, while the pool is empty. A reroll is
   needed only for §5.2/§5.4 (the settlement proof and the exec-root hash), and it uses the carry (§6). Its
   prerequisites and order are §9.5.
6. ~~The tree shape of the BLAKE2s exec root (depth-256 sparse vs compressed)~~ — decided 2026-10-19 by the operator
   after the G1 measurement (doc/stwo/g1-tree-shape.md): **the compressed sparse tree** (a leaf at the shortest unused
   prefix of its key; ~40 compressions per update at a million leaves vs 512 for depth-256; today's busiest span ~4.5 s
   and ~1.5 GB to prove vs ~25 s and ~9.4 GB). Its split/collapse rules ship with their own forgery tests in G2.
7. ~~Whether the reroll waits for a landing Stwo settlement prover (option S) or ships quorum-settled (option R)?~~ —
   decided 2026-10-18 by the operator: **option R**. The reroll ships with the bonded quorum settling the exec root (as it
   effectively does today) and the proof branch refused; Stwo settlement turns on later by a gen-29 gate, no second
   reroll. So what must be FIXED at the reroll is the statement it will prove (root hash, tree shape, position functions,
   call-leaf format, and the records-half design of §9.3 point 3), with a Stwo prototype proving it, not a landing
   prover.

## 8. Risks

- **External dependency in consensus.** A bug in Stwo becomes our bug, and Stwo's API still changes. Mitigation: exact
  pin, gated upgrades, the verifier only (not the prover) in consensus, and our own forgery tests kept against it.
- **"Audited" is not yet true for the core.** Only the stwo-cairo verifier has a public report.
- **WASM proving on low-end phones is unmeasured**; that is what 5.0 is for.
- **The carry is consensus.** A carry bug forks or loses money at genesis. Mitigation: the "loses nothing" test runs
  against the live chain continuously, and rehearsals follow the gen-28 pattern (memory: reroll-rehearsal-lessons).

## 9. Retiring Goldilocks (plan, 2026-10-11)

The operator's decision (2026-10-11): everything built on the Goldilocks field (p = 2^64 − 2^32 + 1) goes — our STARK
stack, `alghash` and `alghash2`, recursion and folds, the wide pool (joinsplit3), the wallet's Goldilocks prover —
replaced by Stwo (Circle STARK over M31) and BLAKE2s, switched at a reroll with the §6 carry. Nothing is deleted
before the reroll. This section is the plan: what depends on the field (read from the code on `next` at 11e751ed,
not from grep hits alone), what replaces each piece, the order, and what is deleted at the end. Counts are `wc -l`
on that tree; live numbers are from this node's own files and journal on 2026-10-11 (read-only).

### 9.1 Inventory: what depends on the field

The field is not only the prover's. It is the **word of the zkVM** (`execnode/zkvm.py`: "every value is a Goldilocks
field element"; ADD/SUB/MUL wrap mod P; LT/DIVMOD/LO32 are windows sized to P), and the zkVM is the only runtime
(`runtimes._REGISTRY` holds one entry). So it reaches contract storage, game clients and two L1 header fields, not
just proofs.

**(a) Consensus state format** — bytes every node must agree on; can change only at a reroll.

| what | where | form today |
|---|---|---|
| exec root | `execnode/exec_root.py` (280) | `alghash2.rnode(KV_ROOT, RECORDS_ROOT)`, both depth-256 sparse alghash2 trees (`storage_tree.py`, 441); pinned `EXEC_GENESIS_ROOT` (protocol.py) |
| KV positions | `execnode/stark/exec_state_bind.py` (309) | `slot_key`/`code_key`/`meta_key` = alghash2 `hashn` of cid limbs + slot, 256 bits |
| record positions | `exec_root.record_key` | alghash2 `hashn([DOM_REC, tag, 5×52-bit limbs])`; leaf values reduced `% P` |
| contract storage | every zkVM contract | slot keys `field·2^32 + key` computed mod P; values are field elements |
| owner encoding | `runtimes.zkvm_addr_digest` | `blake2b("zkvmaddr", addr) mod P`; the `zk_addrs` registry maps it back |
| chain reads | `runtimes._ZkVM.run`, settle branch | BHASH / BEACON reduced `% P` before a contract sees them |
| in-VM hash | `zkvm.OPS` HINIT/HABS/HR0..HR26/HOUT (30 of 61 opcodes) | the 64-bit `alghash` sponge (27 rounds, width 2); contracts' commit-reveal and every roll `LO32(alghash(x))` |
| asset ids | `state.py:168` | `alghash.hashn([issuer_digest, seed]) % P` (0 assets live) |
| L1 block header | `ops/block_ops.construct_block` → `mldsa_block_auth.auth_root` | `auth_root` = a 64-bit **alghash** fold over the block's authorization leaves, **inside the block-hash preimage**; recomputed in `core_loop` verify. The aggregate-proof path it served is gone (`verify_auth_proof` returns False) |
| L1 exec summaries | `calls_commit.block_summary` → `kv_ops.exec_summary_put` | `execsum:<h>` call leaves (alghash2 `entry_leaf`) and records effects; in `meta` but **excluded** from the L1 root (`ROOT_EXCLUDED_META_PREFIXES`) |
| shielded pools | `shielded_field.py` (140, alghash), `shielded_wide.py` (252, alghash2), `shielded_state.py` (515, appnote over alghash) | all empty: 0 commitments in `field_pool` and `shielded` at cursor 168,811; no app-note pool in the live state |

**(b) Consensus verifiers.** The L1 settle branch (`ops/transaction_ops.py` ~2560-2900: `settlement_sparse`,
`calls_commit.verify_calls_bound_to_summaries`, `records_bind.bind_and_verify_records`, run in `ops/proof_child.py`);
L1 exit verifiers (`exec_root.verify_withdrawal/_dividend/_unshield/_outbox_msg`: an alghash2 path of depth 256); L1
`field_shield_check` (wide owners parsed as alghash2 lanes); exec apply of `joinsplit3` / `joinsplit2` bundles
(`joinsplit_transfer.verify_transfer`). The import closure of the L1 entry points is **29 of the 55 modules in
`execnode/stark`, 11,168 lines** (stark, fri, fri_verify, recursion, recursive_verify, comp/rowcomp_verify, air_ir,
backend, extf, transcript, merkle, alghash, alghash2, field, goldilocks_native, stark_native, storage_tree,
exec_state_bind, calls_commit, records_bind/transition, state_transition, io_replay, membership, znote,
mldsa_block_auth, settlement_sparse, native_guard). Native: `native/alghash2` (424 .rs), `wasm/goldilocks` (111 .rs,
loaded as `libgoldilocks.so` by `field.py`), both REQUIRED by `native_guard` and listed in `ops/self_update._CRATES`.

**(c) Prover only.** `execnode/settlement_proofs.py` (615), `vm_circuit.py` (1,314), `merkle_update`, `slot_key_air`,
`state_io_tie`, `state_merge`, `fs_*`, `io_bind`, `deep_eval`, `logup*`, `recursion_depth/_authdepth`,
`recursive_verify_hetero`, `settlement_aggregate`, `bound_epoch_o1`, `zkvm_alghash2`, `soundness` (the model);
`native/starkprove` (2,331 .rs, the LDE arena) and `native/starkcompose` (172 .rs).

**(d) Wallet and clients.** `static/stark/{field,fri,merkle,stark,transcript,tree,bhash,hashing,joinsplit2,joinsplit3}.js`,
`static/alghash.js`, `static/alghash2.js`, `static/vendor/goldilocks-wasm.js` (1,303 lines / 75 KB together);
`static/interface.js` imports all of them for the legacy and wide pools and reads `/status` `proof_rules`;
`static/nadodapp.js` exports `algHashn`/`ALG_P` to **18 game pages and engines** (pets-genes, autogame-engine/-daily,
poker, battleship, coinflip, stormhold, hamster, …), which mirror the contracts' rolls and commitments and replay
carried history with them. Exec endpoints whose wire format is field-shaped: `/exec/field_leaves`,
`/exec/field_shielded`, `/exec/shielded_note`, `/exec/verify_call`, `/exec/settlement`, and the exit-proof
endpoints (packed alghash2 paths; the wallet forwards none of them — no reference in `interface.js`).

**(e) Tests and tools.** 186 files in `tests/` (30,261 lines) touch the field (9.7). Tools: `tools/bench_settle_fri.py`,
`tools/bench_fri_blowup.py` (381), `tools/replay_chain.py`; `scripts/live/_{autogame,cf,faucet,hexholm,stormhold}_e2e.py`;
`scripts/build_native_all.sh`, `scripts/install.sh`, `.github/workflows/ci.yml`, `scripts/run_tests.sh`, `tests/ci_exclude.txt`.

**What `native/mldsa44` says about Goldilocks.** Two doc comments (`src/lib.rs` lines 1 and 11: "matches the Rust
prover pattern in wasm/goldilocks", "same as the Goldilocks lib") naming the build pattern it copied. ML-DSA-44 has no
field dependency on Goldilocks (its own ring is mod 8,380,417), the crate links nothing from `wasm/goldilocks`, and
nothing changes in it except those two comments at the deletion. `execnode/stark/mldsa_block_auth.py` is the module
that does depend on the field (the header `auth_root` above).

### 9.2 What replaces each, and what the carry re-encodes

| category | replacement | carry |
|---|---|---|
| exec root, positions | BLAKE2s-256 everywhere: `root = H(dom, kv, rec)`; `slot_key = H(DOM_KVPOS, cid, slot)`, likewise code/meta/record keys; leaves `H(dom, pos, value)`. Python `hashlib.blake2s` in the node (no crate); the same function as a Stwo Blake component in the settlement circuit | recomputed by a fresh node from the carried storage; the result is pinned as the new `EXEC_GENESIS_ROOT` (§6.2) |
| tree shape | **frozen at the reroll, so decided before it**: depth-256 sparse (today's shape, 256 compressions per path per side in-circuit) or a compressed sparse tree (path ≈ log2 of live leaves). Exit proofs, the settle statement and `exec_genesis` all follow it | — |
| VM word and hash | decided by 9.4 (route A: our VM re-specified; route B: Cairo) | 9.4 |
| owner digests in storage | under either route an owner becomes ≥ 128 bits of BLAKE2s (route A: a multi-limb word; route B: a felt252) | **359 slot values** are owner digests (bet 308, slots 34, dice 10, autogame 2, pets 2, hamster 1, tictactoe 1, roulette 1) and **2 slot keys** contain one (`field·2^32 + d mod P`, found with field ids 0-63); remapped through `zk_addrs` (164 entries), which crosses re-keyed. Old digest → address → new digest is one table walk, the §6.2 hook pass |
| hash-valued storage | — | **12 further values ≥ 2^32** (slots 3, hamster 5, pets 3, faucet 1) are commitments, pins or seeds. Rule for a hash change: **anything a future call will hash is in flight**, even if at rest under a same-hash reroll — refund or rebase it through the existing `carry_in_flight` / `carry_rebase` hooks; never carry a value whose meaning was "alghash of something" |
| client-side history | game clients replay carried runs (autogame legs, pet rolls) from stored values with `algHashn` | either keep `static/alghash.js` (2.5 KB, non-consensus) frozen as a "carried history" decoder, or close those runs in the carry. Operator's call per game; the deletion list (9.7) assumes the first |
| `auth_root` | `blake2b` fold of the same leaves (`hashing.blake2b_hash`), same header field, or drop the field. Recommended: keep the field, change the hash — one function, no header-shape change | none (header of new blocks only) |
| execsum leaves | the new settle statement's call leaves (BLAKE2s) | none (excluded from the root, rebuilt from block 1) |
| exit verifiers | BLAKE2s path verify, `hashlib`, depth per the tree decision | pending exits fold into L1 at the carry, as today |
| shielded pools | the Stwo pool (§5.1) is the only pool | legacy, wide and app-note pools must be empty at the carry (they are; the carry already refuses otherwise, §6.4b) |
| asset ids | `H(dom, issuer, seed)` as 64-hex, a different shape from the carried decimal ids, so no collision by construction | carried verbatim (0 today) |

### 9.3 Settlement proofs do not land, and what that changes

Measured from this node's `nado-exec` and `nado` journals for the 7 days to 2026-10-11: **5** settle-with-proof
bundles built (8.83 MiB each, inline) and **4** resubmissions; **17** spans skipped because the records half moved and
could not be proven (the collect-dividend refusal of memory `settle-proof-landing`, still open); on L1, **14** KV-half
verifications on this node passed in 14.7-87.8 s, **1** verify child was killed (rc −15), and **2** candidates were excluded with
"pre_root must extend the settled tip" — a quorum settle had already moved the tip. `/get_settled` does not say whether
a cursor settled by proof or by quorum, so how many of the 5 landed is not readable without opening the node's
database; in every case the bonded quorum reached the same cursor within minutes. **The quorum is what settles the exec
root today.**

Consequences for the plan:

1. **The Stwo settlement prover is not on the reroll's critical path.** Retiring the Goldilocks prover at the reroll
   removes a path that settles almost nothing. The reroll can ship with quorum settlement and the proof branch
   refused (one gate keyed like `STWO_POOL_HEIGHT`: `STWO_SETTLE_HEIGHT = (1 << 62) if CHAIN_GENERATION == 28 else 0`, off across the reroll), and the Stwo settlement turns
   on later when a protocol commit sets that gate to a height on generation 29 — no second reroll — **provided the statement it will prove
   is fixed by the reroll**: the root hash, the tree shape, the position functions and the call-leaf format. Those
   are (a)-class and cannot change after.
2. So what must exist before the reroll is a **Stwo prototype that proves one sparse-path update and one call of each
   opcode class under the frozen formats**, measured; not a landing prover.
3. The records-half refusal (collect_dividend's amount and nonce are exec state, not calldata) has to be designed into
   the new statement from the start, not ported: it is the reason 17 of 22 attempts in the window were never submitted.
4. The interim loses the trustless path in principle (SETTLE_PROOF_TRUSTLESS), and that is a real reduction while it
   lasts; it is the operator's call whether the reroll waits for a landing Stwo prover instead (strict order, 9.5
   option S).

### 9.4 The open decision: how contracts are proven

Both routes need the 9.2 hash and carry work. They differ in what proves a contract call and who maintains it.

**Route A — hand-written Stwo components for our zkVM.** Keep the ISA idea (registers, SLOAD/SSTORE/PAY io log,
zkpy/zkasm front-end) and re-specify the word: M31 cannot hold amounts (1 NADO = 10^10 raw), so the word becomes
limbs (e.g. 4×16-bit, range-checked by lookup) with checked integer arithmetic instead of mod-P wrap, sound
comparisons over the whole word (retiring the `RANGE; RANGE; LT` 2^62 idiom), and one BLAKE2s-compression opcode in
place of the 30 alghash round opcodes. Components: CPU (one row per step), storage/io bus (LogUp), Blake (from
`native/stwo_js`), range checks, the sparse-path updates and the records transition.
- Cost, measured where possible: rewrite `vm_circuit.py` (1,314) + `settlement_sparse` (645) + transitions
  (`records_transition`, `state_transition`, `merkle_update`, 843) as Rust components. The one comparable we own,
  `native/stwo_js` (2,547 .rs for one fixed statement, landed in one day's commits on 2026-10-11 with the phase-0 prototype behind it),
  suggests **3-5× that: ~8-12k lines of Rust**, plus `zkvm.py` (537), `zkvmasm.py` (175), `zkpy.py` (495) re-specified,
  and **all 29 game builders (12,584 lines) re-audited** for arithmetic that relied on field wrap, with their 18 client
  mirrors moved to BLAKE2s.
- What it keeps: our VM AIR — the class of self-written soundness code that §1 lists every failure in. Stwo removes
  the FRI/PCS/transcript half of that surface; the constraint half stays ours.

**Route B — Cairo programs proven by stwo-cairo.** Rewrite the contracts in Cairo; the exec layer runs the Cairo VM
(or the settler does, with the exec node replaying the io log as today); the node verifies a stwo-cairo proof with
StarkWare's verifier (the part zkSecurity reviewed).
- Cost: **29 contracts rewritten in Cairo** (the 12,584 Python-builder lines are mostly zkasm text, so this is a
  rewrite, not a port), the exec runtime adapter (`runtimes.py`, `state.py` call path), the game clients' mirrors
  (to whatever hash the Cairo contracts use; BLAKE2s keeps 9.2 uniform), a pinned Scarb/Cairo toolchain on the
  settler, and the developer story (Cairo instead of zkpy). Deleted on top of route A's list: `zkvm.py`, `zkvmasm.py`,
  `zkpy.py`, `zkvm_examples.py` (1,265).
- What it buys: the VM AIR is maintained and attacked by others; felt252 holds every 64-bit value and a 251-bit
  owner digest, so the carry re-encodes owners once and never again.
- To check before choosing (entry measurement of 9.5 G1): that stwo-cairo at the pinned revision proves a BLAKE2s
  opcode/builtin, the settler's peak memory for one representative span (the frontier's privacy proof is 1.81 GiB),
  and whether the verifier builds on stable rustc for the fleet (the `native/stwo_js` split of §5.1).

Not presented as a route: keeping mod-P word semantics and emulating them in M31 limbs. It would carry storage
untouched, but it keeps Goldilocks as the VM's arithmetic, which is what the decision retires.

### 9.5 Phases

Each phase has an entry measurement (it decides whether and how the phase runs) and an exit test (it decides that the
phase is done). Nothing below changes the live chain until G7, except where a dormant gate is named.

| phase | entry measurement | work | exit test |
|---|---|---|---|
| **G0 census** (done 2026-10-11, this section) | — | inventory 9.1, live storage census 9.2, settle census 9.3 | numbers recorded here; rerun at G7 |
| **G1 route + tree** (done 2026-10-19: route A, compressed tree; doc/stwo/g1-tree-shape.md) | stwo-cairo checks of 9.4; a Stwo prototype proving N depth-256 BLAKE2s path updates vs a compressed tree, on the settler; the busiest real span's touched-slot count (from DA) | operator chooses route A or B and the tree shape | the decision written into §7; prototype numbers in doc/stwo/ |
| **G2 BLAKE2s commitment** (in progress 2026-10-19: tree, exec root, exits, `auth_root` and the gate done, dormant — see the note under this table) | none beyond G1 | new `exec_root`/positions/records/exit verifiers/execsum leaves/`auth_root`, behind `BLAKE_EXEC_HEIGHT = (1 << 62) if CHAIN_GENERATION == 28 else 1` (GATE LEDGER, doc/reroll.md, test_gate_reroll_transfer) | gen-28 roots byte-identical (dormant); on a gen-29 tree: the carried root recomputed equally on two machines, every pending exit verified by the new path verifier, forged path/position refused |
| **G3 contract runtime** (word decided 2026-10-19: 256-bit wrapping, doc/stwo/g3-vm-word.md) | route from G1 | A: new word + BLAKE2s opcode in `zkvm.py`, zkpy/zkasm, 29 builders, game clients; B: Cairo contracts + runtime adapter | every contract's reference-model test passes on the new runtime (the autogame/pets three-implementation pattern), `test_every_opcode_is_provable` replaced by its route-A/B form, games walked in a headless browser at 412 and 360 px |
| **G4 Stwo settlement statement** | G1 prototype numbers | statement (pre/post root, call leaves, chain reads, records effects incl. collect_dividend from authenticated pre-state), verifier crate on stable rustc behind `native_guard`, prover on the settler | the forgery suite ported from today's settle tests (wrong pre-root, cid_io, chain-read substitution, PAY/asset io, records shift, counterfeit code) refused by the new verifier; an honest span verifies; verify time and proof size measured |
| **G5 carry re-encoding** | rerun census | extend `tools/alphanet6_carryforward.py` (→ `tools/carry.py`, §6.5): owner digests and digest keys remapped through `zk_addrs`, hash-valued slots refunded/rebased, assets, registry re-keyed, new genesis root pinned, all pools empty | "a reroll loses nothing" (§6.5) on the live chain, plus: no slot value or key equal to an old digest remains; the remapped digest count equals the census; a carried pet, battle and autogame run playable on a loopback testnet from the carried genesis |
| **G6 wallet** (built 2026-10-25, below the table) | — | Stwo pool only; drop legacy/wide UI, `proof_rules` read, alghash2/stark imports; nadodapp hash swap; i18n for any string touched | `node tests/i18n_coverage.mjs`; deposit, private send, unshield walked as a user on the testnet from the served URL (CLAUDE.md rule 6); a stale tab refused cleanly |
| **G7 reroll (generation 29)** | fleet `status_pool` uniform; oldest fleet rustc ≥ Stwo's (needs the `/status` field of §5.1 first) | `CHAIN_GENERATION` bump, doc/reroll.md runbook, the gen-28 rehearsal pattern (full suite + testnet + headless walk on the gen-29 tree) | fleet on one genesis; exec root equals the pinned constant on every exec node; first quorum settle lands; exits claim |
| **G8 Stwo settlement on** | 2 weeks of the G4 prover producing verifying proofs against live gen-29 spans, off-chain | `STWO_SETTLE_HEIGHT` set at the fleet's adoption block (CLAUDE.md rule 3) | proofs land; L1 verify time measured on the slowest fleet node |
| **G9 deletion** | gen-29 chain replayed block for block on the deletion tree (the gen-27 cleanup recipe) | 9.7 | same hashes and roots at every height; pyflakes zero; `test_no_undefined_names`; suite green |

**G2 status (2026-10-19).** Done behind the dormant `BLAKE_EXEC_HEIGHT` (2^62 on gen 28, 1 on gen 29, genesis cursors
and block 0 included): `execnode/csmt.py` (the compressed tree), `execnode/exec_root_b2.py` (the exec root, leaf for
leaf with today's — exact parity on a copy of the live state at 274,000: 2,143 KV and 116 record leaves; cold root
0.06 s against 12.2 s), the exec node's root, ring and exit proofs, L1's four exit verifiers keyed on each settled
root's own cursor, `auth_root` as a BLAKE2s chain, and option R (L1 refuses a Goldilocks settle proof or stark auth
evidence for a BLAKE2s root; the settler never builds one). **The calls commitment needs no G2 change:** the leaves L1
persists per block (`block_summary`) are already BLAKE2b digests of the canonical call; only their FOLD is alghash2,
and it runs only in settle-with-proof validation, which the gate refuses. G4 defines the Stwo fold over the same
leaves. Left in G2: the carry's exec genesis in the new format (with G5) and the positions' in-circuit form (with G4).

**G8 status (2026-10-28).** L1's side is built behind the DORMANT `STWO_SETTLE_HEIGHT` (`1 << 62` on gen 29): the `stwo`
settle field, its validation from L1's own blocks and chain inputs (`ops/settle_chain.py`, measured equal to the exec
node's bookkeeping on blocks 0..10533), the proven marker on apply, the exec node's prover wiring, and `chain_eq` in the
shadow run. What the operator does to turn it on, and the one known limit (the boundary carry chain), are in
doc/stwo/g4-settlement-statement.md section 5.

**G6 status (2026-10-25).** Built, no consensus change:
- **Stwo pool only.** The legacy, field and wide pools were measured EMPTY on the live chain (0 commitments,
  `pool_value` 0) and are closed on both layers, so the wallet dropped them: no alghash/alghash2/joinsplit2|3/stark
  imports, no `/status.proof_rules` read, no wide/legacy zaddr forms, deposits and spends Stwo-only, and a page that
  cannot load the Stwo prover stops instead of falling back (tests/test_the_wallet_builds_only_stwo_notes.mjs). A spend
  is restored only by its nullifier (the 20-minute wall-clock rule of the old pools is gone). The retired files stay
  until G9, with the node verifiers whose crosscheck tests pin them.
- **A stale tab is refused.** A page signs only for the chain of the `/protocol.js` it loaded (`PAGE_CHAIN`): a relay
  on another chain is never adopted, nothing is submitted while the current relay is on one, and the page reloads by
  itself when idle once its own origin serves the new chain. Game pages name their chain in every signing request
  (nadodapp `_payloadOf`); the wallet refuses one for another chain, and on gen 29 one that names none
  (tests/test_a_stale_tab_never_signs_for_a_rerolled_chain.mjs).
- **Carried game records** (doc/stwo/g5-carry.md 2c): the pets combine preview reads the whole gene, and history
  displays redraw a record only when the redraw reaches its stored result.
- **Still owed for the exit test:** deposit, private send and unshield walked as a user from the served URL. The Stwo
  pool opens at 269000 on gen 28, so a loopback testnet (which starts at block 0 under gen-28 constants) has no pool to
  walk; the walk belongs to the G7 rehearsal on the gen-29 tree, where the gate is 1. **Walked 2026-10-26** — see below.

**G7 rehearsal (2026-10-25/26, branch `g7-rehearsal`, not for main).** On a gen-29 tree built from a copy of live data:
- **Entry:** fleet `status_pool` uniform; oldest fleet rustc 1.97.1 (Stwo needs ≥ 1.85).
- **Carry** (exec cursor 363091): the contract carry refuses while 8 games are in flight — dice table 587750730 (3
  open bets), hamster races 23228486 / 347893550 / 79590186, autogame runs 251596310 / 650227869. On the copy they clear
  with permissionless calls (dice `reclaim` x3, hamster `void` x3, autogame `advance` x2); **on the live chain those
  are 8 transactions the operator must send before the real carry.** Then: 27/27 contracts carried (2,195 slots), L1
  Δ = 0 on 204,992,396,024,029 raw, 1,097 accounts, 951 identities, 264 device bindings, 130 aliases, 2 open invites
  (= INVITE_ESCROW), the Stwo pool. A node boots from the carried genesis with exactly that supply.
- **Suite** on the gen-29 tree: 61 failures, all fixed — 60 were tests reading a gate's gen-28 value as the shipped one
  (they now pin it, `tests/_harness.gate_at/pinned`; doc/reroll.md failure mode 10) or building a test genesis that
  inherited the real carried files (`NADO_GENESIS_CARRY` / `NADO_EXEC_GENESIS`); one was real (faucet's v1 source
  baked the running generation's digest, so `build("v1")` could not assemble on gen 29). 657/657 then.
- **Walks** (headless Chrome, loopback testnet): the signature-scheme walk (`scripts/testnet/test_scheme_wallet.py`)
  and the two-user Stwo walk with exec nodes and the settle quorum (`scripts/testnet/test_shield_wallet.py`: deposit,
  private send, receive, withdraw with no public NADO, quorum settle, claim) — both PASS, confirmed on every node.
  **This is G6's exit walk and G7's "first quorum settle lands; exits claim".** The walks found four defects, three of
  them in code live on the fleet (the pool never held a note, so none fired): exec nodes never fetched DA from peers
  (L1's `/peers` is an object — every relayed spend would have forked the exec state and frozen settlement); a holder
  with no public NADO could not withdraw ("Proof failed:" with no reason); its fee-exempt claim was refused "Empty
  account" while the wallet said "still settling"; and the wallet assumed every exec node is on :9273 (`/status`
  now advertises `exec_port`). Also fixed: the carry ran its invite refusal only under `--write`, after writing
  `genesis_alloc.dat`; its `--help` ran the carry.
- **Closed since (2026-10-26):** the 8 live game calls were sent and applied (blocks 374706-374707; nothing in flight at
  exec cursor 374760, and the carry dry run on live data at 376003 is Δ = 0 with 27/27 contracts and no refusal); the
  Shield tab follows the pool while open (465cedec).
- **Added for the reroll (2026-10-26, operator decision):** `STWO_JS_128_HEIGHT` — private sends prove at the 128-bit
  node config from block 1 (56 queries and a 16-bit OODS grind: ~129 bits conjectured, where the 340-bit config was
  capped near 113 by its ungrounded OODS term; 75.9 provable; proofs 1.14 MB instead of 2.9 MB). Dormant on gen 28. The final pre-reroll pass (suite + testnet + both walks on the final gen-29 tree) covers it.
- **G7 EXECUTED 2026-10-27** (commit 23b2aa00, betanet-10): every contract carried, the fleet on one genesis within ~3 min,
  the exec root at genesis equal to the carried root on L1 (the first settle landed), invariants Δ = 0 — doc/reroll.md
  "Gen 29 (betanet-10)". G4's landing prover stays off (option R); G8 and G9 follow.
- **G4, the VM component (2026-10-27).** A Stwo proof that a list of zkvm2 calls produces exactly a stated io log
  (doc/stwo/g4-settlement-statement.md section 4 step 3). It is measured on 79 real game calls: 12.4 s to prove, 0.1 s
  to verify, 1.1 MB. Every forged statement and dishonest prover tested is refused.

- **G4, the span settlement (2026-10-27).** A verifier holding no exec state replays a span of L1 blocks through the exec
  node's own transition on a witness of authenticated openings, and checks every contract call against one Stwo proof
  (doc/stwo/g4-settlement-statement.md section 5). On a 239-block span of real game, asset, withdrawal and dividend
  traffic it lands on exactly the exec node's root: prove 6.8 s, verify 0.11 s. Every forgery tested is refused.

  The digest registry is committed in the exec root from `EXEC_ADDR_ROOT_HEIGHT`, so a payout to an address registered
  before the span proves from then on.

  A reverting call is proven too, every one of zkvm2's 13 revert paths.

  The node's verifier builds on stable Rust and every node builds it (an optional crate until the gate).

  Still to build for G4:
  - L1's side of it: the chain inputs from L1's own state, and the settle-tx format and branch behind the gate.

  G8's two weeks of off-chain proofs against live spans start only after all of that is built.

**Order.** G1 before G2 (the tree shape is part of the root). G2 and G4's statement before G5 (the carry pins a root
in the final format). G3, G5, G6 before G7. G4's landing prover and G8 after G7 (option R, recommended by 9.3), or
before G7 (option S: the reroll waits until proofs land on a testnet; slower, keeps the trustless path continuous).
G9 right after G7 is safe for consensus — a gen-29 node never verifies a gen-28 block — and the gen-28 verifier stays
reachable in git history for `tools/replay_chain.py` against an archive of the old chain.

**Size, from the counts above.** New: G2 ~0.6-0.9k lines Python (it replaces 2,806 lines of field-specific
commitment code with hashlib), G4 ~8-12k Rust (route A) or the runtime adapter plus verifier embedding (route B),
G3 the 29 contracts (re-audit or rewrite of 12,584 lines) and 18 client files, G5 a hook pass over 8 contracts
holding digests. Deleted: ~21.2k lines of code and 9.9k of tests (9.7).

### 9.6 Risks

- **The tree shape is permanent.** Depth-256 BLAKE2s paths cost 256 compressions per side per touched slot in-circuit;
  choosing it without the G1 measurement could make the settlement prover too slow to ever land, and only a reroll
  undoes it.
- **Route A keeps our own constraint system.** Every §1 finding except FRI/transcript ones would still be possible in
  a hand-written VM AIR. Mitigation: the G4 forgery suite and an outside review before G8.
- **The carry touches money-bearing storage.** 359 digests in bet, slots and dice tables sit next to open stakes. A
  missed digest leaves a payout that reverts (`split_io` cannot resolve it); the exit test checks for zero residue,
  and a slot the hooks cannot classify refuses the carry rather than guessing.
- **Client history.** Clients that replay carried runs need the old hash; deleting `static/alghash.js` too early
  breaks the display of carried state, not consensus.
- **Toolchain.** Stwo is fetched from git and pins a nightly; fleet nodes build on stable without our root (§5.1).
  A node that cannot build the verifier must stall, never skip (tests/test_a_node_without_the_stwo_verifier_stalls_instead_of_skipping.py
  is the pattern).
- **Left-over build products.** Deleting `native/alghash2`, `starkprove`, `starkcompose`, `wasm/goldilocks` leaves
  untracked `target/` and `.so` files on every node; harmless unless a later commit tracks a file at one of those
  paths (memory: untracked-file-bricks-fleet-fastforward). Remove them from `_CRATES` and the staleness checks in the
  same commit, never reuse the paths.
- **Interim without trustless settlement** (option R): the exec root is quorum-settled only, as it effectively is now.

### 9.7 Deletion list (G9)

Line counts are `wc -l` of tracked files at 11e751ed.

**Code, deleted outright (~21.2k lines):**
- `execnode/stark/` except `stwo_js_native.py` and `native_guard.py` (move both to `execnode/` or `ops/`; `signatures.py`
  and `ops/attest_native.py` import `native_guard`) and the eight modules rewritten under BLAKE2s in G2
  (`exec_state_bind`, `storage_tree`, `calls_commit`, `records_bind`, `records_transition`, `state_transition`,
  `state_merge`, `mldsa_block_auth` — 2,806 lines replaced): **45 files, 14,493 lines** (air_ir, alghash, alghash2,
  appnote_circuit, backend, bound_epoch_o1, comp_verify, deep_eval, extf, field, fri, fri_verify, fs_chain,
  fs_incircuit, fs_step, goldilocks_native, io_bind, io_replay, joinsplit, joinsplit2, joinsplit3, joinsplit_circuit,
  joinsplit_transfer, logup, logup_bind, membership, merkle, merkle_update, recursion, recursion_authdepth,
  recursion_depth, recursive_verify, recursive_verify_hetero, rowcomp_verify, settlement_aggregate,
  settlement_sparse, slot_key_air, soundness, stark, stark_native, state_io_tie, transcript, vm_circuit,
  zkvm_alghash2, znote).
- `execnode/settlement_proofs.py` (615); `execnode/shielded_field.py` (140), `shielded_wide.py` (252),
  `shielded_state.py` (515) — and with them the phase-1 blake2b pool `execnode/shielded.py` (328) and
  `static/shielded.js` (99), which are not field code but serve only the retired legacy pool.
- `native/alghash2`, `native/starkprove`, `native/starkcompose`, `wasm/goldilocks` (3,121 lines with manifests and
  locks; 3,038 of Rust).
- `static/stark/{bhash,field,fri,hashing,joinsplit2,joinsplit3,merkle,stark,transcript,tree}.js`, `static/alghash2.js`,
  `static/vendor/goldilocks-wasm.js` (1,303 lines with `static/alghash.js`, 75 KB); `static/alghash.js` only once no
  carried run needs it (9.2).
- `tools/bench_settle_fri.py`, `tools/bench_fri_blowup.py` (381).
- Route B adds `execnode/zkvm.py`, `zkvmasm.py`, `zkpy.py`, `zkvm_examples.py` (1,265).
- Edited, not deleted: `ops/self_update._CRATES` and the goldilocks special case, `ops/transaction_ops.py` settle and
  shield branches, `ops/proof_child.py`, `execnode/execnode.py` endpoints, `execnode/state.py` pool wiring,
  `runtimes.py`, `protocol.py` (proof-rule constants, `EXEC_GENESIS_ROOT`), `scripts/build_native_all.sh`,
  `scripts/install.sh`, `.github/workflows/ci.yml`, `scripts/run_tests.sh`, the two comments in `native/mldsa44`,
  and the docs that describe the retired stack (`zk-recursion`, `zk-execution-proofs`, `zk-components`, `fri-parameters`,
  `wasm-prover`, `privacy`, `zk-glossary`, `settle-proof-transport`, `rust-only-proving`, `shielded-contracts`), each
  marked historical or rewritten.

**Tests (186 files, 30,261 lines touch the field):**
- **Retire, 83 files / 9,862 lines** — their subject is deleted: the STARK/FRI/recursion/fold/AIR tests (`test_stark*`,
  `test_fri*`, `test_recursion*`, `test_recursive_*`, `test_comp_verify`, `test_rowcomp_verify`, `test_air_ir`,
  `test_deep_eval`, `test_fs_*`, `test_io_bind*`, `test_logup_bind`, `test_merkle_update*`, `test_starkprove`,
  `test_native_reduce`, `test_native_prover_verifies`, `test_proof_*` rule tests, `test_settle_*fold*`,
  `test_settle_recursive_gate`, `test_settle_row_commit_default`, `test_settle_prover_sim`, `test_settlement_o1`,
  `test_settlement_aggregate`, `test_slot_key_air`, `test_state_io_tie`, `test_zkvm_circuit`, `test_zkvm_epoch`,
  `test_zkvm_alghash2`, the joinsplit/membership/wide/appnote tests, the JS cross-checks `joinsplit{2,3}_js_crosscheck.*`,
  `starkjs_crosscheck.sh`, `test_alghash_js_matches_python.mjs`, `test_wallet_air_digest_fits_a_small_stack.mjs`,
  `test_zbill_delivery.js`).
- **Rewrite against the new formats, 41 files / 6,505 lines** — the property survives, the encoding changes: the
  settle-with-proof and binding tests (`test_settle_with_proof`, `test_settlement_sparse`, `test_settle_cid_io_binding`,
  `test_settle_multiblock_da`, `test_records_bound_settle`, `test_prover_records_half`, `test_proof_bind_gate`,
  `test_calldata_binding_is_wide`, …) become the G4 forgery suite; `test_exec_root*`, `test_storage_tree`,
  `test_state_transition*`, `test_records_*`, `test_mldsa_block_auth`, `test_calls_commit`, `test_exec_summary_binding`
  move to BLAKE2s; `test_every_opcode_is_provable` and `test_review_round2` / `test_zk_review_2026_09_24` keep their
  attack cases against the new verifier; `test_self_update_stale_native` / `test_native_report` follow `_CRATES`.
- **Port, 62 files / 13,894 lines** — game, exec, carry and Stwo-pool tests that use the field incidentally (rolls,
  digests, reference models): `test_games_e2e`, the pets/autogame/holdem/dice/mines/coinflip lifecycle tests,
  `test_zkvm*` runtime tests, `test_assets`, the carry tests, `pets_ref.py`, `opcode_programs.py`. Route B rewrites the
  game ones with the contracts.

## Sources

- Stwo: https://github.com/starkware-libs/stwo (README: license, field, backends, production status, audits)
- S-two on Starknet mainnet: https://www.starknet.io/category/decentralization-governance/
- zkSecurity, audit of the stwo-cairo verifier: https://reports.zksecurity.xyz/reports/starkware-stwo-cairo
- Circle STARKs: Haböck, Levit, Papini (2024)
- provably.fast frontier: https://github.com/starknet-innovation/proving/tree/provably-fast-frontier
