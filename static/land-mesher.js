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
import { CHUNK, H, R0, W, B, BLOCKS, ATLAS_TILES, NATURAL, CM, DEEP_MIN, TREE_WOOD, TREE_LEAVES, isTree, opaque, dirOf, frameOf, wrap, column, terrainBlock, fieldOf, treeAt, treeCell, LITTER, shapeOf, FLOWERS } from "./land-world.js";
import { treeModel, leafCellModel, twigModel, flaxModel, saplingModel, flowerModel } from "./land-trees.js";

const N = CHUNK + 2;                                     // cells with the border: real index r in -1..16 is r + 1
const TILE_COLS = 8;                                      // the atlas is TILE_COLS tiles across (static/land.js paints it)
const TILE_ROWS = Math.ceil(ATLAS_TILES / TILE_COLS);
const EU = 0.5 / (16 * TILE_COLS), EV = 0.5 / (16 * TILE_ROWS);   // half a texel of the 16 px tiles
// a fire cell is flames only (the FIRE loop below), never a cube — the first fire render drew lamp-tiled boxes round them
const crisp = (b) => b !== B.air && b !== B.fire && !NATURAL.has(b) && !isTree(b) && !BLOCKS[b].liquid && !LITTER.has(b);

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
export function groundWeights(b, up) {          // (static/land.js weighs the far land by it too)
  const w = [0, 0, 0, 0, 0, 0];                          // grass, dirt, rock, sand, snow, gravel
  const steep = smoothstep(0.62, 0.38, up);              // 1 on a cliff, 0 on the flat
  if (b === B.grass) { const g = smoothstep(0.62, 0.85, up); w[0] = g; w[1] = 1 - g; }
  else if (b === B.dirt || b === B.clay) w[1] = 1;    // clay: earth's texture, its own tint (groundGrain)
  else if (b === B.sand) w[3] = 1;
  else if (b === B.snow) w[4] = 1;
  else if (b === B.gravel) w[5] = 1;
  else w[2] = 1;                                         // stone, basalt, bedrock
  for (let i = 0; i < 6; i++) if (i !== 2) w[i] *= 1 - steep;
  w[2] += steep * (b === B.sand ? 0.5 : 1);
  const n = w.reduce((a, x) => a + x, 0) || 1;
  return w.map((x) => x / n);
}
// the faint per-place grain, and the colour of what is IN the ground where a dig exposes it — a vein of ore must be
// seen to be followed (2026-11-07): coal dark, iron rusty, copper verdigris, tin pale, clay a reddish earth
const ORE_TINT = { [B.coal]: [0.38, 0.38, 0.4], [B.ironore]: [1.12, 0.82, 0.66], [B.copperore]: [0.78, 1.08, 0.92],
  [B.tinore]: [1.18, 1.18, 1.22], [B.clay]: [1.12, 0.86, 0.72], [B.silverore]: [1.3, 1.32, 1.38], [B.goldore]: [1.35, 1.15, 0.55] };
const groundGrain = (b, up, u, v, h) => {
  const j = 0.9 + 0.2 * hash3(u, v, h), t = ORE_TINT[b];
  return t ? [j * t[0], j * t[1], j * t[2]] : [j, j, j];
};

