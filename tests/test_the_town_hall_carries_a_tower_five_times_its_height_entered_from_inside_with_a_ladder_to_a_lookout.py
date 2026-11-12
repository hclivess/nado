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
  4. it is entered from inside the hall: the hall's back wall gets a door and a covered passage reaches the tower's
     north wall, whose ground floor has the matching gap; the ladder is the game's own ladder PIECES (50 x 8 x 300, what
     land.js ladderNear climbs — the first build stacked block cells, a solid column nobody could climb) run unbroken
     from the floor to the belfry inside the shaft's well; the tower stands clear of the town's streets;
  5. tower_present says no before and yes after; on a rehearsal world (a copy of a built town) build_tower sets every
     piece, ladder pieces among them, and a second run leaves it as it is; the first build (TOWER_V1) comes down whole with
     --untower, the hall's wall made good, before the right one goes up; a standing tower with the old block column gets
     the column cleared and the ladder pieces set.
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
check("what the tower takes out — the back wall's middle and the chest in front of it — are pieces the hall has", all(r in hall for r in removes) and len(removes) == 2 and sorted(r[6] for r in removes) == [T.PS, T.CHEST], removes)
streets = [[0, 0, G - 25, 200, 1600, 30, T.SB], [200, 0, G - 25, 1400, 200, 30, T.SB], [200, 200, G - 25, 10, 1400, 35, T.COB], [210, 200, G - 25, 1390, 10, 35, T.COB]]
pairs = [(a, k) for a in adds for k in kept + streets if ov(a, k)]
check("no tower piece overlaps the hall (less that wall) or the quarter's streets and kerbs", not pairs, pairs[:2])
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
bz = T.HALL["Z0"] + T.HALL["D"] - 12
door = [b for b in adds if b[6] == T.DOOR and b[1] == bz + 3]
check("the hall's back wall gets a door", len(door) == 1 and door[0][5] == 200 and door[0][3] == 90, door)
passage = [b for b in adds if b[6] == T.PS and b[1] == bz + 12 and b[1] + b[4] == Z0]
check("a covered passage bridges the hall's back wall to the tower's north wall", len(passage) == 3, passage)
gx0 = door[0][0] if door else 0
north_ground = [b for b in adds if b[6] == T.SB and b[1] == Z0 and b[2] == G + 45 and b[4] == T.TOWER["T"]]
gap_clear = not any(b[0] < gx0 + 90 and b[0] + b[3] > gx0 for b in north_ground)
check("…and the tower's ground-floor north wall leaves the door's gap", gap_clear and len(north_ground) == 2, north_ground)
# the approach: nothing stands in front of the door inside the hall (the agent climbed onto the hall's chest there and
# could not open the door from its top) — the chest is moved along the back wall, clear of the door by more than a body
front = [b for b in kept + adds if b[6] != T.DOOR and b[0] < gx0 + 90 + 40 and b[0] + b[3] > gx0 - 40 and b[1] + b[4] > bz - 150 and b[1] < bz and b[2] < G + 45 + 200 and b[2] + b[5] > G + 45]   # (not the floor and footing under it)
check("nothing stands within 1.5 m in front of the back door inside the hall (the chest moved aside)", not front and any(b[6] == T.CHEST and b[0] + b[3] <= gx0 - 100 for b in adds), front[:2])
check("the tower stands behind the hall, clear of both streets", X0 > 210 and Z0 > T.HALL["Z0"] + T.HALL["D"] and X0 + Sz < 1600 and Z0 + Sz <= 1600, (X0, Z0))
ys = sorted(b[2] for b in ladder)
check("the ladder is the game's ladder pieces (50 x 8 x 300, kind 53), among the tower's pieces", ladder and all(b[6] == T.LADDER and sorted(b[3:5]) == [8, 50] and b[5] == 300 and b in adds for b in ladder), ladder[:2])
check("it runs unbroken from the floor to the belfry: each piece's foot within the 1.5 m the page reaches under it", ys[0] <= G + 45 and all(ys[i + 1] - ys[i] <= 300 for i in range(len(ys) - 1)) and ys[-1] + 300 >= by - 100, (ys, by))
lx = T.TOWER["LADDER_X"]
check("…inside the shaft, in the floors' well, clear of the doorway", all(lx <= b[0] and b[0] + b[3] <= lx + 100 and Z0 + T.TOWER["T"] <= b[1] and b[1] + b[4] <= Z0 + Sz - T.TOWER["T"] and b[1] > Z0 + 100 for b in ladder), ladder[:1])
floors = [b for b in adds if b[6] == T.PL and b[5] == 10]
check("the ladder's well is left open in every floor", floors and all(b[0] + b[3] <= lx or b[0] >= lx + 100 for b in floors), floors[:2])
cells = T.ladder_cells(G)
check("the first build's block column is named for clearing (the cells the page could not climb)", cells and all(c[2] * 100 >= G + 45 for c in cells) and cells[0][0] == lx // 100, cells[:2])
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
    for k, n in {"stonebrick": 1000, "planks": 80, "beam": 12, "tiles": 80, "plaster": 24, "window": 28, "door": 2, "ladder": 40, "torch": 4}.items():
        pl["items"][k] = pl["items"].get(k, 0) + n
    T.DRY = False
    # the first build goes up and comes down again: the hall as it was
    a1, r1, _ = T.tower_pieces(G, T.TOWER_V1)
    l1 = T.ladder_cells(G, T.TOWER_V1)
    await world.boxes(T.WHO, p, [], r1); await world.boxes(T.WHO, p, [b for b in a1 if T.S.box_ok(b) and b[6] != T.LADDER], [])
    _, row, col = S.plot_coords(p)
    await world.apply(T.WHO, [[0, col * S.PLOT + du, row * S.PLOT + dv, h, 53] for du, dv, h in l1])
    check("the first build's tower stands on the rehearsal world", T.tower_present(world.plots[p]["boxes"], T.TOWER_V1))
    await T.untower(world, pl)
    check("--untower takes it down and makes the hall's wall good: the hall as it was", sorted(map(tuple, world.plots[p]["boxes"])) == sorted(map(tuple, hall)) and not any(b == 53 for b in world.plots[p]["edits"].values()), len(world.plots[p]["boxes"]))
    # the live case first: the tower as the first --tower built it — every piece but the ladder, and the block column
    await world.boxes(T.WHO, p, [], [r for r in removes if r[6] != T.CHEST]); await world.boxes(T.WHO, p, [b for b in adds if b not in ladder and b[6] != T.CHEST], [])
    await world.apply(T.WHO, [[0, col * S.PLOT + du, row * S.PLOT + dv, h, 53] for du, dv, h in cells])
    check("the rehearsal holds a standing tower with the old block column", T.tower_present(world.plots[p]["boxes"]) and any(b == 53 for b in world.plots[p]["edits"].values()))
    await T.build_tower(world, pl)
    boxes = world.plots[p]["boxes"]
    check("build_tower on a standing tower clears the block column and sets the ladder pieces", all(a in boxes for a in ladder) and not any(b == 53 for b in world.plots[p]["edits"].values()), (len(boxes), len(ladder)))
    check("…and moves the hall's chest out of the doorway", not any(r[6] == T.CHEST and r in boxes for r in removes) and any(a[6] == T.CHEST and a in boxes for a in adds))
    check("…and every other tower piece is there, the wall out", all(a in boxes for a in adds) and not any(r in boxes for r in removes), (len(boxes), len(adds)))
    n0 = len(boxes)
    await T.build_tower(world, pl)
    check("a second run leaves it as it is", len(world.plots[p]["boxes"]) == n0)
    world.oracle.kill(); await world.oracle.wait()
    await world.http.close(); await ex.close()


asyncio.run(rehearse())
_report.done()
