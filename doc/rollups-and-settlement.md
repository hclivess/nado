# Rollups, namespaces, tunnels & the execution node — complete architecture

The single reference that ties the whole execution/settlement stack together: the **execution node**, **data
availability** (blobs), **namespaces** (multi-rollup — *now built*), what a **rollup** is on NADO,
**settlement**, and the **tunnels** (bridges + shielded + dividend + cross-rollup) that move value and messages
across the L1↔L2 boundary. It says exactly what is **built** vs **designed**, and points at the real code.

Companion notes: [`execution-layer.md`](execution-layer.md) (why the shape), [`l2-settlement.md`](l2-settlement.md)
(scaling argument), [`settlement-layer.md`](settlement-layer.md) (implementation spec),
[`rolling-mode-and-da.md`](rolling-mode-and-da.md) (DA), [`privacy.md`](privacy.md) (shielded pool).

---

## 1. The shape in one screen

```
   ┌──────────────────────────── NADO L1 (consensus) ───────────────────────────┐
   │  orders `blob`s (opaque, size-capped, fee-per-byte)                          │
   │  `settle` attestations → per-namespace bonded-quorum → latest_settled(ns)    │  ← settlement
   │  `bridge`/`bridge_withdraw` escrow + Merkle-proof exit  (tunnels)            │
   │  never executes an L2 tx · phones validate every block                      │
   └───────▲───────────────────────────────┬───────────────────────────▲────────┘
   settle  │           finalized blocks     │ blobs            /get_settled?ns=
   tx      │                                ▼                                    │
   ┌───────┴──────────── execution node (execnode/) ────────────────────────────┐
   │  tails FINALIZED blocks → decodes blobs → VM (vm.py) → state.py             │
   │  Merkle state_root() (stark/merkle.py) · shielded-pool STARK (stark/fri.py) │
   │  maybe_settle() posts `settle` if bonded · /exec/* read API                 │
   └────────────────────────────────────────────────────────────────────────────┘
                                        ▲
                                        │  /exec/* + /get_settled
   ┌────────────────────────────────────┴───────────────────────────────────────┐
   │  interface wallet (static/interface.*) — Settlement tab, shielded, bridge   │
   └──────────────────────────────────────────────────────────────────────────────┘
```

Three actors, one rule: **L1 orders + settles + guards the tunnels; the exec node executes; the wallet drives.**

---

## 2. The execution node (`execnode/`)

A separate process (run by whoever wants programmability — **not** phones). It is the authority on *what the
state is*; L1 is the authority on *what order the inputs came in and which root is settled*.

- **Tail.** Reads **only finalized** L1 blocks (so it inherits L1 finality; nothing it acts on can be
  reorged). `state.cursor` = highest L1 height fully applied.
- **Decode + execute.** Pulls `blob` payloads (and reserved exec ops: `bridge`, `shield`, `dividend`) out of
  each block in canonical (`txid`-sorted, CO-8) order and runs them through the deterministic stack **VM**
  (`execnode/vm.py`) into the contract store (`execnode/state.py`).
- **Commit.** `state.state_root()` is a **blake2b Merkle root** (`execnode/stark/merkle.py`) over the exec
  state — the object L1 settlement commits to and the tunnels prove against.
- **Prove (privacy today).** `execnode/stark/` is a real **hash-based FRI/STARK prover over Goldilocks**
  (`fri.py`, `joinsplit_transfer.py`, `goldilocks_native.py`) that proves shielded-pool transfers in-browser.
  This is the same PQ-sound machinery a Phase-2b **settlement** proof would reuse (§6).
- **Settle.** If run by a bonded validator with `NADO_EXEC_SETTLE=1`, `maybe_settle()` posts a `settle`
  attestation of `(cursor, state_root)` to L1 every `SETTLE_EVERY` blocks.
- **Serve.** A read-only `/exec/*` API for wallets/bridges:

  | Endpoint | Purpose |
  |---|---|
  | `/exec/root`, `/exec/settlement` | state root / cursor / settlement status (settle_enabled, last_settled_cursor, ns) |
  | `/exec/contracts`, `/exec/contract`, `/exec/view` | deployed contracts (+ runtime) + storage + read-only calls |
  | `/exec/examples`, `/exec/runtimes` | the starter contract library + the pluggable runtimes this node can run |
  | `/exec/bridge`, `/exec/withdrawal_proof` | bridge credit view + the Merkle exit proof (tunnels, §7) |
  | `/exec/shielded*`, `/exec/prove_transfer*`, `/exec/unshield*` | shielded pool + delegated **prove-only** proving |
  | `/exec/dividend*` | presence-dividend accrual + exit proof |
  | `/da/publish`, `/da/meta`, `/da/shard`, `/da/get`, `/da/accept` | erasure-coded DA store/serving (§3a) |

