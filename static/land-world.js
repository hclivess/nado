// land-world.js — the Land planet as pure functions (doc/land.md): its geometry, its terrain, its blocks and a plot's
// commitment. Imported by the page (static/land.js), the mesher worker (static/land-mesher.js) and the tests, so all
// three agree on every block of the planet. No DOM, no three.js, no randomness that is not derived from WORLD_SEED.
//
// THE PLANET IS A CUBE-SPHERE. Six faces, each a W x W grid of block columns (W = FACE_N * PLOT = 131072, the same
// numbers execnode/games/land.py numbers its plots by), inflated onto a sphere with the equal-angle warp (tan), so a
// block is ~1 m across everywhere (±~30 % toward a face's corners). A column's blocks are radial layers 0..H-1 above
// the base radius R0. Grid coordinates (face, u, v, h) are the world's only coordinates; positions in metres are
// derived from them for drawing and never stored.
//
// TERRAIN IS A FUNCTION OF THE SEED. terrainBlock(face, u, v, h) is the untouched planet everywhere; what a plot owner
// changes is a sparse list of edits on top (the plot's data, committed on chain by plotCommitment). Noise is sampled on
// the unit sphere, so the terrain is continuous across the faces' seams.

export const FACE_N = 8192;                 // plots along a face edge (execnode/games/land.py FACE_N)
export const PLOT = 16;                     // blocks along a plot edge (land.py PLOT)
export const W = FACE_N * PLOT;             // 131072 block columns along a face edge
export const H = 256;                       // radial layers per column
export const SEA = 96;                      // the sea surface layer
export const R0 = W / (Math.PI / 2);        // ~83,443 m: a column ~1 m wide at a face's centre
export const CHUNK = 16;                    // a chunk is 16^3 blocks; a plot is one column of 16 chunks
export const PLOT_MAX = 6 * FACE_N * FACE_N;
export const WORLD_SEED = 0x4c616e64;      // "Land" — fixed for the life of the planet (titles are minted against it)
export const PLANET = 0;                    // this module is planet 0; every title names its planet (land.py plot_seed)

// A title's asset seed: "LAND" << 48 | planet << 32 | plot (execnode/games/land.py plot_seed). BigInt: it is 80 bits.
const LAND_TAG = 0x4c414e44n;
export const titleSeed = (plot, planet = PLANET) => (LAND_TAG << 48n) | (BigInt(planet) << 32n) | BigInt(plot);
/** { planet, plot } of a title seed, or null for any other asset's seed. */
export function titleOf(seed) {
  const s = BigInt(seed);
  if ((s >> 48n) !== LAND_TAG) return null;
  return { planet: Number((s >> 32n) & 0xffffn), plot: Number(s & 0xffffffffn) };
}

// The landing site: the first wave is this 10 x 10 block of plots — temperate grassland ~5 m above a sea in sight on
// two sides, near face 0's centre (squarest blocks), chosen by scanning the equator band for 100 dry grass plots of
// little relief with the sea close by (2026-11-06). Fixed for good once its titles are minted.
export const SPAWN_FACE = 0;
export const SPAWN_PLOT_ROW = 4924, SPAWN_PLOT_COL = 4662;

export const plotId = (face, prow, pcol) => (face * FACE_N + prow) * FACE_N + pcol;
export function plotOf(face, u, v) { return plotId(face, Math.floor(v / PLOT), Math.floor(u / PLOT)); }
export function plotCoords(id) {
  const pcol = id % FACE_N, prow = Math.floor(id / FACE_N) % FACE_N, face = Math.floor(id / (FACE_N * FACE_N));
  return { face, prow, pcol, u0: pcol * PLOT, v0: prow * PLOT };
}
export function firstWave() {
  const out = [];
  for (let r = 0; r < 10; r++) for (let c = 0; c < 10; c++) out.push(plotId(SPAWN_FACE, SPAWN_PLOT_ROW + r, SPAWN_PLOT_COL + c));
  return out;
}

// ---- geometry --------------------------------------------------------------------------------------------------
// face axes: n (outward normal), a (u direction), b (v direction); a right-handed-ish frame per face.
const FACES = [
  { n: [1, 0, 0], a: [0, 0, -1], b: [0, 1, 0] },
  { n: [-1, 0, 0], a: [0, 0, 1], b: [0, 1, 0] },
  { n: [0, 1, 0], a: [1, 0, 0], b: [0, 0, -1] },
  { n: [0, -1, 0], a: [1, 0, 0], b: [0, 0, 1] },
  { n: [0, 0, 1], a: [1, 0, 0], b: [0, 1, 0] },
  { n: [0, 0, -1], a: [-1, 0, 0], b: [0, 1, 0] },
];
const QUARTER = Math.PI / 4;

