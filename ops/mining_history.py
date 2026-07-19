"""Per-address, per-day mined-reward history — the data behind the wallet's mining chart.

WHY THIS EXISTS: a miner asking "how much am I earning, and is it going up or down?" cannot be answered
from anything the chain already exposes. `account.produced` is a single CUMULATIVE counter (raw NADO the
producer itself earned), so it gives today's grand total and nothing about last Tuesday; and there is no
per-producer block index to walk. The only source of truth is the blocks themselves.

WHAT IT DOES: walks the block store once over a bounded recent window, and thereafter extends only from
the last height it indexed (a handful of new blocks per call at one block per block_time), accumulating
{address: {utc_day: [open_raw, bonded_raw, dividend_raw]}}.

The per-block credit is recomputed with the SAME lane rule and split functions consensus used when the
reward was applied (reward_ops.credit_block_reward), so the block-reward numbers reconcile exactly with
`produced` rather than approximating it. Recomputing also recovers something `produced` throws away: WHICH
LANE each block was won in. Both lanes are kept separate all the way to the client, because a miner
running both needs to see them apart to know which one is actually paying.

The third stream is the PRESENCE DIVIDEND, which is the rest of what a miner earns. It accrues off-L1 into
a running per-address map that keeps no history, so the on-chain `dividend_withdraw` claim is the only
dated record of it — and it is credited here on the day that claim landed, which is the day it became
spendable. That means dividend is "received", while the two lanes are "earned"; they are stacked together
because from the miner's side all three are income, but they are never summed into one opaque bar.

BOUNDED: only KEEP_DAYS of buckets are retained and only ~42 addresses produce on this chain, so the
index is a few KB. It is a display cache, never consensus state — it is rebuilt from blocks on any
reorg and may be discarded at any time.
"""

import threading
import time

from ops.block_ops import epoch_beacon, get_block_number
from ops.mining_ops import epoch_of, lane_of
from ops.kv_ops import hash_by_number
from protocol import split_bonded_block_reward, split_open_block_reward

DAY = 86400
KEEP_DAYS = 30          # buckets retained per address (the wallet asks for 7; the slack costs ~nothing)
SCAN_BUDGET_S = 2.0     # max wall-clock one catch_up call spends scanning before yielding a partial index

_LOCK = threading.Lock()
# upto/anchor: the highest height folded in and its block hash — the hash is what detects a reorg. A reorg
# always replaces a SUFFIX of the chain, so if it touched any height <= upto it necessarily touched upto
# itself; comparing that one hash is therefore a complete check, not a heuristic.
_IDX = {"upto": -1, "anchor": None, "start": None, "days": {}, "gaps": 0, "tip": -1}
_BEACONS = {}           # epoch -> beacon, so a scan doesn't re-read the anchor block once per block


def _reset():
    _IDX.update({"upto": -1, "anchor": None, "start": None, "days": {}, "gaps": 0, "tip": -1})
    _BEACONS.clear()


def _beacon(epoch):
    """epoch_beacon with a memo. epoch_beacon reads the epoch's anchor block, which would otherwise be one
    extra block read per scanned block (EPOCH_LENGTH=60 blocks share a beacon)."""
    b = _BEACONS.get(epoch)
    if b is None:
        b = _BEACONS[epoch] = epoch_beacon(epoch)
    return b


def _credit(block):
    """(address, lane, raw) the producer of `block` was actually credited — mirrors credit_block_reward.
    Returns None when the lane can't be resolved (a missing beacon anchor), so the caller can count the
    block as a gap instead of silently attributing it to the wrong lane."""
    n = block["block_number"]
    try:
        lane = lane_of(n, _beacon(epoch_of(n)))
    except Exception:
        return None
    reward = block["block_reward"]
    cut = (split_open_block_reward(reward)[0] if lane == "open"
           else split_bonded_block_reward(reward)[0])
    return block["block_creator"], lane, cut


def _bucket(addr, day):
    """the [open, bonded, dividend] accumulator for one address on one UTC day"""
    return _IDX["days"].setdefault(addr, {}).setdefault(day, [0, 0, 0])


