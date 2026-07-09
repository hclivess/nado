# NADO API reference

NADO runs **two HTTP services**:

| Service | Default port | Public (live) | Purpose |
|---|---|---|---|
| **L1 node** ("relay") | `9173` | `https://get.nadochain.com` (`/…`) | Consensus chain: transactions, blocks, accounts, mempool, mining, messaging. |
| **Execution node** | `9273` | `https://get.nadochain.com/exec/…`, `/da/…` | Rollup/execution layer: contracts, bridge, shielded pools, dividends, coin-flip, data-availability. |

Both speak JSON over HTTP. All state-changing actions go through **one** endpoint — `POST /submit_transaction` on the L1 node — as a signed transaction; the execution layer only ever *reads* the ordered L1 stream, so exec-layer actions are L1 transactions too (a `blob` tx, or a recipient-typed tx). The exec node's endpoints are all **reads** except the DA `POST`s and the delegated prover.

Signing is ML-DSA-44 over `create_txid(body)` (blake2b of the canonical body minus `public_key`). A browser-ready, node-identical implementation is `static/nadotx.js` (`buildBlobTx`, `finalizeTx`, `canonicalize`, `blake2bHash`).

---

## 1. L1 node API (`:9173`)

### Transactions & mempool
| Method | Path | Params | Returns |
|---|---|---|---|
| POST | `/submit_transaction` | body = signed tx JSON | `{result: bool, message}` |
| GET | `/get_transaction` | `?txid=` | the tx + its block, or not-found |
| GET | `/get_transactions_of_account` | `?address=&min_block=` | txs touching an account |
| GET | `/transaction_pool` · `/transaction_buffer` · `/transaction_hash_pool` | — | current mempool views |
| GET | `/get_recommended_fee` | — | suggested fee |

### Blocks & chain
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/get_latest_block` | — | tip block (has `block_number`) |
| GET | `/get_block` | `?hash=` | one block by hash |
| GET | `/get_block_number` | `?number=` | one block by height |
| GET | `/get_blocks_after` · `/get_blocks_before` | `?hash=&count=` | ranges for sync |
| GET | `/get_settled` | — | latest settled/finalized height |
| GET | `/status` | — | node status: `chain_id`, `version`, tip, peers |
| GET | `/health` | — | liveness |
| GET | `/get_snapshot_manifest` · `/get_snapshot_chunk` | `?index=` | fast-sync snapshot |

### Accounts, supply, richlist
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/get_account` | `?address=` | `{balance, …}` (raw units; 1 NADO = 1e10) |
| GET | `/get_supply` · `/wealth_stats` · `/get_rich_list` · `/get_richest` | — | supply + distribution |
| GET | `/resolve_alias` | `?name=` | on-chain alias → address |
| GET | `/get_aliases_of` | `?address=` | aliases owned by an address |

### Mining, governance, dividends
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/mining_status` · `/posw_difficulty` · `/get_open_weights` | `?epoch=` | mining / open-lane state |
| GET | `/treasury_status` | — | treasury + governance |
| GET | `/get_dividend_inflow` | — | presence-dividend pool inflow |

### Messaging (E2E) & peers
| Method | Path | Params | Returns |
|---|---|---|---|
| GET/POST | `/message` | — | encrypted inbox / send |
| GET/POST | `/msg_key` | `?address=` | ML-KEM-768 public key registry |
| GET | `/peers` · `/announce_peer` · `/whats_my_ip` | — | peer set |

### HTLC (atomic swaps)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/htlcs` · `/get_htlc` | `?id=` | hash-timelock contracts |

---

## 2. Execution node API (`:9273`, public under `/exec/…` and `/da/…`)

### State & settlement
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/root` | `?ns=` | `{cursor, state_root}` — applied height + Merkle root |
| GET | `/exec/settlement` | `?ns=` | settlement status vs L1 |

### Contracts (pluggable VM runtimes)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/contracts` | `?ns=&deployer=&prefix=&limit=` (≤500) | `{contracts:[{cid,deployer,methods,abi}], total, limit}` |
| GET | `/exec/contract` | `?ns=&cid=` | one contract: `deployer, methods, code, storage, runtime, abi` |
| GET | `/exec/view` | `?ns=&cid=&method=&args=<JSON list>` | read-only call `{result}` (never persisted) |
| GET | `/exec/examples` | — | starter library `{name:{code, abi}}` (counter, tip_jar, coin_flip) |
| GET | `/exec/runtimes` | — | `{runtimes:[…], default}` |

### Bridge (L1 ⇄ exec value)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/bridge` | `?ns=` | `{balances, withdrawals}` — exec-side bridged balances |
| GET | `/exec/withdrawal_proof` | `?ns=&nonce=` | Merkle proof for a `bridge_withdraw` exit (claim on L1) |

### Presence dividend
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/dividend` | `?ns=&address=` | accrued dividend |
| GET | `/exec/dividend_proof` | `?ns=&nonce=` | proof for a `collect_dividend` claim |

### Shielded pools (privacy)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/shielded` · `/exec/shielded_note` | `?ns=&…` | Zerocash-style pool (root + notes) |
| GET | `/exec/unshields` · `/exec/unshield_proof` | `?ns=&address=` / `?nonce=` | unshield exits + proofs |
| GET | `/exec/field_shielded` · `/exec/field_leaves` | `?ns=` | Phase-2 STARK-friendly pool |
| POST | `/exec/prove_transfer` | witness body | **delegated prover** → join-split STARK bundle |

