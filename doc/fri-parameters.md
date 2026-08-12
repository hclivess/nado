# FRI parameters — can we trade blowup for queries and shrink the proof?

**Short answer: yes — but the winner is blowup 8, not 16.** On soundness alone `blowup 16 / 96 queries`
looks best (164.4 provable bits against today's 156.0 at 30% of the opening size). Measured, its prover
cost is **4.74x** with **4x** peak memory, which a ~250 s prove against a ~180 s settle cadence cannot
absorb. **`blowup 8 / 96 queries`** keeps essentially today's security (154.2 bits) at **0.36x proof size
and 0.30x verify time** for 2.35x FRI-prove cost — and that multiplier shrinks on the real settle path,
where FRI is not the dominant term. See §4 for the measurements.

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

On soundness alone the best row is `blowup 16 / 96 queries`: 164.4 provable bits — 8 bits MORE than
today — at 30% of the opening size. **§4 measures what that costs the prover and rejects it**; the rows
that survive are `blowup 8 / 96` (154.2 bits) and `blowup 4 / 192` (163.2 bits). Read this table as
"what is *available* at each rate", not as the recommendation.

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

## 4. The prover cost — MEASURED, and it changes the recommendation

`tools/bench_fri_blowup.py` proves and **verifies** the same 16 384-row trace at each configuration
(scaling `_blowup` for the prover and shimming the verifier's `expected_blowup`, so every run is a proof
that actually validates — an unverified proof is not a benchmark).

| fri_blowup | queries | prove s | verify s | proof MiB | peak RSS MiB | vs today: prove / verify / size |
|---|---|---|---|---|---|---|
| **2** | **320** | **5.81** | **2.61** | **9.92** | **94** | 1.00x / 1.00x / 1.00x |
| 4 | 192 | 8.00 | 1.78 | 6.50 | 156 | **1.38x** / 0.68x / 0.66x |
| 8 | 96 | 13.63 | 0.79 | 3.53 | 216 | **2.35x** / 0.30x / 0.36x |
| 16 | 96 | 27.52 | 1.05 | 3.80 | 372 | **4.74x** / 0.40x / 0.38x |

**Blowup 16 is off the table for the settle path.** 4.74x prove time and 4x peak memory against a prove
that already runs ~250 s versus a ~180 s settle cadence would put a span far beyond its window — the
in-flight guard would reject the next span before the previous one finished. The size win (0.38x) is real
but cannot be bought at that price. Note also that blowup 16 at 96 queries is *larger* on the wire than
blowup 8 at the same query count (3.80 vs 3.53 MiB): more fold layers and a bigger final layer eat part
of the saving, so the last doubling pays twice and delivers nothing.

**What the benchmark overstates.** This is a pure STARK prove, where the LDE and FRI dominate. The real
settle prove does not look like that: `sparse_projection` is 137–158 s of a 240–270 s prove and
`SparseStore.root()` is 65.8 s of that — work that does not scale with the FRI blowup at all. So the
multipliers above are an upper bound on the settle path; if FRI is ~40% of a real prove, blowup 8's 2.35x
becomes roughly 1.5x overall. **Measure on the real settle prove before committing** — this bench sizes
the FRI term, not the whole job.

**Verification gets materially cheaper**, and that is the underrated half: 0.30x at blowup 8. Every node
pays verify on every apply and on every fresh sync, so a 3x cut there is a permanent, fleet-wide saving
against a one-time prover cost paid by whoever settles.

### Revised recommendation

The analysis in §2 favoured blowup 16 on soundness alone. With the prover measured, that inverts:

* **blowup 8 / 96 queries** is the target — 154.2 provable bits (about today's 156.0), **0.36x proof
  size, 0.30x verify**, at 2.35x FRI-prove cost that the real settle path will dilute.
* **blowup 4 / 192 queries** is the safe fallback — 163.2 bits (*better* than today), 0.66x size, 0.68x
  verify, only 1.38x prove.
* **blowup 16 is rejected** on prove time and memory, despite having the best soundness-per-byte.

## 5. Deployment

Changing FRI parameters changes what a verifier accepts, so **this is a consensus change and rides a
generation reroll** — a proof built at the old parameters is not verifiable under the new ones, and settle
proofs are re-verified on block apply and on fresh sync. It cannot be a hot toggle.

`soundness.py` reads the live parameters, so once `FRI_BLOWUP`/`NUM_QUERIES` move, the reported figures
follow automatically — the model does not need editing, only the constants.

Suggested order:

1. ~~benchmark prove cost at blowup 4/8/16~~ — **done**, see §4 (`tools/bench_fri_blowup.py`). Remaining:
   re-measure on a REAL settle prove, where FRI is not the dominant term;
2. pick the row that keeps prove time inside the settle cadence — **blowup 8 / 96** is the target and
   **blowup 4 / 192** the fallback (§4); blowup 16 is rejected on prove time and memory;
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