/** The chunk's cells with the border: block ids and the ground field, index ((k * N) + j) * N + i. */
function cells(face, cu, cv, ch, edits) {
  const u0 = cu * CHUNK - 1, v0 = cv * CHUNK - 1, h0 = ch * CHUNK - 1;
  const cols = new Map();                                 // numeric keys: a string key per lookup cost more than the noise
  const colCache = (f, u, v) => { const k = (f * 131072 + u) * 131072 + v; let c = cols.get(k); if (!c) { c = column(f, u, v); cols.set(k, c); } return c; };
  const blk = new Uint8Array(N * N * N), fld = new Float32Array(N * N * N), dug = new Uint8Array(N * N * N);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const w = wrap(face, u0 + i, v0 + j), col = colCache(w.face, w.u, w.v);
    for (let k = 0; k < N; k++) {
      const h = h0 + k, x = (k * N + j) * N + i;
      const e = edits ? edits.get(w.face + ":" + w.u + ":" + w.v + ":" + h) : undefined;
      // the deep (#129) is ground like any other down to DEEP_MIN; under it, solid bedrock
      blk[x] = e !== undefined ? e : h < DEEP_MIN ? B.bedrock : h >= H ? B.air : terrainBlock(w.face, w.u, w.v, h, colCache);
      fld[x] = h < DEEP_MIN ? 1 : h >= H ? -1 : fieldOf(col, h, e);
      // ground someone dug out (not a tree or litter above it) — unless grass has grown back on the earth under it: a
      // levelled site greened over read as a bare brown patch for good (the town, 2026-11-07)
      if (e === B.air && h <= col.top && !(edits && edits.get(w.face + ":" + w.u + ":" + w.v + ":" + (h - 1)) === B.grass)) dug[x] = 1;
    }
  }
  return { blk, fld, dug, colCache };
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
      if (n === b || !opaque(n[6]) || BLOCKS[n[6]].see || shapeOf(n) || MODELS[n[6]] || n[6] === B.window) continue;   // a slope's, a window's or a table's box is not solid: it hides nothing
      if ((s > 0 ? n[ax] : n[ax] + n[ax + 3]) !== plane) continue;
      if (n[o[0]] <= b[o[0]] && n[o[0]] + n[o[0] + 3] >= b[o[0]] + b[o[0] + 3] && n[o[1]] <= b[o[1]] && n[o[1]] + n[o[1] + 3] >= b[o[1]] + b[o[1] + 3]) return true;
    }
    return false;
  };
  // by material, each one's run of indices a draw group ([start, count, block]) — the page gives each material its own
  // textured material (real wood, brick, plaster…; the 16 px atlas tile was the blocky look on houses)
  mine.sort((a, b) => a[6] - b[6]);
  let runM = -1, runAt = 0;
  const close = () => { if (runM >= 0 && solid.idx.length > runAt) solid.groups.push([runAt, solid.idx.length - runAt, runM]); };
  for (const b of mine) {
    if (opaque(b[6]) && b[6] !== runM) { close(); runM = b[6]; runAt = solid.idx.length; }
    if (shapeOf(b)) { meshSlope(b, u0, v0, place, !opaque(b[6]) ? clear : solid, lo, hi); continue; }
    if (b[6] === B.window) { meshWindow(b, u0, v0, place, solid, clear, lo, hi); continue; }
    if (MODELS[b[6]]) {
      // a part of another material (a bed's straw tick, a torch's flame) is its own draw group; the run of the piece's
      // own material resumes after it, so the groups still cover every index exactly once
      meshModel(b, u0, v0, place, solid, lo, hi, (m, draw) => {
        if (m === runM) return draw();
        const own = runM; close(); runM = m; runAt = solid.idx.length; draw(); close(); runM = own; runAt = solid.idx.length;
      }, boxes);
      continue;
    }
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
  close();
}

/** Mesh one chunk: { anchor, smooth (the ground), trees, bark, foliage, stones, solid, clear, water, pieces, glassy, grass }
 *  or { empty }. `boxes`:
 *  the plot's built pieces (land-world BOXES); `lod`: 0 near (grass and every piece), 1 middle (every piece), 2 far
 *  (pieces under LOD_SKIP_CM skipped). */
