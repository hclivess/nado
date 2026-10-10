# Stwo migration, and a reroll that carries everything

Status: **proposal, 2026-10-10.** Nothing here is in consensus yet. Each phase below starts with a measurement, and that
measurement decides whether the phase happens. The proving system and the reroll date are the operator's decisions.

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

### 5.1 Shielded join-split on Stwo (first, while the pool is empty)

The pool holds **0 commitments and 0 nullifiers** today (read from `exec_state.json`, 2026-10-10), and the shield escrow
holds 1,123,000 raw (residual dust). A new pool started at the reroll therefore migrates nothing. Every note created
before the switch makes this phase harder (6.4), so it should go first.

- A new circuit in a `native/stwo_joinsplit` crate, built for the node (verify) and for WASM (wallet prove).
- The wallet swaps `static/stark/joinsplit3.js` for the WASM prover. The served artifact is versioned by content
  (ops/static_versions.py), so stale browsers cannot pair an old prover with the new rules.
- Tests: an honest proof verifies; a forgery that passes the legacy rules fails the new ones (the model is
  tests/test_proof_query_full.py); the wallet's WASM proof verifies in the node; and joinsplit3 history replays below
  the gate.

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
| L1 balances and bonded stake (Δ = 0 enforced) | **all contract state**: contract pots are refunded to players or the deployer, game progress is lost, contracts are redeployed under new ids and the frontends rewired |
| uncollected dividends, user bridge balances, pending exits (folded into L1) | **open invites and HTLCs** (refunded to the funder) |
| device bindings, aliases, account-auth config | **the shielded pool**: the carry *refuses* if it is not empty ("have them unshield before the reroll") |
| fidelity, **but only for identities present at the reroll** (47 of the 79 with fidelity at gen 28) | **fidelity of the 32 identities absent at the reroll**, see 6.3 |

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
  seats, open HTLCs) is refunded to whoever funded it. `otc.escrow_refunds` is already this shape. A contract without
  a hook is refunded and reset, exactly as today, so a missing hook is never worse than now.
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
On the live chain this is a consensus change, so it needs a gated epoch. Back-pay for the epochs already paid is the
operator's decision; the precedent (dividend-carried-identities-gap) was no back-pay.

### 6.4 The shielded pool

- **If the pool is empty at the switch** (it is today): the new pool starts empty under the new hash, and nothing moves.
  This is the reason 5.1 goes first.
- **If it is not empty**: owners must move their notes themselves, because nobody else can open them. Keep the old
  join-split verifier for **one** transaction type: a migration spend that proves an old note against the frozen
  carried old root and nullifier set, and creates a note in the new pool. The old verifier's exposure is then bounded by
  the old pool's escrow, and it never closes on unclaimed notes. Funds are never burned, which matches the rule that
  the coins are real.

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
2. Replace alghash2 with Blake2s, the hash Stwo's production circuits prove?
3. Contracts: hand-written Stwo components (5.2), or Cairo programs proven by stwo-cairo (5.3)?
4. Fix the fidelity divergence on the live chain now (gated), and back-pay or not?
5. When to reroll: the switch is cheapest while the shielded pool is still empty.

## 8. Risks

- **External dependency in consensus.** A bug in Stwo becomes our bug, and Stwo's API still changes. Mitigation: exact
  pin, gated upgrades, the verifier only (not the prover) in consensus, and our own forgery tests kept against it.
- **"Audited" is not yet true for the core.** Only the stwo-cairo verifier has a public report.
- **WASM proving on low-end phones is unmeasured**; that is what 5.0 is for.
- **The carry is consensus.** A carry bug forks or loses money at genesis. Mitigation: the "loses nothing" test runs
  against the live chain continuously, and rehearsals follow the gen-28 pattern (memory: reroll-rehearsal-lessons).

## Sources

- Stwo: https://github.com/starkware-libs/stwo (README: license, field, backends, production status, audits)
- S-two on Starknet mainnet: https://www.starknet.io/category/decentralization-governance/
- zkSecurity, audit of the stwo-cairo verifier: https://reports.zksecurity.xyz/reports/starkware-stwo-cairo
- Circle STARKs: Haböck, Levit, Papini (2024)
- provably.fast frontier: https://github.com/starknet-innovation/proving/tree/provably-fast-frontier
