# NADO execution layer — design note (programmable contracts without burdening L1)

**Status: DESIGN ONLY. Nothing here is built.** This note exists to record the
architecture *before* mainnet locks the L1 assumptions, so that adding programmability
later is a clean extension rather than a retrofit. The L1 described in `protocol.py` and
`ops/` is authoritative; this document is forward-looking.

The one-line thesis: **NADO L1 should never grow a general virtual machine.**
Programmability belongs in a *separate execution layer* that uses NADO only for the two
things a base layer is uniquely good at — **ordering** and **data availability (DA)** —
and that touches consensus, at most, through a single bounded **proof verifier**. This
keeps every property that makes NADO *NADO* (fair phone-mining, post-quantum security,
objective finality, deliberate simplicity) intact.

---

## 1. Why this is the shape

### 1.1 The problem programmability would solve

NADO already extends itself by hand. Every protocol action — `bond`, `unbond`,
`withdraw`, `register`, `heartbeat`, `slash`, `attest`, `commit`, `reveal` — is a
**reserved keyless recipient** (`RESERVED_RECIPIENTS` in `protocol.py`) with a hardcoded
arm in `ops/account_ops.py:reflect_transaction` and a matching validation arm in
`ops/transaction_ops.py`. That list only grows, and **each addition is a
consensus-critical core change**. This is the "precompile everything" model. It does not
scale: tokens, multisig, escrow, vesting, DAOs, oracles — each would be another
hand-written reserved arm forever.

A general execution environment is the clean version of what NADO is already doing
by hand. That is the *real* benefit — an architecture-debt cure, not a "we need DeFi"
argument.

### 1.2 The constraint it must not break

NADO's identity is structural, not marketing:

- **Phone-mineable.** The two-lane OPEN/BONDED design (`doc/mining.md`) exists so a phone
  can validate and produce in slot time. A general VM on L1 makes *block validation*
  unbounded — every node must re-execute every contract — which silently demotes phones
  from validators to light clients. That is a different project.
- **Just-hardened security surface.** Objective fork-choice, the `FINALITY_DEPTH = 30`
  floor, FFG-lite finality, commit-reveal RANDAO, equivocation slashing, and the
  Section 7.4 audit fixes are all *base-layer* guarantees. A VM is the single largest
  consensus-critical surface you can add: the interpreter *becomes* consensus, gas
  metering must be bit-identical across nodes, and any nondeterminism (a JIT, a float, an
  unmetered loop) is a chain split.
- **Browser-reproducible determinism.** The light-miner must recompute identical hashes
  and txids (`doc/determinism-and-chain-id.md`): canonical JSON, **no floats**,
  BigInt-safe integers. A consensus-embedded VM would have to honor the same bar inside
  every opcode.
- **Deliberate simplicity.** Fees were just hidden behind "automatic (NADO)"
  because users don't understand raw units. A first-class gas market — per-instruction
  pricing, priority fees, out-of-gas reverts — is the structural opposite.

The execution-layer model is the design that lets us say **yes** to RISC-V contracts
without any of those four costs landing on L1.

---

## 2. The dividing line: how much does L1 know?

There is exactly **one** decision, and it defines everything else: *how much does NADO L1
know about the execution layer?* It sits on a spectrum, and it is also the lever between
"the L2 inherits NADO's security" and "the L2 is a sibling chain renting space."

| | **Sovereign (Phase 1)** | **Settlement (Phase 2)** |
|---|---|---|
| L1 role | Ordering + DA only | Ordering + DA + **verifies one proof** |
| L1 code added | A blob carrier (one tx type) | Blob carrier **+ a proof verifier** |
| Who defines canonical L2 state | The execution-layer software (sovereign) | L1, by accepting only proven state roots |
| L1↔L2 bridge | Trusted / multisig / social | **Trust-minimized** |
| New consensus-critical surface | **None** | A verifier (bounded, auditable in isolation) |
| VM bug can fork NADO? | **No** | **No** |

The progression is deliberate: **ship sovereign, upgrade to settlement.** You get
programmability immediately with zero L1 risk, and the one later concession (a verifier,
*not* a VM) is what buys NADO's security back for the bridge.

---

## 3. Phase 1 — the sovereign execution layer