/** Unit direction of grid point (u, v) on `face` (u, v continuous; may lie beyond the face, the warp extends). */
export function dirOf(face, u, v) {
  const F = FACES[face];
  const x = Math.tan(((2 * u) / W - 1) * QUARTER), y = Math.tan(((2 * v) / W - 1) * QUARTER);
  const p0 = F.n[0] + F.a[0] * x + F.b[0] * y, p1 = F.n[1] + F.a[1] * x + F.b[1] * y, p2 = F.n[2] + F.a[2] * x + F.b[2] * y;
  const l = Math.hypot(p0, p1, p2);
  return [p0 / l, p1 / l, p2 / l];
}

/** World position (metres, planet centre at the origin) of grid point (face, u, v, h). */
export function posOf(face, u, v, h) {
  const d = dirOf(face, u, v), r = R0 + h;
  return [d[0] * r, d[1] * r, d[2] * r];
}

/** The inverse: which face a direction falls on and its continuous (u, v) there. */
export function gridOf(d) {
  let best = 0, bv = -Infinity;
  for (let f = 0; f < 6; f++) {
    const n = FACES[f].n, dot = n[0] * d[0] + n[1] * d[1] + n[2] * d[2];
    if (dot > bv) { bv = dot; best = f; }
  }
  const F = FACES[best];
  const x = (F.a[0] * d[0] + F.a[1] * d[1] + F.a[2] * d[2]) / bv, y = (F.b[0] * d[0] + F.b[1] * d[1] + F.b[2] * d[2]) / bv;
  return { face: best, u: ((Math.atan(x) / QUARTER + 1) * W) / 2, v: ((Math.atan(y) / QUARTER + 1) * W) / 2 };
}

/** Grid point (face, u, v) brought back onto the face that owns it — a column beyond a face edge is a column of the
 *  neighbouring face. Integers stay integers away from the seams; at a seam the nearest column is taken. */
export function wrap(face, u, v) {
  if (u >= 0 && u < W && v >= 0 && v < W) return { face, u, v };
  const g = gridOf(dirOf(face, u + 0.5, v + 0.5));
  return { face: g.face, u: Math.min(W - 1, Math.max(0, Math.floor(g.u))), v: Math.min(W - 1, Math.max(0, Math.floor(g.v))) };
}

/** Local frame at (face, u, v): up (radial), east (+u) and north (+v), orthonormal. */
export function frameOf(face, u, v) {
  const up = dirOf(face, u, v), e0 = dirOf(face, u + 1, v), n0 = dirOf(face, u, v + 1);
  const ortho = (w) => { const k = w[0] * up[0] + w[1] * up[1] + w[2] * up[2], x = w[0] - k * up[0], y = w[1] - k * up[1], z = w[2] - k * up[2], l = Math.hypot(x, y, z); return [x / l, y / l, z / l]; };
  const east = ortho([e0[0] - up[0], e0[1] - up[1], e0[2] - up[2]]);
  const nr = ortho([n0[0] - up[0], n0[1] - up[1], n0[2] - up[2]]);
  const k = nr[0] * east[0] + nr[1] * east[1] + nr[2] * east[2];      // make north exactly perpendicular to east
  const nx = nr[0] - k * east[0], ny = nr[1] - k * east[1], nz = nr[2] - k * east[2], nl = Math.hypot(nx, ny, nz);
  return { up, east, north: [nx / nl, ny / nl, nz / nl] };
}

