"""
"maybe add fine rotation if needed" (operator 2026-11-10, #169): the evidence (land research fighter/GEOMETRY.md) — a
fighter's 40° swept wing and an X of wings cannot be pieces square to the plot. The world server (scripts/land_server.py
box_ok, boxes_overlap, commitment_bytes, turn_pieces), over HTTP:

  * a piece turned by yaw, pitch and roll (tenths of a degree, 9th-11th numbers) is placed, paid by its own volume;
  * a turned piece cutting into another is refused; two turned plates whose boxes overlap but whose bodies do not are
    both placed (the oriented-box test, not the box around them);
  * turned out of the plot (its turned reach), refused; a unit part (a chest) is never turned; a turn of 0, 0, 0 is
    kept as the plain 7 numbers;
  * the plot commits v4 — byte for byte the browser's code — with a turned piece, and the very v3 commitment it had
    before once the turned piece is taken down (anchors made before rotation stay the plots' commitments);
  * a turned piece in a craft goes round with its quarter turns and comes back where it was after four.

Run: python3 tests/test_a_built_piece_turns_by_yaw_pitch_and_roll_and_its_plot_commits_it.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-turned-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys

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

A, Bk = generate_keydict(), generate_keydict()
PA = 4995 * L.FACE_N + 3435                          # the landing site (static/land-world.js SPAWN_PLOT_ROW/COL)
PLANKS, GLASS = 9, 12


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": [{"id": "7001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": "7001"}, "holders": {A["address"]: "1"}})

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


def js_commitment(plot, salt_hex, edits, boxes):
    js = ("const W = await import(%s); const salt = Uint8Array.from(Buffer.from(%s, 'hex'));"
          "console.log(await W.plotCommitment(%d, salt, %s, %s));") % (json.dumps(os.path.join(ROOT, "static", "land-world.js")),
                                                                       json.dumps(salt_hex), plot, json.dumps(edits), json.dumps(boxes))
    return subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60).stdout.strip()


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_turned_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    ta = await login(c, A)
    ha = {"Authorization": "Bearer " + ta}
    pa = world.player(A["address"])
    pa["items"].update({"planks": 20, "chest": 1})
    async def boxes(add=(), remove=()):
        world.workb.clear()
        return await (await c.post("/land/api/boxes", json={"plot": PA, "add": list(add), "remove": list(remove)}, headers=ha)).json()
    async def plotj():
        return await (await c.get(f"/land/api/plot?plot={PA}", headers=ha)).json()     # the holder sees the salt

    square = [400, 400, 10000, 100, 100, 100, PLANKS]
    r = await boxes([square])
    check("a square piece first", r["added"] == 1, r)
    pj0 = await plotj()

    # ---- placed and paid ----------------------------------------------------------------------------------------------
    wing = [800, 800, 10200, 300, 100, 10, PLANKS, 0, 400, 0, 150]      # yaw 40°, roll 15°
    v0 = pa["items"]["planks"] * 1_000_000 + pa["vol"].get("planks", 0)
    r = await boxes([wing])
    v1 = pa["items"]["planks"] * 1_000_000 + pa["vol"].get("planks", 0)
    check("a piece turned 40° in yaw and 15° in roll is placed", r["added"] == 1 and wing in world.plots[PA]["boxes"], r)
    check("…paid by its own volume (300 x 100 x 10 cm)", v0 - v1 == 300 * 100 * 10, (v0, v1))

    # ---- overlap -------------------------------------------------------------------------------------------------------
    r = await boxes([[850, 820, 10150, 100, 60, 100, PLANKS]])
    check("a piece cutting into the turned one is refused", r["added"] == 0 and "overlap" in r["refused"][0][1], r)
    lo = [200, 1200, 10000, 300, 100, 10, PLANKS, 0, 0, 0, 300]          # two plates rolled 30°, 20 cm apart vertically:
    hi = [200, 1200, 10020, 300, 100, 10, PLANKS, 0, 0, 0, 300]          # the boxes around them overlap, they do not
    check("(the boxes around the two plates overlap)", S._aabb_overlap(S.box_aabb(lo), S.box_aabb(hi)))
    r = await boxes([lo, hi])
    check("two turned plates whose bodies do not touch are both placed", r["added"] == 2, r)

    # ---- the rules -----------------------------------------------------------------------------------------------------
    r = await boxes([[0, 0, 10000, 300, 20, 20, PLANKS, 0, 450, 0, 0]])
    check("turned so it reaches out of the plot: refused", r["added"] == 0, r)
    r = await boxes([[100, 1400, 10000, 90, 50, 55, S.CHEST, 0, 300, 0, 0]])
    check("a unit part (a chest) is never turned", r["added"] == 0, r)
    plain = [1200, 200, 10000, 50, 50, 50, PLANKS]
    r = await boxes([plain + [0, 0, 0, 0]])
    check("a turn of 0, 0, 0 is kept as the plain 7 numbers", r["added"] == 1 and plain in world.plots[PA]["boxes"]
          and not any(len(b) == 11 and b[:7] == plain for b in world.plots[PA]["boxes"]), world.plots[PA]["boxes"])

    # ---- the commitment ------------------------------------------------------------------------------------------------
    pj = await plotj()
    salt = bytes.fromhex(pj["salt"])
    raw = S.commitment_bytes(PA, salt, pj["edits"], pj["boxes"])
    check("with a turned piece the plot commits v4", raw.startswith(b"nado-land-plot-v4"))
    js = js_commitment(PA, pj["salt"], pj["edits"], pj["boxes"])
    check("…byte for byte the browser's code", js == pj["commitment"], (js, pj["commitment"]))
    r = await boxes(remove=[wing, lo, hi, plain])
    pj2 = await plotj()
    check("taken down, the plot commits v3 again — the very commitment it had before",
          r["removed"] == 4 and S.commitment_bytes(PA, salt, pj2["edits"], pj2["boxes"]).startswith(b"nado-land-plot-v3")
          and pj2["commitment"] == pj0["commitment"], (pj0["commitment"], pj2["commitment"]))

    # ---- a craft's quarter turns ------------------------------------------------------------------------------------------
    t = S.turn_pieces([wing], 1)[0]
    check("a quarter turn: its yaw takes -90°, its size and roll ride along", t[8] == 400 - 900 and t[3:6] == wing[3:6] and t[10] == 150, t)
    back = S.turn_pieces([wing], 4)[0]
    check("…and four bring it back where it was", back == wing, back)

    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
