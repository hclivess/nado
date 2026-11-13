/*
 * test_the_clouds_cast_their_shadows_over_the_land_as_the_reference_lets_the_sun_through.mjs — #183 step 4 (the concept
 * picture: "soft long shadows", the far ground mottled; the game's light was "one value for the whole scene", the sun
 * dimmed for the player's own spot and nothing else). land.js now renders a CLOUD SHADOW MAP over the ground round the
 * player — each texel land-clouds.js sunLit at that ground point, marched on the GPU — and every lit material of the land
 * shades its colour by mix(1, lit, share), share the sun's part of the light on level ground. This pins the reference and
 * the page's text:
 *   1. the reference sunLit over the ground: under a heap the sun is let through much less than in the clear (< 0.5
 *      against 1), a point outside the layer's reach or with the sun under the horizon is 1, and the value is the
 *      two-term transmittance of the body's optical depth along the sun's ray (recomputed here);
 *   2. a shadow has an edge: along a line through the shade sunLit comes in runs (heaps) whose edges are sharp — the
 *      penumbra is the star's disc over the base's height, a few metres (land-cosmos.js angularRadius × BASE) — and
 *      never a kilometre of ramp;
 *   3. the page: the land's lit materials (the ground, the far ring, grass, flowers, bark, leaves, far trees, far pieces,
 *      built pieces) take shadeByClouds; its lookup is the eye-relative position plus the shift from the map's eye, over
 *      the map's span; the GPU march is the reference's (eight samples, K.deep, K.sigma, 0.65 e^-τ + 0.35 e^-τ/4, mu > 0.02,
 *      under the base); the sun's intensity carries no cloud factor any more; the share is D/(D+S) with the sun's height;
 *      the map is rendered every CLOUD_SHADOW_MS or an eighth of the span moved; the stats line counts the maps.
 * Run: node tests/test_the_clouds_cast_their_shadows_over_the_land_as_the_reference_lets_the_sun_through.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const C = await import(join(ROOT, "static", "land-clouds.js")), Cosmos = await import(join(ROOT, "static", "land-cosmos.js")), Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const norm = (v) => { const n = Math.hypot(...v); return v.map((x) => x / n); };
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// 1. the reference over the ground: a sun 42° up, a 6 km square of ground round a point on the sea's radius + 2 m
const vol = C.noiseVolume(), dr = [1, 0], up = [0, 1, 0];
const sunDir = norm([Math.sin(48 * Math.PI / 180), Math.cos(48 * Math.PI / 180), 0.2]);     // ~42° over the horizon at the origin
const ground = (x, z) => { const g = [x, C.RG + 2, z]; const r = Math.hypot(...g); return g.map((v) => v * (C.RG + 2) / r); };   // on the sphere
let shade = null, clear = null, lo = 1, hi = 0, n = 0;
for (let x = -3000; x <= 3000 && !(shade && clear); x += 120) for (let z = -3000; z <= 3000; z += 120) {
  const l = C.sunLit(vol, ground(x, z), sunDir, dr); n++; lo = Math.min(lo, l); hi = Math.max(hi, l);
  if (l < 0.5 && !shade) shade = { x, z, l };
  if (l > 0.999 && !clear) clear = { x, z, l };
}
ok(shade && clear, `over 6 km of ground the sun is let through from ${lo.toFixed(2)} (under a heap) to ${hi.toFixed(3)} (clear): shade at (${shade && shade.x}, ${shade && shade.z}), clear at (${clear && clear.x}, ${clear && clear.z})`);
{
  // recomputed: the body's optical depth along the sun's ray through the layer, K.deep per metre, times sigma
  const P = ground(shade.x, shade.z), r = Math.hypot(...P), mu = dot(P, sunDir) / r, sp = C.span(r, mu);
  const steps = 8, dt = (sp[1] - sp[0]) / steps;
  let tau = 0;
  for (let i = 0; i < steps; i++) { const t = sp[0] + dt * (i + 0.5); tau += C.body(vol, C.undrift([P[0] + sunDir[0] * t, P[1] + sunDir[1] * t, P[2] + sunDir[2] * t], dr)) * dt * C.K.deep; }
  tau *= C.K.sigma;
  ok(Math.abs(shade.l - (0.65 * Math.exp(-tau) + 0.35 * Math.exp(-tau * 0.25))) < 1e-9, `…and the value is the two-term transmittance of the body's optical depth along the sun's ray (τ ${tau.toFixed(2)} → ${shade.l.toFixed(3)})`);
  ok(C.sunLit(vol, [0, C.RT + 10, 0], up, dr) === 1 && C.sunLit(vol, ground(0, 0), norm([1, 0.01, 0]), dr) === 1, "over the layer's top, or with the sun at the horizon, the sun is let through whole (1)");
}
// 2. a shadow's edge: along 3 km of ground through the shade, the sun is let through in runs (heaps) with edges some tens
//    of metres wide — never a step within one texel's 10 m, never a kilometre of ramp, never one pall over the whole line
{
  const STEP = 10, line = []; for (let s = -1500; s <= 1500; s += STEP) line.push(C.sunLit(vol, ground(shade.x + s, shade.z), sunDir, dr));
  let jump = 0; for (let i = 1; i < line.length; i++) jump = Math.max(jump, Math.abs(line[i] - line[i - 1]));
  const runs = []; let start = -1;                                  // the contiguous stretches with less than 0.9 let through
  line.forEach((l, i) => { if (l < 0.9 && start < 0) start = i; if ((l >= 0.9 || i === line.length - 1) && start >= 0) { runs.push([start, i]); start = -1; } });
  const edges = [];                                                 // each run's leading edge: from the last ≥ 0.99 before it to its first < 0.6
  for (const [a] of runs) { let j = a; while (j > 0 && line[j - 1] < 0.99) j--; let k = a; while (k < line.length && line[k] >= 0.6) k++; if (j > 0 && k < line.length) edges.push((k - j) * STEP); }
  // a cumulus shadow's edge is SHARP: the penumbra is the star's disc projected over the base's height — 2 × its angular
  // radius (land-cosmos.js sunFrom) × BASE, a few metres — so a step of most of the light within one 10 m stride is the
  // reference being right, not coarse; what it must not do is ramp over a kilometre (a pall, not a heap)
  const penumbra = 2 * Cosmos.sunFrom(Wd.PLANET).angularRadius * C.BASE;
  ok(penumbra > 1 && penumbra < 20, `the penumbra of a heap's shadow is ${penumbra.toFixed(1)} m (the star's ${(2 * Cosmos.sunFrom(Wd.PLANET).angularRadius * 180 / Math.PI).toFixed(2)}° disc over the ${C.BASE.toFixed(0)} m base): an edge within a 10 m stride is right (the sharpest here ${jump.toFixed(2)} of the light in one stride)`);
  ok(edges.length >= 1 && edges.every((e) => e <= 800), `the shade's edges never ramp over a kilometre (${edges.join(", ")} m)`);
  const widths = runs.map(([a, b]) => (b - a) * STEP);
  ok(runs.length >= 1 && widths.some((w) => w >= 60 && w <= 2500) && !(runs.length === 1 && widths[0] >= 2990), `…and the shade comes in heaps along the line (${widths.join(", ")} m across), not one pall over all of it`);
}
// 3. the page carries it
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok((page.match(/shadeByClouds\(/g) || []).length >= 10, `the land's lit materials take shadeByClouds (${(page.match(/shadeByClouds\(/g) || []).length - 1} of them)`);
for (const [what, re] of [["the far ring's ground", /m\.colorNode = shadeByClouds\(color\.mul\(TSL\.attribute\("color", "vec3"\)\)\)/], ["the chunk ground", /m\.colorNode = shadeByClouds\(TSL\.texture\(col, uv\)\.rgb/], ["grass", /matGrass\.colorNode = shadeByClouds\(/], ["flowers", /matFlower\.colorNode = shadeByClouds\(/], ["bark", /bark\.colorNode = shadeByClouds\(/], ["leaves", /leaves\.colorNode = shadeByClouds\(/], ["built pieces", /matPieces\.colorNode = shadeByClouds\(/], ["far trees", /m\.colorNode = shadeByClouds\(s\.rgb\.mul\(TSL\.attribute\("color", "vec3"\)\)\)/], ["far pieces", /m\.colorNode = shadeByClouds\(TSL\.attribute\("col", "vec3"\)\)/]])
  ok(re.test(page), `…${what}`);
const fn = page.slice(page.indexOf("function shadeByClouds("), page.indexOf("function shadeByClouds(") + 700);
ok(/const d = TSL\.positionWorld\.add\(shadowO\.shift\);/.test(fn) && /TSL\.vec2\(TSL\.dot\(d, shadowO\.east\), TSL\.dot\(d, shadowO\.north\)\)\.div\(CLOUD_SHADOW_SPAN\)\.add\(0\.5\)/.test(fn) && /color\.mul\(TSL\.mix\(TSL\.float\(1\), n\.r, shadowO\.share\)\)/.test(fn),
  "the lookup is the eye-relative position plus the shift from the map's centre, east and north over the span; the colour times mix(1, lit, share)");
const gpu = page.slice(page.indexOf("const shadowFn = Fn("), page.indexOf("const shadowFn = Fn(") + 1600);
ok(/Loop\(8, /.test(gpu) && /\.mul\(dt\.mul\(K\.deep\)\)/.test(gpu) && /tau\.mulAssign\(K\.sigma\)/.test(gpu) && /exp\(tau\.negate\(\)\)\.mul\(0\.65\)\.add\(exp\(tau\.negate\(\)\.mul\(0\.25\)\)\.mul\(0\.35\)\)/.test(gpu) && /mu\.greaterThan\(0\.02\)\.and\(r\.lessThan\(Clouds\.RB\)\)/.test(gpu),
  "the GPU marches the reference's sunLit: eight samples of the body, K.deep, K.sigma, 0.65 e^-τ + 0.35 e^-τ/4, mu > 0.02, under the base");
ok(/const P = shadowU\.at\.add\(shadowU\.east\.mul\(uv\.x\.sub\(0\.5\)\.mul\(CLOUD_SHADOW_SPAN\)\)/.test(gpu) && /t0\.add\(K\.path\)/.test(gpu), "…at the ground point span·(uv − ½) east and north of the map's centre, the ray's stretch capped at K.path as span() caps it");
ok(/at = Wd\.posOf\(P\.face, P\.u, P\.v, colAt\(P\.face, Math\.floor\(P\.u\), Math\.floor\(P\.v\)\)\.height\);/.test(page) && /shadowU\.at\.value\.set\(at\[0\], at\[1\], at\[2\]\)/.test(page), "the map's centre is the GROUND under the player, never the eye (a pilot in the layer read full sun everywhere)");
ok(/sun\.intensity = 2\.4 \* Math\.min\(1\.6, star\.flux\) \* day;/.test(page) && !/sun\.intensity = [^\n]*cloudLitNow/.test(page), "the sun's intensity carries no cloud factor: the shade is per point now");
ok(/const D = sun\.intensity \* Math\.max\(0\.05, elev\), S = hemi\.intensity; shadowO\.share\.value = SET\.clouds && shadowCentre && day > 0 \? D \/ \(D \+ S\) : 0;/.test(page), "the share is the sun's irradiance on level ground against the sky's fill, 0 with the clouds off or before a map");
ok(/performance\.now\(\) - shadowAt > CLOUD_SHADOW_MS \|\| Math\.hypot\(cam\[0\] - shadowCentre\[0\], cam\[1\] - shadowCentre\[1\], cam\[2\] - shadowCentre\[2\]\) > CLOUD_SHADOW_SPAN \/ 8/.test(page) && /shadowU\.sunDir\.value\.copy\(cloudLit\.sd\); shadowU\.dr\.value\.set\(dr\[0\], dr\[1\]\);/.test(page),
  "the map is rendered every CLOUD_SHADOW_MS or an eighth of its span moved, at the frame's sun and drift");
ok(/shadowO\.shift\.value\.set\(cam\[0\] - shadowCentre\[0\]/.test(page) && /\$\{shadowMaps\} shadow maps/.test(page), "the shift is set every frame from the map's centre, and the stats line counts the maps");
ok(/const CLOUD_SHADOW_N = 256, CLOUD_SHADOW_SPAN = 6000, CLOUD_SHADOW_MS = 1500;/.test(page), "256 texels over 6 km (23 m a texel, under a heap's 150 m), a map every 1.5 s");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
