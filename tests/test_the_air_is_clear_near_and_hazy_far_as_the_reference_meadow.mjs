/*
 * test_the_air_is_clear_near_and_hazy_far_as_the_reference_meadow.mjs — the Chlorophyll bar (operator 2026-11-21): a
 * linear fog from the view's edge to 2.9 km was 32 % thick at 1 km, and the forest band read a pale blue-grey (77, 100,
 * 81) where the reference's distant forest is dark green (44, 56, 30). Then a squared exponential, tuned at 1 km — and
 * 98 % thick by 6 km, where the distant land (land-far.js, "very stupid and short", operator 2026-11-23) has to show.
 * The haze is now scene.fogNode = hazeFactor(): optical depth HAZE_K d² / (HAZE_D0 + d), thinning with height:
 *   1. the page sets scene.fogNode from hazeFactor, and nothing still sets a linear fog's near;
 *   2. at the ground: clear near (under 2 % at 300 m), under an eighth at 1 km (the far forest stays dark green, the tune
 *      measured live 2026-11-22), 12-30 % at the far ground's edge (1.7 km);
 *   3. …and the distant land shows through it: under 60 % at 5 km, under 85 % at 10 km, under 97 % at 20 km;
 *   4. from 1,000 m up a sight line 10 km long is clearer than from the ground.
 * Run: node tests/test_the_air_is_clear_near_and_hazy_far_as_the_reference_meadow.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const page = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const m = page.match(/const HAZE_K = ([\d.]+), HAZE_D0 = (\d+), HAZE_H = (\d+), HAZE_FLOOR = (\d+);/);
ok(!!m && page.includes('scene.fogNode = TSL.fog(TSL.reference("color", "color", scene.fog), hazeFactor());') && !/scene\.fog\.near/.test(page) && !/new THREE\.Fog\(/.test(page),
  "the haze is scene.fogNode from hazeFactor, and no linear fog or its near is left");
// the factor as hazeFactor writes it: the sight line's mean height over the sea against HAZE_FLOOR and HAZE_H
// (plus a band that fades in from HAZE_MID_FROM to HAZE_MID_TO and then stays — "a little haze past 500 m", operator 2026-11-25)
const mid = page.match(/const HAZE_MID = ([\d.]+), HAZE_MID_FROM = (\d+), HAZE_MID_TO = (\d+);/);
const [MID, MID0, MID1] = mid ? mid.slice(1).map(Number) : [0, 1, 2];
ok(/d\.mul\(d\)\.div\(d\.add\(HAZE_D0\)\)\.mul\(HAZE_K\)\.add\(TSL\.smoothstep\(HAZE_MID_FROM, HAZE_MID_TO, d\)\.mul\(HAZE_MID\)\)\.mul\(thin\)\.negate\(\)\.exp\(\)\.oneMinus\(\)/.test(page) && !!mid
  && /hazeCam\.h\.add\(hFrag\)\.mul\(0\.5\)\.sub\(HAZE_FLOOR\)\.max\(0\)\.div\(HAZE_H\)\.negate\(\)\.exp\(\)/.test(page), "the factor is the optical depth K d²/(D0 + d), thinned with height");
const [K, D0, HH, FLOOR] = m.slice(1).map(Number);
const sst = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const f = (d, hEye = 50, hFar = 50) => 1 - Math.exp(-(K * d * d / (D0 + d) + MID * sst(MID0, MID1, d)) * Math.exp(-Math.max(0, (hEye + hFar) / 2 - FLOOR) / HH));
const pc = (x) => Math.round(100 * x) + " %";
// (1 km: 6.5 % until 2026-11-25; the shot's woods a few hundred metres off wear a light blue cast, so a light one here)
ok(f(300) < 0.02 && f(1000) > 0.08 && f(1000) < 0.18 && f(1700) > 0.12 && f(1700) < 0.3,
  `at the ground, clear near and a light cast on the forest at 1 km: ${[300, 1000, 1700].map((x) => x + " m " + pc(f(x))).join(", ")}`);
ok(f(5000) < 0.6 && f(10000) < 0.85 && f(20000) < 0.97 && f(20000) > 0.6,
  `…and the distant land shows in the haze: ${[5000, 10000, 20000].map((x) => x / 1000 + " km " + pc(f(x))).join(", ")}`);
ok(f(10000, 1000, 50) < f(10000) - 0.1, `from 1,000 m up, 10 km of air is ${pc(f(10000, 1000, 50))} against ${pc(f(10000))} at the ground`);
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
