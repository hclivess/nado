/*
 * test_the_tris_command_counts_the_frames_triangles_by_what_draws_them.mjs — #150 (the stats line gave one number —
 * 557k–638k triangles at the landing on Low, playtest 2026-11-11 — and nothing to cut from it). static/land.js read as
 * text: the /tris console command walks the scene, counts every drawn mesh's triangles (index or positions over three,
 * times its instance count), names the count by the material that draws it — ground, trees, bark, foliage, blocks,
 * pieces, water, grass, flowers, far trees, flames — or by the people's and far boxes' own meshes, and lists them largest
 * first under a total; hidden objects are left out; the header is in all 17 languages.
 * Run: node tests/test_the_tris_command_counts_the_frames_triangles_by_what_draws_them.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
// (the naming of a mesh is drawKind, shared by /tris and /draws since #139: read with the command)
const kindFn = land.slice(land.indexOf("function drawKind() {"), land.indexOf("function drawKind() {") + 1800);
const cmd = land.slice(land.indexOf("  tris: () => {"), land.indexOf("  prof: () => {")) + kindFn;
ok(cmd.length > 200, "the /tris console command exists");
ok(["matGround", "matTrees", "matBark", "matLeaves", "matSolid", "matClear", "matPieces", "matGlassy", "matWater", "matGrass", "matFlower", "matForest", "matFlame"].every((m) => cmd.includes(`[${m}, "`)), "it names a count by every material the page draws with");
ok(/per = \(g\.index \? g\.index\.count : g\.attributes\.position \? g\.attributes\.position\.count : 0\) \/ 3;/.test(cmd) && /const inst = g\.instanceCount !== undefined && g\.instanceCount !== Infinity \? g\.instanceCount : o\.count !== undefined \? o\.count : 1;/.test(cmd), "a mesh's triangles are its index (or positions) over three, times its instances");
ok(/while \(p\) \{ if \(!p\.visible\) \{ shown = false; break; \} p = p\.parent; \}/.test(cmd), "a hidden object, or one under a hidden parent, is left out");
ok(/if \(q\.userData && q\.userData\.person\) \{ k = "people"; break; \}/.test(cmd) && /g\.userData\.person = true;\s+[^\n]*\n\s+return g;/.test(land) && /o === farBoxMesh\) k = "far boxes";/.test(cmd), "the people (every mesh under a figure the page marks as a person) and the far boxes are named by their own meshes");
ok(/\.sort\(\(a, b\) => b\[1\] - a\[1\]\)/.test(cmd) && /conLine\(T\("cTris", "[^"]*\{n\}[^"]*", \{ n: Math\.round\(total \/ 1000\) \}\)\);/.test(cmd), "largest first, under a total in thousands");
ok(Object.keys(I).length === 17 && Object.keys(I).every((l) => typeof I[l]["land.cTris"] === "string" && I[l]["land.cTris"].includes("{n}")), "the header is in all 17 languages with the count");
// /lod (#150): the loaded chunks by level, with the bark and foliage triangles each level's meshes carry
const lodc = land.slice(land.indexOf("  lod: () => {"), land.indexOf("  prof: () => {"));
ok(lodc.length > 100 && /for \(const c of chunks\.values\(\)\) \{/.test(lodc) && /const l = c\.lod \?\? -1/.test(lodc) && /if \(m\.material === matBark\) e\.bark \+= n; else if \(m\.material === matLeaves\) e\.leaves \+= n;/.test(lodc) && /conLine\(T\("cLod", /.test(lodc), "/lod counts the loaded chunks by level and sums their bark and foliage triangles");
ok(Object.keys(I).every((l) => typeof I[l]["land.cLod"] === "string" && I[l]["land.cLod"].length > 10), "its header is in all 17 languages");

// /draws (#139: "433 draw calls a frame on a phone", nothing said which): the next frame's real draw calls by kind
const dr = land.slice(land.indexOf("  draws: () => {"), land.indexOf("  lod: () => {"));
ok(/const kindOf = drawKind\(\)/.test(dr) && /const kindOf = drawKind\(\)/.test(cmd), "/draws names its kinds as /tris does (one drawKind)");
ok(/o\.onBeforeRender = function \(r, sc, cam, \.\.\.rest\) \{/.test(dr) && /return was\.call\(this, r, sc, cam, \.\.\.rest\);/.test(dr) && /for \(const \[o, was\] of hooked\) o\.onBeforeRender = was;/.test(dr),
  "it counts where three draws (each object's onBeforeRender, called by renderObject for every pass), passes the call on, and puts every hook back after the frame");
ok(/renderObject\( object, scene, camera, geometry, material, group, lightsNode[^)]*\) \{[\s\S]{0,600}object\.onBeforeRender\( this, scene, camera, geometry, material, group \);/.test(readFileSync(join(ROOT, "static", "vendor", "three", "three.webgpu.js"), "utf8")),
  "…which the vendored three does call for each object it draws");
ok(/const k = kindOf\(o, rest\[1\] \|\| o\.material\)/.test(dr) && /return \(o, mat = o\.material\) => \{/.test(kindFn) && /m\.name = "piece " \+ \(spec \? spec\[0\]/.test(land), "a mesh with a list of materials is counted by the material each draw uses (a chunk's pieces draw once a material), each piece material named by its texture");
ok(/sh = cam !== camera;/.test(dr) && /conLine\(T\("cDraws", "[^"]*\{n\}[^"]*\{m\}[^"]*\{s\}[^"]*", \{ n: main \+ shadow, m: main, s: shadow \}\)\);/.test(dr), "the view's draws are told apart from the shadows' (any camera but the player's), under a total");
ok(Object.keys(I).length === 17 && Object.keys(I).every((l) => ["{n}", "{m}", "{s}"].every((x) => (I[l]["land.cDraws"] || "").includes(x))), "its header is in all 17 languages with the three counts");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
