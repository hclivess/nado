# Execution-layer instructions (blobs) — developer reference

Every instruction the NADO execution layer understands, how to submit it, and how to read the result.

This is the operational companion to [`rollups-and-settlement.md`](rollups-and-settlement.md) (the whole
architecture), [`execution-layer.md`](execution-layer.md) (why the shape), and [`privacy.md`](privacy.md)
(shielded pool). Source of truth: `execnode/state.py` (`apply_blob`) and `execnode/execnode.py` (the
`/exec/*` read API + the L1 tail loop). Client builders live in `ops/transaction_ops.py`.

---

## 1. Model

An **instruction is a blob**: an opaque-to-L1 JSON object carried by an ordinary L1 transaction whose
`recipient` is the reserved name `"blob"`. L1 orders and stores the blob and burns its fee — it never
decodes it. The **execution node** tails L1, and for every FINALIZED block it replays that block's
exec-relevant txs in block order, dispatching each blob's `payload["op"]` through
`ExecState.apply_blob(payload, sender, txid)`.

Key rules:

- **Ordering.** Blobs apply in L1 block order, and within a block in tx order. This total order is the only
  thing that makes execution deterministic across nodes.
- **Finality.** Only FINALIZED blocks mutate persistent exec state (`tail_loop` reads L1 `/status`
  `finalized_height` and never applies past it), so the persistent cursor never has to handle a reorg.
- **Namespace.** Each blob targets a rollup namespace via `payload.ns` (default `"default"`). A node only
  applies a blob for a namespace it runs; others are ignored. `bridge`/`shield`/dividend are
  **default-layer** features.
- **Never raises.** `apply_blob` is wrapped in try/except and returns a short human string. A malformed,
  unknown, or reverting blob is a **no-op** — it returns `"skip: …"` or `"… -> revert (no-op)"` and mutates
  nothing. There is no error surfaced to the submitter; the fee is still burned by L1.
- **`sender`** is the L1 tx sender (its signed `sender` address). **`txid`** is the L1 txid, used as the
  default deploy nonce.
- **Provisional reads.** Any `/exec/*` read endpoint accepts `?provisional=1` (also `true`/`yes`), returning
  a fast **pre-finality** view: a clone of the finalized state with the unfinalized L1 tail (up to 64 blocks)
  speculatively applied, so a dApp sees a just-included move within ~one block (~6s) instead of a whole
  finality window. It is **display-only** and self-heals on reorg. **Settlement and all Merkle proofs read
  the finalized (plain, no-`provisional`) state.**

### L1-side recipients (not blobs)

Some exec-relevant actions are plain L1 txs with a reserved `recipient`, handled by the tail loop directly
(see `_apply_block` in `execnode/execnode.py`), not by `apply_blob`:

| L1 recipient | Effect on exec state | Builder |
|---|---|---|
| `bridge` | credits `sender`'s exec bridge balance by `amount` (`credit_deposit`) | `construct_bridge_deposit_tx` |
| `bridge_withdraw` | L1 verifies a Merkle proof against the settled root and releases escrow (the exit `bridge_withdraw` blob recorded the leaf) | `construct_bridge_withdraw_tx` |
| `xmsg` | L1-verified cross-rollup DELIVERY → folded into the receiver ns inbox (`apply_xmsg`) | `construct_xmsg_tx` |
| `shield` | shielded DEPOSIT → adds note(s) to the pool (`apply_shield` / `apply_field_shield`) | — |
| `settle` | bonded-validator state-root attestation | `construct_settle_tx` |

---

## 2. How to submit a blob

Build a signed L1 blob tx with `construct_blob_tx(keydict, payload, target_block, fee)`
(`ops/transaction_ops.py`):

```python
from ops.transaction_ops import construct_blob_tx
tx = construct_blob_tx(keys, {"op": "deploy", "code": {...}}, target_block, fee)
# -> {"sender":..., "recipient":"blob", "amount":0, "data":<payload>, "fee":..., "signature":...}
# POST tx to L1 /submit_transaction
```

