"""NODE-LOCAL DEX TRADE INDEX — every swap, liquidity change, launch-curve order and fill and graduation the DEX contract
(execnode/games/dex.py) executed, with the block's time, so the DEX page can draw candles, list recent trades and count
volume, transactions and makers EXACTLY (before this, volume was guessed from 30-s reserve samples: two swaps that netted
out inside a sample were invisible, and launch curves had no price history at all). Served at GET /exec/dex_trades,
/exec/dex_candles and /exec/dex_stats (execnode/execnode.py).

NOT CONSENSUS, AND IT MUST STAY THAT WAY — the asset-history rules (execnode/asset_history.py) apply unchanged: the
capture (DexCallSink) is attached only to the exec node's OWN finalized states through ExecState.call_sink, a class
attribute outside _snapshot()/clone(); it READS the contract's slots before and after a call and never writes; every
failure is swallowed; the rows live in the asset-history sqlite file and share its lifecycle (one transaction per
finalized block, trim on rewind, restart on a gap or a replaced state). tests/test_the_dex_trade_index_… pins it.

EXACT AMOUNTS FROM THE CONTRACT'S OWN STATE. A swap's NADO and coin amounts are the pool's reserve deltas across the call
(the whole input joins the reserve, the 30 bps fee included, so the delta IS what the trader paid and got). A launch
order's fill is computed with the contract's own claim formula — a buyer's coins = amount * BTOUT // BNIN, a seller's
NADO = amount * BNOUT // BTIN — at the block the batch CLEARED (a batch clears lazily, inside whichever buy, sell, settle
or claim touches it first; the capture sees BDONE turn 1). All quantities are in the contract's UNITs (0.01 NADO; 10^8
raw units of the coin). A price is the pool's SPOT after the trade: rn/rt for a pool or a graduated curve, (VN+CN)/CT
for a running curve — in NADO-units per coin-unit."""
import os
import re
import time

# execnode/games/dex.py fields (the per-pool slots are field * 2^32 + pid; batch and order fields likewise)
RN, RT, SUP = 2, 3, 4
KIND, CN, CT, VN, OPEN = 12, 13, 14, 15, 18
BPOOL, BNIN, BTIN, BTOUT, BNOUT, BDONE = 23, 24, 25, 26, 27, 28
OOWN, OBAT, OAMT = 29, 30, 32
CURVE, GRADUATED = 1, 2
_K = 1 << 32

LIMIT_DEFAULT = 200
LIMIT_MAX = 1000
TIMEFRAMES = (60, 300, 900, 3600, 14400, 86400)   # 1m 5m 15m 1h 4h 1d
CANDLES_MAX = 1500

SCHEMA = (
    # one row per trade-like event; nado/tokens in UNITs; pn/pt = the spot after it (see the module note)
    "CREATE TABLE IF NOT EXISTS dex_trades (ns TEXT NOT NULL, cursor INTEGER NOT NULL, seq INTEGER NOT NULL,"
    " ts INTEGER NOT NULL, txid TEXT, cid TEXT NOT NULL, pid INTEGER NOT NULL, kind INTEGER NOT NULL,"
    " side TEXT NOT NULL, trader TEXT, oid INTEGER, nado INTEGER NOT NULL, tokens INTEGER NOT NULL,"
    " pn INTEGER NOT NULL, pt INTEGER NOT NULL, UNIQUE (ns, cursor, seq))",
    "CREATE INDEX IF NOT EXISTS dex_trades_by_pool ON dex_trades (ns, cid, pid, cursor, seq)",
    "CREATE INDEX IF NOT EXISTS dex_trades_by_ts ON dex_trades (ns, cid, ts)",
    # launch orders waiting for their batch to clear (the fill is written then, from these)
    "CREATE TABLE IF NOT EXISTS dex_orders (ns TEXT NOT NULL, cursor INTEGER NOT NULL, cid TEXT NOT NULL,"
    " pid INTEGER NOT NULL, oid INTEGER NOT NULL, batch INTEGER NOT NULL, side TEXT NOT NULL, amt INTEGER NOT NULL,"
    " trader TEXT, UNIQUE (ns, cid, oid))",
    "CREATE INDEX IF NOT EXISTS dex_orders_by_batch ON dex_orders (ns, cid, batch)",
)
TABLES = ("dex_trades", "dex_orders")       # every table keyed by (ns, cursor): trimmed, reset and gap-restarted


