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
covers. The last non-succinct edge — the execution AIR's instance periodic (program/args/io tables), which a
public verifier poly_evals per query — is being closed by COMMITTING those columns (`stark.commit_periodic`,
`vm_circuit.COMMIT_PERIODIC`): the verifier opens them O(log N) per query and binds their roots to the epoch's
commitments, instead of rebuilding and interpolating O(T) tables.

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

## 5. Validity is not canonicity — collapsing the many valid tips

A validity proof establishes that a state transition is CORRECT, not that it is THE ONE — and that distinction
is easy to miss. Just as proof-of-work admits many valid blocks at the same height (any tx set/ordering that
meets the difficulty target is a legitimate tip), a validity proof admits many valid tips: any ordering or
selection of L2 calls that executes honestly has an equally sound proof. Two proposers who order the same
mempool differently both hold real proofs of real transitions. So proofs, on their own, do not hand you a
single chain — they filter out INVALID histories and leave potentially many valid ones. Uniqueness is still a
consensus problem, exactly as under PoW; zk removes "did this execute correctly?" from the fork-choice's plate
but not "which of these correct histories is canonical?".

The direction we are heading is to bind those two answers tightly and cheaply. The on-chain settle-with-proof
path (`ops/transaction_ops.py`, `doc/zk-recursion.md` §5 step 8) already requires every proof to EXTEND the one
committed settled tip — a settlement's `pre_root` must equal the namespace's current settled root (or
`EXEC_GENESIS_ROOT` for the first) — so among all the valid proofs a proposer could produce, only the one
continuing the canonical settled history is accepted; the rest are valid but off-tip. Layered with the
weight-based fork choice that already orders L1 (and the bonded quorum as a liveness floor), the many valid
tips collapse back to a single canonical settled chain. The endgame is that the proof answers "is this
transition valid?" in O(1) and the chain-extension + fork-choice rules answer "is it canonical?" just as
cheaply — so a phone can confirm not just that a history is sound but that it is THE history, without re-running
any of it. Making that collapse unambiguous and constant-cost is an explicit goal, not an afterthought.

## 6. Throughput — VISA-scale that is VALIDATED, not trusted

**Scale by making validation cheap, not by centralizing trust.** VISA clears tens of thousands of transactions
a second by asking almost no one to check the work — a handful of trusted operators do, everyone else takes
their word. A blockchain that copies that shape (a few big sequencers/validators everyone trusts) buys
throughput by spending the one thing it exists to protect. The four goals above buy the same throughput the
opposite way: if verifying an epoch is O(1) and independent of what it executed (goals 1 & 4), then a phone
can keep validating no matter how much execution the network does — so throughput can grow without pricing
anyone out of verifying. Decentralization survives the scale because checking got cheap, not because trust got
concentrated.

The lever is that **proofs decouple global throughput from any single node's capacity.** In a re-execution
chain, every node must re-run every transaction, so the whole network's throughput is capped at what the
*slowest* validator can execute. Here, execution and validation are different jobs: execution FANS OUT (many
provers, many epochs, produced concurrently — nothing forces them through one machine) and validation FANS IN
(K→1 recursion, goal 3, collapses all of it into one O(1) check). Adding execution capacity raises throughput
without raising any verifier's burden. Concretely in this repo the pieces already point this way: an epoch is
already N calls aggregated into ONE proof (`build_epoch_trace`), independent epochs fold with `recursive_verify`,
and the only thing that is inherently serial is the settled-tip chain — extending it is an O(1) root check
(`ops/settlement_ops.settlement_justified`), not a re-execution. So the serial bottleneck is a hash comparison,
not the workload.

The direction we are heading connects this straight back to §5. The many valid tips a proof system admits are,
viewed together, a DAG of proven transitions: different proposers execute different (equally valid) slices of
the mempool in parallel, each slice carrying its own succinct proof, referencing the tips it builds on. Nothing
about validity forces them into a line — the linearization is a separate, cheap step. A DAG-ordered mempool
(narwhal/DAG-BFT-style: decouple "disseminate + prove availability" from "order") is a natural fit, because the
expensive part of ordering — "is each of these blocks real and its execution correct?" — is already answered in
O(1) by the vertex's proof, and admission also requires it to extend a valid settled root (§5). A deterministic
fork-choice then collapses the whole DAG to one canonical settled history. The width of the DAG (how many
proposers work in parallel) sets the throughput; the cost to validate any one vertex stays constant no matter
how wide it gets. We don't need to commit to a specific DAG protocol yet — the point is that the proof stack is
being built so that when we scale out to many concurrent proposers, validation cost per vertex does not move.
That is the whole game: VISA-scale numbers with phone-scale validation, and no trusted operator in the middle.

---

**Non-negotiables while pursuing these** (from hard lessons, see the audit history in doc/zk-recursion.md):
never ship a partial verifier as complete on the money path; every fold/recursion verifier must be
verifier-authoritative and adversarially re-audited; soundness first, throughput second — a fast unsound
prover is worthless.
