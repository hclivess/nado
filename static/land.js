// land.js — Land: one permanent planet, built block by block on plots whose titles are NFTs (doc/land.md).
//
// WHAT RUNS WHERE. The planet itself is static/land-world.js (pure: the same blocks in every browser); chunks are meshed
// off the main thread by static/land-mesher.js workers; this page draws them with three.js r187's WebGPU renderer
// (static/vendor/three, WebGL2 where WebGPU is missing), moves the player and edits blocks. Titles are native assets the
// operator wallet issued (execnode/games/land.py ISSUER), read from the exec node; the land contract (CID) holds each
// plot's anchored commitment and its builder grants.
//
// WHO MAY BUILD. A block can change only inside a plot the signed-in wallet holds the title of, or was granted by its
// current holder (land.py builder_of == that holder). Every edit of a plot is kept with the plot's salt in this browser
// (and, with the world server, on the server); "Anchor" commits SHA-256(plot, salt, edits) on chain with the title shown.
//
// COORDINATES. The player lives in grid space (face, u, v, h); metres are derived only to draw. The camera sits at the
// origin and every mesh is placed at its anchor minus the camera's position, computed in doubles, so float32 never
// carries a coordinate larger than the view distance however far the planet's centre is (R0 ~83 km).
// ONE COPY OF THREE: the core is imported by its import-map NAME, exactly as the add-ons below import it, and the map
// names two shims (land-three-*.js) whose absolute imports the node stamps like three's own relative ones. The node stamps
// every "/static/…" and "./…" import with ?v=<hash> and leaves bare names alone: a path here became three.webgpu.js?v=…
// while the add-ons' "three/webgpu" stayed three.webgpu.js — two URLs, two module instances, two TSL node stacks, and
// the page drew nothing ("pitch black", 2026-11-06; THREE.TSL "Cannot read properties of null (reading 'If')").
// tests/test_the_land_page_loads_one_copy_of_three.py serves the page through the real stamper and pins this.
import * as THREE from "three/webgpu";
import * as TSL from "three/tsl";
// r187's post-processing add-ons (static/vendor/three/addons, pinned like the core); they import "three/webgpu" and
// "three/tsl", which land.html's import map points at the same vendored files
import { ao } from "three/addons/tsl/display/GTAONode.js";
import { bloom } from "three/addons/tsl/display/BloomNode.js";
import { fxaa } from "three/addons/tsl/display/FXAANode.js";
import * as Wd from "./land-world.js";
import * as Cosmos from "./land-cosmos.js";
import { walk } from "./land-walk.js";
import { NadoDapp, wireWallet, renderWallet, alertBar, notify, uiConfirm, uiPrompt, isAddress, esc, base, disp, $ } from "./nadodapp.js";

const CID = "0000000000000000000000000000000c";      // set by execnode/games/redeploy.py wire() at deploy
const ISSUER = "3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f";   // land.py ISSUER — every title's issuer
const NFT_URL = "https://nft.nadochain.com/";
const dapp = new NadoDapp({ cid: CID, app: "Land" });
// ONE SIGN-IN ("im already signed in and it tells me to sign in", operator 2026-11-06). Building needs the world server
// to know who you are, which only a signed login proves (scripts/land_server.py login); the SDK's plain wallet connect
// shares an address and no signature. So in Land the wallet button IS the signed login, and the address that login
// proves becomes the page's wallet address too (anchoring, inviting).
dapp.signIn = () => { location.href = "/land/api/login"; };
const T = (k, en, v) => window.t("land." + k, en, v);

const { CHUNK, PLOT, W, H, B, BLOCKS } = Wd;
const EYE = 1.62, HALF = 0.3, TALL = 1.8, REACH = 7, STEP = 0.65;
const GRAV = 26, JUMP = 8.4, WALK = 4.6, RUN = 7.5, FLY = 14, FLY_FAST = 60;

// ---- state ------------------------------------------------------------------------------------------------------
const P = { face: Wd.SPAWN_FACE, u: 0, v: 0, h: 0, yaw: 0, pitch: -0.15, vu: 0, vv: 0, vh: 0, fly: false, ground: false };
const edits = new Map();              // "face:u:v:h" -> block id: every known edit (mine and, with the server, everyone's)
const plotEdit = new Map();           // plot -> Map(local key "x:z:y" -> block)
const titles = new Map();             // plot -> { aid, holder } for every issued title
const mine = new Set();               // plots whose title the signed-in address holds
const builds = new Set();             // plots the world server says the signed-in address was invited to build on
// GATHERING, TOOLS, CRAFTING, TRADE (doc/land.md): "you must gather resources to make tools to make tools to collect more
// resources". The rules are static/land-recipes.json, the same file the world server judges by; the inventory is the
// server's (it arrives as "inv" messages) — the page never decides what anyone owns.
let RULES = null;
const inv = { items: {}, tools: [], stations: [] };
let invSeen = false;                  // the first "inv" after connecting is what the player HAS, not what they just got
let offers = [];
let hot = [], slot = 0;               // the hotbar: placeable item ids
let job = null;                       // the break in progress: { cell, need (s), done (s), mouse }
let mouseHeld = false;
// BUILT PIECES (land-world BOXES: [x, z, y, w, d, h, m] in cm inside their plot) — "what about 1 cm and people can
// increase the block size to whatever?" (operator, 2026-11-06). The size a player places is theirs to set (PRESETS, or
// any W x D x H in the bag) and lands on a SNAP grid they choose; the ground stays whole cells.
const PRESETS = [[100, 100, 100], [100, 100, 10], [100, 10, 100], [10, 10, 100], [200, 20, 5], [25, 25, 25], [5, 5, 5], [1, 1, 1]];
const SNAPS = [1, 5, 10, 25, 50, 100];
let piece = { w: 100, d: 100, h: 100, snap: 10 };
const plotBoxes = new Map();          // plot -> { list, idx: Map(1 m bucket -> [box]) }
let pipeline = null;                  // the post-processed render (or null: the plain render on a weak device)
let renderer, scene, camera, sun, hemi, atlasTex, matSolid, matClear, matGround, matTrees, matPieces, matGlassy, matBark, matLeaves, ghost, farMesh = null, farAt = null;
let highlight, lastT = 0, locked = false, keys = new Set(), touch = null, viewDist = 6;
const LS = "nado_land_v1";

// ---- the atlas: every block's tiles, painted from seeded noise (original art, no image files) -------------------
const TILE = 16, TCOLS = 8, TROWS = Math.ceil(Wd.ATLAS_TILES / TCOLS);
const PAINT = {
  1: ["#5f9e3a", 0.18, "grass"], 2: ["#7a5a3a", 0.12, "grassSide"], 3: ["#7a5a3a", 0.16], 4: ["#808080", 0.14, "stone"],
  5: ["#d9c98e", 0.08], 6: ["#2f6fb0", 0.06], 7: ["#f2f6f8", 0.04], 8: ["#7a5a3a", 0.12, "snowSide"], 9: ["#6b4a2b", 0.14, "bark"],
  10: ["#a07a4a", 0.1, "rings"], 11: ["#3f7f2e", 0.25, "leaves"], 12: ["#b08850", 0.08, "planks"], 13: ["#777777", 0.2, "cobble"],
  14: ["#9c4434", 0.1, "brick"], 15: ["#bfe3f0", 0.03, "glass"], 16: ["#a8442e", 0.08, "tiles"], 17: ["#e8e0d0", 0.04],
  18: ["#5a3a22", 0.08, "planks"], 19: ["#8a8a8a", 0.1, "brick"], 20: ["#8d8a85", 0.22], 21: ["#3a3a40", 0.12], 22: ["#a8d8f0", 0.05],
  23: ["#ffd98a", 0.06, "lamp"], 24: ["#c0392b", 0.06], 25: ["#e67e22", 0.06], 26: ["#f1c40f", 0.06], 27: ["#27ae60", 0.06],
  28: ["#2e6fd8", 0.06], 29: ["#8e44ad", 0.06], 30: ["#262626", 0.06], 31: ["#f4f4f4", 0.05], 32: ["#e9e6df", 0.05, "marble"],
  33: ["#2a2a2a", 0.3], 34: ["#e8e4da", 0.06, "birch"], 35: ["#24502a", 0.22, "leaves"], 36: ["#6aa83a", 0.2, "leaves"],
};
function paintAtlas() {
  const cv = document.createElement("canvas");
  cv.width = TCOLS * TILE; cv.height = TROWS * TILE;
  const g = cv.getContext("2d");
  let seed = 1234567;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  for (let t = 1; t < Wd.ATLAS_TILES; t++) {
    const [hex, jit, kind] = PAINT[t] || ["#ff00ff", 0];
    const x0 = (t % TCOLS) * TILE, y0 = Math.floor(t / TCOLS) * TILE;
    const c = new THREE.Color(hex);
    for (let y = 0; y < TILE; y++) for (let x = 0; x < TILE; x++) {
      let k = 1 + (rnd() - 0.5) * 2 * jit;
      if (kind === "planks" && y % 4 === 3) k *= 0.7;
      if (kind === "planks" && (x + (Math.floor(y / 4) % 2) * 8) % 16 === 0) k *= 0.75;
      if (kind === "brick" && (y % 4 === 3 || (x + (Math.floor(y / 4) % 2) * 4) % 8 === 0)) k = 0.55 + rnd() * 0.1;
      if (kind === "cobble" && ((x * 7 + y * 3) % 11 < 2)) k *= 0.65;
      if (kind === "tiles" && (y % 4 === 0 || (x + (Math.floor(y / 4) % 2) * 2) % 4 === 0)) k *= 0.72;
      if (kind === "rings") { const r = Math.hypot(x - 7.5, y - 7.5); k *= Math.floor(r) % 3 === 0 ? 0.8 : 1; }
      if (kind === "bark" && x % 4 === 0) k *= 0.75;
      if (kind === "birch" && (y * 5 + x * 3) % 13 < 2) k = 0.25;              // the dark marks on white bark
      if (kind === "glass" && (x === 0 || y === 0 || x === TILE - 1 || y === TILE - 1)) k = 0.75;
      if (kind === "lamp" && (x < 2 || y < 2 || x > TILE - 3 || y > TILE - 3)) k = 0.6;
      if (kind === "marble" && Math.abs(Math.sin(x * 0.7 + y * 0.35)) < 0.12) k *= 0.85;
      if (kind === "leaves" && rnd() < 0.18) k *= 0.6;
      let col = c.clone().multiplyScalar(k);
      if (kind === "grassSide" && y < 4 + (rnd() < 0.4 ? 1 : 0)) col = new THREE.Color("#5f9e3a").multiplyScalar(k);
      if (kind === "snowSide" && y < 4 + (rnd() < 0.4 ? 1 : 0)) col = new THREE.Color("#f2f6f8").multiplyScalar(k);
      const a = kind === "glass" && !(x === 0 || y === 0 || x === TILE - 1 || y === TILE - 1) ? 0.25 : t === 6 ? 0.75 : 1;
      g.fillStyle = `rgba(${Math.min(255, col.r * 255) | 0},${Math.min(255, col.g * 255) | 0},${Math.min(255, col.b * 255) | 0},${a})`;
      g.fillRect(x0 + x, y0 + y, 1, 1);
    }
  }
  return cv;
}

