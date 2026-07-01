# NADO execution node (Phase 1 — sovereign, "beside the node")

This is the **separate execution layer** for NADO smart contracts. It does **not** run inside L1 and is
**not** part of consensus. L1 does the two things a base layer is uniquely good at — **ordering** and
**data availability** — by carrying opaque `blob` transactions; this process replays those blobs through
a small deterministic VM and keeps the resulting contract state. A bug in this VM can never fork the
chain. Phones mine L1 and never run any of this. See `doc/execution-layer.md` for the full design.

```
   ┌────────────────────┐    reads finalized blocks    ┌────────────────────────────┐
   │  NADO L1 node      │  ── (blob txs) over HTTP ──▶  │  execution node (this)     │
   │  orders + stores   │                               │  VM + contract state +     │
   │  opaque blobs      │                               │  read-only query API       │
   └────────────────────┘                               └────────────────────────────┘
```

## Pieces

| file | role |
|------|------|
| `vm.py` | the minimal deterministic stack VM (PUSH/ADD/MLOAD/MSTORE/REQUIRE/RETURN … + gas) |
| `state.py` | contract store; applies blob `deploy`/`call` payloads; canonical `state_root` |
| `execnode.py` | tails an L1 node, extracts `blob` txs from **finalized** blocks, applies them, serves queries |
| `submit_blob.py` | CLI to build + submit a `blob` (deploy/call) to L1 |
| `examples/token.json` | an example fungible-token contract in VM bytecode |

## Contract model

A contract is `{ "<method>": <bytecode>, ... }`. Method `constructor` (optional) runs once at deploy with
`caller = deployer`. State is named key/value maps of ints (`MLOAD`/`MSTORE <map>`). Values are ints and
strings only, so state is canonical and every honest node computes the same `state_root`.

A blob payload is JSON:
- deploy: `{"op":"deploy","code":{...},"nonce":"…"}` → contract id = `blake2b(["deploy",deployer,code,nonce])[:32]`
- call: `{"op":"call","contract":"<cid>","method":"<m>","args":[...]}`

## Run it

```bash
# 1) run an execution node against an L1 node
NADO_L1_URL=http://127.0.0.1:9173 NADO_EXEC_STATE=./exec_state.json python execnode/execnode.py

# 2) deploy the example token (HOME points at your wallet's data dir with keys.dat)
HOME=/root/nado-solo python execnode/submit_blob.py deploy execnode/examples/token.json --l1 http://127.0.0.1:9173
#    -> prints the contract id once mined

# 3) call transfer(to, amount)
HOME=/root/nado-solo python execnode/submit_blob.py call <cid> transfer '["ndo…recipient…", 250]'

# 4) query the execution node (read-only)
curl localhost:9273/exec/root
curl 'localhost:9273/exec/view?cid=<cid>&method=balanceOf&args=["ndo…"]'
curl 'localhost:9273/exec/contract?cid=<cid>'
```

## Phase 2 — settlement + bridge (built)

The execution layer is no longer only sovereign: L1 now **settles** its state root and a **bridge** moves
coins across, trust-minimized by the bonded stake.

- **Settlement.** A bonded validator running an exec node posts a `settle` attestation of its
  `(cursor, state_root)` (enable with `NADO_EXEC_SETTLE=1`; needs its `keys.dat` via `HOME`). When bonded
  shares attesting the same root exceed 2/3, L1 records it as the **canonical settled root** (`/get_settled`).
  `settlement_ops.settlement_justified()` is the pluggable verifier seam — swap the quorum for a single
  STARK validity-proof check later, nothing else changes.
- **Bridge.** `bridge` (deposit) locks L1 coins in escrow; this node credits the depositor exec-side
  (`/exec/bridge`). A `bridge_withdraw` blob op burns the exec-side balance and records a withdrawal;
  `/exec/withdrawal_proof?nonce=N` returns its **Merkle proof against the settled root**, which the user
  submits to L1's `bridge_withdraw` — L1 verifies that ONE proof, checks the nullifier, and releases escrow.

The exec `state_root` is now a **Merkle root** over all state, so any leaf (a withdrawal) is provable to L1.

## Status

Built + tested: `tests/test_blob.py` (DA channel + per-block cap), `tests/test_execnode_vm.py` (VM +
determinism), `tests/test_settlement.py` (bonded-quorum settlement), `tests/test_bridge.py` (Merkle +
full deposit→withdraw→settle→release round-trip). **Not yet built:** the DA availability/pruning window,
and Phase-2b (replacing the bonded-quorum settlement verifier with a succinct STARK validity proof —
the seam is in place). Trust today is the bonded stake (a validator committee), not yet a validity proof.
