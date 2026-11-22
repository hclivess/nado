/*
 * test_the_forest_reads_dark_green_as_the_reference.mjs — the Chlorophyll bar (operator 2026-11-21): its forest measures
 * rgb (44, 56, 30); ours, photographed under a clear sun 2026-11-22, read pale lime (64, 96, 61) — broadleaf leaves painted
 * at 30-44 % lightness, birch 34-48 %, and the far cards baked under a hemisphere light of 2.6 and then lit again in the
 * scene. Read from static/land.js:
 *   1. the broadleaf leaves are painted no lighter than 34 %, the birch no lighter than 40 % (paintLeaves);
 *   2. the far trees' pictures are baked under a light below 2 (bakeForest), so the scene's own light is the one that shows.
 * Run: node tests/test_the_forest_reads_dark_green_as_the_reference.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const page = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const pl = page.slice(page.indexOf("function paintLeaves"), page.indexOf("// 2: needle spray", page.indexOf("function paintLeaves")));
const ls = [...pl.matchAll(/l = (\d+) \+ R\(\) \* (\d+)/g)].map((m) => Number(m[1]) + Number(m[2]));
ok(ls.length >= 2 && ls[0] <= 34 && ls[1] <= 40, `broadleaf leaves at most ${ls[0]} % light, birch at most ${ls[1]} % (were 44 and 48)`);
const bake = page.slice(page.indexOf("async function bakeForest"), page.indexOf("async function bakeForest") + 1500).match(/HemisphereLight\(0x[0-9a-f]+, 0x[0-9a-f]+, ([\d.]+)\)/);
ok(bake && Number(bake[1]) < 2, `the far trees' pictures are baked under a light of ${bake && bake[1]} (was 2.6: lit twice, they read pale)`);
// 3. under the sky's blue fill the far cards and the canopy read grey-green (72, 86, 76): both carry almost no blue
ok(page.includes("m.colorNode = shadeByClouds(s.rgb.mul(TSL.attribute(\"color\", \"vec3\")).mul(TSL.vec3(1.45, 1.1, 0.65)));"),
  "the far cards' pictures are warmed toward olive (red x1.45, blue x0.65), measured against the reference with the clouds off");
const cv = page.match(/m\.colorNode = shadeByClouds\(TSL\.vec3\(([\d.]+), ([\d.]+), ([\d.]+)\)\.mul\(TSL\.attribute\("color", "vec3"\)\)\);/);
ok(cv && Number(cv[3]) < Number(cv[2]) * 0.2 && Number(cv[1]) <= Number(cv[2]), `the canopy is a dark olive with almost no blue (${cv && cv.slice(1).join(", ")})`);
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