// ---- the planet, as the player meets it ---------------------------------------------------------------------------
const colMemo = new Map();
const colAt = (f, u, v) => {
  const k = (f * W + u) * W + v;
  let c = colMemo.get(k);
  if (!c) { if (colMemo.size > 200000) colMemo.clear(); c = Wd.column(f, u, v); colMemo.set(k, c); }
  return c;
};
const key = (f, u, v, h) => f + ":" + u + ":" + v + ":" + h;
function blockAt(f, u, v, h) {
  if (h < 0) return B.bedrock;
  if (h >= H) return B.air;
  const w = Wd.wrap(f, u, v), e = edits.get(key(w.face, w.u, w.v, h));
  return e !== undefined ? e : Wd.terrainBlock(w.face, w.u, w.v, h, colAt);
}
// THE SMOOTH GROUND, as the player touches it: land-world.fieldOf at cell centres, interpolated — the same field the mesher
// draws (static/land-mesher.js nets), so the foot lands where the surface is drawn, not on a hidden cube. What people
// build stays a crisp cell, and a log is a solid cell inside its round trunk; leaves can be walked through.
const crispB = (b) => b !== B.air && !Wd.NATURAL.has(b) && !Wd.isTree(b) && !BLOCKS[b].liquid;
function fieldCell(f, u, v, h) {
  if (h < 0) return 1;
  if (h >= H) return -1;
  const w = Wd.wrap(f, u, v);
  return Wd.fieldOf(colAt(w.face, w.u, w.v), h, edits.get(key(w.face, w.u, w.v, h)));
}
function fieldAt(f, u, v, h) {
  const x = u - 0.5, y = v - 0.5, z = h - 0.5, i = Math.floor(x), j = Math.floor(y), k = Math.floor(z), a = x - i, b = y - j, c = z - k;
  let s = 0;
  for (let n = 0; n < 8; n++) {
    const di = n & 1, dj = (n >> 1) & 1, dk = n >> 2;
    s += fieldCell(f, i + di, j + dj, k + dk) * (di ? a : 1 - a) * (dj ? b : 1 - b) * (dk ? c : 1 - c);
  }
  return s;
}
// ---- pieces, as the player touches them: a 1 m bucket index per plot, so a test looks at the few pieces near it -----
const bkey = (i, j, k) => (i * 64 + j) * 4096 + k;
function indexBoxes(list) {
  const idx = new Map();
  for (const b of list) for (let i = Math.floor(b[0] / Wd.CM); i <= Math.floor((b[0] + b[3] - 1) / Wd.CM); i++)
    for (let j = Math.floor(b[1] / Wd.CM); j <= Math.floor((b[1] + b[4] - 1) / Wd.CM); j++)
      for (let k = Math.floor(b[2] / Wd.CM); k <= Math.floor((b[2] + b[5] - 1) / Wd.CM); k++) {
        const key = bkey(i, j, k); let l = idx.get(key); if (!l) idx.set(key, l = []); l.push(b);
      }
  return idx;
}
/** The plot a grid point is in and the point in that plot's centimetres. */
function plotCm(f, u, v, h) {
  const plot = Wd.plotOf(f, Math.floor(u), Math.floor(v)), q = Wd.plotCoords(plot);
  return { plot, x: (u - q.u0) * Wd.CM, z: (v - q.v0) * Wd.CM, y: h * Wd.CM };
}
/** The piece containing grid point (u, v, h), or null. */
function boxAt(f, u, v, h) {
  const c = plotCm(f, u, v, h), rec = plotBoxes.get(c.plot);
  if (!rec) return null;
  for (const b of rec.idx.get(bkey(Math.floor(c.x / Wd.CM), Math.floor(c.z / Wd.CM), Math.floor(c.y / Wd.CM))) || [])
    if (c.x >= b[0] && c.x < b[0] + b[3] && c.z >= b[1] && c.z < b[1] + b[4] && c.y >= b[2] && c.y < b[2] + b[5]) return { plot: c.plot, b };
  return null;
}
function setPlotBoxes(plot, list) {
  const old = plotBoxes.get(plot);
  plotBoxes.set(plot, { list, idx: indexBoxes(list) });
  const ys = [...list, ...(old ? old.list : [])];
  if (ys.length) remeshPlotRange(plot, Math.min(...ys.map((b) => b[2])), Math.max(...ys.map((b) => b[2] + b[5])));
}
function solidAt(f, u, v, h) {
  if (boxAt(f, u, v, h)) return true;
  const b = blockAt(f, Math.floor(u), Math.floor(v), Math.floor(h));
  if (crispB(b)) return BLOCKS[b].solid;
  return fieldAt(f, u, v, h) > 0;
}

// ---- camera frame -----------------------------------------------------------------------------------------------
function look() {
  const fr = Wd.frameOf(P.face, P.u, P.v), cp = Math.cos(P.pitch), sy = Math.sin(P.yaw), cy = Math.cos(P.yaw);
  const fw = [0, 1, 2].map((i) => cp * (sy * fr.east[i] + cy * fr.north[i]) + Math.sin(P.pitch) * fr.up[i]);
  return { fr, fw };
}
/** World position (metres, doubles) of the eye. */
function eyePos() { return Wd.posOf(P.face, P.u, P.v, (P.eyeH === undefined ? P.h : P.eyeH) + EYE); }   // land-walk.js smooths eyeH

// ---- movement (grid space: u ~ east, v ~ north, h ~ up, ~1 m per unit) ------------------------------------------------
function collides(u, v, h) {
  for (const du of [-HALF, HALF]) for (const dv of [-HALF, HALF]) for (const dh of [0.01, 0.9, TALL - 0.01])
    if (solidAt(P.face, u + du, v + dv, h + dh)) return true;
  return false;
}
function step(dt) {
  const fwd = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0) + (touch ? touch.my : 0);
  const side = (keys.has("KeyD") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("KeyA") || keys.has("ArrowLeft") ? 1 : 0) + (touch ? touch.mx : 0);
  const fast = keys.has("ShiftLeft") || keys.has("ShiftRight");
  const sp = P.fly ? (fast ? FLY_FAST : FLY) : (fast ? RUN : WALK);
  const sy = Math.sin(P.yaw), cy = Math.cos(P.yaw);
  const wu = (sy * fwd + cy * side) * sp, wv = (cy * fwd - sy * side) * sp;
  if (P.fly) P.vh = ((keys.has("Space") || (touch && touch.up) ? 1 : 0) - (keys.has("KeyC") || keys.has("ControlLeft") || (touch && touch.down) ? 1 : 0)) * sp;
  // the body's motion, climbing and descending slopes exactly (land-walk.js: the 5 cm notches it replaced made every
  // other uphill frame "airborne" and stopped the walk — the jitter-jumping of 2026-11-06)
  walk(P, [wu, wv], keys.has("Space") || !!(touch && touch.up), dt, collides, { GRAV, JUMP, STEP });
  if (P.h < 1) { P.h = groundAt(P.face, P.u, P.v); P.vh = 0; }
  if (P.h > H + 400) P.h = H + 400;
  // leaving the face: continue on the neighbouring face, keeping the world direction the player faces
  if (P.u < 0 || P.v < 0 || P.u >= W || P.v >= W) {
    const { fw } = look(), g = Wd.gridOf(Wd.dirOf(P.face, P.u, P.v));
    P.face = g.face; P.u = g.u; P.v = g.v;
    const fr = Wd.frameOf(P.face, P.u, P.v);
    const fe = fw[0] * fr.east[0] + fw[1] * fr.east[1] + fw[2] * fr.east[2], fn = fw[0] * fr.north[0] + fw[1] * fr.north[1] + fw[2] * fr.north[2];
    P.yaw = Math.atan2(fe, fn);                       // updateChunks re-keys the neighbourhood by the new face
  }
}

// ---- aiming: a march along the look direction --------------------------------------------------------------------
// It stops at the first crisp block, log or leaves cell, or at the smooth surface; there the target is the most solid
// natural cell around the hit point (so a click always takes a real cell out, never a sliver of air), and a block is
// placed in the cell the ray came through.
function aim() {
  const { fr, fw } = look();
  const d = [fr.east, fr.north, fr.up].map((ax) => fw[0] * ax[0] + fw[1] * ax[1] + fw[2] * ax[2]);   // in grid axes
  const o = [P.u, P.v, P.h + EYE], cellOf = (p) => p.map(Math.floor), same = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  for (let t = 0; t <= REACH; t += 0.02) {
    const p = [o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t], c = cellOf(p);
    const bx = boxAt(P.face, p[0], p[1], p[2]);
    if (bx) return { box: bx, point: p, before: [p[0] - d[0] * 0.02, p[1] - d[1] * 0.02, p[2] - d[2] * 0.02], dir: d };
    if (Math.round(t / 0.02) % 3) continue;               // pieces need a 2 cm step; cells and the ground do not
    const b = blockAt(P.face, c[0], c[1], c[2]);
    let hit = null;
    if (crispB(b) || Wd.isTree(b)) hit = c;
    else if (fieldAt(P.face, p[0], p[1], p[2]) > 0) {
      // the cell the surface was hit in, when it is solid ground; only when the hit lands on the air side of a cell
      // centre does a neighbour (the most solid one) stand in — never a deeper cell under a solid one
      let best = fieldCell(P.face, c[0], c[1], c[2]) > 0 && Wd.NATURAL.has(b) ? Infinity : -Infinity;
      if (best === Infinity) hit = c;
      else for (const [x, y, z] of [[0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]]) {
        const q = [c[0] + x, c[1] + y, c[2] + z], fq = fieldCell(P.face, q[0], q[1], q[2]);
        if (fq > 0 && Wd.NATURAL.has(blockAt(P.face, q[0], q[1], q[2])) && fq > best) { best = fq; hit = q; }
      }
      if (!hit) continue;
    }
    if (!hit) continue;
    // where a block goes: the nearest cell back along the ray that is really EMPTY (air or water) — on smooth ground the
    // top layer's cell often lies above the drawn surface but still holds grass, and the world server (rightly) places
    // nothing into a cell that holds something
    // Never a cell the player stands in; failing every cell back along the ray, the first empty cell on top of the hit.
    const pu = Math.floor(P.u), pv = Math.floor(P.v), ph = Math.floor(P.h);
    const free = (q) => { const qb = blockAt(P.face, q[0], q[1], q[2]); return (qb === B.air || BLOCKS[qb].liquid) && !(q[0] === pu && q[1] === pv && (q[2] === ph || q[2] === ph + 1)); };
    let prev = null;
    for (const back of [0.3, 0.6, 1.0, 1.5, 2.0, 2.5]) {
      const pc = cellOf([p[0] - d[0] * back, p[1] - d[1] * back, p[2] - d[2] * back]);
      if (!same(pc, hit) && free(pc)) { prev = pc; break; }
    }
    for (let up = 1; !prev && up <= 3; up++) { const q = [hit[0], hit[1], hit[2] + up]; if (free(q)) prev = q; }
    return { hit, prev, point: p, dir: d };
  }
  return null;
}
/** The height a player stands at on (face, u, v): just above the smooth surface. */
function groundAt(f, u, v) {
  let h = Wd.column(f, Math.floor(u), Math.floor(v)).height + 0.05;
  while (collides(u, v, h) && h < H) h += 0.25;
  return h;
}

// ---- edits ------------------------------------------------------------------------------------------------------
// "you can build anywhere unless it is owned" (operator, 2026-11-06): unowned land is open to everyone signed in; an
// owned plot to its holder and the builders they invited. The world server applies the same rule (land_server.py).
const mayBuild = (plot) => !titles.has(plot) || mine.has(plot) || builds.has(plot);
/** Record one cell exactly as the world server holds it (an edit back to the terrain's own block stays listed there,
 *  so it stays listed here — the commitment is computed over the server's list). */
function putCell(face, u, v, h, b) {
  const plot = Wd.plotOf(face, u, v), k = key(face, u, v, h);
  const pc = Wd.plotCoords(plot), lk = (u - pc.u0) + ":" + (v - pc.v0) + ":" + h;
  let pe = plotEdit.get(plot); if (!pe) { pe = new Map(); plotEdit.set(plot, pe); }
  edits.set(k, b); pe.set(lk, b);
  remeshAround(face, u, v, h);
}
/** A cell back to the untouched planet (the wilderness regrew it). */
function dropCell(face, u, v, h) {
  const plot = Wd.plotOf(face, u, v), pc = Wd.plotCoords(plot), pe = plotEdit.get(plot);
  edits.delete(key(face, u, v, h));
  if (pe) pe.delete((u - pc.u0) + ":" + (v - pc.v0) + ":" + h);
  remeshAround(face, u, v, h);
}
/** Change one cell through the world server, which decides: breaking (b = air) gathers — anywhere in the wilderness,
 *  and on a titled plot only for its owner and invited builders — and placing spends one item, only on such a plot. The
 *  cell shows at once and is put back if the server refuses. */
function setBlock(f, u, v, h, b) {
  if (!net.online) return notify(T("offline", "The world server is out of reach — you can explore, but not gather or build."));
  const w = Wd.wrap(f, u, v), plot = Wd.plotOf(w.face, w.u, w.v);
  if (!net.me) return explainNoBuild(plot);
  if (!mayBuild(plot)) return explainNoBuild(plot);
  if (h <= 0 || h >= H) return false;
  putCell(w.face, w.u, w.v, h, b);
  net.send({ t: "set", cells: [[w.face, w.u, w.v, h, b]], req: ++net.req });
  net.pending.set(net.req, plot);
  return true;
}
function explainNoBuild(plot) {
  if (!net.me) notify(T("signInBuild2", "Sign in to gather and build."));
  else notify(T("notYours", "Plot {p} belongs to someone else. Buy a plot, or ask its owner to invite you.", { p: plotLabel(plot) }));
  return false;
}
function save() {
  try { localStorage.setItem(LS, JSON.stringify({ p: [P.face, P.u, P.v, P.h, P.yaw, P.pitch], hot, piece })); } catch (e) {}
}
/** The chosen piece size and snap, under the hotbar. */
function pieceInfo() {
  const id = hot[slot], el = $("pieceInfo");
  if (!el) return;
  el.textContent = id && RULES && !NATURAL_ITEMS.has(id) ? T("pieceInfo", "Piece {w} × {d} × {h} cm · snap {s} cm", { w: piece.w, d: piece.d, h: piece.h, s: piece.snap }) : "";
  save();
}
function load() {
  let d = null;
  try { d = JSON.parse(localStorage.getItem(LS) || "null"); } catch (e) {}
  if (d && Array.isArray(d.hot)) hot = d.hot.filter((x) => typeof x === "string").slice(0, 9);
  if (d && d.piece && [d.piece.w, d.piece.d, d.piece.h].every((x) => Number.isInteger(x) && x >= 1 && x <= Wd.PLOT_CM) && SNAPS.includes(d.piece.snap)) piece = d.piece;
  if (d && Array.isArray(d.p)) { [P.face, P.u, P.v, P.h, P.yaw] = d.p; if (typeof d.p[5] === "number") P.pitch = d.p[5]; return; }
  const sp = Wd.plotCoords(Wd.plotId(Wd.SPAWN_FACE, Wd.SPAWN_PLOT_ROW + 5, Wd.SPAWN_PLOT_COL + 5));
  P.face = sp.face; P.u = sp.u0 + 0.5; P.v = sp.v0 - 6.5;            // amid the first wave of plots
  P.h = groundAt(P.face, P.u, P.v);
}

