"""
PARTS (#175; operator 2026-11-11: "this is xwing … not your shitty jet full of fucking disconnect metal plates", "your whole
fucking building system is fuck", "there are gaps between every fucking part"). The world server's half of
static/land-shapes.js (scripts/land_server.py part_of, part_fill, box_ok, box_vol, engine_count, BoxIndex.overlaps,
World.boxes, craft_mass, craft_thrust, turn_pieces):

  * the server and the browser agree, for every one of the 256 shape bytes, on which are parts, how much of its box each
    fills, which are hollow, what a piece of several sizes costs and how many thrusters an engine is — the browser's own
    code asked in node;
  * a hull is placed and paid a tenth of its solid; a wing is sunk into it (their boxes overlap); the very same part twice
    is refused; a box may stand in a part's box, and a part in a box's; two boxes still may not overlap;
  * an engine is the engine part in the thruster's material and nothing else, of any size and any turn: it costs the
    thrusters its volume comes to, says how many when there are too few, gives them back taken down; a plain thruster,
    a seat and a chest stay whole at their own size;
  * a plot of parts commits byte for byte as the browser does;
  * a craft with an engine weighs and pushes as its thrusters; its parts weigh by what is in them;
  * a part goes round with a craft's quarter turns about its own middle, front first, and four turns — or three and then
    one — bring back the very piece it was (a part that came back as 11 numbers with no turn would be refused for ever);
  * painted plate (white, red, yellow, black) is made at the workbench from steel plate and a pigment, placed and taken
    down by volume.

Run: python3 tests/test_a_part_is_placed_sunk_into_its_neighbours_paid_by_its_fill_and_an_engine_is_its_thrusters.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-parts-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys

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

A = generate_keydict()
PA = 4995 * L.FACE_N + 3435                          # A's titled plot
PLATE, THR, SEAT, PLANKS, GLASS, CHEST = 64, 65, 66, 9, 12, S.CHEST
WHITE, RED, YELLOW, BLACK = 28, 21, 23, 27
code = lambda t, v=0: S.PART_FIRST + 10 * t + v
SIZES = [[130, 440, 130], [200, 600, 150], [1, 1, 1], [37, 911, 5], [1600, 1600, 25600], [260, 880, 260], [30, 60, 30]]


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


def node(js):
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
    return r.stdout.strip() or r.stderr.strip()


def browser_table():
    """What the browser's own code says of every shape byte: [is a part, fill, hollow, [boxVolume per size], [engineCount per size]]."""
    js = ("const S = await import(%s), W = await import(%s); const out = {};"
          "for (let s = 0; s < 256; s++) { const p = S.isPart(s);"
          "  out[s] = [p, p ? S.fill(s) : null, S.hollow(s),"
          "    %s.map(([w, d, h]) => (s === 0 || s > 4 && !p) ? null : W.boxVolume([0, 0, 0, w, d, h, %d, s])),"
          "    %s.map(([w, d, h]) => p ? W.engineCount([0, 0, 0, w, d, h, %d, s]) : null)]; }"
          "console.log(JSON.stringify(out));") % (json.dumps(os.path.join(ROOT, "static", "land-shapes.js")), json.dumps(os.path.join(ROOT, "static", "land-world.js")),
                                                 json.dumps(SIZES), PLATE, json.dumps(SIZES), THR)
    return json.loads(node(js))


def js_commitment(plot, salt_hex, edits, boxes):
    js = ("const W = await import(%s); const salt = Uint8Array.from(Buffer.from(%s, 'hex'));"
          "console.log(await W.plotCommitment(%d, salt, %s, %s));") % (json.dumps(os.path.join(ROOT, "static", "land-world.js")),
                                                                       json.dumps(salt_hex), plot, json.dumps(edits), json.dumps(boxes))
    return node(js)


