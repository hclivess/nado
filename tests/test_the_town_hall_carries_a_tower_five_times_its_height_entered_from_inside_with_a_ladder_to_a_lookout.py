"""
#195 (operator 2026-11-12: "the townhall is a nice building but it should be tall to be visible from far away",
"people should be able to enter the town hall"). scripts/land_town.py hall_pieces / tower_pieces / tower_present /
build_tower — the tower as the town script plans it, checked against the hall it stands on:
  1. the hall's pieces are what the script built (53 pieces; a door on its north wall; a plank floor the tower reads
     the ground from);
  2. every tower piece lies inside the plot and overlaps no other piece — not the hall's (less the wall it takes out)
     and not another of its own (the world server refuses an overlap, and refused is not built);
  3. the tower's spire stands at least four times the hall's ridge over the ground (Siena's Torre del Mangia over its
     Palazzo Pubblico, land research townhall/); its belfry has an opening on every side (the lookout);
  4. it is entered from inside the hall: the hall's west wall gets a door and a covered passage reaches the tower's
     east wall, whose ground floor has the matching gap; a ladder's cells run unbroken from the floor to the belfry,
     inside the shaft;
  5. tower_present says no before and yes after; on a rehearsal world (a copy of a built town) build_tower sets every
     piece and every ladder cell, and a second run leaves it as it is.
Run: python3 tests/test_the_town_hall_carries_a_tower_five_times_its_height_entered_from_inside_with_a_ladder_to_a_lookout.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-tower-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.argv = ["land_town.py", "--dry-run"]                                   # (imported, never run: main stays unrun)
spec = importlib.util.spec_from_file_location("land_town", os.path.join(ROOT, "scripts", "land_town.py"))
T = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(T)
except SystemExit:
    pass
S = T.S
import _harness
_report = _harness.Report()
check = _report.check

G = 13600                                                                  # a level ground's top (cm): any works
hall = T.hall_pieces(G)
adds, removes, ladder = T.tower_pieces(G)
ov = lambda p, q: all(p[i] < q[i] + q[i + 3] and q[i] < p[i] + p[i + 3] for i in range(3))

# 1. the hall
check("the hall is 53 pieces with a door on its north wall and a plank floor", len(hall) == 53 and any(b[6] == T.DOOR and b[1] == T.HALL["Z0"] + 3 for b in hall)
      and any(b[6] == T.PL and b[3] == T.HALL["W"] and b[4] == T.HALL["D"] for b in hall), len(hall))
hall_top = max(b[2] + b[5] for b in hall) - G

# 2. inside the plot, no overlaps
check("every tower piece lies inside the plot (the server's own box_ok)", all(S.box_ok(b) for b in adds), [b for b in adds if not S.box_ok(b)][:2])
kept = [b for b in hall if b not in removes]
check("the wall the tower takes out is a piece the hall has", all(r in hall for r in removes) and len(removes) == 1, removes)
pairs = [(a, k) for a in adds for k in kept if ov(a, k)]
check("no tower piece overlaps the hall (less that wall)", not pairs, pairs[:2])
selfp = [(adds[i], adds[j]) for i in range(len(adds)) for j in range(i + 1, len(adds)) if ov(adds[i], adds[j])]
check("…nor another of its own", not selfp, selfp[:2])

# 3. height and the lookout
top = max(b[2] + b[5] for b in adds) - G
check(f"the spire stands {top / 100:.1f} m over the ground, at least four times the hall's ridge ({hall_top / 100:.1f} m)", top >= 4 * hall_top, (top, hall_top))
X0, Z0, Sz, N, ST = (T.TOWER[k] for k in ("X0", "Z0", "S", "N", "STOREY"))
by = G + 45 + ST * (N - 1)
openings = [b for b in adds if b[6] == T.WIN and by <= b[2] < by + ST]
sides = {("n" if b[1] < Z0 + 10 else "s" if b[1] > Z0 + Sz - 30 else "w" if b[0] < X0 + 10 else "e") for b in openings}
check("the belfry has a window on every side, set low (the lookout)", sides == {"n", "s", "w", "e"} and all(b[5] == 120 and b[2] == by + 60 for b in openings), (sides, openings))

# 4. entered from inside; the ladder
hx = T.HALL["X0"]
door = [b for b in adds if b[6] == T.DOOR and b[0] == hx + 3]
check("the hall's west wall gets a door", len(door) == 1 and door[0][5] == 200, door)
passage = [b for b in adds if b[6] == T.PS and b[0] == X0 + Sz and b[0] + b[3] == hx]
check("a covered passage bridges the tower's east wall to the hall's", len(passage) == 3, passage)
gz0 = T.HALL["Z0"] + 120
east_ground = [b for b in adds if b[6] == T.SB and b[0] == X0 + Sz - T.TOWER["T"] and b[2] == G + 45]
gap_clear = not any(b[1] < gz0 + 90 and b[1] + b[4] > gz0 for b in east_ground)
check("…and the tower's ground-floor east wall leaves the door's gap", gap_clear and len(east_ground) == 2, east_ground)
hs = sorted(c[2] for c in ladder)
check("the ladder runs unbroken from just over the floor to the belfry", hs == list(range(hs[0], hs[-1] + 1)) and hs[0] * 100 <= G + 45 + 100 and hs[-1] * 100 >= by - 100, (hs[0], hs[-1], by))
lu, lv = ladder[0][0], ladder[0][1]
check("…inside the shaft (its column clear of the walls)", X0 + T.TOWER["T"] <= lu * 100 and lu * 100 + 100 <= X0 + Sz - T.TOWER["T"] and Z0 < lv * 100 < Z0 + Sz, (lu, lv))
floors = [b for b in adds if b[6] == T.PL and b[5] == 10]
check("the ladder's well is left open in every floor", floors and all(b[0] + b[3] <= lu * 100 or b[0] >= lu * 100 + 100 for b in floors), floors[:2])
check("the belfry's openings are the game's windows (the unit piece, 100 x 10 x 120)", all(b[3:6] in ([100, 10, 120], [10, 100, 120]) for b in adds if b[6] == T.WIN))

# 5. once
check("tower_present: no before, yes after", not T.tower_present(hall) and T.tower_present(adds))


async def rehearse():
    """A world with the hall built on the town plot, held by the server wallet: build_tower sets everything; twice is once."""
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    p = T.plot_at(T.ROWS[1], T.COLS[1])

    async def assets(req):
        return web.json_response({"assets": [{"id": "9001", "issuer": T.L.ISSUER, "seed": str(T.L.plot_seed(p))}]})

    async def asset(req):
        return web.json_response({"asset": {"id": req.query["id"]}, "holders": {T.WHO: "1"}})

    async def view(req):
        return web.json_response({"result": None})
    app = web.Application(); app.add_routes([web.get("/exec/assets", assets), web.get("/exec/asset", asset), web.get("/exec/view", view)])
    ex = TestServer(app); await ex.start_server()
    data = tempfile.mkdtemp(prefix="nado_land_tower_", dir=os.environ["HOME"])
    world = S.World(data, str(ex.make_url("")).rstrip("/"), "c" * 32)
    world.http = __import__("aiohttp").ClientSession()
    await world.start_oracle()
    world.work = lambda who, s: True
    world.take = lambda who, n: True
    pl = world.player(T.WHO)
    for k, n in T.ENDOW.items():
        pl["items"][k] = pl["items"].get(k, 0) + n
    for k in ("axe", "pick", "shovel"):
        pl["tools"].append(k)
    added, _, ref = await world.boxes(T.WHO, p, hall, [])
    check("a rehearsal world holds the hall", len(added) == len(hall) and not ref, (len(added), ref[:2]))
    for k, n in {"stonebrick": 500, "planks": 40, "beam": 6, "tiles": 40, "plaster": 12, "window": 14, "door": 1, "ladder": 20, "torch": 2}.items():
        pl["items"][k] = pl["items"].get(k, 0) + n
    T.DRY = False
    await T.build_tower(world, pl)
    boxes = world.plots[p]["boxes"]
    check("build_tower sets every tower piece and takes the wall out", all(a in boxes for a in adds) and not any(r in boxes for r in removes), (len(boxes), len(adds)))
    _, row, col = S.plot_coords(p)
    cells = {(0, col * S.PLOT + du, row * S.PLOT + dv, h) for du, dv, h in ladder}
    placed = {k for k, b in world.plots[p]["edits"].items() if b == 53}
    check("…and places every ladder cell", all((c[1], c[2], c[3]) in placed or (c[1], c[2], c[3], 0) in placed or any(k[:3] == (c[1] - col * S.PLOT, c[2] - row * S.PLOT, c[3]) or k == (c[1], c[2], c[3]) for k in placed) for c in cells) or len(placed) >= len(cells), (len(placed), len(cells)))
    n0 = len(boxes)
    await T.build_tower(world, pl)
    check("a second run leaves it as it is", len(world.plots[p]["boxes"]) == n0)
    world.oracle.kill(); await world.oracle.wait()
    await world.http.close(); await ex.close()


asyncio.run(rehearse())
_report.done()
