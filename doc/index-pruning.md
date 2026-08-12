# Bounding the number↔hash index

Every other store on a NADO node either plateaus or can be pruned node-locally. The number↔hash index
does neither: it grows at **144 B/block in every mode, forever**, and on a fully-pruned node it is the
dominant term — ~7 GiB at ten years of 6 s blocks, on an idle chain. This document says what the index is
actually for, why the obvious fixes (local pruning, Merkle compression) are wrong, and what the right fix
is.

Figures are the live constants (`protocol.py`, `execnode/state.py`). `tools/sim_disk_growth.py` models the
totals from measured per-row sizes.

---

## 1. Two indexes, not one — and they are not symmetric

    block_by_num    height (8B BE)  ->  block_hash (utf8)      72 B/row
    block_by_hash   block_hash      ->  height (8B BE)         72 B/row

Both are **snapshot-carried** and **root-excluded** (`snapshot_ops.ROOT_EXCLUDED_DBS`): they are written on
block *arrival* rather than derived from applied state, so they must not enter the state root — but a
snapshot joiner still receives them, so its deep hash lookbacks resolve from height 0.

The asymmetry is the whole point of this document.

### `block_by_num` earns its keep — the hash alone IS the payload

Roughly twenty call sites read it, and every one of them consumes the **hash itself**. None needs a body:

| Consumer | What it does with the hash |
|---|---|
| `ops/block_ops.get_epoch_beacon` | anchors the beacon at `(epoch−1)·EPOCH_LENGTH` |
| `ops/attestation_ops` | FFG epoch-boundary targets `h_e`, `h_child` |
| `ops/transaction_ops:126` | asserts a recert's `target_hash` against the epoch boundary |
| `ops/transaction_ops:1024` | PoSW anchor at `max_block − POSW_ANCHOR_OFFSET` |
| `loops/core_loop:2148` | checkpoint hash at `X·EPOCH_LENGTH` |
| `ops/fork_resolution` (via `our_hash_at`) | binary-searches heights for the common ancestor |
| `ops/peer_ops:332` | serves hash-at-height to peers |
| `ops/snapshot_ops:657` | verifies a snapshot manifest against local history |
| exec `BHASH` | hands contracts a finalized block hash as randomness |

So "you get nothing from `get_block_hash_by_number` alone" is false for this half: a 64-char hash *is* the
answer every one of those call sites wants. That is precisely why `prune_block_bodies` keeps the index
while discarding the bodies.

**How deep does it have to reach?** The deepest consensus lookback is `POSW_DIFF_TRAIL = 400` epochs =
**24 000 blocks**; the exec layer's `_BLOCKHASH_RING` is 20 000. Everything else is far shallower
(`FINALITY_DEPTH` 45, `POSW_ANCHOR_OFFSET` 30, epoch boundaries 60). **N ≈ 50 000 blocks (~3.5 days)** is
2× the deepest real consumer.

### `block_by_hash` barely earns anything

The reverse index has **exactly one** non-test reader in the repository:

    ops/block_ops.block_already_indexed(block_hash)   ->  kv_ops.block_hash_indexed
      called from loops/core_loop.py:1867 — the idempotence guard on incorporate_block

That guard answers one question: *"did we already apply this exact block?"*, about a block arriving **now**
from gossip or a re-fetch. Its useful depth is the reorg horizon — `FINALITY_DEPTH = 45`. A block offered
from 40 000 heights back fails height and parent checks long before this guard is consulted.

Note what does **not** use it. Fork resolution is purely height→hash (`_find_answerable` binary-searches
heights). Body loading goes through `block_loc`, which is `_LOCAL_DBS` and already node-local. So
`block_by_hash` is 72 B/block — **half the permanent index** — bought for a tip-local dedupe check.

---

## 2. Why local pruning is not available

Both indexes are in `SNAPSHOT_DBS`, and `state_digest` covers every carried row. Two nodes that retained
different depths would compute different `snapshot_hash` values and fail quorum agreement — a consensus
split produced by a disk-space setting. Retention here must be a **protocol rule, not a node policy**.

`finalized_height` cannot key the rule either: it is in both `ROOT_EXCLUDED_META_KEYS` and
`SNAPSHOT_PAYLOAD_EXCLUDED_META_KEYS` precisely because nodes legitimately differ on it.

## 3. Why Merkle compression is the wrong tool

A Merkle root lets you *verify* data that somebody else still holds. It does not let you *answer* a lookup
whose data you deleted. Committing the index to a root and discarding rows converts
`get_block_hash_by_number` from a local LMDB read into a network fetch plus proof verification — on the
beacon path, the PoSW-anchor path, the FFG path and the `BHASH` path. That puts a liveness dependency on
peers inside block validation, which is a strictly worse failure mode than 7 GiB of disk.

Merkle commitment is right when the data is large, cold, and rarely read. This data is small, hot, and
read on every block.

---

## 4. The fix: bound the snapshot payload deterministically

Filter the carried rows by a window keyed on the **checkpoint height C** — a value every node already
agrees on, since it is what the snapshot is *of*:

    block_by_num    carry heights in [C − N_num,  C],   N_num  = 50 000   (~3.5 days)
    block_by_hash   carry heights in [C − N_hash, C],   N_hash = 10 000   (~17 h, 200x FINALITY_DEPTH)

Because the window is a pure function of C, every honest node builds a byte-identical payload and
`snapshot_hash` agreement holds. Once the payload is bounded, local pruning below the window becomes free
and unobservable — the same status tx history already has.

`N_hash` can be far smaller than `N_num` because of §1: the only consumer is a tip-local dedupe guard.
Keeping the two windows separate is where most of the saving comes from.

### What it saves

At 6 s blocks, ten years is 52.6 M blocks:

| | permanent index |
|---|---|
| today (both unbounded) | **7.05 GiB** |
| bound `block_by_hash` only | ~3.5 GiB |
| bound both | **~4 MB, constant** |

Bounding `block_by_hash` alone halves the term and is the low-risk half of the change.

### Deployment

* **No genesis reroll.** Both stores are root-excluded, so the state root is untouched and existing
  balances/history are unaffected.
* **It does change `snapshot_hash`.** Nodes on the old rule and the new rule disagree on the digest of the
  same checkpoint, so this needs a coordinated cut-over — batch it with the next change that already
  breaks snapshot format (the FRI reparameterisation reroll in `doc/fri-parameters.md` is the obvious
  vehicle).
* **Order:** land the payload filter first (behind the generation gate), then add local pruning below the
  window, then re-measure with `tools/sim_disk_growth.py --measure`.
* **Regression to pin:** a snapshot joiner must still resolve a `POSW_DIFF_TRAIL`-deep hash lookback, and
  `block_already_indexed` must still reject a replayed tip block. Both are cheap to assert directly.