export function meshChunk(face, cu, cv, ch, edits, boxes, lod, grassOn = true) {
  const h0 = ch * CHUNK;
  if ((!edits || edits.size === 0) && !(boxes && boxes.length)) {   // wholly above the ground, the trees and the sea: air
    let hi = 0;
    for (const [du, dv] of [[0, 0], [CHUNK, 0], [0, CHUNK], [CHUNK, CHUNK], [CHUNK / 2, CHUNK / 2]]) {
      const w = wrap(face, cu * CHUNK + du, cv * CHUNK + dv);
      hi = Math.max(hi, column(w.face, w.u, w.v).top);
    }
    if (h0 > hi + 16 && h0 > 100) return { empty: true };
  }
  const { blk, fld, dug, colCache } = cells(face, cu, cv, ch, edits);
  const at = (i, j, k) => blk[((k + 1) * N + (j + 1)) * N + (i + 1)];
  const u0 = cu * CHUNK, v0 = cv * CHUNK;
  const anchor = dirOf(face, u0, v0).map((x) => x * (R0 + h0));
  const fr = frameOf(face, u0 + CHUNK / 2, v0 + CHUNK / 2);   // the chunk's local frame: gradients become world normals
  const place = (gu, gv, gh) => { const d = dirOf(face, gu, gv), r = R0 + gh; return [d[0] * r - anchor[0], d[1] * r - anchor[1], d[2] * r - anchor[2]]; };
  const smooth = mk(), trees = mk(), solid = mk(), clear = mk(), water = mk();

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
      // DUG GROUND SHOWS EARTH: a vertex touching a dug cell is shared with the untouched turf around the hole, and took
      // its grass — the hole stayed green and grew blades, which read as grass growing straight back ("collecting grass
      // somehow regenerates it", "and at the bottom theres grass?", operator 2026-11-06). Turned turf is earth.
      if (mat === B.grass) for (let c = 0; c < 8; c++) if (dug[((pk + (c >> 2)) * N + pj + ((c >> 1) & 1)) * N + pi + (c & 1)]) { mat = B.dirt; break; }
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
  const bark = mk(), foliage = mk(), stones = mk(), flames = mk();
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
    // FELLED: a trunk cell taken brings everything of the model above it down with it — the cards that overhang the
    // tree's own cells were left hanging in the air otherwise ("the trees arent felled they stay in the air")
    let cutAt = Infinity;
    if (edits) for (let dh = 1; dh <= t.height; dh++) {
      const b = treeCell(t, 0, 0, dh), e = b && edits.get(face + ":" + gu + ":" + gv + ":" + (col.top + dh));
      if (TREE_WOOD.has(b) && e !== undefined && e !== b) { cutAt = col.top + dh; break; }
    }
    const gone = (cu, cv, ch) => {
      const b = treeCell(t, cu - gu, cv - gv, ch - col.top);
      if (!b || !edits) return false;
      const e = edits.get(face + ":" + cu + ":" + cv + ":" + ch);
      return e !== undefined && e !== b;
    };
    gone.cut = cutAt;
    placeTree(t, face, gu, gv, col.height, lod, place, bark, foliage, gone);
  }
  // litter: a loose stone is a small rough rock in its own part, drawn with the ground's material (its weights all rock);
  // a fallen stick is a short forked branch in the bark mesh. Both lie on the drawn surface.
  for (let k = 0; k < CHUNK; k++) for (let j = 0; j < CHUNK; j++) for (let i = 0; i < CHUNK; i++) {
    const b = blk[((k + 1) * N + (j + 1)) * N + (i + 1)];
    if (!LITTER.has(b)) continue;
    const gu = u0 + i, gv = v0 + j, gh = h0 + k, col0 = colCache(face, gu, gv);
    // what lies on the ground stands on the DRAWN ground: the column's own height where the ground under it is the
    // planet's, but the cell's floor where that ground was edited or it is not the column's top (levelled earth — the
    // town; a dug pit) — a planted sapling or flower stood inside the ground or above it there (2026-11-07)
    const edited = edits && edits.get(face + ":" + gu + ":" + gv + ":" + (gh - 1)) !== undefined;
    const col = edited || gh !== col0.top + 1 ? { height: gh } : col0;
    const ou = 0.25 + 0.5 * hash3(gu, gv, 3), ov = 0.25 + 0.5 * hash3(gv, gu, 5), rot = hash3(gu, gh, gv) * 6.283;
    if (b === B.twigs) placeModel(twigModel(1 + Math.floor(hash3(gu, gv, 9) * 5)), face, gu + ou, gv + ov, col.height - 0.01, rot, 1, 0, place, bark, foliage, null);
    else if (b === B.sapling) placeModel(saplingModel(1 + Math.floor(hash3(gu, gv, 17) * 997)), face, gu + 0.5, gv + 0.5, col.height - 0.02, rot, 1,
                                         0.001 + hash3(gu, gv, 23) * 6.28, place, bark, foliage, null);
    // each clump its own wind phase: at one phase a whole stand swayed as a single sheet
    else if (FLOWERS.includes(b)) placeModel(flowerModel(1 + Math.floor(hash3(gu, gv, 29) * 997), FLOWERS.indexOf(b)), face, gu + 0.5, gv + 0.5,
                                             col.height - 0.02, rot, 1, 0.001 + hash3(gv, gu, 31) * 6.28, place, bark, foliage, null);
    else if (b === B.flax) placeModel(flaxModel(1 + Math.floor(hash3(gu, gv, 13) * 997)), face, gu + 0.5, gv + 0.5, col.height - 0.02, rot, 1,
                                      0.001 + hash3(gv, gu, 21) * 6.28, place, bark, foliage, null);
    else pebble(stones, face, gu + ou, gv + ov, col.height, 0.11 + 0.1 * hash3(gv, gh, gu), hash3(gu, gv, 11), rot, place);
  }
  // FIRE (#124): three crossed flame quads in a burning cell, its texture drawn by the page's flame material from uv
  // (0 at the base, 1 at the tips) and a per-cell phase in the colour, so no two fires flicker together
  for (let k = 0; k < CHUNK; k++) for (let j = 0; j < CHUNK; j++) for (let i = 0; i < CHUNK; i++) {
    if (blk[((k + 1) * N + (j + 1)) * N + (i + 1)] !== B.fire) continue;
    const gu = u0 + i, gv = v0 + j, gh = h0 + k, ph = hash3(gu, gv, gh), col = colCache(face, gu, gv);
    const base0 = gh === col.top + 1 ? col.height - 0.05 : gh;          // on the ground: from the drawn surface
    for (let q = 0; q < 3; q++) {
      const a = (q / 3) * Math.PI + ph, ca = Math.cos(a) * 0.45, sa = Math.sin(a) * 0.45, n = flames.n;
      for (const [s, t] of [[-1, 0], [1, 0], [1, 1], [-1, 1]]) {
        const p = place(gu + 0.5 + ca * s, gv + 0.5 + sa * s, base0 + t * 1.05);
        flames.pos.push(p[0], p[1], p[2]); flames.nor.push(0, 0, 1); flames.uv.push((s + 1) / 2, t); flames.col.push(ph, 0, 0); flames.n++;
      }
      flames.idx.push(n, n + 1, n + 2, n, n + 2, n + 3);
    }
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
      // the sea is its own part: the page draws it as water (moving ripples, fresnel to the sky), not an atlas tile — the
      // tile read as "bland untextured marches" from above (operator, 2026-11-06)
      const buf = info.liquid ? water : isClear ? clear : solid, tile = info.tex[D.t];
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
        if (info.liquid) buf.uvw.push(((u0 + i + ci) % 4096 + 4096) % 4096, ((v0 + j + cj) % 4096 + 4096) % 4096, h0 + k + ck);
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
  // the middle distance (lod 1) gets a third of the blades: a meadow that stopped 40 m away left a pale wash beyond it
  // (operator, 2026-11-06). Far chunks (lod 2) none.
  // never through a built piece lying on the ground (blades stood up through a plank floor, the furniture render
  // 2026-11-07): a blade whose spot a piece covers, from just under the ground to 60 cm above it, is not grown. A chunk
  // column IS a plot, so the blade's grid offset from the chunk's corner is the piece's own frame (cm).
  const lying = boxes && boxes.length ? boxes.filter((b) => !shapeOf(b)) : null;
  const under = lying ? (gu, gv, gh) => {
    const x = (((gu - u0) % 4096) + 4096) % 4096 * CM, z = (((gv - v0) % 4096) + 4096) % 4096 * CM, y = gh * CM;
    return lying.some((b) => x >= b[0] && x < b[0] + b[3] && z >= b[1] && z < b[1] + b[4] && b[2] <= y + 60 && b[2] + b[5] >= y - 10);
  } : null;
  const grass = lod >= 2 || !grassOn ? null : scatterGrass(smooth, lod ? GRASS_DENSITY / 3 : GRASS_DENSITY, under);
  const pieces = mk(), glassy = mk();
  if (boxes && boxes.length) meshBoxes(boxes, u0, v0, h0, place, pieces, glassy, lod);
  if (!smooth.idx.length && !trees.idx.length && !solid.n && !clear.n && !pieces.n && !glassy.n && !bark.n && !foliage.n && !stones.n && !water.n && !flames.n) return { empty: true };
  return { anchor, flames: pack(flames), smooth: pack(smooth), trees: pack(trees), solid: pack(solid), clear: pack(clear), pieces: pack(pieces), glassy: pack(glassy),
           bark: pack(bark), foliage: pack(foliage), stones: pack(stones), water: pack(water), grass };
}

