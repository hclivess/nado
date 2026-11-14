"""
THE ENERGY CANNON (#171 item 3, approved by the operator 2026-11-14): a cannon part on a craft, bound to a key at the
cannon, fires a bolt along its barrel while the pilot holds the key; the world server (scripts/land_server.py World.bolt)
checks what the pilot's page says the bolt met:
  1. a cannon is a gadget (it takes a key at the cannon), and its bolt tears a cell of the planet's tree in front of the
     craft within BOLT_RANGE and on the bolt's line — nothing gathered;
  2. a bolt strikes an animal on its line (hunting.weapons.cannon.damage) and kills a deer outright;
  3. refused: a target off the line ("missed"), behind the craft, past the range; a second bolt sooner than BOLT_EVERY;
     a craft with no cannon bound to a key; a craft the caller does not fly; a stranger's titled plot keeps its trees;
     the ground under a tree is no tree;
  4. a bolt into open air is fired and strikes nothing.
Run: python3 tests/test_a_cannon_bound_to_a_key_fires_bolts_that_strike_animals_and_tear_trees.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-cannon-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, math, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
from aiohttp.test_utils import TestServer
from signatures import generate_keydict
from execnode.games import land as L
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check

A, Bk = generate_keydict(), generate_keydict()
PA = 4989 * L.FACE_N + 3433                                   # A's titled plot: a wooded one (as the tearing test)
PB = PA + 1                                                   # the commons beside it
PLATE, THR, SEAT = 64, 65, 66
FACE = 0
CANNON = S.PART_FIRST + S.P_CANNON * 10                       # the cannon part, variant 0


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": [{"id": "7001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": req.query["id"]}, "holders": {A["address"]: "1"}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


def tree_roots(plot):
    fr, fc = (plot // L.FACE_N) % L.FACE_N, plot % L.FACE_N
    js = (f"const W = await import({json.dumps(os.path.join(ROOT, 'static', 'land-world.js'))});"
          f"console.log(JSON.stringify(W.treeRoots({FACE}, {fc * L.PLOT}, {fr * L.PLOT}, {L.PLOT}).map((r) => [r.wu, r.wv, r.col.top, r.tree.kind, r.tree.height])));")
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, check=True).stdout
    return [dict(wu=u, wv=v, top=t, kind=k, height=h) for u, v, t, k, h in json.loads(out)]


async def trunk_cell(world, r):
    cands = [[FACE, r["wu"] + du, r["wv"] + dv, r["top"] + dh] for dh in range(1, r["height"] + 2) for du in (0, 1, -1) for dv in (0, 1, -1)]
    got = await world.blocks_at(cands)
    return next((tuple(c) for c in cands if got[tuple(c)] in S.TREE_WOOD), None)


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_cannon_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = __import__("aiohttp").ClientSession()
    await world.start_oracle()
    world.work = lambda who, s: True
    a, b = A["address"], Bk["address"]
    gun = [600, 700, 20000, 40, 200, 40, PLATE, CANNON]
    check("a cannon part is a gadget: it takes a key at the cannon", S.is_cannon(gun) and S.is_gadget(gun) and not S.is_gadget([0, 0, 0, 10, 10, 10, PLATE]))
    # A's craft: a plate, a seat, a thruster and a cannon, boarded on A's plot; its cannon bound to key 1
    world.player(a)["items"].update({"steel_plate": 4, "thruster": 2, "pilot_seat": 1})
    added, _, refused = await world.boxes(a, PA, [[600, 600, 20000, 400, 150, 5, PLATE], [760, 640, 20005, 80, 90, 110, SEAT], [700, 500, 20000, 100, 100, 140, THR], gun], [])
    check("the craft with its cannon is built", len(added) == 4 and not refused, refused)
    c, _, err = await world.board(a, PA, [760, 640, 20005, 80, 90, 110, SEAT])
    check("…and boarded", err is None, err)
    cid = c["id"]
    gi = next(i for i, p in enumerate(c["pieces"]) if S.is_cannon(p))
    c["slots"] = [1 if i == gi else 0 for i in range(len(c["pieces"]))]
    roots = tree_roots(PA)
    r0 = roots[0]
    wood = await trunk_cell(world, r0)
    check("a trunk cell of a tree on A's plot is found", wood is not None, r0)
    # stand 30 m south of the trunk, level with it, the bolt north along +v
    tu, tv, th = wood[1] + 0.5, wood[2] + 0.5, wood[3] + 0.5
    c["pose"] = [FACE, tu, tv - 30, th, 0.0]
    north = [0, 1, 0]
    before = dict(world.player(a)["items"])
    res, applied, err = await world.bolt(a, cid, north, {"cell": list(wood)})
    check("1. a bolt tears the trunk cell 30 m ahead on its line", err is None and res and res.get("torn", 0) >= 1, (res, err))
    check("…the tree above it comes down with it, nothing gathered", res and res.get("torn", 0) > 1 and dict(world.player(a)["items"]) == before, (res, world.player(a)["items"]))
    res, applied, err = await world.bolt(a, cid, north, None)
    check("3. a second bolt sooner than BOLT_EVERY is refused", err == "too fast", err)
    await asyncio.sleep(S.World.BOLT_EVERY + 0.05)
    # 2. an animal on the line
    world.animals["deer1"] = {"id": "deer1", "kind": "deer", "face": FACE, "u": tu, "v": tv - 10, "h": th - 0.6, "yaw": 0.0, "hp": RULES_HP if (RULES_HP := S.RULES["hunting"]["species"]["deer"]["hp"]) else 3}
    res, _, err = await world.bolt(a, cid, north, {"animal": "deer1"})
    check(f"2. a bolt strikes a deer 20 m ahead on its line and kills it ({S.RULES['hunting']['weapons']['cannon']['damage']} damage against its {RULES_HP} hp)", err is None and res and res.get("killed") == "deer", (res, err))
    await asyncio.sleep(S.World.BOLT_EVERY + 0.05)
    world.animals["deer2"] = {"id": "deer2", "kind": "deer", "face": FACE, "u": tu + 12, "v": tv - 10, "h": th - 0.6, "yaw": 0.0, "hp": 3}
    res, _, err = await world.bolt(a, cid, north, {"animal": "deer2"})
    check("3. an animal 12 m off the bolt's line is missed", err == "missed", err)
    world.animals["deer3"] = {"id": "deer3", "kind": "deer", "face": FACE, "u": tu, "v": tv - 40, "h": th - 0.6, "yaw": 0.0, "hp": 3}
    res, _, err = await world.bolt(a, cid, north, {"animal": "deer3"})
    check("…an animal behind the craft is missed", err == "missed", err)
    world.animals["deer4"] = {"id": "deer4", "kind": "deer", "face": FACE, "u": tu, "v": tv - 30 + S.World.BOLT_RANGE + 50, "h": th - 0.6, "yaw": 0.0, "hp": 3}
    res, _, err = await world.bolt(a, cid, north, {"animal": "deer4"})
    check("…and one past the range", err == "missed", err)
    ground = [FACE, r0["wu"], r0["wv"], r0["top"]]
    c["pose"] = [FACE, r0["wu"] + 0.5, r0["wv"] - 20 + 0.5, r0["top"] + 0.5, 0.0]
    res, _, err = await world.bolt(a, cid, north, {"cell": ground})
    check("…the ground under a tree is no tree", err and "trees" in err, err)
    res, _, err = await world.bolt(b, cid, north, None)
    check("…a craft the caller does not fly fires nothing", err == "you are not flying that", err)
    c["slots"] = [0] * len(c["pieces"])
    await asyncio.sleep(S.World.BOLT_EVERY + 0.05)
    res, _, err = await world.bolt(a, cid, north, None)
    check("…nor one with no cannon bound to a key", err == "no cannon bound to a key", err)
    c["slots"] = [1 if i == gi else 0 for i in range(len(c["pieces"]))]
    await asyncio.sleep(S.World.BOLT_EVERY + 0.05)
    res, _, err = await world.bolt(a, cid, north, None)
    check("4. a bolt into open air is fired and strikes nothing", err is None and res == {"hit": None}, (res, err))
    # a stranger's titled plot keeps its trees: B, in a craft with a cannon over the commons, at a tree on A's plot
    world.player(b)["items"].update({"steel_plate": 4, "thruster": 2, "pilot_seat": 1})
    added, _, refused = await world.boxes(b, PB, [[600, 600, 20000, 400, 150, 5, PLATE], [760, 640, 20005, 80, 90, 110, SEAT], [700, 500, 20000, 100, 100, 140, THR], gun], [])
    cb, _, err = await world.board(b, PB, [760, 640, 20005, 80, 90, 110, SEAT])
    cb["slots"] = [1 if S.is_cannon(p) else 0 for p in cb["pieces"]]
    r1 = roots[1]; w1 = await trunk_cell(world, r1)
    cb["pose"] = [FACE, w1[1] + 0.5, w1[2] + 0.5 - 30, w1[3] + 0.5, 0.0]
    res, _, err = await world.bolt(b, cb["id"], north, {"cell": list(w1)})
    check("3. a stranger's bolt at a tree on A's titled plot is refused: not your plot", err and err.startswith("not your plot"), err)
    world.oracle.kill(); await world.oracle.wait()
    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
