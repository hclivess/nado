/*
 * test_trees_are_drawn_as_models_and_taking_one_apart_never_makes_a_blob.mjs — static/land-trees.js + land-mesher.js
 * ("overall not impressive", operator 2026-11-06). The cells stay the tree's data; the picture follows them:
 *   1. an untouched forest chunk draws its trees as models (bark + alpha leaf cards) and none of their cells — no cell
 *      canopy or log segment is left anywhere in a 3 x 3 block of plots (crowns reaching a chunk's border included);
 *   2. one model per tree: the chunk holding a root's ground layer draws it, once (bark parts counted against roots);
 *   3. every species builds, every model stays inside its tree's footprint (REACH from the axis), and every leaf card's
 *      texture coordinates stay inside its species' atlas tile;
 *   4. taking a tree apart never makes a blob ("taking apart bushes creates blobs", operator 2026-11-06): cutting a log
 *      keeps the model and leaves out that length of trunk, chopping a bush's leaf cell leaves out those leaves, and
 *      neither draws any cell surface; a leaf block placed in the open is a cluster of leaf cards, not a surface;
 *   5. the same chunk meshes to the same bytes twice (every screen grows the same forest), and wind weights are present.
 *
 * Run: node tests/test_trees_are_drawn_as_models_and_taking_one_apart_never_makes_a_blob.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
const T = await import(join(ROOT, "static", "land-trees.js"));
let fails = 0;
// one wind phase per tree: count the phases of vertices that sway (a fallen stick on the ground does not)
const swaying = (p) => { const s = new Set(); for (let i = 0; i < p.wind.length; i += 4) if (p.wind[i] || p.wind[i + 1] || p.wind[i + 2]) s.add(p.wind[i + 3]); return s.size; };
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
    if (r.bark) modelled += swaying(r.bark);   // one phase per tree
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

// 4: take trees apart — the model stays, less the taken parts, and no cell surface appears
const { cu, cv, u, v, col, t } = chunkOf, ch = Math.floor(col.top / 16), logH = col.top + 2;
const phases = (r) => r.bark ? swaying(r.bark) : 0;
const tris = (p) => (p ? p.idx.length / 3 : 0);
const cutLog = new Map([[q.face + ":" + u + ":" + v + ":" + logH, Wd.B.air]]);
const base = M.meshChunk(q.face, cu, cv, ch, null, null, 0), baseCut = M.meshChunk(q.face, cu, cv, ch, cutLog, null, 0);
ok(phases(baseCut) === phases(base) && tris(baseCut.bark) < tris(base.bark),
   `cutting a ${t.kind}'s log keeps its model and leaves out that length of trunk (${tris(base.bark)} -> ${tris(baseCut.bark)} bark triangles)`);
ok(!baseCut.trees, "and draws no cell surface for the cut tree");
// a bush: chop every one of its leaf cells but one
let bush = null;
for (let i = 2; i < 14 && !bush; i++) for (let j = 2; j < 14 && !bush; j++) for (let dx = 0; dx < 3 && !bush; dx++) for (let dy = 0; dy < 3 && !bush; dy++) {
  const bu = (cu0 + dx) * 16 + i, bv = (cv0 + dy) * 16 + j, c = Wd.column(q.face, bu, bv), tb = Wd.treeAt(q.face, bu, bv, c);
  if (tb && tb.kind === "bush") bush = { bu, bv, c, cu: cu0 + dx, cv: cv0 + dy };
}
ok(!!bush, "the block grows a bush");
const bch = Math.floor((bush.c.top + 1) / 16), chop = new Map();
for (const [du, dv] of [[1, 0], [-1, 0], [0, 1], [0, -1], [0, 0]]) chop.set(q.face + ":" + (bush.bu + du) + ":" + (bush.bv + dv) + ":" + (bush.c.top + 1), Wd.B.air);
const b0 = M.meshChunk(q.face, bush.cu, bush.cv, bch, null, null, 0), b1 = M.meshChunk(q.face, bush.cu, bush.cv, bch, chop, null, 0);
ok(tris(b1.foliage) < tris(b0.foliage) && tris(b1.foliage) > 0, `chopping a bush's lower leaves leaves out those cards (${tris(b0.foliage)} -> ${tris(b1.foliage)} leaf triangles)`);
ok(!b1.trees, "and draws no blob where they were");
// a leaf block placed in the open air above the meadow
const placed = new Map([[q.face + ":" + (bush.bu + 4) + ":" + (bush.bv + 4) + ":" + (bush.c.top + 9), Wd.B.leaves]]);
const pch = Math.floor((bush.c.top + 9) / 16), p0 = M.meshChunk(q.face, bush.cu, bush.cv, pch, null, null, 0), p1 = M.meshChunk(q.face, bush.cu, bush.cv, pch, placed, null, 0);
ok(tris(p1.foliage) - tris(p0.foliage) === 12 && !p1.trees, `a placed leaf block is six leaf cards (${tris(p1.foliage) - tris(p0.foliage)} triangles), no surface`);

// 5: deterministic, wind-weighted
const a1 = M.meshChunk(q.face, cu, cv, ch, null, null, 0), a2 = M.meshChunk(q.face, cu, cv, ch, null, null, 0);
const same = (x, y) => x && y && x.length === y.length && x.every((w, i) => w === y[i]);
ok(same(a1.foliage.pos, a2.foliage.pos) && same(a1.bark.pos, a2.bark.pos), "the same chunk meshes to the same forest twice");
ok(a1.foliage.wind && a1.foliage.wind.some((w, i) => i % 4 !== 3 && w !== 0), "leaves carry wind weights");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
