"""
Built pieces at 1 cm, any size ("what about 1 cm and people can increase the block size to whatever?", operator
2026-11-06): the world server (scripts/land_server.py `boxes`) keeps a plot's pieces as [x, z, y, w, d, h, m] boxes in
centimetres, and the commitment the owner anchors covers them (static/land-world.js commitmentBytes v2).

  * a piece from 1 cm³ to a large slab is accepted where the caller may build, and only there;
  * it must lie inside the plot, in whole centimetres, of a material the caller can place; it may not overlap another;
  * it is paid for by VOLUME (one gathered block = 1 m³): a 2 m x 10 cm x 3 m wall spends 0.6 of a block of planks,
    whole blocks are opened as needed and the remainder kept; without enough material nothing is placed;
  * taking a piece down refunds its volume (and folds the remainder back into whole blocks) and takes work time in
    proportion to its size; a piece that is not there cannot be taken down;
  * pieces reach every socket watching the plot, persist across a restart, and the plot's commitment — computed by the
    server and by the browser's own code in node — is the same number and changes when a piece changes;
  * performance: the overlap check goes through the 1 m bucket index (BoxIndex) — a piece far from the others is never
    compared with them.

Run: python3 tests/test_built_pieces_are_any_size_from_a_centimetre_paid_by_volume.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-pieces-")
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
    data = tempfile.mkdtemp(prefix="nado_land_pieces_")
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    ta, tb = await login(c, A), await login(c, Bk)
    ha, hb = {"Authorization": "Bearer " + ta}, {"Authorization": "Bearer " + tb}
    pa = world.player(A["address"])
    pa["items"].update({"planks": 3, "glass": 1})
    async def boxes(add=(), remove=(), h=ha, plot=PA):
        return await (await c.post("/land/api/boxes", json={"plot": plot, "add": list(add), "remove": list(remove)}, headers=h)).json()
    rest = lambda: world.workb.clear()

    w2 = await c.ws_connect("/land/ws?token=" + tb)
    await w2.send_json({"t": "watch", "plots": [PA]})

    # any size, where the caller may build
    peg = [800, 800, 10200, 1, 1, 1, PLANKS]
    wall = [0, 0, 10000, 200, 10, 300, PLANKS]
    r = await boxes([peg, wall])
    check("a 1 cm³ peg and a 2 m x 10 cm x 3 m wall are both placed", r["added"] == 2 and not r["refused"], r)
    check("…paid by volume: 0.6 of a block plus 1 cm³ — one whole block opened and the rest kept open",
          pa["items"]["planks"] == 2 and pa["vol"]["planks"] == 1_000_000 - 600_000 - 1, (pa["items"], pa["vol"]))
    r = await boxes([[300, 300, 10000, 10, 10, 10, PLANKS]], h=hb)
    check("another player cannot place on the plot", r["added"] == 0 and "not your plot" in r["refused"][0][1], r)
    check("the plot holds exactly those pieces", sorted(world.plots[PA]["boxes"]) == sorted([peg, wall]))

    # shape rules
    bad = [[1599, 0, 10000, 2, 1, 1, PLANKS], [0, 0, 10000, 0, 5, 5, PLANKS], [0, 0, 10000, 5, 5, 5, 5],
           [0.5, 0, 10000, 5, 5, 5, PLANKS], [0, 0, 25599, 1, 1, 2, PLANKS], [0, 0, 10000, 5, 5, 5, 3]]
    r = await boxes(bad)
    check("out of the plot, zero size, water, fractions, above the sky, an unplaceable material: all refused", r["added"] == 0 and len(r["refused"]) == 6, r)
    r = await boxes([[100, 5, 10100, 50, 50, 50, PLANKS]])
    check("a piece may not overlap another (this one cuts into the wall)", r["added"] == 0 and "overlap" in r["refused"][0][1], r)
    r = await boxes([[0, 10, 10000, 200, 10, 300, PLANKS]])
    check("…but may sit flush against it", r["added"] == 1, r)
    r = await boxes([[0, 400, 10000, 200, 200, 200, PLANKS]])
    check("without enough material nothing is placed (8 blocks of planks wanted)", r["added"] == 0 and "not enough planks" in r["refused"][0][1], r)

    # taking down
    before = pa["items"].get("planks", 0) * 1_000_000 + pa["vol"].get("planks", 0)
    rest()
    r = await boxes(remove=[wall])
    after = pa["items"].get("planks", 0) * 1_000_000 + pa["vol"].get("planks", 0)
    check("taking the wall down refunds exactly its volume", r["removed"] == 1 and after - before == 600_000 and pa["vol"]["planks"] < 1_000_000, (before, after, pa))
    r = await boxes(remove=[wall])
    check("a piece that is not there cannot be taken down", r["removed"] == 0, r)
    world.workb[A["address"]] = [0.0, __import__("time").time()]
    r = await boxes(remove=[[0, 10, 10000, 200, 10, 300, PLANKS]])
    check("taking a big piece down takes time (an empty work bucket refuses it)", r["removed"] == 0 and "too fast" in r["refused"][0][1], r)

    # live
    seen = []
    for _ in range(20):
        m = await asyncio.wait_for(w2.receive_json(), 5)
        if m["t"] == "boxes":
            seen.append(m)
        if len(seen) >= 3:
            break
    check("every watcher is told what was added and taken down", any(peg in m["add"] for m in seen) and any(wall in m["remove"] for m in seen), seen[:2])
    await w2.close()

    # the commitment covers the pieces, the same in Python and in the browser's code
    pj = await (await c.get(f"/land/api/plot?plot={PA}", headers=ha)).json()
    js = js_commitment(PA, pj["salt"], pj["edits"], pj["boxes"])
    check("the plot's commitment covers its pieces, byte for byte the browser's", js == pj["commitment"] and len(pj["boxes"]) == 2, (js, pj["commitment"]))
    rest()
    await boxes([[1000, 1000, 12000, 1, 1, 1, PLANKS]])
    pj2 = await (await c.get(f"/land/api/plot?plot={PA}", headers=ha)).json()
    check("…and changes when a single 1 cm piece is added", pj2["commitment"] != pj["commitment"])

    # persistence and the index
    world.flush()
    w3 = S.World(data, "http://127.0.0.1:1", "")
    check("pieces survive a restart", sorted(w3.plots[PA]["boxes"]) == sorted(world.plots[PA]["boxes"]))
    idx = S.BoxIndex([[x * 10, 0, 10000, 5, 5, 5, PLANKS] for x in range(150)])
    calls = [0]
    real = S.boxes_overlap
    S.boxes_overlap = lambda a, b: (calls.__setitem__(0, calls[0] + 1), real(a, b))[1]
    far = idx.overlaps([1500, 1500, 20000, 5, 5, 5, PLANKS])
    S.boxes_overlap = real
    check("a piece far from the others is never compared with them (the 1 m bucket index)", far is False and calls[0] == 0, calls)
    await c.close(); await ex.close()


asyncio.run(main())
_report.done()
