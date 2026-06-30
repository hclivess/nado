# Quantum resistance lives in the proof system, not the VM

**Status: reference note.** Clears up a category confusion that matters for NADO's
execution-layer decision (`doc/execution-layer.md`): *"Is RISC-V quantum resistant?"* The
honest answer is that the question doesn't type-check — and understanding *why* is what
disqualifies a whole class of otherwise-attractive VMs for NADO.

---

## 1. An ISA is quantum-neutral, not quantum-resistant

RISC-V is an **instruction set architecture** — `add`, `load`, `store`, `branch`: a way to
*express computation*. "Quantum resistant" / "post-quantum (PQ)" is a property of
**cryptographic algorithms** — whether they survive a quantum adversary:

- **Shor's algorithm** breaks anything based on factoring or discrete log: RSA, elliptic
  curves, and **elliptic-curve pairings**.
- **Grover's algorithm** gives a square-root speedup against hashes / symmetric crypto —
  mitigated simply by doubling the output size (e.g. a 256-bit hash retains ~128-bit
  security).

An ISA has **no cryptographic hardness assumption to break**. Asking whether RISC-V is
quantum resistant is like asking whether x86 or the English language is — the property
lives one layer up, in the *software you run*, not in the instruction set. RISC-V will
happily *execute* post-quantum crypto (ML-DSA, hash-based proofs, lattice math) — it
neither helps nor hurts. It is **quantum-neutral**.

So for NADO's VM choice (`doc/execution-layer.md` §5): RISC-V the VM is **irrelevant to
quantum resistance** — fine to use, fine to avoid, it doesn't move the needle.

## 2. The PQ-determining layer is the PROOF SYSTEM

When people say "RISC-V **zkVM**," the RISC-V part is just the execution model. The quantum
resistance is determined **entirely by the proof system wrapped around the execution:**

| Proof backend | PQ-sound? | Why |
|---|---|---|
| Hash-based **STARK / FRI** (RISC Zero core, SP1 over Plonky3, Cairo, Miden) | **Yes** | Security rests only on hash collision-resistance; Grover is handled by doubling output |
| **Pairing-based SNARK** — Groth16, PLONK-**KZG** | **No** | Shor breaks the elliptic-curve pairing |
| Lattice-based succinct proofs (LaBRADOR, Greyhound, lattice folding) | **Yes (in principle)** | Lattice hardness; but maturity/verifier-cost still being evaluated (see research) |

The execution can be identical RISC-V either way. What makes the result PQ or not-PQ is
the cryptographic **seal**, not the VM.

## 3. The trap: the "cheap verifier" wrapper often breaks PQ

This is the part that bites. **RISC Zero and SP1 commonly wrap their final hash-based STARK
proof in a Groth16 (pairing) SNARK** — specifically to get a tiny, cheap proof that's
cheap to verify on Ethereum. The inner proof was post-quantum; the **outer seal the chain
actually verifies is quantum-breakable.**

So a single product ("a RISC-V zkVM") can be PQ **or** not-PQ depending purely on whether
its *last wrapping step* is hash-based or pairing-based. You cannot read PQ-soundness off
the VM name; you have to look at the final verifier.

Consequence for NADO: **RISC Zero / SP1 in their default Groth16-wrapped mode are
disqualified** as the Phase-2 settlement verifier — they would seal a post-quantum chain
with a quantum-breakable signature, which is incoherent. They qualify only in STARK-only
(unwrapped) mode — which costs you the cheap verifier, creating the central tension below.

## 4. What this means for NADO

NADO's stack must be PQ end-to-end, or it isn't PQ at all:

- **L1 signatures — already PQ.** User authentication is ML-DSA-44 (FIPS 204). Good.
- **The VM — irrelevant.** RISC-V or any ISA is quantum-neutral; pick it on toolchain /
  proving-friendliness grounds, not quantum grounds.
- **The Phase-2 execution-layer proof verifier — MUST be chosen PQ-sound.** A hash-based
  STARK/FRI (or a matured lattice proof), with **no pairing-SNARK wrapper**. Anything
  pairing-based here would be the one quantum-breakable link in an otherwise PQ chain.

### The central tension (the thing the research is hunting)

The PQ-sound proof systems (hash-based STARKs/FRI) tend to have **larger / heavier
verifiers** than the pairing-SNARKs everyone reaches for to get tiny on-chain proofs. But
NADO validators can be **phones**, so the on-L1 verifier must stay **cheap on commodity
hardware**. So NADO needs a proof that is simultaneously:

1. **post-quantum sound** (rules out pairing wrappers), and
2. **phone-cheap to verify** (the axis the rest of the field under-weights because their
   verifiers run on servers).

That pair of constraints — PQ-mandatory **and** verifier-must-run-on-a-phone — is exactly
the gap an existing product may not fill, and is why the execution-layer proving choice is
treated as an open research question (next-gen PQ fields like Circle STARKs / Binius, or
lattice proofs) rather than a settled pick.

---

> Cross-references: `doc/execution-layer.md` §5.4 (PQ alignment of the execution layer),
> `protocol.py` (ML-DSA-44 L1 signatures), `doc/determinism-and-chain-id.md` (the L1 PQ
> signature scheme). The frontier survey of PQ-sound, phone-cheap proving systems is an
> in-flight research item.
