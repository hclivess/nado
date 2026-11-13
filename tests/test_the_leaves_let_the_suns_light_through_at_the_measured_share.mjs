/*
 * test_the_leaves_let_the_suns_light_through_at_the_measured_share.mjs — #183 step 4 ("leaves lit through (translucency)
 * instead of black cores"). land.js treeMaterials: a leaf card emits the sun's light coming THROUGH it, in its own colour,
 * at LEAF_THROUGH of what a front-lit leaf reflects — where the sun strikes the card squarely and the viewer looks toward
 * the sun through it — under the cloud shadow as its reflected light is. The share is from sources, not memory: a leaf
 * absorbs ~85 % of the light between 400 and 700 nm (Golden Delicious sun and shade leaves, mean absorptance > 85 %),
 * reflects ~10 %, and whole apple leaves let up to 2 % of the incident PAR through (Notton & Blanke 1992, Scientia
 * Horticulturae): transmitted against reflected is 0.2–0.5. This pins:
 *   1. LEAF_THROUGH lies in that range and the sources stand beside it;
 *   2. the term: the card's colour × the sun's light × max(0, −normalView·s) × LEAF_THROUGH — three's normalView already
 *      faces the camera on a back face (measured), so this is the sun's strike on the leaf's far side, scattered through
 *      diffusely (a leaf lit from behind glows from any angle; a forward-scatter term, and then a term that flipped the
 *      normal once more, each left a bush's inside black)
 *      — shaded by the clouds, as the leaves' emissive; the sun's direction in view space from the camera's view matrix;
 *      sky() sets the direction and the light every frame.
 * Run: node tests/test_the_leaves_let_the_suns_light_through_at_the_measured_share.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const m = /const LEAF_THROUGH = ([0-9.]+);/.exec(page), T = m && Number(m[1]);
ok(m && T >= 0.2 && T <= 0.5, `LEAF_THROUGH is ${T}: transmitted against reflected, within the sources' 2–5 % against 10 %`);
const note = page.slice(page.indexOf("// LEAVES LIT THROUGH"), page.indexOf("const LEAF_THROUGH"));
ok(/absorbs ~85 %/.test(note) && /reflects ~10 %/.test(note) && /up to 2 % of the incident PAR/.test(note) && /Notton & Blanke 1992/.test(note) && /Golden Delicious/.test(note), "…with the sources beside it (the apple-leaf absorptance, Notton & Blanke 1992)");
const leaves = page.slice(page.indexOf("const leaves = new THREE.MeshStandardNodeMaterial"), page.indexOf("return [bark, leaves];"));
ok(/const sunV = TSL\.cameraViewMatrix\.mul\(TSL\.vec4\(leafSun\.dir, 0\)\)\.xyz\.normalize\(\);/.test(leaves), "the sun's direction in view space comes from the camera's view matrix on the GPU");
ok(/const through = TSL\.clamp\(TSL\.normalView\.dot\(sunV\)\.negate\(\), 0, 1\);/.test(leaves) && !/TSL\.frontFacing/.test(leaves), "the sun's strike on the far side of the side seen: max(0, −normalView·s) with NO flip — three's normalView already faces the camera on a back face (read back on the WebGL2 backend: all four sun/camera cases right; a flip by frontFacing got every back wrong and left a bush's inside black)");
ok(/leaves\.emissiveNode = shadeByClouds\(s\.rgb\.mul\(TSL\.attribute\("color", "vec3"\)\)\.mul\(leafSun\.rgb\)\.mul\(through\.mul\(LEAF_THROUGH\)\)\);/.test(leaves), "the light through the leaf: its colour × the sun × through × LEAF_THROUGH, under the cloud shadow, as the leaves' emissive");
ok(/const lt = SET\.leaves \? 1 : 0;/.test(page) && /leafSun\.dir\.value\.copy\(sd\); leafSun\.rgb\.value\.set\(lt \* sun\.color\.r \* sun\.intensity, lt \* sun\.color\.g \* sun\.intensity, lt \* sun\.color\.b \* sun\.intensity\);/.test(page), "sky() sets the sun's direction and light for the leaves every frame, nothing with the setting off");
ok(/leaves: 1, sound: 1 \}/.test(page) && /leaves: \[0, 1\] \}/.test(page) && /sel\("leaves", T\("gLeaves", "Leaves lit through"\), onOff\)/.test(page), "the setting: on by default, in the graphics panel after the clouds (#166)");
const i18n = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
ok(Object.keys(i18n).length === 17 && Object.values(i18n).every((t) => typeof t["land.gLeaves"] === "string" && t["land.gLeaves"].length > 2), "…named in all 17 languages");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
