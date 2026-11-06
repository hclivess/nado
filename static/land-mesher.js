// land-mesher.js — the Land planet's chunk mesher (a module Web Worker of static/land.js): a 16^3 chunk of the cube-
// sphere in, its triangles out, built off the main thread so walking never stutters on terrain generation.
//
// A chunk is (face, cu, cv, ch): columns u in [cu*16, cu*16+16), v likewise, layers [ch*16, ch*16+16) — exactly one
// plot's columns, so a plot's edits never straddle chunks. Blocks are generated with a one-block border (its
// neighbours, wrapped across face seams by land-world.wrap) so a face between two chunks is culled the same from both
// sides. Positions are in metres RELATIVE TO THE CHUNK'S ANCHOR (its (u0, v0, h0) corner): the page places each mesh at
// anchor - camera in doubles, so float32 vertex positions stay small (~16 m) however far from the centre the planet is.
import { CHUNK, H, R0, B, BLOCKS, ATLAS_TILES, opaque, dirOf, wrap, column, terrainBlock } from "./land-world.js";

const N = CHUNK + 2;                                     // with the border
const TILE_COLS = 8;                                      // the atlas is TILE_COLS tiles across (static/land.js paints it)
const TILE_ROWS = Math.ceil(ATLAS_TILES / TILE_COLS);
const EU = 0.5 / (16 * TILE_COLS), EV = 0.5 / (16 * TILE_ROWS);   // half a texel of the 16 px tiles

// face table: [neighbour offset (du, dv, dh)], the 4 corners of the quad as (u, v, h) offsets in the cell, the light
// factor (top bright, bottom dark — the planet has no ambient occlusion yet), and which atlas tile (0 top, 1 side, 2 bottom)
const DIRS = [
  { d: [0, 0, 1], c: [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], shade: 1.0, t: 0 },     // up
  { d: [0, 0, -1], c: [[0, 1, 0], [1, 1, 0], [1, 0, 0], [0, 0, 0]], shade: 0.5, t: 2 },    // down
  { d: [1, 0, 0], c: [[1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 0, 1]], shade: 0.8, t: 1 },     // +u
  { d: [-1, 0, 0], c: [[0, 1, 0], [0, 0, 0], [0, 0, 1], [0, 1, 1]], shade: 0.8, t: 1 },    // -u
  { d: [0, 1, 0], c: [[1, 1, 0], [0, 1, 0], [0, 1, 1], [1, 1, 1]], shade: 0.65, t: 1 },    // +v
  { d: [0, -1, 0], c: [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], shade: 0.65, t: 1 },   // -v
];

/** Block ids of the chunk with its border: index ((h * N) + v) * N + u over the 18^3 cells. */
function voxels(face, cu, cv, ch, edits) {
  const u0 = cu * CHUNK - 1, v0 = cv * CHUNK - 1, h0 = ch * CHUNK - 1;
  const cols = new Map();                                 // numeric keys: a string key per lookup cost more than the noise
  const colCache = (f, u, v) => { const k = (f * 131072 + u) * 131072 + v; let c = cols.get(k); if (!c) { c = column(f, u, v); cols.set(k, c); } return c; };
  const out = new Uint8Array(N * N * N);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const w = wrap(face, u0 + i, v0 + j);                // a border column across a seam is the neighbour face's
    for (let k = 0; k < N; k++) {
      const h = h0 + k;
      out[(k * N + j) * N + i] = h < 0 || h >= H ? (h < 0 ? B.bedrock : B.air)
        : terrainBlock(w.face, w.u, w.v, h, colCache);
    }
    if (edits) for (let k = 0; k < N; k++) {
      const e = edits.get(w.face + ":" + w.u + ":" + w.v + ":" + (h0 + k));
      if (e !== undefined) out[(k * N + j) * N + i] = e;
    }
  }
  return out;
}

