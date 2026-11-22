// The land beyond the far ground is drawn out to the hills (2026-11-22, the Chlorophyll shot: the far ground ended 1.7 km
// off and past it was sky, where the reference's horizon is hills and forest in the haze; with the wilderness's rolling
// hills a tenth of the meadow views see hills past 1.7 km — test_the_wilderness_rolls_in_hills…).
//   1. a ring reaches past the far ground, to OUTER_R (3-3.95 km: beyond the far ground's 1.7 km, inside the camera's far
//      plane), and past OUTER_R it drops out of sight;
//   2. under the far ground it sinks, so the two never fight;
//   3. a forest stands at its canopy's height in the canopy's olive (the canopy tiles' own colour), the sea at the sea;
//   4. it is built with the far ground, placed with it every frame and shaded by the clouds.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const num = (re) => Number((page.match(re) || [])[1]);
const R = num(/OUTER_R = (\d+)/), STEP = num(/const OUTER_STEP = (\d+)/), SINK = num(/OUTER_SINK = (\d+);/), far = num(/new THREE\.PerspectiveCamera\(SET\.fov, innerWidth \/ innerHeight, [\d.]+, (\d+)\)/);
ok(R >= 3000 && R < far * 0.99 && R > 72 / 2 * 48, `the ring reaches ${R} m: past the far ground's ${72 / 2 * 48} m, inside the camera's far plane (${far} m)`);
ok(STEP > 48 && STEP <= 200 && /\(r > OUTER_R \? 400 : 0\)/.test(page), `one vertex every ${STEP} m, and past OUTER_R the ring drops out of sight`);
ok(SINK > 5 && /Math\.max\(Math\.abs\(du\), Math\.abs\(dv\)\) < inner \? OUTER_SINK : 0/.test(page), `under the far ground it sinks ${SINK} m`);
const canopyCol = (page.match(/m\.colorNode = shadeByClouds\(TSL\.vec3\(([\d., ]+)\)\.mul\(TSL\.attribute\("color", "vec3"\)\)\);/) || [])[1];
const forestCol = (page.match(/OUTER_COL = \{ forest: \[([\d., ]+)\]/) || [])[1];
ok(canopyCol && forestCol && canopyCol.replace(/\s/g, "") === forestCol.replace(/\s/g, ""), `a forest is the canopy's olive (${forestCol})`);
ok(/const kind = wet \? "sea" : can > 0 \? "forest"/.test(page) && /c\.height \+ can/.test(page), "a forest stands at its canopy's height, the sea at the sea");
ok(/buildOuter\(face, fu, fv\);\n\}/.test(page) && /\[farMesh, farSea, borderMesh, farBoxMesh, outerMesh\]/.test(page) && /matOuter\.colorNode = shadeByClouds\(/.test(page),
  "it is built with the far ground, placed with it every frame, and shaded by the clouds");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
