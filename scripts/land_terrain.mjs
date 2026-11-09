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
//   {"trees": plot}                    ->  {"roots": [[face, u, v, top], ...]}  — the untouched plot's trees: each trunk's
//       column and the ground it stands on (its trunk starts at top + 1). The world server seeds new trees from them.
//   {"card": plot}                     ->  {"biome", "low", "high", "mean", "under_sea", "trees", "flax"}  — the untouched
//       plot's facts for its market listing (#125): its commonest biome, its ground in metres above the sea (lowest,
//       highest, mean), how many of its 256 columns lie under the sea, its trees (trunked: a bush is not one) and its flax. A listing states what
//       the planet IS there, so it is read from the generator, never estimated.
//   {"cols": [[face, u, v], ...]}      ->  {"cols": [[height, top, biome], ...]}  — the untouched ground under each column
//       (land-world column): where the world server's animals walk and what kinds live there (HUNTING, #156).
//   {"soil": [face, u, v]}             ->  {"soil": "loam" | "sandy" | "clay" | "peat" | "stony"}  — the column's soil
//       (land-world soilOf), which rules a field there (FARMING, #154).
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
function card(p) {
  if (!(Number.isInteger(p) && p >= 0 && p < W.PLOT_MAX)) throw new Error("bad plot");
  const q = W.plotCoords(p), biomes = {};
  let low = Infinity, high = -Infinity, sum = 0, under = 0, trees = 0, flax = 0;
  for (let du = 0; du < W.PLOT; du++) for (let dv = 0; dv < W.PLOT; dv++) {
    const u = q.u0 + du, v = q.v0 + dv, c = col(q.face, u, v), e = c.top - W.SEA;
    biomes[c.biome] = (biomes[c.biome] || 0) + 1;
    low = Math.min(low, e); high = Math.max(high, e); sum += e;
    if (c.top < W.SEA) under++;
    if (trunked(q.face, u, v, c)) trees++;                         // a bush (leaves, no trunk) is no tree
    if (W.litterAt(q.face, u, v, c) === W.B.flax) flax++;
  }
  const biome = Object.keys(biomes).sort((a, b) => biomes[b] - biomes[a] || (a < b ? -1 : 1))[0];
  return { biome, low, high, mean: Math.round(sum / (W.PLOT * W.PLOT)), under_sea: under, trees, flax };
}
/** A tree with a wooden trunk (land-world treeAt also places bushes: leaves on the ground, nothing to fell or seed). */
const trunked = (f, u, v, c) => { const t = W.treeAt(f, u, v, c); return !!t && W.TREE_WOOD.has(W.treeCell(t, 0, 0, 1)); };
function trees(p) {
  if (!(Number.isInteger(p) && p >= 0 && p < W.PLOT_MAX)) throw new Error("bad plot");
  const q = W.plotCoords(p), out = [];
  for (let du = 0; du < W.PLOT; du++) for (let dv = 0; dv < W.PLOT; dv++) {
    const u = q.u0 + du, v = q.v0 + dv, c = col(q.face, u, v);
    if (trunked(q.face, u, v, c)) out.push([q.face, u, v, c.top]);
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
    else if ("card" in req) out = card(req.card);
    else if ("trees" in req) out = { roots: trees(req.trees) };
    else if (req.cols) out = { cols: req.cols.map(([f, u, v]) => {
      if (!(f >= 0 && f < 6 && u >= 0 && u < W.W && v >= 0 && v < W.W)) return [0, 0, "rock"];
      const c = col(f, Math.floor(u), Math.floor(v)); return [c.height, c.top, c.biome];
    }) };
    else if (req.soil) {
      const [f, u, v] = req.soil;
      if (!(f >= 0 && f < 6 && u >= 0 && u < W.W && v >= 0 && v < W.W)) throw new Error("bad column");
      out = { soil: W.soilOf(f, u, v, col(f, u, v)) };
    }
    else out = { blocks: req.cells.map(([f, u, v, h]) => {
      if (!(f >= 0 && f < 6 && u >= 0 && u < W.W && v >= 0 && v < W.W && Number.isInteger(h))) return -1;
      return h < W.DEEP_MIN ? W.B.bedrock : h >= W.H ? W.B.air : W.terrainBlock(f, u, v, h, col);   // the deep too (#129)
    }) };
  } catch (e) { out = { error: String(e && e.message || e) }; }
  process.stdout.write(JSON.stringify(out) + "\n");
});
