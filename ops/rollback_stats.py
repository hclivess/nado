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
                # r (state-root REJECTS) and e (EMERGENCY-mode entries) shipped after c/d; a record that
                # predates them carries the field absent -> null ("not measured"), same null≠zero rule as d.
                r = v.get("r"); e = v.get("e")
                out[str(k)] = {"c": int(v.get("c", 0)), "d": None if d is None else int(d),
                               "r": None if r is None else int(r), "e": None if e is None else int(e)}
            else:                              # legacy bare-count int: depth/rejects/emergencies never recorded
                out[str(k)] = {"c": int(v), "d": None, "r": None, "e": None}
        return out
    except Exception:
        return {}


def _day(ts=None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _persist(mutate):
    """Load today's record, apply `mutate(rec)` in place, prune beyond retention, write atomically.
    Shared by record()/record_reject()/record_emergency() so all three counters follow ONE contract
    (a telemetry write must NEVER be able to wedge the node — every caller wraps this and drops errors)."""
    with _lock:
        data = _load()
        today = _day()
        rec = data.get(today) or {"c": 0, "d": 0, "r": 0, "e": 0}
        for f in ("c", "d", "r", "e"):
            rec.setdefault(f, 0)               # backfill fields a legacy today-record may lack
        mutate(rec)
        data[today] = rec
        for k in sorted(data)[:-_RETENTION_DAYS]:
            del data[k]
        path = _stats_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)


def record(depth: int = 1):
    """Count ONE reverted block against today (UTC) and raise today's max reorg depth to `depth` —
    the running length of the reorg burst this block belongs to (1 for the tip, 2 for its parent,
    …), so the day's stored depth ends up equal to the deepest single reorg seen that day."""
    d = int(depth)
    def m(rec):
        rec["c"] += 1
        rec["d"] = d if rec["d"] in (None, 0) else max(rec["d"], d)
    _persist(m)


def record_reject():
    """Count ONE state-root gate REFUSAL against today — a block whose committed L1/L2 root did not
    match this node's as-of-parent state (the fatal-divergence signal). A sustained daily spike is the
    fingerprint of a state fork (the alphanet-8 wedge); a healthy fleet trends flat/zero."""
    _persist(lambda rec: rec.__setitem__("r", (rec.get("r") or 0) + 1))


def record_emergency():
    """Count ONE emergency-mode ENTRY against today — the node fell out of consensus and began a
    rollback/resync burst. Pairs with reorg count/depth to separate 'one deep reorg' from 'flapping'."""
    _persist(lambda rec: rec.__setitem__("e", (rec.get("e") or 0) + 1))


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
        # absent day → a real calm 0 for every counter; present record → its stored values (depth/rejects/
        # emergencies may be null for records that predate those fields — "not measured", not a fake 0)
        out.append({"date": day, "count": 0, "depth": 0, "rejects": 0, "emergencies": 0} if rec is None
                   else {"date": day, "count": rec["c"], "depth": rec["d"],
                         "rejects": rec.get("r"), "emergencies": rec.get("e")})
    return out
