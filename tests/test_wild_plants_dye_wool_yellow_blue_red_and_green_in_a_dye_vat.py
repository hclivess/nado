"""
Plant dyes in Land (#128, "Dyes from plants: e.g. woad, madder, weld ... a dye vat station; a dyed garment keeps its dye"):

  1. four wild plants grow on the planet: weld and woad (pulled by hand) and madder (its roots dug with a shovel) on the
     meadow, clubmoss on the forest floor — litter the world server knows as the page does (swept by a placed block,
     burnt by fire), each drawn as its own model and never as the pebble an unknown litter block falls through to;
  2. a dye vat (fired clay, at the kiln) dyes a woollen cloak or cap: weld yellow and madder red, each fixed with
     clubmoss; woad blue with no mordant (indigo is a vat dye); green is the blue dyed over with weld — all reachable
     from what a player gathers and hunts, each dyed garment worn where the undyed one is, through the world server;
  3. the rules carry their sources, and say the clubmoss mordant is a design choice;
  4. the figure is drawn in each dye's colour, and every name is in 17 languages.

Run: python3 tests/test_wild_plants_dye_wool_yellow_blue_red_and_green_in_a_dye_vat.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-dyes-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import importlib.util, json, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
R = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
PLANTS = {"weld": "weld", "woad": "woad", "madder": "madder_root", "clubmoss": "clubmoss"}
COLOURS = ("yellow", "blue", "red", "green")
GARMENTS = ("woollen_cloak", "woollen_cap")

# 1. on the planet, as the page generates it
js = """
const W = await import(%r);
const ids = Object.fromEntries(%s.map((k) => [k, W.B[k]]));
const count = { grass: {}, forest: {} };
for (let u = 54600; u < 56600; u += 2) for (let v = 79000; v < 81000; v += 7) {
  const c = W.column(0, u, v), b = W.litterAt(0, u, v, c), k = W.BLOCKS[b] && W.BLOCKS[b].key;
  if (k in ids && count[c.biome]) count[c.biome][k] = (count[c.biome][k] || 0) + 1;
}
console.log(JSON.stringify({ ids, count, litter: Object.values(ids).every((b) => W.LITTER.has(b)), swept: Object.values(ids).filter((b) => W.SWEPT.has(b)),
  burns: Object.values(ids).filter((b) => W.BURNS.get(b) === 0), solid: Object.values(ids).some((b) => W.BLOCKS[b].solid) }));
