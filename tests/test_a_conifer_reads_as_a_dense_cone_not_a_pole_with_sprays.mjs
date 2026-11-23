/*
 * test_a_conifer_reads_as_a_dense_cone_not_a_pole_with_sprays.mjs — the conifer up close (2026-11-22: in the operator's
 * phone screenshot and beside the Chlorophyll shot every spruce read as a pole with a few drooping sprays, where a Norway
 * spruce is a dark cone whose tiers hide the trunk). Three things made it a pole, each pinned here:
 *   1. the needle spray (static/land.js paintLeaves, atlas tile 2) covers most of its card, at full size and mipped down —
 *      it was needles on the middle twig alone, 0.13-0.15 of the card, so a crown of cards that closed the cone still showed
 *      the sky through it;
 *   2. the middle and far models' sprays face a walker — they lay flat along their branches, edge on from the ground;
 *   3. a fir's whorl branches are thinned EVENLY to the middle and far budgets — at random, a fifth of the far model's crown
 *      could stand bare between tufts.
 *
 * Run: node tests/test_a_conifer_reads_as_a_dense_cone_not_a_pole_with_sprays.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const T = await import(join(ROOT, "static", "land-trees.js")), S = await import(join(ROOT, "static", "land-species.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };

// 1. the needle tile, painted by land.js's own code: its strokes (round-capped lines) rasterised into the tile's 512 x 512
// coverage, then box-filtered as the mip chain is, and cut where the leaf material cuts (alphaTest 0.42)
{
  const src = readFileSync(join(ROOT, "static", "land.js"), "utf8");
  const body = src.slice(src.indexOf("  // 2: needle spray"), src.indexOf("  // 3: palm frond"));
  ok(body.length > 200 && body.length < 6000, "land.js paints the needle spray between its tile 2 and tile 3 markers");
  const N = 512, mask = new Float32Array(N * N);
  const line = (x0, y0, x1, y1, w) => {
    y0 -= 512; y1 -= 512;                                            // tile 2 sits at (0, 512) in the atlas
    const r = w / 2, dx = x1 - x0, dy = y1 - y0, l2 = dx * dx + dy * dy || 1e-9;
    for (let y = Math.max(0, Math.floor(Math.min(y0, y1) - r)); y <= Math.min(N - 1, Math.ceil(Math.max(y0, y1) + r)); y++)
      for (let x = Math.max(0, Math.floor(Math.min(x0, x1) - r)); x <= Math.min(N - 1, Math.ceil(Math.max(x0, x1) + r)); x++) {
        const px = x + 0.5, py = y + 0.5, t = Math.min(1, Math.max(0, ((px - x0) * dx + (py - y0) * dy) / l2));
        if (Math.hypot(px - x0 - t * dx, py - y0 - t * dy) <= r) mask[y * N + x] = 1;
      }
  };
  let seed = 11;
  const R = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  // (the painting clips itself to its tile, 6 px in from every edge: the same clip here)
  const clip = { save() {}, restore() {}, beginPath() {}, clip() {}, rect: (x, y, w, h) => { clip.box = [x, y - 512, x + w, y - 512 + h]; } };
  new Function("line", "R", "hsl", "col", "msk", body)(line, R, () => "#000", clip, clip);
  ok(clip.box && clip.box[0] >= 4 && clip.box[2] <= 508 && clip.box[1] >= 4 && clip.box[3] <= 508, "the needle spray is painted inside its own tile, clear of the palm frond's");
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) if (!clip.box || x < clip.box[0] || x >= clip.box[2] || y < clip.box[1] || y >= clip.box[3]) mask[y * N + x] = 0;
  const cover = [];
  let m = mask, n = N;
  for (let lvl = 0; lvl < 5; lvl++) {
    let c = 0; for (let i = 0; i < n * n; i++) if (m[i] > 0.42) c++;
    cover.push(c / (n * n));
    const h = n / 2, next = new Float32Array(h * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < h; x++) next[y * h + x] = (m[2 * y * n + 2 * x] + m[2 * y * n + 2 * x + 1] + m[(2 * y + 1) * n + 2 * x] + m[(2 * y + 1) * n + 2 * x + 1]) / 4;
    m = next; n = h;
  }
  ok(cover.every((c) => c >= 0.4), `the needle spray covers its card at every mip level (${cover.map((c) => c.toFixed(2)).join(" ")}; ≥ 0.40 — needles on the middle twig alone were 0.13-0.15)`);
}

// 2. each spray card's facing: how much of its area a walker sees side on, averaged round the tree — the horizontal part
// of the card's normal (1 a card standing up, 0 one lying flat)
const facing = (m) => {
  const L = m.leaves; let sum = 0, n = 0;
  for (let q = 0; q < L.idx.length; q += 6) {
    const [a, b, c] = [L.idx[q], L.idx[q + 1], L.idx[q + 2]].map((i) => [L.pos[i * 3], L.pos[i * 3 + 1], L.pos[i * 3 + 2]]);
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    const nx = u[1] * v[2] - u[2] * v[1], ny = u[2] * v[0] - u[0] * v[2], nz = u[0] * v[1] - u[1] * v[0], l = Math.hypot(nx, ny, nz) || 1;
    sum += Math.hypot(nx, ny) / l; n++;
  }
  return sum / n;
};
const SEEDS = [2, 7, 11, 23, 99, 4242];
for (const lod of [1, 2]) {
  const f = SEEDS.reduce((s, sd) => s + facing(T.treeModel("conifer", 9, sd, lod)), 0) / SEEDS.length;
  ok(f >= 0.7, `the ${lod === 1 ? "middle" : "far"} conifer's sprays face a walker (side-on share ${f.toFixed(2)} ≥ 0.70 — lying flat along their drooping branches, 0.48)`);
}

// 3. the whorl branches the far and middle models keep are spread up the trunk: the widest bare stretch between kept
// branches, as a share of the crown's height
const gap = (lod, sd) => {
  const { stems } = S.growPlant("conifer", 9, (() => { let s = sd >>> 0 || 1; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })(), lod);
  const z = stems.filter((s) => s.depth === 1).map((s) => s.pts[0][2]).sort((a, b) => a - b);
  let g = 0; for (let i = 1; i < z.length; i++) g = Math.max(g, z[i] - z[i - 1]);
  return g / (z[z.length - 1] - z[0]);
};
for (const lod of [1, 2]) {
  const worst = Math.max(...SEEDS.map((sd) => gap(lod, sd)));
  ok(worst <= 0.1, `the ${lod === 1 ? "middle" : "far"} conifer keeps branches all the way up (widest bare stretch ${(worst * 100).toFixed(0)} % of the crown ≤ 10 % — thinned at random, the far model's was 20 %)`);
}
console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
