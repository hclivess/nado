/*
 * test_trees_are_grown_from_species_recipes_within_lands_budget_and_footprint.mjs — Land's trees are GROWN from species
 * recipes (static/land-species.js: Solstice's recipes and growth, MIT, adapted to Land — operator 2026-11-08, "adapt the
 * tree builder to our needs", #138):
 *   1. the recipes are Solstice's, read by the same format (heights, trunks, crowns, levels with spans and whorls), and
 *      its MIT notice travels with them;
 *   2. a species' shape survives the adaptation: a fir is a cone (its crown far narrower at the top than at the bottom),
 *      an oak's crown spreads wider for its height than a birch's;
 *   3. every model fits Land: within its tree's footprint (REACH), its top where its cells end, and within the frame
 *      budget near and far (vertices per model, measured against the builder it replaced);
 *   4. the same seed grows the same tree, another seed another;
 *   5. the mesher still caches a few variants per kind and height, so a forest costs its distinct models only.
 *
 * Run: node tests/test_trees_are_grown_from_species_recipes_within_lands_budget_and_footprint.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const S = await import(join(ROOT, "static", "land-species.js")), T = await import(join(ROOT, "static", "land-trees.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };

// 1
const oak = S.parseSpecies(S.RECIPES.oak), fir = S.parseSpecies(S.RECIPES.fir);
ok(oak.height === 11 && oak.trunk.radius === 0.24 && oak.crown === "round" && oak.levels.length === 3 && oak.levels[0].angle[0] === 72 && oak.levels[0].span[1] === 0.97,
   "the oak recipe reads as Solstice wrote it");
ok(fir.crown === "cone" && fir.levels[0].whorl === 5 && fir.levels[1].perMetre === 10, "the fir's whorls and cone read as written");
const src = readFileSync(join(ROOT, "static", "land-species.js"), "utf8");
ok(/MIT licence/.test(src) && /Copyright \(c\) 2026 SamG-Coder/.test(src) && /github\.com\/SamG-Coder\/solstice/.test(src), "Solstice's MIT notice travels with the recipes");
ok(["broadleaf", "birch", "conifer", "bush"].every((k) => S.RECIPES[S.ADAPT[k].recipe]), "every grown Land kind names a recipe");

// 2 + 3
const stats = (m) => {
  let top = 0, reach = 0; const pts = [];
  for (const b of [m.bark, m.leaves]) for (let i = 0; i < b.n; i++) { const x = b.pos[i * 3], y = b.pos[i * 3 + 1], z = b.pos[i * 3 + 2]; top = Math.max(top, z); reach = Math.max(reach, Math.hypot(x, y)); pts.push([x, y, z]); }
  return { top, reach, verts: m.bark.n + m.leaves.n, pts };
};
// a fir's taper as Solstice's own test measures it (tree.rs): its leaves' width in their top third over their bottom third
const taper = (m) => {
  const L = m.leaves; let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < L.n; i++) { lo = Math.min(lo, L.pos[i * 3 + 2]); hi = Math.max(hi, L.pos[i * 3 + 2]); }
  const third = (a, b) => { let mn = Infinity, mx = -Infinity; for (let i = 0; i < L.n; i++) { const y = (L.pos[i * 3 + 2] - lo) / (hi - lo); if (y >= a && y < b) { mn = Math.min(mn, L.pos[i * 3]); mx = Math.max(mx, L.pos[i * 3]); } } return mx - mn; };
  return third(0.67, 1) / third(0, 0.33);
};
// Solstice requires taper < 0.6 of its fir at one seed; Land's random stream differs from Solstice's, so a seed number
// names a different tree here — the species' shape is the average over many trees, and no single one may be top-heavy
const tapers = [2, 7, 11, 23, 99, 4242, 31337, 65537].map((sd) => taper(T.treeModel("conifer", 9, sd, 0)));
const mean = tapers.reduce((a, b) => a + b, 0) / tapers.length;
ok(mean < 0.6 && Math.max(...tapers) < 0.7,
   `a fir is a narrow cone, as Solstice requires of its own (top third / bottom third: ${mean.toFixed(2)} on average over 8 trees < 0.6, none above 0.7: ${tapers.map((t) => t.toFixed(2)).join(" ")})`);
const o = stats(T.treeModel("broadleaf", 5, 7, 0)), bi = stats(T.treeModel("birch", 7, 7, 0));
ok(o.reach / o.top > bi.reach / bi.top, `an oak spreads wider for its height than a birch (${(o.reach / o.top).toFixed(2)} vs ${(bi.reach / bi.top).toFixed(2)})`);
const BUDGET = { 0: 2800, 2: 520 };                    // the builder it replaced: 2,196 near (its fir) and 381 far at most
for (const [k, h] of [["broadleaf", 4], ["broadleaf", 5], ["birch", 6], ["birch", 7], ["conifer", 6], ["conifer", 10], ["bush", 1]]) for (const lod of [0, 2]) {
  const m = stats(T.treeModel(k, h, 4242, lod)), top = S.ADAPT[k].top(h);
  ok(m.reach <= T.REACH + 1e-9 && m.verts <= BUDGET[lod] && Math.abs(m.top - top) < 0.9,
     `${k} ${h} m (lod ${lod}): within its footprint (${m.reach.toFixed(2)} m), its top where its cells end (${m.top.toFixed(1)} of ${top.toFixed(1)} m), ${m.verts} vertices within ${BUDGET[lod]}`);
}
// 4
const a = T.treeModel("broadleaf", 5, 11, 0), a2 = T.treeModel("broadleaf", 5, 11, 0), b = T.treeModel("broadleaf", 5, 12, 0);
ok(JSON.stringify(a.leaves.pos) === JSON.stringify(a2.leaves.pos) && JSON.stringify(a.leaves.pos) !== JSON.stringify(b.leaves.pos), "the same seed grows the same tree, another seed another");
// 5
const mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8");
ok(/const key = t\.kind \+ ":" \+ t\.height \+ ":" \+ variant \+ ":" \+ far;/.test(mesher) && /models\.get\(key\)/.test(mesher), "the mesher caches a few variants per kind and height");

// A ROOT FLARE (#181, playtest 2026-11-11: trunks ended in a flat faceted cut standing on the grass): in every kind's
// LOD0 model the trunk's lowest ring is at least a third wider than the trunk a tenth of the height up, and its first
// ring sits under the ground (z < 0), so no cut face rests on the surface
for (const kind of ["broadleaf", "birch", "conifer"]) {                 // (a bush has no trunk to flare)
  const b = T.treeModel(kind, 12, 7, 0).bark, sp = S.parseSpecies(S.RECIPES[S.ADAPT[kind].recipe]);
  // the first ring is the one under the ground (no limb goes there): its width in x against the recipe's own trunk
  // diameter at this height — the flare is half as much again on top of the tube's base taper
  let lo = Infinity, hi = -Infinity, zmin = Infinity;
  for (let i = 0; i < b.n; i++) { const z = b.pos[i * 3 + 2]; zmin = Math.min(zmin, z); if (z < 0) { lo = Math.min(lo, b.pos[i * 3]); hi = Math.max(hi, b.pos[i * 3]); } }
  const base = hi - lo, plain = 2 * sp.trunk.radius * (12 / sp.height);
  ok(zmin < 0 && base >= 1.3 * plain && base <= 3 * plain, `${kind}: the trunk's first ring is under the ground (${zmin.toFixed(2)} m) and flared — ${base.toFixed(2)} m wide against the recipe's ${plain.toFixed(2)} m trunk`);
}


// A MIDDLE LEVEL OF DETAIL (#150): a tree at LOD1 (a chunk 48–64 m off) is lighter than the near model and heavier than
// the far one, in bark and in leaves alike — every trunked kind, the same seed
for (const kind of ["broadleaf", "birch", "conifer"]) {
  const v = [0, 1, 2].map((lod) => { const m = T.treeModel(kind, 12, 7, lod); return [m.bark.n, m.leaves.n]; });
  ok(v[0][0] > v[1][0] && v[1][0] > v[2][0] && v[0][1] > v[1][1] && v[1][1] > v[2][1], `${kind}: LOD1 sits between LOD0 and LOD2 (bark ${v.map((x) => x[0]).join(" > ")}, leaves ${v.map((x) => x[1]).join(" > ")})`);
}

console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
