// land-forest.js — THE FOREST BEYOND THE CHUNKS (#183; operator 2026-11-11, beside a concept picture of a meadow under a
// tree line with the sea behind it: "compared to this our game looks like from 1996"). Measured on the live page at
// Ultra from a meadow with a wood 144 m ahead: not one tree was drawn. Trees existed only in meshed chunks (128 m at
// most, 48 m on a phone) and the land beyond was bare ground to the horizon — no tree line, anywhere, ever.
//
// Here every tree the world grows (land-world treeAt: the very trees the chunks draw once the player is near, at the
// very same places) stands out to the far-tree range as an IMPOSTOR: two crossed upright cards carrying a picture of
// its own species' model at its own height, four triangles a tree — each drawn from both sides (eight in the index), the
// back with the front's own normal: a card lit as a crown is, not as a wall that turns dark seen from behind. The page bakes the pictures once, at start, from the
// land-trees.js models themselves (SLOTS below, one slot of the atlas each), so a far tree is the near tree's own
// picture — its colours cannot drift from the model's. A tile is TILE columns square, built in a mesher worker.
//
// The page hides a far tree whose chunk it has meshed (the model stands there): each vertex carries its root's chunk
// (`root`) and its offset from the root (`off`), and the material collapses the card onto its root inside the meshed
// disc. Felled trees still stand in the far forest until the player is near enough to mesh their chunk: the far view
// knows the planet as it was generated, not its edits — the same as the far ground, which shows no building either.
import { CHUNK, SEA, posOf, frameOf, treeRoots } from "./land-world.js";

export const TILE = 256;                         // columns along a forest tile's edge (16 chunks)
/** The atlas: one slot per (kind, height) treeAt can name, left to right then UP — uv (0, 0) is slot 0's bottom-left. A
 *  slot is `wide` x `tall` metres of the model seen from its side, its root's ground `foot` above the slot's bottom. */
export const SLOTS = [["broadleaf", 4], ["broadleaf", 5], ["birch", 6], ["birch", 7], ["conifer", 6], ["conifer", 7],
  ["conifer", 8], ["conifer", 9], ["conifer", 10], ["palm", 6], ["palm", 7]];
export const ATLAS = { cols: 6, rows: 2, wide: 5.2, tall: 13, foot: 0.4 };
export const slotOf = (kind, height) => SLOTS.findIndex((s) => s[0] === kind && s[1] === height);

/** The mesher's place hash, in [0, 1): a tree's turn, size and phase are read from it (land-mesher placeTree), and the
 *  far tree reads the same numbers so it is the model's own picture at the model's own turn and size. */
export function hash3(a, b, c) { let h = Math.imul(a, 374761393) ^ Math.imul(b, 668265263) ^ Math.imul(c, 2147483647); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
/** A tree's turn (radians) and size, as land-mesher placeTree gives them to its model. */
export const treeTurn = (face, wu, wv) => hash3(wv, face, wu) * Math.PI * 2;
export const treeSize = (face, wu, wv) => 0.9 + 0.1 * hash3(wu + 3, wv, face);

/** The far trees of tile (tu, tv) of `face` (columns tu*TILE .. in that face's own frame, past its edge the neighbour's):
 *  { n trees, anchor (world metres), pos (each vertex's ROOT, from the anchor), off (the vertex from its root), nor,
 *  uv (the atlas), root (the root's chunk: cu, cv in `face`'s frame), col (the tree's own shade), idx } — eight vertices
 *  a tree, its four triangles indexed from both sides (the material draws front faces only and never flips a normal) —
 *  or { n: 0 } where none grows. */
export function forestTile(face, tu, tv) {
  const u0 = tu * TILE, v0 = tv * TILE, anchor = posOf(face, u0 + TILE / 2, v0 + TILE / 2, SEA);
  const roots = treeRoots(face, u0, v0, TILE).filter((r) => slotOf(r.tree.kind, r.tree.height) >= 0), n = roots.length;
  if (!n) return { n: 0 };
  const pos = new Float32Array(n * 24), off = new Float32Array(n * 24), nor = new Float32Array(n * 24), col = new Float32Array(n * 24);
  const uv = new Float32Array(n * 16), root = new Float32Array(n * 16), idx = n * 8 > 65535 ? new Uint32Array(n * 24) : new Uint16Array(n * 24);
  const { cols, rows, wide, tall, foot } = ATLAS;
  for (let i = 0; i < n; i++) {
    const r = roots[i], slot = slotOf(r.tree.kind, r.tree.height), cx = slot % cols, cy = Math.floor(slot / cols);
    const p = posOf(face, r.u + 0.5, r.v + 0.5, r.col.height), fr = frameOf(face, r.u + 0.5, r.v + 0.5);
    const turn = treeTurn(r.face, r.wu, r.wv), sc = treeSize(r.face, r.wu, r.wv), shade = 0.86 + 0.24 * hash3(r.wu, r.wv, r.face + 11);
    for (let q = 0; q < 2; q++) {
      // card 0 lies along the model's own x (the picture was taken across it), card 1 square to it
      const a = turn + q * Math.PI / 2, ca = Math.cos(a), sa = Math.sin(a);
      const ax = [fr.east[0] * ca + fr.north[0] * sa, fr.east[1] * ca + fr.north[1] * sa, fr.east[2] * ca + fr.north[2] * sa];
      for (let c = 0; c < 4; c++) {
        const s = c & 1 ? 1 : -1, top = c >> 1, k = (i * 8 + q * 4 + c) * 3, k2 = (i * 8 + q * 4 + c) * 2;
        const side = s * wide / 2 * sc, up = (top ? tall - foot : -foot) * sc;
        for (let d = 0; d < 3; d++) {
          pos[k + d] = p[d] - anchor[d];
          off[k + d] = ax[d] * side + fr.up[d] * up;
          col[k + d] = shade;
        }
        // a crown takes the light as a round thing does: its sides face outward, its top the sky
        const nx = ax[0] * s * 0.75 + fr.up[0] * (top ? 0.8 : 0.35), ny = ax[1] * s * 0.75 + fr.up[1] * (top ? 0.8 : 0.35), nz = ax[2] * s * 0.75 + fr.up[2] * (top ? 0.8 : 0.35), nl = Math.hypot(nx, ny, nz);
        nor[k] = nx / nl; nor[k + 1] = ny / nl; nor[k + 2] = nz / nl;
        uv[k2] = (cx + (s + 1) / 2) / cols; uv[k2 + 1] = (cy + top) / rows;
        root[k2] = Math.floor(r.u / CHUNK); root[k2 + 1] = Math.floor(r.v / CHUNK);
      }
      const b = i * 8 + q * 4, o = (i * 2 + q) * 12;
      idx.set([b, b + 1, b + 3, b, b + 3, b + 2, b, b + 3, b + 1, b, b + 2, b + 3], o);
    }
  }
  return { n, anchor, pos, off, nor, uv, root, col, idx };
}