// ---- chunks: a pool of mesher workers ---------------------------------------------------------------------------
const chunks = new Map();                      // "face:cu:cv:ch" -> { meshes: [], anchor, busy, dirty }
const workers = [], queue = [], inflight = new Map();
let reqId = 0;
function startWorkers() {
  const n = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 4) - 1));
  for (let i = 0; i < n; i++) {
    const w = new Worker("/static/land-mesher.js", { type: "module" });
    w.busy = false;
    w.onmessage = (e) => { w.busy = false; done(e.data); pump(); };
    w.onerror = () => { w.busy = false; pump(); };
    workers.push(w);
  }
}
function editsFor(face, cu, cv) {
  // the chunk's columns and their one-block border: the plots around it (border cells across a seam are rare and
  // carried by their own face's key; wrap() resolves them in the worker the same way)
  const out = [];
  const pc0 = Math.floor(cu * CHUNK / PLOT), pr0 = Math.floor(cv * CHUNK / PLOT);
  for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
    const pr = pr0 + dr, pc = pc0 + dc;
    if (pr < 0 || pc < 0 || pr >= Wd.FACE_N || pc >= Wd.FACE_N) continue;
    const plot = Wd.plotId(face, pr, pc), pe = plotEdit.get(plot);
    if (!pe) continue;
    const q = Wd.plotCoords(plot);
    for (const [lk, b] of pe) { const [x, z, y] = lk.split(":").map(Number); out.push([key(face, q.u0 + x, q.v0 + z, y), b]); }
  }
  return out;
}
function request(k) {
  const c = chunks.get(k);
  if (!c || c.busy) { if (c) c.dirty = true; return; }
  c.busy = true; c.dirty = false;
  const [face, cu, cv, ch] = k.split(":").map(Number);
  const pb = plotBoxes.get(Wd.plotId(face, cv, cu));        // a chunk column IS a plot (CHUNK == PLOT)
  const dist = Math.max(Math.abs(cu - Math.floor(P.u / CHUNK)), Math.abs(cv - Math.floor(P.v / CHUNK)));
  c.lod = dist <= 2 ? (touch ? 1 : 0) : dist <= 3 ? 1 : 2;        // 0: grass too (not on a phone); 2: small pieces skipped
  queue.push({ id: ++reqId, k, face, cu, cv, ch, edits: editsFor(face, cu, cv), boxes: pb ? pb.list : null, lod: c.lod });
  pump();
}
function pump() {
  for (const w of workers) {
    if (w.busy || !queue.length) continue;
    // nearest first: the player sees the ground under them before the far hills
    let bi = 0, bd = Infinity;
    const pcu = Math.floor(P.u / CHUNK), pcv = Math.floor(P.v / CHUNK);
    for (let i = 0; i < queue.length; i++) { const q = queue[i], d = Math.abs(q.cu - pcu) + Math.abs(q.cv - pcv) + (q.face === P.face ? 0 : 3); if (d < bd) { bd = d; bi = i; } }
    const m = queue.splice(bi, 1)[0];
    inflight.set(m.id, m.k);
    w.busy = true;
    w.postMessage(m);
  }
}
function geom(part) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(part.pos, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(part.nor, 3));
  if (part.uv) g.setAttribute("uv", new THREE.BufferAttribute(part.uv, 2));
  g.setAttribute("color", new THREE.BufferAttribute(part.col, 3));
  if (part.tile) g.setAttribute("tile", new THREE.BufferAttribute(part.tile, 1));
  if (part.uvw) g.setAttribute("uvw", new THREE.BufferAttribute(part.uvw, 3));
  if (part.gn) g.setAttribute("gn", new THREE.BufferAttribute(part.gn, 3));
  if (part.w1) g.setAttribute("w1", new THREE.BufferAttribute(part.w1, 4));
  if (part.w2) g.setAttribute("w2", new THREE.BufferAttribute(part.w2, 2));
  if (part.wind) g.setAttribute("wind", new THREE.BufferAttribute(part.wind, 4));
  g.setIndex(new THREE.BufferAttribute(part.idx, 1));
  g.computeBoundingSphere();
  return g;
}
function done(m) {
  const k = inflight.get(m.id); inflight.delete(m.id);
  const c = chunks.get(k);
  if (!c) return;
  c.busy = false;
  for (const me of c.meshes) { scene.remove(me); me.geometry.dispose(); }
  c.meshes = [];
  if (!m.empty && !m.error) {
    c.anchor = m.anchor;
    if (m.smooth) c.meshes.push(new THREE.Mesh(geom(m.smooth), matGround));
    if (m.trees) c.meshes.push(new THREE.Mesh(geom(m.trees), matTrees));
    if (m.bark) c.meshes.push(new THREE.Mesh(geom(m.bark), matBark));
    if (m.foliage) c.meshes.push(new THREE.Mesh(geom(m.foliage), matLeaves));
    if (m.stones) c.meshes.push(new THREE.Mesh(geom(m.stones), matGround));
    if (m.pieces) c.meshes.push(new THREE.Mesh(geom(m.pieces), matPieces));
    if (m.glassy) { const me = new THREE.Mesh(geom(m.glassy), matGlassy); me.renderOrder = 1; c.meshes.push(me); }
    if (m.grass) c.meshes.push(...grassMeshes(m.grass));
    if (m.solid) c.meshes.push(new THREE.Mesh(geom(m.solid), matSolid));
    if (m.clear) { const me = new THREE.Mesh(geom(m.clear), matClear); me.renderOrder = 1; c.meshes.push(me); }
    for (const me of c.meshes) { me.castShadow = me.material !== matClear && !me.isInstancedMesh; me.receiveShadow = true; scene.add(me); }
  }
  if (c.dirty) request(k);
}
/** Re-mesh the chunks of a plot that a range of piece heights (cm) touches, creating any the view had not loaded. */
function remeshPlotRange(plot, yLo, yHi) {
  const q = Wd.plotCoords(plot);
  for (let ch = Math.max(0, Math.floor(yLo / (CHUNK * Wd.CM))); ch <= Math.min(H / CHUNK - 1, Math.floor((yHi - 1) / (CHUNK * Wd.CM))); ch++) {
    const k = q.face + ":" + q.pcol + ":" + q.prow + ":" + ch;
    if (!chunks.has(k)) chunks.set(k, { meshes: [], anchor: null, busy: false, dirty: false });
    request(k);
  }
}
function remeshAround(face, u, v, h) {
  const cu = Math.floor(u / CHUNK), cv = Math.floor(v / CHUNK), ch = Math.floor(h / CHUNK);
  const lu = u % CHUNK, lv = v % CHUNK, lh = h % CHUNK;
  const set = new Set([[cu, cv, ch]].map(String));
  if (lu === 0) set.add(String([cu - 1, cv, ch])); if (lu === CHUNK - 1) set.add(String([cu + 1, cv, ch]));
  if (lv === 0) set.add(String([cu, cv - 1, ch])); if (lv === CHUNK - 1) set.add(String([cu, cv + 1, ch]));
  if (lh === 0) set.add(String([cu, cv, ch - 1])); if (lh === CHUNK - 1) set.add(String([cu, cv, ch + 1]));
  for (const s of set) {
    const [a, b2, c] = s.split(",").map(Number), k = face + ":" + a + ":" + b2 + ":" + c;
    if (!chunks.has(k)) chunks.set(k, { meshes: [], anchor: null, busy: false, dirty: false });
    request(k);
  }
}
function updateChunks() {
  const pcu = Math.floor(P.u / CHUNK), pcv = Math.floor(P.v / CHUNK), want = new Set();
  for (let dx = -viewDist; dx <= viewDist; dx++) for (let dy = -viewDist; dy <= viewDist; dy++) {
    if (dx * dx + dy * dy > viewDist * viewDist + 1) continue;
    let face = P.face, cu = pcu + dx, cv = pcv + dy;
    if (cu < 0 || cv < 0 || cu >= W / CHUNK || cv >= W / CHUNK) {
      const w = Wd.wrap(face, cu * CHUNK + 8, cv * CHUNK + 8); face = w.face; cu = Math.floor(w.u / CHUNK); cv = Math.floor(w.v / CHUNK);
    }
    const top = colAt(face, cu * CHUNK + 8, cv * CHUNK + 8).top;
    let lo = Math.max(0, Math.floor((Math.min(top, Wd.SEA) - 10) / CHUNK)), hi = Math.min(H / CHUNK - 1, Math.floor((top + 14) / CHUNK));
    if (Math.abs(dx) <= 2 && Math.abs(dy) <= 2) { lo = Math.min(lo, Math.max(0, Math.floor(P.h / CHUNK) - 1)); hi = Math.max(hi, Math.min(H / CHUNK - 1, Math.floor(P.h / CHUNK) + 1)); }
    const pb = plotBoxes.get(Wd.plotId(face, cv, cu));
    if (pb && pb.list.length) for (const b of pb.list) { lo = Math.min(lo, Math.floor(b[2] / (CHUNK * Wd.CM))); hi = Math.max(hi, Math.min(H / CHUNK - 1, Math.floor((b[2] + b[5] - 1) / (CHUNK * Wd.CM)))); }
    const dd = Math.max(Math.abs(dx), Math.abs(dy)), lodNow = dd <= 2 ? (touch ? 1 : 0) : dd <= 3 ? 1 : 2;
    for (let ch = lo; ch <= hi; ch++) {
      const k = face + ":" + cu + ":" + cv + ":" + ch, c = chunks.get(k);
      want.add(k);
      if (c && c.lod !== undefined && c.lod !== lodNow && (pb || c.lod === 0 || lodNow === 0)) request(k);   // grass and small pieces follow the player
    }
  }
  for (const k of want) if (!chunks.has(k)) { chunks.set(k, { meshes: [], anchor: null, busy: false, dirty: false }); request(k); }
  for (const [k, c] of chunks) if (!want.has(k) && !c.busy) {
    for (const me of c.meshes) { scene.remove(me); me.geometry.dispose(); }
    chunks.delete(k);
  }
  for (let i = queue.length - 1; i >= 0; i--) if (!want.has(queue[i].k)) { const c = chunks.get(queue[i].k); if (c) c.busy = false; queue.splice(i, 1); }
}

// ---- the far land: a coarse ring of the planet beyond the chunks, out to the horizon -------------------------------
function buildFar() {
  const N = 72, STEP = 48, pos = [], col = [], idx = [];
  const fu = Math.round(P.u / STEP) * STEP, fv = Math.round(P.v / STEP) * STEP, face = P.face;
  const anchor = Wd.posOf(face, fu, fv, 0);
  const tint = (c) => c.top <= Wd.SEA ? [0.17, 0.4, 0.66] : c.biome === "snow" ? [0.93, 0.95, 0.97] : c.biome === "beach" ? [0.84, 0.78, 0.55] : c.biome === "rock" ? [0.5, 0.5, 0.52] : [0.36, 0.58, 0.24];
  for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
    const u = fu + (i - N / 2) * STEP, v = fv + (j - N / 2) * STEP;
    const w = Wd.wrap(face, Math.round(u), Math.round(v)), c = Wd.column(w.face, w.u, w.v);
    const near = Math.abs(i - N / 2) * STEP < viewDist * CHUNK && Math.abs(j - N / 2) * STEP < viewDist * CHUNK;
    const h = Math.max(c.height, Wd.SEA + 0.88) - (near ? 6 : 0);       // tucked under the chunks it overlaps
    const p = Wd.posOf(face, u, v, h);
    pos.push(p[0] - anchor[0], p[1] - anchor[1], p[2] - anchor[2]);
    col.push(...tint(c));
  }
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) { const a = j * (N + 1) + i; idx.push(a, a + 1, a + N + 2, a, a + N + 2, a + N + 1); }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx); g.computeVertexNormals();
  if (farMesh) { scene.remove(farMesh); farMesh.geometry.dispose(); }
  farMesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 1, metalness: 0 }));
  farMesh.receiveShadow = true;
  farMesh.userData.anchor = anchor;
  scene.add(farMesh);
  farAt = { face, u: fu, v: fv };
}

// ---- titles: who holds which plot (the exec node's asset table) -----------------------------------------------------
async function getJSON(path) { const r = await fetch(base() + path, { cache: "no-store" }); return r.json(); }
async function refreshTitles() {
  try {
    const r = await getJSON("/exec/assets?issuer=" + ISSUER);
    for (const a of r.assets || []) {
      const tt = Wd.titleOf(a.seed);
      if (!tt || tt.planet !== Wd.PLANET) continue;      // another planet's title, or another asset of the issuer
      const plot = tt.plot;
      if (!titles.has(plot)) titles.set(plot, { aid: a.id, holder: null, asked: false });
      else titles.get(plot).asked = false;              // a title can change hands: ask again on the next look
    }
    mine.clear();
    const me = net.me || dapp.me;
    if (me) {
      const h = await getJSON("/exec/assets?holder=" + encodeURIComponent(me));
      for (const a of h.assets || []) {
        if (a.issuer !== ISSUER) continue;
        const tt = Wd.titleOf(a.seed);
        if (tt && tt.planet === Wd.PLANET) { mine.add(tt.plot); const t = titles.get(tt.plot); if (t) t.holder = me; }
      }
    }
  } catch (e) {}
  hud();
}
async function holderOf(plot) {
  const t = titles.get(plot);
  if (!t) return null;
  try {
    const r = await getJSON("/exec/asset?id=" + t.aid);
    const hs = r.holders || {};                        // /exec/asset: { asset, holders: { address: balance }, cursor }
    t.holder = Object.keys(hs).find((a) => Number(hs[a]) > 0) || null;
  } catch (e) {}
  return t.holder;
}

