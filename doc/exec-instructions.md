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

Invoke a method, persisting storage on success. Optionally **escrow NADO** into the contract for the call.

| field | req | meaning |
|---|---|---|
| `op` | yes | `"call"` |
| `contract` | yes | target `cid` |
| `method` | yes | method name to run |
| `args` | no | argument **list** (default `[]`; must be a list) |
| `value` | no | raw NADO to escrow from the caller's bridge INTO the contract for this call (`int >= 0`, bool rejected; default `0`) |
| `ns` | no | namespace |

Runs `method` on the contract's runtime with `sender` as caller. On success the returned storage replaces the
contract's storage; on **revert it is a no-op** (`"… -> revert (no-op)"`).

**Value / escrow semantics.** When `value > 0`, that many raw NADO are debited from `bridge[sender]` and
credited into the contract's own bridge balance (`bridge[cid]`) **before** the method runs, so the `VALUE`
opcode reflects it and `PAY` can draw on it. A **revert refunds the escrow exactly** — no NADO is created or
lost. Any `PAY` payouts the method schedules are applied **from the contract's balance** after it returns; a
call whose total payouts **exceed the contract's balance reverts** (and refunds), so a contract balance can
never go negative and no NADO is minted. This makes a contract able to **hold and move real bridged NADO** — a
generic escrow/staking primitive, not specific to any one dApp (see the Coin Flip example, §5).

**Skips if:** no such contract; `args` is not a list; `value` not a non-negative int; unknown runtime;
insufficient bridge balance for `value`.

```json
{"op":"call","contract":"<cid hex>","method":"set","args":["hello",42]}
{"op":"call","contract":"<cid hex>","method":"open","args":[7,<commit int>],"value":100000}
```

**VM value opcodes** (`execnode/vm.py`, `stackvm` runtime) — the primitives a contract uses to interact with
escrow: `VALUE` pushes the NADO escrowed with THIS call; `PAY` pops `amount` then `to` and schedules a payout
of `amount` raw NADO from the contract's escrow to `to` (max 16 payouts/call; `amount == 0` skipped; `to` must
be a non-empty string); `CURSOR` pushes the current L1 block height (for deadlines). `MSTORE` stores an int
**or** string (strings let a contract store addresses); a `0`/empty value deletes the key. `run()` returns
`(ok, return_value, new_storage, payouts)`.

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

## 5. Coin Flip (example contract)

Coin Flip is **not a native module** — there is no coinflip-specific op or API. It is an ordinary on-chain
contract (`execnode/contracts/coinflip.json`, runtime `stackvm`) exercised entirely through the generic
`call`/`view`/`upgrade` surface, and it is the **reference example of the `VALUE`/`PAY` escrow pattern** (§3):
stakes are real bridged NADO escrowed into the contract via `call`'s `value`, and the pot is paid out via `PAY`.

It is deployed at `cid = 7ee95a0abd6e00d12edc3bf39f4c8f2d` (node-owned, so **upgradable** by the node via the
`upgrade` op). `game` is an integer id (used as the storage key). The reveal window is `1000` L1 blocks
(`CURSOR + 1000` deadline). All methods are called with the generic `call` op:

| method | args | value | effect |
|---|---|---|---|
| `open` | `game, commit` | `= stake` | open a fresh game (slot 1), escrow the stake as the pot; `commit = HASH(secret)` |
| `join` | `game, commit` | `= stake` | join as slot 2 (stake must equal the opener's); adds to the pot; sets `deadline = CURSOR + 1000` |
| `reveal1` / `reveal2` | `game, secret` | `0` | reveal your secret; reverts unless `HASH(secret)` matches your stored commit |
| `settle` | `game` | `0` | after both reveal, pay the whole pot to the winner via `PAY` — `result = HASH(s1+s2) % 2` (`0` → slot 1, `1` → slot 2) |
| `claim` | `game` | `0` | after the reveal deadline: the lone revealer takes the pot by forfeit, or (nobody revealed) each stake is refunded |

Because every method reverts on any bad precondition (wrong stake, wrong secret, wrong turn, double-join,
already settled), a losing or absent player can only stall, never steal; the `value`-escrow refund and the
"payouts ≤ contract balance" rule (§3) guarantee no NADO is minted or lost.

The Coin Flip dApp (`coinflip.nadochain.com`) reads game / lobby / scoreboard by **deriving them from the
contract's storage maps** via the generic `GET /exec/contract` endpoint (§8) — there is no dedicated read API.

```json
{"op":"call","contract":"7ee95a0abd6e00d12edc3bf39f4c8f2d","method":"open","args":[7,<commit int>],"value":100000}
{"op":"call","contract":"7ee95a0abd6e00d12edc3bf39f4c8f2d","method":"reveal1","args":[7,<secret int>]}
{"op":"call","contract":"7ee95a0abd6e00d12edc3bf39f4c8f2d","method":"settle","args":[7]}
```

---

## 5b. Roulette (example contract)

Roulette is the same story as Coin Flip — **not a native module**, no roulette-specific op or API — but it
shows the escrow pattern extended to a **house-banked, fixed-odds** game. It is an ordinary on-chain contract
(`execnode/contracts/roulette.json`, runtime `stackvm`) deployed at `cid = 186ebadb975794e2ed7eeb1c7b5115a5`
(node-owned, **upgradable**), exercised entirely through the generic `call`/`view`/`upgrade` surface.

It is **peer-banked**: each `game` is two seats — a **bank** (posts a bankroll, commits a secret) and a
**bettor** (stakes a bet on a set of table numbers, commits a secret). One shared spin
`result = HASH(bankSecret + bettorSecret) % 37` (0..36) is fair for the identical reason Coin Flip is: neither
secret is revealed until both are committed. `commit = HASH(secret)`, reveal window `1000` L1 blocks.

**Universal payout rule.** A bet is just the *set of numbers it covers*; a winning bet returns
`stake × (36 ÷ count)`, where `count` is how many numbers it covers (straight `1`→36×, split `2`→18×, street
`3`→12×, corner `4`→9×, line `6`→6×, dozen/column `12`→3×, even-money `18`→2×). With 37 pockets this is the
exact single-zero house edge (`1/37` ≈ 2.70%) for **every** bet — the contract never needs to know bet *types*.
The covered set is passed as 18 fixed slots (`n0…n17`), padded with a sentinel (`99`); `count` is **derived**
on-chain (so coverage can't be understated), and each covered number `n` is recorded at `cov[game*37+n]`.

| method | args | value | effect |
|---|---|---|---|
| `open` | `game, bankCommit` | `= bankroll` | bank a fresh table (seat 1), escrow the bankroll |
| `join` | `game, betCommit, n0…n17` | `= stake` | bet at the table (seat 2): record the covered set + `count`; reverts unless the bankroll covers the max win (`bankroll ≥ stake × (36÷count − 1)`); sets `deadline = CURSOR + 1000` |
| `reveal1` / `reveal2` | `game, secret` | `0` | bank / bettor reveal; reverts unless `HASH(secret)` matches the stored commit |
| `settle` | `game` | `0` | after both reveal: spin `r = HASH(s1+s2) % 37`; if `r` is covered, `PAY` the bettor `stake × 36÷count` from the bankroll, else sweep the stake into the bank. Stores `ro[game]=r+1`, `wn[game]=win` |
| `claim` | `game` | `0` | after the deadline (not both revealed): a stalling bank pays the bettor their **max** win; a stalling bettor forfeits the stake to the bank; if neither revealed, both are refunded |
| `cancel` | `game` | `0` | the bank reclaims its bankroll from a table nobody joined (`nn==1`) |

Each bank escrows **only its own table's bankroll** and receives that table's exact result (`bankroll ± net`)
to its bridge balance — withdrawable to L1 via `bridge_withdraw` (§4). House winnings are therefore returned
fairly to whoever funded that table, with no shared pool and no trust. The Roulette dApp
(`roulette.nadochain.com`) derives table / lobby / scoreboard state from `GET /exec/contract` (§8); there is no
dedicated read API. The build + full test vector is `tests/test_roulette_contract.py`.

```json
{"op":"call","contract":"186ebadb975794e2ed7eeb1c7b5115a5","method":"open","args":[7,<bankCommit>],"value":5000000000000}
{"op":"call","contract":"186ebadb975794e2ed7eeb1c7b5115a5","method":"join","args":[7,<betCommit>,17,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99],"value":100000000000}
{"op":"call","contract":"186ebadb975794e2ed7eeb1c7b5115a5","method":"settle","args":[7]}
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
