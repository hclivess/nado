"""
GADGET KEYS (operator 2026-11-12, in an X fighter parked on a roof — an aircraft that needs a run to lift: "maybe add
some thrusters and bind them to some keys", "THE BINDING GOES TO BLOCK ACTIVATION OF A PARTICULAR GADGET IT MUST BE
UNIVERSAL", "configurable at the gadget", "everything should have a configure and activate"). scripts/land_server.py
is_gadget / gadget_key / World.bind / World.bind_craft / board / dock / boxes:
  1. a key is set AT THE GADGET on a plot: the plot's builder binds a thruster to key 1 and an engine part to key 2; a
     plank is no gadget (refused), a stranger is refused, a key past 9 is refused, 0 takes the key away; the plot's
     payload to the page carries the gadgets' keys beside the boxes;
  2. boarding carries the keys onto the craft, one slot a piece, in the pieces' order; the plot forgets them;
  3. on the craft: the owner sets a key at a piece of the craft (and may not at a plank, nor a stranger at anything,
     nor anyone while another flies it); the page is sent the slots with the pieces;
  4. docking carries the keys back to the plot pieces; boarding again brings them back; taking a bound piece down drops
     its key; the keys survive a restart (the plot file and crafts.json hold them).
Run: python3 tests/test_the_world_server_keeps_a_gadgets_key_at_the_gadget_through_boarding_and_docking.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-gadget-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, sys

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
PA = 4995 * L.FACE_N + 3435
PLATE, THR, SEAT, PLANKS = 64, 65, 66, 9
ENGINE = next(c for c in range(16, 256) if S.part_of(c) and S.part_of(c)[0] == S.P_ENGINE)


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


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_gadget_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = __import__("aiohttp").ClientSession()
    a, b = A["address"], Bk["address"]
    world.player(a)["items"].update({"steel_plate": 6, "thruster": 6, "pilot_seat": 2, "planks": 2})
    world.work = lambda who, s: True
    hull = [600, 600, 20000, 400, 150, 5, PLATE]
    seat = [760, 640, 20005, 80, 90, 110, SEAT]
    thr = [700, 500, 20000, 100, 100, 140, THR]                   # a thruster block, touching the hull's south edge
    eng = [900, 500, 20000, 100, 100, 140, THR, ENGINE]           # an engine part, likewise
    shed = [100, 100, 20000, 100, 100, 100, PLANKS]
    added, _, refused = await world.boxes(a, PA, [hull, seat, thr, eng, shed], [])
    check("the craft's pieces and a shed are built", len(added) == 5 and not refused, refused)
    check("a thruster block and an engine part are gadgets; a plate, a seat and a plank are not", S.is_gadget(thr) and S.is_gadget(eng) and not S.is_gadget(hull) and not S.is_gadget(seat) and not S.is_gadget(shed))

    # 1. configure at the gadget, on the plot
    check("the builder binds the thruster to key 1", await world.bind(a, PA, thr, 1) is None)
    check("…and the engine part to key 2", await world.bind(a, PA, eng, 2) is None)
    check("a plank takes no key", (await world.bind(a, PA, shed, 3) or "").startswith("that does nothing"))
    check("a stranger sets no key here", (await world.bind(b, PA, thr, 3) or "").startswith("not yours"))
    check("a key past 9, or not a number, is refused", (await world.bind(a, PA, thr, 10) or "").startswith("a key is") and (await world.bind(a, PA, thr, "1") or "").startswith("a key is") and (await world.bind(a, PA, thr, True) or "").startswith("a key is"))
    check("a piece that is not there takes no key", (await world.bind(a, PA, [1, 1, 20000, 1, 1, 1, THR], 1) or "").startswith("no such piece"))
    rec = world.plots[PA]
    check("the plot keeps {gadget_key: slot}", rec.get("gadgets") == {S.gadget_key(thr): 1, S.gadget_key(eng): 2}, rec.get("gadgets"))
    check("0 takes a key away", await world.bind(a, PA, eng, 0) is None and rec["gadgets"] == {S.gadget_key(thr): 1})
    await world.bind(a, PA, eng, 2)
    # the page's payload
    world.flush()
    body = __import__("json").load(open(os.path.join(data, f"{PA}.json")))
    check("the plot file holds the gadgets' keys", body.get("gadgets") == {S.gadget_key(thr): 1, S.gadget_key(eng): 2}, body.get("gadgets"))

    # 2. boarding carries them
    c, parts, err = await world.board(a, PA, seat)
    check("boarding makes the craft of the pieces touching the seat", err is None and sorted(parts) == sorted([hull, seat, thr, eng]), (err, parts))
    want = [{S.gadget_key(thr): 1, S.gadget_key(eng): 2}.get(S.gadget_key(x), 0) for x in parts]
    check("the craft carries one slot a piece, in the pieces' order: the thruster's 1, the engine's 2, the rest 0", c["slots"] == want and sorted(c["slots"]) == [0, 0, 1, 2], (c["slots"], want))
    check("the plot forgets them", not rec.get("gadgets"), rec.get("gadgets"))

    # 3. on the craft
    cid = c["id"]
    i_thr = next(i for i, x in enumerate(parts) if x[6] == THR and len(x) == 7)
    i_hull = next(i for i, x in enumerate(parts) if x[6] == PLATE)
    check("the owner, flying it, sets the thruster's key to 3", world.bind_craft(a, cid, i_thr, 3) is None and c["slots"][i_thr] == 3)
    check("a plate on the craft takes no key", (world.bind_craft(a, cid, i_hull, 1) or "").startswith("that does nothing"))
    check("a stranger sets nothing on it", (world.bind_craft(b, cid, i_thr, 1) or "") == "not your craft")
    check("a piece that is not on it is refused", (world.bind_craft(a, cid, 99, 1) or "").startswith("no such piece"))
    check("a key past 9 is refused", (world.bind_craft(a, cid, i_thr, 12) or "").startswith("a key is"))
    check("the craft's version moved (every page is sent its pieces and slots again)", c.get("ver", 0) >= 1)
    world.leave(a, cid)
    c["pilot"] = b                                                 # someone else at the controls (a handover's flight)
    check("while another flies it, its owner sets no key", (world.bind_craft(a, cid, i_thr, 1) or "") == "someone is flying it")
    c["pilot"] = None
    # the page is sent the slots with the pieces (the players message reads crafts_near and adds c["slots"])
    near = world.crafts_near(c["pose"], 50)
    check("crafts_near finds it, with its slots", any(x["id"] == cid and x.get("slots") == c["slots"] for x in near))

    # 4. docking carries them back; boarding again; taking a piece down drops its key; a restart keeps them
    world.flush()
    saved = __import__("json").load(open(os.path.join(data, "crafts.json")))
    check("crafts.json holds the slots", saved[cid]["slots"] == c["slots"])
    p, add, err = await world.dock(a, cid)
    check("docking sets the pieces down", err is None and p == PA and len(add) == 4, err)
    g = world.plots[PA].get("gadgets") or {}
    thr2 = next(x for x in add if x[6] == THR and len(x) == 7); eng2 = next(x for x in add if x[6] == THR and len(x) > 7)
    check("the plot has the keys back at the pieces: the thruster's 3, the engine's 2", g == {S.gadget_key(thr2): 3, S.gadget_key(eng2): 2}, g)
    world.flush()
    world2 = S.World(data, "http://127.0.0.1:1", "")
    check("a restart reads them back from the plot file", (world2.plots[PA].get("gadgets") or {}) == g)
    c2, parts2, err = await world.board(a, PA, next(x for x in add if x[6] == SEAT))
    check("boarding again brings them onto the craft", err is None and sorted(c2["slots"]) == [0, 0, 2, 3])
    p, add, err = await world.dock(a, c2["id"])
    thr3 = next(x for x in add if x[6] == THR and len(x) == 7)
    _, removed, refused = await world.boxes(a, PA, [], [thr3])
    check("the thruster taken down drops its key; the engine keeps its own", len(removed) == 1 and S.gadget_key(thr3) not in world.plots[PA]["gadgets"] and len(world.plots[PA]["gadgets"]) == 1, (refused, world.plots[PA].get("gadgets")))
    world.oracle.kill() if getattr(world, "oracle", None) else None
    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