// ---- a window (land-world B.window): a timber frame — two jambs, a sill, a head and a cross mullion, FRAME cm thick, the
// window's full depth — around a 1 cm pane at the middle of its depth (the pane in the glass part). Its thin axis (x or z)
// is the wall it sits in. Drawn whole by the chunk its bottom is in.
const FRAME = 8, BAR = 5;
function meshWindow(b, u0, v0, place, solid, clear, lo, hi) {
  if (b[2] < lo || b[2] >= hi) return;
  const thinX = b[3] < b[4], W = thinX ? b[4] : b[3], D = thinX ? b[3] : b[4], H = b[5], tile = BLOCKS[b[6]].tex[1];
  // a sub-box in the window's own terms (a: across, t: through the wall, y: up), in cm from its corner
  const sub = (buf, a0, a1, t0, t1, y0, y1, tl) => {
    const lo3 = thinX ? [b[0] + t0, b[1] + a0, b[2] + y0] : [b[0] + a0, b[1] + t0, b[2] + y0];
    const hi3 = thinX ? [b[0] + t1, b[1] + a1, b[2] + y1] : [b[0] + a1, b[1] + t1, b[2] + y1];
    cuboid(buf, lo3, hi3, u0, v0, place, tl);
  };
  sub(solid, 0, FRAME, 0, D, 0, H, tile); sub(solid, W - FRAME, W, 0, D, 0, H, tile);          // jambs
  sub(solid, FRAME, W - FRAME, 0, D, 0, FRAME, tile); sub(solid, FRAME, W - FRAME, 0, D, H - FRAME, H, tile);   // sill, head
  sub(solid, W / 2 - BAR / 2, W / 2 + BAR / 2, D / 2 - 2, D / 2 + 2, FRAME, H - FRAME, tile);     // the mullion
  sub(solid, FRAME, W - FRAME, D / 2 - 2, D / 2 + 2, H / 2 - BAR / 2, H / 2 + BAR / 2, tile);     // the transom
  sub(clear, FRAME, W - FRAME, D / 2 - 0.5, D / 2 + 0.5, FRAME, H - FRAME, BLOCKS[B.glass].tex[1]);   // the pane
}
// ---- furniture and fittings (land-world: table .. torch): each a real model of cuboid parts — legs, a top, a back, rails —
// inside its unit box, not the box itself ("start creating various structures ... realistic", operator 2026-11-07).
// A part is [l0, l1, s0, s1, y0, y1, material?] in cm: l along the box's LONG side, s across it (a chair's back and a
// bed's headboard are at their named ends, so turning the piece (T) turns the model), y up; material: the piece's own
// unless named. Drawn whole by the chunk its bottom is in.
const legs = (L, S, w, i, y1) => [[i, i + w], [L - i - w, L - i]].flatMap(([a, b]) => [[i, i + w], [S - i - w, S - i]].map(([c, d]) => [a, b, c, d, 0, y1]));
export const MODELS = {
  [B.table]: (L, S) => [[0, L, 0, S, 72, 76], ...legs(L, S, 6, 4, 72),
    [10, L - 10, 5, 7, 62, 72], [10, L - 10, S - 7, S - 5, 62, 72], [5, 7, 10, S - 10, 62, 72], [L - 7, L - 5, 10, S - 10, 62, 72]],
  [B.chair]: (L, S) => [[0, L, 0, S - 2, 42, 46],
    [3, 7, 2, 6, 0, 42], [L - 7, L - 3, 2, 6, 0, 42], [3, 7, S - 6, S - 2, 0, 95], [L - 7, L - 3, S - 6, S - 2, 0, 95],
    [7, L - 7, S - 5, S - 3, 58, 64], [7, L - 7, S - 5, S - 3, 76, 84], [7, L - 7, S - 6, S - 2, 89, 95]],
  [B.bench]: (L, S) => [[0, L, 0, S, 41, 45], [15, 19, 3, S - 3, 0, 41], [L - 19, L - 15, 3, S - 3, 0, 41], [19, L - 19, S / 2 - 3, S / 2 + 3, 12, 18]],
  // a rope bed: posts, rails, a head and foot board, a straw tick on the ropes, a wool blanket and a pillow
  [B.bed]: (L, S) => [[0, 8, 0, 8, 0, 90], [0, 8, S - 8, S, 0, 90], [L - 8, L, 0, 8, 0, 55], [L - 8, L, S - 8, S, 0, 55],
    [8, L - 8, 0, 5, 20, 35], [8, L - 8, S - 5, S, 20, 35], [2, 6, 8, S - 8, 40, 85], [L - 6, L - 2, 8, S - 8, 35, 50],
    [8, L - 8, 5, S - 5, 35, 48, B.thatch], [70, L - 8, 4, S - 4, 48, 51, B.red], [12, 45, 20, S - 20, 48, 57, B.white]],
  [B.fence]: (L, S) => [[0, 8, 0, S, 0, 100], [L - 8, L, 0, S, 0, 100], [8, L - 8, 2, S - 2, 38, 46], [8, L - 8, 2, S - 2, 76, 84]],
  // a ladder: two rails and a rung every 30 cm (lashed sticks — climbed by standing at it, land.js step)
  [B.ladder]: (L, S, H) => [[0, 5, 0, S, 0, H], [L - 5, L, 0, S, 0, H],
    ...Array.from({ length: Math.floor((H - 20) / 30) + 1 }, (_, i) => [5, L - 5, S / 2 - 2, S / 2 + 2, 20 + i * 30, 24 + i * 30])],
  // a chest: a plank body, a darker lid and two iron bands over it
  [B.chest]: (L, S) => [[1, L - 1, 1, S - 1, 0, 44], [1, L - 1, 1, S - 1, 44, 54, B.darkwood], [12, 16, 0, S, 0, 55, B.black],
    [L - 16, L - 12, 0, S, 0, 55, B.black]],
  // a torch: a shaft, a head wrapped in fibre and pitch, and its flame (a lamp: it glows, and lights the night near it)
  [B.torch]: (L, S) => [[L / 2 - 1.5, L / 2 + 1.5, S / 2 - 1.5, S / 2 + 1.5, 0, 100], [L / 2 - 2.5, L / 2 + 2.5, S / 2 - 2.5, S / 2 + 2.5, 96, 106, B.thatch],
    [L / 2 - 2, L / 2 + 2, S / 2 - 2, S / 2 + 2, 106, 118, B.lamp]],
};
// a chair is pulled up to a table: its back is on the side AWAY from the nearest table within 1.5 m (a unit piece turns
// only two ways, so its facing is read from where it stands, never a stored flag the world server would have to know)
export function facesAway(b, boxes) {
  const longX = b[3] >= b[4], sAx = longX ? 1 : 0, mid = b[sAx] + b[sAx + 3] / 2;
  let best = null, bd = 150 * 150;
  for (const t of boxes) if (t[6] === B.table && Math.abs(t[2] - b[2]) < 50) {
    const dx = t[0] + t[3] / 2 - b[0] - b[3] / 2, dz = t[1] + t[4] / 2 - b[1] - b[4] / 2, d = dx * dx + dz * dz;
    if (d < bd) { bd = d; best = t; }
  }
  return best ? best[sAx] + best[sAx + 3] / 2 > mid : false;       // true: the table is on the s = S side, so the back flips
}
function meshModel(b, u0, v0, place, buf, lo, hi, group, boxes) {
  if (b[2] < lo || b[2] >= hi) return;
  const longX = b[3] >= b[4], L = longX ? b[3] : b[4], S = longX ? b[4] : b[3];
  const flip = b[6] === B.chair && facesAway(b, boxes);
  for (const [l0, l1, s0f, s1f, y0, y1, m] of MODELS[b[6]](L, S, b[5])) {
    const s0 = flip ? S - s1f : s0f, s1 = flip ? S - s0f : s1f;
    const lo3 = longX ? [b[0] + l0, b[1] + s0, b[2] + y0] : [b[0] + s0, b[1] + l0, b[2] + y0];
    const hi3 = longX ? [b[0] + l1, b[1] + s1, b[2] + y1] : [b[0] + s1, b[1] + l1, b[2] + y1];
    const mat = m ?? b[6];
    group(mat, () => cuboid(buf, lo3, hi3, u0, v0, place, BLOCKS[mat].tex[1]));
  }
}
/** Six faces of the cuboid lo..hi (plot cm), each wound to face out, texture per metre. */
function cuboid(buf, lo, hi, u0, v0, place, tile) {
  const c = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
  for (let ax = 0; ax < 3; ax++) for (const side of [0, 1]) {
    const o = [0, 1, 2].filter((a) => a !== ax), q = (a, b2) => { const p = [0, 0, 0]; p[ax] = side ? hi[ax] : lo[ax]; p[o[0]] = a ? hi[o[0]] : lo[o[0]]; p[o[1]] = b2 ? hi[o[1]] : lo[o[1]]; return p; };
    let f = [q(0, 0), q(1, 0), q(1, 1), q(0, 1)];
    const P = f.map((p) => place(u0 + p[0] / CM, v0 + p[1] / CM, p[2] / CM));
    const e1 = P[1].map((x, i) => x - P[0][i]), e2 = P[2].map((x, i) => x - P[0][i]);
    let n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    // wound to face out: its normal turned away from the cuboid's middle
    const pa = place(u0 + c[0] / CM, v0 + c[1] / CM, c[2] / CM), fcp = f.reduce((a, p) => a.map((x, i) => x + p[i] / 4), [0, 0, 0]), pf = place(u0 + fcp[0] / CM, v0 + fcp[1] / CM, fcp[2] / CM);
    if (n[0] * (pf[0] - pa[0]) + n[1] * (pf[1] - pa[1]) + n[2] * (pf[2] - pa[2]) < 0) { f = f.slice().reverse(); P.reverse(); n = n.map((x) => -x); }
    const nl = Math.hypot(...n) || 1, base = buf.n;
    for (let i = 0; i < 4; i++) {
      buf.pos.push(P[i][0], P[i][1], P[i][2]); buf.nor.push(n[0] / nl, n[1] / nl, n[2] / nl);
      buf.uv.push(f[i][o[0]] / CM, f[i][o[1]] / CM); buf.tile.push(tile); buf.col.push(1, 1, 1); buf.n++;
    }
    buf.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
}

// ---- a slope (land-world SHAPES): five faces — the bottom, the tall end, the sloped face and two triangular sides. Built
// in the piece's own terms (r: 0..1 up the rise, c: 0..1 across it, y: 0..1 up), mapped to the plot by its shape; each
// face is wound by its own geometry (its normal turned away from the piece's middle), so all four shapes come out right.
function meshSlope(b, u0, v0, place, buf, lo, hi) {
  if (b[2] >= hi || b[2] + b[5] <= lo) return;               // drawn whole by the chunk its bottom is in
  if (b[2] < lo) return;
  const s = shapeOf(b), info = BLOCKS[b[6]], tile = info.tex[1];
  const at = (r, c, y) => {
    const X = s === 1 ? b[0] + r * b[3] : s === 2 ? b[0] + (1 - r) * b[3] : b[0] + c * b[3];
    const Z = s === 3 ? b[1] + r * b[4] : s === 4 ? b[1] + (1 - r) * b[4] : b[1] + c * b[4];
    return [X, Z, b[2] + y * b[5]];
  };
  const mid = at(0.66, 0.5, 0.33);
  const faces = [
    [at(0, 0, 0), at(1, 0, 0), at(1, 1, 0), at(0, 1, 0)],    // bottom
    [at(1, 0, 0), at(1, 0, 1), at(1, 1, 1), at(1, 1, 0)],    // the tall end
    [at(0, 0, 0), at(0, 1, 0), at(1, 1, 1), at(1, 0, 1)],    // the slope
    [at(0, 0, 0), at(1, 0, 1), at(1, 0, 0)],                 // a side
    [at(0, 1, 0), at(1, 1, 0), at(1, 1, 1)],                 // the other side
  ];
  for (let f of faces) {
    const P = f.map((q) => place(u0 + q[0] / CM, v0 + q[1] / CM, q[2] / CM));
    const e1 = P[1].map((x, i) => x - P[0][i]), e2 = P[2].map((x, i) => x - P[0][i]);
    let n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    const cf = f.reduce((a, q) => a.map((x, i) => x + q[i] / f.length), [0, 0, 0]);
    const pc = place(u0 + cf[0] / CM, v0 + cf[1] / CM, cf[2] / CM), pm = place(u0 + mid[0] / CM, v0 + mid[1] / CM, mid[2] / CM);
    if (n[0] * (pc[0] - pm[0]) + n[1] * (pc[1] - pm[1]) + n[2] * (pc[2] - pm[2]) < 0) { f = f.slice().reverse(); P.reverse(); n = n.map((x) => -x); }
    const nl = Math.hypot(...n) || 1;
    // texture per metre across the face: its first edge and the one at right angles to it
    const ax = f[1].map((x, i) => x - f[0][i]), al = Math.hypot(...ax) || 1, ux = ax.map((x) => x / al);
    const ay0 = f[f.length - 1].map((x, i) => x - f[0][i]), k = ay0[0] * ux[0] + ay0[1] * ux[1] + ay0[2] * ux[2];
    const ay = ay0.map((x, i) => x - k * ux[i]), ayl = Math.hypot(...ay) || 1, uy = ay.map((x) => x / ayl);
    const base = buf.n;
    for (let i = 0; i < f.length; i++) {
      buf.pos.push(P[i][0], P[i][1], P[i][2]);
      buf.nor.push(n[0] / nl, n[1] / nl, n[2] / nl);
      const d = f[i].map((x, j) => x - f[0][j]);
      buf.uv.push((d[0] * ux[0] + d[1] * ux[1] + d[2] * ux[2]) / CM, (d[0] * uy[0] + d[1] * uy[1] + d[2] * uy[2]) / CM);
      buf.tile.push(tile);
      const sh = info.glow ? 1.6 : 1;
      buf.col.push(sh, sh, sh);
      buf.n++;
    }
    if (f.length === 4) buf.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    else buf.idx.push(base, base + 1, base + 2);
  }
}

// ---- a loose stone: a once-subdivided icosahedron, flattened, its corners pushed in and out by the place's hash --------
let unitSphere = null;
function sphere() {
  if (unitSphere) return unitSphere;
  const t = (1 + Math.sqrt(5)) / 2, V = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]].map((p) => { const l = Math.hypot(...p); return p.map((x) => x / l); });
  let F = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
  const mid = new Map(), m = (a, b) => { const k = a < b ? a * 64 + b : b * 64 + a; if (!mid.has(k)) { const p = V[a].map((x, i) => x + V[b][i]), l = Math.hypot(...p); mid.set(k, V.push(p.map((x) => x / l)) - 1); } return mid.get(k); };
  F = F.flatMap(([a, b, c]) => { const ab = m(a, b), bc = m(b, c), ca = m(c, a); return [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]; });
  return (unitSphere = { V, F });
}
/** A rock of radius r sitting a third sunk at grid (cu, cv) on ground `base`, into the ground buffer `out`. */
function pebble(out, face, cu, cv, base, r, seed, rot, place) {
  const { V, F } = sphere(), fr = frameOf(face, cu, cv), first = out.n, cr = Math.cos(rot), sr = Math.sin(rot);
  const g = V.map(([x, y, z], i) => {
    const k = r * (0.8 + 0.4 * hash3(i, Math.floor(seed * 1e6), 7));
    const lx = x * k * 1.15, ly = y * k * 0.9, lz = z * k * 0.6;
    return [cu + lx * cr - ly * sr, cv + lx * sr + ly * cr, base - r * 0.2 + lz];
  });
  for (let i = 0; i < V.length; i++) {
    const [x, y, z] = V[i], nx = x * cr - y * sr, ny = x * sr + y * cr, p = place(g[i][0], g[i][1], g[i][2]);
    out.pos.push(p[0], p[1], p[2]);
    out.nor.push(nx * fr.east[0] + ny * fr.north[0] + z * fr.up[0], nx * fr.east[1] + ny * fr.north[1] + z * fr.up[1], nx * fr.east[2] + ny * fr.north[2] + z * fr.up[2]);
    const j = 0.75 + 0.25 * hash3(i, 3, Math.floor(seed * 1e6));
    out.col.push(j, j, j);
    out.uvw.push(((g[i][0] % 4096) + 4096) % 4096, ((g[i][1] % 4096) + 4096) % 4096, g[i][2]);
    out.gn.push(nx, ny, z);
    out.w1.push(0, 0, 1, 0); out.w2.push(0, 0);                      // all rock
    out.n++;
  }
  for (const [a, b, c] of F) out.idx.push(first + a, first + b, first + c);
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
        let x = 0, y = 0, z = 0, zTop = -Infinity;
        for (const v of vs) { x += g[v * 3]; y += g[v * 3 + 1]; z += g[v * 3 + 2]; zTop = Math.max(zTop, g[v * 3 + 2]); }
        // the quad's top corner decides a felling (gone.cut: no part of a felled tree reaches above its cut), its centre
        // the cell it stands in
        if (zTop >= gone.cut || gone(Math.floor(x / vs.size), Math.floor(y / vs.size), Math.floor(z / vs.size))) continue;
      }
      for (let k = 0; k < 6; k++) out.idx.push(put(I[q + k]));
    }
  }
}