- **Pluggable runtimes.** The contract engine is a **registry** (`execnode/runtimes.py`): a contract records the
  runtime it deployed under (`{"op":"deploy","runtime":"<name>",...}`, default `stackvm`) and every call/view
  dispatches back to it, so the VM is swappable without touching `state.py` or L1 consensus. A runtime is any
  object with `validate_code` + `run(code, method, caller, args, storage) → (ok, ret, new_storage)`;
  determinism is the only hard requirement.

---

## 2a. The VM vs. the execution node — a precise split

These are two different things, and conflating them causes confusion. The **VM** is a pure function; the
**execution node** is the stateful service around it.

| | **The VM** (`execnode/vm.py`) | **The execution node** (`execnode/execnode.py` + `execnode/state.py`) |
|---|---|---|
| What it is | a deterministic **interpreter for one contract call** | a long-running **service** that holds state and orchestrates everything |
| Shape | `run(code, method, sender, args, storage) → (ok, ret, new_storage)` — a **pure function** | a process: tail loop + `ExecState` + `/exec/*` HTTP API |
| Owns state? | **No** — storage is passed in, new storage returned out | **Yes** — contracts, bridge balances, shielded pool, dividend, **outbox**, cursor (`ExecState`) |
| Knows blocks / L1 / cursor? | **No** | **Yes** — tails finalized L1 blocks, tracks `cursor` |
| Knows blobs / deploy / emit / bridge / settlement / namespaces? | **No** | **Yes** — `apply_blob` dispatch, `credit_deposit`, `maybe_settle`, per-`ns` states |
| I/O, network, time? | **None** (sandboxed — no ambient anything, no floats) | network (L1 + API), disk (persistence), poll timer |
| Determinism scope | one call is a pure function of its inputs | the **whole state** is a pure function of the ordered L1 blob stream |
| On failure | a revert is `ok=False`, storage unchanged | a bad blob is a skipped no-op; the loop never dies |
| Merkle root / proofs | — | `state_root()`, `withdrawal_proof`, `outbox_proof`, … |
| Relationship | **called by** the node for `deploy` (constructor) and `call` | **calls** the VM as a subroutine; does everything else itself |

**In one sentence:** the VM runs a *single contract method* in a sandbox; the execution node is the service
that holds the state, reads the ordered L1 blobs, decides what each blob does, invokes the VM for the contract
ones, and commits / serves / settles the result.

What happens when block N arrives:
1. the **exec node** pulls block N's blobs in L1 order (per namespace);
2. for a `call`/`deploy` blob it **invokes the VM** (`run(...)`) with the target contract's current storage;
3. it writes the VM's `new_storage` back into `ExecState.contracts`;
4. for non-contract ops (`emit`, `bridge`, `shield`, `dividend`) the **exec node handles them directly — the
   VM is never involved**;
5. it recomputes `state_root()`, persists, and (if bonded) settles it.

The VM never sees a bridge, a blob, a namespace, an outbox, or a settlement — those are **all** the exec node.
This split is deliberate: the VM stays a tiny, auditable, deterministic core, while the node carries the messy
orchestration. It also draws the Phase-2b line exactly — a validity proof would prove **the VM's execution**
(the pure function), never the node's orchestration.

---

## 3. Data availability — `blob`s

Programmability data reaches the exec layer as **opaque blobs** carried in L1 blocks:

- One reserved recipient, `blob`. L1 validates the envelope (real signer, fee ≥ `MIN_TX_FEE` per byte, size ≤
  `BLOB_MAX_BYTES`) and **never decodes the payload** — it is consensus-*ordered* and consensus-*available*,
  consensus-*opaque*. A blob can therefore never fork L1.
- **Per-block cap `MAX_BLOB_BYTES_PER_BLOCK` (256 KiB)** keeps block size phone-relayable at slot time.
- Blob bodies are prunable after the DA window (`rolling-mode-and-da.md`); phones **sample**, they don't store.
- Because blobs are opaque, a blob's **namespace lives inside the bytes the exec node decodes** — L1 needs no
  blob change to support many rollups (contrast §4).

