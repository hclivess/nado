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

import * as Shapes from "./land-shapes.js";

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
export const SPAWN_PLOT_ROW = 4995, SPAWN_PLOT_COL = 3435;   // a temperate meadow at a forest's edge (regenerated world, 2026-11-06)

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
const PERM = [0, 1, 2, 3, 4, 5, 6].map((i) => makePerm(WORLD_SEED + i * 7919));
function fbm(P, x, y, z, oct, lac = 2, gain = 0.5) {
  let s = 0, a = 1, f = 1, n = 0;
  for (let i = 0; i < oct; i++) { s += a * noise3(P, x * f, y * f, z * f); n += a; a *= gain; f *= lac; }
  return s / n;
}

// ---- blocks ----------------------------------------------------------------------------------------------------
// id -> { key (the mesher's ground colours), solid, see (light passes: neighbours draw their face), liquid, glow,
// tex [top, side, bottom] (atlas tiles, static/land.js paints them). What a block is CALLED, what breaking it gives and
// whether anyone can place it is static/land-recipes.json (items name the block they place).
export const BLOCKS = [
  { key: "air", solid: false, see: true },
  { key: "grass", solid: true, tex: [1, 2, 3] },
  { key: "dirt", solid: true, tex: [3, 3, 3] },
  { key: "stone", solid: true, tex: [4, 4, 4] },
  { key: "sand", solid: true, tex: [5, 5, 5] },
  { key: "water", solid: false, see: true, liquid: true, tex: [6, 6, 6] },
  { key: "snow", solid: true, tex: [7, 8, 3] },
  { key: "log", solid: true, tex: [10, 9, 10] },
  { key: "leaves", solid: true, see: true, tex: [11, 11, 11] },
  { key: "planks", solid: true, tex: [12, 12, 12] },
  { key: "cobble", solid: true, tex: [13, 13, 13] },
  { key: "brick", solid: true, tex: [14, 14, 14] },
  { key: "glass", solid: true, see: true, tex: [15, 15, 15] },
  { key: "tiles", solid: true, tex: [16, 16, 16] },
  { key: "plaster", solid: true, tex: [17, 17, 17] },
  { key: "darkwood", solid: true, tex: [18, 18, 18] },
  { key: "stonebrick", solid: true, tex: [19, 19, 19] },
  { key: "gravel", solid: true, tex: [20, 20, 20] },
  { key: "basalt", solid: true, tex: [21, 21, 21] },
  { key: "ice", solid: true, see: true, tex: [22, 22, 22] },
  { key: "lamp", solid: true, glow: true, tex: [23, 23, 23] },
  { key: "red", solid: true, tex: [24, 24, 24] },
  { key: "orange", solid: true, tex: [25, 25, 25] },
  { key: "yellow", solid: true, tex: [26, 26, 26] },
  { key: "green", solid: true, tex: [27, 27, 27] },
  { key: "blue", solid: true, tex: [28, 28, 28] },
  { key: "purple", solid: true, tex: [29, 29, 29] },
  { key: "black", solid: true, tex: [30, 30, 30] },
  { key: "white", solid: true, tex: [31, 31, 31] },
  { key: "marble", solid: true, tex: [32, 32, 32] },
  { key: "bedrock", solid: true, tex: [33, 33, 33] },
  // the forest's other species (appended: every id above keeps its meaning) — static/land-mesher.js draws them organic
  { key: "birchlog", solid: true, tex: [10, 34, 10] },
  { key: "needles", solid: true, see: true, tex: [35, 35, 35] },
  { key: "fronds", solid: true, see: true, tex: [36, 36, 36] },
  // litter on the ground (appended): picked up by hand, walked through, drawn as a stone or a fallen stick (land-mesher.js)
  { key: "pebble", solid: false, see: true, tex: [4, 4, 4] },
  { key: "twigs", solid: false, see: true, tex: [10, 10, 10] },
  // a real house (appended, "continue working until the crafting tree has all components to build A REAL HOUSE"):
  // iron ore in veins through the rock; doors, hewn timber and thatch to build with
  { key: "ironore", solid: true, tex: [37, 37, 37] },
  { key: "door", solid: true, tex: [38, 38, 38] },
  { key: "beam", solid: true, tex: [39, 39, 39] },
  { key: "thatch", solid: true, tex: [40, 40, 40] },
  // a window: a timber frame with a cross mullion around a thin pane, made whole (land-mesher.js meshWindow) — set into a
  // wall's frame as in Medieval Dynasty's window walls, not a sheet of blue glass ("windows on the house look weird")
  { key: "window", solid: true, tex: [41, 41, 41] },
  // BELOW GROUND ("start creating various structures and adding additional recipes and materials ... in a sensible,
  // realistic yet engaging manner", operator 2026-11-07): coal for fuel, copper and tin for bronze, clay beds in the soil
  { key: "coal", solid: true, tex: [42, 42, 42] },
  { key: "copperore", solid: true, tex: [43, 43, 43] },
  { key: "tinore", solid: true, tex: [44, 44, 44] },
  { key: "clay", solid: true, tex: [45, 45, 45] },
  // FURNISHING A HOUSE ("start creating various structures ... in a sensible, realistic yet engaging manner", operator
  // 2026-11-07): unit items, each drawn as its real model (land-mesher.js MODELS: legs, a top, a back, rails), not a box
  { key: "table", solid: true, tex: [12, 12, 12] },
  { key: "chair", solid: true, tex: [12, 12, 12] },
  { key: "bench", solid: true, tex: [12, 12, 12] },
  { key: "bed", solid: true, tex: [12, 12, 12] },
  { key: "fence", solid: true, tex: [39, 39, 39] },
  { key: "torch", solid: true, tex: [18, 18, 18] },
  // flax: it grows in stands on the meadows, a litter plant pulled up by hand (land-trees.js flaxModel)
  { key: "flax", solid: false, see: true, tex: [11, 11, 11] },
  // a sapling: planted in soil, it grows into a young tree of its climate (scripts/land_server.py ECOLOGY)
  { key: "sapling", solid: false, see: true, tex: [11, 11, 11] },
  // MORE STRUCTURES (#114): a ladder the walker climbs (land.js step, land-walk.js climb) and a chest that holds items on
  // its plot (scripts/land_server.py chest) — unit pieces drawn as their models (land-mesher.js MODELS)
  { key: "ladder", solid: true, tex: [12, 12, 12] },
  { key: "chest", solid: true, tex: [12, 12, 12] },
  // FIRE (#124): a burning cell — flames in the air beside something that burns (scripts/land_server.py FIRE); it glows,
  // lights the night and is walked through (and hurts nothing yet)
  { key: "fire", solid: false, see: true, glow: true, tex: [23, 23, 23] },
  // THE DEEP (#129, doc/land-core.md): veins below 300 m of the deep crust hold silver and gold
  { key: "silverore", solid: true, tex: [46, 46, 46] },
  { key: "goldore", solid: true, tex: [47, 47, 47] },
  // WILD FLOWERS (operator 2026-11-07: "make the town tile beautiful … if anything is amiss, add it"): they grow in drifts
  // on the meadows, are picked by hand and planted like a sapling (land-trees.js flowerModel)
  { key: "poppy", solid: false, see: true, tex: [11, 11, 11] },
  { key: "cornflower", solid: false, see: true, tex: [11, 11, 11] },
  { key: "daisy", solid: false, see: true, tex: [11, 11, 11] },
  { key: "buttercup", solid: false, see: true, tex: [11, 11, 11] },
  // LIGHT ("we could use some more intense sources of light - townhall disappears after walking 20 meters at night",
  // operator 2026-11-07): a lantern (glass round a flame, an iron frame) and a street lamp (a lantern on an iron post) —
  // unit pieces drawn as their models; they light the night much farther than a torch (land.js LIGHTS)
  { key: "lantern", solid: true, glow: true, tex: [23, 23, 23] },
  { key: "lamppost", solid: true, glow: true, tex: [23, 23, 23] },
  // TOWARD FLIGHT (#146, "tech up and build an X fighter … you add techs all the way until you can build an X fighter",
  // operator 2026-11-09): steel plate to build a hull with, and the two working parts of a craft — a thruster and a pilot
  // seat — each made by recipe from what the planet holds (land-recipes.json; doc/land-tech-to-flight.md)
  { key: "steelplate", solid: true, tex: [48, 48, 48] },
  { key: "thruster", solid: true, tex: [49, 49, 49] },
  { key: "pilotseat", solid: true, tex: [50, 50, 50] },
  // FACTORIES (#148, "we also may need factorization like factorio or Satisfactory … for advanced tech", operator
  // 2026-11-09): machines that run a recipe by themselves from the chests beside them, and the generator that powers them
  { key: "smelter", solid: true, tex: [51, 51, 51] },
  { key: "assembler", solid: true, tex: [52, 52, 52] },
  { key: "generator", solid: true, tex: [53, 53, 53] },
  // FOOD AND FARMING (#153, #154: "we will need all the civilisation essentials like berries, hunting, crops…",
  // "farmland, farming, soil types, etc", operator 2026-11-09; doc/land-civilisation.md): a berry bush and wild grain
  // grow on the planet as litter does (models, walked through), sown wheat grows on tilled FARMLAND — natural ground,
  // drawn smooth as earth tinted by its soil
  { key: "berrybush", solid: false, see: true, tex: [11, 11, 11] },
  { key: "wheat", solid: false, see: true, tex: [11, 11, 11] },
  { key: "wheatyoung", solid: false, see: true, tex: [11, 11, 11] },
  { key: "farmland", solid: true, tex: [3, 3, 3] },
  // A WELL (#155): a piece of dressed stone over water; Use on it with a bucket draws a bucketful, and it never runs dry
  { key: "well", solid: true, tex: [19, 19, 19] },
  // A TRADING STAND (#161): a market stall of planks; offers are made at one and taken at the stands near it
  { key: "stand", solid: true, tex: [12, 12, 12] },
  // FINDING THE WAY (#173, doc/land-navigation.md): magnetite, an iron ore that is magnetic (Magnetite l.47), runs in some of
  // the iron veins; near the surface some of it is lodestone — magnetite magnetised, the leading theory says by lightning
  // (Lodestone l.66) — which magnetises the needle of a compass. Drawn from photographs (land research ore/OBSERVED.md).
  { key: "magnetite", solid: true, tex: [54, 54, 54] },
  { key: "lodestone", solid: true, tex: [55, 55, 55] },
  // the NAV UNIT (#173, doc/land-navigation.md 1.4): an instrument a craft carries — built into it like its seat, it
  // tells the pilot the way to the town hall by dead reckoning (land-flight.js navSays)
  { key: "navunit", solid: true, tex: [56, 56, 56] },
  // PROPELLANT FROM WATER (#173, doc/land-navigation.md 1.5): an electrolyser splits water into hydrogen and oxygen, a
  // liquefier cools them to liquid — machines, run on a generator's power like the smelter and the assembler, each run
  // charged the energy its recipe takes (land-recipes.json "mj"; land research rockets/ENERGY.md)
  { key: "electrolyser", solid: true, tex: [57, 57, 57] },
  { key: "liquefier", solid: true, tex: [58, 58, 58] },
  // ROCKETS (#173, doc/land-navigation.md 1.5): an engine, a propellant tank and a positioning satellite, built on a launch
  // pad — the world server computes the launch from their masses (land_server.py launch_numbers)
  { key: "rocketengine", solid: true, tex: [59, 59, 59] },
  { key: "proptank", solid: true, tex: [60, 60, 60] },
  { key: "satellite", solid: true, tex: [61, 61, 61] },
  { key: "launchpad", solid: true, tex: [62, 62, 62] },
  // a BOULDER (#183 step 5, #181 "potato stones"): the planet's own rock lying on the meadow or the forest floor — drawn
  // by the mesher as a rock of the pebble's kind a metre and a half across (litter: never a cube), SOLID to the player
  // and to a craft (the cell), broken only with a pick (land-recipes.json breaking), never swept by a placed block
  { key: "boulder", solid: true, see: true, tex: [4, 4, 4] },
];
export const B = Object.fromEntries(BLOCKS.map((b, i) => [b.key, i]));
export const ATLAS_TILES = 63;              // tiles 0..62 (0 unused; the farm's blocks reuse earth's and leaves')
export const opaque = (id) => BLOCKS[id].solid && !BLOCKS[id].see;

