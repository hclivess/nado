# NADO API reference

NADO runs **two HTTP services**:

| Service | Default port | Public (live) | Purpose |
|---|---|---|---|
| **L1 node** ("relay") | `9173` | `https://get.nadochain.com` (`/…`) | Consensus chain: transactions, blocks, accounts, mempool, mining, messaging. |
| **Execution node** | `9273` | `https://get.nadochain.com/exec/…`, `/da/…` | Rollup/execution layer: contracts, bridge, shielded pools, dividends, coin-flip, data-availability. |

Both speak JSON over HTTP. All state-changing actions go through **one** endpoint — `POST /submit_transaction` on the L1 node — as a signed transaction; the execution layer only ever *reads* the ordered L1 stream, so exec-layer actions are L1 transactions too (a `blob` tx, or a recipient-typed tx). The exec node's endpoints are all **reads** except the DA `POST`s (`/da/publish`, `/da/accept`, `/da/announce`) and `POST /exec/verify_call` (checks a proven call without executing it). There is no delegated prover: it took a spending key over HTTP and was removed (security review 2026-09-23, Z7); the wallet proves on the device.

Signing is ML-DSA-44 over `create_txid(body)` (blake2b of the canonical body minus `public_key`). A browser-ready, node-identical implementation is `static/nadotx.js` (`buildBlobTx`, `finalizeTx`, `canonicalize`, `blake2bHash`).

---

## 1. L1 node API (`:9173`)

