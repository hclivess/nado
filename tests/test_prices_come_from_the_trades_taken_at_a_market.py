"""
"we need currencies of all types so we need a flexible value system based on supply and demand" (operator,
2026-11-09; doc/land-civilisation.md 'Currencies and value', #163). The world server (scripts/land_server.py):

  * coins: a mint (stone brick, iron, planks, at an anvil with a hammer) strikes ten coins from a bar of copper, silver
    or gold — coins come only from metal someone mined;
  * every offer taken is a trade on the record, kept across a restart;
  * the going rate of X in Y at a market is the volume-weighted ratio of its trades, a trade weighing half as much every
    half_life_s, none older than window_s;
  * X never traded for Y is priced through what links them;
  * a market's prices are its own: trades at a market across the land do not move them;
  * prices can be asked in any item; a trade of several items on a side names no single price and is left out;
  * GET /land/api/prices gives the values here and a day ago (the board's arrows).

Run: python3 tests/test_prices_come_from_the_trades_taken_at_a_market.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-prices-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from signatures import generate_keydict, sign, unhex
from hashing import blake2b_hash

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
A, Bk, C = generate_keydict(), generate_keydict(), generate_keydict()
RULES = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
MK = RULES["market"]
FACE, U0, V0, H = 0, 55040, 79712, 200                         # unowned land; the stands stand in the air (no terrain needed)


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": []})

    async def asset(req):
        return web.json_response({"asset": {"id": "0"}, "holders": {}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


async def login(c, kd):
    ch = await (await c.get("/land/api/challenge?kind=agent")).json()
    msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, kd["address"], ch["nonce"], ch["issued"]], 32)
    r = await c.post("/land/api/agent_login", json={"address": kd["address"], "public_key": kd["public_key"],
                                                    "signature": sign(kd["private_key"], unhex(msg)), "nonce": ch["nonce"]})
    return {"Authorization": "Bearer " + (await r.json())["token"]}


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_prices_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    ha, hb = await login(c, A), await login(c, Bk)
    a, b = A["address"], Bk["address"]
    async def api(path, body, h):
        return await (await c.post(path, json=body, headers=h)).json()
    items = lambda who: world.inv_json(who)["items"]
    def at(who, u, v):
        world.keep_place(who, [FACE, u, v, float(H), 0.0])

    # ---- coins from a mint --------------------------------------------------------------------------------------------
    pa = world.player(a)
    pa["tools"].append("hammer"); pa["stations"] += ["anvil"]
    pa["items"].update({"stonebrick": 6, "iron": 10, "planks": 4, "copper": 2})
    r = await api("/land/api/craft", {"recipe": "copper_coin"}, ha)
    check("no coins without a mint", not r["ok"], r)
    r = await api("/land/api/craft", {"recipe": "mint"}, ha)
    check("a mint is made of stone brick, iron and planks at an anvil", r["ok"] and "mint" in world.inv_json(a)["stations"], r)
    r = await api("/land/api/craft", {"recipe": "copper_coin", "times": 2}, ha)
    check("it strikes ten coins from a bar of copper — no coin from nothing", r["ok"] and items(a).get("copper_coin") == 20 and not items(a).get("copper"), r)

    # ---- a trade on the record ----------------------------------------------------------------------------------------
    p = S.plot_of(FACE, U0, V0)
    fc, fr = p % S.FACE_N, (p // S.FACE_N) % S.FACE_N
    stand = [(U0 - fc * 16) * 100, (V0 - fr * 16) * 100, H * 100] + RULES["items"]["stand"]["unit"] + [S.STAND]
    pa["items"]["stand"] = 1
    r = await api("/land/api/boxes", {"plot": p, "add": [stand]}, ha)
    check("a trading stand", r.get("added") == 1, r)
    at(a, U0 + 1, V0 + 0.5); at(b, U0 + 1.5, V0 + 0.5)
    world.player(b)["items"]["copper_coin"] = 100
    r = await api("/land/api/offer", {"give": {"iron": 4}, "want": {"copper_coin": 40}}, ha)
    r = await api("/land/api/accept", {"id": r["id"]}, hb)
    check("an offer taken", r["ok"], r)
    t = world.trades[-1]
    check("…is a trade on the record: what for what, where, when", t["give"] == {"iron": 4} and t["want"] == {"copper_coin": 40} and t["spot"][0] == FACE and abs(t["at"] - time.time()) < 5, t)
    px = lambda unit, **k: world.prices([FACE, U0 + 1, V0 + 0.5], unit, **k)["values"]
    check("the going rate is the trade's ratio: iron at 10 copper coins", abs(px("copper_coin")["iron"] - 10) < 1e-6, px("copper_coin"))
    check("…and copper coins at a tenth of an iron, asked in iron", abs(px("iron")["copper_coin"] - 0.1) < 1e-6, px("iron"))

    # ---- supply and demand: recency-weighted volume ----------------------------------------------------------------------
    now = time.time()
    hl = MK["half_life_s"]
    world.trades[-1]["at"] = int(now - hl)                           # the first trade a half-life ago: it weighs one half
    world.trades.append({"at": int(now), "spot": t["spot"], "give": {"iron": 1}, "want": {"copper_coin": 20}})
    v = px("copper_coin", now=now)["iron"]
    check("a new dearer trade moves the price, older trades weighing less", abs(v - (0.5 * 40 + 20) / (0.5 * 4 + 1)) < 0.05, v)
    world.trades.append({"at": int(now - MK["window_s"] - 10), "spot": t["spot"], "give": {"iron": 1}, "want": {"copper_coin": 1000}})
    check("…a trade older than the window counts for nothing", abs(px("copper_coin", now=now)["iron"] - v) < 1e-6)

    # ---- through what links them ----------------------------------------------------------------------------------------
    world.trades.append({"at": int(now), "spot": t["spot"], "give": {"sand": 10}, "want": {"iron": 1}})
    vs = px("copper_coin", now=now)["sand"]
    check("sand never traded for coins is priced through iron", abs(vs - v / 10) < 1e-6, (vs, v))
    world.trades.append({"at": int(now), "spot": t["spot"], "give": {"sand": 1, "cobble": 1}, "want": {"iron": 5}})
    check("a trade of several items on a side names no price", abs(px("copper_coin", now=now)["sand"] - vs) < 1e-6 and "cobble" not in px("copper_coin", now=now))

    # ---- a market's prices are its own ------------------------------------------------------------------------------------
    world.trades.append({"at": int(now), "spot": [FACE, U0 + 500, V0, 0], "give": {"iron": 1}, "want": {"copper_coin": 999}})
    check("a trade at a market across the land does not move this one", abs(px("copper_coin", now=now)["iron"] - v) < 1e-6)
    far = world.prices([FACE, U0 + 500, V0], "copper_coin", now=now)["values"]
    check("…while there iron is priced by its own trade", abs(far["iron"] - 999) < 1e-6, far)

    # ---- the API, and the record kept ------------------------------------------------------------------------------------
    r = await (await c.get("/land/api/prices", params={"face": "0", "u": str(U0 + 1), "v": str(V0), "unit": "copper_coin"})).json()
    check("GET /land/api/prices gives the values here and a day ago", "iron" in r["values"] and "before" in r and r["unit"] == "copper_coin", r)
    r = await c.get("/land/api/prices", params={"face": "0", "u": "1", "v": "1", "unit": "warpcore"})
    check("…in a unit that is an item", r.status == 400)
    world.odirty = True; world.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "")
    check("the record of trades survives a restart", w2.trades == world.trades)

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
