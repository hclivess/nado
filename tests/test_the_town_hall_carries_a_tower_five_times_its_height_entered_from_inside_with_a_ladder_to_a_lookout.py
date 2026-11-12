"""
#195 (operator 2026-11-12: "the townhall is a nice building but it should be tall to be visible from far away",
"people should be able to enter the town hall"). scripts/land_town.py hall_pieces / tower_pieces / tower_present /
build_tower — the tower as the town script plans it, checked against the hall it stands on:
  1. the hall's pieces are what the script built (53 pieces; a door on its north wall; a plank floor the tower reads
     the ground from);
  2. every tower piece lies inside the plot and overlaps no other piece — not the hall's (less the wall it takes out)
     and not another of its own (the world server refuses an overlap, and refused is not built);
  3. the tower's spire stands at least four times the hall's ridge over the ground (Siena's Torre del Mangia over its
     Palazzo Pubblico, land research townhall/); its top is an OPEN LOOKOUT (operator 2026-11-12: "there is no outlook
     on top just fucking windows to sides" — the third build had four low windows): nothing but a waist-high parapet
     round the edge and a pier at each corner stands on the top floor, so every side is open from the parapet to the
     roof; the top floor covers the ladder's well but for a hatch exactly the ladder's reach, so a body over the hatch
     is on the ladder;
  4. it is entered from inside the hall: the hall's back wall gets a door and a covered passage reaches the tower's
     north wall, whose ground floor has the matching gap; the ladder is the game's own ladder PIECES (50 x 8 x 300, what
     land.js ladderNear climbs — the first build stacked block cells, a solid column nobody could climb) run unbroken
     from the floor to the belfry inside the shaft's well; the tower stands clear of the town's streets;
  5. tower_present says no before and yes after; on a rehearsal world (a copy of a built town) build_tower sets every
     piece, ladder pieces among them, and a second run leaves it as it is; the first build (TOWER_V1) comes down whole with
     --untower, the hall's wall made good, before the right one goes up; a standing tower with the old block column gets
     the column cleared and the ladder pieces set; a standing tower with the third build's windowed top storey has the
     windows and walls taken out and the lookout set.
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
# THE LOOKOUT: what stands on the top floor within the shaft — the parapet pieces (PARAPET high, round the edge), the four
# corner piers (from the parapet's top to the roof), the torch; no window, no wall higher than the parapet anywhere but
# the piers, so a body standing at the parapet looks out over it on every side
on_top = [b for b in adds if by <= b[2] < by + ST and X0 <= b[0] and b[0] + b[3] <= X0 + Sz and Z0 <= b[1] and b[1] + b[4] <= Z0 + Sz]
check("no window on the top storey (the lookout is open, not windowed)", not any(b[6] == T.WIN for b in on_top), [b for b in on_top if b[6] == T.WIN])
par = [b for b in on_top if b[6] == T.SB and b[2] == by and b[5] == T.PARAPET]
piers = [b for b in on_top if b[6] == T.SB and b[2] == by + T.PARAPET and b[3] == T.PIER and b[4] == T.PIER and b[2] + b[5] == by + ST]
check("a parapet of chest height (over a step, under a jump) runs round the whole edge of the top floor", len(par) == 4 and 0.65 * 100 < T.PARAPET < 8.4 ** 2 / 52 * 100
      and {(b[0], b[1], b[3], b[4]) for b in par} == {(X0, Z0, Sz, T.TOWER["T"]), (X0, Z0 + Sz - T.TOWER["T"], Sz, T.TOWER["T"]), (X0, Z0 + T.TOWER["T"], T.TOWER["T"], Sz - 2 * T.TOWER["T"]), (X0 + Sz - T.TOWER["T"], Z0 + T.TOWER["T"], T.TOWER["T"], Sz - 2 * T.TOWER["T"])}, par)
check("a pier at each corner carries the roof from the parapet's top", len(piers) == 4 and {(b[0], b[1]) for b in piers} == {(X0, Z0), (X0 + Sz - T.PIER, Z0), (X0, Z0 + Sz - T.PIER), (X0 + Sz - T.PIER, Z0 + Sz - T.PIER)}, piers)
others = [b for b in on_top if b not in par and b not in piers and b[6] != T.TORCH and b[6] != T.LADDER and not (b[6] == T.PL and b[5] == 10)]
check("nothing else stands on the top floor: every side is open from the parapet to the roof", not others, others)
# every side, between its piers, is clear from the parapet's top to the roof: a ray out from the floor's middle at eye
# height (1.62 m over the floor, land.js EYE) meets no piece on its way out of the shaft on any of the four sides
eye = by + 162
def blocked(x, z):                                        # (the ladder's top piece stands 2.2 m over the floor at the south parapet: handholds to climb out by)
    return [b for b in adds if b[6] != T.LADDER and b[0] <= x < b[0] + b[3] and b[1] <= z < b[1] + b[4] and b[2] <= eye < b[2] + b[5]]
rays = {"n": [(X0 + Sz // 2, z) for z in range(Z0 - 10, Z0 + Sz // 2, 5)], "s": [(X0 + Sz // 2, z) for z in range(Z0 + Sz // 2, Z0 + Sz + 10, 5)],
        "w": [(x, Z0 + Sz // 2) for x in range(X0 - 10, X0 + Sz // 2, 5)], "e": [(x, Z0 + Sz // 2) for x in range(X0 + Sz // 2, X0 + Sz + 10, 5)]}
hit = {side: [blocked(x, z) for x, z in pts if blocked(x, z)] for side, pts in rays.items()}
check("an eye at the lookout's middle sees straight out on every side, over the parapet, under the roof", not any(hit.values()), {k: v[:1] for k, v in hit.items() if v})

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
lx, well = T.TOWER["LADDER_X"], T.TOWER["WELL"]
check("…inside the shaft, in the floors' well, clear of the doorway", all(lx <= b[0] and b[0] + b[3] <= lx + well and Z0 + T.TOWER["T"] <= b[1] and b[1] + b[4] <= Z0 + Sz - T.TOWER["T"] and b[1] > Z0 + 100 for b in ladder), ladder[:1])
floors = [b for b in adds if b[6] == T.PL and b[5] == 10 and b[2] < by - 10]
check("the ladder's well is left open in every floor below the top", floors and all(b[0] + b[3] <= lx or b[0] >= lx + well for b in floors), floors[:2])
# THE TOP FLOOR'S HATCH: the top floor covers the well except where the ladder comes up; the open part (the hatch) is
# exactly the ladder's reach (45 cm, ladderNear) and a half body (30 cm, HALF) from the ladder's face — a body wholly over
# the hatch has its middle within the reach (it is on the ladder), and a body off the ladder stands over the floor
top_floor = [b for b in adds if b[6] == T.PL and b[5] == 10 and b[2] == by - 10]
lad_z = ladder[0][1]
covered = lambda x, z: any(b[0] <= x < b[0] + b[3] and b[1] <= z < b[1] + b[4] for b in top_floor)
inner = [(x, z) for x in range(X0 + T.TOWER["T"], X0 + Sz - T.TOWER["T"], 5) for z in range(Z0 + T.TOWER["T"], Z0 + Sz - T.TOWER["T"], 5)]
hole = [(x, z) for x, z in inner if not covered(x, z)]
check("the top floor is covered everywhere but the hatch", hole and all(lx <= x < lx + well and z >= lad_z - 45 - 30 for x, z in hole), (len(hole), hole[:2]))
check("the hatch takes the climbing body: the well's width, from the ladder's reach less a half body to the wall", all(not covered(x, z) for x in range(lx, lx + well, 5) for z in range(lad_z - 45 - 30, Z0 + Sz - T.TOWER["T"], 5)))
check("the ladder passes up through the hatch, clear of the top floor", not any(ov(b, f) for b in ladder for f in top_floor))
# a player who walks in straight through the door (its middle, a body 60 cm wide: land.js HALF 0.3) and climbs is inside
# the well with a hand to spare — the second build's well began 45 cm east of the door's middle and the first floor's
# west piece stopped the climber's head at 1.3 m
mid = gx0 + 45
check("the well takes a body walking in through the door's middle, 15 cm to spare each side", lx <= mid - 30 - 15 and mid + 30 + 15 <= lx + well and all(b[0] <= mid - 25 and b[0] + b[3] >= mid + 25 for b in ladder), (lx, well, mid))
cells = T.ladder_cells(G)
check("the first build's block column is named for clearing (the cells the page could not climb, at the first build's x)", cells and all(c[2] * 100 >= G + 45 for c in cells) and cells[0][0] == T.TOWER["CELL_X"] // 100, cells[:2])
check("every window in the tower is the game's unit piece (100 x 10 x 120 — the server refuses any other)", any(b[6] == T.WIN for b in adds) and all(b[3:6] in ([100, 10, 120], [10, 100, 120]) for b in adds if b[6] == T.WIN))

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
    # the live case first: the tower as the second build (TOWER_V2: the narrower well) left it — its floors, no ladder
    # pieces, the first build's block column, the chest where the hall put it
    a2, r2, l2 = T.tower_pieces(G, T.TOWER_V2)
    await world.boxes(T.WHO, p, [], [r for r in r2 if r[6] != T.CHEST]); await world.boxes(T.WHO, p, [b for b in a2 if b not in l2 and b[6] != T.CHEST], [])
    await world.apply(T.WHO, [[0, col * S.PLOT + du, row * S.PLOT + dv, h, 53] for du, dv, h in cells])
    stale = [b for b in a2 if b[6] == T.PL and b[5] == 10 and b not in adds]
    check("the rehearsal holds a standing tower with the old block column and the narrower well's floors", T.tower_present(world.plots[p]["boxes"]) and any(b == 53 for b in world.plots[p]["edits"].values()) and stale and all(b in world.plots[p]["boxes"] for b in stale), len(stale))
    await T.build_tower(world, pl)
    boxes = world.plots[p]["boxes"]
    check("build_tower on a standing tower clears the block column and sets the ladder pieces", all(a in boxes for a in ladder) and not any(b == 53 for b in world.plots[p]["edits"].values()), (len(boxes), len(ladder)))
    check("…and replaces the narrower well's floors with this build's", not any(b in boxes for b in stale) and all(b in boxes for b in adds if b[6] == T.PL and b[5] == 10), len(stale))
    check("…and moves the hall's chest out of the doorway", not any(r[6] == T.CHEST and r in boxes for r in removes) and any(a[6] == T.CHEST and a in boxes for a in adds))
    check("…and every other tower piece is there, the wall out", all(a in boxes for a in adds) and not any(r in boxes for r in removes), (len(boxes), len(adds)))
    n0 = len(boxes)
    await T.build_tower(world, pl)
    check("a second run leaves it as it is", len(world.plots[p]["boxes"]) == n0)
    # the live case of 2026-11-12: the third build's top storey — four stone walls with a low window each, the well open
    # through the top floor — made into the lookout: the walls and windows out, the parapet, piers and hatch floor in
    lookout = [b for b in adds if by <= b[2] < by + ST and b[6] in (T.SB, T.PL) and X0 <= b[0] and b[0] + b[3] <= X0 + Sz and Z0 <= b[1] and b[1] + b[4] <= Z0 + Sz] + [b for b in adds if b[6] == T.PL and b[2] == by - 10 and b[3] == well]
    y, Tt = by, T.TOWER["T"]
    old_top = []
    for x, z, w, d, along in ((X0, Z0, Sz, Tt, True), (X0, Z0 + Sz - Tt, Sz, Tt, True), (X0, Z0 + Tt, Tt, Sz - 2 * Tt, False), (X0 + Sz - Tt, Z0 + Tt, Tt, Sz - 2 * Tt, False)):
        if along:
            m = x + w // 2 - 50
            old_top += [[x, z, y, m - x, d, ST, T.SB], [m + 100, z, y, x + w - m - 100, d, ST, T.SB], [m, z, y, 100, d, 60, T.SB], [m, z, y + 180, 100, d, ST - 180, T.SB], [m, z + 5, y + 60, 100, 10, 120, T.WIN]]
        else:
            m = z + d // 2 - 50
            old_top += [[x, z, y, w, m - z, ST, T.SB], [x, m + 100, y, w, z + d - m - 100, ST, T.SB], [x, m, y, w, 100, 60, T.SB], [x, m, y + 180, w, 100, ST - 180, T.SB], [x + 5, m, y + 60, 10, 100, 120, T.WIN]]
    await world.boxes(T.WHO, p, [], lookout)
    _, _, refw = await world.boxes(T.WHO, p, old_top, [])
    boxes = world.plots[p]["boxes"]
    check("the rehearsal holds the third build's windowed top", not refw and all(b in boxes for b in old_top) and not any(b in boxes for b in lookout), (refw[:2], len(boxes)))
    await T.build_tower(world, pl)
    boxes = world.plots[p]["boxes"]
    check("build_tower on the windowed top takes its walls and windows out and sets the lookout", not any(b in boxes for b in old_top) and all(b in boxes for b in lookout) and len(boxes) == n0, (len(boxes), n0))
    world.oracle.kill(); await world.oracle.wait()
    await world.http.close(); await ex.close()


asyncio.run(rehearse())
_report.done()
