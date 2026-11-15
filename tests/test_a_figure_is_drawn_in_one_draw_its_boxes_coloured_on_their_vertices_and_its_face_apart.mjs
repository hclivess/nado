/*
 * test_a_figure_is_drawn_in_one_draw_its_boxes_coloured_on_their_vertices_and_its_face_apart.mjs — #139: /draws on a
 * phone at the landing counted four people as 48 draws, a box each in its own material. land.js avatar() now lays every
 * box of a figure into one geometry, each box's colour on its vertices, in one material all figures share; the face is
 * its own plane. Run on three's own geometry (three.core.js) with the page's avatar():
 *   1. a figure is two meshes — its body and its face — whatever it wears (a skirt, pigtails, a cap, a cloak);
 *   2. the body keeps every box (36 corners a box), each where it stood: the head's top at 1.88 m, the cap's at 1.99 m;
 *   3. each box carries its colour: the skin's on the head, the trousers' on the legs, the cap's on the cap;
 *   4. two figures share the one body material (vertex colours on);
 *   5. the face is the kawaii plane on the head's front, as before.
 * Run: node tests/test_a_figure_is_drawn_in_one_draw_its_boxes_coloured_on_their_vertices_and_its_face_apart.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const THREE = await import(join(ROOT, "static", "vendor", "three", "three.core.js"));
const src = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = src.indexOf("let figureMaterial = null;"), b = src.indexOf("\n}\n", src.indexOf("function avatar(", a));
const C = { skin: 0xe0b090, hair: 0x302010, top: 0x4060a0, legs: 0x203040, cap: 0xc04020, cloak: 0x206040 };
const make = new Function("THREE", "lookColours", "faceFlat", src.slice(a, b + 2) + "\nreturn { avatar, mat: () => figureMaterial };")(THREE, () => C, () => null);
const g = make.avatar("x", { body: 1, face: 2 }), g2 = make.avatar("y", { body: 0 });
const meshes = g.children.filter((m) => m.isMesh);
ok(meshes.length === 2 && g2.children.filter((m) => m.isMesh).length === 2, `1. a figure is two meshes, its body and its face (${meshes.length}; a cap, a cloak, a skirt and pigtails on it)`);
const body = meshes.find((m) => m.geometry.attributes.color), face = meshes.find((m) => m !== body);
// body type 1 with a cap and a cloak: legs 2, skirt, torso, arms 2, head, hair, pigtails 2, cap, cloak = 12 boxes
ok(body && body.geometry.attributes.position.count === 12 * 36, `2. the body keeps every box, 36 corners each (${body && body.geometry.attributes.position.count / 36} boxes)`);
body.geometry.computeBoundingBox();
ok(Math.abs(body.geometry.boundingBox.max.y - 1.99) < 1e-6, `…each where it stood: the cap's top at ${body.geometry.boundingBox.max.y.toFixed(2)} m`);
const P = body.geometry.attributes.position, K = body.geometry.attributes.color, colAt = (pred) => { for (let i = 0; i < P.count; i++) if (pred(P.getX(i), P.getY(i), P.getZ(i))) return new THREE.Color(K.getX(i), K.getY(i), K.getZ(i)).getHex(); };
ok(colAt((x, y, z) => Math.abs(y - 1.5) < 1e-6 && Math.abs(x) <= 0.19 + 1e-6 && Math.abs(z) < 0.19) === C.skin, "3. the head's corners are the skin's colour");
ok(colAt((x, y) => Math.abs(y) < 1e-6 && x < -0.2) === C.legs, "…the legs' the trousers'");
ok(colAt((x, y) => Math.abs(y - 1.99) < 1e-6) === C.cap, "…the cap's the cap's");
ok(body.material === g2.children.find((m) => m.geometry && m.geometry.attributes.color).material && body.material.vertexColors === true && body.material === make.mat(), "4. two figures share the one body material, its vertex colours on");
ok(face && face.geometry.type === "PlaneGeometry" && Math.abs(face.position.z - 0.192) < 1e-9 && Math.abs(face.position.y - 1.69) < 1e-9 && face.material.transparent, "5. the face is the kawaii plane on the head's front");
ok(g.userData.person === true, "…and the figure is still marked a person (for /tris and /draws)");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