def dex_cids(repo=None):
    """The DEX contract ids the page trades on — read from static/dex.js exactly as the node's price sampler does
    (ops/dex_prices.py), so the index and the page can never disagree about which contract is the DEX. Never raises."""
    try:
        repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(repo, "static", "dex.js"), encoding="utf-8").read()
        m = re.search(r'^const CID = "([0-9a-z]+)";', src, re.M)       # the sampler's own pattern (ops/dex_prices.py)
        return {m.group(1)} if m else set()
    except Exception:
        return set()


def _slots(st, cid):
    return ((st.contracts.get(cid) or {}).get("storage") or {}).get("slots") or {}


def _sv(slots, f, k):
    try:
        return int(slots.get(str(f * _K + int(k)), 0))
    except Exception:
        return 0


def _pool(slots, pid):
    return {f: _sv(slots, f, pid) for f in (KIND, RN, RT, SUP, CN, CT, VN, OPEN)}


def _spot(p):
    """(pn, pt): the pool's spot, NADO-units per coin-unit as a ratio of integers."""
    if p[KIND] == CURVE:
        return p[VN] + p[CN], p[CT]
    return p[RN], p[RT]


def _int(a, default=0):
    try:
        return int(a)
    except Exception:
        return default


class DexCallSink:
    """What ExecState.call_sink holds for one finalized namespace. before() and after() are called around every
    `call` blob (state.py _call_capture_*); both READ ONLY and are wrapped there so a failure costs one record."""

    def __init__(self, store, ns, cids):
        self.store, self.ns, self.cids = store, ns, set(cids)

    def before(self, st, p):
        cid = p.get("contract")
        if cid not in self.cids:
            return None
        method, args = p.get("method"), p.get("args") if isinstance(p.get("args"), list) else []
        slots = _slots(st, cid)
        if method in ("swapn", "swapt", "launch", "buy", "sell", "settle"):
            pid = _int(args[0]) if args else 0
            batch = _sv(slots, OPEN, pid)
        elif method in ("join", "exit"):
            pid = _int(args[1]) if len(args) > 1 else 0
            batch = 0
        elif method == "claim":
            batch = _sv(slots, OBAT, _int(args[0]) if args else 0)
            pid = _sv(slots, BPOOL, batch)
        else:
            return None
        if pid <= 0:
            return None
        oid = _int(args[1]) if method in ("buy", "sell") and len(args) > 1 else 0
        return {"cid": cid, "method": method, "pid": pid, "batch": batch, "pool": _pool(slots, pid),
                "bdone": _sv(slots, BDONE, batch) if batch else 1, "oamt": _sv(slots, OAMT, oid) if oid else 0, "oid": oid}

    def after(self, st, p, sender, txid, pre):
        cid, pid, method = pre["cid"], pre["pid"], pre["method"]
        slots = _slots(st, cid)
        a, b = pre["pool"], _pool(slots, pid)
        if a == b and pre["oamt"] == (_sv(slots, OAMT, pre["oid"]) if pre["oid"] else 0):
            return                                          # a revert (or a no-op): nothing moved
        base = {"cursor": st.applying_height(), "txid": str(txid or ""), "cid": cid, "pid": pid, "trader": str(sender or "")}
        recs = []
        pn, pt = _spot(b)
        if method in ("swapn", "swapt") and (a[RN], a[RT]) != (b[RN], b[RT]):
            buy = method == "swapn"
            recs.append(dict(base, t="trade", kind=a[KIND], side="buy" if buy else "sell",
                             nado=abs(b[RN] - a[RN]), tokens=abs(a[RT] - b[RT]), pn=pn, pt=pt))
        elif method in ("join", "exit") and (a[RN], a[RT]) != (b[RN], b[RT]):
            recs.append(dict(base, t="trade", kind=a[KIND], side="add" if method == "join" else "remove",
                             nado=abs(b[RN] - a[RN]), tokens=abs(b[RT] - a[RT]), pn=pn, pt=pt))
        elif method == "launch" and a[KIND] != CURVE and b[KIND] == CURVE:
            recs.append(dict(base, t="trade", kind=CURVE, side="launch", nado=0, tokens=b[CT], pn=pn, pt=pt))
        # a batch that CLEARED in this call (it clears before a new order joins, so it is written first)
        if pre["batch"] and not pre["bdone"] and _sv(slots, BDONE, pre["batch"]):
            bt = pre["batch"]
            recs.append(dict(base, t="clear", batch=bt, bnin=_sv(slots, BNIN, bt), btin=_sv(slots, BTIN, bt),
                             btout=_sv(slots, BTOUT, bt), bnout=_sv(slots, BNOUT, bt), pn=pn, pt=pt,
                             grad=int(a[KIND] == CURVE and b[KIND] == GRADUATED)))
        if method in ("buy", "sell") and pre["oid"] and not pre["oamt"]:
            amt = _sv(slots, OAMT, pre["oid"])
            if amt > 0:
                recs.append(dict(base, t="order", oid=pre["oid"], batch=_sv(slots, OBAT, pre["oid"]),
                                 side="buy" if method == "buy" else "sell", amt=amt))
        if recs:
            self.store.dex_sink(self.ns, recs)


