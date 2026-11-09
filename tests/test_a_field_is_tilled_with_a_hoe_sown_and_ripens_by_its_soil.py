"""
"we will need all the civilisation essentials like berries, hunting, crops, water, wells…", "farmland, farming, soil
types, etc" (operator, 2026-11-09; doc/land-civilisation.md, #153, #154). The world server (scripts/land_server.py) over
HTTP against the REAL planet — the server asks scripts/land_terrain.mjs, i.e. static/land-world.js, what each cell holds
and what soil a column has, so a field behaves as the ground really is:

  * foraging: a berry bush picked by hand gives berries; wild grain pulled gives grain and a seed;
  * tilling: only with a hoe (made from sticks, stone and cordage), only turf or earth, never stony ground; the field is
    farmland and stays (a build, not a gathered cell that regrows);
  * sowing: seed goes only on farmland; it ripens after crop_s times its soil's time — clay slower than loam — and
    sooner when water lies near the field;
  * the harvest: ripe wheat on a field gives its soil's grain and seed, more than wild grain.

Run: python3 tests/test_a_field_is_tilled_with_a_hoe_sown_and_ripens_by_its_soil.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-farming-")
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
F = RULES["farming"]

# real cells from the generator, on unowned land near the landing: open turf of each soil, a field cell by the water, a
# berry bush and a stand of wild grain
js = """
const W = await import(%s);
const out = {}, want = (k, c) => { if (!out[k]) out[k] = c; };
const turf = (f, u, v, c) => W.terrainBlock(f, u, v, c.top) === W.B.grass && W.terrainBlock(f, u, v, c.top + 1) === W.B.air;
for (let du = 0; du < 3000 && Object.keys(out).length < 6; du += 1) for (let dv = 0; dv < 40; dv += 1) {
  const f = 0, u = 55100 + du, v = 79700 + dv, c = W.column(f, u, v);
  if (c.top <= W.SEA) continue;
  const lit = W.terrainBlock(f, u, v, c.top + 1);
  if (lit === W.B.berrybush) want("bush", [f, u, v, c.top + 1]);
  if (lit === W.B.wheat) want("wild", [f, u, v, c.top + 1]);
  if (!turf(f, u, v, c)) continue;
  const s = W.soilOf(f, u, v, c);
  // a loam field with turf two columns over at its own layer, where a ditch is dug and a bucketful poured (irrigation)
  const d = W.column(f, u + 2, v);
  if (s === "loam" && out.loam && !out.wet && Math.abs(u - out.loam[1]) > 8 && d.top === c.top && turf(f, u + 2, v, d)) { out.wet = [f, u, v, c.top]; out.ditch = [f, u + 2, v, c.top]; continue; }
  if (s === "loam") want("loam", [f, u, v, c.top]);
  if (s === "clay") want("clay", [f, u, v, c.top]);
}
// stony ground lies on the heights: a coarse search of the face
for (let u = 0; u < W.W && !out.stony; u += 97) for (let v = 0; v < W.W && !out.stony; v += 89) {
  const c = W.column(0, u, v);
  if (W.soilOf(0, u, v, c) === "stony" && W.terrainBlock(0, u, v, c.top) !== W.B.snow && W.terrainBlock(0, u, v, c.top + 1) === W.B.air
      && [W.B.grass, W.B.dirt].includes(W.terrainBlock(0, u, v, c.top))) out.stony = [0, u, v, c.top];
}
console.log(JSON.stringify(out));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
CELLS = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=300).stdout)


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
    data = tempfile.mkdtemp(prefix="nado_land_farm_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    h = await login(c, A)
    me = A["address"]

    async def setc(cells):
        world.workb.clear()                                        # a full work bucket: timing never decides a check
        return await (await c.post("/land/api/set", json={"cells": cells}, headers=h)).json()
    items = lambda: world.inv_json(me)["items"]
    edit = lambda cell: world.plots[S.plot_of(*cell[:3])]["edits"].get((cell[1] % 16, cell[2] % 16, cell[3]))
    above = lambda cell: cell[:3] + [cell[3] + 1]

    check("the generator gives every place this test needs", all(k in CELLS for k in ("bush", "wild", "loam", "clay", "wet", "ditch", "stony")), CELLS)

    # ---- foraging ---------------------------------------------------------------------------------------------------
    r = await setc([CELLS["bush"] + [0]])
    check("a berry bush picked by hand gives berries", r["applied"] == 1 and items().get("berries") == 3, r)
    r = await setc([CELLS["wild"] + [0]])
    check("wild grain pulled by hand gives grain and a seed", r["applied"] == 1 and items().get("grain") == 1 and items().get("seed") == 1, r)

    # ---- tilling ----------------------------------------------------------------------------------------------------
    r = await setc([CELLS["loam"] + [S.FARMLAND]])
    check("no hoe, no field", r["applied"] == 0 and "hoe" in r["refused"][0][1], r)
    pl = world.player(me)
    for k, n in (("sticks", 4), ("stone", 4), ("cordage", 2), ("seed", 3)):
        pl["items"][k] = pl["items"].get(k, 0) + n
    r = await (await c.post("/land/api/craft", json={"recipe": "hoe"}, headers=h)).json()
    check("a stone hoe is made from sticks, stone and cordage", "hoe" in world.inv_json(me)["tools"], r)
    r = await setc([CELLS["stony"] + [S.FARMLAND]])
    check("stony ground cannot be tilled", r["applied"] == 0 and "stony" in r["refused"][0][1], (CELLS["stony"], r))
    # IRRIGATION: a ditch dug beside the wet field and a bucketful poured into it
    pl["items"]["water"] = pl["items"].get("water", 0) + 1
    r = await setc([CELLS["ditch"] + [0]])
    r2 = await setc([CELLS["ditch"] + [S.WATER]])
    check("a ditch is dug beside a field and a bucketful poured into it", r["applied"] == 1 and r2["applied"] == 1, (r, r2))
    r = await setc([CELLS["loam"] + [S.FARMLAND], CELLS["clay"] + [S.FARMLAND], CELLS["wet"] + [S.FARMLAND]])
    check("with a hoe, turf becomes farmland", r["applied"] == 3 and all(edit(CELLS[k]) == S.FARMLAND for k in ("loam", "clay", "wet")), r)
    p = S.plot_of(*CELLS["loam"][:3])
    check("…and a field stays: it is not set to regrow", (CELLS["loam"][1] % 16, CELLS["loam"][2] % 16, CELLS["loam"][3]) not in world.plots[p].get("exp", {}))

    # ---- sowing -----------------------------------------------------------------------------------------------------
    near = CELLS["loam"][:2] + [CELLS["loam"][2] + 1, CELLS["loam"][3] + 1]         # beside the field, on turf
    r = await setc([near + [S.WHEATYOUNG]])
    check("seed is not sown on plain turf", r["applied"] == 0 and "farmland" in r["refused"][0][1], r)
    t0 = time.time()
    r = await setc([above(CELLS[k]) + [S.WHEATYOUNG] for k in ("loam", "clay", "wet")])
    check("seed is sown on farmland, one seed each", r["applied"] == 3 and items().get("seed", 0) == 1, r)
    due = {k: world.plots[S.plot_of(*CELLS[k][:3])]["grow"][(CELLS[k][1] % 16, CELLS[k][2] % 16, CELLS[k][3] + 1)] - t0 for k in ("loam", "clay", "wet")}
    check("loam ripens in its time", abs(due["loam"] - F["crop_s"] * F["soil"]["loam"]["time"]) < 5, due)
    check("clay soil is slower than loam", abs(due["clay"] - F["crop_s"] * F["soil"]["clay"]["time"]) < 5 and due["clay"] > due["loam"], due)
    check("an irrigated field ripens sooner", abs(due["wet"] - F["crop_s"] * F["soil"]["loam"]["time"] * F["moist"]) < 5, due)

    # ---- ripening and the harvest -----------------------------------------------------------------------------------
    back = await world.grow(now=t0 + due["wet"] + 1)
    check("when its time comes the wet field is ripe, the others still growing",
          edit(above(CELLS["wet"])) == S.WHEAT and edit(above(CELLS["loam"])) == S.WHEATYOUNG, back)
    await world.grow(now=t0 + due["clay"] + 1)
    check("…and then all of it", all(edit(above(CELLS[k])) == S.WHEAT for k in ("loam", "clay")))
    g0, s0 = items().get("grain", 0), items().get("seed", 0)
    r = await setc([above(CELLS["loam"]) + [0]])
    sl = F["soil"]["loam"]
    check("a loam harvest gives its soil's grain and seed", r["applied"] == 1 and items().get("grain") == g0 + sl["grain"] and items().get("seed") == s0 + sl["seed"], (r, items()))
    g0 = items().get("grain", 0)
    r = await setc([above(CELLS["clay"]) + [0]])
    check("a clay harvest is richer still", r["applied"] == 1 and items().get("grain") == g0 + F["soil"]["clay"]["grain"], r)
    check("a field gives more than wild grain", sl["grain"] > 1 and sl["seed"] > 1)
    r = await setc([CELLS["loam"][:3] + [CELLS["loam"][3] + 1, S.WHEATYOUNG]])
    check("the field is sown again with the seed it gave", r["applied"] == 1, r)

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