> **Implementation status (Phase 1 AND Phase 2 built).**
> - **Phase 1 (sovereign):** the `blob` reserved recipient (`protocol.py`, validated/burned in
>   `transaction_ops`/`account_ops`, `tests/test_blob.py` incl. the **per-block blob-bytes cap** §3.3), a
>   deterministic stack VM (`execnode/vm.py`), a contract state store (`execnode/state.py`), a tailing
>   execution node + query API (`execnode/execnode.py`), submit CLI + example token; determinism tested in
>   `tests/test_execnode_vm.py`. Proven live end-to-end (token deploy + transfer via blobs).
> - **Phase 2 (settled + bridge):** `settle` records a bonded validator's `(exec_cursor, state_root)`;
>   `ops/settlement_ops.settlement_justified()` (the pluggable verifier seam) settles a root once bonded
>   shares exceed 2/3, exposed at `/get_settled` (`tests/test_settlement.py`). The exec `state_root` is a
>   **Merkle** root, so a `bridge` deposit → exec credit → `bridge_withdraw` burn → **Merkle proof against
>   the settled root** → L1 escrow release round-trips trust-minimized (`tests/test_bridge.py`).
> - **Still to do:** the DA availability/pruning window, and **Phase-2b** — replacing the bonded-quorum
>   settlement verifier with a single succinct STARK validity proof (the seam is in place). Trust today is
>   the bonded stake (a validator committee), not yet a validity proof.


### 3.1 What L1 does: carry opaque blobs

The execution layer is its **own binary, its own state, its own (optional) node set.**
Contract transactions never reach `reflect_transaction`. They are posted into NADO blocks
as **opaque blobs** that L1 orders but never interprets.

Concretely, this is *one* new reserved recipient — call it `blob` — added to
`RESERVED_RECIPIENTS`, whose `reflect_transaction` arm does almost nothing on L1:

- It validates the envelope (sender is a real keyed address, signature/txid valid,
  `chain_id` bound, fee paid for the bytes consumed) **exactly like any other tx** — this
  reuses the existing `validate_transaction` path with no new crypto.
- It does **not** decode the payload. The payload (`tx["data"]`, or a side-carried blob
  body referenced by hash) is consensus-*ordered* and consensus-*available*, but
  consensus-*opaque*. L1's only assertions are size and fee.

That is the entire L1 surface for Phase 1: a fee-metered, size-capped, opaque byte
carrier. It cannot fork the chain because L1 never branches on its contents.

### 3.2 What the execution layer does

A separate set of **execution nodes** (run by whoever wants programmability; phones do
not) read the ordered `blob` payloads out of finalized NADO blocks and:

1. Decode them into execution-layer transactions.
2. Run them through the **RISC-V VM** (Section 5).
3. Maintain contract state in their own store.

The canonical execution state is defined by the *execution-layer software*, not by NADO
consensus — this is the Celestia "sovereign rollup" model. NADO gives this layer a
total order and guaranteed availability of inputs; the layer supplies its own state
transition function and (in Phase 1) its own security for anything it can't anchor.

**Honest framing of Phase 1:** at this stage the execution layer is closer to "a separate
chain that uses NADO for ordering + DA" than "an L2 secured by NADO." That is the correct
*first* step — it ships fast, it is fully isolated, and it lets the VM and gas model
iterate on their own cadence without ever risking the base layer. Section 4 is what
upgrades it into a real rollup.

### 3.3 DA constraints that protect phone-mining

Even opaque blobs are not free: they grow block size, and phones download/relay blocks.
The following are **hard requirements**, not optimizations — without them, DA quietly
re-burdens the exact property we set out to protect:

- **Blob size cap per block** (a new consensus constant, e.g. `MAX_BLOB_BYTES`), so block
  size stays bounded and slot-time validation/relay stays phone-feasible.
- **Blob bodies are prunable and not part of the long-term state index.** L1 commits to a
  blob by hash in the block header preimage; the body need only be available for a
  bounded availability window, after which full execution nodes (not L1, not phones) are
  the durable store.
- **Phones sync headers + payment state and skip blob bodies.** The light-miner already
  reproduces only what it needs (`doc/determinism-and-chain-id.md`); a phone validates
  that a blob of the committed hash/size was *available and paid for*, never its contents.
- **Blob fees price bytes, not computation.** This is a small, clean DA-fee term
  (raw-per-byte) on top of the existing `MIN_TX_FEE` floor — emphatically **not** a gas
  market on L1. Computation is priced *inside* the execution layer (Section 5.2), where
  it belongs.

---

## 4. Phase 2 — settlement via a single proof verifier

What turns "separate chain using NADO for DA" into "L2 whose correctness NADO enforces"
is L1 being able to **verify a proof** about execution-layer state transitions. That is
the *only* new consensus-critical surface NADO ever takes on for programmability — and it
is a **verifier**, not a VM:

