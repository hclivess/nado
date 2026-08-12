# FRI parameters — can we trade blowup for queries and shrink the proof?

> **STATUS: this lever is REJECTED — on the size argument, not on prove cost.** The question was closed on
> 2026-08-03 in [settle-proof-transport.md §4b](settle-proof-transport.md) (commit `6a6614cc`), and this
> document was written on 2026-08-12 without citing that, recommending blowup 8. **That was a
> regression** — a closed question re-opened on weaker evidence.
>
> On re-examination *both* rounds leaned on prove-cost numbers taken with `NADO_ALLOW_PYTHON_KERNELS=1`,
> timing a prover no node runs. Those figures are **withdrawn** (§4b there, §4 here) and replaced with
> native measurements. The rejection survives regardless, because it never depended on them: at protocol
> strength the lever turns ~97 MiB into ~32 MiB, and **32 MiB still needs DA exactly as 97 MiB does**, so
> it does not change the architecture. That is the argument to answer if anyone re-opens this — a third
> time — not the timing table.
>
> What is worth keeping here is the *soundness accounting* (§2) and the native cost measurements (§4,
> §4a). The recommendation does not survive; see §7.

**Short answer: no.** On soundness alone the trade looks attractive — `blowup 16 / 96 queries` reaches
164.4 provable bits against today's 156.0 at 30% of the opening size, and `blowup 8 / 96` holds 154.2
bits at 0.36× size. Measured natively, blowup 8 costs **3.14× on the FRI term** and **1.11× on a real
(idle) settle prove**, and halves the proof. But the size it buys does not cross the threshold that would
matter: DA is required at 97 MiB and at 32 MiB alike, so a consensus change buys a smaller number in the
same architecture.

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
today — at 30% of the opening size. **No row survives as a recommendation** — §4 and §4b of the transport
doc both measure the prover cost and reject the lever (§7). Read this table strictly as "what is
*available* at each rate" — it is the soundness accounting, not a menu to pick from.

---

## 3. What this does NOT solve

**It does not put the proof in a block, and it never can.** A full block is ~256 KiB and
`MAX_BLOB_BYTES_PER_BLOCK` is 1 MiB. Even a 5x cut leaves a ~20 MiB proof — still ~80x an entire block.
The DA path (publish the proof, carry only its commitment) remains the only architecture that works.

**This paragraph used to continue "…so the lever is still worth pulling for three other reasons" and list
transport, verify time and headroom. That framing is what produced the wrong recommendation, so it is
struck.** Those three benefits are real but none of them requires a consensus change:

* **transport** — 32 MiB and 97 MiB are handled by the same DA path; neither gossips inline.
* **verify time** — the 0.33x verify win is genuine and is the strongest thing this lever has (§4). It is
  also the one benefit obtainable another way: the periodic-column fix already cut verify 6.7x
  (1267 s → 187.9 s) with no protocol change at all.
* **headroom** — "merely large" is not a category the protocol has. A proof either fits in a block or
  needs DA, and 32 MiB needs DA.

Read §7 before treating any of the tables below as actionable.

---

## 4. The prover cost on an ISOLATED FRI term — measured

`tools/bench_fri_blowup.py` proves and **verifies** the same 16 384-row trace at each configuration
(scaling `_blowup` for the prover and shimming the verifier's `expected_blowup`, so every run is a proof
that actually validates — an unverified proof is not a benchmark).

> **The Python-kernel table that stood here has been DELETED.** It was taken with
> `NADO_ALLOW_PYTHON_KERNELS=1`, timing a prover no node runs and that the Rust-only guard treats as a
> hard failure. It is replaced below by a native-arena run of the identical trace, not corrected in place.

| fri_blowup | queries | prove s | verify s | proof MiB | peak RSS MiB | vs today: prove / verify / size |
|---|---|---|---|---|---|---|
| **2** | **320** | **6.01** | **2.86** | **9.92** | **94** | 1.00x / 1.00x / 1.00x |
| 4 | 192 | 12.90 | 1.80 | 6.50 | 156 | **2.14x** / 0.63x / 0.66x |
| 8 | 96 | 18.88 | 0.96 | 3.53 | 217 | **3.14x** / 0.33x / 0.36x |
| 16 | 96 | 36.74 | 0.95 | 3.80 | 372 | **6.11x** / 0.33x / 0.38x |

**Native is WORSE than the withdrawn Python figures, not better** (3.14x against 2.35x at blowup 8; 6.11x
against 4.74x at 16). The Rust arena has already removed the overhead that the blowup does not touch, so
the extra LDE and Merkle work is a larger share of what remains. Verify and size ratios are essentially
unchanged, since those are protocol quantities rather than implementation ones.

Note also that blowup 16 at 96 queries is *larger* on the wire than blowup 8 at the same query count
(3.80 vs 3.53 MiB): more fold layers and a bigger final layer eat part of the saving, so the last doubling
pays twice and delivers nothing.

**Trace size matters more than it looks.** The same native bench at 1024 rows reports 0.90x / 1.01x /
3.18x — blowup 8 appears free because fixed per-prove overhead swamps the LDE at that size. Only the
16 384-row run above is representative. A small run is a smoke test, not a measurement.

