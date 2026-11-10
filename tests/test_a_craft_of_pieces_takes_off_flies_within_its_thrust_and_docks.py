"""
FLIGHT on the world server (#147, doc/land-tech-to-flight.md; "you must add actual physics like engines and gravity to
the game and build a real usable xfighter", operator 2026-11-09). scripts/land_server.py board / fly / leave / dock:

  1. a craft is the pieces touching a pilot seat (and those touching them): boarding the seat, where the caller may build,
     lifts exactly those off the plot into a craft — the plot keeps what does not touch; its mass is the pieces' volume x
     their density (a unit part by its own mass), its thrust 30 kN a thruster;
  2. no thruster touching, no craft; another's plot, no take-off; a stranger cannot board someone's parked craft;
  3. the pilot's poses are taken within the craft's top speed (vmax x time + slack) and refused beyond it — no teleport;
     the server answers a refused pose with the one it holds;
  4. leaving parks it; a restart keeps the craft, parked (no pilot);
  5. docking sets it down as pieces on the plot under the seat, turned to the nearest quarter turn — refused where the
     owner may not build; the craft is then gone; turn_pieces turns a point (x, z) to (z, -x) at +90°;
  6. players near are sent the craft — its pieces the first time, then its pose.

Run: python3 tests/test_a_craft_of_pieces_takes_off_flies_within_its_thrust_and_docks.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-craft-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, math, sys, time

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
PA = 4995 * L.FACE_N + 3435                          # A's titled plot
PB = PA + 1                                          # B's
PLATE, THR, SEAT, PLANKS = 64, 65, 66, 9


def fake_exec():
    holders = {"7001": A["address"], "7002": Bk["address"]}

    async def assets(req):
        return web.json_response({"assets": [{"id": "7001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA))},
                                             {"id": "7002", "issuer": L.ISSUER, "seed": str(L.plot_seed(PB))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": req.query["id"]}, "holders": {holders[req.query["id"]]: "1"}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_craft_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = __import__("aiohttp").ClientSession()
    a, b = A["address"], Bk["address"]
    world.player(a)["items"].update({"steel_plate": 3, "thruster": 2, "pilot_seat": 2, "planks": 2})

    # 1. a small craft: a plate hull 4 m x 1.5 m x 5 cm, a seat on it, a thruster behind; a plank shed apart from it
    hull = [600, 600, 20000, 400, 150, 5, PLATE]
    seat = [760, 640, 20005, 80, 90, 110, SEAT]
    thr = [700, 500, 20000, 100, 100, 140, THR]                   # touches the hull's south edge (z 500..600)
    shed = [100, 100, 20000, 100, 100, 100, PLANKS]
    added, _, refused = await world.boxes(a, PA, [hull, seat, thr, shed], [])
    check("the craft's pieces and a shed apart are built", len(added) == 4 and not refused, refused)
    c, parts, err = await world.board(a, PA, seat)
    check("boarding the seat makes a craft of exactly the pieces touching it", err is None and sorted(parts) == sorted([hull, seat, thr]), (err, parts))
    check("…they leave the plot, the shed stays", world.plots[PA]["boxes"] == [shed], world.plots[PA]["boxes"])
    mass = 4 * 1.5 * 0.05 * 1.5 + 0.15 + 0.4
    check("its mass is volume x density, unit parts by their own mass", abs(c["mass"] - mass) < 1e-6 and c["thrust"] == 30, (c["mass"], mass, c["thrust"]))
    check("…kept relative to the seat, which is the craft's origin", [0, 0, 0] == [c["pieces"][[x[6] for x in c["pieces"]].index(SEAT)][i] + (40, 45, 0)[i] for i in range(3)], c["pieces"])

    # 2. the rules
    s2 = [1200, 1200, 20005, 80, 90, 110, SEAT]
    await world.boxes(a, PA, [s2], [])
    _, _, err = await world.board(a, PA, s2)
    check("no thruster touching, no craft", err and "thruster" in err, err)
    world.player(b)["items"].update({"pilot_seat": 1, "thruster": 1})
    await world.boxes(b, PB, [[500, 500, 20000, 80, 90, 110, SEAT], [580, 500, 20000, 100, 100, 140, THR]], [])
    _, _, err = await world.board(a, PB, [500, 500, 20000, 80, 90, 110, SEAT])
    check("no take-off from another's plot", err and "not your plot" in err, err)

    # 3. flying within its top speed
    cid = c["id"]
    p0 = list(c["pose"])
    time.sleep(0.2)
    ok_pose = [p0[0], p0[1] + 5, p0[2], p0[3] + 3, 0.5]
    check("a pose within its speed is taken", world.fly(a, cid, ok_pose) is None and world.crafts[cid]["pose"][1] == round(p0[1] + 5, 3))
    check("a jump of 500 m is refused (no teleport)", world.fly(a, cid, [p0[0], p0[1] + 500, p0[2], p0[3], 0.5]) and world.crafts[cid]["pose"][1] == round(p0[1] + 5, 3))
    check("only its pilot says where it is", world.fly(b, cid, ok_pose) is not None)

    # 3b. the engines' work (#171): kept as its pilot says it, for others to see its exhaust; nonsense never stored
    time.sleep(0.1)
    world.fly(a, cid, ok_pose, [0.724, 0.72, 0.0, 0.0])
    check("the pilot's engine work is kept with the craft", world.crafts[cid].get("eng") == [0.72, 0.72, 0.0, 0.0], world.crafts[cid].get("eng"))
    for bad in ([2, 0, 0, 0], [0.5, 0.5, 0, 9], ["x", 0, 0, 0], [0.5, 0.5, 0], [float("nan"), 0, 0, 0], [True, 0, 0, 0], "full"):
        world.fly(a, cid, ok_pose, bad)
    check("engine work out of range or not numbers is never stored", world.crafts[cid].get("eng") == [0.72, 0.72, 0.0, 0.0], world.crafts[cid].get("eng"))

    # 4. parked, and kept
    check("leaving parks it, and its engines stop", world.leave(a, cid) is None and world.crafts[cid]["pilot"] is None and world.crafts[cid].get("eng") is None)
    _, _, err = await world.board(b, cid=cid)
    check("a stranger cannot board it", err and "owner" in err, err)
    _, _, err = await world.board(a, cid=cid)
    check("its owner boards it again", err is None and world.crafts[cid]["pilot"] == a, err)
    world.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "")
    check("a restart keeps the craft, parked", cid in w2.crafts and w2.crafts[cid]["pilot"] is None and w2.crafts[cid]["pieces"] == world.crafts[cid]["pieces"])

    # 5. docking: over B's plot refused; over A's, turned a quarter (yaw ~ 90°), it becomes pieces again
    world.crafts[cid]["pose"] = [0, (PB % L.FACE_N) * L.PLOT + 8.0, (PB // L.FACE_N) * L.PLOT + 8.0, 200.0, 0.0]
    _, _, err = await world.dock(a, cid)
    check("docking where the owner may not build is refused", err and "not your plot" in err, err)
    world.crafts[cid]["pose"] = [0, (PA % L.FACE_N) * L.PLOT + 8.0, (PA // L.FACE_N) * L.PLOT + 8.0, 200.0, math.pi / 2 + 0.2]
    p, add, err = await world.dock(a, cid)
    turned = S.turn_pieces(world.crafts.get(cid, {"pieces": []})["pieces"], 1) if cid in world.crafts else None
    check("docking on its owner's plot sets it down as pieces, and the craft is gone", err is None and p == PA and len(add) == 3 and cid not in world.crafts, (err, p, add))
    hullp = next(x for x in add if x[6] == PLATE)
    check("…turned a quarter: the 4 m hull now runs north-south", hullp[3] == 150 and hullp[4] == 400, hullp)
    check("turn_pieces at +90° sends (x, z) to (z, -x)", S.turn_pieces([[10, 20, 0, 30, 40, 5, 9]], 1) == [[20, -40, 0, 40, 30, 5, 9]])
    check("…a slope rising east rises south", S.turn_pieces([[0, 0, 0, 10, 10, 10, 9, 1]], 1)[0][7] == 4)

    # 6. players near are sent it
    c2, _, err = await world.board(a, PA, next(x for x in add if x[6] == SEAT))
    class Sock:
        def __init__(self): self.sent = []
        async def send_json(self, m): self.sent.append(m)
    hub, sk = S.Hub(), Sock()
    hub.socks = {sk: {"id": 1, "who": b, "pos": list(c2["pose"]), "watch": set()}}
    await hub.positions(world); await hub.positions(world)
    first, second = sk.sent[0]["crafts"], sk.sent[1]["crafts"]
    check("a player near is sent the craft with its pieces, then only its pose", err is None and first and "pieces" in first[0] and second and "pieces" not in second[0] and second[0]["pose"] == c2["pose"], (err, first[:1], second[:1]))
    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
