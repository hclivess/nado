/*
 * test_a_crafts_pieces_are_drawn_in_one_draw_a_material_each_in_its_own_place.mjs — #139: measured with /draws on a
 * phone at the landing, 551 draw calls a frame, 220 of them one craft's painted plate. A craft was a mesh a piece (and a
 * mesh a tone of each part), so a 60-piece X-wing cost hundreds of draws. land.js mergeByMaterial bakes a craft's pieces
 * that share a material into one geometry. Run on three's own geometry (three.core.js), the page's function:
 *   1. the pieces of one material become one mesh, each material its own, the plumes left as they were;
 *   2. every vertex is kept, moved and turned to where its piece stood (a piece's corner lands where it did);
 *   3. normals are turned with the piece; the attributes the materials read (uv, color, tile) come through whole;
 *   4. glass keeps its renderOrder 1; a material with one piece is left alone;
 *   5. craftMesh calls it with the plumes kept.
 * Run: node tests/test_a_crafts_pieces_are_drawn_in_one_draw_a_material_each_in_its_own_place.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const THREE = await import(join(ROOT, "static", "vendor", "three", "three.core.js"));
const src = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = src.indexOf("function mergeByMaterial("), b = src.indexOf("\n}\n", a);
const mergeByMaterial = new Function("THREE", src.slice(a, b + 2) + "\nreturn mergeByMaterial;")(THREE);

const box = (w, h, d) => { const g = new THREE.BoxGeometry(w, h, d); g.setAttribute("color", new THREE.Float32BufferAttribute(new Array(g.attributes.position.count * 3).fill(1), 3));
  g.setAttribute("tile", new THREE.Float32BufferAttribute(new Array(g.attributes.position.count).fill(7), 1)); return g; };
const paint = new THREE.MeshBasicMaterial(), steel = new THREE.MeshBasicMaterial(), glass = new THREE.MeshBasicMaterial();
const g = new THREE.Group();
const p1 = new THREE.Mesh(box(1, 1, 1), paint); p1.position.set(10, 0, 0);
const p2 = new THREE.Mesh(box(2, 1, 1), paint); p2.position.set(0, 5, 0); p2.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2);
const p3 = new THREE.Mesh(box(1, 1, 1), paint); p3.position.set(0, 0, -3);
const s1 = new THREE.Mesh(box(1, 1, 1), steel);
const g1 = new THREE.Mesh(box(1, 1, 1), glass); g1.renderOrder = 1; g1.position.set(0, 2, 0);
const g2 = new THREE.Mesh(box(1, 1, 1), glass); g2.renderOrder = 1; g2.position.set(0, 3, 0);
const plume = new THREE.Mesh(box(1, 1, 1), paint);
for (const m of [p1, p2, p3, s1, g1, g2, plume]) g.add(m);
const verts = (ms) => ms.reduce((t, m) => t + (m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count), 0);
const before = verts([p1, p2, p3]);
mergeByMaterial(g, new Set([plume]));

const meshes = g.children.filter((m) => m !== plume);
const pm = meshes.filter((m) => m.material === paint), sm = meshes.filter((m) => m.material === steel), gm = meshes.filter((m) => m.material === glass);
ok(pm.length === 1 && sm.length === 1 && gm.length === 1 && g.children.includes(plume) && g.children.length === 4, `1. three painted pieces are one mesh, two glass one, the lone steel piece and the plume left as they were (${g.children.length} children)`);
ok(sm[0] === s1, "…the lone steel piece is the same mesh, untouched");
const P = pm[0].geometry.attributes.position;
ok(P.count === before, `2. every vertex of the three painted pieces is kept (${P.count} of ${before})`);
pm[0].geometry.computeBoundingBox(); const bb = pm[0].geometry.boundingBox;
ok(Math.abs(bb.max.x - 10.5) < 1e-6 && Math.abs(bb.min.z + 3.5) < 1e-6 && Math.abs(bb.max.y - 6) < 1e-6, `…each moved and turned to where it stood (x to 10.5, z to −3.5, the turned 2 m piece up to y 6): ${bb.min.toArray().map((x) => x.toFixed(2))} … ${bb.max.toArray().map((x) => x.toFixed(2))}`);
{
  // the turned piece's +x face normal (1,0,0) is turned 90° about z: (0,1,0)
  const N = pm[0].geometry.attributes.normal; let up = 0, along = 0;
  const off = 36; for (let i = off; i < off + 6; i++) { if (Math.abs(N.getY(i) - 1) < 1e-6) up++; if (Math.abs(N.getX(i) - 1) < 1e-6) along++; }
  ok(up === 6 && along === 0, `3. normals are turned with their piece (${up} of the turned piece's first face point up)`);
}
const att = pm[0].geometry.attributes;
ok(att.uv && att.uv.count === before && att.color && att.color.count === before && att.tile && att.tile.count === before && [...att.tile.array].every((t) => t === 7),
  "…uv, color and tile come through whole");
ok(gm[0].renderOrder === 1, "4. the merged glass keeps renderOrder 1 (drawn after what is seen through it)");
ok(/mergeByMaterial\(g, new Set\(g\.userData\.plumes \|\| \[\]\)\);\n  g\.matrixAutoUpdate = false;\n  return g;/.test(src), "5. craftMesh merges its pieces, the plumes kept");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
