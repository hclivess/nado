// land-mesher.js — the Land planet's chunk mesher (a module Web Worker of static/land.js): a 16^3 chunk of the cube-
// sphere in, its triangles out, built off the main thread so walking never stutters on terrain generation.
//
// THE GROUND IS SMOOTH, WHAT PEOPLE BUILD IS CRISP ("it should not really be blocky", operator 2026-11-06). Three kinds
// of geometry come out of one chunk of cells:
//   smooth — the natural ground (land-world NATURAL) as the zero surface of land-world.fieldOf, by Surface Nets: one
//            vertex per cell-corner cube the surface crosses, placed at the mean of the crossings on its edges, with the
//            field's gradient as its normal; coloured by material and slope (grass on the flat, earth and rock on the
//            steep, snow that slides off cliffs).
//   bark, foliage — every tree as a model (land-trees.js): trunk, limbs and alpha leaf cards, weighted for the wind,
//            less every part whose cell was taken, so the picture never shows wood or leaves that are gone. A leaf cell
//            outside a tree (placed) is a small cluster of cards; a log cell outside one is a round segment (`trees`).
//   solid  — built materials (planks, brick, tiles, wool…) as crisp textured cubes, culled against crisp neighbours and
//            against ground that buries them.
//   clear  — glass, ice and the sea's surface.
// The cells are the data either way: the commitment, the server and the API never see this difference.
//
// A chunk is (face, cu, cv, ch): columns u in [cu*16, cu*16+16), v likewise, layers [ch*16, ch*16+16) — one plot's columns.
// Cells are generated with a one-cell border (wrapped across face seams by land-world.wrap). A surface edge is drawn by
// the chunk that holds its LOWER cell, so every edge of the world belongs to exactly one chunk (no gaps, no doubles).
// Positions are metres RELATIVE TO THE CHUNK'S ANCHOR; the page places each mesh at anchor - camera in doubles.
import { CHUNK, H, R0, W, B, BLOCKS, ATLAS_TILES, NATURAL, CM, TREE_WOOD, TREE_LEAVES, isTree, opaque, dirOf, frameOf, wrap, column, terrainBlock, fieldOf, treeAt, treeCell } from "./land-world.js";
import { treeModel, leafCellModel } from "./land-trees.js";

const N = CHUNK + 2;                                     // cells with the border: real index r in -1..16 is r + 1
const TILE_COLS = 8;                                      // the atlas is TILE_COLS tiles across (static/land.js paints it)
const TILE_ROWS = Math.ceil(ATLAS_TILES / TILE_COLS);
const EU = 0.5 / (16 * TILE_COLS), EV = 0.5 / (16 * TILE_ROWS);   // half a texel of the 16 px tiles
const crisp = (b) => b !== B.air && !NATURAL.has(b) && !isTree(b) && !BLOCKS[b].liquid;

// crisp-cube faces: neighbour offset, the quad's corners as (u, v, h) offsets, a light factor, the atlas tile (0 top, 1 side, 2 bottom)
const DIRS = [
  { d: [0, 0, 1], c: [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], shade: 1.0, t: 0 },
  { d: [0, 0, -1], c: [[0, 1, 0], [1, 1, 0], [1, 0, 0], [0, 0, 0]], shade: 0.5, t: 2 },
  { d: [1, 0, 0], c: [[1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 0, 1]], shade: 0.8, t: 1 },
  { d: [-1, 0, 0], c: [[0, 1, 0], [0, 0, 0], [0, 0, 1], [0, 1, 1]], shade: 0.8, t: 1 },
  { d: [0, 1, 0], c: [[1, 1, 0], [0, 1, 0], [0, 1, 1], [1, 1, 1]], shade: 0.65, t: 1 },
  { d: [0, -1, 0], c: [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], shade: 0.65, t: 1 },
];

