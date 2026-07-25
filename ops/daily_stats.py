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
  peers, open, bonded, mempool, volatility — gauge MAXIMA for the day (daily peak, not average:
                  "how big did the network get / how bad did mempool dissent spike today" is the
                  operator question, and a max is restart-proof)
  up_agree, tip_agree — consensus-agreement FLOOR gauges (daily MINIMUM): the worst upcoming-block
                  and tip agreement seen at sample times — for agreement the LOW is the alarm

Days the sampler never saw are served as null, NOT zero — the chart must show "not measured yet"
(no bar) rather than lie that the network was empty before this feature shipped.
"""
import json
import os
import threading
import time

from ops.data_ops import get_home

_RETENTION_DAYS = 400
SAMPLE_INTERVAL = 60                  # s between sample() calls (nado.py's thread) — a minute keeps the
                                      # per-second consensus gauges' daily min/max honest; the walk is ~10 blocks
_MAX_WALK = 3000                      # blocks one sample may catch up (~5 h) — a node returning from a
                                      # long outage resumes near the tip instead of replaying days
_GAUGES = ("peers", "open", "bonded", "mempool", "volatility")   # daily-peak gauges (max)
_FLOORS = ("up_agree", "tip_agree")                              # daily-low gauges (min)

# Per-day TRANSACTION-TYPE split (the Stats tab's stacked "Transactions per day by type" chart). A tx's
# type is its `recipient`: a plain keyed address = "transfer" (value payment); a reserved protocol name is
# grouped into a few readable buckets so the stacked chart stays legible. Any reserved name not called out
# (exec blob/settle, bridge, shield, dividend, governance, alias, htlc, msg, faucet, slash, …) falls into
# "other". Days sampled before this shipped have no `types` and are served null — split "not measured",
# never a fake zero (same contract as the rest of this file).
_TX_CATEGORIES = ("transfer", "stake", "consensus", "other")
_STAKE_RECIPIENTS = frozenset(("bond", "unbond", "withdraw"))
_CONSENSUS_RECIPIENTS = frozenset(("attest", "commit", "reveal", "duty", "register"))


def _tx_category(tx) -> str:
    from protocol import RESERVED_RECIPIENTS
    r = tx.get("recipient")
    if r not in RESERVED_RECIPIENTS:
        return "transfer"                    # plain value transfer between keyed addresses
    if r in _STAKE_RECIPIENTS:
        return "stake"                       # bond / unbond / withdraw
    if r in _CONSENSUS_RECIPIENTS:
        return "consensus"                   # FFG attest + RANDAO commit/reveal + merged duty + open-lane register
    return "other"                           # exec/L2, bridge, shield, dividend, governance, alias, htlc, msg, …


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


def sample(tip_height, load_block, gauges: dict, floors: dict = None) -> dict:
    """One sampling pass: walk blocks (last_height, tip] crediting txs/fees to each block's own UTC
    day, then fold today's gauge maxima (`gauges`) and consensus-floor minima (`floors`) in.
    `load_block` is height -> block dict or falsy (injected: ops.block_ops.get_block_number in
    production, a stub in tests). The very first pass starts AT the tip — the walk exists to stay
    current, not to replay history. Returns {walked, tip} for the log."""
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
            block_txs = b.get("block_transactions") or []
            rec["txs"] = rec.get("txs", 0) + len(block_txs)
            rec["blocks"] = rec.get("blocks", 0) + 1
            types = rec.setdefault("types", {})              # per-type split (absent on pre-feature days)
            for t in block_txs:
                c = _tx_category(t)
                types[c] = types.get(c, 0) + 1
            rec["fees_last"] = int(b.get("cumulative_fees") or 0)
            data["last_height"] = h
            walked += 1
        today = days.setdefault(_day(), _fresh())
        for k in _GAUGES:
            if gauges.get(k) is not None:
                today[k] = max(int(today.get(k) or 0), int(gauges[k]))
        for k in _FLOORS:
            if (floors or {}).get(k) is not None:
                prev = today.get(k)
                today[k] = int(floors[k]) if prev is None else min(int(prev), int(floors[k]))
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
            out.append({"date": d, "txs": None, "blocks": None, "fees": None, "types": None,
                        **{k: None for k in _GAUGES + _FLOORS}})
            continue
        fl = rec.get("fees_last")
        fees = str(fl - prev_fees) if fl is not None and prev_fees is not None else None
        if fl is not None:
            prev_fees = fl
        # `types` is a dense {category: count} for every bucket (0-filled) on days that carry the split, or
        # null on days sampled before the split shipped (drawn empty, like any unmeasured series).
        rt = rec.get("types")
        types = {c: int(rt.get(c, 0)) for c in _TX_CATEGORIES} if rt is not None else None
        out.append({"date": d, "txs": rec.get("txs"), "blocks": rec.get("blocks"), "fees": fees,
                    "types": types, **{k: rec.get(k) for k in _GAUGES + _FLOORS}})
    return out
