# land_town.py — the TOWN at the landing (issues #122 #123): the four central plots of the first wave (face 0, rows
# 4999–5000, cols 3439–3440), held by this server's wallet, levelled, with two crossing streets and a town hall.
# The world server's rules hold for the town as for anyone (scripts/land_server.py World.apply / World.boxes: only
# where the caller may build, pieces paid by volume from its bag), so the server wallet is ENDOWED once with the
# materials the build takes — written into its bag here, before the build, and listed in the run's output and in #123.
# Runs OFFLINE on the world's data while nado-land is stopped (the service holds the world in memory and would write
# over a concurrent change): systemctl stop nado-land; HOME=/root python3 scripts/land_town.py; systemctl start.
#   --repair  levels the town that stands EXACTLY (true_level) and sets its benches and street torches down on the
#             ground — the first build left roads and a bench hanging in the air (operator, 2026-11-07).
import asyncio, importlib.util, json, os, subprocess, sys, urllib.request
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location("land_server", os.path.join(REPO, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
from execnode.games import land as L

DATA, EX = "/srv/nado-home/land/planet0", os.environ.get("LAND_EXEC", "http://127.0.0.1:9273")   # a rehearsal may name none
ROWS, COLS = (4999, 5000), (3439, 3440)
U0, V0 = COLS[0] * 16, ROWS[0] * 16                  # the town's corner, grid units (32 x 32 columns)
WHO = L.ISSUER
# block ids (static/land-world.js B)
PL, COB, SB, TI, PS, BM, DOOR, WIN, TABLE, CHAIR, BENCH, TORCH, CHEST, DIRT = 9, 10, 16, 13, 14, 38, 37, 40, 45, 46, 47, 50, 54, 2
LADDER = 53                       # the ladder PIECE (land-recipes.json "ladder" places 53 as a 50 x 8 x 300 unit): the page climbs pieces only
ENDOW = {"stonebrick": 400, "cobble": 120, "planks": 160, "plaster": 160, "beam": 80, "tiles": 160, "dirt": 600,
         "door": 2, "window": 8, "table": 2, "chair": 8, "bench": 8, "torch": 16, "chest": 1}
DRY = "--dry-run" in sys.argv
# --rehearse: the whole build on a COPY of the world's data (LAND_DATA), the town's titles taken as the server wallet's
# — every piece through the world server's own checks, nothing live touched
REHEARSE = "--rehearse" in sys.argv
REPAIR = "--repair" in sys.argv
# --garden: the town square made beautiful ("make the town tile beautiful so it attracts people, use only assets from the
# game (they must be available to all players)", operator 2026-11-07) — wild flowers, a pond, a fountain, an orchard;
# every block and piece one any player can gather or make (flowers picked on the meadows, water in a bucket, saplings
# from leaves, stone brick at the kiln)
GARDEN = "--garden" in sys.argv
# --lights: street lamps at every corner of the crossing and both ends of each street ("we could use some more intense
# sources of light - townhall disappears after walking 20 meters at night", operator 2026-11-07)
LIGHTS = "--lights" in sys.argv
# --tower: the tower on the hall (#195, "it should be tall to be visible from far away") — tower_pieces below; once
# (tower_present); the level ground's top is read from the hall's own floor, nothing else of the town is touched
TOWER_MODE = "--tower" in sys.argv
UNTOWER = "--untower" in sys.argv                      # take the first build's tower (TOWER_V1, in the street) down
if REHEARSE:
    DATA = os.environ["LAND_DATA"]


def plot_at(r, c): return r * L.FACE_N + c


def terrain():
    """Each town column's ground top, and every non-air cell above the level (trees, litter) — from the generator."""
    js = """
const W = await import(%s);
const tops = [], above = [];
for (let du = 0; du < 32; du++) for (let dv = 0; dv < 32; dv++) {
  const u = %d + du, v = %d + dv, c = W.column(0, u, v); tops.push([u, v, c.top]);
  for (let h = c.top - 1; h <= c.top + 20; h++) { const b = W.terrainBlock(0, u, v, h); if (b && h > c.top - 1) above.push([u, v, h, b]); }
}
console.log(JSON.stringify({ tops, above, natural: [...W.NATURAL] }));""" % (json.dumps(os.path.join(REPO, "static", "land-world.js")), U0, V0)
    return json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=600).stdout)


