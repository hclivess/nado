// The wilderness rolls in hills, and owned ground never moves (operator 2026-11-22, beside the Chlorophyll shot: "make
// it realistic", "wilderness only", "yes protect"; "the rule is already there": owned land is never changed or
// regenerated, the wilderness regrows).
//   1. OWNED GROUND IS THE GROUND IT WAS BOUGHT ON: every column of every plot titled on 2026-11-22 (land-protected.js) has
//      exactly the height, top and biome it had before the hills — the fingerprint below was taken from the generator as
//      it stood (origin/main 7124f94f) and must never change; the town's four plots are among them;
//   2. the mask is 0 over an owned plot, rises smoothly over ROLL_BLEND metres around it (no cliff at its edge), and is
//      1 in the open wilderness;
//   3. the wilderness has hills: the height's spread over a 70 x 60 km sample is ~39 m (it was ~26), and still mostly
//      land, the sea no more than 45 % of it;
//   4. what the hills are for: from a tenth of the meadow views hills stand over the forest past 1.7 km (a thirtieth
//      before) — line of sight with the planet's curve and the canopies, as the eye sees.
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const F = await import(join(ROOT, "static", "land-forest.js"));
const { PROTECTED_PLOTS } = await import(join(ROOT, "static", "land-protected.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const FN = Wd.FACE_N;

// 1
const OWNED_GROUND = "323c3df53839a150526c104cdfe80263caffa624bb7280cdf78209786e33ddd3";
{ const h = createHash("sha256");
  for (const p of PROTECTED_PLOTS) { const r = Math.floor(p / FN) % FN, c = p % FN; for (let i = 0; i < 16; i++) for (let j = 0; j < 16; j++) { const k = Wd.column(0, c * 16 + i, r * 16 + j); h.update(`${k.height.toFixed(6)},${k.top},${k.biome};`); } }
  ok(PROTECTED_PLOTS.length === 100 && h.digest("hex") === OWNED_GROUND, `the ${PROTECTED_PLOTS.length} owned plots' ${PROTECTED_PLOTS.length * 256} columns are the ground they were bought on (fingerprint)`);
  const town = [4999, 5000].flatMap((r) => [3439, 3440].map((c) => r * FN + c));
  ok(town.every((t) => PROTECTED_PLOTS.includes(t)), "the town's four plots are among them"); }

// 2
{ const own = new Set(PROTECTED_PLOTS), r = Wd.SPAWN_PLOT_ROW + 4; let c = Wd.SPAWN_PLOT_COL + 4; while (own.has(r * FN + c - 1)) c--;
  const edge = c * 16, v = r * 16 + 8, m = (d) => Wd.wildMask(0, edge - d, v);
  let inside = 0; for (const p of PROTECTED_PLOTS) { const pr = Math.floor(p / FN) % FN, pc = p % FN; for (let i = 0; i < 16; i += 5) for (let j = 0; j < 16; j += 5) inside = Math.max(inside, Wd.wildMask(0, pc * 16 + i, pr * 16 + j)); }
  ok(inside === 0, "the mask is 0 over every owned plot");
  const steps = [0, 16, 32, 48, 64, 80, 96, 112, 128].map(m);
  ok(steps.every((x, i) => i === 0 || x >= steps[i - 1]) && steps[0] === 0 && steps[4] > 0.3 && steps[4] < 0.7 && m(Wd.ROLL_BLEND + 16) === 1,
     `…rises smoothly off the landing's edge (${steps.map((x) => x.toFixed(2)).join(" ")}) and is 1 past ROLL_BLEND (${Wd.ROLL_BLEND} m)`);
  let jump = 0; for (let d = 0; d < 160; d++) jump = Math.max(jump, Math.abs(Wd.column(0, edge - d, v).height - Wd.column(0, edge - d - 1, v).height));
  ok(jump < 3, `no cliff at an owned edge: the ground steps at most ${jump.toFixed(2)} m a column across the blend`); }

// 3
{ const hs = []; let sea = 0;
  for (let k = 0; k < 6000; k++) { const u = 20000 + (k * 7919) % 70000, v = 50000 + (k * 104729) % 60000, c = Wd.column(0, u, v); hs.push(c.height); if (c.top <= Wd.SEA) sea++; }
  const m = hs.reduce((a, b) => a + b) / hs.length, sd = Math.sqrt(hs.reduce((a, b) => a + (b - m) ** 2, 0) / hs.length);
  ok(sd > 34 && sd < 50 && sea / hs.length < 0.45, `the wilderness has hills: the height spreads ${sd.toFixed(1)} m (was ~26), the sea ${(100 * sea / hs.length).toFixed(0)} % of it`); }

// 4
{ const U0 = 56200, V0 = 79500, R = 24000, STEP = 1200, RP = Wd.R0 + Wd.SEA; let views = 0, see = 0;
  for (let u = U0 - R; u <= U0 + R; u += STEP) for (let v = V0 - R; v <= V0 + R; v += STEP) {
    const c0 = Wd.column(0, u, v); if (c0.biome !== "grass" || c0.top <= Wd.SEA) continue;
    const eye = c0.height + 1.7;
    for (let k = 0; k < 8; k++) {
      const du = Math.sin(k * Math.PI / 4), dv = Math.cos(k * Math.PI / 4); views++;
      let maxA = -9, hills = 0;
      for (let d = 20; d <= 3800; d += d < 400 ? 20 : 64) {
        const c = Wd.column(0, Math.round(u + du * d), Math.round(v + dv * d)), h = c.top <= Wd.SEA ? Wd.SEA : c.height + F.canopyHeight(c), a = (h - (d * d) / (2 * RP) - eye) / d;
        if (a > maxA) { if (d > 1700 && h > eye + 15) hills++; maxA = a; }
      }
      if (hills) see++;
    }
  }
  ok(see / views > 0.07, `from ${(100 * see / views).toFixed(0)} % of ${views} meadow views hills stand over the forest past 1.7 km (3 % before)`); }
// 6. wooded crests over meadow vales (the Chlorophyll shot, 2026-11-22: its hills are forest, its vales meadow; ours, with
//    the hills raised, showed bare tan slopes — 18 % of crests wooded, 24 % of vales). The forest field leans with the roll.
{ let seed = 11; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const crest = [0, 0], vale = [0, 0];
  for (let i = 0; i < 20000; i++) {
    const u = Math.floor(50000 + rnd() * 14000), v = Math.floor(72000 + rnd() * 14000), c = Wd.column(0, u, v), r = Wd.rollAt(0, u, v);
    if (c.top <= Wd.SEA || (c.biome !== "forest" && c.biome !== "grass")) continue;
    const g = r > 30 ? crest : r < -30 ? vale : null; if (g) { g[0]++; if (c.biome === "forest") g[1]++; }
  }
  ok(crest[1] / crest[0] > 0.5 && vale[1] / vale[0] < 0.15, `the crests are wooded (${(100 * crest[1] / crest[0]).toFixed(0)} % forest) and the vales meadow (${(100 * vale[1] / vale[0]).toFixed(0)} %)`); }
// 7. OPEN MEADOWS (2026-11-23, beside the Chlorophyll shot: a tree every ~16 m of meadow read as parkland): in the
// wilderness a meadow's lone trees grow toward the woods and none out in the open, its bushes thinner in the open — and an
// owned plot's trees are the trees it was bought with (the fingerprint was taken with the generator before the change)
{ const OWNED_TREES = "614b6a5742551bbf86d0709158a30600de9a1f15c31f4b7ba099165d3b7217fd";
  const h = createHash("sha256");
  for (const p of PROTECTED_PLOTS) { const r = Math.floor(p / FN) % FN, c = p % FN; for (let i = 0; i < 16; i++) for (let j = 0; j < 16; j++) { const u = c * 16 + i, v = r * 16 + j, t = Wd.treeAt(0, u, v, Wd.column(0, u, v)); h.update(t ? `${t.kind}${t.height};` : "-;"); } }
  ok(h.digest("hex") === OWNED_TREES, "the owned plots' trees are the trees they were bought with (fingerprint)");
  let open = 0, openTrees = 0, fringe = 0, fringeTrees = 0, openBush = 0, fringeBush = 0;
  for (let u = 40002; u < 70000; u += 7) for (let v = 65003; v < 95000; v += 131) {
    const c = Wd.column(0, u, v); if (c.biome !== "grass" || c.wild < 1) continue;
    const t = Wd.treeAt(0, u, v, c), tree = t && t.kind !== "bush", bush = t && t.kind === "bush";
    if (c.woods < 0) { open++; if (tree) openTrees++; if (bush) openBush++; } else if (c.woods > 0.08) { fringe++; if (tree) fringeTrees++; if (bush) fringeBush++; }
  }
  ok(open > 5000 && openTrees === 0 && fringe > 1000 && fringeTrees / fringe > 0.001,   // (0.4 % at most, in the 56 % of a plot clear of its edge)
    `7. an open meadow grows no lone tree (${openTrees} in ${open} columns), its fringe by the woods does (${(100 * fringeTrees / fringe).toFixed(2)} %)`);
  ok(openBush / open < 0.6 * (fringeBush / fringe) && openBush > 0, `…and its bushes thin out in the open (${(100 * openBush / open).toFixed(1)} % against ${(100 * fringeBush / fringe).toFixed(1)} % by the woods)`); }
// …and a wilderness wood is as thick at its edge as inside (the edge read as a row of bare trunks at 0.035 a column)
{ let edge = 0, edgeT = 0, inner = 0, innerT = 0;
  for (let u = 50000; u < 60000; u += 7) for (let v = 75000; v < 85000; v += 53) {
    const c = Wd.column(0, u, v); if (c.biome !== "forest" || c.wild < 1) continue;
    const inside = (c.woods - 0.12) / 0.25, t = Wd.treeAt(0, u, v, c), tr = !!t && t.kind !== "bush";
    if (inside < 0.3) { edge++; if (tr) edgeT++; } else if (inside >= 1) { inner++; if (tr) innerT++; } }
  ok(edge > 1000 && inner > 1000 && edgeT / edge > 0.9 * (innerT / inner),
    `a wood is as thick at its edge (${(100 * edgeT / edge).toFixed(1)} % of columns) as inside (${(100 * innerT / inner).toFixed(1)} %)`); }
// THE WILD'S CONIFER LINE (2026-11-25, operator: "wilderness only"): on a mid-height hill (here 100 m over the sea) a wood in
// the wilderness grows broadleaf and birch as the Chlorophyll shot's hills do, while an owned plot (wild 0) keeps EXACTLY the
// species the old rule gave it — conifers from 60 m — so no bought tree changes. Asked of treeAt over many forest columns.
{
  let owned = 0, ownedConifer = 0, wild = 0, wildConifer = 0, high = 0, highConifer = 0;
  for (let u = 3000; u < 3400 && owned < 200; u++) for (let v = 5002; v < 5014; v++) {
    const base = { biome: "forest", woods: 1, temp: 0.1, wet: 0 };
    const o = Wd.treeAt(0, u, v, { ...base, top: Wd.SEA + 100, wild: 0 });
    if (o && o.kind !== "bush") { owned++; if (o.kind === "conifer") ownedConifer++; }
    const w = Wd.treeAt(0, u, v, { ...base, top: Wd.SEA + 100, wild: 1 });
    if (w && w.kind !== "bush") { wild++; if (w.kind === "conifer") wildConifer++; }
    const h = Wd.treeAt(0, u, v, { ...base, top: Wd.SEA + 200, wild: 1 });
    if (h && h.kind !== "bush") { high++; if (h.kind === "conifer") highConifer++; }
  }
  ok(owned > 50 && ownedConifer / owned > 0.7, `an owned wood 100 m up keeps the old rule's conifers (${ownedConifer} of ${owned})`);
  ok(wild > 50 && wildConifer === 0, `the wild wood at the same height grows broadleaf and birch (${wildConifer} conifers of ${wild})`);
  ok(high > 50 && highConifer / high > 0.7, `…and the wild's high ground (200 m) is still conifer (${highConifer} of ${high})`);
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