// ---- noise -----------------------------------------------------------------------------------------------------
// Seeded 3-D gradient noise (Perlin's improved noise over a seeded permutation). Deterministic in IEEE doubles.
function mulberry(a) { return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function makePerm(seed) {
  const r = mulberry(seed), p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  for (let i = 255; i > 0; i--) { const j = Math.floor(r() * (i + 1)), t = p[i]; p[i] = p[j]; p[j] = t; }
  const P = new Uint8Array(512);
  for (let i = 0; i < 512; i++) P[i] = p[i & 255];
  return P;
}
const fade = (t) => t * t * t * (t * (t * 6 - 15) + 10);
const lerp = (a, b, t) => a + t * (b - a);
function grad(h, x, y, z) { const g = h & 15, u = g < 8 ? x : y, v = g < 4 ? y : g === 12 || g === 14 ? x : z; return ((g & 1) ? -u : u) + ((g & 2) ? -v : v); }
function noise3(P, x, y, z) {
  const X = Math.floor(x) & 255, Y = Math.floor(y) & 255, Z = Math.floor(z) & 255;
  x -= Math.floor(x); y -= Math.floor(y); z -= Math.floor(z);
  const u = fade(x), v = fade(y), w = fade(z);
  const A = P[X] + Y, AA = P[A] + Z, AB = P[A + 1] + Z, B = P[X + 1] + Y, BA = P[B] + Z, BB = P[B + 1] + Z;
  return lerp(lerp(lerp(grad(P[AA], x, y, z), grad(P[BA], x - 1, y, z), u), lerp(grad(P[AB], x, y - 1, z), grad(P[BB], x - 1, y - 1, z), u), v),
    lerp(lerp(grad(P[AA + 1], x, y, z - 1), grad(P[BA + 1], x - 1, y, z - 1), u), lerp(grad(P[AB + 1], x, y - 1, z - 1), grad(P[BB + 1], x - 1, y - 1, z - 1), u), v), w);
}
const PERM = [0, 1, 2, 3, 4].map((i) => makePerm(WORLD_SEED + i * 7919));
function fbm(P, x, y, z, oct, lac = 2, gain = 0.5) {
  let s = 0, a = 1, f = 1, n = 0;
  for (let i = 0; i < oct; i++) { s += a * noise3(P, x * f, y * f, z * f); n += a; a *= gain; f *= lac; }
  return s / n;
}

// ---- blocks ----------------------------------------------------------------------------------------------------
// id -> { key (i18n "land.b.<key>"), name (English default), solid, see (light passes: neighbours draw their face),
// build (in the builder's palette), tex [top, side, bottom] (atlas tiles, static/land.js paints them) }
export const BLOCKS = [
  { key: "air", name: "Air", solid: false, see: true, build: false },
  { key: "grass", name: "Grass", solid: true, build: true, tex: [1, 2, 3] },
  { key: "dirt", name: "Dirt", solid: true, build: true, tex: [3, 3, 3] },
  { key: "stone", name: "Stone", solid: true, build: true, tex: [4, 4, 4] },
  { key: "sand", name: "Sand", solid: true, build: true, tex: [5, 5, 5] },
  { key: "water", name: "Water", solid: false, see: true, build: false, liquid: true, tex: [6, 6, 6] },
  { key: "snow", name: "Snow", solid: true, build: true, tex: [7, 8, 3] },
  { key: "log", name: "Log", solid: true, build: true, tex: [10, 9, 10] },
  { key: "leaves", name: "Leaves", solid: true, see: true, build: true, tex: [11, 11, 11] },
  { key: "planks", name: "Planks", solid: true, build: true, tex: [12, 12, 12] },
  { key: "cobble", name: "Cobblestone", solid: true, build: true, tex: [13, 13, 13] },
  { key: "brick", name: "Brick", solid: true, build: true, tex: [14, 14, 14] },
  { key: "glass", name: "Glass", solid: true, see: true, build: true, tex: [15, 15, 15] },
  { key: "tiles", name: "Roof tiles", solid: true, build: true, tex: [16, 16, 16] },
  { key: "plaster", name: "Plaster", solid: true, build: true, tex: [17, 17, 17] },
  { key: "darkwood", name: "Dark planks", solid: true, build: true, tex: [18, 18, 18] },
  { key: "stonebrick", name: "Stone brick", solid: true, build: true, tex: [19, 19, 19] },
  { key: "gravel", name: "Gravel", solid: true, build: true, tex: [20, 20, 20] },
  { key: "basalt", name: "Basalt", solid: true, build: true, tex: [21, 21, 21] },
  { key: "ice", name: "Ice", solid: true, see: true, build: true, tex: [22, 22, 22] },
  { key: "lamp", name: "Lamp", solid: true, build: true, glow: true, tex: [23, 23, 23] },
  { key: "red", name: "Red wool", solid: true, build: true, tex: [24, 24, 24] },
  { key: "orange", name: "Orange wool", solid: true, build: true, tex: [25, 25, 25] },
  { key: "yellow", name: "Yellow wool", solid: true, build: true, tex: [26, 26, 26] },
  { key: "green", name: "Green wool", solid: true, build: true, tex: [27, 27, 27] },
  { key: "blue", name: "Blue wool", solid: true, build: true, tex: [28, 28, 28] },
  { key: "purple", name: "Purple wool", solid: true, build: true, tex: [29, 29, 29] },
  { key: "black", name: "Black wool", solid: true, build: true, tex: [30, 30, 30] },
  { key: "white", name: "White wool", solid: true, build: true, tex: [31, 31, 31] },
  { key: "marble", name: "Marble", solid: true, build: true, tex: [32, 32, 32] },
  { key: "bedrock", name: "Bedrock", solid: true, build: false, tex: [33, 33, 33] },
];
export const B = Object.fromEntries(BLOCKS.map((b, i) => [b.key, i]));
export const ATLAS_TILES = 34;              // tiles 0..33 (0 unused)
export const opaque = (id) => BLOCKS[id].solid && !BLOCKS[id].see;

// ---- terrain ---------------------------------------------------------------------------------------------------
/** The ground of column (face, u, v): { top (highest solid layer), biome } — the untouched planet. */
export function column(face, u, v) {
  const d = dirOf(face, u + 0.5, v + 0.5);
  const x = d[0] * R0, y = d[1] * R0, z = d[2] * R0;            // noise is sampled in METRES on the sphere
  const at = (P, len, oct) => fbm(P, x / len, y / len, z / len, oct);
  const cont = at(PERM[0], 30000, 5);                            // continents and seas, ~30 km
  const hills = at(PERM[1], 400, 4);                             // rolling ground, ~400 m
  const detail = at(PERM[2], 45, 2);                             // the ground's grain, ~45 m
  const rid = 1 - Math.abs(at(PERM[3], 2500, 5));                // mountain ridges, ~2.5 km
  const mtn = Math.max(0, at(PERM[4], 12000, 3) * 2.2 - 0.15);   // where the ranges are, ~12 km
  const height = Math.max(8, Math.min(H - 8, SEA + 4 + cont * 90 + hills * 14 + detail * 2.5 + rid * rid * rid * mtn * 110));
  const top = Math.floor(height);
  const temp = at(PERM[4], 20000, 3) * 0.6 + at(PERM[0], 7000, 2) * 0.4 - Math.abs(d[1]) * 0.55 - Math.max(0, top - SEA) * 0.004;
  const biome = top < SEA + 2 && top >= SEA - 3 ? "beach" : temp < -0.32 ? "snow" : top > SEA + 70 ? "rock" : "grass";
  return { top, height, biome };
}

function hash32(a, b, c) {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35) ^ Math.imul(c + 0x27d4eb2f, 0x165667b1);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return h >>> 0;
}