def write_block(db, ns, h, ts, recs):
    """Write block h's DEX records (inside the store's open transaction). A clear becomes one fill row per order of its
    batch, by the contract's claim formula; a graduation follows its batch's fills."""
    seq = 0
    for r in recs:
        if r["t"] == "trade":
            db.execute("INSERT OR REPLACE INTO dex_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (ns, h, seq, ts, r["txid"], r["cid"], r["pid"], r["kind"], r["side"], r["trader"], None,
                        r["nado"], r["tokens"], r["pn"], r["pt"]))
            seq += 1
        elif r["t"] == "order":
            db.execute("INSERT OR REPLACE INTO dex_orders VALUES (?,?,?,?,?,?,?,?,?)",
                       (ns, h, r["cid"], r["pid"], r["oid"], r["batch"], r["side"], r["amt"], r["trader"]))
        elif r["t"] == "clear":
            for oid, side, amt, trader in db.execute(
                    "SELECT oid, side, amt, trader FROM dex_orders WHERE ns=? AND cid=? AND batch=? ORDER BY cursor, oid",
                    (ns, r["cid"], r["batch"])).fetchall():
                if side == "buy":
                    nado, tokens = amt, (amt * r["btout"] // r["bnin"] if r["bnin"] else 0)
                else:
                    nado, tokens = (amt * r["bnout"] // r["btin"] if r["btin"] else 0), amt
                db.execute("INSERT OR REPLACE INTO dex_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (ns, h, seq, ts, r["txid"], r["cid"], r["pid"], CURVE, side, trader, oid, nado, tokens,
                            r["pn"], r["pt"]))
                seq += 1
            if r["grad"]:
                db.execute("INSERT OR REPLACE INTO dex_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (ns, h, seq, ts, r["txid"], r["cid"], r["pid"], GRADUATED, "graduate", r["trader"], None,
                            0, 0, r["pn"], r["pt"]))
                seq += 1


# ---- reads (called by the store under its lock) -------------------------------------------------------------------
_COLS = "cursor, seq, ts, txid, pid, kind, side, trader, oid, nado, tokens, pn, pt"


def _row(r):
    cur, seq, ts, txid, pid, kind, side, trader, oid, nado, tokens, pn, pt = r
    return {"cursor": cur, "seq": seq, "ts": ts, "txid": txid, "pid": pid, "kind": kind, "side": side, "trader": trader,
            "oid": oid, "nado": nado, "tokens": tokens, "pn": pn, "pt": pt}