// the ground's colours, written as sRGB (what an artist picks) and turned linear below — vertex colours are LINEAR to the
// renderer, and sRGB values read as linear came out washed pale (the first smooth render, 2026-11-06)
const C = { bark: [0.36, 0.25, 0.15], birch: [0.88, 0.86, 0.80] };
for (const k in C) C[k] = C[k].map((x) => Math.pow(x, 2.2));
function hash3(a, b, c) { let h = Math.imul(a, 374761393) ^ Math.imul(b, 668265263) ^ Math.imul(c, 2147483647); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
// THE GROUND'S MATERIALS ("Realistic (PBR)", operator 2026-11-06): each ground vertex carries blend weights for six real
// textures (static/vendor/textures: grass, earth, rock, sand, snow, gravel) from its material and its slope — grass on
// the flat gives way to earth and then rock as it steepens, snow slides off cliffs — and static/land.js's ground node
// material mixes them. The vertex colour is only a faint per-place grain on top.
const smoothstep = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
function groundWeights(b, up) {
  const w = [0, 0, 0, 0, 0, 0];                          // grass, dirt, rock, sand, snow, gravel
  const steep = smoothstep(0.62, 0.38, up);              // 1 on a cliff, 0 on the flat
  if (b === B.grass) { const g = smoothstep(0.62, 0.85, up); w[0] = g; w[1] = 1 - g; }
  else if (b === B.dirt) w[1] = 1;
  else if (b === B.sand) w[3] = 1;
  else if (b === B.snow) w[4] = 1;
  else if (b === B.gravel) w[5] = 1;
  else w[2] = 1;                                         // stone, basalt, bedrock
  for (let i = 0; i < 6; i++) if (i !== 2) w[i] *= 1 - steep;
  w[2] += steep * (b === B.sand ? 0.5 : 1);
  const n = w.reduce((a, x) => a + x, 0) || 1;
  return w.map((x) => x / n);
}
const groundGrain = (b, up, u, v, h) => { const j = 0.9 + 0.2 * hash3(u, v, h); return [j, j, j]; };

/** The chunk's cells with the border: block ids and the ground field, index ((k * N) + j) * N + i. */
function cells(face, cu, cv, ch, edits) {
  const u0 = cu * CHUNK - 1, v0 = cv * CHUNK - 1, h0 = ch * CHUNK - 1;
  const cols = new Map();                                 // numeric keys: a string key per lookup cost more than the noise
  const colCache = (f, u, v) => { const k = (f * 131072 + u) * 131072 + v; let c = cols.get(k); if (!c) { c = column(f, u, v); cols.set(k, c); } return c; };
  const blk = new Uint8Array(N * N * N), fld = new Float32Array(N * N * N);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const w = wrap(face, u0 + i, v0 + j), col = colCache(w.face, w.u, w.v);
    for (let k = 0; k < N; k++) {
      const h = h0 + k, x = (k * N + j) * N + i;
      const e = edits ? edits.get(w.face + ":" + w.u + ":" + w.v + ":" + h) : undefined;
      blk[x] = e !== undefined ? e : h < 0 ? B.bedrock : h >= H ? B.air : terrainBlock(w.face, w.u, w.v, h, colCache);
      fld[x] = h < 0 ? 1 : h >= H ? -1 : fieldOf(col, h, e);
    }
  }
  return { blk, fld, colCache };
}

