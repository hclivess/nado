// A WOOD'S FLOOR IS LEAF LITTER, NOT THE MEADOW'S GRASS.
//
// Operator 2026-11-25: trees "2002 garbage", "yours looks like some fucking Nintendo ripoff". Under the canopy the ground was the
// meadow's grass scan tinted meadow-green — a flat olive under the trunks. A seventh ground texture, "forest" (Poly Haven
// forest_floor, CC0; tools/land_textures.py), is the floor of a wood: land-mesher groundWeights takes the ground's forest share
// (forestFloor: a forest column's woods field, 1 inside a wood, fading across its edge) from the grass. Pinned:
//   1. groundWeights: with no forest the weights are as they were; under a wood the grass's share becomes the floor's;
//      a cliff stays rock; the weights sum to one;
//   2. the mesher hands the floor's weight on (w2 has three) and reads it from the column; the far land writes 0 there;
//   3. the page loads "forest" with the ground, reads w2 as three, and draws the floor in the canopy's shade.
//
// Run: node tests/test_a_woods_floor_is_leaf_litter_not_the_meadows_grass.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const M = await import(join(ROOT, "static", "land-mesher.js")), W = await import(join(ROOT, "static", "land-world.js"));
const near = (a, b) => a.every((x, i) => Math.abs(x - b[i]) < 1e-9);

// 1
const flat0 = M.groundWeights(W.B.grass, 1), flat1 = M.groundWeights(W.B.grass, 1, 1), half = M.groundWeights(W.B.grass, 1, 0.5);
ok(flat0.length === 7 && near(flat0, [1, 0, 0, 0, 0, 0, 0]), "open grass is grass (no forest share)");
ok(near(flat1, [0, 0, 0, 0, 0, 0, 1]), "under a wood the grass's share is the wood's floor");
ok(Math.abs(half[0] - 0.5) < 1e-9 && Math.abs(half[6] - 0.5) < 1e-9, "…half way across a wood's edge, half and half");
const cliff = M.groundWeights(W.B.grass, 0.2, 1);
ok(cliff[2] > 0.99, `a cliff under a wood is rock (${cliff[2].toFixed(2)})`);
ok([flat0, flat1, half, cliff, M.groundWeights(W.B.sand, 1, 1)].every((w) => Math.abs(w.reduce((a, x) => a + x, 0) - 1) < 1e-9)
  && M.groundWeights(W.B.sand, 1, 1)[6] === 0, "the weights sum to one, and only grass gives way to the floor");

// 2
const mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8"), far = readFileSync(join(ROOT, "static", "land-far.js"), "utf8");
ok(/o\.w2\.push\(w\[4\], w\[5\], w\[6\]\);/.test(mesher) && /groundWeights\(mat, nh, mat === B\.grass \? forestFloor\(gu, gv\) : 0\)/.test(mesher)
  && /f = c\.biome === "forest" \? smoothstep\(0\.12, 0\.3, c\.woods\) : 0;/.test(mesher), "the mesher reads the floor from the column's woods and hands it on (w2 has three)");
ok(/w2 = new Float32Array\(V \* 3\)/.test(far) && /w2\.set\(wt\.slice\(4\), k \* 3\);/.test(far), "the far land's ground carries the same three (its floor 0: a far wood hides it)");

// 3
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok(/const GROUND = \["grass", "dirt", "rock", "sand", "snow", "gravel", "forest"\];/.test(page)
  && /TSL\.attribute\("w2", "vec3"\)/.test(page) && (page.match(/new THREE\.BufferAttribute\((?:part|r)\.w2, 3\)/g) || []).length === 2,
  "the page loads the floor with the ground and reads w2 as three, near and far");
ok(/\.add\(tri\(tex\[6\]\)\.mul\(underBlades\)\.mul\(w2\.z\)\)/.test(page) && /GROUND_ROUGH = \[[^\]]*, 0\.95\]/.test(page),
  "the floor is drawn in the canopy's shade, rough as earth");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
