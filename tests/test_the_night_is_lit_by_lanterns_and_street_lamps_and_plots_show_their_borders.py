"""
Light and borders in Land (operator 2026-11-07: "we could use some more intense sources of light - townhall disappears
after walking 20 meters at night"; "there should be some kind of a visual cue marking the ownership borders"):

  1. a lantern and a street lamp are made from bare hands (glass, iron, a torch at the anvil), drawn as their models
     inside their boxes with glowing glass, and known to the world server;
  2. they light the night farther than a torch — a lantern a yard, a street lamp a street — and the page's few lights go
     to the sources whose light reaches the player soonest;
  3. every titled plot around the player is outlined in the colour of whose it is (yours, invited, for sale, someone
     else's, owner not yet known; wilderness none; photo mode only the plot it photographs); plots of one holder share
     one outline, plots on sale keep each their own; a border follows the drawn ground and the pieces on it, never a
     tree; it is on by default and a setting turns it off;
  4. the new names are in 17 languages.

Run: python3 tests/test_the_night_is_lit_by_lanterns_and_street_lamps_and_plots_show_their_borders.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-light-borders-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import importlib.util, json, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
import _harness
_report = _harness.Report()
check = _report.check
R = json.load(open(os.path.join(ROOT, "static", "land-recipes.json")))
page = open(os.path.join(ROOT, "static", "land.js"), encoding="utf-8").read()

# 1. reachable from bare hands
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
check("a lantern and a street lamp are made from bare hands", {"lantern", "lamppost"} <= have)
js = """
const W = await import(%s), M = await import(%s), R = %s;
const out = {};
for (const k of ["lantern", "lamppost"]) {
  const u = R.items[k].unit, L = Math.max(u[0], u[1]), S_ = Math.min(u[0], u[1]), parts = M.MODELS[W.B[k]](L, S_, u[2]);
  out[k] = { inside: parts.every(([l0, l1, s0, s1, y0, y1]) => l0 >= 0 && l1 <= L && s0 >= 0 && s1 <= S_ && y0 >= 0 && y1 <= u[2]),
             glass: parts.some((p) => p[6] === W.B.lamp), glow: !!W.BLOCKS[W.B[k]].glow };
}
out.n = W.BLOCKS.length;
console.log(JSON.stringify(out));
""" % (json.dumps(os.path.join(ROOT, "static", "land-world.js")), json.dumps(os.path.join(ROOT, "static", "land-mesher.js")), json.dumps(R))
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=120)
J = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
check("both are drawn as their models inside their boxes, with glowing glass", all(J.get(k, {}).get("inside") and J[k]["glass"] and J[k]["glow"] for k in ("lantern", "lamppost")), (J, r.stderr[-300:]))
check("the world server knows every block", S.N_BLOCKS == J.get("n"))

# 2. their light
L = {k: dict(re.findall(r"(\w+): ([\d.]+)", v)) for k, v in re.findall(r"(\w+): \{ (i: [^}]+) \}", page.split("const LIGHTS = ", 1)[1].split(";", 1)[0])}
check("a street lamp reaches farther and shines brighter than a lantern, a lantern than a torch",
      float(L["lamppost"]["d"]) > float(L["lantern"]["d"]) > float(L["torch"]["d"]) and float(L["lamppost"]["i"]) > float(L["lantern"]["i"]) > float(L["torch"]["i"]), L)
check("the page's lights go to the sources whose light reaches the player soonest (distance over reach)",
      "sort((a, b) => a[0] / LIGHTS[a[2]].d - b[0] / LIGHTS[b[2]].d)" in page and "l.distance = L.d;" in page)

# 3. borders: whose a plot is, as the page decides it (its own borderKind, run here)
fn = page.split("function borderKind(plot) {", 1)[1].split("\n}\n", 1)[0]
js = """
let SHOT = null; const net = { me: "ME" }, dapp = { me: "ME" };
const titles = new Map([[1, {}], [2, { holder: "X", sale: { seller: "ME" } }], [3, { holder: "M", sale: { seller: "Y" } }],
                        [4, { holder: "O" }], [5, { holder: "O" }], [6, { holder: "Z" }]]);
const mine = new Set([5]), builds = new Set([6]);
const borderKind = (plot) => { %s };
const a = [0, 1, 2, 3, 4, 5, 6].map(borderKind);
SHOT = 4; const b = [3, 4].map(borderKind);
console.log(JSON.stringify({ a, b }));
""" % fn
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
K = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
check("a plot's border says whose it is: none in the wilderness, owner unknown, yours (and your own listing), for sale, someone else's, invited",
      K.get("a") == [None, "titled", "mine", "sale", "owned", "mine", "build"], (K, r.stderr[-300:]))
check("…and photo mode outlines only the plot it photographs", K.get("b") == [None, "shot"], K)
check("plots of one holder share one outline, plots on sale keep each their own",
      'k !== "sale" && holder && n >= 0 && (titles.get(n) || {}).holder === holder && borderKind(n) === k) continue;' in page)
check("a border follows the drawn ground and the pieces on it, never a tree",
      "const g = earthAt(q.face, u, v), t = pieceTopAt(p," in page and "const inside = (y) => fieldAt(f, u, v, y) > 0;" in page)
check("borders are on by default, and a setting turns them off", "borders: 1 }" in page and "borders: [0, 1] }" in page
      and "const on = SHOT !== null || SET.borders;" in page)
check("the page asks whose every outlined plot is (its colour), not only the one underfoot",
      "if (t && SHOT === null && !mine.has(p) && !t.asked) { t.asked = true; holderOf(p)" in page)
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
check("the new names are in 17 languages", len(tr) == 17 and all(l.get("land.i.lantern") and l.get("land.i.lamppost") for l in tr.values()))
_report.done()