const GRASS_DENSITY = 6;                                   // clumps per m² of meadow
function scatterGrass(g, density, under) {
  const P = g.pos, N = g.nor, I = g.idx, W1 = g.w1, U = g.uvw, out = [], kinds = [];
  for (let t = 0; t < I.length; t += 3) {
    const a = I[t], b = I[t + 1], c = I[t + 2];
    const gw = (W1[a * 4] + W1[b * 4] + W1[c * 4]) / 3;
    if (gw < 0.55) continue;
    const ax = P[a * 3], ay = P[a * 3 + 1], az = P[a * 3 + 2];
    const ex = P[b * 3] - ax, ey = P[b * 3 + 1] - ay, ez = P[b * 3 + 2] - az, fx = P[c * 3] - ax, fy = P[c * 3 + 1] - ay, fz = P[c * 3 + 2] - az;
    const cx = ey * fz - ez * fy, cy = ez * fx - ex * fz, cz = ex * fy - ey * fx, area = Math.hypot(cx, cy, cz) / 2;
    const n = Math.floor(area * density * gw + hash3(a, b, c));
    for (let k = 0; k < n; k++) {
      let r1 = hash3(a + k, b, c * 3 + 1), r2 = hash3(a, b + k, c * 7 + 2);
      if (r1 + r2 > 1) { r1 = 1 - r1; r2 = 1 - r2; }
      if (under) {
        const gp = (o) => U[a * 3 + o] + (U[b * 3 + o] - U[a * 3 + o]) * r1 + (U[c * 3 + o] - U[a * 3 + o]) * r2;
        if (under(gp(0), gp(1), gp(2))) continue;
      }
      out.push(ax + ex * r1 + fx * r2, ay + ey * r1 + fy * r2, az + ez * r1 + fz * r2, N[a * 3], N[a * 3 + 1], N[a * 3 + 2], hash3(c, k, a));
      kinds.push(hash3(k, a, c) < 0.04 ? 1 : 0);                       // one clump in 25 is a wildflower
    }
  }
  return out.length ? { inst: new Float32Array(out), kind: new Uint8Array(kinds) } : null;
}

