# Validity-proof signature aggregation (proof of block validity)

A design note on a "some time down the road" upgrade: replacing per-transaction signature verification with
a single STARK proof of block validity. This is the L1 sibling of the exec-layer settle-with-proof
(`zk-settlement-completion.md`) — it applies the same "prove it once, verify it cheaply everywhere"
principle to the most expensive thing an L1 node does, which on nado is **post-quantum signature
verification**.

## The idea

Today every node re-verifies every transaction's signature: a block with N txs costs N ML-DSA-44 verifies
on every node. Instead, the block producer proves **in-circuit** that

> "every one of the N transactions in this block carries a valid ML-DSA-44 signature over its txid (and
> applies to valid state)"

and ships **one proof + the transactions with their signatures stripped**. Every node then checks **one
proof** instead of N signatures. This is *validity-proof signature aggregation*; taken to include the state
transition it is *proof of block validity* — a block becomes a validity-rollup of its own transactions.

## Why this fits nado specifically

1. **Signatures ARE the cost.** An ML-DSA-44 transaction is a ~10-byte body wrapped in a **~2.4 KB
   signature** (plus a ~1.3 KB public key on first use). Post-quantum signatures are large precisely because
   they are the thing you would most want to compress away. Stripping signatures from what is gossiped and
   stored is a large **bandwidth + data-availability** win, and verification drops from O(N) signature
   checks to ~O(1) proof check. (nado already strips the *pubkey* after an address's first tx — PUBKEY-ONCE,
   `interface.js`/`transaction_ops.create_txid` — so the residual per-tx weight this targets is the
   signature.)

