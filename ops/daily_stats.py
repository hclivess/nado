"""
Node-local DAILY NETWORK TELEMETRY (non-consensus) — sibling of rollback_stats.py, same contract:
one small JSON file at the node-home top level (survives genesis-reroll purges), atomic writes,
UTC days, served dense by GET /daily_stats for the wallet Stats tab's trend charts.

PULL-ONLY by design: a background thread in nado.py calls sample() every few minutes; it reads live
gauges (peers, registry sizes, mempool) and walks the blocks incorporated since the previous sample.
Nothing hooks the consensus path — a telemetry bug can cost a data point, never a block.

Per UTC day the file records:
  txs, blocks   — from the walk, credited to the day of each block's OWN timestamp (so a node that
                  was briefly down backfills the right day when it catches up)
  fees_last     — cumulative_fees of the newest walked block that day (raw units); the chart's
                  fees-per-day is the delta between consecutive OBSERVED days, derived at read time
  peers, open, bonded, mempool — gauge MAXIMA for the day (daily peak, not average: "how big did
                  the network get today" is the operator question, and a max is restart-proof)

Days the sampler never saw are served as null, NOT zero — the chart must show "not measured yet"
(no bar) rather than lie that the network was empty before this feature shipped.
"""
import json
import os
import threading
import time

from ops.data_ops import get_home

_RETENTION_DAYS = 400
SAMPLE_INTERVAL = 300                 # s between sample() calls (nado.py's thread)
_MAX_WALK = 3000                      # blocks one sample may catch up (~5 h) — a node returning from a
                                      # long outage resumes near the tip instead of replaying days
_GAUGES = ("peers", "open", "bonded", "mempool")


def _stats_path():
    return f"{get_home()}/daily_stats.json"


_lock = threading.Lock()


def _load() -> dict:
    """The persisted {"last_height": int, "days": {day: rec}}; missing/corrupt = empty history."""
    try:
        with open(_stats_path()) as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("days"), dict):
            return data
    except Exception:
        pass
    return {"last_height": 0, "days": {}}


def _day(ts=None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _fresh() -> dict:
    return {"txs": 0, "blocks": 0}


def sample(tip_height, load_block, gauges: dict) -> dict:
    """One sampling pass: walk blocks (last_height, tip] crediting txs/fees to each block's own UTC
    day, then fold today's gauge maxima in. `load_block` is height -> block dict or falsy (injected:
    ops.block_ops.get_block_number in production, a stub in tests). The very first pass starts AT the
    tip — the walk exists to stay current, not to replay history. Returns {walked, tip} for the log."""
    with _lock:
        data = _load()
        days = data["days"]
        last = int(data.get("last_height") or 0)
        start = max(last + 1, tip_height - _MAX_WALK + 1) if last else tip_height
        walked = 0
        for h in range(start, tip_height + 1):
            b = load_block(h)
            if not b:
                break                                    # pruned/unindexed — retry from here next pass
            rec = days.setdefault(_day(b.get("block_timestamp")), _fresh())
            rec["txs"] = rec.get("txs", 0) + len(b.get("block_transactions") or [])
            rec["blocks"] = rec.get("blocks", 0) + 1
            rec["fees_last"] = int(b.get("cumulative_fees") or 0)
            data["last_height"] = h
            walked += 1
        today = days.setdefault(_day(), _fresh())
        for k in _GAUGES:
            if gauges.get(k) is not None:
                today[k] = max(int(today.get(k) or 0), int(gauges[k]))
        for k in sorted(days)[:-_RETENTION_DAYS]:
            del days[k]
        path = _stats_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        return {"walked": walked, "tip": tip_height}


def daily_counts(days: int = 30) -> list:
    """The last `days` UTC days, dense oldest-first, ending today. Observed days carry ints (and
    `fees` — that day's burn in raw units AS A STRING: cumulative_fees can exceed 2^53, so the raw
    delta never rides a JS float); unobserved days carry nulls throughout. `fees` is the delta of
    fees_last between consecutive observed days — the first observed day has no baseline, so null."""
    days = max(1, int(days))
    recorded = _load()["days"]
    now = int(time.time())
    prev_fees = None
    # walk oldest->newest so each day's fees baseline is the nearest OBSERVED day before it (also one
    # further back than the window, so the window's first day still gets a delta when history allows)
    for k in sorted(recorded):
        if k < _day(now - (days - 1) * 86400):
            prev_fees = recorded[k].get("fees_last", prev_fees)
    out = []
    for i in range(days - 1, -1, -1):
        d = _day(now - i * 86400)
        rec = recorded.get(d)
        if rec is None:
            out.append({"date": d, "txs": None, "blocks": None, "fees": None,
                        "peers": None, "open": None, "bonded": None, "mempool": None})
            continue
        fl = rec.get("fees_last")
        fees = str(fl - prev_fees) if fl is not None and prev_fees is not None else None
        if fl is not None:
            prev_fees = fl
        out.append({"date": d, "txs": rec.get("txs"), "blocks": rec.get("blocks"), "fees": fees,
                    **{k: rec.get(k) for k in _GAUGES}})
    return out
