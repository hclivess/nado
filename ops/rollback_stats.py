"""
Node-local REORG TELEMETRY (non-consensus): every block this node successfully reverts bumps a
per-UTC-day counter AND advances that day's max reorg depth (the deepest single reorg run — how
many consecutive blocks one emergency pass had to unwind). Persisted as one small JSON file
({"YYYY-MM-DD": {"c": blocks_reverted, "d": max_depth}}) and served by GET /rollback_stats for the
wallet's Stats tab (reorgs-per-day chart with a trend line and a per-day deepest-reorg overlay).

Depth is what tells a shallow-but-frequent churn (many 1-block reorgs) apart from a rare deep one
(a single burst that unwound many blocks) even when the block totals match. Legacy days recorded
before depth tracking existed carry d=null ("not measured"), never a fake 0 — the chart draws no
depth mark for them, consistent with the null≠zero rule the daily-stats panels follow.

The file lives at the node-home TOP LEVEL (~/nado/rollback_stats.json), deliberately outside the
purge allowlist in ops/data_ops.purge_chain_data: a genesis reroll wipes chain-derived data, but
"how turbulent were this node's reorgs" is operational history ABOUT the node — wiping it with the
chain would erase exactly the record an operator wants after an eventful day. UTC days so every
node's series lines up on the network panel regardless of box timezone.

Writes are atomic (tmp + os.replace) and rare — a reorg burst is bounded by max_rollbacks per
emergency pass — so recording can sit inline in the rollback path. Recording must NEVER break a
rollback: callers wrap record() and drop failures (telemetry loses a tick; the chain does not care).
"""
import json
import os
import threading
import time

from ops.data_ops import get_home

_RETENTION_DAYS = 400                 # keep over a year of history; the chart reads a window of it


def _stats_path():
    return f"{get_home()}/rollback_stats.json"


_lock = threading.Lock()


def _load() -> dict:
    """The persisted {day: {"c": count, "d": max_depth}} map; a missing or corrupt file is an EMPTY
    history, never an error (a telemetry file must not be able to wedge the node that writes it).
    Legacy days stored as a bare int (count only, before depth tracking) load as d=None ("not
    measured") so the record survives the format change without inventing a depth it never saw."""
    try:
        with open(_stats_path()) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        out = {}
        for k, v in data.items():
            if isinstance(v, dict):
                d = v.get("d")
                out[str(k)] = {"c": int(v.get("c", 0)), "d": None if d is None else int(d)}
            else:                              # legacy bare-count int: depth was never recorded
                out[str(k)] = {"c": int(v), "d": None}
        return out
    except Exception:
        return {}


def _day(ts=None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def record(depth: int = 1):
    """Count ONE reverted block against today (UTC) and raise today's max reorg depth to `depth` —
    the running length of the reorg burst this block belongs to (1 for the tip, 2 for its parent,
    …), so the day's stored depth ends up equal to the deepest single reorg seen that day. Prune
    beyond retention, persist atomically."""
    with _lock:
        data = _load()
        today = _day()
        rec = data.get(today) or {"c": 0, "d": 0}
        rec["c"] += 1
        d = int(depth)
        rec["d"] = d if rec["d"] is None else max(rec["d"], d)
        data[today] = rec
        for k in sorted(data)[:-_RETENTION_DAYS]:
            del data[k]
        path = _stats_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)


def daily_counts(days: int = 30) -> list:
    """The last `days` UTC days as a DENSE, oldest-first [{date, count, depth}] series ending today.
    Zero-filled on purpose: a day with no reorgs is a real, chartable zero — count 0 AND depth 0 (a
    calm day genuinely had no reorg to be deep), not a gap. A day that WAS turbulent but predates
    depth tracking carries depth null ("not measured"), distinct from a measured 0 — sparse output
    would make every chart consumer re-derive the calendar."""
    days = max(1, int(days))
    data = _load()
    now = int(time.time())
    out = []
    for i in range(days - 1, -1, -1):
        day = _day(now - i * 86400)
        rec = data.get(day)
        out.append({"date": day, "count": 0, "depth": 0} if rec is None
                   else {"date": day, "count": rec["c"], "depth": rec["d"]})
    return out
