# STARK recursion for NADO — O(1) settlement verification

**Status:** research + implementation (this doc drives `execnode/stark/alghash2.py`, the alghash hash
backend, and `execnode/stark/recursion.py`). Grounded in the *actual* proof stack: `execnode/stark/stark.py`
(the STARK), `fri.py` (FRI), `merkle.py`, `transcript.py`, `alghash.py`, and the execution AIR
`execnode/stark/vm_circuit.py`.

## 1. The problem, precisely

After epoch **segmentation** (`settlement_proofs.prove_settlement`, shipped) an epoch of any size is proven
by **K segment proofs** whose state roots chain `root_0 → root_1 → … → root_K`. That removes the size cap,
but L1 still verifies **K proofs** — verification is `O(K)`, not `O(1)`.

**Recursion** = fold those K proofs into **one** constant-size proof that L1 verifies with a single check,
independent of K (and, ultimately, of history depth). A *recursion proof* is a STARK whose statement is
"I ran the STARK verifier on proofs π₁…π₂ and it accepted, and their roots chain." Applied as a binary tree
(`fold(fold(π₁,π₂), fold(π₃,π₄))…`) it collapses any number of proofs to one root proof.

There is **no sound shortcut**: O(1) aggregation *requires* verifying proofs inside a proof. So the whole
question is: **can the STARK verifier be arithmetized cheaply and soundly?**

## 2. What the verifier actually computes (from `stark.verify` + `fri.verify`)

Per proof, the verifier does exactly:

1. **Transcript replay** (`transcript.py`): a hash chain — absorb each column Merkle root, draw the α
   constraint-combination challenges, then (in FRI) absorb each fold-layer root and draw the fold challenges,
   absorb the final layer, check the grinding PoW, and draw `num_queries` query indices. ⇒ **≈ W + layers +
   num_queries hash invocations**, all sequential.
2. **FRI low-degree test** (`fri.verify`): interpolate the final (small) layer and check its high coefficients
   vanish — pure field arithmetic; and per query, `layers` **Merkle-path openings** (each `log₂N` node
   hashes) plus a **fold-consistency** field computation `g = (lo+hi)/2 + α·(lo−hi)/(2x)`.
3. **Composition spot-check** (`stark.verify` loop): per query, `W` **trace-column Merkle openings** at the
   `lo`/`nxt` rows, recompute the composition polynomial from the opened rows + the verifier's own periodic
   values (field arithmetic over the AIR constraints), and check it equals the FRI layer-0 value.

**Cost shape:** field arithmetic (folds, composition, interpolation) is *cheap* to arithmetize — it is
already field-native. The binding cost is **hashing**: `num_queries × layers × (2 + W)` Merkle node hashes +
the transcript chain. Every one is a hash, and **that is what a recursion circuit must re-execute in-field.**

## 3. The two hard requirements

### 3.0 "But BLAKE2b isn't arithmetizable" — the three options, and which we take

BLAKE2b is ARX (64-bit add / xor / rotate). Three ways to deal with it:

- **Arithmetize it directly** — *possible but ~1000× too costly.* ~1,150 word-ops/compression as 8-bit
  XOR/ADD LogUp lookups ⇒ ~30–60k trace rows per compression; a verifier needs hundreds of Merkle-path
  compressions ⇒ tens of millions of rows to verify one proof. That is why "not arithmetizable" is the
  *practical* truth. Rejected.
- **Swap the hash in the recursed layer** — *the industry-standard move (Plonky2/Poseidon, Miden/RPO,
  RISC Zero/Poseidon2), and what we do.* A byte-oriented hash stays where proofs are verified *natively*;
  anything verified *in-circuit* uses an algebraic hash (`alghash2`, §3.1). ~8 rows per round vs ~30–60k.
- **Hybrid wrap** — *shipped.* Recursion only needs the **inner** proofs algebraic, so:
  `prove_epoch_calls(..., backend=ALGHASH2)` (and `prove_epoch`/`prove_settlement`) emit a **recursion-ready**
  proof whose verification is field-native; a fold circuit consumes those; and the **outermost** root proof
  keeps `blake2b` (the default), so L1 + browsers verify one proof with fast native hashing and conservative
  cryptanalysis at the boundary. `verify_epoch_calls` reads the hash from the proof's `backend` tag, so a
  mixed batch just works. Tested: an execution-AIR epoch proof under alghash2 verifies field-natively and a
  forced-blake2b verifier rejects it.

