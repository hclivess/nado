"""
Exec summaries survive a snapshot bootstrap, and their retention is bounded.

The settle-with-proof DA binding is a pure function of kv_ops.exec_summary_get. A snapshot-synced node that
lacked those summaries would REFUSE settle-with-proof txs its peers accept -> consensus fork. That is exactly
the M-8 class of bug (snapshot bootstrap dropping the L1 replay-guard nullifier sets), so it is asserted
here rather than assumed: summaries live in the `meta` sub-DB, which is in kv_ops.SNAPSHOT_DBS, so the
full-consensus-state snapshot carries them — but "should be covered" is not evidence, a round trip is.

Also asserts the retention bound. Summaries are snapshot-carried, so an unbounded set would grow with chain
length AND bloat every snapshot; incorporate_block GCs one height per block at EXEC_SUMMARY_RETENTION.

Run: python3 tests/test_exec_summary_snapshot.py
"""
import os, sys, tempfile, traceback
_HOME = tempfile.mkdtemp(prefix="nado_execsnap_")
os.environ["HOME"] = _HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import kv_ops, snapshot_ops
from protocol import EXEC_SUMMARY_RETENTION, SETTLE_PROOF_MAX_SPAN

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t_meta_is_snapshot_carried():
    """The structural precondition: summaries live in `meta`, and `meta` is snapshot-carried."""
    assert "meta" in kv_ops.SNAPSHOT_DBS, "exec summaries live in the meta sub-DB — it MUST be snapshotted"
    assert kv_ops._exec_summary_key(7).startswith("execsum:"), "summary key must be a meta scalar key"


def t_summaries_survive_a_snapshot_round_trip():
    """Write summaries, snapshot, wipe into a FRESH home, import, and require them back byte-identical."""
    kv_ops.init_env(_HOME)
    written = {}
    for h in range(100, 106):
        inert = (h % 2 == 0)
        calls = {"default": [h * 11 + 1, h * 11 + 2]} if h % 3 else {}
        kv_ops.exec_summary_put(h, inert, calls)
        written[h] = (1 if inert else 0, calls)

    snap = snapshot_ops.build_snapshot(105, "cafebabe" * 8, "test-proto", "0", home=_HOME)
    manifest = snap[0] if isinstance(snap, tuple) else snap["manifest"]
    chunks = snap[1] if isinstance(snap, tuple) else snap["chunks"]

    other = tempfile.mkdtemp(prefix="nado_execsnap2_")
    os.environ["HOME"] = other
    kv_ops.init_env(other)
    assert kv_ops.exec_summary_get(101) is None, "fresh home must start with no summaries"
    ok = snapshot_ops.import_snapshot(manifest, chunks, home=other)
    assert ok, "snapshot import must succeed"

    for h, (inert, calls) in written.items():
        got = kv_ops.exec_summary_get(h)
        assert got is not None, f"summary for height {h} did NOT survive the snapshot (M-8 class fork risk)"
        assert int(got.get("inert", -1)) == inert, f"height {h}: inert bit changed across the snapshot"
        got_calls = {k: [int(x) for x in v] for k, v in (got.get("calls") or {}).items()}
        assert got_calls == {k: [int(x) for x in v] for k, v in calls.items() if v}, \
            f"height {h}: call leaves changed across the snapshot ({got_calls} != {calls})"

    os.environ["HOME"] = _HOME
    kv_ops.init_env(_HOME)


def t_retention_window_covers_the_span_cap():
    """The GC window must be strictly larger than the largest span a proof may cover, or a legal proof
    could reference a height already collected."""
    assert EXEC_SUMMARY_RETENTION > SETTLE_PROOF_MAX_SPAN, \
        f"retention {EXEC_SUMMARY_RETENTION} must exceed the span cap {SETTLE_PROOF_MAX_SPAN}"
    from protocol import FINALITY_DEPTH
    assert EXEC_SUMMARY_RETENTION > FINALITY_DEPTH, \
        "a GC'd height must be unreachable by a rollback, else rollback would need to restore it"


def t_delete_is_idempotent():
    """The rolling GC deletes a height every block, including ones that were never written (a node that
    started mid-chain). That must not raise inside incorporate_block's write txn."""
    kv_ops.init_env(_HOME)
    kv_ops.exec_summary_del(987654)           # never written
    kv_ops.exec_summary_put(555, True, {})
    kv_ops.exec_summary_del(555)
    kv_ops.exec_summary_del(555)              # twice
    assert kv_ops.exec_summary_get(555) is None, "delete must be idempotent and actually remove"


def t_absent_reads_as_none_not_empty():
    """The settle branch distinguishes 'no summary' (refuse) from 'summary with no calls' (fold nothing).
    Conflating them would let a node bind a span to an empty call list and accept a fabricated one."""
    kv_ops.init_env(_HOME)
    kv_ops.exec_summary_put(777, True, {})
    empty = kv_ops.exec_summary_get(777)
    assert empty is not None and (empty.get("calls") or {}) == {}, "a call-free block still has a summary"
    assert kv_ops.exec_summary_get(778) is None, "an unwritten height must read None, never {}"


for name, fn in [
    ("meta sub-DB is snapshot-carried (precondition)", t_meta_is_snapshot_carried),
    ("summaries survive a snapshot round trip", t_summaries_survive_a_snapshot_round_trip),
    ("retention window exceeds span cap + reorg reach", t_retention_window_covers_the_span_cap),
    ("rolling GC delete is idempotent", t_delete_is_idempotent),
    ("absent reads None, not empty-calls", t_absent_reads_as_none_not_empty),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
