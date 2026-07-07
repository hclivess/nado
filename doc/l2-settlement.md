# L2 settlement & ultimate scaling — design note

**Status: DESIGN, building on BUILT primitives.** Phase-2a settlement (bonded-stake quorum) and the
Merkle bridge are already implemented and tested (`ops/settlement_ops.py`, `execnode/`, `tests/test_settlement.py`,
`tests/test_bridge.py`). This note takes those primitives and draws the path to **ultimate scaling**: NADO L1
as a **shared settlement + data-availability + ordering layer** for many execution layers ("rollups"), where
L1 work per settlement is **O(1) in the number of L2 transactions**. It extends
[`execution-layer.md`](execution-layer.md) (Phase 1/2 architecture) and
[`rolling-mode-and-da.md`](rolling-mode-and-da.md) (DA + pruning).

The one-line thesis: **NADO never executes L2 transactions — it orders their data, guarantees availability,
and verifies one proof per batch.** Aggregate throughput then scales with the number of execution nodes, not
with anything L1 does. Phones stay first-class (headers + DA sampling), exactly as today.

---

## 1. What already exists (the settlement substrate is live)

| Primitive | Where | What it does |
|---|---|---|
| `blob` recipient | `protocol.RESERVED_RECIPIENTS`, `MAX_BLOB_BYTES_PER_BLOCK = 256 KiB` | opaque, size-capped, fee-metered byte carrier — L1 orders it, never decodes it |
| `execnode` | `execnode/execnode.py`, `state.py`, `vm.py` | tails **finalized** L1 blocks, decodes blobs → exec txs, runs the VM, maintains a Merkle-rooted state store |
| `settle` tx | `construct_settle_tx` → `{exec_cursor, state_root}`, fee-exempt | a bonded validator running an exec node attests "at cursor C the exec state root is R" |
| settlement verifier | `settlement_ops.settlement_justified(cursor, root, reg)` | a root is **SETTLED** when attesting bonded shares `> SETTLE_NUM/SETTLE_DEN` (2/3). `latest_settled()` derives the highest justified `(cursor, root)`; exposed at `/get_settled` |
| trust-minimized bridge | `bridge` / `bridge_withdraw` recipients; `execnode.withdrawal_proof(nonce)` | L1 deposit escrows NADO → exec credit → exec burn → **Merkle proof against the settled root** → L1 releases escrow |

Two properties of this substrate matter for everything below:

- **`settlement_justified()` is a pluggable seam.** Today it counts bonded stake (a committee). Phase-2b
  replaces the body of that one predicate with **verification of a single succinct validity proof** — the
  signature and every caller stay identical. `execnode.py` already caps POST bodies at 16 MB with the comment
  *"proofs are ~1–4 MB; each apply verifies a ~1 MB proof"* — the code is written in anticipation of this.
- **Settled state is revert-safe.** `latest_settled()` is *derived* from attestations, not a stored
  watermark, and L1's `FINALITY_DEPTH = 30` floor means a settled root anchored below finality can never be
  reorged out. Settlement inherits L1 finality for free.

So NADO is already a settlement layer for **one** execution layer. Ultimate scaling is: make it **many**, and
make each settlement **a proof instead of a vote**.

---

## 2. The settlement interface, generalized to N rollups

Today `settle` carries `{exec_cursor, state_root}` for the single canonical exec layer. Generalize the tuple
with a **namespace** (rollup id):

```
settle : { ns, prev_cursor, new_cursor, prev_root, new_root, proof? }
```

- `ns` — a rollup namespace (a registered id, or simply the deploy address / code hash of the rollup's state
  machine). L1 keeps one settled-root pointer **per `ns`** (`latest_settled(ns)`).
- `blob` payloads likewise carry `ns` so each rollup's ordered input stream is separable.
- Everything else is unchanged: L1 orders the blobs (per-`ns` sequence = L1 `txid`-sorted in-block order,
  CO-8), guarantees their availability for the DA window, and advances `latest_settled(ns)` when the `ns`
  batch is justified.

This is the whole generalization. NADO becomes a **shared** ordering + DA + settlement layer: any number of
execution layers post blobs and settle roots under distinct namespaces, all secured by the same L1 finality,
with **zero new consensus-critical surface per rollup** — a rollup is just data under a namespace plus one
verifier call, not a core change.

---

## 3. The three settlement regimes (increasing trust-minimization)

The `settlement_justified(ns, cursor, root, …)` seam admits exactly three implementations. Ship left-to-right;
each is a strictly stronger security claim behind the same predicate.