// ---- terrain ---------------------------------------------------------------------------------------------------
/** The ground of column (face, u, v): { top (highest solid layer), biome } — the untouched planet. */
export function column(face, u, v) {
  const d = dirOf(face, u + 0.5, v + 0.5);
  const x = d[0] * R0, y = d[1] * R0, z = d[2] * R0;            // noise is sampled in METRES on the sphere
  const at = (P, len, oct) => fbm(P, x / len, y / len, z / len, oct);
  // RELIEF ("the land is basically flat", operator 2026-11-06: hills were ±14 m over 400 m, so a walk saw a plain).
  const cont = at(PERM[0], 30000, 5);                            // continents and seas, ~30 km
  const hills = at(PERM[1], 900, 4);                             // hills and dales, ~900 m, ±30 m
  const vales = at(PERM[5], 220, 3);                             // the ground's folds, ~220 m
  const detail = at(PERM[2], 45, 2);                             // its grain, ~45 m
  const rid = 1 - Math.abs(at(PERM[3], 2500, 5));                // mountain ridges, ~2.5 km
  const mtn = Math.max(0, at(PERM[4], 9000, 3) * 2.4 - 0.05);    // where the ranges are, ~9 km (more of them)
  let height = SEA + 5 + cont * 80 + hills * 30 + vales * 8 + detail * 2.5 + rid * rid * rid * mtn * 130;
  if (height > SEA + 110) height = SEA + 110 + (height - SEA - 110) * 0.35;   // high peaks compressed, never cut flat
  height = Math.max(8, Math.min(H - 8, height));
  const top = Math.floor(height);
  // CLIMATE: temperature (latitude, altitude, broad noise) and moisture; the biome follows both ("there are no biomes")
  const temp = at(PERM[4], 20000, 3) * 0.6 + at(PERM[0], 7000, 2) * 0.4 - Math.max(0, Math.abs(d[1]) - 0.55) * 1.1 - Math.max(0, top - SEA) * 0.0025;
  const wet = at(PERM[6], 8000, 3) * 0.8 + at(PERM[6], 1500, 2) * 0.3;
  // FORESTS GROW IN PATCHES ("trees should generate the way normal trees generate? in patches called forests"): a forest
  // field over ~1 km, wetter ground more wooded
  const woods = at(PERM[5], 1100, 3) + wet * 0.35;
  const biome = top < SEA + 2 && top >= SEA - 3 ? "beach"
    : top > SEA + 95 ? "rock"
    : temp < -0.28 ? "snow"
    : temp > 0.0 && wet < -0.04 ? "desert"
    : woods > 0.12 ? "forest" : "grass";
  // the soil's depth before rock, varying over ~60 m — measured 5 to 8 layers ("there is barely any digging depth",
  // operator 2026-11-06: it was 3 everywhere, so a spade met rock almost at once)
  const soil = 4 + Math.min(5, Math.max(0, Math.floor((at(PERM[3], 60, 2) * 0.5 + 0.5) * 6)));
  return { top, height, biome, soil, temp, wet, woods };
}

