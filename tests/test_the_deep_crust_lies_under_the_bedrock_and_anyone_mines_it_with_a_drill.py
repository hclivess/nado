"""
THE DEEP, phase 1 (#129, doc/land-core.md): under the crust's bedrock floor lies the deep crust, down to DEEP_MIN.

  1. the planet (static/land-world.js, the one generator): every deep cell is stone or an ore vein (magnetite among the iron, #173); silver and gold
     only below DEEP_RICH, and there; layer 0 is bedrock, and so is everything under DEEP_MIN; the mesher draws a tunnel
     dug in the deep (its walls), and the world server's terrain oracle answers deep cells as the page does;
  2. the world server: bedrock gives way only to a drill — on an owned plot only to its owner, as any of the plot's
     cells; below layer 0 the deep is everyone's (a stranger digs and builds under an owned plot) and a dug deep cell
     never grows back; nothing under DEEP_MIN is reachable;
  3. a plot's commitment is the same with or without the deep under it, on the server and in the page alike;
  4. the drill, silver and gold are reachable from bare hands; every block is known to the server; the new names are in
     17 languages.

Run: python3 tests/test_the_deep_crust_lies_under_the_bedrock_and_anyone_mines_it_with_a_drill.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-deep-")
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
MESHER = json.dumps(os.path.join(ROOT, "static", "land-mesher.js"))
P = (0 * S.FACE_N + 4995) * S.FACE_N + 3435           # the landing site's corner plot
face, row, col = S.plot_coords(P)
U, V = col * S.PLOT + 8, row * S.PLOT + 8

# 1. the planet
js = """
const W = await import(%s), M = await import(%s);
const B = W.B, kinds = {}, rich = {}, shallow = {};
for (let h = -1; h >= W.DEEP_MIN; h -= 1) for (let d = 0; d < 6; d++) {
  const b = W.deepBlock(0, %d + d * 5, %d + d * 3, h); kinds[b] = 1;
  if (h <= W.DEEP_RICH) rich[b] = (rich[b] || 0) + 1; else shallow[b] = (shallow[b] || 0) + 1;
}
const same = [-1, -17, -400, -2000].every((h) => W.terrainBlock(0, %d, %d, h) === W.deepBlock(0, %d, %d, h));
// a tunnel: a 3-cell run dug out of a deep chunk, against the same chunk untouched
const u = %d, v = %d, h = -40, ch = Math.floor(h / W.CHUNK);
const tri = (r) => Object.values(r || {}).reduce((n, m) => n + (m && m.pos ? m.pos.length / 3 : 0), 0);
const ed = new Map([[0, 1, 2].map((i) => [`0:${u + i}:${v}:${h}`, 0])].flat());
const dug = M.meshChunk(0, Math.floor(u / 16), Math.floor(v / 16), ch, ed, null, 0);
const whole = M.meshChunk(0, Math.floor(u / 16), Math.floor(v / 16), ch, new Map(), null, 0);
console.log(JSON.stringify({ kinds: Object.keys(kinds).map(Number), rich, shallow, same, B: { stone: B.stone, bedrock: B.bedrock, silver: B.silverore, gold: B.goldore, coal: B.coal, iron: B.ironore, copper: B.copperore, tin: B.tinore, magnetite: B.magnetite },
  zero: W.terrainBlock(0, u, v, 0), under: W.deepBlock(0, u, v, W.DEEP_MIN - 1), DEEP_MIN: W.DEEP_MIN, n: W.BLOCKS.length,
  dug: tri(dug), whole: tri(whole), keys: Object.keys(dug || {}) }));
