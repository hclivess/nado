// land-mesher.js — the Land planet's chunk mesher (a module Web Worker of static/land.js): a 16^3 chunk of the cube-
// sphere in, its triangles out, built off the main thread so walking never stutters on terrain generation.
//
// THE GROUND IS SMOOTH, WHAT PEOPLE BUILD IS CRISP ("it should not really be blocky", operator 2026-11-06). Three kinds
// of geometry come out of one chunk of cells:
//   smooth — the natural ground (land-world NATURAL) as the zero surface of land-world.fieldOf, by Surface Nets: one
//            vertex per cell-corner cube the surface crosses, placed at the mean of the crossings on its edges, with the
//            field's gradient as its normal; coloured by material and slope (grass on the flat, earth and rock on the
//            steep, snow that slides off cliffs). Tree canopies are a second surface over the leaf cells, and every log
//            cell is a round trunk segment.
//   solid  — built materials (planks, brick, tiles, wool…) as crisp textured cubes, culled against crisp neighbours and
//            against ground that buries them.
//   clear  — glass, ice and the sea's surface.
// The cells are the data either way: the commitment, the server and the API never see this difference.
//
// A chunk is (face, cu, cv, ch): columns u in [cu*16, cu*16+16), v likewise, layers [ch*16, ch*16+16) — one plot's columns.
// Cells are generated with a one-cell border (wrapped across face seams by land-world.wrap). A surface edge is drawn by
// the chunk that holds its LOWER cell, so every edge of the world belongs to exactly one chunk (no gaps, no doubles).
// Positions are metres RELATIVE TO THE CHUNK'S ANCHOR; the page places each mesh at anchor - camera in doubles.
import { CHUNK, H, R0, B, BLOCKS, ATLAS_TILES, NATURAL, CM, opaque, dirOf, frameOf, wrap, column, terrainBlock, fieldOf } from "./land-world.js";

const N = CHUNK + 2;                                     // cells with the border: real index r in -1..16 is r + 1
const TILE_COLS = 8;                                      // the atlas is TILE_COLS tiles across (static/land.js paints it)
const TILE_ROWS = Math.ceil(ATLAS_TILES / TILE_COLS);
const EU = 0.5 / (16 * TILE_COLS), EV = 0.5 / (16 * TILE_ROWS);   // half a texel of the 16 px tiles
const crisp = (b) => b !== B.air && !NATURAL.has(b) && b !== B.leaves && b !== B.log && !BLOCKS[b].liquid;

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
const C = {
  grass: [0.30, 0.52, 0.18], grass2: [0.40, 0.58, 0.20], dirt: [0.42, 0.30, 0.19], stone: [0.47, 0.46, 0.45],
  sand: [0.82, 0.74, 0.50], snow: [0.93, 0.95, 0.97], gravel: [0.52, 0.50, 0.47], basalt: [0.22, 0.22, 0.25],
  bedrock: [0.15, 0.15, 0.15], leaves: [0.20, 0.42, 0.14], leaves2: [0.28, 0.50, 0.16], bark: [0.36, 0.25, 0.15],
};
for (const k in C) C[k] = C[k].map((x) => Math.pow(x, 2.2));
const mix = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
function hash3(a, b, c) { let h = Math.imul(a, 374761393) ^ Math.imul(b, 668265263) ^ Math.imul(c, 2147483647); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }
function groundColour(b, up, u, v, h) {
  const j = 0.92 + 0.16 * hash3(u, v, h);              // a little grain, fixed per place
  let c;
  if (b === B.grass) c = up > 0.82 ? mix(C.grass, C.grass2, hash3(v, u, 7)) : up > 0.55 ? mix(C.dirt, C.grass, (up - 0.55) / 0.27) : mix(C.stone, C.dirt, Math.max(0, up - 0.2) / 0.35);
  else if (b === B.snow) c = up > 0.6 ? C.snow : mix(C.stone, C.snow, Math.max(0, up - 0.3) / 0.3);
  else if (b === B.dirt) c = up > 0.6 ? C.dirt : mix(C.stone, C.dirt, Math.max(0, up) / 0.6);
  else c = C[BLOCKS[b].key] || C.stone;
  return [c[0] * j, c[1] * j, c[2] * j];
}

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
  return { blk, fld };
}