function mk() { return { pos: [], nor: [], uv: [], col: [], tile: [], uvw: [], gn: [], w1: [], w2: [], wind: [], idx: [], groups: [], n: 0 }; }
function pack(b) {
  if (!b.n || !b.idx.length) return null;
  const out = { pos: new Float32Array(b.pos), nor: new Float32Array(b.nor), col: new Float32Array(b.col),
                idx: b.n > 65535 ? new Uint32Array(b.idx) : new Uint16Array(b.idx) };
  if (b.uv.length) out.uv = new Float32Array(b.uv);
  if (b.tile.length) out.tile = new Float32Array(b.tile);
  for (const k of ["uvw", "gn", "w1", "w2", "wind"]) if (b[k].length) out[k] = new Float32Array(b[k]);
  if (b.groups.length) out.groups = b.groups;
  return out;
}

// ---- worker protocol: {id, face, cu, cv, ch, edits: [[key, block], ...]} -> {id, ...meshChunk} ----------------------
if (typeof self !== "undefined" && typeof window === "undefined" && typeof self.postMessage === "function") {
  self.onmessage = (e) => {
    const m = e.data;
    let res;
    try { res = meshChunk(m.face, m.cu, m.cv, m.ch, m.edits && m.edits.length ? new Map(m.edits) : null, m.boxes, m.lod, m.grass !== false); }
    catch (err) { res = { error: String(err && err.message || err) }; }
    const tr = [];
    if (res.grass) tr.push(res.grass.inst.buffer, res.grass.kind.buffer);
    for (const part of [res.smooth, res.trees, res.solid, res.clear, res.pieces, res.glassy, res.bark, res.foliage, res.stones, res.water]) if (part) for (const a of [part.pos, part.nor, part.col, part.idx, part.uv, part.tile, part.uvw, part.gn, part.w1, part.w2, part.wind]) if (a) tr.push(a.buffer);
    self.postMessage(Object.assign({ id: m.id }, res), tr);
  };
}