/** Mesh one chunk: { anchor [x, y, z] (metres, doubles), solid {pos, nor, uv, col, idx}, clear {…} } or { empty }. */
export function meshChunk(face, cu, cv, ch, edits) {
  // a chunk wholly above every column's ground (+ the tallest tree) and above the sea is air: skip the generation
  const h0 = ch * CHUNK;
  if (!edits || edits.size === 0) {
    let hi = 0;
    for (const [du, dv] of [[0, 0], [CHUNK, 0], [0, CHUNK], [CHUNK, CHUNK], [CHUNK / 2, CHUNK / 2]]) {
      const w = wrap(face, cu * CHUNK + du, cv * CHUNK + dv);
      hi = Math.max(hi, column(w.face, w.u, w.v).top);
    }
    if (h0 > hi + 16 && h0 > 100) return { empty: true };
  }
  const vox = voxels(face, cu, cv, ch, edits);
  const at = (i, j, k) => vox[((k + 1) * N + (j + 1)) * N + (i + 1)];
  // corner directions for the chunk's 17 x 17 corner grid (shared by every layer)
  const u0 = cu * CHUNK, v0 = cv * CHUNK;
  const dirs = new Float64Array(17 * 17 * 3);
  for (let j = 0; j <= CHUNK; j++) for (let i = 0; i <= CHUNK; i++) {
    const d = dirOf(face, u0 + i, v0 + j);
    dirs.set(d, (j * 17 + i) * 3);
  }
  const rad0 = R0;
  const ax = dirs[0] * (rad0 + h0), ay = dirs[1] * (rad0 + h0), az = dirs[2] * (rad0 + h0);
  const bufs = [mk(), mk()];
  let any = false;
  for (let k = 0; k < CHUNK; k++) for (let j = 0; j < CHUNK; j++) for (let i = 0; i < CHUNK; i++) {
    const b = at(i, j, k);
    if (b === B.air) continue;
    const info = BLOCKS[b], clear = !opaque(b);
    for (let f = 0; f < 6; f++) {
      const D = DIRS[f], n = at(i + D.d[0], j + D.d[1], k + D.d[2]);
      if (opaque(n)) continue;                            // hidden behind a solid opaque block
      if (n === b && (info.liquid || b === B.glass || b === B.ice)) continue;   // inside a body of water / a glass pane
      if (info.liquid && f !== 0) continue;                // water draws its surface only (a still sea)
      if (info.liquid && n !== B.air) continue;
      const buf = bufs[clear ? 1 : 0], tile = info.tex[D.t];
      const tu = (tile % TILE_COLS) / TILE_COLS, tv = 1 - (Math.floor(tile / TILE_COLS) + 1) / TILE_ROWS;
      const base = buf.n;
      for (let c = 0; c < 4; c++) {
        const [ci, cj, ck] = D.c[c], di = ((j + cj) * 17 + (i + ci)) * 3;
        let hh = h0 + k + ck;
        if (info.liquid && ck === 1) hh -= 0.12;             // the water surface sits a little below the bank
        const r = rad0 + hh;
        buf.pos.push(dirs[di] * r - ax, dirs[di + 1] * r - ay, dirs[di + 2] * r - az);
        // half a texel in from the tile's edge: nearest sampling at the exact edge reads the NEIGHBOURING tile (a seam
        // of another block's colour along every block edge)
        buf.uv.push(tu + ((c === 1 || c === 2) ? 1 / TILE_COLS - EU : EU), tv + ((c >= 2) ? 1 / TILE_ROWS - EV : EV));
        const s = D.shade * (info.glow ? 1.6 : 1);
        buf.col.push(s, s, s);
      }
      // the normal from the quad itself (the cells are not exactly axis-aligned on a sphere)
      const p = buf.pos, q = base * 3;
      const e1 = [p[q + 3] - p[q], p[q + 4] - p[q + 1], p[q + 5] - p[q + 2]], e2 = [p[q + 9] - p[q], p[q + 10] - p[q + 1], p[q + 11] - p[q + 2]];
      let nx = e1[1] * e2[2] - e1[2] * e2[1], ny = e1[2] * e2[0] - e1[0] * e2[2], nz = e1[0] * e2[1] - e1[1] * e2[0];
      const nl = Math.hypot(nx, ny, nz) || 1; nx /= nl; ny /= nl; nz /= nl;
      for (let c = 0; c < 4; c++) buf.nor.push(nx, ny, nz);
      buf.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
      buf.n += 4;
      any = true;
    }
  }
  if (!any) return { empty: true };
  return { anchor: [ax, ay, az], solid: pack(bufs[0]), clear: pack(bufs[1]) };
}

function mk() { return { pos: [], nor: [], uv: [], col: [], idx: [], n: 0 }; }
function pack(b) {
  if (!b.n) return null;
  return { pos: new Float32Array(b.pos), nor: new Float32Array(b.nor), uv: new Float32Array(b.uv), col: new Float32Array(b.col),
           idx: b.n > 65535 ? new Uint32Array(b.idx) : new Uint16Array(b.idx) };
}

// ---- worker protocol: {id, face, cu, cv, ch, edits: [[key, block], ...]} -> {id, ...meshChunk} ----------------------
if (typeof self !== "undefined" && typeof window === "undefined" && typeof self.postMessage === "function") {
  self.onmessage = (e) => {
    const m = e.data;
    let res;
    try { res = meshChunk(m.face, m.cu, m.cv, m.ch, m.edits && m.edits.length ? new Map(m.edits) : null); }
    catch (err) { res = { error: String(err && err.message || err) }; }
    const tr = [];
    for (const part of [res.solid, res.clear]) if (part) tr.push(part.pos.buffer, part.nor.buffer, part.uv.buffer, part.col.buffer, part.idx.buffer);
    self.postMessage(Object.assign({ id: m.id }, res), tr);
  };
}