// ---- anchoring a plot's build on chain ------------------------------------------------------------------------------
async function anchor(plot) {
  const t = titles.get(plot);
  if (!t || !mine.has(plot)) return explainNoBuild(plot);
  if (!net.online) return notify(T("offline", "The world server is out of reach — you can explore, but not gather or build."));
  // the world server holds the plot's list and salt; recompute its commitment here before the wallet signs it
  const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin" })).json();
  const list = r.edits || [];
  const commit = r.salt ? await Wd.plotCommitment(plot, Uint8Array.from(r.salt.match(/../g).map((x) => parseInt(x, 16))), list) : null;
  if (!commit || commit !== r.commitment) return alertBar(T("anchorMismatch", "The world server's copy of this plot does not match its fingerprint — not anchoring. Reload and try again."));
  if (!await uiConfirm({ title: T("anchorTitle", "Anchor plot {p} on chain?", { p: plotLabel(plot) }),
    body: T("anchorBody", "The chain records a fingerprint of this plot's build — not the build itself. Your title is shown to the land contract and comes straight back."),
    rows: [{ k: T("edits", "Changed blocks"), v: String(list.length) }, { k: T("fingerprint", "Fingerprint"), v: commit.slice(0, 18) + "…" }],
    confirmText: T("anchorGo", "Anchor") })) return;
  dapp.call("anchor", [plot, BigInt(commit)], 1n, T("anchoring", "Anchoring plot {p}…", { p: plotLabel(plot) }), { phase: "anchor", plot }, { asset: t.aid });
}

// ---- inviting a builder: a friend, or an AI agent with its own key (scripts/land_agent.py newkey prints its address) ----
async function invite(plot) {
  const t = titles.get(plot);
  if (!t || !mine.has(plot)) return explainNoBuild(plot);
  const addr = await uiPrompt({ title: T("inviteTitle", "Invite a builder to plot {p}", { p: plotLabel(plot) }),
    body: T("inviteBody", "Paste the address of a friend or of your AI agent. They can build here while you hold this plot; selling it ends the invitation."),
    placeholder: T("inviteAddr", "NADO address"), confirmText: T("inviteGo", "Invite") });
  const a = String(addr || "").trim();
  if (!a) return;
  if (!isAddress(a) || a === dapp.me) return alertBar(T("inviteBad", "That is not someone else's NADO address."));
  dapp.call("allow", [plot, a], 1n, T("inviting", "Inviting a builder to plot {p}…", { p: plotLabel(plot) }), { phase: "allow", plot }, { asset: t.aid });
}

