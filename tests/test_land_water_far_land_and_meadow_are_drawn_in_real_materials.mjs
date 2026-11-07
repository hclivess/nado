/*
 * test_land_water_far_land_and_meadow_are_drawn_in_real_materials.mjs — what a player sees past their feet
 * ("did you fix the bland untextured marches?", "what is this spacing?", "it is possible to build oneself into the
 * terrain", operator 2026-11-06):
 *   1. the sea is its own part (`water`), with world coordinates for its ripples — not an atlas tile in `clear`;
 *   2. the page draws water in a material of its own (moving ripples, fresnel to the sky's colour, kept in step with it),
 *      and the far land in the ground's material with the six texture weights (no flat vertex colour), its sea in water;
 *   3. the meadow's colour varies over tens of metres (it read as one pale wash from above);
 *   4. a natural block is refused where it would raise the ground into the player;
 *   5. the plot line under the position is a wrapping row with gaps (a long translation jammed its button into the text).
 *
 * Run: node tests/test_land_water_far_land_and_meadow_are_drawn_in_real_materials.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1: find the sea: a column below SEA, scanning out along a face row
let sea = null;
for (let u = 0; u < Wd.W && !sea; u += 977) for (let v = 0; v < Wd.W && !sea; v += 1013) { const c = Wd.column(0, u, v); if (c.top < Wd.SEA - 3) sea = { u, v }; }
ok(!!sea, "the planet has a sea");
const r = M.meshChunk(0, Math.floor(sea.u / 16), Math.floor(sea.v / 16), Math.floor(Wd.SEA / 16), null, null, 0);
ok(r.water && r.water.uvw && r.water.uvw.length === r.water.pos.length, "the sea surface is its own part, with world coordinates for every vertex");
const clearHasSea = r.clear && r.clear.pos.length > 0;
ok(!clearHasSea, "and none of it is drawn as an atlas tile among glass and ice");

// 2, 3, 4: the page
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
const wm = land.slice(land.indexOf("function waterMaterial"), land.indexOf("function treeMaterials"));
ok(/mx_noise_vec3/.test(wm) && /TSL\.time/.test(wm) && /uniform\(waterSky\)/.test(wm) && /waterSky\.copy\(hor\)/.test(land),
   "water has moving ripples and a fresnel to the sky, whose colour follows the horizon");
ok(/if \(m\.water\)[^\n]*matWater/.test(land), "the page draws the water part in the water material");
const far = land.slice(land.indexOf("function buildFar"), land.indexOf("// ---- titles"));
ok(/new THREE\.Mesh\(g, matGround\)/.test(far) && /groundWeights\(/.test(far) && /"w1"/.test(far) && /"w2"/.test(far) && !/vertexColors: true/.test(far),
   "the far land is drawn in the ground's material with the six texture weights, not flat vertex colour");
ok(/new THREE\.Mesh\(gs, matWater\)/.test(far), "and the far sea in the water material");
const gm = land.slice(land.indexOf("function groundMaterial"), land.indexOf("// ---- grass:"));
ok(/mx_noise_float\(uvw\.xy\.mul\(0\.021\)\)/.test(gm) && /meadow/.test(gm), "the meadow's colour varies over tens of metres");
const act = land.slice(land.indexOf("function act("), land.indexOf("function wireInput"));
ok(/NATURAL_ITEMS\.has\(id\)[\s\S]{0,2000}noRoomYou[\s\S]{0,600}setBlock/.test(act), "a natural block is refused where it would raise the ground into the player");

// 6: the finished picture is colour-graded ("we need professional color grading too"): S-curve, saturation, split toning,
// a vignette — after tone mapping, before anti-aliasing
const gr = land.slice(land.indexOf("function grade("), land.indexOf("function buildPipeline"));
ok(/sat:/.test(land) && /S-curve/.test(gr) && /GRADE\.cool/.test(gr) && /GRADE\.warm/.test(gr) && /vignette/.test(gr) && /fxaa\(grade\(TSL\.renderOutput\(lit\)\)\)/.test(land),
   "the picture is graded after tone mapping: an S-curve, saturation, cool shadows and warm highlights, a vignette");
// 5
ok(/#hudPlot\{display:flex;flex-wrap:wrap;align-items:center;gap:/.test(html), "the plot line is a wrapping row with gaps");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