// ---- built pieces: boxes at 1 cm (land-world.js BOXES) ------------------------------------------------------------
// Every piece is up to six textured quads, its texture tiling per METRE (uv in metres + the material's atlas tile as an
// attribute; static/land.js's node material takes fract(uv) inside the tile), so a 2 cm peg shows 2 cm of grain, not a
// squeezed tile. Performance (the operator asked, 2026-11-06): one merged mesh per chunk; a face wholly covered by a
// touching opaque piece is not drawn (a wall of flush planks is its outer skin, not every plank's six faces); a chunk the
// page marks far (lod 2) skips pieces whose largest side is under LOD_SKIP_CM — detail costs nothing at a distance.
const LOD_SKIP_CM = 20;
// axis and sign of each face. No baked shade: pieces are lit by the real sun and sky (a fixed per-face darkening on top of
// that, as the cube cells once had, turned a wall in its own shadow black — the first house render, 2026-11-06)
const BOX_FACES = [{ ax: 2, s: 1 }, { ax: 2, s: -1 }, { ax: 0, s: 1 }, { ax: 0, s: -1 }, { ax: 1, s: 1 }, { ax: 1, s: -1 }];
function meshBoxes(boxes, u0, v0, h0, place, solid, clear, lod) {
  const lo = h0 * CM, hi = (h0 + CHUNK) * CM;
  const mine = boxes.filter((b) => b[2] < hi && b[2] + b[5] > lo && !(lod >= 2 && Math.max(b[3], b[4], b[5]) < LOD_SKIP_CM));
  if (!mine.length) return;
  // neighbours by 1 m bucket, for the covered-face test
  const idx = new Map(), bk = (i, j, k) => (i * 64 + j) * 4096 + k;
  for (const b of boxes) for (let i = Math.floor(b[0] / CM); i <= Math.floor((b[0] + b[3] - 1) / CM); i++)
    for (let j = Math.floor(b[1] / CM); j <= Math.floor((b[1] + b[4] - 1) / CM); j++)
      for (let k = Math.floor(b[2] / CM); k <= Math.floor((b[2] + b[5] - 1) / CM); k++) {
        const key = bk(i, j, k); let l = idx.get(key); if (!l) idx.set(key, l = []); l.push(b);
      }
  const covered = (b, ax, s) => {
    // the face's plane and rectangle (in the other two axes); a touching opaque piece whose opposite face spans it hides it
    const plane = s > 0 ? b[ax] + b[ax + 3] : b[ax], o = [0, 1, 2].filter((a) => a !== ax);
    const cell = [0, 0, 0];
    cell[ax] = Math.floor((s > 0 ? plane : plane - 1) / CM);
    cell[o[0]] = Math.floor(b[o[0]] / CM); cell[o[1]] = Math.floor(b[o[1]] / CM);
    for (const n of idx.get(bk(cell[0], cell[1], cell[2])) || []) {
      if (n === b || !opaque(n[6]) || BLOCKS[n[6]].see) continue;
      if ((s > 0 ? n[ax] : n[ax] + n[ax + 3]) !== plane) continue;
      if (n[o[0]] <= b[o[0]] && n[o[0]] + n[o[0] + 3] >= b[o[0]] + b[o[0] + 3] && n[o[1]] <= b[o[1]] && n[o[1]] + n[o[1] + 3] >= b[o[1]] + b[o[1] + 3]) return true;
    }
    return false;
  };
  for (const b of mine) {
    const info = BLOCKS[b[6]], buf = !opaque(b[6]) ? clear : solid;
    const y0 = Math.max(b[2], lo), y1 = Math.min(b[2] + b[5], hi);          // this chunk's slice of the piece
    const mn = [b[0], b[1], y0], mx = [b[0] + b[3], b[1] + b[4], y1];
    for (const F of BOX_FACES) {
      if (F.ax === 2 && F.s > 0 && b[2] + b[5] > hi) continue;              // its top is in the chunk above
      if (F.ax === 2 && F.s < 0 && b[2] < lo) continue;                     // its bottom is in the chunk below
      if (covered(b, F.ax, F.s)) continue;
      const o = [0, 1, 2].filter((a) => a !== F.ax), base = buf.n;
      const tile = info.tex[F.ax === 2 ? (F.s > 0 ? 0 : 2) : 1];
      // corners counter-clockwise seen from outside: (o0, o1) around the face, flipped for the negative side
      const ring = F.s > 0 ? [[0, 0], [1, 0], [1, 1], [0, 1]] : [[0, 0], [0, 1], [1, 1], [1, 0]];
      const ordered = (F.ax === 1) ? ring.map(([a, c]) => [c, a]) : ring;   // keep the winding right-handed for the v axis
      for (const [a, c] of ordered) {
        const q = [0, 0, 0];
        q[F.ax] = F.s > 0 ? mx[F.ax] : mn[F.ax];
        q[o[0]] = a ? mx[o[0]] : mn[o[0]]; q[o[1]] = c ? mx[o[1]] : mn[o[1]];
        const p = place(u0 + q[0] / CM, v0 + q[1] / CM, q[2] / CM);
        buf.pos.push(p[0], p[1], p[2]);
        buf.uv.push(q[o[0]] / CM, q[o[1]] / CM);                           // metres: the texture tiles once per metre
        buf.tile.push(tile);
        const sh = info.glow ? 1.6 : 1;
        buf.col.push(sh, sh, sh);
      }
      const P = buf.pos, k = base * 3;
      const e1 = [P[k + 3] - P[k], P[k + 4] - P[k + 1], P[k + 5] - P[k + 2]], e2 = [P[k + 9] - P[k], P[k + 10] - P[k + 1], P[k + 11] - P[k + 2]];
      let nx = e1[1] * e2[2] - e1[2] * e2[1], ny = e1[2] * e2[0] - e1[0] * e2[2], nz = e1[0] * e2[1] - e1[1] * e2[0];
      const nl = Math.hypot(nx, ny, nz) || 1;
      for (let c = 0; c < 4; c++) buf.nor.push(nx / nl, ny / nl, nz / nl);
      buf.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
      buf.n += 4;
    }
  }
}

/** Mesh one chunk: { anchor, smooth (the ground), trees, solid, clear, pieces, glassy, grass } or { empty }. `boxes`:
 *  the plot's built pieces (land-world BOXES); `lod`: 0 near (grass and every piece), 1 middle (every piece), 2 far
 *  (pieces under LOD_SKIP_CM skipped). */