// ---- the live world (scripts/land_server.py, behind /land/ on land.nadochain.com) --------------------------------------
// Without it (the page served elsewhere, or the server down) the planet can still be explored, not changed.
const net = { ws: null, online: false, me: null, req: 0, pending: new Map(), lastWatch: "", tries: 0, send(m) { try { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(m)); } catch (e) {} } };
const others = new Map();             // player id -> { mesh, p: [face, u, v, h, yaw], who }
function connect() {
  let ws;
  try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/land/ws"); } catch (e) { return; }
  net.ws = ws;
  ws.onmessage = (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.t === "hello") {
      const was = net.me;
      net.online = true; net.tries = 0; net.me = m.you || null; net.lastWatch = "";
      invSeen = false;                                       // a (re)connect re-sends the whole bag: not a pickup
      // the server is the record now: drop the plots this browser cached, the server sends each watched one back
      for (const [plot, pe] of plotEdit) { const q = Wd.plotCoords(plot); for (const lk of pe.keys()) { const [x, z, y] = lk.split(":").map(Number); edits.delete(key(q.face, q.u0 + x, q.v0 + z, y)); } }
      plotEdit.clear();
      // the world server's answer decides who this page is signed in as: an address left over from a plain wallet connect
      // (no signature) would show "connected" while every build is refused — the operator's "already signed in"
      if (net.me !== dapp.me) {
        dapp.me = net.me;
        try { if (net.me) localStorage.setItem(dapp.LS_ME, net.me); else localStorage.removeItem(dapp.LS_ME); } catch (e) {}
        renderWallet(dapp);
      }
      if (!net.me) { inv.items = {}; inv.tools = []; inv.stations = []; hotbar(); }
      if (net.me !== was) refreshTitles();
      hud();
    } else if (m.t === "plot") {
      applyPlot(m.plot, m.edits || []);
      if ((m.boxes || []).length || plotBoxes.has(m.plot)) setPlotBoxes(m.plot, m.boxes || []);
    } else if (m.t === "boxes") {
      const cur = plotBoxes.get(m.plot), rm = new Set((m.remove || []).map((b) => b.join(",")));
      // idempotent: the placer's own piece is already shown (optimistically) when the server's echo arrives
      const kept = (cur ? cur.list : []).filter((b) => !rm.has(b.join(","))), have = new Set(kept.map((b) => b.join(",")));
      const list = kept.concat((m.add || []).filter((b) => !have.has(b.join(","))));
      setPlotBoxes(m.plot, list);                       // re-meshes the old and new pieces' heights alike
    } else if (m.t === "boxes_ok") {
      if (m.refused && m.refused.length) { notify(String(m.refused[0][1])); if (m.plot !== undefined) resync(m.plot); }
    } else if (m.t === "edit") {
      for (const [f, u, v, h, b] of m.cells || []) putCell(f, u, v, h, b);
    } else if (m.t === "revert") {
      for (const [f, u, v, h] of m.cells || []) dropCell(f, u, v, h);
    } else if (m.t === "inv") {
      if (invSeen) pickup(inv.items, m.items || {}, inv.tools, m.tools || [], inv.stations, m.stations || []);
      invSeen = true;
      inv.items = m.items || {}; inv.tools = m.tools || []; inv.stations = m.stations || [];
      fillHot(); hotbar(); if (bagOpen()) renderBag();
    } else if (m.t === "offers") {
      offers = m.offers || []; if (bagOpen()) renderBag();
    } else if (m.t === "done") {
      if (m.error) notify(String(m.error));
    } else if (m.t === "set_ok") {
      const plot = net.pending.get(m.req); net.pending.delete(m.req);
      if (m.refused && m.refused.length) {
        notify(String(m.refused[0][1] || T("refused", "The world server refused that change.")));
        if (plot !== undefined) resync(plot);          // put back what the server actually holds
      }
    } else if (m.t === "players") {
      const seen = new Set();
      for (const o of m.list || []) { seen.add(o.id); let r = others.get(o.id); if (!r) { r = { mesh: avatar(o.who || o.id), who: o.who }; scene.add(r.mesh); others.set(o.id, r); } r.p = o.p; }
      for (const [id, r] of others) if (!seen.has(id)) { scene.remove(r.mesh); others.delete(id); }
    }
  };
  ws.onclose = () => {
    const was = net.online;
    net.online = false; net.ws = null;
    for (const r of others.values()) scene.remove(r.mesh);
    others.clear();
    if (was) hud();
    setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(5, net.tries++)));   // back off; a page without a server stays local
  };
}
/** Replace a plot's cells with the server's list (a pushed "plot", or a resync after a refused change). */
function applyPlot(plot, list) {
  const q = Wd.plotCoords(plot), old = plotEdit.get(plot);
  if (old) for (const lk of old.keys()) { const [x, z, y] = lk.split(":").map(Number); edits.delete(key(q.face, q.u0 + x, q.v0 + z, y)); }
  plotEdit.delete(plot);
  for (const [x, z, y, b] of list) putCell(q.face, q.u0 + x, q.v0 + z, y, b);
  if (old) for (let ch = 0; ch < H / CHUNK; ch++) { const k = q.face + ":" + q.u0 / CHUNK + ":" + q.v0 / CHUNK + ":" + ch; if (chunks.has(k)) request(k); }
}
async function resync(plot) {
  try { const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin" })).json(); applyPlot(plot, r.edits || []); setPlotBoxes(plot, r.boxes || []); } catch (e) {}
}
function avatar(seed) {
  let h = 0; for (const ch of String(seed)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const g = new THREE.Group(), col = new THREE.Color().setHSL((h % 360) / 360, 0.55, 0.5);
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.6, 1.2, 0.35), new THREE.MeshLambertMaterial({ color: col }));
  body.position.y = 0.6;
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.5), new THREE.MeshLambertMaterial({ color: 0xe9c9a8 }));
  head.position.y = 1.45;
  g.add(body, head);
  return g;
}
function netTick() {
  if (!net.online) return;
  // watch the plots in view (a chunk column is a plot), and say where we stand
  const pcu = Math.floor(P.u / CHUNK), pcv = Math.floor(P.v / CHUNK), ids = [];
  for (let dx = -viewDist; dx <= viewDist; dx++) for (let dy = -viewDist; dy <= viewDist; dy++) {
    const cu = pcu + dx, cv = pcv + dy;
    if (cu >= 0 && cv >= 0 && cu < Wd.FACE_N && cv < Wd.FACE_N) ids.push(Wd.plotId(P.face, cv, cu));
  }
  const sig = ids.join(",");
  if (sig !== net.lastWatch) { net.lastWatch = sig; net.send({ t: "watch", plots: ids }); }
  net.send({ t: "pos", p: [P.face, P.u, P.v, P.h, P.yaw] });
}
async function builderCheck(plot) {
  if (!net.online || !net.me || mine.has(plot) || builds.has(plot) || !titles.has(plot)) return;
  try { const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin" })).json(); if (r.may_build) { builds.add(plot); hud(); } } catch (e) {}
}

// ---- HUD -------------------------------------------------------------------------------------------------------
const plotLabel = (plot) => { const q = Wd.plotCoords(plot); return `${q.face}·${q.prow}·${q.pcol}`; };
function hud() {
  const w = Wd.wrap(P.face, Math.floor(P.u), Math.floor(P.v)), plot = Wd.plotOf(w.face, w.u, w.v), t = titles.get(plot);
  const changed = (plotEdit.get(plot) || new Map()).size;
  $("hudPos").textContent = T("where", "Plot {p} · height {h} m", { p: plotLabel(plot), h: Math.round(P.h - Wd.SEA) })
    + (changed ? " · " + T("changed", "{n} {n|one:changed block|other:changed blocks}", { n: changed }) : "")
    + ((plotBoxes.get(plot) || { list: [] }).list.length ? " · " + T("pieces", "{n} {n|one:piece|other:pieces}", { n: plotBoxes.get(plot).list.length }) : "");
  const st = $("hudPlot");
  // the owner is looked up once the plot's title is KNOWN (titles load after the first frames), once per refresh
  if (t && !mine.has(plot) && !t.asked) { t.asked = true; holderOf(plot).then(hud); }
  let html;
  if (t && net.online && net.me && !t.checked) { t.checked = true; builderCheck(plot); }
  const signIn = net.online && !net.me ? ` <a class="btn" href="/land/api/login">${esc(T("signInBuild", "Sign in to build"))}</a>` : "";
  if (!t) html = `<span class="pill">${esc(T("wild", "Wilderness"))}</span> <span class="dim">${esc(T("wildOpen", "Unowned: anyone may gather and build here. Own a plot to protect what you build."))}</span>${signIn}`;
  else if (builds.has(plot) && !mine.has(plot)) html = `<span class="pill ok">${esc(T("invited", "You may build here"))}</span> <span class="dim">${esc(t.holder ? T("owned", "Owned by {o}", { o: disp(t.holder) }) : "")}</span>`;
  else if (mine.has(plot)) html = `<span class="pill ok">${esc(T("yours", "Your plot"))}</span> <button id="btnAnchor" class="ghost">${esc(T("anchorBtn", "Anchor build"))}</button> <button id="btnInvite" class="ghost">${esc(T("inviteBtn", "Invite a builder"))}</button>`;
  else html = `<span class="pill">${esc(t.holder ? T("owned", "Owned by {o}", { o: disp(t.holder) }) : T("titled", "Titled"))}</span> <a class="btn" target="_blank" rel="noopener" href="${NFT_URL}#token/${esc(t.aid)}">${esc(T("market", "View on the market"))}</a>${signIn}`;
  if (st.dataset.html !== html) {
    st.innerHTML = html; st.dataset.html = html;
    const b = $("btnAnchor"); if (b) b.onclick = () => anchor(plot);
    const iv = $("btnInvite"); if (iv) iv.onclick = () => invite(plot);
  }
}
// ---- names: every item, tool and station through i18n (keys land.i.<id>, land.t.<id>, land.s.<id>) ---------------------
const nameOf = (id) => RULES.items[id] ? T("i." + id, RULES.items[id].name) : RULES.tools[id] ? T("t." + id, RULES.tools[id].name)
  : RULES.stations[id] ? T("s." + id, RULES.stations[id].name) : id;
const placeable = (id) => RULES && RULES.items[id] && RULES.items[id].places;
/** Show what changed in the inventory beside the crosshair, a line per item ("Stone +1", a new tool by name), fading out.
 *  Gathering's yield used to land in the bag unannounced — fiber, stone and sticks place nothing, so they are not on the
 *  hotbar, and the operator dug grass for minutes believing it gave nothing (2026-11-06). */
function pickup(was, now, wasTools, tools, wasSt, st) {
  const lines = [];
  for (const id of Object.keys(now)) { const d = (now[id] || 0) - (was[id] || 0); if (d > 0) lines.push(`${nameOf(id)} +${d}`); }
  for (const t of tools.concat(st)) if (!wasTools.includes(t) && !wasSt.includes(t)) lines.push(nameOf(t));
  const box = $("pickup");
  for (const text of lines.slice(0, 4)) {
    const el = document.createElement("div");
    el.textContent = text;
    box.appendChild(el);
    setTimeout(() => el.classList.add("go"), 1400);
    setTimeout(() => el.remove(), 2100);
  }
}
/** Keep the hotbar on what the player can place: what they chose first, then anything placeable they hold. */
function fillHot() {
  if (!RULES) return;
  hot = hot.filter((id) => placeable(id));
  for (const id of Object.keys(inv.items)) if (placeable(id) && inv.items[id] > 0 && !hot.includes(id) && hot.length < 9) hot.push(id);
  if (slot >= Math.max(1, hot.length)) slot = 0;
}
function tileIcon(cv, id, px) {
  const g = cv.getContext("2d"), tile = BLOCKS[RULES.items[id].places].tex[1];
  g.imageSmoothingEnabled = false;
  g.drawImage(atlasTex.image, (tile % TCOLS) * TILE, Math.floor(tile / TCOLS) * TILE, TILE, TILE, 0, 0, px, px);
}
function hotbar() {
  const bar = $("hotbar");
  if (!RULES || !hot.length) {
    bar.innerHTML = `<div class="hs empty">${esc(net.me ? T("emptyHands", "Empty hands — gather something") : T("signInGather", "Sign in to gather"))}</div>`;
    $("hotName").textContent = "";
    return;
  }
  bar.innerHTML = hot.map((id, i) => `<div class="hs${i === slot ? " on" : ""}${(inv.items[id] || 0) ? "" : " none"}" data-i="${i}" title="${esc(nameOf(id))}"><canvas width="32" height="32"></canvas><span>${i + 1}</span><b>${inv.items[id] || 0}</b></div>`).join("");
  bar.querySelectorAll(".hs").forEach((el) => {
    const i = Number(el.dataset.i);
    tileIcon(el.querySelector("canvas"), hot[i], 32);
    el.onclick = (e) => { e.stopPropagation(); slot = i; hotbar(); };
  });
  $("hotName").textContent = nameOf(hot[slot]);
  pieceInfo();
}

// ---- the bag: what you have, what you can make, and trade ---------------------------------------------------------
const bagOpen = () => !$("palette").classList.contains("hidden");
function palette(open) {
  $("palette").classList.toggle("hidden", !open);
  if (!open) return;
  if (document.pointerLockElement) document.exitPointerLock();
  renderBag();
}
const bagText = (bag) => Object.entries(bag).map(([id, n]) => `${n} ${esc(nameOf(id))}`).join(", ");
function canMake(r) {
  return (r.with || []).every((w) => inv.tools.includes(w) || inv.stations.includes(w))
    && r.uses.every(([id, n]) => (inv.items[id] || 0) >= n);
}
function renderBag() {
  if (!RULES) return;
  if (!net.me) { $("palGrid").innerHTML = `<p class="dim">${esc(T("bagSignIn", "Sign in to gather, make things and trade."))}</p>`; return; }
  const items = Object.entries(inv.items).filter(([, n]) => n > 0);
  const opts = Object.keys(RULES.items).map((id) => `<option value="${id}">${esc(nameOf(id))}</option>`).join("");
  $("palGrid").innerHTML = `
    <h3>${esc(T("have", "You have"))}</h3>
    <div class="chips">${items.length ? items.map(([id, n]) => `<button class="chip${placeable(id) ? " pl" : ""}" data-pick="${id}">${n} × ${esc(nameOf(id))}</button>`).join("") : `<span class="dim">${esc(T("nothingYet", "Nothing yet — pick up the stones and sticks lying on the ground, and pull grass and leaves by hand."))}</span>`}
      ${inv.tools.map((t) => `<span class="chip tool">${esc(nameOf(t))}</span>`).join("")}${inv.stations.map((t) => `<span class="chip tool">${esc(nameOf(t))}</span>`).join("")}</div>
    <div class="dim">${esc(T("bagHint", "Click a block to put it on your hotbar. Tools work as soon as you have them."))}</div>
    <h3>${esc(T("pieceSize", "Piece size"))}</h3>
    <div class="tradeform">${PRESETS.map((x, i) => `<button class="chip pl" data-preset="${i}">${x.join("×")}</button>`).join("")}</div>
    <div class="tradeform"><span>W</span><input id="pzW" type="number" min="1" max="1600" value="${piece.w}"><span>D</span><input id="pzD" type="number" min="1" max="1600" value="${piece.d}">
      <span>H</span><input id="pzH" type="number" min="1" max="25600" value="${piece.h}"><span>cm · ${esc(T("snap", "snap"))}</span>
      <select id="pzS">${SNAPS.map((x) => `<option value="${x}"${x === piece.snap ? " selected" : ""}>${x} cm</option>`).join("")}</select></div>
    <h3>${esc(T("make", "Make"))}</h3>
    <div class="recipes">${RULES.recipes.map((r) => {
      const out = r.makes.map(([id, n]) => (RULES.items[id] ? n + " " : "") + nameOf(id)).join(", ");
      const need = r.uses.map(([id, n]) => `${n} ${nameOf(id)}`).join(" + ") + ((r.with || []).length ? " · " + T("with", "with {w}", { w: r.with.map(nameOf).join(", ") }) : "");
      const own = r.makes.every(([id]) => inv.tools.includes(id) || inv.stations.includes(id));
      return `<div class="rcp${canMake(r) && !own ? "" : " off"}"><div><b>${esc(out)}</b><div class="dim">${esc(need)}</div></div>
        <button class="ghost" data-make="${r.id}" ${canMake(r) && !own ? "" : "disabled"}>${esc(own ? T("haveIt", "You have it") : T("makeGo", "Make"))}</button></div>`;
    }).join("")}</div>
    <h3>${esc(T("trade", "Trade"))}</h3>
    <div class="offers">${offers.length ? offers.map((o) => `<div class="rcp"><div>${esc(T("offerLine", "{g} for {w}", { g: bagText(o.give), w: bagText(o.want) }))}<div class="dim">${esc(o.by === net.me ? T("yourOffer", "Your offer") : disp(o.by))}</div></div>
        ${o.by === net.me ? `<button class="ghost" data-cancel="${o.id}">${esc(T("cancelOffer", "Withdraw"))}</button>` : `<button class="ghost" data-accept="${o.id}" ${Object.entries(o.want).every(([id, n]) => (inv.items[id] || 0) >= n) ? "" : "disabled"}>${esc(T("acceptOffer", "Trade"))}</button>`}</div>`).join("") : `<span class="dim">${esc(T("noOffers", "No offers yet."))}</span>`}</div>
    <div class="tradeform">
      <span>${esc(T("offerGive", "Give"))}</span><input id="ofGN" type="number" min="1" value="1"><select id="ofG">${opts}</select>
      <span>${esc(T("offerWant", "for"))}</span><input id="ofWN" type="number" min="1" value="1"><select id="ofW">${opts}</select>
      <button class="ghost" id="ofPost">${esc(T("offerPost", "Post offer"))}</button>
    </div>
    <div class="tradeform">
      <span>${esc(T("giveTo", "Give"))}</span><input id="gvN" type="number" min="1" value="1"><select id="gvI">${opts}</select>
      <input id="gvTo" placeholder="${esc(T("inviteAddr", "NADO address"))}"><button class="ghost" id="gvGo">${esc(T("giveGo", "Give"))}</button>
    </div>`;
  const g = $("palGrid"), req = (m) => net.send(Object.assign({ req: ++net.req }, m));
  g.querySelectorAll("[data-make]").forEach((b) => { b.onclick = () => req({ t: "craft", recipe: b.dataset.make }); });
  g.querySelectorAll("[data-pick]").forEach((b) => { b.onclick = () => { const id = b.dataset.pick; if (!placeable(id)) return; if (!hot.includes(id)) { if (hot.length < 9) hot.push(id); else hot[slot] = id; } slot = hot.indexOf(id); save(); hotbar(); }; });
  g.querySelectorAll("[data-accept]").forEach((b) => { b.onclick = () => req({ t: "accept", id: b.dataset.accept }); });
  g.querySelectorAll("[data-cancel]").forEach((b) => { b.onclick = () => req({ t: "cancel_offer", id: b.dataset.cancel }); });
  g.querySelectorAll("[data-preset]").forEach((b) => { b.onclick = () => { [piece.w, piece.d, piece.h] = PRESETS[Number(b.dataset.preset)]; pieceInfo(); renderBag(); }; });
  const size = () => {
    const v = (id, max) => Math.max(1, Math.min(max, Math.round(Number($(id).value) || 1)));
    piece = { w: v("pzW", Wd.PLOT_CM), d: v("pzD", Wd.PLOT_CM), h: v("pzH", Wd.H_CM), snap: Number($("pzS").value) };
    pieceInfo();
  };
  for (const id of ["pzW", "pzD", "pzH", "pzS"]) $(id).onchange = size;
  $("ofPost").onclick = () => req({ t: "offer", give: { [$("ofG").value]: Number($("ofGN").value) }, want: { [$("ofW").value]: Number($("ofWN").value) } });
  $("gvGo").onclick = () => {
    const to = $("gvTo").value.trim();
    if (!isAddress(to) || to === net.me) return alertBar(T("inviteBad", "That is not someone else's NADO address."));
    req({ t: "give", to, items: { [$("gvI").value]: Number($("gvN").value) } });
  };
}

// ---- input -----------------------------------------------------------------------------------------------------
// Breaking takes as long as the material's hardness over the tool's speed (land-recipes.json "breaking"); the server
// keeps the same clock, so a quicker page gains nothing. A mouse breaks while held; a tap on a touch screen keeps
// breaking the aimed cell until it gives or the aim moves.
/** Where a piece of the chosen size goes for this aim: flush against the face of the piece it hits, or standing on the
 *  ground where it hits; centred on the hit point on the other two axes, on the snap grid, inside the plot. */
function placement(a) {
  if (!a) return null;
  const { w, d, h, snap } = piece, sz = [w, d, h];
  const pt = a.point, c = plotCm(P.face, pt[0], pt[1], pt[2]);
  const at = [c.x, c.z, c.y], out = [0, 0, 0];
  let ax = 2, sign = 1;
  if (a.box) {
    const b = a.box.b, bc = plotCm(P.face, a.before[0], a.before[1], a.before[2]), was = [bc.x, bc.z, bc.y];
    for (const i of [2, 0, 1]) if (was[i] < b[i] || was[i] >= b[i] + b[i + 3]) { ax = i; sign = was[i] < b[i] ? -1 : 1; break; }
    out[ax] = sign > 0 ? b[ax] + b[ax + 3] : b[ax] - sz[ax];
  } else out[2] = Math.floor(at[2]);                       // on the ground: its bottom where the ground was hit
  for (const i of [0, 1, 2]) if (i !== ax) out[i] = Math.round((at[i] - sz[i] / 2) / snap) * snap;
  out[0] = Math.max(0, Math.min(Wd.PLOT_CM - w, out[0])); out[1] = Math.max(0, Math.min(Wd.PLOT_CM - d, out[1]));
  const box = [out[0], out[1], out[2], w, d, h, 0];
  // never inside the player
  const me = plotCm(P.face, P.u, P.v, P.h);
  const body = [me.x - HALF * Wd.CM, me.z - HALF * Wd.CM, me.y, 2 * HALF * Wd.CM, 2 * HALF * Wd.CM, TALL * Wd.CM];
  const rec = plotBoxes.get(c.plot);
  const clash = (me.plot === c.plot && Wd.boxesOverlap(box, body)) || (rec && rec.list.some((o) => Wd.boxesOverlap(box, o)));
  return { plot: c.plot, box, ok: !clash && box[2] >= 0 && box[2] + h <= Wd.H_CM };
}
function startBreak(c, mouse) {
  if (!RULES) return;
  const b = blockAt(P.face, c[0], c[1], c[2]), rule = RULES.breaking[b];
  if (!rule) return notify(T("cantGather", "Nothing here can be gathered."));
  if (rule.needs && !inv.tools.includes(rule.needs)) return notify(T("needsTool", "That needs a {t}.", { t: nameOf(rule.needs) }));
  const speed = rule.class && inv.tools.includes(rule.class) ? RULES.tools[rule.class].speed : 1;
  job = { cell: c, need: rule.hard / speed, done: 0, mouse };
}
function startTakeDown(bx, mouse) {
  const rule = RULES.breaking[bx.b[6]] || { hard: 1 };
  if (rule.needs && !inv.tools.includes(rule.needs)) return notify(T("needsTool", "That needs a {t}.", { t: nameOf(rule.needs) }));
  const speed = rule.class && inv.tools.includes(rule.class) ? RULES.tools[rule.class].speed : 1;
  job = { box: bx, need: Math.max(0.05, (rule.hard * Wd.boxVolume(bx.b)) / 1e6 / speed), done: 0, mouse };
}
function breakTick(dt) {
  const bar = $("breakBar");
  if (!job) { bar.classList.add("hidden"); return; }
  const a = aim();
  const same = job.box ? a && a.box && a.box.b === job.box.b : a && a.hit && a.hit.join() === job.cell.join();
  if ((job.mouse && !mouseHeld) || !same) { job = null; bar.classList.add("hidden"); return; }
  job.done += dt;
  bar.classList.remove("hidden");
  bar.firstElementChild.style.width = Math.min(100, (100 * job.done) / job.need) + "%";
  if (job.done >= job.need) {
    const j = job; job = null; bar.classList.add("hidden");
    if (j.box) net.send({ t: "boxes", plot: j.box.plot, remove: [j.box.b], req: ++net.req });
    else setBlock(P.face, j.cell[0], j.cell[1], j.cell[2], B.air);
  }
}
const NATURAL_ITEMS = new Set(["dirt", "sand", "gravel", "snow"]);   // these fill the ground's cells; the rest are pieces
const haveCm3 = (id) => (inv.items[id] || 0) * 1e6 + ((inv.vol || {})[id] || 0);
function act(place, mouse) {
  const a = aim();
  if (!a) return;
  if (place) {
    const id = hot[slot];
    if (!net.online || !net.me) return setBlock(P.face, Math.floor(a.point[0]), Math.floor(a.point[1]), Math.floor(a.point[2]), B.air);   // says why first
    if (!id || !(haveCm3(id) > 0)) return notify(T("noItem", "You have none of that — gather or make some first."));
    if (NATURAL_ITEMS.has(id)) {
      if (!a.prev) return;
      return setBlock(P.face, a.prev[0], a.prev[1], a.prev[2], RULES.items[id].places);
    }
    const pl = placement(a);
    if (!pl) return;
    if (!mayBuild(pl.plot)) return explainNoBuild(pl.plot);
    if (!pl.ok) return notify(T("noRoom", "No room for that piece there."));
    const box = pl.box.slice(); box[6] = RULES.items[id].places;
    if (haveCm3(id) < Wd.boxVolume(box)) return notify(T("notEnough", "Not enough {i} for a piece that size.", { i: nameOf(id) }));
    const cur = plotBoxes.get(pl.plot);
    setPlotBoxes(pl.plot, (cur ? cur.list : []).concat([box]));                 // shown at once; put back if refused
    net.send({ t: "boxes", plot: pl.plot, add: [box], req: ++net.req });
  } else {
    if (a.box) return startTakeDown(a.box, mouse);
    const [u, v, h] = a.hit;
    if (blockAt(P.face, u, v, h) === B.bedrock) return;
    startBreak(a.hit, mouse);
  }
}
function wireInput(canvas) {
  canvas.addEventListener("click", () => { if (!locked && !touch) canvas.requestPointerLock(); });
  document.addEventListener("pointerlockchange", () => { locked = document.pointerLockElement === canvas; $("help").classList.toggle("hidden", locked); });
  document.addEventListener("mousemove", (e) => {
    if (!locked) return;
    P.yaw += e.movementX * 0.0024; P.pitch = Math.max(-1.55, Math.min(1.55, P.pitch - e.movementY * 0.0024));
  });
  document.addEventListener("mousedown", (e) => { if (!locked) return; if (e.button === 0) { mouseHeld = true; act(false, true); } else if (e.button === 2) act(true); });
  document.addEventListener("mouseup", (e) => { if (e.button === 0) mouseHeld = false; });
  document.addEventListener("contextmenu", (e) => { if (locked) e.preventDefault(); });
  document.addEventListener("wheel", (e) => { if (!locked || !hot.length) return; slot = (slot + (e.deltaY > 0 ? 1 : hot.length - 1)) % hot.length; hotbar(); }, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
    keys.add(e.code);
    if (/^Digit[1-9]$/.test(e.code) && Number(e.code.slice(5)) <= hot.length) { slot = Number(e.code.slice(5)) - 1; hotbar(); }
    if (e.code === "KeyR") { const i = PRESETS.findIndex((x) => x[0] === piece.w && x[1] === piece.d && x[2] === piece.h); [piece.w, piece.d, piece.h] = PRESETS[(i + 1) % PRESETS.length]; pieceInfo(); }
    if (e.code === "KeyT") { [piece.w, piece.d] = [piece.d, piece.w]; pieceInfo(); }
    if (e.code === "BracketLeft" || e.code === "BracketRight") { const i = SNAPS.indexOf(piece.snap); piece.snap = SNAPS[Math.max(0, Math.min(SNAPS.length - 1, (i < 0 ? 2 : i) + (e.code === "BracketRight" ? 1 : -1)))]; pieceInfo(); }
    if (e.code === "KeyF") { P.fly = !P.fly; P.vh = 0; notify(P.fly ? T("flyOn", "Flying — Space up, C down, Shift fast") : T("flyOff", "Walking"), 1600); }
    if (e.code === "KeyE") palette($("palette").classList.contains("hidden"));
    if (e.code === "Escape") palette(false);
    if (e.code === "Space" && locked) e.preventDefault();
  });
  document.addEventListener("keyup", (e) => keys.delete(e.code));
  window.addEventListener("blur", () => keys.clear());
  // touch: the left half steers, the right half looks; buttons jump/fly/break/place
  if ("ontouchstart" in window || navigator.maxTouchPoints > 0) {
    touch = { mx: 0, my: 0, up: false, down: false };
    document.body.classList.add("touch");
    let stickId = null, lookId = null, sx = 0, sy = 0, lx = 0, ly = 0;
    canvas.addEventListener("touchstart", (e) => {
      for (const t of e.changedTouches) {
        if (t.clientX < innerWidth / 2 && stickId === null) { stickId = t.identifier; sx = t.clientX; sy = t.clientY; }
        else if (lookId === null) { lookId = t.identifier; lx = t.clientX; ly = t.clientY; }
      }
      e.preventDefault();
    }, { passive: false });
    canvas.addEventListener("touchmove", (e) => {
      for (const t of e.changedTouches) {
        if (t.identifier === stickId) { touch.mx = Math.max(-1, Math.min(1, (t.clientX - sx) / 50)); touch.my = Math.max(-1, Math.min(1, -(t.clientY - sy) / 50)); }
        if (t.identifier === lookId) { P.yaw += (t.clientX - lx) * 0.006; P.pitch = Math.max(-1.55, Math.min(1.55, P.pitch - (t.clientY - ly) * 0.006)); lx = t.clientX; ly = t.clientY; }
      }
      e.preventDefault();
    }, { passive: false });
    canvas.addEventListener("touchend", (e) => {
      for (const t of e.changedTouches) { if (t.identifier === stickId) { stickId = null; touch.mx = touch.my = 0; } if (t.identifier === lookId) lookId = null; }
    });
    const hold = (id, k) => { const el = $(id); el.addEventListener("touchstart", (e) => { touch[k] = true; e.preventDefault(); }, { passive: false }); el.addEventListener("touchend", () => { touch[k] = false; }); };
    hold("tJump", "up"); hold("tDown", "down");
    $("tFly").onclick = () => { P.fly = !P.fly; P.vh = 0; };
    $("tBreak").onclick = () => act(false, false);
    $("tPlace").onclick = () => act(true);
    $("tPal").onclick = () => palette(true);
  }
  $("palClose").onclick = () => palette(false);
}

