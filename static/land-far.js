/*
 * land-far.js — the land beyond the chunks, built in a mesher worker (land-mesher.js) and drawn by land.js.
 *
 * THE DISTANCE ("we need to improve drawing of distance without perf impact.. right now it is very stupid and short",
 * operator 2026-11-23). Measured before: the land ended 3.8 km out in a hard rim (the outer ring's edge, inside a camera
 * far plane of 4 km) where from 560 m up the horizon of this planet (R0 ~83 km) is ~10 km off and a range's crests show
 * from much further; and the far ground and that ring were sampled on the MAIN thread, ~9,000 columns at 35-55 us each
 * every 400 m walked — a third of a second of frame lost each time.
 *
 * Now every far piece is a pure function of (face, anchor) built here, off the main thread:
 *   farGround — the textured ground from the chunks' edge to FAR_N / 2 * FAR_STEP (1.7 km), as before;
 *   farRing   — one ring of a clipmap of the land beyond it: each ring doubles the last's step and reach (RINGS), the
 *               ground at its height, a forest at its canopy's (Forest.canopyHeight) in the canopy's olive, the rest in
 *               its ground's colour, out to 30 km: past the horizon from every height a craft flies at. A ring is a hole
 *               the size of the ring inside it, its anchor on its own step's double, so the two share an edge exactly;
 *               the inner ring's skirt hides the cracks of its finer edge. ~2,900 columns a ring.
 * ~16,000 triangles in all for the four rings; the GPU does not notice them (each is a few hundred metres across).
 */
import { SEA, posOf, wrap, column, terrainBlock, frameOf } from "./land-world.js";
import { canopyHeight } from "./land-forest.js";
import { groundWeights } from "./land-mesher.js";

export const FAR_N = 72, FAR_STEP = 48;                 // the textured far ground: 72 cells of 48 m (1.7 km each way)
// the rings: step (m between vertices), half (reach from the anchor, m; 30 steps), snap (the anchor's grid: twice the
// step, so the ring outside — whose step this is — has its cell edges on this ring's edge). Ring 0 is the former outer
// ring (128 m to 3.8 km); its inner edge sinks under the far ground as before (RING_SINK), the others meet edge to edge.
export const RINGS = [
  { step: 128, half: 3840, snap: 256 },
  { step: 256, half: 7680, snap: 512 },
  { step: 512, half: 15360, snap: 1024 },
  { step: 1024, half: 30720, snap: 2048 },
];
export const RING_SINK = 14;                            // m: ring 0 under the far ground it overlaps (a cell of overlap)
export const RING_COL = { forest: [0.076, 0.066, 0.009], grass: [0.085, 0.12, 0.032], beach: [0.42, 0.38, 0.26], desert: [0.45, 0.38, 0.24],
  rock: [0.22, 0.21, 0.19], snow: [0.78, 0.8, 0.84], sea: [0.02, 0.045, 0.07] };

/** The anchor of ring k for a player at (u, v): on the ring's snap grid. */
export const ringAnchor = (k, u, v) => { const s = RINGS[k].snap; return [Math.round(u / s) * s, Math.round(v / s) * s]; };

// a grid's vertex normals from central differences (one-sided at an edge or beside an unused vertex), wound as the
// triangles are (a, a + 1, a + N + 2): (p[i+1] - p[i-1]) x (p[j+1] - p[j-1]) — what computeVertexNormals gives a smooth grid
function gridNormals(pos, N, used) {
  const M = N + 1, nor = new Float32Array(pos.length);
  const ok = (i, j) => i >= 0 && j >= 0 && i <= N && j <= N && (!used || used[j * M + i]);
  for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
    const k = j * M + i;
    if (used && !used[k]) continue;
    const i0 = ok(i - 1, j) ? i - 1 : i, i1 = ok(i + 1, j) ? i + 1 : i, j0 = ok(i, j - 1) ? j - 1 : j, j1 = ok(i, j + 1) ? j + 1 : j;
    const a = (j * M + i1) * 3, b = (j * M + i0) * 3, c = (j1 * M + i) * 3, d = (j0 * M + i) * 3;
    const ux = pos[a] - pos[b], uy = pos[a + 1] - pos[b + 1], uz = pos[a + 2] - pos[b + 2];
    const vx = pos[c] - pos[d], vy = pos[c + 1] - pos[d + 1], vz = pos[c + 2] - pos[d + 2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const l = Math.hypot(nx, ny, nz) || 1;
    nor[k * 3] = nx / l; nor[k * 3 + 1] = ny / l; nor[k * 3 + 2] = nz / l;
  }
  return nor;
}
const gridIndex = (N, keep) => {
  const idx = [];
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    if (keep && !keep(i, j)) continue;
    const a = j * (N + 1) + i; idx.push(a, a + 1, a + N + 2, a, a + N + 2, a + N + 1);
  }
  return idx;
};

