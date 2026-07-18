# NADO zk glossary — every term in the proof stack

Plain-language definitions of the acronyms and terms used across `execnode/stark/*`, `doc/zk-*.md`, and the
settlement layer. Each entry says what the thing IS, why it's here, and where it lives in the code. Read
top-to-bottom the first time — later terms build on earlier ones.

---

### Field (Goldilocks)
The set of numbers all the math happens in: integers mod the prime `p = 2^64 − 2^32 + 1` (`execnode/stark/field.py`).
Chosen because `p − 1 = 2^32·(2^32 − 1)`, so there is a "2^k-th root of unity" for every k ≤ 32 — exactly what
the NTT/FRI need to build evaluation domains of size 2^k. Every value in the prover is a plain integer in `[0, p)`;
a phone can verify with cheap 64-bit modular arithmetic.

### NTT (Number-Theoretic Transform)
The finite-field analogue of the FFT: converts a polynomial between its **coefficients** and its **evaluations**
on a root-of-unity domain in `O(n log n)` (`field.ntt`, native Rust in `wasm/goldilocks`). It's how the prover
evaluates trace polynomials on the large domain fast.

### Trace
The table of numbers a computation produces: `T` rows × `W` columns, where each row is the machine's state at one
step and each column is one register/value over time (`stark.py`). Proving = showing this table obeys the rules.

### AIR (Algebraic Intermediate Representation)
How the "rules" of a computation are written down as **polynomial constraints** over the trace
(`stark.py`, `execnode/stark/vm_circuit.py`). Two kinds:
- **transition** constraints `c(current_row, next_row, …) = 0` that must hold on every step (e.g. "the next
  register = this register + the immediate");
- **boundary** constraints `(row, col, value)` that pin specific inputs/outputs.
A constraint is a formula that evaluates to 0 exactly when the rule is satisfied. "Arithmetizing" a computation
means expressing it as an AIR.

### Periodic columns
Fixed, PUBLIC per-row values the verifier can recompute itself (round constants, selector flags, lookup tables)
— they let one uniform constraint behave differently on different rows (`stark.prove(..., periodic=…)`). Public =
not part of the secret witness.

### Witness
The private/prover-supplied part of the trace — the values only the prover knows or fills in. Opposed to the
public statement (periodic + boundaries). Soundness hinges on the verifier controlling the public part and the
prover controlling ONLY the witness.

### LDE (Low-Degree Extension) / blowup
Interpolate each trace column to a polynomial of degree `< T`, then evaluate it on a domain `blowup×` larger (a
coset). `blowup` is the Reed–Solomon rate denominator; a bigger blowup = more redundancy = more soundness per
check (`stark._coset_evaluate`, `_blowup`). "Coset" just means the domain is shifted off the trace's own domain so
the two don't collide.

### Merkle tree / commitment / root / opening / path
A binary hash tree over a vector of values. The single top hash (the **root**) is a short **commitment** to the
whole vector: you can later reveal one value plus the sibling hashes up to the root (an **opening** / authentication
**path**) and the verifier recomputes the root to check it (`execnode/stark/merkle.py`). This is how the prover
commits to a polynomial's evaluations and later reveals a few without being able to change them.

### Hash backends (blake2b / alghash2 / recursion)
The stack is hash-agnostic — it needs a leaf/node hash + a Fiat-Shamir transcript, supplied by a `backend`
(`execnode/stark/backend.py`):
- **blake2b** (default) — a fast byte-oriented hash; used everywhere a proof is verified NATIVELY (L1, browsers).
- **alghash2** — a wide **algebraic** sponge over the field (`execnode/stark/alghash2.py`, width 12, capacity 4
  → 256-bit digest, ~128-bit collision resistance): its round function IS field arithmetic, so a hash can be
  expressed as constraints and verified INSIDE a proof (needed for recursion). "Sponge" = a hash built by
  repeatedly mixing (permuting) a fixed-width state.
- **recursion** — alghash2's transcript but Merkle leaf/node = the fixed-arity `rleaf`/`rnode` (one permutation
  per node, no length prefix). A proof committed with this backend has exactly the tree the in-circuit membership
  AIR spends one permutation-block per level on.

### Composition polynomial
The single polynomial that packages "every constraint holds": a Fiat-Shamir-random linear combination of every
constraint, each DIVIDED by the polynomial that vanishes where it must hold (`stark._composition`). Key fact: that
quotient is a genuine low-degree polynomial **iff** the constraint actually holds everywhere — a violation leaves
a non-polynomial (high-degree) term. So "the trace satisfies the AIR" reduces to "this composition polynomial is
low-degree."

### FRI (Fast Reed–Solomon Interactive Oracle Proof of Proximity)
The engine that proves a Merkle-committed vector of evaluations really is a **low-degree** polynomial
(`execnode/stark/fri.py`). It repeatedly **folds** the polynomial in half using a random challenge —
`g(x²) = f_even(x²) + α·f_odd(x²)` — halving the degree and domain each round, committing each layer's Merkle root,
until the polynomial is tiny (the **final layer**, sent in the clear). The verifier spot-checks, at random query
positions, that each layer is the correct fold of the previous one, and that the final layer is genuinely
low-degree. A STARK = "reduce to a composition polynomial" + "FRI proves it low-degree."

### Fold / fold-consistency
One FRI halving step. Its check (division-free): `2·x·folded = x·(lo+hi) + α·(lo−hi)`, where `lo`,`hi` are the two
opened evaluations at a query and `folded` is the next layer's value. If a prover chooses `α` freely the check is
vacuous — which is why `α` MUST be Fiat-Shamir-derived.