The payload rides verbatim in the tx's `data` field; `recipient` is `"blob"` and `amount` is `0`. Submit the
signed tx to L1's `/submit_transaction`. Fee is per-byte (size-capped by L1). The Coin Flip dApp does not sign
locally — it **delegates signing to the wallet** (SSO), which builds the same blob tx.

Every op below is the `data`/`payload` object. All accept an optional `"ns"` field (default `"default"`).

---

## 3. Contract ops

### `deploy`

Deploy a contract to a pluggable runtime.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"deploy"` |
| `code` | yes | contract code (map of method → bytecode; must pass `runtime.validate_code`) |
| `runtime` | no | runtime name, default `runtimes.DEFAULT_RUNTIME` (`stackvm`) |
| `nonce` | no | deploy nonce; **defaults to the L1 `txid`** |
| `abi` | no | non-consensus UX metadata `{method: {args, doc}}` (must be a dict, else ignored) |
| `ns` | no | namespace |

The contract id is deterministic: `cid = blake2b_hash(["deploy", sender, code, nonce])[:32]`
(`ExecState.contract_id`). Because it depends only on known inputs, a deployer knows its cid **before** the
blob lands. If `code` contains a `"constructor"` method it is run at deploy; if it reverts, the contract
deploys with **empty storage**.

**Skips if:** payload not a dict; unknown runtime; `code` fails validation (raises `VMError`, caught);
`cid` already exists.

```json
{"op":"deploy","code":{"constructor":"…","get":"…","set":"…"},"runtime":"stackvm",
 "abi":{"set":{"args":["key","value"],"doc":"store a value"}}}
```

### `call`

Invoke a method, persisting storage on success.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"call"` |
| `contract` | yes | target `cid` |
| `method` | yes | method name to run |
| `args` | no | argument **list** (default `[]`; must be a list) |
| `ns` | no | namespace |

Runs `method` on the contract's runtime with `sender` as caller. On success the returned storage replaces the
contract's storage; on **revert it is a no-op** (`"… -> revert (no-op)"`).

**Skips if:** no such contract; `args` is not a list; unknown runtime.

```json
{"op":"call","contract":"<cid hex>","method":"set","args":["hello",42]}
```

### `upgrade`

Replace a contract's code (and optionally runtime/abi), **preserving its cid and storage**.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"upgrade"` |
| `contract` | yes | target `cid` |
| `code` | yes | new code (validated before install) |
| `runtime` | no | new runtime, default the contract's current runtime |
| `abi` | no | new abi (installed only if a dict) |
| `ns` | no | namespace |

**Alphanet rule:** only the original deployer may upgrade — `sender` must equal `contracts[cid].deployer`.
This deliberately breaks strict immutability: on mainnet an upgrade would be gated behind on-chain
governance / a timelock, but on alphanet the deployer owns the contract outright (see the code comment in
`apply_blob`).

**Skips if:** no such contract; `sender` is not the deployer; unknown runtime; new `code` fails validation.

```json
{"op":"upgrade","contract":"<cid hex>","code":{"constructor":"…","set":"…"}}
```

---

### `transfer_contract`