export function meshChunk(face, cu, cv, ch, edits, boxes, lod) {
  const h0 = ch * CHUNK;
  if ((!edits || edits.size === 0) && !(boxes && boxes.length)) {   // wholly above the ground, the trees and the sea: air
    let hi = 0;
    for (const [du, dv] of [[0, 0], [CHUNK, 0], [0, CHUNK], [CHUNK, CHUNK], [CHUNK / 2, CHUNK / 2]]) {
      const w = wrap(face, cu * CHUNK + du, cv * CHUNK + dv);
      hi = Math.max(hi, column(w.face, w.u, w.v).top);
    }
    if (h0 > hi + 16 && h0 > 100) return { empty: true };
  }
  const { blk, fld, colCache } = cells(face, cu, cv, ch, edits);
  const at = (i, j, k) => blk[((k + 1) * N + (j + 1)) * N + (i + 1)];
  const u0 = cu * CHUNK, v0 = cv * CHUNK;
  const anchor = dirOf(face, u0, v0).map((x) => x * (R0 + h0));
  const fr = frameOf(face, u0 + CHUNK / 2, v0 + CHUNK / 2);   // the chunk's local frame: gradients become world normals
  const place = (gu, gv, gh) => { const d = dirOf(face, gu, gv), r = R0 + gh; return [d[0] * r - anchor[0], d[1] * r - anchor[1], d[2] * r - anchor[2]]; };
  const smooth = mk(), trees = mk(), solid = mk(), clear = mk();

  // ---- the smooth surfaces: Surface Nets over a field sampled at cell centres -----------------------------------
  function nets(F, colourOf, out, isMat = (b) => NATURAL.has(b), extra = null) {
    // cubes are indexed by their min-corner cell, real -1..15 (padded 0..16); a cube's vertex sits where F crosses 0
    const S = N - 1, vid = new Int32Array(S * S * S).fill(-1);
    const f = (pi, pj, pk) => F[(pk * N + pj) * N + pi];
    const E = [[0, 0, 0, 1, 0, 0], [0, 1, 0, 1, 1, 0], [0, 0, 1, 1, 0, 1], [0, 1, 1, 1, 1, 1], [0, 0, 0, 0, 1, 0], [1, 0, 0, 1, 1, 0],
      [0, 0, 1, 0, 1, 1], [1, 0, 1, 1, 1, 1], [0, 0, 0, 0, 0, 1], [1, 0, 0, 1, 0, 1], [0, 1, 0, 0, 1, 1], [1, 1, 0, 1, 1, 1]];
    for (let pk = 0; pk < S; pk++) for (let pj = 0; pj < S; pj++) for (let pi = 0; pi < S; pi++) {
      let pos = 0, neg = 0;
      for (let c = 0; c < 8; c++) (f(pi + (c & 1), pj + ((c >> 1) & 1), pk + (c >> 2)) > 0 ? pos++ : neg++);
      if (!pos || !neg) continue;
      let sx = 0, sy = 0, sz = 0, n = 0;
      for (const [a0, b0, c0, a1, b1, c1] of E) {
        const fa = f(pi + a0, pj + b0, pk + c0), fb = f(pi + a1, pj + b1, pk + c1);
        if ((fa > 0) === (fb > 0)) continue;
        const t = fa / (fa - fb);
        sx += a0 + (a1 - a0) * t; sy += b0 + (b1 - b0) * t; sz += c0 + (c1 - c0) * t; n++;
      }
      // grid coordinates: padded cell p has its centre at real (p - 1) + 0.5
      const gu = u0 + pi - 0.5 + sx / n, gv = v0 + pj - 0.5 + sy / n, gh = h0 + pk - 0.5 + sz / n;
      // the gradient over the cube's 8 corners; the normal points out of the solid
      let gx = 0, gy = 0, gz = 0;
      for (let c = 0; c < 8; c++) {
        const val = f(pi + (c & 1), pj + ((c >> 1) & 1), pk + (c >> 2));
        gx += (c & 1 ? 1 : -1) * val; gy += ((c >> 1) & 1 ? 1 : -1) * val; gz += (c >> 2 ? 1 : -1) * val;
      }
      const gl = Math.hypot(gx, gy, gz) || 1;
      const nu = -gx / gl, nv = -gy / gl, nh = -gz / gl;
      const nw = [0, 1, 2].map((i) => nu * fr.east[i] + nv * fr.north[i] + nh * fr.up[i]);
      // the material: the highest NATURAL corner of the cube, whatever the field's sign there — the top layer (grass,
      // snow, sand) often sits just above the exact surface, and taking only solid corners coloured flat meadows as bare
      // earth (the dirt one layer down)
      let mat = B.stone, best = -1;
      for (let c = 0; c < 8; c++) {
        const ci = pi + (c & 1), cj = pj + ((c >> 1) & 1), ck = pk + (c >> 2), b = blk[(ck * N + cj) * N + ci];
        if (isMat(b) && ck > best) { best = ck; mat = b; }
      }
      const p = place(gu, gv, gh), col = colourOf(mat, nh, Math.floor(gu), Math.floor(gv), Math.floor(gh));
      vid[(pk * S + pj) * S + pi] = out.n;
      out.pos.push(p[0], p[1], p[2]); out.nor.push(nw[0], nw[1], nw[2]); out.col.push(col[0], col[1], col[2]);
      if (extra) extra(out, mat, nu, nv, nh, gu, gv, gh);
      out.n++;
    }
    // quads: one per cell-centre edge the surface crosses, joining the 4 cubes around it; only edges whose LOWER cell is
    // inside the chunk (real 0..15 on every axis), so neighbouring chunks never draw the same edge
    const V = (ri, rj, rk) => vid[((rk + 1) * S + (rj + 1)) * S + (ri + 1)];
    for (let rk = 0; rk < CHUNK; rk++) for (let rj = 0; rj < CHUNK; rj++) for (let ri = 0; ri < CHUNK; ri++) {
      const here = f(ri + 1, rj + 1, rk + 1) > 0;
      for (let ax = 0; ax < 3; ax++) {
        const there = ax === 0 ? f(ri + 2, rj + 1, rk + 1) > 0 : ax === 1 ? f(ri + 1, rj + 2, rk + 1) > 0 : f(ri + 1, rj + 1, rk + 2) > 0;
        if (here === there) continue;
        // the 4 cubes sharing this edge: offsets (0/-1) on the two other axes
        let q;
        if (ax === 0) q = [V(ri, rj - 1, rk - 1), V(ri, rj, rk - 1), V(ri, rj, rk), V(ri, rj - 1, rk)];
        else if (ax === 1) q = [V(ri - 1, rj, rk - 1), V(ri - 1, rj, rk), V(ri, rj, rk), V(ri, rj, rk - 1)];
        else q = [V(ri - 1, rj - 1, rk), V(ri, rj - 1, rk), V(ri, rj, rk), V(ri - 1, rj, rk)];
        if (q.some((x) => x < 0)) continue;
        if (here) out.idx.push(q[0], q[1], q[2], q[0], q[2], q[3]);
        else out.idx.push(q[0], q[2], q[1], q[0], q[3], q[2]);
      }
    }
  }
  // the ground: texture coordinates continuous across chunks (grid metres, folded every 4096 m — a whole number of
  // texture repeats, so the fold is seamless and float32 keeps centimetres), its grid-space normal for the rock's
  // three-way projection, and the material weights
  nets(fld, groundGrain, smooth, undefined, (o, mat, nu, nv, nh, gu, gv, gh) => {
    o.uvw.push(((gu % 4096) + 4096) % 4096, ((gv % 4096) + 4096) % 4096, gh);
    o.gn.push(nu, nv, nh);
    const w = groundWeights(mat, nh);
    o.w1.push(w[0], w[1], w[2], w[3]); o.w2.push(w[4], w[5]);
  });
  // ---- the forest: every tree is its model, less the parts whose cells were taken --------------------------------------
  // ("taking apart bushes creates blobs", operator 2026-11-06: a cut tree used to fall back to a smooth surface over its
  // leaf cells — a blob. Now the model stays and only what stood in a taken cell is left out: chop a leaf cell and those
  // leaves go, cut a log and that length of trunk goes.) Roots keep 2 columns from a plot edge and a chunk column IS a
  // plot, so every tree lies within its own chunk column; each chunk it spans masks its own cells (still the tree's), and
  // the chunk holding its root's ground layer draws the model — once.
  const modelled = new Uint8Array(N * N * N);
  const bark = mk(), foliage = mk();
  // roots up to 3 columns outside the chunk too: their crowns reach the one-cell border the cells are read over, and an
  // unmasked border cell was drawn a second time beside every neighbour's model (the first model render)
  for (let j = -3; j < CHUNK + 3; j++) for (let i = -3; i < CHUNK + 3; i++) {
    const gu = u0 + i, gv = v0 + j;
    if (gu < 0 || gv < 0 || gu >= W || gv >= W) continue;              // across a face seam: drawn from its cells there
    const col = colCache(face, gu, gv), t = treeAt(face, gu, gv, col);
    if (!t) continue;
    const span = t.height + 2;
    if (col.top + span < h0 - 1 || col.top > h0 + CHUNK) continue;
    for (let du = -2; du <= 2; du++) for (let dv = -2; dv <= 2; dv++) for (let dh = 1; dh <= span; dh++) {
      const pi = i + du + 1, pj = j + dv + 1, pk = col.top + dh - h0 + 1, b = treeCell(t, du, dv, dh);
      if (pi < 0 || pj < 0 || pk < 0 || pi >= N || pj >= N || pk >= N || !b) continue;
      const x = (pk * N + pj) * N + pi;
      if (blk[x] === b) modelled[x] = 1;                                   // still the tree's own cell
    }
    if (i < 0 || j < 0 || i >= CHUNK || j >= CHUNK || col.top < h0 || col.top >= h0 + CHUNK) continue;
    // a part of the model is left out when the cell it stands in was one of this tree's and an edit has taken it
    const gone = (cu, cv, ch) => {
      const b = treeCell(t, cu - gu, cv - gv, ch - col.top);
      if (!b || !edits) return false;
      const e = edits.get(face + ":" + cu + ":" + cv + ":" + ch);
      return e !== undefined && e !== b;
    };
    placeTree(t, face, gu, gv, col.height, lod, place, bark, foliage, gone);
  }
  // leaves a player PLACED (or a tree's leaf cell put back into another spot): a small cluster of leaf cards in the cell,
  // in its species' tile — never a surface (the blob)
  for (let k = 0; k < CHUNK; k++) for (let j = 0; j < CHUNK; j++) for (let i = 0; i < CHUNK; i++) {
    const x = ((k + 1) * N + (j + 1)) * N + (i + 1), b = blk[x];
    if (!TREE_LEAVES.has(b) || modelled[x]) continue;
    const tile = b === B.needles ? 2 : b === B.fronds ? 3 : 0, gu = u0 + i, gv = v0 + j, gh = h0 + k;
    placeModel(leafCellModel(tile), face, gu + 0.5, gv + 0.5, gh + 0.5, hash3(gu, gh, gv) * 6.283, 1, hash3(gv, gu, gh) * 6.283,
               place, bark, foliage, null);
  }

  // ---- trunks: every log cell is a round segment (octagonal, tapering as it rises) -----------------------------------
  for (let k = 0; k < CHUNK; k++) for (let j = 0; j < CHUNK; j++) for (let i = 0; i < CHUNK; i++) {
    const wood = at(i, j, k);
    if (!TREE_WOOD.has(wood) || modelled[((k + 1) * N + (j + 1)) * N + (i + 1)]) continue;
    const slim = wood === B.birchlog ? 0.7 : 1, bark = wood === B.birchlog ? C.birch : C.bark;
    const below = at(i, j, k - 1) === wood, r0 = (below ? 0.30 : 0.36) * slim, r1 = (at(i, j, k + 1) === wood ? 0.30 : 0.26) * slim;
    const cu0 = u0 + i + 0.5, cv0 = v0 + j + 0.5, hb = h0 + k - (below ? 0 : 0.4), ht = h0 + k + 1;
    const base = trees.n;
    for (let s = 0; s < 8; s++) {
      const a = (s / 8) * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
      for (const [hh, rr] of [[hb, r0], [ht, r1]]) {
        const p = place(cu0 + ca * rr, cv0 + sa * rr, hh);
        trees.pos.push(p[0], p[1], p[2]);
        trees.nor.push(...[0, 1, 2].map((x) => ca * fr.east[x] + sa * fr.north[x]));
        const g = 0.85 + 0.2 * hash3(s, k, i * 31 + j);
        trees.col.push(bark[0] * g, bark[1] * g, bark[2] * g);
        trees.n++;
      }
    }
    for (let s = 0; s < 8; s++) {
      const a = base + s * 2, b = base + ((s + 1) % 8) * 2;
      trees.idx.push(a, b, b + 1, a, b + 1, a + 1);
    }
  }

  // ---- crisp cubes: what people build, and glass, ice and the sea -------------------------------------------------
  const fAt = (i, j, k) => fld[((k + 1) * N + (j + 1)) * N + (i + 1)];
  for (let k = 0; k < CHUNK; k++) for (let j = 0; j < CHUNK; j++) for (let i = 0; i < CHUNK; i++) {
    const b = at(i, j, k);
    if (!crisp(b) && !BLOCKS[b].liquid) continue;
    const info = BLOCKS[b], isClear = !opaque(b);
    for (let f = 0; f < 6; f++) {
      const D = DIRS[f], ni = i + D.d[0], nj = j + D.d[1], nk = k + D.d[2], n = at(ni, nj, nk);
      if (info.liquid) {                                  // the sea draws its surface only, where air is above
        if (f !== 0 || n !== B.air || fAt(ni, nj, nk) > 0) continue;
      } else {
        if (crisp(n) && opaque(n)) continue;              // behind another built block
        if (n === b && (b === B.glass || b === B.ice)) continue;
        if (fAt(ni, nj, nk) > 0.25) continue;             // buried in the ground
      }
      const buf = isClear ? clear : solid, tile = info.tex[D.t];
      const tu = (tile % TILE_COLS) / TILE_COLS, tv = 1 - (Math.floor(tile / TILE_COLS) + 1) / TILE_ROWS;
      const base = buf.n;
      for (let c = 0; c < 4; c++) {
        const [ci, cj, ck] = D.c[c];
        const p = place(u0 + i + ci, v0 + j + cj, h0 + k + ck - (info.liquid && ck === 1 ? 0.12 : 0));
        buf.pos.push(p[0], p[1], p[2]);
        // half a texel in from the tile's edge: nearest sampling at the exact edge reads the NEIGHBOURING tile
        buf.uv.push(tu + ((c === 1 || c === 2) ? 1 / TILE_COLS - EU : EU), tv + ((c >= 2) ? 1 / TILE_ROWS - EV : EV));
        const s = D.shade * (info.glow ? 1.6 : 1);
        buf.col.push(s, s, s);
      }
      const p = buf.pos, q = base * 3;
      const e1 = [p[q + 3] - p[q], p[q + 4] - p[q + 1], p[q + 5] - p[q + 2]], e2 = [p[q + 9] - p[q], p[q + 10] - p[q + 1], p[q + 11] - p[q + 2]];
      let nx = e1[1] * e2[2] - e1[2] * e2[1], ny = e1[2] * e2[0] - e1[0] * e2[2], nz = e1[0] * e2[1] - e1[1] * e2[0];
      const nl = Math.hypot(nx, ny, nz) || 1; nx /= nl; ny /= nl; nz /= nl;
      for (let c = 0; c < 4; c++) buf.nor.push(nx, ny, nz);
      buf.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
      buf.n += 4;
    }
  }
  // GRASS ("your fidelity reference": a meadow of dense, waving grass with wildflowers): clumps scattered over every
  // ground triangle that is mostly grass and gentle, about GRASS_DENSITY per m², each at a point chosen from the
  // triangle's place (the same meadow on every screen). The page draws them instanced, near the player only.
  const grass = lod ? null : scatterGrass(smooth);
  const pieces = mk(), glassy = mk();
  if (boxes && boxes.length) meshBoxes(boxes, u0, v0, h0, place, pieces, glassy, lod);
  if (!smooth.idx.length && !trees.idx.length && !solid.n && !clear.n && !pieces.n && !glassy.n && !bark.n && !foliage.n) return { empty: true };
  return { anchor, smooth: pack(smooth), trees: pack(trees), solid: pack(solid), clear: pack(clear), pieces: pack(pieces), glassy: pack(glassy),
           bark: pack(bark), foliage: pack(foliage), grass };
}

