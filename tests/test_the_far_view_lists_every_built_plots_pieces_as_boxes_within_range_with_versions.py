"""
#193 (operator 2026-11-12: "the village is only visible from like 50 meters away, this means that large cities will be
completely invisible - we must fix this, and efficiently so"). The world server's far view (scripts/land_server.py
far_view, GET /land/api/far):
  1. every plot with pieces within r metres of a place is listed with its version and each piece as its bounding box in
     cm of its plot [x, z, y, w, d, h, block] — a turned piece by its turned bounds (box_aabb), a plot with no pieces
     not at all, a plot beyond r not at all;
  2. `since` {plot: ver} brings an unchanged plot back without its boxes (the page keeps what it has) and a changed one
     whole; an edit bumps the version;
  3. the endpoint bounds r at FAR_R and refuses bad input.
Run: python3 tests/test_the_far_view_lists_every_built_plots_pieces_as_boxes_within_range_with_versions.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-far-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient
from signatures import generate_keydict
from execnode.games import land as L

spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
A = generate_keydict()
PA = 4995 * L.FACE_N + 3435                          # A's plot
PB = PA + 1                                          # the next plot east, A's too
PLATE, PLANKS = 64, 9


def fake_exec():
    async def assets(req):
        return web.json_response({"assets": [{"id": "7001", "issuer": L.ISSUER, "seed": str(L.plot_seed(PA))}, {"id": "7002", "issuer": L.ISSUER, "seed": str(L.plot_seed(PB))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": req.query["id"]}, "holders": {A["address"]: "1"}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application()
    app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    return app


async def main():
    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_far_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    world.http = __import__("aiohttp").ClientSession()
    c = TestClient(TestServer(S.make_app(world, S.Hub(), "https://land.example", "https://wallet.example", secure_cookies=False)))
    await c.start_server()
    me = A["address"]
    world.player(me)["items"].update({"steel_plate": 9, "planks": 9})
    # two plots built on, one of them with a turned plate; a third plot with nothing
    flat = [100, 100, 20000, 400, 300, 10, PLATE]
    turned = [800, 800, 20000, 400, 100, 10, PLATE, 0, 450, 0, 0]       # turned 45° about up: its bounds are wider
    added, _, refused = await world.boxes(me, PA, [flat, turned], [])
    check("two pieces are built on plot A, one turned", len(added) == 2 and not refused, refused)
    shed = [200, 200, 20000, 100, 100, 100, PLANKS]
    added, _, refused = await world.boxes(me, PB, [shed], [])
    check("one on plot B", len(added) == 1 and not refused, refused)
    f, row, col = S.plot_coords(PA)
    u0, v0 = col * S.PLOT, row * S.PLOT

    # 1. within range
    r = await (await c.get(f"/land/api/far?face={f}&u={u0 + 8}&v={v0 + 8}&r=100")).json()
    plots = {p["plot"]: p for p in r["plots"]}
    check("both built plots are listed within 100 m, with their versions and their boxes", set(plots) == {PA, PB} and all("ver" in p and "boxes" in p for p in plots.values()), r)
    bx = sorted(plots[PA]["boxes"])
    aabb = S.box_aabb(turned)
    check("a flat piece is its own box; a turned one its turned bounds (a 400 × 100 plate at 45°: 354 × 354, box_aabb's own)", [100, 100, 20000, 400, 300, 10, PLATE] in bx and any(b[6] == PLATE and b[4] > 100 and b[3] < 400 and b[:6] == [int(x) for x in aabb[:6]] for b in bx), (bx, aabb))
    check("a plot with nothing built is not listed", PA + 2 not in plots)
    far = await (await c.get(f"/land/api/far?face={f}&u={u0 + 8 + 300}&v={v0 + 8}&r=100")).json()
    check("300 m away with r = 100, nothing is listed", far["plots"] == [], far)
    far = await (await c.get(f"/land/api/far?face={f}&u={u0 + 8 + 300}&v={v0 + 8}&r=400")).json()
    check("…and with r = 400, both are", {p["plot"] for p in far["plots"]} == {PA, PB})

    # 2. since
    since = json.dumps({str(PA): plots[PA]["ver"], str(PB): plots[PB]["ver"]})
    r2 = await (await c.get(f"/land/api/far?face={f}&u={u0 + 8}&v={v0 + 8}&r=100&since={since}")).json()
    check("unchanged plots come back without their boxes", all("boxes" not in p and p["ver"] == plots[p["plot"]]["ver"] for p in r2["plots"]) and len(r2["plots"]) == 2, r2)
    added, _, refused = await world.boxes(me, PB, [[400, 400, 20000, 100, 100, 100, PLANKS]], [])
    r3 = await (await c.get(f"/land/api/far?face={f}&u={u0 + 8}&v={v0 + 8}&r=100&since={since}")).json()
    pb = next(p for p in r3["plots"] if p["plot"] == PB)
    check("an edited plot comes back whole with a new version", "boxes" in pb and len(pb["boxes"]) == 2 and pb["ver"] != plots[PB]["ver"], pb)
    check("…the other still without", "boxes" not in next(p for p in r3["plots"] if p["plot"] == PA))

    # 3. bounds
    big = await (await c.get(f"/land/api/far?face={f}&u={u0}&v={v0}&r=99999")).json()
    check("r past FAR_R is cut to it (the answer is still given)", "plots" in big)
    bad = await c.get("/land/api/far?face=0&u=x&v=1")
    check("bad input is refused", bad.status == 400)
    bad = await c.get(f"/land/api/far?face={f}&u={u0}&v={v0}&since=[1]")
    check("…and a since that is no object", bad.status == 400)
    await c.close(); await ex.close(); await world.http.close()


asyncio.run(main())
_report.done()