2. **nado already has a PQ-sound proof system.** This upgrade only preserves nado's post-quantum guarantee
   if the *aggregating* proof is itself PQ-sound. nado's proofs are **STARKs** — hash-based, no trusted
   setup, PQ-sound (`execnode/stark/*`) — so aggregating PQ signatures under a STARK keeps the quantum
   guarantee end to end. A pairing-based SNARK (e.g. Mina's Kimchi/Pickles) is **not** PQ, so aggregating
   ML-DSA signatures under it would reintroduce exactly the weakness ML-DSA exists to remove. nado's choice
   of STARKs is what makes this coherent.

3. **The toolbox is already here.** nado has the recursion + in-circuit hashing machinery this needs
   (`recursion.py`, `fs_incircuit.py`, `alghash2`, `vm_circuit.py`, the native Rust prover). What is missing
   is one specific circuit — see below.

## The honest catches (why it is "past a certain tx volume," not "always")

- **Proving ML-DSA in-circuit is the hard, expensive side.** Verifying one ML-DSA-44 signature *natively*
  is ~0.15 ms; expressing that verification as an arithmetic circuit is genuinely heavy. Dilithium
  verification involves **NTTs, rejection-sampling bounds, and SHAKE/Keccak hashing** — among the harder
  primitives to arithmetize (Keccak's bit-oriented permutation is notoriously circuit-unfriendly; nado uses
  the STARK-friendly `alghash2` internally for exactly this reason, but the *signature scheme's own* hashing
  is fixed at SHAKE-256 and must be proven as-is). So there is a real **crossover threshold**:
  - at low tx volume the proving overhead dwarfs the savings (you spent more proving than you saved
    verifying),
  - at high tx volume the per-tx proving cost amortizes and the DA + verify savings dominate.

  That threshold is the whole premise ("if a chain has more than a certain amount of txs"). It moves down as
  the native prover gets faster and as the Dilithium circuit is optimized.

- **The data must still be available.** The proof replaces *re-checking signatures*, not the transaction
  data — nodes still need the tx bodies to reconstruct state. This is the same data-availability requirement
  the exec layer already reasons about (`doc/execution-layer.md` §DA), and it nudges toward specialized
  provers / a proving market rather than every phone proving its own block.

- **The new component is a Dilithium-verification circuit** (an ML-DSA-44 verify AIR). That is a substantial
  build on top of what nado has, and signature-verification-in-ZK is an active research area generally
  (see e.g. work on hash-based and lattice signature circuits). It is the gating artifact.

## How it maps onto nado's architecture

A block already carries `block_transactions`. The change:

- **Block format** — transactions ride with signatures **stripped** (the txid still commits the body, as
  today; `create_txid` already excludes `public_key`, so it would exclude `signature` too). The block gains
  one `validity_proof` field over `(txids, pubkeys-or-commitment)`.
- **Producer** — after selecting the tx set, prove in-circuit: for each tx, `ML_DSA44.verify(pubkey, txid,
  sig)` holds, with `pubkey` bound to the sender via `proof_sender` (the same binding
  `ops/address_ops.proof_sender` enforces natively) and `txid` bound to the committed body. This is a new
  AIR composed (via the existing recursion) with the block's other commitments.
- **Verifier (block validation)** — `validate_transactions_in_block` replaces the per-tx `validate_origin`
  signature check with a single `verify(validity_proof)`. Everything else (spending, reserved-tx rules,
  target matching) is already a pure function of committed state and stays.
- **Interplay with existing pieces** — `PUBKEY-ONCE` means most txs already omit the pubkey (recoverable
  on-chain), so the proof binds each tx to its established sender pubkey rather than re-shipping keys. The
  `_CRYPTO_LOCK`-serialized native verify (`signatures.py`) — a per-verify global lock that is itself a
  scaling limit — disappears from the hot path entirely, which is a second, separate win.

## Relationship to the settlement / recursion track

- **settle-with-proof** proves the **exec/L2 state transition** (contract execution) — it is prover-limited,
  not verifier-limited, and mostly wired (`zk-settlement-completion.md`).
- **signature aggregation** proves **L1 transaction-signature validity** — it needs one genuinely new,
  expensive circuit (Dilithium-in-STARK) and is gated on throughput.
- Both fold under the **same** recursion + in-circuit-FS machinery, so the two compose: a fully
  proof-validated nado block would carry one recursive proof attesting *both* "all signatures valid" *and*
  "the state transition is correct" — which is the Mina-style "block is one proof" endpoint, reached the
  post-quantum way.

## Architecture — block authorization with a detached proof (adopted 2026-07-27)

The framing below is the authoritative plan (folded in from a peer design note, `zk-signature-aggregation-02.md`).
It scopes the circuit tightly and, crucially, keeps the **block hash independent of proof completion**.

### Detached evidence — the load-bearing idea
The block **core** carries the transactions (signatures STRIPPED) plus two commitment fields — `auth_root`
(a field-native commitment to the ordered authorization entries) and `auth_count` (the exact number `K` of
signature checks) — and NOTHING else about signatures. The signatures (or the proof) travel in a SEPARATE
evidence envelope, exactly one of:

```
{ "type": "raw",   "witnesses": [ ordered signature entries ] }        # every block can always ship this
{ "type": "stark", "circuit_id": ..., "proof": ... }                    # substituted when a proof is ready
```

The **block hash is byte-identical whether the evidence is raw or a proof.** This is what makes it safe: a
relay can build the canonical block for an offline winner from the signed mempool without racing proof
completion, and an invalid/absent proof never poisons block identity when valid alternate evidence exists.
(nado already keeps the block-timestamp out of the block-hash preimage for a related determinism reason —
`calls_commit.py`.)

### Narrow proof scope — prove ONLY signature validity
The proof attests exactly one thing: *"for every one of the `auth_count` authorization leaves, a valid
ML-DSA-44 signature exists over its txid under the sender's resolved public key."* Everything else stays in
the **native** verifier, unchanged: spending, target-height, reserved-recipient, uniqueness, fee, state-root,
`create_txid`, PUBKEY-ONCE resolution, and the cheap `proof_sender` binding — AND the native verifier
**independently recomputes `auth_root` and `auth_count`** from the block. This deliberately keeps the L1 state
machine, canonical JSON, and blake2b address-checksum OUT of the circuit. Only the FIPS-204 signature check
goes in.

```
auth_leaf_i = H_field(AUTH_DOMAIN, block_height, tx_index, txid_limbs, sender_limbs,
                      H_field(resolved_pubkey_bytes), authorization_kind, signature_count)
auth_root   = field-native Merkle root / sponge over the ordered leaves      # H_field = alghash2, NOT SHAKE
```

### Chunked incremental proving + recursive fold
To fit a ~6 s slot: decode each signature ONCE on mempool admission and cache its witness keyed by
`(circuit_id, ordered auth leaves, chunk length)`; prove fixed-size chunks (16/32/64 sig checks) in PARALLEL
as the block template evolves; freeze the tx set ~1.5 s before the deadline, prove the tail chunk, and
**fold the chunk proofs into one root proof** via the existing `recursive_verify` machinery (the same K→1
fold now live for settlement). Padding rows carry an explicit selector the AIR forces to contribute nothing,
and it enforces exactly `auth_count` active rows in one contiguous sequence. The final proof's PUBLIC
statement binds chain/genesis id, height, parent hash, `auth_version`, `circuit_id`, `auth_root`,
`auth_count`, and the first/last covered tx indices — so a proof cannot be replayed onto another block, cover
only a favorable subset, or duplicate leaves.

### Sizing gate (why it is throughput-gated)
Byte crossover ≈ `ceil((P + metadata) / 2420)` for proof size `P` (an ML-DSA-44 sig is 2420 B). nado's current
~1 MiB proofs only pay off past ~434 tx (not viable) — the dedicated AIR must reach **100–200 KiB** (verify
≤100 ms) to be practical; pilot target 128 sigs/block. Below ~50 KiB is a research assumption, not a launch
premise. CPU crossover is separate and worse on pure-Python nodes, so the FIRST win is bandwidth / storage /
killing the global `_CRYPTO_LOCK` — not native-node CPU.

### Rollout — Optional → Mandatory (never a flag-flip to mandatory)
A: shadow-prove every real block, compare to native checks, no consensus impact. B: ship the signature-free
core + detached envelope; raw evidence valid for all blocks, proof substitutable (single-sig txs only). C:
relay PREFERS proof when `2420*K ≥ 1.25*P`. D: consensus REQUIRES a proof when `K ≥ K_required` (128 only if
the final proof ≤200 KiB); raw stays valid below threshold + for legacy kinds. E: add multisig, and optionally
fold signature validity into the L1 state-transition proof (the Mina endpoint). Go/no-go gates before D:
proof ≤200 KiB at target soundness, verify ≤100 ms p95 on the slowest node, ≥3 independent proving operators
produce the identical statement, ≥99.9% shadow success over ≥100 k blocks, independent security review of
circuit/transcript/recursion/parser, and an emergency proof-disable that is a CONSENSUS upgrade, not an
operator flag. Keep a RAW witness sidecar for the reorg horizon (`finality_depth` + margin) and the FFG
slashing horizon; the block-winner signature stays detached + unchanged.

## Implementation status (build order) — STARTED 2026-07-27

The verify equation decomposes into these sub-circuits, in rough build order. Golden references for every
piece: `dilithium_py.ml_dsa.ML_DSA_44` (the node's pure-Python PQ backend) and `static/vendor/nado-crypto.js`
(@noble, the browser verifier) — the AIR must reproduce the SAME verification byte-for-byte.

- ✅ **Params** — `execnode/stark/mldsa_params.py`: the ML-DSA-44 constant table (Q=8380417, N=256, k=l=4,
  γ1, γ2, η, τ, β, ω, D, byte lengths), asserted against `dilithium_py` in tests.
- ✅ **Sub-circuit 1 — the ‖z‖∞ norm bound** (`mldsa_norm_air.py`, `tests/test_mldsa_norm_air.py`): proves
  every decoded z coefficient's centered representative satisfies |v| < γ1−β, EXACTLY (sign hint + two-sided
  bit-range check so it is not a power-of-two over-approximation), coefficients pinned to the public z via
  boundaries (verifier-authoritative). Establishes the mod-Q-over-Goldilocks + exact-range pattern the rest
  reuse. Proven against a real signature's z from `dilithium_py`.
- ✅ **Sub-circuit 2 — the mod-Q multiply-reduce gadget** (`mldsa_modq_air.py`, `tests/test_mldsa_modq_air.py`):
  c = a·b mod Q via reduce-by-hint (a·b = k·Q + c over Goldilocks — a·b < Q² < 2^46 < P, no wrap — with c, k
  range-checked into [0, Q)). The arithmetic atom for the NTT and A·z − c·t1. Proven incl. the (Q-1)² worst case.
- ✅ **Sub-circuit 3a — the NTT butterfly gadget** (`mldsa_butterfly_air.py`, `tests/test_mldsa_butterfly_air.py`):
  one Cooley-Tukey butterfly `(a,b,zeta) → (a+zeta·b, a−zeta·b) mod Q`, built on the mod-Q reduce + conditional
  add/sub-mod-Q. Matches dilithium_py's real `ntt_zetas` (bit-reversed powers of 1753) and reproduces its first
  NTT stage (128 butterflies). Per-butterfly reduction ≡ dilithium's reduce-at-end (needed so Goldilocks never
  overflows).
