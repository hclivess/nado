"""
"im getting attacked by a deer 500 meters above the ground" (operator, 2026-11-11, flying the X-wing; #192). Two faults
made it: the world server kept a PILOT at the spot they boarded — their "pos" reports were refused as faster than walking
(pace, #167), while the craft's own "fly" reports, bounded by its top speed, never moved the player's place — and an animal
charged any player within `charge` metres by ground distance alone, the warning reaching someone in the air.

  1. the herd: a stag charges and strikes a player on the ground beside it (as before), and neither charges nor strikes
     the same player 500 m up — nor one CHARGE_RISE above it on a roof; a player up a slope within CHARGE_RISE is charged;
  2. the hub: a pilot's accepted "fly" is their place — the socket's pos is the craft's pose (what the herd, the market and
     Hub.where read), and their next "pos" report from beside the craft is paced from it, not from the boarding spot.

Run: python3 tests/test_an_animal_charges_only_what_it_can_reach_and_a_pilot_is_where_the_craft_is.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-reach-air-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, math, subprocess, sys
sys.stdout.reconfigure(line_buffering=True)   # (CI's runner kills a hung test: the checks printed so far must be in its log)

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
A = generate_keydict()
RULES = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
HN = RULES["hunting"]
PA = 4995 * L.FACE_N + 3435                          # A's titled plot (the craft is built and boarded there)
PLATE, THR, SEAT = 64, 65, 66

js = """
const W = await import(%s);
const u = 55031, v = 79905, c = W.column(0, u, v);
console.log(JSON.stringify({ pos: [0, u + 0.5, v + 0.5, c.height + 0.05, 0] }));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
HERE = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=120).stdout)


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


