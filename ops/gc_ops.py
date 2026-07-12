"""
Idle-account GC — deterministic, IN-BLOCK state pruning (the protocol.py GC note is the spec).

Runs inside the FIRST block of each epoch's write txn (core_loop.incorporate_block calls apply;
rollback.rollback_one_block calls revert), so every node mutates state at the same height with the
same inputs and snapshot state roots stay identical — a node-local sweep would fork them.

Two decoupled sweeps, each driven by a consensus meta watermark and bounded by GC_MAX_PER_EPOCH:

  ACCOUNT sweep (`gc_accts_below` watermark -> epoch - GC_IDLE_EPOCHS): walks recert_by_epoch
  buckets once; an address whose LATEST recert is older than the idle horizon and whose account doc
  is trivially empty (balance=bonded=produced=0, no schemaless extras, no pending unbond) has its
  doc + bond_since row deleted. Its recert ROWS are kept — dividend-weight reconstruction
  (ops/dividend_ops.fidelity_at_epoch) reads rows, never docs.

  ROW-RETENTION sweep (`gc_rows_below` watermark -> epoch - RECERT_HISTORY_EPOCHS): drops whole
  recert epoch buckets. Weight-exactness argument in protocol.py: any continuous recert run that
  spans the retention horizon must exceed FIDELITY_CAP recerts and is capped identically either
  way, so open_shares(fidelity_at_epoch(E)) is unchanged for every E the network still serves
  (/get_open_weights refuses epochs whose lookback would cross the horizon).

REVERT SAFETY: every deleted doc/row and the previous watermarks go into ONE record in the
NODE-LOCAL gc_revert sub-DB, written inside the same txn — a rollback of the boundary block
restores everything byte-identically; records below finality are pruned lazily (local, no
determinism requirement, since finality bounds every legal rollback).
"""
from ops import kv_ops
from protocol import EPOCH_LENGTH, GC_IDLE_EPOCHS, RECERT_HISTORY_EPOCHS, GC_MAX_PER_EPOCH

# account docs eligible for GC may carry ONLY these zeroed/lease fields — any schemaless extra
# (public_key pubkey-once binding, kem_pub messaging key, ...) makes the account NOT trivially
# empty and permanently exempts it (conservative by design).
_GC_FIELDS = set(kv_ops.ACCOUNT_FIELDS)


def _trivially_empty(doc: dict) -> bool:
    return (doc.get("balance", 0) == 0 and doc.get("bonded", 0) == 0 and doc.get("produced", 0) == 0
            and set(doc) <= _GC_FIELDS)


def apply_idle_gc(block_height: int, logger) -> dict:
    """Run both sweeps for the boundary block at `block_height` (no-op at non-boundary heights and
    while the horizons are still pre-genesis). MUST be called inside the block's write txn, at the
    same fixed point on every node. Returns {"accounts": n, "rows": n} for logging."""
    if block_height % EPOCH_LENGTH != 0 or block_height == 0:
        return {"accounts": 0, "rows": 0}
    epoch = block_height // EPOCH_LENGTH
    row_horizon = epoch - RECERT_HISTORY_EPOCHS
    acct_horizon = epoch - GC_IDLE_EPOCHS
    record = {"rows": [], "accounts": [], "bond_since": [], "wm_rows": None, "wm_accts": None}
    work = 0

    # --- ACCOUNT sweep FIRST: candidates from recert buckets below acct_horizon, own watermark ----
    # Ordering invariant: the ROW sweep below never deletes a bucket the account sweep hasn't
    # processed yet (its bound includes gc_accts_below) — otherwise, on a cold start with both
    # watermarks at 0, row deletion could erase an idle address's only recerts before the account
    # sweep ever enumerated it, leaving its doc permanently un-GC-able.
    wm_accts = kv_ops.meta_get_int("gc_accts_below", 0)
    if acct_horizon > wm_accts:
        record["wm_accts"] = wm_accts
        e = wm_accts
        while e < acct_horizon and work < GC_MAX_PER_EPOCH:
            for addr in kv_ops.recert_bucket_addresses(e):             # LMDB dup order — deterministic
                work += 1
                if kv_ops.recert_latest(addr) >= acct_horizon:
                    continue                                           # active again later — not idle
                doc = kv_ops.account_raw_get(addr)
                if doc is None:
                    continue                                           # already GC'd via an earlier bucket
                if not _trivially_empty(doc) or kv_ops.unbond_get(addr) is not None:
                    continue                                           # holds value/extras — exempt
                since = kv_ops.bond_since_get_raw(addr)
                if since is not None:
                    record["bond_since"].append((addr, int(since)))
                    kv_ops.bond_since_del(addr)
                record["accounts"].append((addr, doc))
                kv_ops.account_del(addr)
            e += 1
        kv_ops.meta_set_int("gc_accts_below", e)      # consensus watermark (identical on every node)

    # --- ROW-RETENTION sweep: whole buckets below min(row_horizon, account watermark) -------------
    wm_rows = kv_ops.meta_get_int("gc_rows_below", 0)
    row_bound = min(row_horizon, kv_ops.meta_get_int("gc_accts_below", 0))
    if row_bound > wm_rows:
        record["wm_rows"] = wm_rows
        e = wm_rows
        while e < row_bound and work < GC_MAX_PER_EPOCH:
            pairs = kv_ops.recert_bucket_del(e)       # deletes the whole bucket, returns (addr, epoch)
            record["rows"].extend(pairs)
            work += len(pairs) + 1                    # +1: an empty bucket still costs a probe
            e += 1
        kv_ops.meta_set_int("gc_rows_below", e)       # consensus watermark

    if record["rows"] or record["accounts"] or record["bond_since"] \
            or record["wm_rows"] is not None or record["wm_accts"] is not None:
        kv_ops.gc_revert_put(block_height, record)    # NODE-LOCAL, same txn — exists iff the sweep did
    return {"accounts": len(record["accounts"]), "rows": len(record["rows"])}


def revert_idle_gc(block_height: int, logger):
    """Exact inverse of apply_idle_gc for a rolled-back boundary block. MUST run inside the rollback
    write txn, BEFORE the other reversals (mirror of apply running last). A missing record means the
    sweep was a complete no-op at this height — then so is the revert."""
    record = kv_ops.gc_revert_pop(block_height)
    if record is None:
        return
    for addr, doc in record.get("accounts", []):
        kv_ops.account_raw_put(addr, doc)
    for addr, since in record.get("bond_since", []):
        kv_ops.bond_since_put(addr, since)
    for addr, epoch in record.get("rows", []):
        kv_ops.recert_put(addr, epoch)
    if record.get("wm_rows") is not None:
        kv_ops.meta_set_int("gc_rows_below", record["wm_rows"])
    if record.get("wm_accts") is not None:
        kv_ops.meta_set_int("gc_accts_below", record["wm_accts"])


def prune_local_revert_records(finalized_height: int):
    """Lazy NODE-LOCAL cleanup: rollback can never cross the finalized floor, so records below it
    are dead weight. Called opportunistically (outside any consensus path)."""
    try:
        return kv_ops.gc_revert_prune(int(finalized_height))
    except Exception:
        return 0