// ---- SOILS (#154, "farmland, farming, soil types, etc", operator 2026-11-09): the ground under the turf is not one
// dirt. Its kind follows what the generator already knows — sand by the sea and in deserts, stone on the heights, peat
// where it is cold and wet, clay where the subsoil's clay beds lie, loam everywhere else — and it rules a field: how
// long a crop takes and what it gives (land-recipes.json "farming"). A pure function of the place: page, server and
// tests read the same soil.
export const SOILS = ["loam", "sandy", "clay", "peat", "stony"];
export function soilOf(face, u, v, col) {
  col = col || column(face, u, v);
  if (col.biome === "beach" || col.biome === "desert") return "sandy";
  if (col.biome === "rock" || col.top > SEA + 70) return "stony";
  if (col.temp < -0.12 && col.wet > 0.05) return "peat";
  if (noise3(PERM[2], u / 37, v / 37, face * 131) > 0.18) return "clay";        // over the subsoil's clay beds (terrainBlock)
  if (col.wet > 0.32 && col.top < SEA + 14) return "peat";                       // a wet lowland: a fen
  return "loam";
}

function hash32(a, b, c) {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35) ^ Math.imul(c + 0x27d4eb2f, 0x165667b1);
  h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12; h = Math.imul(h, 0x297a2d39); h ^= h >>> 15;
  return h >>> 0;
}


const TREE_REACH = 12;                       // the tallest conifer's crown, above its root's ground

// ---- the forest ("single tree type?", operator 2026-11-06) -------------------------------------------------------
// A tree's species and size are a function of its root's place and climate, so every browser and the server grow the
// same forest: broadleaf (round crowns), birch (slim, white bark), conifers (cones of needles; more of them uphill, the
// only trees in snow), palms on beaches (a crown of fronds) and bushes in meadows. Every crown stays within 2 columns of
// its root and roots keep 2 columns from a plot edge, so no tree straddles two plots.
export const TREE_WOOD = new Set([B.log, B.birchlog]);
export const TREE_LEAVES = new Set([B.leaves, B.needles, B.fronds]);
export const isTree = (b) => TREE_WOOD.has(b) || TREE_LEAVES.has(b);
/** The tree rooted at column (face, u, v): { kind, height } or null. */
/** The young tree a sapling at column (face, u, v) grows into (scripts/land_server.py ECOLOGY): its climate's species, as
 *  treeAt picks them, at a young height — a conifer where it is cold or high, a birch in the cool, else a broadleaf. */
