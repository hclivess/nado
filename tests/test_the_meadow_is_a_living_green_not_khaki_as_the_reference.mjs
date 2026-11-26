/*
 * test_the_meadow_is_a_living_green_not_khaki_as_the_reference.mjs — "match the graphical fidelity" (the operator's goal;
 * the live vale beside the Chlorophyll shot, 2026-11-24): every band of our meadow — the grass underfoot, the middle
 * distance, the far slope — read red 0.90-0.94 of its green (hue 66-70°), against the reference's 0.82-0.84 (74-76°) at
 * every distance: khaki, not a living green. After, at the same held moment: 0.80, 0.90, 0.83. From the page's own paints:
 *   1. a grass blade's paint (grassCardTexture) holds red at most 0.86 of its green;
 *   2. the meadow ground's two ends (lush, dry) hold red at most 0.80 of their green — the scanned grass under them adds
 *      red, and the strip past the blades read 0.90 until they did;
 *   3. the far meadow's tint (GREEN FROM AFAR) adds no red over the near: a far slope stays as green as the near one;
 *   4. the grass is dark to the ground: blades no lighter than 0.10-0.40, the ground under them in their shade.
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
// (at most 0.80, below the blades' 0.86: the ground under this tint is the scanned grass, brown and red-heavy — past the
// blades' reach the strip read red 0.90 of its green at ends of 0.85, 0.87 at 0.80, and 0.85, the reference's middle
// meadow, at 0.76 and 0.75, 2026-11-24)
const GROUND_MAX = 0.80;
ok(ends && lush <= GROUND_MAX && dry <= GROUND_MAX, `the meadow ground's ends hold red ${lush && lush.toFixed(2)} (lush) and ${dry && dry.toFixed(2)} (dry) of their green (at most ${GROUND_MAX}: the scan under them adds red)`);
// 3
const far = /TSL\.mix\(TSL\.vec3\(1, 1, 1\), TSL\.vec3\(([\d.]+), ([\d.]+), ([\d.]+)\), TSL\.smoothstep\(80, 500,/.exec(page);
ok(far && Number(far[1]) <= 1 && Number(far[2]) >= Number(far[1]), `the far meadow's tint adds no red (red x${far && far[1]}, green x${far && far[2]})`);
// 4. DARK TO THE GROUND (2026-11-24): in one picture the reference's grass underfoot is 0.56 as light as its middle meadow,
// ours read 0.81 (0.62 after) — a ratio in one picture holds whatever the sun's height. The blades' paint is no lighter
// than 0.10 at the root and 0.40 at the tip, and the meadow ground under them is in their shade (UNDER_BLADES) where the
// blades are drawn (grassShade, 0 with the grass off: a page without blades keeps its ground lit)
const paint = /const L = ([\d.]+) \+ ([\d.]+) \* t1 \*\* 0\.8;/.exec(page);
ok(paint && Number(paint[1]) <= 0.1 && Number(paint[1]) + Number(paint[2]) <= 0.4, `4. a blade runs from ${paint && paint[1]} at the root to ${paint && (Number(paint[1]) + Number(paint[2])).toFixed(2)} at the tip`);
const ub = /const UNDER_BLADES = ([\d.]+);/.exec(page);
ok(ub && Number(ub[1]) < 0.8 && /const underBlades = TSL\.mix\(TSL\.float\(1\), TSL\.mix\(TSL\.float\(UNDER_BLADES\), TSL\.float\(1\), TSL\.smoothstep\(30, 56, [^)]*\)\.length\(\)\)\), grassShade\);/.test(page)
  && /const color = tri\(tex\[0\]\)\.mul\(meadow\)\.mul\(underBlades\)/.test(page), `…the meadow ground under the blades takes ${ub && ub[1]} of the light, back to full past their reach`);
ok(/grassShade\.value = SET\.grass \? 1 : 0;\s+\/\/[^\n]*\n\s+matGround = groundMaterial\(\);/.test(page) && /if \(k === "grass"\) \{ grassShade\.value = SET\.grass \? 1 : 0;/.test(page),
  "…only where blades are drawn: set at start and with the grass setting");
// PAST THE BLADES, NOT A LIME LAWN (2026-11-26, the vale beside the Chlorophyll shot): the open meadow past the grass
// measured (114, 138, 51) against the reference's (92, 110, 42), with half its fine texture; with the base at 0.70 (was
// 0.82), tussocks of 3 m at ±11 % and 1.1 m at ±7 % (was one at ±6 %) and the far green 0.84, 1.55, 0.78 (was 0.98,
// 1.8, 0.9 — the same hue), it measured (100, 124, 45) and the near grass (53, 67, 23) unchanged
{
  const base = /\.mul\(TSL\.float\(([\d.]+)\)\.add\(TSL\.mx_noise_float\(uvw\.xy\.mul\(0\.31\)\)\.mul\(([\d.]+)\)\)\.add\(TSL\.mx_noise_float\(uvw\.xy\.mul\(0\.9\)\)\.mul\(([\d.]+)\)\)\)/.exec(page);
  ok(base && +base[1] <= 0.74 && +base[2] >= 0.18 && +base[3] >= 0.1,
    `the open meadow is darker than the lime lawn it was, tussocked at two sizes (base ${base && base[1]}, ±${base && base[2] / 2} at 3 m, ±${base && base[3] / 2} at 1.1 m)`);
  const fg = /TSL\.vec3\(([\d.]+), ([\d.]+), ([\d.]+)\), TSL\.smoothstep\(80, 500/.exec(page);
  ok(fg && +fg[2] <= 1.6 && Math.abs(+fg[1] / +fg[2] - 0.98 / 1.8) < 0.02 && Math.abs(+fg[3] / +fg[2] - 0.9 / 1.8) < 0.02,
    `…and its far green no brighter, at the hue it had (${fg && fg.slice(1).join(", ")})`);
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