### Transactions & mempool
| Method | Path | Params | Returns |
|---|---|---|---|
| POST | `/submit_transaction` | body = signed tx JSON | `{result: bool, message}` |
| GET | `/get_transaction` | `?txid=` | the tx + its block, or not-found |
| GET | `/get_transactions_of_account` | `?address=&min_block=` | txs touching an account |
| GET | `/transaction_pool` · `/transaction_hash_pool` | — | current mempool views |
| GET | `/transaction_ids` | `?compress=zstd` | txids only (~64B/tx) — the cheap half of mempool set reconciliation |
| POST | `/transactions_by_id` | body = codec list of txids (≤1000) | only the named txs — divergent peers fetch just what they miss |
| GET | `/next_block_txids` | — | `{tip, height, txids}`: exactly the tx set this node would assemble into the next block on its tip — the pre-assembly reconcile probe ([leaderless-assembly.md](leaderless-assembly.md)) |
| GET | `/get_recommended_fee` | — | suggested fee (tip block's mean fee + 1, in-memory) |
| GET | `/get_account_mempool` | `?address=` | the address's PENDING activity: `free_in`/`free_out`, `exec_in`/`exec_out` and light per-tx summaries |

### Blocks & chain
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/get_latest_block` | — | tip block (has `block_number`) |
| GET | `/get_block` | `?hash=` or `?number=` (+`hash_only=1`) | one block, by hash or height; `hash_only=1` answers from the height index even where the body is pruned |
| GET | `/get_blocks_after` · `/get_blocks_before` | `?hash=&count=` | ranges for sync |
| GET | `/get_settled` | `?ns=` | the quorum-settled exec checkpoint `{ns, exec_cursor, state_root}` (default namespace when `ns` is omitted) |
| GET | `/status` | — | node status: `chain_id`, `version`, tip, peers; debug telemetry: `hard_finality`, `recovery` (live recovery phase), `recovery_fail` (last failed recovery), `last_block_reject` (why production last skipped), `last_fork_diff` (tx-set diff of the last fork's first divergent block) |
| GET | `/status` → `jobs` | | every job this machine should run (doc/jobs.md): `roles`, `units` (systemd state, enabled, last run and result per declared unit), `inner` (in-node samplers: `dex_prices.last_ok`), `reconcile` (the root reconciler's last result) `problems` (anything missing, stopped, failing or stale — empty = healthy) and `unreadable` (units whose state could not be read) |
| GET | `/status` → `native` | | per native crate: library present, current against its Rust sources, newer than this process |
| GET | `/status` → `auth_active` | | whether the `auth` transaction (account authentication) is live on this chain generation |
| GET | `/status_pool` | — | the `/status` this node last read from each peer, keyed by IP (fleet view: `running_commit`, height, …) |
| GET | `/health` | `?key=` | CPython GC stats for leak triage — server key or localhost only; use `/status` for liveness |
| GET | `/get_snapshot_manifest` · `/get_snapshot_chunk` | chunk: `?id=[&height=]` | fast-sync snapshot (manifest of the latest finalized checkpoint; one msgpack chunk by id) |
| GET | `/protocol.json` · `/protocol.js` | — | the client-facing protocol constants (integers above 2^53 - 1 as decimal strings) |

### Accounts, supply, richlist
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/get_account` | `?address=` | `{balance, …}` (raw units; 1 NADO = 1e10) |
| GET | `/get_account` (auth fields) | `?address=` | with account authentication live, the doc also carries `auth` (the installed config: `v`, `keys`, `sign`, `reconf`), `auth_pending` (`cfg`, `eff`, `txid`) and `auth_freeze` — see doc/key-rotation.md |
| GET | `/get_supply` · `/wealth_stats` · `/get_rich_list` | — | supply + distribution |
| GET | `/resolve_alias` | `?name=` | on-chain alias → address |
| GET | `/get_aliases_of` | `?address=` | aliases owned by an address |
| GET | `/msig_address` | `?threshold=&members=` (comma-separated) | the canonical M-of-N descriptor and its multisig address (pure derivation; 400 on a bad descriptor) |
| GET | `/wallet_view` | `?address=&since=` | everything a wallet polls per tick in one call: `latest`, `account`, `mining_status`, `unbond`, `mempool`, `tags` |

### Mining, governance, dividends
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/mining_status` | `?address=` | the address's mining view (lane, presence, share odds) |
| GET | `/get_open_weights` | `[?epoch=]` | open-lane weights; with `?epoch=` the committed (or reconstructed) weights of that epoch. `?epoch=` REFUSES (410) epochs whose recert lookback crosses the idle-GC row-retention horizon (a cold exec node bootstraps from a settled checkpoint instead) |
| GET | `/mining_history` | `?address=&days=` | what the address earned per UTC day, split by source (`open`, `bonded`, `dividend`, `total`) |
| GET | `/duty_committee` | `[?epoch=&address=]` | the epoch's duty committee `{epoch, seats}`; with `?address=` also `in_committee`, `seats_of` |
| GET | `/get_unbond` | `?address=` | a pending unbond `{amount, release_block}` (or null), `matured`, `blocks_left` |
| GET | `/posw_difficulty` | — | RETIRED at gen 25: always `{required_t: 0, retired: true}` |
| GET | `/mining_status` fields (2026-09-08) | `?address=` | `bonded_producing`, `my_bonded_raw`, `my_bonded_effective` (= stake), `bond_attest_required` (always False: savings need no device), `bond_plain` (always True), `open_excluded_bonded` (always False), `bonded_producer_cut` (raw), `expected_seconds_between_wins`. The gen-25 cap / knee / pool fields (`bond_cap_active`, `bond_knee`, `bond_device_cap`, `pools_retired`, the delegation view) and `/pools` were removed after the betanet-8 reroll |
| GET | `/treasury_status` | — | treasury + governance |
| GET | `/get_dividend_inflow` | `?epoch=` (required) | `{epoch, inflow}`: the presence-dividend pool inflow credited during that epoch |

### Referrals & invites ([referrals.md](referrals.md))
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/referrals` | `?address=` (required) | who the address named as its referrer, and the identities that named it, each with its window |
| GET | `/invite` | `?id=` | one funded invite `{sender, amount, expiry, status, claimant}` (or null) and `tip` |
| GET | `/invites` | `?address=` | the invites the address funded |

### Messaging (E2E) & peers
| Method | Path | Params | Returns |
|---|---|---|---|
| GET/POST | `/message` | — | encrypted inbox / send |
| GET/POST | `/msg_key` | `?address=` | ML-KEM-768 public key registry |
| GET | `/peers` · `/announce_peer` · `/whats_my_ip` | — | peer set |
| GET | `/relays` | — | wallet-usable relays on this chain: self + every status_pool peer with its live height, the operator-published TLS `url` (or null) and the bare `api` address — the web wallet's failover pool ([relays.md](relays.md)) |

### HTLC (atomic swaps)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/htlcs` · `/get_htlc` | `/htlcs?address=` (optional filter) / `/get_htlc?id=` | hash-timelock contracts |

### Shielded exits (L1 side)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/unshield_claimed` | `?addr=&nonces=1,2,3` (≤500) | which of the address's unshield exits L1 has already released |

---

## 2. Execution node API (`:9273`, public under `/exec/…` and `/da/…`)

### State & settlement
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/root` | `?ns=` | `{cursor, state_root}` — applied height + Merkle root |
| GET | `/exec/roots` | `?ns=` | this node's epoch-boundary root ring `{cursor: root}` plus its live cursor |
| GET | `/exec/settlement` | `?ns=` | settlement status vs L1 |
| GET | `/exec/state_snapshot` | `?ns=` | full state payload as of this node's last accepted settle — the settled-checkpoint bootstrap donor side (joiner verifies its recomputed root against L1 `/get_settled`); 404 until the node has settled once |

### Contracts (pluggable VM runtimes)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/contracts` | `?ns=&deployer=&prefix=&limit=` (≤500) | `{contracts:[{cid,deployer,methods,abi}], total, limit}` |
| GET | `/exec/contract` | `?ns=&cid=` | one contract: `deployer, methods, code, storage, runtime, abi` |
| GET | `/exec/view` | `?ns=&cid=&method=&args=<JSON list>` | read-only call `{result}` (never persisted) |
| GET | `/exec/examples` | — | starter library `{examples: {name:{code, abi}}}` (counter, tip_jar, commit_box) |
| GET | `/exec/runtimes` | — | `{runtimes:[…], default}` |
| GET | `/exec/blockhash` | `?height=` or `?heights=H1,H2,…` | L1 block hashes for the BLOCKHASH randomness `{height: hex|null}` |
| GET | `/exec/beacon` | `?ns=&epochs=E1,E2,…` (≤64) | `{cursor, beacons: {epoch: hex|null}}` — the BEACON randomness a game settles from |

### Assets ([assets.md](assets.md))
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/assets` | `?issuer=&holder=` | the asset registry with holder counts |
| GET | `/exec/asset` | `?id=[&holder=]` | one asset: metadata and holder table (or one balance) |
| GET | `/exec/allowances` | `?owner=` / `?spender=` `[&asset=]` | delegated-spend approvals (amounts as strings) |

### Bridge (L1 ⇄ exec value)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/bridge` | `?ns=` | `{balances, withdrawals}` — exec-side bridged balances |
| GET | `/exec/withdrawal_proof` | `?ns=&nonce=` | Merkle proof for a `bridge_withdraw` exit (claim on L1) |
| GET | `/exec/withdrawals` | `?address=[&root=]` | an address's unclaimed cash-outs (`amount` as a string), each with its proof once L1's settled root covers it; the wallet and game SDK claim them automatically |

### Presence dividend
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/dividend` | `?ns=&address=` | accrued dividend |
| GET | `/exec/dividend_proof` | `?ns=&nonce=` | proof for a `collect_dividend` claim |
| GET | `/exec/dividend_proofs` | `?address=[&root=]` | every claimable proof for an address in one call; served against L1's settled root by default |

### Shielded pools (privacy)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/unshields` · `/exec/unshield_proof` | `?addr=` / `?nonce=[&root=]` | unshield exits + proofs |
| GET | `/exec/stwo_spendable` | `?root=&nf=&cm1=&cm2=&unshield=&fee=` | would a Stwo spend with these public inputs apply now (the live pool, doc/stwo-migration.md §5.1) |
| GET | `/exec/stwo_nullifiers` | — | the Stwo pool's spent set, sorted (checked locally by the wallet) |
| GET | `/exec/stwo_carried_deposits` | `[?addr=]` | the public records of Stwo deposits carried across the last reroll |
| GET | `/exec/field_shielded` · `/exec/field_leaves` | `?ns=` | the Stwo shielded pool (status · leaves) |

### Cross-domain messaging
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/exec/outbox` · `/exec/outbox_proof` | `?ns=` / `?seq=` | emitted messages + proofs (a message is GC'd once its finalized `xmsg` delivery burns the L1 nullifier) |
| GET | `/exec/inbox` | `?ns=` | delivered messages |

### Data availability (erasure-coded blobs)
| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/da/have` · `/da/meta` · `/da/get` · `/da/shard` | `?c=<commitment>` (`/da/shard` also `&i=<shard index>`) | availability, manifest, bytes, one shard |
| POST | `/da/publish` · `/da/accept` · `/da/announce` | object / shard body | publish an object / accept a verified shard / announce one |

---

## 3. Blob ops — the `data` payload of a `blob` transaction

Send a `blob` tx (`recipient:"blob"`, `amount:0`, `data:<payload>`) via `POST /submit_transaction`. The execution node applies each blob **in L1 order** (`ExecState.apply_blob`). A malformed/reverting blob is a deterministic no-op. `op` selects the action:

| `op` | Payload fields | Effect |
|---|---|---|
| `deploy` | `code, abi?, nonce?, runtime?` | Deploy a contract. `cid = hash(["deploy", deployer, code, nonce])[:32]`. |
| `call` | `contract, method, args[], value?` | Invoke a contract method; persists new storage if it doesn't revert. `value` escrows raw NADO from your bridge balance into the contract for the call (the VM's `VALUE` opcode sees it; `PAY` spends it; a revert refunds exactly). |
| `upgrade` | `contract, code, runtime?, abi?` | Deployer-only (betanet): replace a contract's code, keeping its cid + storage. |
| `emit` | `to_ns, data` | Append a cross-domain message to the outbox. |
| `bridge_withdraw` | `amount` | Burn exec bridge balance → provable L1 exit (claim with `/exec/withdrawal_proof`). |
| `collect_dividend` | — | Burn accrued dividend → provable L1 claim. |
| `field_transfer` | bundle | Private transfer inside the Stwo shielded pool. (`shielded_transfer`, the deleted legacy pool's op, is skipped at every height.) |

There is **no coinflip-specific op** — the Coin Flip dApp is a contract driven entirely through `call`/`view`/`upgrade` (see §5).

Contract call args and 256-bit commit/secret integers ride as **bare JSON integers** (`nadotx.canonicalize` emits BigInt as digits, matching the node), so they survive signing byte-for-byte.

## 4. Recipient-typed L1 transactions

Besides `blob`, `POST /submit_transaction` accepts these `recipient` values (built by `ops/transaction_ops.py`):

| `recipient` | Purpose |
|---|---|
| `<address>` | Ordinary value transfer (a format-2 address, `address_ops.is_address`). |
| `bridge` | **Deposit**: lock L1 coins into escrow; the exec node credits your `bridge` balance. |
| `bridge_withdraw` | Fee-exempt exit carrying the Merkle proof from `/exec/withdrawal_proof`. |
| `dividend_withdraw` | Fee-exempt dividend claim. |
| `alias` | Register/point an on-chain alias. |
| `msgkey` | Publish your ML-KEM-768 messaging key. |
| `attest` | Validator attestation. |
| `htlc_lock` / `htlc_claim` / `htlc_refund` | Hash-timelock (atomic swaps). |

**Landing semantics.** `max_block` binds every tx. `blob`, `bridge`, `bridge_withdraw`,
`dividend_withdraw`, `faucet` and plain transfers land *flexibly* in `[min_block, max_block]` — set
`min_block` to your submit tip + 8 (`TX_INCLUSION_DELAY`) so no producer can include the tx before it
has propagated (omitting it is legal but was a measured fork driver). Everything else (`settle`,
`bond`, `register`, governance, …) lands *exactly* at `max_block`; aim it far enough ahead for gossip
(the node's own submitters use 12–30 blocks). `duty` is windowed: it carries a signed `min_block` and lands anywhere in
`[min_block, max_block]` — every duty timing rule binds to `max_block`, so the window is semantically
free and removes the landing cliff that seeded the last organic fork class; legacy duties (no
`min_block`) still land exactly.

**Mempool door gates (user-origin only).** The relay refuses at submission — never at gossip, so a
refusal can't diverge pools — (a) a `dividend_withdraw` whose `min_block` is missing or nearer than
tip + 4 ("refresh your wallet"), and (b) a second `withdraw` (unbond claim) from a sender who already
has one waiting in the pool ("unbond withdrawal already pending"), (c) a second `dividend_withdraw`
for the same (sender, exec nonce) while one is pooled ("dividend claim already pending"), (d) a
`blob` with `op: collect_dividend` whose `min_block` is missing or nearer than tip + 4 (the same
propagation rule as (a) — this narrow op is only ever wallet-built), and (e) a second `register` from
a sender who already has one pooled ("registration already pending"). One in-flight claim/attempt is
complete — duplicates can never pay out and only pile up as phantom pending credit until they die.

---

## 5. Coin Flip dApp flow (`coinflip.nadochain.com`)

A fair, **staked** 2-player game that is an ordinary on-chain **contract** — not a native module. It lives at
the zkVM game `execnode/games/coinflip.py` (runtime `zkvm`; redeployed each reroll — the live cid is at coinflip.nadochain.com)
(node-owned, so upgradable via the `upgrade` op), and is driven entirely through the generic `call` op with
`value` escrow. It is the reference example of the VM's `VALUE`/`PAY` escrow primitive. Every call is signed by
your NADO wallet (delegated via the `exec_sign` redirect — the key never touches the dApp):

1. **Fund** — bridge NADO into the exec layer (recipient `bridge` deposit) → your `bridge` balance.
2. **Open / join** — `call open {game, commit=HASH(secret)}` with `value=stake` opens a game; a second player `call join {game, commit}` with a matching `value=stake`. Each `value` escrows the stake into the contract as the pot.
3. **Reveal** — `call reveal {game, secret}` (256-bit CSPRNG secret; the commit is public, so low entropy would be brute-forceable).
4. **Settle** — once both revealed, `call settle {game}` `PAY`s the whole pot to the winner (`result = HASH(s₁+s₂+gameId) LO32 % 2` → slot 1 or 2).
5. **Or forfeit** — the reveal window is `REVEAL_WINDOW` = 600 blocks from the join (`dl`). After it closes, `call settle {game}` pays the WHOLE pot to a lone revealer; if nobody revealed, each player gets their own stake back. The opener can `cancel` a game nobody joined and take the stake back. A sore loser can only stall, never steal.
6. **Cash out** — `bridge_withdraw {amount}` → claim on L1 with `/exec/withdrawal_proof` (the wallet does this automatically from `/exec/withdrawals` once the record is settled; a game page asks the wallet's background signer with `{bridge_claim: {nonce}}`).

There is **no coinflip read API**: the dApp derives game / lobby / scoreboard from the contract's storage maps
via the generic `GET /exec/contract?cid=<coinflip-cid>` (storage maps: `st` stake, `pt` pot,
`sd` settled, `nn` state, `dl` reveal deadline, `p1`/`p2` addresses, `c1`/`c2` commits, `s1`/`s2` secrets,
`v1`/`v2` revealed flags, `ws` winner slot, `md` commit-reveal mode, `sh` legacy settle height).

## 6. Signing from a dApp (`exec_sign`) — who may be signed for silently

A dApp never holds a key. It asks the wallet to sign, one of two ways (`static/nadodapp.js` does both):

- **redirect:** `https://<wallet>/?exec_sign=<base64 JSON>&ret=<return URL>&app=<name>`; the wallet answers by
  navigating back to `ret` with `?ok=1&txid=…` (or `ok=0&err=…`);
- **hidden frame:** a reusable `<iframe src="<wallet>/?bgsvc=1">`; the page posts `{nadoExecSignReq: 1, payload, app}`
  and the wallet posts the result back to the page's origin.

**Silent signing follows the caller, never `ret`** (2026-09-27; `tests/test_exec_sign_trust.mjs`). A request is signed
without a tap only when the site that ASKED is a trusted one — the postMessage sender's `e.origin`, or on the redirect
path the origin of `document.referrer` — and it is the same site `ret` names. `ret` is part of the request, so a link
from anywhere could name a trusted game; until this rule, such a link made a default wallet sign any value-free call
with no tap. A request whose caller is unknown or different still works, through the visible confirm, which says the
site did not ask and shows every counterparty (`to`, asset, `spender`, arguments).

What this asks of a dApp:

- **Do not set `Referrer-Policy: no-referrer`** (header or `<meta name="referrer">`) on a page that redirects to the
  wallet. The browser default (`strict-origin-when-cross-origin`) sends the origin the wallet needs; with no referrer
  every move asks for a tap.
- `ret` must be an `http(s)` URL; anything else (`javascript:`, `data:`) is refused as malformed.
- A hidden-frame answer always goes to the sender's own origin; a `ret` in the message is ignored.

What the silent path covers: value-free contract calls (on by default, Settings → auto-sign), NADO bets up to the
user's cap (never an asset-valued call), `htlc_claim` paying the user, and — only if the user turns on "auto-sign
everything" — any contract call, never an asset transfer, approval or contract transfer.