export function saplingTree(face, u, v, col) {
  const cold = col.temp < -0.12 || col.top > SEA + 60, cool = col.temp < 0.05;
  return cold ? { kind: "conifer", height: 6 } : cool && hash32(face + 7, u, v) % 2 ? { kind: "birch", height: 5 } : { kind: "broadleaf", height: 4 };
}
// INVARIANT (#183, treeRoots below): a TREE (not a bush) needs roll < TREE_ROLL_MAX, or — a palm — hh % 60 === 0.
// treeRoots skips every other column without building it; raise a tree's odds past TREE_ROLL_MAX here and the forest
// beyond the chunks silently loses those trees (tests/test_the_forest_stands_beyond_the_chunks_as_pictures_of_its_own_trees.mjs
// asks treeAt of every biome at its densest and fails on a tree treeChance rules out).
export const TREE_ROLL_MAX = 0.09;
/** Whether column (face, u, v)'s hash leaves a TREE possible at all (whatever its biome turns out to be). */
export function treeChance(face, u, v) { const hh = hash32(face, u, v); return (hh % 100003) / 100003 < TREE_ROLL_MAX || hh % 60 === 0; }
export function treeAt(face, u, v, col) {
  const lu = u % PLOT, lv = v % PLOT;
  if (lu < 2 || lu > PLOT - 3 || lv < 2 || lv > PLOT - 3 || col.top <= SEA) return null;
  const hh = hash32(face, u, v), r = (hh >>> 8) % 100, size = (hh >>> 16) % 4, roll = (hh % 100003) / 100003;
  // the climate picks the species: conifers where it is cold or high, birch in the cool and wet, broadleaf in the mild
  const cold = col.temp < -0.12 || col.top > SEA + 60, cool = col.temp < 0.05;
  const species = () => cold ? (r < 80 ? { kind: "conifer", height: 7 + size } : { kind: "birch", height: 6 + (size >> 1) })
    : cool ? (r < 30 ? { kind: "conifer", height: 7 + size } : r < 60 ? { kind: "birch", height: 6 + (size >> 1) } : { kind: "broadleaf", height: 4 + (size >> 1) })
    : (r < 18 ? { kind: "birch", height: 6 + (size >> 1) } : { kind: "broadleaf", height: 4 + (size >> 1) });
  switch (col.biome) {
    case "forest": {
      // dense inside, thinning toward its edge (the forest field), an understorey of bushes
      const inside = Math.min(1, Math.max(0, (col.woods - 0.12) / 0.25));
      if (roll < 0.035 + 0.055 * inside) return species();
      if (roll > 0.97) return { kind: "bush", height: 1 };
      return null;
    }
    case "grass":
      if (roll < 0.004) return species();                     // a lone tree in the meadow
      if (roll > 0.975) return { kind: "bush", height: 1 };
      return null;
    case "snow":
      if (roll < (col.wet > 0 ? 0.03 : 0.006)) return { kind: "conifer", height: 6 + size };   // taiga where it is wet
      return null;
    case "beach":
      return col.temp > 0 && hh % 60 === 0 ? { kind: "palm", height: 6 + (size >> 1) } : null;
    case "desert":
      return roll > 0.996 ? { kind: "bush", height: 1 } : null;
  }
  return null;
}
/** Every TREE (bushes left out) rooted in the size x size square of columns from (u0, v0) of `face` — columns past a face
 *  edge are the neighbouring face's (wrap) — as [{ u, v, face, wu, wv, col, tree }], (u, v) in `face`'s own frame and
 *  (face, wu, wv) the column that owns the root. Exactly the trees treeAt names, found without building the nine columns
 *  in ten whose hash already rules a tree out (treeAt's INVARIANT) — the far forest asks this of a million columns. */
export function treeRoots(face, u0, v0, size) {
  const out = [];
  for (let v = v0; v < v0 + size; v++) for (let u = u0; u < u0 + size; u++) {
    const w = wrap(face, u, v), lu = w.u % PLOT, lv = w.v % PLOT;
    if (lu < 2 || lu > PLOT - 3 || lv < 2 || lv > PLOT - 3) continue;
    if (!treeChance(w.face, w.u, w.v)) continue;
    const col = column(w.face, w.u, w.v), tree = treeAt(w.face, w.u, w.v, col);
    if (tree && tree.kind !== "bush") out.push({ u, v, face: w.face, wu: w.u, wv: w.v, col, tree });
  }
  return out;
}
/** What tree `t` rooted at (du, dv) from this column puts at `dh` layers above its root's ground (or air). The mesher
 *  reads it too: a tree whose cells are all untouched is drawn as a model (land-trees.js) in their place. */
export function treeCell(t, du, dv, dh) {
  const r = Math.abs(du) + Math.abs(dv), H0 = t.height;
  switch (t.kind) {
    case "broadleaf":
      if (r === 0 && dh >= 1 && dh <= H0) return B.log;
      if (dh >= H0 - 1 && dh <= H0 + 1 && r <= (dh === H0 + 1 ? 1 : 3)) return B.leaves;
      return 0;
    case "birch":
      if (r === 0 && dh >= 1 && dh <= H0) return B.birchlog;
      if (dh >= H0 - 2 && dh <= H0 + 1 && r <= (dh >= H0 ? 1 : 2) && !(r === 2 && Math.abs(du) === 1)) return B.leaves;
      return 0;
    case "conifer": {
      if (r === 0 && dh >= 1 && dh <= H0) return B.log;
      if (dh < 3 || dh > H0 + 1) return 0;
      const rad = Math.round(((H0 + 1 - dh) * 2.6) / (H0 - 1));       // a cone, widest at the bottom of the crown
      return r <= Math.min(2, rad) ? B.needles : 0;
    }
    case "palm":
      if (r === 0 && dh >= 1 && dh <= H0) return B.log;
      if (dh === H0 + 1 && r <= 2) return B.fronds;
      if (dh === H0 && r === 1) return B.fronds;
      return 0;
    case "bush":
      if (dh === 1 && r <= 1) return B.leaves;
      if (dh === 2 && r === 0) return B.leaves;
      return 0;
  }
  return 0;
}

// ---- litter: loose stones and fallen sticks ("where the fuck do i take stone and sticks?", operator 2026-11-06) ---------
// The first stone and the first sticks lie on the ground, in plain sight, and come up by hand in a moment — the way into
// the whole web of tools. Before this, stone was a hidden bonus in every 4th clod of turf and sticks came only from
// leaves, which nobody could find without reading the source. A litter cell is the air cell just above the ground; it is
// a function of place like everything else, and like every gathered cell in the commons it lies there again later.
export const FLOWERS = [B.poppy, B.cornflower, B.daisy, B.buttercup];
export const LITTER = new Set([B.pebble, B.twigs, B.flax, B.sapling, ...FLOWERS, B.berrybush, B.wheat, B.wheatyoung, B.boulder]);   // drawn as models; walked through (a boulder: solid)
// A BLOCK TAKES THE PLACE OF LOOSE LITTER (a pebble, twigs, flax, a wild flower) and the placer picks it up, as in every
// block game's tall grass: they filled the meadow's air cells, so a block aimed at a flowery spot went into the empty
// cell over it, a metre up ("sometimes it places it above", 2026-11-08). A planted sapling is someone's — never swept.
// scripts/land_server.py SWEPT is the same set.
export const SWEPT = new Set([B.pebble, B.twigs, B.flax, ...FLOWERS, B.berrybush, B.wheat]);   // a sown crop is not swept: someone's field
// WHAT BURNS (#124), and what it leaves: a cell of grass burns to bare earth, wood, leaves, litter and plants to air; a
// built piece of these materials burns down whole (scripts/land_server.py FIRE). Stone, earth, sand, brick, metal,
// glass and water do not burn — they are what stops a fire.
export const BURNS = new Map([[B.grass, B.dirt], [B.log, 0], [B.birchlog, 0], [B.leaves, 0], [B.needles, 0], [B.fronds, 0],
  [B.twigs, 0], [B.flax, 0], [B.sapling, 0], [B.poppy, 0], [B.cornflower, 0], [B.daisy, 0], [B.buttercup, 0],
  [B.berrybush, 0], [B.wheat, 0], [B.wheatyoung, 0]]);
