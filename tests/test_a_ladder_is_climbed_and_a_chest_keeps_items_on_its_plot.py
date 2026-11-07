"""
More structures in Land (#114): a ladder the walker climbs and a chest that keeps items on its plot.

  1. both are reachable from bare hands and are unit pieces drawn as their models (a ladder's rails and a rung every
     30 cm; a chest's body, lid and bands) inside their boxes;
  2. the walker on a ladder (land-walk.js climb): no gravity — it rises when climbing, holds still when nothing is
     pressed (it would fall without the ladder), and the page climbs only within a ladder's reach;
  3. the chest, through the world server's own methods: items move from the bag into it and back exactly (all or
     nothing — a call that cannot move everything it names moves nothing, and nobody puts in what they lack); on an
     OWNED plot only its owner and builders open it; a chest holding anything cannot be taken down (its items are never
     lost with it), an empty one can; its contents survive a restart;
  4. the world server knows every block, and the new names and chest strings are in 17 languages.

Run: python3 tests/test_a_ladder_is_climbed_and_a_chest_keeps_items_on_its_plot.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-ladder-chest-")
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

# 1 + 2: rules, models and the walker, in node (the page's own modules)
js = """
const W = await import(%s), M = await import(%s), K = await import(%s);
const R = %s, B = W.B;
const have = new Set(), tools = new Set(), st = new Set();
const cls = (c) => [...tools].some((t) => t === c || R.tools[t].class === c);
for (let g = true, n = 0; g && n < 60; n++) { g = false;
  for (const r of Object.values(R.breaking)) { if (!r.yields || (r.needs && !cls(r.needs))) continue; for (const [i] of r.yields) if (!have.has(i)) { have.add(i); g = true; } if (r.bonus && !have.has(r.bonus[0])) { have.add(r.bonus[0]); g = true; } }
  for (const r of R.recipes) { if (!r.uses.every(([i]) => have.has(i)) || !(r.with || []).every((w) => st.has(w) || cls(w))) continue;
    for (const [i] of r.makes) { const s = i in R.tools ? tools : i in R.stations ? st : have; if (!s.has(i)) { s.add(i); g = true; } } } }
const inside = (k) => { const u = R.items[k].unit, L = Math.max(u[0], u[1]), S_ = Math.min(u[0], u[1]), parts = M.MODELS[B[k]](L, S_, u[2]);
  return { n: parts.length, ok: parts.every(([l0, l1, s0, s1, y0, y1]) => l0 >= 0 && l1 <= L && s0 >= 0 && s1 <= S_ && y0 >= 0 && y1 <= u[2]) }; };
// the walker: a body in open air with climb on and vh = 0 holds; with climb off it falls; climbing it rises
const open = () => false;
const mk = () => ({ u: 0.5, v: 0.5, h: 10, vu: 0, vv: 0, vh: 0, fly: false, ground: false });
const C = { GRAV: 22, JUMP: 7, STEP: 0.55 };
const a = mk(); a.climb = true; for (let i = 0; i < 30; i++) K.walk(a, [0, 0], false, 1 / 60, open, C);
const b = mk(); for (let i = 0; i < 30; i++) K.walk(b, [0, 0], false, 1 / 60, open, C);
const c = mk(); c.climb = true; for (let i = 0; i < 30; i++) { c.vh = 1.8; K.walk(c, [0, 0], false, 1 / 60, open, C); }
console.log(JSON.stringify({ reach: ["ladder", "chest"].every((k) => have.has(k)), ladder: inside("ladder"), chest: inside("chest"),
  hold: a.h, fall: b.h, climb: c.h, blocks: W.BLOCKS.length }));