| Regime | `settlement_justified` body | Trust | Status |
|---|---|---|---|
| **2a — bonded quorum** | 2/3 of bonded stake attested `(ns, cursor, root)` | a validator committee is honest | **BUILT** |
| **2b — validity proof** | one succinct **STARK** proves `apply(blobs[prev..new]) : prev_root → new_root` verifies | cryptographic soundness only | seam ready |
| **2c — recursive aggregation** | one STARK proves **many** rollups' batches at once (proof-of-proofs) | cryptographic; **O(1) L1 cost for the whole ecosystem** | design |

**2b — single validity proof (the trust flip).** The exec layer periodically posts `new_root` + a STARK that
re-executing the ordered blobs from `prev_root` yields `new_root`. L1 verifies the proof; it never re-executes
a contract and never trusts a committee. This is the payoff of the RISC-V → ZK lineage
([`execution-layer.md`](execution-layer.md) §5.4). **PQ-soundness is mandatory:** the proof system must be
**hash-based (STARK/FRI), never a pairing-SNARK** (Groth16/PLONK-KZG) — a pairing wrapper reintroduces a
quantum-breakable primitive into a PQ chain and is disqualified
([`quantum-resistance-and-vms.md`](quantum-resistance-and-vms.md)). The verifier must be **phone-irrelevant but
full-node-cheap**: a few ms and a few hundred KB, run only by full nodes, never by phones.

**2c — recursive aggregation (the "ultimate" lever).** A proof-aggregation step (run off-L1 by a prover
market) folds the batch proofs of *many* rollups over a settlement epoch into **one** recursive STARK. L1
verifies a **single** proof per epoch and advances every `latest_settled(ns)` it covers. Now L1's settlement
cost is **constant regardless of how many rollups exist or how many transactions they processed** — the
verification cost is decoupled from aggregate throughput entirely. This is the mechanism by which "ordering +
DA + one proof" scales without bound on the execution side.

---

## 4. Where the throughput actually comes from

Per settlement epoch, **L1's total work is bounded and independent of L2 transaction count**:

1. **Carry blobs** — capped at `MAX_BLOB_BYTES_PER_BLOCK` (256 KiB/block today; a consensus constant tuned to
   keep slot-time relay phone-feasible). This bounds *DA bytes*, not computation.
2. **Verify one proof** — in 2c, a single recursive STARK for the whole ecosystem.

Everything expensive happens **off L1**: contract execution, state growth, and proving all live in execution
nodes and a prover market. Aggregate TPS therefore scales with **the number and capacity of execution nodes**,
throttled on L1 only by the DA byte budget — which is itself relieved by §5. The base layer stays exactly what
it is today: a bounded, phone-validatable ordering layer.

**Concretely, L1 gains no new per-transaction cost.** A rollup doing 10k TPS and one doing 10 TPS impose the
*same* settlement load on L1 (one proof, capped blob). That is the definition of a settlement layer.

---

## 5. Data availability at scale (the real bottleneck)

Verifying a proof says the transition is *correct*; it does **not** say the inputs are *available* for others
to reconstruct L2 state. DA is where scaling actually strains, and it is designed in
[`rolling-mode-and-da.md`](rolling-mode-and-da.md) §4.2 — pulled in here as a hard dependency:

- **Erasure-code each block's blob data** (Reed–Solomon, ~2× expansion) and spread coded chunks across the
  validator set so **any ~50% reconstruct the whole**. A phone stores only its assigned chunks.
- **Hash-based Data Availability Sampling.** Phones verify availability by random-sampling a few chunks
  against a **Merkle/FRI commitment in the block header — NOT KZG** (PQ constraint, same as the proof system).
- **Availability challenge window + voluntary archival.** During the retention window anyone can challenge a
  missing chunk; after the window + finalization + reconstruction guarantee, blob bodies are prunable
  (`HISTORY_RETENTION_BLOCKS`). Longevity beyond the window = archive nodes / external DA pinning.

DA is what lets L1 raise `MAX_BLOB_BYTES` (more rollup throughput) **without** forcing phones to store more —
they sample, they don't store. Rolling mode and the blob cap must be tuned together; they share one budget.

---

## 6. The bridge is still the crux

Every rollup exposes a trust-minimized two-way bridge, escrow held per-`ns` at the `bridge` reserved address:

- **Deposit:** L1 `bridge` tx escrows NADO against `ns`; the exec node credits it exec-side (already built).
- **Withdraw:** exec-side burn → `execnode.withdrawal_proof(nonce)` → L1 `bridge_withdraw` with a **Merkle
  proof against `latest_settled(ns)`** (2a) or an inclusion claim under a **validity-proven** root (2b). L1
  releases escrow only against a settled root, so a bad exec-layer state can never drain the bridge.
- **Escape hatch (censorship resistance) — to design.** A forced-withdrawal path: if a rollup's sequencer/prover
  stalls, users must be able to exit against the last settled root via L1 alone. Historically where rollups
  fail; gets its own review.