export const PIECE_BURNS = new Set([B.planks, B.darkwood, B.thatch, B.beam, B.door, B.window, B.table, B.chair, B.bench,
  B.bed, B.fence, B.torch, B.ladder, B.chest]);
export const BOULDER_MEADOW = 1600, BOULDER_WOOD = 900;   // columns per boulder: one in a 40 m square of meadow, one in a 30 m square of wood
/** The litter on column (face, u, v): B.boulder, B.pebble, B.twigs, B.flax, a flower, wild grain, a berry bush or 0. */
export function litterAt(face, u, v, col) {
  if (col.top <= SEA) return 0;
  // BOULDERS (#183 step 5: the concept picture's mossy boulder; land research look/step5/OBSERVED.md, the Tahoe erratic):
  // one column in BOULDER_MEADOW of a meadow and one in BOULDER_WOOD of a wood carries the planet's own rock — a density
  // chosen for the look (a design choice, not a measured one), a rock in sight from most of a meadow and none in a desert
  const bh = hash32(face + 71, v, u);
  if ((col.biome === "grass" && bh % BOULDER_MEADOW === 0) || (col.biome === "forest" && bh % BOULDER_WOOD === 0)) return B.boulder;
  const hh = hash32(face + 17, v, u);
  switch (col.biome) {
    // FLAX grows in STANDS, as a sown or wild crop does — a patch of meadow (one 8 m region in nine) thick with it, then
    // none for a while — so a player who finds one finds plenty (2026-11-07)
    // WILD FLOWERS in drifts: one 8 m region in seven is a patch of one kind (the region's hash picks which), a cell in
    // four of it in bloom — a walk across the meadow passes a red patch, then a white one
    case "grass": return hh % 17 === 4 ? B.pebble : hh % 19 === 9 ? B.twigs
      : hash32(face + 53, v >> 3, u >> 3) % 9 === 0 && hh % 5 < 3 ? B.flax
      : hash32(face + 61, v >> 3, u >> 3) % 7 === 0 && hh % 4 === 1 ? FLOWERS[hash32(face + 67, v >> 3, u >> 3) % 4]
      // WILD GRAIN in stands like flax (one 8 m region in eleven), BERRY BUSHES scattered at the meadow's edge (#153) —
      // only where nothing else stood, so every older litter cell is where it was
      : hash32(face + 71, v >> 3, u >> 3) % 11 === 0 && hh % 5 < 2 ? B.wheat : hh % 97 === 17 ? B.berrybush : 0;
    case "forest": return hh % 23 === 4 ? B.pebble : hh % 9 === 2 ? B.twigs : hh % 71 === 13 ? B.berrybush : 0;   // a forest floor is strewn with sticks
    case "desert": return hh % 13 === 6 ? B.pebble : 0;
    case "rock": return hh % 6 === 1 ? B.pebble : 0;
    case "beach": return hh % 23 === 5 ? B.pebble : hh % 41 === 7 ? B.twigs : 0;
    case "snow": return hh % 29 === 2 ? B.pebble : 0;
  }
  return 0;
}

// ---- THE DEEP (#129, doc/land-core.md phase 1): below layer 0 — under the crust's bedrock floor (layers 0..3) — lies the
// deep crust, down to DEEP_MIN, still on the surface grid (shell 0 reaches 41.8 km; no shell boundary is needed yet).
// Stone, threaded by the same kind of veins as the rock above; below DEEP_RICH layers the veins also hold silver and
// gold. Under DEEP_MIN the floor of what is built so far is bedrock again (the mantle is phase 3).
export const DEEP_MIN = -2048;               // a whole number of chunks (CHUNK), so a chunk is never half deep
export const DEEP_RICH = -300;
// MAGNETITE (#173): a quarter of the ~8 m regions an iron vein runs through hold magnetite instead — the same ore family,
// smelted to iron the same way (land-recipes.json iron_magnetite), so no iron is lost to it (the share is a design choice).
// Within LODE_DEPTH of the rock's top it is LODESTONE: lightning, the leading theory of how magnetite is magnetised
// (Lodestone l.66), reaches the rock near the surface, never the deep — the depth is a design choice.
export const LODE_DEPTH = 8;
const isMagnetite = (face, u, v, h) => hash32(face + 37, (u >> 3) * 5 + (h >> 3), v >> 3) % 4 === 0;
export function deepBlock(face, u, v, h) {
  if (h < DEEP_MIN) return B.bedrock;
  if (!(noise3(PERM[6], u / 7.3, v / 7.3, h / 4.1 + face * 977) > 0.33)) return B.stone;
  const r = hash32(face + 31, (u >> 3) * 7 + (h >> 3), v >> 3) % 100;
  if (h > DEEP_RICH) return r >= 40 && r < 75 && isMagnetite(face, u, v, h) ? B.magnetite : r < 40 ? B.coal : r < 75 ? B.ironore : r < 92 ? B.copperore : B.tinore;
  if (r >= 30 && r < 56 && isMagnetite(face, u, v, h)) return B.magnetite;
  return r < 30 ? B.coal : r < 56 ? B.ironore : r < 70 ? B.copperore : r < 80 ? B.tinore : r < 93 ? B.silverore : B.goldore;
}