// ---- tree models: one per (kind, height, variant, detail), turned and placed per tree --------------------------------
const VARIANTS = 6;
const models = new Map();
/** Copy tree `t`'s model into `bark` / `foliage`, its root at grid (gu + .5, gv + .5) on the ground at `ground`, leaving
 *  out every part that stood in a cell `gone(u, v, h)` says was taken. */
function placeTree(t, face, gu, gv, ground, lod, place, bark, foliage, gone) {
  const far = lod >= 2 ? 2 : 0, variant = Math.floor(hash3(gu, gv, face * 7 + 1) * VARIANTS);
  const key = t.kind + ":" + t.height + ":" + variant + ":" + far;
  let m = models.get(key);
  if (!m) { m = treeModel(t.kind, t.height, (variant + 1) * 7919 + t.height * 131 + t.kind.length, far); models.set(key, m); }
  placeModel(m, face, gu + 0.5, gv + 0.5, ground, hash3(gv, face, gu) * Math.PI * 2, 0.9 + 0.1 * hash3(gu + 3, gv, face),
             hash3(gu, gv + 5, face) * 6.283, place, bark, foliage, gone);
}
/** Place model `m` (local x along u, y along v, z up) at grid (cu, cv, base), turned by `rot` and scaled by `sc`, in GRID
 *  units — so it bends with the planet exactly as the cells it stands for. Every model is built of quads (6 indices: a
 *  tube's facet, a leaf card, a frond's segment); a quad whose centre lies in a cell `gone` names is left out. */