---

## 3a. DA store & serving — for pruned blobs and oversized proofs — **BUILT**

A blob rides L1 for *ordering*, but its body is prunable and some payloads (a shielded-transfer STARK proof is
~1–4 MB) are far too big for the 64 KiB per-tx blob cap. Both need **data availability** beyond L1: an
erasure-coded store served across the peer network.

- **Codec (`ops/da.py`).** Reed–Solomon k-of-n over `P = 2⁶¹−1` (Lagrange), with an **index-bound hash-based
  (PQ) Merkle commitment** over the shard set. `encode(data,k,n) → {commitment, shards, …}`;
  `sample_proof`/`verify_sample` check one `(shard, proof)` against the commitment; `reconstruct` rebuilds from
  any k (and detects a corrupt shard via the redundancy).
- **Store + serving (`ops/da_store.py`, `/da/*`).** `DaStore.put` erasure-codes + stores every `(shard, proof)`;
  `accept` stores a *peer-supplied* shard **only if it verifies** against the commitment (no poisoning); `get`
  reconstructs locally; `prune` drops a settled commitment (rolling window). Served over `/da/publish · meta ·
  shard · get · accept`.
- **Universal fetch.** `da_fetch` resolves a commitment by pulling k(+1) **verified** shards from **across the
  live L1 peer set** (each peer runs the exec/DA node on the convention port) — not a single configured URL —
  and caches the result, so proofs **spread organically** as nodes fetch. Phones never participate: DA is a
  full/exec/DA-node concern; phones read state from relays.

### DA-backed shielded transfers (the shielded pool is multi-validator-settleable)

A shielded transfer's proof can't fit a blob, so **only its statement + the proof's DA `commitment` ride L1**
(`{op:"field_transfer","proof_da":<commitment>}`), fixing the transfer's order and (via the commitment) its
content. Each exec node **pre-resolves** every such proof from DA *before* mutating state, all-or-nothing per
block — an unavailable proof **stalls the block in L1 order** rather than half-applying it. Every honest node
fetches the identical bundle by commitment and applies the identical transfer, so the pool is reconstructible
by the whole bonded quorum (not a single operator). The wallet's on-device prover publishes the proof to
`/da/publish` then submits the commitment blob (DA-only — no legacy single-node apply path). See
[privacy.md](privacy.md).

---

## 3b. Contract library — the first exec-node contracts — **BUILT**

`execnode/contract_lib.py` is a small assembler abstraction plus **generalized method patterns** and the first
example contracts built from them, so new contracts compose from patterns instead of hand-rolled opcodes:

- **`counter_methods`** → `COUNTER`: a shared integer (`inc`/`get`).
- **`accumulator_methods`** → `TIP_JAR`: a per-caller running total (`add`/`of`/`mine`) — generalizes tips,
  reputation, per-address vote weight.