**Verification gets materially cheaper**, and that is the underrated half: 0.33x at blowup 8. Every node
pays verify on every apply and on every fresh sync, so a 3x cut there is a permanent, fleet-wide saving
against a one-time prover cost paid by whoever settles.

### 4a. The same question, measured END TO END on the real settle path

`tools/bench_settle_fri.py` drives the actual `prove_settlement_sparse` entry point against a real settle
stash written by the live node (27 deployed contracts, `depth=EXEC_TREE_DEPTH=256`), with calls rebuilt
from on-chain DA calldata, verifying every proof with `verify_settlement_sparse`. Native arena, and each
configuration in a **fresh process** — the module-level `_E_CACHE`/`_FOLD_CACHE` in `settlement_sparse`
survive between proves, so three configs in one interpreter measure cache warmth, not the blowup.

Busy span 17430 → 17460 (30 blocks, 248 real exec calls, ~8/block), produced by submitting 300
bridge-funded `faucet.fund()` calls to the live chain so they actually execute rather than being skipped.

**COLD vs WARM IS THE WHOLE STORY, and getting it wrong inverts the answer.**
`storage_tree._FOLD_CACHE` is a cross-store cache (see the analysis in that file, 2026-08-06) that makes
each settle prove cost O(slots the span changed) instead of O(all slots). A **fresh process** pays the
full singleton-fold rebuild — ~50 s of alghash2 permutations — that a long-running exec node pays **once**.
Since this bench runs every configuration in its own process (it must, or the cache contaminates the
comparison), the naive run measures cold starts, which production is not.

**COLD — every config in a fresh process:**

| fri_blowup | queries | prove s | of which sparse | verify s | proof MiB | peak RSS | vs today |
|---|---|---|---|---|---|---|---|
| **2** | **320** | **58.9** | 50.0 | **5.0** | **12.06** | 162 | 1.00x / 1.00x / 1.00x |
| 4 | 192 | 63.1 | 50.4 | 3.7 | 8.63 | 213 | 1.07x / 0.72x / 0.72x |
| 8 | 96 | 75.1 | 51.7 | 2.8 | 5.68 | 327 | **1.27x** / 0.55x / 0.47x |

**WARM (`--warm`) — one discarded prove first, i.e. what a running exec node actually does:**

| fri_blowup | queries | prove s | of which sparse | verify s | proof MiB | peak RSS | vs today |
|---|---|---|---|---|---|---|---|
| **2** | **320** | **10.2** | 0.5 | **4.5** | **12.06** | 168 | 1.00x / 1.00x / 1.00x |
| 4 | 192 | 13.5 | 0.6 | 3.5 | 8.63 | 218 | 1.32x / 0.76x / 0.72x |
| 8 | 96 | 26.2 | 0.7 | 2.5 | 5.68 | 332 | **2.57x** / 0.55x / **0.47x** |

The sparse half is **85% of a cold prove and 5% of a warm one**. So the FRI multiplier lands at 1.27x cold
and **2.57x warm** — and warm is the production number. That is close to the 3.14x the isolated bench
(§4) reports, which means **the isolated bench was broadly right about the multiplier all along**; the
"94% sparse, so it barely matters" framing came from measuring cold starts.

What survives from this, measured:

* **prove cost in production is 2.57x**, not the 1.27x a cold benchmark suggests, and not the 2.35x/7.0x
  Python figures the two rejections were written on;
* **the size win is ~0.47x, not 0.36x**, and it does not move with load — a settle proof carries
  substantial non-FRI content;
* **memory roughly doubles** — 162 → 332 MiB peak at blowup 8. Nobody had measured this;
* **verify is 0.55x**, cold or warm, because verification does not touch the fold cache.

A steady-state settle prove is **10.2 s**, not the ~250 s figure quoted in older documents. Load beyond
~8 calls/block has not been measured.

**SCOPE — this is the UNFOLDED path only.** Every figure above comes from
`prove_settlement_sparse(..., recursive=False, fold=False)`. The K→1 recursion fold is a different and far
heavier prove: `execnode.py` records a real folded run at **1156.9 s total** with
`prove_transition=883.6 s`, against a `SETTLE_PROVE_TIMEOUT` of 1200 s. None of the blowup ratios here
have been measured on the folded path, and it would be wrong to assume they carry over — the fold's cost
sits in `prove_transition`, which the unfolded path reports as 0.0 s. Do not quote 10.2 s or 2.57x for a
folded prove.

### What this benchmark is NOT

It proves a **single-column** 16 384-row trace whose constraint is `x' = x² + 7`. No LogUp, no periodic
columns, no sparse projection, no recursion fold — none of the machinery the settle circuit is made of. It
sizes **the FRI term in isolation**, which was its stated purpose, and it cannot tell you what fraction of
a settle prove that term is. Multiplying its 0.36× size ratio against the real ~97 MiB proof is an
extrapolation, not a measurement, and any figure derived that way should be treated as a guess.

