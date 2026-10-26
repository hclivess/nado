# Exchange & custodian integration

How to integrate NADO into a centralized exchange, custodian, or payment processor: address handling,
deposit detection, confirmation/finality rules, and withdrawal signing + broadcast.

> **Compatibility, up front.** NADO's node RPC is **not** wire-compatible with Bitcoin Core's JSON-RPC
> (`getrawtransaction`, `sendrawtransaction`, `getbalance`) or Ethereum's JSON-RPC 2.0 (`eth_getBalance`,
> `eth_sendRawTransaction`, `eth_getTransactionByHash`). You **cannot** point a Bitcoin/Geth/Web3 client at
> a NADO node. NADO exposes a **custom REST/HTTP API**. The good news: the *model* is account-based (ETH-like,
> not UTXO) with **deterministic finality**, so a thin custom adapter is straightforward — the only real lift
> is the post-quantum signer for withdrawals.

---

## 1. Chain model in one screen

| Property | Value | Integration impact |
|---|---|---|
| Ledger model | **Account-based** (direct balances) | No UTXO tracking; balance = one lookup. ETH-style. |
| Signatures | **ML-DSA-44** (post-quantum, FIPS 204) | secp256k1 HSMs/libs do **not** apply. Needs the NADO signer. |
| Finality | Depth floor `finalized_height` (tip − 45, still reorgable) + un-crossable `hard_finality` (FFG checkpoint / backstop) | Credit deposits at `hard_finality` — no reorg guesswork. |
| Address | 42 hex body + 8 hex checksum (50 chars, lowercase hex, no prefix) | Custom validation; not base58/bech32/EIP-55. |
| Amount unit | integer **raw**, `1 NADO = 10_000_000_000 raw` (10 decimals) | Not 8 (BTC sats) / 18 (ETH wei). |
| Min fee | `MIN_TX_FEE = 1000` raw | See `/get_recommended_fee`. |
| Tx expiry | `max_block` landing window | Unmined txs expire — rebroadcast/reprice logic differs from BTC/ETH. |
| Transport | REST over HTTP, default port **9173** | JSON; `?compress=zstd` returns zstd-compressed JSON. |
| Network id | `chain_id` (read it from `/status`; it changes at every reroll) | Bound into every tx — cross-chain replay is impossible. |

---

## 2. RPC surface (the endpoints you need)

All are `GET` with `?query=params` unless noted. Add `?compress=zstd` for zstd-compressed JSON; default is
plain JSON. Amount fields are integer **raw**; add `?readable=true` where supported to get
decimal strings.

