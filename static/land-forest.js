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
import { CHUNK, SEA, posOf, frameOf, treeRoots, column, wrap } from "./land-world.js";
import { ADAPT, drawnTop } from "./land-species.js";

export const TILE = 256;                         // columns along a forest tile's edge (16 chunks)
/** The atlas: one slot per (kind, height) treeAt can name, left to right then UP — uv (0, 0) is slot 0's bottom-left. A
 *  slot is `wide` x `tall` metres of the model seen from its side, its root's ground `foot` above the slot's bottom. */
export const SLOTS = [["broadleaf", 4], ["broadleaf", 5], ["birch", 6], ["birch", 7], ["conifer", 6], ["conifer", 7],
  ["conifer", 8], ["conifer", 9], ["conifer", 10], ["palm", 6], ["palm", 7]];
// wide 13 (2026-11-25, was 9.2): a broadleaf's drawn crown reaches 2 x REACH x REACH_SCALE = 12.7 m across (land-trees clampR),
// so a 9.2 m cell cut every far broadleaf to a column 2.5 times taller than wide — the vale's woods a wall of narrow crowns
// beside the Chlorophyll shot's round ones, where the near model is 1.4 to 1. The cell now holds the widest crown drawn.
export const ATLAS = { cols: 6, rows: 2, wide: 13, tall: 22, foot: 0.4 };   // (5.2 x 13 until the trees were drawn taller than their cells, #210)
export const slotOf = (kind, height) => SLOTS.findIndex((s) => s[0] === kind && s[1] === height);

/** The mesher's place hash, in [0, 1): a tree's turn, size and phase are read from it (land-mesher placeTree), and the
 *  far tree reads the same numbers so it is the model's own picture at the model's own turn and size. */
