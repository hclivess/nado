"""
Per-day reorg telemetry (ops/rollback_stats.py) — the data behind the wallet Stats tab's
reorgs-per-day chart (/rollback_stats): blocks reverted per UTC day plus the day's max reorg depth.

The load-bearing properties: counts accumulate per UTC day and SURVIVE reloads (a restart must not
zero the history); max depth records the DEEPEST single reorg run, not the total; the served series
is DENSE and zero-filled (a calm day is a real 0 the chart can draw, not a gap); legacy bare-count
days load with depth null ("not measured", never a fake 0); a corrupt or missing file is an empty
history, never an exception (telemetry must not be able to wedge the rollback path that feeds it);
retention prunes the oldest days only.

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
    """Each record() is ONE reverted block; the arg is that block's burst depth. Three calls today =
    count 3, and the day's depth is the deepest run seen (3), not the total — through a fresh load."""
    RS.record(1); RS.record(2); RS.record(3)
    series = RS.daily_counts(days=1)
    assert series[-1]["count"] == 3, series
    assert series[-1]["depth"] == 3, "depth must be the DEEPEST single reorg, not a sum"
    assert RS._load() == {series[-1]["date"]: {"c": 3, "d": 3}}, "must persist, not just cache"


def t_depth_is_max_not_last():
    """A later, shallower reorg must not lower the day's recorded max depth."""
    RS.record(5); RS.record(1)
    assert RS.daily_counts(days=1)[-1]["depth"] == 5, "depth must stay at the day's peak"


def t_legacy_bare_count_loads_with_null_depth():
    """A day persisted in the old {day: int} format loads as count=int, depth=null (not measured) —
    never a fabricated 0 — so the chart draws no depth mark for pre-tracking days."""
    import json
    day = "2019-06-15"
    with open(RS._stats_path(), "w") as f:
        json.dump({day: 4}, f)
    loaded = RS._load()
    assert loaded == {day: {"c": 4, "d": None}}, loaded


def t_series_is_dense_zero_filled_and_ordered():
    """30 requested days = 30 rows, oldest first, ending today, calm days as literal zero count AND
    zero depth (a calm day genuinely had no reorg to be deep)."""
    series = RS.daily_counts(days=30)
    assert len(series) == 30, len(series)
    assert series == sorted(series, key=lambda r: r["date"]), "must be oldest-first"
    assert series[-1]["date"] == time.strftime("%Y-%m-%d", time.gmtime()), "must end today (UTC)"
    assert all(r["count"] == 0 and r["depth"] == 0 for r in series[:-1]), "untouched days = real 0/0, not missing"


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
    ("depth records the day's peak, not the last reorg", t_depth_is_max_not_last),
    ("legacy bare-count day loads with null depth", t_legacy_bare_count_loads_with_null_depth),
    ("series is dense, zero-filled, oldest-first", t_series_is_dense_zero_filled_and_ordered),
    ("corrupt file reads as empty and self-repairs", t_corrupt_file_is_empty_history),
    ("retention prunes the oldest days only", t_retention_prunes_oldest_only),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
