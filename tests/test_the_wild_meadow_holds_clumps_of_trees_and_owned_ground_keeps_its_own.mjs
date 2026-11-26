// THE WILD MEADOW HOLDS CLUMPS OF TREES, AND OWNED GROUND KEEPS ITS OWN (2026-11-26, operator: "Clumps, skip built ground").
// The reference's meadow holds rounded clumps of trees out in the grass with open meadow between; since 2026-11-23 the wild
// meadow's trees grew only toward the woods, and the open grass had none. Groves now stand in patches of their own field.
// Pinned (land-world.js treeAt, GROVE):
//   1. over 155 ha of wild meadow by the vale, the trees come in clumps — dozens of 3 or more within 12 m of each other —
//      and the meadow stays open (a few trees a hectare, not a wood);
//   2. a grove is the wilderness's alone: with wildMask 0 (every titled plot) the meadow's trees are exactly the old rule's,
//      and every plot titled today is on PROTECTED_PLOTS (the mask's source), checked against the frozen list here;
//   3. the groves read a field of their own (GROVE_PERM), so no older layer of the planet moved.
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1
const u0 = 49200, v0 = 75700, N = 1600, pts = [];
let meadow = 0;
for (let v = v0; v < v0 + N; v++) for (let u = u0; u < u0 + N; u++) {
  const c = W.column(0, u, v);
  if (c.biome !== "grass") continue;
  meadow++;
  const t = W.treeAt(0, u, v, c);
  if (t && t.kind !== "bush") pts.push([u, v]);
}
const par = pts.map((_, i) => i), f = (i) => (par[i] === i ? i : (par[i] = f(par[i])));
const g = new Map();
pts.forEach((p, i) => { const k = Math.floor(p[0] / 12) + ":" + Math.floor(p[1] / 12); if (!g.has(k)) g.set(k, []); g.get(k).push(i); });
pts.forEach((p, i) => { for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (const j of g.get((Math.floor(p[0] / 12) + a) + ":" + (Math.floor(p[1] / 12) + b)) || []) if (j !== i && Math.hypot(p[0] - pts[j][0], p[1] - pts[j][1]) < 12) par[f(i)] = f(j); });
const sz = new Map();
pts.forEach((_, i) => sz.set(f(i), (sz.get(f(i)) || 0) + 1));
const clumps = [...sz.values()].filter((x) => x >= 3).length, perHa = (pts.length / meadow) * 1e4;
ok(meadow > 1e6 && clumps >= 30, `the wild meadow holds clumps of trees: ${clumps} of 3 or more over ${(meadow / 1e4).toFixed(0)} ha (2026-11-26: 58; before the groves the open grass had none past the woods' edge)`);
ok(perHa > 3 && perHa < 6, `…and stays an open meadow: ${perHa.toFixed(2)} trees a hectare (2.71 before, 4.06 with the groves)`);

// 2
const nGrove = (wild) => {
  let n = 0;
  for (let v = v0; v < v0 + 400; v++) for (let u = u0; u < u0 + 400; u++) {
    const c = W.column(0, u, v);
    if (c.biome !== "grass") continue;
    const t = W.treeAt(0, u, v, { ...c, wild });
    if (t && t.kind !== "bush") n++;
  }
  return n;
};
const owned = nGrove(0);
// the old rule on owned ground: a lone tree at 0.004 of a column, whatever the grove field says there
let oldRule = 0;
for (let v = v0; v < v0 + 400; v++) for (let u = u0; u < u0 + 400; u++) {
  const c = W.column(0, u, v);
  if (c.biome !== "grass") continue;
  const t = W.treeAt(0, u, v, { ...c, wild: 0, woods: -1 });
  if (t && t.kind !== "bush") oldRule++;
}
// (not "wild > owned": owned ground keeps the old lone tree in 250 m² everywhere, the wild meadow only at the woods' edge
// and in its groves — the groves adding clumps is check 1)
ok(owned === oldRule && owned > 0, `with the wilderness mask at 0 the meadow keeps exactly its old trees (${owned} of ${oldRule}), the grove field read nowhere`);
const src = readFileSync(join(ROOT, "static", "land-world.js"), "utf8");
ok(/const grove = w > 0 \? GROVE \* smooth\(GROVE_FROM, GROVE_FROM \+ 0\.14, noise3\(GROVE_PERM, u \/ 45, v \/ 45, face \* 53\)\) : 0;/.test(src)
   && /const lone = 0\.004 \* \(1 - w\) \+ \(0\.004 \* edge \+ grove\) \* w,/.test(src),
   "a grove grows only by the wilderness mask (w): an owned plot's term is the old 0.004");
const prot = readFileSync(join(ROOT, "static", "land-protected.js"), "utf8").match(/\d{6,}/g).length;
ok(prot === 100, `every plot titled on 2026-11-26 is on PROTECTED_PLOTS (100 of 100 measured on the exec node; the list holds ${prot})`);

// 3
ok(/const GROVE_PERM = makePerm\(WORLD_SEED \+ 14 \* 7919\);/.test(src) && (src.match(/makePerm\(WORLD_SEED \+ 14 \* 7919\)/g) || []).length === 1,
   "the groves read a field of their own (seed slot 14), so no older layer of the planet moved");

// 4. PALMS ON WARM COASTS ONLY (2026-11-26): this vale's shore (temp 0.183, the mild broadleaf zone) was lined with palms whose
// thin fronds vanish past ~100 m — rows of bare dark posts. A wild beach needs PALM_WARM; an owned one above 0, as bought.
{
  let palms = 0;
  for (let v = 76028; v < 76628; v++) for (let u = 49779; u < 50379; u++) { const c = W.column(0, u, v), t = W.treeAt(0, u, v, c); if (t && t.kind === "palm") palms++; }
  ok(palms === 0, `4. no palm on the temperate shore by the vale (${palms} within 300 m; 62 before)`);
  let warm = 0, all = 0, warmPalm = false, ownedPalm = false;
  for (let u = 0; u < 262144; u += 997) for (let v = 0; v < 262144; v += 991) {
    const c = W.column(0, u, v);
    if (c.biome !== "beach" || c.wild < 0.99) continue;
    all++; if (c.temp > W.PALM_WARM) warm++;
  }
  // the rule itself, for a warm wild beach column and an owned one at a mild temperature
  for (let hh = 0; hh < 600 && !(warmPalm && ownedPalm); hh++) {
    const u = 1000 + hh, v = 2003;                                  // (lv 3: rows 0-1 of a plot grow no tree)
    const base = { ...W.column(0, u, v), biome: "beach", top: W.SEA + 2 };
    if (W.treeAt(0, u, v, { ...base, temp: W.PALM_WARM + 0.05, wild: 1 })?.kind === "palm") warmPalm = true;
    if (W.treeAt(0, u, v, { ...base, temp: 0.1, wild: 0 })?.kind === "palm") ownedPalm = true;
  }
  ok(W.PALM_WARM >= 0.2 && W.PALM_WARM <= 0.3 && warm > 0.08 * all && warm < 0.25 * all,
     `…palms keep the warmest wild coasts (${warm} of ${all} sampled wild beaches, PALM_WARM ${W.PALM_WARM})`);
  ok(warmPalm && ownedPalm, "…a warm wild beach still grows them, and an owned beach above 0 keeps them as bought");
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