function placeModel(m, face, cu, cv, base, rot, sc, phase, place, bark, foliage, gone) {
  const cr = Math.cos(rot), sr = Math.sin(rot), fr = frameOf(face, cu, cv);
  for (const [src, out] of [[m.bark, bark], [m.leaves, foliage]]) {
    if (!src.n) continue;
    const g = new Float64Array(src.n * 3), at = new Int32Array(src.n).fill(-1);
    for (let i = 0; i < src.n; i++) {
      const x = src.pos[i * 3], y = src.pos[i * 3 + 1];
      g[i * 3] = cu + (x * cr - y * sr) * sc; g[i * 3 + 1] = cv + (x * sr + y * cr) * sc; g[i * 3 + 2] = base + src.pos[i * 3 + 2] * sc;
    }
    const put = (i) => {
      if (at[i] >= 0) return at[i];
      const p = place(g[i * 3], g[i * 3 + 1], g[i * 3 + 2]);
      out.pos.push(p[0], p[1], p[2]);
      const nx = src.nor[i * 3], ny = src.nor[i * 3 + 1], nz = src.nor[i * 3 + 2], ex = nx * cr - ny * sr, ey = nx * sr + ny * cr;
      out.nor.push(ex * fr.east[0] + ey * fr.north[0] + nz * fr.up[0], ex * fr.east[1] + ey * fr.north[1] + nz * fr.up[1], ex * fr.east[2] + ey * fr.north[2] + nz * fr.up[2]);
      out.uv.push(src.uv[i * 2], src.uv[i * 2 + 1]);
      out.tile.push(src.tile[i]);
      out.col.push(src.col[i * 3], src.col[i * 3 + 1], src.col[i * 3 + 2]);
      // the wind blows along the local east; its strength is the vertex's weight, its rhythm the tree's own phase
      const w = src.wind[i * 4];
      out.wind.push(fr.east[0] * w, fr.east[1] * w, fr.east[2] * w, phase);
      return (at[i] = out.n++);
    };
    const I = src.idx;
    for (let q = 0; q < I.length; q += 6) {
      if (gone) {
        const vs = new Set(I.slice(q, q + 6));
        let x = 0, y = 0, z = 0;
        for (const v of vs) { x += g[v * 3]; y += g[v * 3 + 1]; z += g[v * 3 + 2]; }
        if (gone(Math.floor(x / vs.size), Math.floor(y / vs.size), Math.floor(z / vs.size))) continue;
      }
      for (let k = 0; k < 6; k++) out.idx.push(put(I[q + k]));
    }
  }
}