""" % (os.path.join(ROOT, "static", "land-world.js"), json.dumps(list(PLANTS)))
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=300)
J = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
ids, cnt = J.get("ids", {}), J.get("count", {})
check("the four plants are blocks of the planet", len(ids) == 4 and all(isinstance(b, int) for b in ids.values()), (J, r.stderr[-300:]))
check("weld, woad and madder grow on the meadow around the town", all(cnt.get("grass", {}).get(k, 0) > 20 for k in ("weld", "woad", "madder")), cnt)
check("…and clubmoss on the forest floor, not the meadow", cnt.get("forest", {}).get("clubmoss", 0) > 20 and not cnt.get("grass", {}).get("clubmoss"), cnt)
check("they are litter: walked through, swept by a placed block, burnt by fire", J.get("litter") and len(J.get("swept", [])) == 4
      and len(J.get("burns", [])) == 4 and not J.get("solid"), J)
check("the world server sweeps and burns them as the page does", set(ids.values()) <= S.SWEPT and all(S.BURNS.get(b) == 0 for b in ids.values())
      and S.DYE_PLANTS == set(ids.values()))
src = open(os.path.join(ROOT, "static", "land-world.js"), encoding="utf-8").read()
lf = src[src.index("export function litterAt"):src.index("// ---- THE DEEP")]
check("…only where no older litter stood: the dye plants come last on the meadow and the forest floor, so every pebble, stick, "
      "flax plant, flower, grain stand and berry bush keeps its place",
      "B.wheat : hh % 97 === 17 ? B.berrybush\n" in lf and lf.index("? B.berrybush\n") < lf.index("? B.weld") < lf.index("? B.woad") < lf.index("? B.madder : 0;")
      and "hh % 71 === 13 ? B.berrybush\n" in lf and lf.index("hh % 71 === 13 ? B.berrybush\n") < lf.index("? B.clubmoss : 0;"))
brk = {k: R["breaking"].get(str(b)) for k, b in ids.items()}
check("weld, woad and clubmoss are pulled up by hand", all(brk[k] and not brk[k].get("needs") and brk[k]["yields"][0][0] == PLANTS[k] for k in ("weld", "woad", "clubmoss")), brk)
check("…madder's roots are dug, with a shovel", brk["madder"] and brk["madder"].get("needs") == "shovel" and brk["madder"]["yields"][0][0] == "madder_root", brk["madder"])
mesher = open(os.path.join(ROOT, "static", "land-mesher.js"), encoding="utf-8").read()
check("each is drawn as its own model, never as a pebble",
      "const DYE_MODEL = new Map([[B.weld, weldModel], [B.woad, woadModel], [B.madder, madderModel], [B.clubmoss, clubmossModel]]);" in mesher
      and mesher.index("else if (DYE_MODEL.has(b))") < mesher.index("else pebble(stones,"))
r = subprocess.run(["node", "--input-type=module", "-e", """
const T = await import(%r);
const out = {};
for (const f of ["weldModel", "woadModel", "madderModel", "clubmossModel"]) { const m = T[f](7), l = T[f](7, true), tall = Math.max(...m.bark.pos.filter((_, i) => i %% 3 === 2));
  out[f] = { tris: (m.bark.idx.length + m.leaves.idx.length) / 3, lite: (l.bark.idx.length + l.leaves.idx.length) / 3, tall }; }