/** The untouched block at (face, u, v, h) — u, v integers on the face. */
export function terrainBlock(face, u, v, h, colCache) {
  if (h < 0) return deepBlock(face, u, v, h);
  if (h === 0) return B.bedrock;
  const col = colCache ? colCache(face, u, v) : column(face, u, v);
  if (h <= col.top) {
    if (h < col.top - col.soil + 1) {
      if (h < 4) return B.bedrock;
      // ORE VEINS through the rock: ONE 3-D field over a few metres says where a vein runs (so it runs on as you follow
      // it), and a hash of the ~8 m region it runs through says what it holds — coal most often, then iron, copper, and
      // tin rarest (bronze is copper with a little tin, as in the world). One noise per rock cell: the mesher reads
      // every cell of a chunk, and four fields would have cost four times as much.
      if (!(noise3(PERM[6], u / 7.3, v / 7.3, h / 4.1 + face * 977) > 0.33)) return B.stone;
      const r = hash32(face + 31, (u >> 3) * 7 + (h >> 3), v >> 3) % 100;
      if (r >= 40 && r < 75 && isMagnetite(face, u, v, h)) return h >= col.top - col.soil + 1 - LODE_DEPTH ? B.lodestone : B.magnetite;
      return r < 40 ? B.coal : r < 75 ? B.ironore : r < 92 ? B.copperore : B.tinore;
    }
    // CLAY BEDS in the subsoil (two to four layers down) where a broad field says the ground is clayey — clay is dug,
    // not conjured from earth and sand
    if (h < col.top - 1 && h >= col.top - 4 && (col.biome === "grass" || col.biome === "forest" || col.biome === "beach")
        && noise3(PERM[2], u / 37, v / 37, face * 131) > 0.18) return B.clay;
    if (col.biome === "beach" || col.biome === "desert") return B.sand;
    if (col.biome === "rock") return h === col.top && col.top > SEA + 95 ? B.snow : B.stone;
    if (col.top < SEA) return h === col.top ? B.gravel : B.dirt;
    if (h === col.top) return col.biome === "snow" ? B.snow : B.grass;
    return B.dirt;
  }
  if (h <= SEA) return col.biome === "snow" && h === SEA ? B.ice : B.water;
  // trees, from roots within 2 columns (treeCell). Nothing grows more than TREE_REACH layers above a column's own
  // ground — part of the world's definition (every client applies it), and what lets the mesher skip the root search
  // for the open air above every hill. A trunk wins over a neighbour's crown in its own column.
  if (h > col.top + TREE_REACH) return B.air;
  let found = B.air;
  for (let du = -2; du <= 2; du++) for (let dv = -2; dv <= 2; dv++) {
    const ru = u - du, rv = v - dv;
    if (ru < 0 || rv < 0 || ru >= W || rv >= W) continue;
    const rc = colCache ? colCache(face, ru, rv) : column(face, ru, rv), t = treeAt(face, ru, rv, rc);
    if (!t) continue;
    const b = treeCell(t, du, dv, h - rc.top);
    if (TREE_WOOD.has(b)) return b;
    if (b && !found) found = b;
  }
  if (!found && h === col.top + 1) return litterAt(face, u, v, col) || B.air;
  return found;
}

// ---- the smooth ground ---------------------------------------------------------------------------------------------
// "it should not really be blocky" (operator, 2026-11-06): NATURAL ground is drawn as a smooth surface, built materials
// stay crisp. The data is unchanged — cells with a block id — and the surface is the zero level of a FIELD over the cell
// centres, one definition shared by the mesher (what is drawn), collision and aiming (what is touched):
//   an untouched cell:  height(column) - (h + 0.5), clamped to [-1, 1] — the generator's exact, unrounded ground;
//   an edited cell:     +1 if a natural material was put there, -1 otherwise (dug out, or a built block, which carves
//                       its own room in the ground and is drawn crisp).
export const NATURAL = new Set([B.grass, B.dirt, B.stone, B.sand, B.snow, B.gravel, B.basalt, B.bedrock, B.ironore, B.magnetite, B.lodestone, B.coal, B.copperore, B.tinore, B.clay,
  B.silverore, B.goldore, B.farmland]);   // farmland: tilled earth, smooth ground like the rest (#154)
export function fieldOf(col, h, edit) {
  if (edit !== undefined) return NATURAL.has(edit) ? 1 : -1;
  if (h <= 0) return 1;
  return Math.max(-1, Math.min(1, col.height - (h + 0.5)));
}

// ---- plot data and its commitment ---------------------------------------------------------------------------------
// A plot's data is two lists:
//   EDITS — the ground, in whole cells: [x, z, y, block] with x (u - u0) and z (v - v0) in 0..15, y the layer in
//           0..H-1, block an id (0 = the terrain there was removed). Sorted by (y, z, x), one entry per cell.
//   BOXES — what is built, at 1 cm ("what about 1 cm and people can increase the block size to whatever?", operator
//           2026-11-06): [x, z, y, w, d, h, m] in CENTIMETRES inside the plot (x, z in 0..1599, y in 0..H*100-1), a size
//           of at least 1 cm on each axis that stays inside the plot, and m the block id of its material. Pieces never
//           overlap (the world server refuses an overlapping one), so a plot's boxes are a set; canonical order is by
//           the tuple. A box is a few numbers whatever its size: a nail and a 16 m slab cost the same to store.
export const CM = 100;                        // centimetres per block (the ground's cell)
export const PLOT_CM = PLOT * CM, H_CM = H * CM;
export function canonicalEdits(edits) {
  const m = new Map();
  for (const [x, z, y, b] of edits) {
    if (!(x >= 0 && x < PLOT && z >= 0 && z < PLOT && y >= 0 && y < H && Number.isInteger(b) && b >= 0 && b < BLOCKS.length)) throw new Error("bad edit");
    m.set((y * PLOT + z) * PLOT + x, b);
  }
  return [...m.keys()].sort((a, b) => a - b).map((k) => [k % PLOT, Math.floor(k / PLOT) % PLOT, Math.floor(k / (PLOT * PLOT)), m.get(k)]);
}
// SHAPES (a roof needs slopes — "A REAL HOUSE", operator 2026-11-06): a piece may carry an 8th number, its shape — 1..4 a
// slope (a wedge) rising toward +x, -x, +z, -z across its box; absent (or 0) a box. A wedge is solid below its slope; it
// pays half its box's volume; for overlap it is its box (two wedges of a gable sit side by side).
export const SLOPE_POS_X = 1, SLOPE_NEG_X = 2, SLOPE_POS_Z = 3, SLOPE_NEG_Z = 4;
// ROTATION (#169, operator 2026-11-10: "maybe add fine rotation if needed" — the evidence: a fighter's 40° swept wing and
// an X of wings cannot be pieces square to the plot): a piece may carry three more numbers after its shape — yaw, pitch
// and roll in TENTHS OF A DEGREE (-1799..1800) — turning it about its own centre: roll about north (+z), then pitch about
// east (+x), then yaw about up (+y), all in the plot's frame. [x, z, y, w, d, h] stays the piece before it turns; the
// turned piece must lie inside the plot (its bounding box). An unturned piece keeps its 7 or 8 numbers, byte for byte.
const ROT_MAX = 1800;
/** Is [x, z, y, w, d, h, m] (or with a shape as an 8th number — 1..4 a slope, from 16 a part of land-shapes.js — and
 *  yaw, pitch, roll as 9th-11th) a piece inside the plot? */