- **Validity (ZK) proof — recommended.** The execution layer periodically posts a state
  root plus a succinct proof that "applying the ordered blobs since the last root yields
  this new root." L1 runs a **proof verifier** (a new reserved arm, e.g. `settle`) that
  accepts the new root only if the proof checks. L1 never executes a contract; it checks
  a proof. This is bounded, auditable in isolation, and is the natural payoff of the
  RISC-V → ZK lineage (Section 5.4).
- **Fraud proof — alternative.** L1 hosts an interactive dispute game instead; cheaper
  steady-state, but it requires challenge windows and a bisection referee, and the
  dispute game itself becomes consensus-critical. For NADO, a validity verifier is the
  cleaner fit and pairs better with the PQ posture.

Once L1 only blesses proven roots, the **bridge is trust-minimized**: an L1→L2 deposit
locks NADO at a `bridge` reserved address against the proven root, and an L2→L1 withdrawal
is honored by L1 because the proof attests the L2 burn. No multisig, no social trust.

**The bridge is the crux of the whole design.** Everything reduces to one tradeoff:
maximum isolation (Phase 1) and trust-minimized bridging (Phase 2) are the two ends of the
*same* lever. There is no free lunch — if L1 verifies nothing, the bridge is trusted; if
the bridge is trust-minimized, L1 verifies something. Most rollup exploits historically
live in the bridge, so this is where review effort concentrates.

---

## 5. The RISC-V VM (lives in the execution layer, never on L1)

RISC-V is the right ISA *if and only if* it stays out of L1 consensus. The reasons it is
the right pick once it's in the execution layer:

### 5.1 Why RISC-V over EVM / WASM

- **No legacy to honor.** NADO carries no EVM debt, so there is no reason to inherit
  256-bit-word semantics or a bespoke bytecode. Contracts compile from Rust/C/C++ via
  mature LLVM/GCC toolchains.
- **Open metering references.** CKB-VM and PolkaVM are production RISC-V contract VMs to
  copy gas-metering, host-ABI, and memory-model design from, rather than inventing one.
- **ZK-native.** RISC-V is the substrate ZK proving converged on (RISC Zero), which is
  precisely what makes the Phase 2 validity-proof path natural.

### 5.2 Determinism and gas (inside the layer)

The execution layer must hold the *same* determinism bar L1 holds, just one layer down:

- **Deterministic gas metering.** RISC-V has no native gas concept, so the VM instruments
  basic blocks and charges per instruction/memory op. Metering must be bit-identical
  across execution nodes — the same consensus discipline as L1, scoped to the layer.
- **No nondeterminism.** No wall-clock, no floats in consensus-relevant paths, no
  ambient randomness (draw from the NADO RANDAO beacon when needed — `doc/mining.md`
  §3.3), no JIT unless provably deterministic. An interpreter is the safe default;
  PolkaVM-style sandboxed JIT is an optimization to justify separately.
- **Canonical execution-tx encoding.** Reuse NADO's canonical bytes discipline
  (`canonical_bytes`, sorted keys, integer-only, BigInt-safe) so the layer is itself
  browser-verifiable where useful.

### 5.3 State model — NADO's KV already fits

Contract state reduces to key→value, which is exactly what NADO's state index already is:
a single schemaless LMDB KV store applied under one atomic `write_txn` per block
(`ops/kv_ops.py`, `doc/storage.md`). The execution layer reuses that shape for its own
store — namespaced per contract, ordered writes, one atomic apply per execution batch.
This is the one part of programmability NADO does **not** have to fight its substrate for.

Contract **accounts have no keys** (no ML-DSA keypair); a contract address is derived
deterministically from its deployer + nonce (or code hash). The layer must define this
addressing — it is *not* the L1 `make_address` scheme, which is reserved for
key-controlled and reserved accounts.

### 5.4 Post-quantum alignment

L1 user authentication is ML-DSA-44 (FIPS 204) and stays that way. The execution layer
should not weaken that: external calls authenticate with PQ signatures, and the Phase 2
proof system should be chosen PQ-soundly (a hash-based / lattice-friendly proving system),
so "PQ-secure base layer + PQ-sound RISC-V execution layer" is one coherent story rather
than a quantum-soft L2 bolted onto a quantum-hard L1.

> **The VM is irrelevant to quantum resistance — the *proof system* decides it.** RISC-V
> (any ISA) is quantum-*neutral*; a "RISC-V zkVM" is PQ only if its final verifier is
> hash-based (STARK/FRI) and **not** a pairing-SNARK wrapper (Groth16/PLONK-KZG). This
> disqualifies the common Groth16-wrapped RISC Zero / SP1 configurations for NADO. Full
> reasoning in [quantum-resistance-and-vms.md](quantum-resistance-and-vms.md).

