"""Shared DEX price history (doc/dex-bridge.md), sampled INSIDE the node — served as static/market/prices.json.

The chart used to be per-browser (each visitor's localStorage), so a first-time visitor saw an empty chart. A sampler
now records the AMM's prices and the cross-chain book's mid, and every visitor reads the same history.

WHY THIS LIVES IN THE NODE (2026-09-26): it used to be scripts/dex_price_sampler.py, started by hand with `&`. The
reboot of 2026-09-24 17:34 killed it two minutes after its last write, nothing restarted it, and the chart froze for two
days — while it also still pasted betanet-7 contract ids, so it could not have sampled betanet-8 anyway. The node's
own loop (nado.py _dex_prices_loop) now runs it wherever the node runs. INVARIANTS kept here:
  * the contract ids are READ from static/dex.js (`const CID`, `const OTC_CID`), the constants the DEX page itself
    uses and the redeploy rewires — never pasted, so the chart and the page cannot point at different contracts;
  * the file carries the chain id it was sampled on; a reroll (a different CHAIN_ID) starts a fresh history instead of
    drawing the old chain's prices under the new one;
  * pull-only and failure-isolated: an unreachable exec node (fleet nodes run none) writes nothing and retries.
"""
import json
import os
import re
import time
import urllib.request

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_HERE, "static", "market", "prices.json")
DEX_JS = os.path.join(_HERE, "static", "dex.js")
EX = os.environ.get("NADO_EXEC_URL", "http://127.0.0.1:9273").rstrip("/")
EVERY = 30                      # seconds between samples
KEEP = 2880                     # ~24h at 30s


def contract_ids():
    """(amm_cid, otc_cid) as the DEX page uses them — or (None, None) if dex.js carries none."""
    try:
        src = open(DEX_JS, encoding="utf-8").read()
    except OSError:
        return None, None
    amm = re.search(r'^const CID = "([0-9a-z]+)";', src, re.M)
    otc = re.search(r'^const OTC_CID = "([0-9a-z]+)";', src, re.M)
    return (amm.group(1) if amm else None), (otc.group(1) if otc else None)


def _sto(cid):
    with urllib.request.urlopen(f"{EX}/exec/contract?ns=default&cid={cid}&provisional=1", timeout=10) as r:
        return json.loads(r.read().decode()).get("storage") or {}


def sample(amm, otc):
    """({seriesKey: price}, {pool: NADO reserve}, {settled oid: (key, NADO)}). AMM pools key on the pool id; a
    cross-chain market keys on 'x:<network>' and prices as NADO per 1 foreign coin, the mid of the live book (best
    bid/ask). A market with only one side quoted uses that side — an honest one-sided price beats no price."""
    out, res, fills = {}, {}, {}
    sto = _sto(amm)
    rn, rt = sto.get("rn") or {}, sto.get("rt") or {}
    for pid, n in rn.items():
        n, t = int(n or 0), int(rt.get(pid) or 0)
        if n > 0 and t > 0:
            out[pid] = t / n
            res[pid] = n / 100                        # the NADO reserve, in NADO (a pool unit is 0.01 NADO)
    if otc:
        try:
            o = _sto(otc)
            mk, kind, st, wch = o.get("mk") or {}, o.get("kind") or {}, o.get("st") or {}, o.get("wch") or {}
            namt, wamt = o.get("namt") or {}, o.get("wamt") or {}
            books = {}
            for oid in mk:
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
                if int(st.get(oid) or 0) == 3:            # SETTLED = a completed swap; the volume series counts these
                    fills[oid] = ("x:" + net, n)
                if int(st.get(oid) or 0) != 1:            # the book itself is OPEN orders only
                    continue
                b = books.setdefault(net, {"bid": [], "ask": []})
                # ASK_NADO (1) = maker pays NADO for the coin -> a BID for the coin; BID_NADO (2) = the ask.
                b["bid" if int(kind.get(oid) or 0) == 1 else "ask"].append(n / f)
            for net, b in books.items():
                bb = max(b["bid"]) if b["bid"] else None
                ba = min(b["ask"]) if b["ask"] else None
                mid = (bb + ba) / 2 if (bb and ba) else (bb or ba)
                if mid:
                    out["x:" + net] = mid
        except Exception:
            pass                                      # the book is optional — never lose the AMM samples
    return out, res, fills


def load(chain_id):
    """The history on disk — or a fresh one when it was sampled on another chain (a reroll) or cannot be read."""
    try:
        with open(OUT) as f:
            doc = json.load(f)
        if doc.get("chain_id") == chain_id and isinstance(doc.get("pools"), dict):
            return doc
    except Exception:
        pass
    return {"chain_id": chain_id, "pools": {}}


def fold(doc, prices, res, fills, now):
    """Fold one sample into the history (pure: no I/O, so it is testable).
    VOLUME ("trades"): per market, [ts, NADO turned over]. An AMM pool's NADO reserve moves by exactly the NADO side of
    each swap, and a liquidity add/remove leaves the price unchanged — so a reserve move WITH a price move is trading.
    Sampled every EVERY seconds, so swaps that net out inside one interval are under-counted: an estimate, and the
    page says so. A cross-chain market counts each order the moment it reaches SETTLED, by its NADO amount."""
    trades, last = doc.setdefault("trades", {}), doc.setdefault("last", {})
    for pid, price in prices.items():
        arr = doc["pools"].setdefault(pid, [])
        moved = bool(arr) and abs(arr[-1][1] - price) > 1e-12
        if not arr or moved or now - arr[-1][0] >= 300:
            arr.append([now, round(price, 10)])
            del arr[:-KEEP]
        if pid in res:
            prev = last.get(pid)
            if moved and prev is not None and abs(res[pid] - prev) > 1e-9:
                trades.setdefault(pid, []).append([now, round(abs(res[pid] - prev), 4)])
            last[pid] = res[pid]
    first = "settled" not in doc                      # first run: everything already settled predates this series —
    seen = doc.setdefault("settled", [])              # remember it, do not book it as today's volume
    for oid, (key, n) in fills.items():
        if first:
            seen.append(oid)
            continue
        if oid in seen:
            continue
        seen.append(oid)
        trades.setdefault(key, []).append([now, round(n, 4)])
    del seen[:-5000]
    for k in list(trades):                            # a week of trade events is plenty for a 24h figure
        trades[k] = [t for t in trades[k] if t[0] >= now - 7 * 86400][-KEEP:]
    doc["ts"] = now
    return doc


def sample_once(chain_id):
    """One pass: sample, fold, write atomically. Returns the number of series sampled, or None when the exec node or
    the DEX contracts are unavailable (nothing is written then)."""
    amm, otc = contract_ids()
    if not amm:
        return None
    try:
        prices, res, fills = sample(amm, otc)
    except Exception:
        return None                                   # no exec node here (fleet nodes run none) or it is restarting
    doc = fold(load(chain_id), prices, res, fills, int(time.time()))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    os.replace(tmp, OUT)                              # atomic: a reader never sees a half-written file
    return len(prices)
