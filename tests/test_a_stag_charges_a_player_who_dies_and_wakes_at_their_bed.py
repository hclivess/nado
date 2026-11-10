"""
"add aggressive deer and death/respawn mechanism" (operator, 2026-11-09; #162). The world server (scripts/land_server.py):

  * a stag (an angry deer) charges a player within hunting.charge metres, and strikes within strike_reach — no faster
    than strike_every_s — for its damage; a deer that is not angry still runs from a player;
  * a struck boar fights back: it charges the hunter instead of running;
  * a visitor (no one signed in) is never struck;
  * health: a player's health drops by each strike, and comes back a point every regen_s once nothing has hurt them
    for calm_s, up to max;
  * at 0 the player dies: health is full again, the bag is kept, they wake at the bed they last used (Use on a bed) —
    or at the landing with no bed — and nothing hurts them for grace_s; a bed that is not a bed is refused.

Run: python3 tests/test_a_stag_charges_a_player_who_dies_and_wakes_at_their_bed.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-death-")
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
    data = tempfile.mkdtemp(prefix="nado_land_death_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    h = await login(c, A)
    c.server.app["bg"][-1].cancel()                              # the test steps the herd itself (no sockets here)
    me, pos = A["address"], HERE["pos"]
    pl = world.player(me)
    pl["items"]["stone"] = 7
    dist = lambda a: math.hypot(a["u"] - pos[1], a["v"] - pos[2])
    def animal(kind, du, angry=False):
        world.animal_seq += 1
        a = {"id": world.animal_seq, "kind": kind, "face": 0, "u": pos[1] + du, "v": pos[2], "h": pos[3], "yaw": 0.0,
             "hp": HN["species"][kind]["hp"], "go": 1e18, "flee": 0, "angry": angry}
        world.animals[a["id"]] = a
        return a
    async def step(n=1, players=None):
        hits = []
        for _ in range(n):
            hits += await world.herd([pos], players=[(me, pos)] if players is None else players) or []
        return hits

    # ---- a stag charges, a doe runs ---------------------------------------------------------------------------------
    stag = animal("deer", 8, angry=True)
    doe = animal("deer", -5)
    d0s, d0d = dist(stag), dist(doe)
    await step(2)
    check("a stag charges a player within charge metres", dist(stag) < d0s - 1, (d0s, dist(stag)))
    check("…while a deer that is not angry runs", dist(doe) > d0d + 1, (d0d, dist(doe)))
    stag["u"] = pos[1] + 1.2
    hits = await step()
    check("within reach it strikes for its damage", hits == [(me, HN["species"]["deer"]["damage"], "deer")], hits)
    hits = await step()
    check("…no faster than strike_every_s", hits == [], hits)
    stag["bite"] = 0
    check("a visitor (signed out) is never struck: with nobody signed in near, no strike lands", (await world.herd([pos], players=[])) == [])

    # ---- health -----------------------------------------------------------------------------------------------------
    r = world.hurt(me, 3, "deer")
    check("a strike takes health", r == ("hurt", HL["max"] - 3) and world.inv_json(me)["hp"] == HL["max"] - 3, r)
    now = time.time()
    check("no healing while something hurt them lately", world.heal(now + 1) == [])
    healed = world.heal(now + HL["calm_s"] + 1)
    check("once calm, a point comes back", healed == [me] and world.inv_json(me)["hp"] == HL["max"] - 2)
    check("…one every regen_s", world.heal(now + HL["calm_s"] + 2) == [] and world.heal(now + HL["calm_s"] + 2 + HL["regen_s"]) == [me])

    # ---- death ------------------------------------------------------------------------------------------------------
    r = world.hurt(me, 99, "deer")
    check("at 0 the player dies, waking at the landing with no bed", r == ("died", None), r)
    check("…full health again, the bag kept", world.inv_json(me)["hp"] == HL["max"] and world.inv_json(me)["items"].get("stone") == 7)
    check("…and nothing hurts them in their grace", world.hurt(me, 5, "deer") is None and world.inv_json(me)["hp"] == HL["max"])
    # a bed: built on the commons, used
    f, u, v = 0, int(pos[1]) + 3, int(pos[2])
    p = S.plot_of(f, u, v)
    fc, fr = p % S.FACE_N, (p // S.FACE_N) % S.FACE_N
    bed = [(u - fc * 16) * 100, (v - fr * 16) * 100, 20000] + RULES["items"]["bed"]["unit"] + [S.BED]
    pl["items"]["bed"] = 1
    world.workb.clear()
    r = await (await c.post("/land/api/boxes", json={"plot": p, "add": [bed]}, headers=h)).json()
    check("a bed is built", r.get("added") == 1, r)
    r = await (await c.post("/land/api/bed", json={"plot": p, "box": bed[:6] + [S.CHEST]}, headers=h)).json()
    check("only a bed is slept in", not r["ok"], r)
    r = await (await c.post("/land/api/bed", json={"plot": p, "box": bed}, headers=h)).json()
    check("Use on a bed: the player will wake there", r["ok"] and pl["bed"][4] == p, r)
    pl["grace"] = 0
    r = world.hurt(me, 99, "boar")
    check("dying now, they wake at their bed", r[0] == "died" and r[1][:4] == pl["bed"][:4] and world.player(me)["pos"][:3] == pl["bed"][:3], r)

    # ---- a struck boar fights back ------------------------------------------------------------------------------------
    # back in the wild: the bed made this plot settled land, where no animal charges anyone (#168)
    world.plot(p)["boxes"].clear()
    pl["grace"] = 0
    pl["tools"].append("spear")
    boar = animal("boar", 2.5)
    world.workb.clear()
    world.keep_place(me, pos)
    res, err = world.hunt(me, boar["id"], pos)
    check("a boar is struck", res and res["hit"] == "boar", (res, err))
    b0 = dist(boar)
    await step()
    check("…and, struck, it charges the hunter instead of running", dist(boar) < b0, (b0, dist(boar)))

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
