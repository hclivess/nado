"""
The town square (operator 2026-11-07: "parts of the road are hanging in the air, and so is one of the benches", then
"make the town tile beautiful so it attracts people, use only assets from the game (they must be available to all
players)... if anything is amiss, add it", and "make people spawn by the town hall by default"):

  1. scripts/land_town.py, rehearsed from scratch on an empty world (its build and its garden through the world
     server's own World.apply / World.boxes, nothing refused): every one of the town's 1,024 columns is EXACTLY level —
     an edited ground cell at T and an edited air cell at T + 1, so the drawn surface lies at T + 1 under every road
     slab (an untouched column drew its ground up to a metre lower); benches and street torches stand ON the ground;
  2. the garden is made of things any player gets: wild flowers (picked on the meadows, where they grow in drifts),
     water (scooped with a bucket made at a workbench), saplings, stone brick — flowers and saplings planted in soil,
     water in cells dug at T with ground under it, the town greened over by the game's own spreading rule;
  3. the world server's rules: a flower is planted only in earth or grass; a bucket scoops water and nothing scoops it
     without one; water is placed only where something holds it;
  4. the page draws what lies on levelled ground at the cell's floor, not at the column's untouched height, and draws
     no dug-earth tint over grass grown back; a newcomer arrives in front of the town hall's door, and /tp spawn goes
     there; the new names are in 17 languages.

Run: python3 tests/test_the_town_square_is_exactly_level_and_its_garden_is_made_of_things_any_player_gets.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-town-square-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
R = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
WORLD = json.dumps(os.path.join(ROOT, "static", "land-world.js"))
TOWN = [40955247, 40955248, 40963439, 40963440]
POPPY, CORNFLOWER, DAISY, BUTTERCUP, SAPLING, WATER, BENCH, TORCH = 58, 59, 60, 61, 52, 5, 47, 50

# 1 + 2. the whole town, built and gardened from scratch on an empty world
data = os.path.join(os.environ["HOME"], "planet")
os.makedirs(data)
env = dict(os.environ, LAND_DATA=data, LAND_EXEC="http://127.0.0.1:1")
r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "land_town.py"), "--rehearse", "--garden", "--lights"], capture_output=True,
                   text=True, timeout=1500, env=env)
out = r.stdout
check("the town is built and gardened through the world server's own rules, nothing refused",
      r.returncode == 0 and "refused" not in out and "exact level at 137" in out and "garden on plot 40963439" in out, (out[-800:], r.stderr[-800:]))
T = 136
recs = {p: json.load(open(os.path.join(data, f"{p}.json"))) for p in TOWN} if r.returncode == 0 else {}
NAT = set(json.loads(subprocess.run(["node", "--input-type=module", "-e", f"const W = await import({WORLD}); console.log(JSON.stringify([...W.NATURAL]))"],
                                    capture_output=True, text=True, timeout=60).stdout))
edits = {}
for p, d in recs.items():
    face, row, col = S.plot_coords(p)
    for k, b in d["edits"].items():
        x, z, y = map(int, k.split(":"))
        edits[(col * 16 + x, row * 16 + z, y)] = b
U0, V0 = 3439 * 16, 4999 * 16
level = [(u, v) for u in range(U0, U0 + 32) for v in range(V0, V0 + 32)
         if edits.get((u, v, T + 1)) in (0, POPPY, CORNFLOWER, DAISY, BUTTERCUP, SAPLING) and (edits.get((u, v, T)) in NAT or edits.get((u, v, T)) == WATER)]
check(f"every one of the town's 1,024 columns is exactly level ({len(level)}): edited ground at {T}, edited air (or a plant) at {T + 1}",
      len(level) == 1024, 1024 - len(level))
G = (T + 1) * 100
seats = [b for d in recs.values() for b in d["boxes"] if b[6] in (BENCH, TORCH) and b[2] < G + 40]
check("benches and street torches stand on the ground, none above it", seats and all(b[2] == G for b in seats), sorted({b[2] for b in seats}))
flowers = [(k, b) for k, b in edits.items() if b in (POPPY, CORNFLOWER, DAISY, BUTTERCUP)]
check(f"the garden's {len(flowers)} flowers and its saplings stand in soil on the level ground",
      len(flowers) > 100 and all(k[2] == T + 1 and edits.get((k[0], k[1], T)) in (S.GRASS, S.DIRT) for k, b in flowers)
      and sum(1 for b in edits.values() if b == SAPLING) == 9)
water = [k for k, b in edits.items() if b == WATER]
check(f"its pond and fountain ({len(water)} cells of water) lie in cells dug at {T}, ground under every one",
      len(water) == 28 and all(k[2] == T and edits.get((k[0], k[1], T - 1), 2) != 0 for k in water))
lamps = [b for d in recs.values() for b in d["boxes"] if b[6] == 63]
check("twelve street lamps stand on the ground round the town's streets", len(lamps) == 12 and all(b[2] == (T + 1) * 100 for b in lamps), lamps)
# a repair run over the finished town levels nothing that is the garden's: its pond and fountain keep their water, and
# what stands on the ground (flowers, saplings, a grown tree's logs) stays — a repair once cleared every one of them
# (2026-11-07; the live town was restored from the backup taken before the run)
def standing():
    from collections import Counter
    c = Counter()
    for p in TOWN:
        for k, b in json.load(open(os.path.join(data, f"{p}.json")))["edits"].items():
            if int(k.split(":")[2]) >= T + 1 and b:
                c[b] += 1
    return c
before = standing()
r2 = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "land_town.py"), "--rehearse", "--repair"], capture_output=True,
                    text=True, timeout=1500, env=env)
water2 = sum(1 for p in TOWN for b in json.load(open(os.path.join(data, f"{p}.json")))["edits"].values() if b == WATER)
check("a repair over the finished town refuses nothing and leaves the garden's water", r2.returncode == 0 and "refused" not in r2.stdout and water2 == 28,
      (r2.stdout[-400:], water2))
check("…and leaves everything standing on the ground as it was (flowers, saplings)", before and standing() == before, (before, standing()))
check("…changing no cell at all of a town already level", "exact level at 137: 0 cells" in r2.stdout, r2.stdout[-300:])
fountain = [b for b in recs.get(40963439, {}).get("boxes", []) if b[6] == 16 and 400 <= b[0] <= 1000 and 600 <= b[1] <= 1200]
check("the fountain's basin and pillar are stone brick", len(fountain) == 5, fountain)
bare = sum(1 for (u, v, y), b in edits.items() if y == T and b == S.DIRT and edits.get((u, v, T + 1)) == 0)
check("the town has greened over by the game's own rule (no bare earth under open air)", bare == 0, bare)

# every material of the garden is one any player gets, from bare hands
have, tools, st = set(), set(), set()
cls = lambda c: any(t == c or R["tools"][t].get("class") == c for t in tools)
grew = True
while grew:
    grew = False
    for rr in R["breaking"].values():
        if not isinstance(rr, dict) or (rr.get("needs") and not cls(rr["needs"])):
            continue
        for i, _ in (rr.get("yields") or []) + ([rr["bonus"]] if rr.get("bonus") else []):
            if i not in have:
                have.add(i); grew = True
    for rr in R["recipes"]:
        if not isinstance(rr, dict) or not all(i in have for i, _ in rr["uses"]) or not all(x in st or cls(x) for x in rr.get("with", [])):
            continue
        for i, _ in rr["makes"]:
            box = tools if i in R["tools"] else st if i in R["stations"] else have
            if i not in box:
                box.add(i); grew = True
check("every material of the garden is one a player gets from bare hands (flowers, water in a bucket, saplings, stone brick)",
      {"poppy", "cornflower", "daisy", "buttercup", "water", "sapling", "stonebrick", "torch"} <= have and "bucket" in tools,
      sorted({"poppy", "cornflower", "daisy", "buttercup", "water", "sapling", "stonebrick", "torch"} - have))
js = """
const W = await import(%s); const seen = {}; let all = 0;
for (let u = 0; u < 400; u++) for (let v = 0; v < 400; v++) { const f = 0, uu = 55000 + u, vv = 79600 + v, c = W.column(f, uu, vv);
  const b = W.litterAt(f, uu, vv, c); if (W.FLOWERS.includes(b)) { seen[b] = (seen[b] || 0) + 1; all++; } }