export function boxOk(b) {
  if (!Array.isArray(b) || (b.length !== 7 && b.length !== 8 && b.length !== 11) || !b.every(Number.isInteger)) return false;
  const [x, z, y, w, d, h, m] = b;
  if (!(x >= 0 && z >= 0 && y >= 0 && w >= 1 && d >= 1 && h >= 1 && m > 0 && m < BLOCKS.length && !BLOCKS[m].liquid)) return false;
  if (b.length > 7 && !((b[7] >= 0 && b[7] <= 4) || Shapes.isPart(b[7])) || (b.length === 8 && !b[7])) return false;
  if (b.length > 7 && Shapes.isPart(b[7]) && Shapes.decode(b[7]).type === Shapes.ENGINE && m !== B.thruster) return false;   // an engine is made of thrusters, nothing else (engineCount)
  if (b.length === 11) {
    if (!b.slice(8).every((r) => r > -ROT_MAX && r <= ROT_MAX) || !(b[8] || b[9] || b[10])) return false;
    const a = boxAabb(b);
    return a[0] >= 0 && a[1] >= 0 && a[2] >= 0 && a[0] + a[3] <= PLOT_CM && a[1] + a[4] <= PLOT_CM && a[2] + a[5] <= H_CM;
  }
  return x + w <= PLOT_CM && z + d <= PLOT_CM && y + h <= H_CM;
}
export const shapeOf = (b) => (b.length > 7 ? b[7] : 0);
/** yaw, pitch, roll in tenths of a degree; [0, 0, 0] for a piece square to the plot. */
export const rotOf = (b) => (b.length > 8 ? [b[8], b[9], b[10]] : [0, 0, 0]);
export const isTurned = (b) => b.length > 8 && !!(b[8] || b[9] || b[10]);
/** One canonical spelling: a box is 7 numbers, a slope 8, a turned piece 11 (no rotation dropped, a trailing 0 too). */
export const normalBox = (b) => {
  if (b.length > 8 && !(b[8] || b[9] || b[10])) b = b.slice(0, 8);
  return b.length === 8 && !b[7] ? b.slice(0, 7) : b.slice();
};
/** Turn vector [x, z, y] (east, north, up) by rotation r (tenths of a degree): roll, then pitch, then yaw. */
export function turnVec(r, v, inverse = false) {
  const rad = (t) => (t / 10) * Math.PI / 180;
  const roll = (q, a) => [q[0] * Math.cos(a) - q[2] * Math.sin(a), q[1], q[0] * Math.sin(a) + q[2] * Math.cos(a)];
  const pitch = (q, a) => [q[0], q[1] * Math.cos(a) - q[2] * Math.sin(a), q[1] * Math.sin(a) + q[2] * Math.cos(a)];
  const yaw = (q, a) => [q[0] * Math.cos(a) - q[1] * Math.sin(a), q[0] * Math.sin(a) + q[1] * Math.cos(a), q[2]];
  if (!inverse) return yaw(pitch(roll(v, rad(r[2])), rad(r[1])), rad(r[0]));
  return roll(pitch(yaw(v, -rad(r[0])), -rad(r[1])), -rad(r[2]));
}
const centreOf = (b) => [b[0] + b[3] / 2, b[1] + b[4] / 2, b[2] + b[5] / 2];
/** The box [x, z, y, w, d, h] (whole cm, outward) a piece fills — itself, or what a turned piece reaches. */
export function boxAabb(b) {
  if (!isTurned(b)) return b.slice(0, 6);
  const r = rotOf(b), c = centreOf(b), ex = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    const e = [0, 0, 0]; e[i] = b[3 + i] / 2;
    const t = turnVec(r, e);
    for (let k = 0; k < 3; k++) ex[k] += Math.abs(t[k]);
  }
  const lo = [0, 1, 2].map((k) => Math.floor(c[k] - ex[k] + 1e-6)), hi = [0, 1, 2].map((k) => Math.ceil(c[k] + ex[k] - 1e-6));
  return [lo[0], lo[1], lo[2], hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]];
}
const aabbOverlap = (a, b) => a[0] < b[0] + b[3] && b[0] < a[0] + a[3] && a[1] < b[1] + b[4] && b[1] < a[1] + a[4] && a[2] < b[2] + b[5] && b[2] < a[2] + a[5];
/** Do two pieces overlap? Square ones as boxes (touching faces do not overlap); a turned one by the separating axis test
 *  of two oriented boxes (touching, within a hundredth of a millimetre, does not either). A slope overlaps as its box. */