/**
 * The textured far ground round (fu, fv): the ground at its height (sunk 6 m where the chunks draw it: within nearHalf
 * of the anchor), every vertex with the six texture weights the mesher gives the near ground, and the sea's surface
 * over it. (Moved here unchanged from land.js buildFar, which ran it on the main thread.)
 */
export function farGround(face, fu, fv, nearHalf) {
  const N = FAR_N, STEP = FAR_STEP, V = (N + 1) * (N + 1);
  const anchor = posOf(face, fu, fv, 0), fr = frameOf(face, fu, fv);
  const pos = new Float32Array(V * 3), sea = new Float32Array(V * 3), uvw = new Float32Array(V * 3), suvw = new Float32Array(V * 3);
  const mats = new Int32Array(V);
  for (let j = 0, k = 0; j <= N; j++) for (let i = 0; i <= N; i++, k++) {
    const u = fu + (i - N / 2) * STEP, v = fv + (j - N / 2) * STEP;
    const w = wrap(face, Math.round(u), Math.round(v)), c = column(w.face, w.u, w.v);
    const near = Math.abs(i - N / 2) * STEP < nearHalf && Math.abs(j - N / 2) * STEP < nearHalf;
    const p = posOf(face, u, v, c.height - (near ? 6 : 0)), q = posOf(face, u, v, SEA + 0.88 - (near ? 6 : 0));
    for (let d = 0; d < 3; d++) { pos[k * 3 + d] = p[d] - anchor[d]; sea[k * 3 + d] = q[d] - anchor[d]; }
    const mu = ((u % 4096) + 4096) % 4096, mv = ((v % 4096) + 4096) % 4096;
    uvw[k * 3] = mu; uvw[k * 3 + 1] = mv; uvw[k * 3 + 2] = c.height;
    suvw[k * 3] = mu; suvw[k * 3 + 1] = mv; suvw[k * 3 + 2] = SEA + 1;
    mats[k] = terrainBlock(w.face, w.u, w.v, Math.max(1, c.top));
  }
  const nor = gridNormals(pos, N), seaNor = gridNormals(sea, N);
  // the weights need the slope, and rock's three-way projection a grid-space normal: the world normals in the frame here
  const gn = new Float32Array(V * 3), w1 = new Float32Array(V * 4), w2 = new Float32Array(V * 2), col = new Float32Array(V * 3).fill(1);
  for (let k = 0; k < V; k++) {
    const x = nor[k * 3], y = nor[k * 3 + 1], z = nor[k * 3 + 2];
    const ne = x * fr.east[0] + y * fr.east[1] + z * fr.east[2], nn = x * fr.north[0] + y * fr.north[1] + z * fr.north[2], nu = x * fr.up[0] + y * fr.up[1] + z * fr.up[2];
    gn[k * 3] = ne; gn[k * 3 + 1] = nn; gn[k * 3 + 2] = nu;
    const wt = groundWeights(mats[k], nu);
    w1.set(wt.slice(0, 4), k * 4); w2.set(wt.slice(4), k * 2);
  }
  const idx = new Uint32Array(gridIndex(N));
  return { face, fu, fv, anchor, pos, nor, sea, seaNor, uvw, suvw, gn, w1, w2, col, idx };
}

/**
 * Ring k of the distant land, anchored at (au, av): { anchor, pos, nor, col, idx }.
 *   hole: [u0, u1, v0, v1] — the ring inside it (its anchor +- its half): cells wholly inside are not drawn;
 *   sink: [cu, cv, inner] — ring 0 only: vertices within `inner` of the far ground's centre sink RING_SINK under it;
 *   last: the outermost ring — its corners past its half drop away, so its rim is a circle under the horizon.
 * The outer edge carries a skirt (a strip hung half a step down, both ways round): the next ring out shares the edge's
 * every other vertex, and the skirt fills the slivers between.
 */
