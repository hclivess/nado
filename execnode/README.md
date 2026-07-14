# NADO execution node (Phase 1 — sovereign, "beside the node")

This is the **separate execution layer** for NADO smart contracts. It does **not** run inside L1 and is
**not** part of consensus. L1 does the two things a base layer is uniquely good at — **ordering** and
**data availability** — by carrying opaque `blob` transactions; this process replays those blobs through
the deterministic **zkVM** and keeps the resulting contract state. A bug in this VM can never fork the
chain. Phones mine L1 and never run any of this. See `doc/execution-layer.md` for the full design and
`doc/zk-execution-proofs.md` for the provable-execution stack (issue #85).

> **As of alphanet-5 (v1.0.0-alpha.9), the zkVM is the ONLY runtime.** The old string/BLAKE2b stack VM was
> deleted — no legacy, no history replay. Contract *execution is provable*: a call is applied by verifying a
> STARK + replaying its public I/O log instead of re-executing, and a whole epoch of calls settles as one
> proof (`execnode/settlement_proofs.py`). See `doc/zk-execution-proofs.md`.

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
| `zkvm.py` | the field-native, PROVABLE register VM (one step = one STARK row; alghash HASH, byte-limb arithmetic, I/O log) |
| `zkvmasm.py` | **zkasm** — the zkVM assembly language + assembler (labels, `slot`/`hash`/`rem`/`gte`/`arg` macros) contracts are written in |
| `zkvm_examples.py` | starter library (counter / tip-jar / commit-box) served at `/exec/examples` |
| `stark/vm_circuit.py` | the execution AIR + per-call and epoch (`prove_epoch_calls`) provers |
| `settlement_proofs.py` | the epoch settlement proof binding pre/post state root into the `ops.settlement_ops` seam |
| `runtimes.py` | runtime registry — ships one engine, `"zkvm"`; addresses enter as field digests |
| `state.py` | contract store; applies blob `deploy`/`call` payloads; canonical `state_root`; `decode_view` |
| `execnode.py` | tails an L1 node, extracts `blob` txs from **finalized** blocks, applies them, serves queries |
| `submit_blob.py` | CLI to build + submit a `blob` (deploy/call) to L1 |
| `games/` | the ported on-chain games (coinflip, dice, roulette, tictactoe, …) + `deploy.py` |

## Contract model

A contract is `{ "<method>": [[op, d, s, imm], …], … }` — zkVM bytecode (8 registers r0..r7, flat field-element
`slots` storage, `alghash` HASH, BLOCKHASH/BEACON chain randomness). Method `constructor` (optional) runs once
at deploy with `caller = deployer`. Storage is `{"slots": {slot: value}}`; addresses enter as field digests
(resolved back via the exec node's registry). A contract can carry an `abi._view` schema so the exec node
presents its flat slots as the named maps a frontend expects (`decode_view`) — so a ported game changes only
its cid. State is canonical (integers only), so every honest node computes the same `state_root`.

**Args are variadic (up to 1024).** The first 8 call args preload r0..r7; the `ARG rd rs` opcode loads
`args[rs]` by dynamic index, proven by a dedicated LogUp lookup into the public args table — so merkle proofs
and batch inputs are first-class call arguments, no bitmask packing. Gas/trace ceiling is the full proof
capacity (`GAS_LIMIT = 131070` steps, one 2^17-row trace). Design rule: the VM carries as few limits as
possible — the *proof* is the gate, not re-execution — every remaining bound is soundness-mandated (DIVMOD/LT
windows) or proof capacity, never taste (`tests/test_zkvm_args.py` covers the soundness negatives).

A blob payload is JSON:
- deploy: `{"op":"deploy","runtime":"zkvm","code":{…}|"codez":…,"abi":{…},"nonce":"…"}` → cid = `blake2b(["deploy",deployer,code,nonce])[:32]`
- call: `{"op":"call","contract":"<cid>","method":"<m>","args":[…],"value":<raw>}`
- proven: `/exec/prove_call` returns a STARK; `/exec/verify_call` verifies + applies a call without re-executing it.

## Run it

```bash
# 1) run an execution node against an L1 node
NADO_L1_URL=http://127.0.0.1:9173 NADO_EXEC_STATE=./exec_state.json python execnode/execnode.py

# 2) deploy a ported game (HOME points at your wallet's data dir with keys.dat); prints its cid
HOME=/root/nado python -m execnode.games.deploy coinflip
HOME=/root/nado python -m execnode.games.deploy dice --upgrade <cid>     # replace a contract's code in place

# 3) call a method (stake escrowed as VALUE)
HOME=/root/nado python execnode/submit_blob.py call <cid> open '[12345]'

# 4) query the execution node (read-only) — /exec/contract returns the decode_view'd named maps
curl localhost:9273/exec/root
curl 'localhost:9273/exec/contract?cid=<cid>'
curl -X POST localhost:9273/exec/prove_call -d '{"cid":"<cid>","method":"open","args":[12345]}'   # STARK a call
```

## Phase 2 — settlement + bridge (built)

The execution layer is no longer only sovereign: L1 now **settles** its state root and a **bridge** moves
coins across, trust-minimized by the bonded stake.

- **Settlement.** A bonded validator running an exec node posts a `settle` attestation of its
  `(cursor, state_root)` (enable with `NADO_EXEC_SETTLE=1`; needs its `keys.dat` via `HOME`). When bonded
  shares attesting the same root exceed 2/3, L1 records it as the **canonical settled root** (`/get_settled`).
  `settlement_ops.settlement_justified()` is the pluggable verifier seam, and **Phase-2b is now built**:
  `settlement_proofs.settlement_verifier()` installs a STARK validity-proof check there — an epoch of zkVM
  calls proves `pre_root → post_root` in one proof, so L1 can justify a root by math, not just by quorum.
- **Bridge.** `bridge` (deposit) locks L1 coins in escrow; this node credits the depositor exec-side
  (`/exec/bridge`). A `bridge_withdraw` blob op burns the exec-side balance and records a withdrawal;
  `/exec/withdrawal_proof?nonce=N` returns its **Merkle proof against the settled root**, which the user
  submits to L1's `bridge_withdraw` — L1 verifies that ONE proof, checks the nullifier, and releases escrow.

The exec `state_root` is now a **Merkle root** over all state, so any leaf (a withdrawal) is provable to L1.

## Status

Built + tested: `tests/test_blob.py` (DA channel + per-block cap), `tests/test_zkvm*.py` (VM, execution AIR,
epoch aggregation, runtime + 3-way differential), `tests/test_stark_aux.py` (LogUp), `tests/test_settlement.py`
(bonded-quorum) + `tests/test_settlement_proof.py` (epoch validity proof), `tests/test_bridge.py` (Merkle +
full deposit→withdraw→settle→release round-trip), `tests/test_zkvm_args.py` (the `ARG` indexed-args bus +
`DIVMODW`, with soundness negatives). **Provable execution is live** (per-call + epoch proofs,
`/exec/prove_call`, the settlement seam). Epochs larger than one trace **segment and chain their state
roots** (`prove_settlement`/`verify_settlement`), so proof coverage is unbounded-epoch-safe. **Still open:**
**recursion** — folding the per-segment proofs into one O(1)-verify proof (needs an in-VM STARK verifier over
a wide-sponge alghash), the DA availability/pruning window, and full-state (non-zkVM op families)
settlement. **Games: all 15 ported + live on alphanet-5** (coinflip/dice/roulette/slots/mines/blackjack +
tictactoe/connect4/reversi/chess + farkle + bet + battleship + pets + holdem, in `execnode/games/`, all
E2E-tested in `tests/test_games_e2e.py`). See `doc/zk-execution-proofs.md`.

**Contract upgradability (mainnet trust model).** Contracts are mutable by their owner by default and
immutable once locked. `deploy` records an `upgradable` flag (default `true`; pass `{"upgradable": false}` to
be immutable from birth); `upgrade` replaces code while preserving cid + storage, but is refused once locked;
`lock` permanently renounces upgradability (one-way, no unlock); `transfer_contract` hands the owner right on.
The flag is consensus state (committed in `state_root`) and surfaced by `/exec/contract`. Full reference:
`doc/exec-instructions.md` §9.1.