Security invariants that must hold at every regime: settled roots sit **below the finality floor** (no reorg);
the proof system and DA commitments are **PQ-sound hash-based**; the bridge honors **only** settled roots; and
`latest_settled` stays **derived** (revert-symmetric) so a reorg of a `settle`/proof tx cleanly recomputes.

---

## 7. Sequencing & composability (open, but shaped by L1)

- **Free shared sequencing.** L1 already imposes a canonical, deterministic order on everything in a block
  (`txid`-sorted, CO-8). Using that as each `ns`'s input order makes NADO a **based rollup** substrate: the
  NADO block producer *is* the sequencer, so there is no separate sequencer to trust or decentralize, and
  cross-rollup ordering is globally consistent by construction.
- **Cross-rollup messaging.** Because all namespaces settle to the same L1 and read the same ordered stream, a
  message from rollup A to rollup B can be a blob A emits that B consumes, finalized against A's settled root.
  Full composability semantics (atomicity, latency) are an open design item.
- **Prover market.** 2b/2c need someone to produce proofs. In 2a proving is a fee-exempt bonded-validator duty
  (`maybe_settle`, every `SETTLE_EVERY` blocks); at scale, proving should become an **open, incentivized
  market** (post a valid proof, collect a bounty), decoupled from block production.

---

## 8. Phasing

1. **2a — bonded-quorum settlement + Merkle bridge. DONE.** Single namespace, committee trust.
2. **Namespaces.** Generalize `settle`/`blob` to carry `ns`; per-`ns` settled pointer + bridge escrow. Pure
   extension, no new consensus surface.
3. **2b — single STARK validity proof.** Replace the `settlement_justified` body with FRI-proof verification;
   flip bridge trust from committee to cryptography. Keep 2a as a fallback/liveness backstop during rollout.
4. **DA hardening.** Reed–Solomon + hash-based DAS + challenge window (unlocks higher `MAX_BLOB_BYTES`).
5. **2c — recursive aggregation + prover market.** One proof settles the whole ecosystem per epoch → constant
   L1 cost. Open, incentivized proving.
6. **Escape hatch + cross-rollup messaging.** Censorship resistance and composability.

---

## 9. Open problems

- **Proof cost & latency** — prover hardware, batch cadence vs. settlement latency, and keeping the FRI
  verifier full-node-cheap while phone-irrelevant.
- **Prover / sequencer decentralization** — based sequencing removes the sequencer problem but not the prover
  problem; the market design and its liveness under censorship.
- **Escape hatch** — the forced-exit path against the last settled root when a rollup stalls.
- **Namespace governance** — registration, spam/DoS on the shared blob budget, per-`ns` fair DA allocation.
- **Cross-rollup atomicity** — messaging semantics and settlement-epoch alignment across namespaces.
- **DA weight** — 1D Reed–Solomon + hash sampling is the right stage; full 2D-DAS is deferred until throughput
  demands it.

---

## 10. Decision summary

- **NADO is a settlement layer, not an execution layer.** It orders blobs, guarantees availability, and
  verifies one proof per batch — it never runs an L2 transaction.
- **The primitives are already live** (`blob`, `settle`, bonded-quorum `settlement_justified`, Merkle bridge);
  scaling is *generalize to namespaces* + *swap the verifier for a proof* + *aggregate proofs*.
- **Ultimate scaling = recursive proof aggregation (2c):** one hash-based STARK settles many rollups per epoch,
  so L1 cost is constant in aggregate L2 throughput.
- **PQ-soundness is non-negotiable:** STARK/FRI proofs and Merkle/FRI DA commitments — never KZG/Groth16.
- **Phones stay first-class:** headers + DA sampling, capped blob bytes, snapshot bootstrap — the identity is
  untouched at any chain age.
- **The bridge is the crux;** review concentrates there, and settled roots ride L1 finality so they can't be
  reorged.

> Cross-references: [`execution-layer.md`](execution-layer.md) (Phase 1/2, RISC-V VM, PQ proof system),
> [`rolling-mode-and-da.md`](rolling-mode-and-da.md) (DA, erasure coding, hash-based DAS, pruning),
> [`quantum-resistance-and-vms.md`](quantum-resistance-and-vms.md) (why proofs/DA must be hash-based),
> `ops/settlement_ops.py` (`settlement_justified` seam, `latest_settled`), `execnode/` (tailing node,
> `maybe_settle`, `withdrawal_proof`), `protocol.py` (`RESERVED_RECIPIENTS`, `SETTLE_NUM/DEN`,
> `MAX_BLOB_BYTES_PER_BLOCK`, `HISTORY_RETENTION_BLOCKS`). Settlement 2a + bridge are implemented; namespaces,
> validity proofs, aggregation, and DA hardening are design.
