/*
 * test_the_forest_stands_beyond_the_chunks_as_pictures_of_its_own_trees.mjs — #183 ("compared to this our game looks
 * like from 1996", operator 2026-11-11, beside a concept picture of a meadow under a tree line). Measured on the live
 * page at Ultra, a wood 144 m ahead: not one tree drawn — trees existed only inside the meshed chunks. The forest now
 * stands out to the far-tree range as crossed cards carrying a picture of each tree's own model (static/land-forest.js).
 *   1. the far forest is the world's own trees: treeRoots names exactly the trees treeAt names, column for column,
 *      across a face edge too — and the shortcut it takes (treeChance) rules out no tree of any biome at its densest;
 *   2. every (species, height) the world can grow has its picture in the atlas;
 *   3. a tile is eight vertices and four triangles a tree, each triangle indexed from both sides, every card standing
 *      on its root (the root's own place on the planet), its picture inside its own slot of the atlas, tagged with its
 *      root's chunk — what the page hides a far tree by;
 *   4. the far tree is turned and sized by the numbers the mesher gives the model (one definition, not two);
 *   5. the page's regression sites: a forest job survives the chunk queue's prune, a chunk says when it is meshed, the
 *      atlas is read back and set upright by its marker, and the readout counts the far trees.
 *
 * Run: node tests/test_the_forest_stands_beyond_the_chunks_as_pictures_of_its_own_trees.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js")), F = await import(join(ROOT, "static", "land-forest.js"));
const src = (f) => readFileSync(join(ROOT, "static", f), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };

// ---- 1. the far forest is the world's own trees -----------------------------------------------------------------
const EDGE = W.FACE_N * 16;                                   // columns along a face edge
const brute = (face, u0, v0, size) => {
  const out = [];
  for (let v = v0; v < v0 + size; v++) for (let u = u0; u < u0 + size; u++) {
    const w = W.wrap(face, u, v), t = W.treeAt(w.face, w.u, w.v, W.column(w.face, w.u, w.v));
    if (t && t.kind !== "bush") out.push(`${u}:${v}:${w.face}:${w.u}:${w.v}:${t.kind}:${t.height}`);
  }
  return out;
};
const named = (rs) => rs.map((r) => `${r.u}:${r.v}:${r.face}:${r.wu}:${r.wv}:${r.tree.kind}:${r.tree.height}`);
let total = 0;
for (const [face, u0, v0, size, what] of [[0, 54260 - 48, 80600, 96, "a wood by the town"], [0, EDGE - 48, 80000, 96, "across a face edge"],
  [2, 30000, 41000, 96, "another face"], [0, 54992, 79968, 64, "the build plot and its neighbours"]]) {
  const a = named(W.treeRoots(face, u0, v0, size)), b = brute(face, u0, v0, size);
  total += b.length;
  ok(a.length === b.length && a.every((x, i) => x === b[i]), `treeRoots names treeAt's trees, column for column — ${what} (${b.length} trees)`);
}
ok(total > 200, `the sampled squares grow trees at all (${total})`);
// the shortcut: a column treeChance rules out grows no tree in any biome, however dense the wood, cold or wet the land
let grown = 0, missed = 0; const kinds = new Set();
const COLS = [];
for (const biome of ["forest", "grass", "snow", "beach", "desert", "rock"]) for (const temp of [-0.5, 0, 0.3]) for (const top of [W.SEA + 2, W.SEA + 80])
  COLS.push({ biome, temp, top, height: top, woods: 1, wet: 1 });
for (let u = 2; u < 2 + 16 * 400; u++) {
  if (u % 16 < 2 || u % 16 > 13) continue;
  for (const v of [5, 22, 39]) for (const col of COLS) {
    const t = W.treeAt(1, u, v, col);
    if (!t || t.kind === "bush") continue;
    grown++; kinds.add(t.kind + ":" + t.height);
    if (!W.treeChance(1, u, v)) missed++;
  }
}
ok(grown > 1000 && missed === 0, `no tree of any biome at its densest grows where treeChance says none can (${grown} trees asked, ${missed} missed)`);

// ---- 2. every tree the world grows has its picture ----------------------------------------------------------------
const noSlot = [...kinds].filter((k) => F.slotOf(k.split(":")[0], Number(k.split(":")[1])) < 0);
ok(kinds.size >= 9 && !noSlot.length, `every (species, height) the world grows has a slot in the atlas (${kinds.size} grown; none without: ${noSlot.join(" ") || "-"})`);
ok(F.SLOTS.length < F.ATLAS.cols * F.ATLAS.rows, "the atlas keeps one slot free (the page's upright marker is drawn there)");
ok(new Set(F.SLOTS.map((s) => s.join(":"))).size === F.SLOTS.length, "no slot is named twice");

// ---- 3. a tile's geometry ---------------------------------------------------------------------------------------
const tu = Math.floor(54260 / F.TILE), tv = Math.floor(80600 / F.TILE), T = F.forestTile(0, tu, tv);
const roots = W.treeRoots(0, tu * F.TILE, tv * F.TILE, F.TILE);
ok(T.n > 100 && T.n === roots.length, `a tile carries every tree rooted in it (${T.n})`);
ok(T.pos.length === T.n * 24 && T.off.length === T.n * 24 && T.nor.length === T.n * 24 && T.col.length === T.n * 24 && T.uv.length === T.n * 16 && T.root.length === T.n * 16,
  "eight vertices a tree: place, offset, normal, shade, picture and root chunk for each");
ok(T.idx.length === T.n * 24 && Math.max(...T.idx) === T.n * 8 - 1, "four triangles a tree, each indexed from both sides (24 indices)");
{
  let both = true, flat = true, onRoot = true, inSlot = true, chunk = true, sized = true, unit = true;
  const { cols, rows, wide, tall } = F.ATLAS;
  for (let i = 0; i < T.n; i++) {
    const r = roots[i], p = W.posOf(0, r.u + 0.5, r.v + 0.5, r.col.height), slot = F.slotOf(r.tree.kind, r.tree.height), cx = slot % cols, cy = Math.floor(slot / cols);
    for (let q = 0; q < 2; q++) {
      const o = (i * 2 + q) * 12, tri = (k) => [T.idx[o + k], T.idx[o + k + 1], T.idx[o + k + 2]];
      // triangles 0, 1 are one side; 2, 3 the same corners wound the other way
      const same = (a, b) => [...a].sort().join() === [...b].sort().join(), turn = (a) => { const m = a.indexOf(Math.min(...a)); return [a[m], a[(m + 1) % 3], a[(m + 2) % 3]].join(); };
      if (!(same(tri(0), tri(6)) && turn(tri(0)) !== turn(tri(6)) && same(tri(3), tri(9)) && turn(tri(3)) !== turn(tri(9)))) both = false;
      for (let c = 0; c < 4; c++) {
        const k = (i * 8 + q * 4 + c) * 3, k2 = (i * 8 + q * 4 + c) * 2;
        for (let d = 0; d < 3; d++) if (Math.abs(T.pos[k + d] + T.anchor[d] - p[d]) > 0.02) onRoot = false;
        if (Math.hypot(T.off[k], T.off[k + 1], T.off[k + 2]) > Math.hypot(wide / 2, tall) * 1.001) sized = false;
        if (Math.abs(Math.hypot(T.nor[k], T.nor[k + 1], T.nor[k + 2]) - 1) > 1e-4) unit = false;
        const su = T.uv[k2] * cols - cx, sv = T.uv[k2 + 1] * rows - cy;
        if (su < -1e-5 || su > 1 + 1e-5 || sv < -1e-5 || sv > 1 + 1e-5) inSlot = false;
        if (T.root[k2] !== Math.floor(r.u / W.CHUNK) || T.root[k2 + 1] !== Math.floor(r.v / W.CHUNK)) chunk = false;
      }
      // a card is flat: its four offsets lie in one plane (the triple product of three of its edges is nothing)
      const v = (c) => { const k = (i * 8 + q * 4 + c) * 3; return [T.off[k], T.off[k + 1], T.off[k + 2]]; }, a = v(0), e = [1, 2, 3].map((c) => v(c).map((x, d) => x - a[d]));
      const det = e[0][0] * (e[1][1] * e[2][2] - e[1][2] * e[2][1]) - e[0][1] * (e[1][0] * e[2][2] - e[1][2] * e[2][0]) + e[0][2] * (e[1][0] * e[2][1] - e[1][1] * e[2][0]);
      if (Math.abs(det) > 0.05) flat = false;
    }
  }
  ok(both, "every triangle is there twice, wound both ways (front faces only are drawn, and no normal is flipped)");
  ok(onRoot, "every vertex's place is its tree's root on the planet (the card collapses onto it where the chunk is meshed)");
  ok(flat && sized && unit, "a card is flat, no larger than a slot of the atlas, its normals of length one");
  ok(inSlot, "a card's picture lies inside its own (species, height) slot");
  ok(chunk, "every vertex carries its root's chunk (cu, cv)");
}
{
  // a tile wholly past the face's edge: the neighbouring face's trees, in this face's frame (the player sees over the edge)
  const eu = EDGE / F.TILE, ev = Math.floor(80000 / F.TILE), E = F.forestTile(0, eu, ev), over = W.treeRoots(0, eu * F.TILE, ev * F.TILE, F.TILE);
  ok(E.n > 0 && E.n === over.length && over.every((r) => r.face !== 0 && r.u >= EDGE), `a tile past the face's edge carries the neighbouring face's trees (${E.n})`);
}
{
  // a tile over open sea grows nothing and says so without arrays
  let sea = null;
  for (let i = 0; i < 400 && !sea; i++) { const t = F.forestTile(0, 7 + i * 3, 11 + i * 5); if (!t.n) sea = t; }
  ok(sea && !sea.pos, "a tile where no tree grows is { n: 0 } — nothing to send, nothing to draw");
}

// ---- 4. turned and sized as the model is ---------------------------------------------------------------------------
const mesher = src("land-mesher.js");
ok(!/function hash3\(/.test(mesher) && /import \{[^}]*\bhash3\b[^}]*\} from "\.\/land-forest\.js"/.test(mesher), "the mesher's place hash is land-forest's own (one definition)");
ok(/placeModel\(m, face, gu \+ 0\.5, gv \+ 0\.5, ground, treeTurn\(face, gu, gv\), treeSize\(face, gu, gv\),/.test(mesher), "the mesher turns and sizes a tree's model by treeTurn / treeSize — the far card's own numbers");
ok(F.treeTurn(0, 5, 9) === F.hash3(9, 0, 5) * Math.PI * 2 && F.treeSize(0, 5, 9) === 0.9 + 0.1 * F.hash3(8, 9, 0), "treeTurn / treeSize are what the mesher has always used (no tree in the world turned when the far forest arrived)");
ok(/if \(m\.forest\)/.test(mesher) && /forestTile\(m\.face, m\.tu, m\.tv\)/.test(mesher), "a mesher worker builds a forest tile when asked");

// ---- 5. the page's regression sites --------------------------------------------------------------------------------
const page = src("land.js");
ok(/if \(!queue\[i\]\.forest && !want\.has\(queue\[i\]\.k\)\)/.test(page), "the chunk queue's prune leaves forest jobs alone (pruned, the far forest never arrived)");
ok(/c\.busy = false; c\.ready = true;/.test(page), "a chunk says when it has been meshed (far trees hide only where the models stand)");
ok(/readRenderTargetPixelsAsync/.test(page) && /marker/.test(page), "the atlas is read back and set upright by its marker (the two backends store a render target's rows in opposite orders)");
ok(/\$\{forestTrees\} far trees/.test(page), "the stats readout counts the far trees");
ok(/pt\("forest", updateForest\)/.test(page) && /bakeForest\(\)\.catch/.test(page), "the page bakes the atlas at start and keeps the forest's tiles up to date");


// ---- 6. the tree line is not built last ----------------------------------------------------------------------------
// (measured at view 8 under a software renderer: the chunk queue was still not empty after 8 minutes, every forest tile
// ranked behind every chunk, and the readout said "0 far trees" — the bare horizon the forest was written to end)
const rankSrc = /function jobRank\(q, pcu, pcv, face\) \{[\s\S]*?\n\}/.exec(page);
ok(!!rankSrc && /d = jobRank\(q, pcu, pcv, P\.face\)/.test(page), "the mesher's queue is ordered by jobRank, and by nothing else");
if (rankSrc) {
  const jobRank = new Function(rankSrc[0] + "; return jobRank;")();
  const chunk = (du, dv, face = 0) => jobRank({ cu: 100 + du, cv: 100 + dv, face }, 100, 100, 0);
  const tile = (dtu, dtv) => jobRank({ forest: 1, cu: 100 + dtu * 16, cv: 100 + dtv * 16, face: 0 }, 100, 100, 0);
  ok(chunk(0, 0) < chunk(1, 0) && chunk(1, 0) < chunk(1, 1) && chunk(2, 0, 1) > chunk(2, 0), "chunks go nearest first, another face's after this one's");
  ok(chunk(1, 1) < tile(0, 0), "the ground underfoot is meshed before the first forest tile");
  ok(tile(0, 0) < tile(1, 0) && tile(1, 0) < tile(2, 2), "forest tiles go nearest first");
  let far = 0;                                                // the farthest tile of the forest's range against the view disc's rim
  for (let dv = -5; dv <= 5; dv++) for (let du = -5; du <= 5; du++) if (Math.hypot(Math.max(Math.abs(du) - 0.5, 0), Math.max(Math.abs(dv) - 0.5, 0)) * F.TILE <= 1152) far = Math.max(far, tile(du, dv));
  ok(far < chunk(8, 0), `every forest tile in range is asked for before a chunk eight away (${far.toFixed(1)} against ${chunk(8, 0)}): a far chunk's trees are the forest's own`);
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);