/** Is there a tree trunk rooted at column (face, u, v)? (one per ~70 grass columns, never on a plot's edge ring, so a
 *  tree's canopy stays inside the plot it grows on and a neighbour's edit never cuts it.) */
export function treeAt(face, u, v, col) {
  if (col.biome !== "grass" || col.top <= SEA + 1) return false;
  const lu = u % PLOT, lv = v % PLOT;
  if (lu < 2 || lu > PLOT - 3 || lv < 2 || lv > PLOT - 3) return false;
  return hash32(face, u, v) % 70 === 0;
}

const TREE_REACH = 10;

/** The untouched block at (face, u, v, h) — u, v integers on the face. */
export function terrainBlock(face, u, v, h, colCache) {
  if (h <= 0) return B.bedrock;
  const col = colCache ? colCache(face, u, v) : column(face, u, v);
  if (h <= col.top) {
    if (h < col.top - 3) return h < 4 ? B.bedrock : B.stone;
    if (col.biome === "beach") return B.sand;
    if (col.biome === "rock") return h === col.top && col.top > SEA + 95 ? B.snow : B.stone;
    if (col.top < SEA) return h === col.top ? B.gravel : B.dirt;
    if (h === col.top) return col.biome === "snow" ? B.snow : B.grass;
    return B.dirt;
  }
  if (h <= SEA) return col.biome === "snow" && h === SEA ? B.ice : B.water;
  // trees: a 5-high trunk and a canopy of radius 2, from roots within 2 columns. Nothing grows more than TREE_REACH
  // layers above a column's own ground — part of the world's definition (every client applies it), and what lets the
  // mesher skip the root search for the open air above every hill.
  if (h > col.top + TREE_REACH) return B.air;
  for (let du = -2; du <= 2; du++) for (let dv = -2; dv <= 2; dv++) {
    const ru = u + du, rv = v + dv;
    if (ru < 0 || rv < 0 || ru >= W || rv >= W) continue;
    const rc = colCache ? colCache(face, ru, rv) : column(face, ru, rv);
    if (!treeAt(face, ru, rv, rc)) continue;
    const dh = h - rc.top;
    if (du === 0 && dv === 0 && dh >= 1 && dh <= 5) return B.log;
    const r = Math.abs(du) + Math.abs(dv);
    if (dh >= 4 && dh <= 6 && r <= (dh === 6 ? 1 : 3) && !(du === 0 && dv === 0 && dh <= 5)) return B.leaves;
  }
  return B.air;
}