Hand a contract's **ownership** — the deployer right (who may `upgrade` or `transfer_contract` it) — to another
address. Code, storage, and cid are unchanged; only `contracts[cid].deployer` is reassigned. Lets a contract
be handed to a new maintainer without redeploying.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"transfer_contract"` |
| `contract` | yes | target `cid` |
| `to` | yes | new owner address (non-empty string) |
| `ns` | no | namespace |

**Rule:** only the current owner may transfer — `sender` must equal `contracts[cid].deployer`. After transfer,
the new owner alone can `upgrade`/`transfer_contract`; the old owner can no longer.

**Skips if:** no such contract; `sender` is not the current owner; `to` missing/empty.

```json
{"op":"transfer_contract","contract":"<cid hex>","to":"ndo…newowner"}
```

---

## 4. Value / bridge ops

Deposits are **L1-side** (send an L1 tx to recipient `bridge` with an `amount`; the tail loop credits the
sender's exec bridge balance via `credit_deposit`). Exits are blobs that burn exec balance and record a
provable withdrawal leaf; after the carrying `state_root` **settles** on L1 you claim the L1 coins with a
Merkle proof.

### `bridge_withdraw`

| field | req | meaning |
|---|---|---|
| `op` | yes | `"bridge_withdraw"` |
| `amount` | yes | positive `int` raw units (bool rejected) |
| `ns` | no | namespace |

Burns `amount` from `bridge[sender]`, increments `wd_nonce`, records
`withdrawals[str(nonce)] = {"addr": sender, "amount": amount}`. Fetch the proof from
`/exec/withdrawal_proof?nonce=` and submit it to L1's `bridge_withdraw` recipient (via
`construct_bridge_withdraw_tx`) once settled.

**Skips if:** `amount` not a positive int; bridge balance `< amount`.

```json
{"op":"bridge_withdraw","amount":100000}
```

### `collect_dividend`

Collect the sender's whole accrued presence-dividend (see [`presence-dividend.md`](presence-dividend.md)).

| field | req | meaning |
|---|---|---|
| `op` | yes | `"collect_dividend"` |
| `ns` | no | namespace |

Burns the entire `dividend[sender]` into `dividend_withdrawals[str(dw_nonce)] = {"addr", "amount"}`. Claim on
L1 with the proof from `/exec/dividend_proof?nonce=` after settlement (fee-exempt `dividend_withdraw` tx).

**Skips if:** no accrued dividend for `sender` (`amount <= 0`).

```json
{"op":"collect_dividend"}
```

---

## 5. Coin flip (native staked module)

A built-in two-player commit-reveal coin flip — no contract to deploy. Stakes are escrowed from bridge
balances. `game` is an integer id (coerced to string internally). `FLIP_REVEAL_WINDOW = 1000` exec-cursor
blocks. See the Coin Flip dApp (coinflip.nadochain.com).

### `flip_bet`

Open a game (slot 1) or join it (slot 2), escrowing the stake from your bridge balance into the pot.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"flip_bet"` |
| `game` | yes | game id |
| `commit` | yes | non-negative `int` = `_hash_value(secret)` (256-bit; `execnode/vm.py`) |
| `stake` | yes | positive `int` raw stake (bool rejected) |
| `ns` | no | namespace |

First caller opens the game, escrows `stake`, sets `deadline = cursor + FLIP_REVEAL_WINDOW`. A second matching
caller joins slot 2, escrows a matching stake, and the deadline is reset to `cursor + FLIP_REVEAL_WINDOW`.

**Rejects BEFORE debiting any funds** (no stake is lost) if: bad `commit`; bad `stake`; game already settled;
`sender` already in the game; game full (`>= 2` players); `stake != opener's stake`; insufficient bridge
balance.

```json
{"op":"flip_bet","game":7,"commit":<int hash>,"stake":100000}
```

### `flip_reveal`

| field | req | meaning |
|---|---|---|
| `op` | yes | `"flip_reveal"` |
| `game` | yes | game id |
| `secret` | yes | `int` opening the commit (`_hash_value(secret) == commit`) |
| `ns` | no | namespace |

**Skips if:** bad `secret`; no open/unsettled game; fewer than 2 players; `sender` not a player; already
revealed; secret does not open your commit.

```json
{"op":"flip_reveal","game":7,"secret":<int>}
```

### `flip_settle`

