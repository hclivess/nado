"""
A Land title on the market reads like a realtor's ad (#125, "the land plot should have a screenshot attached like in a
realtor ad, also plot size etc", operator 2026-11-07):

  1. the plot's facts are the PLANET's: the world server's card (land_terrain.mjs card) states the commonest biome, the
     ground above the sea, the columns under it, the trees and the flax exactly as static/land-world.js generates them
     (counted again here, column by column), with the plot's size, place, distance to the town hall, what is built on
     it, and the title the chain holds for it;
  2. /land/api/card and /land/api/shot answer any origin (the NFT market is another site); a card without a photo
     queues the plot for one, and the photo is served as a JPEG once taken;
  3. the photographer takes asked-for plots first, then every title without a current photo; a photo is retaken only
     once its plot has changed AND it is SHOT_STALE old; a failed or empty capture never replaces a photo;
  4. the page's photo mode (?shot=<plot>) hides the page, frames the plot from off its corner at its noon, draws nothing
     until the world has settled, and then titles itself "shot-ready" for scripts/land_shot.mjs (which prefers
     $LAND_SHOT_BROWSER, then Brave, then Chrome);
  5. the NFT market shows a Land title's photo and facts ONLY when the world server names THAT asset as that plot's
     title — a copy minted with the same uri borrows neither and is called out — in 17 languages.

Run: python3 tests/test_a_land_title_is_listed_with_its_aerial_photo_and_the_planets_own_facts_and_a_copy_borrows_neither.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-listing-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web, ClientSession
from aiohttp.test_utils import TestServer
from execnode.games import land as L
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check

HALL = S.TOWN_HALL_PLOT
FLAXY = (0 * L.FACE_N + 4998) * L.FACE_N + 3435
OWNER = "ndoLSTO" + "O" * 41
TITLES = {HALL: "880001", FLAXY: "880002"}

# 1. the planet's own count, column by column, in the page's module
js = """
const W = await import(%s);
const out = {};
for (const p of %s) {
  const q = W.plotCoords(p), b = {}; let lo = 1e9, hi = -1e9, sum = 0, under = 0, trees = 0, flax = 0;
  for (let du = 0; du < 16; du++) for (let dv = 0; dv < 16; dv++) {
    const c = W.column(q.face, q.u0 + du, q.v0 + dv), e = c.top - W.SEA;
    b[c.biome] = (b[c.biome] || 0) + 1; lo = Math.min(lo, e); hi = Math.max(hi, e); sum += e; if (c.top < W.SEA) under++;
    { const t = W.treeAt(q.face, q.u0 + du, q.v0 + dv, c); if (t && W.TREE_WOOD.has(W.treeCell(t, 0, 0, 1))) trees++; }   // a bush is no tree
    if (W.litterAt(q.face, q.u0 + du, q.v0 + dv, c) === W.B.flax) flax++;
  }
  out[p] = { b, lo, hi, mean: Math.round(sum / 256), under, trees, flax };
}
console.log(JSON.stringify(out));
""" % (json.dumps(os.path.join(ROOT, "static", "land-world.js")), json.dumps([HALL, FLAXY]))
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=300)
GEN = {int(k): v for k, v in json.loads(r.stdout.strip().splitlines()[-1]).items()}


async def main():
    async def assets(req):
        return web.json_response({"assets": [{"id": a, "issuer": L.ISSUER, "seed": str(L.plot_seed(p)), "name": "Land plot", "sym": "PLOT"}
                                             for p, a in TITLES.items()]})

    async def asset(req):
        return web.json_response({"holders": {OWNER if req.query["id"] == TITLES[FLAXY] else L.ISSUER: "1"}})
    ex = web.Application(); ex.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset)])
    exs = TestServer(ex); await exs.start_server()
    data = os.path.join(os.environ["HOME"], "land")
    world = S.World(data, f"http://127.0.0.1:{exs.port}", "e" * 32)
    app = S.make_app(world, S.Hub(), "http://land.test", "http://wallet.test", secure_cookies=False)
    srv = TestServer(app); await srv.start_server()
    base = f"http://127.0.0.1:{srv.port}"
    try:
        async with ClientSession() as c:
            got = {}
            for p in (HALL, FLAXY):
                rr = await c.get(f"{base}/land/api/card?plot={p}", headers={"Origin": "https://get.nadochain.com"})
                got[p] = (rr.headers.get("Access-Control-Allow-Origin"), await rr.json())
            g, card = GEN[FLAXY], got[FLAXY][1]
            check("a card states the plot's size: 16 × 16 m, 256 m²", card["size_m"] == 16 and card["area_m2"] == 256, card)
            check("…its place: planet, face, row and column", (card["planet"], card["face"], card["row"], card["col"]) == (0, 0, 4998, 3435), card)
            check("…the commonest biome, the ground above the sea and the columns under it, as the planet generates them",
                  card["biome"] == max(g["b"], key=g["b"].get) and (card["low"], card["high"], card["mean"], card["under_sea"]) == (g["lo"], g["hi"], g["mean"], g["under"]), (card, g))
            check(f"…its trees and its flax, counted column by column ({g['trees']} trees, {g['flax']} flax)",
                  card["trees"] == g["trees"] and card["flax"] == g["flax"] and (g["trees"] or g["flax"]), (card, g))
            check("…the town hall's distance: none on its own plot, 16 m a plot away, straight-line in plots",
                  got[HALL][1]["town_hall_m"] == 0 and card["town_hall_m"] == round(((5000 - 4998) ** 2 + (3440 - 3435) ** 2) ** 0.5 * 16), card["town_hall_m"])
            check("…and the title the chain holds for it, with its holder", card["aid"] == TITLES[FLAXY] and card["holder"] == OWNER
                  and got[HALL][1]["aid"] == TITLES[HALL], card)
            # 2
            check("the card answers any origin (the market is another site)", got[FLAXY][0] == "*", got[FLAXY][0])
            check("a card without a photo has none and queues the plot for one", card["shot"] is None and FLAXY in world.shot_want and HALL in world.shot_want)
            rr = await c.get(f"{base}/land/api/shot?plot={FLAXY}")
            check("…whose photo is not served before it is taken", rr.status == 404)
            # 3. the photographer's order and staleness
            check("asked-for plots are photographed first", world.next_shot() == HALL)
            world.shot_want.clear()
            world._write(os.path.join("shots", f"{HALL}.json"), {"ver": 0, "at": int(time.time())})
            check("…then every title without a photo", world.next_shot() == FLAXY)
            jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 4000
            open(os.path.join(world.shots, f"{FLAXY}.jpg"), "wb").write(jpg)
            world._write(os.path.join("shots", f"{FLAXY}.json"), {"ver": 0, "at": int(time.time())})
            check("…and none once each has a current photo", world.next_shot() is None)
            rr = await c.get(f"{base}/land/api/shot?plot={FLAXY}")
            check("a taken photo is served as a JPEG to any origin", rr.status == 200 and rr.headers["Content-Type"] == "image/jpeg"
                  and rr.headers.get("Access-Control-Allow-Origin") == "*" and await rr.read() == jpg)
            card = await (await c.get(f"{base}/land/api/card?plot={FLAXY}")).json()
            check("…and the card names it, stamped with when it was taken", card["shot"] == f"/land/api/shot?plot={FLAXY}&v={card['shot_at']}")
            world.plot(FLAXY)["ver"] = 3
            check("a changed plot keeps a photo younger than SHOT_STALE", not world.shot_due(FLAXY))
            check("…and is retaken once the photo is SHOT_STALE old", world.shot_due(FLAXY, time.time() + S.SHOT_STALE + 1))
            check("an unchanged plot is not retaken within the day", not world.shot_due(HALL, time.time() + 10 * S.SHOT_STALE))
            check("…and every title's photo is retaken once a day, changed or not", world.shot_due(HALL, time.time() + S.SHOT_DAILY + 1))
            world._write(os.path.join("shots", f"{HALL}.json"), {"ver": 0, "at": int(time.time()) - S.SHOT_DAILY - 50})
            world._write(os.path.join("shots", f"{FLAXY}.json"), {"ver": 3, "at": int(time.time()) - S.SHOT_DAILY - 10})
            check("…the oldest photo first", world.next_shot() == HALL)
            # a capture that fails or writes nothing never replaces the photo: shoot() through a page nothing serves
            S.SHOT_TIMEOUT = 60
            S.SHOT_TMP = tempfile.mkdtemp(prefix="nado-test-shot-tmp-")
            ok = await world.shoot(FLAXY, "http://127.0.0.1:1")
            # the capture's browser profile is gone after it, whatever happened (60 were left in /tmp in a day, 2026-11-08)
            left = os.listdir(S.SHOT_TMP)
            check("a capture leaves no browser profile behind", left == [], left)
            shutil.rmtree(S.SHOT_TMP, ignore_errors=True)
            check("a failed capture never replaces a photo", ok is False and open(os.path.join(world.shots, f"{FLAXY}.jpg"), "rb").read() == jpg
                  and not os.path.exists(os.path.join(world.shots, f".{FLAXY}.jpg")))
            rr = await c.get(f"{base}/land/api/card?plot=x")
            check("a malformed plot is refused", rr.status == 400)
    finally:
        await srv.close(); await exs.close()


asyncio.run(main())

# 4. photo mode and the capture script
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
html = open(os.path.join(ROOT, "static", "land.html"), encoding="utf-8").read()
shot = open(os.path.join(ROOT, "scripts", "land_shot.mjs"), encoding="utf-8").read()
check("photo mode hides everything but the world", "body.shot > :not(#world){display:none!important}" in html and 'document.body.classList.add("shot")' in page)
check("…frames the plot from off its south-west corner and sets the clock to the plot's noon",
      "P.u = q.u0 - 7; P.v = q.v0 - 11; P.h = top + 16;" in page and "Date.now = () => real() + off;" in page and "Cosmos.sunFrom(Wd.PLANET, t - Cosmos.EPOCH)" in page)
check("…draws nothing until the world has settled, then says shot-ready",
      "if (shotTick(now)) return;" in page and "if (queue.length || inflight.size || !chunks.size) { shotBusyAt = now; return true; }" in page
      and 'document.title = "shot-ready"' in page and 'ready = title === "shot-ready"' in shot)
check("the capture prefers $LAND_SHOT_BROWSER, then Brave, then Chrome",
      'process.env.LAND_SHOT_BROWSER\n  || ["brave-browser", "brave", "google-chrome", "chromium", "chromium-browser"].find(onPath)' in shot)
srv_src = open(os.path.join(ROOT, "scripts", "land_server.py"), encoding="utf-8").read()
check("a capture leaves no browser behind: its process group is killed on a timeout, its profile removed after it exits",
      "os.killpg(proc.pid, 9)" in srv_src and "start_new_session=True" in srv_src and 'proc.once("exit", r)' in shot and "maxRetries: 10" in shot)
check("the photographer runs one capture at a time, niced", '"nice", "-n", "19", "node"' in srv_src and "await world.shoot(p, shot_page)" in srv_src)

# 5. the market: verified, or nothing borrowed
nft = open(os.path.join(ROOT, "static", "nft.js"), encoding="utf-8").read()
js = """
const src = (await import("node:fs")).readFileSync(%s, "utf8");
const pick = (name) => src.match(new RegExp("const " + name + " = [\\\\s\\\\S]*?\\\\n};"))[0];
const body = pick("landPlotOf") + "\\nreturn landPlotOf;";
const landPlotOf = new Function(body)();
console.log(JSON.stringify([
  landPlotOf({ sym: "PLOT", uri: "https://land.nadochain.com/?plot=40938864" }),
  landPlotOf({ sym: "PLOT", uri: "https://land.nadochain.com.evil.example/?plot=40938864" }),
  landPlotOf({ sym: "NFT", uri: "https://land.nadochain.com/?plot=40938864" }),
  landPlotOf({ sym: "PLOT", uri: "https://land.nadochain.com/?plot=40938864&x=1" }),
]));
""" % json.dumps(os.path.join(ROOT, "static", "nft.js"))
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
check("the market knows a Land title by its symbol and its exact Land uri, nothing looser", out == [40938864, None, None, None], (out, r.stderr[-300:]))
check("…shows its photo and facts only when the world server names THIS asset as that plot's title",
      'landCards[aid] = c && c.plot === p && String(c.aid) === String(aid) ? c : false;' in nft
      and 'return c && c.shot ? `<img class="${cls}" loading="lazy" src="${esc(LAND + c.shot)}" alt="">`' in nft)
check("…and calls out a copy instead", 'if (c === false) return `<p class="small warnline">${T("landFake"' in nft)
check("…on the grid and on the title's own page", nft.count("media(aid, k.uri, ") == 2 and "${landFacts(aid)}" in nft)
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "nft.json"), encoding="utf-8"))
keys = sorted(set(__import__("re").findall(r'T\("((?:land|b)[A-Z]\w*)"', nft)))
check(f"its {len(keys)} strings are in 17 languages, every placeholder kept",
      len(keys) >= 25 and len(tr) == 17 and all(all(l.get("nft." + k) for k in keys) for l in tr.values())
      and all(set(__import__("re").findall(r"\{(\w+)[}|]", l["nft." + k])) == set(__import__("re").findall(r"\{(\w+)[}|]", tr["en"]["nft." + k]))
              for l in tr.values() for k in keys), [k for k in keys if any(not l.get("nft." + k) for l in tr.values())])
_report.done()
