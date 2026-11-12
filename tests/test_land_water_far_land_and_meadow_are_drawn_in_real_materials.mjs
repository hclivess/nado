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
// never into the player: a block in their own space goes only at their feet, with room above, and lifts them onto it — no
// longer refused with a message ("only hinders", 2026-11-08); walked in test_a_block_goes_where_you_look…mjs
ok(/NATURAL_ITEMS\.has\(id\)[\s\S]{0,2000}!roomFor\(a\.prev\)( \|\| !rootsIn\(a\.prev\))?\) return;[\s\S]{0,300}setBlock[\s\S]{0,200}if \(lift\) \{ P\.h = ch \+ 1/.test(act)
   && /const roomFor = \(c\) => !inBody\(c\) \|\| \(c\[2\] < P\.h \+ FEET && !collides\(P\.u, P\.v, c\[2\] \+ 1\)\)/.test(land),
   "a natural block never goes into the player: at their feet it lifts them onto it, elsewhere in their body it is not placed");

// a flower, a pebble, flax under the aim are taken over by a placed block (land-world.js SWEPT), not climbed over — the
// world server picks them up into the bag (test_land_players_gather_make_tools_craft_and_trade.py)
const pc = land.slice(land.indexOf("function placeCell("), land.indexOf("function entryFace("));
ok(/Wd\.SWEPT\.has\(b\) && !!held && !Wd\.SWEPT\.has\(held\) && held !== B\.sapling/.test(pc), "a block aimed at loose litter takes its cell");
// …and the last resort is the cell right on top of the aimed one or nothing: it climbed two cells, and a sapling aimed at a
// flowery spot was outlined floating over the flower (found with /aim on the live page, 2026-11-08)
ok(/const top = \[hit\[0\], hit\[1\], hit\[2\] \+ 1\];\s*\/\/[^\n]*\n\s*return free\(top\) \? top : null;/.test(pc) && !/up <= 2/.test(pc),
   "a block never goes higher than the cell right on top of the one aimed at");

// a night you can find your way in: away from the lamps the ground measured 6 of 255 at night, all but black (live,
// 2026-11-08); moonlight and a blue sky fill brought the same view to 19
const skyFn = land.slice(land.indexOf("function sky("), land.indexOf("function sky(") + 3000);
// (the sky fill is scaled by what the clouds let through since #183 step 4a — (0.85 + 0.15 × cloudLitNow), never below 85 %)
ok(/moon\.intensity = 0\.9 \* \(1 - day\)/.test(skyFn) && /hemi\.intensity = \(1\.1 \+ 1\.1 \* day\) \* \(0\.85 \+ 0\.15 \* cloudLitNow\)/.test(skyFn)
   && /hemi\.color\.copy\(SKY\.moonFill\)\.lerp\(SKY\.horizon, day\)/.test(skyFn) && /moonFill: new THREE\.Color\(0x4a5f8a\)/.test(land),
   "night is lit by the moon and a blue sky fill, not left black");

// the page keeps what is left of a cut block (the server's vol) and drops a spent item from the hotbar (2026-11-08)
ok(land.includes("inv.vol = m.vol || {};") && /hot = hot\.filter\(\(id\) => placeable\(id\) && haveCm3\(id\) > 0\);/.test(land),
   "the page keeps the leftover volume and drops spent items from the hotbar");

