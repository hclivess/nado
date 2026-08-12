"""
Durable governance archive — every treasury payout that actually happened, plus who received how much.

WHY THIS EXISTS. The Quorum tab reads `treasury_proposals`, which is a LIVE view, not a record: it drops
expired-never-executed proposals, caps the list at 50, and is a write-only display index deliberately
EXCLUDED from the state root (so a reorg can leave a ghost on one node that a fresh-synced node never
has — two nodes can legitimately disagree about it). None of that is an archive.

The authoritative record is the CHAIN: a `treasury_execute` transaction is in a block forever, and it
carries the whole spend (pid, recipient, amount, memo) plus who executed it. This module walks those
blocks and keeps the result in a node-local JSON, exactly the way ops/daily_stats.py samples telemetry —
pull-only, so NOTHING here touches consensus, the state root, or the apply/revert path. A wrong number
here is a reporting bug, never a fork.

WHAT IT DELIBERATELY DOES NOT DO. It does not persist payout details into the `tspend:<pid>` meta row
that already marks a proposal executed. That row IS in the state root, so widening it would change the
root and demand a genesis reroll — far too much for a reporting feature.

SCOPE LIMIT, ACCEPTED. A snapshot-bootstrapped node has no blocks below its checkpoint, so it can only
archive from that checkpoint forward; `start_height` records where its view actually begins, and the API
returns it so a UI can say "history from block N" instead of implying completeness. An archive node that
has the full chain gets the full history. Rebuilding is always possible — it is derived from blocks.

CHAIN-SCOPED. The file is stamped with CHAIN_ID/CHAIN_GENERATION and dropped when either changes: a
genesis reroll makes the previous chain's payouts meaningless, and mixing them into the new chain's
totals is exactly the bug that had the wallet showing a 7-day mining chart on an hour-old chain.
"""
import json
import os
import threading

from ops.data_ops import get_home

# Blocks one pass may catch up. A node returning from a long outage walks forward over several passes
# instead of blocking the sampler thread for minutes on one giant scan.
_MAX_WALK = 5000
# Hard cap on retained payout records. Treasury payouts are governance-rare (each needs a 2/3 stake
# quorum), so this is a runaway guard, not an expected limit; the oldest are dropped first and
# `truncated` is reported so a UI never silently implies it is showing everything.
_MAX_RECORDS = 5000

_lock = threading.Lock()


def _path():
    return f"{get_home()}/treasury_history.json"


def _chain_stamp() -> str:
    try:
        from protocol import CHAIN_ID, CHAIN_GENERATION
        return f"{CHAIN_ID}/{CHAIN_GENERATION}"
    except Exception:
        return "unknown"


def _fresh() -> dict:
    return {"chain": _chain_stamp(), "cursor": 0, "start_height": None, "payouts": [], "truncated": False}


def _load() -> dict:
    """The persisted archive, or a fresh one when it is missing, corrupt, or from ANOTHER chain."""
    now = _chain_stamp()
    try:
        with open(_path()) as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("payouts"), list) and d.get("chain") == now:
            return d
    except Exception:
        pass
    return _fresh()


def _save(d: dict):
    d["chain"] = _chain_stamp()
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, p)      # atomic: a crash mid-write must never leave a half-file the next load rejects


def _payout_of(tx, height):
    """The payout record for a `treasury_execute` tx, or None if it is not one / is malformed.

    Reads the SIGNED body only (`data.spend`), which is what the node validated and applied — never a
    recomputed guess. A malformed entry is skipped rather than recorded as a zero, because a fabricated
    0-NADO row in the archive is worse than an absent one."""
    if (tx or {}).get("recipient") != "treasury_execute":
        return None
    data = tx.get("data") or {}
    spend = data.get("spend") or {}
    to, amt = spend.get("recipient"), spend.get("amount")
    if not isinstance(to, str) or not isinstance(amt, int) or isinstance(amt, bool) or amt <= 0:
        return None
    return {"pid": str(data.get("pid") or ""), "to": to, "amount": int(amt),
            "height": int(height), "memo": str(spend.get("memo") or "")[:256],
            "by": str(tx.get("sender") or ""), "txid": str(tx.get("txid") or "")}


def scan(tip_height, load_block) -> dict:
    """One incremental pass: walk (cursor, tip] and archive every treasury payout found.

    `load_block` is height -> block dict or falsy (ops.block_ops.get_block_number in production, a stub
    in tests). Returns {walked, found, cursor} for the log. Never raises into the caller's loop."""
    with _lock:
        d = _load()
        last = int(d.get("cursor") or 0)
        # A reroll or deep re-anchor can leave the cursor far ABOVE the live tip; restart at the tip
        # rather than walking a range that no longer exists (the daily_stats reset, same reasoning).
        if last and tip_height < last - _MAX_WALK:
            last = 0
            d = _fresh()
        start = max(last + 1, tip_height - _MAX_WALK + 1) if last else max(1, tip_height - _MAX_WALK + 1)
        walked = found = 0
        for h in range(start, tip_height + 1):
            b = load_block(h)
            if not b:
                continue          # pruned/missing body: skip it, but keep the cursor moving
            if d.get("start_height") is None:
                d["start_height"] = h      # where THIS node's view of the archive actually begins
            for tx in (b.get("transactions") or []):
                rec = _payout_of(tx, h)
                if rec:
                    d["payouts"].append(rec)
                    found += 1
            d["cursor"] = h
            walked += 1
        if len(d["payouts"]) > _MAX_RECORDS:
            d["payouts"] = d["payouts"][-_MAX_RECORDS:]
            d["truncated"] = True
        _save(d)
        return {"walked": walked, "found": found, "cursor": d["cursor"]}


def report(limit: int = 200) -> dict:
    """The archive + the aggregates a governance page needs.

    `payouts` is newest-first and capped by `limit`; `by_recipient` and `total_paid` are computed over
    the WHOLE retained archive, not just the returned page — otherwise the totals would silently change
    as someone paged, which is the kind of number people quote at each other."""
    d = _load()
    payouts = d.get("payouts") or []
    by = {}
    total = 0
    for p in payouts:
        amt = int(p.get("amount") or 0)
        total += amt
        e = by.setdefault(p.get("to") or "", {"total": 0, "count": 0, "last_height": 0})
        e["total"] += amt
        e["count"] += 1
        e["last_height"] = max(e["last_height"], int(p.get("height") or 0))
    ranked = sorted(({"recipient": k, **v} for k, v in by.items()), key=lambda r: -r["total"])
    lim = max(1, min(int(limit or 200), 1000))
    return {
        "chain": d.get("chain"),
        "start_height": d.get("start_height"),      # the archive begins here ON THIS NODE (see SCOPE LIMIT)
        "cursor": d.get("cursor"),
        "truncated": bool(d.get("truncated")),
        "count": len(payouts),
        "total_paid": total,
        "recipients": len(ranked),
        "by_recipient": ranked,
        "payouts": sorted(payouts, key=lambda p: -int(p.get("height") or 0))[:lim],
    }
