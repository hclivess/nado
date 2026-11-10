"""
"ballistics? bow and arrow? knife? carpentry tools?" (operator, 2026-11-09; doc/land-civilisation.md 3b, #157). The world
server (scripts/land_server.py):

  * an arrow leaves the hunter's eye along the aim at the bow's draw speed and falls under gravity: aimed straight at a
    still deer 30 m off it drops under it and misses; aimed a little above (the drop allowed for) it hits;
  * it hits a running animal only where the animal is when the arrow arrives: aimed at where a fleeing deer is, it
    misses behind; aimed ahead of it (led), it hits;
  * every shot spends an arrow, none without one; an arrow that misses lands, and one that can be found lies there to
    be picked up — from beside it, not from across the meadow;
  * a kill gives its meat to anyone, its hide and bone only to a hunter with a knife;
  * carpentry: a saw (at an anvil) cuts more planks and beams from a log than the workbench alone; a chisel makes a
    wheel; a knife is made by hand.

Run: python3 tests/test_an_arrow_flies_falls_and_can_miss_and_a_knife_and_a_saw_do_their_work.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-arrows-")
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
HN, HL = RULES["hunting"], RULES["health"]

js = """
const W = await import(%s);
const u = 55031, v = 79905, c = W.column(0, u, v);
console.log(JSON.stringify({ pos: [0, u + 0.5, v + 0.5, c.height + 0.05, 0] }));
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
    data = tempfile.mkdtemp(prefix="nado_land_arrows_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    h = await login(c, A)
    c.server.app["bg"][-1].cancel()                              # the test places the animals itself
    me, pos = A["address"], HERE["pos"]
    world.keep_place(me, pos)
    pl = world.player(me)
    B = HN["ballistics"]
    items = lambda: world.inv_json(me)["items"]
    ground = lambda du, dv: (asyncio.get_event_loop(), None)
    async def gh(u, v):
        return (await world.cols([[0, u, v]]))[0][0]
    async def deer(du, dv, **kw):
        world.animal_seq += 1
        u, v = pos[1] + du, pos[2] + dv
        a = {"id": world.animal_seq, "kind": "deer", "face": 0, "u": u, "v": v, "h": await gh(u, v), "yaw": 0.0, "hp": 99,
             "go": 1e18, "flee": 0, "angry": False}
        a.update(kw)
        world.animals.clear(); world.animals[a["id"]] = a
        return a
    def aim_at(a, lead=0.0, allow_drop=True):
        """yaw and pitch from the hunter's eye to the animal's body (led `lead` m along its run), with the arrow's drop
        allowed for or not."""
        size = HN["species"][a["kind"]]["size"]
        tu, tv, th = a["u"] + math.sin(a["yaw"]) * lead, a["v"] + math.cos(a["yaw"]) * lead, a["h"] + size[2] * 0.6
        du, dv, dh = tu - pos[1], tv - pos[2], th - (pos[3] + 1.5)
        R = math.hypot(du, dv)
        drop = B["g"] * (R / B["draw"]) ** 2 / 2 if allow_drop else 0
        return math.atan2(du, dv), math.atan2(dh + drop, R)
    async def shoot(yaw, pitch):
        world.workb.clear()
        return await (await c.post("/land/api/shoot", json={"yaw": yaw, "pitch": pitch}, headers=h)).json()

    pl["tools"].append("bow")
    r = await shoot(0.0, 0.0)
    check("no arrow, no shot", not r["ok"] and "arrows" in r["error"], r)
    pl["items"]["arrow"] = 20

    # ---- it falls ---------------------------------------------------------------------------------------------------------
    d = await deer(0, 30)
    r = await shoot(*aim_at(d, allow_drop=False))
    check("aimed straight at a still deer 30 m off, the arrow drops under it and misses", r["ok"] and r["hit"] is None and r["end"], r)
    check("…an arrow spent", items()["arrow"] == 19)
    d = await deer(0, 30)
    r = await shoot(*aim_at(d))
    check("aimed a little above, the drop allowed for, it hits", r["ok"] and r["hit"] == "deer" and d["hp"] < 99, r)
    check("…after its time of flight (30 m at the draw speed)", abs(r["flight"] - 30 / B["draw"]) < 0.15, r["flight"])

    # ---- a running animal must be led -------------------------------------------------------------------------------------
    d = await deer(20, 25, yaw=math.pi / 2, flee=time.time() + 30)    # running east, across the line of fire
    r = await shoot(*aim_at(d))
    check("aimed at where a running deer is, the arrow arrives behind it", r["ok"] and r["hit"] is None, r)
    d = await deer(20, 25, yaw=math.pi / 2, flee=time.time() + 30)
    sp = HN["species"]["deer"]["speed"]
    r = await shoot(*aim_at(d, lead=sp * math.hypot(20, 25) / B["draw"]))
    check("aimed ahead of it, led by its run over the arrow's flight, it hits", r["ok"] and r["hit"] == "deer", r)

    # ---- a miss lies on the ground ------------------------------------------------------------------------------------------
    world.animals.clear()
    world.rng.seed(7)
    lay = None
    for _ in range(8):
        r = await shoot(0.0, -0.2)                                # into the ground ahead
        if world.drops:
            lay = next(iter(world.drops.values())); break
    check("an arrow that misses lands; some lie there to be picked up", lay is not None and lay["item"] == "arrow", world.drops)
    n0 = items()["arrow"]
    world.keep_place(me, [0, lay["u"] + 20, lay["v"], lay["h"], 0])
    r = await (await c.post("/land/api/pickup", json={"id": lay["id"]}, headers=h)).json()
    check("…not from across the meadow", not r["ok"] and "far" in r["error"], r)
    world.keep_place(me, [0, lay["u"] + 1, lay["v"], lay["h"], 0])
    r = await (await c.post("/land/api/pickup", json={"id": lay["id"]}, headers=h)).json()
    check("…but from beside it, back into the bag", r["ok"] and items()["arrow"] == n0 + 1 and lay["id"] not in world.drops, r)
    world.keep_place(me, pos)

    # ---- the knife ---------------------------------------------------------------------------------------------------------
    pl["tools"].append("spear")
    d = await deer(0, 2, hp=1)
    d["h"] = pos[3]
    world.workb.clear()
    res, err = world.hunt(me, d["id"], pos)
    check("without a knife a kill gives only its meat", res and res["killed"] == "deer" and {i for i, _ in res["drops"]} == {"meat"}, (res, err))
    for k, n in (("stone", 2), ("sticks", 1), ("cordage", 1)):
        pl["items"][k] = pl["items"].get(k, 0) + n
    r = await (await c.post("/land/api/craft", json={"recipe": "knife"}, headers=h)).json()
    check("a knife is made by hand from stone, a stick and cordage", r["ok"] and "knife" in r["inventory"]["tools"], r)
    d = await deer(0, 2, hp=1)
    d["h"] = pos[3]
    world.workb.clear()
    res, err = world.hunt(me, d["id"], pos)
    check("with a knife, hide and bone too", res and {i for i, _ in res["drops"]} == {"meat", "hide", "bone"}, (res, err))

    # ---- carpentry -----------------------------------------------------------------------------------------------------------
    pl["stations"] += ["workbench", "anvil"]; pl["tools"].append("hammer")
    pl["items"].update({"wood": 4, "iron": 5, "planks": 10, "sticks": 2})
    r = await (await c.post("/land/api/craft", json={"recipe": "planks"}, headers=h)).json()
    plain = r["inventory"]["items"]["planks"] - 10
    r = await (await c.post("/land/api/craft", json={"recipe": "planks_saw"}, headers=h)).json()
    check("no saw, no sawn planks", not r["ok"], r)
    for rid in ("saw", "chisel"):
        r = await (await c.post("/land/api/craft", json={"recipe": rid}, headers=h)).json()
        check(f"a {rid} is made of iron at the anvil", r["ok"] and rid in r["inventory"]["tools"], r)
    p0 = items()["planks"]
    r = await (await c.post("/land/api/craft", json={"recipe": "planks_saw"}, headers=h)).json()
    check(f"a saw cuts more planks from a log ({items()['planks'] - p0} against {plain})", r["ok"] and items()["planks"] - p0 > plain, r)
    r = await (await c.post("/land/api/craft", json={"recipe": "wheel"}, headers=h)).json()
    check("a chisel makes a wheel", r["ok"] and items().get("wheel") == 1, r)

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
