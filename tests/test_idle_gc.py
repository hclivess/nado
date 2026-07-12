"""
Idle-account GC (ops/gc_ops.py — deterministic in-block sweeps at epoch boundaries):
  1. account sweep: long-lapsed TRIVIALLY-EMPTY docs deleted; value/extras/active/pending-unbond kept
  2. row-retention sweep: whole ancient recert buckets dropped, bounded by the account watermark
  3. WEIGHT EXACTNESS: open_shares(fidelity_at_epoch(E)) unchanged by the row sweep for every E the
     network still serves (the saturation argument in protocol.py)
  4. revert: a rolled-back boundary block restores docs/rows/watermarks byte-identically
  5. txn-abort atomicity; non-boundary + young-chain no-ops

Run: python3 tests/test_idle_gc.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_idlegc_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("idlegc"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import (EPOCH_LENGTH, GC_IDLE_EPOCHS, RECERT_HISTORY_EPOCHS, POSW_LEASE_EPOCHS,
                      SATURATION_LOOKBACK_EPOCHS, FIDELITY_CAP)
from ops import kv_ops
from ops.gc_ops import apply_idle_gc, revert_idle_gc
from ops.account_ops import create_account
from ops.dividend_ops import fidelity_at_epoch
from ops.mining_ops import open_shares

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

# --- scenario ---------------------------------------------------------------------------------
# Boundary at epoch CUR: account horizon = CUR - GC_IDLE_EPOCHS, row horizon = CUR - RECERT_HISTORY.
CUR = RECERT_HISTORY_EPOCHS + 500                    # both horizons active
HEIGHT = CUR * EPOCH_LENGTH
ACCT_HORIZON = CUR - GC_IDLE_EPOCHS
ROW_HORIZON = CUR - RECERT_HISTORY_EPOCHS

A = "ndo" + "aa" * 23      # idle + trivially empty -> GC'd
B = "ndo" + "bb" * 23      # idle but holds balance -> kept
C = "ndo" + "cc" * 23      # recently active -> kept
D = "ndo" + "dd" * 23      # idle + empty but carries a schemaless extra (public_key) -> kept
E = "ndo" + "ee" * 23      # idle + empty with a stale bond_since row -> GC'd incl. bond_since
S = "ndo" + "ff" * 23      # SATURATION address: continuous run crossing the row horizon

create_account(A, registered=1, fidelity=3)
create_account(B, balance=5, registered=1)
create_account(C, registered=1, fidelity=2)
create_account(D, registered=1)
kv_ops.account_set_field(D, "public_key", "ab" * 32)
create_account(E, registered=1)
kv_ops.bond_since_put(E, 7)
create_account(S, balance=1, registered=1, fidelity=FIDELITY_CAP)   # balance -> exempt from the doc sweep

kv_ops.recert_put(A, ROW_HORIZON + 5)                # idle: latest recert far below acct horizon
kv_ops.recert_put(B, ROW_HORIZON + 6)
kv_ops.recert_put(C, ROW_HORIZON + 7)                # ancient row...
kv_ops.recert_put(C, CUR - 1)                        # ...but ALSO a fresh one -> active
kv_ops.recert_put(D, ROW_HORIZON + 8)
kv_ops.recert_put(E, ROW_HORIZON + 9)
# S: a CONTINUOUS run (gaps <= POSW_LEASE_EPOCHS) from BELOW the row horizon to above it, with more
# than FIDELITY_CAP recerts total, so its capped weight must be identical after the ancient rows go.
S_RUN = [ROW_HORIZON - 10 + i * POSW_LEASE_EPOCHS for i in range(FIDELITY_CAP + 5)]
for r in S_RUN:
    kv_ops.recert_put(S, r)
# ancient DELETABLE rows strictly below the row horizon (A's own plus one for S)
kv_ops.recert_put(A, ROW_HORIZON - 20)
PROBE_E = S_RUN[-1] + 1                              # an epoch the network still serves weights for
WEIGHT_BEFORE = open_shares(fidelity_at_epoch(S, PROBE_E))

RAW_A = kv_ops.account_raw_get(A)
assert RAW_A is not None


def t1_apply_sweeps():
    """Prove the boundary sweep deletes exactly the idle+empty docs and the ancient rows."""
    with kv_ops.write_txn():
        stats = apply_idle_gc(HEIGHT, logger)
    assert stats["accounts"] == 2, f"expected A+E GC'd, got {stats['accounts']}"
    assert kv_ops.account_raw_get(A) is None, "idle empty account must be deleted"
    assert kv_ops.account_raw_get(E) is None, "idle empty account with bond_since must be deleted"
    assert kv_ops.bond_since_get_raw(E) is None, "stale bond_since row must go with the doc"
    assert kv_ops.account_raw_get(B) is not None, "account with balance must be kept"
    assert kv_ops.account_raw_get(C) is not None, "recently-active account must be kept"
    assert kv_ops.account_raw_get(D) is not None, "account with schemaless extras must be kept"
    # row retention: buckets strictly below ROW_HORIZON gone (bounded by the account watermark)
    assert stats["rows"] >= 2, "ancient rows must be dropped"
    assert kv_ops.recert_epochs(A, upto_epoch=ROW_HORIZON - 1) == [], "A's ancient row gone"
    assert ROW_HORIZON + 5 in kv_ops.recert_epochs(A), "rows at/above the horizon stay (weights history)"
    assert kv_ops.meta_get_int("gc_accts_below", -1) == ACCT_HORIZON, "account watermark caught up"
    assert kv_ops.meta_get_int("gc_rows_below", -1) == ROW_HORIZON, "row watermark caught up"


def t2_weight_exactness_across_row_sweep():
    """Prove open_shares(fidelity_at_epoch(E)) is UNCHANGED by the ancient-row deletion for a
    saturated continuous run crossing the horizon — the property that keeps dividend settlement
    roots identical on nodes that GC'd and nodes that never had the ancient rows."""
    after = open_shares(fidelity_at_epoch(S, PROBE_E))
    assert after == WEIGHT_BEFORE == open_shares(FIDELITY_CAP), \
        f"weight must survive the row sweep: {WEIGHT_BEFORE} -> {after}"
    # sanity: the run REALLY lost rows below the horizon
    assert min(kv_ops.recert_epochs(S)) >= ROW_HORIZON, "S's pre-horizon rows must be gone"