// ---- the smooth ground ---------------------------------------------------------------------------------------------
// "it should not really be blocky" (operator, 2026-11-06): NATURAL ground is drawn as a smooth surface, built materials
// stay crisp. The data is unchanged — cells with a block id — and the surface is the zero level of a FIELD over the cell
// centres, one definition shared by the mesher (what is drawn), collision and aiming (what is touched):
//   an untouched cell:  height(column) - (h + 0.5), clamped to [-1, 1] — the generator's exact, unrounded ground;
//   an edited cell:     +1 if a natural material was put there, -1 otherwise (dug out, or a built block, which carves
//                       its own room in the ground and is drawn crisp).
export const NATURAL = new Set([B.grass, B.dirt, B.stone, B.sand, B.snow, B.gravel, B.basalt, B.bedrock]);
export function fieldOf(col, h, edit) {
  if (edit !== undefined) return NATURAL.has(edit) ? 1 : -1;
  if (h <= 0) return 1;
  return Math.max(-1, Math.min(1, col.height - (h + 0.5)));
}

// ---- plot data and its commitment ---------------------------------------------------------------------------------
// A plot's data is its edit list: [x, z, y, block] with x (u - u0) and z (v - v0) in 0..15, y the layer in 0..H-1, and
// block an id (0 = air: the terrain block there was removed). Canonical form: sorted by (y, z, x), one entry per cell.
export function canonicalEdits(edits) {
  const m = new Map();
  for (const [x, z, y, b] of edits) {
    if (!(x >= 0 && x < PLOT && z >= 0 && z < PLOT && y >= 0 && y < H && Number.isInteger(b) && b >= 0 && b < BLOCKS.length)) throw new Error("bad edit");
    m.set((y * PLOT + z) * PLOT + x, b);
  }
  return [...m.keys()].sort((a, b) => a - b).map((k) => [k % PLOT, Math.floor(k / PLOT) % PLOT, Math.floor(k / (PLOT * PLOT)), m.get(k)]);
}
const enc = new TextEncoder();
/** The bytes a commitment hashes: tag, plot id (u32 BE), the 32-byte salt, then each edit as x u8, z u8, y u16 BE,
 *  block u8. scripts/land_server.py builds the same bytes (tests/test_a_plot_commitment_is_the_same_in_the_page_and_the_server). */
export function commitmentBytes(plot, salt, edits) {
  const tag = enc.encode("nado-land-plot-v1"), ce = canonicalEdits(edits);
  if (!(salt instanceof Uint8Array) || salt.length !== 32) throw new Error("salt must be 32 bytes");
  const out = new Uint8Array(tag.length + 4 + 32 + ce.length * 5);
  out.set(tag, 0);
  let o = tag.length;
  out[o++] = plot >>> 24; out[o++] = (plot >>> 16) & 255; out[o++] = (plot >>> 8) & 255; out[o++] = plot & 255;
  out.set(salt, o); o += 32;
  for (const [x, z, y, b] of ce) { out[o++] = x; out[o++] = z; out[o++] = y >>> 8; out[o++] = y & 255; out[o++] = b; }
  return out;
}
/** The commitment anchored on chain (land.py anchor arg 1): SHA-256 of commitmentBytes as a 256-bit integer string. */
export async function plotCommitment(plot, salt, edits) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", commitmentBytes(plot, salt, edits)));
  let n = 0n;
  for (const x of d) n = (n << 8n) | BigInt(x);
  return n === 0n ? "1" : n.toString();                         // the contract refuses 0; SHA-256 is never 0 in practice
}