### 3.1 The hash must be arithmetization-friendly *and* sound

Today `merkle.py`/`transcript.py`/`fri.py` use **BLAKE2b**. BLAKE2b is byte-oriented — expressing one
invocation as field constraints costs thousands of gates, so a recursion circuit over BLAKE2b Merkle paths is
hopeless. The verifier's hash must be an **algebraic** hash (a Poseidon/Rescue-class sponge) whose round
function *is* field arithmetic — then a Merkle-path hash is a handful of `x^7` S-boxes + an MDS mix, which the
AIR already knows how to constrain (the execution AIR's `HR0..7` sponge rows do exactly this for `alghash`).

But the current **`alghash` is width-2, capacity 1** — a **64-bit digest ⇒ ~32-bit collision resistance**
(birthday). That is fine as an in-VM *convenience* hash (a game deriving a card) but **unsound as the
commitment hash of a proof we recursively verify**: a ~2³² Merkle collision lets a cheating prover open a
leaf two ways and forge the inner proof. So recursion needs a **wide-sponge algebraic hash** with a ≥256-bit
capacity (≥128-bit collision resistance). → `alghash2` (§5.1): a **width-12 sponge, rate 8 / capacity 4**
(4 × 64 = 256-bit capacity), Poseidon-style (`x^7` S-box, MDS mix, full rounds), nothing-up-my-sleeve
constants. Digest = the first 4 rate elements (256 bits).

*(Demonstration round count, like the existing `alghash`; a production deployment pins audited Poseidon2/RPO
round counts. The arithmetization technique — and this whole pipeline — is identical either way.)*

### 3.2 The verifier circuit must fit a provable trace

`num_queries × layers × (2+W)` hashes is large at production parameters (64 queries, ~17 layers, ~100
columns ⇒ >10⁵ hashes ⇒ millions of trace rows). Two levers make it tractable:

- **Recursion parameters are small by choice.** The *inner* proofs being folded can use a **reduced query
  count** (soundness is topped up by grinding + the recursion depth), shrinking the verifier trace by ~10×.
- **The verifier is itself segmentable.** If one fold doesn't fit `MAX_T`, it splits — but the whole point is
  that at the *root* of the tree, one fold must fit one trace. Choosing inner parameters so `verify(2 proofs)
  ≤ MAX_T` is what makes the fold terminate at a single O(1) proof.

## 4. Design chosen: a **verifier AIR** proven by the existing STARK framework

Two ways to arithmetize the verifier:

- **(A) In-zkVM** — write the verifier as a **zkasm** program and `prove_call` it (reusing the execution AIR).
  Pro: maximal infra reuse; the execution AIR already arithmetizes the `alghash` sponge. Con: the general VM
  pays overhead per hash (~10 rows/`alghash` via `HINIT/HABS/HR0..7/HOUT`), and Merkle-path loops are awkward
  in raw asm. **`zkpy` (the new Python→zkasm compiler) makes writing it tractable** and clobber-safe.
- **(B) A dedicated recursion AIR** — a purpose-built column layout + constraints that check Merkle paths /
  folds / composition directly. Pro: ~5–10× fewer rows than the general VM. Con: a large new AIR to audit.

**We take (A) for the first working fold** (correctness + infra reuse + `zkpy` safety), and keep (B) as the
throughput optimization once the Rust prover (the ~10× lever) lands. Both prove the *same statement*, so the
choice is performance, not soundness.

## 5. Implementation status (this repo)

**Shipped + tested (`tests/test_recursion.py`):**

1. ✅ **`alghash2.py`** — the wide-sponge algebraic hash (§3.1): width-12, rate-8/capacity-4, 256-bit digest.
   Tests: MDS linear layer is invertible (a bijection), ~48%-avalanche, deterministic + domain/length
   separated, no collisions across 8000 structured digests.
2. ✅ **Native Rust accelerator** (`native/alghash2/`, a `cdylib` bound by ctypes) — the permutation/sponge
   on the recursion hot path, **bit-identical** to the Python (Python hands it the same RC/IV/MDS at init;
   verified over 2000 random inputs) and **~20× faster** (26k hashn/s). Falls back to pure Python if unbuilt.
   This is the "use Rust for provers" lever, applied where it matters — the algebraic-hash inner loop.
3. ✅ **Hash backend** (`backend.py`) — `merkle.py`/`transcript.py`/`fri.py`/`stark.py` are parameterized by
   `backend ∈ {blake2b (default, byte-identical to today), alghash2}`. Existing blake2b proofs are
   regression-guarded (`test_stark`, `test_settlement_proof` unchanged); an **alghash2-STARK proves +
   verifies + rejects a tampered proof / a cross-backend proof** — the same FRI/STARK code, a different hash,
   so **an inner proof's verification is now field-native** (the precondition for recursion).
4. ✅ **The core recursion gadget** (`recursion.py`, `prove_preimage`/`verify_preimage`) — an AIR that
   arithmetizes the alghash2 permutation (one round per row, degree-7 transition, RC as public periodic
   columns) and proves **knowledge of a hash preimage in-circuit**: the in-circuit digest equals the native
   `alghash2.leaf`, the proof verifies, and a wrong digest / tampered trace are rejected. This is the atomic
   hashing-in-circuit unit a full verifier repeats.

**The verifier circuit — both halves built, verifier-authoritative, tested:**

5. ✅ **FRI low-degree half** (`fri_verify.py`, `tests/test_fri_verify.py`) — `prove_fold`/`verify_fold` fold a
   batch of FRI proofs into ONE recursion STARK: membership (siblings-as-witness) + fold-consistency
   `2·x·nxt = x(lo+hi)+α(lo−hi)`, chained across layers and pinned to the public final. The VERIFIER re-derives
   the whole statement from the committed roots (`_canonical_public`: geometry, Fiat-Shamir α, query indices,
   grinding, the final-layer low-degree test), builds the AIR periodic + boundaries itself, and the query
   strength is the verifier's own policy (defaults to `fri.NUM_QUERIES`, never read from the prover's bundle).
   Tests: honest folds verify; a high-degree proof is refused + rejected; tampered root/grind/final and any
   sub-protocol query count are rejected; a naive verify demands full protocol strength.
