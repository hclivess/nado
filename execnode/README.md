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

## Status

Phase 1 (sovereign) skeleton: L1 `blob` DA channel + deterministic VM + tailing execution node + query
API + CLI, all with tests (`tests/test_blob.py`, `tests/test_execnode_vm.py`). **Not yet built:** the
per-block blob-bytes cap on L1 (`doc/execution-layer.md §3.3`), the DA availability/pruning window, and
Phase 2 (a single settlement proof verified on L1 for a trust-minimized bridge). This is a sovereign
layer: its canonical state is defined by this software replaying L1's ordering, not yet enforced by L1.