console.log(JSON.stringify(out));""" % os.path.join(ROOT, "static", "land-trees.js")], capture_output=True, text=True, timeout=60)
M = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
check("…each lighter than a clump of flax (168 triangles), and lighter still from the middle level on (a phone, #150)",
      len(M) == 4 and all(0 < m["lite"] < m["tris"] <= 168 for m in M.values()), (M, r.stderr[-300:]))
check("…and as tall as its sources say: weld 1-1.5 m, woad up to 1.2 m, clubmoss's upright shoots 5-30 cm, its spore cones among them",
      M and 1.0 <= M["weldModel"]["tall"] <= 1.5 and M["woadModel"]["tall"] <= 1.2 and M["clubmossModel"]["tall"] <= 0.30, M)

# 2. the dye vat, through the rules and the world server
rec = {x["id"]: x for x in R["recipes"] if isinstance(x, dict)}
check("a dye vat is fired from clay at the kiln", rec["dye_vat"]["makes"] == [["dye_vat", 1]] and dict(rec["dye_vat"]["uses"]).get("clay")
      and rec["dye_vat"]["with"] == ["kiln"] and "dye_vat" in R["stations"])
for g in GARMENTS:
    u = {c: dict(rec[f"{g}_{c}"]["uses"]) for c in COLOURS}
    check(f"a {g} is dyed in the vat: yellow with weld, red with madder, each fixed with clubmoss",
          u["yellow"].get(g) == 1 and u["yellow"].get("weld") and u["yellow"].get("clubmoss")
          and u["red"].get(g) == 1 and u["red"].get("madder_root") and u["red"].get("clubmoss")
          and all(rec[f"{g}_{c}"]["with"] == ["dye_vat"] for c in COLOURS), u)
    check(f"…blue with woad and no mordant (a vat dye), green by dyeing the blue one over with weld",
          u["blue"] == {g: 1, "woad": u["blue"]["woad"]} and u["green"].get(f"{g}_blue") == 1 and u["green"].get("weld") and g not in u["green"], u)
    check(f"…and each dyed {g} is worn where the undyed one is", all(R["items"][f"{g}_{c}"].get("wear") == R["items"][g]["wear"] for c in COLOURS))
have, tools, st = set(), set(), set()
cls = lambda c: any(t == c or R["tools"][t].get("class") == c for t in tools)
for sp in R["hunting"]["species"].values():
    for i, _ in sp["drops"]:
        have.add(i)
grew = True
while grew:
    grew = False
    for b in R["breaking"].values():
        if not isinstance(b, dict) or not b.get("yields") or (b.get("needs") and not cls(b["needs"])):
            continue
        for i, _ in b["yields"] + ([b["bonus"]] if b.get("bonus") else []):
            if i not in have:
                have.add(i); grew = True
    for x in R["recipes"]:
        if not isinstance(x, dict) or not all(i in have for i, _ in x["uses"]) or not all(w in st or cls(w) for w in x.get("with", [])):
            continue
        for i, _ in x["makes"]:
            box = tools if i in R["tools"] else st if i in R["stations"] else have
            if i not in box:
                box.add(i); grew = True
dyed = {f"{g}_{c}" for g in GARMENTS for c in COLOURS}
check("all eight dyed garments are reachable from what a player gathers and hunts", dyed <= have, sorted(dyed - have))
w = S.World(os.path.join(os.environ["HOME"], "land"), "http://127.0.0.1:1", "")
A = "ndoDYE" + "A" * 42
pl = w.player(A)
pl["items"]["woollen_cap_red"] = 1
check("a red woollen cap goes on the head through the world server", w.wear(A, "head", "woollen_cap_red") is None and pl["worn"]["head"] == "woollen_cap_red")
pl["items"]["woollen_cloak_green"] = 1
check("…and a green woollen cloak on the back, nowhere else", w.wear(A, "head", "woollen_cloak_green") is not None
      and w.wear(A, "back", "woollen_cloak_green") is None and pl["worn"]["back"] == "woollen_cloak_green")

# 3. the sources
about = R.get("dyes", {}).get("about", "")
check("the rules carry their sources: weld, woad and madder, and the mordant",
      all(x in about for x in ("CAMEO", "Rubia tinctorum", "12-20 %", "Duff & Sinclair 1988", "Diphasiastrum complanatum", "Lincoln green")), about[:200])
check("…and say the clubmoss mordant is a design choice", "THE MORDANT IS CLUBMOSS, a DESIGN CHOICE" in about)

# 4. drawn, and named
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()
fn = page.split("const SKIN = ", 1)[1].split("function avatar(", 1)[0]
js = """
class Color { setHSL(h, s, l) { this.v = 1; return this; } getHex() { return this.v; } }
const THREE = { Color };
const SKIN = %s
console.log(JSON.stringify({ WEAR, look: lookColours("x", { worn: { back: "woollen_cloak_red", head: "woollen_cap_blue" } }) }));
""" % fn
out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
P = json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
Wc = P.get("WEAR", {})
check("every dyed garment has its own colour, none the undyed brown", all(isinstance(Wc.get(d), int) for d in dyed) and len({Wc.get(d) for d in dyed}) == 8
      and not {Wc.get(d) for d in dyed} & {Wc.get("woollen_cloak"), Wc.get("woollen_cap")}, (P, out.stderr[-200:]))
check("…and the figure is drawn in it", P.get("look", {}).get("cloak") == Wc.get("woollen_cloak_red") and P.get("look", {}).get("cap") == Wc.get("woollen_cap_blue"), P.get("look"))
L = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = [f"land.b.{k}" for k in PLANTS] + [f"land.i.{i}" for i in PLANTS.values()] + ["land.s.dye_vat"] + [f"land.i.{d}" for d in sorted(dyed)]
check("the plants, what they give, the dye vat and the eight garments are named in all 17 languages",
      len(L) == 17 and all(L[x].get(k) for x in L for k in keys), [(x, k) for x in L for k in keys if not L[x].get(k)])
check("…no two dyed garments share a name in any language", all(len({L[x][f"land.i.{d}"] for d in dyed}) == 8 for x in L))

print("\n" + ("ALL PASS" if not _report.fails else f"{_report.fails} FAILED"))
sys.exit(1 if _report.fails else 0)
