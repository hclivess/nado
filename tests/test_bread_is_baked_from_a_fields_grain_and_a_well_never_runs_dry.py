"""
"we will need all the civilisation essentials like berries, hunting, crops, water, wells, mills…" (operator,
2026-11-09; doc/land-civilisation.md, #155). The world server (scripts/land_server.py) over HTTP, as a player would:

  * bread: a quern (stone and sticks, at a workbench) grinds grain into flour; flour and a bucketful of water bake into
    bread at a campfire;
  * eating is a reward, never a need: food is eaten one at a time, berries and bread only; a meal makes breaking take
    food.work of its time while it lasts, berries a little while, bread longer, and meals add up only to max_s;
  * a well, built of cobble, planks and cordage, stands on the ground as a piece; Use on it with a bucket draws a
    bucketful, again and again (it never runs dry); without a bucket it gives nothing; and it is taken down whole.

Run: python3 tests/test_bread_is_baked_from_a_fields_grain_and_a_well_never_runs_dry.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-bread-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys, time

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
A = generate_keydict()
RULES = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
FOOD = RULES["food"]

# an open meadow spot in the commons for the well (two metres of air over turf) and a rock cell to time a break by
js = """
const W = await import(%s);
for (let du = 0; du < 400; du++) {
  const u = 55120 + du, v = 79708, c = W.column(0, u, v);
  if (c.top > W.SEA && W.terrainBlock(0, u, v, c.top) === W.B.grass && W.terrainBlock(0, u, v, c.top + 1) === W.B.air
      && W.terrainBlock(0, u, v, c.top + 2) === W.B.air && W.terrainBlock(0, u + 1, v, c.top + 1) === W.B.air
      && W.column(0, u + 1, v).top === c.top && W.column(0, u, v + 1).top === c.top && W.terrainBlock(0, u, v + 1, c.top + 1) === W.B.air
      && W.terrainBlock(0, u + 1, v + 1, c.top + 1) === W.B.air && W.column(0, u + 1, v + 1).top === c.top && (u %% 16) < 14 && (v %% 16) < 14) {
    let rock = null;
    for (let h = c.top - c.soil - 1; h > 4 && !rock; h--) if (W.terrainBlock(0, u, v, h) === W.B.stone) rock = [0, u, v, h];
    console.log(JSON.stringify({ spot: [0, u, v, c.top], rock })); process.exit(0);
  }
}
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
CELLS = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=120).stdout)


def fake_exec():                                                   # no titles: all of it is the commons
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
    data = tempfile.mkdtemp(prefix="nado_land_bread_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    h = await login(c, A)
    me = A["address"]
    post = lambda path, body: c.post(path, json=body, headers=h)
    async def api(path, body):
        return await (await post(path, body)).json()
    items = lambda: world.inv_json(me)["items"]
    pl = world.player(me)
    pl["stations"] += ["workbench", "campfire"]
    for k, n in (("grain", 7), ("stone", 6), ("sticks", 4), ("water", 1), ("berries", 3), ("cobble", 12), ("planks", 7), ("cordage", 3)):
        pl["items"][k] = n

    # ---- bread ------------------------------------------------------------------------------------------------------
    r = await api("/land/api/craft", {"recipe": "flour"})
    check("no flour without a quern", not r["ok"], r)
    r = await api("/land/api/craft", {"recipe": "quern"})
    check("a quern is made from stone and sticks at a workbench", r["ok"] and "quern" in world.inv_json(me)["stations"], r)
    r = await api("/land/api/craft", {"recipe": "flour", "times": 2})
    check("the quern grinds grain into flour, three to one", r["ok"] and items().get("flour") == 2 and items().get("grain") == 1, r)
    r = await api("/land/api/craft", {"recipe": "bread"})
    check("flour and a bucketful of water bake into bread at the campfire", r["ok"] and items().get("bread") == 2 and not items().get("water"), r)

    # ---- eating -----------------------------------------------------------------------------------------------------
    r = await api("/land/api/eat", {"item": "cobble"})
    check("only food is eaten", not r["ok"] and r["inventory"]["items"].get("cobble") == 12, r)
    rock = CELLS["rock"]
    world.workb.clear()
    hard = RULES["breaking"]["3"]["hard"]
    check("a hungry player has no bonus", S.World.fed_work(pl) == 1)
    r = await api("/land/api/eat", {"item": "bread"})
    fed = r["inventory"]["fed"]
    check("bread is eaten one at a time, and feeds for its time", r["ok"] and r["inventory"]["items"].get("bread") == 1 and abs(fed - FOOD["items"]["bread"]) <= 2, r)
    check("…while it lasts, work takes food.work of its time", S.World.fed_work(pl) == FOOD["work"] < 1)
    r = await api("/land/api/eat", {"item": "berries"})
    check("berries add their own time to the meal", abs(r["inventory"]["fed"] - fed - FOOD["items"]["berries"]) <= 2, r)
    for _ in range(4):
        await api("/land/api/eat", {"item": "bread"}); pl["items"]["bread"] = 1
    check("meals add up only to max_s", world.inv_json(me)["fed"] <= FOOD["max_s"], world.inv_json(me)["fed"])
    # the work bucket is charged less while fed: a break that costs `hard` seconds costs hard * work
    world.workb[me] = [S.WORK_CAP, time.time()]
    pl["tools"].append("pick")
    r = await api("/land/api/set", {"cells": [rock + [0]]})
    spent = S.WORK_CAP - world.workb[me][0]
    check("a fed player's break costs less of their work", r["applied"] == 1 and abs(spent - hard / RULES["tools"]["pick"]["speed"] * FOOD["work"]) < 0.05, (r, spent))
    pl["fed"] = time.time() - 1
    check("…and the meal wears off", world.inv_json(me)["fed"] == 0 and S.World.fed_work(pl) == 1)

    # ---- the well ---------------------------------------------------------------------------------------------------
    r = await api("/land/api/craft", {"recipe": "well"})
    check("a well is made from cobble, planks and cordage at a workbench", r["ok"] and items().get("well") == 1, r)
    f, u, v, top = CELLS["spot"]
    p = S.plot_of(f, u, v)
    fc, fr = p % S.FACE_N, (p // S.FACE_N) % S.FACE_N
    unit = RULES["items"]["well"]["unit"]
    well = [(u - fc * 16) * 100, (v - fr * 16) * 100, (top + 1) * 100, unit[0], unit[1], unit[2], S.WELL]
    r = await api("/land/api/boxes", {"plot": p, "add": [well]})
    check("the well stands on the meadow as a piece", r.get("added") == 1 and well in world.plots[p]["boxes"], r)
    r = await api("/land/api/well", {"plot": p, "box": well})
    check("without a bucket, a well gives nothing", not r["ok"] and "bucket" in r["error"] and not items().get("water"), r)
    pl["tools"].append("bucket")
    for _ in range(5):
        r = await api("/land/api/well", {"plot": p, "box": well})
    check("with a bucket it gives a bucketful, again and again: it never runs dry", r["ok"] and items().get("water") == 5, r)
    r = await api("/land/api/well", {"plot": p, "box": well[:6] + [S.CHEST]})
    check("only a well gives water", not r["ok"], r)
    world.workb.clear()
    r = await api("/land/api/boxes", {"plot": p, "remove": [well]})
    check("a well is taken down whole, back into the bag", r.get("removed") == 1 and items().get("well") == 1, r)

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