// ---- frame -----------------------------------------------------------------------------------------------------
// ---- the ground's material: six real textures (static/vendor/textures, CC0 Poly Haven) mixed by the weights the mesher
// gives every ground vertex. Each is sampled at two scales and the two mixed, which hides the repetition a single tiling
// shows from any height; rock is projected from three sides by the ground's normal, so a cliff is not a smear.
const GROUND = ["grass", "dirt", "rock", "sand", "snow", "gravel"];
const GROUND_ROUGH = [0.96, 0.95, 0.85, 0.9, 0.55, 0.9];
function loadTex(name) {
  const t = new THREE.TextureLoader().load(`/static/vendor/textures/${name}.jpg`);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}
function groundMaterial() {
  const uvw = TSL.attribute("uvw", "vec3"), gn = TSL.attribute("gn", "vec3").abs();
  const w1 = TSL.attribute("w1", "vec4"), w2 = TSL.attribute("w2", "vec2");
  const near = uvw.xy.div(3.2), far = uvw.xy.div(23.0);                // metres per repeat, close up and from afar
  const two = (t) => TSL.mix(TSL.texture(t, near).rgb, TSL.texture(t, far).rgb, 0.35);
  const tex = GROUND.map((k) => loadTex(k + "_col"));
  // rock: three planar projections blended by the normal's weight on each axis
  const tw = gn.pow(4), tws = tw.x.add(tw.y).add(tw.z);
  const rock = TSL.texture(tex[2], TSL.vec2(uvw.y, uvw.z).div(4.5)).rgb.mul(tw.x)
    .add(TSL.texture(tex[2], TSL.vec2(uvw.x, uvw.z).div(4.5)).rgb.mul(tw.y))
    .add(TSL.texture(tex[2], near.mul(3.2 / 4.5)).rgb.mul(tw.z)).div(tws);
  // the scanned grass is a forest floor (brown-green); under the blades it is tinted to a living meadow's green
  const color = two(tex[0]).mul(TSL.vec3(0.72, 1.0, 0.55)).mul(w1.x).add(two(tex[1]).mul(w1.y)).add(rock.mul(w1.z)).add(two(tex[3]).mul(w1.w))
    .add(two(tex[4]).mul(w2.x)).add(two(tex[5]).mul(w2.y));
  const m = new THREE.MeshStandardNodeMaterial({ metalness: 0 });
  m.colorNode = color.mul(TSL.attribute("color", "vec3"));
  m.roughnessNode = w1.x.mul(GROUND_ROUGH[0]).add(w1.y.mul(GROUND_ROUGH[1])).add(w1.z.mul(GROUND_ROUGH[2])).add(w1.w.mul(GROUND_ROUGH[3]))
    .add(w2.x.mul(GROUND_ROUGH[4])).add(w2.y.mul(GROUND_ROUGH[5]));
  return m;
}

// ---- grass: instanced clumps of tapered blades, dark at the root and light at the tip, swaying in the wind on the GPU
// (the mesher scatters them over the meadow, near the player only). One clump in 25 is a wildflower.
let clumpGeo = null, flowerGeo = null, matGrass = null;
function bladeClump(blades, flower) {
  const pos = [], col = [], nor = [], idx = [];
  let seed = flower ? 7 : 3;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < blades; i++) {
    const a = rnd() * Math.PI * 2, r = rnd() * 0.14, h = 0.22 + rnd() * 0.33, w = 0.01 + rnd() * 0.008, lean = 0.05 + rnd() * 0.12;
    const bx = Math.cos(a) * r, bz = Math.sin(a) * r, dx = Math.cos(a + 1.3) * w, dz = Math.sin(a + 1.3) * w, lx = Math.cos(a) * lean, lz = Math.sin(a) * lean;
    const base = pos.length / 3;
    pos.push(bx - dx, 0, bz - dz, bx + dx, 0, bz + dz, bx - dx * 0.6 + lx * 0.4, h * 0.55, bz - dz * 0.6 + lz * 0.4,
             bx + dx * 0.6 + lx * 0.4, h * 0.55, bz + dz * 0.6 + lz * 0.4, bx + lx, h, bz + lz);
    const root = [0.05, 0.12, 0.02], mid = [0.13, 0.28, 0.05], tip = [0.30, 0.45, 0.10];
    col.push(...root, ...root, ...mid, ...mid, ...tip);
    for (let k = 0; k < 5; k++) nor.push(0, 1, 0);                 // up-facing normals: the blade takes the ground's light
    // both faces, each wound to face out, both with the up normal: a double-sided material would flip the back face's
    // normal downward and the blade's back would render black
    idx.push(base, base + 1, base + 3, base, base + 3, base + 2, base + 2, base + 3, base + 4,
             base, base + 3, base + 1, base, base + 2, base + 3, base + 2, base + 4, base + 3);
  }
  if (flower) for (let i = 0; i < 3; i++) {                        // three small yellow heads
    const a = rnd() * Math.PI * 2, r = rnd() * 0.1, h = 0.45 + rnd() * 0.2, s = 0.03, base = pos.length / 3;
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    pos.push(x - s, h, z - s, x + s, h, z - s, x + s, h, z + s, x - s, h, z + s);
    for (let k = 0; k < 4; k++) { col.push(0.95, 0.75, 0.12); nor.push(0, 1, 0); }
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  g.setIndex(idx);
  return g;
}
function grassMeshes(gr) {
  if (!clumpGeo) {
    clumpGeo = bladeClump(9, false); flowerGeo = bladeClump(4, true);
    matGrass = new THREE.MeshStandardNodeMaterial({ roughness: 0.85, metalness: 0 });
    matGrass.colorNode = TSL.attribute("color", "vec3");
    // wind: the tip sways most, the root not at all; each clump in its own phase
    const lp = TSL.positionLocal, sway = TSL.sin(TSL.time.mul(1.7).add(TSL.instanceIndex.toFloat().mul(0.731))).mul(0.06)
      .add(TSL.sin(TSL.time.mul(0.45).add(TSL.instanceIndex.toFloat().mul(0.113))).mul(0.05));
    // the sway's strength comes from the blade's OWN height (the geometry's vertex), not from positionLocal: by here
    // that already includes the instance's place in the chunk, metres up — squared, it threw the grass into the sky
    const tipness = TSL.attribute("position", "vec3").y.div(0.75).clamp(0, 1).pow(2);
    matGrass.positionNode = lp.add(TSL.vec3(sway, 0, sway.mul(0.6)).mul(tipness));
  }
  const n = gr.kind.length, nf = gr.kind.reduce((a, x) => a + x, 0);
  const grass = new THREE.InstancedMesh(clumpGeo, matGrass, n - nf), flowers = new THREE.InstancedMesh(flowerGeo, matGrass, Math.max(1, nf));
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), q2 = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), nv = new THREE.Vector3(), p = new THREE.Vector3(), sc = new THREE.Vector3();
  let gi = 0, fi = 0;
  for (let i = 0; i < n; i++) {
    const o = i * 7, r = gr.inst[o + 6];
    p.set(gr.inst[o], gr.inst[o + 1], gr.inst[o + 2]);
    nv.set(gr.inst[o + 3], gr.inst[o + 4], gr.inst[o + 5]).normalize();
    q.setFromUnitVectors(up, nv).multiply(q2.setFromAxisAngle(up, r * Math.PI * 2));
    const s = 0.75 + 0.55 * r;
    m.compose(p, q, sc.set(s, s, s));
    if (gr.kind[i]) flowers.setMatrixAt(fi++, m); else grass.setMatrixAt(gi++, m);
  }
  flowers.count = fi;
  return fi ? [grass, flowers] : [grass];
}

