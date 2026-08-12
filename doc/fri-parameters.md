# FRI parameters — can we trade blowup for queries and shrink the proof?

**Short answer: yes, and by more than expected.** NADO's own soundness model says
`FRI_BLOWUP = 16` with **96 queries** is *stronger* than today's `blowup 2 / 320 queries` — 164.4 provable
bits against 156.0 — while cutting the FRI openings to **30%** of their current size. The security
argument is settled; what is not yet measured is the prover cost of the larger evaluation domain, and
that is the only thing standing between this analysis and a decision.

Everything below is computed with `execnode/stark/soundness.py` — the repo's own model, at the live
parameters it reports (`E=192, nu=18, grind=18, log_trace=17`) — not with numbers borrowed from a paper.

---

## 1. Where we are

    FRI_BLOWUP   = 2          (fri.py — stark.prove always passes 2)
    NUM_QUERIES  = 320
    GRIND_BITS   = 18
    -> PROVABLE  = 156.0 bits (best regime: Johnson/JBR)
       conjectured = 176.0 bits

A blowup of 2 means a rate of 1/2, and a rate that high buys very little per query: it is why **320**
queries are needed at all. The measured cost is **0.381 MiB of FRI openings per query**, perfectly
linear, which is what makes a settle-with-proof transaction ~97 MiB on the wire.

`soundness.py` also reports the ceiling: at blowup 2, soundness **saturates at 381 queries**. We are at
320 — close enough to the ceiling that adding queries is nearly pure size for nearly no security.

---

## 2. The tradeoff, computed

Provable bits and the resulting opening size, across blowup and query count. `vs now` is opening size
relative to the current 320-query configuration (openings scale linearly with queries; blowup does not
change the *number* of openings, it changes how much each one proves).

| blowup | queries | provable | conjectured | regime | vs now |
|---|---|---|---|---|---|
| **2** | **320** | **156.0** | **176.0** | JBR | **1.00x**  ← today |
| 2 | 256 | 143.1 | 269.3 | JBR | 0.80x |
| 4 | 192 | 163.2 | 397.1 | JBR | 0.60x |
| 4 | 128 | 144.0 | 270.7 | JBR | 0.40x |
| 8 | 128 | 164.2 | 397.8 | JBR | 0.40x |
| 8 | 96 | 154.2 | 302.8 | JBR | 0.30x |
| 8 | 64 | 114.0 | 207.9 | JBR | 0.20x |
| **16** | **96** | **164.4** | 398.1 | JBR | **0.30x** |
| 16 | 80 | 159.7 | 334.8 | JBR | 0.25x |
| 16 | 64 | 144.4 | 271.4 | JBR | 0.20x |
| 16 | 48 | 114.0 | 208.1 | JBR | 0.15x |

Saturation (queries beyond which soundness stops improving at all):

| blowup | saturates at |
|---|---|
| 2 | 381 queries |
| 4 | 233 |
| 8 | 190 |
| 16 | 173 |

**The headline row is `blowup 16 / 96 queries`: 164.4 provable bits — 8 bits MORE than we have today —
at 30% of the opening size.** There is no security/size tradeoff to agonise over at that point; it is
better on both axes. `blowup 16 / 80` (159.7 bits, 0.25x) is also still stronger than today.

If one wanted to spend the gain on size instead of security, `blowup 16 / 64` gives 144.4 bits at
**0.20x** — a 5x reduction, still comfortably above 128.

---

## 3. What this does NOT solve

**It does not put the proof in a block, and it never can.** A full block is ~256 KiB and
`MAX_BLOB_BYTES_PER_BLOCK` is 1 MiB. Even a 5x cut leaves a ~20 MiB proof — still ~80x an entire block.
The DA path (publish the proof, carry only its commitment) remains the only architecture that works.
This lever is worth pulling for three other reasons:

* **transport** — 20 MiB gossips and erasure-codes very differently from 97 MiB;
* **verify time** — fewer queries is directly less verifier work on every node, on every apply and every
  fresh sync;
* **headroom** — it moves the inline path from "impossible" to "merely large", which matters while DA
  coverage is still one-node-deep.

---

## 4. The cost that is NOT yet measured, and gates the decision

Raising the blowup enlarges the **evaluation domain**: at blowup 16 the LDE is over 16x the trace length
instead of 2x, i.e. **8x the current domain**. That falls on the prover — the low-degree extension, the
Merkle commitment over it, and the per-layer folding.

This matters because proving is already the bottleneck, not proof size:

* a prove takes ~250 s against a settle cadence of ~180 s;
* `sparse_projection` is 137–158 s of a 240–270 s prove, and `SparseStore.root()` is 65.8 s of that;
* `prove_transition` dominates at ~126 s per state update.

An 8x domain does not multiply total prove time by 8 — the dominant costs above are *not* the FRI LDE —
but it is certainly not free, and **nobody has measured it**. Fewer queries also makes the *verifier*
and the *opening phase* cheaper, which partly offsets it.

> **Do not ship this on the model alone.** Benchmark `prove` at (blowup 4, 8, 16) with the matching query
> counts on a real epoch trace and compare wall-clock and peak RSS against today. If blowup 16 pushes a
> prove past the settle cadence, blowup 8 at 96 queries (154.2 bits, 0.30x) buys nearly the same size cut
> for a quarter of the domain growth.

---

## 5. Deployment

Changing FRI parameters changes what a verifier accepts, so **this is a consensus change and rides a
generation reroll** — a proof built at the old parameters is not verifiable under the new ones, and settle
proofs are re-verified on block apply and on fresh sync. It cannot be a hot toggle.

`soundness.py` reads the live parameters, so once `FRI_BLOWUP`/`NUM_QUERIES` move, the reported figures
follow automatically — the model does not need editing, only the constants.

Suggested order:

1. benchmark prove cost at blowup 4/8/16 (the one open question);
2. pick the row that keeps prove time inside the settle cadence — preferring **blowup 16 / 96** if it
   fits, since it is strictly better than today, else **blowup 8 / 96**;
3. change `FRI_BLOWUP` and `NUM_QUERIES` together, in the same commit as a `CHAIN_GENERATION` bump;
4. re-run the settle-proof E2E and confirm `soundness.py` reports the expected bits.

---

## 6. Related reading

The result above comes from the Johnson-bound regime the model already implements. If we ever want to
push further, the relevant literature is **proximity gaps for Reed–Solomon codes** (Ben-Sasson, Carmon,
Ishai, Kopparty, Saraf) and the **ethSTARK documentation**, which is the standard reference for exactly
this queries-vs-blowup accounting and for the proven/conjectured split the model reports.

`libSTARK` (the original 2018 reference implementation) is **not** a useful source here: it is
binary-field with additive FFTs where NADO is Goldilocks prime-field, it has no recursion, and its own
README warns it is academic-grade and "very likely contains multiple serious security flaws".
