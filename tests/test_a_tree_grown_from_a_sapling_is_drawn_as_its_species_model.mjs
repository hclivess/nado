/*
 * test_a_tree_grown_from_a_sapling_is_drawn_as_its_species_model.mjs — a tree grown from a sapling is edits, not the
 * planet's, and was drawn as stacked log blocks and leaf clusters; it is drawn as its species' grown model now, like
 * every natural tree ("no there are still old shitty trees in the world", operator 2026-11-08). Through the mesher:
 *   1. a planted tree whose cells are the ones the world server grows (land-world saplingTree) is its model: bark and
 *      leaf cards, none of its log cells drawn as trunk segments, none of its leaf cells as leaf clusters;
 *   2. on levelled ground too (the town's earth is edited): it stands on the cell's floor;
 *   3. a crown cell picked since is left out of the model;
 *   4. what is no such tree stays its cells: a pillar of logs someone built, and a planted tree whose trunk was cut.
 *
 * Run: node tests/test_a_tree_grown_from_a_sapling_is_drawn_as_its_species_model.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js")), M = await import(join(ROOT, "static", "land-mesher.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };
const verts = (r, k) => (r && r[k] ? r[k].pos.length / 3 : 0);
const u = 3440 * 16 + 6, v = 4999 * 16 + 3, g0 = 136, col = W.column(0, u, v), t = W.saplingTree(0, u, v, col);
const mesh = (ed) => M.meshChunk(0, Math.floor(u / 16), Math.floor(v / 16), Math.floor((g0 + 1) / 16), ed, null, 0);
const planted = () => {
  const ed = new Map([[`0:${u}:${v}:${g0}`, W.B.grass]]);                 // levelled ground: an edited turf cell
  for (let du = -2; du <= 2; du++) for (let dv = -2; dv <= 2; dv++) for (let dh = 1; dh <= t.height + 2; dh++) {
    const b = W.treeCell(t, du, dv, dh); if (b) ed.set(`0:${u + du}:${v + dv}:${g0 + dh}`, b);
  }
  return ed;
};
const base = mesh(new Map([[`0:${u}:${v}:${g0}`, W.B.grass]]));
const whole = mesh(planted());
ok(verts(whole, "bark") > verts(base, "bark") + 100 && verts(whole, "foliage") > verts(base, "foliage") + 100 && verts(whole, "trees") === verts(base, "trees"),
   `a planted ${t.kind} is its grown model: bark ${verts(whole, "bark") - verts(base, "bark")} and leaf ${verts(whole, "foliage") - verts(base, "foliage")} vertices, no log cell drawn as a trunk segment`);
// it stands on the cell's floor: the model's lowest bark sits at the ground layer's top, not the column's untouched height
let lowest = Infinity;
{ const p = whole.bark.pos, a = whole.anchor; const fr = W.frameOf(0, u + 0.5, v + 0.5); const R0 = W.R0;
  for (let i = 0; i < p.length; i += 3) { const x = p[i] + a[0], y = p[i + 1] + a[1], z = p[i + 2] + a[2], r = Math.hypot(x, y, z) - R0; const d = Math.hypot(x - (fr.up[0] * (R0 + g0 + 1)), 0, 0); lowest = Math.min(lowest, r); } }
ok(Math.abs(lowest - (g0 + 1 - 0.3)) < 0.6, `…standing on the levelled ground's floor (its trunk reaches down to ${lowest.toFixed(2)} m, the floor at ${g0 + 1})`);
// 3. a crown cell picked
// (a model's leaf card is left out when its centre lies in a picked cell: the crown's upper layers are picked here)
const picked = planted();
for (const [k, b] of [...picked]) if (W.TREE_LEAVES.has(b) && Number(k.split(":")[3]) >= g0 + t.height) picked.set(k, 0);
ok(verts(mesh(picked), "foliage") < verts(whole, "foliage") && verts(mesh(picked), "foliage") > verts(base, "foliage"),
   `crown cells picked since are left out of the model, the rest of it stays (${verts(whole, "foliage")} -> ${verts(mesh(picked), "foliage")} leaf vertices)`);
// a sapling that grew under a neighbour's crown has that neighbour's leaves in its trunk's cells: still a tree
const under = planted(); under.set(`0:${u}:${v}:${g0 + 3}`, W.B.leaves);
ok(verts(mesh(under), "trees") === verts(base, "trees") && verts(mesh(under), "bark") > verts(base, "bark") + 100,
   "a tree grown under a neighbour's crown (its leaves in the trunk's cells) is still its model");
// 4. not such a tree: a log pillar on the turf (one cell short of the trunk), a cut trunk
const pillar = new Map([[`0:${u}:${v}:${g0}`, W.B.grass]]);
for (let dh = 1; dh < t.height; dh++) pillar.set(`0:${u}:${v}:${g0 + dh}`, W.treeCell(t, 0, 0, 1));
ok(verts(mesh(pillar), "trees") > verts(base, "trees"), "a pillar of logs someone built stays its cells");
const cut = planted(); cut.set(`0:${u}:${v}:${g0 + 2}`, 0);
ok(verts(mesh(cut), "trees") > verts(base, "trees"), "a planted tree whose trunk was cut is drawn as its cells, never a model floating over the cut");
console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
