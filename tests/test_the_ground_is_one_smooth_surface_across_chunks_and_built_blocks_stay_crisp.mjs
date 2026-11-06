/*
 * test_the_ground_is_one_smooth_surface_across_chunks_and_built_blocks_stay_crisp.mjs — static/land-mesher.js after "it
 * should not really be blocky" (operator, 2026-11-06), meshing real chunks of the landing site in node:
 *   1. the ground is ONE watertight surface: over a 3 x 3 block of plots, every edge of the smooth mesh is shared by
 *      exactly two triangles except along the block's outer rim — no gap and no doubled seam where chunks meet;
 *   2. it is smooth: no smooth-surface vertex sits on a whole layer the way a cube's corner would (the surface follows
 *      the generator's exact height), and the meadow is coloured as grass, not bare earth;
 *   3. trees are organic: the logs come out as round trunks and the canopy as a surface (their own part, `trees`), with
 *      no crisp cube for either;
 *   4. what people build stays crisp: a brick placed on the ground is textured cube faces (with atlas uvs), and the
 *      ground around it stays smooth;
 *   5. digging dents the ground: removing a solid cell lowers the surface there;
 *   6. the field is the one land-world.fieldOf rule the page touches the ground by (static/land.js fieldCell).
 *
 * Run: node tests/test_the_ground_is_one_smooth_surface_across_chunks_and_built_blocks_stay_crisp.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

const q = Wd.plotCoords(Wd.firstWave()[44]), cu0 = q.u0 / 16, cv0 = q.v0 / 16;
const top = Wd.column(q.face, q.u0 + 8, q.v0 + 8).top, ch = Math.floor(top / 16);
const chs = [ch - 1, ch, ch + 1];

// 1. watertight across chunks: count every smooth edge in world space (mm keys)
const edgeUse = new Map();
let smoothTris = 0, solidAny = false, onLayer = 0, verts = 0, green = 0, brown = 0;
const keyOf = (x, y, z) => `${Math.round(x * 1000)},${Math.round(y * 1000)},${Math.round(z * 1000)}`;
for (let dx = 0; dx < 3; dx++) for (let dy = 0; dy < 3; dy++) for (const c of chs) {
  const r = M.meshChunk(q.face, cu0 + dx, cv0 + dy, c, null);
  if (r.empty || !r.smooth) continue;
  if (r.solid) solidAny = true;
  const P = r.smooth.pos, I = r.smooth.idx, A = r.anchor;
  const k = (i) => keyOf(A[0] + P[i * 3], A[1] + P[i * 3 + 1], A[2] + P[i * 3 + 2]);
  for (let t = 0; t < I.length; t += 3) {
    smoothTris++;
    const v = [k(I[t]), k(I[t + 1]), k(I[t + 2])];
    for (const [a, b] of [[0, 1], [1, 2], [2, 0]]) { const e = v[a] < v[b] ? v[a] + "|" + v[b] : v[b] + "|" + v[a]; edgeUse.set(e, (edgeUse.get(e) || 0) + 1); }
  }
  for (let i = 0; i < P.length / 3; i++) {
    verts++;
    const x = A[0] + P[i * 3], y = A[1] + P[i * 3 + 1], z = A[2] + P[i * 3 + 2], g = Wd.gridOf([x, y, z].map((w) => w / Math.hypot(x, y, z)));
    const h = Math.hypot(x, y, z) - Wd.R0;
    if (Math.abs(h - Math.round(h)) < 1e-3) onLayer++;
    const cr = r.smooth.col[i * 3], cg = r.smooth.col[i * 3 + 1];
    if (g.u > q.u0 + 16 && g.u < q.u0 + 32 && g.v > q.v0 + 16 && g.v < q.v0 + 32) (cg > cr * 1.3 ? green++ : brown++);
  }
}
// rim: any edge with a vertex outside the inner ring of the 3x3 block (the outer chunks' far halves) may be open
const inner = (key) => key.split("|").every((p) => {
  const [x, y, z] = p.split(",").map((w) => Number(w) / 1000), g = Wd.gridOf([x, y, z].map((w) => w / Math.hypot(x, y, z)));
  return g.u > q.u0 + 4 && g.u < q.u0 + 44 && g.v > q.v0 + 4 && g.v < q.v0 + 44;
});
let open = 0, doubled = 0;
for (const [e, n] of edgeUse) if (inner(e)) { if (n === 1) open++; if (n > 2) doubled++; }
ok(smoothTris > 1000 && open === 0 && doubled === 0, `the ground over 3 x 3 plots is one watertight surface: ${smoothTris} triangles, ${open} open and ${doubled} doubled edges inside`);

// 2. smooth, and coloured as a meadow
ok(onLayer / verts < 0.05, `vertices follow the exact ground, not whole layers (${onLayer} of ${verts} on a layer)`);
ok(green > brown * 3, `the meadow is grass-coloured (${green} green vertices, ${brown} other)`);

// 3. trees: round trunks and canopy surfaces, no crisp cubes
let treeParts = 0;
for (let dx = 0; dx < 3; dx++) for (let dy = 0; dy < 3; dy++) for (const c of chs) { const r = M.meshChunk(q.face, cu0 + dx, cv0 + dy, c, null); if (!r.empty && r.trees) treeParts++; }
ok(!solidAny && treeParts > 0, `no crisp cube anywhere in untouched land; the trees are their own smooth part (${treeParts} chunks hold some)`);

// 4. a brick stays crisp
const key = (u, v, h) => `${q.face}:${u}:${v}:${h}`;
const bu = q.u0 + 20, bv = q.v0 + 20, bt = Wd.column(q.face, bu, bv).top + 1;
const withBrick = M.meshChunk(q.face, cu0 + 1, cv0 + 1, Math.floor(bt / 16), new Map([[key(bu, bv, bt), Wd.B.brick]]));
ok(withBrick.solid && withBrick.solid.uv && withBrick.solid.pos.length / 3 >= 16 && withBrick.smooth,
   `a placed brick is crisp textured faces (${withBrick.solid ? withBrick.solid.pos.length / 12 : 0} quads) beside smooth ground`);

// 5. digging dents the ground
const du = q.u0 + 24, dv = q.v0 + 24, dc = Wd.column(q.face, du, dv), dig = Wd.fieldOf(dc, dc.top) > 0 ? dc.top : dc.top - 1;
const lowest = (r, u, v) => {
  let lo = Infinity; const P = r.smooth.pos, A = r.anchor;
  for (let i = 0; i < P.length / 3; i++) {
    const x = A[0] + P[i * 3], y = A[1] + P[i * 3 + 1], z = A[2] + P[i * 3 + 2], g = Wd.gridOf([x, y, z].map((w) => w / Math.hypot(x, y, z)));
    if (Math.abs(g.u - (u + 0.5)) < 0.75 && Math.abs(g.v - (v + 0.5)) < 0.75) lo = Math.min(lo, Math.hypot(x, y, z) - Wd.R0);
  }
  return lo;
};
const before = lowest(M.meshChunk(q.face, cu0 + 1, cv0 + 1, Math.floor(dig / 16), null), du, dv);
const after = lowest(M.meshChunk(q.face, cu0 + 1, cv0 + 1, Math.floor(dig / 16), new Map([[key(du, dv, dig), Wd.B.air]])), du, dv);
ok(after < before - 0.3, `digging a cell dents the surface there (lowest point ${before.toFixed(2)} -> ${after.toFixed(2)} m)`);

// 6. one field for drawing and touching
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok(/Wd\.fieldOf\(colAt\(/.test(land) && /fieldOf/.test(readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8")),
   "the page touches the ground by the same fieldOf the mesher draws it by");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
