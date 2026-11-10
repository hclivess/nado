"""
"pick recommended" (operator 2026-11-10, #168 option a): stags killed players who stood still — in the bag, a panel,
building — four times in three hours on the town agent. Settled land is safe; the wild stays dangerous. The world
server (scripts/land_server.py herd, tame):

  * in the wild an angry stag charges and strikes a player (as before, #162);
  * on a plot with a piece built on it, the same stag beside the player strikes nothing, and does not charge;
  * a stag outside such a plot does not walk onto it — it turns back at the edge;
  * an animal already on it (the plot was built on around it) may still walk out;
  * in the town no animal is spawned, however long the herd runs around a player standing there;
  * the town's plots and a built-on plot are tame, a bare plot in the wild is not.

Run: python3 tests/test_animals_keep_off_the_town_and_plots_with_buildings_and_strike_no_one_there.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-tame-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, json, math, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
RULES = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
HN = RULES["hunting"]

js = """
const W = await import(%s);
const at = (u, v) => [0, u + 0.5, v + 0.5, W.column(0, u, v).height + 0.05, 0];
console.log(JSON.stringify({ wild: at(55031, 79905), town: at(55039, 79999) }));
""" % json.dumps(os.path.join(ROOT, "static", "land-world.js"))
HERE = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=120).stdout)


async def main():
    data = tempfile.mkdtemp(prefix="nado_land_tame_", dir=os.environ["HOME"])
    world = S.World(data, "http://127.0.0.1:9", "c" * 32)
    await world.start_oracle()                                   # the herd asks the terrain oracle for ground and biome
    me, pos = "a" * 50, HERE["wild"]
    p = S.plot_of(0, int(pos[1]), int(pos[2]))
    fc, fr = p % S.FACE_N, (p // S.FACE_N) % S.FACE_N
    u0, v0 = fc * S.PLOT, fr * S.PLOT

    def animal(kind, u, v, angry=True):
        world.animal_seq += 1
        a = {"id": world.animal_seq, "kind": kind, "face": 0, "u": u, "v": v, "h": pos[3], "yaw": 0.0,
             "hp": HN["species"][kind]["hp"], "go": 1e18, "flee": 0, "angry": angry}
        world.animals[a["id"]] = a
        return a

    async def step(n=1, at=None):
        hits = []
        for _ in range(n):
            hits += await world.herd([at or pos], players=[(me, at or pos)]) or []
        return hits

    # ---- the tame rule ----------------------------------------------------------------------------------------------
    check("a bare plot in the wild is not tame", not world.tame(0, pos[1], pos[2]))
    check("the town's plots are", all(world.tame(0, (q % S.FACE_N) * S.PLOT + 8, (q // S.FACE_N) * S.PLOT + 8) for q in S.TOWN_PLOTS))

    # ---- the wild: as before ----------------------------------------------------------------------------------------
    stag = animal("deer", pos[1] + 1.2, pos[2])
    hits = await step()
    check("in the wild a stag beside a player strikes", hits == [(me, HN["species"]["deer"]["damage"], "deer")], hits)
    world.animals.clear()

    # ---- a built-on plot ----------------------------------------------------------------------------------------------
    world.plot(p)["boxes"].append([100, 100, int(pos[3] * 100), 100, 100, 100, S.CHEST])
    check("a piece built on it makes the plot tame", world.tame(0, pos[1], pos[2]))
    stag = animal("deer", pos[1] + 1.2, pos[2])
    d0 = (stag["u"], stag["v"])
    hits = await step(4)
    check("on it, the same stag beside the player strikes nothing", hits == [], hits)
    check("…and does not charge them", math.hypot(stag["u"] - pos[1], stag["v"] - pos[2]) >= 1.2 - 0.01, (d0, stag["u"], stag["v"]))
    world.animals.clear()
    # a stag outside the plot, the player inside it near the edge: it would charge in — it turns back at the edge
    edge = [0, u0 + 1.5, pos[2], pos[3], 0]
    out = animal("deer", u0 - 4, pos[2])
    for _ in range(12):
        await world.herd([edge], players=[(me, edge)])
        if world.tame(0, out["u"], out["v"]):
            break
    check("a stag outside does not walk onto it", not world.tame(0, out["u"], out["v"]), (out["u"], out["v"], u0))
    world.animals.clear()
    # one already on it (the plot was built on around it) walks out when it flees
    inside = animal("deer", pos[1] + 3, pos[2], angry=False)
    u_in = inside["u"]
    inside["flee"] = 1e18
    await world.herd([pos], players=[])
    check("an animal already on it may still walk off", inside["u"] != u_in, (u_in, inside["u"]))
    world.animals.clear()

    # ---- the town: none spawned ---------------------------------------------------------------------------------------
    town = HERE["town"]
    check("the town's middle is tame", world.tame(0, town[1], town[2]))
    spawned, inside = 0, []
    for _ in range(40):                                         # cleared each step, so the herd keeps spawning anew
        await world.herd([town], players=[(me, town)])
        spawned += len(world.animals)
        inside += [(a["u"], a["v"]) for a in world.animals.values() if world.tame(0, a["u"], a["v"])]
        world.animals.clear()
    check(f"around a player in the town the herd spawns, outside it ({spawned} in 40 steps)", spawned > 0, spawned)
    check("…and never in the town", inside == [], inside[:5])
    world.oracle.kill(); await world.oracle.wait()


asyncio.run(main())
_report.done()