console.log(JSON.stringify({ seen, all, n: W.BLOCKS.length }));
""" % WORLD
J = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=300).stdout)
check(f"wild flowers grow on the meadows round the landing, every kind ({J['seen']})", len(J["seen"]) == 4 and J["all"] > 200, J)
check("the world server knows every block", S.N_BLOCKS == J["n"])


# 3. the world server's rules for flowers, buckets and water
async def rules():
    w = S.World(os.path.join(os.environ["HOME"], "rules"), "http://127.0.0.1:1", "")
    await w.start_oracle()
    w.work = lambda who, s: True
    w.take = lambda who, n: True
    A = "ndoGARD" + "G" * 41
    pl = w.player(A)
    pl["items"].update({"poppy": 2, "water": 2})
    f, u, v = 0, 3435 * 16 + 8, 4995 * 16 + 8
    col = (await w.terrain([[f, u, v, h] for h in range(130, 160)]))
    top = 130 + max(i for i, b in enumerate(col) if b in (S.GRASS, S.DIRT))
    clear = [] if col[top + 1 - 130] == 0 else [[f, u, v, top + 1, 0]]          # litter on it is picked first
    _, ref, _ = await w.apply(A, [[f, u, v, top + 3, POPPY]])
    check("a flower is not planted in the air", ref and "earth or grass" in ref[0][1], ref)
    _, ref, _ = await w.apply(A, clear + [[f, u, v, top + 1, POPPY]])
    check("…and is planted in the meadow's soil", not ref, ref)
    _, ref, _ = await w.apply(A, [[f, u + 1, v, top + 3, WATER]])
    check("water is not placed where nothing holds it", ref and "something under it" in ref[0][1], ref)
    _, ref, _ = await w.apply(A, [[f, u + 1, v, top, 0], [f, u + 1, v, top, WATER]])
    check("…and is, into a dug cell with ground under it", not ref, ref)
    _, ref, _ = await w.apply(A, [[f, u + 1, v, top, 0]])
    check("nothing scoops water without a bucket", ref and "bucket" in ref[0][1], ref)
    pl["tools"].append("bucket")
    n0 = pl["items"].get("water", 0)
    _, ref, _ = await w.apply(A, [[f, u + 1, v, top, 0]])
    check("a bucket scoops it back: a bucketful in the bag", not ref and pl["items"].get("water", 0) == n0 + 1, (ref, pl["items"]))
    w.oracle.kill(); await w.oracle.wait()


asyncio.run(rules())

# 4. the page
mesher = open(os.path.join(ROOT, "static", "land-mesher.js"), encoding="utf-8").read()
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
check("what lies on levelled ground is drawn at the cell's floor, not the column's untouched height",
      "const col = edited || gh !== col0.top + 1 ? { height: gh } : col0;" in mesher)
check("…and grass grown back over dug ground is drawn as grass, not bare earth", "=== B.grass)) dug[x] = 1;" in mesher)
q = (TOWN[3] // 8192) % 8192, TOWN[3] % 8192
check("a newcomer arrives on the street before the town hall's door, facing it; /tp spawn goes there too",
      "const TOWN_HALL_PLOT = 40963440;" in page and "return [q.face, q.u0 + 8.5, q.v0 + 1.5, 0];" in page
      and "[P.face, P.u, P.v, P.yaw] = townSpawn();" in page
      # /tp spawn (rewritten by #167: signed in, the world server moves the player to ITS landing; a visitor's page
      # goes to townSpawn itself) — the pin had kept the wording of the page before #167 and was red since (#189)
      and "const sp = townSpawn(); P.face = sp[0]; P.u = sp[1]; P.v = sp[2]; P.yaw = sp[3];" in page
      and 'if (net.online && net.me) return net.send({ t: "tp", to });' in page)
_srv_src = open(os.path.join(ROOT, "scripts", "land_server.py"), encoding="utf-8").read()
check("…and the world server's landing is the same place: the town hall's plot, 8.5 m in, 1.5 m up the street",
      "TOWN_HALL_PLOT = 40963440" in _srv_src and "return [face, col * PLOT + 8.5, row * PLOT + 1.5]" in _srv_src
      and "to = landing() + [None]" in _srv_src)
check("with a bucket, the first water the view crosses is scooped", "if (a.water && hasClass(\"bucket\")) return startBreak(a.water, mouse);" in page)
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = ["land.i.poppy", "land.i.cornflower", "land.i.daisy", "land.i.buttercup", "land.i.water", "land.t.bucket"]
check("the new names are in 17 languages", len(tr) == 17 and all(all(l.get(k) for k in keys) for l in tr.values()))
_report.done()