async def login(c, kd):
    ch = await (await c.get("/land/api/challenge?kind=agent")).json()
    msg = blake2b_hash([S.DOMAIN, S.AGENT_ORIGIN, kd["address"], ch["nonce"], ch["issued"]], 32)
    r = await c.post("/land/api/agent_login", json={"address": kd["address"], "public_key": kd["public_key"],
                                                    "signature": sign(kd["private_key"], unhex(msg)), "nonce": ch["nonce"]})
    return (await r.json())["token"]


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_reach_air_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    world.http = __import__("aiohttp").ClientSession()
    hub = S.Hub()
    c = TestClient(TestServer(S.make_app(world, hub, "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    tok = await login(c, A)
    c.server.app["bg"][-1].cancel()                              # the test steps the herd itself
    me, pos = A["address"], HERE["pos"]
    dist = lambda a: math.hypot(a["u"] - pos[1], a["v"] - pos[2])

    def stag(du):
        world.animal_seq += 1
        a = {"id": world.animal_seq, "kind": "deer", "face": 0, "u": pos[1] + du, "v": pos[2], "h": pos[3], "yaw": 0.0,
             "hp": HN["species"]["deer"]["hp"], "go": 1e18, "flee": 0, "angry": True}
        world.animals[a["id"]] = a
        return a

    async def step(q, n=1):
        hits = []
        for _ in range(n):
            hits += await world.herd([q], players=[(me, q)]) or []
        return hits

    async def charged(s, q):
        """Does the stag turn on the player at q? The warning (world.charges) is given once, on the step it turns, and
        it closes in over the steps after. (The stag's own height follows the ground it moves over — a metre or two
        across these steps — so a case's height is set well clear of CHARGE_RISE, not at its edge.)"""
        s["u"] = pos[1] + 8; s["v"] = pos[2]
        d0, warned = dist(s), False
        for _ in range(2):
            await step(q)
            warned = warned or any(ch[0] == me for ch in world.charges)
        return warned, d0 - dist(s)

    # ---- 1. the herd: reach ------------------------------------------------------------------------------------------
    s = stag(8)
    warned, closed = await charged(s, pos)
    check("on the ground beside it, a stag charges the player: the warning, then it closes in", warned and closed > 1, (warned, closed))
    s["u"] = pos[1] + 1.2
    hits = await step(pos)
    check("…and strikes within reach", hits == [(me, HN["species"]["deer"]["damage"], "deer")], hits)
    # the same player, 500 m up in a craft over the very same spot (heights from the stag's own: the herd keeps it on its ground)
    up = list(pos); up[3] = s["h"] + 500
    s["bite"] = 0
    warned, closed = await charged(s, up)
    check("500 m up, it neither charges (no warning)", not warned and closed < 0.01, (warned, closed))
    s["u"] = pos[1] + 1.2
    hits = await step(up)
    check("…nor strikes", hits == [], hits)
    roof = list(pos); roof[3] = s["h"] + S.CHARGE_RISE + 3
    warned, closed = await charged(s, roof)
    check("on a roof above CHARGE_RISE: not charged either", not warned and closed < 0.01, (S.CHARGE_RISE, warned, closed))
    slope = list(pos); slope[3] = s["h"] + S.CHARGE_RISE - 4
    warned, closed = await charged(s, slope)
    check("up a slope within CHARGE_RISE: charged (a hillside it runs up)", warned and closed > 1, (warned, closed))

    # ---- 2. the hub: a pilot is where the craft is ------------------------------------------------------------------
    world.player(me)["items"].update({"steel_plate": 3, "thruster": 2, "pilot_seat": 1})
    hull = [600, 600, 20000, 400, 150, 5, PLATE]
    seat = [760, 640, 20005, 80, 90, 110, SEAT]
    thr = [700, 500, 20000, 100, 100, 140, THR]
    added, _, refused = await world.boxes(me, PA, [hull, seat, thr], [])
    check("a craft's pieces are built on the player's plot", len(added) == 3 and not refused, refused)
    cobj, parts, err = await world.board(me, PA, seat)
    check("…and boarded", err is None and cobj, err)
    craft = cobj["id"]
    cp = world.crafts[craft]["pose"]
    ws = await c.ws_connect("/land/ws?token=" + tok)
    try:
        ground = [cp[0], cp[1], cp[2], cp[3], 0.0]
        await ws.send_json({"t": "pos", "p": ground}); await asyncio.sleep(0.3)
        st = next(s for s in hub.socks.values() if s.get("who") == me)
        check("before the flight the socket's place is the boarding spot", st.get("pos") and abs(st["pos"][3] - cp[3]) < 0.01, st.get("pos"))
        # the flight: pose reports within the craft's top speed, up to 500 m — one every 0.2 s as the page sends them
        h = cp[3]
        for _ in range(12):
            h += min(RULES["flight"]["vmax"] * 0.2 * 0.9, 25)            # (25 m a report: well under the top speed and the world's ceiling)
            await ws.send_json({"t": "fly", "craft": craft, "pose": [cp[0], cp[1], cp[2], h, 0.0]})
            await asyncio.sleep(0.2)
        st = next(s for s in hub.socks.values() if s.get("who") == me)
        check("after it, the socket's place is the craft's pose (what the herd and the market read)", st["pos"][3] > cp[3] + 10 and abs(st["pos"][3] - world.crafts[craft]["pose"][3]) < 0.01, (st["pos"], world.crafts[craft]["pose"]))
        check("…and Hub.where says so too", abs(hub.where(world, me)[3] - st["pos"][3]) < 0.01, hub.where(world, me))
        # a "pos" from beside the craft (the pilot's own report, metres from the boarding spot) is paced from the craft
        got = []
        await ws.send_json({"t": "pos", "p": [cp[0], cp[1] + 1, cp[2], h, 0.0]}); await asyncio.sleep(0.4)
        while True:
            try:
                got.append(await ws.receive_json(timeout=0.3))
            except Exception:
                break
        fixes = [m for m in got if m.get("t") == "pos_fix"]
        st = next(s for s in hub.socks.values() if s.get("who") == me)
        check("a pos report beside the craft is not refused as a journey from the boarding spot", not fixes and abs(st["pos"][3] - h) < 0.01, (fixes, st["pos"]))
        # an AIRCRAFT's pose (#191) carries pitch and roll: seven numbers, kept; angles past a full turn are refused
        err = world.fly(me, craft, [cp[0], cp[1], cp[2], h, 0.3, -0.2, 0.9])
        check("a seven-number pose (yaw, pitch, roll) is taken and kept whole", err is None and len(world.crafts[craft]["pose"]) == 7 and world.crafts[craft]["pose"][6] == 0.9, (err, world.crafts[craft]["pose"]))
        err = world.fly(me, craft, [cp[0], cp[1], cp[2], h, 0.3, 9.0, 0.0])
        check("…a pitch past a half turn is not a place", err == "not a place", err)
        err = world.fly(me, craft, [cp[0], cp[1], cp[2], h, -14.647, 0.1, 0.0])
        check("…but a yaw of many turns is (the X-wing's parked yaw was -14.647: the page counts turns)", err is None, err)
        # an aircraft lands and is set down as pieces with its seven-number pose (dock unpacked five, and an aircraft could
        # never be docked, 2026-11-12)
        while h > cp[3] + 1:                                        # back down, 25 m a report (the top speed bounds a report)
            h = max(cp[3], h - 25); err = world.fly(me, craft, [cp[0], cp[1], cp[2], h, 0.0, 0.0, 0.0])
            check("…a report on the way down is taken", err is None, err) if err else None
        world.crafts[craft]["pilot"] = me
        dp, dadd, derr = await world.dock(me, craft)
        check("a craft with a seven-number pose is set down as pieces by /dock", err is None and derr is None and dp == PA and len(dadd) == 3, (err, derr, dp, dadd))
        cobj, parts, err = await world.board(me, PA, [b for b in dadd if b[6] == SEAT][0])
        check("…and boarded again", err is None and cobj, err)
        craft = cobj["id"]; cp = world.crafts[craft]["pose"]; h = cp[3]
        for _ in range(4):
            h += 25; err = world.fly(me, craft, [cp[0], cp[1], cp[2], h, 0.3, 0.0, 0.0])
        check("…flown up again", err is None, err)
        # the crafts API (GET /land/api/crafts near a place) lists the flying craft at its CURRENT pose (#191: a page test
        # found it missing after a short roll)
        near = await (await c.get(f"/land/api/crafts?face={cp[0]}&u={cp[1]}&v={cp[2]}")).json()
        check("the crafts API lists the flying craft at its current pose", any(x["id"] == craft and abs(x["pose"][3] - h) < 0.01 for x in near.get("crafts", [])), near)
        far = await (await c.get(f"/land/api/crafts?face={cp[0]}&u={cp[1] + 150}&v={cp[2] + 150}")).json()
        check("…and from 212 m away too (within its 192 m square)", any(x["id"] == craft for x in far.get("crafts", [])), far)
        # THE EVENT TRACE (#194): the page's events land in the player's bounded trace file, with the server's time
        await ws.send_json({"t": "trace", "events": [{"t": 1700000000000, "k": "leave", "craft": craft, "from": [0, 1, 2, 3, 0], "to": [0, 2, 2, 3, 0], "tried": 2}, {"k": 5}, "junk"]})
        await asyncio.sleep(0.4)
        tp = os.path.join(data, "trace", me + ".jsonl")
        lines = open(tp).read().splitlines() if os.path.exists(tp) else []
        check("a trace batch is kept, one line an event, the malformed ones dropped, the server's time added", len(lines) == 1 and json.loads(lines[0])["k"] == "leave" and "srv" in json.loads(lines[0]), lines)
        big = [{"t": 1, "k": "x", "pad": "p" * 1000} for _ in range(50)]
        for _ in range(30):
            world.trace_append(me, big)
        size = os.path.getsize(tp)
        check("…and the file stays bounded (cut to its newest half megabyte)", world.TRACE_KEEP // 2 < size <= 2 * world.TRACE_KEEP + 2000, size)
        check("…every kept line whole", all(json.loads(l)["k"] == "x" for l in open(tp).read().splitlines()[1:]))
        check("a visitor's trace is not kept", world.trace_append(None, big) == 0 and world.trace_append("", big) == 0)
        err = world.fly(me, craft, [cp[0], cp[1], cp[2], h, 0.3, 0.0])
        check("…and six numbers are no pose", err == "not a place", err)
    finally:
        await ws.close()
    await c.close(); await ex.close(); await world.http.close()


asyncio.run(main())
_report.done()
