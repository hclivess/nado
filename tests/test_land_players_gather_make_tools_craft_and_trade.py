"""
"You must gather resources to make tools to make tools to collect more resources" (operator, 2026-11-06), and "materials
trading is necessary": the world server's economy (scripts/land_server.py, rules in static/land-recipes.json), driven
over HTTP against the REAL planet — the server asks scripts/land_terrain.mjs, i.e. static/land-world.js, what each cell
holds, so a yield is what the ground really is.

  * by hand: grass gives earth and fiber, leaves give sticks and fiber, a loose stone a stone, a fallen stick two sticks;
    a log and rock cannot be broken by hand;
  * tools: cordage from fiber, a stone axe and pickaxe from sticks, stone and cordage; with the axe a cut trunk fells its
    tree above the cut (wood for every log, sticks from the crown, nothing left floating),
  * a real house: iron ore in veins, charcoal, a bloomery and iron, an anvil and hammer, nails and hinges, a door that
    goes in whole at its size, swings on its hinge and comes back as a door; lime and mortar for masonry; thatch and
    beams; iron tools that outwork stone ones, and any axe for a recipe that needs one,
    with the pickaxe rock gives cobblestone; a tool you already made makes breaking quicker;
  * time: breaking spends seconds of work (hardness over tool speed) — a caller cannot strip the planet faster than a hand;
  * stations: planks need a workbench (which needs an axe), bricks need a kiln (which needs a campfire); a recipe is refused
    until its station and its materials are there;
  * the commons: anyone signed in gathers AND builds on unowned land ("you can build anywhere unless it is owned"); a
    gathered wilderness cell grows back, a built one stays;
  * placing spends one item and only on a plot the caller may build on;
  * trade: a gift moves items; an offer escrows what it gives, is taken atomically (both sides move or neither), and a
    withdrawn offer returns its escrow; nobody can offer what they lack or take their own offer;
  * persistence: inventories, offers and regrow times survive a restart.

Run: python3 tests/test_land_players_gather_make_tools_craft_and_trade.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-economy-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from signatures import generate_keydict, sign, unhex
from hashing import blake2b_hash
from execnode.games import land as L

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check

A, Bk = generate_keydict(), generate_keydict()
ROW, COL = 4995, 3435                                              # static/land-world.js SPAWN_PLOT_ROW/COL
PA = ROW * L.FACE_N + COL                                          # A's titled plot (face 0)

# real cells from the generator: a wilderness tree (log + leaves), a grass top and the rock under it, near the landing
js = """
const W = await import(%s);
const q = W.plotCoords(%d); let out = null;
for (let du = 32; du < 600 && !out; du++) for (let dv = 0; dv < 16 && !out; dv++) {
  const u = q.u0 + du, v = q.v0 + dv, c = W.column(q.face, u, v);
  const t = W.treeAt(q.face, u, v, c);
  if (t && t.kind === "broadleaf") out = { face: q.face, u, v, top: c.top, height: t.height };
}
const g = { u: out.u + 3, v: out.v };
// the litter nearest the tree: a loose stone and a fallen stick lying on the meadow (land-world litterAt)
const lit = {};
for (let du = 0; du < 200 && !(lit.pebble && lit.twigs); du++) for (let dv = 0; dv < 16; dv++) {
  const u = out.u + du, v = q.v0 + dv, c = W.column(q.face, u, v), b = W.terrainBlock(q.face, u, v, c.top + 1);
  if (b === W.B.pebble && !lit.pebble) lit.pebble = [q.face, u, v, c.top + 1];
  if (b === W.B.twigs && !lit.twigs) lit.twigs = [q.face, u, v, c.top + 1];
}
const gc = W.column(out.face, g.u, g.v);
console.log(JSON.stringify({ tree: out, grass: [out.face, g.u, g.v, gc.top], grassBlock: W.terrainBlock(out.face, g.u, g.v, gc.top),
  // rock: under the soil, whose depth varies by place (land-world column().soil)
  rock: [out.face, g.u, g.v, gc.top - gc.soil - 1], rockBlock: W.terrainBlock(out.face, g.u, g.v, gc.top - gc.soil - 1),
  leaves: [out.face, out.u + 1, out.v, out.top + out.height], leavesBlock: W.terrainBlock(out.face, out.u + 1, out.v, out.top + out.height),
  log: [out.face, out.u, out.v, out.top + 2], logBlock: W.terrainBlock(out.face, out.u, out.v, out.top + 2),
  pebble: lit.pebble, twigs: lit.twigs,
  // iron ore: the first ore cell under the grass column, down through the rock
  ore: (() => { for (let h = gc.top - gc.soil - 1; h > 4; h--) if (W.terrainBlock(out.face, g.u, g.v, h) === W.B.ironore) return [out.face, g.u, g.v, h];
                for (let du = 1; du < 40; du++) for (let h = gc.top - 6; h > 4; h--) if (W.terrainBlock(out.face, g.u + du, g.v, h) === W.B.ironore) return [out.face, g.u + du, g.v, h];
                return null; })(),
  // a second grass top, away from the tree (the tree's own cells are felled earlier in the test)
  grass2: [out.face, out.u - 4, out.v + 3, W.column(out.face, out.u - 4, out.v + 3).top],
  grass2Block: W.terrainBlock(out.face, out.u - 4, out.v + 3, W.column(out.face, out.u - 4, out.v + 3).top) }));