6. ✅ **Composition (trace↔constraints) half** (`comp_verify.py`, `tests/test_comp_verify.py`) — `prove_comp`/
   `verify_comp` prove, per query point, that the opened trace columns are Merkle-authenticated under the
   segment's committed column roots AND recompute the composition **by evaluating the constraint-IR (`air_ir`)
   in-circuit** to a public layer-0 target. Same verifier-authoritative discipline (siblings-as-witness,
   verifier builds the schedule). Generic over the AIR: the 1-column x² demo and the W=106 execution AIR share
   the code path — only W and the program differ (2W+16 ≤ `MAX_COLUMNS`=256 fits the execution AIR). Tests:
   honest binding verifies; a FALSE layer-0 target is rejected (the binding is authoritative); a value not in
   the committed column tree is rejected by membership; **and it binds a GENUINE `stark.prove(x², backend=
   RECURSION)` proof — every FRI query's Merkle-opened trace columns recompute in-circuit to that query's real
   FRI layer-0 value** (the exact `stark.verify` spot-check, done inside a recursion proof). So both halves now
   run against real proofs, not hand-built values.

**What remains (no new soundness primitive — assembly + throughput + one optimization):**

7. ✅ **Combine the halves — and collapse K→1** (`recursive_verify.py`, `tests/test_recursive_verify.py`).
   `prove`/`verify` take ONE proof or a LIST of K (chained segments): one fold + one comp bundle covers all of
   them (comp points carry per-proof column roots). The verifier reads only each proof's SMALL PUBLIC PART
   (`public_part`: geometry, column roots, FRI roots/final/pow, the declared per-query layer-0 values) — never
   openings or paths — re-derives every proof's Fiat-Shamir challenges AND query positions itself, and builds
   both public statements. **The seam is in-circuit-validated**: the declared layer-0 value is handed to comp as
   the composition target AND pinned as a boundary on the fold's CLO carry, whose leaf-selector ties it to the
   Merkle-authenticated layer-0 opening — so a declared value that isn't the committed one cannot satisfy the
   fold's membership (this closed a real gap: the value used to be trusted from the proof). Both halves passing
   ⇒ every committed trace satisfies the AIR and its composition is low-degree ⇒ = K× `stark.verify`, proven via
   ONE bundle. Tests: an honest K=3 chain verifies from public parts; wrong AIR, fold-root mismatch, tampered
   layer-0 seam, and a lied segment seed are each rejected.