def _prune(now_ts):
    """drop buckets older than KEEP_DAYS, and addresses left with none"""
    floor = int(now_ts // DAY) - KEEP_DAYS
    for addr in list(_IDX["days"]):
        buckets = _IDX["days"][addr]
        for d in [d for d in buckets if d < floor]:
            del buckets[d]
        if not buckets:
            del _IDX["days"][addr]


def catch_up(tip, block_time=6, days=KEEP_DAYS, budget_s=SCAN_BUDGET_S):
    """Bring the index up to `tip`. SYNCHRONOUS and block-store bound — call it from a thread.

    Returns {"upto", "tip", "building", "gaps", "start"}. `building` is True when the time budget ran out
    before reaching the tip: the index is then a correct but PARTIAL view (it always covers a contiguous
    height range, never a hole), and the next call resumes where this one stopped. On a cold chain the
    whole window is folded in in one call; the budget only matters once the window grows large.
    """
    with _LOCK:
        if tip < _IDX["upto"] or (
            _IDX["upto"] >= 0 and _IDX["anchor"] and hash_by_number(_IDX["upto"]) != _IDX["anchor"]
        ):
            _reset()        # reorg (or a rolled-back node): the cached attribution is no longer the chain

        if _IDX["upto"] < 0:
            # first build: start far enough back to cover `days`, with slack for faster-than-target blocks
            span = int(days * DAY / max(1, block_time) * 1.25) + 600
            _IDX["start"] = max(0, tip - span)
            _IDX["upto"] = _IDX["start"] - 1

        deadline = time.monotonic() + budget_s
        h = _IDX["upto"] + 1
        while h <= tip:
            block = get_block_number(h)
            if not block:
                _IDX["gaps"] += 1       # pruned/unindexed height — never attributed, and reported
            else:
                day = int(block["block_timestamp"] // DAY)
                got = _credit(block)
                if got is None:
                    _IDX["gaps"] += 1   # unresolvable lane: skip the REWARD, still take the block's claims
                else:
                    addr, lane, raw = got
                    _bucket(addr, day)[0 if lane == "open" else 1] += raw
                # presence-dividend collections settled in this block. The dividend accrues off-L1 into a
                # running per-address map with no history, so the claim TX is the only dated record of it —
                # this is income on the day it landed, which is also the day it became spendable.
                for t in block.get("block_transactions") or []:
                    if t.get("recipient") != "dividend_withdraw":
                        continue
                    d = t.get("data")
                    if not isinstance(d, dict):
                        continue
                    who, amt = d.get("addr"), d.get("amount")
                    try:
                        amt = int(amt)
                    except (TypeError, ValueError):
                        continue
                    if who and amt > 0:
                        _bucket(who, day)[2] += amt
            _IDX["upto"] = h
            h += 1
            # check the clock every 256 blocks rather than every block (time.monotonic dominates otherwise)
            if (h & 0xFF) == 0 and time.monotonic() > deadline:
                break

        _IDX["tip"] = tip
        if _IDX["upto"] >= 0:
            _IDX["anchor"] = hash_by_number(_IDX["upto"])
        _prune(time.time())
        return {"upto": _IDX["upto"], "tip": tip, "building": _IDX["upto"] < tip,
                "gaps": _IDX["gaps"], "start": _IDX["start"]}


def state():
    """index progress, for callers that must tell the user the view is still partial"""
    with _LOCK:
        return {"upto": _IDX["upto"], "start": _IDX["start"], "gaps": _IDX["gaps"],
                "building": _IDX["upto"] < _IDX["tip"], "producers": len(_IDX["days"])}


def series(address, days=7, now_ts=None):
    """The last `days` UTC days for `address`, oldest first — one entry per day INCLUDING zero days, so a
    chart can plot a continuous axis without the client inventing the gaps."""
    now_ts = time.time() if now_ts is None else now_ts
    today = int(now_ts // DAY)
    with _LOCK:
        buckets = dict(_IDX["days"].get(address, {}))
        covered_from = _IDX["start"]
    out = []
    for d in range(today - days + 1, today + 1):
        op, bo, dv = buckets.get(d, [0, 0, 0])
        out.append({"day": d, "date": time.strftime("%Y-%m-%d", time.gmtime(d * DAY)),
                    "open": op, "bonded": bo, "dividend": dv, "total": op + bo + dv})
    return out, covered_from
