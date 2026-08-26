#!/usr/bin/env python3
"""dex_price_sampler.py — SHARED price history for the DEX chart (doc/dex-bridge.md).

The chart used to be per-browser: history lived in each visitor's localStorage, so a first-time visitor
saw an empty chart no matter how long the market had been trading. This samples the AMM's pool reserves
from the exec node and publishes them as a small JSON file the page fetches, so EVERY visitor sees the
same real history immediately. Same shape as the /stats sampler: node-local JSON, pull-only, capped ring,
never back-filled — a gap in the file is an honest gap, not an invented price.

Run (detached):  HOME=/srv/nado-home python3 scripts/dex_price_sampler.py &
"""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "static", "market", "prices.json")
EX = os.environ.get("NADO_EXEC_URL", "http://127.0.0.1:9273").rstrip("/")
CID = "7e97163299583191d40d8676f43d5cfe"          # the AMM
OTC = "6bb0bd0d5dad478bb33d254e73cde85d"          # the cross-chain order book
EVERY = 30                      # seconds between samples
KEEP = 2880                     # ~24h at 30s

def load():
    try:
        with open(OUT) as f: return json.load(f)
    except Exception: return {"pools": {}}

def _sto(cid):
    with urllib.request.urlopen(f"{EX}/exec/contract?ns=default&cid={cid}&provisional=1", timeout=10) as r:
        return json.loads(r.read().decode()).get("storage") or {}

def sample():
    """{seriesKey: price}. AMM pools key on the pool id; a cross-chain market keys on 'x:<network>' and
    prices as NADO per 1 foreign coin, taken as the mid of the live order book (best bid/ask). A market
    with only one side quoted uses that side — an honest one-sided price beats no price."""
    out = {}
    sto = _sto(CID)
    rn, rt = sto.get("rn") or {}, sto.get("rt") or {}
    for pid, n in rn.items():
        n, t = int(n or 0), int(rt.get(pid) or 0)
        if n > 0 and t > 0: out[pid] = t / n
    try:
        o = _sto(OTC)
        mk, kind, st, wch = o.get("mk") or {}, o.get("kind") or {}, o.get("st") or {}, o.get("wch") or {}
        namt, wamt = o.get("namt") or {}, o.get("wamt") or {}
        books = {}
        for oid in mk:
            if int(st.get(oid) or 0) != 1:            # OPEN orders only
                continue
            net = wch.get(oid)
            if not isinstance(net, str):
                continue
            try:
                n = int(namt.get(oid) or 0) / 1e10    # NADO
                f = float(wamt.get(oid) or 0)         # foreign coin
            except (TypeError, ValueError):
                continue
            if n <= 0 or f <= 0:
                continue
            b = books.setdefault(net, {"bid": [], "ask": []})
            # ASK_NADO (1) = maker pays NADO for the coin -> a BID for the coin; BID_NADO (2) = the ask.
            b["bid" if int(kind.get(oid) or 0) == 1 else "ask"].append(n / f)
        for net, b in books.items():
            bb = max(b["bid"]) if b["bid"] else None
            ba = min(b["ask"]) if b["ask"] else None
            mid = (bb + ba) / 2 if (bb and ba) else (bb or ba)
            if mid: out["x:" + net] = mid
    except Exception:
        pass                                          # the book is optional — never lose the AMM samples
    return out

def main():
    print(f"[dex-sampler] -> {OUT} every {EVERY}s", flush=True)
    while True:
        try:
            doc, now = load(), int(time.time())
            prices = sample()
            for pid, price in prices.items():
                arr = doc["pools"].setdefault(pid, [])
                if not arr or abs(arr[-1][1] - price) > 1e-12 or now - arr[-1][0] >= 300:
                    arr.append([now, round(price, 10)])
                    del arr[:-KEEP]
            doc["ts"] = now
            tmp = OUT + ".tmp"
            with open(tmp, "w") as f: json.dump(doc, f, separators=(",", ":"))
            os.replace(tmp, OUT)                    # atomic: a reader never sees a half-written file
        except Exception as e:
            print(f"[dex-sampler] {e}", flush=True)
        time.sleep(EVERY)

if __name__ == "__main__":
    main()
