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

**The remaining layer (built ON this foundation, not faked):**

5. **`fold(π_a, π_b)`** — chain the gadget: (a) absorb-mux the gadget up a Merkle path → a membership circuit;
   (b) stack membership + the field-arithmetic FRI-fold/composition checks → the full inner-STARK verifier
   circuit; (c) `prove` that circuit over two inner proofs → one fold proof; `fold_tree` folds pairwise to
   one root. The verifier's accept/reject oracle is already `recursion.verify_inner` (= `stark.verify` with
   alghash2). Everything it needs is field-native (step 3) and its dominant cost is arithmetized (step 4).
   The gate to running it at production parameters is **prover throughput** — the Python STARK prover proves
   even the small gadget in ~tens of seconds (the field-arithmetic composition, now that hashing is native);
   a full **native/Rust STARK prover** (the NTT half already exists in `wasm/goldilocks`) is the engineering
   prerequisite, a throughput task, *not* a soundness one.
6. **Wire into settlement** — `settlement_proofs.prove_recursive` folds the segment proofs into one; the seam
   verifies the single root proof (an O(1) path on top of the shipped segmentation).

The design's soundness rests entirely on §6; steps 1–4 discharge the parts that were genuinely missing (a
sound arithmetic hash + a field-native inner proof + in-circuit hashing), which is what made recursion
impossible before.

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