export function hash3(a, b, c) { let h = Math.imul(a, 374761393) ^ Math.imul(b, 668265263) ^ Math.imul(c, 2147483647); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
/** A tree's turn (radians) and size, as land-mesher placeTree gives them to its model. */
export const treeTurn = (face, wu, wv) => hash3(wv, face, wu) * Math.PI * 2;
// WILD BROADLEAVES ARE DRAWN BIGGER (operator 2026-11-25, "bigger wild broadleaves", wilderness only): the Chlorophyll shot's
// woods are 25-35 m trees whose rounded crowns read as masses; ours, drawn 17-20 m and packed ~5 m apart, read as a wall of
// spiky tops. A broadleaf is drawn WILD_BIG x larger in the wild — times wildMask, 1 deep in the wild and fading to 1x toward
// any owned plot, so owned ground looks as it did. Drawing only: the tree's cells (treeCell) are unchanged.
// INVARIANT (#183): the near model (land-mesher placeTree) and the far card both read this, with the same kind and mask.
export const WILD_BIG = 0.5;
export const treeSize = (face, wu, wv, kind = "", wild = 0) => (0.9 + 0.1 * hash3(wu + 3, wv, face)) * (kind === "broadleaf" ? 1 + WILD_BIG * wild : 1);
// THE WOOD'S MANTLE (2026-11-26, the Chlorophyll shot beside the vale: its woods are foliage down to the meadow, ours a
// palisade — a thin strip of crowns over a band of bare trunks as tall again, every broadleaf's lower 45 % (ADAPT.span0,
// which ties the drawn crown to the crown cells and so cannot move). A real wood's edge is closed by its mantle: shrubs and
// low-branched young trees that the side light keeps leafy to the ground. A wild broadleaf or birch toward its wood's edge
// (the less inside, the likelier; none deep in, where the edge hides it) gets two more crossed cards: the CROWN of its own
// picture, from the ground to its crown's base, turned 45° from its own, mirrored the other way and in shade. Drawn as a
// far tree only, wilderness only (times wildMask, like WILD_BIG), and gone with the tree at the handover to the model.
export const MANTLE = { kinds: ["broadleaf", "birch"], shade: 0.72, over: 1.1 };
export const mantleChance = (kind, col) => {
  if (!MANTLE.kinds.includes(kind)) return 0;
  const w = col.wild === undefined ? 0 : col.wild, inside = Math.min(1, Math.max(0, (col.woods - 0.12) / 0.25));
  return w * (1 - inside) ** 3;
};

/** The far trees of tile (tu, tv) of `face` (columns tu*TILE .. in that face's own frame, past its edge the neighbour's):
 *  { n trees, anchor (world metres), pos (each vertex's ROOT, from the anchor), off (the vertex from its root), nor,
 *  uv (the atlas), root (the root's chunk: cu, cv in `face`'s frame), col (the tree's own shade), idx } — eight vertices
 *  a tree, its four triangles indexed from both sides (the material draws front faces only and never flips a normal) —
 *  or { n: 0 } where none grows. */
export function forestTile(face, tu, tv) {
  const u0 = tu * TILE, v0 = tv * TILE, anchor = posOf(face, u0 + TILE / 2, v0 + TILE / 2, SEA);
  const roots = treeRoots(face, u0, v0, TILE).filter((r) => slotOf(r.tree.kind, r.tree.height) >= 0), n = roots.length;
  if (!n) return { n: 0 };
  const mant = roots.map((r) => hash3(r.wv + 41, r.wu + 7, r.face) < mantleChance(r.tree.kind, r.col)), nm = mant.filter(Boolean).length, q8 = n + nm;
  const pos = new Float32Array(q8 * 24), off = new Float32Array(q8 * 24), nor = new Float32Array(q8 * 24), col = new Float32Array(q8 * 24);
  const uv = new Float32Array(q8 * 16), root = new Float32Array(q8 * 16), idx = q8 * 8 > 65535 ? new Uint32Array(q8 * 24) : new Uint16Array(q8 * 24);
  const { cols, rows, wide, tall, foot } = ATLAS;
  // two crossed cards (8 vertices, both faces indexed) for card i: horizontal reach `half` along turn `a0`, from `lo` to `hi`
  // metres above the root, showing the slot's picture between rows v0 and v1 (fractions of the slot), lit as a crown
  const cards = (i, p, fr, a0, half, lo, hi, cx, cy, v0, v1, mir, shade, r) => {
    for (let q = 0; q < 2; q++) {
      // card 0 lies along the model's own x (the picture was taken across it), card 1 square to it
      const a = a0 + q * Math.PI / 2, ca = Math.cos(a), sa = Math.sin(a);
      const ax = [fr.east[0] * ca + fr.north[0] * sa, fr.east[1] * ca + fr.north[1] * sa, fr.east[2] * ca + fr.north[2] * sa];
      for (let c = 0; c < 4; c++) {
        const s = c & 1 ? 1 : -1, top = c >> 1, k = (i * 8 + q * 4 + c) * 3, k2 = (i * 8 + q * 4 + c) * 2;
        const side = s * half, up = top ? hi : lo;
        for (let d = 0; d < 3; d++) {
          pos[k + d] = p[d] - anchor[d];
          off[k + d] = ax[d] * side + fr.up[d] * up;
          col[k + d] = shade;
        }
        // a crown takes the light as a round thing does: its sides face outward, its top the sky
        const nx = ax[0] * s * 0.75 + fr.up[0] * (top ? 0.8 : 0.35), ny = ax[1] * s * 0.75 + fr.up[1] * (top ? 0.8 : 0.35), nz = ax[2] * s * 0.75 + fr.up[2] * (top ? 0.8 : 0.35), nl = Math.hypot(nx, ny, nz);
        nor[k] = nx / nl; nor[k + 1] = ny / nl; nor[k + 2] = nz / nl;
        uv[k2] = (cx + (s * mir + 1) / 2) / cols; uv[k2 + 1] = (cy + (top ? v1 : v0)) / rows;
        root[k2] = Math.floor(r.u / CHUNK); root[k2 + 1] = Math.floor(r.v / CHUNK);
      }
      const b = i * 8 + q * 4, o = (i * 2 + q) * 12;
      idx.set([b, b + 1, b + 3, b, b + 3, b + 2, b, b + 3, b + 1, b, b + 2, b + 3], o);
    }
  };
  for (let i = 0, j = n; i < n; i++) {
    const r = roots[i], slot = slotOf(r.tree.kind, r.tree.height), cx = slot % cols, cy = Math.floor(slot / cols);
    const p = posOf(face, r.u + 0.5, r.v + 0.5, r.col.height), fr = frameOf(face, r.u + 0.5, r.v + 0.5);
    const turn = treeTurn(r.face, r.wu, r.wv), sc = treeSize(r.face, r.wu, r.wv, r.tree.kind, r.col.wild === undefined ? 0 : r.col.wild), shade = 0.86 + 0.24 * hash3(r.wu, r.wv, r.face + 11);
    // NOT ONE CUT-OUT REPEATED (the Chlorophyll shot, 2026-11-22: a row of far trees read as identical cards — 12 pictures,
    // each always the same way round, sizes within 10 %): half the trees show their picture mirrored, and each crown is
    // 0.85-1.15 its picture's width. The CARD's own: treeSize (shared with the near model) and the height are untouched,
    // so a tree is as tall as a card as it is as a model at the handover.
    const mir = hash3(r.wv + 5, r.wu, r.face + 19) < 0.5 ? -1 : 1, wid = 0.85 + 0.3 * hash3(r.wu + 9, r.wv + 2, r.face);
    cards(i, p, fr, turn, wide / 2 * sc * wid, -foot * sc, (tall - foot) * sc, cx, cy, 0, 1, mir, shade, r);
    if (mant[i]) {
      // the mantle: the crown's part of the picture (from its base, span0 of the drawn tree, to the slot's top), from the
      // ground to a little over the crown's base, so it closes the trunk band under this tree's own crown
      const base = ADAPT[r.tree.kind].span0 * drawnTop(r.tree.kind, r.tree.height), v0 = (foot + base) / tall;
      cards(j++, p, fr, turn + Math.PI / 4, wide / 2 * sc * wid, -foot * sc, base * MANTLE.over * sc, cx, cy, v0, 1, -mir, shade * MANTLE.shade, r);
    }
  }
  return { n, mantle: nm, anchor, pos, off, nor, uv, root, col, idx };
}

// THE CANOPY BEYOND THE TREES (the Chlorophyll bar, operator 2026-11-21: a meadow under hills covered in forest to the
// horizon; its engine draws a far tile "as one aggregate" once a tree is a few pixels). The card trees above reach
// FOREST_RANGE (1.15 km); past them the hills were bare ground to the fog (2.9 km) — the band where the reference's
// forests are. A canopy tile is ONE heightfield over a forest tile, CANOPY_STEP metres a cell: a vertex in forest stands
// at the crown tops its climate grows (the same species rule as treeAt: conifers cold or high, birch and conifer in the
// cool, broadleaf and birch in the mild), thinner toward the forest's edge, with a crown's bump; a vertex out of the
// forest sinks under the ground, so a forest's edge is a wall down to the meadow as a real tree line is. It is drawn from
// the planet's forest field, not tree by tree: at this distance a tree is a few pixels and the field is what reads.
export const CANOPY_STEP = 8;                    // metres a cell — a design choice (a crown is 3-5 m; a cell is ~2 px at 2 km)
// A CANOPY TILE IS 1,024 m (four forest tiles a side): at one forest tile (256 m) the band from the card trees' reach to the
// far ground's edge took ~75 meshes, a draw call each, and a page drawing in software slowed enough that a flown craft's
// engine reports (sent from the frame) fell behind (the pilot walk, 2026-11-22). Sixteen times the area a mesh: ~6-9 draws.
export const CANOPY_TILE = 1024;
/** Crown-top height over the ground (m) where `col` is forest, or 0: the mean of what treeAt grows there, times how far
 *  inside the forest it stands (its density), at least half — and a lone meadow tree is too sparse to make canopy. */
export function canopyHeight(col) {
  if (col.top <= SEA) return 0;
  if (col.biome === "snow") return col.wet > 0 ? 8.5 * 2.0 * 0.7 : 0;           // taiga where it is wet (treeAt: conifers 6-9, drawn x2)
  if (col.biome !== "forest") return 0;
  const cold = col.temp < -0.12 || col.top > SEA + 60, cool = col.temp < 0.05;
  // treeAt's species and heights averaged by their shares, times their DRAWN scale (land-species.js: the trees are drawn
  // taller than their cells, #210): cold 80 % conifer x2 + 20 % birch x2.2; cool 30/30/40 conifer/birch/broadleaf; mild
  // 18 % birch, 82 % broadleaf x3
  const mean = cold ? 8.0 * 2.04 : cool ? 6.6 * 2.46 : 5.0 * 2.86;
  const inside = Math.min(1, Math.max(0, (col.woods - 0.12) / 0.25));
  return mean * (0.55 + 0.45 * inside);
}
/** The canopy of CANOPY_TILE tile (tu, tv) of `face`: { n cells drawn, anchor, pos (from the anchor), col (shade), idx } or { n: 0 }. */
export function canopyTile(face, tu, tv) {
  const T = CANOPY_TILE, S = CANOPY_STEP, N = T / S, u0 = tu * T, v0 = tv * T, anchor = posOf(face, u0 + T / 2, v0 + T / 2, SEA);
  const H = new Float32Array((N + 1) * (N + 1)), G = new Float32Array((N + 1) * (N + 1));
  let any = false;
  for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
    const u = u0 + i * S, v = v0 + j * S, w = wrap(face, u, v), c = column(w.face, w.u, w.v), k = j * (N + 1) + i;
    G[k] = c.height; H[k] = canopyHeight(c); if (H[k] > 0) any = true;
  }
  if (!any) return { n: 0 };
  const pos = new Float32Array((N + 1) * (N + 1) * 3), col = new Float32Array((N + 1) * (N + 1) * 3), idx = [];
  for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
    const k = j * (N + 1) + i, u = u0 + i * S, v = v0 + j * S, r = hash3(u, v, face + 31);
    // a crown's bump: up to 40 % of the height up or down, so the top reads as many crowns, not a lawn
    const h = H[k] > 0 ? G[k] + H[k] * (0.8 + 0.4 * r) : G[k] - 3;
    const p = posOf(face, u, v, h);
    pos[k * 3] = p[0] - anchor[0]; pos[k * 3 + 1] = p[1] - anchor[1]; pos[k * 3 + 2] = p[2] - anchor[2];
    const sh = 0.8 + 0.35 * hash3(v, u, face + 7);                               // each crown its own shade
    col[k * 3] = sh; col[k * 3 + 1] = sh; col[k * 3 + 2] = sh;
  }
  let n = 0;
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const a = j * (N + 1) + i, b = a + 1, c = a + N + 1, d = c + 1;
    if (!(H[a] > 0 || H[b] > 0 || H[c] > 0 || H[d] > 0)) continue;
    idx.push(a, b, d, a, d, c); n++;
  }
  return { n, anchor, pos, col, idx: (N + 1) * (N + 1) > 65535 ? new Uint32Array(idx) : new Uint16Array(idx) };
}
