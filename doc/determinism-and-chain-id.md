# Determinism, chain-id, and browser reproducibility

Consensus requires every node — and the browser light-miner — to compute **identical** hashes,
txids, and signatures from the same data. Two audit items (M14, M3) were consensus-critical
once the legacy `#compat` gates were removed, so they were fixed in this relaunch.

## Canonical encoding (audit M14)

`hashing.py` previously hashed `repr(data)`, which is **not** stable across Python
versions/implementations — a latent network-fork hazard. It is replaced by a canonical encoder:

```python
def canonical_bytes(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
```

- **Sorted keys** → dict insertion order is irrelevant.
- **Compact separators** → whitespace is irrelevant.
- Inputs must be JSON primitives (`str/int/list/dict/None`) and contain **no floats**.

`blake2b_hash(data)` and `blake2b_hash_link(a, b)` hash `canonical_bytes(...)`. This is used for
block hashes, txids (`create_txid`), the producer/ticket set hashes, and address checksums.

### Browser reproducibility (BigInt-safe, no floats)

The canonical form is deliberately trivial to reproduce in a browser: a JS client computes the
same bytes with `JSON.stringify` over recursively sorted keys. The **only** caveat is integers:
NADO raw amounts exceed JS's `2**53` safe-integer limit, so a browser must serialize integers
with **BigInt** (Python's `json` already emits ints exactly). Consequently, **consensus-hashed
structures must never contain floats** — amounts, fees, timestamps, block numbers, rewards and
`cumulative_fees` are all integers.

## Chain-id binding (audit M3)

A `chain_id` (`CHAIN_ID = "nado-relaunch-1"`) is included in:
- every **transaction** body (added in `draft_transaction`, asserted in
  `validate_transaction`), so it is committed by the txid and bound by the signature; and
- every **block** body (added in `construct_block`, checked in `verify_block`).

This prevents a transaction or block from another chain (or the pre-relaunch chain) from being
replayed here.

## Transaction id & signature scheme

- `txid = blake2b_hash(transaction_body)` (canonical) — commits the *whole* body, incl.
  `chain_id`.
- The Ed25519 signature is always over `unhex(txid)` (the legacy `< 102000` "sign the packed
  body" branch is gone — fresh chain). `validate_origin` verifies the signature over the txid;
  `validate_txid` independently recomputes the txid from the body, so tampering any field is
  rejected.
- `proof_sender` checks `make_address(public_key) == sender`.

> Note: an Ed25519 signature is **not** a VRF — `Curve25519.verify` accepts non-unique
> `(R,S)`, so a signature must never be used as selection randomness (see
> [mining.md](mining.md)); the RANDAO beacon is used for that.

## Address derivation

`make_address(public_key)` = `"ndo" + public_key[:42] + make_checksum("ndo" + public_key[:42])`,
where `make_checksum = blake2b_hash(body, size=2)` (canonical). `validate_address` recomputes
the checksum; the keyless reserved recipients `bond`/`unbond` are also accepted. Because the
checksum now uses canonical hashing, the genesis/treasury address is the legacy public-key body
re-checksummed (`…b803280`, see [economics.md](economics.md)).

## In-block transaction ordering — KNOWN OPEN (CO-8)

`construct_block` currently hashes `block_transactions` in the order they came from the local
pool, while the network only converges the transaction *set*. Equal-fee transactions can
therefore let two honest nodes compute different block hashes for the same set. The fix
(recommended, **not yet implemented**) is to canonicalize the order — sort `block_transactions`
by `txid` in `construct_block` and validate that ordering in `verify_block`. Track this for the
S4.3 work.
</content>
