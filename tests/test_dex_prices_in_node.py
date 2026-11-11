"""The DEX price history is sampled inside the node, from the contracts the DEX page uses, and restarts on a reroll
(ops/dex_prices.py, nado.py _node_jobs_loop, doc/jobs.md).

The old sampler was a detached script: a reboot killed it and the shared chart froze for two days, and it pasted
betanet-7 contract ids. Pins: the ids come from static/dex.js (the page's own constants, which the redeploy rewires);
a history sampled on another chain is not continued; the fold keeps the old series/volume semantics; the node starts
the loop; and the detached script is gone. And (#185) beside the capped samples the sampler keeps hourly candles for the
life of the chain in a file of its own, seeded from the samples on disk, appended only when an hour closes.

Run: python3 tests/test_dex_prices_in_node.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-dexprices-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys, re, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import dex_prices as D

import _harness
_report = _harness.Report()
check = _report.check


js = open(os.path.join(ROOT, "static", "dex.js")).read()
amm, otc = D.contract_ids()
check("the AMM id is the page's own `const CID`", amm == re.search(r'^const CID = "([0-9a-z]+)";', js, re.M).group(1))
check("the order book id is the page's own `const OTC_CID`", otc == re.search(r'^const OTC_CID = "([0-9a-z]+)";', js, re.M).group(1))
check("no contract id is pasted into the sampler", not re.search(r'"[0-9a-f]{32}"', open(D.__file__).read()))

D.OUT = os.path.join(os.environ["HOME"], "prices.json")
json.dump({"chain_id": "betanet-7", "pools": {"1": [[1, 2.0]]}}, open(D.OUT, "w"))
check("a history sampled on another chain is not continued", D.load("betanet-8") == {"chain_id": "betanet-8", "pools": {}})
json.dump({"pools": {"1": [[1, 2.0]]}}, open(D.OUT, "w"))
check("a history with no chain stamp (the old script's) is not continued", D.load("betanet-8")["pools"] == {})
json.dump({"chain_id": "betanet-8", "pools": {"1": [[1, 2.0]]}}, open(D.OUT, "w"))
check("the same chain's history is continued", D.load("betanet-8")["pools"] == {"1": [[1, 2.0]]})

# the very first sample already sees o1 settled (it predates the series): remembered, never booked as volume
doc = D.fold({"chain_id": "c", "pools": {}}, {"1": 2.0}, {"1": 10.0}, {"o1": ("x:eth", 0.3)}, 1000)
doc = D.fold(doc, {"1": 2.5}, {"1": 12.0}, {"o1": ("x:eth", 0.3)}, 1030)
check("a price move is recorded", doc["pools"]["1"] == [[1000, 2.0], [1030, 2.5]])
check("a reserve move with a price move books volume", doc["trades"]["1"] == [[1030, 2.0]])
check("orders already settled at the first sample are not booked as volume", "x:eth" not in doc["trades"])
doc = D.fold(doc, {}, {}, {"o1": ("x:eth", 0.3), "o2": ("x:eth", 0.4)}, 1090)
check("a newly settled order is booked once", doc["trades"]["x:eth"] == [[1090, 0.4]])

# a still market (#185): measured live, 2,879 of ETH's 2,880 samples repeated the price before them — the stored price is
# rounded, the sample was not, so every sample "moved" and one day of a market that never moved filled the cap
still = {"chain_id": "c", "pools": {}}
for k in range(40):                                   # twenty minutes at 30 s, one price with more digits than are stored
    D.fold(still, {"x:eth": 11723.62024466781234}, {}, {}, 5000 + 30 * k)
check("a price that does not move is stored on the 5-minute heartbeat, not at every sample",
      [x[0] for x in still["pools"]["x:eth"]] == [5000, 5300, 5600, 5900] and len({x[1] for x in still["pools"]["x:eth"]}) == 1)
D.fold(still, {"x:eth": 11723.7}, {}, {}, 5000 + 30 * 40)
check("…and a real move is stored at once", still["pools"]["x:eth"][-1] == [6200, 11723.7])
check("so the samples of a still market reach ten days, not one", D.KEEP * 300 >= 10 * 86400)

# ---- the long history (#185, operator 2026-11-11: "last 24 hours is kinda weak"): hourly candles beside the samples ----
H, T0 = D.HOUR, 500 * D.HOUR                           # T0: the top of an hour
samples = [[T0 + 10, 2.0], [T0 + 600, 3.0], [T0 + 1200, 1.5], [T0 + 3000, 2.5], [T0 + H + 5, 4.0], [T0 + 3 * H + 1, 5.0]]
trades = [[T0 + 700, 1.25], [T0 + 800, 0.5], [T0 + 2 * H + 9, 9.0], [T0 + 3 * H + 2, 2.0]]
check("an hour's candle is its first, highest, lowest and last sample, and the NADO traded in it",
      D._candles(samples, trades, 0, T0 + 3 * H) == [[T0, 2.0, 3.0, 1.5, 2.5, 1.75], [T0 + H, 4.0, 4.0, 4.0, 4.0, 0]])
check("an hour with a trade and no quote has no candle (nothing is back-filled)",
      all(c[0] != T0 + 2 * H for c in D._candles(samples, trades, 0, T0 + 9 * H)))

doc = {"chain_id": "c", "pools": {}}
def step(prices, fills, now):
    D.fold(doc, prices, {}, fills, now)
    return D.roll(doc, prices, now)
check("the first sample opens the hour's candle and closes none",
      step({"x:btc": 100.0}, {}, T0 + 30) == [] and doc["open"]["x:btc"] == [T0, 100.0, 100.0, 100.0, 100.0, 0])
step({"x:btc": 120.0}, {}, T0 + 60)
check("a later sample moves the high and the close", doc["open"]["x:btc"] == [T0, 100.0, 120.0, 100.0, 120.0, 0])
step({"x:btc": 90.0}, {"o2": ("x:btc", 0.4)}, T0 + 90)
check("…the low, and a swap settled in the hour is its volume", doc["open"]["x:btc"] == [T0, 100.0, 120.0, 90.0, 90.0, 0.4])
check("the first sample of the next hour closes the candle and opens the next",
      step({"x:btc": 95.0}, {"o2": ("x:btc", 0.4)}, T0 + H + 30) == [("x:btc", [T0, 100.0, 120.0, 90.0, 90.0, 0.4])]
      and doc["open"]["x:btc"] == [T0 + H, 95.0, 95.0, 95.0, 95.0, 0])
check("a market whose quote went away still closes its last hour, and keeps no open candle",
      step({}, {"o2": ("x:btc", 0.4)}, T0 + 2 * H + 30) == [("x:btc", [T0 + H, 95.0, 95.0, 95.0, 95.0, 0])] and "x:btc" not in doc["open"])
step({}, {"o2": ("x:btc", 0.4), "o3": ("x:btc", 1.0)}, T0 + 2 * H + 60)
check("a swap settled while nothing is quoted is drawn at the last price known",
      doc["open"]["x:btc"] == [T0 + 2 * H, 95.0, 95.0, 95.0, 95.0, 1.0])
check("the samples file keeps its own cap: the candle adds one row a market, not a series",
      set(doc) == {"chain_id", "pools", "trades", "last", "settled", "ts", "open"} and all(len(c) == 6 for c in doc["open"].values()))

# the first run after this ships: the samples on disk already hold part of the open hour and days before it
old = {"chain_id": "c", "settled": [], "trades": {"x:eth": [[T0 - H + 9, 2.0], [T0 + 20, 0.5]]},
       "pools": {"x:eth": [[T0 - 2 * H + 5, 5.0], [T0 - H + 5, 6.0], [T0 - H + 900, 6.5], [T0 + 10, 7.0], [T0 + 40, 9.0]]}}
D.fold(old, {"x:eth": 8.0}, {}, {}, T0 + 100)
closed = D.roll(old, {"x:eth": 8.0}, T0 + 100)
check("at the first run the open hour starts from the samples already in it",
      closed == [] and old["open"]["x:eth"] == [T0, 7.0, 9.0, 7.0, 8.0, 0.5])
hist = {"chain_id": "c", "tf": H, "pools": {}}
check("a market the history has not met is seeded from every whole hour the samples hold",
      D.extend(hist, old, closed, T0 + 100) is True
      and hist["pools"]["x:eth"] == [[T0 - 2 * H, 5.0, 5.0, 5.0, 5.0, 0], [T0 - H, 6.0, 6.5, 6.0, 6.5, 2.0]] and hist["ts"] == T0 + 100)
check("…and nothing changes until an hour closes", D.extend(hist, old, [], T0 + 130) is False and hist["ts"] == T0 + 100)
done = [("x:eth", [T0, 7.0, 9.0, 7.0, 8.0, 0.5])]
check("a closed hour is appended", D.extend(hist, old, done, T0 + H + 5) is True and hist["pools"]["x:eth"][-1] == done[0][1] and len(hist["pools"]["x:eth"]) == 3)
check("the same hour is refused a second time (the history was written, the samples were not)",
      D.extend(hist, old, done, T0 + H + 35) is False and len(hist["pools"]["x:eth"]) == 3)
check("an hour before the last is refused: hours only go forward",
      D.extend(hist, old, [("x:eth", [T0 - H, 1.0, 1.0, 1.0, 1.0, 0])], T0 + H + 65) is False and len(hist["pools"]["x:eth"]) == 3)
keep, D.HIST_KEEP = D.HIST_KEEP, 3
D.extend(hist, old, [("x:eth", [T0 + H, 8.0, 8.0, 8.0, 8.0, 0])], T0 + 2 * H + 5)
D.HIST_KEEP = keep
check("the history is bounded: the oldest hour leaves when the cap is reached",
      [c[0] for c in hist["pools"]["x:eth"]] == [T0 - H, T0, T0 + H])
check("the cap is years, not days — the history is for the life of the chain", D.HIST_KEEP >= 5 * 365 * 24)

# the file: its own, restarted on another chain, and written only when an hour closes
D.HIST = os.path.join(os.environ["HOME"], "history.json")
json.dump({"chain_id": "betanet-7", "tf": H, "pools": {"1": [[T0, 1, 1, 1, 1, 0]]}}, open(D.HIST, "w"))
D._hist = None
check("a long history kept on another chain is not continued", D.history("betanet-8") == {"chain_id": "betanet-8", "tf": H, "pools": {}})
json.dump({"chain_id": "betanet-8", "tf": H, "pools": {"1": [[T0, 1, 1, 1, 1, 0]]}}, open(D.HIST, "w"))
D._hist = None
check("the same chain's long history is continued", D.history("betanet-8")["pools"] == {"1": [[T0, 1, 1, 1, 1, 0]]})
check("…and is read from disk once a process", D.history("betanet-8") is D.history("betanet-8"))

import types
clock, quote = [T0 + 15], [{"x:btc": 50.0}]
_time, _ids, _sample = D.time, D.contract_ids, D.sample
D.time = types.SimpleNamespace(time=lambda: clock[0])
D.contract_ids = lambda: ("amm", "otc")
D.sample = lambda amm, otc: (dict(quote[0]), {}, {})
for f in (D.OUT, D.HIST):
    os.remove(f)
D._hist = None
check("a pass samples one series", D.sample_once("c9") == 1)
first = json.load(open(D.HIST))
check("the first pass writes both files — the history with no closed hour yet",
      os.path.exists(D.OUT) and first == {"chain_id": "c9", "tf": H, "pools": {"x:btc": []}, "ts": T0 + 15})
stamp = os.stat(D.HIST).st_mtime_ns
for k in range(1, 100):                               # the rest of the hour, a sample every 30 s, the price moving each time
    clock[0], quote[0] = T0 + 15 + 30 * k, {"x:btc": 50.0 + k}
    D.sample_once("c9")
check("within the hour the long history is not written again", os.stat(D.HIST).st_mtime_ns == stamp)
clock[0], quote[0] = T0 + H + 15, {"x:btc": 10.0}
D.sample_once("c9")
check("the hour's close lands in the history file: open, high, low, close",
      json.load(open(D.HIST))["pools"] == {"x:btc": [[T0, 50.0, 149.0, 50.0, 149.0, 0]]})
D._hist = None                                        # the node restarts: the open candle is in prices.json, the history on disk
for k in range(1, 2 * 24 * 120):                      # two more days at 30 s, the price moving at every sample
    clock[0], quote[0] = T0 + H + 15 + 30 * k, {"x:btc": 10.0 + k % 7}
    D.sample_once("c9")
doc, hist = json.load(open(D.OUT)), json.load(open(D.HIST))
check("the samples keep their cap — a day of a market that moves at every sample", len(doc["pools"]["x:btc"]) == D.KEEP)
check("…while the history keeps every hour since the first (the 24-hour wall this fixes)",
      [c[0] for c in hist["pools"]["x:btc"]] == [T0 + i * H for i in range(48)]
      and hist["pools"]["x:btc"][0][0] < doc["pools"]["x:btc"][0][0] - 86400)
check("…each hour its own candle after a restart too", all(c[2] == 16.0 and c[3] == 10.0 for c in hist["pools"]["x:btc"][2:]))
D.time, D.contract_ids, D.sample = _time, _ids, _sample
check("the history file is not committed: it is this node's own data", "static/market/history.json" in open(os.path.join(ROOT, ".gitignore")).read().split())

src = open(os.path.join(ROOT, "nado.py")).read()
check("the node starts the loop", 'target=_node_jobs_loop' in src and "dex_prices.sample_once" in src)
check("the detached script is gone", not os.path.exists(os.path.join(ROOT, "scripts", "dex_price_sampler.py")))

print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