def trades(db, ns, cid, pid=None, limit=LIMIT_DEFAULT, before=None, trader=None):
    """Newest first. `before` = [cursor, seq] of the last row a page showed. Returns (rows, next_before or None)."""
    limit = max(1, min(int(limit), LIMIT_MAX))
    q, a = f"SELECT {_COLS} FROM dex_trades WHERE ns=? AND cid=?", [ns, cid]
    if pid is not None:
        q += " AND pid=?"; a.append(int(pid))
    if trader:
        q += " AND trader=?"; a.append(str(trader))
    if before:
        q += " AND (cursor<? OR (cursor=? AND seq<?))"; a += [int(before[0]), int(before[0]), int(before[1])]
    rows = [_row(r) for r in db.execute(q + " ORDER BY cursor DESC, seq DESC LIMIT ?", a + [limit]).fetchall()]
    return rows, ([rows[-1]["cursor"], rows[-1]["seq"]] if len(rows) == limit else None)


def candles(db, ns, cid, pid, tf, limit=500):
    """OHLC of the spot after each trade, per `tf`-second bucket, oldest first: [t, open, high, low, close, volume
    (NADO-units), buys, sells]. The open of a bucket is the previous bucket's close (no gaps between candles); a bucket
    with no trade is skipped. Prices are floats in NADO-units per coin-unit (non-consensus, display only)."""
    tf = int(tf) if int(tf) in TIMEFRAMES else 300
    limit = max(1, min(int(limit), CANDLES_MAX))
    since = int(time.time()) - tf * limit
    prev = db.execute("SELECT pn, pt FROM dex_trades WHERE ns=? AND cid=? AND pid=? AND ts<? AND pt>0 "
                      "ORDER BY cursor DESC, seq DESC LIMIT 1", (ns, cid, int(pid), since)).fetchone()
    last = prev[0] / prev[1] if prev else None
    out, cur = [], None
    for ts, side, nado, pn, pt in db.execute(
            "SELECT ts, side, nado, pn, pt FROM dex_trades WHERE ns=? AND cid=? AND pid=? AND ts>=? "
            "ORDER BY cursor, seq", (ns, cid, int(pid), since)).fetchall():
        if not pt:
            continue
        p, t = pn / pt, ts - ts % tf
        if cur is None or cur[0] != t:
            o = last if last is not None else p
            cur = [t, o, max(o, p), min(o, p), p, 0, 0, 0]
            out.append(cur)
        cur[2], cur[3], cur[4] = max(cur[2], p), min(cur[3], p), p
        if side in ("buy", "sell"):
            cur[5] += nado
            cur[6 if side == "buy" else 7] += 1
        last = p
    return out


WINDOWS = (("m5", 300), ("h1", 3600), ("h6", 21600), ("h24", 86400))


def stats(db, ns, cid, now=None):
    """Per pool: {buys, sells, volume (NADO-units), change (spot ratio now / then, per window), makers (24 h), created (ts
    of its first indexed event), last (ts)} — the Dexscreener columns, from the index in one pass."""
    now = int(now if now is not None else time.time())
    out = {}
    for pid, first, last in db.execute("SELECT pid, MIN(ts), MAX(ts) FROM dex_trades WHERE ns=? AND cid=? GROUP BY pid",
                                       (ns, cid)).fetchall():
        out[pid] = {"created": first, "last": last, **{w: {"buys": 0, "sells": 0, "volume": 0, "then": None} for w, _ in WINDOWS},
                    "makers": set()}
    for pid, ts, side, nado, trader in db.execute(
            "SELECT pid, ts, side, nado, trader FROM dex_trades WHERE ns=? AND cid=? AND ts>=? AND side IN ('buy','sell')",
            (ns, cid, now - 86400)).fetchall():
        s = out.get(pid)
        if s is None:
            continue
        s["makers"].add(trader)
        for w, sec in WINDOWS:
            if ts >= now - sec:
                s[w]["buys" if side == "buy" else "sells"] += 1
                s[w]["volume"] += nado
    for pid, s in out.items():
        for w, sec in WINDOWS:
            r = db.execute("SELECT pn, pt FROM dex_trades WHERE ns=? AND cid=? AND pid=? AND ts<? AND pt>0 "
                           "ORDER BY cursor DESC, seq DESC LIMIT 1", (ns, cid, pid, now - sec)).fetchone()
            s[w]["then"] = [r[0], r[1]] if r else None
        s["makers"] = len(s["makers"])
    return out