The measurement that *does* speak to the settle path is §4b of
[settle-proof-transport.md](settle-proof-transport.md): 53.3 s → 374.4 s for 3.166 MiB → 1.070 MiB.
`tools/bench_settle_fri.py` drives the real `prove_settlement_sparse` entry point against a real settle
stash if a further data point is ever wanted.

## 5. Why it is not a free knob anyway

`fri_blowup = 2` is a **structural identity**, not a setting. `stark.py` derives
`blowup = 2·next_pow2(max_degree)`, `N = blowup·T`, `deg_bound = next_pow2(max_degree)·T`, so
`fri_blowup = N/deg_bound = 2` falls out — and `stark_native.py` pins it for that reason. Both benchmarks
reach other values by monkey-patching `stark._blowup` and shimming the verifier's `expected_blowup`. That
is legitimate for measurement and misleading as a sense of how easy the change would be: raising the
blowup to 16 means an 8× larger LDE domain, paid in NTT and Merkle work on every column.

## 6. If it were ever revisited: deployment

Changing FRI parameters changes what a verifier accepts. Whether that needs a genesis reroll depends
entirely on whether any settle proof has actually landed on the live chain: proofs are re-verified on
block apply and on fresh sync, so old proofs under new parameters would fail. With **no landed settle
proofs**, a coordinated fleet `/update` is sufficient and no reroll is involved. Verify that before
assuming either way — do not repeat the claim that it "rides a reroll" without checking.

`soundness.py` reads the live parameters, so once `FRI_BLOWUP`/`NUM_QUERIES` move, the reported figures
follow automatically — the model does not need editing, only the constants.

## 7. Standing conclusion

**Do not raise the FRI blowup** — but be precise about why, because the usual reason is wrong.

*Not* because the prover cost is prohibitive. Natively it is 3.14× on the FRI term and, on a real settle
prove at today's load, **1.11× overall** (§4a) — that is affordable. The two rounds that rejected this on
prove time were both reading Python-prover numbers.

**Because it does not change the architecture.** At protocol strength the lever takes ~97 MiB to ~32 MiB.
Both need DA; neither fits in a block (1 MiB `MAX_BLOB_BYTES_PER_BLOCK`, ~256 KiB a full block). A
consensus change that moves a proof between two sizes that are handled identically buys nothing, and the
verify and transport wins it does deliver are available for free once DA transport lands. The open work on
settle-proof size is **DA transport** (§5 item 3 of the transport doc).

**Requirement 1 has now been met** (§4a): the busy-span measurement exists, warm and cold. In production
(warm) the lever costs **2.57x prove** and **~2x prover memory** for 0.47x size and 0.55x verify. That is
a real cost — not the 7.0x the first rejection claimed, but not the 1.27x a cold benchmark suggests
either.

**Requirement 2 has not been met and is the whole question:** what does a 32 MiB proof let us do that a
97 MiB proof does not? Both need DA; neither fits in a block. Until someone answers that, the size table
is irrelevant no matter how good it looks, and a consensus change cannot be justified by it.

The one genuinely attractive number is **verify at 0.55x**, paid by every node on every apply and every
fresh sync. If that becomes the reason to act, say so explicitly and weigh it against 2.57x prove and 2x
prover memory — do not smuggle it in behind the proof-size argument, which is the mistake made twice here.

### The improvement this exercise actually found

Not FRI. **A cold settle prove is 58.9 s and a warm one is 10.2 s** — a ~48 s gap that is entirely
`SparseStore.root()` rebuilding singleton folds: ~2.15 M alghash2 permutations at 17.6 µs, of which 99.6%
are folds of a lone leaf against the canonical empty roots. `_FOLD_CACHE` removes it in steady state but
**nothing removes it for a cold process**, and cold processes are not rare:

* every exec-node restart pays it before its first settle;
* every **verify** in a fresh process pays it — including a fresh-syncing node checking historical settles.

The permutation is already native and is genuine compute (54 rounds x a dense 12x12 MDS), so there is no
FFI overhead worth shaving; `storage_tree.py` says as much. The ways down are to do **fewer** permutations
or to not redo them:

1. **persist the fold cache** across restarts — the folded chain is a pure function of
   `(depth, key, value)`, so it is safe to write to disk and reload; this is engineering, not consensus;
2. **reduce `EXEC_TREE_DEPTH`** (256 today) — folds scale linearly with depth, but this is a consensus
   change and needs its own argument.

Neither has been attempted. Both are larger wins than the FRI lever, and neither requires touching the
proof format.

---

## 8. Related reading

The result above comes from the Johnson-bound regime the model already implements. If we ever want to
push further, the relevant literature is **proximity gaps for Reed–Solomon codes** (Ben-Sasson, Carmon,
Ishai, Kopparty, Saraf) and the **ethSTARK documentation**, which is the standard reference for exactly
this queries-vs-blowup accounting and for the proven/conjectured split the model reports.

`libSTARK` (the original 2018 reference implementation) is **not** a useful source here: it is
binary-field with additive FFTs where NADO is Goldilocks prime-field, it has no recursion, and its own
README warns it is academic-grade and "very likely contains multiple serious security flaws".
