# Signature aggregation — built, measured, removed

**Status: REMOVED, 2026-07-31.** This is a post-mortem, kept deliberately. The idea is attractive and most of
its reasoning was sound; the only thing that settled it was measurement. Anyone proposing it again should
start here.

## What was proposed, and what was right about it

Replace per-transaction signature verification with one STARK proving that every transaction in a block
carries a valid ML-DSA-44 signature, then ship **one proof plus the transactions with signatures stripped** —
a block as a validity-rollup of its own transactions.

Two of the three supporting arguments hold up:

- **STARKs are the right vehicle if you do this at all.** Aggregating post-quantum signatures under a
  pairing-based SNARK would reintroduce exactly the weakness ML-DSA exists to remove. nado's proofs are
  hash-based and PQ-sound, so the guarantee survives end to end.
- **Data availability was the strong framing.** An ML-DSA transaction is a ~10-byte body wrapped in a ~2.4 KB
  signature. Signatures dominate what a block *weighs*, and the original note correctly posed this as a
  crossover threshold rather than an unconditional win.

One argument was wrong, and was never checked:

- **"Signature verification is the expensive thing."** Measured: `nado_pq_native.verify_internal` is
  **120.4 µs**. A 200-transaction block spends ~**24 ms** on signatures — a rounding error beside execution.

## What killed it: the numbers

Proving the *butterfly half* of the `w'` computation for **one** signature — not a block, not a batch, one
signature, and only part of it:

| | measured |
|---|---|
| prove | **7.11 min** (T = 16384, W = 193) |
| proof size | **1.87 MB** |
| verify | **6.98 s** |
| against | 2420 B and 120.4 µs |

≈ **770× the size** and **58,000× the verify time**, for half of one signature. The full `w'` schedule is
18432 rows per signature (13312 butterflies + 5120 pointwise products).

Aggregation only wins by amortising a fixed cost over a batch of size B:

- **size** break-even: B ≈ 116
- **verify** break-even: B ≈ 12
- **achievable**: B ≤ 7, from the trace-row budget

It loses on both axes at every reachable batch size. The crossover the original note asked about is real — it
just sits on the wrong side of what the machine can build.

### Two escapes were tested; both failed

- **"It's Python."** No. 97.6% of prove wall-clock was already in Rust, and the verifier's hot kernel was
  native too (pure-Python permute 3167 µs vs 54 µs through ctypes). Batching every Merkle path in a proof
  into ONE native call bought **1.07×** — the boundary crossings were not dominant, the permutation
  arithmetic was.
- **"It's the recursion."** Partly, and spectacularly: folding three sub-proofs that together cost 16.7 s ran
  **>32 min and >26 GB** before being killed, ~1000× the size of what it compressed. Worth fixing for other
  reasons; deleting it does not close a 770× size gap.

## What the work paid for

**Two forgery-class bugs**, both "valid AIR, invalid witness" — the circuit computes the right thing, but the
witness was never constrained to be honest:

1. `mldsa_ntt_air.apply_inverse` emitted `(d, 1, z)` per Gentleman–Sande step. The butterfly AIR constrains
   `t = zeta*b`, `out0 = a + t`, so it proved `out0 = d + z` — a SUM — while the value actually stored was
   `z*d`. **0 of 1024 rows** had the AIR's output equal to the value used.
2. `mldsa_hint_air`'s `KQ` was a free witness and `M = 44` is invertible mod P, so a prover could solve
   `kq = (raw − out)·M⁻¹` and satisfy the only constraint mentioning it for **any** claimed UseHint output.
   Forging `out ∈ {0, 1, 43, 12345}` — all four accepted.

Both were inert *only because `w'` was a public input*, and both would have become keyless universal forgery
the moment the NTT moved into the witness. Earlier the same day, constraint #60 in the same file compared `r`
against `q−1` where Dilithium's wrap case is `r − r0 == q−1`, so ~half of all signatures produced a trace
violating its own AIR (12 of 24 failed before the fix, 0 of 24 after).

**The lesson that outlives the feature:** all three passed the semantic tests, because the AIRs matched
Dilithium. What was wrong was what the witness was ALLOWED to be, and no semantic test can see that.
`final layer is not low-degree` is the symptom — it means the trace violates its own AIR, not that FRI is
broken.

**Speed-ups that stayed**, none signature-specific:

- `alghash2` permute **54.11 µs → 28.71 µs**, by deleting two u128 *divisions* per call (`addf`, and the MDS
  accumulation) sitting directly beneath a comment observing that division was the dominant cost. On the hot
  path of every proof the chain makes.
- `merkle_verify_paths` — M authentication paths in one native call instead of a Python loop invoking a
  native permute per level.
- ExpandA **285–456 ms → 1.76 ms** (removed with the stack, but the pattern generalises: the proven sponge
  exists to emit a witness trace; computing a *value* only needs the bytes).

## What was already the right answer

Not signatures — **execution**. And it was built before this was attempted.

`execnode/settlement_proofs.py` proves an entire epoch as ONE zkVM trace (N calls across many contracts,
concatenated into a single STARK). **L1 verifies one proof in ~0.3 s, independent of the call count**,
replaying the authenticated I/O log to recompute the post-state root with **no re-execution**.

That is the asymmetry ZK exists for: re-running ten thousand contract calls is genuinely expensive; checking
a proof that they ran correctly is not. Live as `SETTLE_PROOF_RECURSIVE` since the alphanet-14 reroll. The
shielded pool (`execnode/stark/joinsplit2.py`) is the other legitimate use, for a different reason — its
inputs are hidden by construction, so there is no cheaper alternative for it to compete against.

**The rule this episode is evidence for: prove what is expensive to REDO; do not prove what is cheap to
CHECK.**

## What stayed

`execnode/stark/mldsa_block_auth.py` — the block-level authorization **commitment**. Every block binds
`(auth_root, auth_count)` into its hash preimage and every verifier recomputes both from the block's own
transactions. A pure function of committed block data, costs nothing, never depended on an aggregate proof
being accepted, and imports only `alghash` and `field`.

## If anyone revisits this

The one change that would move the verdict is **in-circuit Keccak/SHAKE** — what would let a block genuinely
DROP signature bytes rather than merely replace the arithmetic, turning a 770× size regression into a size
win and vindicating the data-availability argument that motivated this. `mldsa_keccak_air` reached W = 6080;
its composition trace would need 12178 columns against a `MAX_COLUMNS` of 8192.

That is a separate project with its own budget, and it should begin with a measurement of what a block
actually spends its time and bytes on — not with an assumption about it.
