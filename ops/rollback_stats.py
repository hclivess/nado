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

_RETENTION_DAYS = 400                    # keep over a year of history; the chart reads a window of it
# First UTC day this node was observing. Days BEFORE it are genuinely "not measured" (the node did not
# exist / was not running) and must serve null, not a zero — otherwise a fresh node's empty history reads
# as "30 clean days" and the Stats panel asserts consensus health for days it never saw. Days at/after it
# with no record ARE real zeros (the node was up and nothing happened). Non-date key so the day-map
# iteration can skip it.
_SINCE_KEY = "__since__"
# CHAIN-SCOPED (2026-08-25): this file deliberately survives the genesis-reroll purge (it sits at the node-home
# top level, on the purge allowlist) — and so, after the betanet-5 reroll, the Stats panel showed July's reorgs
# and emergency entries as if they belonged to a chain that was two hours old. Reorg history is only meaningful
# within one genesis lineage. Same discipline as daily_stats/treasury_history: stamp CHAIN_ID/CHAIN_GENERATION and
# drop everything when it differs. A file WITHOUT a stamp is dropped too — the stamp shipped after the gen-23
# reroll, so every unstamped file on every node is the previous chain's history.
_CHAIN_KEY = "__chain__"
_MARKERS = (_SINCE_KEY, _CHAIN_KEY)


def _chain_stamp() -> str:
    try:
        from protocol import CHAIN_ID, CHAIN_GENERATION
        return f"{CHAIN_ID}/{CHAIN_GENERATION}"
    except Exception:
        return "?"


def _raw() -> dict:
    """The file as written, or {} — and {} (a foreign lineage) when its chain stamp is absent or differs."""
    try:
        with open(_stats_path()) as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get(_CHAIN_KEY) != _chain_stamp():
            return {}
        return data
    except Exception:
        return {}


def _stats_path():
    return f"{get_home()}/rollback_stats.json"


_lock = threading.Lock()


def _load() -> dict:
    """The persisted {day: {"c": count, "d": max_depth}} map; a missing or corrupt file is an EMPTY
    history, never an error (a telemetry file must not be able to wedge the node that writes it).
    Legacy days stored as a bare int (count only, before depth tracking) load as d=None ("not
    measured") so the record survives the format change without inventing a depth it never saw."""
    try:
        data = _raw()
        out = {}
        for k, v in data.items():
            if k in _MARKERS:
                continue                       # observation / chain markers, not day records
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


def _read_since() -> str:
    """The first UTC day this node observed, or the earliest day it has a record for (best available
    evidence on a file written before the marker existed), or None if we simply cannot tell."""
    try:
        data = _raw()
        s = data.get(_SINCE_KEY)
        if isinstance(s, str) and s:
            return s
        days = [k for k in data if k not in _MARKERS]
        return min(days) if days else None
    except Exception:
        return None


def note_observing():
    """Stamp the first-observation day if absent. Called once at node startup so a node that runs
    perfectly CLEANLY (never triggering a reorg/reject/emergency write) still establishes when its
    zero-days become meaningful — without this, absence of records is ambiguous forever."""
    try:
        with _lock:
            data = _raw()                     # {} for a foreign/unstamped lineage: that history is dropped here
            if data.get(_SINCE_KEY):
                return
            if not data and os.path.exists(_stats_path()):
                try:
                    with open(_stats_path()) as f:
                        _old = json.load(f)
                    if isinstance(_old, dict) and _old.get(_CHAIN_KEY) == _chain_stamp():
                        return                # same chain, file just did not parse into days — do NOT overwrite
                except Exception:
                    return                    # file exists but did not parse — do NOT overwrite real history
            # Prefer the earliest day we actually have a record for: stamping today on a node with months of
            # telemetry would null every previously-observed CALM day, over-correcting into the opposite error.
            days = [k for k in data if k not in _MARKERS]
            data[_SINCE_KEY] = (min(days) if days else _day())
            data[_CHAIN_KEY] = _chain_stamp()
            path = _stats_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
    except Exception:
        pass


def _persist(mutate):
    """Load today's record, apply `mutate(rec)` in place, prune beyond retention, write atomically.
    Shared by record()/record_reject()/record_emergency() so all three counters follow ONE contract
    (a telemetry write must NEVER be able to wedge the node — every caller wraps this and drops errors)."""
    with _lock:
        data = _load()
        today = _day()
        rec = data.get(today) or {"c": 0, "d": 0, "r": 0, "e": 0}
        for f in ("c", "d", "r", "e"):
            if rec.get(f) is None:             # a field a legacy today-record lacks — _load stamps it None
                rec[f] = 0                     # ("not measured"). But we ARE measuring today now, so it is a
                                               # true 0, not null (setdefault would leave an existing None).
                                               # Only today's record is touched; past days keep their nulls.
        mutate(rec)
        data[today] = rec
        for k in sorted(data)[:-_RETENTION_DAYS]:
            del data[k]
        # PRESERVE the observation marker: _load() strips it, so writing that dict back would erase it on
        # the very first record — and then absence of a record would be ambiguous again. Re-attach after
        # pruning (it is not a day, so it must never be pruned as one).
        since = _read_since() or _day()
        data = dict(data)
        data[_SINCE_KEY] = since
        data[_CHAIN_KEY] = _chain_stamp()
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
    fingerprint of a state fork (the betanet-8 wedge); a healthy fleet trends flat/zero."""
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
    since = _read_since()
    now = int(time.time())
    out = []
    for i in range(days - 1, -1, -1):
        day = _day(now - i * 86400)
        rec = data.get(day)
        if rec is not None:
            # a stored record: its own values (depth/rejects/emergencies may be null on records that
            # predate those fields — "not measured", not a fake 0)
            out.append({"date": day, "count": rec["c"], "depth": rec["d"],
                        "rejects": rec.get("r"), "emergencies": rec.get("e")})
        elif since is not None and day < since:
            # BEFORE this node was observing: null everything. Zero-filling here is what made a fresh
            # node's empty history read as "30 clean days" and let the Stats panel assert consensus
            # health for days it never saw. Absence of evidence is not evidence of a calm day.
            out.append({"date": day, "count": None, "depth": None,
                        "rejects": None, "emergencies": None})
        else:
            # the node WAS observing and recorded nothing — a real, chartable calm zero
            out.append({"date": day, "count": 0, "depth": 0, "rejects": 0, "emergencies": 0})
    return out
