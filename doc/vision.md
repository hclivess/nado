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

## 6. Throughput — what proofs buy (verification), and what they don't (bandwidth)

**Proofs remove the re-execution bottleneck. They do NOT remove the data bottleneck.** Be precise about this,
because overclaiming here is how a roadmap starts to read as fantasy. In a re-execution chain every node reruns
every transaction, so throughput is capped by the slowest validator's CPU. Succinct proofs lift that cap off
*validation*: a validator checks a proof in O(1) instead of re-executing the work (goals 1 & 4), so a phone can
confirm an epoch of arbitrary execution without ever having had the CPU to run it. That decouples *verification*
from *execution* — the real, defensible win, and it is genuinely in the code (`build_epoch_trace` aggregates N
calls into one proof; `recursive_verify` folds independent epochs; extending the settled tip is an O(1) root
check, `ops/settlement_ops.settlement_justified`, not a re-run).

What no proof removes is the cost of the DATA itself. Someone still has to transmit and store the transactions;
verifying them cheaply doesn't make them cheap to move. VISA-rate transaction data — tens of thousands of tx/s —
is a large, sustained bandwidth and storage load, well beyond a home connection and nowhere near a phone. So
"VISA-scale on every node" is not a claim this design makes. The honest scaling story separates two roles a
re-execution chain wrongly conflates:

- **Verification** — deciding the chain is correct. Proofs make this O(1) and data-light: a light client checks
  the settlement proof and *samples* data availability (downloads a few random pieces, not the whole block) to be
  convinced the data exists without holding it. This stays cheap for everyone, phones included, however high
  throughput climbs — so the *right to verify* is never priced out, which is the property that actually keeps a
  chain decentralized.
- **Data carrying** — disseminating and storing the transactions. This scales with throughput and is bounded by
  real bandwidth and disk. It is borne by a smaller set of provisioned producer/data nodes, and the honest way to
  push it further is engineering, not magic: data-availability sampling to keep light clients cheap, and
  eventually sharding the data so no single node carries all of it.

So "VISA-scale that is validated, not trusted" means the achievable thing: as throughput rises, the cost to
*verify* the chain and to *check its data is available* stays flat for every participant — nobody is forced to
trust a handful of operators — even though the data-carrying nodes are necessarily better-provisioned. VISA-rate
*validation* on a phone is realistic; VISA-rate *data on every node* is not, and the design says which it delivers.

On the DAG/mempool idea from §5: a DAG of proven transitions is a reasonable way to *order* concurrent proposals
(narwhal/DAG-BFT-style — decouple "make data available" from "agree on order"), but only among the provisioned
producer nodes that already carry the data. It does not let a phone ingest the mempool and it does not repeal
bandwidth limits — it is a throughput technique for the producer layer, and one we are not committing to. The
part that survives is narrow and solid: because every vertex carries its own O(1) proof, ordering never
re-imposes an execution cost, so that layer scales with the producers' bandwidth rather than with anyone's CPU.

---

**Non-negotiables while pursuing these** (from hard lessons, see the audit history in doc/zk-recursion.md):
never ship a partial verifier as complete on the money path; every fold/recursion verifier must be
verifier-authoritative and adversarially re-audited; soundness first, throughput second — a fast unsound
prover is worthless.