- **`commit_reveal_methods`** → `COIN_FLIP`: a fair 2-player coin flip — each player `commit`s `HASH(secret)`,
  then `reveal`s; `flip` returns the parity of `HASH(secret₀‖secret₁)`, unbiasable until both secrets are out.
  Generalizes sealed-bid auctions and lotteries. (Needs the VM's `HASH`/`MOD` primitives.)

This library `COIN_FLIP` is a fair-**result** oracle demo, not an escrow. (The VM has since gained a
`VALUE`/`PAY` escrow primitive and `MSTORE` now stores addresses as string values, so a contract *can* hold and
move real bridged NADO — the **live, staked** Coin Flip dApp is exactly that: a deployed contract
`execnode/contracts/coinflip.json` at cid `7ee95a0abd6e00d12edc3bf39f4c8f2d`; see
[exec-instructions.md](exec-instructions.md) §3/§5.) The library example is served to the wallet's Rollup tab
via `/exec/examples` for one-click deploy.

---

## 4. Namespaces (multi-rollup) — **BUILT**

A **namespace** (`ns`) is a rollup id, so many execution layers settle to L1 **independently** under the same
bonded quorum. L1 keeps **one settled pointer per `ns`** (`latest_settled(ns)`).

- **Where `ns` appears.** Only on the **settlement + tunnel** consensus surface — `settle` and
  `bridge_withdraw` — since blobs are opaque (their `ns` is exec-decoded). This keeps the L1 surface tiny.
- **Wire format (canonical).** `ns` lives in `data["ns"]`. The **default namespace is OMITTED** from `data`,
  so the pre-namespace execution layer's txs stay byte-identical and a redundant `data["ns"]="default"` is
  **rejected** as non-canonical (`ops/transaction_ops` settle arm). A namespace id is `[a-z0-9._-]`, ≤ 32
  chars (`protocol.valid_namespace`).
- **Uniqueness is per `(ns, validator, cursor)`** — the same validator may attest the same cursor in two
  different namespaces, and one rollup's settlement never touches another's. Enforced in the per-block dedup
  tag and `kv_ops.settlement_exists(ns, cursor, validator)`.
- **Storage.** The `settlements` DUPSORT db is keyed `ns \x00 be8(cursor)` (`kv_ops._settle_key`);
  `settlement_cursors(ns)` filters by prefix. Revert-symmetric (`settlement_put`/`settlement_del`).
- **Read.** `GET /get_settled?ns=<id>` → `{ns, exec_cursor, state_root}` (default `ns` when omitted).

Implemented across `protocol.py` (`DEFAULT_NS`, `valid_namespace`), `ops/kv_ops.py`, `ops/settlement_ops.py`,
`ops/account_ops.py`, `ops/transaction_ops.py`, `nado.py`, `execnode/execnode.py`; covered by
`tests/test_settlement.py` t7–t9 (isolation, canonical-form, bad-id rejection). **`execnode` now runs a
per-namespace state registry** (`NADO_EXEC_NAMESPACES`): the default full-featured layer plus contract-only
rollup namespaces, each with its own state file, blob-routed by the blob's `ns`, and settled independently via
`maybe_settle` (one `settle` per namespace). The `/exec/*` read endpoints take `?ns=`. Covered by
`tests/test_exec_namespaces.py` (routing, isolation, unrun-drop, default determinism).

---

## 5. What a rollup is on NADO

A rollup = **a namespace + the execution software that defines its state machine**, using NADO for ordering,
DA, and settlement. Two maturity levels (both supported by the substrate):

- **Sovereign (Phase 1).** The rollup posts blobs; its canonical state is defined by its own software. NADO
  gives total order + availability; the rollup supplies its own security for anything it can't yet anchor.
- **Settled (Phase 2).** The rollup also posts `settle` roots that L1 *justifies* (§6), so L1 enforces which
  root is canonical and the **tunnels become trust-minimized**.

Contracts run in the RISC-V-class VM off L1 (`execution-layer.md` §5); contract accounts are keyless
(address = deployer+nonce / code hash), distinct from L1's `make_address`.

---

## 6. Settlement — how a root becomes canonical

1. A bonded validator's exec node posts `settle{exec_cursor, state_root[, ns]}` (`construct_settle_tx`,
   fee-exempt, one per `(ns, validator, cursor)`).
2. On each block L1 evaluates `settlement_ops.settlement_justified(ns, cursor, root, bonded_registry)`:
   **attesting bonded shares > `SETTLE_NUM/SETTLE_DEN` (2/3)** — the same integer stake quorum as FFG finality.
3. `latest_settled(ns)` is the **highest justified** `(cursor, root)` — **derived**, not stored, so a reorg of
   a `settle` tx cleanly un-justifies it. Exposed at `/get_settled?ns=`.

**Finality coupling:** exec nodes consume only finalized blocks and settled roots sit below `FINALITY_DEPTH`
(30), so a settled root is never reorged — settlement inherits L1 finality for free.

**Phase-2b seam (real DI, currently inert).** `settlement_ops.set_settlement_verifier(fn)` installs a callable
`(ns, cursor, state_root)->bool`. When set, a root is justified if the **validity proof verifies OR** the
quorum is met (proof-preferred, quorum as liveness fallback). Default `None` ⇒ pure Phase-2a quorum — **no
behavioural change until a real verifier is installed.** This is the single line that flips settlement from
committee-trust to cryptographic-trust. **Honest status:** the arbitrary-execution zkVM prover that would back
it is a genuine, separate cryptographic build — the existing FRI prover proves the fixed shielded circuit, not
general VM execution. The seam is wired; the prover is not faked.

---

## 7. Tunnels — moving value & messages across the L1↔L2 boundary

A "tunnel" is any path that carries value or a message across the L1/exec boundary, secured by the settled
root. NADO has three built, one designed.