Settle once both players have revealed.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"flip_settle"` |
| `game` | yes | game id |
| `ns` | no | namespace |

Result: `int(blake2b_hash([s1, s2]), 16) % 2` — `0` → slot 1 wins, `1` → slot 2 wins. Pays the whole `pot`
to the winner's bridge balance and marks the game `settled`. (`/exec/flip_game` already exposes `result` +
`winner_slot` as soon as both reveal, before settle is submitted.)

**Skips if:** nothing to settle (no game / already settled); not both players revealed (use `flip_claim` after
the deadline).

```json
{"op":"flip_settle","game":7}
```

### `flip_claim`

Anti-grief resolution after the reveal deadline passes.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"flip_claim"` |
| `game` | yes | game id |
| `ns` | no | namespace |

Branches (only after `cursor > deadline`):
- **exactly one** player revealed → that player takes the whole pot by forfeit.
- **both** revealed → skip (`"both revealed — use flip_settle"`).
- **nobody** revealed (or no opponent joined) → each player is refunded their `stake`; game marked settled.

**Skips if:** nothing to claim (no game / already settled); the reveal deadline has not passed
(`cursor <= deadline`).

```json
{"op":"flip_claim","game":7}
```

---

## 6. Cross-domain messaging

### `emit`

Commit a cross-domain message into the outbox (committed in `state_root`, provable via
`/exec/outbox_proof`).

| field | req | meaning |
|---|---|---|
| `op` | yes | `"emit"` |
| `to_ns` | yes | non-empty string: destination namespace |
| `data` | no | arbitrary payload |
| `ns` | no | source namespace |

Appends `{"seq": len(outbox), "from": sender, "to_ns": to_ns, "data": data}` (append-only; `seq == index`).
This blob only **commits** the message. Delivery is separate: a consumer verifies the outbox proof against
the emitter's **settled** L1 root, then submits an `xmsg` L1 tx (`construct_xmsg_tx`, recipient `xmsg`) that
L1 verifies and folds into the receiver ns's inbox (`apply_xmsg`). See
[`rollups-and-settlement.md`](rollups-and-settlement.md) §7.4.

**Skips if:** `to_ns` is not a non-empty string.

```json
{"op":"emit","to_ns":"myrollup","data":{"kind":"ping","n":1}}
```

---

## 7. Privacy ops

Shielded deposits are **L1-side** (recipient `shield`). The two shielded-transfer instructions are blobs;
they carry proofs/commitments and are verified by the pool. Full detail: [`privacy.md`](privacy.md).

### `field_transfer`

Phase-2 field-native join-split (full STARK proof from the delegated prover). The proof bundle rides as an
**opaque JSON string** so its large field ints survive JSON round-trips.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"field_transfer"` |
| `bundle_json` | one of | the bundle as a JSON **string** (preferred; big ints preserved) |
| `bundle` | one of | the bundle as a JSON object |
| `proof_da` | no | DA commitment; the tail loop resolves the bundle from DA before applying (block stalls if unavailable) |
| `ns` | no | namespace |

Applied via `apply_field_transfer`. **Skips if:** `bundle_json` unparsable; bundle not a dict.

### `shielded_transfer`

Phase-1 join-split / unshield against the shielded pool.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"shielded_transfer"` |
| `public` | yes | public inputs dict (root, nullifiers, `out_commitments`, `public_value`, `fee`, optional `withdraw_addr`) |
| `proof` | yes | proof dict |
| `ns` | no | namespace |

Verified + applied by `apply_transfer` (double-spend + value conservation checked). If
`public.public_value < 0` the coins **leave** the pool (unshield): a provable exit
`unshield_withdrawals[nonce] = {"addr": withdraw_addr, "amount": -public_value}` is recorded for L1 to release
from `SHIELD_ESCROW` against the settled root (claim proof at `/exec/unshield_proof?nonce=`).

**Skips if:** `public`/`proof` not dicts; verifier rejects; unshield missing `withdraw_addr`.

---

## 8. Read-endpoints reference