const GRASS_DENSITY = 6;                                   // clumps per m² of meadow
function scatterGrass(g) {
  const P = g.pos, N = g.nor, I = g.idx, W1 = g.w1, out = [], kinds = [];
  for (let t = 0; t < I.length; t += 3) {
    const a = I[t], b = I[t + 1], c = I[t + 2];
    const gw = (W1[a * 4] + W1[b * 4] + W1[c * 4]) / 3;
    if (gw < 0.55) continue;
    const ax = P[a * 3], ay = P[a * 3 + 1], az = P[a * 3 + 2];
    const ex = P[b * 3] - ax, ey = P[b * 3 + 1] - ay, ez = P[b * 3 + 2] - az, fx = P[c * 3] - ax, fy = P[c * 3 + 1] - ay, fz = P[c * 3 + 2] - az;
    const cx = ey * fz - ez * fy, cy = ez * fx - ex * fz, cz = ex * fy - ey * fx, area = Math.hypot(cx, cy, cz) / 2;
    const n = Math.floor(area * GRASS_DENSITY * gw + hash3(a, b, c));
    for (let k = 0; k < n; k++) {
      let r1 = hash3(a + k, b, c * 3 + 1), r2 = hash3(a, b + k, c * 7 + 2);
      if (r1 + r2 > 1) { r1 = 1 - r1; r2 = 1 - r2; }
      out.push(ax + ex * r1 + fx * r2, ay + ey * r1 + fy * r2, az + ez * r1 + fz * r2, N[a * 3], N[a * 3 + 1], N[a * 3 + 2], hash3(c, k, a));
      kinds.push(hash3(k, a, c) < 0.04 ? 1 : 0);                       // one clump in 25 is a wildflower
    }
  }
  return out.length ? { inst: new Float32Array(out), kind: new Uint8Array(kinds) } : null;
}

