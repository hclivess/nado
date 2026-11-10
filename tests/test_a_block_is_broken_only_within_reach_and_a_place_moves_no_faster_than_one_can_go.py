"""
"pick recommended" (operator 2026-11-10, #167 option b): a cell was broken anywhere on the planet without going there,
and a page's place jumped anywhere (/tp <u> <v>), so markets, trips and hunts measured a place that cost nothing to
change. The world server (scripts/land_server.py REACH_M, pace_ok, move, tp):

  * a break from someone whose place nobody knows is refused ("stand in the world first");
  * beside it, it breaks; 30 m off, it is out of reach — the same for placing in the wild;
  * /land/api/move (an agent without a page): a step at a walk is taken, a 1 km jump is refused, its place kept;
  * the pace: 30 m in half a second is a flier, in a tenth it is a jump; an hour away buys no more than 5 s;
    over another face's edge only from near it;
  * the page's socket: a place reported too far from the last is put back (pos_fix, "pace"); /tp spawn moves the
    player to the landing; /tp bed without a bed is refused ("nobed"), with one it goes there; /tp <u> <v> does nothing;
  * dying, the pace starts again where they wake;
  * with two pages open, a dig is measured from the page that moved last (not the first one found).

Run: python3 tests/test_a_block_is_broken_only_within_reach_and_a_place_moves_no_faster_than_one_can_go.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-reach-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys

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

js = """
const W = await import(%s);
const u = 55031, v = 79905, c = W.column(0, u, v);
console.log(JSON.stringify({ u, v, top: c.top, block: W.terrainBlock(0, u, v, c.top) }));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
G = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=120).stdout)


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
    return (await r.json())["token"]


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_reach_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    hub = S.Hub()
    c = TestClient(TestServer(S.make_app(world, hub, "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    tok = await login(c, A)
    h = {"Authorization": "Bearer " + tok}
    me, u, v, top = A["address"], G["u"], G["v"], G["top"]
    cell = [0, u, v, top, 0]
    post = lambda path, body: c.post(path, json=body, headers=h)
    async def dig(cells):
        world.workb.clear()
        return await (await post("/land/api/set", {"cells": cells})).json()

    # ---- reach ------------------------------------------------------------------------------------------------------
    r = await dig([cell])
    check("a break from someone nobody knows the place of is refused", r["applied"] == 0 and "stand in the world first" in r["refused"][0][1], r)
    world.keep_place(me, [0, u + 30.5, v + 0.5, top + 1, 0])
    r = await dig([cell])
    check("30 m off, it is out of reach", r["applied"] == 0 and "out of reach" in r["refused"][0][1], r)
    world.player(me)["items"]["dirt"] = 5
    r = await dig([[0, u, v, top + 3, 2]])
    check("…and so is placing in the wild from there", r["applied"] == 0 and "out of reach" in r["refused"][0][1], r)
    world.keep_place(me, [0, u + 1.5, v + 0.5, top + 1, 0])
    r = await dig([cell])
    check("beside it, it breaks", r["applied"] == 1, r)

    # ---- move (an agent without a page) -------------------------------------------------------------------------------
    r = await (await post("/land/api/move", {"p": [0, u + 4.5, v + 0.5, top + 1, 0]})).json()
    check("a step at a walk is taken", r["ok"] and abs(world.player(me)["pos"][1] - (u + 4.5)) < 0.01, r)
    r = await (await post("/land/api/move", {"p": [0, u + 1004.5, v + 0.5, top + 1, 0]})).json()
    check("a 1 km jump is refused, the place kept", not r["ok"] and abs(world.player(me)["pos"][1] - (u + 4.5)) < 0.01 and "faster than you can go" in r["error"], r)
    r = await (await post("/land/api/move", {"p": [0, u, v, top, 0, 9]})).json()
    check("…and a place that is no place is refused", not r["ok"], r)

    # ---- the pace -----------------------------------------------------------------------------------------------------
    a = [0, 1000.0, 1000.0, 100.0, 0]
    check("30 m in half a second is a flier", S.pace_ok(a, 0, [0, 1030.0, 1000.0, 100.0, 0], 0.5))
    check("…in a tenth of one it is a jump", not S.pace_ok(a, 0, [0, 1030.0, 1000.0, 100.0, 0], 0.1))
    check("an hour away buys no more than 5 s of going", not S.pace_ok(a, 0, [0, 1000.0 + S.PACE_MPS * 5 + S.PACE_SLACK + 50, 1000.0, 100.0, 0], 3600))
    check("a fall is no journey (height is not counted)", S.pace_ok(a, 0, [0, 1000.0, 1000.0, -40.0, 0], 0.1))
    check("onto another face only from near its edge", not S.pace_ok(a, 0, [1, 1000.0, 1000.0, 100.0, 0], 1)
          and S.pace_ok([0, 3.0, 5000.0, 100.0, 0], 0, [1, 5000.0, 3.0, 100.0, 0], 1))

    # ---- the page's socket --------------------------------------------------------------------------------------------
    ws = await c.ws_connect("/land/ws?token=" + tok)
    async def say(m, want):
        await ws.send_json(m)
        for _ in range(40):
            got = await ws.receive_json(timeout=10)
            if got.get("t") == want:
                return got
        return None
    here = world.player(me)["pos"]
    r = await say({"t": "pos", "p": [0, here[1] + 900, here[2], here[3], 0]}, "pos_fix")
    check("a place reported 900 m from the last is put back where the world last saw them", r and r["why"] == "pace" and abs(r["p"][1] - here[1]) < 0.01, r)
    r = await say({"t": "tp", "to": "spawn"}, "pos_fix")
    check("/tp spawn moves them to the landing", r and r["why"] == "tp" and r["p"][:3] == S.landing(), r)
    r = await say({"t": "tp", "to": "bed"}, "pos_fix")
    check("/tp bed without a bed is refused", r and r["why"] == "nobed", r)
    world.player(me)["bed"] = [0, u + 2, v + 2, top + 1, S.plot_of(0, u, v)]
    r = await say({"t": "tp", "to": "bed"}, "pos_fix")
    check("…with one, it goes there", r and r["why"] == "tp" and r["p"][:3] == [0, u + 2, v + 2], r)
    st = next(iter(hub.socks.values()))
    check("…and the pace starts there", abs(st["pace"][0][1] - (u + 2)) < 0.01)
    await ws.close()

    # ---- two pages open: measured from the one that moved last ----------------------------------------------------------
    w1 = await c.ws_connect("/land/ws?token=" + tok); w2 = await c.ws_connect("/land/ws?token=" + tok)
    world.pace_free = True                                       # the two places are put by hand here; the pace has its own checks above
    await w1.send_json({"t": "pos", "p": [0, u + 300.5, v + 0.5, top + 1, 0]}); await asyncio.sleep(0.3)
    await w2.send_json({"t": "pos", "p": [0, u + 1.5, v + 2.5, top + 1, 0]}); await asyncio.sleep(0.3)
    r = await dig([[0, u, v + 2, top, 0]])
    check("with two pages open, a dig is measured from the page that moved last (beside it), not the first one found",
          r["applied"] == 1 or "nothing here" in str(r["refused"]), r)
    await w1.close(); await w2.close()

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