// a plant in hand is outlined red (and not placed) unless earth or grass is under it — the world server's rule
// (land_server.py "a plant is planted in earth or grass"); it showed green floating over another flower (2026-11-08)
ok(/const rootsIn = [\s\S]{0,300}held !== B\.sapling && !Wd\.FLOWERS\.includes\(held\)[\s\S]{0,200}below === B\.grass \|\| below === B\.dirt/.test(land)
   && land.includes("const go = roomFor(a.prev) && rootsIn(a.prev)") && land.includes("!roomFor(a.prev) || !rootsIn(a.prev)) return;")
   && /a plant is planted in earth or grass/.test(readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8")),
   "a plant is outlined and placed only over earth or grass, as the world server rules");

// …and a cell a built piece reaches into is not empty: the page aims no block there (the server refuses one,
// test_built_pieces_are_any_size_from_a_centimetre_paid_by_volume.py)
ok(/&& !pieceIn\(q\);/.test(pc) && /function pieceIn\(\[u, v, h\]\)[\s\S]{0,400}Wd\.boxesOverlap\(cell, o\)/.test(land), "a cell a piece reaches into takes no block");

// litter catches the look only near its small model — low in its cell, near its middle — not across the whole metre: a
// pebble in front of a chest hid the chest (the factory walk, 2026-11-09)
ok(/if \(Wd\.LITTER\.has\(b\)\) \{ if \(p\[2\] - c\[2\] < LITTER_H && Math\.hypot\(p\[0\] - c\[0\] - 0\.5, p\[1\] - c\[1\] - 0\.5\) < LITTER_R\) hit = c; \}/.test(land)
   && /const LITTER_H = 0\.45, LITTER_R = 0\.42;/.test(land), "litter catches the look only near its model");

// 6: the finished picture is colour-graded ("we need professional color grading too"): S-curve, saturation, split toning,
// a vignette — after tone mapping, before anti-aliasing
const gr = land.slice(land.indexOf("function grade("), land.indexOf("function buildPipeline"));
ok(/sat:/.test(land) && /S-curve/.test(gr) && /GRADE\.cool/.test(gr) && /GRADE\.warm/.test(gr) && /vignette/.test(gr) && /fxaa\(grade\(TSL\.renderOutput\(lit\)\)\)/.test(land),
   "the picture is graded after tone mapping: an S-curve, saturation, cool shadows and warm highlights, a vignette");
// 5
ok(/#hudPlot\{display:flex;flex-wrap:wrap;align-items:center;gap:/.test(html), "the plot line is a wrapping row with gaps");

// GRASS AND EARTH ARE TRIPLANAR (#181 item 5): on a hillside the two layers take the rock's three projections, the side
// ones weighted by the face's turn from the sky, so a steep slope is not a texture stretched along it
const gmTri = land.slice(land.indexOf("function groundMaterial()"), land.indexOf("function groundMaterial()") + 3000);
ok(/const tri = \(t\) => TSL\.mix\(TSL\.texture\(t, near\)\.rgb\.mul\(tw\.z\)\.add\(TSL\.texture\(t, TSL\.vec2\(uvw\.y, uvw\.z\)\.div\(3\.2\)\)\.rgb\.mul\(tw\.x\)\)\.add\(TSL\.texture\(t, TSL\.vec2\(uvw\.x, uvw\.z\)\.div\(3\.2\)\)\.rgb\.mul\(tw\.y\)\)\.div\(tws\)/.test(gmTri)
   && /const color = tri\(tex\[0\]\)\.mul\(meadow\)\.mul\(w1\.x\)\.add\(tri\(tex\[1\]\)\.mul\(w1\.y\)\)/.test(gmTri), "grass and earth are blended from three projections by the ground normal, as the rock is");

// STARS ARE POINTS AT EVERY RESOLUTION (#181 item 9): a star's point size grows as the render resolution drops so it is
// never under two buffer pixels (the upscale split a sub-pixel star into a pair of dots), and the size follows the setting
ok(/const starPx = \(base\) => Math\.max\(base, \(base \+ 0\.6\) \/ \(basePR\(\) \* SET\.res \/ 100\)\);/.test(land) && /size: starPx\(1\.6\)/.test(land) && /size: starPx\(3\.2\)/.test(land)
   && /if \(k === "res"\) \{ renderer\.setPixelRatio\(basePR\(\) \* SET\.res \/ 100\); if \(stars\) stars\.material\.size = starPx\(1\.6\); if \(satPts\) satPts\.material\.size = starPx\(3\.2\); \}/.test(land),
   "a star is never under two buffer pixels: its point size grows as the render resolution drops, and follows the setting");

// (the verdict last: a pin added after it could never fail the test — the triplanar pin sat there for an hour, 2026-11-12)
if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