---

## 6. What touches L1 vs. what never does

**Touches L1 (small, bounded, reviewable in isolation):**

- Phase 1: one `blob` reserved recipient — opaque, size-capped, fee-metered byte carrier.
- Phase 1: `MAX_BLOB_BYTES` + a raw-per-byte DA fee term; blob bodies prunable.
- Phase 2: one `settle`/verifier reserved arm + a `bridge` lock address.

**Never touches L1:**

- The RISC-V VM, the interpreter, the gas schedule.
- Contract state, contract addressing, contract storage growth.
- The gas market / fee-per-instruction economics.
- Any contract execution. L1 orders inputs and (Phase 2) checks one proof — it never runs
  a contract.

This is the whole point: the blast radius of programmability is confined to a byte carrier
and a proof checker. Phone-mining, the audit posture, finality, and the simple L1 fee UX
are untouched.

---

## 7. A smaller adjacent option (not the execution layer)

If the goal is *only* to stop precompile sprawl — not to add general programmability —
there is a cheaper move that stays entirely inside L1: **generalize the reserved-recipient
dispatch** in `ops/account_ops.py` / `ops/transaction_ops.py` into a small, **explicitly
non-Turing-complete** operation table (or a tightly gas-bounded mini-interpreter over a
handful of fixed opcodes). That kills the "one hand-written arm per feature" debt without
putting a general execution engine in consensus.

This is **orthogonal** to the execution layer and worth doing regardless: it is the 80% of
the benefit (sprawl relief) with ~0% of the burden (no unbounded computation, no state
blowup, no phone demotion). The execution layer is for when you want *open-ended*
programmability that an operation table deliberately cannot express.

---

## 8. Open problems

- **Bridge security** (the crux) — economic and cryptographic review of the Phase 2
  verifier and the deposit/withdrawal flow; this is where rollups historically fail.
- **DA availability proofs** — Phase 1 assumes blob availability for a window; a malicious
  producer withholding a blob body it committed needs a detection/penalty story
  (data-availability sampling is the heavyweight answer; a bounded window + full-node
  redundancy is the light one).
- **Proof-system choice** — PQ-soundness vs. proving cost vs. verifier cost on commodity
  L1 nodes (the verifier must stay phone-irrelevant but full-node-cheap).
- **Execution-layer consensus (Phase 1)** — a sovereign layer needs its own sybil
  resistance / ordering-of-execution rules until Phase 2 anchors it; define whether it
  borrows NADO's order verbatim (single-sequencer-by-L1-order) or runs its own.
- **Fee/MEV interaction** — blob ordering on L1 vs. execution ordering in the layer, and
  whether L1's `txid`-sorted in-block order (CO-8) is a sufficient sequencing rule for the
  layer.

---

## 9. Decision summary

- **L1 never gets a VM.** Programmability is a separate execution layer.
- **Phase 1: sovereign.** L1 carries opaque, size-capped, fee-metered blobs (one `blob`
  reserved recipient). Zero new consensus-critical surface; VM bugs cannot fork NADO;
  phones unaffected (headers + payment state, skip blob bodies).
- **Phase 2: settlement.** Add *one* proof verifier (`settle`) + a `bridge` address. This —
  not a VM — is the only consensus surface programmability ever adds, and it is what makes
  the L1↔L2 bridge trust-minimized.
- **RISC-V is the right ISA**, but only inside the execution layer: no EVM debt, Rust/C
  toolchains, ZK-native for Phase 2, PQ-aligned proof system.
- **NADO's KV state model already fits** contract state; that part is free.
- **The bridge is the crux** — isolation and trust-minimized bridging are the two ends of
  one lever.
- **If you only want sprawl relief**, generalize the reserved-recipient dispatch into a
  non-Turing-complete op table instead (Section 7) — orthogonal, cheap, no execution layer
  required.

Net: a *completely individual* execution layer is the design that lets NADO say yes to
RISC-V smart contracts without spending the fairness, security, or simplicity that the
base layer was built to protect. Bank the identity on L1; keep RISC-V as a deliberate
execution-layer bet, sovereign-first and settlement-later.

> Cross-references: `doc/whitepaper.md` §8 (roadmap), `doc/mining.md` (two-lane / phone
> validation), `doc/storage.md` + `ops/kv_ops.py` (KV state index), `protocol.py`
> (`RESERVED_RECIPIENTS`, fees, finality), `doc/determinism-and-chain-id.md` (canonical
> bytes / browser reproducibility). This note is **design-only**; none of it is implemented.
