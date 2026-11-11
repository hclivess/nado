"""
NO SECOND DEATH BEHIND THE DEATH CARD, AND A CHARGE IS ANNOUNCED (#176; the playtest of 2026-11-11: a new player killed
twelve times in ninety minutes, nine of them in one incident behind the death card, and the town agent's record at 1,103
deaths). Through the page's own socket and the world server's own herd step (scripts/land_server.py Hub.herd_step):

  * a stag that turns on a player tells their page so ONCE per charge — which animal and where it is — while it is still
    metres off; and again when a new charge begins;
  * a strike says where it came from;
  * a player who dies is kept by the world server at the place they wake (the landing here) from that moment: their
    page's socket stands there, whatever the page — still at the death spot behind the card — goes on reporting;
  * those reports are dropped without a word (no "Faster than anyone can go" for the dead);
  * so with the grace long over and the page never touched, nothing strikes them again: one death, not one every grace_s;
  * the page reporting from the wake place wakes them: the grace runs from then, and the pace rule holds from there.

Run: python3 tests/test_a_player_who_dies_is_kept_at_the_place_they_wake_and_is_not_struck_again_behind_the_death_card.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-deathloop-")
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
    return (await r.json())["token"]


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_deathloop_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    hub = S.Hub()
    c = TestClient(TestServer(S.make_app(world, hub, "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    tok = await login(c, A)
    c.server.app["bg"][-1].cancel()                              # the test steps the herd itself, by the hub's own step
    me, pos = A["address"], HERE["pos"]
    pl = world.player(me)
    ws = await c.ws_connect("/land/ws?token=" + tok)

    async def heard(wait=0.6):
        """Everything the page's socket is sent in the next `wait` seconds (the server's own loops keep talking: a fixed
        time, not a wait for quiet)."""
        got, end = [], time.time() + wait
        while time.time() < end:
            try:
                got.append(await ws.receive_json(timeout=max(0.05, end - time.time())))
            except (asyncio.TimeoutError, TypeError):
                break
        return got
    of = lambda got, t: [m for m in got if m.get("t") == t]

    def animal(du, angry=True):
        world.animal_seq += 1
        a = {"id": world.animal_seq, "kind": "deer", "face": 0, "u": pos[1] + du, "v": pos[2], "h": pos[3], "yaw": 0.0,
             "hp": HN["species"]["deer"]["hp"], "go": 1e18, "flee": 0, "angry": angry}
        world.animals[a["id"]] = a
        return a

    await ws.send_json({"t": "pos", "p": pos})
    await heard()
    st = next(iter(hub.socks.values()))
    check("the page stands in the wild", st["pos"] and abs(st["pos"][1] - pos[1]) < 0.01 and not world.tame(0, pos[1], pos[2]), st["pos"])

    # ---- the charge is announced, once ----------------------------------------------------------------------------------
    stag = animal(8)
    await hub.herd_step(world)
    ch = of(await heard(), "charge")
    check("a stag turning on the player tells their page: which animal, what it is, where it is",
          len(ch) == 1 and ch[0]["id"] == stag["id"] and ch[0]["by"] == "deer" and abs(ch[0]["at"][0] - (pos[1] + 8)) < 2.1, ch)
    await hub.herd_step(world); await hub.herd_step(world)
    check("…once per charge, not every step", of(await heard(), "charge") == [])
    stag["u"] = pos[1] + 40                                       # it loses them…
    await hub.herd_step(world)
    stag["u"] = pos[1] + 8                                        # …and turns on them again
    await hub.herd_step(world)
    check("a new charge is announced again", len(of(await heard(), "charge")) == 1)

    # ---- a strike says where it came from --------------------------------------------------------------------------------
    stag["u"] = pos[1] + 1.2
    await hub.herd_step(world)
    hu = of(await heard(), "hurt")
    check("a strike tells the page where it came from", len(hu) == 1 and hu[0]["hp"] == HL["max"] - HN["species"]["deer"]["damage"]
          and abs(hu[0]["at"][0] - (pos[1] + 1.2)) < 0.01 and abs(hu[0]["at"][1] - pos[2]) < 0.01, hu)

    # ---- death: kept at the wake place from that moment -------------------------------------------------------------------
    pl["hp"] = 1; stag["bite"] = 0
    await hub.herd_step(world)
    got = await heard()
    land = S.landing()
    check("struck at 1 health, the player dies", len(of(got, "died")) == 1 and pl["deaths"] == 1, got)
    check("the world keeps them at the landing from that moment", pl["pos"][:3] == land and len(pl["pos"]) == 5, pl["pos"])
    check("…and so does their page's socket, marked dead", st["pos"][:3] == land and st["dead"] == land, (st["pos"], st.get("dead")))

    # ---- the page, behind the death card, goes on reporting the death spot ------------------------------------------------
    for _ in range(3):
        await ws.send_json({"t": "pos", "p": pos})
    got = await heard()
    check("its reports are dropped: the socket stays at the landing", st["pos"][:3] == land and st["dead"] == land, st["pos"])
    check("…without a word — no 'faster than anyone can go' for the dead", of(got, "pos_fix") == [], got)

    # ---- the grace long over, the page never touched: no second death -----------------------------------------------------
    pl["grace"] = 0
    killer = animal(1.2)                                          # an angry stag standing on the death spot
    for _ in range(6):
        killer["bite"] = 0
        await hub.herd_step(world)
    got = await heard()
    check("with the grace over and the card never answered, nothing strikes them again: one death, not one every grace_s",
          pl["deaths"] == 1 and pl["hp"] == HL["max"] and of(got, "died") == [] and of(got, "hurt") == [], (pl["deaths"], pl["hp"], got))

    # ---- waking: the page reports from the wake place ------------------------------------------------------------------
    t0 = time.time()
    await ws.send_json({"t": "pos", "p": [0, land[1] + 1.0, land[2] + 0.5, pos[3], 0]})
    await heard()
    check("the page at the wake place has woken", not st["dead"] and abs(st["pos"][1] - (land[1] + 1.0)) < 0.01, (st.get("dead"), st["pos"]))
    check("…and the grace runs from the waking", pl["grace"] >= t0 + HL["grace_s"] - 0.01, pl["grace"] - t0)
    await ws.send_json({"t": "pos", "p": [0, land[1] + 4.0, land[2] + 0.5, pos[3], 0]})
    await heard()
    check("they walk on from there", abs(st["pos"][1] - (land[1] + 4.0)) < 0.01, st["pos"])
    await ws.send_json({"t": "pos", "p": [0, land[1] + 900, land[2], pos[3], 0]})
    fx = of(await heard(), "pos_fix")
    check("…and the pace rule holds again: 900 m in a moment is put back", len(fx) == 1 and fx[0]["why"] == "pace" and abs(fx[0]["p"][1] - (land[1] + 4.0)) < 0.01, fx)

    await ws.close()
    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
