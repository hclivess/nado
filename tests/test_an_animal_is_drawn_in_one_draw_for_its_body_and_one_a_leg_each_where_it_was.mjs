/*
 * test_an_animal_is_drawn_in_one_draw_for_its_body_and_one_a_leg_each_where_it_was.mjs — #139: /draws on a desktop at
 * the landing counted 164 draws of animals, a dozen and more meshes each. land.js bakeColoured bakes the meshes hung
 * straight on an animal (body, belly, head, neck, eyes, ears, tusks, antlers, tail), each with its own place, turn and
 * scale, into one geometry with each one's colour on its vertices, in one shared material; the legs swing on their hips
 * and stay their own. Run on three's own geometry (three.core.js) with the page's animalMesh, each kind built baked and
 * unbaked:
 *   1. an animal is one body mesh and its four legs on their hips — a deer, a stag, a boar, a rabbit;
 *   2. the baked body is the same shape: as many corners, and the same bounds, as the parts it was made of;
 *   3. each part's colour is on its corners (the deer's brown body, its pale belly, its black eyes);
 *   4. every animal shares the one body material, vertex colours on; the legs still swing (four hips returned).
 * Run: node tests/test_an_animal_is_drawn_in_one_draw_for_its_body_and_one_a_leg_each_where_it_was.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const THREE = await import(join(ROOT, "static", "vendor", "three", "three.core.js"));
const src = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = src.indexOf("const ANIMAL_LOOK = {"), b = src.indexOf("\n}\n", src.indexOf("function bakeColoured(", a));
const body = src.slice(a, b + 2);
const build = (bake) => new Function("THREE", (bake ? body : body.replace("  bakeColoured(g);\n", "")) + "\nreturn { animalMesh, ANIMAL_LOOK, mat: () => colouredMaterial };")(THREE);
const B = build(true), U = build(false);
const corners = (g) => { let n = 0; g.traverse((m) => { if (m.isMesh && m.parent === g) n += m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count; }); return n; };
const bounds = (g) => { const box = new THREE.Box3(); for (const m of g.children) if (m.isMesh) { m.updateMatrixWorld(true); const q = m.geometry.clone(); q.applyMatrix4(m.matrix); q.computeBoundingBox(); box.union(q.boundingBox); } return box; };
const mats = new Set();
for (const [kind, angry] of [["deer", false], ["deer", true], ["boar", false], ["rabbit", false]]) {
  const x = B.animalMesh(kind, angry), y = U.animalMesh(kind, angry);
  const meshes = x.g.children.filter((m) => m.isMesh), hips = x.g.children.filter((m) => !m.isMesh);
  const name = kind + (angry ? " (a stag)" : "");
  ok(meshes.length === 1 && hips.length === 4 && x.legs.length === 4 && hips.every((h) => h.children.length === 1 && h.children[0].isMesh),
    `1. a ${name} is one body mesh and four legs on their hips (${meshes.length} + ${hips.length}; unbaked it was ${y.g.children.filter((m) => m.isMesh).length} + 4)`);
  const bx = bounds(x.g), by = bounds(y.g), close = (p, q) => p.distanceTo(q) < 1e-5;
  ok(meshes[0].geometry.attributes.position.count === corners(y.g) && close(bx.min, by.min) && close(bx.max, by.max),
    `2. …the same shape: ${meshes[0].geometry.attributes.position.count} corners (unbaked ${corners(y.g)}), the same bounds`);
  mats.add(meshes[0].material);
  if (kind === "deer" && !angry) {
    const K = meshes[0].geometry.attributes.color, seen = new Set(); for (let i = 0; i < K.count; i++) seen.add(new THREE.Color(K.getX(i), K.getY(i), K.getZ(i)).getHex());
    const L = B.ANIMAL_LOOK.deer;
    ok(seen.has(L.body) && seen.has(L.belly) && seen.has(0x111111) && seen.has(0xf4efe6), "3. each part's colour is on its corners: the brown body, the pale belly, the black eyes, the white tail");
  }
}
ok(mats.size === 1 && [...mats][0] === B.mat() && [...mats][0].vertexColors === true, "4. every animal shares the one body material, vertex colours on");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