async def true_level(world, T, cols, natural):
    """EXACTLY LEVEL at T + 1 (the roads' and benches' footing): the drawn ground is the smooth field over cell centres
    (land-world fieldOf), and an UNTOUCHED cell's field follows its column's fractional height — a column whose top was
    already T was left untouched by the first levelling and drew its ground anywhere from T to T + 1, up to a metre under
    a road slab. Every town column gets an edited earth cell at T (+1) and an edited air cell at T + 1 (-1), so the
    surface lies exactly at T + 1. Only through World.apply: an untouched cell at T is dug and earth put back; an
    untouched air cell at T + 1 gets earth put in and dug out. Returns the cells, in order."""
    out = []
    for u, v in cols:
        p = S.plot_of(0, u, v)
        edited = (world.plots.get(p) or {}).get("edits", {})       # READ only: every write goes through World.apply
        k = lambda h: (u - (p % S.FACE_N) * S.PLOT, v - ((p // S.FACE_N) % S.FACE_N) * S.PLOT, h)
        at = await world.blocks_at([[0, u, v, T], [0, u, v, T + 1]])
        b0, b1 = at[(0, u, v, T)], at[(0, u, v, T + 1)]
        if k(T) not in edited:
            out += ([[0, u, v, T, 0]] if b0 else []) + [[0, u, v, T, DIRT]]
        elif b0 not in natural and b0 != WATER:              # a pond or a basin of the garden stays as it is
            out += ([[0, u, v, T, 0]] if b0 else []) + [[0, u, v, T, DIRT]]
        # T + 1 must not draw as GROUND: an edited air cell, or anything edited there that is not natural ground — a plant,
        # a sapling, a tree's log stand there and are drawn as open space (field -1) as air is. A repair once cleared
        # them all (107 flowers and the orchard's lowest logs, 2026-11-07: restored from the backup taken before the run)
        if k(T + 1) not in edited:
            out += [[0, u, v, T + 1, DIRT], [0, u, v, T + 1, 0]] if b1 == 0 else [[0, u, v, T + 1, 0]] if b1 in natural else []
        elif b1 in natural:
            out += [[0, u, v, T + 1, 0]]
    return out


POPPY, CORNFLOWER, DAISY, BUTTERCUP, SAPLING, WATER = 58, 59, 60, 61, 52, 5     # static/land-world.js B
LAMPPOST = 63


def lamps(G):
    """{plot: [lamppost pieces]}: one at the crossing's corner of each quarter and one at each street's far end in it,
    on the grass just off the kerb (24 x 24 cm, 3.2 m tall — land-recipes.json lamppost unit)."""
    out = {}
    for r in ROWS:
        for c in COLS:
            west, north = c == COLS[1], r == ROWS[1]            # the N-S street on this plot's west edge, the E-W on its north
            x_by = 216 if west else 1360                        # beside the N-S street, off its kerb
            z_by = 216 if north else 1360                       # beside the E-W street
            far_z = 1536 if north else 40                       # the N-S street's far end in this plot
            far_x = 1536 if west else 40                        # the E-W street's far end
            out[plot_at(r, c)] = [[x_by, z_by, G, 24, 24, 320, LAMPPOST], [x_by, far_z, G, 24, 24, 320, LAMPPOST],
                                  [far_x, z_by, G, 24, 24, 320, LAMPPOST]]
    return out


def garden(T, G):
    """The garden: {plot: (cells [[face, u, v, h, block]], pieces [box])} — cells in the order to apply them (a pond's
    ground dug before its water goes in). Flowers and saplings stand on the level ground (layer T + 1); water fills cells
    dug at layer T, so a pond's surface lies just under the grass."""
    out = {}
    def at(r, c):
        u0, v0 = c * 16, r * 16
        cells, pieces = [], []
        cell = lambda x, z, h, b: cells.append([0, u0 + x, v0 + z, h, b])
        out[plot_at(r, c)] = (cells, pieces)
        return cell, pieces
    kinds = (POPPY, CORNFLOWER, DAISY, BUTTERCUP)
    # NW: a flower garden round a pond (4 x 3 m), drifts of colour toward the street
    cell, pieces = at(ROWS[0], COLS[0])
    pond = {(x, z) for x in range(4, 8) for z in range(4, 7)}
    for x, z in sorted(pond):
        cell(x, z, T, 0); cell(x, z, T, WATER)
    for x in range(3, 9):
        for z in range(3, 8):
            if (x, z) not in pond:
                cell(x, z, T + 1, kinds[(x + z) % 4])
    for x in range(1, 10):
        cell(x, 10, T + 1, POPPY if x % 2 else DAISY)
        cell(x, 11, T + 1, CORNFLOWER if x % 2 else BUTTERCUP)
    # NE: an orchard — nine saplings 4 m apart (they grow into the trees of their climate), buttercups between, daisies
    cell, pieces = at(ROWS[0], COLS[1])
    for x in (6, 10, 14):
        for z in (3, 7, 11):
            cell(x, z, T + 1, SAPLING)
    for x in (8, 12):
        for z in (5, 9):
            cell(x, z, T + 1, BUTTERCUP)
    for z in range(1, 13):
        cell(4, z, T + 1, DAISY)
    # SW: a fountain plaza — a stone-brick basin round 4 x 4 m of water, a lit pillar in it, a ring of flowers outside
    cell, pieces = at(ROWS[1], COLS[0])
    for x in range(5, 9):
        for z in range(7, 11):
            cell(x, z, T, 0); cell(x, z, T, WATER)
    pieces += [[470, 670, G, 460, 30, 50, SB], [470, 1100, G, 460, 30, 50, SB], [470, 700, G, 30, 400, 50, SB],
               [900, 700, G, 30, 400, 50, SB], [680, 880, G - 100, 40, 40, 210, SB], [695, 895, G + 110, 10, 10, 120, TORCH]]
    for x in range(3, 11):
        for z in range(5, 13):
            if x in (3, 10) or z in (5, 12):
                cell(x, z, T + 1, POPPY if (x + z) % 2 else CORNFLOWER)
    # SE: flower beds before the hall (either side of the door path), along its east side and behind it
    cell, pieces = at(ROWS[1], COLS[1])
    for x in list(range(4, 8)) + list(range(10, 14)):
        cell(x, 3, T + 1, POPPY if x % 2 else BUTTERCUP)
    for z in range(4, 13):
        cell(14, z, T + 1, DAISY)
    for x in range(4, 14):
        cell(x, 14, T + 1, CORNFLOWER)
    return out


# the town hall: in the quarter of plot (5000, 3440), facing the E-W street to its north — its pieces, absolute cm in
# the plot, for the level ground's top G (cm); a function so the tower (#195) is checked against them
HALL = dict(X0=350, Z0=450, W=1000, D=800, WH=280)
def hall_pieces(G):
    X0, Z0, W, D, WH = HALL["X0"], HALL["Z0"], HALL["W"], HALL["D"], HALL["WH"]
    F = G + 45                                                                   # the hall's floor level
    hall = []
    hall.append([X0 - 20, Z0 - 20, G - 25, W + 40, D + 40, 65, SB])               # stone footing, up to the floor
    hall.append([X0, Z0, F - 5, W, D, 5, PL])                                     # plank floor (on the footing)
    for cx, cz in ((0, 0), (W - 20, 0), (0, D - 20), (W - 20, D - 20)):
        hall.append([X0 + cx, Z0 + cz, F, 20, 20, WH, BM])                        # corner posts
    # front wall (z = Z0) with a door in the middle and a window either side
    dx = W // 2 - 45
    hall += [[X0 + 20, Z0, F, 110, 12, WH, PS], [X0 + 230, Z0, F, dx - 230, 12, WH, PS],
             [X0 + dx + 90, Z0, F, W - 230 - dx - 90, 12, WH, PS], [X0 + W - 130, Z0, F, 110, 12, WH, PS]]
    for wx in (130, W - 230):
        hall += [[X0 + wx, Z0, F, 100, 12, 80, PS], [X0 + wx, Z0, F + 200, 100, 12, WH - 200, PS],
                 [X0 + wx, Z0 + 1, F + 80, 100, 10, 120, WIN]]
    hall += [[X0 + dx, Z0, F + 200, 90, 12, WH - 200, PS], [X0 + dx, Z0 + 3, F, 90, 5, 200, DOOR]]
    # back wall with two windows, side walls with one each
    hall += [[X0 + 20, Z0 + D - 12, F, 160, 12, WH, PS], [X0 + 280, Z0 + D - 12, F, W - 560, 12, WH, PS],
             [X0 + W - 180, Z0 + D - 12, F, 160, 12, WH, PS]]
    for wx in (180, W - 280):
        hall += [[X0 + wx, Z0 + D - 12, F, 100, 12, 80, PS], [X0 + wx, Z0 + D - 12, F + 200, 100, 12, WH - 200, PS],
                 [X0 + wx, Z0 + D - 11, F + 80, 100, 10, 120, WIN]]
    for sxw in (0, W - 12):
        hall += [[X0 + sxw, Z0 + 20, F, 12, 290, WH, PS], [X0 + sxw, Z0 + 410, F, 12, D - 430, WH, PS],
                 [X0 + sxw, Z0 + 310, F, 12, 100, 80, PS], [X0 + sxw, Z0 + 310, F + 200, 12, 100, WH - 200, PS],
                 [X0 + sxw + 1, Z0 + 310, F + 80, 10, 100, 120, WIN]]
    hall.append([X0, Z0, F + WH, W, D, 15, BM])                                   # the tie-beam floor of the roof
    ry, half = F + WH + 15, D // 2 + 40
    hall += [[X0 - 30, Z0 - 40, ry, W + 60, half, 170, TI, 3], [X0 - 30, Z0 + D // 2, ry, W + 60, half, 170, TI, 4]]
    # furniture: two long tables with chairs and benches, a chest at the back, torches inside and at the door
    for tx in (X0 + 150, X0 + 600):
        hall.append([tx, Z0 + 330, F, 120, 80, 76, TABLE])
        hall += [[tx + 35, Z0 + 270, F, 50, 45, 95, CHAIR], [tx + 35, Z0 + 420, F, 50, 45, 95, CHAIR]]
    hall += [[X0 + 100, Z0 + D - 90, F, 150, 35, 45, BENCH], [X0 + W - 250, Z0 + D - 90, F, 150, 35, 45, BENCH],
             [X0 + W // 2 - 45, Z0 + D - 70, F, 90, 50, 55, CHEST],
             [X0 + 30, Z0 + 30, F, 10, 10, 120, TORCH], [X0 + W - 40, Z0 + D - 40, F, 10, 10, 120, TORCH],
             [X0 + dx - 30, Z0 - 40, G, 10, 10, 120, TORCH], [X0 + dx + 110, Z0 - 40, G, 10, 10, 120, TORCH]]

    return hall


# THE TOWER (#195; operator 2026-11-12: "the townhall is a nice building but it should be tall to be visible from far
# away", "people should be able to enter the town hall"): a square stone tower BEHIND the hall (its south side — the
# N-S street runs along this quarter's west edge, the E-W street along its north: the first build, 2026-11-12, stood a
# tower in the street), five storeys of 3.2 m and a belfry, its spire ~23 m over the square — about four and a half
# times the hall's ridge, after the proportion of Siena's Torre del Mangia over its Palazzo Pubblico (land research
# townhall/: the photograph; the tower 102 m, l.6). Entered from inside the hall by a door cut into its back wall and a
# short covered passage under the roof's overhang; a ladder (the game's own) runs up the shaft through the floors' well
# to the belfry, which has a window on every side, set low — the lookout. Plank floors a storey; the game's unit windows
# (100 x 10 x 120, the server refuses any other size) on the outer faces; a gable roof of tiles like the hall's; a beam
# spire post; a torch below and one at the lookout. Every number here is a DESIGN CHOICE in the hall's own units (cm);
# the pieces are the game's blocks, paid from the town's bag.
TOWER = dict(X0=760, Z0=1290, S=280, T=20, STOREY=320, N=5, SPIRE=500, LADDER_X=900, door="north")   # (z 1290: against the hall roof's overhang; the gable ends at the plot's edge)
# the first build's place (in the west street, 2026-11-12): what --untower takes down
TOWER_V1 = dict(X0=30, Z0=480, S=280, T=20, STOREY=320, N=5, SPIRE=500, LADDER_X=100, door="east")
def tower_pieces(G, P=None):
    """(adds, removes, ladder) for the hall's plot: the pieces to set (the ladder's among them), the hall wall to take out
    for the door, and the ladder's pieces on their own. P: the tower's place (TOWER).
    THE LADDER IS PIECES, NOT BLOCKS (#195, 2026-11-12): land.js ladderNear climbs only a plot PIECE of kind 53 — the
    game's ladder item is a 50 x 8 x 300 unit piece — while the first build stacked BLOCK cells of 53 up the well, a
    solid column nobody could climb (the agent stood at its foot). ladder_cells names that column for clearing."""
    P = P or TOWER
    X0, Z0, S, T, ST, N, SP, LX, door = (P[k] for k in ("X0", "Z0", "S", "T", "STOREY", "N", "SPIRE", "LADDER_X", "door"))
    F = G + 45
    hx, hz, hw, hd, WH = HALL["X0"], HALL["Z0"], HALL["W"], HALL["D"], HALL["WH"]
    adds, removes = [], []
    if door == "north":
        adds.append([X0 - 20, Z0 - 20, G - 25, S + 40, S + 20, 65, SB])                      # footing, to the plot's south edge
        gx0, gx1 = X0 + S // 2 - 45, X0 + S // 2 + 45                                        # the door's x (90 wide), in the tower's middle
    else:
        adds.append([X0 - 20, Z0 - 20, G - 25, S + 20, S + 40, 65, SB])                      # (v1: to the hall's own footing)
        gz0, gz1 = hz + 120, hz + 210
    adds.append([X0, Z0, F - 5, S, S, 5, PL])                                                 # the ground floor
    top = F + ST * N
    for k in range(N):
        y = F + ST * k
        belfry = k == N - 1
        def wall(x, z, w, d):
            adds.append([x, z, y, w, d, ST, SB])
        def slitted(x, z, w, d, along_x, big):
            # a wall with a window in its middle: two wall pieces, a lintel over the window, a sill under it; the window
            # is the unit piece set 5 cm from the wall's face; the belfry's sit low (a lookout to lean out of)
            ww, wh, sill = 100, 120, (60 if big else 110)
            if along_x:
                m = x + w // 2 - ww // 2
                adds.extend([[x, z, y, m - x, d, ST, SB], [m + ww, z, y, x + w - m - ww, d, ST, SB],
                             [m, z, y, ww, d, sill, SB], [m, z, y + sill + wh, ww, d, ST - sill - wh, SB], [m, z + 5, y + sill, ww, 10, wh, WIN]])
            else:
                m = z + d // 2 - ww // 2
                adds.extend([[x, z, y, w, m - z, ST, SB], [x, m + ww, y, w, z + d - m - ww, ST, SB],
                             [x, m, y, w, ww, sill, SB], [x, m, y + sill + wh, w, ww, ST - sill - wh, SB], [x + 5, m, y + sill, 10, ww, wh, WIN]])
        def gapped_x(x, z, w, d, g0, g1):                                                     # a wall along x with a door gap g0..g1
            adds.extend([[x, z, y, g0 - x, d, ST, SB], [g1, z, y, x + w - g1, d, ST, SB], [g0, z, y + 200, g1 - g0, d, ST - 200, SB]])
        def gapped_z(x, z, w, d, g0, g1):
            adds.extend([[x, z, y, w, g0 - z, ST, SB], [x, g1, y, w, z + d - g1, ST, SB], [x, g0, y + 200, w, g1 - g0, ST - 200, SB]])
        # the corners belong to the north and south walls; the west and east walls run between them
        if door == "north":
            if belfry: slitted(X0, Z0, S, T, True, True)
            elif k == 0: gapped_x(X0, Z0, S, T, gx0, gx1)                                     # the door gap toward the hall
            else: wall(X0, Z0, S, T)                                                          # blank: it faces the hall
            slitted(X0, Z0 + S - T, S, T, True, belfry)                                       # south: outer
            slitted(X0, Z0 + T, T, S - 2 * T, False, belfry)                                  # west: outer
            slitted(X0 + S - T, Z0 + T, T, S - 2 * T, False, belfry)                          # east: outer
        else:
            slitted(X0, Z0, S, T, True, belfry)                                               # north
            slitted(X0, Z0 + T, T, S - 2 * T, False, belfry)                                  # west
            if belfry:
                slitted(X0, Z0 + S - T, S, T, True, True); slitted(X0 + S - T, Z0 + T, T, S - 2 * T, False, True)
            else:
                wall(X0, Z0 + S - T, S, T)
                if k == 0: gapped_z(X0 + S - T, Z0 + T, T, S - 2 * T, gz0, gz1)
                else: wall(X0 + S - T, Z0 + T, T, S - 2 * T)
        if k > 0:
            # the storey's floor in two pieces, the ladder's column (LX .. + 100) left open as its well
            adds.append([X0 + T, Z0 + T, y - 10, LX - (X0 + T), S - 2 * T, 10, PL])
            adds.append([LX + 100, Z0 + T, y - 10, X0 + S - T - (LX + 100), S - 2 * T, 10, PL])
        if k == 0:
            adds.append([X0 + 30, Z0 + 30, F, 10, 10, 120, TORCH])
    # the belfry's roof: a gable of tiles over the top, as the hall's; the spire post from the ridge; a torch at the lookout
    ry, half = top, S // 2 + 30
    adds += [[X0 - 20, Z0 - 30, ry, S + 40, half, 150, TI, 3], [X0 - 20, Z0 + S // 2, ry, S + 40, half, 150, TI, 4]]
    adds.append([X0 + S // 2 - 20, Z0 + S // 2 - 20, ry + 150, 40, 40, SP, BM])                # the spire post
    adds.append([X0 + 30, Z0 + 30, top - ST, 10, 10, 120, TORCH])
    # the door from the hall, and a covered passage (plaster walls, a plank floor, under the hall roof's overhang)
    ph = (G + 340) - F                                                                       # (the passage's walls stop under the roof)
    if door == "north":
        # the hall's back wall's middle piece gives way to two pieces, a lintel and a door in the tower's line
        bz = hz + hd - 12
        removes.append([hx + 280, bz, F, hw - 560, 12, WH, PS])
        adds += [[hx + 280, bz, F, gx0 - (hx + 280), 12, WH, PS], [gx1, bz, F, hx + hw - 280 - gx1, 12, WH, PS],
                 [gx0, bz, F + 200, gx1 - gx0, 12, WH - 200, PS], [gx0, bz + 3, F, 90, 5, 200, DOOR]]
        pz, pd = bz + 12, Z0 - (bz + 12)
        adds += [[gx0 - 20, pz, F, 20, pd, ph, PS], [gx1, pz, F, 20, pd, ph, PS], [gx0, pz, F + 200, 90, pd, ph - 200, PS],
                 [gx0, pz, F - 5, 90, pd, 5, PL]]
    else:
        removes.append([hx, hz + 20, F, 12, 290, WH, PS])
        adds += [[hx, hz + 20, F, 12, 100, WH, PS], [hx, hz + 210, F, 12, 100, WH, PS],
                 [hx, gz0, F + 200, 12, 90, WH - 200, PS], [hx + 3, gz0, F, 5, 90, 200, DOOR]]
        px, pw = X0 + S, hx - (X0 + S)
        adds += [[px, gz0 - 20, F, pw, 20, ph, PS], [px, gz1, F, pw, 20, ph, PS], [px, gz0, F + 200, pw, 90, ph - 200, PS],
                 [px, gz0, F - 5, pw, 90, 5, PL]]
    # the ladder: unit pieces (50 x 8 x 300) stacked up the floors' well against the shaft's south inner wall (the north
    # wall's ground floor is the doorway), from the ground floor to the belfry — each within the 1.5 m the page reaches
    # under a piece's foot, so the climb never breaks between two
    ladder = [[LX + 25, Z0 + S - T - 8, y, 50, 8, 300, LADDER] for y in range(F, top - ST, 300)]
    adds += ladder
    return adds, removes, ladder
def ladder_cells(G, P=None):
    """The first build's ladder: BLOCK cells [du, dv, h] (plot columns 0..15, grid heights) up the well — what --tower
    clears before setting the pieces, and what --untower clears of the v1 build."""
    P = P or TOWER
    X0, Z0, S, ST, N, LX = (P[k] for k in ("X0", "Z0", "S", "STOREY", "N", "LADDER_X"))
    F = G + 45
    top = F + ST * N
    lu, lv = LX // 100, (Z0 + S // 2) // 100
    return [[lu, lv, h] for h in range(F // 100 + 1, (top - ST) // 100 + 1)]
def tower_present(boxes, P=None):
    """Does the hall's plot already carry the tower? Its spire post, nowhere else in the town."""
    P = P or TOWER
    X0, Z0, S = P["X0"], P["Z0"], P["S"]
    return any(b[6] == BM and b[3] == 40 and b[4] == 40 and b[5] == P["SPIRE"] and b[0] == X0 + S // 2 - 20 and b[1] == Z0 + S // 2 - 20 for b in boxes)


async def build_tower(world, pl):
    """The tower on the hall's plot (#195): the ground's top G read from the hall's plank floor (F - 5 = G + 40), the hall
    wall for the door taken out, the pieces set — once; a second run reports it standing. A standing tower still gets
    its ladder made good: the first build's block column cleared and the ladder pieces set where they are missing."""
    p = plot_at(ROWS[1], COLS[1])
    boxes = (world.plots.get(p) or {}).get("boxes", [])
    floors = [b for b in boxes if b[6] == PL and b[3] == HALL["W"] and b[4] == HALL["D"] and b[5] == 5]
    if not floors:
        sys.exit(f"plot {p}: no hall floor found — build the town first")
    G = floors[0][2] + 5 - 45
    adds, removes, ladder = tower_pieces(G)
    _, row, col = S.plot_coords(p)
    cells = [[0, col * S.PLOT + du, row * S.PLOT + dv, h, 0] for du, dv, h in ladder_cells(G)]
    if tower_present(boxes):
        want = [b for b in ladder if b not in boxes]
        if DRY:
            print(f"plot {p}: the tower stands; would clear {len(cells)} block cells of the old ladder and set {len(want)} ladder pieces"); return
        _, ref3, _ = await world.apply(WHO, cells)
        added, _, ref2 = await world.boxes(WHO, p, want, [])
        print(f"plot {p}: the tower stands already; {len(cells) - len(ref3)} old ladder cells cleared, {len(added)} ladder pieces set"
              + (f"; refused: {ref2[:4]}" if ref2 else "")); return
    missing = [b for b in removes if b not in boxes]
    if missing:
        sys.exit(f"plot {p}: the hall wall to take out is not there: {missing}")
    if DRY:
        print(f"plot {p}: would take out {len(removes)}, set {len(adds)} pieces ({len(ladder)} of them the ladder) (G {G})"); return
    _, removed, ref = await world.boxes(WHO, p, [], removes)
    added, _, ref2 = await world.boxes(WHO, p, adds, [])
    print(f"plot {p}: {len(removed)} wall piece out, {len(added)} tower pieces set ({len(ladder)} ladder pieces among them)"
          + (f"; refused: {(ref + ref2)[:4]}" if ref or ref2 else ""))
    print("the server wallet keeps:", {k: pl["items"].get(k, 0) for k in ("stonebrick", "planks", "beam", "tiles", "plaster", "window", "door", "ladder", "torch")})


async def untower(world, pl):
    """The first build's tower (TOWER_V1: it stood in the west street) taken down: its pieces removed, the hall's west
    wall made whole again, its ladder cells cleared — only what tower_pieces(G, TOWER_V1) names, nothing else."""
    p = plot_at(ROWS[1], COLS[1])
    boxes = (world.plots.get(p) or {}).get("boxes", [])
    if not tower_present(boxes, TOWER_V1):
        print(f"plot {p}: no tower of the first build stands"); return
    floors = [b for b in boxes if b[6] == PL and b[3] == HALL["W"] and b[4] == HALL["D"] and b[5] == 5]
    G = floors[0][2] + 5 - 45
    adds, removes, _ = tower_pieces(G, TOWER_V1)
    ladder = ladder_cells(G, TOWER_V1)
    there = [b for b in adds if b in boxes]
    if DRY:
        print(f"plot {p}: would take down {len(there)} pieces, put back {len(removes)}, clear {len(ladder)} ladder cells"); return
    _, removed, ref = await world.boxes(WHO, p, [], there)
    added, _, ref2 = await world.boxes(WHO, p, removes, [])
    _, row, col = S.plot_coords(p)
    cells = [[0, col * S.PLOT + du, row * S.PLOT + dv, h, 0] for du, dv, h in ladder]
    _, ref3, _ = await world.apply(WHO, cells)
    print(f"plot {p}: {len(removed)} pieces taken down, {len(added)} wall piece back, {len(cells) - len(ref3)} ladder cells cleared"
          + (f"; refused: {(ref + ref2)[:4]} {ref3[:3]}" if ref or ref2 or ref3 else ""))


async def green(world, town, until):
    """The town's bare earth greens over by the game's own rule (World.spread: earth under open air turns to grass, fast
    beside grass), fast-forwarded until none is left — only on the town's plots."""
    real = world.holder
    async def only_town(p):
        return await real(p) if p in town else None
    world.holder = only_town
    t0 = 1_900_000_000
    for i in range(until):
        await world.spread(t0 + i * S.SPREAD_S)
    world.holder = real


async def main():
    if not DRY and not REHEARSE:
        try:
            urllib.request.urlopen("http://127.0.0.1:9176/land/api/challenge?kind=agent", timeout=3)  # nosec B310 # the operator's own service
            sys.exit("nado-land is running — stop it first (the service would write over this build)")
        except SystemExit:
            raise
        except Exception:
            pass
    src = open(os.path.join(REPO, "static", "land.js")).read()
    cid = src.split('const CID = "', 1)[1].split('"', 1)[0]
    world = S.World(DATA, EX, cid)
    from aiohttp import ClientSession, ClientTimeout
    world.http = ClientSession(timeout=ClientTimeout(total=10))     # what the service opens at start (titles, holders)
    await world.start_oracle()
    world.work = lambda who, s: True                  # the town is built at once, not at a hand's pace
    world.take = lambda who, n: True
    if REHEARSE:
        town = {plot_at(r, c) for r in ROWS for c in COLS}
        real = world.holder
        async def holder(p):
            return WHO if p in town else await real(p)
        world.holder = holder
    # the town's titles must be the server wallet's
    for r in ROWS:
        for c in COLS:
            h = await world.holder(plot_at(r, c))
            if h != WHO and not DRY:
                sys.exit(f"plot {plot_at(r, c)} is held by {h}, not the server wallet — mint the first wave first")
    pl = world.player(WHO)
    for k in ("axe", "pick", "shovel"):
        if k not in pl["tools"]:
            pl["tools"].append(k)
    endow = {"dirt": 400} if REPAIR else ENDOW            # the repair's earth: what levelling exactly takes, at most
    if TOWER_MODE or UNTOWER:                              # the tower's stone, planks, tiles, a beam, windows, a door, a ladder, torches
        endow = {"stonebrick": 500, "planks": 40, "beam": 6, "tiles": 40, "plaster": 12, "window": 14, "door": 1, "ladder": 20, "torch": 2}
    if LIGHTS:
        endow = dict(endow, lamppost=endow.get("lamppost", 0) + 12)
    if GARDEN:                                             # the garden's plants, water and stone — all things a player gets
        extra = {"poppy": 80, "cornflower": 80, "daisy": 80, "buttercup": 80, "sapling": 9, "water": 40, "stonebrick": 20, "torch": 2}
        endow = {k: endow.get(k, 0) + extra.get(k, 0) for k in set(endow) | set(extra)}   # added to, never in place of
    for k, n in endow.items():
        pl["items"][k] = pl["items"].get(k, 0) + n
    print("endowed the server wallet with", json.dumps(endow))

    if TOWER_MODE or UNTOWER:
        if UNTOWER:
            await untower(world, pl)
        if TOWER_MODE:
            await build_tower(world, pl)
        world.flush()
        world.oracle.kill(); await world.oracle.wait()
        await world.http.close()
        return
    # 1. level the site at the median ground top T: clear everything above (trees, litter, ground), fill dips with earth
    t = terrain()
    tops = sorted(x[2] for x in t["tops"])
    T = tops[len(tops) // 2]
    top = {(u, v): h for u, v, h in t["tops"]}
    # cleared: everything above the level, and anything lying on a low column below it (litter, a sapling) before its fill
    cells = [] if REPAIR else [[0, u, v, h, 0] for u, v, h, b in t["above"] if h > T or h > top[(u, v)]]
    if not REPAIR:
        for (u, v), h in top.items():
            for hh in range(h + 1, T + 1):
                cells.append([0, u, v, hh, DIRT])
    print(f"level {T}: {sum(1 for c in cells if c[4] == 0)} cells cleared, {sum(1 for c in cells if c[4] == DIRT)} filled")
    refused = []
    for i in range(0, len(cells), 2000):
        if not DRY:
            _, ref, _ = await world.apply(WHO, cells[i:i + 2000])
            refused += ref
    # a tree's cells above its cut trunk came down with it (FELLING), so clearing them later finds air: not a refusal
    if refused:
        now = await world.blocks_at([r[0][:4] for r in refused if isinstance(r[0], list)])
        refused = [r for r in refused if not (isinstance(r[0], list) and r[0][4] == 0 and now.get(tuple(r[0][:4])) == 0)]
    # then EXACTLY level (true_level): the clearing and filling above leave the untouched columns at T drawn below T + 1
    exact = await true_level(world, T, sorted(top), set(t["natural"]))
    print(f"exact level at {T + 1}: {len(exact)} cells")
    for i in range(0, len(exact), 2000):
        if not DRY:
            _, ref, _ = await world.apply(WHO, exact[i:i + 2000])
            refused += ref
    if refused:
        from collections import Counter
        print("level: refused", len(refused), dict(Counter(r[1] for r in refused)), refused[:6])

    # 2. pieces, per plot (a piece never spans plots). y is absolute cm; the paving slab is sunk into the top layer.
    G = (T + 1) * 100                                  # the level ground's top, cm
    pieces = {plot_at(r, c): [] for r in ROWS for c in COLS}
    def put(r, c, b):
        pieces[plot_at(r, c)].append(b)
    # streets: 4 m wide on the plot boundaries (2 m in each plot), stone brick with cobble kerbs, 30 cm slab, top 5 cm
    # above the ground; the cross leaves a 14 x 14 m quarter in each plot
    for r in ROWS:
        for c in COLS:
            west = c == COLS[1]                        # the N-S street runs along this plot's west edge (else its east)
            north = r == ROWS[1]                       # the E-W street along this plot's north edge (else its south)
            sx = 0 if west else 1400
            sz = 0 if north else 1400
            put(r, c, [sx, 0, G - 25, 200, 1600, 30, SB])                       # the N-S street's half
            # the E-W street's half, leaving the N-S street's crossing to the first slab
            put(r, c, [200 if west else 0, sz, G - 25, 1400, 200, 30, SB])
            # kerbs along the quarter's street sides
            kx = 200 if west else 1390
            put(r, c, [kx, (200 if north else 0), G - 25, 10, 1400, 35, COB])
            kz = 200 if north else 1390
            put(r, c, [(210 if west else 0), kz, G - 25, 1390, 10, 35, COB])   # stops short of the other kerb
    hr, hc = ROWS[1], COLS[1]
    hall = hall_pieces(G)
    for b in hall:
        put(hr, hc, b)
    # benches and torches along the streets in the other three quarters
    for r, c in ((ROWS[0], COLS[0]), (ROWS[0], COLS[1]), (ROWS[1], COLS[0])):
        west, north = c == COLS[1], r == ROWS[1]
        bx = 230 if west else 1220
        bz = 230 if north else 1335
        # on the ground (G), beside the street — they stood at G + 5, the slab's top, and hung over the grass
        put(r, c, [bx, 600, G, 35, 150, 45, BENCH])
        put(r, c, [600, bz, G, 150, 35, 45, BENCH])
        put(r, c, [bx + (40 if west else -20), 300, G, 10, 10, 120, TORCH])
        put(r, c, [bx + (40 if west else -20), 1100, G, 10, 10, 120, TORCH])
    total = 0
    for p, bs in pieces.items():
        bs = [b for b in bs if b]
        total += len(bs)
        if DRY:
            continue
        if REPAIR:
            # only the benches and torches that stood at G + 5 come down to G (everything else stands as built)
            old = [b for b in (world.plots.get(p) or {}).get("boxes", []) if b[6] in (BENCH, TORCH) and b[2] == G + 5]
            new = [b for b in bs if b[6] in (BENCH, TORCH) and b[2] == G and any(o[:2] == b[:2] for o in old)]
            if old:
                _, removed, ref = await world.boxes(WHO, p, [], old)
                added, _, ref2 = await world.boxes(WHO, p, new, [])
                print(f"plot {p}: {len(removed)} pieces lifted, {len(added)} set down on the ground" + (f", refused: {(ref + ref2)[:4]}" if ref or ref2 else ""))
            continue
        added, _, ref = await world.boxes(WHO, p, bs, [])
        print(f"plot {p}: {len(added)} pieces placed" + (f", {len(ref)} refused: {ref[:4]}" if ref else ""))
    if GARDEN and not DRY:
        refused = []
        for p, (gcells, gpieces) in garden(T, G).items():
            for i in range(0, len(gcells), 500):
                _, ref, _ = await world.apply(WHO, gcells[i:i + 500])
                refused += ref
            added, _, ref = await world.boxes(WHO, p, gpieces, [])
            refused += ref
            print(f"garden on plot {p}: {len(gcells)} cells, {len(added)} pieces")
        if refused:
            from collections import Counter
            print("garden: refused", len(refused), dict(Counter(str(r[1]) for r in refused)))
        await green(world, set(pieces), 120)
        bare = sum(1 for p in pieces for (x, z, y), b in world.plots[p]["edits"].items() if y == T and b == DIRT)
        print(f"greened: {bare} cells of bare earth left at the surface")
    if LIGHTS and not DRY:
        for p, ls in lamps(G).items():
            added, _, ref = await world.boxes(WHO, p, ls, [])
            print(f"lights on plot {p}: {len(added)} street lamps" + (f", refused: {ref[:3]}" if ref else ""))
    print(f"{total} pieces planned; the server wallet keeps what is left of its endowment:",
          {k: pl['items'].get(k, 0) for k in set(ENDOW) | set(endow)})
    if not DRY:
        world.flush()
    world.oracle.kill(); await world.oracle.wait()
    await world.http.close()

if __name__ == "__main__":
    asyncio.run(main())