// ---- the forest's materials (static/land-trees.js builds the models in the mesher worker) -----------------------------
// LEAVES: a painted atlas, 2 x 2 tiles — broadleaf cluster, birch cluster, needle spray, palm frond (land-trees.js
// LEAF_TILE). Colour and coverage are painted on two separate opaque canvases and joined into one RGBA texture: a canvas
// stores colour PREMULTIPLIED, so its transparent pixels are black, and every mip level would blend black into the leaf
// edges (dark-rimmed cards at a distance). Here the space between leaves carries the leaves' own mean green.
function paintLeaves() {
  const S = 1024, T = 512;
  const mk = () => { const c = document.createElement("canvas"); c.width = c.height = S; return c; };
  const colC = mk(), mskC = mk(), col = colC.getContext("2d"), msk = mskC.getContext("2d");
  const bg = ["#3d5a24", "#5a7330", "#22402a", "#5b7a2c"];
  for (let t = 0; t < 4; t++) { col.fillStyle = bg[t]; col.fillRect((t & 1) * T, (t >> 1) * T, T, T); }
  msk.fillStyle = "#000"; msk.fillRect(0, 0, S, S);
  let seed = 11;
  const R = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  // one shape onto both canvases: its colour on one, white coverage on the other
  const both = (draw, fill, stroke) => {
    for (const [g, f] of [[col, fill], [msk, "#fff"]]) { g.save(); g.fillStyle = f; g.strokeStyle = stroke === undefined ? f : (g === msk ? "#fff" : stroke); draw(g); g.restore(); }
  };
  const leaf = (x, y, ang, len, wid, fill, rib) => {
    both((g) => {
      g.translate(x, y); g.rotate(ang); g.beginPath(); g.moveTo(0, 0);
      g.quadraticCurveTo(wid, len * 0.45, 0, len); g.quadraticCurveTo(-wid, len * 0.45, 0, 0); g.fill();
    }, fill);
    col.save(); col.translate(x, y); col.rotate(ang); col.strokeStyle = rib; col.lineWidth = 1.5;     // the midrib, colour only
    col.beginPath(); col.moveTo(0, len * 0.05); col.lineTo(0, len * 0.9); col.stroke(); col.restore();
  };
  const line = (x0, y0, x1, y1, w, c) => both((g) => { g.lineWidth = w; g.lineCap = "round"; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke(); }, c, c);
  const hsl = (h, s, l) => `hsl(${h},${s}%,${l}%)`;
  // 0: broadleaf — twigs from the middle, then leaves, densest at the heart
  for (let k = 0; k < 7; k++) { const a = R() * 6.28; line(256, 256, 256 + Math.cos(a) * 190, 256 + Math.sin(a) * 190, 4, "#4a3826"); }
  for (let k = 0; k < 120; k++) {
    const a = R() * 6.28, r = Math.sqrt(R()) * 200, l = 30 + R() * 14;
    leaf(256 + Math.cos(a) * r, 256 + Math.sin(a) * r, R() * 6.28, 50 + R() * 34, 16 + R() * 10, hsl(95 + R() * 25, 42 + R() * 18, l), hsl(90, 40, l + 12));
  }
  // 1: birch — smaller, rounder, lighter leaves on fine twigs
  for (let k = 0; k < 9; k++) { const a = R() * 6.28; line(768, 256, 768 + Math.cos(a) * 200, 256 + Math.sin(a) * 200, 2, "#5a4a3a"); }
  for (let k = 0; k < 170; k++) {
    const a = R() * 6.28, r = Math.sqrt(R()) * 210, l = 34 + R() * 14;
    leaf(768 + Math.cos(a) * r, 256 + Math.sin(a) * r, R() * 6.28, 30 + R() * 16, 15 + R() * 6, hsl(80 + R() * 20, 50 + R() * 15, l), hsl(75, 45, l + 10));
  }
  // 2: needle spray — a twig down the middle (base at the top: v = 0 is the branch's base), needles toward the tip
  line(256, 520, 256, 1010, 7, "#4a3626");
  for (let y = 525; y < 1010; y += 3) {
    const f = (y - 520) / 490, env = Math.pow(Math.sin(Math.PI * Math.min(1, f * 1.1 + 0.08)), 0.5);
    for (const sg of [-1, 1]) {
      const a = (0.75 + R() * 0.3) * sg, ln = (55 + R() * 55) * env, l = 14 + R() * 12;
      line(256, y, 256 + Math.sin(a) * ln, y + Math.cos(a) * ln * 0.75, 2.6, hsl(140 + R() * 25, 32 + R() * 16, l));
    }
  }
  // 3: palm frond — the rachis down the middle, long tapering leaflets swept toward the tip
  line(768, 512, 768, 1024, 7, "#8a8a4a");
  for (let y = 520; y < 1020; y += 8) {
    const f = (y - 512) / 512, env = Math.pow(Math.sin(Math.PI * Math.min(1, f + 0.04)), 0.55);
    for (const sg of [-1, 1]) {
      const ln = 245 * env, a = (1.05 + R() * 0.15) * sg, ex = 768 + Math.sin(a) * ln, ey = y + Math.cos(a) * ln * 0.55, l = 30 + R() * 12;
      both((g) => { g.beginPath(); g.moveTo(768, y - 4); g.quadraticCurveTo((768 + ex) / 2, (y + ey) / 2 - 10, ex, ey); g.quadraticCurveTo((768 + ex) / 2, (y + ey) / 2 + 6, 768, y + 5); g.fill(); }, hsl(78 + R() * 18, 52 + R() * 14, l));
    }
  }
  const c = col.getImageData(0, 0, S, S).data, m = msk.getImageData(0, 0, S, S).data, out = new Uint8Array(S * S * 4);
  for (let i = 0; i < S * S; i++) { out[i * 4] = c[i * 4]; out[i * 4 + 1] = c[i * 4 + 1]; out[i * 4 + 2] = c[i * 4 + 2]; out[i * 4 + 3] = m[i * 4]; }
  const tex = new THREE.DataTexture(out, S, S, THREE.RGBAFormat);   // row 0 = v 0: canvas top is each tile's v = 0
  tex.colorSpace = THREE.SRGBColorSpace; tex.generateMipmaps = true;
  tex.minFilter = THREE.LinearMipmapLinearFilter; tex.magFilter = THREE.LinearFilter; tex.anisotropy = 4;
  tex.needsUpdate = true;
  return tex;
}
function treeMaterials() {
  const wind = TSL.attribute("wind", "vec4"), t = TSL.time, ph = wind.w;
  // a slow sway with a gusting second rhythm, biased downwind; each tree on its own phase
  const gust = TSL.sin(t.mul(1.3).add(ph)).mul(0.55).add(TSL.sin(t.mul(2.7).add(ph.mul(1.7))).mul(0.25)).add(0.35);
  const sway = TSL.positionLocal.add(wind.xyz.mul(gust));
  const lin = (name) => { const x = loadTex(name); x.colorSpace = THREE.NoColorSpace; return x; };
  const uv = TSL.uv(), birch = TSL.attribute("tile", "float");
  const bark = new THREE.MeshStandardNodeMaterial({ roughness: 0.92, metalness: 0 });
  bark.colorNode = TSL.mix(TSL.texture(loadTex("bark_col"), uv).rgb, TSL.texture(loadTex("birch_col"), uv).rgb, birch).mul(TSL.attribute("color", "vec3"));
  bark.normalNode = TSL.normalMap(TSL.mix(TSL.texture(lin("bark_nor"), uv), TSL.texture(lin("birch_nor"), uv), birch));
  bark.positionNode = sway;
  const leafTex = paintLeaves(), s = TSL.texture(leafTex, uv);
  const leaves = new THREE.MeshStandardNodeMaterial({ roughness: 0.7, metalness: 0, side: THREE.DoubleSide, alphaTest: 0.42 });
  leaves.colorNode = s.rgb.mul(TSL.attribute("color", "vec3"));
  leaves.opacityNode = s.a;
  // leaves flutter on top of the sway: a quick small motion along each card's normal
  const flutter = TSL.sin(t.mul(9).add(ph.mul(3)).add(TSL.positionLocal.x.mul(4)).add(TSL.positionLocal.z.mul(3))).mul(wind.xyz.length().mul(0.22));
  leaves.positionNode = sway.add(TSL.attribute("normal", "vec3").mul(flutter));
  return [bark, leaves];
}

// ---- the picture: ambient occlusion, bloom, anti-aliasing ("overall not impressive", operator 2026-11-06) ---------------
// GTAO from a depth + normal pre-pass darkens what the sky cannot reach — the foot of a wall, the inside of a doorway, the
// ground under a tree — through builtinAOContext, i.e. on INDIRECT light only (the sun's own shadow map handles direct);
// a soft bloom lets the sun and lit glass glow; FXAA smooths edges after tone mapping. A touch device gets the plain
// render: two scene passes are more than a phone's GPU should pay for its first impression.
function buildPipeline() {
  if (touch || new URLSearchParams(location.search).has("plain")) return null;
  try {
    const pl = new THREE.RenderPipeline(renderer);
    const pre = TSL.pass(scene, camera);
    pre.setMRT(TSL.mrt({ output: TSL.normalView }));
    const aoPass = ao(pre.getTextureNode("depth"), pre.getTextureNode(), camera);
    aoPass.resolutionScale = 0.5;
    aoPass.radius.value = 0.6;
    const main = TSL.pass(scene, camera);
    main.contextNode = TSL.builtinAOContext(aoPass.getTextureNode().sample(TSL.screenUV).r);
    const lit = main.add(bloom(main, 0.18, 0.35, 0.92));
    pl.outputColorTransform = false;                       // tone map + sRGB first, then anti-alias the finished image
    pl.outputNode = fxaa(TSL.renderOutput(lit));
    return pl;
  } catch (e) { return null; }                             // an older backend without these nodes: the plain render
}

// ---- light and sky ------------------------------------------------------------------------------------------------
// The sun is a real star at a real distance (static/land-cosmos.js): the planet orbits it and turns under it, and the page
// reads where it is in the planet's frame, how far, how big it looks and how bright it is. Everything else follows ITS
// HEIGHT ABOVE THE PLAYER'S HORIZON, so it is noon on one side of the planet while it is night on the other. One sunlight casts shadows in a box that follows
// the player (the camera is the origin); the moon is its dim blue opposite. The dome is re-coloured from that height —
// a deep zenith over a pale horizon by day, a glow around the sun as it sets, stars at night — and the fog takes the
// horizon's colour so the land melts into the sky instead of ending at a wall.
const SKY = { zenith: new THREE.Color(0x2f6fc8), horizon: new THREE.Color(0xb7d6ef), nightZ: new THREE.Color(0x03060d),
  nightH: new THREE.Color(0x0b1424), dusk: new THREE.Color(0xf0874a), duskZ: new THREE.Color(0x29386d), white: new THREE.Color(0xfff8ee) };