""" % tuple(json.dumps(x) for x in (os.path.join(ROOT, "static", "land-world.js"), os.path.join(ROOT, "static", "land-mesher.js"),
                                  os.path.join(ROOT, "static", "land-walk.js"), R))
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=300)
J = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
check("a ladder and a chest are reachable from bare hands", J.get("reach"), r.stderr[-400:])
check("a ladder is drawn as rails and a rung every 30 cm, a chest as body, lid and bands — inside their boxes",
      J.get("ladder", {}).get("ok") and J["ladder"]["n"] >= 2 + 9 and J.get("chest", {}).get("ok") and J["chest"]["n"] == 4, J)
check("on a ladder the walker holds still with nothing pressed (it would fall without one)",
      abs(J.get("hold", 0) - 10) < 1e-9 and J.get("fall", 10) < 9.9, J)
check("…and climbs when climbing", J.get("climb", 0) > 10.8, J)
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
check("the page climbs only within a ladder's reach (45 cm around it, from 1.5 m under its foot to its top)",
      "const lad = !P.fly && ladderNear();" in page and "c.x > b[0] - 45 && c.x < b[0] + b[3] + 45" in page and "c.y > b[2] - 150 && c.y < b[2] + b[5]" in page
      and "P.vh = up ? CLIMB : down && !P.ground ? -CLIMB : 0;" in page)

# 3: the chest, through the world server
A, Bp, OWNER = "ndoCHSA" + "A" * 41, "ndoCHSB" + "B" * 41, "ndoOWNR" + "O" * 41


async def main():
    data = os.path.join(os.environ["HOME"], "land")
    w = S.World(data, "http://127.0.0.1:1", "")
    owned = set()
    async def holder(q):
        return OWNER if q in owned else None
    async def may_build(q, a):
        return q not in owned or a == OWNER
    w.holder, w.may_build = holder, may_build
    w.work = lambda who, s: True
    pa = w.player(A); pa["items"].update({"chest": 2, "stone": 10, "wood": 3}); pa["tools"] += ["axe"]
    p = 4995 * 8192 + 3435
    box = [200, 200, 15000, 90, 50, 55, 54]
    added, _, ref = await w.boxes(A, p, [box], [])
    check("a chest is placed as a unit piece", added == [box], ref)
    items, err = await w.chest(A, p, box, {"stone": 4, "wood": 3}, {})
    check("items go into the chest exactly", not err and items == {"stone": 4, "wood": 3} and pa["items"].get("stone") == 6 and "wood" not in pa["items"], (items, err, pa["items"]))
    items, err = await w.chest(A, p, box, {"stone": 99}, {})
    check("nobody puts in what they lack (and nothing moves)", err and w.plots[p]["chests"][S.chest_key(box)] == {"stone": 4, "wood": 3} and pa["items"]["stone"] == 6, err)
    items, err = await w.chest(A, p, box, {"stone": 1}, {"wood": 9})
    check("all or nothing: a call that cannot move everything moves nothing", err and pa["items"]["stone"] == 6 and w.plots[p]["chests"][S.chest_key(box)]["wood"] == 3, err)
    pb = w.player(Bp)
    items, err = await w.chest(Bp, p, box, {}, {"wood": 2})
    check("in the commons a chest is everyone's", not err and pb["items"].get("wood") == 2 and items["wood"] == 1, err)
    _, rem, ref = await w.boxes(A, p, [], [box])
    check("a chest holding anything cannot be taken down", not rem and ref and "empty the chest" in ref[0][1], ref)
    w.flush()
    w2 = S.World(data, "http://127.0.0.1:1", "")
    check("its contents survive a restart", w2.plots[p]["chests"][S.chest_key(box)] == {"stone": 4, "wood": 1})
    owned.add(p)
    items, err = await w.chest(Bp, p, box, {}, {"stone": 1})
    check("on an owned plot only its owner and their builders open it", err and "not your plot" in err, err)
    owned.discard(p)
    await w.chest(A, p, box, {}, {"stone": 4, "wood": 1})
    _, rem, ref = await w.boxes(A, p, [], [box])
    check("an empty chest comes down and back into the bag", rem == [box] and pa["items"].get("chest") == 2, (rem, ref, pa["items"].get("chest")))


asyncio.run(main())

# 4
srv = int([l for l in open(os.path.join(ROOT, "scripts", "land_server.py")) if l.startswith("N_BLOCKS = ")][0].split()[2])
check("the world server knows every block", srv == J.get("blocks"), (srv, J.get("blocks")))
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = ["land.i.ladder", "land.i.chest", "land.noUse", "land.chestHint", "land.chestIn", "land.chestBag", "land.chestEmpty"]
check("the names and the chest's strings are in 17 languages", len(tr) == 17 and all(all(l.get(k) for k in keys) for l in tr.values()))
_report.done()