### 7.1 Bridge tunnel (value: L1 ⇄ exec) — **BUILT, now per-namespace**
- **In (deposit):** `bridge` tx locks `amount` at the `BRIDGE_ESCROW` address on L1; the exec node reads the
  ordered deposit and credits the sender exec-side.
- **Out (withdraw):** exec-side burn → `execnode.withdrawal_proof(nonce)` returns a **Merkle branch against the
  exec `state_root`** → user submits `bridge_withdraw{addr, amount, nonce, proof[, ns]}`. L1 verifies that ONE
  branch against **`latest_settled(ns)`**, checks the **nullifier** (no double-claim, `bridge_nullifier_exists`)
  and escrow funding, then releases. A withdraw against an *unsettled* root is refused.
- **Trust:** today the exit is trust-minimized *given* the bonded-quorum settled root (Phase-2a); Phase-2b
  makes it trust-minimized on the proof alone. `tests/test_bridge.py` covers the full round-trip + forgery
  rejection.

### 7.2 Shielded-pool tunnels (privacy: transparent ⇄ shielded) — **BUILT**
`shield` (transparent → shielded notes) and `unshield` (shielded → transparent, exit proven against the settled
exec root) move value in/out of the private pool; transfers inside prove on-device with the FRI/STARK prover
(`privacy.md`, `execnode/shielded.py`, `/exec/prove_transfer*`). The unshield exit uses the **same
settled-root Merkle-proof pattern** as the bridge.

### 7.3 Dividend tunnel (presence dividend: pool → miner) — **BUILT**
The open-lane **presence dividend** accrues off-L1 on the exec layer and is withdrawn in aggregate via
`dividend_withdraw`, proven against the settled root (`presence-dividend.md`). Same exit pattern.

### 7.4 Cross-rollup message tunnel (namespace A → namespace B) — **BUILT**
Both halves are implemented. **Emit (sender):** the `emit` blob op appends a message to the rollup's
**outbox** (`ExecState.outbox`), committed in `state_root` and provable via `outbox_proof(seq)` /
`GET /exec/outbox_proof?ns=&seq=` — the exact `withdrawal_proof` pattern. **Deliver (receiver):** an L1
`xmsg` tx carries the outbox message + its Merkle proof, and **L1 is the verifier** — it checks the proof
against `latest_settled(from_ns)` and burns a `(from_ns, seq)` nullifier (exactly the bridge pattern). So
delivery is trust-minimized *and* **deterministic for every receiver node**: they all read the same
L1-verified `xmsg` from the finalized stream and fold it into their `inbox`, committed in `state_root`
(`execnode.state.apply_xmsg`). This **sidesteps the settled-root-oracle problem entirely** — the exec node
never has to decide what is settled; L1, which holds the settled roots, decides. The leaf L1 verifies is the
shared `hashing.outbox_leaf`, byte-identical to what the exec node commits. Covered by `tests/test_xmsg.py`
(valid delivery, replay / forgery / unsettled / to_ns-mismatch rejection, receiver inbox commitment).
Remaining: multi-message atomicity/latency semantics and a forced-inclusion **escape hatch**.

**Every tunnel shares one invariant:** value/messages only cross on a **proof against a settled root** +
**nullifier** (no replay). The settled root is the single trust anchor; the tunnels never trust the exec node
directly.

---

## 8. The wallet (interface) binding

The mining wallet's **Settlement tab** (`static/interface.*`, `/settlement`) shows, read-only and fail-soft:
the L1 settled root & cursor (`/get_settled`), this exec node's tip (`/exec/settlement`), the **gap** awaiting
settlement, whether **your** exec root agrees with the quorum, and **your role** (Settling / Bonded-not-settling
/ Observer) from your bonded stake. Bridge, shielded, and dividend tunnels are driven from their own tabs.

The **Rollup tab** (`/rollup`) is the contract front-end: pick a namespace, **browse** deployed contracts (list
→ methods + storage), **deploy** (paste code or one-click an example from `/exec/examples`), and **call** a
method (a `call` blob, applied at finality) or **view** it read-only (`/exec/view`). Each contract shows its
pluggable runtime. Tabs are grouped into dropdown menus (Wallet / Rollups / Explore / Govern) and everything is
routed through i18n.

---

## 9. Security invariants (the short list)

