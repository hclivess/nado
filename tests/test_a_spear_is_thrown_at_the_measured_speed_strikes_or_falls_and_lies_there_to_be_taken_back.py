"""
A thrown spear (#157, "a thrown spear" left open by ballistics part 1; doc/land-civilisation.md 3b). The world server
(scripts/land_server.py throw_spear):

  * the spear leaves the hand at the MEASURED throw speed (hunting.ballistics.throw, 16 m/s: trained javelin athletes
    threw Schöningen spear replicas at over 35 mph, ~15.6 m/s — Milks, Parker & Pope 2019) and falls under gravity: a
    still deer 12 m off is hit when the drop is allowed for, after the flight time that speed gives;
  * it is a TOOL, not ammunition: it leaves the hunter's tools while it flies, and none is thrown without a spear;
  * it ALWAYS lies where it ended — beside the deer it struck, or where it fell short — and is taken back from beside it
    (not from across the meadow), back among the tools; a second one is not taken while the hunter carries one;
  * until it is taken back the hunter has no spear: no strike, no second throw;
  * the page throws it only at an animal within throw_reach (24 m, where the study's athletes stopped hitting), when it
    has no arrows to shoot, draws it as a spear in flight and on the ground, and says a miss in 17 languages.

Run: python3 tests/test_a_spear_is_thrown_at_the_measured_speed_strikes_or_falls_and_lies_there_to_be_taken_back.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-spear-")
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
    data = tempfile.mkdtemp(prefix="nado_land_spear_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    h = await login(c, A)
    c.server.app["bg"][-1].cancel()                              # the test places the animals itself
    me, pos = A["address"], HERE["pos"]
    world.keep_place(me, pos)
    pl = world.player(me)
    B = HN["ballistics"]
    async def gh(u, v):
        return (await world.cols([[0, u, v]]))[0][0]
    async def deer(du, dv):
        world.animal_seq += 1
        u, v = pos[1] + du, pos[2] + dv
        a = {"id": world.animal_seq, "kind": "deer", "face": 0, "u": u, "v": v, "h": await gh(u, v), "yaw": 0.0, "hp": 99,
             "go": 1e18, "flee": 0, "angry": False}
        world.animals.clear(); world.animals[a["id"]] = a
        return a
    def aim_at(a, allow_drop=True):
        size = HN["species"][a["kind"]]["size"]
        du, dv, dh = a["u"] - pos[1], a["v"] - pos[2], a["h"] + size[2] * 0.6 - (pos[3] + 1.5)
        R = math.hypot(du, dv)
        drop = B["g"] * (R / B["throw"]) ** 2 / 2 if allow_drop else 0
        return math.atan2(du, dv), math.atan2(dh + drop, R)
    async def throw(yaw, pitch):
        world.workb.clear()
        return await (await c.post("/land/api/throw", json={"yaw": yaw, "pitch": pitch}, headers=h)).json()
    tools = lambda: world.inv_json(me)["tools"]

    check("the throw speed is the measured one (about 15.6 m/s, rounded to 16) and the reach where hits stopped",
          B["throw"] == 16 and B["throw_reach"] == 24 and "Milks" in B["about_throw"] and "Sch" in B["about_throw"])
    r = await throw(0.0, 0.0)
    check("no spear, no throw", not r["ok"] and "spear" in r["error"], r)
    pl["tools"].append("spear")

    # ---- it flies at the measured speed and strikes ------------------------------------------------------------------
    d = await deer(0, 12)
    r = await throw(*aim_at(d))
    check("aimed with the drop allowed for, the spear strikes a still deer 12 m off", r["ok"] and r["hit"] == "deer" and d["hp"] < 99, r)
    check("…after the time 12 m takes at the throw speed", abs(r["flight"] - 12 / B["throw"]) < 0.15, r["flight"])
    check("…and it has left the hunter's tools", "spear" not in tools())
    lying = [x for x in world.drops.values() if x["item"] == "spear"]
    check("…it lies beside the deer it struck, to be taken back", len(lying) == 1 and math.hypot(lying[0]["u"] - d["u"], lying[0]["v"] - d["v"]) < 1.5, lying)
    r = await throw(0.0, 0.0)
    check("with the spear lying out there, there is no second throw", not r["ok"] and "spear" in r["error"], r)
    check("…and no strike either", not world._has_class(pl, "spear"))

    # ---- taken back from beside it, not from afar ----------------------------------------------------------------------
    sid = lying[0]["id"]
    check("not taken back from across the meadow", world.pickup(me, sid, pos) == "too far away" and "spear" not in tools())
    beside = [0, lying[0]["u"] + 0.5, lying[0]["v"], lying[0]["h"], 0]
    check("taken back from beside it, among the tools again", world.pickup(me, sid, beside) is None and "spear" in tools() and sid not in world.drops)

    # ---- a miss falls and still lies there ---------------------------------------------------------------------------
    d = await deer(0, 20)
    r = await throw(*aim_at(d, allow_drop=False))
    check("aimed straight at a deer 20 m off, the spear falls short", r["ok"] and r["hit"] is None and r["end"], r)
    lying = [x for x in world.drops.values() if x["item"] == "spear"]
    check("…and ALWAYS lies where it fell (an arrow is found only sometimes)", len(lying) == 1 and math.hypot(lying[0]["u"] - r["end"][1], lying[0]["v"] - r["end"][2]) < 0.6, lying)
    pl["tools"].append("spear")                                   # another made meanwhile
    near = [0, lying[0]["u"], lying[0]["v"], lying[0]["h"], 0]
    check("a second spear is not taken while one is carried — it stays lying", world.pickup(me, lying[0]["id"], near) == "you carry one already" and lying[0]["id"] in world.drops)

    # ---- the page -----------------------------------------------------------------------------------------------------
    page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
    hunt = page[page.index("function huntAt(an)"):page.index("\n}\n", page.index("function huntAt(an)"))]
    check("the page strikes within reach, shoots when it has arrows, and only then throws the spear — within throw_reach",
          hunt.index("H.weapons.spear.reach") < hunt.index("inv.items.arrow > 0) return loose()") < hunt.index("an.d <= H.ballistics.throw_reach) return throwSpear()"))
    check("…sends the throw and flies it at the throw speed", 'net.send({ t: "throw", yaw: P.yaw, pitch: P.pitch, req: ++net.req })' in page and "B.throw * cp * Math.sin(P.yaw)" in page)
    check("…and draws a spear, in flight and lying on the ground", "const m = spearMesh(); scene.add(m);" in page and "RULES.tools[item] ? spearMesh() : arrowMesh()" in page)
    tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
    check("a miss is said in all 17 languages", len(tr) == 17 and all(l.get("land.spearMiss") for l in tr.values()) and 'T("spearMiss"' in page)
    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
