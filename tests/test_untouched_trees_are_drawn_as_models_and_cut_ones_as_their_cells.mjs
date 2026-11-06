/*
 * test_untouched_trees_are_drawn_as_models_and_cut_ones_as_their_cells.mjs — static/land-trees.js + land-mesher.js
 * ("overall not impressive", operator 2026-11-06). The cells stay the tree's data; the picture follows them:
 *   1. an untouched forest chunk draws its trees as models (bark + alpha leaf cards) and none of their cells — no cell
 *      canopy or log segment is left anywhere in a 3 x 3 block of plots (crowns reaching a chunk's border included);
 *   2. one model per tree: the chunk holding a root's ground layer draws it, once (bark parts counted against roots);
 *   3. every species builds, every model stays inside its tree's footprint (REACH from the axis), and every leaf card's
 *      texture coordinates stay inside its species' atlas tile;
 *   4. cutting one log of a tree takes that tree's model away and draws that tree from its cells instead;
 *   5. the same chunk meshes to the same bytes twice (every screen grows the same forest), and wind weights are present.
 *
 * Run: node tests/test_untouched_trees_are_drawn_as_models_and_cut_ones_as_their_cells.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
const T = await import(join(ROOT, "static", "land-trees.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

const q = Wd.plotCoords(Wd.firstWave()[44]), cu0 = q.u0 / 16, cv0 = q.v0 / 16;
// 1 + 2: a 3 x 3 block of plots, every layer that holds ground or trees
let cellParts = 0, roots = 0, modelled = 0, chunkOf = null;
for (let dx = 0; dx < 3; dx++) for (let dy = 0; dy < 3; dy++) {
  const cu = cu0 + dx, cv = cv0 + dy;
  let lo = 99, hi = 0;
  for (let i = 0; i < 16; i++) for (let j = 0; j < 16; j++) {
    const col = Wd.column(q.face, cu * 16 + i, cv * 16 + j), t = Wd.treeAt(q.face, cu * 16 + i, cv * 16 + j, col);
    lo = Math.min(lo, col.top); hi = Math.max(hi, col.top);
    if (t) { roots++; if (!chunkOf && t.kind !== "bush") chunkOf = { cu, cv, u: cu * 16 + i, v: cv * 16 + j, col, t }; }
  }
  for (let ch = Math.floor(lo / 16); ch <= Math.floor((hi + 12) / 16); ch++) {
    const r = M.meshChunk(q.face, cu, cv, ch, null, null, 0);
    if (r.empty) continue;
    if (r.trees) cellParts++;
    if (r.bark) modelled += new Set(Array.from(r.bark.wind).filter((_, k) => k % 4 === 3)).size;   // one phase per tree
  }
}
ok(roots > 10, `the block grows a forest (${roots} trees)`);
ok(cellParts === 0, `no tree cell is drawn where the trees are untouched (${cellParts} chunks with cell canopy)`);
ok(modelled === roots, `one model per tree: ${modelled} models for ${roots} roots`);

// 3: every species, both details
for (const kind of ["broadleaf", "birch", "conifer", "palm", "bush"]) for (const lod of [0, 2]) {
  const m = T.treeModel(kind, kind === "bush" ? 1 : 8, 4242, lod), tile = T.LEAF_TILE[kind];
  let far = 0, uvBad = 0;
  for (const part of [m.bark, m.leaves]) for (let i = 0; i < part.n; i++) far = Math.max(far, Math.hypot(part.pos[i * 3], part.pos[i * 3 + 1]));
  for (let i = 0; i < m.leaves.n; i++) {
    const u = m.leaves.uv[i * 2], v = m.leaves.uv[i * 2 + 1], tu = (tile & 1) * 0.5, tv = (tile >> 1) * 0.5;
    if (u < tu || u > tu + 0.5 || v < tv || v > tv + 0.5) uvBad++;
  }
  ok(m.bark.n + m.leaves.n > 0 && m.leaves.idx.length > 0, `${kind} (lod ${lod}) builds: ${m.bark.idx.length / 3} bark triangles, ${m.leaves.idx.length / 3} leaf triangles`);
  ok(far <= T.REACH + 1e-9, `${kind} (lod ${lod}) stays within ${T.REACH} m of its axis (${far.toFixed(2)})`);
  ok(uvBad === 0, `${kind} (lod ${lod}) leaf cards sample only their atlas tile ${tile}`);
}

// 4: cut one log of a tree: its model goes, its cells come back
const { cu, cv, u, v, col, t } = chunkOf, ch = Math.floor(col.top / 16), logH = col.top + 2;
const before = M.meshChunk(q.face, cu, cv, Math.floor(logH / 16), null, null, 0);
const edits = new Map([[q.face + ":" + u + ":" + v + ":" + logH, Wd.B.air]]);
const after = M.meshChunk(q.face, cu, cv, Math.floor(logH / 16), edits, null, 0);
const phases = (r) => r.bark ? new Set(Array.from(r.bark.wind).filter((_, k) => k % 4 === 3)).size : 0;
const base = M.meshChunk(q.face, cu, cv, ch, null, null, 0), baseCut = M.meshChunk(q.face, cu, cv, ch, edits, null, 0);
ok(phases(baseCut) === phases(base) - 1, `cutting a ${t.kind}'s log removes its model (${phases(base)} -> ${phases(baseCut)} models in its chunk)`);
ok(!before.trees && (after.trees || baseCut.trees), "and the cut tree is drawn from its cells instead");

// 5: deterministic, wind-weighted
const a1 = M.meshChunk(q.face, cu, cv, ch, null, null, 0), a2 = M.meshChunk(q.face, cu, cv, ch, null, null, 0);
const same = (x, y) => x && y && x.length === y.length && x.every((w, i) => w === y[i]);
ok(same(a1.foliage.pos, a2.foliage.pos) && same(a1.bark.pos, a2.bark.pos), "the same chunk meshes to the same forest twice");
ok(a1.foliage.wind && a1.foliage.wind.some((w, i) => i % 4 !== 3 && w !== 0), "leaves carry wind weights");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