async def main():
    # ---- the two sides agree ------------------------------------------------------------------------------------------
    js = browser_table()
    wrong = []
    for s in range(256):
        is_p, fill, hollow, vols, engs = js[str(s)]
        p = S.part_of(s)
        mine = [p is not None, S.part_fill(s) if p else None, bool(p) and p[0] in S.PART_HOLLOW,
                [None if (s == 0 or (s > 4 and not p)) else S.box_vol([0, 0, 0, w, d, h, PLATE, s]) for w, d, h in SIZES],
                [S.engine_count([0, 0, 0, w, d, h, THR, s]) if p else None for w, d, h in SIZES]]
        if mine != [is_p, fill, hollow, vols, engs]:
            wrong.append((s, mine, js[str(s)]))
    check("the server and the browser agree on every shape byte: which are parts, their fill, the hollow ones, what a piece costs, an engine's thrusters",
          not wrong and sum(1 for s in range(256) if S.part_of(s)) == 64, wrong[:3])
    check("…and a part's types and variants are the browser's", json.loads(node("const S = await import(%s); console.log(JSON.stringify([S.FIRST, S.VARIANTS, S.SHELL, S.TYPES.length]))"
          % json.dumps(os.path.join(ROOT, "static", "land-shapes.js")))) == [S.PART_FIRST, S.PART_VARIANTS, S.PART_SHELL, 10])
    check("…the thruster an engine is counted in is the thruster item's own size", S.THRUSTER_CM3 == 100 * 100 * 140 == S.RULES["items"]["thruster"]["unit"][0] * S.RULES["items"]["thruster"]["unit"][1] * S.RULES["items"]["thruster"]["unit"][2])

    ex = TestServer(fake_exec()); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_parts_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "b" * 32)
    world.http = __import__("aiohttp").ClientSession()
    a = A["address"]
    pl = world.player(a)
    pl["items"].update({"steel_plate": 6, "glass": 1, "planks": 4, "thruster": 3, "pilot_seat": 1, "chest": 1})
    stock = lambda item: pl["items"].get(item, 0) * S.BLOCK_CM3 + pl["vol"].get(item, 0)

    async def boxes(add=(), remove=()):
        world.workb.clear()
        return await world.boxes(a, PA, list(add), list(remove))

    # ---- box_ok ---------------------------------------------------------------------------------------------------------
    hull = [600, 400, 20000, 200, 600, 150, PLATE, code(S.P_HULL, 6)]
    check("a part's code is a piece; a byte that is none (15, an unused variant 57, 116) is not",
          S.box_ok(hull) and not any(S.box_ok(hull[:7] + [s]) for s in (5, 15, 57, 67, 116, 255)))
    check("an engine is the thruster's material and nothing else", S.box_ok([0, 0, 0, 130, 440, 130, THR, code(S.P_ENGINE)])
          and not S.box_ok([0, 0, 0, 130, 440, 130, PLATE, code(S.P_ENGINE)]) and S.box_ok([0, 0, 0, 130, 440, 130, THR, code(S.P_HULL, 3)]))

    # ---- placed, paid by its fill, sunk into its neighbours ---------------------------------------------------------------
    v0 = stock("steel_plate")
    added, _, refused = await boxes([hull])
    check("a hull is placed", added == [hull] and not refused, refused)
    check("…paid a tenth of the solid its shape fills (a skin)", v0 - stock("steel_plate") == 200 * 600 * 150 * S.part_fill(hull[7]) // 10000 == S.box_vol(hull), (v0 - stock("steel_plate"), S.box_vol(hull)))
    wing = [750, 600, 20060, 500, 300, 20, PLATE, code(S.P_WING, 3)]                # its root 50 cm inside the hull's box
    v0 = stock("steel_plate")
    added, _, refused = await boxes([wing])
    check("a wing is sunk into the hull: their boxes overlap, and it is placed", S.boxes_overlap(hull, wing) and added == [wing], refused)
    check("…paid by its own fill", v0 - stock("steel_plate") == S.box_vol(wing) == 500 * 300 * 20 * S.part_fill(wing[7]) // 10000)
    added, _, refused = await boxes([wing])
    check("the very same part twice is refused", not added and "overlap" in refused[0][1], refused)
    plank_in = [650, 500, 20050, 50, 50, 50, PLANKS]
    added, _, refused = await boxes([plank_in])
    check("a box may stand in a part's box (a part does not fill it)", added == [plank_in], refused)
    added, _, refused = await boxes([[660, 510, 20060, 50, 50, 50, PLANKS]])
    check("two boxes still may not overlap", not added and "overlap" in refused[0][1], refused)
    tube = [640, 490, 20040, 60, 200, 60, PLATE, code(S.P_TUBE, 9)]
    v0 = stock("steel_plate")
    added, _, refused = await boxes([tube])
    check("a part may run into a box, paid as the solid it is (a tube: 785 thousandths)", added == [tube] and v0 - stock("steel_plate") == 60 * 200 * 60 * 785 // 1000, refused)
    canopy = [620, 700, 20150, 160, 250, 80, GLASS, code(S.P_CANOPY)]
    added, _, refused = await boxes([canopy])
    check("a canopy is placed in glass", added == [canopy], refused)
    turned_wing = [750, 300, 20060, 500, 300, 20, PLATE, code(S.P_WING, 3), 0, 0, 1800]     # rolled half round: the other side's wing
    added, _, refused = await boxes([turned_wing])
    check("a part is turned by yaw, pitch and roll as any piece", added == [turned_wing], refused)

    # ---- the commitment ---------------------------------------------------------------------------------------------------
    rec = world.plots[PA]
    salt = bytes.fromhex(rec["salt"]) if isinstance(rec.get("salt"), str) else rec.get("salt")
    if salt:
        mine = S.commitment(PA, salt, rec.get("edits", {}), rec["boxes"]) if hasattr(S, "commitment") else None
    pj = world.plot_json(PA, a) if hasattr(world, "plot_json") else None
    raw = S.commitment_bytes(PA, b"\x03" * 32, [], rec["boxes"])
    jsb = node("const W = await import(%s); console.log(Buffer.from(W.commitmentBytes(%d, new Uint8Array(32).fill(3), [], %s)).toString('hex'));"
               % (json.dumps(os.path.join(ROOT, "static", "land-world.js")), PA, json.dumps(rec["boxes"])))
    check("a plot of parts commits byte for byte as the browser does (v4: one is turned)", raw.hex() == jsb and raw.startswith(b"nado-land-plot-v4"), (raw.hex()[:80], jsb[:80]))
    square = [b for b in rec["boxes"] if len(b) < 11]
    raw3 = S.commitment_bytes(PA, b"\x03" * 32, [], square)
    jsb3 = node("const W = await import(%s); console.log(Buffer.from(W.commitmentBytes(%d, new Uint8Array(32).fill(3), [], %s)).toString('hex'));"
                % (json.dumps(os.path.join(ROOT, "static", "land-world.js")), PA, json.dumps(square)))
    check("…and v3 with none turned, the part in the shape's byte", raw3.hex() == jsb3 and raw3.startswith(b"nado-land-plot-v3") and len(raw3) == 17 + 4 + 32 + 4 + 4 + 14 * len(square))

    # ---- an engine is its thrusters -----------------------------------------------------------------------------------------
    engine = [900, 400, 20000, 130, 440, 130, THR, code(S.P_ENGINE)]
    check("an engine 1.3 x 4.4 x 1.3 m is two thrusters; a plain thruster one; a plate none", S.engine_count(engine) == 2
          and S.engine_count([0, 0, 0, 100, 100, 140, THR]) == 1 and S.engine_count(hull) == 0 and S.is_engine(engine) and not S.is_engine([0, 0, 0, 100, 100, 140, THR]))
    added, _, refused = await boxes([engine[:6] + [PLATE, engine[7]]])
    check("an engine in steel plate is no piece", not added and refused, refused)
    pl["items"]["thruster"] = 1
    added, _, refused = await boxes([engine])
    check("with one thruster an engine of two is refused, and says how many it is", not added and "2 thrusters" in refused[0][1] and pl["items"]["thruster"] == 1, refused)
    pl["items"]["thruster"] = 3
    added, _, refused = await boxes([engine])
    check("with three it is placed, for two", added == [engine] and pl["items"]["thruster"] == 1, (refused, pl["items"]["thruster"]))
    small = [1100, 400, 20000, 30, 60, 30, THR, code(S.P_ENGINE), 0, 0, 450]
    added, _, refused = await boxes([small])
    check("a small engine, turned, is one thruster", added == [small] and pl["items"]["thruster"] == 0, refused)
    _, removed, refused = await boxes(remove=[engine, small])
    check("taken down, they give their thrusters back", removed == [engine, small] and pl["items"]["thruster"] == 3, (refused, pl["items"]["thruster"]))
    added, _, refused = await boxes([[1100, 400, 20000, 100, 140, 100, THR]])
    check("a plain thruster is still a thruster's own size (either way round), and nothing else", not added and "100 x 100 x 140" in refused[0][1], refused)
    added, _, refused = await boxes([[1100, 400, 20000, 100, 100, 140, THR, code(S.P_TUBE, 9)], [1300, 1300, 20000, 90, 50, 55, CHEST, code(S.P_BODY, 9)],
                                     [1100, 700, 20000, 80, 90, 110, SEAT, 0, 300, 0, 0]])
    check("no other part is made of thrusters, and a chest or a seat is never a part or turned", not added and len(refused) == 3, refused)
    added, _, refused = await boxes([[1100, 400, 20000, 100, 100, 140, THR], [1300, 1300, 20000, 90, 50, 55, CHEST]])
    check("…whole and square they are placed, one item each", len(added) == 2 and pl["items"]["thruster"] == 2 and pl["items"]["chest"] == 0, refused)
    await boxes(remove=[[1100, 400, 20000, 100, 100, 140, THR], [1300, 1300, 20000, 90, 50, 55, CHEST]])

    # ---- taken down: refunded by its fill -----------------------------------------------------------------------------------
    v0 = stock("steel_plate")
    _, removed, refused = await boxes(remove=[wing, tube])
    check("a part taken down gives back what it took", len(removed) == 2 and stock("steel_plate") - v0 == S.box_vol(wing) + S.box_vol(tube), refused)

    # ---- a craft: weighed and pushed --------------------------------------------------------------------------------------
    dens, unit = S.FLIGHT["density"], S.FLIGHT["unit_mass"]
    craft = [hull, engine, [600, 500, 20150, 80, 90, 110, SEAT], wing]
    mass = S.box_vol(hull) / 1e6 * dens["64"] + 2 * unit["65"] + unit["66"] + S.box_vol(wing) / 1e6 * dens["64"]
    check("a craft's engine weighs as its two thrusters, its parts by the plate actually in them", abs(S.craft_mass(craft) - mass) < 1e-9, (S.craft_mass(craft), mass))
    check("…and pushes as two thrusters", S.craft_thrust(craft) == 2 * S.FLIGHT["thrust_kn"] and S.craft_thrust(craft + [[0, 0, 0, 100, 100, 140, THR]]) == 3 * S.FLIGHT["thrust_kn"])
    check("a plain piece weighs as before: its box by its density", abs(S.craft_mass([[0, 0, 0, 400, 150, 5, PLATE]]) - 4 * 1.5 * 0.05 * 1.5) < 1e-9)
    # over the world: seat, hull and engine take off as one craft and dock a quarter round
    seat = [660, 600, 20150, 80, 90, 110, SEAT]
    added, _, refused = await boxes([engine, seat, wing])
    check("(the craft is built: an engine in the hull's side, a seat on it, the wing)", len(added) == 3, refused)
    c, parts, err = await world.board(a, PA, seat)
    check("boarding takes the hull, the parts sunk into it and the engine as one craft (an engine is its thruster)",
          err is None and all(x in parts for x in (hull, engine, wing, seat, canopy)), (err, parts))
    check("…its thrust two thrusters', its mass the parts'", err is None and c["thrust"] == 2 * S.FLIGHT["thrust_kn"] and abs(c["mass"] - round(S.craft_mass(c["pieces"]), 3)) < 1e-9, c and (c["mass"], c["thrust"]))
    if err is None:
        import math
        world.leave(a, c["id"])
        col, row = PA % L.FACE_N, PA // L.FACE_N
        world.crafts[c["id"]]["pose"] = [0, col * L.PLOT + 8.0, row * L.PLOT + 8.0, 200.0, math.pi / 2]
        p, add, err = await world.dock(a, c["id"])
        dh = next((x for x in add if x[6] == PLATE and x[7] == hull[7]), None)
        check("docked a quarter round, a part keeps its own size and takes the turn as yaw (its front still its front)",
              err is None and dh is not None and dh[3:6] == hull[3:6] and len(dh) == 11 and dh[8] == -900 and all(S.box_ok(x) for x in add), (err, dh))
        check("…and every piece of it is on the plot", err is None and all(x in world.plots[PA]["boxes"] for x in add))

    # ---- quarter turns ----------------------------------------------------------------------------------------------------
    rel = [[-100, -300, 0, 200, 600, 150, PLATE, code(S.P_HULL, 6)], [100, -100, 60, 500, 300, 20, PLATE, code(S.P_WING, 3)],
           [-65, -400, 0, 130, 440, 130, THR, code(S.P_ENGINE)], [100, 0, 60, 500, 300, 20, PLATE, code(S.P_WING, 3), 0, 0, 1800]]
    q1 = S.turn_pieces(rel, 1)
    check("a quarter turn: a part keeps its width and depth and takes -90° of yaw about its middle (a box would swap them)",
          all(len(t) == 11 and t[3:8] == b[3:8] and t[8] == -900 for t, b in zip(q1[:3], rel[:3])) and q1[1][:2] == [50 - 250, -350 - 150], q1)
    check("…its middle going round as a box's does: (x, z) to (z, -x)", all(abs((t[0] + t[3] / 2) - (b[1] + b[4] / 2)) <= 0.5 and abs((t[1] + t[4] / 2) + (b[0] + b[3] / 2)) <= 0.5 for t, b in zip(q1, rel)))
    check("four quarter turns bring every part back the very piece it was", S.turn_pieces(rel, 4) == rel and S.turn_pieces(rel, 0) == rel)
    again = S.turn_pieces(S.turn_pieces(rel, 3), 1)
    check("docked at 270° and then at 90°, a part is the 8 numbers it was — never 11 with no turn (box_ok refuses that for ever)",
          again == rel and all(len(x) in (8, 11) and (len(x) == 8 or any(x[8:])) for x in again), again)
    check("…and every turn of it is a piece", all(S.box_ok([x[0] + 800, x[1] + 800, x[2] + 20000] + list(x[3:])) for q in range(4) for x in S.turn_pieces(rel, q)))
    check("a plain box and a slope turn as they always did", S.turn_pieces([[10, 20, 0, 30, 40, 5, 9]], 1) == [[20, -40, 0, 40, 30, 5, 9]] and S.turn_pieces([[0, 0, 0, 10, 10, 10, 9, 1]], 1)[0][7] == 4)

    # ---- painted plate ------------------------------------------------------------------------------------------------------
    pl["stations"].append("workbench")
    pl["items"].update({"steel_plate": 16, "lime": 1, "ironore": 2, "clay": 1, "charcoal": 1})
    errs = [world.craft(a, rid) for rid in ("white_plate", "red_plate", "yellow_plate", "black_plate")]
    check("white, red, yellow and black plate are made at the workbench: four plates and a pigment each (lime, iron ore, iron ore and clay, charcoal)",
          errs == [None] * 4 and all(pl["items"].get(k) == 4 for k in ("white_plate", "red_plate", "yellow_plate", "black_plate"))
          and pl["items"]["steel_plate"] == 0 and not any(pl["items"].get(k) for k in ("lime", "ironore", "clay", "charcoal")), (errs, pl["items"]))
    check("…and not without the pigment", world.craft(a, "red_plate") is not None)
    painted = [[200 + 120 * i, 1300, 20000, 100, 100, 100, m, code(S.P_BODY, 9)] for i, m in enumerate((WHITE, RED, YELLOW, BLACK))]
    added, _, refused = await boxes(painted)
    check("painted plate is placed as parts, a block's worth each", len(added) == 4 and all(pl["items"][k] == 3 for k in ("white_plate", "red_plate", "yellow_plate", "black_plate")), refused)
    removed, refused = [], []
    for half in (painted[:2], painted[2:]):                      # 3 s of work a block by hand: four at once is more than the 10 s anyone has saved
        _, r, f = await boxes(remove=half); removed += r; refused += f
    check("…and taken down gives the painted plate back", len(removed) == 4 and all(pl["items"][k] == 4 for k in ("white_plate", "red_plate", "yellow_plate", "black_plate")), refused)
    check("painted plate weighs as the steel plate it is", all(dens[str(m)] == dens["64"] for m in (WHITE, RED, YELLOW, BLACK)))

    await world.http.close(); await ex.close()


asyncio.run(main())
_report.done()
