// land_terrain.mjs — the world server's terrain oracle (scripts/land_server.py starts it beside itself): answers "which
// block does the untouched planet have here" by running static/land-world.js, the SAME generator every browser runs —
// never a second implementation of it, whose floating-point drift would let the server and the page disagree about
// what was mined. The server needs it to know what a break really yields (a player cannot claim stone where there is
// earth) and what an un-built cell goes back to.
//
// Protocol: one JSON request per line on stdin, one JSON reply per line on stdout, in order.
//   {"cells": [[face, u, v, h], ...]}  ->  {"blocks": [id, ...]}
//   {"fell": [face, u, v, h]}          ->  {"cells": [[face, u, v, h, id], ...]}  — the untouched cells of the tree whose
//       trunk is cut at that cell that stand above the cut (its logs above, its crown), each truly that tree's in the
//       untouched planet. Empty when the cell is no tree's trunk. ("can we add some basic gravity", operator 2026-11-06)
//   {"grow": [face, u, v, h]}          ->  {"cells": [[face, u, v, h, id], ...]}  — the young tree a sapling planted at
//       that cell grows into (land-world saplingTree): its trunk from that cell up, its crown, as land-world treeCell
//       draws a tree. The server writes only the cells that are still air. (ECOLOGY, scripts/land_server.py)
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const W = await import(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "land-world.js"));
const memo = new Map();
const col = (f, u, v) => {
  const k = (f * W.W + u) * W.W + v;
  let c = memo.get(k);
  if (!c) { if (memo.size > 500000) memo.clear(); c = W.column(f, u, v); memo.set(k, c); }
  return c;
};
/** A tree's trunk is its root's column (land-world treeCell: wood only at du = dv = 0), so the cut cell names the root. */
function fell(f, u, v, h) {
  if (!(f >= 0 && f < 6 && u >= 0 && u < W.W && v >= 0 && v < W.W && Number.isInteger(h))) return [];
  const c = col(f, u, v), t = W.treeAt(f, u, v, c), cut = h - c.top;
  if (!t || !W.TREE_WOOD.has(W.treeCell(t, 0, 0, cut))) return [];
  const out = [];
  for (let du = -2; du <= 2; du++) for (let dv = -2; dv <= 2; dv++) for (let dh = cut; dh <= t.height + 2; dh++) {
    const b = W.treeCell(t, du, dv, dh);
    if (!b || (du === 0 && dv === 0 && dh === cut)) continue;
    if (W.TREE_WOOD.has(b) && dh === cut) continue;                    // the cut itself; wood beside it is no tree's
    const x = u + du, y = v + dv, hh = c.top + dh;
    if (W.terrainBlock(f, x, y, hh, col) === b) out.push([f, x, y, hh, b]);   // truly this tree's cell
  }
  return out;
}
function grow(f, u, v, h) {
  if (!(f >= 0 && f < 6 && u >= 0 && u < W.W && v >= 0 && v < W.W && Number.isInteger(h))) return [];
  const t = W.saplingTree(f, u, v, col(f, u, v)), out = [];
  for (let du = -2; du <= 2; du++) for (let dv = -2; dv <= 2; dv++) for (let dh = 1; dh <= t.height + 2; dh++) {
    const b = W.treeCell(t, du, dv, dh);
    if (b) out.push([f, u + du, v + dv, h - 1 + dh, b]);
  }
  return out;
}
const rl = createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let out;
  try {
    const req = JSON.parse(line);
    if (req.fell) out = { cells: fell(...req.fell) };
    else if (req.grow) out = { cells: grow(...req.grow) };
    else out = { blocks: req.cells.map(([f, u, v, h]) => {
      if (!(f >= 0 && f < 6 && u >= 0 && u < W.W && v >= 0 && v < W.W && Number.isInteger(h))) return -1;
      return h < 0 ? W.B.bedrock : h >= W.H ? W.B.air : W.terrainBlock(f, u, v, h, col);
    }) };
  } catch (e) { out = { error: String(e && e.message || e) }; }
  process.stdout.write(JSON.stringify(out) + "\n");
});
