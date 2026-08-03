# Getting a settle-with-proof onto the chain

Everything below is measured on alphanet-15 (2026-08-03), not estimated. The consensus side has accepted
validity proofs for several generations; no node has ever successfully submitted one. This document says
why, and what the viable shape is.

## 1. The measurements

| quantity | value | how |
|---|---|---|
| settle tx, protocol params | **97.30 MiB** | logged live by the exec node |
| dominant term | `segment.proof.openings` | field-by-field breakdown |
| scaling | **0.381 MiB per FRI query**, linear | 0.892 MiB @ NQ=2, 3.166 @ 8, 24.385 @ 64 |
| FRI params | `BLOWUP=2`, `NUM_QUERIES=320`, `GRIND_BITS=18` | `execnode/stark/fri.py` |
| security | `320 × 0.4 + 18 ≈ 146 bits provable` (Johnson) | fri.py's own accounting |
| `pre_contracts` share | ~1.6 MiB of 97 (**<2%**) | measured against 25 live contracts |
| a full block | **~256 KiB** | `transaction_pool_max_bytes` comment; a produced block logged 71,163 B |
| L1 submit cap | 8 MiB (was aiohttp's 1 MiB default) | raised 2026-08-03 |
| settle cadence, as configured | **~2 per minute** | 58 settles in 30 min, live |
| segments per settle | **1** for the whole span (fold off) | logged: "span→586: 1 segment(s)" |

Two things follow immediately, and both killed a candidate fix:

* **The payload is O(queries), not O(state).** `verify_bound_epoch_replay` (in-circuit membership instead
  of shipping `pre_contracts`) would save under 2%. It is not the fix.
* **The binding constraint is the BLOCK, not the HTTP cap.** 97 MiB is ~380× a block. The best
  query/blowup reparameterisation — blowup 16 at ~64 queries for the same 146 bits — still gives 24 MiB,
  ~95× a block. A 4–6× reduction cannot close a 380× gap, so **the proof can never ride inside a block at
  any FRI parameters.**

## 2. Why the obvious cadence makes it hopeless, and why that is fixable

At the configured cadence the exec node settles roughly every 30 seconds, so proofs would be produced at

    97.30 MiB × 2/min  =  194 MiB/min  ≈  280 GiB/day

which no small network can carry on any transport, DA included.

But proof size is **independent of span**: with the fold off, `prove_settlement_sparse` emits ONE bound
epoch for the entire span, and the size is dominated by FRI queries rather than by the number of calls
(ROADMAP's own measurement: proof size constant while calls go 1→8). So a settle covering 240 blocks costs
the same ~97 MiB as one covering 2.

Settling at the protocol maximum span instead of every poll is therefore a pure win, and a large one:

| cadence | proofs/day | at 97 MiB | at 24 MiB (blowup 16) |
|---|---|---|---|
| every ~2 blocks (today) | ~2880 | 280 GiB/day | 69 GiB/day |
| every `SETTLE_PROOF_MAX_SPAN` (240 blocks ≈ 24 min) | ~60 | **5.8 GiB/day** | **1.4 GiB/day** |

1.4 GiB/day is an ordinary DA workload. That is the difference between "infeasible" and "engineering".

## 3. The transport

The proof cannot go in a block, so it goes to DA and the settle tx carries only its commitment. This is not
new machinery: `/da/publish`, `proof_da` and `da_fetch` already exist, and the shielded path already
submits exactly this way ("the caller publishes it to /da/publish and submits an L1 blob carrying only the
commitment", `execnode/execnode.py`).

## 4. The actual open problem: WHEN the proof is verified

`validate_transactions_in_block` runs inside `verify_block`, **strictly before incorporation, for every
block a node incorporates — including historical blocks during a fresh sync.** So a naive DA reference
means a joining node must fetch and verify one ~97 MiB proof per settle across the whole chain. That is the
real obstacle, and it is about verification timing, not size.

Three candidate resolutions, with the honest objection to each:

1. **Depth-gate the re-verification.** Verify a settle proof only while its block is within
   `FINALITY_DEPTH` (45) of the tip; below that, accept it on accumulated weight, exactly as the chain
   already treats deep history for snapshot bootstrap ("classic weak-subjectivity checkpoint").
   *Objection:* a full-syncing node then no longer independently verifies historical settlements — it
   inherits them. That is a real reduction in what a from-genesis sync proves, and it should be a
   deliberate decision rather than a side effect.

2. **Lean on the quorum path for history.** A settlement can be justified by bonded quorum OR by proof.
   Historical settles carry quorum attestations regardless, so a fresh syncer could rely on those and treat
   the proof as tip-time evidence only. *Objection:* this quietly makes the proof decorative for anyone who
   was not online at the time, which is most of the security argument for having it.

3. **Recursion to a genuinely succinct proof.** The K→1 fold is the intended answer and would make all of
   this moot. *Objection:* measured 2026-08-02, a fold over the W=106 exec AIR ran **5h07m at 492% CPU and
   8.2 GB without completing**. It needs to reduce size by ~1000×, not 4×, and it currently cannot produce
   at all.

## 4b. The FRI blowup lever, measured — and rejected

`fri_blowup` is not a tunable. `stark.py` sets `blowup = 2·next_pow2(max_degree)`, `N = blowup·T` and
`deg_bound = next_pow2(max_degree)·T`, so `fri_blowup = N/deg_bound = 2` is a **structural identity**
(`stark_native.py` pins it for exactly that reason). Raising it to 16 means an **8× larger LDE domain**,
paid in NTT and Merkle work on every column.

Measured at equal provable security (blowup 2 needs 4× the queries of blowup 16 for the same bits):

| config | proving time | proof size |
|---|---|---|
| blowup 2, NQ 8 | 53.3 s | 3.166 MiB |
| blowup 16, NQ 2 | **374.4 s** | **1.070 MiB** |

**3.0× smaller for 7.0× slower.** At protocol strength that turns ~97 MiB into ~32 MiB while multiplying a
proving cost that is already the binding constraint (the K→1 fold cannot complete at all).

And it does not change the conclusion it was meant to serve: 32 MiB is still ~128× a block, so DA is
required either way — and at the max-span cadence the difference is 5.7 vs 1.9 GiB/day, which no operator
would notice. **Paying 7× proving time to move between two numbers that both need DA is a bad trade, so
this lever is dropped.**

## 5. Recommendation

Sequence, cheapest first:

1. **DONE** — settle at the max span rather than every poll. Pure win, no consensus change, 48× less proof
   data.
2. ~~Raise the FRI blowup~~ — **rejected on measurement**, see §4b: 3× smaller for 7× slower, and DA is
   needed regardless.
3. **Publish to DA, commitment on chain.** Machinery exists. This is now the next step.
4. **Then** decide §4 deliberately — it is a security-model choice about what a from-genesis sync proves,
   and it is the only part that should not be decided by whoever is implementing.

Until (1)–(3) land, `NADO_EXEC_SETTLE_PROVE` should stay off: it costs minutes of proving per tick to build
a transaction that is rejected on size.
