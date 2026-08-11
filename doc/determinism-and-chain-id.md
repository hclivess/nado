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

A `chain_id` (`CHAIN_ID = "betanet-8"`, and it changes at every reroll) is included in:
- every **transaction** body (added in `draft_transaction`, asserted in
  `validate_transaction`), so it is committed by the txid and bound by the signature; and
- every **block** body (added in `construct_block`, checked in `verify_block`).

This prevents a transaction or block from another chain (or the pre-relaunch chain) from being
replayed here.

## Transaction id & signature scheme

- `txid = blake2b_hash(transaction_body)` (canonical) — commits the *whole* body, incl.
  `chain_id`.
- The ML-DSA-44 signature is always over `unhex(txid)` (the legacy `< 102000` "sign the packed
  body" branch is gone — fresh chain). `validate_origin` verifies the signature over the txid;
  `validate_txid` independently recomputes the txid from the body, so tampering any field is
  rejected.
- `proof_sender` checks `make_address(public_key) == sender`.

> Note: an ML-DSA-44 signature is **not** a VRF — the scheme accepts non-unique
> `(R,S)`, so a signature must never be used as selection randomness (see
> [mining.md](mining.md)); the RANDAO beacon is used for that.

## Address derivation

`make_address(public_key)` = `"ndo" + public_key[:42] + make_checksum("ndo" + public_key[:42])`,
where `make_checksum = blake2b_hash(body, size=2)` (canonical). `validate_address` recomputes
the checksum; the keyless reserved recipients `bond`/`unbond` are also accepted. Because the
checksum now uses canonical hashing, the genesis/treasury address is the legacy public-key body
re-checksummed (`…b803280`, see [economics.md](economics.md)).

## State-root determinism — what the root may commit (CHAIN_GENERATION 7)

Every block hash commits an L1 `state_root` (see [l2-settlement.md](l2-settlement.md) for the parallel
L2 `exec_root`): `construct_block` computes it, `block_content_hash`/`save_block` hash it, and
`verify_block` **re-derives it and fatally rejects a mismatch**. This is what binds *state* — not just
the block sequence — to consensus: a node whose balances/stake/attestations diverge from the producer's
computes a different root, so it either produces a losing block hash or refuses to extend. Divergence is
**fatal by design** — a halted node is recoverable; a node that climbs on diverged state is silent poison.

For that gate to be sound, the root MUST be a **pure function of the applied block sequence** — identical
on every node that applied the same blocks, regardless of how it got there (live production, cold sync,
snapshot + tail replay), its height, or its pruning/retention. So the invariant is:

> **Only data written *from block-included transactions* may enter the state root.**

The root is `snapshot_ops.l1_state_root()` = a blake2b Merkle root over the **consensus subset** of
`kv_ops.SNAPSHOT_DBS` — full DBs in `ROOT_EXCLUDED_DBS` are dropped, and the rows named in
`ROOT_EXCLUDED_META_KEYS` are dropped from the `meta` DB. The invariant has a sharper form than "written
from a block tx": the root must be **invariant to the reorg/retention PATH**, not just to the block set — a
value can be block-derived and still fork the root if it is written/pruned differently on a node that has
rolled back. Four classes of data have been pulled OUT of the root — each was a real fork:

1. **Reorg revert journals** (`bond_since_revert`, `hb_revert`, `msgkey_revert`, `gc_revert`,
   `block_loc`) → moved to `kv_ops._LOCAL_DBS` (excluded from `SNAPSHOT_DBS` entirely). These are
   rollback bookkeeping whose contents depend on a node's reorg history. *(betanet-7 h76000 split.)*
2. **Block storage** (`block_by_num`, `block_by_hash`) → `ROOT_EXCLUDED_DBS`. These are written on block
   *arrival* (`save_block`), so their contents depend on a node's height, history-retention/pruning, and
   orphan/fork bodies accumulated across reorgs. They were **52% of the root and grew 1:1 with height**,
   so a catching-up node computed a different as-of-parent root than the producer and tripped the (correct)
   fatal gate at ~h62 — the **betanet-8 fresh-sync wedge**. Blocks are already committed by the block-hash
   *chain* (parent linkage + tx content), so putting the block bytes in the state root was a **redundant,
   non-deterministic second commitment**. They are still *carried in the snapshot transfer* (a joiner's deep
   hash-lookbacks need them) — only the root **commitment** excludes them. Fixed in `CHAIN_GENERATION` 5.
3. **Node-local `meta` rows** (`finalized_height`, `pruned_below`) → `ROOT_EXCLUDED_META_KEYS`. The gen-5
   fix above was *incomplete*: not the whole `meta` DB is block-derived. `finalized_height` is the FFG
   finality floor, advanced by **peer corroboration** — a producer at tip ≥ `FINALITY_DEPTH` persists
   `tip − FINALITY_DEPTH`, while a catching-up node that does not yet consider its tip corroborated keeps
   `0`; `pruned_below` is the block-body prune watermark, advanced by **local retention/pruning progress**.
   The instant finality first advanced, a producer and a fresh synchronizer at the *same tip* committed
   different as-of-parent roots, so the fatal gate refused **block 47** (= `FINALITY_DEPTH`+2, with
   `FINALITY_DEPTH`=45). Both rows are still *carried in the snapshot* (a joiner needs the finality floor and
   prune watermark) — only the root **commitment** excludes them, and the exclusion is **surgical**: every
   *other* `meta` row (attestation-uniqueness replay guards, chain markers) stays in the root because it *is*
   block-derived. Fixed in `CHAIN_GENERATION` 6.
4. **Retention / rollback-path-dependent `meta` rows** (`execsum:<h>`) → `ROOT_EXCLUDED_META_PREFIXES` (a
   key-**prefix** exclusion in the `meta` DB). This one was *not* a block-application bug at all: a canonical
   forward replay of the diverged span reproduced the network root byte-for-byte. The fault was that
   **`rollback_one_block` is not the exact inverse of `incorporate_block`**. `incorporate_block` writes
   `execsum:<h>` *and* prunes the one leaving the retention window (`exec_summary_del(h − EXEC_SUMMARY_RETENTION)`),
   but `rollback_one_block` only deletes the block's *own* height and never restores the pruned row — so a node
   that has rolled back holds a **different `execsum` set** than a forward-only node at the same tip. An
   emergency-mode rollback storm dropped `execsum:3301..3305` on the catching-up betanet-8 nodes; their
   `l1_state_root` diverged from the canonical forward-only chain and the fatal gate refused them **forever**
   (a node wedged below its own finalized floor cannot self-heal). The summaries are still *carried in the
   snapshot* (settle-with-proof binding needs the retention window) — only the root **commitment** drops them.
   A sibling of the same bug: reverting an epoch's first dividend inflow left a phantom `divinflow:<e>=0` row
   (a present-`0` `meta` int merkleizes differently from an absent key); `dividend_inflow_add` now `meta_del`s
   on zero so apply/rollback round-trips exactly. Fixed in `CHAIN_GENERATION` 7.

Everything that remains in the root — accounts (balances/stake), `totals`, the block-derived `meta` rows
(attestation uniqueness + replay guards, `divinflow`, chain markers), `attestations`, `commits`/`reveals`,
`settlements`, `recerts`, `bond_since`, `unbonds`, `aliases`, `htlcs`, `treasury_*` — is written **only**
from block-included transactions (`ops/account_ops.py` apply path) **and reverts exactly on rollback**, so it
is identical on every node that applied the same blocks by any path.

Regression coverage: `tests/test_seed_divergence.py` (`test_revert_journals_excluded_from_root`,
`test_block_stores_excluded_from_root`, `test_node_local_meta_excluded_from_root`,
`test_empty_account_canonicalized`, `test_execsum_excluded_from_root`, `test_dividend_inflow_revert_roundtrips`).
The rule for anyone adding a new `SNAPSHOT_DB` **or a new `meta` row**: **if its value — or its mere
presence — is not a deterministic function of the applied block sequence that also reverts exactly on
rollback, it must be excluded from the root** — `_LOCAL_DBS` if node-only, `ROOT_EXCLUDED_DBS` for a whole
carried-but-not-committed DB, `ROOT_EXCLUDED_META_KEYS` for an individual `meta` row, or
`ROOT_EXCLUDED_META_PREFIXES` for a `meta` key family. And any new `meta` row that can return to `0` from
absent must `meta_del` at `0`, or rollback will leave a phantom that forks the root.

## In-block transaction ordering — RESOLVED (CO-8)

`construct_block` currently hashes `block_transactions` in the order they came from the local
pool, while the network only converges the transaction *set*. Equal-fee transactions can
therefore let two honest nodes compute different block hashes for the same set. The fix
(**now implemented**) is to canonicalize the order — `construct_block`/`rebuild_block` sort `block_transactions`
by `txid` in `construct_block` and validate that ordering in `verify_block`. Track this for the
S4.3 work.
