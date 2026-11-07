# land_town.py — the TOWN at the landing (issues #122 #123): the four central plots of the first wave (face 0, rows
# 4999–5000, cols 3439–3440), held by this server's wallet, levelled, with two crossing streets and a town hall.
# The world server's rules hold for the town as for anyone (scripts/land_server.py World.apply / World.boxes: only
# where the caller may build, pieces paid by volume from its bag), so the server wallet is ENDOWED once with the
# materials the build takes — written into its bag here, before the build, and listed in the run's output and in #123.
# Runs OFFLINE on the world's data while nado-land is stopped (the service holds the world in memory and would write
# over a concurrent change): systemctl stop nado-land; HOME=/root python3 scripts/land_town.py; systemctl start.
import asyncio, importlib.util, json, os, subprocess, sys, tempfile, urllib.request
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
spec = importlib.util.spec_from_file_location("land_server", os.path.join(REPO, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
from execnode.games import land as L

DATA, EX = "/srv/nado-home/land/planet0", "http://127.0.0.1:9273"
ROWS, COLS = (4999, 5000), (3439, 3440)
U0, V0 = COLS[0] * 16, ROWS[0] * 16                  # the town's corner, grid units (32 x 32 columns)
WHO = L.ISSUER
# block ids (static/land-world.js B)
PL, COB, SB, TI, PS, BM, DOOR, WIN, TABLE, CHAIR, BENCH, TORCH, CHEST, DIRT = 9, 10, 16, 13, 14, 38, 37, 40, 45, 46, 47, 50, 54, 2
ENDOW = {"stonebrick": 400, "cobble": 120, "planks": 160, "plaster": 160, "beam": 80, "tiles": 160, "dirt": 600,
         "door": 2, "window": 8, "table": 2, "chair": 8, "bench": 8, "torch": 16, "chest": 1}
DRY = "--dry-run" in sys.argv
# --rehearse: the whole build on a COPY of the world's data (LAND_DATA), the town's titles taken as the server wallet's
# — every piece through the world server's own checks, nothing live touched
REHEARSE = "--rehearse" in sys.argv
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
console.log(JSON.stringify({ tops, above }));""" % (json.dumps(os.path.join(REPO, "static", "land-world.js")), U0, V0)
    return json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=600).stdout)


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
    for k, n in ENDOW.items():
        pl["items"][k] = pl["items"].get(k, 0) + n
    print("endowed the server wallet with", json.dumps(ENDOW))

    # 1. level the site at the median ground top T: clear everything above (trees, litter, ground), fill dips with earth
    t = terrain()
    tops = sorted(x[2] for x in t["tops"])
    T = tops[len(tops) // 2]
    top = {(u, v): h for u, v, h in t["tops"]}
    # cleared: everything above the level, and anything lying on a low column below it (litter, a sapling) before its fill
    cells = [[0, u, v, h, 0] for u, v, h, b in t["above"] if h > T or h > top[(u, v)]]
    for (u, v), h in top.items():
        for hh in range(h + 1, T + 1):
            cells.append([0, u, v, hh, DIRT])
    print(f"level {T}: {sum(1 for c in cells if c[4] == 0)} cells cleared, {sum(1 for c in cells if c[4] == DIRT)} filled")
    refused = []
    for i in range(0, len(cells), 2000):
        if not DRY:
            _, ref, _ = await world.apply(WHO, cells[i:i + 2000])
            refused += ref
    if refused:
        from collections import Counter
        print("level: refused", len(refused), dict(Counter(r[1] for r in refused)))

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
    # the town hall: in the quarter of plot (5000, 3440), facing the E-W street to its north
    hr, hc = ROWS[1], COLS[1]
    X0, Z0, W, D, WH = 350, 450, 1000, 800, 280
    hall = []
    hall.append([X0 - 20, Z0 - 20, G - 25, W + 40, D + 40, 65, SB])               # stone footing, up to the floor
    F = G + 45                                                                   # the hall's floor level
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
             [X0 + dx - 30, Z0 - 40, G + 5, 10, 10, 120, TORCH], [X0 + dx + 110, Z0 - 40, G + 5, 10, 10, 120, TORCH]]
    for b in hall:
        put(hr, hc, b)
    # benches and torches along the streets in the other three quarters
    for r, c in ((ROWS[0], COLS[0]), (ROWS[0], COLS[1]), (ROWS[1], COLS[0])):
        west, north = c == COLS[1], r == ROWS[1]
        bx = 230 if west else 1220
        bz = 230 if north else 1335
        put(r, c, [bx, 600, G + 5, 35, 150, 45, BENCH])
        put(r, c, [600, bz, G + 5, 150, 35, 45, BENCH])
        put(r, c, [bx + (40 if west else -20), 300, G + 5, 10, 10, 120, TORCH])
        put(r, c, [bx + (40 if west else -20), 1100, G + 5, 10, 10, 120, TORCH])
    total = 0
    for p, bs in pieces.items():
        bs = [b for b in bs if b]
        total += len(bs)
        if DRY:
            continue
        added, _, ref = await world.boxes(WHO, p, bs, [])
        print(f"plot {p}: {len(added)} pieces placed" + (f", {len(ref)} refused: {ref[:4]}" if ref else ""))
    print(f"{total} pieces planned; the server wallet keeps what is left of its endowment:",
          {k: pl['items'].get(k, 0) for k in ENDOW})
    if not DRY:
        world.flush()
    world.oracle.kill(); await world.oracle.wait()
    await world.http.close()

asyncio.run(main())
