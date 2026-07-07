# Settlement layer — implementation spec

**Status: partly BUILT (Phase 2a), this spec drives the rest.** This is the *implementation* companion to the
conceptual notes [`l2-settlement.md`](l2-settlement.md) and [`execution-layer.md`](execution-layer.md): concrete
data structures, tx/wire formats, the settlement lifecycle, the node ↔ execnode ↔ interface wiring, API
contracts, a phased checklist of what's built vs. to-build, and the test plan. Where those notes argue *why*,
this one says *what to write*.

Guiding rule (unchanged): **L1 never executes an L2 transaction.** It orders `blob` data, guarantees
availability, and moves a per-namespace settled-root pointer forward when a settlement is *justified* — today
by a bonded-stake quorum, later by one STARK proof, behind the same predicate.

---

## 0. Component map

```
                    ┌─────────────────────────────────────────────┐
   miners/phones ── │  NADO L1  (nado.py, ops/, protocol.py)       │
   (interface)      │   • orders `blob` txs (opaque, size-capped)  │
                    │   • `settle` tx → attestations               │
                    │   • settlement_ops.settlement_justified()    │  ← the verifier seam
                    │   • latest_settled() → /get_settled          │
                    │   • `bridge` / `bridge_withdraw` escrow      │
                    └───────────────▲──────────────┬──────────────┘
                        settle tx    │  finalized   │ blobs
                                     │  blocks      ▼
                    ┌────────────────┴─────────────────────────────┐
   contract users ─ │  execnode (execnode/)                         │
   (interface)      │   • tails FINALIZED L1 blocks (state.cursor)  │
                    │   • decodes blobs → VM (vm.py) → state.py     │
                    │   • Merkle state_root()  (stark/merkle.py)    │
                    │   • maybe_settle() posts `settle` if bonded   │
                    │   • STARK prover (stark/fri.py) — privacy now │
                    │   • /exec/* read API (root, settlement, …)    │
                    └──────────────────────────────────────────────┘
```

- **L1** is authoritative for *ordering, availability, and which root is settled*. It is blind to blob contents.
- **execnode** is authoritative for *what the state is*. It computes the root L1 blesses.
- **interface** (`static/interface.*`) is the wallet/miner; it reads both and shows the user their settlement
  position.

---

## 1. What's already built (do not re-implement)

| Piece | Location | Contract |
|---|---|---|
| `blob` carrier | `protocol.RESERVED_RECIPIENTS`, `MAX_BLOB_BYTES_PER_BLOCK = 262144` | opaque, size-capped, fee-per-byte |
| `settle` tx | `ops.transaction_ops.construct_settle_tx(keydict, exec_cursor, state_root, target_block)` | `{recipient:"settle", data:{exec_cursor, state_root}, fee:0}`; one attestation per `(validator, cursor)` |
| verifier seam | `ops.settlement_ops.settlement_justified(cursor, state_root, bonded_registry) -> bool` | `attesting_shares * SETTLE_DEN > total * SETTLE_NUM` (2/3) |
| settled pointer | `ops.settlement_ops.latest_settled() -> (cursor, root)` | derived (revert-safe); exposed at `GET /get_settled` |
| bridge | `bridge` / `bridge_withdraw` recipients; `execnode.state.withdrawal_proof(nonce)` | deposit→credit→burn→Merkle-proof-vs-settled-root→release |
| exec tail + settle | `execnode/execnode.py` `apply loop`, `maybe_settle()` (`NADO_EXEC_SETTLE`, every `SETTLE_EVERY`) | consumes only FINALIZED blocks |
| Merkle state root | `execnode/state.py:state_root()`, `execnode/stark/merkle.py` | the object settlement commits to |
| STARK prover | `execnode/stark/fri.py`, `joinsplit_transfer.py`, `goldilocks_native.py` | **built for privacy today**; reused for Phase-2b settlement |
| **exec settlement status** | `execnode` `GET /exec/settlement` (**this change**) | `{cursor, state_root, settle_enabled, settle_every, last_settled_cursor, l1}` |

The single most important fact for planning: **`settlement_justified()` and the FRI prover already exist.**
Phase-2b is *"call the prover to make a blob→root proof, and replace the body of that one predicate with
`fri.verify(...)`"* — not a new subsystem.

---

## 2. Data model & wire formats

