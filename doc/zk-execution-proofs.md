# ZK execution proofs for contracts — feasibility (issue #85)

**Status: BUILT (first cut live, 2026-07-14).** The proving stack from §4's build order is implemented and
tested end-to-end:

| piece | where | state |
|---|---|---|
| two-phase aux commitment + LogUp lookup argument | `stark/stark.py` (`aux_spec`), `stark/logup.py` | ✅ (`tests/test_stark_aux.py`; one-phase path byte-identical, shielded suites pass) |
| zkVM — field-native provable register VM + assembler | `execnode/zkvm.py`, `execnode/zkvmasm.py` | ✅ (`tests/test_zkvm.py`) |
| zkVM execution AIR (101 columns, 94 constraints, 4 LogUp buses) | `execnode/stark/vm_circuit.py` | ✅ (`tests/test_zkvm_circuit.py` — adversarial suite) |
| exec-layer runtime `"zkvm"` + digest registry + slot storage | `execnode/runtimes.py`, `state.py` | ✅ (`tests/test_zkvm_runtime.py` — 3-way differential) |
| proven-execution endpoints | `/exec/prove_call`, `/exec/verify_call` | ✅ |
| **epoch settlement proof** — binds `pre_root → post_root`, installs into the settlement seam | `execnode/settlement_proofs.py` | ✅ (`tests/test_settlement_proof.py` — incl. real `ops.settlement_ops` seam) |

Measured (this host, Python + native Goldilocks): a real contract call (blockhash randomness → LO32 →
DIVMOD → storage read/modify/write → conditional payout, T=512) **proves in ~25 s, verifies in ~0.25 s**;
the verifier applies the call by replaying its public I/O log (`zkvm.replay_io`) — **zero re-execution**.
Proof ~1.5 MB at 8 FRI queries (~10 MB at the protocol 64; Poseidon-Merkle/pruned openings are the known
size lever).

**The settlement path is closed end-to-end.** `settlement_proofs.prove_epoch` runs an ordered batch of zkVM
calls, emits one per-call proof each, and binds the pre/post **zkVM state roots** — which are byte-identical
to the `["kv", cid, "slots", …]` leaves `execnode/state.py` already commits in `state_root`, so `post_root`
*is* the settled root's zkVM projection. `verify_epoch` checks the whole batch with **no re-execution**
(verify each proof → replay each authenticated log → recompute the root), and
`settlement_proofs.settlement_verifier(...)` plugs straight into `ops.settlement_ops.set_settlement_verifier`
— the Phase-2b seam — so L1 can justify a root by proof instead of by bonded quorum.

The composition insight that kept this small: because each call's proof already binds its
authenticated public I/O log, the epoch transition needs **no second in-circuit memory argument** — it is
`verify-proof → replay-log → chain-root`. Two honest remainders, both noted where they live:
- **Succinct aggregation** — folding the N per-call proofs into one O(1)-verify proof (STARK recursion). At
  NADO's volume N is tiny and L1 verifying N sub-second proofs is fine; recursion is the scale hedge, not a
  correctness gap. The LogUp/aux machinery (`stark/logup.py`) is the groundwork a recursive verifier reuses.
- **Full-state settlement** — this proves the zkVM-contract projection; the other blob families
  (bridge/dividend/shielded) already carry their own L1-checkable proofs/arithmetic, and a full-state proof
  composes this with those.
- **Rust prover port** (~10×, the `wasm/goldilocks` lineage) — a throughput lever, orthogonal to correctness.

The analysis below is the original feasibility study that led to this design — kept for the reasoning.

---

