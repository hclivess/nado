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

### Coin Flip (staked betting) — **new**
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/flip_game` | `?ns=&game=<id>` | game state (see §4) |

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
| `deploy` | `code, abi?, nonce?, runtime?` | Deploy a contract. `cid = hash(["deploy", deployer, code, nonce])[:32]`, immutable. |
| `call` | `contract, method, args[]` | Invoke a contract method; persists new storage if it doesn't revert. |
| `emit` | `to_ns, data` | Append a cross-domain message to the outbox. |
| `bridge_withdraw` | `amount` | Burn exec bridge balance → provable L1 exit (claim with `/exec/withdrawal_proof`). |
| `collect_dividend` | — | Burn accrued dividend → provable L1 claim. |
| `shielded_transfer` / `field_transfer` | proof/bundle | Private transfer inside a shielded pool. |
| `flip_bet` | `game, commit, stake` | **Coin Flip:** open/join a game; escrow `stake` from your bridge balance into the pot. |
| `flip_reveal` | `game, secret` | Reveal your secret (must satisfy `HASH(secret)==commit`). |
| `flip_settle` | `game` | After both reveal, pay the pot to the winner (`blake2b([s₁,s₂])%2`). Anyone may call. |
| `flip_claim` | `game` | After the reveal deadline: revealer wins by forfeit, or stakes are refunded. |

Contract call args and the 256-bit `commit`/`secret` ride as **bare JSON integers** (`nadotx.canonicalize` emits BigInt as digits, matching the node), so they survive signing byte-for-byte.

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

A fair, **staked** 2-player game entirely on-chain, signed by your NADO wallet (delegated via the `exec_sign` redirect — the key never touches the dApp):

1. **Fund** — bridge NADO into the exec layer (recipient `bridge` deposit) → your `bridge` balance.
2. **Bet** — `flip_bet {game, commit=HASH(secret), stake}`. First bettor opens; the second must match the stake. Both stakes escrow into the pot.
3. **Reveal** — `flip_reveal {game, secret}` (256-bit secret; the commit was public, so low entropy would be brute-forceable — the dApp uses a full CSPRNG secret).
4. **Settle** — once both revealed, `flip_settle {game}` pays `2×stake` to the winner (parity of `blake2b([s₁,s₂])`).
5. **Or claim** — if an opponent withholds their reveal past the deadline (`cursor + 1000` blocks), `flip_claim {game}` awards the pot to the revealer by forfeit (no-reveal/no-opponent games refund). A sore loser can only stall, never steal.
6. **Cash out** — `bridge_withdraw {amount}` → claim on L1 with `/exec/withdrawal_proof`.

Game state is public at `GET /exec/flip_game?game=<id>`:
```json
{ "exists": true, "stake": 1000, "pot": 2000, "settled": true,
  "deadline": 22168, "cursor": 21200, "ncom": 2, "nrev": 2,
  "players": { "ndo…": {"slot":1,"committed":true,"revealed":true} },
  "result": 0, "winner_slot": 1 }
```