### Final-layer low-degree test
The base case of the FRI induction: interpolate the small final layer and require its high-degree coefficients to
vanish (`fri.py`). Skipping it lets an arbitrary high-degree tower fold "consistently" while proving nothing — a
total soundness break. Any FRI verifier MUST enforce it.

### Query / num_queries
Each FRI query is one random spot-check of the fold tower. More queries = exponentially lower forgery
probability; the protocol uses 64 (`fri.NUM_QUERIES`). A proof verified at too few queries (e.g. 4 ≈ 20 bits) is
forgeable.

### Transcript / Fiat-Shamir
Turns the interactive protocol non-interactive: every "random" challenge is derived by HASHING everything sent so
far (`execnode/stark/transcript.py`). **Fiat-Shamir soundness requires the hash bind ALL public values** — omit
one (e.g. a commitment) and a prover can choose it after seeing the challenge and forge (the classic weak-FS bug).
In FRI the transcript absorbs each layer root (drawing each fold `α`), then the final layer, then the grinding
nonce, then draws the query positions — so `α` and the positions are pinned to the roots and cannot be chosen.

### Grinding (proof-of-work)
An extra unconditional soundness margin: the prover must find a nonce whose transcript hash has `GRIND_BITS`
leading zeros before the query positions are drawn, so grinding favorable Fiat-Shamir positions costs `2^GRIND_BITS`
per attempt (`transcript.grind`, native in `native/alghash2`).

### STARK
Scalable Transparent ARgument of Knowledge: the whole proof — commit the trace LDE, form the composition, FRI-prove
it low-degree, and spot-check that the committed composition equals the quotient recomputed from the committed
trace at FRI's query points (`stark.prove`/`stark.verify`). "Transparent" = no trusted setup; "post-quantum" = the
only assumption is a collision-resistant hash.

### Composition spot-check
The half of `stark.verify` that ties FRI back to the trace: at each query, open the trace columns, RECOMPUTE the
composition value from them + the periodic values + the AIR constraints, and require it equals the FRI layer-0
value. This is what forces the low-degree polynomial FRI accepted to actually be the committed trace satisfying
the constraints.

### Constraint IR + native composition
The AIR constraints are Python closures; tracing each one once with symbolic inputs records an SSA bytecode of
field ops (`execnode/stark/air_ir.py`), which a native Rust interpreter (`native/starkcompose`) evaluates over the
whole LDE — bit-identical, an order of magnitude faster than Python. Pure throughput; no soundness change.

### LogUp / lookup argument
The log-derivative lookup argument the VM execution AIR uses for memory-checking / multiset equality
(`execnode/stark/logup.py`): proves "every used value appears in a table" via a running rational sum that
balances iff the multisets match. Drawn with a challenge after the trace is committed (two-phase protocol).

### zkVM / zkasm / zkpy
The provable virtual machine whose one step = one trace row (`execnode/zkvm.py`); **zkasm** is its assembly
(`execnode/zkvmasm.py`); **zkpy** is a Python-to-zkasm compiler with automatic register allocation
(`execnode/zkpy.py`). Contracts (the games, settlement) run on it; the execution AIR (`vm_circuit.py`) proves a
run happened without re-executing it.

### Epoch / aggregation
An epoch is N contract calls concatenated into ONE trace so L1 verifies ONE proof for the whole batch instead of N
(`settlement_proofs.prove_epoch`).

### Segmentation
When an epoch is too big for one trace (> `MAX_T` rows), split it into consecutive segments and CHAIN their state
roots `root_0 → … → root_K` (`settlement_proofs.prove_settlement`). Removes the size cap; L1 still verifies K
proofs (O(K)).

### Recursion / the fold
Verifying a proof INSIDE a proof, to collapse those K proofs into ONE constant-size proof L1 checks with a single
verification (`execnode/stark/fri_verify.py`, `recursion.py`). A recursion proof's statement is "I ran the verifier
on these inner proofs and it accepted." Applied as a binary tree (`fold(fold(π₁,π₂), fold(π₃,π₄))…`) it collapses
any number of proofs to one root proof — the path to O(1) settlement.

### Membership AIR / carry columns / siblings-as-witness
The in-circuit gadget that proves a leaf hashes up a Merkle path to a public root, one alghash2 permutation block
per level. The opened value is a WITNESS carried in dedicated columns (tied to the leaf lane, held constant) so
the fold constraint reads the SAME value the Merkle path authenticates. The path **siblings are witness** (not
periodic), so the verifier never needs the prover's paths and cannot be handed forged ones.

### Verifier-authoritative
The property that the VERIFIER, not the prover, builds the entire public statement of a proof (roots, challenges,
selectors, boundaries) by re-deriving it from the committed roots — the prover supplies only witness. This is the
cure for the whole class of "the proof trusted a prover-supplied public input" soundness bugs.

### Settlement (Phase-2b) / the seam
The mechanism by which L1 accepts a settled zkVM state root because a PROOF justifies it, instead of a bonded-stake
committee attesting it. The proof path (on-chain `kv_ops.settlement_proven` marker, checked in `settlement_ops.settlement_justified`) is built but disabled today — quorum is the only live settlement authority.
The fold plugs in here to make that single L1 check O(1) in the epoch size — once the recursion verifier is sound
AND bound to the state root (composition spot-check for the execution AIR).
