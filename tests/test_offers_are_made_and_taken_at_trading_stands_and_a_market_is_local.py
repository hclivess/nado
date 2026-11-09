"""
"trading, global marketplace, no inflationary economy", "local markets first, global only with the invention of the
internet", "trading stands" (operator, 2026-11-09; doc/land-civilisation.md, #161). The world server (scripts/land_server.py)
over HTTP, the players placed where they stand:

  * an offer is made only standing at a trading stand, and lives there;
  * it is seen within market.reach of its stand — at that stand, at another stand of the same market — and not from a
    market across the land; its maker sees it anywhere (to withdraw it);
  * it is taken only standing at a stand of its market: seen from the meadow nearby, but not taken there;
  * the market keeps market.fee of what the maker receives (a sink against inflation);
  * an offer from before the markets (no stand) is withdrawn by its maker and taken by nobody;
  * a gift is handed over in person: beside the other player, not across the land;
  * a stand with open offers on it is not taken down.

Run: python3 tests/test_offers_are_made_and_taken_at_trading_stands_and_a_market_is_local.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-market-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, sys

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
    data = tempfile.mkdtemp(prefix="nado_land_market_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    ha, hb, hc = await login(c, A), await login(c, Bk), await login(c, C)
    a, b, cc = A["address"], Bk["address"], C["address"]
    async def api(path, body, h):
        return await (await c.post(path, json=body, headers=h)).json()
    items = lambda who: world.inv_json(who)["items"]
    def at(who, u, v):
        world.keep_place(who, [FACE, u, v, float(H), 0.0])

    async def build_stand(u, v):
        """A trading stand whose centre is at (u + 1, v + 0.5): a piece on the plot holding (u, v)."""
        p = S.plot_of(FACE, u, v)
        fc, fr = p % S.FACE_N, (p // S.FACE_N) % S.FACE_N
        box = [(u - fc * 16) * 100, (v - fr * 16) * 100, H * 100] + RULES["items"]["stand"]["unit"] + [S.STAND]
        world.player(a)["items"]["stand"] = world.player(a)["items"].get("stand", 0) + 1
        world.workb.clear()
        r = await api("/land/api/boxes", {"plot": p, "add": [box]}, ha)
        return p, box, r

    for who in (a, b, cc):
        world.player(who)["items"].update({"planks": 20, "sand": 100, "cobble": 20})

    # ---- an offer is made at a stand ----------------------------------------------------------------------------------
    at(a, U0 + 1, V0 + 0.5)
    r = await api("/land/api/offer", {"give": {"planks": 4}, "want": {"sand": 40}}, ha)
    check("no stand, no offer", not r["ok"] and "trading stand" in r["error"] and items(a)["planks"] == 20, r)
    pA, standA, r = await build_stand(U0, V0)
    check("a trading stand is built", r.get("added") == 1, r)
    r = await api("/land/api/offer", {"give": {"planks": 4}, "want": {"sand": 40}}, ha)
    oid = r.get("id")
    check("standing at it, an offer is made and lives at that stand", r["ok"] and world.offers[oid]["stand"] == [pA, standA], r)

    # ---- seen in its market, not across the land ----------------------------------------------------------------------
    pB, standB, r = await build_stand(U0 + 40, V0)                 # a second stand of the same market, 40 m off
    pF, standF, r = await build_stand(U0 + 140, V0)                # a stand of another market, 140 m off
    seen = lambda h: c.get("/land/api/offers", headers=h)
    at(b, U0 + 41, V0 + 0.5)
    r = await (await seen(hb)).json()
    check("it is seen at another stand of its market", any(o["id"] == oid for o in r["offers"]), r)
    at(cc, U0 + 141, V0 + 0.5)
    r = await (await seen(hc)).json()
    check("…not at a stand of a market across the land", not any(o["id"] == oid for o in r["offers"]), r)
    r = await api("/land/api/accept", {"id": oid}, hc)
    check("…and not taken from there", not r["ok"] and oid in world.offers, r)
    at(a, U0 + 900, V0)
    r = await (await seen(ha)).json()
    check("its maker sees it anywhere (to withdraw it)", any(o["id"] == oid for o in r["offers"]), r)
    r = await (await c.get("/land/api/offers", params={"face": "0", "u": str(U0 + 1), "v": str(V0)})).json()
    check("anyone sees the offers of a place by naming it", any(o["id"] == oid for o in r["offers"]), r)

    # ---- taken only at a stand of its market --------------------------------------------------------------------------
    at(b, U0 + 20, V0 + 20)                                          # in the market's reach, but at no stand
    r = await api("/land/api/accept", {"id": oid}, hb)
    check("seen from the meadow nearby, but not taken there", not r["ok"] and "trading stand" in r["error"] and oid in world.offers, r)
    at(b, U0 + 41, V0 + 0.5)
    a_sand = items(a).get("sand", 0)
    r = await api("/land/api/accept", {"id": oid}, hb)
    fee = int(40 * MK["fee"])
    check("at a stand of its market it is taken", r["ok"] and items(b)["planks"] == 24 and items(b)["sand"] == 60, r)
    check(f"…and the market keeps its share of what the maker receives ({fee} of 40 sand)", fee > 0 and items(a)["sand"] == a_sand + 40 - fee, items(a))

    # ---- an offer from before the markets -----------------------------------------------------------------------------
    world.player(a)["items"]["cobble"] -= 2
    world.offers["old1"] = {"id": "old1", "by": a, "give": {"cobble": 2}, "want": {"sand": 1}, "at": 1}
    at(b, U0 + 1, V0 + 0.5)
    r = await (await seen(hb)).json()
    check("an offer from before the markets is seen by nobody but its maker", not any(o["id"] == "old1" for o in r["offers"]), r)
    r = await api("/land/api/accept", {"id": "old1"}, hb)
    check("…taken by nobody", not r["ok"] and "old1" in world.offers, r)
    r = await api("/land/api/cancel_offer", {"id": "old1"}, ha)
    check("…and withdrawn by its maker, the escrow back", r["ok"] and items(a)["cobble"] == 20, r)

    # ---- gifts in person ----------------------------------------------------------------------------------------------
    at(a, U0 + 1, V0 + 0.5); at(cc, U0 + 141, V0 + 0.5)
    r = await api("/land/api/give", {"to": cc, "items": {"cobble": 1}}, ha)
    check("a gift is not sent across the land", not r["ok"] and "in person" in r["error"] and items(a)["cobble"] == 20, r)
    at(cc, U0 + 3, V0 + 0.5)
    r = await api("/land/api/give", {"to": cc, "items": {"cobble": 1}}, ha)
    check("…it is handed over beside the other player", r["ok"] and items(cc)["cobble"] == 21, r)

    # ---- a stand with open offers stays up ------------------------------------------------------------------------------
    r = await api("/land/api/offer", {"give": {"cobble": 1}, "want": {"sand": 1}}, ha)
    oid2 = r["id"]
    world.workb.clear()
    r = await api("/land/api/boxes", {"plot": pA, "remove": [standA]}, ha)
    check("a stand with open offers on it is not taken down", r.get("removed", 0) == 0 and standA in world.plots[pA]["boxes"], r)
    await api("/land/api/cancel_offer", {"id": oid2}, ha)
    world.workb.clear()
    r = await api("/land/api/boxes", {"plot": pA, "remove": [standA]}, ha)
    check("…and once they are withdrawn, it is", r.get("removed") == 1, r)

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