function mk() { return { pos: [], nor: [], uv: [], col: [], tile: [], uvw: [], gn: [], w1: [], w2: [], wind: [], idx: [], n: 0 }; }
function pack(b) {
  if (!b.n || !b.idx.length) return null;
  const out = { pos: new Float32Array(b.pos), nor: new Float32Array(b.nor), col: new Float32Array(b.col),
                idx: b.n > 65535 ? new Uint32Array(b.idx) : new Uint16Array(b.idx) };
  if (b.uv.length) out.uv = new Float32Array(b.uv);
  if (b.tile.length) out.tile = new Float32Array(b.tile);
  for (const k of ["uvw", "gn", "w1", "w2", "wind"]) if (b[k].length) out[k] = new Float32Array(b[k]);
  return out;
}

// ---- worker protocol: {id, face, cu, cv, ch, edits: [[key, block], ...]} -> {id, ...meshChunk} ----------------------
if (typeof self !== "undefined" && typeof window === "undefined" && typeof self.postMessage === "function") {
  self.onmessage = (e) => {
    const m = e.data;
    let res;
    try { res = meshChunk(m.face, m.cu, m.cv, m.ch, m.edits && m.edits.length ? new Map(m.edits) : null, m.boxes, m.lod); }
    catch (err) { res = { error: String(err && err.message || err) }; }
    const tr = [];
    if (res.grass) tr.push(res.grass.inst.buffer, res.grass.kind.buffer);
    for (const part of [res.smooth, res.trees, res.solid, res.clear, res.pieces, res.glassy, res.bark, res.foliage]) if (part) for (const a of [part.pos, part.nor, part.col, part.idx, part.uv, part.tile, part.uvw, part.gn, part.w1, part.w2, part.wind]) if (a) tr.push(a.buffer);
    self.postMessage(Object.assign({ id: m.id }, res), tr);
  };
}
