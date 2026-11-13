/*
 * test_a_sky_map_is_read_back_from_the_eye_it_was_marched_from_so_the_clouds_stand_still_at_speed.mjs — the operator
 * (2026-11-13): "at high speeds clouds really stutter". The sky map (land.js buildClouds / cloudsFrame) is marched from
 * the eye latched at a cycle's start and swapped in whole 32 frames later; at 290 m/s every swap moved every cloud by the
 * 150 m flown since, at once. Now each texel carries its cloud's distance (land-clouds.js march's fifth value) and the
 * dome reads the map reprojected from the latched eye to the frame's eye (Clouds.reproject, which the TSL reader copies
 * line for line). This pins the reference:
 *   1. march's distance: on a ray through cloud it lies within the ray's stretch through the layer and where the density
 *      is (the light-weighted mean of the march's distances, recomputed here); a ray through clear sky carries the middle
 *      of its stretch; a ray that never enters the layer carries FAR; the first four values are as before;
 *   2. reproject: a cloud at a known point, seen from the latched eye in direction u0, is seen from an eye moved by
 *      `shift` in direction d at distance t, and reproject(d, shift, t) gives u0 back — for shifts of a metre and of
 *      150 m, in every direction;
 *   3. the stutter it removes: for a craft at 290 m/s over a half-second cycle and a cloud a kilometre off, reading the
 *      map at d itself (what the page did) is off by more than 5 degrees; reprojected, by nothing; and reading it over as
 *      the page does (the first distance from the texel at d, a far one where no cloud is) the first guess lands within
 *      5 degrees — inside a heap's 3–10 — and the next on it;
 *   4. the page's reader carries the reprojection: land.js reads the distance target, reprojects three times over and
 *      reads the light at the result, names and marches both targets, and sets the shift every frame from the latched eye.
 * Run: node tests/test_a_sky_map_is_read_back_from_the_eye_it_was_marched_from_so_the_clouds_stand_still_at_speed.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const C = await import(join(ROOT, "static", "land-clouds.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const norm = (v) => { const n = Math.hypot(...v); return v.map((x) => x / n); };
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const deg = (a, b) => Math.acos(Math.max(-1, Math.min(1, dot(a, b)))) * 180 / Math.PI;

// 1. the distance a march carries
const vol = C.noiseVolume(), dr = [1, 0];
const L = C.light([0, 1, 0], [20, 19, 18], [1.5, 1.8, 2.4], [1.2, 1.4, 1.8]);
const ground = [0, C.RG + 2, 0], up = [0, 1, 0];
let cloudRay = null, clearRay = null;
for (let i = 0; i < 4000 && !(cloudRay && clearRay); i++) {
  const az = (i * 2.399963), el = 0.15 + (i % 37) * 0.02, d = norm([Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az)]);
  const m = C.march(vol, ground, d, L, dr);
  if (m[3] > 0.5 && !cloudRay) cloudRay = { d, m };
  if (m[3] < 0.001 && !clearRay) clearRay = { d, m };
}
ok(cloudRay && clearRay, "from the ground: a ray through a heap and a ray through clear sky are found");
{
  const { d, m } = cloudRay, r = Math.hypot(...ground), mu = dot(ground, d) / r, sp = C.span(r, mu);
  ok(m.length === 5 && m[4] >= sp[0] && m[4] <= sp[1], `through cloud, the fifth value is a distance within the ray's stretch through the layer (${m[4].toFixed(0)} m in ${sp[0].toFixed(0)}..${sp[1].toFixed(0)})`);
  // the light-weighted mean of the march's own distances, stepped again here
  const dt = (sp[1] - sp[0]) / C.K.steps;
  let T = 1, t = sp[0] + dt * 0.5, D = 0, A = 0;
  for (let i = 0; i < C.K.steps && T > 0.01; i++, t += dt) {
    const p = C.undrift([ground[0] + d[0] * t, ground[1] + d[1] * t, ground[2] + d[2] * t], dr), dens = C.density(vol, p, Math.exp(-t / C.K.haze));
    if (dens <= 0.001) continue;
    const a = 1 - Math.exp(-dens * C.K.sigma * dt);
    D += T * a * t; A += T * a; T *= 1 - a;
  }
  ok(Math.abs(m[4] - D / A) < 1, `…and it is the light-weighted mean of where the cloud was met (${(D / A).toFixed(1)} m)`);
  ok(Math.abs(m[3] - A) < 1e-9, "…and the cover is as before");
}
{
  const { d, m } = clearRay, r = Math.hypot(...ground), mu = dot(ground, d) / r, sp = C.span(r, mu);
  ok(Math.abs(m[4] - (sp[0] + sp[1]) / 2) < 1e-6, `through clear sky the distance is the middle of the stretch (${m[4].toFixed(0)} m)`);
}
{
  const above = [0, C.RT + 3000, 0], m = C.march(vol, above, up, L, dr);
  ok(m[3] === 0 && m[4] === C.FAR, `a ray that never enters the layer (from 3 km over the tops, straight up) carries FAR (${m[4]} m)`);
}

// 2. reproject gives the latched direction back
let worst = 0;
for (const shiftM of [1, 150]) for (let i = 0; i < 200; i++) {
  const az = i * 2.399963, el = -0.3 + (i % 23) * 0.06;
  const u0 = norm([Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az)]), t0 = 600 + (i % 7) * 900;
  const E0 = [0, C.RG + 2, 0], P = [E0[0] + u0[0] * t0, E0[1] + u0[1] * t0, E0[2] + u0[2] * t0];
  const sh = norm([Math.sin(i), 0.1, Math.cos(i * 1.7)]).map((x) => x * shiftM), E1 = [E0[0] + sh[0], E0[1] + sh[1], E0[2] + sh[2]];
  const toP = [P[0] - E1[0], P[1] - E1[1], P[2] - E1[2]], t = Math.hypot(...toP), d = norm(toP);
  worst = Math.max(worst, deg(C.reproject(d, sh, t), u0));
}
ok(worst < 1e-4, `reproject(d, shift, t) returns the latched direction for shifts of 1 m and 150 m in every direction (worst ${worst.toExponential(1)} degrees)`);

// 3. the stutter: 290 m/s, a half-second cycle, a cloud a kilometre off
{
  const E0 = [0, C.RG + 500, 0], flown = [290 * 0.53, 0, 0], E1 = [E0[0] + flown[0], E0[1], E0[2]];
  const P = [0, C.RB + 60, 1000];                                 // a cloud ahead-and-up, a kilometre off
  const u0 = norm([P[0] - E0[0], P[1] - E0[1], P[2] - E0[2]]), toP = [P[0] - E1[0], P[1] - E1[1], P[2] - E1[2]], d = norm(toP), t = Math.hypot(...toP);
  const jump = deg(d, u0);
  ok(jump > 5, `read at d itself, the swap moved that cloud by ${jump.toFixed(1)} degrees at once (the stutter)`);
  ok(deg(C.reproject(d, flown, t), u0) < 1e-4, "reprojected with its distance, by nothing");
  // over again, as the page reads it: the first distance from the texel at d, which holds clear sky's middle-of-stretch
  const r = Math.hypot(...E0), sp = C.span(r, dot(E0, u0) / r), tClear = (sp[0] + sp[1]) / 2;
  const u1 = C.reproject(d, flown, tClear), u2 = C.reproject(d, flown, t);   // (the texel at u1 holds the cloud's true t)
  ok(deg(u1, u0) < 5 && deg(u2, u0) < 1e-4, `over again: the first guess lands within ${deg(u1, u0).toFixed(2)} degrees of it (inside a heap's width), the next on it`);
}

// 4. the page carries it
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const reader = page.slice(page.indexOf("const uvOf = (u) =>"), page.indexOf("cloudSky = new THREE.Mesh"));
ok(/reproject = \(dist\) => d\.mul\(max\(dist, 1\)\)\.add\(cloudO\.shift\)\.normalize\(\)/.test(reader), "the dome's reader reprojects as Clouds.reproject does: d·dist + shift, normalised (a distance under a metre read as one: never NaN)");
ok(/u1 = reproject\(read\(1, d\)\.r\), u2 = reproject\(read\(1, u1\)\.r\), u3 = reproject\(read\(1, u2\)\.r\), lit = read\(0, u3\)/.test(reader), "…three times over, the light read at the result");
ok(/count: 2, type: THREE\.HalfFloatType/.test(page) && /cloudMRT = TSL\.mrt\(\{ output: texel\.get\("color"\), dist: vec4\(texel\.get\("dist"\)/.test(page), "the map has two targets and the march writes its colour to the first EXPLICITLY (TSL.output is never assigned under a fragmentNode) and the distance to the second");
ok(/rt\.textures\[0\]\.name = "output"; rt\.textures\[1\]\.name = "dist";/.test(page), "the two targets are NAMED output and dist — the MRT node finds a target by its texture's name, and an unnamed one is never written");
ok(/tm\.outputNode = texel\.get\("color"\);/.test(page) && !/tm\.fragmentNode/.test(page), "the tile's colour is the material's outputNode, not a fragmentNode — three applies a renderer MRT only on that path (a fragmentNode wrote neither target)");
ok(/renderer\.setMRT\(cloudMRT\)/.test(page) && /cloudO\.shift\.value\.set\(cam\[0\] - cloudEye\[0\]/.test(page), "the tiles are marched into both, and the shift is set every frame from the eye the front map was marched from");
ok(/D\.addAssign\(t\.mul\(a\)\.mul\(T\)\)/.test(page) && /dist\.assign\(min\(float\(Clouds\.FAR\), select\(al\.greaterThan\(0\.001\), D\.div\(max\(al, 1e-6\)\), t0\.add\(t1\)\.mul\(0\.5\)\)\)\)/.test(page), "the GPU march sums the distance as the reference does and carries the middle of the stretch where no cloud is");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