""" % (WORLD, MESHER, U, V, U, V, U, V, U, V)
r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=600)
J = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
B = J.get("B", {})
check("every deep cell is stone or an ore vein", J and set(J["kinds"]) <= {B["stone"], B["coal"], B["iron"], B["copper"], B["tin"], B["silver"], B["gold"], B["magnetite"]}, (J.get("kinds"), r.stderr[-400:]))
# (magnetite, #173: an iron ore that runs in a quarter of the iron veins' regions — land-world.js isMagnetite. The list
# here predated it and the check was red from that commit, #189.)
check("…magnetite being one of them: it runs where the iron does", B.get("magnetite") in J.get("kinds", []) and B.get("iron") in J.get("kinds", []), J.get("kinds"))
check("silver and gold lie only below DEEP_RICH — and they do lie there",
      str(B.get("silver")) not in J.get("shallow", {}) and str(B.get("gold")) not in J.get("shallow", {})
      and J.get("rich", {}).get(str(B.get("silver"))) and J.get("rich", {}).get(str(B.get("gold"))), (J.get("rich"), J.get("shallow")))
check("the page's terrain is the deep below layer 0", J.get("same"))
check("layer 0 is bedrock, and so is all under DEEP_MIN", J.get("zero") == B.get("bedrock") and J.get("under") == B.get("bedrock") and J.get("DEEP_MIN") == S.DEEP_MIN)
check(f"a tunnel dug in the deep is drawn: its walls ({J.get('dug')} vertices, none for the solid rock untouched)",
      J.get("dug", 0) >= 8 and J.get("dug", 0) > J.get("whole", 0), J)
check("the world server knows every block", S.N_BLOCKS == J.get("n"))

# 2. the world server
A, OWNER = "ndoDEEPA" + "A" * 40, "ndoDEEPO" + "O" * 40


async def main():
    w = S.World(os.path.join(os.environ["HOME"], "land"), "http://127.0.0.1:1", "")
    await w.start_oracle()
    owned = set()

    async def holder(q): return OWNER if q in owned else None
    async def may_build(q, a): return q not in owned or a == OWNER
    w.holder, w.may_build = holder, may_build
    w.work = lambda who, s: True
    w.take = lambda who, n: True
    at = await w.blocks_at([[face, U, V, -40], [face, U, V, 0]])
    check("the oracle answers a deep cell as the page does", at[(face, U, V, 0)] == B["bedrock"] and at[(face, U, V, -40)] in J["kinds"], at)
    pl = w.player(A); pl["tools"] += ["iron_pick"]
    _, ref, _ = await w.apply(A, [[face, U, V, 0, 0]])
    check("bedrock does not give way to a pick", ref and "drill" in ref[0][1], ref)
    pl["tools"] += ["drill"]
    owned.add(P)
    _, ref, _ = await w.apply(A, [[face, U, V, 0, 0]])
    check("…on an owned plot, a stranger's drill does not break its bedrock either", ref and "not your plot" in ref[0][1], ref)
    owned.discard(P)
    _, ref, _ = await w.apply(A, [[face, U, V, 0, 0]])
    check("a drill breaks bedrock", not ref, ref)
    owned.add(P)
    pl["items"]["planks"] = 1
    _, ref, _ = await w.apply(A, [[face, U, V, -1, 0], [face, U, V, -2, 0], [face, U, V, -2, R["items"]["planks"]["places"]]])
    k = (U - col * S.PLOT, V - row * S.PLOT, -1)
    check("below layer 0 the deep is everyone's: a stranger digs and builds under an owned plot", not ref, ref)
    check("…and a dug deep cell never grows back", w.plots[P]["edits"].get(k) == 0 and k not in (w.plots[P].get("exp") or {}))
    _, ref, _ = await w.apply(A, [[face, U, V, S.DEEP_MIN - 1, 0]])
    check("nothing under DEEP_MIN is reachable", ref and "out of the world" in ref[0][1], ref)
    # 3. the commitment ignores the deep, on both sides
    salt = bytes(range(32))
    top = [[1, 2, 140, 0], [3, 4, 141, 7]]
    deep = top + [[1, 2, -1, 0], [5, 5, -2000, 0]]
    same_srv = S.commitment_bytes(P, salt, deep) == S.commitment_bytes(P, salt, top)
    jsc = "const W = await import(%s); const s = Uint8Array.from(%s); console.log(JSON.stringify([await W.plotCommitment(%d, s, %s), await W.plotCommitment(%d, s, %s)]));" % (
        WORLD, json.dumps(list(salt)), P, json.dumps(deep), P, json.dumps(top))
    rc = subprocess.run(["node", "--input-type=module", "-e", jsc], capture_output=True, text=True, timeout=120)
    pc = json.loads(rc.stdout.strip().splitlines()[-1]) if rc.stdout.strip() else [None, 0]
    srv_c = str(int.from_bytes(__import__("hashlib").sha256(S.commitment_bytes(P, salt, top)).digest(), "big"))
    check("a plot's commitment is the same with or without the deep under it — on the server and in the page",
          same_srv and pc[0] == pc[1], (same_srv, pc, rc.stderr[-300:]))
    w.oracle.kill(); await w.oracle.wait()


asyncio.run(main())

# 4. reachable, and named
have, tools, st = set(), set(), set()
cls = lambda c: any(t == c or R["tools"][t].get("class") == c for t in tools)
grew = True
while grew:
    grew = False
    for bid, rr in R["breaking"].items():
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
check("the drill is made from bare hands, and silver and gold smelted from the deep's ores",
      "drill" in tools and {"silverore", "goldore", "silver", "gold"} <= have, sorted({"silverore", "goldore", "silver", "gold"} - have))
tr = json.load(open(os.path.join(ROOT, "static", "i18n_games", "land.json"), encoding="utf-8"))
keys = ["land.needsDrill", "land.i.silverore", "land.i.goldore", "land.i.silver", "land.i.gold", "land.t.drill"]
check("the new names are in 17 languages", len(tr) == 17 and all(all(l.get(k) for k in keys) for l in tr.values()))
_report.done()
