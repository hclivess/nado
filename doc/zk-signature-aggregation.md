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

## Status and where it slots in

- **Not built.** There is no ML-DSA verification circuit today; this is the gating artifact.
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