export function boxesOverlap(a, b) {
  if (!isTurned(a) && !isTurned(b)) return aabbOverlap(a, b);
  if (!aabbOverlap(boxAabb(a), boxAabb(b))) return false;
  const axes = (p) => [0, 1, 2].map((i) => { const e = [0, 0, 0]; e[i] = 1; return turnVec(rotOf(p), e); });
  const A = axes(a), Bx = axes(b), ha = [a[3] / 2, a[4] / 2, a[5] / 2], hb = [b[3] / 2, b[4] / 2, b[5] / 2];
  const ca = centreOf(a), cb = centreOf(b), T = [cb[0] - ca[0], cb[1] - ca[1], cb[2] - ca[2]];
  const dot = (u, v) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  const cross = (u, v) => [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const tests = [...A, ...Bx];
  for (const u of A) for (const v of Bx) { const c = cross(u, v); if (Math.hypot(...c) > 1e-9) tests.push(c); }
  for (const L of tests) {
    const n = Math.hypot(...L), l = [L[0] / n, L[1] / n, L[2] / n];
    const ra = A.reduce((s, u, i) => s + ha[i] * Math.abs(dot(u, l)), 0), rb = Bx.reduce((s, v, i) => s + hb[i] * Math.abs(dot(v, l)), 0);
    if (Math.abs(dot(T, l)) >= ra + rb - 1e-3) return false;            // a gap, or a touch: no overlap
  }
  return true;
}
// PARTS (#175, land-shapes.js): a shape from 16 is a modelled solid filling the piece's box — a hull, a wing, an engine.
/** Is the piece a part (land-shapes.js), not a box or a slope? */
export const isPart = (b) => b.length > 7 && Shapes.isPart(b[7]);
/** Is the piece an engine: the engine part, in the thruster's material (boxOk allows it no other)? */
export const isEngine = (b) => b.length > 7 && b[6] === B.thruster && Shapes.isPart(b[7]) && Shapes.decode(b[7]).type === Shapes.ENGINE;
// the block a part's triangles of each tone (land-shapes.js MATERIAL, DARK, STEEL, GLOW) are drawn as: its own material,
// black, steel plate, a lamp. scripts/land_server.py needs none of it: a tone is paint, not matter.
export const toneBlock = (b, tone) => (tone === Shapes.DARK ? B.black : tone === Shapes.STEEL ? B.steelplate : tone === Shapes.GLOW ? B.lamp : b[6]);
/** cm³ of material in a piece (a block is 1,000,000): a box its box, a slope half of it, a part the share of its box its
 *  shape fills — a tenth of that for a hollow one (land-shapes.js SHELL) — in whole-number arithmetic, the very sum
 *  scripts/land_server.py box_vol does (the largest product, 1600 × 1600 × 25600 × 1000, is well inside a double). */
export function boxVolume(b) {
  const s = shapeOf(b), box = b[3] * b[4] * b[5];
  if (!s) return box;
  if (!Shapes.isPart(s)) return Math.floor(box / 2);
  return Math.max(1, Math.floor((box * Shapes.fill(s)) / (1000 * (Shapes.hollow(s) ? Shapes.SHELL : 1))));
}
// AN ENGINE IS THRUSTERS. The thruster item is a 1.0 × 1.0 × 1.4 m unit (land-recipes.json); an engine part of any size is
// as many of them as its volume comes to, to the nearest whole one and never fewer than one — what it costs to place,
// gives back taken down, weighs (flight.unit_mass) and pushes (flight.thrust_kn). The server: engine_count.
export const THRUSTER_CM3 = 1400000;
export const engineCount = (b) => (isEngine(b) ? Math.max(1, Math.floor((boxVolume(b) + THRUSTER_CM3 / 2) / THRUSTER_CM3)) : b[6] === B.thruster ? 1 : 0);
/** May these two pieces not share a place? Boxes and slopes may not overlap; a PART overlaps freely — with a box, with
 *  another part — because a part does not fill its box (a wing's box is mostly air) and parts are meant to be sunk into
 *  one another: that is what closes the seams. Only the very same piece twice is refused (the server does: a duplicate).
 *  boxesOverlap itself stays pure geometry: a body in the way, a fire, a craft's joints all still ask it. */
export const piecesClash = (a, b) => !isPart(a) && !isPart(b) && boxesOverlap(a, b);
/** Is the point (x, z, y) in cm inside piece b — for a slope, below its sloped face? */
export function inPiece(b, x, z, y) {
  if (isTurned(b)) {                                       // into the piece's own frame: about its centre, turned back
    const c = centreOf(b), l = turnVec(rotOf(b), [x - c[0], z - c[1], y - c[2]], true);
    x = c[0] + l[0]; z = c[1] + l[1]; y = c[2] + l[2];
  }
  if (!(x >= b[0] && x < b[0] + b[3] && z >= b[1] && z < b[1] + b[4] && y >= b[2] && y < b[2] + b[5])) return false;
  const s = shapeOf(b);
  if (!s) return true;
  if (Shapes.isPart(s)) return Shapes.inside(s, (x - b[0]) / b[3], (y - b[2]) / b[5], (z - b[1]) / b[4]);   // the part's own outline (z its depth: north before it turns)
  const f = s === 1 ? (x - b[0]) / b[3] : s === 2 ? (b[0] + b[3] - x) / b[3] : s === 3 ? (z - b[1]) / b[4] : (b[1] + b[4] - z) / b[4];
  return y - b[2] <= f * b[5];
}
export function canonicalBoxes(boxes) {
  const out = [...new Map(boxes.map((b0) => { const b = normalBox(b0); if (!boxOk(b)) throw new Error("bad box"); return [b.join(","), b]; })).values()];
  return out.sort((a, b) => {
    for (let i = 0; i < 7; i++) if (a[i] !== b[i]) return a[i] - b[i];
    if (a.length !== b.length) return a.length - b.length;
    for (let i = 7; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
    return 0;
  });
}
const enc = new TextEncoder();
/** The bytes a commitment hashes: tag, plot id (u32 BE), the 32-byte salt, the edit count (u32 BE) and each edit as
 *  x u8, z u8, y u16 BE, block u8, then the box count (u32 BE) and each box as x, z, y, w, d, h (u16 BE each), its
 *  material u8 and its shape u8 (v3: shapes; no title had been minted, so no v2 anchor exists to keep).
 *  scripts/land_server.py builds the same bytes (commitment_bytes; the server test checks the two agree). */
export function commitmentBytes(plot, salt, edits, boxes = []) {
  // the deep below a plot is the commons, not the plot's build: never committed (scripts/land_server.py agrees)
  const ce = canonicalEdits(edits.filter((e) => e[2] >= 0)), cb = canonicalBoxes(boxes);
  // v4 (#169) only for a plot with a turned piece: each piece then carries yaw, pitch, roll (i16 BE); every plot without
  // one keeps its v3 bytes, so a commitment anchored before rotation existed stays the plot's commitment
  const v4 = cb.some(isTurned), tag = enc.encode(v4 ? "nado-land-plot-v4" : "nado-land-plot-v3");
  if (!(salt instanceof Uint8Array) || salt.length !== 32) throw new Error("salt must be 32 bytes");
  const out = new Uint8Array(tag.length + 4 + 32 + 4 + ce.length * 5 + 4 + cb.length * (v4 ? 20 : 14));
  out.set(tag, 0);
  let o = tag.length;
  const u32 = (n) => { out[o++] = n >>> 24; out[o++] = (n >>> 16) & 255; out[o++] = (n >>> 8) & 255; out[o++] = n & 255; };
  const u16 = (n) => { out[o++] = n >>> 8; out[o++] = n & 255; };
  u32(plot);
  out.set(salt, o); o += 32;
  u32(ce.length);
  for (const [x, z, y, b] of ce) { out[o++] = x; out[o++] = z; u16(y); out[o++] = b; }
  u32(cb.length);
  for (const b of cb) {
    const [x, z, y, w, d, h, m] = b; u16(x); u16(z); u16(y); u16(w); u16(d); u16(h); out[o++] = m; out[o++] = shapeOf(b);
    if (v4) for (const r of rotOf(b)) u16(r & 0xffff);         // i16 two's complement, big-endian
  }
  return out;
}
/** The commitment anchored on chain (land.py anchor arg 1): SHA-256 of commitmentBytes as a 256-bit integer string. */
export async function plotCommitment(plot, salt, edits, boxes = []) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", commitmentBytes(plot, salt, edits, boxes)));
  let n = 0n;
  for (const x of d) n = (n << 8n) | BigInt(x);
  return n === 0n ? "1" : n.toString();                         // the contract refuses 0; SHA-256 is never 0 in practice
}