7b. ✅ **The execution AIR (two-phase, W=106) — via ROW COMMITMENT.** `stark.prove(..., row_commit=True)`
   (RECURSION backend) commits LDE ROWS instead of columns: one recursion-Merkle tree per phase whose leaf j =
   `alghash2.rrow(row j)` (hashn-style multi-chunk absorption), so a query opens whole rows with ONE path per
   tree — 4 paths per spot-check point instead of 2·106, which is what makes the wide AIR recursable.
   `rowcomp_verify.py` is the row-mode composition gadget: in-circuit leaf absorption (the pinned hashn frame +
   per-chunk carry injection) chained into the node path (witness sibling + IACC-pinned direction), generic over
   groups (main/aux trees) and LogUp challenges (PCHAL). `recursive_verify` detects the mode, replays the
   two-phase transcript (main root → β,γ → aux root → α's), evaluates the AIR's own periodic columns at each
   FS-derived point (per-proof `periodic_list` — the execution AIR's program/args/io tables differ per segment),
   and chunks the composition half (`comp_points_per_proof`) to bound each recursion trace.
   **The settlement seam rides it**: `settlement_proofs.prove/verify_settlement_o1` — segment statements + io
   replay + state-root chain natively (no crypto), and ONE recursion bundle in place of the K per-segment
   `stark.verify` calls. Query strength is verifier policy (protocol constant by default —
   `verify_epoch`/`verify_settlement` were also hardened to stop reading the prover's declared `num_queries`).
   **VALIDATED END-TO-END (2026-07-16):** the FULL W=106 recursion bundle now **completes AND verifies** — a
   real multi-segment execution-AIR epoch settled by ONE recursion bundle in place of the K per-segment
   `stark.verify` calls, with the tamper/policy negatives rejected (`tests/test_settlement_o1.py` under
   `NADO_HEAVY=1`: ~15 GB, minutes). Two things made this real. (a) **Native prover:** NTT cap → 2^22, native
   `rleaf`/`rnode` Merkle (`rmerkle_commit`), and a division-free Goldilocks reduction across all three native
   crates — ~5× faster / 4.5× less memory, bit-identical, so it stopped OOMing (it used to die at ~40 GB in
   pure Python). (b) Completing it exposed and let us fix a real latent bug: the composition gadget's degree
   overflow when RE-EVALUATING the degree-8 exec AIR under sparse periodic gating — fixed by
   `air_ir.gadget_max_degree`, which gives the gadget exactly the `max_degree` headroom the inner AIR needs
   (prover + verifier derive it identically). The wrapper is still committed as CAPABILITY, NOT wired as the
   authoritative settlement verifier UNTIL step 8; the proof it checks is producible + verifiable at real scale.
8. ✅ **On-chain settle-with-proof — DONE (`ops/transaction_ops.py` `settle` branch, `ops/settlement_ops.py`,
   `ops/kv_ops.py`, `tests/test_settle_with_proof.py`).** A `settle` tx MAY carry the recursion bundle; EVERY
   node verifies it deterministically at block-validation — at the PROTOCOL query strength (never the bundle's
   own count), binding the proof's `post_root` to the tx's attested `state_root`, its `cursor` to `exec_cursor`,
   and its `pre_root` to the namespace's committed settled tip (`EXEC_GENESIS_ROOT` for the first settlement, so
   a proof can never start from a fabricated pre-state). On success it records the on-chain marker
   `kv_ops.settlement_proven`, and `settlement_ops.settlement_justified` accepts a root when that marker is set
   OR the bonded quorum is met — both PURE functions of committed on-chain state, so no node diverges (this is
   what makes it fork-safe: the old node-local `_EPOCH_PROOFS`/`settlement_verifier` callback — which would have
   forked a node that had a proof from one that didn't — is REMOVED). The soundness hole flagged here before
   (a verifier that ignored the attested full root) is closed: the exact `state_root` is the binding.
   Universal rule, no activation gate; the proof must fit the same universal `MAX_PEER_BODY` block bound every
   tx does, which ties its practicality to proof SIZE — the §5b authoritative-depth frontier.
9. ✅ **Succinct (T-independent) verify — BUILT.** Two layers:
   **(a) Structured periodic in the core** (`stark._per_expand`/`_per_evaluator`, `tests/test_stark_periodic.py`).
   A periodic column may be `{"period": p, "base": [p values], "sparse": [(row, val)]}`: the verifier evaluates
   its interpolation at a query point as `h(x^{T/p})` plus closed-form Lagrange terms `Δ·g^r(x^T−1)/(T(x−g^r))`
   for the sparse rows — O(p + #sparse) per point instead of the O(T) interpolation at old `stark.verify:208`.
   Proofs are BYTE-IDENTICAL to the dense form (the structured form is representation, not protocol; legacy
   dense columns still take the old path). Verify-time domain materialization (`F.domain(N)` in `stark.verify`,
   `fri.verify`, `fri_verify._canonical_public`) is likewise replaced by on-demand `off·ω^pos`.
   **(b) The recursion gadgets restructured onto it** (`fri_verify.py`, `comp_verify.py`): hash blocks padded
   from `BR = 9` to **16 rows** so every fixed pattern (round constants, round/absorb/hold/link gates) is a true
   16-periodic base; all instance data (fold x/α, finals, selectors, check-row publics, per-path link releases)
   is SPARSE (O(1) rows per Merkle path); and the one dense instance column — the path DIRECTION bits — moved to
   WITNESS, pinned to the FS-derived leaf index by a boolean gate + an IACC accumulator (`IACC = 2·IACC' + d`
   per absorb, boundary-pinned to the index at the path start and 0 at the digest row; unique over ℤ since the
   index < 2^path_len < P). Net: gadget verification does NO O(T) work — cost is O(queries · layers),
   independent of both inner and recursion trace lengths. In-circuit Fiat-Shamir (`fs_incircuit.py`,
   `fs_step.py`, `fs_chain.py` — bit-identical to the backend `Transcript`, `tests/test_fs_*`) remains available
   for the LAST native cost, the O(queries·layers) challenge re-derivation, if/when that matters.

The design's soundness rests on §6; steps 1–7 discharge the parts that were genuinely missing (a sound
arithmetic hash, a field-native inner proof, in-circuit hashing, both verifier-authoritative halves combined
with an in-circuit-validated seam), and step 9 makes the verification succinct.

## 5b. The next rung — recursion DEPTH (fold-of-folds), for true O(1) in K

Everything above collapses the K segment proofs of ONE epoch into ONE bundle, but a verifier still does O(K)
cheap work (rebuild K public statements, K FRI native-checks) and the bundle grows with K. True O(1) — constant
in K AND across epochs — needs recursion DEPTH: a bundle that verifies OTHER bundles.

The mechanism is already self-similar, so no new cryptography is required, only wiring:

  * **Enabler — recursion-backed gadgets.** A gadget proof (fold / comp / rowcomp) is itself an alghash2 STARK.
    Today it commits under `backend.ALGHASH2` (hashn Merkle). Switch it to `backend.RECURSION` (rleaf/rnode,
    one permutation per node) and the gadget proof's OWN FRI becomes exactly the shape `fri_verify` already
    folds and `comp_verify` already binds. A fold proof can then be an INNER proof of another fold. (Pure
    Merkle-hash change, orthogonal to every AIR/constraint — the transcript is unchanged since RECURSION
    extends ALGHASH2.)

  * **The tree.** `recursive_verify` applied to a LIST of bundles' gadget proofs as its inner proofs yields a
    LEVEL-1 super-bundle attesting "these B bundles all verify." Recurse: a balanced fan-in-F tree over the
    epoch bundles has depth ⌈log_F(K)⌉ and a single ROOT bundle of fixed size. The verifier checks ONE root
    bundle — O(1) in K — plus the O(log K) hashes to re-derive the tree's public statement (each level's inner
    "public part" is the level-below root's small public part, chained by the same verifier-authoritative
    discipline: the verifier rebuilds every level's statement from committed roots, never the prover's word).

  * **The AIR at each level is FIXED and PUBLIC** — it is the gadget's own `_transitions()` (round + membership +
    fold/composition), the same at every level, so the verifier program is a constant the depth verifier bakes
    in. The only data-dependent inputs are roots (boundaries) and the FS schedule, both verifier-derived.

  * **Cross-epoch chaining** rides the same seam: epoch e's post-state root is a boundary of epoch e+1's first
    segment (already true in `settlement_proofs`), so a depth tree spanning epochs proves the WHOLE chain's
    execution history with one root bundle — the settlement seam (`settlement_justified`) then checks that one
    constant-size object instead of a bonded quorum.

Soundness is inherited, not extended: each tree node is an ordinary verifier-authoritative recursion proof over
alghash2, so a forged root bundle means a forged inner proof at some level, i.e. a broken alghash2 collision or
a broken FRI — the same assumptions as §6. The work remaining is engineering (the fan-in driver + the per-level
public-statement rebuild + throughput), NOT a new soundness primitive. Tracked as the O(1)-in-K milestone.

**BUILT + measured (`execnode/stark/recursion_depth.py`, `tests/test_recursion_depth.py`):** the LOW-DEGREE
depth tree — `fold_tree`/`verify_tree` over the `out_backend=RECURSION` enabler (`fri_verify.prove_fold`) that
makes a fold proof itself rleaf/rnode-committed and thus foldable. A fold-of-folds ROOT was proven, and a
single fold node **verifies in ~0.2 s** — a recursion proof verifying recursion proofs.

**Honest accounting of the O(1) claim.** A plain fold attests only that its OWN trace is low-degree — NOT that
the children it folded were themselves valid. So verifying just the root is NOT sound for the low-degree tree:
`verify_tree` correctly RE-VERIFIES every node (and cross-checks that each parent folds the roots it names),
which is O(N) *cheap* fold-checks — a big constant-factor win over O(N) *expensive* `stark.verify`s and a bundle
that shrinks the per-node cost, but NOT asymptotic O(1). **True root-only O(1) requires the AUTHORITATIVE tree:**
each level must ALSO bind the composition half (prove, in-circuit, that the child proofs' authenticated openings
satisfy the child AIR — `recursive_verify` applied to the level below, across the fold-AIR and comp-AIR
together), so the root TRANSITIVELY attests every descendant verified and the verifier checks the root alone.
That per-level composition binding — a heterogeneous-AIR recursion step with a verifier-rebuilt per-level
schedule — is the genuine remaining cryptographic frontier (not just wiring), and it is what would shrink the
settlement proof enough to sit comfortably inside a normal tx (step 8's transport bound). The PROVE side is
also throughput-bound exactly as §6/§7 warn (a level-1 fold measured at N=131072, ~19 min pure Python — the
recursion LDE outgrows the native NTT cap), so `test_recursion_depth` validates the enabler + foldability fast
and gates the full fold-of-folds step behind `NADO_HEAVY=1`; the Rust prover is the throughput prerequisite for
deep trees.

## 5c. O(1) SETTLEMENT — the assembled architecture (built + validated 2026-07-16)

The whole point of the above is an L1 that settles an epoch of arbitrary execution by checking a fixed-size
object. Everything below the final in-circuit statement-rebuild is now BUILT and validated; the remaining piece
is scoped precisely.

**Holistic native prover (`native/starkprove`, `execnode/stark/stark_native.py`).** A persistent Rust LDE arena
runs the whole prove (LDE → Merkle → composition → FRI → openings) in u64 buffers, so the Python prover never
materializes N-sized column lists — the recursion memory wall. Byte-identical to `stark.prove` for every mode
(column/row, single/two-phase, RECURSION + ALGHASH2), wired into `stark.prove`, shielded/BLAKE2B untouched.
`tests/test_starkprove.py`, `tests/test_holistic_wired.py`. This is what makes recursion proofs memory-feasible.

**Authoritative depth (`execnode/stark/recursion_authdepth.py`).** `recursive_verify` applied to a bundle's own
fold_0 + comp_0 (RECURSION-committed) → a root that attests the bundle verifies — the fold/comp CRYPTO collapsed
to a constant-size object (the §5b binding, one level). `tests/test_recursion_authdepth.py`.

**State-root binding — the dominant O(K) removed.** The settled root was a FLAT blake2b merkle over EVERY leaf,
forcing verify_epoch to re-merkleize the whole state + REPLAY the io (O(state)). Replaced by a sparse alghash
storage root the recursion can bind, verified by a bound state-transition instead of a replay:
  * `storage_tree.py` — sparse alghash Merkle; `verify_transition` applies the io as O(touched·depth) folds.
  * `merkle_update.py` — the IN-CIRCUIT core: proves `old→pre_root` AND `new→post_root` sharing ONE path (two
    parallel alghash sponge folds over shared sib/dir cols — the shared path is the soundness crux). Foldable.
  * `state_transition.py` — chain K updates (post_i = pre_{i+1}); the K proofs share the merkle-update AIR so
    they fold K→1 via `recursive_verify` → authoritative depth → O(1).
  * `exec_state_bind.py` — `net_updates` derives the epoch's net writes from its (proven) io; `bind_and_verify`
    requires the transition to prove EXACTLY those, so it provably IS the epoch's transition.
  * `settlement_sparse.py` — `verify_bound_epoch` = exec proof (io valid) + bound transition, NO replay/whole-
    state merkle; `verify_withdrawal` = membership in the same root (bridge/dividend/unshield exits).
  `tests/test_{storage_tree,merkle_update,state_transition,exec_state_bind,settlement_sparse}.py`, all green:
  a real epoch verifies via the sparse root with no replay, its post_root equals an independent full
  re-projection, and withdrawals prove against the same root.

**Commitments — the O(1)-shaped public input (`execnode/stark/calls_commit.py`).** The epoch's K ordered calls
collapse to ONE field element (`calls_commitment` = a `merkle_node` chain over the call leaves = a `membership.py`
fold, hence provable + foldable); the io collapses the same way (`io_commitment`, domain-separated). So the
settlement public statement is the O(1)-shaped `(calls_commitment, io_commitment, sparse_pre_root,
sparse_post_root)` (`settlement_sparse.public_statement_o1`). `tests/test_calls_commit.py`.

**In-circuit statement rebuild — the STATE half + the binding primitive (built).**
  * `logup_bind.py` — LogUp multiset-equality: two lists of tuples are the same multiset inside a proof (the
    primitive that binds the exec's storage writes to the transition's updates in-circuit). `tests/test_logup_bind.py`.
  * `io_replay.py` — the state transition proven fully IN-CIRCUIT: process the epoch's io directly (SLOAD =
    membership, SSTORE = merkle-update) against the running sparse root, chained pre_root → post_root, every step
    RECURSION-committed (foldable → O(1)). `tests/test_io_replay.py`.
  * `settlement_sparse.prove/verify_bound_epoch_replay` — the assembled O(1) settlement: exec proof + io replay +
    the O(1)-shaped commitments; the CRYPTO is O(1) (folded). `tests/test_settlement_sparse.py`.

**Committed exec periodic tables — BUILT (the exec verify is no longer O(#io)).** The exec AIR proves its trace
against per-epoch periodic tables (the program/io/args log + per-row context — the exec has FIVE LogUp buses
binding the trace to them, see vm_circuit.py). A public verifier used to REBUILD + dense-evaluate those tables —
an O(T) `poly_eval` per query per column, the residual O(#io). Now:
  * `stark.prove/verify(commit_periodic=[...])` — opt-in COMMITTED periodic columns: the listed columns' LDE is
    Merkle-committed (root absorbed as a public parameter before the main trace) and OPENED at each FRI query
    point (O(log N)) instead of dense-evaluated; caller-supplied `periodic_roots` bind them to the statement.
    `commit_periodic=None` is byte-identical to before. `tests/test_commit_periodic.py`.
  * `vm_circuit.COMMIT_PERIODIC` — the epoch-DATA columns (program/io/args tables + per-row context/args), threaded
    through `prove_epoch_calls`/`verify_epoch_calls`. The fixed range tables + sparse block selectors moved to the
    structured `{period,base,sparse}` form (T-independent eval, bit-identical LDE — `test_exec_commit_periodic`),
    so NOTHING the verifier rebuilds is O(T).
  * `vm_circuit.verify_epoch_o1(proof, per_roots)` — the O(1)-SHAPED exec verify: takes the committed roots from
    the on-chain statement, never rebuilds a data table, does only O(#calls) work (the block schedule) + the
    STARK's O(queries·log N). `tests/test_exec_commit_periodic.py` (accepts from roots alone, no io log; a wrong
    root is rejected). Differentially validated: the committed proof accepts iff the public proof does.

**The remaining glue for end-to-end O(1) settlement — the sharpened frontier.** Analysis (2026-07-16) collapsed
what looked like two bindings into ONE real piece:
  * Piece 1 (bind `per_roots` to the commitment) largely DISSOLVES: `per_root` IS the io/args/program commitment,
    and the exec AIR's five LogUp buses already bind the committed columns to the trace (the comp spot-check
    re-checks each bus at the query points using the OPENED committed values). A prover committing a different io
    table just yields a valid proof of a DIFFERENT execution — soundness at the exec level is "correct execution
    of the committed io", not "the io is the real one". So no separate chain proof is needed; the settlement uses
    `per_root` (or a fingerprint of it) as the io commitment directly.
  * Piece 2 (bind the STATE replay to the exec's committed io) is the real remaining piece. It cannot open the
    committed columns at the trace rows (they live on a coset LDE, not at gᵀⁱ), and it must avoid computing
    `slot_key` (blake2b) in-circuit. The clean, arithmetization-friendly route is an ORDERED RLC FINGERPRINT:
    add a phase-2 aux column to the exec AIR accumulating `F_exec = Σ r^i · combine(ctr,kind,a,b)` over io rows
    (r = a challenge drawn after the io commitment), pinned as a public boundary; the io_replay accumulates the
    SAME `F_exec` over its raw (kind,slot,value) steps (pinned in the folded bundle); settlement checks the two
    boundaries equal (O(1)). Schwartz–Zippel makes F equal ⇒ same ordered io w.h.p.; the call/cid schedule is
    bound separately by `calls_commitment`, so together they bind (cid,kind,slot,value) WITHOUT a shared-transcript
    fold or an in-circuit hash. Cost: one degree-2 aux column added to the W=106 two-phase exec AIR — a delicate,
    opt-in, differentially-validated money-path change (the deliberate next build).

Until piece 2 lands, `verify_bound_epoch_replay` keeps the native O(#io) binding as the verified fallback
(soundness-first — no partial O(1) shipped as complete). `verify_epoch_o1` is a validated CAPABILITY (the exec
verify is already off the O(#io) periodic-table cost); the RLC fingerprint is what makes wiring it into settlement
sound end-to-end.

**DEPLOYMENT.** Swapping the sparse root in as THE consensus settled root (settle-tx `state_root`,
`ops/transaction_ops` bridge/dividend/unshield exits, `state.py`) is a genesis-level state-root-scheme change,
NOT inert on the live chain, so it rides the reroll (with CHAIN_ID→alphanet-6 + settle-with-proof).

## 6. Soundness ledger (what each piece rests on)

- **Inner proofs:** FRI/STARK soundness (already tested) over **alghash2** collision-resistance (≥128-bit).
- **The fold:** the *execution AIR's* soundness (already tested, incl. the ARG-bus negatives) — the fold
  proof is an ordinary zkVM proof of the verifier program, so a forged fold means a forged execution proof.
- **Grinding** (`transcript.grind`, unconditional 2^GRIND_BITS) tops up the reduced-query inner proofs.
- **No blake2b in the recursed layer** — every hash the fold re-executes is alghash2, so nothing in the
  recursion depends on a non-arithmetizable primitive.

Explicitly **not** claimed: production-parameter proving time in Python (the Rust port is the throughput
prerequisite — this pipeline is correctness-first, demonstrated at reduced parameters). The mechanism is the
deliverable; scaling it is an engineering (not a soundness) task.