| Endpoint | Purpose |
|---|---|
| `GET /status` | Tip + **finality**: `latest_block_hash`, `finalized_height`, `hard_finality`, `ffg_finalized`, `snapshot_height`, `protocol`, `version`, `chain_id`. Poll this. |
| `GET /get_latest_block` | Full latest block (height, hash, txs). |
| `GET /get_block?number=N` | Block by height. |
| `GET /get_block?hash=H` | Block by hash. |
| `GET /get_account?address=A[&readable=true]` | Balance & account record: `balance`, `produced`, `bonded`, `reg_epoch`. `404` if the account has never been seen. |
| `GET /get_transaction?txid=T` | One tx by id. **Note:** returns the tx body only — see the [confirmations gap](#6-confirmations--finality). |
| `GET /get_transactions_of_account?address=A&min_block=N` | Address history from height `N` up. Deposit-scan primitive. Rate-limited 60/min/IP. |
| `POST /submit_transaction` | Broadcast a signed tx (JSON body). `200` accept, `403` reject, `429` over 30/min/IP. |
| `GET /get_recommended_fee` | Suggested fee (raw). |
| `GET /get_supply` | Circulating / total supply. |
| `GET /resolve_alias?alias=x` | Resolve a human alias → address (optional; users may deposit via alias). |
| `GET /health` | Liveness probe. |

Run your **own** node and talk to it over loopback — do not depend on a third-party endpoint for balances or
broadcast.

---

## 3. Addresses

Format 2 (50 chars, all lowercase hex, no prefix): **42 hex** body = a 21-byte blake2b hash of the WHOLE ML-DSA
public key, + **8 hex** blake2b checksum of the body.

```
<42 hex: blake2b(["nado-address-v2", pubkey_hex_lower], size=21)><8 hex: blake2b(body, size=4)>
```

Both hashes run over the **compact JSON encoding** of their input (`hashing.canonical_bytes`), not the raw text, and
the size is the blake2b OUTPUT length (`digest_size`), not a slice of a 32-byte digest. Concretely:

```python
import hashlib, json
enc  = lambda x: json.dumps(x, separators=(",", ":"), sort_keys=True).encode()
body = hashlib.blake2b(enc(["nado-address-v2", pubkey_hex.lower()]), digest_size=21).hexdigest()
addr = body + hashlib.blake2b(enc(body), digest_size=4).hexdigest()    # enc(body) = the body WITH its JSON quotes
```

Hashing the checksum over the bare 42 characters (no quotes) gives a different value and rejects every valid address.
Check your implementation on a real one: `3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f` → body
`3cc4c44a94a900f79716dc6d3822a81603b1ce7862`, checksum `ce03572f`. Reference: `ops/address_ops.address_body_v2` /
`make_checksum`.

**Validate before crediting or paying out** (mirrors consensus, `ops/address_ops.validate_address`):

1. length exactly 50, lowercase hex;
2. `address[-8:] == blake2b(enc(address[:-8]), digest_size=4)` (the checksum, over the JSON-quoted body) — catches typos/truncation. A 46-char
   address (the old format 1) is invalid everywhere.

An address can **receive and hold** NADO with **no on-chain registration** — a transfer to a never-seen
address creates it. (On-chain *registration* — a device-attested presence lease — is only for mining participation, not for
holding or receiving.) So exchange deposit addresses are just freshly generated keypairs.

---

## 4. Amounts & fees

* Everything on the wire is an **integer in raw units**. `1 NADO = 10_000_000_000 raw` (10 decimals).
  Convert: `nado = raw / 1e10`. Never use floats for accounting — keep raw integers end to end.
* `MIN_TX_FEE = 1000` raw. Query `GET /get_recommended_fee` for a live suggestion and set `fee` at or above it.
* Fees are a flat field on the tx (`fee`), not gas × price. Note that ML-DSA keys/signatures are large
  (pubkey ~1.3 KB, signature ~2.4 KB), so a tx is a few KB — size it into your fee policy if that ever
  becomes fee-relevant.

---

## 5. Deposits (credit-in)

Poll-based; there is no push/websocket feed yet (see [§9](#9-gaps--recommended-node-additions)).

1. Generate a keypair per user (or use a shared address + a memo/tag convention if you prefer).
2. On an interval, read `GET /status` → note `latest_block_hash`, `hard_finality`.
3. For each watched address, `GET /get_transactions_of_account?address=A&min_block=<last_scanned>` and pick out
   txs whose `recipient` is your address and `amount > 0`.
4. **Credit only at finality** — see below.
5. Persist `hard_finality` as your high-water mark so a restart re-scans only the unfinalized tail.

Ignore txs whose `recipient` is a **reserved keyword** (not a payment) — any name in
`protocol.RESERVED_RECIPIENTS` (`bond`, `unbond`, `withdraw`, `register`, `duty`, `blob`, `settle`, `bridge`, `htlc_*`,
`dividend*`, `treasury*`, `tpm_*`, …). Only a valid 50-char address is a transfer recipient.

---

## 6. Confirmations & finality

This is where NADO is *stronger* than PoW chains: it has **deterministic economic finality**, not just
probabilistic confirmations.

* `hard_finality` (from `/status`) is the **un-crossable floor**: rollback refuses to go below it, ever. It is
  the higher of the FFG-finalized checkpoint and a liveness backstop (see [finality.md](finality.md)).
* `finalized_height` is the faster **depth floor** (`tip − FINALITY_DEPTH`, 45 blocks); a deep reorg may still
  cross it, so treat it as a softer tier.
* **Canonical deposit rule:** credit a deposit once its **block height ≤ `hard_finality`**. Below that floor
  there is no reorg risk — no "wait N confirmations and hope."
* A softer, faster tier (optional): `confirmations = latest_height − tx_height`, credit at some threshold, but
  treat as *provisional* until it is at or below `hard_finality`.

> **Gap to be aware of:** `GET /get_transaction?txid=` currently returns the **transaction body only** — it does
> **not** include the block height, confirmations, or a finalized flag. Today you derive height from the
> address-history scan (§5), which knows each tx's block. Surfacing `block_number` / `confirmations` /
> `finalized` directly on `/get_transaction` is a recommended node addition ([§9](#9-gaps--recommended-node-additions)).

---

## 7. Withdrawals (pay-out)

A withdrawal is a **signed transfer transaction** posted to `/submit_transaction`. Sign **offline** in your hot
wallet; the private key never touches the node.

### 7.1 Transaction schema

A transfer is a flat dict (field order is irrelevant — the txid uses a canonical sorted encoding):

```jsonc
{
  "sender":      "<50-hex address>",  // your hot-wallet address
  "recipient":   "<50-hex address>",  // destination (validate the checksum first!)
  "amount":      12300000000,         // raw units (1.23 NADO)
  "fee":         1000,                // raw, >= MIN_TX_FEE / get_recommended_fee
  "timestamp":   1783460000,          // unix seconds
  "nonce":       "…",                 // unique per tx (anti-replay)
  "max_block":   17600,               // the last block this tx may land in (expiry)
  "chain_id":    "<from /status>",    // binds the tx to this network
  "data":        "",                  // "" for a plain transfer
  "public_key":  "…",                 // ML-DSA-44 pubkey (hex); omittable after first on-chain use (pubkey-once)
  "txid":        "…",                 // blake2b of the canonical body, EXCLUDING public_key
  "signature":   "…"                  // ML-DSA sign(private_key, unhex(txid))
}
```

### 7.2 txid & signature (must be byte-exact)

1. Build the body **without** `txid`/`signature`.
2. `txid = blake2b(canonical_sorted_json(body without "public_key"))` — `public_key` is a recoverable witness,
   not identity, so it is excluded from the hash (this is what lets a later tx omit the 1.3 KB key and still
   hash the same). See `ops/transaction_ops.create_txid`.
3. `signature = ML-DSA-44_sign(private_key, unhex(txid))`.
4. The node re-derives the txid and verifies the signature identically; any encoding divergence forks the txid,
   so match the canonical encoding exactly (the browser light-miner and CLI both do).

Because `chain_id` is inside the signed body, a tx **cannot** be replayed on another network.

### 7.3 Broadcast, expiry, and re-send

* `POST /submit_transaction` with the signed dict (JSON body). `200` accepted into the pool, `403`
  rejected (bad sig / fee / balance / expiry), `429` over 30/min/IP.
* `max_block` gives the tx a **landing window** — if it isn't mined in time it **expires** and must be
  rebuilt with a fresh `timestamp`/`max_block`/`nonce`. This differs from BTC/ETH where a tx lingers in the
  mempool indefinitely; build expiry handling into your broadcaster.
* Poll the address history / a future `/get_transaction` confirmation field to confirm the withdrawal landed
  and finalized before marking it complete.

---

## 8. Reserved recipients & other gotchas

* **Reserved recipients** (every name in `protocol.RESERVED_RECIPIENTS`) are protocol operations, not payments —
  never treat them as deposits/withdrawals.
* **Post-quantum key sizes:** pubkey ~1.3 KB, signature ~2.4 KB. Transactions are a few KB; plan storage and any
  size-based fee logic accordingly. After an address's first on-chain tx, later txs may **omit** `public_key`
  (pubkey-once) — but including it is always valid.
* **Aliases:** users may hand out a human alias instead of an address; `GET /resolve_alias` maps it to the
  owner address. Deposits are still indexed under the resolved address.
* **Pre-mainnet network:** this is a betanet (read `chain_id` from `/status`; it changes at every reroll, which
  carries balances forward); treat values as non-final until mainnet.

---

## 9. Gaps & recommended node additions

To make CEX integration turnkey, the following are worth adding to the node (tracked separately):

1. **`confirmations` + `finalized` on `/get_transaction`** — return the tx's `block_number`, `latest_height −
   block_number`, and whether `block_number ≤ hard_finality`, so integrators don't cross-reference the block
   store themselves.
2. **A push feed for new finalized blocks** (websocket or long-poll) so deposit detection isn't heavy polling.
3. **A standalone signing SDK/CLI** (offline ML-DSA-44 signer + txid/canonical-encoding + address-checksum
   helpers) in a couple of languages — this is the single biggest blocker to third-party integration, since no
   existing secp256k1 tooling applies. `scripts/nado_cli.py` already builds and signs txs against the exact
   `ops.transaction_ops.construct_*` helpers and is the reference implementation.
4. **Paginated / cursor history** on `/get_transactions_of_account` for large-volume addresses.

## 10. "Do I need an ETH-JSON-RPC shim?"

A thin gateway could map a **read** subset (`eth_blockNumber`, `eth_getBalance`, `eth_getBlockByNumber`,
`eth_getTransactionByHash`, `net_version`) onto NADO REST, letting some off-the-shelf tooling do balance/height
polling. But address format and — critically — **signing** still diverge, so withdrawals always need the native
ML-DSA signer. A documented REST integration + a signing SDK (above) is the higher-leverage path than chasing
RPC-shape compatibility.

---

## Minimal integration checklist

- [ ] Run a local NADO node; poll `GET /status` for `hard_finality` / `chain_id`.
- [ ] Generate ML-DSA-44 keypairs; derive + checksum 50-char addresses; validate all external addresses.
- [ ] Deposits: scan `GET /get_transactions_of_account`; **credit at `block_number ≤ hard_finality`**.
- [ ] Withdrawals: build → `create_txid` (canonical, pubkey-excluded) → ML-DSA sign → `POST /submit_transaction`;
      handle `max_block` expiry + `429` backoff.
- [ ] Accounting in **raw integer units** (`/1e10` only for display).
- [ ] Ignore reserved-recipient txs.