- ⬜ **Sub-circuit 3b — the full 256-point NTT routing**: compose 8 stages × 128 butterflies with the in-place
  data flow + the periodic zeta schedule; the engine that takes A·z and c·t1 to/from the NTT domain.
- ✅ **Sub-circuit 4 — decompose + UseHint + hint weight** (`mldsa_hint_air.py`, `tests/test_mldsa_hint_air.py`):
  w1 = UseHint(h, Az−ct1·2^d) over the γ2 rounding (a = 2γ2, m = (Q−1)/a = 44) and ‖h‖₁ ≤ ω. Proves the split
  r = r1·a + r0 (r0 centred, carried shifted), r1 ∈ [0,m], boolean wrap/sign flags, and the mod-m ±1 step by
  reduce-by-hint. Matches `utils.decompose`/`use_hint` over 300+ values **including the Q−1 wrap edge** (whose
  detection must mirror the reference's PRE-decrement test — a real trap this surfaced).
- ✅ **Sub-circuit 5 — signature/pubkey DECODE** (`mldsa_decode_air.py`, `tests/test_mldsa_decode_air.py`):
  bit-unpacks t1 (10-bit), z (18-bit, γ1−x), w1 (6-bit) and the ω+k hint encoding. Canonical by construction
  (the verifier re-derives the bit windows from the public bytes) and rejects non-monotonic cuts /
  non-increasing positions / non-zero padding — the malleability checks. Verified against a REAL keypair +
  internal-mode signature.
- ✅ **Sub-circuit 6 (THE mountain) — Keccak-f[1600] / SHAKE arithmetisation**
  (`mldsa_keccak_air.py`, `tests/test_mldsa_keccak_air.py`): for ExpandA (SHAKE128, dominates — k·l=16
  rejection-sampled polys), tr, μ, SampleInBall, and the final c̃ == SHAKE256(μ‖w1). The algebraic sponge
  (alghash2) legally cannot substitute (it would change the hashed bytes and break cross-verify with every
  on-chain signature + the browser), so Keccak is proven as-is: the 5×5×64 GF(2) state is carried as 1600
  BOOLEAN columns with XOR = a+b−2ab, NOT = 1−a, AND = a·b; θ/ρ/π collapse into one degree-1 expression over
  the input bits, χ's degree-3 step is split via auxiliary AND-product columns, ι XORs the public round
  constant — every constraint degree ≤ 2. The reference sponge matches **hashlib/OpenSSL** (SHAKE128+256,
  multi-block absorb, long squeeze) and **all 8000 round constraints are satisfied by a real Keccak round**.
  ⚠️ **Open**: one round is 3·1600 = **4800 columns**, far past `MAX_COLUMNS`. Composing the 24-round
  permutation (and then the sponge) needs a raised column cap or a lane/bit-sliced decomposition — this is the
  next step, and it is what determines whether the proof size lands in the 100–200 KiB target band.
- ⬜ **Composition + block-format swap**: fold the per-signature proofs (via the existing `recursive_verify`)
  into one block validity proof; strip signatures from the gossiped/stored block; swap
  `validate_transactions_in_block`'s per-tx `validate_origin` for one `verify(validity_proof)`.

## Status and where it slots in

- **Started (2026-07-27): params + sub-circuit 1 built and tested.** The gating artifact (a full ML-DSA
  verification circuit) is under construction; the Keccak/SHAKE AIR (sub-circuit 5) is the dominant remaining
  cost.
- **Reachable, not free.** The proof system (PQ-sound STARK), recursion, in-circuit hashing, and native
  prover are all in place; the remaining work is (a) the Dilithium-44 verify AIR, (b) composing it with the
  block commitments via the existing recursion, (c) the sig-stripped block format + the block-validation
  swap, and (d) enough proving throughput (the native Rust prover) that the crossover threshold sits below
  real block sizes.
- **Sequencing.** This is *after* the settle-with-proof line lands (it shares and stresses the same prover),
  and its value grows with tx volume — so it is a "reach for it once blocks are consistently full" upgrade,
  exactly as posed. The consensus-aggregation note (`doc/consensus-aggregation.md` §5, "succinct
  proof-of-threshold") is the same shape applied to attestations and lands behind the same seam.

## One-line summary

Treat each block as a validity-rollup of its own transactions: prove "all N post-quantum signatures verify"
once, ship the block without its signatures, and check one PQ-sound STARK instead of N ML-DSA verifies —
worth it past the tx-volume crossover, gated on a Dilithium-in-STARK circuit, and directly on nado's
existing recursion / settle-with-proof trajectory.