def t3_second_boundary_noop():
    """Prove the next boundary with no new horizon movement does nothing (watermarks make it cheap)."""
    with kv_ops.write_txn():
        stats = apply_idle_gc(HEIGHT, logger)        # same height replay (idempotent watermarks)
    assert stats == {"accounts": 0, "rows": 0}, f"replay must be a no-op, got {stats}"


def t4_revert_restores_exactly():
    """Prove rolling back the boundary block restores docs, bond_since, rows and watermarks."""
    with kv_ops.write_txn():
        revert_idle_gc(HEIGHT, logger)
    assert kv_ops.account_raw_get(A) == RAW_A, "account doc must restore byte-identically"
    assert kv_ops.account_raw_get(E) is not None and kv_ops.bond_since_get_raw(E) == 7
    assert ROW_HORIZON - 20 in kv_ops.recert_epochs(A), "ancient row restored"
    assert min(kv_ops.recert_epochs(S)) < ROW_HORIZON, "S's pre-horizon rows restored"
    assert kv_ops.meta_get_int("gc_accts_below", -1) == 0 and kv_ops.meta_get_int("gc_rows_below", -1) == 0, \
        "watermarks restored"
    # and a revert with no record is a clean no-op
    with kv_ops.write_txn():
        revert_idle_gc(HEIGHT, logger)


def t5_txn_abort_atomicity():
    """Prove an aborted boundary txn leaves NOTHING behind — no deletions, no watermark, no record."""
    try:
        with kv_ops.write_txn():
            apply_idle_gc(HEIGHT, logger)
            assert kv_ops.account_raw_get(A) is None, "deleted inside the txn"
            raise RuntimeError("abort")
    except RuntimeError:
        pass
    assert kv_ops.account_raw_get(A) == RAW_A, "abort must undo the account deletion"
    assert kv_ops.meta_get_int("gc_accts_below", -1) == 0, "abort must undo the watermark"
    assert kv_ops.gc_revert_pop(HEIGHT) is None, "abort must undo the revert record"


def t6_noops():
    """Prove non-boundary heights and young chains are complete no-ops."""
    assert apply_idle_gc(HEIGHT + 1, logger) == {"accounts": 0, "rows": 0}, "non-boundary -> no-op"
    with kv_ops.write_txn():
        assert apply_idle_gc(EPOCH_LENGTH * 5, logger) == {"accounts": 0, "rows": 0}, \
            "young chain (horizons pre-genesis) -> no-op"
    assert kv_ops.gc_revert_pop(EPOCH_LENGTH * 5) is None, "no-op must write no record"
    # documented relation the weight-exactness proof rests on
    assert RECERT_HISTORY_EPOCHS > SATURATION_LOOKBACK_EPOCHS, "retention must exceed the saturation lookback"
    assert GC_IDLE_EPOCHS < RECERT_HISTORY_EPOCHS, "accounts must sweep long before their rows vanish"


for name, fn in sorted((n, f) for n, f in list(globals().items())
                       if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)

print(f"\n{'ALL IDLE-GC CHECKS PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