### 2.1 Settle attestation (built)
```jsonc
{ "recipient": "settle", "amount": 0, "fee": 0,
  "data": { "exec_cursor": <int>, "state_root": "<hex>" }, ... }   // + sender/pubkey/txid/signature
```
Indexed **one per `(validator, exec_cursor)`** (`transaction_ops` reflect arm). Reflecting stores the
attestation; `settlements_for_cursor(cursor)` and `settlement_cursors()` (`kv_ops`) read them back.

### 2.2 Namespaces (to build — the multi-rollup step)
Add an optional `ns` (rollup id: a registered short id, or the deploy address / code hash of the rollup state
machine; **absent ⇒ the default namespace**, preserving today's behavior):
```jsonc
{ "recipient": "settle", "data": { "ns": "<id|absent>", "exec_cursor": n, "state_root": r } }
{ "recipient": "blob",   "data": { "ns": "<id|absent>", "payload": <bytes|hash> } }
```
- L1 keeps `latest_settled(ns)`; the settle index key becomes `(ns, validator, cursor)`.
- `blob` DA byte budget (`MAX_BLOB_BYTES_PER_BLOCK`) is **shared across namespaces** — fair-allocation /
  anti-spam is an open item (§7).
- **Back-compat:** `ns` omitted ⇒ `ns = "default"`. No consensus break for the existing single layer.

### 2.3 Validity proof (Phase 2b, to build)
```jsonc
{ "recipient": "settle",
  "data": { "ns": id, "prev_cursor": a, "new_cursor": b,
            "prev_root": r0, "new_root": r1, "proof": "<FRI proof bytes|hash>" } }
```
`settlement_justified()` body becomes: fetch `prev_root` = current `latest_settled(ns)`, then
`return stark.verify_settlement(prev_root, new_root, blobs[a..b], proof)`. Proof bytes ride a `blob` (they are
~1–4 MB; `execnode` already caps request bodies at 16 MB for exactly this). The bonded-quorum path stays as a
liveness fallback during rollout (accept a root if **either** justified-by-proof **or** justified-by-quorum).

---

## 3. Settlement lifecycle (per namespace)

1. **Order** — users post `blob{ns, payload}` txs; L1 fixes their order (`txid`-sorted in block, CO-8) and
   guarantees availability for the DA window.
2. **Execute** — execnode tails *finalized* blocks (`state.cursor` = highest applied L1 height), decodes the
   `ns` blobs, runs the VM, advances `state_root()`.
3. **Settle** — a bonded execnode calls `maybe_settle()` every `SETTLE_EVERY` blocks → `construct_settle_tx`
   → L1. (2b: instead post `new_root` + FRI proof.)
4. **Justify** — L1 recomputes `settlement_justified(ns, cursor, root)` on every relevant block; when true,
   `latest_settled(ns)` advances. Derived, so a reorg of a settle/proof tx cleanly un-justifies.
5. **Bridge** — deposits credit against the settled root; withdrawals release escrow against a Merkle branch
   (2a) or the validity-proven root (2b) of `latest_settled(ns)`.

**Finality coupling:** execnode consumes only finalized blocks and settled roots sit below `FINALITY_DEPTH`, so
a settled root is never reorged — settlement inherits L1 finality with no extra machinery.

---

## 4. Interface binding (the mining wallet)

The interface (`static/interface.html` + `interface.js`) already fetches `relayBase()+"/get_settled"` and
`execBase()+"/exec/*"`. Add a **Settlement** tab that makes the user's settlement position first-class.

### 4.1 Data sources
- `GET {relay}/get_settled` → `{cursor, state_root}` — the **L1-justified** root (ecosystem truth).
- `GET {exec}/exec/settlement` → `{cursor, state_root, settle_enabled, settle_every, last_settled_cursor}` —
  **this exec node's** tip and whether it is posting attestations.
- `GET {relay}/get_account?address=<wallet>` → `bonded` — is the mining wallet a bonded validator (hence a
  potential settler)?

### 4.2 What it shows
- **Settled root** (L1) vs **exec tip** (execnode), and the **gap** = `exec.cursor − settled.cursor` (how many
  blocks behind settlement runs) with an OK/lagging indicator.
- **Your role:** if `account.bonded > 0` and `settle_enabled`, badge *"You are settling (every N blocks)"*; if
  bonded but not enabled, show how to turn it on (`NADO_EXEC_SETTLE=1`); if not bonded, *"Bond stake to help
  settle"* linking the Stake tab.
- **Contracts**/state summary (count, root prefix) for context.
- **Match check:** does *your* exec `state_root` at the settled cursor equal the L1 settled root? Green = your
  node agrees with the quorum; red = you are on a divergent execution (an early fraud signal, pre-2b).

### 4.3 Wiring (additive, fail-soft)
- `interface.html`: one `#tabbtn` in `#tabbar` + one `[data-tab="settlement"]` pane. Mirror an existing simple
  tab (e.g. the dividend/stake pane) so styling is consistent.
- `interface.js`: `TAB_NAMES.add("settlement")`; a `renderSettlement()` that does the three fetches inside
  `try/catch` and degrades gracefully (execnode down ⇒ show L1-only view, never throw); call it from `showTab`.
- Node route: add `"settlement"` to `_TAB_PATHS` in `nado.py` so `/settlement` deep-links like other tabs.
- Strictly read-only in v1 — no new signing path from the browser. Enabling settling stays an operator env
  flag; the wallet only *reflects* it.

---

## 5. Node / execnode / L1 changes summary

**execnode**
- [x] `GET /exec/settlement` status endpoint (done).
- [ ] `ns` awareness: filter blobs by namespace, keep per-`ns` state + root, settle per `ns`.
- [ ] Phase-2b: `prove_settlement(prev_root, blobs, new_root)` over the FRI backend; post proof + root.

**L1 (`ops/`, `protocol.py`, `nado.py`)**
- [ ] `settle`/`blob` reflect + validate arms read optional `ns` (default `"default"`); settle index keyed by
  `(ns, validator, cursor)`; `latest_settled(ns)`; `/get_settled?ns=`.
- [ ] `settlement_justified()` gains the 2b proof branch (verify FRI) with the 2a quorum as fallback.
- [ ] `_TAB_PATHS += ("settlement",)` for interface deep-linking.

**interface**
- [ ] Settlement tab (§4).

---

## 6. Test plan

- **Unit (settlement_ops):** `settlement_justified` boundary (just-under vs just-over 2/3), multi-root at one
  cursor (no double-count), `latest_settled` picks highest justified cursor, revert-symmetry (drop an
  attestation → root un-justifies). *(2a suite exists: `tests/test_settlement.py`.)*
- **Namespaces:** two namespaces settle independently; a blob/settle for `ns=A` never moves `latest_settled(B)`;
  omitted `ns` behaves exactly as `"default"` (back-compat).
- **Bridge:** deposit→credit→withdraw→proof→release round-trip per namespace; a withdraw against an
  *unsettled* root is refused. *(2a: `tests/test_bridge.py`.)*
- **Phase 2b:** a valid FRI settlement proof justifies a root with **zero** bonded attestations; a forged
  `new_root` fails `stark.verify`; quorum fallback still works when no proof is posted.
- **Interface:** `renderSettlement` with execnode reachable, execnode down (L1-only, no throw), bonded vs
  unbonded wallet, and agree/diverge root match.

---

## 7. Open items (carried from l2-settlement.md §9)

Prover cost/latency & keeping the FRI verifier full-node-cheap; prover/sequencer decentralization; the
forced-exit **escape hatch**; **namespace registration + fair DA allocation / anti-spam** on the shared blob
budget; cross-rollup messaging/atomicity; DA erasure-coding + hash-based sampling (`rolling-mode-and-da.md`
§4.2) before raising `MAX_BLOB_BYTES`.

---

## 8. Implementation order (smallest shippable steps)

1. **`/exec/settlement` + Settlement tab** — makes the *existing* 2a settlement visible in the mining wallet.
   Read-only, zero consensus risk. **(this change: endpoint done; tab next.)**
2. **Namespaces** — the multi-rollup generalization; pure extension, `ns` defaults preserve behavior.
3. **Phase-2b proof** — `prove_settlement` over the existing FRI backend + the `settlement_justified` proof
   branch; flip bridge trust from committee to math, quorum as fallback.
4. **DA hardening** — erasure coding + hash-based sampling, then raise the blob budget.
5. **Escape hatch, prover market, cross-rollup messaging.**

> Cross-references: [`l2-settlement.md`](l2-settlement.md) (why/scaling), [`execution-layer.md`](execution-layer.md)
> (Phase 1/2, VM, PQ proof system), [`rolling-mode-and-da.md`](rolling-mode-and-da.md) (DA),
> `ops/settlement_ops.py`, `execnode/` (`state.py`, `stark/`, `execnode.py`), `ops/transaction_ops.py`
> (`construct_settle_tx`, bridge), `protocol.py` (`RESERVED_RECIPIENTS`, `SETTLE_NUM/DEN`, `MAX_BLOB_BYTES_PER_BLOCK`).