""" % (json.dumps(os.path.join(ROOT, "static", "land-world.js")), PA)
CELLS = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=120).stdout)


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": [{"id": "6001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": "6001"}, "holders": {A["address"]: "1"}})

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
    data = tempfile.mkdtemp(prefix="nado_land_eco_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    ha, hb = await login(c, A), await login(c, Bk)
    post = lambda path, body, h: c.post(path, json=body, headers=h)
    async def setc(cells, h):
        return await (await post("/land/api/set", {"cells": cells}, h)).json()
    async def craft(rid, h, times=1):
        return await (await post("/land/api/craft", {"recipe": rid, "times": times}, h)).json()
    inv = lambda addr: world.inv_json(addr)
    def rest():                                                   # a full work bucket, so timing never decides a check below
        world.workb.clear()

    check("the cells are real: grass, rock, leaves and a log where the generator puts them",
          (CELLS["grassBlock"], CELLS["rockBlock"], CELLS["leavesBlock"], CELLS["logBlock"]) == (1, 3, 8, 7), CELLS)

    # ---- by hand -------------------------------------------------------------------------------------------------
    r = await setc([CELLS["grass"] + [0]], ha)
    check("by hand, grass gives earth and fiber", r["applied"] == 1 and inv(A["address"])["items"].get("dirt") == 1
          and inv(A["address"])["items"].get("fiber") == 1, r)
    r = await setc([CELLS["leaves"] + [0]], ha)
    check("by hand, leaves give sticks and fiber", r["applied"] == 1 and inv(A["address"])["items"].get("sticks") == 1, r)
    # the litter: the first stone and sticks lie in plain sight ("where the fuck do i take stone and sticks?", 2026-11-06)
    n0 = dict(inv(A["address"])["items"])
    r = await setc([CELLS["pebble"] + [0]], ha)
    check("by hand, a loose stone on the ground gives a stone", r["applied"] == 1 and inv(A["address"])["items"].get("stone", 0) == n0.get("stone", 0) + 1, r)
    r = await setc([CELLS["twigs"] + [0]], ha)
    check("by hand, a fallen stick gives two sticks", r["applied"] == 1 and inv(A["address"])["items"].get("sticks", 0) == n0.get("sticks", 0) + 2, r)
    # A BLOCK TAKES THE PLACE OF LITTER ("sometimes it places it above", 2026-11-08): a daisy planted where the stone lay,
    # then earth placed into that cell — the earth goes in and the daisy comes back into the bag, as picking it would
    world.player(A["address"])["items"].update({"daisy": 1, "dirt": 1})
    r = await setc([CELLS["pebble"] + [60]], ha)
    check("a wild flower is planted where the stone lay", r["applied"] == 1 and inv(A["address"])["items"].get("daisy", 0) == 0, r)
    world.player(A["address"])["items"]["daisy"] = 1
    r = await setc([CELLS["pebble"] + [60]], ha)
    check("…a flower is not planted over a flower", r["applied"] == 0 and "already" in r["refused"][0][1], r)
    r = await setc([CELLS["pebble"] + [2]], ha)
    check("…earth placed there takes the flower's place, and the flower goes into the bag",
          r["applied"] == 1 and inv(A["address"])["items"].get("daisy", 0) == 2 and inv(A["address"])["items"].get("dirt", 0) == 0, (r, inv(A["address"])["items"]))
    world.player(A["address"])["items"].update({"sapling": 1, "dirt": 1})
    r = await setc([CELLS["twigs"] + [52]], ha)
    r2 = await setc([CELLS["twigs"] + [2]], ha)
    check("…but a planted sapling is never swept away", r["applied"] == 1 and r2["applied"] == 0 and "already" in r2["refused"][0][1], (r, r2))
    r = await setc([CELLS["log"] + [0]], ha)
    check("a log cannot be broken by hand", r["applied"] == 0 and "axe" in r["refused"][0][1], r)
    r = await setc([CELLS["rock"] + [0]], ha)
    check("rock cannot be broken by hand", r["applied"] == 0 and "pickaxe" in r["refused"][0][1], r)
    r = await setc([[0, 5, 5, 0, 0]], ha)
    check("bedrock's layer is never touched", r["applied"] == 0, r)

    # ---- time -----------------------------------------------------------------------------------------------------
    rest()
    fx, fz, fy = CELLS["grass"][1], CELLS["grass"][2], CELLS["grass"][3]
    lots = [[0, fx + i, fz + 1, fy - 1, 0] for i in range(1, 30)]            # 29 earth cells at 0.6 s each by hand
    r = await setc(lots, ha)
    check("breaking spends work: a caller cannot break faster than a hand",
          r["applied"] < 20 and any("too fast" in x[1] for x in r["refused"]), (r["applied"], r["refused"][:1]))

    # ---- tools ----------------------------------------------------------------------------------------------------
    world.player(A["address"])["items"].update({"fiber": 9, "sticks": 6, "stone": 4})
    r = await craft("axe", ha)
    check("an axe needs cordage first", not r["ok"] and "cordage" in r["error"], r)
    for _ in range(3):
        check("fiber twists into cordage", (await craft("cordage", ha))["ok"])
    check("sticks, stone and cordage make a stone axe", (await craft("axe", ha))["ok"] and "axe" in inv(A["address"])["tools"])
    check("…and a stone pickaxe", (await craft("pick", ha))["ok"] and "pick" in inv(A["address"])["tools"])
    rest()
    r = await setc([CELLS["log"] + [0]], ha)
    # FELLING ("can we add some basic gravity", operator 2026-11-06): the log cut is 2 above the ground; every log above
    # it comes down as wood and the crown as what its leaves give — nothing is left floating
    H0, sticks_after_cut = CELLS["tree"]["height"], inv(A["address"])["items"].get("sticks", 0)
    check("with the axe, cutting a trunk fells the tree above the cut: a wood for the cut and for every log above it",
          r["applied"] > H0 - 1 and inv(A["address"])["items"].get("wood") == 1 + (H0 - 2), (r["applied"], inv(A["address"])["items"]))
    check("…and its crown comes down as sticks", sticks_after_cut > n0.get("sticks", 0) + 2, inv(A["address"])["items"])
    above = [CELLS["log"][0], CELLS["log"][1], CELLS["log"][2], CELLS["log"][3] + 1, 0]
    r2 = await setc([above], ha)
    check("nothing is left floating: the log above the cut is already gone", r2["applied"] == 0 and "nothing" in r2["refused"][0][1], r2)
    r = await setc([CELLS["rock"] + [0]], ha)
    check("with the pickaxe rock gives cobblestone", r["applied"] == 1 and inv(A["address"])["items"].get("cobble", 0) >= 1, r)
    check("a tool makes its work quicker: a log is 2.5 s by hand, 2.5 / 3 s with the axe",
          abs(S.RULES["breaking"]["7"]["hard"] / S.RULES["tools"]["axe"]["speed"] - 2.5 / 3) < 1e-9)

    # ---- stations ----------------------------------------------------------------------------------------------------
    world.player(A["address"])["items"].update({"wood": 12, "cordage": 4, "cobble": 16, "clay": 8, "sticks": 12, "stone": 8})
    r = await craft("planks", ha)
    check("planks need a workbench", not r["ok"] and "workbench" in r["error"], r)
    check("a workbench (it needs the axe) is made", (await craft("workbench", ha))["ok"] and "workbench" in inv(A["address"])["stations"])
    n0 = inv(A["address"])["items"].get("planks", 0)
    check("then a wood makes four planks", (await craft("planks", ha))["ok"] and inv(A["address"])["items"].get("planks", 0) == n0 + 4)
    r = await craft("kiln", ha)
    check("a kiln needs a campfire", not r["ok"] and "campfire" in r["error"], r)
    check("campfire, then kiln", (await craft("campfire", ha))["ok"] and (await craft("kiln", ha))["ok"])
    check("the kiln fires clay into bricks", (await craft("brick", ha))["ok"] and inv(A["address"])["items"].get("brick") == 4)
    check("an unknown recipe is refused", not (await craft("warpdrive", ha))["ok"])

    # ---- iron, and a real house ("continue working until the crafting tree has all components to build A REAL HOUSE")
    rest()
    r = await setc([CELLS["ore"] + [0]], ha)
    check("iron ore lies in veins in the rock and the pickaxe mines it", CELLS["ore"] is not None and r["applied"] == 1
          and inv(A["address"])["items"].get("ironore") == 1, (CELLS["ore"], r))
    world.player(A["address"])["items"].update({"wood": 10, "ironore": 16, "cobble": 30, "clay": 12, "stone": 6, "sand": 8, "fiber": 12, "planks": 12})
    check("wood burns to charcoal at the campfire", (await craft("charcoal", ha, 5))["ok"] and inv(A["address"])["items"].get("charcoal") == 10)
    r = await craft("iron", ha)
    check("iron needs a bloomery", not r["ok"] and "bloomery" in r["error"], r)
    check("a bloomery (cobblestone and clay, at the campfire), then ore and charcoal smelt into iron",
          (await craft("bloomery", ha))["ok"] and (await craft("iron", ha, 3))["ok"] and inv(A["address"])["items"].get("iron") == 3)
    world.player(A["address"])["items"]["iron"] = 12
    check("an anvil from iron, a hammer at the anvil", (await craft("anvil", ha))["ok"] and (await craft("hammer", ha))["ok"]
          and "anvil" in inv(A["address"])["stations"] and "hammer" in inv(A["address"])["tools"])
    check("nails and hinges are forged at the anvil with the hammer", (await craft("nails", ha))["ok"] and (await craft("hinges", ha))["ok"]
          and inv(A["address"])["items"].get("nails") == 12 and inv(A["address"])["items"].get("hinges") == 2)
    check("a door: planks, hinges and nails at the workbench with the hammer", (await craft("door", ha))["ok"] and inv(A["address"])["items"].get("door") == 1)
    check("lime from stone and charcoal in the kiln; mortar from lime and sand", (await craft("lime", ha))["ok"] and (await craft("mortar", ha))["ok"]
          and inv(A["address"])["items"].get("mortar") == 4)
    n_sb = inv(A["address"])["items"].get("stonebrick", 0)
    check("masonry is laid in mortar: stone brick needs it", (await craft("stonebrick", ha))["ok"] and inv(A["address"])["items"].get("stonebrick") == n_sb + 2
          and inv(A["address"])["items"].get("mortar") == 3)
    check("thatch from fibre; hewn timber beams from wood with an axe", (await craft("thatch", ha))["ok"] and (await craft("beam", ha))["ok"])
    check("an iron axe is forged", (await craft("iron_axe", ha))["ok"] and "iron_axe" in inv(A["address"])["tools"])
    pl = world.player(A["address"])
    check("tools by class: the iron axe outworks the stone one (6 vs 3), and a recipe that needs an axe takes either",
          S.World._speed(pl, "axe") == 6 and S.World._has_class(pl, "axe")
          and S.World._has_class({"tools": ["iron_axe"], "stations": []}, "axe") and not S.World._has_class({"tools": ["pick"], "stations": []}, "axe"))
    # the door: placed whole at its size, swings on its hinge, comes back as a door
    pa_rec = world.plot(PA)
    dx, dz, dy = 300, 300, (CELLS["grass"][3] + 40) * 100
    added, removed, refused = await world.boxes(A["address"], PA, [[dx, dz, dy, 120, 5, 200, 37]], [])
    check("a door goes in only at its own size", not added and "90 x 5 x 200" in refused[0][1], refused)
    added, removed, refused = await world.boxes(A["address"], PA, [[dx, dz, dy, 90, 5, 200, 37]], [])
    check("…and at its size it costs one door", added == [[dx, dz, dy, 90, 5, 200, 37]] and inv(A["address"])["items"].get("door", 0) == 0, (added, refused))
    nb, ob, err = await world.door(A["address"], PA, [dx, dz, dy, 90, 5, 200, 37])
    check("a door swings open on its hinge (width and depth swap)", err is None and nb == [dx, dz, dy, 5, 90, 200, 37], (nb, err))
    nb2, ob2, err2 = await world.door(A["address"], PA, nb)
    check("…and shut again", err2 is None and nb2 == [dx, dz, dy, 90, 5, 200, 37], (nb2, err2))
    added, _, _ = await world.boxes(A["address"], PA, [[dx, dz + 5, dy, 30, 30, 30, 9]], [])
    _, _, err3 = await world.door(A["address"], PA, nb2)
    check("it will not swing through a piece in its way", added and err3 == "no room to swing it", (added, err3))
    rest()
    _, removed, _ = await world.boxes(A["address"], PA, [], [nb2])
    check("taken down, it comes back as a door", removed == [nb2] and inv(A["address"])["items"].get("door") == 1, removed)

    # ---- the commons, and building --------------------------------------------------------------------------------
    rest()
    wild_cell = CELLS["leaves"][:3] + [CELLS["leaves"][3] + 6]          # open air above the crown
    r = await setc([wild_cell + [10]], ha)                               # cobblestone (the planks are traded below)
    # "you can build anywhere unless it is owned" (operator, 2026-11-06)
    check("anyone signed in builds on unowned land", r["applied"] == 1, r)
    pw0 = S.plot_of(*wild_cell[:3])
    k0 = (wild_cell[1] % 16, wild_cell[2] % 16, wild_cell[3])
    check("…and what is built there stays (it is not set to regrow)", world.plots[pw0]["edits"].get(k0) == 10 and k0 not in world.plots[pw0].get("exp", {}))
    r = await setc([CELLS["grass"][:3] + [CELLS["grass"][3] + 3, 0]], hb)
    rest()
    r = await setc([CELLS["grass2"] + [0]], hb)
    check("anyone signed in gathers in the wilderness", CELLS["grass2Block"] == 1 and r["applied"] == 1, r)
    pw = S.plot_of(*CELLS["leaves"][:3])
    k = (CELLS["leaves"][1] % 16, CELLS["leaves"][2] % 16, CELLS["leaves"][3])
    check("a gathered wilderness cell is set to grow back", k in world.plots[pw].get("exp", {}))
    world.plots[pw]["exp"][k] = 0                                   # its time has come
    back = world.regrow()
    check("…and grows back: the cell returns to the untouched planet", pw in back and k not in world.plots[pw]["edits"], back)
    U, V = COL * 16 + 3, ROW * 16 + 3
    rest()
    top = (await setc([[0, U, V, 200, 0]], ha))                    # air there: nothing to gather
    check("nothing to gather from air", top["applied"] == 0 and "nothing here" in top["refused"][0][1], top)
    b0 = inv(A["address"])["items"].get("planks", 0)
    r = await setc([[0, U, V, 200, 9]], ha)
    check("the holder places a plank on their plot and spends one", r["applied"] == 1 and inv(A["address"])["items"].get("planks", 0) == b0 - 1, r)
    r = await setc([[0, U, V, 200, 11]], ha)
    check("nothing is placed where something already is", r["applied"] == 0 and "already" in r["refused"][0][1], r)
    r = await setc([[0, U + 1, V, 200, 12]], ha)
    check("nobody places what they do not have (no glass)", r["applied"] == 0 and "no glass" in r["refused"][0][1], r)
    rest()
    r = await setc([[0, U, V, 200, 0]], ha)
    check("breaking a placed plank gives the plank back", r["applied"] == 1 and inv(A["address"])["items"].get("planks", 0) == b0, r)
    r = await setc([[0, U + 2, V, 200, 9]], hb)
    check("another player cannot build on the plot", r["applied"] == 0, r)

    # ---- trade ----------------------------------------------------------------------------------------------------
    world.player(Bk["address"])["items"].update({"sand": 10})
    r = await (await post("/land/api/give", {"to": Bk["address"], "items": {"brick": 2}}, ha)).json()
    check("a gift moves items", r["ok"] and inv(Bk["address"])["items"].get("brick") == 2 and inv(A["address"])["items"].get("brick", 0) == 2, r)
    r = await (await post("/land/api/give", {"to": Bk["address"], "items": {"brick": 99}}, ha)).json()
    check("nobody gives what they lack", not r["ok"], r)
    a_sand0 = inv(A["address"])["items"].get("sand", 0)
    r = await (await post("/land/api/offer", {"give": {"planks": 4}, "want": {"sand": 6}}, ha)).json()
    oid = r.get("id")
    check("an offer escrows what it gives", r["ok"] and inv(A["address"])["items"].get("planks", 0) == b0 - 4, r)
    r = await (await post("/land/api/accept", {"id": oid}, ha)).json()
    check("nobody takes their own offer", not r["ok"], r)
    world.player(Bk["address"])["items"]["sand"] = 5
    r = await (await post("/land/api/accept", {"id": oid}, hb)).json()
    check("an offer cannot be taken without what it asks for — and then nothing moves", not r["ok"]
          and inv(Bk["address"])["items"].get("sand", 0) == 5 and oid in world.offers, r)
    world.player(Bk["address"])["items"]["sand"] = 10
    r = await (await post("/land/api/accept", {"id": oid}, hb)).json()
    check("taking it moves both sides at once", r["ok"] and inv(Bk["address"])["items"].get("planks", 0) == 4
          and inv(Bk["address"])["items"].get("sand", 0) == 4 and inv(A["address"])["items"].get("sand", 0) == a_sand0 + 6 and oid not in world.offers, r)
    r = await (await post("/land/api/offer", {"give": {"cobble": 3}, "want": {"wood": 1}}, ha)).json()
    cb = inv(A["address"])["items"].get("cobble", 0)
    r2 = await (await post("/land/api/cancel_offer", {"id": r["id"]}, ha)).json()
    check("a withdrawn offer returns its escrow", r2["ok"] and inv(A["address"])["items"].get("cobble", 0) == cb + 3, r2)
    r = await (await post("/land/api/offer", {"give": {"warpcore": 1}, "want": {"wood": 1}}, ha)).json()
    check("an offer of a thing that is not an item is refused", not r["ok"], r)

    # ---- persistence ----------------------------------------------------------------------------------------------
    await (await post("/land/api/offer", {"give": {"stone": 1}, "want": {"sand": 1}}, ha)).json()
    world.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "")
    check("inventories, tools, stations and open offers survive a restart",
          w2.inv_json(A["address"]) == world.inv_json(A["address"]) and set(w2.offers) == set(world.offers))
    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