let moon, dome, sunDisc, sunGlow, sunHalo, stars, skyAt = 0;
const SKY_R = 3200;                          // the dome's radius: everything celestial is drawn at its true ANGLE on it
const smooth01 = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
function glowTexture() {
  const cv = document.createElement("canvas"); cv.width = cv.height = 128;
  const g = cv.getContext("2d"), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, "rgba(255,244,220,1)"); r.addColorStop(0.12, "rgba(255,226,170,0.55)"); r.addColorStop(0.4, "rgba(255,190,120,0.12)"); r.addColorStop(1, "rgba(255,170,90,0)");
  g.fillStyle = r; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function buildSky() {
  dome = new THREE.Mesh(new THREE.SphereGeometry(3400, 48, 24), new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, fog: false, depthWrite: false }));
  dome.geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(dome.geometry.attributes.position.count * 3), 3));
  dome.renderOrder = -2;
  scene.add(dome);
  // the star itself: a sphere whose radius on the dome gives it its TRUE apparent size, and a glow that the eye (and a
  // camera) would see around something that bright
  sunDisc = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 12), new THREE.MeshBasicMaterial({ color: 0xfff6e8, fog: false, depthWrite: false }));
  sunDisc.renderOrder = -1;
  const glowMat = () => new THREE.SpriteMaterial({ map: glowTexture(), fog: false, depthWrite: false, transparent: true, blending: THREE.AdditiveBlending });
  sunGlow = new THREE.Sprite(glowMat());                    // the tight bloom around the disc
  sunHalo = new THREE.Sprite(glowMat());                    // the wide, faint one
  sunGlow.renderOrder = sunHalo.renderOrder = -1;
  scene.add(sunDisc, sunGlow, sunHalo);
  const n = 2200, pos = new Float32Array(n * 3);
  let seed = 99;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < n; i++) {
    const z = rnd() * 2 - 1, a = rnd() * Math.PI * 2, r = Math.sqrt(1 - z * z);
    pos.set([Math.cos(a) * r * 3300, z * 3300, Math.sin(a) * r * 3300], i * 3);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  stars = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: 1.6, sizeAttenuation: false, transparent: true, fog: false, depthWrite: false }));
  stars.renderOrder = -1;
  scene.add(stars);
}
function sky(fr) {
  const star = Cosmos.sunFrom(Wd.PLANET), sd = new THREE.Vector3(...star.dir), up = new THREE.Vector3(fr.up[0], fr.up[1], fr.up[2]);
  const elev = sd.dot(up);                                  // the sun's height over this player's horizon (-1..1)
  const day = smooth01(-0.08, 0.22, elev), dusk = Math.max(0, 1 - Math.abs(elev) / 0.22);
  sun.position.copy(sd).multiplyScalar(150);
  sun.color.setRGB(1, 0.62 + 0.35 * smooth01(0, 0.4, elev), 0.38 + 0.55 * smooth01(0, 0.5, elev));
  sun.intensity = 2.4 * Math.min(1.6, star.flux) * day;
  // shadows only once the sun is well up: at a grazing sun the shadow map streaks the ground (acne), and real dusk
  // shadows are long and faint anyway
  sun.castShadow = elev > 0.12;
  moon.position.copy(sd).multiplyScalar(-150);
  moon.intensity = 0.35 * (1 - day);
  hemi.position.copy(up);                                   // three's hemisphere light assumes +Y; here "up" is radial
  hemi.intensity = 0.6 + 1.6 * day;                         // the sky lights what the sun does not reach: a wall in its own
                                                            // shade is dim, never black (the first house render was)
  hemi.color.copy(SKY.nightH).lerp(SKY.horizon, day);
  const zen = SKY.nightZ.clone().lerp(SKY.zenith, day).lerp(SKY.duskZ, dusk * 0.5);
  const hor = SKY.nightH.clone().lerp(SKY.horizon, day).lerp(SKY.dusk, dusk * 0.6);
  scene.fog.color.copy(hor);
  scene.background = hor;
  dome.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), up);
  sunDisc.position.copy(sd).multiplyScalar(SKY_R);
  sunDisc.scale.setScalar(SKY_R * Math.tan(star.angularRadius));    // ~17 m at 3.2 km: 0.6° of sky, as from 0.8 AU
  sunDisc.visible = sunGlow.visible = sunHalo.visible = elev > -0.05;
  // over-bright on purpose: the tone mapper takes the disc to white, as a real sun reads to an eye or a camera
  sunDisc.material.color.setRGB(6 * star.colour[0], 6 * star.colour[1] * (0.75 + 0.25 * day), 6 * star.colour[2] * (0.55 + 0.45 * day));
  const rs = SKY_R * Math.tan(star.angularRadius);
  sunGlow.position.copy(sd).multiplyScalar(SKY_R * 0.99); sunGlow.scale.setScalar(rs * 14);
  sunHalo.position.copy(sd).multiplyScalar(SKY_R * 0.98); sunHalo.scale.setScalar(rs * 60);
  sunGlow.material.opacity = 1; sunHalo.material.opacity = 0.35 + 0.25 * day;
  stars.material.opacity = 1 - smooth01(-0.15, 0.05, elev);
  const R = Cosmos.skyRotation(Wd.PLANET);                  // the fixed stars, carried into the turning planet's frame
  stars.matrixAutoUpdate = false;
  stars.matrix.set(R[0], R[1], R[2], 0, R[3], R[4], R[5], 0, R[6], R[7], R[8], 0, 0, 0, 0, 1);
  if (performance.now() - skyAt < 400) return;              // the dome's colours change slowly: repaint twice a second
  skyAt = performance.now();
  const local = sd.clone().applyQuaternion(dome.quaternion.clone().invert());
  const pos = dome.geometry.attributes.position, Cc = dome.geometry.attributes.color, v = new THREE.Vector3(), c = new THREE.Color();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).normalize();
    const alt = v.y;
    c.copy(hor).lerp(zen, Math.pow(Math.max(0, alt), 0.55));
    const toward = Math.max(0, v.dot(local));
    const glow = dusk * Math.pow(toward, 6) * (1 - Math.max(0, alt));
    c.lerp(SKY.dusk, Math.min(1, glow * 1.4));
    c.lerp(SKY.white, day * 0.45 * Math.pow(toward, 24));    // by day the sky whitens toward the sun (scattering)
    if (alt < 0) c.multiplyScalar(1 + alt * 0.6);           // below the horizon: the haze darkens
    Cc.setXYZ(i, c.r, c.g, c.b);
  }
  Cc.needsUpdate = true;
}
function frame(now) {
  const dt = Math.min(0.05, (now - lastT) / 1000 || 0); lastT = now;
  step(dt);
  breakTick(dt);
  const cam = eyePos(), { fr, fw } = look();
  camera.up.set(fr.up[0], fr.up[1], fr.up[2]);
  camera.lookAt(fw[0], fw[1], fw[2]);
  hemi.position.set(fr.up[0], fr.up[1], fr.up[2]);     // "up" is radial on a planet: three's hemisphere light assumes +Y
  for (const c of chunks.values()) if (c.anchor) for (const me of c.meshes) me.position.set(c.anchor[0] - cam[0], c.anchor[1] - cam[1], c.anchor[2] - cam[2]);
  if (farMesh) { const a = farMesh.userData.anchor; farMesh.position.set(a[0] - cam[0], a[1] - cam[1], a[2] - cam[2]); }
  for (const r of others.values()) {
    if (!r.p) continue;
    const [f, u, v, h, yaw] = r.p, q = Wd.posOf(f, u, v, h), ofr = Wd.frameOf(f, u, v);
    r.mesh.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    r.mesh.up.set(ofr.up[0], ofr.up[1], ofr.up[2]);
    const fx = Math.sin(yaw) * ofr.east[0] + Math.cos(yaw) * ofr.north[0], fy = Math.sin(yaw) * ofr.east[1] + Math.cos(yaw) * ofr.north[1], fz = Math.sin(yaw) * ofr.east[2] + Math.cos(yaw) * ofr.north[2];
    r.mesh.lookAt(r.mesh.position.x + fx, r.mesh.position.y + fy, r.mesh.position.z + fz);
  }
  sky(fr);
  // the aimed block's outline
  const a = aim();
  // a cell's outline, or the piece's own box; and where the chosen piece would go (green: it fits, red: it does not)
  const frameBox = (obj, plot, b) => {
    const q = Wd.plotCoords(plot), cx = q.u0 + (b[0] + b[3] / 2) / Wd.CM, cz = q.v0 + (b[1] + b[4] / 2) / Wd.CM, cy = (b[2] + b[5] / 2) / Wd.CM;
    const c = Wd.posOf(P.face, cx, cz, cy);
    obj.position.set(c[0] - cam[0], c[1] - cam[1], c[2] - cam[2]);
    obj.up.set(fr.up[0], fr.up[1], fr.up[2]);
    obj.lookAt(obj.position.x + fr.north[0], obj.position.y + fr.north[1], obj.position.z + fr.north[2]);
    obj.scale.set(b[3] / Wd.CM + 0.01, b[5] / Wd.CM + 0.01, b[4] / Wd.CM + 0.01);
    obj.visible = true;
  };
  highlight.visible = ghost.visible = false;
  if (a && a.box) frameBox(highlight, a.box.plot, a.box.b);
  else if (a && a.hit) {
    const hp = Wd.plotOf(P.face, a.hit[0], a.hit[1]), q = Wd.plotCoords(hp);
    frameBox(highlight, hp, [(a.hit[0] - q.u0) * Wd.CM, (a.hit[1] - q.v0) * Wd.CM, a.hit[2] * Wd.CM, Wd.CM, Wd.CM, Wd.CM]);
  }
  const id = hot[slot];
  if (a && id && !NATURAL_ITEMS.has(id) && net.me) {
    const pl = placement(a);
    if (pl) { frameBox(ghost, pl.plot, pl.box); ghost.material.color.setHex(pl.ok && mayBuild(pl.plot) ? 0x33dd77 : 0xdd4433); }
  }
  if (pipeline) pipeline.render(); else renderer.render(scene, camera);
}
let tick = 0;
function slow() {
  updateChunks();
  netTick();
  if (!farAt || farAt.face !== P.face || Math.abs(farAt.u - P.u) > 400 || Math.abs(farAt.v - P.v) > 400) buildFar();
  hud();
  if (++tick % 20 === 0) save();
}

// ---- start -----------------------------------------------------------------------------------------------------
async function start() {
  load();
  RULES = await (await fetch("/static/land-recipes.json", { cache: "no-cache" })).json();
  const canvas = $("world");
  renderer = new THREE.WebGPURenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.setSize(innerWidth, innerHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;            // r187's WebGPU renderer has no PCFSoftShadowMap
  await renderer.init();
  $("hudGpu").textContent = renderer.backend && renderer.backend.isWebGPUBackend ? "WebGPU" : "WebGL2";
  scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xb7d6ef, viewDist * CHUNK * 0.9, 2900);
  camera = new THREE.PerspectiveCamera(72, innerWidth / innerHeight, 0.08, 4000);
  camera.position.set(0, 0, 0);
  sun = new THREE.DirectionalLight(0xfff4e0, 3);
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -48, right: 48, top: 48, bottom: -48, near: 10, far: 320 });
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.04;
  scene.add(sun, sun.target);                               // the target stays at the origin: the player
  moon = new THREE.DirectionalLight(0x8fa8d8, 0.3); scene.add(moon, moon.target);
  hemi = new THREE.HemisphereLight(0xcfe8ff, 0x5a4a38, 0.9); scene.add(hemi);
  scene.add(new THREE.AmbientLight(0x8090b0, 0.45));      // a night is dark, never black
  buildSky();
  const atlas = paintAtlas();
  atlasTex = new THREE.CanvasTexture(atlas);
  atlasTex.magFilter = THREE.NearestFilter; atlasTex.minFilter = THREE.NearestFilter; atlasTex.colorSpace = THREE.SRGBColorSpace;
  atlasTex.generateMipmaps = false;
  matSolid = new THREE.MeshStandardMaterial({ map: atlasTex, vertexColors: true, alphaTest: 0.5, roughness: 0.85, metalness: 0 });
  matClear = new THREE.MeshStandardMaterial({ map: atlasTex, vertexColors: true, transparent: true, depthWrite: false, roughness: 0.15, metalness: 0 });
  matGround = groundMaterial();
  matTrees = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9, metalness: 0 });
  [matBark, matLeaves] = treeMaterials();
  // pieces: the material's atlas tile, repeated once per METRE of the piece (uv is in metres; fract() keeps it inside
  // the tile, half a texel in from its edge), so any size shows its material at true scale
  // the tile number is ROUNDED: interpolated across a triangle, 16 arrives as 15.9999 and its row rounds down to the
  // neighbouring tile (glass-blue specks all over the first roof render)
  const tileA = TSL.attribute("tile", "float").add(0.5).floor(), f = TSL.fract(TSL.uv());
  const tw = 1 / TCOLS, th = 1 / TROWS, eu = 0.5 / (TILE * TCOLS), ev = 0.5 / (TILE * TROWS);
  const atlasUV = TSL.vec2(tileA.mod(TCOLS).mul(tw).add(eu).add(f.x.mul(tw - 2 * eu)),
    TSL.float(1).sub(tileA.div(TCOLS).floor().add(1).mul(th)).add(ev).add(f.y.mul(th - 2 * ev)));
  const sample = TSL.texture(atlasTex, atlasUV), shade = TSL.attribute("color", "vec3");
  matPieces = new THREE.MeshStandardNodeMaterial({ roughness: 0.85, metalness: 0 });
  matPieces.colorNode = sample.rgb.mul(shade);
  matGlassy = new THREE.MeshStandardNodeMaterial({ roughness: 0.1, metalness: 0, transparent: true, depthWrite: false });
  matGlassy.colorNode = sample.rgb.mul(shade);
  matGlassy.opacityNode = sample.a;
  ghost = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), new THREE.LineBasicMaterial({ color: 0x33dd77 }));
  ghost.visible = false;
  scene.add(ghost);
  highlight = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1.02, 1.02, 1.02)), new THREE.LineBasicMaterial({ color: 0x111111 }));
  scene.add(highlight);
  addEventListener("resize", () => { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); });
  pipeline = buildPipeline();
  startWorkers();
  wireInput(canvas);
  hotbar();
  updateChunks(); buildFar();
  setInterval(slow, 250);
  renderer.setAnimationLoop(frame);
  connect();
  $("loading").classList.add("hidden");
  try { await dapp.init(); } catch (e) { alertBar(T("cryptoFail", "The wallet bundle failed to load — reload to sign in.")); return; }
  wireWallet(dapp, () => { renderWallet(dapp); refreshTitles(); });
  renderWallet(dapp);
  refreshTitles();
  setInterval(refreshTitles, 30000);
}
dapp.onReturn((pend, ok, err, err2) => {
  dapp.showReturn(pend, ok, err, { anchor: T("anchorSent", "Anchoring — confirming…"), allow: T("inviteSent", "Invitation sent — confirming…") });
  refreshTitles();
});
start().catch((e) => {
  $("loading").textContent = T("noGpu", "This browser cannot draw the planet ({e}). Try a current Chrome, Edge, Firefox or Safari.", { e: String(e && e.message || e) });
});
