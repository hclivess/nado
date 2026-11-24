/*
 * test_a_far_forest_is_matte_foliage_not_a_grey_veil.mjs — "match the graphical fidelity" (the operator's goal; the live
 * vale beside the Chlorophyll shot, 2026-11-24): with a standard material's specular the far forest wore a white veil —
 * toward the sun a pale grey wall, and front-lit (65, 79, 56), saturation 16, against the reference's (46, 58, 36), 24;
 * diffuse only it measured (47, 64, 36), saturation 28, at the same held moment (land.js bakeForest):
 *   1. the far cards' material is diffuse only (Lambert): no specular term at all;
 *   2. with the same collapse onto a meshed chunk's root, the same colour (the under-canopy shade, the cloud shadow) and
 *      the same cut-out shadow.
 * Run: node tests/test_a_far_forest_is_matte_foliage_not_a_grey_veil.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const mat = page.slice(page.indexOf("async function bakeForest()"), page.indexOf("function forestDone("));
const after = mat.slice(mat.indexOf("ensureSeen();"));
ok(/const m = new THREE\.MeshLambertNodeMaterial\(\{ alphaTest: 0\.4 \}\)/.test(after) && !/MeshStandardNodeMaterial/.test(after),
  "1. the far cards' material is diffuse only (Lambert): no specular veil");
ok(/m\.positionNode = TSL\.positionLocal\.add\(TSL\.attribute\("off", "vec3"\)\.mul\(show\)\)/.test(after) && /m\.colorNode = shadeByClouds\(underShade\)/.test(after)
  && /m\.opacityNode = s\.a;/.test(after) && /m\.maskShadowNode = s\.a\.greaterThan\(0\.4\)/.test(after) && /matForest = m;/.test(after),
  "2. …with the same collapse onto a meshed chunk's root, the same colour and the same cut-out shadow");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