### Cross-domain messaging
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/outbox` · `/exec/outbox_proof` | `?ns=` / `?seq=` | emitted messages + proofs |
| GET | `/exec/inbox` | `?ns=` | delivered messages |

### Data availability (erasure-coded blobs)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/da/have` · `/da/meta` · `/da/get` · `/da/shard` | `?commitment=` / `?index=` | availability, manifest, bytes, one shard |
| POST | `/da/publish` · `/da/accept` | object / shard body | publish an object / accept a verified shard |

---

## 3. Blob ops — the `data` payload of a `blob` transaction

Send a `blob` tx (`recipient:"blob"`, `amount:0`, `data:<payload>`) via `POST /submit_transaction`. The execution node applies each blob **in L1 order** (`ExecState.apply_blob`). A malformed/reverting blob is a deterministic no-op. `op` selects the action:

| `op` | Payload fields | Effect |
|---|---|---|
| `deploy` | `code, abi?, nonce?, runtime?` | Deploy a contract. `cid = hash(["deploy", deployer, code, nonce])[:32]`. |
| `call` | `contract, method, args[], value?` | Invoke a contract method; persists new storage if it doesn't revert. `value` escrows raw NADO from your bridge balance into the contract for the call (the VM's `VALUE` opcode sees it; `PAY` spends it; a revert refunds exactly). |
| `upgrade` | `contract, code, runtime?, abi?` | Deployer-only (alphanet): replace a contract's code, keeping its cid + storage. |
| `emit` | `to_ns, data` | Append a cross-domain message to the outbox. |
| `bridge_withdraw` | `amount` | Burn exec bridge balance → provable L1 exit (claim with `/exec/withdrawal_proof`). |
| `collect_dividend` | — | Burn accrued dividend → provable L1 claim. |
| `shielded_transfer` / `field_transfer` | proof/bundle | Private transfer inside a shielded pool. |

There is **no coinflip-specific op** — the Coin Flip dApp is a contract driven entirely through `call`/`view`/`upgrade` (see §5).

Contract call args and 256-bit commit/secret integers ride as **bare JSON integers** (`nadotx.canonicalize` emits BigInt as digits, matching the node), so they survive signing byte-for-byte.

## 4. Recipient-typed L1 transactions

Besides `blob`, `POST /submit_transaction` accepts these `recipient` values (built by `ops/transaction_ops.py`):

| `recipient` | Purpose |
|---|---|
| `<ndo… address>` | Ordinary value transfer. |
| `bridge` | **Deposit**: lock L1 coins into escrow; the exec node credits your `bridge` balance. |
| `bridge_withdraw` | Fee-exempt exit carrying the Merkle proof from `/exec/withdrawal_proof`. |
| `dividend_withdraw` | Fee-exempt dividend claim. |
| `alias` | Register/point an on-chain alias. |
| `msgkey` | Publish your ML-KEM-768 messaging key. |
| `attest` | Validator attestation. |
| `htlc_lock` / `htlc_claim` / `htlc_refund` | Hash-timelock (atomic swaps). |

---

## 5. Coin Flip dApp flow (`coinflip.nadochain.com`)

A fair, **staked** 2-player game that is an ordinary on-chain **contract** — not a native module. It lives at
`execnode/contracts/coinflip.json` (runtime `stackvm`), deployed at cid `7ee95a0abd6e00d12edc3bf39f4c8f2d`
(node-owned, so upgradable via the `upgrade` op), and is driven entirely through the generic `call` op with
`value` escrow. It is the reference example of the VM's `VALUE`/`PAY` escrow primitive. Every call is signed by
your NADO wallet (delegated via the `exec_sign` redirect — the key never touches the dApp):

1. **Fund** — bridge NADO into the exec layer (recipient `bridge` deposit) → your `bridge` balance.
2. **Open / join** — `call open {game, commit=HASH(secret)}` with `value=stake` opens a game; a second player `call join {game, commit}` with a matching `value=stake`. Each `value` escrows the stake into the contract as the pot.
3. **Reveal** — `call reveal1|reveal2 {game, secret}` (256-bit CSPRNG secret; the commit is public, so low entropy would be brute-forceable).
4. **Settle** — once both revealed, `call settle {game}` `PAY`s the whole pot to the winner (`result = HASH(s₁+s₂) % 2` → slot 1 or 2).
5. **Or claim** — if an opponent withholds their reveal past the deadline (`CURSOR + 1000` blocks), `call claim {game}` awards the pot to the revealer by forfeit (no-reveal/no-opponent games refund). A sore loser can only stall, never steal.
6. **Cash out** — `bridge_withdraw {amount}` → claim on L1 with `/exec/withdrawal_proof`.

There is **no coinflip read API**: the dApp derives game / lobby / scoreboard from the contract's storage maps
via the generic `GET /exec/contract?cid=7ee95a0abd6e00d12edc3bf39f4c8f2d` (storage maps: `st` stake, `pt` pot,
`sd` settled, `nn` player count, `dl` deadline, `p1`/`p2` addresses, `c1`/`c2` commits, `s1`/`s2` secrets,
`r1`/`r2` revealed flags, `ws` winner slot).
