# Execution-layer VM & proving-system frontier — research findings

**Status: research note (2026-06-30), design input only — nothing here is built.** This
records a multi-source, adversarially-verified survey of the *next-generation* VM /
proving frontier, run to answer a sharp question: **is there a design "better than all of
them"** for NADO's planned execution layer (`doc/execution-layer.md`)? The honest answer
is **no — "better than all on every axis" is structurally impossible** for a
post-quantum chain, and *why* it's impossible is the most useful result here.

Method: 6 search angles → 27 sources fetched → 127 claims extracted → 25 verified by
3-vote adversarial check (23 confirmed, 2 refuted). Primary sources (IACR ePrint, CRYPTO/
ASIACRYPT papers, project specs) preferred; vendor benchmarks flagged. This field moves
monthly — **re-validate against fresh 2026 benchmarks before any build commitment.**

---

## 1. The key result: PQ-soundness and a cheap verifier structurally trade off

The single most important finding (verified 3-0, a16z/Thaler "SNARK Security and
Performance"): **there is a structural tension between post-quantum soundness and a cheap
verifier.**

- **Hash/FRI-based systems** (FRI, Ligero, Brakedown, Orion, and by extension
  Circle-STARK/Stwo, Plonky3, Binius, BaseFold) are transparent and **plausibly
  post-quantum** — hashing is their only cryptographic primitive — **but their verifier
  cost grows *linearly* with the number of security bits**, because a single
  polynomial-commitment query yields only ~2–4 bits of security.
- **Constant, cheap verifiers belong only to the non-PQ pairing / discrete-log systems**
  (Groth16, PLONK-KZG, Marlin, Bulletproofs, Nova) — all broken by Shor, all **disqualified
  for NADO** (`doc/quantum-resistance-and-vms.md`).

Quantified on Ethereum: a PLONK (pairing) proof verifies for **<300,000 gas**, while
StarkWare's FRI (PQ) proofs cost **~5,000,000 gas** — and StarkWare ran at *lower* security
(~80-bit vs ~100–110-bit). The cheap-verifier axis favors exactly the systems NADO cannot
use. **So any PQ choice pays a verifier premium, and "dominate everything" is off the
table.** That is not a gap in the survey — it is the shape of the problem.

---

## 2. The frontier in three PQ-relevant camps (+ one disqualified)

### Camp A — Lookup-centric zkVMs proving a *standard* ISA (Jolt / Lasso)
The "lookup singularity" thesis (Thaler/Whitehat): make the circuit do *only* table
lookups. Jolt proves standard RISC-V (RV32IM) by giving each instruction a giant lookup
table concatenated into "Just One Lookup Table," so **prover cost scales with input size,
not ISA size** — adding instructions is cheap and the toolchain is simpler. This is the
strongest data point on "prove a standard ISA vs. design a custom provable ISA": you may
not *need* a custom ISA.

- **Maturity:** implemented, peer-reviewed (Jolt, EUROCRYPT 2024; Lasso). Two honest
  asymmetries: the *verifier's* field work *does* grow with the number of primitive
  instructions, and the cheap-table trick needs instructions that decompose into small
  subtables.
- **PQ status:** **as launched, NOT post-quantum** — it shipped on elliptic-curve
  commitments (Hyrax/BN254). Its roadmap migrates to the hash-based **Binius** commitment,
  which would make it *plausibly* PQ and (claimed) ≥5× faster prover — but that is
  **roadmap, not confirmed-shipped**, and the ≥5× is a proponent projection, not a measured
  benchmark.

### Camp B — Hash-based transparent backends (the mature PQ option)
FRI, BaseFold, **Circle-STARK / Stwo over Mersenne-31 (M31)**, Plonky3, Binius.
**These ARE post-quantum and the most production-mature** (RISC Zero, SP1, Starknet/Cairo
run hash-based STARKs on mainnet today). They pay the §1 verifier premium.

- **BaseFold** (CRYPTO 2024): transparent, field-agnostic, hash-only multilinear PCS;
  O(n log n) prover, **O(log² n) verifier** (polylog, *not* constant). Generalizes FRI to
  any foldable code, removing FRI's FFT-friendly-field requirement.
- **Circle-STARK / Stwo over M31:** best fit for **phone/commodity CPU** validators — M31
  has cheap modular reduction (~1.3× faster than BabyBear) and Stwo produces **much smaller
  proofs than Binius** (Stwo 92.5 KiB vs Binius64 360 KiB on Blake2s).
- **Binius (binary-tower fields): REMOVED from the production shortlist.** Its developer
  **Irreducible shut down (Nov 12, 2025)** with no production deployments (Binius64
  relicensed MIT+Apache). Its one real edge — binary-tower **ASIC hardware-efficiency** —
  is **irrelevant to phone CPU validators**. This is a decisive, recent maturity flag my
  training cutoff would have missed.

### Camp C — Lattice-based PQ succinct proofs (the genuinely new frontier)
The most novel branch, and the only family that could *eventually* beat FRI on PQ + small
proof + sublinear verifier **jointly**:
- **Greyhound** (CRYPTO 2024): first concretely-efficient lattice PCS (Module-SIS,
  transparent), **O(√N) verifier**, ~93 KB proofs at N=2³⁰; composes with **LaBRADOR** for
  polylog proofs + sublinear verifier.
- **LatticeFold+** (CRYPTO 2025): PQ folding scheme, 5–10× faster than LatticeFold;
  explicitly PQ where the Nova folding family is **not**.
- **RoK and Roll** (ASIACRYPT 2025): first lattice SNARK to **break the "quadratic
  barrier,"** Õ(λ) proof size + succinct verification; 2026 follow-up **RoKoko** ~200 KB.
- **Maturity:** **research-grade.** Verifiers are *sublinear* (O(√N), "succinct"), **not
  the phone-cheap *constant*** you'd want, and absolute sizes (tens-to-200+ KB) and
  on-mobile cost are unproven.

### Disqualified — pairing / discrete-log (Groth16, PLONK-KZG, Nova family)
Constant cheap verifiers, but broken by Shor. **Not usable on a PQ chain.** Listed only so
the trade-off in §1 is explicit: the cheapest verifiers exist, just not for us.

---

## 3. Maturity map

| Camp | Examples | PQ-sound? | Verifier | Maturity |
|---|---|---|---|---|
| A — lookup VM, standard ISA | Jolt/Lasso | not yet (EC today; Binius=roadmap) | grows w/ #instrs | implemented, peer-reviewed |
| B — hash/FRI backends | Circle-STARK/**Stwo/M31**, Plonky3, BaseFold, RISC Zero, SP1, Cairo | **yes** | linear in security bits (polylog field ops) | **mainnet** |
| B — Binius | binary towers | yes | — | **orphaned (Irreducible shut down Nov 2025)** |
| C — lattice | Greyhound, LatticeFold+, RoK-and-Roll | **yes** | sublinear (O(√N)/succinct) | **research-grade** |
| ✗ disqualified | Groth16, PLONK-KZG, Nova | **no** | constant/cheap | mainnet (but non-PQ) |

---

## 4. The forward bet for NADO (synthesis — *medium* confidence)

No design dominates, so the defensible move is a **pragmatic synthesis, not a novel
domination**:

- **Primary bet:** a **hash-based Circle-STARK / Stwo backend over M31** (post-quantum,
  the most phone-performant mature PQ backend, smallest proofs among hash backends), paired
  with a **lookup-centric (Jolt-style) VM ported to that PQ commitment** (best
  dev-ergonomics, cheapest ISA extension, and NADO's LMDB KV state model fits a
  RISC-V/lookup VM with memory-checking).
- **Runner-up / research hedge:** **lattice folding** (LatticeFold+ / Greyhound /
  RoK-and-Roll) reserved for the **Phase-2 single settlement verifier** — the one place a
  small PQ proof matters most — but as a *research track*, not a Phase-1 production
  dependency.
- **Explicitly not recommended:** a fully novel custom-provable-ISA-on-binary-field design
  (the Binius ecosystem just collapsed); and Binius itself for production.

### What must be proven out first (the honest ceiling)
1. **On-phone (ARM) verifier cost.** *Every* verifier figure in the sources is asymptotic
   or measured on x86 servers (AWS C7i). Nobody measured wall-clock/peak-memory on the
   mobile/commodity validators that *define* NADO's constraint. This is the #1 unknown.
2. **Phase-2 settlement proof size/cost.** The single on-chain PQ verifier's proof size and
   cost (with a recursive wrapper) is the *binding* constraint and is unproven — and is
   exactly where lattice (Õ(λ)/~200 KB) might or might not beat FRI's linear-in-security
   verifier in practice.
3. **Did Jolt actually ship its PQ (Binius/Twist-and-Shout) backend,** and does the
   lookup-singularity dev-ergonomics advantage survive the move to a PQ commitment?

---

## 5. Caveats & refuted material (do not rely on)

- **Refuted (1-2, did not survive verification):** the claim that ePrint 2026/858 proves an
  *unconditional* FRI/STIR/WHIR soundness theorem *above the Johnson bound* (replacing a
  2025-disproved up-to-capacity conjecture). **Treat FRI/STARK high-rate soundness as
  not-clearly-settled**, not newly theorem-backed, when leaning on the leading PQ backend.
- **Vendor benchmarks:** binius.xyz / irreducible.com are Irreducible's own (cherry-pick
  risk); rivals reportedly beat Binius64 on Keccak. The Jolt/Lasso claims are a16z's own
  team but have independent peer-reviewed substance.
- **Time-sensitivity:** Irreducible shut down 2025-11-12; Jolt's PQ migration is roadmap;
  lattice proof sizes are dropping fast (RoKoko already improved RoK-and-Roll to ~200 KB);
  the gas figures and StarkWare's ~80-bit security are point-in-time.

---

## 6. How this lands against NADO's docs

- Confirms `doc/quantum-resistance-and-vms.md`: the proof system, not the VM, decides PQ —
  and the PQ requirement is what *creates* the verifier-cost tension.
- Confirms `doc/execution-layer.md` Phase-2: the single on-chain settlement verifier is the
  binding constraint; choose it hash-based (Circle-STARK/Stwo) for production now, keep
  lattice as the hedge — never a pairing-SNARK wrapper.
- The phone-cheap-verifier axis is unmeasured on ARM — a concrete prerequisite to flag
  before committing to programmability.

> Primary sources: a16z "SNARK Security and Performance" and "FAQs on Jolt"; Jolt eprint
> 2023/1217 (EUROCRYPT 2024); BaseFold eprint 2023/1705 (CRYPTO 2024); Greyhound eprint
> 2024/1293 (CRYPTO 2024); LatticeFold+ eprint 2025/247 (CRYPTO 2025); RoK-and-Roll eprint
> 2025/1220 (ASIACRYPT 2025) / RoKoko 2026/575; Irreducible shutdown post (2025-11-12);
> binius.xyz/benchmarks; StarkWare Stwo; Vitalik on Circle STARKs. Full verified-claim set
> + votes archived in the research run output.
