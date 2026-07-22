"""
Node-local ROLLBACK TELEMETRY (non-consensus): every block this node successfully reverts bumps a
per-UTC-day counter, persisted as one small JSON file ({"YYYY-MM-DD": count}) and served by
GET /rollback_stats for the wallet's Stats tab (rollbacks-per-day chart with a trend line).

The file lives at the node-home TOP LEVEL (~/nado/rollback_stats.json), deliberately outside the
purge allowlist in ops/data_ops.purge_chain_data: a genesis reroll wipes chain-derived data, but
"how turbulent were this node's reorgs" is operational history ABOUT the node — wiping it with the
chain would erase exactly the record an operator wants after an eventful day. UTC days so every
node's series lines up on the network panel regardless of box timezone.

Writes are atomic (tmp + os.replace) and rare — a rollback burst is bounded by max_rollbacks per
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
    """The persisted {day: count} map; a missing or corrupt file is an EMPTY history, never an error
    (a telemetry file must not be able to wedge the node that writes it)."""
    try:
        with open(_stats_path()) as f:
            data = json.load(f)
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        return {}


def _day(ts=None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def record(n: int = 1):
    """Count `n` reverted blocks against today (UTC), prune beyond retention, persist atomically."""
    with _lock:
        data = _load()
        today = _day()
        data[today] = data.get(today, 0) + int(n)
        for k in sorted(data)[:-_RETENTION_DAYS]:
            del data[k]
        path = _stats_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)


def daily_counts(days: int = 30) -> list:
    """The last `days` UTC days as a DENSE, oldest-first [{date, count}] series ending today.
    Zero-filled on purpose: a day with no rollbacks is a real, chartable zero (a calm day), not a
    gap — sparse output would make every chart consumer re-derive the calendar."""
    days = max(1, int(days))
    data = _load()
    now = int(time.time())
    return [{"date": _day(now - i * 86400), "count": data.get(_day(now - i * 86400), 0)}
            for i in range(days - 1, -1, -1)]
