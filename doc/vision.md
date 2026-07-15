# NADO proof-system vision — the four goals

These are the goals the zk/settlement work strives toward. Every design decision in the proof stack
(doc/zk-recursion.md, doc/zk-execution-proofs.md, doc/settlement-layer.md) should be justifiable against
them; anything that moves away from one of them needs an explicit, written reason.

## 1. Succinctness

**Verifying must not cost what executing cost.** A proof's verification time and size must be independent of
the amount of work it attests — a phone (or L1 itself) checks an epoch of arbitrary contract execution in
milliseconds, from a few kilobytes.

Concretely in this repo: the verifier does no O(T) work per proof — structured periodic columns evaluate in
O(period + sparse rows) instead of O(T) interpolation; verify-time domains are computed point-by-point, never
materialized; recursion-gadget verification costs O(queries · layers) regardless of the trace length it
covers. The remaining non-succinct edge is the execution AIR's instance periodic (program/args/io tables) —
interpolated once per segment, amortized over all query points.

## 2. Composability

**Proofs are building blocks, not endpoints.** Any proof in the system can become the INPUT of another proof:
an execution proof feeds a fold; a fold feeds a settlement bundle; a settlement bundle should eventually feed
a cross-epoch chain proof. That requires:

- a field-native, arithmetization-friendly hash everywhere in the recursed layer (alghash2 — no blake2b
  inside anything we recurse over);
- verifier-authoritative statements (the verifier re-derives every challenge, position, and schedule from
  committed roots — a proof carries WITNESS, never its own statement);
- uniform interfaces: one constraint-IR (air_ir) that any AIR lowers to, one commitment discipline
  (row commitment for wide traces), one transcript shape — so the same recursion gadgets serve the x² demo
  AIR and the W=106 execution AIR without new cryptography.

## 3. K→1

**Many proofs collapse into one.** An epoch is K segment proofs; the chain is many epochs; the goal is that
NO verifier ever needs to check K things. One recursion bundle (one FRI fold + one composition proof set)
re-establishes exactly what K separate `stark.verify` calls would — with the K statements rebuilt by the
verifier from small public parts, chained state roots binding the segments into a single transition.

Built: `recursive_verify` (K proofs → one bundle, column- and row-committed, single- and two-phase) and
`settlement_proofs.prove/verify_settlement_o1` (the money path: one bundle per epoch instead of K segment
verifications). Next rung: fold-of-folds — recursion DEPTH, so bundles themselves collapse and K→1 holds
across epochs, not just within one.

## 4. O(1)

**The endgame: constant.** Verification cost, proof size, and L1's settlement burden are all O(1) in the
amount of execution settled — not O(K), not O(T), not O(epochs). "O(1)" here means the constant-ish cost
class of checking a single fixed-shape recursion bundle (in practice polylog factors from Merkle paths and
query counts — the same constant every production recursive STARK means by O(1)).

This is what the other three goals compose into: succinct verification (no per-proof O(T)) × composability
(proofs consume proofs) × K→1 (fan-in at every level) = a chain whose full execution history is attested by
ONE constant-size, constant-time check — and a settlement seam (`ops/settlement_ops.settlement_justified`)
where that one check can stand in for the bonded quorum (proof OR quorum, never proof-blocks-liveness).

---

**Non-negotiables while pursuing these** (from hard lessons, see the audit history in doc/zk-recursion.md):
never ship a partial verifier as complete on the money path; every fold/recursion verifier must be
verifier-authoritative and adversarially re-audited; soundness first, throughput second — a fast unsound
prover is worthless.