// ---- built pieces: boxes at 1 cm (land-world.js BOXES) ------------------------------------------------------------
// Every piece is up to six textured quads, its texture tiling per METRE (uv in metres + the material's atlas tile as an
// attribute; static/land.js's node material takes fract(uv) inside the tile), so a 2 cm peg shows 2 cm of grain, not a
// squeezed tile. Performance (the operator asked, 2026-11-06): one merged mesh per chunk; a face wholly covered by a
// touching opaque piece is not drawn (a wall of flush planks is its outer skin, not every plank's six faces); a chunk the
// page marks far (lod 1) skips pieces whose largest side is under LOD_SKIP_CM — detail costs nothing at a distance.
const LOD_SKIP_CM = 20;
// axis and sign of each face. No baked shade: pieces are lit by the real sun and sky (a fixed per-face darkening on top of
// that, as the cube cells once had, turned a wall in its own shadow black — the first house render, 2026-11-06)
const BOX_FACES = [{ ax: 2, s: 1 }, { ax: 2, s: -1 }, { ax: 0, s: 1 }, { ax: 0, s: -1 }, { ax: 1, s: 1 }, { ax: 1, s: -1 }];
function meshBoxes(boxes, u0, v0, h0, place, solid, clear, lod) {
  const lo = h0 * CM, hi = (h0 + CHUNK) * CM;
  const mine = boxes.filter((b) => b[2] < hi && b[2] + b[5] > lo && !(lod && Math.max(b[3], b[4], b[5]) < LOD_SKIP_CM));
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

/** Mesh one chunk: { anchor, smooth (the ground), trees, solid, clear, pieces } (each {pos, nor, col, idx[, uv, tile]} or
 *  null), or { empty }. `boxes`: the plot's built pieces (land-world BOXES); `lod`: 1 for a far chunk. */
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
  const { blk, fld } = cells(face, cu, cv, ch, edits);
  const at = (i, j, k) => blk[((k + 1) * N + (j + 1)) * N + (i + 1)];
  const u0 = cu * CHUNK, v0 = cv * CHUNK;
  const anchor = dirOf(face, u0, v0).map((x) => x * (R0 + h0));
  const fr = frameOf(face, u0 + CHUNK / 2, v0 + CHUNK / 2);   // the chunk's local frame: gradients become world normals
  const place = (gu, gv, gh) => { const d = dirOf(face, gu, gv), r = R0 + gh; return [d[0] * r - anchor[0], d[1] * r - anchor[1], d[2] * r - anchor[2]]; };
  const smooth = mk(), trees = mk(), solid = mk(), clear = mk();

  // ---- the smooth surfaces: Surface Nets over a field sampled at cell centres -----------------------------------
  function nets(F, colourOf, out) {
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
        if (NATURAL.has(b) && ck > best) { best = ck; mat = b; }
      }
      const p = place(gu, gv, gh), col = colourOf(mat, nh, Math.floor(gu), Math.floor(gv), Math.floor(gh));
      vid[(pk * S + pj) * S + pi] = out.n;
      out.pos.push(p[0], p[1], p[2]); out.nor.push(nw[0], nw[1], nw[2]); out.col.push(col[0], col[1], col[2]);
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
  nets(fld, groundColour, smooth);
  // canopies: a surface over the leaf cells (crisp tree tops would be the blockiest thing on the planet)
  let leaves = false;
  const leafF = new Float32Array(N * N * N);
  // a log cell INSIDE the crown (a leaf beside it) counts as canopy here: a leaf surface with a trunk-shaped shaft through
  // it showed as black caps on every tree top. The trunk below the crown stays bare.
  const leafAt = (x) => x >= 0 && x < blk.length && blk[x] === B.leaves;
  for (let x = 0; x < blk.length; x++) {
    const crown = blk[x] === B.log && (leafAt(x + 1) || leafAt(x - 1) || leafAt(x + N) || leafAt(x - N));
    leafF[x] = blk[x] === B.leaves || crown ? 1 : -1;
    if (blk[x] === B.leaves) leaves = true;
  }
  if (leaves) nets(leafF, (m, up, u, v, h) => { const c = mix(C.leaves, C.leaves2, hash3(u, h, v)); const j = 0.85 + 0.25 * hash3(u, v, h); return [c[0] * j, c[1] * j, c[2] * j]; }, trees);

  // ---- trunks: every log cell is a round segment (octagonal, tapering as it rises) -----------------------------------
  for (let k = 0; k < CHUNK; k++) for (let j = 0; j < CHUNK; j++) for (let i = 0; i < CHUNK; i++) {
    if (at(i, j, k) !== B.log) continue;
    const below = at(i, j, k - 1) === B.log, r0 = below ? 0.30 : 0.36, r1 = at(i, j, k + 1) === B.log ? 0.30 : 0.26;
    const cu0 = u0 + i + 0.5, cv0 = v0 + j + 0.5, hb = h0 + k - (below ? 0 : 0.4), ht = h0 + k + 1;
    const base = trees.n;
    for (let s = 0; s < 8; s++) {
      const a = (s / 8) * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
      for (const [hh, rr] of [[hb, r0], [ht, r1]]) {
        const p = place(cu0 + ca * rr, cv0 + sa * rr, hh);
        trees.pos.push(p[0], p[1], p[2]);
        trees.nor.push(...[0, 1, 2].map((x) => ca * fr.east[x] + sa * fr.north[x]));
        const g = 0.85 + 0.2 * hash3(s, k, i * 31 + j);
        trees.col.push(C.bark[0] * g, C.bark[1] * g, C.bark[2] * g);
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
  const pieces = mk(), glassy = mk();
  if (boxes && boxes.length) meshBoxes(boxes, u0, v0, h0, place, pieces, glassy, lod);
  if (!smooth.idx.length && !trees.idx.length && !solid.n && !clear.n && !pieces.n && !glassy.n) return { empty: true };
  return { anchor, smooth: pack(smooth), trees: pack(trees), solid: pack(solid), clear: pack(clear), pieces: pack(pieces), glassy: pack(glassy) };
}

function mk() { return { pos: [], nor: [], uv: [], col: [], tile: [], idx: [], n: 0 }; }
function pack(b) {
  if (!b.n || !b.idx.length) return null;
  const out = { pos: new Float32Array(b.pos), nor: new Float32Array(b.nor), col: new Float32Array(b.col),
                idx: b.n > 65535 ? new Uint32Array(b.idx) : new Uint16Array(b.idx) };
  if (b.uv.length) out.uv = new Float32Array(b.uv);
  if (b.tile.length) out.tile = new Float32Array(b.tile);
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
    for (const part of [res.smooth, res.trees, res.solid, res.clear, res.pieces, res.glassy]) if (part) for (const a of [part.pos, part.nor, part.col, part.idx, part.uv, part.tile]) if (a) tr.push(a.buffer);
    self.postMessage(Object.assign({ id: m.id }, res), tr);
  };
}
