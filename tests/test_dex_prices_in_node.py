"""The DEX price history is sampled inside the node, from the contracts the DEX page uses, and restarts on a reroll
(ops/dex_prices.py, nado.py _node_jobs_loop, doc/jobs.md).

The old sampler was a detached script: a reboot killed it and the shared chart froze for two days, and it pasted
betanet-7 contract ids. Pins: the ids come from static/dex.js (the page's own constants, which the redeploy rewires);
a history sampled on another chain is not continued; the fold keeps the old series/volume semantics; the node starts
the loop; and the detached script is gone.

Run: python3 tests/test_dex_prices_in_node.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-dexprices-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys, re, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import dex_prices as D

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


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

src = open(os.path.join(ROOT, "nado.py")).read()
check("the node starts the loop", 'target=_node_jobs_loop' in src and "dex_prices.sample_once" in src)
check("the detached script is gone", not os.path.exists(os.path.join(ROOT, "scripts", "dex_price_sampler.py")))

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
