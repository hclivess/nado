/*
 * test_the_air_is_clear_near_and_hazy_far_as_the_reference_meadow.mjs — the Chlorophyll bar (operator 2026-11-21): a
 * linear fog from the view's edge to 2.9 km was 32 % thick at 1 km, and the forest band read a pale blue-grey (77, 100,
 * 81) where the reference's distant forest is dark green (44, 56, 30). The haze is now squared-exponential:
 *   1. scene.fog is a FogExp2 at HAZE_DENSITY, and nothing still sets a linear fog's near (it has none);
 *   2. as three computes it (1 - exp(-(d·x)²)): clear near (under 2 % at 300 m), under an eighth at 1 km (the far forest
 *      stays dark green, measured live), a fifth or so at the far ground's edge (1.7 km), and well into the sky colour by 2.9 km.
 * Run: node tests/test_the_air_is_clear_near_and_hazy_far_as_the_reference_meadow.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const page = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const d = Number((page.match(/const HAZE_DENSITY = ([\d.]+);/) || [])[1]);
ok(page.includes("scene.fog = new THREE.FogExp2(0xb7d6ef, HAZE_DENSITY);") && !/scene\.fog\.near/.test(page) && !/new THREE\.Fog\(/.test(page),
  "the haze is a FogExp2 at HAZE_DENSITY, and no linear fog or its near is left");
const f = (x) => 1 - Math.exp(-((d * x) ** 2));
ok(f(300) < 0.02 && f(1000) > 0.04 && f(1000) < 0.12 && f(1700) > 0.12 && f(1700) < 0.3 && f(2900) > 0.35,
  `clear near, hazy far: ${[300, 1000, 1700, 2900].map((x) => x + " m " + Math.round(100 * f(x)) + " %").join(", ")}`);
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
