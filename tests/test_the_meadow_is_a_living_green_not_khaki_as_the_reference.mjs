/*
 * test_the_meadow_is_a_living_green_not_khaki_as_the_reference.mjs — "match the graphical fidelity" (the operator's goal;
 * the live vale beside the Chlorophyll shot, 2026-11-24): every band of our meadow — the grass underfoot, the middle
 * distance, the far slope — read red 0.90-0.94 of its green (hue 66-70°), against the reference's 0.82-0.84 (74-76°) at
 * every distance: khaki, not a living green. After, at the same held moment: 0.80, 0.90, 0.83. From the page's own paints:
 *   1. a grass blade's paint (grassCardTexture) holds red at most 0.86 of its green;
 *   2. the meadow ground's two ends (lush, dry) hold red at most 0.86 of their green — the dry end is no yellow;
 *   3. the far meadow's tint (GREEN FROM AFAR) adds no red over the near: a far slope stays as green as the near one.
 * Run: node tests/test_the_meadow_is_a_living_green_not_khaki_as_the_reference.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const MAX = 0.86;                                         // the reference's 0.82-0.84, with a little room
// 1
const blade = /g\.fillStyle = `rgb\(\$\{Math\.round\(255 \* L \* ([\d.]+)\)\}, \$\{Math\.round\(255 \* L\)\}, \$\{Math\.round\(255 \* L \* ([\d.]+)\)\}\)`;/.exec(page);
ok(blade && Number(blade[1]) <= MAX, `a grass blade's paint holds red ${blade && blade[1]} of its green (at most ${MAX})`);
// 2
const ends = /const meadow = TSL\.mix\(TSL\.vec3\(([\d.]+), ([\d.]+), ([\d.]+)\), TSL\.vec3\(([\d.]+), ([\d.]+), ([\d.]+)\), patch\)/.exec(page);
const lush = ends && Number(ends[1]) / Number(ends[2]), dry = ends && Number(ends[4]) / Number(ends[5]);
ok(ends && lush <= MAX && dry <= MAX, `the meadow ground's ends hold red ${lush && lush.toFixed(2)} (lush) and ${dry && dry.toFixed(2)} (dry) of their green`);
// 3
const far = /TSL\.mix\(TSL\.vec3\(1, 1, 1\), TSL\.vec3\(([\d.]+), ([\d.]+), ([\d.]+)\), TSL\.smoothstep\(80, 500,/.exec(page);
ok(far && Number(far[1]) <= 1 && Number(far[2]) >= Number(far[1]), `the far meadow's tint adds no red (red x${far && far[1]}, green x${far && far[2]})`);
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