All are `GET /exec/*` on the exec node. All namespaced endpoints accept `?ns=` (default `default`) and
`?provisional=1` (pre-finality, display-only). Proof endpoints return `state_root` alongside the proof and
must be read from the **finalized** state for a valid claim.

| path | purpose | key query params |
|---|---|---|
| `/exec/root` | node summary: `state_root`, `cursor`, contract count, L1 url | `ns`, `provisional` |
| `/exec/settlement` | per-ns `(cursor, state_root)`, settle flags/cadence, all served namespaces | `ns`, `provisional` |
| `/exec/contracts` | contract list (cid, deployer, methods, runtime, abi); storage omitted | `ns`, `deployer`, `prefix`, `limit` (default 100, max 500), `provisional` |
| `/exec/contract` | one contract in full incl. entire storage; 404 if unknown | `cid`, `ns`, `provisional` |
| `/exec/view` | read-only method call (storage never persisted); `result` null on missing/revert | `cid`, `method`, `args` (JSON list), `ns`, `provisional` |
| `/exec/flip_game` | coin-flip game state; `result`+`winner_slot` once both reveal | `game`, `ns`, `provisional` |
| `/exec/outbox` | cross-domain outbox messages `{seq, from, to_ns, data}` | `ns`, `provisional` |
| `/exec/outbox_proof` | Merkle proof that outbox `seq` is in the ns `state_root` | `ns`, `seq` |
| `/exec/inbox` | messages delivered to this ns (from L1-verified `xmsg`) | `ns`, `provisional` |
| `/exec/bridge` | all exec bridge balances + recorded withdrawal records | — |
| `/exec/withdrawal_proof` | Merkle proof for a `bridge_withdraw` record vs current `state_root` | `nonce` |
| `/exec/dividend` | accrued presence-dividend (with `?address=` also pending withdrawals) | `address` |
| `/exec/dividend_proof` | Merkle proof for a collected dividend withdrawal | `nonce` |
| `/exec/unshields` | pending unshield exits for an L1 `?addr=` | `addr` |
| `/exec/unshield_proof` | Merkle proof for an unshield exit vs current `state_root` | `nonce` |
| `/exec/shielded` | phase-1 pool status (root, note/nullifier counts, recent anchors) | — |
| `/exec/field_shielded` | phase-2 field-pool status; `?cm=` also a commitment's position | `cm` |
| `/exec/field_leaves` | full field-pool commitment list (build a Merkle path on-device) | — |
| `/exec/examples` | starter contract library (`contract_lib.LIBRARY`) | — |
| `/exec/runtimes` | available runtimes + default | — |
| `/exec/prove_transfer`, `/exec/prove_transfer2` | **POST** delegated STARK provers (return `bundle_json`; never apply) | POST body = secret witness |

(There is also a `/da/*` data-availability API — publish/fetch erasure-coded proof objects by commitment.)

---

## 9. Contract lifecycle

1. **deploy** — pick a runtime, submit `{op:"deploy", code, …}`. The cid is
   `blake2b_hash(["deploy", sender, code, nonce])[:32]`, deterministic and knowable before the blob lands
   (nonce defaults to the L1 txid). A `constructor`, if present, runs at deploy; a reverting constructor
   yields empty storage.
2. **call** — `{op:"call", contract, method, args}` mutates storage on success, no-ops on revert. Use
   `/exec/view` for read-only calls.
3. **upgrade** — `{op:"upgrade", contract, code}` replaces code but keeps the cid and storage. **Alphanet:
   deployer-only** (`sender == deployer`); mainnet would gate this behind governance/timelock.
4. **transfer_contract** — `{op:"transfer_contract", contract, to}` hands ownership (the upgrade/transfer
   right) to `to`. Owner-only; code, storage, and cid are unchanged.

Because every write is a blob ordered by L1, contract state is a pure function of the finalized blob stream —
identical on every exec node and committed in `state_root`.
