"""
The Land planet's first wave and its town (issues #116 #121 #122 #123; doc/land.md "Decisions", operator 2026-11-06 and
2026-11-07: "set land for sale the first batch, also assign the first patch to the server wallet and build roads+townhall").
What ran on the live chain is scripts/land_first_wave.py and scripts/land_town.py; this pins that they ARE the decision:

  1. the wave is the 100 plots of the landing site (face 0, rows 4995–5004, cols 3435–3444), each title minted to the
     issuer — this server's wallet — with supply 1, never mintable, its seed land.plot_seed;
  2. every title is registered on the NFT market with the 5 % royalty under one collection, and all but the town are
     listed at 5 NADO; the town is the central 2 x 2 plots around the landing, kept by the server wallet;
  3. the Land page names the deployed title contract (not the placeholder), and the world server reads it from there;
     and it decodes a title's plot from the exec API's seed EXACTLY — a ~3.6·10^23 JSON number JSON.parse would round
     (every minted title read as no plot, the town as "Wilderness", until the seeds were parsed exact);
  4. the town builds under the world server's own rules (World.apply / World.boxes — never a write around them), only
     on the town's plots, only after their titles are the server wallet's, with its endowment stated, and it refuses to
     run while the live service holds the world (it would write over the build).

Run: python3 tests/test_the_land_first_wave_is_the_documented_sale_and_the_town_is_the_servers.py
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _harness
_report = _harness.Report()
check = _report.check

wave = open(os.path.join(ROOT, "scripts", "land_first_wave.py"), encoding="utf-8").read()
town = open(os.path.join(ROOT, "scripts", "land_town.py"), encoding="utf-8").read()
doc = open(os.path.join(ROOT, "doc", "land.md"), encoding="utf-8").read()
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()

# 1
check("the wave is the landing site's 100 plots (rows 4995–5004, cols 3435–3444, face 0)",
      "ROWS, COLS = range(4995, 5005), range(3435, 3445)" in wave and "def plot_of(r, c): return (0 * L.FACE_N + r) * L.FACE_N + c" in wave
      and "rows 4995–5004, columns 3435–3444" in doc)
check("…each title minted to the issuer (this server's wallet): supply 1, never mintable, its seed land.plot_seed",
      'assert KD["address"] == L.ISSUER' in wave and '"seed": L.plot_seed(p)' in wave and '"supply": 1' in wave and '"mintable": False' in wave
      and '"dec": 0' in wave)
# 2
check("every title registered with the 5 % royalty, under one collection; listed at 5 NADO",
      "PRICE, ROYALTY_BPS = 5 * NADO, 500" in wave and '"method": "register", "args": [0x504C0000 + i, AID[p], L.plot_seed(p), ROYALTY_BPS, COLL_ID]' in wave
      and "**5 NADO** each" in doc and "**5 %**" in doc)
check("the town — the central 2 x 2 plots — is kept by the server wallet, every other title listed",
      "TOWN = {(r, c) for r in (4999, 5000) for c in (3439, 3440)}" in wave and "if (r, c) not in TOWN and" in wave
      and "ROWS, COLS = (4999, 5000), (3439, 3440)" in town)
check("the wave is idempotent: a minted, registered or listed title is skipped on a rerun",
      "if str(AID[p]) not in have" in wave and "if str(AID[p]) not in reg" in wave and "str(AID[p]) not in lst" in wave)
# 3
m = re.search(r'^const CID = "([0-9a-f]{32})";', page, re.M)
check("the Land page names the deployed title contract, not the placeholder",
      m and m.group(1) != "0000000000000000000000000000000c", m and m.group(1))
srv = open(os.path.join(ROOT, "scripts", "land_server.py"), encoding="utf-8").read()
check("…and the world server reads it from the page", "cid = (src.split('const CID = \"', 1)[1]" in srv)
import json, subprocess
sys.path.insert(0, ROOT)
seed = (0x4C414E44 << 48) | (0 << 32) | 40938864                   # land.plot_seed(40938864): the API's own shape below
body = '{"assets": [{"issuer": "x", "seed": %d, "name": "Land plot", "id": "1"}]}' % seed
js = """
const W = await import(%s);
const src = (await import("node:fs")).readFileSync(%s, "utf8");
const exactSeeds = new Function("return " + src.match(/const exactSeeds = ([^;]+);/)[1])();
const a = exactSeeds(%s).assets[0], naive = JSON.parse(%s).assets[0];
console.log(JSON.stringify({ exact: W.titleOf(a.seed), naive: (() => { try { return W.titleOf(naive.seed); } catch (e) { return String(e).slice(0, 60); } })() }));
""" % (json.dumps(os.path.join(ROOT, "static", "land-world.js")), json.dumps(os.path.join(ROOT, "static", "land.js")), json.dumps(body), json.dumps(body))
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=120)
out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
check("the page decodes a title's plot from the API's seed exactly (a plain JSON.parse does not)",
      out.get("exact") == {"planet": 0, "plot": 40938864} and out.get("naive") != out.get("exact"), (out, r.stderr[-300:]))
check("…for both of its title lists (the issuer's, and the player's own)",
      'await getAssets("/exec/assets?issuer=" + ISSUER)' in page and 'await getAssets("/exec/assets?holder=" + encodeURIComponent(me))' in page)
check("a plot on sale says so — its price and a way to buy it — instead of naming the market that escrows it",
      "if (holder && /^[0-9a-f]{32}$/.test(holder))" in page and 'String(st.l_asset[k]) === String(t.aid) && Number((st.l_left || {})[k]) > 0' in page
      and 'T("forSale", "For sale · {p} NADO"' in page and 'T("buyMarket", "Buy on the market")' in page and "rawToNado, nadoToRaw, randId, $ } from" in page)
# the holder and the sale change together, after the listing is read: set one at a time, a refresh flickered "Owned by
# b0162eda…" (the market contract) with "For sale" on every plot listed for sale (walking the live page, 2026-11-08)
hof = page[page.index("async function holderOf("):page.index("const listingCache")]
check("…and never flickers to naming the market: holder and sale are set together, once the listing is read",
      "t.holder = holder; t.sale = sale;" in hof and hof.index("await listingsOf(holder)") < hof.index("t.holder = holder; t.sale = sale;")
      and "t.holder = Object.keys" not in hof and "t.sale = null" not in hof)
# 4
check("the town builds through the world server's own rules, never around them",
      "await world.apply(WHO, cells[i:i + 2000])" in town and "await world.boxes(WHO, p, bs, [])" in town
      and "rec[\"edits\"]" not in town and "rec[\"boxes\"]" not in town)
check("…only after the town's titles are the server wallet's",
      "if h != WHO and not DRY:" in town and "mint the first wave first" in town)
check("…with its endowment stated, and never while the live service holds the world",
      "ENDOW = {" in town and 'print("endowed the server wallet with", json.dumps(endow))' in town
      and "nado-land is running — stop it first" in town)
_report.done()
