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

## 6. Throughput — SCALE-OUT (O(1) per node, Θ(N) total)

**Proofs remove the re-execution bottleneck. They do NOT remove the data bottleneck — so the goal is to make the
data bottleneck scale OUT.** Be precise about this,
because overclaiming here is how a roadmap starts to read as fantasy. In a re-execution chain every node reruns
every transaction, so throughput is capped by the slowest validator's CPU. Succinct proofs lift that cap off
*validation*: a validator checks a proof in O(1) instead of re-executing the work (goals 1 & 4), so a phone can
confirm an epoch of arbitrary execution without ever having had the CPU to run it. That decouples *verification*
from *execution* — the real, defensible win, and it is genuinely in the code (`build_epoch_trace` aggregates N
calls into one proof; `recursive_verify` folds independent epochs; extending the settled tip is an O(1) root
check, `ops/settlement_ops.settlement_justified`, not a re-run).

What no proof removes is the cost of the DATA itself. Someone still has to transmit and store the transactions;
verifying them cheaply doesn't make them cheap to move. So the naive picture — every node ingests every
transaction — *does* hit a bandwidth wall, and VISA-rate data on a single home connection is not realistic. But
that picture is the thing to get rid of, not to accept: the workaround is that **no node has to hold all the
data.** Two modern, deployed techniques do this:

- **Erasure-coded data availability + sampling (DAS).** The block's data is Reed–Solomon-extended so any ~50% of
  the pieces reconstruct the whole; a light client then downloads a handful of *random* pieces and, if they're
  all present, is convinced (to overwhelming probability) that the entire block is recoverable — without ever
  downloading it. Checking availability becomes O(1) samples, independent of block size. This is live in Celestia
  and is the core of Ethereum's danksharding.
- **Sharded storage / dissemination.** The pieces are spread across the network so each node stores and serves a
  *fraction* of the data, not all of it. Per-node load is `total ÷ N`, so it stays bounded as throughput grows —
  aggregate capacity is the sum of many ordinary nodes, not the ceiling of one.

Put together, these turn the data problem from "one machine must go faster" into "add machines." That is the
target term this section aims at, the throughput analogue of O(1):

> **SCALE-OUT — per-participant cost stays O(1) while total throughput grows with the network (Θ(N)).**

Verification is O(1) via proofs (goals 1 & 4); data *availability* is O(1) via sampling; storage and bandwidth per
node are O(total ÷ N) → bounded. So every participant's cost stays flat as the network grows, and the way you get
more throughput is more nodes, each doing a constant amount — horizontal scale, not a faster monolith. VISA-scale
stops being a per-node heroics problem and becomes a network-size problem, which is the tractable kind. That is a
real and defensible destination — not "every phone is a VISA-throughput full node," but "no participant's cost
rises as throughput does, so throughput can rise as far as the network is wide."

The DAG/mempool idea from §5 slots in here as the *ordering* layer for that scaled-out data: a DAG of proven
transitions (narwhal/DAG-BFT-style — decouple "make data available" from "agree on order") lets many producers
disseminate and reference each other's data in parallel, and because every vertex already carries its own O(1)
proof, ordering never re-imposes an execution cost — the ordering layer scales with aggregate producer bandwidth
(itself sharded), not with any one node's CPU. We are not committing to a specific DAG protocol; the durable
point is that O(1) verification, O(1) data-availability sampling, and Θ(N) sharded data are mutually compatible —
so SCALE-OUT is an engineering target to build toward, the same way O(1) is.

---

**Non-negotiables while pursuing these** (from hard lessons, see the audit history in doc/zk-recursion.md):
never ship a partial verifier as complete on the money path; every fold/recursion verifier must be
verifier-authoritative and adversarially re-audited; soundness first, throughput second — a fast unsound
prover is worthless.