export function farRing(k, face, au, av, hole, sink, last) {
  const { step, half } = RINGS[k], N = (2 * half) / step, M = N + 1, V = M * M;
  const anchor = posOf(face, au, av, 0);
  const cellU = (i) => au - half + i * step, cellV = (j) => av - half + j * step;
  const keep = (i, j) => !hole || !(cellU(i) >= hole[0] && cellU(i + 1) <= hole[1] && cellV(j) >= hole[2] && cellV(j + 1) <= hole[3]);
  const used = new Uint8Array(V);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) if (keep(i, j)) for (const [di, dj] of [[0, 0], [1, 0], [0, 1], [1, 1]]) used[(j + dj) * M + i + di] = 1;
  const pos = new Float32Array(V * 3), col = new Float32Array(V * 3), hs = new Float32Array(V);
  for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
    const q = j * M + i;
    if (!used[q]) continue;
    const u = cellU(i), v = cellV(j), du = u - au, dv = v - av;
    const w = wrap(face, Math.round(u), Math.round(v)), c = column(w.face, w.u, w.v);
    const wet = c.top <= SEA, can = wet ? 0 : canopyHeight(c);
    const kind = wet ? "sea" : can > 0 ? "forest" : c.biome in RING_COL ? c.biome : "grass";
    let h = wet ? SEA + 0.5 : c.height + can;
    if (sink && Math.max(Math.abs(u - sink[0]), Math.abs(v - sink[1])) < sink[2]) h -= RING_SINK;
    if (last && Math.hypot(du, dv) > half) h -= 400;
    hs[q] = h;
    const p = posOf(face, u, v, h);
    for (let d = 0; d < 3; d++) { pos[q * 3 + d] = p[d] - anchor[d]; col[q * 3 + d] = RING_COL[kind][d]; }
  }
  const nor = gridNormals(pos, N, used);
  const idx = gridIndex(N, keep);
  // the skirt round the outer edge: each edge vertex again, half a step lower
  const edge = [];
  for (let i = 0; i < N; i++) edge.push([i, 0, i + 1, 0], [N, i, N, i + 1], [i + 1, N, i, N], [0, i + 1, 0, i]);
  const extra = [], xcol = [], xnor = [];
  let next = V;
  const low = new Map();
  const lowOf = (i, j) => {
    const q = j * M + i;
    if (low.has(q)) return low.get(q);
    const p = posOf(face, cellU(i), cellV(j), hs[q] - step / 2);
    extra.push(p[0] - anchor[0], p[1] - anchor[1], p[2] - anchor[2]);
    xcol.push(col[q * 3], col[q * 3 + 1], col[q * 3 + 2]); xnor.push(nor[q * 3], nor[q * 3 + 1], nor[q * 3 + 2]);
    low.set(q, next); return next++;
  };
  for (const [i0, j0, i1, j1] of edge) {
    const a = j0 * M + i0, b = j1 * M + i1, la = lowOf(i0, j0), lb = lowOf(i1, j1);
    idx.push(a, b, lb, a, lb, la, a, lb, b, a, la, lb);
  }
  const all = (base, more) => { const out = new Float32Array(base.length + more.length); out.set(base); out.set(more, base.length); return out; };
  return { k, face, au, av, anchor, pos: all(pos, extra), nor: all(nor, xnor), col: all(col, xcol), idx: new Uint32Array(idx) };
}

/** The work of one far job (a mesher message): the far ground and/or the rings named, all for one place, swapped together. */
export function farJob(m) {
  const out = { far: true, rings: [] };
  if (m.ground) out.ground = farGround(m.face, m.ground.fu, m.ground.fv, m.ground.nearHalf);
  for (const r of m.rings) out.rings.push(farRing(r.k, m.face, r.au, r.av, r.hole, r.sink, r.k === RINGS.length - 1));
  return out;
}
/** The buffers a far job's result hands back to the page (transferred, not copied). */
export function farBuffers(res) {
  const tr = [];
  if (res.ground) for (const a of ["pos", "nor", "sea", "seaNor", "uvw", "suvw", "gn", "w1", "w2", "col", "idx"]) tr.push(res.ground[a].buffer);
  for (const r of res.rings) for (const a of ["pos", "nor", "col", "idx"]) tr.push(r[a].buffer);
  return tr;
}
