// The land beyond the far ground is drawn out to the hills (2026-11-22, the Chlorophyll shot: the far ground ended 1.7 km
// off and past it was sky, where the reference's horizon is hills and forest in the haze; with the wilderness's rolling
// hills a tenth of the meadow views see hills past 1.7 km — test_the_wilderness_rolls_in_hills…). Since 2026-11-23 it is
// ring 0 of the distant land (static/land-far.js; how far the rings reach: test_the_distant_land_is_drawn_out_past_the_horizon…).
//   1. ring 0 reaches past the far ground (128 m a vertex, to 3.8 km);
//   2. where it overlaps the far ground it sinks under it, so the two never fight; inside that it is not built at all;
//   3. a forest stands at its canopy's height in the canopy's olive (the canopy tiles' own colour), the sea at the sea;
//   4. the page places it with the far ground every frame and shades it by the clouds.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const Far = await import(join(ROOT, "static", "land-far.js")), Wd = await import(join(ROOT, "static", "land-world.js")), Fo = await import(join(ROOT, "static", "land-forest.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const FAR_HALF = Far.FAR_N / 2 * Far.FAR_STEP, R0 = Far.RINGS[0];
ok(R0.half > FAR_HALF * 2 && R0.step > Far.FAR_STEP && R0.step <= 200, `ring 0: one vertex every ${R0.step} m out to ${R0.half} m, past the far ground's ${FAR_HALF} m`);
// a ring 0 built as the page asks for it (land.js updateFar), round a meadow by the town
const fu = 55680, fv = 80640, [au, av] = Far.ringAnchor(0, 55660, 80600), r = FAR_HALF - R0.step;
const ring = Far.farRing(0, 0, au, av, [fu - r, fu + r, fv - r, fv + r], [fu, fv, FAR_HALF - Far.FAR_STEP], false);
// read a vertex back: its height over the sea from its position
const N = 2 * R0.half / R0.step, M = N + 1, hOf = (i, j) => { const q = j * M + i, p = [0, 1, 2].map((d) => ring.pos[q * 3 + d] + ring.anchor[d]); return Math.hypot(...p) - Wd.R0; };
let sunk = 0, sunkOk = 0, high = 0, highOk = 0, forest = 0, forestOk = 0, inside = 0;
const used = new Set(ring.idx);
for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
  const u = au - R0.half + i * R0.step, v = av - R0.half + j * R0.step, q = j * M + i;
  if (!used.has(q)) { if (Math.max(Math.abs(u - fu), Math.abs(v - fv)) < r) inside++; continue; }
  const w = Wd.wrap(0, u, v), c = Wd.column(w.face, w.u, w.v), can = c.top <= Wd.SEA ? 0 : Fo.canopyHeight(c), want = c.top <= Wd.SEA ? Wd.SEA + 0.5 : c.height + can;
  const h = hOf(i, j), under = Math.max(Math.abs(u - fu), Math.abs(v - fv)) < FAR_HALF - Far.FAR_STEP;
  if (under) { sunk++; if (Math.abs(h - (want - Far.RING_SINK)) < 0.05) sunkOk++; } else { high++; if (Math.abs(h - want) < 0.05) highOk++; }
  if (can > 0 && !under) { forest++; const col = [0, 1, 2].map((d) => ring.col[q * 3 + d]); if (col.every((x, d) => Math.abs(x - Far.RING_COL.forest[d]) < 1e-6)) forestOk++; }
}
ok(sunk > 50 && sunkOk === sunk && Far.RING_SINK > 5, `under the far ground's edge it sinks ${Far.RING_SINK} m (${sunkOk} of ${sunk} vertices)`);
ok(inside > 500, `inside the far ground it is not built at all (${inside} vertices skipped)`);
ok(high > 2000 && highOk === high, `past the far ground every vertex stands at its ground, or its canopy where a forest grows, or the sea (${highOk} of ${high})`);
const canopyCol = (page.match(/m\.colorNode = shadeByClouds\(TSL\.vec3\(([\d., ]+)\)\.mul\(TSL\.attribute\("color", "vec3"\)\)\);/) || [])[1];
ok(canopyCol && canopyCol.split(",").map(Number).every((x, d) => x === Far.RING_COL.forest[d]) && forest > 50 && forestOk === forest,
  `a forest is the canopy's olive (${Far.RING_COL.forest}; ${forestOk} of ${forest} forest vertices)`);
const rm = page.slice(page.indexOf("function ringMaterial()"), page.indexOf("function farDone("));
ok(/\[farMesh, farSea, borderMesh, farBoxMesh, \.\.\.ringMeshes\]/.test(page) && /matOuter = ringMaterial\(\)/.test(page) && /m\.colorNode = shadeByClouds\(/.test(rm),
  "the page places the rings with the far ground every frame, and the clouds shade them");
// the grain: noise on the vertex's planet place (stable as the eye moves), each layer faded under a few pixels, the sea plain
{ const uvOk = ring.uvw && ring.uvw.length === ring.pos.length && [...used].slice(0, 200).every((q) => Math.abs(ring.uvw[q * 3] - (((au - R0.half + (q % M) * R0.step) % Far.RING_UV) + Far.RING_UV) % Far.RING_UV) < 1e-3);
  ok(uvOk && /TSL\.attribute\("uvw", "vec3"\)/.test(rm) && /TSL\.mx_noise_float\(uvw\.xy\.div\(wl\)\)/.test(rm) && /TSL\.smoothstep\(px\.mul\(3\), px\.mul\(6\), TSL\.float\(wl\)\)/.test(rm)
    && /TSL\.mix\(grain\.max\(0\.3\), TSL\.float\(1\), sea\)/.test(rm),
    "a ring is grained by noise on its own planet place (crowns, groves, fields), faded under a few pixels, the sea left plain"); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
