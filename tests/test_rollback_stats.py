"""
Per-day rollback telemetry (ops/rollback_stats.py) — the data behind the wallet Stats tab's
rollbacks-per-day chart (/rollback_stats).

The load-bearing properties: counts accumulate per UTC day and SURVIVE reloads (a restart must not
zero the history); the served series is DENSE and zero-filled (a calm day is a real 0 the chart can
draw, not a gap); a corrupt or missing file is an empty history, never an exception (telemetry must
not be able to wedge the rollback path that feeds it); retention prunes the oldest days only.

Run: python3 tests/test_rollback_stats.py
"""
import os, sys, tempfile, time, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_rbstats_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import rollback_stats as RS

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t_record_accumulates_and_persists():
    """Three rollbacks today must read back as today=3 — including through a fresh load (restart)."""
    RS.record(); RS.record(2)
    series = RS.daily_counts(days=1)
    assert series[-1]["count"] == 3, series
    assert RS._load() == {series[-1]["date"]: 3}, "must persist, not just cache"


def t_series_is_dense_zero_filled_and_ordered():
    """30 requested days = 30 rows, oldest first, ending today, calm days as literal zeros."""
    series = RS.daily_counts(days=30)
    assert len(series) == 30, len(series)
    assert series == sorted(series, key=lambda r: r["date"]), "must be oldest-first"
    assert series[-1]["date"] == time.strftime("%Y-%m-%d", time.gmtime()), "must end today (UTC)"
    assert all(r["count"] == 0 for r in series[:-1]), "untouched days must be REAL zeros, not missing"


def t_corrupt_file_is_empty_history():
    """Garbage on disk must never raise — record() must also recover by rewriting it."""
    with open(RS._stats_path(), "w") as f:
        f.write("{not json")
    assert RS._load() == {}
    assert RS.daily_counts(days=5)[-1]["count"] == 0
    RS.record()
    assert RS.daily_counts(days=1)[-1]["count"] == 1, "record must recover from a corrupt file"


def t_retention_prunes_oldest_only():
    """Days beyond the retention window fall off the back; recent days are untouched."""
    import json
    old = {f"2001-01-{d:02d}": 9 for d in range(1, 11)}
    with open(RS._stats_path(), "w") as f:
        json.dump(old, f)
    real, RS._RETENTION_DAYS = RS._RETENTION_DAYS, 3
    try:
        RS.record()
    finally:
        RS._RETENTION_DAYS = real
    kept = RS._load()
    assert len(kept) == 3 and time.strftime("%Y-%m-%d", time.gmtime()) in kept, kept
    assert "2001-01-01" not in kept and "2001-01-09" in kept, f"must drop the OLDEST: {sorted(kept)}"


for name, fn in [
    ("record accumulates per day and persists", t_record_accumulates_and_persists),
    ("series is dense, zero-filled, oldest-first", t_series_is_dense_zero_filled_and_ordered),
    ("corrupt file reads as empty and self-repairs", t_corrupt_file_is_empty_history),
    ("retention prunes the oldest days only", t_retention_prunes_oldest_only),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