**Original study (2026-07-14, pre-build):**
Question ([#85](https://github.com/hclivess/nado/issues/85)): can zk-STARKs replace redundant
contract execution — every node re-running every contract — with a single prover and a cheap
proof check? This note answers it *for NADO specifically*, with measured numbers from the
in-repo STARK stack (`execnode/stark/`), and lands on a concrete verdict + build order.

**TL;DR verdict:**

1. **Yes in principle — and it's already designed.** This is exactly *Phase-2b* of
   `doc/execution-layer.md`: replace the bonded-quorum settlement verifier with one succinct
   STARK validity proof. The seam (`ops/settlement_ops.settlement_justified()`) exists, the
   proving toolchain (FRI, AIR framework, Poseidon-style hash, native Rust field) exists and
   is live for the shielded pool.
2. **No for the current VM as-is.** `execnode/vm.py` is arithmetization-hostile (BLAKE2b
   `HASH`, JSON canonicalization, 4096-bit ints, 4096-char strings, string-keyed maps,
   BLAKE2b/JSON state root). Proving it would first require a **"provable VM v2"** redesign
   (§4).
3. **Know what you're buying.** For NADO, ZK execution proofs buy **bridge/settlement trust
   minimization**, *not* scalability. NADO already eliminated redundant execution
   architecturally: L1 nodes and phones never execute contracts; only exec nodes replay, and
   replaying a call natively costs ~microseconds. Proving that same call costs
   **10⁴–10⁶× more** than executing it. The premise in the issue ("10,000 computers run the
   same contract") describes Ethereum, not NADO.

---

## 1. What verifiable computation actually changes — and for whom

The issue's framing is correct as computer science: a STARK makes execution *asymmetric* —
one prover does the work, everyone else verifies a proof in milliseconds, and soundness rests
only on hash collision-resistance (post-quantum, no trusted setup — the same reason the
shielded pool uses it, `doc/privacy.md`).

But the *bottleneck it destroys* must actually exist to be worth destroying:

| chain | who re-executes a contract call | ZK proof would save |
|---|---|---|
| Ethereum | every full node, forever (incl. sync) | enormous redundant compute |
| **NADO today** | **exec nodes only** (opt-in, a handful); L1 orders opaque blobs, phones skip bodies | almost no compute — replay is native-speed and off-consensus |

NADO's cost model: a 100k-gas-cap call replays in well under a millisecond of native Python.
Measured live volume is currently ~0.01 blobs/block. The redundant-execution bill is ~zero.

What NADO *does* pay today is **trust**: the settled exec root (`/get_settled`) is attested by
a 2/3 bonded-validator quorum, and the L1↔exec **bridge** releases escrow against that root.
A validity proof upgrades exactly that: L1 would accept a root because *math says the blobs
produce it*, not because a committee said so. That is the real prize — it is the Phase-2b
"verifier, not VM" endgame — and it should be argued as a **bridge-security** feature, never
as a throughput feature.

A second real (smaller) win: an exec node could **sync by verifying proofs** instead of
replaying history, and light clients could trust `exec/view` answers against a proven root.

---

## 2. Measured reality of the in-repo prover (this machine, native Rust field)

The repo already ships a complete transparent STARK: `stark/field.py` (Goldilocks),
`stark/fri.py`, `stark/stark.py` (AIR: transition + boundary constraints, periodic columns),
`stark/alghash.py` (Poseidon-style x⁷ sponge — the STARK-friendly hash), `stark/merkle.py`,
`stark/transcript.py`, with the Rust `goldilocks_native` acceleration and a byte-identical
browser prover (`doc/wasm-prover.md`).

Measured (2026-07-14, `goldilocks_native.available() == True`):

| workload | prove | verify | proof size |
|---|---|---|---|
| join-split transfer (512×16 trace, x⁷ constraints, tree depth 12) | ~3.8 s | ms | ~1 MB |
| 1-column squaring AIR, T=8192 | ~3.4 s | ~0.2 s | ~1.2 MB |

Takeaways:

- **Throughput** ≈ low-thousands of trace rows/sec/column in the current Python-orchestrated
  stack. A full-capacity batch proof (`MAX_TRACE_ROWS = 2^17` rows × a ~40-column VM AIR)
  extrapolates to **tens of minutes** on this box. A pure-Rust prover (the existing
  `wasm/goldilocks` lineage extended from field ops to the whole pipeline) is the known ~10×
  lever, putting a max batch in the low minutes. Workable, because volume is tiny.
- **Verification is genuinely cheap**: 0.1–0.2 s in Python, once per settlement epoch. Even if
  every L1 node (phones included) verifies each `settle` proof, an hourly ~1 MB proof +
  sub-second check is a non-issue. The FRI verifier premium (`doc/execution-layer-vm-research.md`
  §1 — PQ verifiers pay linear-in-security-bits) is acceptable at settlement cadence; it is
  what rules out per-call proofs.
- **Proof size ~1 MB+** means proofs live in the DA store / exec layer, never as L1 state; L1
  verifies and records only the root (the `settle` arm as designed).

---

## 3. Why the *current* VM cannot be proven (and shouldn't be)

Proving "applying the ordered blobs to old root R₁ yields new root R₂" requires expressing
every VM semantic as field constraints. `execnode/vm.py` was designed for *replay*
determinism, not provability — four features are each individually disqualifying:

1. **`HASH` = BLAKE2b over canonical JSON.** The repo's own words (`stark/alghash.py`):
   BLAKE2b is "astronomically expensive to express as field constraints" — it is 64-bit
   XOR/rotate-heavy, needing bit decomposition over Goldilocks (~10³–10⁴ rows per
   compression), and the *JSON canonicalization* of the preimage would itself need an
   in-circuit byte machine. Every commit-reveal game uses this opcode.
2. **The state root is a BLAKE2b Merkle tree over JSON leaves** (`state.py` / `hashing.py`).
   Every `MSTORE` inside the proof needs an authenticated state update — i.e. in-circuit
   Merkle paths in the state-commitment hash. With BLAKE2b that's the §1 cost times tree
   depth, times every write in the batch. (This is exactly why the shielded pool grew a
   *field-native* twin — `alghash` commitments + `stark/membership.py` — instead of proving
   BLAKE2b paths.)
3. **Value domain: ints to 4096 bits, strings to 4096 chars, `CONCAT`, str/int-polymorphic
   `EQ`/`AND`/`OR`.** Goldilocks is a 64-bit field; 4096-bit arithmetic means 64-limb
   carry-checked bignum gadgets, and general string handling in-circuit is a byte-array VM of
   its own. Addresses-as-strings (`"ndo…"`) flow through `CALLER`, `PAY`, map keys.
4. **Dynamic string-keyed maps.** Provable random-access storage needs a memory-checking /
   permutation argument (grand-product or lookup columns). `stark/stark.py` deliberately has
   none — only transition + boundary constraints. (Addable within the existing framework as a
   degree-2/3 running-product column, but it is new core proof machinery, not circuit code.)

Conclusion: **do not try to arithmetize vm.py.** The honest route is the one the shielded
pool already walked: build the *field-native twin* and migrate.

---

## 4. What a provable VM ("VM v2") actually requires

NADO's position is unusually good for this: the VM is ~25 opcodes, gas-capped at 100k steps,
with tiny real-world call footprints (a game move is hundreds of instructions + a handful of
storage ops). This is *not* the "build RISC Zero" problem — it's a small custom zkVM over an
already-working AIR stack. Required changes:

- **Field-native values.** All stack/storage values become Goldilocks elements (or fixed
  4-limb 256-bit words for balances/hashes). Addresses encode as field digests
  (`alghash(DOM_OWNER, addr)` — the owner-tag pattern the shielded pool already uses).
  Strings go; `CONCAT` goes; commit-reveal uses `HASH = alghash` sponge.
- **State commitment over `alghash`.** The exec state root (or at minimum the per-contract
  storage subtrees) becomes a Poseidon-style sparse Merkle tree, so in-circuit reads/writes
  cost ~24 rows per tree level (the `membership.py` gadget, reused). Withdrawal/dividend
  leaves that L1 verifies transparently can stay BLAKE2b in a hybrid root.
- **Memory-checking argument** in `stark.py` (permutation/grand-product column) for stack and
  storage consistency — the one genuinely new piece of proof-system machinery.
- **The VM AIR itself**: one row per instruction (pc, opcode selector via periodic/lookup
  columns, stack top registers, gas counter) + a hash coprocessor region. Comparable in kind
  to `joinsplit_circuit.py`, several times larger in effort. Realistic trace budget: a game
  call ≈ 10²–10³ rows + ~10³ rows per storage write → **50–200 calls per 2^17 batch proof**.
- **Batching, not recursion.** There is no recursive verifier (FRI-in-FRI is a research
  project); one settlement proof = one big trace over the epoch's calls. At current volume a
  single 2^17 batch covers *days* of traffic. Recursion only becomes relevant at ~thousands of
  calls per epoch — a good problem to have, solvable then (or via the lattice-hedge track in
  `execution-layer-vm-research.md` §4).
- **Migration cost is real:** every deployed game contract (roulette, dice, coinflip,
  blackjack, mines, pets, bet, …) uses strings and BLAKE2b `HASH`. Per the no-legacy rule,
  v2 would replace, not coexist — contracts recompile to field-native semantics.

Prover economics stay honest: someone still executes — the prover — and pays ~10⁴–10⁶× the
native cost. That's fine *because* it's one machine per epoch, permissionless (anyone can
prove; the proof is its own authority), and it removes the bonded committee from the bridge's
trust base.

---

## 5. The cheaper middle option: a one-shot fraud proof

Because the VM is deterministic, gas-capped (100k steps), and value-bounded (4096-bit/char),
there is a much cheaper trust upgrade that needs **no ZK at all**: keep bonded-quorum
settlement, add a **non-interactive fraud proof** — a challenger posts one disputed call with
Merkle-proven pre-state, and the verifier re-executes *that single bounded call* and slashes
the lying quorum if the claimed post-root doesn't match. No trace, no prover, weeks not
months.

Its cost is architectural, and must be named: the re-execution arm puts a *bounded
interpreter* on L1, denting the "L1 never gets a VM" invariant (`execution-layer.md` §4
explicitly prefers validity proofs for this reason), and fraud proofs need challenge windows
(delayed bridge finality) plus at least one honest watcher. It is listed here because it
dominates the *trust-per-engineering-week* ratio, not because it's the endgame.

---

## 6. Verdict and recommended order

**Feasible: yes — as Phase-2b settlement validity proofs over a redesigned field-native VM,
using the existing STARK stack.** Not feasible (and not sensible) as per-call proofs or over
the current BLAKE2b/JSON/string VM. Not a scalability play — NADO's architecture already
avoided redundant execution; this is the bridge-trust endgame.

If/when pursued (this is multi-month, second-priority behind product):

1. **Memory-checking argument** in `stark.py` (permutation column) + tests. Unlocks
   everything; useful to the shielded pool too.
2. **VM v2 spec**: field-native opcode set, alghash `HASH`, address encoding, storage as
   alghash sparse-Merkle subtrees, per-batch gas/trace budget.
3. **VM AIR** proving single calls; differential-verify against the native v2 interpreter
   (three-way, per `doc` house rules — native replay stays the liveness path forever).
4. **Batch proof** (epoch of calls → old root/new root as boundary constraints), Rust-ify the
   prover hot path (extend `wasm/goldilocks`).
5. **Wire into the seam**: `settlement_justified()` accepts *either* 2/3 bonded quorum *or* a
   valid proof (belt-and-suspenders first), then proof-only once burned in.
6. Meanwhile, if bridge trust needs hardening sooner: the §5 fraud proof as an interim,
   explicitly marked for deletion at Phase-2b.

> Cross-references: `doc/execution-layer.md` (Phase-2/2b design, the seam),
> `doc/execution-layer-vm-research.md` (proving-frontier survey: PQ ⇒ verifier premium; Stwo/
> M31 + lattice hedge), `doc/quantum-resistance-and-vms.md` (proof system decides PQ — no
> Groth16 wrappers), `doc/privacy.md` + `stark/` (the live STARK stack these numbers come
> from), `doc/wasm-prover.md` (measured prover costs + the Rust acceleration lineage).
