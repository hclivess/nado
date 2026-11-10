"""
"we will need all the civilisation essentials like berries, hunting, crops, water, wells, mills, tools, weapons…"
(operator, 2026-11-09; doc/land-civilisation.md, #156). The world server (scripts/land_server.py) keeps the animals:

  * they come to where players are: up to per_area within area metres of a player present, 18-40 m off, on dry land,
    of the kinds the ground's biome holds; and they are gone when no player is near;
  * they wander, and run from a player who comes within flee metres;
  * hunting: nothing without a weapon; a spear strikes only within its reach; a bow shoots instead (its arrows fly:
    tests/test_an_arrow_flies_falls_and_can_miss_and_a_knife_and_a_saw_do_their_work.py); a strike costs work; at 0 hp
    the animal is gone and its meat, hide and bone (with a knife) are in the hunter's bag — over HTTP as over the socket;
  * what game gives is used: meat is cooked at the campfire and eaten (a meal); hide and lime tan into leather at a
    tanning rack; a spear, a bow and arrows are made from what bare hands gather.

Run: python3 tests/test_animals_wander_near_players_flee_and_are_hunted_with_a_spear_or_a_bow.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-hunt-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, math, subprocess, sys, time

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
HN = RULES["hunting"]

# a player's place on dry land near the landing, its ground's biome
js = """
const W = await import(%s);
const u = 55031, v = 79905, c = W.column(0, u, v);
console.log(JSON.stringify({ pos: [0, u + 0.5, v + 0.5, c.height + 0.05, 0], biome: c.biome }));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
HERE = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=120).stdout)


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
    data = tempfile.mkdtemp(prefix="nado_land_hunt_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    h = await login(c, A)
    # the server's own herd loop steps the animals for the players on its sockets (none here) — stopped, so this test
    # steps them itself for the place it names
    c.server.app["bg"][-1].cancel()
    me, pos = A["address"], HERE["pos"]
    world.keep_place(me, pos)                                      # where the agent stands (its kept place)
    pl = world.player(me)
    api = lambda path, body: c.post(path, json=body, headers=h)
    items = lambda: world.inv_json(me)["items"]
    dist = lambda a, q: math.hypot(a["u"] - q[1], a["v"] - q[2])

    # ---- they come to where players are -----------------------------------------------------------------------------
    sp = HN["species"]
    await world.herd([pos])                                        # (a new animal stands where it came, a moment)
    first = list(world.animals.values())
    ground = await world.cols([[a["face"], a["u"], a["v"]] for a in first])
    check("each comes on dry land, of a kind its ground's biome holds",
          first and all(top > S.SEA and biome in sp[a["kind"]]["biomes"] for a, (_, top, biome) in zip(first, ground)), [(a["kind"], g) for a, g in zip(first, ground)])
    for _ in range(5):
        await world.herd([pos])
    near = [a for a in world.animals.values() if dist(a, pos) < HN["area"]]
    check("animals come to where a player is, up to per_area", 0 < len(near) <= HN["per_area"], len(near))
    check("…come from 18-40 m off, not out of thin air at the player's feet", all(dist(a, pos) > 10 for a in near), [round(dist(a, pos)) for a in near])
    r = await (await c.get("/land/api/animals", params={"face": "0", "u": str(pos[1]), "v": str(pos[2])})).json()
    check("anyone sees the animals near a place", len(r["animals"]) == len(world.animals) and all(len(x) == 7 for x in r["animals"]), r)

    # ---- they run from a player -------------------------------------------------------------------------------------
    a = near[0]
    a["angry"] = False                                             # (a stag would charge instead: #162, its own test)
    a["u"], a["v"], a["go"], a["flee"] = pos[1] + 4, pos[2], 0, 0
    d0 = dist(a, pos)
    for _ in range(4):
        await world.herd([pos])
    check("an animal a player comes close to runs away", a["id"] in world.animals and dist(a, pos) > d0 + 2, (d0, dist(a, pos)))

    # ---- hunting ----------------------------------------------------------------------------------------------------
    a["u"], a["v"], a["h"], a["flee"] = pos[1] + 2, pos[2], pos[3], 0
    r = await (await api("/land/api/hunt", {"id": a["id"]})).json()
    check("nothing is hunted without a weapon", not r["ok"] and "spear or a bow" in r["error"], r)
    for k, n in (("sticks", 6), ("stone", 4), ("cordage", 6), ("fiber", 4), ("wood", 1)):
        pl["items"][k] = n
    pl["stations"] += ["workbench", "campfire"]
    for rid in ("spear", "bow", "arrow"):
        r = await (await api("/land/api/craft", {"recipe": rid})).json()
        check(f"{'arrows are' if rid == 'arrow' else 'a ' + rid + ' is'} made from what bare hands gather", r["ok"], r)
    pl["tools"].remove("bow"); pl["items"].pop("arrow", None)
    pl["tools"].append("knife")                                     # (hide and bone need one: #157)
    world.workb.clear()
    a["u"] = pos[1] + 10
    r = await (await api("/land/api/hunt", {"id": a["id"]})).json()
    check("a spear does not reach an animal 10 m away", not r["ok"] and "far" in r["error"], r)
    a["u"], a["hp"] = pos[1] + 2, sp[a["kind"]]["hp"]
    hp0, struck = a["hp"], 0
    while a["id"] in world.animals and struck < 5:
        world.workb.clear()
        r = await (await api("/land/api/hunt", {"id": a["id"]})).json(); struck += 1
        a["u"], a["v"] = pos[1] + 2, pos[2]                         # (it runs; the hunter follows)
    drops = sp[a["kind"]]["drops"]
    check("a spear within reach strikes until the animal falls", a["id"] not in world.animals and struck == math.ceil(hp0 / HN["weapons"]["spear"]["damage"]), (struck, r))
    check("…and what it drops is in the hunter's bag", r["killed"] == a["kind"] and all(items().get(i, 0) >= n for i, n in drops), (r, items()))
    world.workb[me] = [0, time.time()]
    b = next(iter(world.animals.values()), None) or a
    # (on the hunter's own ground: an animal spawned on a slope stands metres higher or lower, out of a spear's reach)
    world.animals[b["id"]] = b; b["u"], b["v"], b["h"] = pos[1] + 2, pos[2], pos[3]
    r = await (await api("/land/api/hunt", {"id": b["id"]})).json()
    check("a strike costs work: no strikes faster than a hand", not r["ok"] and "fast" in r["error"], r)

    # the bow shoots instead of striking (BALLISTICS, #157: tests/test_an_arrow_flies_falls_and_can_miss…)
    pl["tools"].remove("spear"); pl["tools"].append("bow")
    world.workb.clear()
    r = await (await api("/land/api/hunt", {"id": b["id"]})).json()
    check("a bow does not strike like a spear: it shoots", not r["ok"] and "shoots" in r["error"], r)
    r = await (await api("/land/api/hunt", {"id": 999999})).json()
    check("an animal that is gone cannot be hunted", not r["ok"], r)

    # ---- what game gives ---------------------------------------------------------------------------------------------
    pl["items"]["meat"] = pl["items"].get("meat", 0) + 1
    r = await (await api("/land/api/craft", {"recipe": "cooked_meat"})).json()
    check("meat is cooked at the campfire", r["ok"] and items().get("cooked_meat") == 1, r)
    r = await (await api("/land/api/eat", {"item": "cooked_meat"})).json()
    check("…and cooked meat is a meal", r["ok"] and abs(r["inventory"]["fed"] - RULES["food"]["items"]["cooked_meat"]) <= 2, r)
    r = await (await api("/land/api/eat", {"item": "meat"})).json()
    check("raw meat is not eaten", not r["ok"], r)
    pl["items"].update({"hide": 1, "lime": 1, "sticks": 6, "cordage": 2})
    r = await (await api("/land/api/craft", {"recipe": "tanning_rack"})).json()
    r = await (await api("/land/api/craft", {"recipe": "leather"})).json()
    check("hide and lime tan into leather at a tanning rack", r["ok"] and items().get("leather") == 1, r)

    # ---- and gone when no one is near -------------------------------------------------------------------------------
    await world.herd([[0, pos[1] + 5000, pos[2], pos[3], 0]])
    check("the animals near a place are gone when no player is near it", not any(dist(a, pos) < HN["area"] for a in world.animals.values()))
    await world.herd([])
    check("…and with nobody present there are none", not world.animals)

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