- **L1 never executes an L2 tx** — blobs are opaque; L1 checks order, availability, and one settlement predicate.
- **Settled roots ride finality** — below `FINALITY_DEPTH`, exec tails only finalized blocks → no reorg.
- **Derived settlement** — `latest_settled` recomputes from attestations → revert-symmetric.
- **Per-namespace isolation** — keyed by `(ns, …)`; one rollup can't move another's pointer or bridge.
- **Tunnels gate on settled root + nullifier** — no exit without a proof against a settled root; no double-exit.
- **PQ-sound everywhere it matters** — settlement proofs (2b) and DA commitments must be **hash-based
  (STARK/FRI / Merkle), never KZG/Groth16** (`quantum-resistance-and-vms.md`).
- **Phones stay light** — headers + DA sampling; blob cap bounds block size.

---

## 10. Built vs designed

| Piece | Status |
|---|---|
| `blob` DA carrier, per-block cap | **built** |
| execnode: tail, VM, Merkle state_root, `/exec/*` | **built** |
| Shielded-pool FRI/STARK prover (privacy) | **built** |
| `settle` + bonded-quorum settlement, `/get_settled` | **built** |
| Bridge / shielded / dividend tunnels (Merkle-proof exits) | **built** |
| **Namespaces (multi-rollup): `ns` on settle/bridge, per-ns pointer, isolation** | **built (this work)** |
| **Per-`ns` execution node** (registry of states, blob-routed, settle-per-ns, `/exec/*?ns=`) | **built (this work)** |
| Phase-2b settlement verifier **seam** (`set_settlement_verifier`) | **built (inert DI)** |
| Phase-2b **validity proof** (zkVM over arbitrary exec) | **designed — real crypto build, not stubbed** |
| **DA erasure-coding + hash-based sampling** (`ops/da.py`: RS k-of-n + Merkle commit + sample verify) | **built (primitive); blob integration designed** |
| Recursive proof aggregation (one proof settles many rollups) | designed (moot without a zkVM) |
| **Cross-domain outbox** (`emit` op, committed messages, `outbox_proof`) | **built (this work)** |
| **Cross-rollup delivery** (`xmsg`: L1 verifies message vs sender's settled root → receiver inbox) | **built (this work)** |
| Forced-exit escape hatch; multi-message atomicity | designed |

---

## 11. File / function map

| Concern | Code |
|---|---|
| Namespaces | `protocol.DEFAULT_NS` / `valid_namespace`; `ops/kv_ops._settle_key`, `settlement_*(ns,…)` |
| Settlement predicate + pointer + 2b seam | `ops/settlement_ops.settlement_justified` / `latest_settled` / `set_settlement_verifier` |
| Settle tx + validation + reflect | `ops/transaction_ops.construct_settle_tx` + settle validate arm; `ops/account_ops` reflect arm |
| Bridge tunnel | `construct_bridge_deposit_tx` / `construct_bridge_withdraw_tx`; `bridge`/`bridge_withdraw` arms; `execnode.state.withdrawal_proof` |
| Cross-domain outbox | `emit` op + `execnode.state.outbox` / `outbox_proof`; `/exec/outbox`, `/exec/outbox_proof` |
| Cross-rollup delivery | `xmsg` arm + `construct_xmsg_tx`; shared `hashing.outbox_leaf`; `kv_ops.xmsg_nullifier_*`; `execnode.state.apply_xmsg` + inbox; `/exec/inbox` |
| Data availability | `ops/da.py` — `encode` / `reconstruct` / `sample_proof` / `verify_sample` (Reed-Solomon + Merkle) |
| Exec node | `execnode/execnode.py` (tail, `maybe_settle`, `/exec/*`), `execnode/state.py`, `execnode/vm.py`, `execnode/stark/` |
| Node API | `nado.py` `/get_settled?ns=`, `/exec/*` proxy |
| Wallet | `static/interface.html` + `interface.js` Settlement tab; `nado._TAB_PATHS` |
| Tests | `tests/test_settlement.py` (incl. namespaces), `tests/test_bridge.py`, `tests/test_blob.py`, `tests/test_execnode_vm.py` |

> Namespaces + the settlement/tunnel stack described here are **implemented and tested**; Phase-2b validity
> proofs, per-`ns` exec nodes, DA hardening, aggregation, and cross-rollup tunnels are **designed** and clearly
> marked as such — nothing here is a stub dressed up as done.
