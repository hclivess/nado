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
import { walk, trunkAt, TRUNK_R, restorePlace } from "./land-walk.js";
import { snapBox, piecesFor, restOnGround } from "./land-snap.js";
import { levelOps, earthNeeded, trunkIn, siteLayer, topFirst } from "./land-level.js";
import { groundWeights } from "./land-mesher.js";
import { craftStep, flightOf, craftBody, bodyInside } from "./land-flight.js";
import { GFX_PRESETS, BENCH_ORDER, benchTarget, frameStats, holds, pickPreset, LADDER, governor, govStep } from "./land-gfx.js";
import { NadoDapp, wireWallet, renderWallet, alertBar, notify, uiConfirm, uiPrompt, isAddress, esc, base, disp, rawToNado, nadoToRaw, randId, $ } from "./nadodapp.js";

const CID = "e7dfe9aa3cbb4b0c9293caeaf992a041";      // the land title contract (deployed 2026-11-07, scripts/land_first_wave.py); redeploy.py wire() repoints it
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
const inv = { items: {}, tools: [], stations: [], worn: {}, look: { skin: 0, hair: 0 } };
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
let piece = { w: 100, d: 100, h: 100, snap: 10, shape: 0, rot: 0, tilt: [0, 0, 0] };   // shape: 0 box, 1 slope, 2 stairs (G cycles; T turns); tilt: yaw, pitch, roll in tenths of a degree (#169)
const plotBoxes = new Map();          // plot -> { list, idx: Map(1 m bucket -> [box]) }
let pipeline = null;                  // the post-processed render (or null: the plain render on a weak device)
let renderer, scene, camera, sun, hemi, atlasTex, matSolid, matClear, matGround, matTrees, matPieces, matGlassy, matBark, matLeaves, matWater, matFlame, ghost, farMesh = null, farAt = null;
// A PHONE ("very laggy on a phone", operator 2026-11-08) is known from the start — before the renderer is made — so
// what it costs is set for it: 1.25 pixels per CSS pixel (not 2: ~2.6x fewer to shade), 4 chunks of full view (the far
// land still draws to the horizon), two point lights, no shadows unless asked for (/set shadows 1), and full tree
// models in the nearest ring only. Measured as a phone in the town: tests/test_land_is_light_enough_for_a_phone.mjs.
const PHONE = "ontouchstart" in window || navigator.maxTouchPoints > 0;
let highlight, lastT = 0, locked = false, keys = new Set(), touch = null, viewDist = PHONE ? 4 : 6;
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
  37: ["#7d7570", 0.14, "ore"], 38: ["#6e4a2c", 0.06, "door"], 39: ["#7a5534", 0.08, "beam"], 40: ["#c9a95a", 0.14, "thatch"],
  41: ["#5a3a22", 0.06, "door"], 42: ["#2b2b2d", 0.18, "coal"], 43: ["#7d7570", 0.14, "copper"], 44: ["#7d7570", 0.14, "tin"],
  45: ["#a5765a", 0.1], 46: ["#7d7570", 0.14, "silver"], 47: ["#7d7570", 0.14, "gold"],
  48: ["#9aa3ad", 0.05, "steel"], 49: ["#3b3f45", 0.08, "thruster"], 50: ["#4a5058", 0.06, "seat"],
  51: ["#5a5f66", 0.08, "smelter"], 52: ["#5f6670", 0.06, "assembler"], 53: ["#4d5a4f", 0.06, "generator"],
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
      if (kind === "door" && (x === 0 || x === TILE - 1 || y === 0 || y === TILE - 1 || x % 5 === 0)) k *= 0.7;
      if (kind === "door" && x === TILE - 4 && y === 8) k = 2.2;                 // the handle
      if (kind === "beam" && y % 5 === 2) k *= 0.82;
      if (kind === "thatch" && (x * 3 + y) % 4 === 0) k *= 0.75;
      if (kind === "steel" && (x === 0 || y === 0 || x === TILE - 1 || y === TILE - 1)) k *= 0.72;         // a panel's seams
      if (kind === "steel" && (x === 2 || x === TILE - 3) && (y === 2 || y === TILE - 3)) k = 1.35;        // its rivets
      let col = c.clone().multiplyScalar(k);
      if (kind === "grassSide" && y < 4 + (rnd() < 0.4 ? 1 : 0)) col = new THREE.Color("#5f9e3a").multiplyScalar(k);
      if (kind === "snowSide" && y < 4 + (rnd() < 0.4 ? 1 : 0)) col = new THREE.Color("#f2f6f8").multiplyScalar(k);
      if (kind === "ore" && (x * 5 + y * 7) % 9 < 2) col = new THREE.Color("#9a5a32").multiplyScalar(k);   // rusty specks
      if (kind === "coal" && (x * 3 + y * 5) % 7 < 1) col = new THREE.Color("#55555c").multiplyScalar(k);    // a dull glint
      if (kind === "copper" && (x * 5 + y * 3) % 8 < 2) col = new THREE.Color("#3f9a7a").multiplyScalar(k);  // verdigris
      if (kind === "tin" && (x * 7 + y * 2) % 9 < 2) col = new THREE.Color("#c9ccd2").multiplyScalar(k);     // pale metal
      if (kind === "silver" && (x * 3 + y * 7) % 8 < 2) col = new THREE.Color("#e4e8ee").multiplyScalar(k);  // bright metal
      if (kind === "gold" && (x * 5 + y * 2) % 8 < 2) col = new THREE.Color("#e8c547").multiplyScalar(k);    // gold flecks
      if (kind === "thruster" && Math.hypot(x - 7.5, y - 7.5) < 4.5) col = new THREE.Color("#ff8a3a").multiplyScalar(k * (1.3 - Math.hypot(x - 7.5, y - 7.5) / 7));   // the nozzle's glow
      if (kind === "seat" && y < 7 && x > 2 && x < 13) col = new THREE.Color("#6fd3e8").multiplyScalar(k * 0.9);             // the canopy glass
      if (kind === "smelter" && y > 8 && y < 13 && x > 4 && x < 11) col = new THREE.Color("#ff7a2a").multiplyScalar(k * 1.2);   // its mouth, glowing
      if (kind === "assembler" && (x === 7 || y === 7)) col = new THREE.Color("#e8c547").multiplyScalar(k);                   // a hazard cross
      if (kind === "generator" && Math.hypot(x - 7.5, y - 7.5) < 3) col = new THREE.Color("#6fe39a").multiplyScalar(k * 1.1);  // a green lamp
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
  if (h < Wd.DEEP_MIN) return B.bedrock;                 // THE DEEP (#129) is ground down to DEEP_MIN
  if (h >= H) return B.air;
  const w = Wd.wrap(f, u, v), e = edits.get(key(w.face, w.u, w.v, h));
  return e !== undefined ? e : Wd.terrainBlock(w.face, w.u, w.v, h, colAt);
}
// THE SMOOTH GROUND, as the player touches it: land-world.fieldOf at cell centres, interpolated — the same field the mesher
// draws (static/land-mesher.js nets), so the foot lands where the surface is drawn, not on a hidden cube. What people
// build stays a crisp cell, and a log is a solid cell inside its round trunk; leaves can be walked through.
const crispB = (b) => b !== B.air && !Wd.NATURAL.has(b) && !Wd.isTree(b) && !BLOCKS[b].liquid;
function fieldCell(f, u, v, h) {
  if (h < Wd.DEEP_MIN) return 1;
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
  for (const b0 of list) { const a = Wd.boxAabb(b0), b = b0;            // a turned piece (#169): every bucket it reaches
   for (let i = Math.floor(a[0] / Wd.CM); i <= Math.floor((a[0] + a[3] - 1) / Wd.CM); i++)
    for (let j = Math.floor(a[1] / Wd.CM); j <= Math.floor((a[1] + a[4] - 1) / Wd.CM); j++)
      for (let k = Math.floor(a[2] / Wd.CM); k <= Math.floor((a[2] + a[5] - 1) / Wd.CM); k++) {
        const key = bkey(i, j, k); let l = idx.get(key); if (!l) idx.set(key, l = []); l.push(b);
      }
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
    if (Wd.inPiece(b, c.x, c.z, c.y)) return { plot: c.plot, b };      // a slope is solid below its sloped face
  return null;
}
function setPlotBoxes(plot, list) {
  const old = plotBoxes.get(plot);
  plotBoxes.set(plot, { list, idx: indexBoxes(list) }); topSeq++;
  const ys = [...list, ...(old ? old.list : [])];
  const ab = ys.map((b) => Wd.boxAabb(b));                    // a turned piece reaches higher and lower than its box (#169)
  if (ys.length) remeshPlotRange(plot, Math.min(...ab.map((b) => b[2])), Math.max(...ab.map((b) => b[2] + b[5])));
}
// THE HIGHEST THING ON A PLOT (#171): a craft's body is hundreds of points, swept in 15 cm moves — near things that is
// the price of not flying through them, but in the open sky it is all air. A craft whose lowest reach is over the top of
// every plot it spans skips them: the top is the plot's highest ground + TREE_TOP, its highest placed block, its highest
// piece. Kept until something is added (topSeq); a removal only leaves the top too high, which costs checks, never a miss.
let topSeq = 0;
const plotTops = new Map(), TREE_TOP = 40;
function plotTop(plot) {
  const c = plotTops.get(plot);
  if (c && c.seq === topSeq) return c.top;
  const q = Wd.plotCoords(plot);
  let top = -Infinity;
  for (let i = 0; i <= Wd.PLOT; i += 2) for (let j = 0; j <= Wd.PLOT; j += 2)
    top = Math.max(top, colAt(q.face, Math.min(W - 1, q.u0 + i), Math.min(W - 1, q.v0 + j)).height + TREE_TOP);
  for (const lk of (plotEdit.get(plot) || new Map()).keys()) top = Math.max(top, Number(lk.split(":")[2]) + 1);
  for (const b of (plotBoxes.get(plot) || { list: [] }).list) { const a = Wd.boxAabb(b); top = Math.max(top, (a[2] + a[5]) / Wd.CM); }
  plotTops.set(plot, { seq: topSeq, top });
  return top;
}
/** The ground under a craft's seat (#171): the ground itself, never the top of something built — that is its body's to
 *  meet. groundAt rises out of whatever the point is buried in, so a seat that came to a wall was put on top of it and the
 *  craft hopped over the wall (the page walk, 2026-11-10). Lower than the untouched planet (a pit, the levelled town) is
 *  still the ground. */
function craftGround(f, u, v) {
  const g = groundAt(f, u, v), plain = colAt(f, Math.floor(u), Math.floor(v)).height + 0.05;
  return g > plain + 0.5 ? plain : g;
}
/** Which of the craft's body points are inside something at pose (bodyInside) — only over a plot something reaches up to. */
function craftHits(c, pose) {
  const [f, u, v, h] = pose, low = h + c.bodyLow, r = c.bodyR;
  for (const du of [-r, r]) for (const dv of [-r, r]) {
    const pu = Math.max(0, Math.min(W - 1, Math.floor(u + du))), pv = Math.max(0, Math.min(W - 1, Math.floor(v + dv)));
    if (plotTop(Wd.plotOf(f, pu, pv)) >= low) return bodyInside(c.body, pose, craftSolid);
  }
  return [];
}
/** solidAt for a craft's body (#171): hundreds of points a step, most of them in open air — a point well over the smooth
 *  ground with no block or piece there is air without the ground field's eight-cell sum. */
function craftSolid(f, u, v, h) {
  if (boxAt(f, u, v, h)) return true;
  const cu = Math.floor(u), cv = Math.floor(v), b = blockAt(f, cu, cv, Math.floor(h));
  if (crispB(b)) return BLOCKS[b].solid;
  if (b === B.air && h > colAt(f, cu, cv).height + 2) return false;
  if (b === B.air && edits.get(key(f, cu, cv, Math.floor(h))) === B.air) return false;   // dug out (solidAt)
  // the smooth ground holds a point only when it is still ground 30 cm over it: a craft resting on the ground, its belly
  // in the turf's rounding, is on it, not in it (it hovered 10 cm up and never landed); a hillside ahead still stops it
  return fieldAt(f, u, v, h + 0.3) > 0;
}
function solidAt(f, u, v, h) {
  if (boxAt(f, u, v, h)) return true;
  const cu = Math.floor(u), cv = Math.floor(v), ch = Math.floor(h), b = blockAt(f, cu, cv, ch);
  if (crispB(b)) return BLOCKS[b].solid;
  // A DUG CELL IS OPEN: the smooth surface rounds into a narrow hole, so a body 60 cm wide hung inside a 1 m shaft and
  // could not climb down it to the ore it was dug for (the agent's first mine, 2026-11-09). A cell someone dug out is
  // air all through; untouched ground keeps its smooth surface (a slope stays a slope underfoot).
  if (b === B.air && edits.get(key(f, cu, cv, ch)) === B.air) return false;
  return fieldAt(f, u, v, h) > 0;
}

// ---- camera frame -----------------------------------------------------------------------------------------------
function look() {
  const fr = Wd.frameOf(P.face, P.u, P.v), cp = Math.cos(P.pitch), sy = Math.sin(P.yaw), cy = Math.cos(P.yaw);
  const fw = [0, 1, 2].map((i) => cp * (sy * fr.east[i] + cy * fr.north[i]) + Math.sin(P.pitch) * fr.up[i]);
  return { fr, fw };
}
/** World position (metres, doubles) of the eye. */
function eyePos() {
  const e = Wd.posOf(P.face, P.u, P.v, (P.eyeH === undefined ? P.h : P.eyeH) + EYE);   // land-walk.js smooths eyeH
  if (!flying) return e;
  // THE CHASE VIEW: flying, the camera hangs behind and above the craft, looking where the pilot looks — from the seat
  // the craft was under the camera and never seen (the first flight, 2026-11-09)
  const { fr, fw } = look();
  return [0, 1, 2].map((i) => e[i] - fw[i] * CHASE_BACK + fr.up[i] * CHASE_UP);
}
const CHASE_BACK = 9, CHASE_UP = 2.5;
const LITTER_H = 0.45, LITTER_R = 0.42;                // m: how high and how far round its middle litter catches the look                    // m behind (along the look) and above the pilot's eye

// ---- movement (grid space: u ~ east, v ~ north, h ~ up, ~1 m per unit) ------------------------------------------------
function collides(u, v, h) {
  for (const du of [-HALF, HALF]) for (const dv of [-HALF, HALF]) for (const dh of [0.01, 0.9, TALL - 0.01])
    if (solidAt(P.face, u + du, v + dv, h + dh)) return true;
  return trunkAt(u, v, h, HALF, TALL, isLog);
}
/** Cell [u, v, h] overlaps the player's body. */
const inBody = ([cu, cv, ch]) => cu + 1 > P.u - HALF && cu < P.u + HALF && cv + 1 > P.v - HALF && cv < P.v + HALF && ch + 1 > P.h && ch < P.h + TALL;
/** A block may go into this cell now: anywhere outside the body; inside it only at the feet — a cell starting below
 *  FEET above the soles: standing on smooth ground the soles are partway up the turf's cell, so the empty cell above it
 *  starts at the shins (the first walk, 2026-11-08, found it refused) — where the player is lifted to stand on it, and
 *  only with room for them there. Never into the player ("sadly it is possible to build oneself into the terrain",
 *  operator 2026-11-06), and never refused with a message either ("only hinders", 2026-11-08). */
const FEET = 0.75;
const roomFor = (c) => !inBody(c) || (c[2] < P.h + FEET && !collides(P.u, P.v, c[2] + 1));
/** A plant in hand (a sapling, a wild flower) goes only where earth or grass is under it — the world server's rule
 *  ("a plant is planted in earth or grass"); the outline showed a daisy green floating over another flower, and the
 *  tap did nothing (planting by the town pavilion, 2026-11-08). Anything else goes anywhere. */
const rootsIn = ([cu, cv, ch]) => {
  const held = RULES && RULES.items[hot[slot]] && RULES.items[hot[slot]].places;
  if (held === B.wheatyoung) return blockAt(P.face, cu, cv, ch - 1) === B.farmland;   // seed is sown on a field (#154)
  if (held !== B.sapling && !Wd.FLOWERS.includes(held)) return true;
  const below = blockAt(P.face, cu, cv, ch - 1);
  return below === B.grass || below === B.dirt;
};
// trunks are solid cylinders (land-walk.js trunkAt); leaves stay walk-through
const isLog = (cu, cv, ch) => Wd.TREE_WOOD.has(blockAt(P.face, cu, cv, ch));
const CLIMB = 1.8;                               // m/s up or down a ladder
/** A ladder within reach of the body: its box, grown by 45 cm around and reaching from 1.5 m below its foot to its top. */
function ladderNear() {
  const c = plotCm(P.face, P.u, P.v, P.h), rec = plotBoxes.get(c.plot);
  if (!rec) return null;
  for (const b of rec.list) if (b[6] === B.ladder && c.x > b[0] - 45 && c.x < b[0] + b[3] + 45 && c.z > b[1] - 45 && c.z < b[1] + b[4] + 45
    && c.y > b[2] - 150 && c.y < b[2] + b[5]) return b;
  return null;
}
let pillar = null;                                   // a block to put under the player once their feet clear its cell
function pillarTick() {
  if (!pillar) return;
  const [u, v, h] = pillar.cell;
  if (!P.ground) pillar.air = true;
  // it waits for this jump only: moved off the column, it is forgotten
  if (Math.floor(P.u) !== u || Math.floor(P.v) !== v) { pillar = null; return; }
  if (P.h >= h + 1) { const c = pillar; pillar = null; setBlock(P.face, u, v, h, c.b); return; }
  // landed before the feet cleared it: it goes in as a block placed at the feet does, under them, lifting them onto it.
  // The body keeps real time (frame), so on a slow device a whole jump can pass between two frames and the tap arrive
  // on the way down — it was dropped then, and nothing was placed (the 0.7 fps walk, 2026-11-08)
  if (P.ground && pillar.air) {
    const c = pillar; pillar = null;
    if (roomFor(c.cell) && setBlock(P.face, u, v, h, c.b)) { P.h = h + 1; P.vh = 0; }
  }
}
function step(dt) {
  pillarTick();
  const fwd = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0) + (touch ? touch.my : 0);
  const side = (keys.has("KeyD") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("KeyA") || keys.has("ArrowLeft") ? 1 : 0) + (touch ? touch.mx : 0);
  if (flying) return flyStep(dt, fwd, side);                // at the controls of a craft: it moves, the pilot rides
  const fast = keys.has("ShiftLeft") || keys.has("ShiftRight");
  const sp = P.fly ? (fast ? FLY_FAST : FLY) : (fast ? RUN : WALK);
  const sy = Math.sin(P.yaw), cy = Math.cos(P.yaw);
  const wu = (sy * fwd + cy * side) * sp, wv = (cy * fwd - sy * side) * sp;
  if (P.fly) P.vh = ((keys.has("Space") || (touch && touch.up) ? 1 : 0) - (keys.has("KeyC") || keys.has("ControlLeft") || (touch && touch.down) ? 1 : 0)) * sp;
  // the body's motion, climbing and descending slopes exactly (land-walk.js: the 5 cm notches it replaced made every
  // other uphill frame "airborne" and stopped the walk — the jitter-jumping of 2026-11-06)
  // A LADDER (#114): standing at one, forward or Space climbs, back goes down, nothing holds you there; gravity is off
  // while you are on it (land-walk.js climb) and comes back the moment you leave its reach (stepping off at the top)
  const lad = !P.fly && ladderNear();
  P.climb = !!lad;
  if (lad) {
    const up = fwd > 0 || keys.has("Space") || !!(touch && touch.up), down = fwd < 0 || keys.has("KeyC");
    P.vh = up ? CLIMB : down && !P.ground ? -CLIMB : 0;
  }
  walk(P, [wu, wv], keys.has("Space") || !!(touch && touch.up), dt, collides, { GRAV, JUMP, STEP });
  // fell out of the world: only below the deep (#129) — it was "below layer 1", which threw a miner back to the surface
  if (P.h < Wd.DEEP_MIN + 1) { P.h = groundAt(P.face, P.u, P.v); P.vh = 0; }
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

// ---- FLIGHT (#147, doc/land-tech-to-flight.md; "you must add actual physics like engines and gravity to the game and build
// a real usable xfighter", operator 2026-11-09). Use (Q, or the Use button) on a pilot seat: the pieces touching it become
// a craft (the world server lifts them off the plot, scripts/land_server.py board). The pilot flies it here —
// land-flight.js craftStep: its thrusters against its weight, gravity, drag, the ground — steering where they look: the
// stick / W A S D push along the facing, Jump climbs, Down sinks; the page tells the server where it is five times a
// second, and the server bounds that by the craft's top speed. Use again leaves it parked; /dock sets it down as pieces.
const FLIGHT = () => RULES.flight;
const crafts = new Map();               // id -> { pieces, pose, owner, pilot, mass, thrust, mesh }: crafts near, as sent
let flying = null;                      // the craft this player flies: { id, pose, vel, mass, thrust, bottom, grounded }
let flySent = 0, lastCraft = null;
const PILOT_SIT = 0.6;                  // m the pilot's feet sit below the seat's bottom, so the eye is ~1 m over it
function flyStep(dt, fwd, side) {
  const c = flying, F = FLIGHT();
  craftStep(c, { fwd, side, yaw: P.yaw, up: keys.has("Space") || !!(touch && touch.up), down: keys.has("KeyC") || keys.has("ControlLeft") || !!(touch && touch.down) },
    dt, F, (u, v) => craftGround(c.pose[0], u, v) - 0.05, (pose) => craftHits(c, pose));
  // the craft stays on its face of the planet (crossing an edge flying is for later)
  c.pose[1] = Math.max(1, Math.min(W - 1, c.pose[1])); c.pose[2] = Math.max(1, Math.min(W - 1, c.pose[2]));
  P.face = c.pose[0]; P.u = c.pose[1]; P.v = c.pose[2]; P.h = c.pose[3] - PILOT_SIT; P.vu = P.vv = P.vh = 0; P.ground = true;
  P.eyeH = P.h;                         // the walker smooths the eye's height (land-walk.js), and it does not walk now: the
                                        // camera stayed on the ground while the craft climbed out of view (first flight)
  const own = crafts.get(c.id); if (own) own.pose = c.pose;
  const now = performance.now();
  if (now - flySent > 200) {
    flySent = now;
    const e = c.engine || { throttle: 0, lift: 0, dir: [0, 0] };       // the engines' work, for everyone's exhaust (#171)
    net.send({ t: "fly", craft: c.id, pose: c.pose.map((x, i) => (i ? +x.toFixed(3) : x)), eng: [e.throttle, e.lift, e.dir[0], e.dir[1]].map((x) => +x.toFixed(2)) });
  }
}
/** A box geometry whose texture is tiled once per metre on every face (as the mesher tiles a piece) and white vertex
 *  colours (the piece materials multiply by them). w, h, d in metres. */
function pieceBox(w, h, d) {
  const g = new THREE.BoxGeometry(w, h, d), uv = g.attributes.uv;
  const size = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];          // BoxGeometry faces: +x -x +y -y +z -z
  for (let f = 0; f < 6; f++) for (let k = 0; k < 4; k++) { const i = f * 4 + k; uv.setXY(i, uv.getX(i) * size[f][0], uv.getY(i) * size[f][1]); }
  g.setAttribute("color", new THREE.Float32BufferAttribute(new Array(g.attributes.position.count * 3).fill(1), 3));
  return g;
}
/** A craft as drawn: its pieces in their materials, relative to the seat (x east, z north of a level craft facing north;
 *  local -Z is its nose, so the basis below stays right-handed). */
function craftMesh(pieces) {
  const g = new THREE.Group();
  for (const b of pieces) {
    const m = new THREE.Mesh(pieceBox(b[3] / Wd.CM, b[5] / Wd.CM, b[4] / Wd.CM), pieceMaterial(b[6]));
    m.position.set((b[0] + b[3] / 2) / Wd.CM, (b[2] + b[5] / 2) / Wd.CM, -(b[1] + b[4] / 2) / Wd.CM);
    if (Wd.isTurned(b)) m.quaternion.copy(turnQuat(b, (v) => [v[0], v[2], -v[1]]));   // the craft's frame: x east, y up, z south
    g.add(m);
    if (b[6] === B.thruster) {                    // its exhaust (#171): a cone from the thruster's underside, drawn per frame
      const pl = new THREE.Mesh(plumeGeo(), new THREE.MeshBasicMaterial({ color: 0xffb060, transparent: true, opacity: 0, depthWrite: false,
        blending: THREE.AdditiveBlending, side: THREE.DoubleSide }));
      pl.position.set((b[0] + b[3] / 2) / Wd.CM, b[2] / Wd.CM, -(b[1] + b[4] / 2) / Wd.CM);
      pl.visible = false; g.add(pl); (g.userData.plumes ||= []).push(pl);
    }
  }
  g.matrixAutoUpdate = false;
  return g;
}
/** Degrees (a number or text) to tenths of a degree in -1799..1800, the range a piece's turn is kept in. */
function tenths(x) {
  let t = Math.round((Number(x) || 0) * 10) % 3600;
  if (t > 1800) t -= 3600; if (t <= -1800) t += 3600;
  return t;
}
// ---- THE ENGINES' WORK, SEEN (#171; operator: "it should be visible that x is 'fighting gravity' and not just floating
// effortlessly"). From photographs of real jets (land research exhaust/OBSERVED.md): a hovering jet shows no flame by day —
// its work shows as a column of disturbed air and blown dust under it — and at night its engines glow orange. So: a plume
// at each thruster as long and bright as the thrust in use (land-flight.js engine: throttle, lift, push), pointing against
// the thrust (down for lift, back for push), faint by day and glowing at night; dust and haze on the ground under a low
// hover; a small tremble while it works.
let plumeG = null;
const plumeGeo = () => plumeG || (plumeG = new THREE.ConeGeometry(0.42, 1, 18, 1, true).rotateX(Math.PI).translate(0, -0.5, 0));   // base at 0, tip at -1
let dustTex = null;
function dustTexture() {
  if (dustTex) return dustTex;
  const cv = document.createElement("canvas"); cv.width = cv.height = 128;
  const x = cv.getContext("2d"), gr = x.createRadialGradient(64, 64, 6, 64, 64, 64);
  gr.addColorStop(0, "rgba(196,178,150,0.0)"); gr.addColorStop(0.35, "rgba(196,178,150,0.55)"); gr.addColorStop(0.7, "rgba(170,155,130,0.25)"); gr.addColorStop(1, "rgba(160,150,130,0)");
  x.fillStyle = gr; x.fillRect(0, 0, 128, 128);
  return (dustTex = new THREE.CanvasTexture(cv));
}
/** The engines' work of craft c this frame: { throttle, lift, push, dir } — the one I fly from my own step, the others'
 *  as their pilots said it (the world server relays it), or nothing when parked. */
function engineOf(id, c) {
  if (flying && flying.id === id && flying.engine) return flying.engine;
  if (!c.eng || !c.pilot) return null;
  return { throttle: c.eng[0], lift: c.eng[1], push: Math.max(0, c.eng[0] - c.eng[1]), dir: [c.eng[2], c.eng[3]] };
}
function engineFrame(id, c, cam, now) {
  const e = engineOf(id, c), thr = e ? e.throttle : 0, mesh = c.mesh;
  for (const pl of mesh.userData.plumes || []) {
    pl.visible = thr > 0.02;
    if (!pl.visible) continue;
    const yaw = c.pose[4], fwd = e.dir[0] * Math.sin(yaw) + e.dir[1] * Math.cos(yaw), right = e.dir[0] * Math.cos(yaw) - e.dir[1] * Math.sin(yaw);
    const ex = new THREE.Vector3(-e.push * right, -Math.max(e.lift, 0.05), e.push * fwd).normalize();   // against the thrust, in the craft's frame
    pl.quaternion.setFromUnitVectors(new THREE.Vector3(0, -1, 0), ex);
    const flick = 0.9 + 0.2 * Math.random();
    pl.scale.set(0.7 + 0.5 * thr, (0.3 + 3.2 * thr) * flick, 0.7 + 0.5 * thr);
    // by day a pale column of hot, shimmering air (the photos: no flame), by night the engines' orange glow
    pl.material.color.setRGB(0.85 + 0.15 * torchNight, 0.82 - 0.14 * torchNight, 0.76 - 0.4 * torchNight);
    pl.material.opacity = Math.min(0.85, thr * (0.42 + 0.45 * torchNight) * flick);
  }
  // a tremble while it works: a few centimetres, quicker than the eye follows
  if (thr > 0.02) {
    const fr = Wd.frameOf(c.pose[0], c.pose[1], c.pose[2]), a = 0.035 * thr * (Math.sin(now * 0.031) + 0.6 * Math.sin(now * 0.053));
    const el = mesh.matrix.elements; el[12] += fr.up[0] * a; el[13] += fr.up[1] * a; el[14] += fr.up[2] * a;
  }
  // dust and haze where its downwash meets the ground, under a low hover
  const g = groundAt(c.pose[0], c.pose[1], c.pose[2]), above = c.pose[3] - g;
  const k = e ? thr * Math.max(0, 1 - above / 16) : 0;
  if (!c.dust) {
    c.dust = new THREE.Mesh(new THREE.CircleGeometry(1, 40), new THREE.MeshBasicMaterial({ map: dustTexture(), transparent: true, depthWrite: false, opacity: 0 }));
    scene.add(c.dust);
  }
  c.dust.visible = k > 0.03;
  if (c.dust.visible) {
    const fr = Wd.frameOf(c.pose[0], c.pose[1], c.pose[2]), q = Wd.posOf(c.pose[0], c.pose[1], c.pose[2], g + 0.15);
    c.dust.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    c.dust.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...fr.up));
    c.dust.rotateZ(now * 0.0004);
    const r = 4 + 7 * thr; c.dust.scale.set(r, r, 1);
    c.dust.material.color.setScalar(1 - 0.8 * torchNight);   // dust is lit by the sky: unlit, it glowed like a floodlight at night
    c.dust.material.opacity = Math.min(0.85, 0.9 * k);
  }
}
/** The orientation of a turned piece (#169) in a frame whose axes `toFrame` maps [east, north, up] vectors into. */
function turnQuat(b, toFrame) {
  const r = Wd.rotOf(b), V = (a) => new THREE.Vector3(...toFrame(Wd.turnVec(r, a)));
  // the box's own axes turned: its width along east, its height along up, its depth along the frame's third axis
  const X = V([1, 0, 0]), Y = V([0, 0, 1]), Z = new THREE.Vector3().crossVectors(X, Y);
  return new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(X, Y, Z));
}
function craftPlace(mesh, pose, cam) {
  const [f, u, v, h, yaw] = pose, q = Wd.posOf(f, u, v, h), fr = Wd.frameOf(f, u, v);
  const V = (a) => new THREE.Vector3(a[0], a[1], a[2]);
  const E = V(fr.east), N = V(fr.north), U = V(fr.up);
  const fwd = N.clone().multiplyScalar(Math.cos(yaw)).add(E.clone().multiplyScalar(Math.sin(yaw)));
  const right = E.clone().multiplyScalar(Math.cos(yaw)).sub(N.clone().multiplyScalar(Math.sin(yaw)));
  mesh.matrix.makeBasis(right, U, fwd.negate()).setPosition(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
  mesh.matrixWorldNeedsUpdate = true;
}
function craftsSeen(list) {
  const seen = new Set();
  for (const o of list || []) {
    seen.add(o.id);
    let c = crafts.get(o.id);
    if (!c) { if (!o.pieces) continue; c = { pieces: o.pieces, mesh: craftMesh(o.pieces) }; scene.add(c.mesh); crafts.set(o.id, c); }
    Object.assign(c, { owner: o.owner, pilot: o.pilot, mass: o.mass, thrust: o.thrust, eng: o.eng || null });
    if (!(flying && flying.id === o.id)) c.pose = o.pose;        // the craft I fly goes where I fly it
  }
  for (const [id, c] of crafts) if (!seen.has(id) && !(flying && flying.id === id)) { scene.remove(c.mesh); if (c.dust) scene.remove(c.dust); crafts.delete(id); }
}
// the materials a craft is made of (land-world.js: steel plate, glass, thruster): Use on one of them may mean "fly this"
const CRAFT_SKIN = new Set([B.steelplate, B.glass, B.thruster]);
/** The pilot seat among the pieces touching piece b on its plot (and those touching them…, as the world server joins a
 *  craft: land_server.py connected, CRAFT_PAD 1 cm), or null. */
function craftSeat(plot, b) {
  const rec = plotBoxes.get(plot);
  if (!rec) return null;
  const grow = (p) => [p[0] - 1, p[1] - 1, p[2] - 1, p[3] + 2, p[4] + 2, p[5] + 2, ...p.slice(6)];
  const seen = new Set([b]), todo = [b];
  while (todo.length && seen.size <= 400) {
    const cur = todo.pop();
    if (cur[6] === B.pilotseat) return cur;
    const g = grow(cur), ab = Wd.boxAabb(g), near = new Set();      // its neighbours from the 1 m buckets it reaches
    for (let i = Math.floor(ab[0] / Wd.CM); i <= Math.floor((ab[0] + ab[3] - 1) / Wd.CM); i++)
      for (let j = Math.floor(ab[1] / Wd.CM); j <= Math.floor((ab[1] + ab[4] - 1) / Wd.CM); j++)
        for (let k = Math.floor(ab[2] / Wd.CM); k <= Math.floor((ab[2] + ab[5] - 1) / Wd.CM); k++)
          for (const o of rec.idx.get(bkey(i, j, k)) || []) near.add(o);
    for (const o of near) if (!seen.has(o) && Wd.boxesOverlap(g, o)) { seen.add(o); todo.push(o); }
  }
  return null;
}
/** Use on a pilot seat, or near your own parked craft: take the controls. */
function board(target) {
  if (!net.online || !net.me) return notify(T("signInFirst", "Sign in first."));
  net.send(Object.assign({ t: "board", req: ++net.req }, target));
}
function nearMyCraft() {
  let best = null, bd = 8;
  for (const [id, c] of crafts) {
    if (c.owner !== net.me || c.pilot || !c.pose || c.pose[0] !== P.face) continue;
    const d = Math.hypot(c.pose[1] - P.u, c.pose[2] - P.v, c.pose[3] - P.h);
    if (d < bd) { bd = d; best = id; }
  }
  return best;
}
function leaveCraft() {
  if (!flying) return;
  const c = flying; flying = null; lastCraft = c.id;
  net.send({ t: "fly", craft: c.id, pose: c.pose });
  net.send({ t: "leave", craft: c.id, req: ++net.req });
  const own = crafts.get(c.id); if (own) { own.pilot = null; own.pose = c.pose; }
  // step off beside the seat, onto the ground
  P.u = c.pose[1] + Math.cos(c.pose[4]) * 1.5; P.v = c.pose[2] - Math.sin(c.pose[4]) * 1.5; P.h = groundAt(P.face, P.u, P.v); P.vh = 0; P.eyeH = P.h;
  notify(T("fParked", "Parked. Use it again to fly; /dock sets it down here as pieces."));
  hud();
}
function startFlying(c) {
  const bottom = Math.min(0, ...c.pieces.map((b) => Wd.boxAabb(b)[2])) / Wd.CM;   // a turned piece: its lowest reach
  flying = { id: c.id, pose: c.pose.slice(), vel: [0, 0, 0], mass: c.mass, thrust: c.thrust, bottom, grounded: true,
    body: craftBody(c.pieces, Wd.boxAabb) };                              // what of it meets the world (#171)
  flying.bodyLow = Math.min(0, ...flying.body.map((p) => p[2]));
  flying.bodyR = Math.max(1, ...flying.body.map((p) => Math.hypot(p[0], p[1])));
  P.yaw = c.pose[4]; P.fly = false;
  const k = crafts.get(c.id) || { pieces: c.pieces, mesh: craftMesh(c.pieces) };
  if (!crafts.has(c.id)) { scene.add(k.mesh); crafts.set(c.id, k); }
  Object.assign(k, { owner: c.owner, pilot: c.pilot, mass: c.mass, thrust: c.thrust, pose: flying.pose });
  const f = flightOf(FLIGHT(), c.mass, c.thrust);
  notify(f.lifts ? T("fBoard", "At the controls — look to steer, stick/W A S D to push, Jump to climb, Down to sink, Use to leave.")
    : T("fHeavy", "Too heavy to lift: {t} kN of thrust against {w} kN of weight — add thrusters or make it lighter.", { t: Math.round(c.thrust), w: Math.round(f.weight) }), 6000);
}

// ---- aiming: a march along the look direction --------------------------------------------------------------------
// It stops at the first crisp block, log or leaves cell, or at the smooth surface; there the target is the most solid
// natural cell around the hit point (so a click always takes a real cell out, never a sliver of air), and a block is
// placed in the cell the ray came through.
function aim() {
  const { fr, fw } = look();
  const d = [fr.east, fr.north, fr.up].map((ax) => fw[0] * ax[0] + fw[1] * ax[1] + fw[2] * ax[2]);   // in grid axes
  const o = [P.u, P.v, P.h + EYE], cellOf = (p) => p.map(Math.floor);
  let wet = null;                                          // the first water cell the ray crosses (a bucket scoops it)
  for (let t = 0; t <= REACH; t += 0.02) {
    const p = [o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t], c = cellOf(p);
    const bx = boxAt(P.face, p[0], p[1], p[2]);
    if (bx) return { box: bx, point: p, before: [p[0] - d[0] * 0.02, p[1] - d[1] * 0.02, p[2] - d[2] * 0.02], dir: d };
    if (Math.round(t / 0.02) % 3) continue;               // pieces need a 2 cm step; cells and the ground do not
    const b = blockAt(P.face, c[0], c[1], c[2]);
    if (!wet && BLOCKS[b].liquid) wet = c;
    let hit = null;
    // LITTER (a pebble, sticks, flax, a flower) is a small model on the ground, not a cube: it catches the look only near
    // it — low in its cell and near its middle. Caught anywhere in the cell, a pebble hid the chest standing behind it, so
    // a chest or a machine could not be opened from there (the factory walk, 2026-11-09)
    if (Wd.LITTER.has(b)) { if (p[2] - c[2] < LITTER_H && Math.hypot(p[0] - c[0] - 0.5, p[1] - c[1] - 0.5) < LITTER_R) hit = c; }
    else if (crispB(b) || Wd.isTree(b)) hit = c;
    // the foot of a trunk: the drawn trunk stands on the smooth surface, inside the grass cell below its first log, so a
    // ray at it reaches the ground cell first — and dug grass from under the tree ("it goes through it and digs grass")
    else if (Wd.TREE_WOOD.has(blockAt(P.face, c[0], c[1], c[2] + 1)) && Math.hypot(p[0] - c[0] - 0.5, p[1] - c[1] - 0.5) < TRUNK_R + 0.1) hit = [c[0], c[1], c[2] + 1];
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
      // the top layer first: snow or turf partly above the drawn surface is dug before the earth under it (land-level.js)
      hit = topFirst(hit, (c) => Wd.NATURAL.has(blockAt(P.face, c[0], c[1], c[2])), (c) => fieldCell(P.face, c[0], c[1], c[2]));
    }
    if (!hit) continue;
    return { hit, prev: placeCell(o, d, hit, p), point: p, dir: d, water: wet };
  }
  return null;
}
/** WHERE A BLOCK GOES: the empty cell right where the look meets the surface — just in front of the point hit — and a
 *  green outline shows it before the tap (frame). Into a dug hole that is the hole; against a wall, the cell before it;
 *  on a crisp block, the cell beyond the face you look at, as in every block game. ("filling back in dirt is very
 *  inaccurate, it is impossible to judge what will happen upon placing a block, sometimes it places it above at other
 *  times below, and sometimes both", operator 2026-11-08: it was the first empty cell met walking back along the ray in
 *  steps of 30 cm and more, which on smooth ground came out beside, above or below the aimed cell with the angle, and
 *  nothing drew it.) That cell holding something (turf standing above the drawn surface): the cell beyond the face of the
 *  aimed cell the look comes in through, then the cell right on top of it — never higher, or nowhere.
 *  It may be the player's own cell: looking down at your feet the block goes under you and lifts you onto it (act). */
function placeCell(o, d, hit, p) {
  // empty: air, water, or loose litter the block in hand takes the place of (land-world.js SWEPT; the world server picks
  // it up into the bag) — a flower, a pebble, flax no longer push a block up into the cell over them
  const held = RULES && RULES.items[hot[slot]] && RULES.items[hot[slot]].places;
  const free = (q) => {
    const b = blockAt(P.face, q[0], q[1], q[2]);
    return (b === B.air || BLOCKS[b].liquid || (Wd.SWEPT.has(b) && !!held && !Wd.SWEPT.has(held) && held !== B.sapling)) && !pieceIn(q);
  };
  const at = [p[0] - d[0] * 0.07, p[1] - d[1] * 0.07, p[2] - d[2] * 0.07].map(Math.floor);   // a march step back: air side
  if (free(at)) return at;
  const n = entryFace(o, d, hit), side = [hit[0] + n[0], hit[1] + n[1], hit[2] + n[2]];
  if (free(side)) return side;
  const top = [hit[0], hit[1], hit[2] + 1];                   // only ever the cell right on top: two up, a block floated
  return free(top) ? top : null;                              // over the flower between ("/aim", 2026-11-08)
}
/** A built piece reaches into cell [u, v, h]: it takes no block (the world server refuses one) — a daisy was planted inside
 *  the plank floor of the town pavilion, in the cell under its 10 cm edge (2026-11-08). */
function pieceIn([u, v, h]) {
  const plot = Wd.plotOf(P.face, u, v), rec = plotBoxes.get(plot);
  if (!rec || !rec.list.length) return false;
  const q = Wd.plotCoords(plot), cell = [(u - q.u0) * Wd.CM, (v - q.v0) * Wd.CM, h * Wd.CM, Wd.CM, Wd.CM, Wd.CM];
  return rec.list.some((o) => Wd.boxesOverlap(cell, o));
}
/** The face of cell c that a ray from o along d enters it through, as the step to the neighbour beyond it: the face whose
 *  plane the ray crosses last on its way in (the slab test). */
function entryFace(o, d, c) {
  let best = -Infinity, n = [0, 0, 1];
  for (let i = 0; i < 3; i++) {
    if (Math.abs(d[i]) < 1e-9) continue;
    const t = ((d[i] > 0 ? c[i] : c[i] + 1) - o[i]) / d[i];
    if (t > best) { best = t; n = [0, 0, 0]; n[i] = d[i] > 0 ? -1 : 1; }
  }
  return n;
}
/** The height a player stands at on (face, u, v): just above the smooth surface. */
function groundAt(f, u, v) {
  let h = Wd.column(f, Math.floor(u), Math.floor(v)).height + 0.05;
  if (collides(u, v, h)) { while (collides(u, v, h) && h < H) h += 0.25; return h; }   // buried: rise out of it
  // IN THE AIR: the untouched planet's height is not the ground where it was dug or levelled lower (the town; a pit) —
  // a piece put "on the ground" there floated up to a metre over it ("i place a block and it places above my head",
  // 2026-11-07). Fall to what is really under it (at most GROUND_FALL m), then find its surface to a centimetre.
  let lo = h;
  while (lo > h - GROUND_FALL && lo > Wd.DEEP_MIN + 1 && !collides(u, v, lo - 0.25)) lo -= 0.25;
  if (!collides(u, v, lo - 0.25)) return h;               // nothing under it within reach: keep the planet's height
  let a = lo - 0.25, b = lo;                                // a collides, b does not
  for (let n = 0; n < 6; n++) { const m = (a + b) / 2; if (collides(u, v, m)) a = m; else b = m; }
  return b;
}
const WELCOME_SEEN = "nado_land_welcome_seen";       // localStorage: this device has put the welcome card away (wireInput)
const GROUND_FALL = 64;                                 // metres a ground search falls before it gives up
const STEP_DT = 0.05, FRAME_MAX = 1.0;                  // seconds: one physics step at most; a frame's time at most (frame)

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
  edits.set(k, b); pe.set(lk, b); topSeq++;
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
  if (h >= 0 && !mayBuild(plot)) return explainNoBuild(plot);   // the deep (h < 0) is everyone's (#129)
  if (h < Wd.DEEP_MIN || h >= H) return false;
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
  try { localStorage.setItem(LS, JSON.stringify({ p: [P.face, P.u, P.v, P.h, P.yaw, P.pitch], at: Math.floor(Date.now() / 1000), hot, piece })); } catch (e) {}
}
/** The chosen piece size and snap, under the hotbar. */
function pieceInfo() {
  const id = hot[slot], el = $("pieceInfo");
  if (!el) return;
  const [w, d, h] = pieceDims();
  const shapeName = [T("shapeBox", "box"), T("shapeSlope", "slope"), T("shapeStairs", "stairs")][piece.shape || 0];
  const tl = piece.tilt || [0, 0, 0], tilted = tl.some((t) => t);
  el.textContent = id && RULES && !NATURAL_ITEMS.has(id) ? T("pieceInfo", "Piece {w} × {d} × {h} cm · snap {s} cm", { w, d, h, s: piece.snap }) + " · " + shapeName
    + (tilted ? " · " + T("tiltInfo", "tilt {y}° {p}° {r}°", { y: tl[0] / 10, p: tl[1] / 10, r: tl[2] / 10 }) : "") : "";
  save();
}
// A NEWCOMER ARRIVES BY THE TOWN HALL ("make people spawn by the town hall by default", operator 2026-11-07): on the
// street in front of its door (scripts/land_town.py: the hall in the quarter of plot (5000, 3440), door in the middle of
// its front wall facing the street), looking at it. /tp spawn goes there too.
const TOWN_HALL_PLOT = 40963440;
function takePlace(p) {
  if (!Array.isArray(p) || p.length < 5 || !p.slice(0, 5).every(Number.isFinite) || !(p[0] >= 0 && p[0] < 6)) return;
  const [f, u, v, h, yaw] = p;
  if (f === P.face && Math.hypot(u - P.u, v - P.v) < 1 && Math.abs(h - P.h) < 2) return;     // already there
  P.face = f; P.u = u; P.v = v; P.yaw = yaw; P.vu = P.vv = P.vh = 0;
  if (collides(u, v, h)) { P.h = groundAt(f, u, v); pendingPlace = [f, u, v, h, yaw, P.pitch]; } else P.h = h;
  save();
}
function townSpawn() {
  const q = Wd.plotCoords(TOWN_HALL_PLOT);
  return [q.face, q.u0 + 8.5, q.v0 + 1.5, 0];             // the door is 8.05-8.95 m in, the street 0-2 m; yaw 0 faces +v
}
function load() {
  let d = null;
  try { d = JSON.parse(localStorage.getItem(LS) || "null"); } catch (e) {}
  localPlace = d && Array.isArray(d.p) ? (Number.isFinite(d.at) ? d.at : Infinity) : 0;   // when this browser last saved a place
  if (d && Array.isArray(d.hot)) hot = d.hot.filter((x) => typeof x === "string").slice(0, 9);
  if (d && d.piece && [d.piece.w, d.piece.d, d.piece.h].every((x) => Number.isInteger(x) && x >= 1 && x <= Wd.PLOT_CM) && SNAPS.includes(d.piece.snap)) {
    piece = d.piece;
    if (!(Array.isArray(piece.tilt) && piece.tilt.length === 3 && piece.tilt.every((t) => Number.isInteger(t) && t > -1800 && t <= 1800))) piece.tilt = [0, 0, 0];
  }
  const at = d && restorePlace(d.p, W, (f, u, v, h) => { const pf = P.face; P.face = f; const c = collides(u, v, h); P.face = pf; return c; },
    (f, u, v) => colAt(f, Math.floor(u), Math.floor(v)).height, (f, u, v) => { const pf = P.face; P.face = f; const g = groundAt(f, u, v); P.face = pf; return g; });
  if (at) {
    [P.face, P.u, P.v, P.h, P.yaw, P.pitch] = at;
    // A PLACE UNDERGROUND (a mine, THE DEEP #129) is solid rock until its plot's edits arrive from the world server, so
    // restorePlace puts the player on the surface. Keep the saved place and take it back once that plot's edits show it
    // open (applyPlot) — reloading in your mine leaves you in your mine. Without the server, the surface stays.
    if (at[3] !== d.p[3]) pendingPlace = d.p.slice(0, 6);
    return;
  }
  [P.face, P.u, P.v, P.yaw] = townSpawn();
  P.h = groundAt(P.face, P.u, P.v);
}

// ---- chunks: a pool of mesher workers ---------------------------------------------------------------------------
const chunks = new Map();                      // "face:cu:cv:ch" -> { meshes: [], anchor, busy, dirty }
let pendingPlace = null, localPlace = 0;                       // a saved place underground, until its plot's edits arrive (load)
const workers = [], queue = [], inflight = new Map();
let reqId = 0;
function startWorkers() {
  const n = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 4) - 1));
  for (let i = 0; i < n; i++) {
    const w = new Worker("/static/land-mesher.js", { type: "module" });
    w.busy = false;
    w.onmessage = (e) => { w.busy = false; pt("mesh", () => done(e.data)); pump(); };
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
  c.lod = PHONE ? (dist <= 1 ? 1 : 2) : dist <= 2 ? 0 : dist <= 3 ? 1 : 2;   // 0: grass too (not on a phone); 2: far trees, small pieces skipped
  queue.push({ id: ++reqId, k, face, cu, cv, ch, edits: editsFor(face, cu, cv), boxes: pb ? pb.list : null, lod: c.lod, grass: !!SET.grass });   // no blades with grass off (a phone's default, #166)
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
    if (m.flames) { const me = new THREE.Mesh(geom(m.flames), matFlame); me.renderOrder = 2; c.meshes.push(me); }
    if (m.water) { const me = new THREE.Mesh(geom(m.water), matWater); me.renderOrder = 1; c.meshes.push(me); }
    if (m.pieces) {
      // one draw group per material (the mesher sorted them), each in its real texture where it has one
      const g = geom(m.pieces), mats = [];
      for (const [start, count, blk] of m.pieces.groups || []) { g.addGroup(start, count, mats.length); mats.push(pieceMaterial(blk)); }
      c.meshes.push(new THREE.Mesh(g, mats.length ? mats : matPieces));
    }
    if (m.glassy) { const me = new THREE.Mesh(geom(m.glassy), matGlassy); me.renderOrder = 1; c.meshes.push(me); }
    if (m.grass) c.meshes.push(...grassMeshes(m.grass));
    if (m.solid) c.meshes.push(new THREE.Mesh(geom(m.solid), matSolid));
    if (m.clear) { const me = new THREE.Mesh(geom(m.clear), matClear); me.renderOrder = 1; c.meshes.push(me); }
    for (const me of c.meshes) { me.castShadow = me.material !== matClear && me.material !== matWater && me.material !== matFlame && !me.isInstancedMesh; me.receiveShadow = me.material !== matFlame; scene.add(me); }
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
    if (Math.abs(dx) <= 2 && Math.abs(dy) <= 2) { lo = Math.min(lo, Math.max(Wd.DEEP_MIN / CHUNK, Math.floor(P.h / CHUNK) - 1)); hi = Math.max(hi, Math.min(H / CHUNK - 1, Math.floor(P.h / CHUNK) + 1)); }
    const pb = plotBoxes.get(Wd.plotId(face, cv, cu));
    if (pb && pb.list.length) for (const b of pb.list) { lo = Math.min(lo, Math.floor(b[2] / (CHUNK * Wd.CM))); hi = Math.max(hi, Math.min(H / CHUNK - 1, Math.floor((b[2] + b[5] - 1) / (CHUNK * Wd.CM)))); }
    const dd = Math.max(Math.abs(dx), Math.abs(dy)), lodNow = PHONE ? (dd <= 1 ? 1 : 2) : dd <= 2 ? 0 : dd <= 3 ? 1 : 2;
    for (let ch = lo; ch <= hi; ch++) {
      const k = face + ":" + cu + ":" + cv + ":" + ch, c = chunks.get(k);
      want.add(k);
      if (c && c.lod !== undefined && c.lod !== lodNow && (pb || c.lod < 2 || lodNow < 2)) request(k);   // grass (lod 0 and 1) and small pieces follow the player
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
// In the ground's own material ("did you fix the bland untextured marches?", operator 2026-11-06: it was flat vertex
// colour, a green that read as painted cardboard past the near land): every vertex carries the six texture weights the
// mesher gives the near ground, from the surface's block and slope, and the sea is the near water's own surface over
// the seabed instead of a blue tint on the ground. Both are tucked under the near chunks they overlap.
let farSea = null;
function buildFar() {
  const N = 72, STEP = 48, face = P.face;
  const fu = Math.round(P.u / STEP) * STEP, fv = Math.round(P.v / STEP) * STEP;
  const anchor = Wd.posOf(face, fu, fv, 0), fr = Wd.frameOf(face, fu, fv);
  const pos = [], sea = [], uvw = [], suvw = [], w1 = [], w2 = [], col = [], mats = [], idx = [];
  for (let j = 0; j <= N; j++) for (let i = 0; i <= N; i++) {
    const u = fu + (i - N / 2) * STEP, v = fv + (j - N / 2) * STEP;
    const w = Wd.wrap(face, Math.round(u), Math.round(v)), c = Wd.column(w.face, w.u, w.v);
    const near = Math.abs(i - N / 2) * STEP < viewDist * CHUNK && Math.abs(j - N / 2) * STEP < viewDist * CHUNK;
    const p = Wd.posOf(face, u, v, c.height - (near ? 6 : 0)), q = Wd.posOf(face, u, v, Wd.SEA + 0.88 - (near ? 6 : 0));
    pos.push(p[0] - anchor[0], p[1] - anchor[1], p[2] - anchor[2]);
    sea.push(q[0] - anchor[0], q[1] - anchor[1], q[2] - anchor[2]);
    uvw.push(((u % 4096) + 4096) % 4096, ((v % 4096) + 4096) % 4096, c.height);
    suvw.push(((u % 4096) + 4096) % 4096, ((v % 4096) + 4096) % 4096, Wd.SEA + 1);
    mats.push(Wd.terrainBlock(w.face, w.u, w.v, Math.max(1, c.top)));
    col.push(1, 1, 1);
  }
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) { const a = j * (N + 1) + i; idx.push(a, a + 1, a + N + 2, a, a + N + 2, a + N + 1); }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx); g.computeVertexNormals();
  // the weights need the slope, and rock's three-way projection a grid-space normal: the world normals in the frame here
  const nw = g.getAttribute("normal"), gn = [];
  for (let k = 0; k < nw.count; k++) {
    const x = nw.getX(k), y = nw.getY(k), z = nw.getZ(k);
    const ne = x * fr.east[0] + y * fr.east[1] + z * fr.east[2], nn = x * fr.north[0] + y * fr.north[1] + z * fr.north[2], nu = x * fr.up[0] + y * fr.up[1] + z * fr.up[2];
    gn.push(ne, nn, nu);
    const wt = groundWeights(mats[k], nu);
    w1.push(wt[0], wt[1], wt[2], wt[3]); w2.push(wt[4], wt[5]);
  }
  g.setAttribute("uvw", new THREE.Float32BufferAttribute(uvw, 3));
  g.setAttribute("gn", new THREE.Float32BufferAttribute(gn, 3));
  g.setAttribute("w1", new THREE.Float32BufferAttribute(w1, 4));
  g.setAttribute("w2", new THREE.Float32BufferAttribute(w2, 2));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  const gs = new THREE.BufferGeometry();
  gs.setAttribute("position", new THREE.Float32BufferAttribute(sea, 3));
  gs.setAttribute("uvw", new THREE.Float32BufferAttribute(suvw, 3));
  gs.setIndex(idx); gs.computeVertexNormals();
  for (const m of [farMesh, farSea]) if (m) { scene.remove(m); m.geometry.dispose(); }
  farMesh = new THREE.Mesh(g, matGround);
  farMesh.receiveShadow = true;
  farSea = new THREE.Mesh(gs, matWater);
  farSea.renderOrder = 1;
  farMesh.userData.anchor = farSea.userData.anchor = anchor;
  scene.add(farMesh, farSea);
  farAt = { face, u: fu, v: fv };
}

// ---- titles: who holds which plot (the exec node's asset table) -----------------------------------------------------
async function getJSON(path) { const r = await fetch(base() + path, { cache: "no-store" }); return r.json(); }
// A title's asset seed is ~3.6·10^23 (land.plot_seed: the LAND tag, the planet, the plot) and the exec API writes it as a
// JSON NUMBER, which JSON.parse rounds to a float — every title then decoded to no plot and the town read "Wilderness"
// (2026-11-07, the first wave just minted). Long numbers in a seed field are quoted before parsing, so they reach
// titleOf (BigInt) exact.
const exactSeeds = (txt) => JSON.parse(txt.replace(/("seed":\s*)(\d{16,})/g, '$1"$2"'));
async function getAssets(path) { const r = await fetch(base() + path, { cache: "no-store" }); return exactSeeds(await r.text()); }
async function refreshTitles() {
  try {
    const r = await getAssets("/exec/assets?issuer=" + ISSUER);
    for (const a of r.assets || []) {
      const tt = Wd.titleOf(a.seed);
      if (!tt || tt.planet !== Wd.PLANET) continue;      // another planet's title, or another asset of the issuer
      const plot = tt.plot;
      if (!titles.has(plot)) titles.set(plot, { aid: a.id, holder: null, asked: false });
      else { const t = titles.get(plot); t.asked = false; t.checked = false; }   // a title can change hands, an invitation
                                                          // come or go: ask again on the next look
    }
    mine.clear();
    const me = net.me || dapp.me;
    if (me) {
      const h = await getAssets("/exec/assets?holder=" + encodeURIComponent(me));
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
    const holder = Object.keys(hs).find((a) => Number(hs[a]) > 0) || null;
    // A TITLE ON SALE is held by the market contract that escrows it: the HUD said "Owned by b0162eda…" and nothing about
    // buying it (the first wave, 2026-11-07). A holder that is a contract (32 hex, not an address) is asked for the
    // listing that holds this title: if there is one, the plot is for sale at its price.
    // The holder and the sale change TOGETHER, once both are known: set one at a time, the HUD drawn while the listing
    // was still being read said "Owned by b0162eda…" again on every refresh, flickering with "For sale" (2026-11-08)
    let sale = null;
    if (holder && /^[0-9a-f]{32}$/.test(holder)) {
      const st = await listingsOf(holder), lid = Object.keys(st.l_asset || {}).find((k) => String(st.l_asset[k]) === String(t.aid) && Number((st.l_left || {})[k]) > 0);
      if (lid) sale = { price: BigInt((st.l_price || {})[lid] || 0), lid: Number(lid), seller: (st.l_seller || {})[lid] || null, market: holder };
    }
    t.holder = holder; t.sale = sale;
  } catch (e) {}
  return t.holder;
}
const listingCache = new Map();                      // contract -> { at, st }: one storage read a minute per market
async function listingsOf(cid) {
  const c = listingCache.get(cid);
  if (c && Date.now() - c.at < 60000) return c.st;
  const r = exactSeeds(await (await fetch(base() + "/exec/contract?cid=" + cid, { cache: "no-store" })).text());
  const st = r.storage || {};
  listingCache.set(cid, { at: Date.now(), st });
  return st;
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

// ---- selling a plot, from where you stand (#126, "users should be able to put up their land for sale in an automated
// process including the screenshot", operator 2026-11-07): one price, one wallet approval, and the title is listed on
// the NFT market — whose page shows the world server's photo of the plot and its facts (/land/api/card). Asking for the
// card here also puts the plot first in line for a new photo when its last one is out of date. Taking it off sale and
// changing the price are the market's own seller calls, offered here on the plot you have listed.
let marketCid = null;
async function market() {
  // the market's contract is the one its own page names (execnode/games/redeploy.py wires it there at every deploy):
  // read, never copied here, so a redeploy cannot leave this page listing on a dead contract
  if (!marketCid) {
    const m = (await (await fetch("/static/nft.js", { cache: "no-cache" })).text()).match(/^const CID = "([0-9a-f]{32})";/m);
    marketCid = m ? m[1] : null;
  }
  return marketCid;
}
async function askPrice(title, body, value) {
  const v = await uiPrompt({ title, body, value, placeholder: T("sellPrice", "Price in NADO"), confirmText: T("sellNext", "Next") });
  if (v == null || !String(v).trim()) return null;
  const raw = nadoToRaw(v);
  if (!raw) { alertBar(T("sellBad", "Enter a price above zero, in NADO.")); return null; }
  return raw;
}
async function sell(plot) {
  const t = titles.get(plot);
  if (!t || !mine.has(plot)) return explainNoBuild(plot);
  const cid = await market().catch(() => null);
  if (!cid) return alertBar(T("noMarket", "The market cannot be reached right now — try again in a minute."));
  let card = null;
  try { card = await (await fetch("/land/api/card?plot=" + plot, { cache: "no-store" })).json(); } catch (e) {}
  const price = await askPrice(T("sellTitle", "Sell plot {p}", { p: plotLabel(plot) }),
    T("sellBody", "Your price, in NADO. The market keeps the title until someone buys it or you take it off sale; the listing shows the plot's photo and its facts."));
  if (!price) return;
  const rows = [{ k: T("sellAsk", "Price"), v: rawToNado(price) + " NADO" }, { k: T("sellSize", "Size"), v: "16 × 16 m · 256 m²" }];
  if (card) rows.push({ k: T("sellPhoto", "Photo"), v: card.shot ? T("sellPhotoAt", "taken {d}", { d: new Date(card.shot_at * 1000).toLocaleString() }) : T("sellPhotoSoon", "being taken — it appears on the listing by itself") });
  if (!await uiConfirm({ title: T("sellConfirm", "List plot {p} for sale?", { p: plotLabel(plot) }), rows,
    body: T("sellRoyalty", "When it sells, the plot's creator receives its royalty and you receive the rest, in one step."),
    confirmText: T("sellGo", "List for sale") })) return;
  dapp.call("list", [randId(), BigInt(t.aid), price], 1n, T("selling", "Listing plot {p} for {n} NADO…", { p: plotLabel(plot), n: rawToNado(price) }),
    { phase: "list", plot }, { cid, asset: t.aid, confirm: true });
}
async function reprice(plot) {
  const t = titles.get(plot);
  if (!t || !t.sale || t.sale.seller !== (net.me || dapp.me)) return;
  const price = await askPrice(T("repriceTitle", "New price for plot {p}", { p: plotLabel(plot) }),
    T("repriceBody", "It stays on sale; only its price changes."), rawToNado(t.sale.price));
  if (!price) return;
  dapp.call("reprice", [t.sale.lid, price], null, T("repricing", "Repricing plot {p} to {n} NADO…", { p: plotLabel(plot), n: rawToNado(price) }),
    { phase: "reprice", plot }, { cid: t.sale.market, confirm: true });
}
async function unlist(plot) {
  const t = titles.get(plot);
  if (!t || !t.sale || t.sale.seller !== (net.me || dapp.me)) return;
  if (!await uiConfirm({ title: T("unlistTitle", "Take plot {p} off sale?", { p: plotLabel(plot) }),
    body: T("unlistBody", "The title comes back to your wallet."), confirmText: T("unlistGo", "Take off sale") })) return;
  dapp.call("unlist", [t.sale.lid], null, T("unlisting", "Taking plot {p} off sale…", { p: plotLabel(plot) }),
    { phase: "unlist", plot }, { cid: t.sale.market, confirm: true });
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
      // the world server keeps a signed-in player's last place: on this page's first connect, go back there — wherever
      // (on whichever device) they last played. A place underground waits for its plot's edits (pendingPlace).
      // …only if it is newer than this browser's own (a reload in the same browser keeps where you just were — the server
      // keeps a place at most every 10 s, and a reload went back up to 10 s of walking)
      if (!net.placed) { net.placed = true; if (m.pos && (m.pos_at || 0) > localPlace) takePlace(m.pos); }
      // reloaded mid-flight: back into the seat of the craft the world server still holds us as the pilot of (the craft
      // stayed in the air, out of reach — "on respawn i fell out of the x and cannot reenter it", 2026-11-10)
      if (m.flying && !flying) board({ craft: m.flying });
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
    } else if (m.t === "ignite") {
      if (m.error) notify(m.error);
    } else if (m.t === "chest") {
      if (chest && m.plot === chest.plot && String(m.box) === String(chest.box)) { chest.items = m.items || {}; renderChest(); }
      if (m.error) notify(m.error);
    } else if (m.t === "chat") {
      conLine(`<${String(m.who || "").slice(0, 10)}…> ${String(m.text || "")}`);
    } else if (m.t === "chat_ok" && m.error) {
      conLine(T("cSignIn", "Sign in to chat."), "err");
    } else if (m.t === "edit") {
      for (const [f, u, v, h, b] of m.cells || []) putCell(f, u, v, h, b);
    } else if (m.t === "revert") {
      for (const [f, u, v, h] of m.cells || []) dropCell(f, u, v, h);
    } else if (m.t === "inv") {
      if (invSeen) pickup(inv.items, m.items || {}, inv.tools, m.tools || [], inv.stations, m.stations || []);
      invSeen = true;
      // vol: what is left of blocks a piece was cut from (cm³) — sent all along and never kept, so the page counted only
      // whole blocks and refused a piece the leftover would pay for (2026-11-08)
      inv.items = m.items || {}; inv.tools = m.tools || []; inv.stations = m.stations || []; inv.vol = m.vol || {};
      inv.worn = m.worn || {}; inv.look = m.look || { skin: 0, hair: 0 };
      fedUntil = performance.now() + (m.fed || 0) * 1000;                     // a meal's time left (#155)
      inv.quests = m.quests || []; inv.level = m.level || 1; inv.xp = m.xp || 0;   // the quest log and level (#165)
      showHp(m.hp, m.hp_max);
      fillHot(); hotbar(); if (bagOpen()) renderBag(); if (!$("wardPanel").classList.contains("hidden")) renderWard();
    } else if (m.t === "offers") {
      offers = m.offers || []; if (bagOpen()) renderBag();
    } else if (m.t === "done") {
      if (m.error) notify(String(m.error));
      else if (m.op === "eat") notify(T("ate", "Well fed: work goes quicker for a while."));
      else if (m.op === "bed") notify(T("bedSet", "Your bed: you will wake here."));
    } else if (m.t === "set_ok") {
      const plot = net.pending.get(m.req); net.pending.delete(m.req);
      if (m.refused && m.refused.length) {
        notify(String(m.refused[0][1] || T("refused", "The world server refused that change.")));
        if (plot !== undefined) resync(plot);          // put back what the server actually holds
      }
    } else if (m.t === "players") {
      const seen = new Set();
      for (const o of m.list || []) {
        seen.add(o.id);
        let r = others.get(o.id);
        const sig = JSON.stringify(o.look || null);
        if (r && r.sig !== sig) { scene.remove(r.mesh); r = null; }      // they changed clothes: dress them again
        if (!r) { r = { mesh: avatar(o.who || o.id, o.look), who: o.who, sig }; scene.add(r.mesh); others.set(o.id, r); }
        r.p = o.p;
      }
      for (const [id, r] of others) if (!seen.has(id)) { scene.remove(r.mesh); others.delete(id); }
      craftsSeen(m.crafts);
      animalsSeen(m.animals);
      npcsSeen(m.npcs);
      dropsSeen(m.drops);
    } else if (m.t === "talk") {
      if (talkingTo && (!m.npc || m.npc === talkingTo)) renderNpc(m);
    } else if (m.t === "quest") {
      if (m.error) notify(m.error === "not done yet" ? T("qNotYet", "Not done yet") : m.error.startsWith("at most") ? T("qMax", "You hold as many quests as you can — finish or drop one.") : String(m.error));
      else if (m.op === "turnin") notify(T("qDone", "Done: +{x} experience.", { x: m.xp }) + (m.paid && Object.keys(m.paid).length ? " " + T("qPaid", "The town pays {p}.", { p: bagText(m.paid) }) : ""));
      else if (m.op === "accept") notify(T("qTaken", "Quest taken — see it in your bag."));
      if (talkingTo && m.op !== "drop") net.send({ t: "talk", npc: talkingTo, req: ++net.req });
    } else if (m.t === "hurt") {
      // struck (#162): the hearts drop and the screen flashes red
      showHp(m.hp); const f = $("hurtFlash"); f.classList.add("on"); setTimeout(() => f.classList.remove("on"), 120);
    } else if (m.t === "died") {
      died(m.by, m.bed);
    } else if (m.t === "pos_fix") {
      // TRAVEL (#167): the world server puts the player where it says — after /tp (the landing, or their bed), or back
      // where it last saw them when the page moved faster than anyone can go
      if (m.why === "nobed") { conLine(T("tpNoBed", "You have no bed yet — Use on a bed you built, and /tp bed takes you there."), "err"); return; }
      if (!Array.isArray(m.p) || flying) return;
      P.face = m.p[0]; P.u = m.p[1]; P.v = m.p[2];
      P.h = Number.isFinite(m.p[3]) ? m.p[3] : groundAt(P.face, P.u, P.v); P.vu = P.vv = P.vh = 0;
      save(); updateChunks();
      if (m.why === "tp") conLine(m.to === "bed" ? T("tpBed", "At your bed.") : T("tpSpawn", "At the landing."));
      else notify(T("tpPace", "Faster than anyone can go — back where the world last saw you."), 4000);
    } else if (m.t === "shoot" || m.t === "pickup") {
      if (m.t === "shoot" && m.flight) {
        // the server's arrow ended after `flight` seconds (in a body, or on the ground): the page's own arrow stops there
        const a = arrowsInFlight[arrowsInFlight.length - 1];
        if (a) a.until = Math.min(a.until, m.flight);
      }
      if (m.error && m.error !== "it is gone" && m.error !== "too far away" && m.error !== "too fast") notify(m.error === "no arrows" ? T("huntArrows", "No arrows — make some from sticks, stone and fiber.") : String(m.error));
      else if (m.t === "shoot" && !m.error) huntSaid(m);
    } else if (m.t === "hunt") {
      // the strike's answer: a miss the world server explains, a hit (it runs), or game for the bag
      if (m.error === "too far away") notify(T("huntFar", "Too far — get closer, or use a bow."));
      else if (m.error === "no arrows") notify(T("huntArrows", "No arrows — make some from sticks, stone and fiber."));
      else if (m.error === "hunting needs a spear or a bow") notify(T("huntNeeds", "Hunting needs a spear or a bow."));
      else if (m.error && m.error !== "too fast" && m.error !== "it is gone") notify(String(m.error));
      else huntSaid(m);
    } else if (m.t === "machine") {
      if (machine && m.plot === machine.plot) renderMachine(m);
    } else if (m.t === "craft_ok") {
      // FLIGHT: the world server's answer to board / leave / dock
      if (m.error) { notify(m.error, 5000); conLine(m.error, "err"); }
      else if (m.op === "board" && m.craft) startFlying(m.craft);
      else if (m.op === "dock") { notify(T("fDocked", "Set down as pieces.")); }
      else if (m.op === "handover") { const w = String(m.to || ""); conLine(T("fGave", "Given to {w}. It is theirs, and they are at its controls.", { w: w.slice(0, 6) + "…" + w.slice(-5) })); }
    } else if (m.t === "given") {
      // a craft handed to me (#171): mine now, and I am at its controls — wherever it is
      const w = String(m.by || "");
      notify(T("fGiven", "{w} gave you a craft — you are at its controls.", { w: w.slice(0, 6) + "…" + w.slice(-5) }), 6000);
      if (!flying) board({ craft: m.craft });
    } else if (m.t === "craft_fix") {
      // the server held the craft somewhere else (a claim faster than it flies): back to where it holds it
      if (flying && flying.id === m.craft) { flying.pose = m.pose.slice(); flying.vel = [0, 0, 0]; }
    }
  };
  ws.onclose = () => {
    const was = net.online;
    net.online = false; net.ws = null;
    for (const r of others.values()) scene.remove(r.mesh);
    others.clear();
    for (const r of animals.values()) scene.remove(r.mesh);
    animals.clear();
    for (const r of npcs.values()) scene.remove(r.mesh);
    npcs.clear();
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
  if (pendingPlace && Wd.plotOf(pendingPlace[0], Math.floor(pendingPlace[1]), Math.floor(pendingPlace[2])) === plot) {
    const [f, u, v, h, yaw, pitch] = pendingPlace, pf = P.face;
    pendingPlace = null;
    P.face = f;
    if (!collides(u, v, h)) { [P.u, P.v, P.h, P.yaw, P.pitch] = [u, v, h, yaw, Number.isFinite(pitch) ? pitch : P.pitch]; P.vh = 0; }
    else P.face = pf;
  }
  if (old) for (let ch = Wd.DEEP_MIN / CHUNK; ch < H / CHUNK; ch++) { const k = q.face + ":" + q.u0 / CHUNK + ":" + q.v0 / CHUNK + ":" + ch; if (chunks.has(k)) request(k); }
}
async function resync(plot) {
  try { const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin" })).json(); applyPlot(plot, r.edits || []); setPlotBoxes(plot, r.boxes || []); } catch (e) {}
}
// THE LOOK (#111, "the crafted items should be what changes how you look"): a body of boxes — legs, torso, arms, head,
// hair — in the player's chosen skin and hair, dressed in what they wear (scripts/land_server.py look_of). What is not
// covered shows a plain undershirt, tinted per player so two strangers are told apart, and dark breeches. Front is +Z
// (lookAt), so hair and a cloak hang at -Z.
const SKIN = [0xf1d2b6, 0xe0b48f, 0xc68c62, 0x9b6440, 0x6e4229, 0x4a2c1b];   // land_server.py LOOK_SKIN = 6
// hair: six natural, then six bright for a kawaii look — pink, sky, lilac, mint, silver-white, tangerine (#145)
const HAIR = [0x2a1d14, 0x5a3a22, 0x9c6b3a, 0xd9b26a, 0x8e2f1c, 0xb9b4ad,
  0xf28cb8, 0x5aa9e6, 0x9b7be0, 0x6fd3a0, 0xf4f1ea, 0xff7a3d];               // land_server.py LOOK_HAIR = 12
const BODIES = 2, FACES = 6;                                                     // land_server.py LOOK_BODY, LOOK_FACE
const WEAR = { linen_shirt: 0xe6dcc3, linen_trousers: 0xcabd98, linen_cap: 0xeee5cf, linen_cloak: 0xb9a57c };
const WEAR_SLOTS = ["head", "body", "legs", "back"];
function lookColours(seed, look) {
  let h = 0; for (const ch of String(seed)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  look = look || {}; const worn = look.worn || {};
  const under = new THREE.Color().setHSL((h % 360) / 360, 0.35, 0.42).getHex();
  return { skin: SKIN[look.skin] ?? SKIN[0], hair: HAIR[look.hair] ?? HAIR[0], top: WEAR[worn.body] ?? under,
           legs: WEAR[worn.legs] ?? 0x3b3f46, cap: WEAR[worn.head] ?? null, cloak: WEAR[worn.back] ?? null };
}
// BODY AND FACE (#145, "add kawaii faces and let users customize the basics like gender and face and hair color",
// operator 2026-11-09) — and NOT BLOCKS ("rework characters to not be fucking blocks", the same evening): a rounded chibi
// figure — a big round head with one of FACES drawn kawaii faces on its front (faceCanvas, on a cap of the sphere), a
// capsule body, rounded arms and legs with hands and shoes. Body type 0: a fringe of short hair; 1: longer hair, pigtails
// and a skirt. Clothes keep their colours (lookColours): a soft cap, a cloak that drapes behind. ~1.75 m, front +Z.
function avatar(seed, look) {
  const c = lookColours(seed, look), g = new THREE.Group(), girl = (look && look.body) === 1;
  const mat = (col) => new THREE.MeshLambertMaterial({ color: col });
  const put = (geo, col, x, y, z, rx = 0, rz = 0) => { const m = new THREE.Mesh(geo, typeof col === "number" ? mat(col) : col); m.position.set(x, y, z); m.rotation.set(rx, 0, rz); g.add(m); return m; };
  const capsule = (r, len) => new THREE.CapsuleGeometry(r, len, 4, 12);
  const sphere = (r, ...cut) => new THREE.SphereGeometry(r, 24, 16, ...cut);
  // legs and shoes
  for (const x of [-0.09, 0.09]) { put(capsule(0.075, 0.42), c.legs, x, 0.33, 0); put(sphere(0.085), 0x3a2e2a, x, 0.06, 0.03).scale.set(1, 0.6, 1.4); }
  if (girl) put(new THREE.CylinderGeometry(0.16, 0.29, 0.34, 20, 1, true), c.top, 0, 0.62, 0).material.side = THREE.DoubleSide;   // a skirt
  // the body, a little narrower for body type 1; arms hang slightly out, hands in skin
  put(capsule(girl ? 0.16 : 0.18, 0.34), c.top, 0, 0.92, 0).scale.set(1, 1, 0.82);
  for (const s of [-1, 1]) {
    const x = s * (girl ? 0.21 : 0.24);
    put(capsule(0.06, 0.34), c.top, x, 0.94, 0, 0, s * 0.12);
    put(sphere(0.065), c.skin, x + s * 0.03, 0.7, 0.01);
  }
  // the head: round and big, its face a cap of the sphere just over the skin (the drawn face is mirrored to read right)
  const R = 0.25, hy = 1.42;
  put(sphere(R), c.skin, 0, hy, 0);
  const tex = faceTexture((look && look.face) || 0);
  put(sphere(R + 0.003, Math.PI / 2 - 0.8, 1.6, 0.85, 1.25), new THREE.MeshLambertMaterial({ map: tex, transparent: true, depthWrite: false }), 0, hy, 0);
  // hair: a cap over the top and back, a fringe in front; for body type 1 longer at the back and two pigtails
  put(sphere(R + 0.03, 0, Math.PI * 2, 0, 1.0), c.hair, 0, hy, 0);                                   // the crown
  put(sphere(R + 0.03, Math.PI * 1.5 - 1.75, 3.5, 0.9, girl ? 1.75 : 1.15), c.hair, 0, hy, 0);       // sides and back
  put(sphere(R + 0.035, Math.PI / 2 - 0.85, 1.7, 0.55, 0.42), c.hair, 0, hy, 0);                      // a fringe
  if (girl) for (const s of [-1, 1]) {                                                                // two pigtails, hanging
    put(sphere(0.06), c.hair, s * 0.27, hy + 0.02, -0.02);
    put(capsule(0.065, 0.26), c.hair, s * 0.31, hy - 0.18, -0.03, 0, s * 0.22);
  }
  if (c.cap != null) put(sphere(R + 0.045, 0, Math.PI * 2, 0, 1.0), c.cap, 0, hy + 0.03, 0).scale.set(1.05, 0.8, 1.05);   // a soft cap
  if (c.cloak != null) {                                                                                                 // a cloak drapes behind
    const cl = put(new THREE.CylinderGeometry(0.24, 0.36, 0.95, 20, 1, true, Math.PI * 0.6, Math.PI * 0.8), c.cloak, 0, 0.78, 0);
    cl.material.side = THREE.DoubleSide;
  }
  return g;
}
// ---- ANIMALS (#156, "hunting", operator 2026-11-09): the world server keeps them near players (land_server.py herd) and
// sends where each is with the players near; the page draws each kind — a deer, a boar, a rabbit — glides it to where
// the server says, stands it on the drawn ground, and swings its legs while it moves. Break on one under the crosshair
// strikes it with a spear (close) or a bow (far, an arrow each). A STAG (antlers) charges a player who comes near, and
// any deer or boar struck fights back (#162: "add aggressive deer and death/respawn mechanism", operator 2026-11-09).
const animals = new Map();                        // id -> { kind, mesh, legs, u, v, h, yaw, cu, cv, cyaw, gh, moving }
const ANIMAL_LOOK = {
  deer: { body: 0x8a5a33, belly: 0xd9c3a0, len: 1.15, high: 0.85, girth: 0.32, head: 0.18, neck: 0.45 },
  boar: { body: 0x4b3b31, belly: 0x5e4c40, len: 0.95, high: 0.5, girth: 0.34, head: 0.22, neck: 0.12 },
  rabbit: { body: 0x9a8a78, belly: 0xe8e0d4, len: 0.3, high: 0.16, girth: 0.13, head: 0.1, neck: 0.06 },
};
function animalMesh(kind, angry) {
  const L = ANIMAL_LOOK[kind] || ANIMAL_LOOK.deer, g = new THREE.Group(), legs = [];
  const mat = (col) => new THREE.MeshLambertMaterial({ color: col });
  const put = (geo, col, x, y, z, parent = g) => { const m = new THREE.Mesh(geo, mat(col)); m.position.set(x, y, z); parent.add(m); return m; };
  const body = put(new THREE.SphereGeometry(1, 16, 10), L.body, 0, L.high + L.girth * 0.3, 0);
  body.scale.set(L.girth, L.girth * 1.05, L.len * 0.5);
  put(new THREE.SphereGeometry(1, 12, 8), L.belly, 0, L.high + L.girth * 0.05, 0).scale.set(L.girth * 0.85, L.girth * 0.7, L.len * 0.42);
  // the head on its neck, forward (+z) and up
  const hz = L.len * 0.5 + L.head * 0.4, hy = L.high + L.girth * 0.3 + L.neck;
  if (L.neck > 0.1) put(new THREE.CylinderGeometry(L.head * 0.45, L.girth * 0.5, L.neck * 1.15, 10), L.body, 0, L.high + L.girth * 0.3 + L.neck * 0.5, hz - L.head * 0.6).rotation.x = 0.45;
  const head = put(new THREE.SphereGeometry(L.head, 14, 10), L.body, 0, hy, hz);
  head.scale.set(0.85, 0.9, 1.35);
  for (const s of [-1, 1]) put(new THREE.SphereGeometry(L.head * 0.12, 8, 6), 0x111111, s * L.head * 0.55, hy + L.head * 0.25, hz + L.head * 0.75);   // eyes
  if (kind === "boar") { put(new THREE.CylinderGeometry(L.head * 0.35, L.head * 0.42, L.head * 0.5, 10), 0x6e5548, 0, hy - L.head * 0.15, hz + L.head * 1.2).rotation.x = Math.PI / 2;
    for (const s of [-1, 1]) put(new THREE.ConeGeometry(0.02, 0.1, 6), 0xeeeadd, s * L.head * 0.4, hy - L.head * 0.2, hz + L.head * 1.05).rotation.x = -0.6; }   // tusks
  if (kind === "rabbit") for (const s of [-1, 1]) { const e = put(new THREE.CapsuleGeometry(0.025, 0.14, 4, 8), L.body, s * 0.04, hy + 0.12, hz - 0.03); e.rotation.z = s * 0.2; }
  if (kind === "deer") {
    for (const s of [-1, 1]) put(new THREE.ConeGeometry(0.05, 0.12, 8), L.body, s * L.head * 0.7, hy + L.head * 0.6, hz - L.head * 0.4);       // ears
    if (angry) for (const s of [-1, 1]) {                                                                                                    // a stag's antlers: it charges (#162)
      const a = put(new THREE.CylinderGeometry(0.015, 0.025, 0.4, 6), 0xcbb48c, s * 0.08, hy + 0.32, hz - 0.08); a.rotation.z = -s * 0.5;
      const b = put(new THREE.CylinderGeometry(0.01, 0.015, 0.18, 6), 0xcbb48c, s * 0.2, hy + 0.42, hz); b.rotation.x = 0.6;
    }
    put(new THREE.SphereGeometry(0.07, 8, 6), 0xf4efe6, 0, L.high + L.girth * 0.55, -L.len * 0.5);                                             // white tail
  }
  // four legs, each hung from its hip so it can swing
  for (const [x, z] of [[-1, 1], [1, 1], [-1, -1], [1, -1]]) {
    const hip = new THREE.Group(); hip.position.set(x * L.girth * 0.55, L.high, z * L.len * 0.32); g.add(hip);
    put(new THREE.CylinderGeometry(L.girth * 0.16, L.girth * 0.12, L.high, 8), kind === "boar" ? 0x3a2d25 : L.body, 0, -L.high / 2, 0, hip);   // hip to hoof
    legs.push(hip);
  }
  return { g, legs };
}
function animalsSeen(list) {
  const seen = new Set();
  for (const [id, kind, u, v, h, yaw, angry] of list || []) {
    seen.add(id);
    let r = animals.get(id);
    if (!r) { const m = animalMesh(kind, angry); r = { kind, mesh: m.g, legs: m.legs, cu: u, cv: v, cyaw: yaw, gh: h, phase: Math.random() * 6 }; scene.add(r.mesh); animals.set(id, r); }
    r.moving = Math.hypot(u - (r.u ?? u), v - (r.v ?? v)) > 0.01;
    Object.assign(r, { u, v, h, yaw });
  }
  for (const [id, r] of animals) if (!seen.has(id)) { scene.remove(r.mesh); animals.delete(id); }
}
/** Each frame: glide every animal to where the server says, on the drawn ground, its legs swinging while it moves. */
function animalsFrame(dt, cam) {
  const k = Math.min(1, dt * 5);
  for (const r of animals.values()) {
    r.cu += (r.u - r.cu) * k; r.cv += (r.v - r.cv) * k;
    r.cyaw += Math.atan2(Math.sin(r.yaw - r.cyaw), Math.cos(r.yaw - r.cyaw)) * k;
    if (!r.gat || Math.hypot(r.cu - r.gat[0], r.cv - r.gat[1]) > 0.15) { r.gh = groundAt(P.face, r.cu, r.cv) - 0.05; r.gat = [r.cu, r.cv]; }
    const q = Wd.posOf(P.face, r.cu, r.cv, r.gh), ofr = Wd.frameOf(P.face, r.cu, r.cv);
    r.mesh.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    r.mesh.up.set(ofr.up[0], ofr.up[1], ofr.up[2]);
    const sy = Math.sin(r.cyaw), cy = Math.cos(r.cyaw);
    r.mesh.lookAt(r.mesh.position.x + sy * ofr.east[0] + cy * ofr.north[0], r.mesh.position.y + sy * ofr.east[1] + cy * ofr.north[1], r.mesh.position.z + sy * ofr.east[2] + cy * ofr.north[2]);
    r.phase += dt * (r.moving ? 9 : 0);
    r.legs.forEach((l, i) => { l.rotation.x = r.moving ? Math.sin(r.phase + (i === 0 || i === 3 ? 0 : Math.PI)) * 0.5 : 0; });
  }
}
/** The animal under the crosshair within `reach` m, nearer than any cell or piece the view meets: { id, kind, d } or null. */
function animalAimed(reach) {
  if (!animals.size) return null;
  const { fr, fw } = look();
  const d = [fr.east, fr.north, fr.up].map((ax) => fw[0] * ax[0] + fw[1] * ax[1] + fw[2] * ax[2]);
  // what hides an animal: a cell or a piece, never the litter on the ground — flax and flowers in front of a deer took the
  // strike and were picked instead (the first hunting walk, 2026-11-09)
  const o = [P.u, P.v, P.h + EYE], a = aim(), low = a && !a.box && a.hit && Wd.LITTER.has(blockAt(P.face, a.hit[0], a.hit[1], a.hit[2]));
  const wall = a && !low ? Math.hypot(a.point[0] - o[0], a.point[1] - o[1], a.point[2] - o[2]) : Infinity;
  let best = null;
  for (const [id, r] of animals) {
    const L = ANIMAL_LOOK[r.kind] || ANIMAL_LOOK.deer, c = [r.cu, r.cv, r.gh + L.high + L.girth * 0.3];
    const w = [c[0] - o[0], c[1] - o[1], c[2] - o[2]], t = w[0] * d[0] + w[1] * d[1] + w[2] * d[2];
    if (t < 0 || t > reach || t > wall + 0.3) continue;
    const miss = Math.hypot(w[0] - d[0] * t, w[1] - d[1] * t, w[2] - d[2] * t);
    if (miss < Math.max(L.len * 0.55, L.girth + 0.15) && (!best || t < best.d)) best = { id, kind: r.kind, d: t };
  }
  return best;
}
// ---- HEALTH, DEATH AND RESPAWN (#162): the world server keeps a player's health; the page shows it as hearts, flashes
// when struck, and on a death shows what killed them, then wakes them at their bed (Use on a bed) or at the landing.
// The bag is kept.
let hpMax = 20;
function showHp(hp, max) {
  if (max) hpMax = max;
  const el = $("hudHp");
  if (!el || hp == null) return;
  el.classList.toggle("hidden", !net.me);
  const full = Math.max(0, Math.ceil(hp / 2)), all = Math.ceil(hpMax / 2);
  el.textContent = "♥".repeat(full) + "♡".repeat(Math.max(0, all - full)) + ` ${hp}/${hpMax}` + (inv.level ? " · " + T("level", "Level {n}", { n: inv.level }) : "");
}
let wakeAt = null;
function died(by, bed) {
  wakeAt = bed || null;
  $("deathBy").textContent = T("diedBy", "You were killed by a {a}.", { a: animalName(by) });
  $("deathWhere").textContent = bed ? T("wakeBed", "You wake at your bed.") : T("wakeLanding", "You wake at the landing — use a bed to wake there instead.");
  if (document.pointerLockElement) document.exitPointerLock();
  $("deathCard").classList.remove("hidden");
}
function wakeUp() {
  $("deathCard").classList.add("hidden");
  if (wakeAt) { [P.face, P.u, P.v] = [wakeAt[0], wakeAt[1] + 1.2, wakeAt[2]]; }
  else { [P.face, P.u, P.v, P.yaw] = townSpawn(); }
  P.h = groundAt(P.face, P.u, P.v); P.vu = P.vv = P.vh = 0; P.eyeH = P.h;
  save();
  if (!touch) lockPointer();                                // the button's own click: back to play at once
}
// ---- NPCS AND QUESTS (#165, "we may need npcs and quests and move this a little towards world of warcraft as well",
// operator 2026-11-09): the people of the town, kept by the world server, drawn as people with their name over them and
// a mark when they have something for this player — "!" work, "?" a quest to hand in. Use on one talks to them: what
// they offer (Accept), the player's quests that end with them (Hand in). The quest log is in the bag.
const npcs = new Map();                            // id -> { mesh, plate, mark, sig, at }
function label(text, sub, col) {
  const cv = document.createElement("canvas"); cv.width = 256; cv.height = 64;
  const g = cv.getContext("2d");
  g.textAlign = "center"; g.font = "bold 26px sans-serif"; g.lineWidth = 5; g.strokeStyle = "rgba(0,0,0,.75)";
  g.fillStyle = col || "#ffe9a8"; g.strokeText(text, 128, 28); g.fillText(text, 128, 28);
  if (sub) { g.font = "18px sans-serif"; g.fillStyle = "#e8eef4"; g.strokeText(sub, 128, 54); g.fillText(sub, 128, 54); }
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthWrite: false, transparent: true }));
  sp.scale.set(1.6, 0.4, 1);
  return sp;
}
const roleName = (r) => T("npc." + r, { elder: "Elder", trader: "Trader", smith: "Smith" }[r] || r);
function npcsSeen(list) {
  const seen = new Set();
  for (const n of list || []) {
    seen.add(n.id);
    let r = npcs.get(n.id);
    if (!r) {
      const mesh = avatar("npc:" + n.id, n.look), plate = label(n.name, roleName(n.role));
      plate.position.set(0, 2.05, 0); mesh.add(plate);
      r = { mesh, at: n.at, name: n.name, role: n.role }; scene.add(mesh); npcs.set(n.id, r);
    }
    if (r.markSig !== n.mark) {                                  // "!" work for you, "?" a quest to hand in
      if (r.mark) r.mesh.remove(r.mark);
      r.mark = n.mark ? label(n.mark, null, n.mark === "?" ? "#9fe0ff" : "#ffd84a") : null;
      if (r.mark) { r.mark.scale.set(1.4, 0.35, 1); r.mark.position.set(0, 2.45, 0); r.mesh.add(r.mark); }
      r.markSig = n.mark;
    }
  }
  for (const [id, r] of npcs) if (!seen.has(id)) { scene.remove(r.mesh); npcs.delete(id); }
}
function npcsFrame(cam) {
  for (const r of npcs.values()) {
    if (r.gh === undefined) r.gh = groundAt(r.at[0], r.at[1], r.at[2]);
    const q = Wd.posOf(r.at[0], r.at[1], r.at[2], r.gh), ofr = Wd.frameOf(r.at[0], r.at[1], r.at[2]);
    r.mesh.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    r.mesh.up.set(ofr.up[0], ofr.up[1], ofr.up[2]);
    // they face the player when the player is near, the street otherwise
    const du = P.u - r.at[1], dv = P.v - r.at[2], near = Math.hypot(du, dv) < 8, yaw = near ? Math.atan2(du, dv) : 0;
    const sy = Math.sin(yaw), cy = Math.cos(yaw);
    r.mesh.lookAt(r.mesh.position.x + sy * ofr.east[0] + cy * ofr.north[0], r.mesh.position.y + sy * ofr.east[1] + cy * ofr.north[1], r.mesh.position.z + sy * ofr.east[2] + cy * ofr.north[2]);
  }
}
/** The NPC under the crosshair within talking reach: its id, or null. */
function npcAimed() {
  if (!npcs.size) return null;
  const { fr, fw } = look();
  const d = [fr.east, fr.north, fr.up].map((ax) => fw[0] * ax[0] + fw[1] * ax[1] + fw[2] * ax[2]);
  const o = [P.u, P.v, P.h + EYE], reach = RULES && RULES.quests ? RULES.quests.talk : 4;
  let best = null;
  for (const [id, r] of npcs) {
    const c = [r.at[1], r.at[2], (r.gh ?? P.h) + 1.0], w = [c[0] - o[0], c[1] - o[1], c[2] - o[2]], t = w[0] * d[0] + w[1] * d[1] + w[2] * d[2];
    if (t < 0 || t > reach + 0.5) continue;
    if (Math.hypot(w[0] - d[0] * t, w[1] - d[1] * t, w[2] - d[2] * t) < 0.55 && (!best || t < best.t)) best = { id, t };
  }
  return best && best.id;
}
let talkingTo = null;
function openNpc(id) {
  if (!net.online || !net.me) return notify(T("signInFirst", "Sign in first."));
  talkingTo = id;
  const r = npcs.get(id);
  $("npcTitle").textContent = r ? `${r.name} · ${roleName(r.role)}` : id;
  $("npcGrid").textContent = "…";
  if (document.pointerLockElement) document.exitPointerLock();
  $("npcPanel").classList.remove("hidden");
  net.send({ t: "talk", npc: id, req: ++net.req });
}
function questText(q) {
  if (q.kind === "bring") return T("qBring", "Bring {n} × {i}", { n: q.n, i: nameOf(q.item) });
  if (q.kind === "hunt") return T("qHunt", "Hunt {n} × {a}", { n: q.n, a: animalName(q.what) }) + (q.got !== undefined && q.got > 0 ? ` (${q.got}/${q.n})` : "");
  const to = RULES.quests.npcs.find((n) => n.id === q.to);
  return T("qDeliver", "Carry a parcel to {who}", { who: to ? `${to.name} (${roleName(to.role)})` : q.to });
}
function renderNpc(m) {
  const g = $("npcGrid");
  if (m.error) { g.textContent = m.error === "too far away — go up to them" ? T("qFar", "Too far — go up to them.") : m.error; return; }
  const greet = { elder: T("npcElderSays", "Work for willing hands — the town pays from its treasury."), trader: T("npcTraderSays", "Trade at the stands; I keep an eye on the prices."), smith: T("npcSmithSays", "Bring me metal and I will show you what it can become.") }[m.role] || "";
  g.innerHTML = `<p class="dim">${esc(greet)}</p>
    ${m.ends.length ? `<h3>${esc(T("qEnds", "Your quests here"))}</h3>` + m.ends.map((q) => `<div class="rcp"><div>${esc(questText(q))}</div>
      <button class="ghost" data-turnin="${q.id}" ${q.ready ? "" : "disabled"}>${esc(q.ready ? T("qTurnIn", "Hand in") : T("qNotYet", "Not done yet"))}</button></div>`).join("") : ""}
    ${m.offers.length ? `<h3>${esc(T("qOffers", "Work offered"))}</h3>` + m.offers.map((q) => `<div class="rcp"><div>${esc(questText(q))}<div class="dim">${esc(T("qPays", "+{x} experience", { x: RULES.quests.xp[q.kind] }))}</div></div>
      <button class="ghost" data-qaccept="${q.id}">${esc(T("qAccept", "Accept"))}</button></div>`).join("") : ""}`;
  g.querySelectorAll("[data-qaccept]").forEach((b) => { b.onclick = () => net.send({ t: "quest", op: "accept", npc: talkingTo, id: b.dataset.qaccept, req: ++net.req }); });
  g.querySelectorAll("[data-turnin]").forEach((b) => { b.onclick = () => net.send({ t: "quest", op: "turnin", npc: talkingTo, id: b.dataset.turnin, req: ++net.req }); });
}
/** What a strike or an arrow did, in the player's language. */
function huntSaid(m) {
  const H = RULES.hunting;
  if (m.killed) {
    const butchered = (H.species[m.killed].drops || []).some(([i]) => (H.butcher || []).includes(i));
    notify(T("huntKilled", "You hunted a {a}.", { a: animalName(m.killed) }) + (!m.knife && butchered ? " " + T("noKnife", "Without a knife you took only the meat.") : ""));
  } else if (m.hit) {
    notify((H.species[m.hit] || {}).damage ? T("huntHitFight", "A hit — the {a} turns on you!", { a: animalName(m.hit) }) : T("huntHit", "A hit — the {a} runs!", { a: animalName(m.hit) }));
  } else if (m.end) notify(T("huntMiss", "A miss — the arrow fell short or wide."));
}
const animalName = (k) => T("a." + k, { deer: "deer", boar: "boar", rabbit: "rabbit" }[k] || k);
/** Break on an animal: a spear strike when it is within the spear's reach; else, with a bow, an arrow loosed along the
 *  look (BALLISTICS #157: it flies, falls and can miss — the world server flies it again and judges the hit). */
function huntAt(an) {
  const H = RULES && RULES.hunting;
  if (!H) return false;
  const spear = hasClass("spear"), bow = hasClass("bow");
  if (!spear && !bow) { notify(T("huntNeeds", "Hunting needs a spear or a bow.")); return true; }
  if (spear && an.d <= H.weapons.spear.reach) { net.send({ t: "hunt", id: an.id, req: ++net.req }); return true; }
  if (!bow) { notify(T("huntFar", "Too far — get closer, or use a bow.")); return true; }
  return loose();
}
// ---- BALLISTICS (#157, "ballistics? bow and arrow? knife? carpentry tools?", operator 2026-11-09): an arrow leaves the
// eye along the look at the bow's draw speed and falls under gravity — the page flies one to show it, the world server
// flies its own and says what it hit (a running animal must be led, a far one aimed above). Arrows that missed lie where
// they fell for a while; walking over one picks it up.
const arrowsInFlight = [];                       // { mesh, o, vel, t0, until }
let arrowGeo = null;
function arrowMesh() {
  const g = new THREE.Group();
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.7, 5), new THREE.MeshLambertMaterial({ color: 0x9a7a52 }));
  shaft.rotation.x = Math.PI / 2; g.add(shaft);
  const tip = new THREE.Mesh(new THREE.ConeGeometry(0.018, 0.06, 6), new THREE.MeshLambertMaterial({ color: 0x777777 }));
  tip.rotation.x = Math.PI / 2; tip.position.z = 0.38; g.add(tip);
  const fl = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.002, 0.1), new THREE.MeshLambertMaterial({ color: 0xd8d0c0 }));
  fl.position.z = -0.32; g.add(fl);
  return g;
}
function loose() {
  if (!(inv.items.arrow > 0)) { notify(T("huntArrows", "No arrows — make some from sticks, stone and fiber.")); return true; }
  const B = RULES.hunting.ballistics, cp = Math.cos(P.pitch);
  const vel = [B.draw * cp * Math.sin(P.yaw), B.draw * cp * Math.cos(P.yaw), B.draw * Math.sin(P.pitch)];
  const m = arrowMesh(); scene.add(m);
  arrowsInFlight.push({ mesh: m, o: [P.u, P.v, P.h + 1.5], vel, t0: performance.now(), until: 4, face: P.face });
  net.send({ t: "shoot", yaw: P.yaw, pitch: P.pitch, req: ++net.req });
  return true;
}
function arrowsFrame(now, cam) {
  const g = RULES && RULES.hunting ? RULES.hunting.ballistics.g : 9.8;
  for (let i = arrowsInFlight.length - 1; i >= 0; i--) {
    const a = arrowsInFlight[i], t = (now - a.t0) / 1000;
    if (t >= a.until) { scene.remove(a.mesh); arrowsInFlight.splice(i, 1); continue; }
    const p = [a.o[0] + a.vel[0] * t, a.o[1] + a.vel[1] * t, a.o[2] + a.vel[2] * t - g * t * t / 2];
    const q = Wd.posOf(a.face, p[0], p[1], p[2]), dt = 0.02;
    const p2 = [p[0] + a.vel[0] * dt, p[1] + a.vel[1] * dt, p[2] + (a.vel[2] - g * t) * dt], q2 = Wd.posOf(a.face, p2[0], p2[1], p2[2]);
    a.mesh.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    a.mesh.lookAt(q2[0] - cam[0], q2[1] - cam[1], q2[2] - cam[2]);
  }
}
const groundArrows = new Map();                  // drop id -> { mesh, u, v, h, asked }
function dropsSeen(list) {
  const seen = new Set();
  for (const [id, item, u, v, h] of list || []) {
    seen.add(id);
    if (!groundArrows.has(id)) { const m = arrowMesh(); scene.add(m); groundArrows.set(id, { mesh: m, u, v, h, item }); }
  }
  for (const [id, r] of groundArrows) if (!seen.has(id)) { scene.remove(r.mesh); groundArrows.delete(id); }
}
function dropsFrame(now, cam) {
  const reach = RULES && RULES.hunting ? RULES.hunting.ballistics.pickup : 2.5;
  for (const [id, r] of groundArrows) {
    const q = Wd.posOf(P.face, r.u, r.v, r.h + 0.05), q2 = Wd.posOf(P.face, r.u + 0.3, r.v + 0.2, r.h + 0.12);   // stuck in at a slant
    r.mesh.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    r.mesh.lookAt(q2[0] - cam[0], q2[1] - cam[1], q2[2] - cam[2]);
    // walking over one picks it up (asked once a second at most)
    if (net.me && Math.hypot(r.u - P.u, r.v - P.v) < Math.min(1.5, reach) && (!r.asked || now - r.asked > 1000)) {
      r.asked = now; net.send({ t: "pickup", id, req: ++net.req });
    }
  }
}
/** One of FACES kawaii faces on skin colour `skin`, 64 px: 0 sparkly eyes and a smile, 1 happy closed eyes (^ ^),
 *  2 a wink, 3 a cat mouth (:3), 4 sleepy, 5 surprised. Big dark eyes with white glints, pink blush, a small mouth. */
function faceCanvas(face, skin) {
  const cv = document.createElement("canvas"); cv.width = cv.height = 64;
  const g = cv.getContext("2d");
  if (skin != null) { g.fillStyle = "#" + skin.toString(16).padStart(6, "0"); g.fillRect(0, 0, 64, 64); }   // none: a decal
  const eye = (x) => {                                       // a big round eye with two glints
    g.fillStyle = "#2b1e2e"; g.beginPath(); g.ellipse(x, 34, 6, 8, 0, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#fff"; g.beginPath(); g.arc(x - 2, 31, 2.4, 0, Math.PI * 2); g.fill(); g.beginPath(); g.arc(x + 2.5, 37, 1.2, 0, Math.PI * 2); g.fill();
  };
  const arc = (x, up) => { g.strokeStyle = "#2b1e2e"; g.lineWidth = 2.4; g.lineCap = "round"; g.beginPath(); g.arc(x, up ? 37 : 31, 5, up ? Math.PI * 1.15 : Math.PI * 0.15, up ? Math.PI * 1.85 : Math.PI * 0.85); g.stroke(); };
  const line = (x) => { g.strokeStyle = "#2b1e2e"; g.lineWidth = 2.4; g.lineCap = "round"; g.beginPath(); g.moveTo(x - 5, 35); g.lineTo(x + 5, 35); g.stroke(); };
  if (face === 1) { arc(21, true); arc(43, true); } else if (face === 2) { eye(21); arc(43, true); }
  else if (face === 4) { line(21); line(43); } else { eye(21); eye(43); }
  g.fillStyle = "rgba(255,120,150,.45)"; g.beginPath(); g.ellipse(13, 44, 5, 3, 0, 0, Math.PI * 2); g.fill(); g.beginPath(); g.ellipse(51, 44, 5, 3, 0, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "#7a2f3a"; g.fillStyle = "#c2414f"; g.lineWidth = 2; g.lineCap = "round"; g.beginPath();
  if (face === 3) { g.arc(29, 47, 3, 0, Math.PI); g.moveTo(41, 47); g.arc(35, 47, 3, 0, Math.PI); g.stroke(); }          // :3
  else if (face === 5) { g.ellipse(32, 49, 3, 4, 0, 0, Math.PI * 2); g.fill(); }                                       // o
  else if (face === 4) { g.moveTo(29, 48); g.lineTo(35, 48); g.stroke(); }
  else { g.arc(32, 45, 4, 0.15 * Math.PI, 0.85 * Math.PI); g.stroke(); }                                              // a smile
  return cv;
}
const faceTex = new Map();
/** A face as a decal for the head's front cap: transparent around it; mirrored, as the sphere's u runs right to left
 *  seen from the front. */
function faceTexture(face) {
  if (!faceTex.has(face)) {
    const t = new THREE.CanvasTexture(faceCanvas(face, null));
    t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping; t.repeat.x = -1; t.offset.x = 1;
    faceTex.set(face, t);
  }
  return faceTex.get(face);
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
  if (!net.online || !net.me || mine.has(plot) || !titles.has(plot)) return;
  // asked again at every title refresh (t.checked is reset there): an invitation given while you play shows up, and one
  // withdrawn — or ended by a sale — goes away, without a reload
  try {
    const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin" })).json();
    if (r.may_build !== builds.has(plot)) { if (r.may_build) builds.add(plot); else builds.delete(plot); hud(); }
  } catch (e) {}
}

// ---- HUD -------------------------------------------------------------------------------------------------------
const plotLabel = (plot) => { const q = Wd.plotCoords(plot); return `${q.face}·${q.prow}·${q.pcol}`; };
function hud() {
  const w = Wd.wrap(P.face, Math.floor(P.u), Math.floor(P.v)), plot = Wd.plotOf(w.face, w.u, w.v), t = titles.get(plot);
  const changed = (plotEdit.get(plot) || new Map()).size;
  $("hudPos").textContent = T("where", "Plot {p} · height {h} m", { p: plotLabel(plot), h: Math.round(P.h - Wd.SEA) })
    + (changed ? " · " + T("changed", "{n} {n|one:changed block|other:changed blocks}", { n: changed }) : "")
    + ((plotBoxes.get(plot) || { list: [] }).list.length ? " · " + T("pieces", "{n} {n|one:piece|other:pieces}", { n: plotBoxes.get(plot).list.length }) : "");
  if (flying) {                                             // at the controls: speed, height over the ground, what lifts it
    const sp = Math.hypot(...flying.vel), up = flying.pose[3] + flying.bottom - groundAt(flying.pose[0], flying.pose[1], flying.pose[2]);
    $("hudPos").textContent = T("fHud", "Flying · {s} m/s · {a} m up · thrust {t} kN, weight {w} kN", { s: sp.toFixed(1), a: Math.max(0, up).toFixed(1), t: Math.round(flying.thrust), w: Math.round(flightOf(FLIGHT(), flying.mass, flying.thrust).weight) })
      + " · " + T("fEngines", "engines {e} %", { e: Math.round(100 * ((flying.engine && flying.engine.throttle) || 0)) });   // the thrust in use (#171)
  }
  const st = $("hudPlot");
  // the owner is looked up once the plot's title is KNOWN (titles load after the first frames), once per refresh
  if (t && !mine.has(plot) && !t.asked) { t.asked = true; holderOf(plot).then(hud); }
  let html;
  if (t && net.online && net.me && !t.checked) { t.checked = true; builderCheck(plot); }
  const signIn = net.online && !net.me ? ` <a class="btn" href="/land/api/login">${esc(T("signInBuild", "Sign in to build"))}</a>` : "";
  if (!t) html = `<span class="pill">${esc(T("wild", "Wilderness"))}</span> <span class="dim">${esc(T("wildOpen", "Unowned: anyone may gather and build here. Own a plot to protect what you build."))}</span>${signIn}`;
  else if (builds.has(plot) && !mine.has(plot)) html = `<span class="pill ok">${esc(T("invited", "You may build here"))}</span> <span class="dim">${esc(t.holder ? T("owned", "Owned by {o}", { o: disp(t.holder) }) : "")}</span>`;
  else if (mine.has(plot)) html = `<span class="pill ok">${esc(T("yours", "Your plot"))}</span> <button id="btnAnchor" class="ghost">${esc(T("anchorBtn", "Anchor build"))}</button> <button id="btnInvite" class="ghost">${esc(T("inviteBtn", "Invite a builder"))}</button> <button id="btnSell" class="ghost">${esc(T("sellBtn", "Sell"))}</button>`;
  // your own listing: the market holds the title (so it is not in `mine`), and only its seller may reprice or withdraw it
  else if (t.sale && t.sale.seller && t.sale.seller === (net.me || dapp.me)) html = `<span class="pill ok">${esc(T("yourSale", "Your plot · for sale at {p} NADO", { p: rawToNado(t.sale.price.toString()) }))}</span> <button id="btnReprice" class="ghost">${esc(T("repriceBtn", "Change price"))}</button> <button id="btnUnlist" class="ghost">${esc(T("unlistBtn", "Take off sale"))}</button> <a class="btn" target="_blank" rel="noopener" href="${NFT_URL}#token/${esc(t.aid)}">${esc(T("seeListing", "See the listing"))}</a>`;
  else if (t.sale) html = `<span class="pill">${esc(T("forSale", "For sale · {p} NADO", { p: rawToNado(t.sale.price.toString()) }))}</span> <a class="btn" target="_blank" rel="noopener" href="${NFT_URL}#token/${esc(t.aid)}">${esc(T("buyMarket", "Buy on the market"))}</a>${signIn}`;
  else html = `<span class="pill">${esc(t.holder ? T("owned", "Owned by {o}", { o: disp(t.holder) }) : T("titled", "Titled"))}</span> <a class="btn" target="_blank" rel="noopener" href="${NFT_URL}#token/${esc(t.aid)}">${esc(T("market", "View on the market"))}</a>${signIn}`;
  if (st.dataset.html !== html) {
    st.innerHTML = html; st.dataset.html = html;
    const b = $("btnAnchor"); if (b) b.onclick = () => anchor(plot);
    const iv = $("btnInvite"); if (iv) iv.onclick = () => invite(plot);
    const sl = $("btnSell"); if (sl) sl.onclick = () => sell(plot);
    const rp = $("btnReprice"); if (rp) rp.onclick = () => reprice(plot);
    const ul = $("btnUnlist"); if (ul) ul.onclick = () => unlist(plot);
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
  // an item spent to the last leaves the bar ("Wood 0" kept its slot after the wood ran out, 2026-11-08)
  hot = hot.filter((id) => placeable(id) && haveCm3(id) > 0);
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
// TOOLS BY CLASS: a rule or recipe that needs "an axe" takes any axe (stone or iron), and work goes at the best one's speed —
// as the world server judges it (scripts/land_server.py _has_class / _speed)
const hasClass = (cls) => inv.tools.some((t) => t === cls || (RULES.tools[t] && RULES.tools[t].class === cls));
// EATING (#155): while a meal lasts, breaking takes RULES food.work of its time — the world server's work bucket counts
// the same (land_server.py fed_work), so the bar and the server agree on when a cell gives
let fedUntil = 0;
const fedWork = () => (RULES && RULES.food && performance.now() < fedUntil ? RULES.food.work : 1);
const toolSpeed = (cls) => Math.max(1, ...inv.tools.filter((t) => RULES.tools[t] && RULES.tools[t].class === cls).map((t) => RULES.tools[t].speed));
function canMake(r) {
  return (r.with || []).every((w) => hasClass(w) || inv.stations.includes(w))
    && r.uses.every(([id, n]) => (inv.items[id] || 0) >= n);
}
/** The trading stand nearest the player within r m (its plot and box), or null — the world server judges it again. */
function standNear(r) {
  let best = null;
  for (const [plot, pb] of plotBoxes) {
    const q = Wd.plotCoords(plot);
    if (q.face !== P.face || Math.abs(q.u0 + 8 - P.u) > r + 12 || Math.abs(q.v0 + 8 - P.v) > r + 12) continue;
    for (const b of pb.list || []) {
      if (b[6] !== B.stand) continue;
      const d = Math.hypot(q.u0 + (b[0] + b[3] / 2) / Wd.CM - P.u, q.v0 + (b[1] + b[4] / 2) / Wd.CM - P.v);
      if (d <= r && (!best || d < best.d)) best = { plot, box: b, d };
    }
  }
  return best;
}
// PRICES (#163): the market's board — what each thing is worth here, in the unit the player picks, from the trades
// taken at its stands (land_server.py prices); an arrow says how it moved in a day. Nothing has a fixed price.
let priceUnit = "copper_coin";
const fmtQty = (x) => (x >= 100 ? Math.round(x).toString() : x >= 1 ? x.toFixed(x >= 10 ? 1 : 2).replace(/\.?0+$/, "") : x.toPrecision(2));
// the last board per unit is drawn at once and refreshed behind it: the bag redraws whenever the inventory changes, and
// the board blanked to "…" each time until the fetch came back (the market walk, 2026-11-09)
const priceCache = new Map();
async function showPrices() {
  const el = $("pxList");
  if (!el) return;
  const draw = (r) => {
    const rows = Object.entries(r.values).sort((a, b) => b[1] - a[1]);
    const out = $("pxList");
    if (!out) return;
    out.innerHTML = rows.length ? rows.map(([id, v]) => {
      const was = r.before[id], arrow = was ? (v > was * 1.02 ? " ▲" : v < was * 0.98 ? " ▼" : "") : "";
      return `<div>${esc(T("pxRow", "{i}: {v} × {u}", { i: nameOf(id), v: fmtQty(v), u: nameOf(priceUnit) }))}${arrow}</div>`;
    }).join("") : esc(T("pxNone", "No trades here yet in that — prices come from the offers people take."));
  };
  const unit = priceUnit;
  if (priceCache.has(unit)) draw(priceCache.get(unit));
  try {
    const r = await (await fetch(`/land/api/prices?face=${P.face}&u=${P.u.toFixed(2)}&v=${P.v.toFixed(2)}&unit=${encodeURIComponent(unit)}`)).json();
    priceCache.set(unit, r);
    if (unit === priceUnit) draw(r);
  } catch (e) {}
}
function renderBag() {
  if (!RULES) return;
  if (!net.me) { $("palGrid").innerHTML = `<p class="dim">${esc(T("bagSignIn", "Sign in to gather, make things and trade."))}</p>`; return; }
  const items = Object.entries(inv.items).filter(([, n]) => n > 0);
  const atStand = !!standNear(RULES.market ? RULES.market.at : 6);   // MARKETS (#161): trade is done at a trading stand
  // (a quest's parcel is carried, not traded)
  const opts = Object.keys(RULES.items).filter((id) => !RULES.items[id].quest).map((id) => `<option value="${id}">${esc(nameOf(id))}</option>`).join("");
  $("palGrid").innerHTML = `
    <h3>${esc(T("have", "You have"))}</h3>
    <div class="chips">${items.length ? items.map(([id, n]) => `<button class="chip${placeable(id) ? " pl" : ""}" data-pick="${id}">${n} × ${esc(nameOf(id))}</button>`).join("") : `<span class="dim">${esc(T("nothingYet", "Nothing yet — pick up the stones and sticks lying on the ground, and pull grass and leaves by hand."))}</span>`}
      ${inv.tools.map((t) => `<span class="chip tool">${esc(nameOf(t))}</span>`).join("")}${inv.stations.map((t) => `<span class="chip tool">${esc(nameOf(t))}</span>`).join("")}</div>
    ${items.some(([id]) => RULES.food && RULES.food.items[id]) ? `<div class="chips">${items.filter(([id]) => RULES.food.items[id]).map(([id]) =>
      `<button class="chip pl" data-eat="${id}">${esc(T("eatIt", "Eat {i}", { i: nameOf(id) }))}</button>`).join("")}</div>` : ""}
    ${performance.now() < fedUntil ? `<div class="dim">${esc(T("fedFor", "Well fed: work goes quicker for {m} more min.", { m: Math.ceil((fedUntil - performance.now()) / 60000) }))}</div>` : ""}
    <div class="dim">${esc(T("bagHint", "Click a block to put it on your hotbar. Tools work as soon as you have them."))}</div>
    ${(inv.quests || []).length ? `<h3>${esc(T("qLog", "Quests"))}</h3>` + inv.quests.map((q) => `<div class="rcp"><div>${esc(questText(q))}<div class="dim">${esc(q.ready ? T("qReady", "Done — hand it in") : T("qFrom", "for {who}", { who: (RULES.quests.npcs.find((n) => n.id === (q.to || q.giver)) || {}).name || "" }))}</div></div>
      <button class="ghost" data-qdrop="${q.id}">${esc(T("qDrop", "Drop"))}</button></div>`).join("") : ""}
    <h3>${esc(T("pieceSize", "Piece size"))}</h3>
    <div class="tradeform">${PRESETS.map((x, i) => `<button class="chip pl" data-preset="${i}">${x.join("×")}</button>`).join("")}</div>
    <div class="tradeform"><span>W</span><input id="pzW" type="number" min="1" max="1600" value="${piece.w}"><span>D</span><input id="pzD" type="number" min="1" max="1600" value="${piece.d}">
      <span>H</span><input id="pzH" type="number" min="1" max="25600" value="${piece.h}"><span>cm · ${esc(T("snap", "snap"))}</span>
      <select id="pzS">${SNAPS.map((x) => `<option value="${x}"${x === piece.snap ? " selected" : ""}>${x} cm</option>`).join("")}</select></div>
    <div class="tradeform">${[T("shapeBox", "box"), T("shapeSlope", "slope"), T("shapeStairs", "stairs")].map((n, i) =>
      `<button class="chip pl${(piece.shape || 0) === i ? " tool" : ""}" data-shape="${i}" aria-pressed="${(piece.shape || 0) === i}">${esc(n)}</button>`).join("")}
      <button class="chip pl" id="pzTurn">${esc(T("turnPiece", "Turn ↻"))}</button></div>
    <div class="tradeform"><span>${esc(T("tiltYaw", "Yaw"))}</span><input id="pzYaw" type="number" step="0.1" min="-179.9" max="180" value="${(piece.tilt || [0, 0, 0])[0] / 10}">
      <span>${esc(T("tiltPitch", "Pitch"))}</span><input id="pzPitch" type="number" step="0.1" min="-179.9" max="180" value="${(piece.tilt || [0, 0, 0])[1] / 10}">
      <span>${esc(T("tiltRoll", "Roll"))}</span><input id="pzRoll" type="number" step="0.1" min="-179.9" max="180" value="${(piece.tilt || [0, 0, 0])[2] / 10}"><span>°</span>
      <button class="chip pl" id="pzSquare">${esc(T("tiltSquare", "Square"))}</button></div>
    <h3>${esc(T("make", "Make"))}</h3>
    <div class="recipes">${RULES.recipes.map((r) => {
      const out = r.makes.map(([id, n]) => (RULES.items[id] ? n + " " : "") + nameOf(id)).join(", ");
      const need = r.uses.map(([id, n]) => `${n} ${nameOf(id)}`).join(" + ") + ((r.with || []).length ? " · " + T("with", "with {w}", { w: r.with.map(nameOf).join(", ") }) : "");
      const own = r.makes.every(([id]) => inv.tools.includes(id) || inv.stations.includes(id));
      return `<div class="rcp${canMake(r) && !own ? "" : " off"}"><div><b>${esc(out)}</b><div class="dim">${esc(need)}</div></div>
        <button class="ghost" data-make="${r.id}" ${canMake(r) && !own ? "" : "disabled"}>${esc(own ? T("haveIt", "You have it") : T("makeGo", "Make"))}</button></div>`;
    }).join("")}</div>
    <h3>${esc(T("trade", "Trade"))}</h3>
    <div class="dim">${esc(atStand ? T("mkHere", "At a market: offers made here are seen at the stands within {m} m; the market keeps {p}% of what you receive.", { m: RULES.market.reach, p: Math.round(RULES.market.fee * 100) })
      : T("mkNoStand", "Offers are made and taken at a trading stand — build one (planks, beams and cordage, at a workbench), or go to a market."))}</div>
    ${atStand ? `<div class="tradeform"><span>${esc(T("pxIn", "Prices here, in"))}</span><select id="pxUnit">${Object.keys(RULES.items).map((id) =>
      `<option value="${id}"${id === priceUnit ? " selected" : ""}>${esc(nameOf(id))}</option>`).join("")}</select></div><div id="pxList" class="dim">…</div>` : ""}
    <div class="offers">${offers.length ? offers.map((o) => `<div class="rcp"><div>${esc(T("offerLine", "{g} for {w}", { g: bagText(o.give), w: bagText(o.want) }))}<div class="dim">${esc(o.by === net.me ? (o.spot ? T("yourOffer", "Your offer") : T("mkOld", "Your offer from before the markets — withdraw it.")) : disp(o.by))}</div></div>
        ${o.by === net.me ? `<button class="ghost" data-cancel="${o.id}">${esc(T("cancelOffer", "Withdraw"))}</button>` : `<button class="ghost" data-accept="${o.id}" ${atStand && Object.entries(o.want).every(([id, n]) => (inv.items[id] || 0) >= n) ? "" : "disabled"}>${esc(T("acceptOffer", "Trade"))}</button>`}</div>`).join("") : `<span class="dim">${esc(T("noOffers", "No offers yet."))}</span>`}</div>
    <div class="tradeform">
      <span>${esc(T("offerGive", "Give"))}</span><input id="ofGN" type="number" min="1" value="1"><select id="ofG">${opts}</select>
      <span>${esc(T("offerWant", "for"))}</span><input id="ofWN" type="number" min="1" value="1"><select id="ofW">${opts}</select>
      <button class="ghost" id="ofPost" ${atStand ? "" : "disabled"}>${esc(T("offerPost", "Post offer"))}</button>
    </div>
    <div class="tradeform">
      <span>${esc(T("giveTo", "Give"))}</span><input id="gvN" type="number" min="1" value="1"><select id="gvI">${opts}</select>
      <input id="gvTo" placeholder="${esc(T("inviteAddr", "NADO address"))}"><button class="ghost" id="gvGo">${esc(T("giveGo", "Give"))}</button>
    </div>`;
  const g = $("palGrid"), req = (m) => net.send(Object.assign({ req: ++net.req }, m));
  g.querySelectorAll("[data-make]").forEach((b) => { b.onclick = () => req({ t: "craft", recipe: b.dataset.make }); });
  g.querySelectorAll("[data-eat]").forEach((b) => { b.onclick = () => req({ t: "eat", item: b.dataset.eat }); });
  g.querySelectorAll("[data-qdrop]").forEach((b) => { b.onclick = () => req({ t: "quest", op: "drop", id: b.dataset.qdrop }); });
  if ($("pxUnit")) { $("pxUnit").onchange = () => { priceUnit = $("pxUnit").value; showPrices(); }; showPrices(); }
  g.querySelectorAll("[data-pick]").forEach((b) => { b.onclick = () => { const id = b.dataset.pick; if (!placeable(id)) return; if (!hot.includes(id)) { if (hot.length < 9) hot.push(id); else hot[slot] = id; } slot = hot.indexOf(id); save(); hotbar(); }; });
  g.querySelectorAll("[data-accept]").forEach((b) => { b.onclick = () => req({ t: "accept", id: b.dataset.accept }); });
  g.querySelectorAll("[data-cancel]").forEach((b) => { b.onclick = () => req({ t: "cancel_offer", id: b.dataset.cancel }); });
  g.querySelectorAll("[data-preset]").forEach((b) => { b.onclick = () => { [piece.w, piece.d, piece.h] = PRESETS[Number(b.dataset.preset)]; pieceInfo(); renderBag(); }; });
  // SHAPE AND TURN ON A TOUCH SCREEN: box / slope / stairs and a quarter turn were keys only (G, T), so on a phone every
  // piece was a box facing one way — no roof, no stairs, no door turned (building the town pavilion by hand, 2026-11-08)
  g.querySelectorAll("[data-shape]").forEach((b) => { b.onclick = () => { piece.shape = Number(b.dataset.shape); pieceInfo(); renderBag(); }; });
  $("pzTurn").onclick = () => { turnPiece(); renderBag(); };
  const size = () => {
    const v = (id, max) => Math.max(1, Math.min(max, Math.round(Number($(id).value) || 1)));
    piece = { w: v("pzW", Wd.PLOT_CM), d: v("pzD", Wd.PLOT_CM), h: v("pzH", Wd.H_CM), snap: Number($("pzS").value), shape: piece.shape, rot: piece.rot, turned: piece.turned,
      tilt: ["pzYaw", "pzPitch", "pzRoll"].map((id) => tenths($(id).value)) };
    pieceInfo();
  };
  for (const id of ["pzW", "pzD", "pzH", "pzS", "pzYaw", "pzPitch", "pzRoll"]) $(id).onchange = size;
  $("pzSquare").onclick = () => { piece.tilt = [0, 0, 0]; pieceInfo(); renderBag(); };
  $("ofPost").onclick = () => req({ t: "offer", give: { [$("ofG").value]: Number($("ofGN").value) }, want: { [$("ofW").value]: Number($("ofWN").value) } });
  $("gvGo").onclick = () => {
    const to = $("gvTo").value.trim();
    if (!isAddress(to) || to === net.me) return alertBar(T("inviteBad", "That is not someone else's NADO address."));
    // a gift is handed over in person (#161): to a player standing beside you
    const near = [...others.values()].some((r) => r.who === to && r.p && r.p[0] === P.face && Math.hypot(r.p[1] - P.u, r.p[2] - P.v) <= RULES.market.hand);
    if (!near) return alertBar(T("giftNear", "A gift is handed over in person — stand beside them."));
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
  const [w, d, h] = pieceDims(), snap = piece.snap, sz = [w, d, h];
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
  // lined up with the pieces around it (land-snap.js): same material first, edges, flush faces, level bottoms and tops
  const it = RULES && hot[slot] && RULES.items[hot[slot]], rec0 = plotBoxes.get(c.plot);
  let box = [out[0], out[1], out[2], w, d, h, it && it.places ? it.places : 0];
  if (!a.box) {                                          // on the ground: on its lowest point under the whole footprint
    const q = Wd.plotCoords(c.plot);
    box = restOnGround(box, (x, z) => groundAt(P.face, q.u0 + x / Wd.CM, q.v0 + z / Wd.CM) * Wd.CM);
  }
  if (rec0 && rec0.list.length) box = snapBox(box, rec0.list, a.box ? ax : -1);
  box[0] = Math.max(0, Math.min(Wd.PLOT_CM - w, box[0])); box[1] = Math.max(0, Math.min(Wd.PLOT_CM - d, box[1]));
  // never inside the player
  const me = plotCm(P.face, P.u, P.v, P.h);
  const body = [me.x - HALF * Wd.CM, me.z - HALF * Wd.CM, me.y, 2 * HALF * Wd.CM, 2 * HALF * Wd.CM, TALL * Wd.CM];
  const rec = plotBoxes.get(c.plot);
  // TILT (#169): a box or a slope is turned about its centre by the piece's yaw, pitch and roll (never a unit part — a
  // seat, a door, a chest stand square — nor a flight of stairs, which is many pieces); it must still fit the plot
  const tl = piece.tilt || [0, 0, 0], tilt = !(it && it.unit) && (piece.shape || 0) !== 2 && tl.some((t) => t);
  const pieces = shaped(box, it && it.unit ? 0 : piece.shape).map((p) => (tilt ? [...p.slice(0, 7), p.length > 7 ? p[7] : 0, ...tl] : p));
  if (tilt) box = pieces[0];
  const clash = (me.plot === c.plot && pieces.some((p) => Wd.boxesOverlap(p, body))) || (rec && pieces.some((p) => rec.list.some((o) => Wd.boxesOverlap(p, o))));
  return { plot: c.plot, box, pieces, ok: !clash && pieces.every((p) => Wd.boxOk(Wd.normalBox(p.slice(0, 6).concat([p[6] || 1], p.slice(7))))) && box[2] >= 0 && box[2] + h <= Wd.H_CM };
}
// ROOFS AND STAIRS ("A REAL HOUSE"): which way a slope or a flight rises — away from the player, the way they face, then
// turned a quarter at a time by T — as land-world's shape number (1 +x, 2 -x, 3 +z, 4 -z)
function riseShape() {
  const e = Math.sin(P.yaw), n = Math.cos(P.yaw), order = [1, 3, 2, 4];
  const s = Math.abs(e) > Math.abs(n) ? (e > 0 ? 1 : 2) : (n > 0 ? 3 : 4);
  return order[(order.indexOf(s) + (piece.rot || 0)) % 4];
}
const shaped = (box, shape) => piecesFor(box, shape, shape ? riseShape() : 0);
function startBreak(c, mouse) {
  if (!RULES) return;
  const b = blockAt(P.face, c[0], c[1], c[2]), rule = RULES.breaking[b];
  if (!rule) return notify(T("cantGather", "Nothing here can be gathered."));
  if (rule.needs && !hasClass(rule.needs)) return notify(T("needsTool", "That needs a {t}.", { t: nameOf(rule.needs) }));
  const speed = rule.class ? toolSpeed(rule.class) : 1;
  job = { cell: c, need: rule.hard / speed * fedWork(), done: 0, mouse };
}
/** Open or close the door aimed at (Q, or the touch button): it swings a quarter turn on its hinge (land_server.py door). */
// ---- FIRE (#124): X with a fire-making tool lights the air cell in front of what you aim at, if something beside it
// burns; the world server decides and runs the fire (it spreads only where you may build, and burns what it reaches)
function ignite() {
  if (!net.online || !net.me) return notify(T("signInFirst", "Sign in first."));
  if (!hasClass("fire")) return notify(T("noFireTool", "You need something to make fire with — a bow drill (sticks and cordage) or flint and steel."));
  const a = aim();
  if (!a) return notify(T("igniteAim", "Aim at something that burns: grass, wood, leaves, thatch, planks."));
  let c;
  if (a.box) { const q = a.before; c = [Math.floor(q[0]), Math.floor(q[1]), Math.floor(q[2])]; }
  else if (a.prev) c = a.prev;
  else return notify(T("igniteAim", "Aim at something that burns: grass, wood, leaves, thatch, planks."));
  const w = Wd.wrap(P.face, c[0], c[1]);
  net.send({ t: "ignite", cell: [w.face, w.u, w.v, c[2]], req: ++net.req });
}
// ---- FARMING (#154, "farmland, farming, soil types, etc", operator 2026-11-09): Use on turf or earth with a hoe tills
// it into farmland and says what the soil is — its kind rules how long a crop takes and what it gives (land-recipes.json
// "farming"); seed is then placed on the field like any block, and the world server ripens it
const SOIL_SAYS = {
  loam: () => T("soilLoam", "loam — crops grow at full speed and yield well"),
  clay: () => T("soilClay", "clay soil — slow to ripen, but rich"),
  peat: () => T("soilPeat", "peat — rich, a little slow"),
  sandy: () => T("soilSandy", "sandy soil — slow, and a poor harvest"),
  stony: () => T("soilStony", "stony ground — a hoe cannot work it"),
};
/** Water within the farming rule's reach, at the field's layer or under it: a moist field ripens sooner (server moist()). */
function moistAt(u, v, h) {
  const r = RULES.farming.moist_reach;
  for (let du = -r; du <= r; du++) for (let dv = -r; dv <= r; dv++) for (const dh of [0, -1])
    if (blockAt(P.face, u + du, v + dv, h + dh) === B.water) return true;
  return false;
}
/** Use on the ground: till it when it is turf or earth. False when the aimed cell is no such ground (Use goes on). */
function tillAt([u, v, h]) {
  const b = blockAt(P.face, u, v, h);
  if (b !== B.grass && b !== B.dirt) return false;
  if (!RULES || !RULES.farming) return false;
  if (!hasClass("hoe")) { notify(T("tillNeedsHoe", "Tilling needs a hoe — make one from sticks, stone and cordage.")); return true; }
  const soil = Wd.soilOf(P.face, u, v, colAt(P.face, u, v));
  if (!RULES.farming.soil[soil] || RULES.farming.soil[soil].till === false) { notify(SOIL_SAYS.stony()); return true; }
  const over = blockAt(P.face, u, v, h + 1);
  if (over !== B.air && !Wd.SWEPT.has(over)) { notify(T("tillOpen", "A field needs open air over it.")); return true; }
  if (setBlock(P.face, u, v, h, B.farmland))
    notify(T("tilled", "Tilled: {s}.", { s: SOIL_SAYS[soil]() }) + (moistAt(u, v, h) ? " " + T("tillMoist", "Water is near: it ripens sooner.") : "") + " " +
           T("tillSow", "Sow wheat seed on it."), 6000);
  return true;
}
function useDoor() {
  if (flying) return leaveCraft();                                             // Use at the controls: step out
  const a = aim();
  if (a && a.box && a.box.b[6] === B.pilotseat) return board({ plot: a.box.plot, box: a.box.b });   // take the seat
  // …or Use on any part of a craft — its hull, its canopy, a thruster: the seat it is built round (a seat inside a closed
  // cockpit could not be aimed at past the glass — the X fighter of #169, 2026-11-10)
  if (a && a.box && CRAFT_SKIN.has(a.box.b[6])) { const st = craftSeat(a.box.plot, a.box.b); if (st) return board({ plot: a.box.plot, box: st }); }
  { const n = npcAimed(); if (n) return openNpc(n); }                          // Use on a person: talk to them (#165)
  if (a && !a.box && a.hit && net.me && tillAt(a.hit)) return;                 // Use on the ground with a hoe: till it
  if (!(a && a.box && [B.door, B.chest, B.smelter, B.assembler, B.generator, B.well, B.bed].includes(a.box.b[6]))) { const mine = nearMyCraft(); if (mine) return board({ craft: mine }); }
  if (a && a.box && a.box.b[6] === B.chest) return openChest(a.box);           // Q uses what you aim at: a door or a chest
  if (a && a.box && a.box.b[6] === B.bed) {                                    // a bed: wake here after a death (#162)
    if (!net.online || !net.me) return notify(T("signInFirst", "Sign in first."));
    return net.send({ t: "bed", plot: a.box.plot, box: a.box.b, req: ++net.req });
  }
  if (a && a.box && a.box.b[6] === B.well) {                                   // a well: a bucketful, if you have a bucket (#155)
    if (!net.online || !net.me) return notify(T("signInFirst", "Sign in first."));
    if (!hasClass("bucket")) return notify(T("wellBucket", "A well is drawn with a bucket — make one at a workbench."));
    return net.send({ t: "well", plot: a.box.plot, box: a.box.b, req: ++net.req });
  }
  if (a && a.box && [B.smelter, B.assembler, B.generator].includes(a.box.b[6])) return openMachine(a.box);   // a machine
  if (!a || !a.box || a.box.b[6] !== B.door) return notify(T("noUse", "Aim at a door or a chest to use it."));
  if (!net.online || !net.me) return notify(T("signInFirst", "Sign in first."));
  net.send({ t: "door", plot: a.box.plot, box: a.box.b, req: ++net.req });
}
// ---- a machine (#148): Use on a smelter or an assembler shows what it makes and why it waits, and the recipes it can
// run — choosing one sets it going (scripts/land_server.py set_machine / factory_tick); on a generator, its power left
let machine = null;                              // { plot, box } of the machine panel open
function openMachine(bx) {
  if (!net.online || !net.me) return notify(T("signInFirst", "Sign in first."));
  machine = { plot: bx.plot, box: bx.b };
  net.send({ t: "machine", plot: bx.plot, box: bx.b, req: ++net.req });
  if (document.pointerLockElement) document.exitPointerLock();
  $("machTitle").textContent = nameOf(Object.keys(RULES.items).find((k) => RULES.items[k].places === bx.b[6]));
  $("machGrid").textContent = "…";
  $("machPanel").classList.remove("hidden");
}
/** The world server's status, in the player's language (it says it in English: land_server.py factory_tick). */
function machineStatus(st) {
  st = st || "idle";
  if (st === "idle") return T("mIdle", "Waiting — choose what it makes.");
  if (st === "running") return T("mRunning", "Running.");
  if (st === "no chest beside it") return T("mNoChest", "Needs a chest beside it — it takes from it and makes into it.");
  if (st === "its chest is full") return T("mFull", "Its chest is full.");
  if (st.startsWith("needs ")) { const name = st.slice(6), id = Object.keys(RULES.items).find((k) => RULES.items[k].name.toLowerCase() === name); return T("mNeeds", "Needs {i} in the chest beside it.", { i: id ? nameOf(id) : name }); }
  if (st.startsWith("no power")) return T("mNoPower", "No power — a generator with coal or charcoal beside it, within {m} m.", { m: RULES.machines.power_reach });
  return st;
}
function renderMachine(m) {
  const box = $("machGrid");
  if (m.error) notify(m.error, 5000);
  if (!m.cfg) { box.textContent = m.error || ""; return; }
  if (machine.box[6] === B.generator) {
    box.innerHTML = `<p>${esc(T("mGen", "{n} runs of power left. Put coal (20 runs) or charcoal (10) in a chest beside it.", { n: m.cfg.charge || 0 }))}</p>`;
    return;
  }
  const recipeLine = (id) => { const r = RULES.recipes.find((x) => x.id === id); return r ? r.makes.map(([i, n]) => `${n} ${nameOf(i)}`).join(", ") + " ← " + r.uses.map(([i, n]) => `${n} ${nameOf(i)}`).join(" + ") : id; };
  box.innerHTML = `<p><b>${esc(m.cfg.recipe ? recipeLine(m.cfg.recipe) : T("mNothing", "Makes nothing yet — choose below."))}</b></p>
    <p class="dim">${esc(machineStatus(m.cfg.status))}${m.cfg.made ? " · " + esc(T("mMade", "made {n}", { n: m.cfg.made })) : ""}</p>
    <p class="small dim">${esc(T("mHint", "It takes what it needs from a chest beside it and puts what it makes there; a generator within {m} m powers it.", { m: RULES.machines.power_reach }))}</p>
    ${(m.can || []).map((id) => `<div class="mrow${m.cfg.recipe === id ? " on" : ""}"><span>${esc(recipeLine(id))}</span><button class="ghost" data-mrec="${esc(id)}">${esc(T("mChoose", "Make this"))}</button></div>`).join("")}`;
  box.querySelectorAll("[data-mrec]").forEach((b) => { b.onclick = () => net.send({ t: "machine", plot: machine.plot, box: machine.box, recipe: b.dataset.mrec, req: ++net.req }); });
}
// ---- a chest (#114): items kept on its plot by the world server; open it with Q, click an item to move one (Shift: all)
let chest = null;                                // { plot, box, items } of the open chest
function openChest(bx) {
  if (!net.online || !net.me) return notify(T("signInFirst", "Sign in first."));
  chest = { plot: bx.plot, box: bx.b, items: null };
  chestSend({}, {});
  if (document.pointerLockElement) document.exitPointerLock();
  $("chestPanel").classList.remove("hidden");
  renderChest();
}
function chestSend(put, take) { net.send({ t: "chest", plot: chest.plot, box: chest.box, put, take, req: ++net.req }); }
function renderChest() {
  const box = $("chestGrid");
  if (!box || !chest) return;
  // a tap moves one; "All" moves them all — a phone has no Shift, and filling a machine's chest took a tap an item (#148)
  const row = (id, n, dir) => `<span class="crow"><button class="pb" data-${dir}="${esc(id)}" title="${esc(T("chestHint", "Click: one · Shift+click: all"))}"><b>${n}</b> ${esc(nameOf(id))}</button>${n > 1 ? `<button class="pb" data-${dir}all="${esc(id)}">${esc(T("chestAll", "All"))}</button>` : ""}</span>`;
  const items = chest.items, mine = Object.entries(inv.items || {}).filter(([, n]) => n > 0);
  box.innerHTML = `<h3>${esc(T("chestIn", "In the chest"))}</h3><div class="chestRow">${items == null ? "…" : Object.keys(items).length ? Object.entries(items).map(([id, n]) => row(id, n, "take")).join("") : `<span class="dim">${esc(T("chestEmpty", "empty"))}</span>`}</div>
    <h3>${esc(T("chestBag", "In your bag"))}</h3><div class="chestRow">${mine.length ? mine.map(([id, n]) => row(id, n, "put")).join("") : `<span class="dim">${esc(T("chestEmpty", "empty"))}</span>`}</div>
    <p class="small dim">${esc(T("chestHint", "Click: one · Shift+click: all"))}</p>`;
  box.querySelectorAll("[data-take]").forEach((b) => { b.onclick = (e) => { const id = b.dataset.take; chestSend({}, { [id]: e.shiftKey ? chest.items[id] : 1 }); }; });
  box.querySelectorAll("[data-put]").forEach((b) => { b.onclick = (e) => { const id = b.dataset.put; chestSend({ [id]: e.shiftKey ? inv.items[id] : 1 }, {}); }; });
  box.querySelectorAll("[data-takeall]").forEach((b) => { b.onclick = () => chestSend({}, { [b.dataset.takeall]: chest.items[b.dataset.takeall] }); });
  box.querySelectorAll("[data-putall]").forEach((b) => { b.onclick = () => chestSend({ [b.dataset.putall]: inv.items[b.dataset.putall] }, {}); });
}
// ---- the wardrobe (#111): what you wear, and your skin and hair — V, or from the bag. Garments are sewn in the bag with a
// needle; putting one on takes it out of the bag (the world server's "wear"), and everyone near you sees it.
function wardrobe(open) {
  $("wardPanel").classList.toggle("hidden", !open);
  if (!open) return;
  if (!net.online || !net.me) { $("wardPanel").classList.add("hidden"); return notify(T("signInFirst", "Sign in first.")); }
  if (document.pointerLockElement) document.exitPointerLock();
  renderWard();
}
function renderWard() {
  const box = $("wardGrid");
  if (!box) return;
  const look = Object.assign({ skin: 0, hair: 0, body: 0, face: 0 }, inv.look, { worn: inv.worn || {} }), c = lookColours(net.me || "", look);
  const hex = (n) => "#" + n.toString(16).padStart(6, "0");
  const part = (x, y, w, h, col, z = 1, r = "8px", extra = "") => `<i style="left:${x}px;top:${y}px;width:${w}px;height:${h}px;background:${hex(col)};z-index:${z};border-radius:${r};${extra}"></i>`;
  // the figure, front on, as the 3D one is made (avatar): a big round head with the chosen face, a rounded body, limbs and
  // hands, a skirt and pigtails for body type 1 — in the same colours (lookColours)
  const faceUrl = (f) => faceCanvas(f, c.skin).toDataURL(), girl = look.body === 1;
  const fig = (c.cloak != null ? part(26, 64, 68, 112, c.cloak, 0, "18px 18px 6px 6px") : "")
    + part(24, 2, 72, 66, c.hair, 1, "50%") + (girl ? part(26, 34, 68, 46, c.hair, 1, "10px 10px 22px 22px") + part(8, 34, 16, 40, c.hair, 1) + part(96, 34, 16, 40, c.hair, 1) : "")
    + `<i style="left:30px;top:10px;width:60px;height:60px;z-index:3;border-radius:50%;background:url(${faceUrl(look.face)}) center/cover"></i>`
    + (c.cap != null ? part(26, 0, 68, 24, c.cap, 4, "34px 34px 6px 6px") : part(30, 6, 60, 16, c.hair, 4, "30px 30px 4px 4px"))
    + part(36, 70, 48, 62, c.top, 2, "22px") + part(20, 74, 15, 54, c.top, 2) + part(85, 74, 15, 54, c.top, 2)
    + part(20, 124, 15, 15, c.skin, 3, "50%") + part(85, 124, 15, 15, c.skin, 3, "50%")
    + (girl ? part(30, 112, 60, 30, c.top, 3, "4px", "clip-path:polygon(20% 0,80% 0,100% 100%,0 100%)") : "")
    + part(41, 128, 16, 58, c.legs, 2) + part(63, 128, 16, 58, c.legs, 2) + part(38, 182, 22, 10, 0x3a2e2a, 3, "6px") + part(60, 182, 22, 10, 0x3a2e2a, 3, "6px");
  const sw = (list, key) => list.map((col, i) => `<button class="sw${look[key] === i ? " on" : ""}" data-${key}="${i}" style="background:${hex(col)}" aria-label="${i + 1}"></button>`).join("");
  const slots = WEAR_SLOTS.map((slot) => {
    const on = look.worn[slot], have = Object.entries(inv.items || {}).filter(([id, n]) => n > 0 && RULES.items[id] && RULES.items[id].wear === slot);
    return `<div class="wslot"><b>${esc(T("slot." + slot, slot))}</b> ${on ? `${esc(nameOf(on))} <button class="ghost" data-off="${slot}">${esc(T("wTakeOff", "Take off"))}</button>` : `<span class="dim">${esc(T("wNothing", "nothing"))}</span>`}
      ${have.map(([id]) => `<button data-wear="${esc(id)}" data-slot="${slot}">${esc(T("wWear", "Wear {i}", { i: nameOf(id) }))}</button>`).join(" ")}</div>`;
  }).join("");
  box.innerHTML = `<div class="ward"><div class="fig">${fig}</div><div>
    <h3>${esc(T("wSkin", "Skin"))}</h3><div class="sws">${sw(SKIN, "skin")}</div>
    <h3>${esc(T("wHair", "Hair"))}</h3><div class="sws">${sw(HAIR, "hair")}</div>
    <h3>${esc(T("wBody", "Body"))}</h3><div class="sws">${[T("wBoy", "Boy"), T("wGirl", "Girl")].map((n, i) => `<button class="chip pl${look.body === i ? " tool" : ""}" data-body="${i}" aria-pressed="${look.body === i}">${esc(n)}</button>`).join("")}</div>
    <h3>${esc(T("wFace", "Face"))}</h3><div class="sws">${Array.from({ length: FACES }, (_, i) => `<button class="sw face${look.face === i ? " on" : ""}" data-face="${i}" style="background:url(${faceUrl(i)}) center/cover" aria-label="${i + 1}"></button>`).join("")}</div>
    <h3>${esc(T("wClothes", "Clothes"))}</h3>${slots}</div></div>
    <p class="small dim">${esc(T("wHint", "Sew clothes from linen with a needle — make them in the bag (E). What you wear is what others see."))}</p>`;
  const send = (m) => net.send(Object.assign(m, { req: ++net.req }));
  const lookSend = (part) => send(Object.assign({ t: "look", skin: look.skin, hair: look.hair, body: look.body, face: look.face }, part));
  box.querySelectorAll("[data-skin]").forEach((b) => { b.onclick = () => lookSend({ skin: Number(b.dataset.skin) }); });
  box.querySelectorAll("[data-hair]").forEach((b) => { b.onclick = () => lookSend({ hair: Number(b.dataset.hair) }); });
  box.querySelectorAll("[data-body]").forEach((b) => { b.onclick = () => lookSend({ body: Number(b.dataset.body) }); });
  box.querySelectorAll("[data-face]").forEach((b) => { b.onclick = () => lookSend({ face: Number(b.dataset.face) }); });
  box.querySelectorAll("[data-wear]").forEach((b) => { b.onclick = () => send({ t: "wear", slot: b.dataset.slot, item: b.dataset.wear }); });
  box.querySelectorAll("[data-off]").forEach((b) => { b.onclick = () => send({ t: "wear", slot: b.dataset.off, item: null }); });
}
function startTakeDown(bx, mouse) {
  const rule = RULES.breaking[bx.b[6]] || { hard: 1 };
  if (rule.needs && !hasClass(rule.needs)) return notify(T("needsTool", "That needs a {t}.", { t: nameOf(rule.needs) }));
  const speed = rule.class ? toolSpeed(rule.class) : 1;
  const unit = unitOf(bx.b[6]);
  job = { box: bx, need: Math.max(0.05, (rule.hard * (unit ? 1e6 : Wd.boxVolume(bx.b))) / 1e6 / speed * fedWork()), done: 0, mouse };
}
function breakTick(dt) {
  const bar = $("breakBar");
  if (!job) { bar.classList.add("hidden"); return; }
  const a = aim();
  const same = job.box ? a && a.box && a.box.b === job.box.b
    : a && ((a.hit && a.hit.join() === job.cell.join()) || (a.water && a.water.join() === job.cell.join()));
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
const NATURAL_ITEMS = new Set(["dirt", "sand", "gravel", "snow", "sapling", "water", "poppy", "cornflower", "daisy", "buttercup", "seed"]);   // these fill the ground's cells; the rest are pieces

// ---- LEVELLING ("it is currently not possible to level ground ... to have a nice clean structure", operator 2026-11-06;
// Enshrouded and Valheim level a site with a hoe first). L with a shovel flattens the 5 x 5 columns around the aimed cell
// to that cell's layer T: natural cells above T are dug out (the player keeps what they give), cell T becomes edited earth
// (untouched turf there is dug and replaced), hollows below T are filled with earth from the bag, and an untouched air
// cell just above T is made an exact one (an earth placed and dug back, nothing spent) — edited cells sit on whole layers,
// so the ground comes out dead flat; an untouched air cell would blend it up to 17 cm high. Plain breaks and placements,
// judged by the world server as ever; a column's batch goes only when the shovel's work time allows (land_server work()).
const LEVEL_R = 2, LEVEL_DEPTH = 3;
let level = null;                                          // { cols: [{ plot, ops }], at }
const levelWorld = { block: (u, v, h) => blockAt(P.face, u, v, h), edited: (u, v, h) => edits.has(key(P.face, u, v, h)), top: (u, v) => colAt(P.face, u, v).top };
function startLevel() {
  if (!net.me) return notify(T("signInBuild2", "Sign in to gather and build."));
  if (!hasClass("shovel")) return notify(T("levelNeedsShovel", "Levelling needs a shovel."));
  const a = aim();
  if (!a || !a.hit || a.box) return notify(T("levelAim", "Aim at the ground to level it."));
  const [u0, v0] = a.hit, T0 = siteLayer(levelWorld, u0, v0, LEVEL_R), cols = [];
  let trunk = false;
  for (let du = -LEVEL_R; du <= LEVEL_R; du++) for (let dv = -LEVEL_R; dv <= LEVEL_R; dv++) {
    const u = u0 + du, v = v0 + dv, plot = Wd.plotOf(P.face, u, v);
    if (!mayBuild(plot)) return explainNoBuild(plot);
    if (Math.abs(colAt(P.face, u, v).top - T0) > LEVEL_DEPTH + 1) continue;      // a cliff edge is left alone
    const ops = levelOps(levelWorld, u, v, T0, LEVEL_DEPTH, hasClass("axe"));
    if (!hasClass("axe") && trunkIn(levelWorld, u, v, T0)) trunk = true;
    if (ops.length) cols.push({ plot, ops });
  }
  if (trunk) notify(T("levelTrunk", "A tree stands on the site — make an axe to fell it, or the ground stays bumped there."));
  if (earthNeeded(cols.flatMap((c) => c.ops), levelWorld) > (inv.items.dirt || 0))
    return notify(T("levelNoEarth", "Not enough earth to fill the hollows — dig some first."));
  level = { cols, at: 0 };
  notify(T("levelling", "Levelling…"));
}
function levelTick(now) {
  if (!level || now < level.at) return;
  const c = level.cols.shift();
  if (!c) { level = null; return notify(T("levelDone", "Level.")); }
  const cells = c.ops.map(([u, v, h, b]) => [P.face, u, v, h, b]);
  for (const [u, v, h, b] of c.ops) putCell(P.face, u, v, h, b);                       // shown at once; resynced if refused
  net.send({ t: "set", cells, req: ++net.req });
  net.pending.set(net.req, c.plot);
  // the next column when this one's work is done: each break is its rule's hardness over the shovel's speed
  const work = c.ops.filter((o) => o[3] === B.air).reduce((t) => t + 0.6 / toolSpeed("shovel") * fedWork(), 0);
  level.at = now + work * 1000 + 120;
}
const haveCm3 = (id) => (inv.items[id] || 0) * 1e6 + ((inv.vol || {})[id] || 0);
// UNIT ITEMS (a door): placed whole at their own size, either way round (T turns it), one item per piece
const unitOf = (m) => { const id = RULES && Object.keys(RULES.items).find((k) => RULES.items[k].places === m); return id ? RULES.items[id].unit : null; };
/** A quarter turn (T, or Turn in the bag): the footprint swaps width and depth (a door turns), and a slope or a flight of
 *  stairs rises the next way round. */
function turnPiece() {
  [piece.w, piece.d] = [piece.d, piece.w]; piece.turned = !piece.turned;
  if (piece.shape) piece.rot = ((piece.rot || 0) + 1) % 4;
  pieceInfo();
}
function pieceDims() {
  const it = RULES && hot[slot] && RULES.items[hot[slot]];
  if (it && it.unit) return piece.turned ? [it.unit[1], it.unit[0], it.unit[2]] : [it.unit[0], it.unit[1], it.unit[2]];
  return [piece.w, piece.d, piece.h];
}
function act(place, mouse) {
  // signed out, a tap says so whatever it points at: it used to say nothing when the view held no target (sky, a gap in
  // a crown) — a visitor tapping in a forest got silence (the live two-player walk, 2026-11-07)
  if (!net.me) return notify(T("signInBuild2", "Sign in to gather and build."));
  if (!place) { const an = animalAimed(RULES && RULES.hunting ? RULES.hunting.weapons.bow.reach : 30); if (an && huntAt(an)) return; }   // game first (#156)
  const a = aim();
  // nothing within reach to break, a bow in the bag: Break looses an arrow along the look — aimed above a far animal, or
  // ahead of a running one (#157)
  if (!a && !place && hasClass("bow")) return loose();
  if (!a) return;
  if (place) {
    const id = hot[slot];
    if (!net.online || !net.me) return setBlock(P.face, Math.floor(a.point[0]), Math.floor(a.point[1]), Math.floor(a.point[2]), B.air);   // says why first
    if (!id || !(haveCm3(id) > 0)) return notify(T("noItem", "You have none of that — gather or make some first."));
    if (NATURAL_ITEMS.has(id)) {
      // JUMP AND PLACE UNDER ("the jump + place under should work", operator 2026-11-07): in the air above the cell you
      // jumped from, looking down at what is under you, the block goes into that cell — as soon as your feet clear it,
      // so the click need not land on the top of the jump
      const fu = Math.floor(P.u), fv = Math.floor(P.v);
      if (!P.ground && !P.fly && a.hit && a.hit[0] === fu && a.hit[1] === fv && a.hit[2] + 1 <= P.h + 0.05) {
        pillar = { cell: [fu, fv, a.hit[2] + 1], b: RULES.items[id].places, air: true };
        return pillarTick();
      }
      if (!a.prev || !roomFor(a.prev) || !rootsIn(a.prev)) return;   // the outline says so: red (frame)
      const [cu, cv, ch] = a.prev, lift = inBody(a.prev);
      if (!setBlock(P.face, cu, cv, ch, RULES.items[id].places)) return;
      if (lift) { P.h = ch + 1; P.vh = 0; }                         // standing on it
      return;
    }
    const pl = placement(a);
    if (!pl) return;
    if (!mayBuild(pl.plot)) return explainNoBuild(pl.plot);
    if (!pl.ok) return notify(T("noRoom", "No room for that piece there."));
    const add = pl.pieces.map((b) => { const x = b.slice(); x[6] = RULES.items[id].places; return x; });
    const vol = add.reduce((a, b) => a + Wd.boxVolume(b), 0);
    if (RULES.items[id].unit ? !((inv.items[id] || 0) >= 1) : haveCm3(id) < vol) return notify(T("notEnough", "Not enough {i} for a piece that size.", { i: nameOf(id) }));
    const cur = plotBoxes.get(pl.plot);
    setPlotBoxes(pl.plot, (cur ? cur.list : []).concat(add));                   // shown at once; put back if refused
    net.send({ t: "boxes", plot: pl.plot, add, req: ++net.req });
  } else {
    if (a.box) return startTakeDown(a.box, mouse);
    // WATER: with a bucket, the first water the view crosses is scooped (a bucketful into the bag) — not the pond's bed
    if (a.water && hasClass("bucket")) return startBreak(a.water, mouse);
    const [u, v, h] = a.hit;
    // bedrock (the crust's floor, and under the deep) gives way only to a drill, and never under DEEP_MIN
    if (blockAt(P.face, u, v, h) === B.bedrock && (h < 0 || !hasClass("drill"))) return notify(T("needsDrill", "Bedrock — only a drill breaks it."));
    startBreak(a.hit, mouse);
  }
}
// ---- the console ("there should be also a console like in minecraft to send commands", "also add configurable setting
// along with the console (command line)", operator 2026-11-06): / opens it with a command, Enter with chat, Escape
// closes it. A line without a slash is chat to the players around you (the world server relays it to whoever watches
// the plots you watch). SETTINGS are this viewer's own, remembered in this browser — a convenience, nothing shared.
const LS_SET = "nado_land_settings";
const SET_DEF = { fov: 72, sens: 1, invert: 0, grass: 1, shadows: 2, effects: 1, borders: 1, stats: 0, res: 100, view: 6, fps: 0, auto: 1 };
const SET_RANGE = { fov: [50, 110], sens: [0.2, 4], invert: [0, 1], grass: [0, 1], shadows: [0, 3], effects: [0, 1], borders: [0, 1], stats: [0, 1],
  res: [50, 100], view: [2, 10], fps: [0, 60], auto: [0, 1] };
// GRAPHICS (#166, operator 2026-11-10: "make graphical settings more configurable (resolution, shadows, etc)"): res is the
// render resolution in % of the screen's pixels, shadows off / low / medium / high (the sun's shadow map size and reach),
// view the chunks drawn around you, fps a frame-rate cap (0: none). A phone starts on what it can carry — no shadows,
// grass or effects, 4 chunks — and any of them can be turned on in the panel (they used to be refused on a touch screen).
const SET_PHONE = { shadows: 0, grass: 0, effects: 0, view: 4 };
const SHADOW_Q = [null, { map: 1024, box: 32 }, { map: 2048, box: 48 }, { map: 4096, box: 64 }];   // by SET.shadows
const SET_VER = 2;                      // stored with the settings: 1 had shadows 0/1 (1 = today's medium), no phone choice
const SET = (() => {
  let s = {};
  try { s = JSON.parse(localStorage.getItem(LS_SET) || "{}") || {}; } catch (e) {}
  if (s.sv !== SET_VER) {               // settings saved before the panel: 1 was the only shadows there were, and a phone's
    if (s.shadows === 1) s.shadows = 2; // stored grass/effects were never used (refused on touch) — not a choice to honour
    if (PHONE) { delete s.grass; delete s.effects; delete s.shadows; }
  }
  const o = { ...SET_DEF, ...(PHONE ? SET_PHONE : {}) };
  for (const k in SET_DEF) if (typeof s[k] === "number" && s[k] >= SET_RANGE[k][0] && s[k] <= SET_RANGE[k][1]) o[k] = s[k];
  return o;
})();
// settings saved since the panel came (#166): the player has chosen, and the first-run benchmark leaves their choice alone
const SET_CHOSEN = (() => { try { return (JSON.parse(localStorage.getItem(LS_SET) || "{}") || {}).sv === SET_VER; } catch (e) { return false; } })();
function saveSet() { try { localStorage.setItem(LS_SET, JSON.stringify({ ...SET, sv: SET_VER })); } catch (e) {} }
const gfxPreset = () => Object.keys(GFX_PRESETS).find((n) => Object.entries(GFX_PRESETS[n]).every(([k, v]) => SET[k] === v)) || "custom";
const basePR = () => Math.min(PHONE ? 1.25 : 2, devicePixelRatio || 1);
let conOpen = false, conHist = [], conHi = 0;
function conLine(text, cls) {
  const log = $("conLog");
  if (!log) return;
  const d = document.createElement("div");
  d.textContent = text;
  if (cls) d.className = cls;
  log.appendChild(d);
  while (log.childNodes.length > 80) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
  log.classList.add("show");
  clearTimeout(conLine.t);
  if (!conOpen) conLine.t = setTimeout(() => log.classList.remove("show"), 9000);   // chat fades while you play
}
function conShow(open, prefill) {
  conOpen = open;
  $("console").classList.toggle("open", open);
  $("conLog").classList.toggle("show", open);
  const inp = $("conIn");
  if (open) { if (document.pointerLockElement) document.exitPointerLock(); inp.value = prefill || ""; setTimeout(() => inp.focus(), 0); }
  else inp.blur();
  if (open) $("help").classList.add("hidden");                          // shown once only (wireInput: THE WELCOME CARD, ONCE)
}
function applySetting(k) {
  if (k === "fov" && camera) { camera.fov = SET.fov; camera.updateProjectionMatrix(); }
  if (k === "grass") for (const key of chunks.keys()) request(key);           // re-mesh with or without the blades
  if (!renderer) return;                                                       // before start(): start() applies them all
  if (k === "res") renderer.setPixelRatio(basePR() * SET.res / 100);
  if (k === "shadows") shadowQuality();
  if (k === "view") { viewDist = SET.view; if (scene && scene.fog) scene.fog.near = viewDist * CHUNK * 0.9; updateChunks(); buildFar(); }
  if (k === "effects") pipeline = buildPipeline();                             // the post-processing is built again, or dropped
}
/** The sun's shadow map for SET.shadows: its size and the box it covers; the old map is let go so the next frame draws a
 *  new one at the new size. Off casts nothing (frame: sun.castShadow). */
function shadowQuality() {
  const q = SHADOW_Q[SET.shadows];
  if (!q || !sun) return;
  sun.shadow.mapSize.set(q.map, q.map);
  Object.assign(sun.shadow.camera, { left: -q.box, right: q.box, top: q.box, bottom: -q.box });
  sun.shadow.camera.updateProjectionMatrix();
  if (sun.shadow.map) { sun.shadow.map.dispose(); sun.shadow.map = null; }
}
// ---- the graphics panel (#166): presets and each setting, applied at once and kept in this browser ------------------------
const settingsOpen = () => !$("setPanel").classList.contains("hidden");
function settings(open) {
  $("setPanel").classList.toggle("hidden", !open);
  if (!open) return;
  if (document.pointerLockElement) document.exitPointerLock();
  renderSettings();
}
function setSetting(k, v) {
  if (!(k in SET_DEF) || !(Number.isFinite(v) && v >= SET_RANGE[k][0] && v <= SET_RANGE[k][1]) || SET[k] === v) return;
  SET[k] = v; saveSet(); applySetting(k);
}
function renderSettings() {
  const box = $("setGrid");
  if (!box) return;
  const now = gfxPreset(), esc = (x) => String(x).replace(/[&<>"]/g, (c) => "&#" + c.charCodeAt(0) + ";");
  const NAMES = Object.fromEntries(Object.keys(GFX_PRESETS).concat("custom").map((n) => [n, presetName(n)])), last = benchLast();
  const sel = (k, label, opts) => `<label class="srow"><span>${esc(label)}</span><select data-set="${k}">`
    + opts.map(([v, t]) => `<option value="${v}"${SET[k] === v ? " selected" : ""}>${esc(t)}</option>`).join("") + `</select></label>`;
  const onOff = [[0, T("gOff", "Off")], [1, T("gOn", "On")]];
  box.innerHTML = `<div class="presets">` + Object.keys(GFX_PRESETS).concat("custom").map((n) =>
    n === "custom" ? (now === "custom" ? `<button class="ghost on" disabled>${esc(NAMES.custom)}</button>` : "")
      : `<button class="ghost${now === n ? " on" : ""}" data-preset="${n}">${esc(NAMES[n])}</button>`).join("") + `</div>`
    + `<div class="srow"><span class="dim">${esc(last ? T("benchLast", "Measured here: {p} — {f} fps", { p: presetName(last.preset), f: last.fps }) : T("benchNone", "Not measured on this device yet"))}</span>`
    + `<button class="ghost" id="benchGo"${benching ? " disabled" : ""}>${esc(benching ? T("benchBusy", "Measuring…") : T("benchBtn", "Benchmark"))}</button></div>`
    + sel("res", T("gRes", "Render resolution"), [50, 60, 70, 80, 90, 100].map((v) => [v, v + " %"]))
    + sel("shadows", T("gShadows", "Shadows"), [[0, T("gOff", "Off")], [1, NAMES.low], [2, NAMES.medium], [3, NAMES.high]])
    + sel("view", T("gView", "View distance"), [2, 3, 4, 5, 6, 7, 8, 9, 10].map((v) => [v, T("gViewN", "{n} {n|one:chunk|other:chunks} · {m} m", { n: v, m: v * CHUNK })]))
    + sel("fps", T("gFps", "Frame-rate cap"), [[0, T("gFpsNone", "None")], [30, "30"], [60, "60"]])
    + sel("grass", T("gGrass", "Grass"), onOff)
    + sel("effects", T("gEffects", "Effects (bloom, ambient light)"), onOff)
    + sel("auto", T("gAuto", "Adjust automatically (presets only)"), onOff)
    + sel("fov", T("gFov", "Field of view"), [60, 66, 72, 80, 90, 100, 110].concat([SET.fov]).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b).map((v) => [v, v + "°"]))
    + `<p class="dim">${esc(T("gNote", "Kept in this browser. Each change applies at once."))}</p>`;
  for (const b of box.querySelectorAll("[data-preset]")) b.onclick = () => {
    for (const [k, v] of Object.entries(GFX_PRESETS[b.dataset.preset])) setSetting(k, v);
    renderSettings();
  };
  for (const e of box.querySelectorAll("select[data-set]")) e.onchange = () => { setSetting(e.dataset.set, Number(e.value)); renderSettings(); };
  const go = box.querySelector("#benchGo"); if (go) go.onclick = () => bench();
}
function presetName(n) {
  return { low: T("gLow", "Low"), medium: T("gMedium", "Medium"), high: T("gHigh", "High"), ultra: T("gUltra", "Ultra") }[n] || T("gCustom", "Custom");
}
// ---- THE BENCHMARK (#166: "performance benchmark that sets graphical settings"): from Ultra down, each preset is put on,
// warmed (its chunks meshed, its shaders compiled, its shadows cast) and its frames measured where the player stands; the
// first that holds the device's target (60 fps, a phone 30 — land-gfx.js holds) is kept. Run from the panel or /bench,
// and once by itself on a device that has never chosen (not in a headless browser: page tests and plot photos).
const LS_BENCH = "nado_land_bench";
let benching = false;
function benchLast() { try { const b = JSON.parse(localStorage.getItem(LS_BENCH) || "null"); return b && GFX_PRESETS[b.preset] ? b : null; } catch (e) { return null; } }
/** Frame intervals (ms) for `ms` of drawing; a tab that stops drawing (hidden) ends it at 3 × ms with what it has. */
const framesFor = (ms) => new Promise((done) => {
  const out = []; let last = 0, over = false; const t0 = performance.now();
  const end = () => { if (!over) { over = true; done(out); } };
  const f = (now) => { if (over) return; if (last) out.push(now - last); last = now; if (now - t0 < ms) requestAnimationFrame(f); else end(); };
  requestAnimationFrame(f); setTimeout(end, ms * 3);
});
// ---- THE GOVERNOR (#166, land-gfx.js govStep): while playing on a preset, frames slow for 3 s move it one preset down,
// fast for 12 s one up, and a step that did not help is taken back. A player's own mix (Custom) is theirs: it is left
// alone. On by default (SET.auto); not in a headless browser (page tests, plot photos) unless the page is opened with
// ?gov (its own test).
let GOV_ON = null, gov = null;           // GOV_ON is decided at the first frame: SHOT is declared further down this file
function govTick(now, gap) {
  if (GOV_ON === null) GOV_ON = SHOT === null && (!/HeadlessChrome/.test(navigator.userAgent) || new URLSearchParams(location.search).has("gov"));
  if (!GOV_ON || !SET.auto || benching || document.hidden) { gov = null; return; }
  const at = LADDER.indexOf(gfxPreset());
  if (at < 0) { gov = null; return; }
  // a frame-rate cap is the pace asked for: capped at 30, 33 ms frames are on time, not slow
  const target = SET.fps ? Math.min(SET.fps, benchTarget(PHONE)) : benchTarget(PHONE);
  if (!gov || gov.target !== target) gov = Object.assign(governor(target), { target });
  const to = govStep(gov, gap, now, at);
  if (to === at) return;
  for (const [k, v] of Object.entries(GFX_PRESETS[LADDER[to]])) setSetting(k, v);
  saveSet();
  notify(to < at ? T("govDown", "Graphics lowered to {p} to keep it smooth", { p: presetName(LADDER[to]) })
    : T("govUp", "Graphics raised to {p}", { p: presetName(LADDER[to]) }), 3000);
  if (settingsOpen()) renderSettings();
}
async function bench() {
  if (benching || !renderer) return;
  benching = true;
  const target = benchTarget(PHONE), cap = SET.fps, measured = {};
  SET.fps = 0;                                              // measured uncapped: a cap would pass a preset it cannot hold
  if (settingsOpen()) renderSettings();
  notify(T("benchRun", "Measuring which graphics this device draws smoothly — a few seconds…"), 4000);
  try {
    for (const name of BENCH_ORDER) {
      for (const [k, v] of Object.entries(GFX_PRESETS[name])) setSetting(k, v);
      await framesFor(PHONE ? 3000 : 2000);
      measured[name] = await framesFor(3000);
      if (holds(frameStats(measured[name]), target)) break;
    }
    const chosen = pickPreset(measured, target), st = frameStats(measured[chosen]), fps = st ? Math.round(st.fps) : 0;
    for (const [k, v] of Object.entries(GFX_PRESETS[chosen])) setSetting(k, v);
    try { localStorage.setItem(LS_BENCH, JSON.stringify({ at: Date.now(), preset: chosen, fps })); } catch (e) {}
    notify(T("benchDone", "Graphics: {p} — {f} fps. Change it in Settings.", { p: presetName(chosen), f: fps }), 6000);
  } finally {
    SET.fps = cap; saveSet(); benching = false;
    if (settingsOpen()) renderSettings();
  }
}
const CMDS = {
  help: () => [["/help", T("cHelp", "this list")], ["/pos", T("cPos", "where you are")], ["/tp spawn | /tp bed", T("cTpTo", "go to the landing, or to your bed")],
    ["/aim", T("cAim", "what you aim at, and where a block would go")], ["/prof", T("cProf", "the profiler: where each frame's time goes")], ["/dock", T("cDock", "set your landed craft down as pieces")], ["/handover <player>", T("cGive", "give your craft to a player — they take its controls")], ["/fly", T("cFly", "fly or walk")], ["/settings", T("cSettings", "your settings")], ["/bench", T("cBench", "measure this device and pick its graphics")], ["/tilt <yaw> <pitch> <roll>", T("cTilt", "turn the piece in hand, in degrees")], ["/set <name> <value>", T("cSet", "change one (e.g. /set fov 90)")],
    ["/clear", T("cClear", "clear this log")], ["…", T("cChat", "anything else is chat to the players around you")]].forEach(([c, d]) => conLine(c + " — " + d)),
  pos: () => conLine(`${T("cFace", "face")} ${P.face} · u ${Math.floor(P.u)} · v ${Math.floor(P.v)} · h ${P.h.toFixed(1)} · ${T("cPlot", "plot")} ${Wd.plotOf(P.face, Math.floor(P.u), Math.floor(P.v))}`),
  // /tp (#167): to the landing or to your own bed — nowhere else; going far is walking, flying, or a craft. Signed in, the
  // world server moves you (and refuses a page that moves itself faster than anyone can go); a visitor goes to the landing
  tp: (a) => {
    const to = (a[0] || "").toLowerCase();
    if (to !== "spawn" && to !== "bed") return conLine(T("cTpUse", "Usage: /tp spawn (the landing), or /tp bed (your bed)."), "err");
    if (net.online && net.me) return net.send({ t: "tp", to });
    if (to === "bed") return conLine(T("signInFirst", "Sign in first."), "err");
    const sp = townSpawn(); P.face = sp[0]; P.u = sp[1]; P.v = sp[2]; P.yaw = sp[3]; P.h = groundAt(P.face, P.u, P.v); P.vu = P.vv = P.vh = 0;
    save(); conLine(T("tpSpawn", "At the landing."));
  },
  // /aim: what the crosshair is on and the cell a block goes into — what the outline shows, in words a report can quote
  // ("it is impossible to judge what will happen upon placing a block", operator 2026-11-08)
  aim: () => {
    const a = aim();
    if (!a) return conLine(T("cAimNone", "Nothing within reach."));
    // a block by the item that places it, or the item of its own name (ores, clay, flax), or its own name (land.b.*)
    const named = (b) => {
      if (b === B.wheatyoung) return T("b.wheatyoung", "Young wheat");     // a growing crop, not the seed it was sown as
      const k = BLOCKS[b].key, id = RULES && Object.keys(RULES.items).find((i) => RULES.items[i].places === b);
      return id ? nameOf(id) : RULES && RULES.items[k] ? nameOf(k) : T("b." + k, k);
    };
    const at = a.box ? [Wd.plotCoords(a.box.plot).u0 + Math.floor(a.box.b[0] / Wd.CM), Wd.plotCoords(a.box.plot).v0 + Math.floor(a.box.b[1] / Wd.CM), Math.floor(a.box.b[2] / Wd.CM)] : a.hit;
    conLine(T("cAimAt", "Aiming at {b} — u {u} · v {v} · h {h}.", { b: named(a.box ? a.box.b[6] : blockAt(P.face, at[0], at[1], at[2])), u: at[0], v: at[1], h: at[2] }));
    if (a.prev) conLine(T("cAimPut", "A block goes to u {u} · v {v} · h {h}.", { u: a.prev[0], v: a.prev[1], h: a.prev[2] }));
    // the ground's soil (#154): what a field there would be
    if (!a.box && [B.grass, B.dirt, B.farmland].includes(blockAt(P.face, at[0], at[1], at[2])))
      conLine(T("cAimSoil", "Soil: {s}.", { s: SOIL_SAYS[Wd.soilOf(P.face, at[0], at[1], colAt(P.face, at[0], at[1]))]() }));
  },
  // /dock: your parked craft nearby (or the one you fly, landed) set down as pieces on the plot under its seat
  dock: () => {
    // the craft flown last is asked for too: the list of crafts near can lag a moment behind leaving it (the server checks
    // it is yours and parked)
    const id = flying ? flying.id : nearMyCraft() || lastCraft;
    if (!id) return conLine(T("cDockNone", "No craft of yours near — land it and stand by it."), "err");
    if (flying) leaveCraft();
    net.send({ t: "dock", craft: id, req: ++net.req });
  },
  // /handover <player>: HAND A CRAFT OVER (#171) — the one you fly, or your parked craft near; to a player by their address, or
  // by the start of the address of one standing near. They own it and take its controls at once (land_server.py give).
  handover: (a) => {
    const id = flying ? flying.id : nearMyCraft() || lastCraft, w = String(a[0] || "").toLowerCase();
    if (!id) return conLine(T("cDockNone", "No craft of yours near — land it and stand by it."), "err");
    const near = [...new Set([...others.values()].map((r) => r.who).filter((x) => x && x.startsWith(w)))];
    const to = /^[0-9a-f]{50}$/.test(w) ? w : w.length >= 4 && near.length === 1 ? near[0] : null;
    if (!to) return conLine(T("cGiveWho", "Give it to whom? /handover <address> — or the start of the address of a player near."), "err");
    if (flying) leaveCraft();
    net.send({ t: "handover", craft: id, to, req: ++net.req });    // not "give": that message is a gift of items
  },
  fly: () => { P.fly = !P.fly; P.vh = 0; conLine(P.fly ? T("flyOn", "Flying — Space up, C down, Shift fast") : T("flyOff", "Walking")); },
  settings: () => { settings(true); Object.keys(SET_DEF).forEach((k) => conLine(`${k} = ${SET[k]}  (${SET_RANGE[k][0]}–${SET_RANGE[k][1]})`)); },
  set: (a) => {
    const k = a[0], v = Number(a[1]);
    if (!(k in SET_DEF)) return conLine(T("cSetBad", "Unknown setting — /settings lists them."), "err");
    if (!(Number.isFinite(v) && v >= SET_RANGE[k][0] && v <= SET_RANGE[k][1])) return conLine(T("cSetRange", "{k} takes a number from {a} to {b}.", { k, a: SET_RANGE[k][0], b: SET_RANGE[k][1] }), "err");
    SET[k] = v;
    saveSet();
    applySetting(k);
    if (settingsOpen()) renderSettings();
    conLine(`${k} = ${v}`);
  },
  clear: () => { $("conLog").textContent = ""; },
  bench: () => { bench(); },
  // /tilt <yaw> <pitch> <roll> in degrees (to a tenth): the piece in hand turns about its centre (#169); /tilt 0 0 0 squares it
  tilt: (a) => {
    if (a.length !== 3 || !a.every((x) => Number.isFinite(Number(x)))) return conLine(T("cTiltUse", "Usage: /tilt <yaw> <pitch> <roll> in degrees, e.g. /tilt 40 0 15 — /tilt 0 0 0 squares the piece."), "err");
    piece.tilt = a.map(tenths); pieceInfo(); if (bagOpen()) renderBag();
    conLine(T("tiltInfo", "tilt {y}° {p}° {r}°", { y: piece.tilt[0] / 10, p: piece.tilt[1] / 10, r: piece.tilt[2] / 10 }));
  },
  prof: () => { profToggle(); conLine(PROF.on ? T("cProfOn", "Profiler on — ` (the key left of 1) or /prof closes it.") : T("cProfOff", "Profiler off.")); },
};
function conRun(line) {
  const text = String(line || "").trim();
  if (!text) return;
  conHist.push(text); if (conHist.length > 50) conHist.shift(); conHi = conHist.length;
  if (text[0] === "/") {
    const [cmd, ...args] = text.slice(1).split(/\s+/);
    const f = CMDS[cmd.toLowerCase()];
    conLine("> " + text, "me");
    return f ? f(args) : conLine(T("cUnknown", "Unknown command — /help lists them."), "err");
  }
  if (!net.me || !net.online) return conLine(T("cSignIn", "Sign in to chat."), "err");
  net.send({ t: "chat", text: text.slice(0, 200) });
}
function wireConsole() {
  const inp = $("conIn");
  inp.addEventListener("keydown", (e) => {
    // a line sent, back to play: the mouse is captured again (it was left free, and the next click hit the browser's
    // refusal — lockPointer)
    if (e.key === "Enter") { e.preventDefault(); const v = inp.value; conShow(false); conRun(v); if (!touch) lockPointer(); }
    else if (e.key === "Escape") { e.preventDefault(); conShow(false); }
    else if (e.key === "ArrowUp" && conHi > 0) { e.preventDefault(); inp.value = conHist[--conHi]; }
    else if (e.key === "ArrowDown") { e.preventDefault(); conHi = Math.min(conHist.length, conHi + 1); inp.value = conHist[conHi] || ""; }
    e.stopPropagation();
  });
}
/** Capture the mouse for play. The browser refuses it for about a second after the player let it go ("Pointer lock
 *  cannot be acquired immediately after the user has exited the lock") — that refusal came up as an error bar and play
 *  stayed stuck until another click (operator 2026-11-09, chatting on the live page): it is retried once the second has
 *  passed, and never shown. */
function lockPointer() {
  const c = $("world");
  if (!c || document.pointerLockElement === c) return;
  try {
    const r = c.requestPointerLock();
    if (r && r.catch) r.catch(() => setTimeout(() => { if (!document.pointerLockElement && !conOpen) { try { const r2 = c.requestPointerLock(); if (r2 && r2.catch) r2.catch(() => {}); } catch (e) {} } }, 1100));
  } catch (e) {}
}
function wireInput(canvas) {
  wireConsole();
  canvas.addEventListener("click", () => { if (!locked && !touch) lockPointer(); });
  // THE WELCOME CARD, ONCE: it came back every time the mouse was released — after every chat line, every bag — and on a
  // phone it never went at all, since only a captured mouse put it away ("the popup keeps popping up and on mobile it is
  // permanent", "it remains there", operator 2026-11-09, playing on the live page). The first tap, click or key anywhere
  // — or its Play button — puts it away, and this device does not see it again (/help lists the controls).
  const welcome = $("help");
  const away = () => { if (welcome.classList.contains("hidden")) return; welcome.classList.add("hidden"); try { localStorage.setItem(WELCOME_SEEN, "1"); } catch (e) {} };
  try { if (localStorage.getItem(WELCOME_SEEN)) welcome.classList.add("hidden"); } catch (e) {}
  // a press on the card itself is left to the card's own click: hidden on the press, the card was gone before the release,
  // and its Play button never got its click (the live e2e, 2026-11-09)
  for (const ev of ["pointerdown", "touchstart", "keydown"]) document.addEventListener(ev, (e) => { if (!(e.target && e.target.closest && e.target.closest("#help"))) away(); }, { capture: true, passive: true });
  welcome.addEventListener("click", () => { away(); if (!touch) lockPointer(); });
  document.addEventListener("pointerlockchange", () => { locked = document.pointerLockElement === canvas; if (locked) away(); });
  document.addEventListener("mousemove", (e) => {
    if (!locked) return;
    P.yaw += e.movementX * 0.0024 * SET.sens; P.pitch = Math.max(-1.55, Math.min(1.55, P.pitch - e.movementY * 0.0024 * SET.sens * (SET.invert ? -1 : 1)));
  });
  document.addEventListener("mousedown", (e) => { if (!locked) return; if (e.button === 0) { mouseHeld = true; act(false, true); } else if (e.button === 2) act(true); });
  document.addEventListener("mouseup", (e) => { if (e.button === 0) mouseHeld = false; });
  document.addEventListener("contextmenu", (e) => { if (locked) e.preventDefault(); });
  document.addEventListener("wheel", (e) => { if (!locked || !hot.length) return; slot = (slot + (e.deltaY > 0 ? 1 : hot.length - 1)) % hot.length; hotbar(); }, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
    if (!conOpen && e.code === "Slash") { e.preventDefault(); keys.clear(); return conShow(true, "/"); }
    if (!conOpen && (e.code === "Enter" || e.code === "NumpadEnter") && $("palette").classList.contains("hidden")) { e.preventDefault(); keys.clear(); return conShow(true, ""); }
    keys.add(e.code);
    if (/^Digit[1-9]$/.test(e.code) && Number(e.code.slice(5)) <= hot.length) { slot = Number(e.code.slice(5)) - 1; hotbar(); }
    if (e.code === "KeyR") { const i = PRESETS.findIndex((x) => x[0] === piece.w && x[1] === piece.d && x[2] === piece.h); [piece.w, piece.d, piece.h] = PRESETS[(i + 1) % PRESETS.length]; pieceInfo(); }
    if (e.code === "KeyT") turnPiece();
    if (e.code === "KeyQ") useDoor();
    if (e.code === "Backquote") profToggle();                     // the profiler (True Wind's key)
    if (e.code === "KeyX") ignite();
    if (e.code === "KeyV") wardrobe($("wardPanel").classList.contains("hidden"));
    if (e.code === "KeyL") startLevel();
    if (e.code === "KeyG") { piece.shape = ((piece.shape || 0) + 1) % 3; pieceInfo(); }
    if (e.code === "BracketLeft" || e.code === "BracketRight") { const i = SNAPS.indexOf(piece.snap); piece.snap = SNAPS[Math.max(0, Math.min(SNAPS.length - 1, (i < 0 ? 2 : i) + (e.code === "BracketRight" ? 1 : -1)))]; pieceInfo(); }
    if (e.code === "KeyF") { P.fly = !P.fly; P.vh = 0; notify(P.fly ? T("flyOn", "Flying — Space up, C down, Shift fast") : T("flyOff", "Walking"), 1600); }
    if (e.code === "KeyE") palette($("palette").classList.contains("hidden"));
    if (e.code === "Escape") { palette(false); settings(false); }
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
    $("tUse").onclick = () => useDoor();                // Q on a keyboard: a door, a chest, a pilot seat; leave a craft
  }
  $("palClose").onclick = () => palette(false);
  $("chestClose").onclick = () => { $("chestPanel").classList.add("hidden"); chest = null; };
  $("machClose").onclick = () => { $("machPanel").classList.add("hidden"); machine = null; };
  $("deathGo").onclick = () => wakeUp();                // the death card (#162)
  $("npcClose").onclick = () => { $("npcPanel").classList.add("hidden"); talkingTo = null; };
  $("wardClose").onclick = () => wardrobe(false);
  $("setOpen").onclick = () => { palette(false); settings(true); };
  $("setClose").onclick = () => settings(false);
  $("wardOpen").onclick = () => { palette(false); wardrobe(true); };
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
  // the meadow's own colour, varying over tens of metres — lusher, drier, darker patches — so from above it reads as a
  // living field, not one pale wash ("bland untextured marches", operator 2026-11-06)
  const patch = TSL.mx_noise_float(uvw.xy.mul(0.021)).mul(0.5).add(TSL.mx_noise_float(uvw.xy.mul(0.083)).mul(0.25)).add(0.5).clamp(0, 1);
  const meadow = TSL.mix(TSL.vec3(0.46, 0.78, 0.30), TSL.vec3(0.80, 0.86, 0.38), patch).mul(TSL.float(0.82).add(TSL.mx_noise_float(uvw.xy.mul(0.31)).mul(0.12)));
  const color = two(tex[0]).mul(meadow).mul(w1.x).add(two(tex[1]).mul(w1.y)).add(rock.mul(w1.z)).add(two(tex[3]).mul(w1.w))
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
// WATER: lakes and the sea ("bland untextured marches", operator 2026-11-06 — they were a flat 16-px atlas tile). Ripples
// from two scrolling noise fields bend the normal (the sun glints in them), and the colour runs from a deep green-blue
// looking down to the sky's horizon colour at a glancing angle (fresnel), so a lake mirrors the time of day.
const waterSky = new THREE.Color(0xb7d6ef);            // sky() keeps it on the horizon's colour
function waterMaterial() {
  const uvw = TSL.attribute("uvw", "vec3"), t = TSL.time;
  const a = TSL.mx_noise_vec3(TSL.vec3(uvw.x.mul(0.45).add(t.mul(0.18)), uvw.y.mul(0.45), t.mul(0.21)));
  const b = TSL.mx_noise_vec3(TSL.vec3(uvw.x.mul(1.7), uvw.y.mul(1.7).sub(t.mul(0.31)), t.mul(0.37)));
  const n = TSL.normalView.add(a.mul(0.14).add(b.mul(0.07))).normalize();
  const view = TSL.positionView.normalize().negate();
  const fres = TSL.float(1).sub(n.dot(view).clamp(0, 1)).pow(4).mul(0.85).add(0.06);
  const m = new THREE.MeshStandardNodeMaterial({ roughness: 0.05, metalness: 0, transparent: true, depthWrite: false });
  m.normalNode = n;
  m.colorNode = TSL.mix(TSL.color(0x0f3b3f), TSL.uniform(waterSky), fres);
  m.opacityNode = TSL.float(0.78).add(fres.mul(0.2));
  return m;
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

// ---- built pieces in their real materials ("A REAL HOUSE"): the scanned CC0 textures (static/vendor/textures) with their
// normal maps, tiled once per metre (the mesher's uv is in metres). Before, every piece sampled a 16 px atlas tile — the
// blocky look of every house. A material with no scan (wool colours, lamps) keeps its tile (matPieces).
//   block -> [texture, tint, roughness]
const PIECE_TEX = {
  9: ["planks", 1, 0.8], 15: ["darkwood", 1, 0.8], 11: ["brick", 1, 0.9], 14: ["plaster", 1, 0.95], 13: ["tiles", 1, 0.7],
  10: ["cobble", 1, 0.9], 16: ["stonebrick", 1, 0.88], 7: ["bark", 1, 0.95], 31: ["birch", 1, 0.9], 32: ["plaster", 1.08, 0.6],
  37: ["darkwood", 1.15, 0.75], 38: ["planks", 0.78, 0.85], 39: ["thatch", 1, 0.98], 40: ["darkwood", 1.25, 0.7],
  2: ["dirt", 1, 0.95], 3: ["rock", 1, 0.85], 4: ["sand", 1, 0.9], 6: ["snow", 1, 0.55], 17: ["gravel", 1, 0.9],
  // furniture and fittings: joinery in planed planks, a fence in weathered split rails, a torch's charred shaft
  45: ["planks", 0.92, 0.7], 46: ["planks", 0.92, 0.7], 47: ["planks", 0.85, 0.8], 48: ["planks", 0.88, 0.75], 49: ["planks", 0.68, 0.95],
  50: ["darkwood", 1, 0.9], 53: ["planks", 0.75, 0.9], 54: ["planks", 0.95, 0.7],
  // steel (#146): plate in brushed panels; a thruster and a pilot seat in darker steel until flight draws their models
  64: ["steel", 1, 0.38], 65: ["steel", 0.55, 0.45], 66: ["steel", 0.75, 0.5],
  67: ["steel", 0.6, 0.6], 68: ["steel", 0.85, 0.45], 69: ["steel", 0.7, 0.5],
};
const pieceMats = new Map();
function pieceMaterial(blk) {
  if (pieceMats.has(blk)) return pieceMats.get(blk);
  const spec = PIECE_TEX[blk];
  let m = matPieces;
  if (Wd.BLOCKS[blk] && Wd.BLOCKS[blk].glow) {
    // a lamp or a torch's flame gives light rather than taking it: emissive, so the bloom haloes it and it reads at night
    m = new THREE.MeshStandardNodeMaterial({ roughness: 1, metalness: 0 });
    m.colorNode = TSL.vec3(1.0, 0.78, 0.45); m.emissiveNode = TSL.vec3(1.0, 0.62, 0.25).mul(2.4);
  } else if (spec) {
    const [name, tint, rough] = spec;
    m = new THREE.MeshStandardNodeMaterial({ roughness: rough, metalness: 0 });
    const uv = TSL.uv(), col = name === "thatch" ? thatchTexture() : name === "steel" ? steelTexture() : loadTex(name + "_col");
    m.colorNode = TSL.texture(col, uv).rgb.mul(tint).mul(TSL.attribute("color", "vec3"));
    if (name === "steel") m.metalness = 0.55;                                 // metal: it takes the sky's colour a little
    if (name !== "thatch" && name !== "steel") { const nor = loadTex(name + "_nor"); nor.colorSpace = THREE.NoColorSpace; m.normalNode = TSL.normalMap(TSL.texture(nor, uv)); }
  }
  pieceMats.set(blk, m);
  return m;
}
// steel has no scan either: brushed metal in 1 m panels — fine streaks along the grain, darker seams, a rivet at each
// corner — painted once
let steelTex = null;
function steelTexture() {
  if (steelTex) return steelTex;
  const cv = document.createElement("canvas"); cv.width = cv.height = 256;
  const g = cv.getContext("2d");
  g.fillStyle = "#a3abb4"; g.fillRect(0, 0, 256, 256);
  let seed = 91; const R = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < 900; i++) { const y = R() * 256, l = 58 + R() * 16; g.strokeStyle = `hsla(210,8%,${l}%,.35)`; g.lineWidth = 0.6 + R(); g.beginPath(); g.moveTo(0, y); g.lineTo(256, y + (R() - 0.5) * 2); g.stroke(); }
  g.strokeStyle = "#5d646c"; g.lineWidth = 3; g.strokeRect(1.5, 1.5, 253, 253);
  g.fillStyle = "#d4dae0"; for (const x of [12, 244]) for (const y of [12, 244]) { g.beginPath(); g.arc(x, y, 4, 0, Math.PI * 2); g.fill(); }
  steelTex = new THREE.CanvasTexture(cv); steelTex.wrapS = steelTex.wrapT = THREE.RepeatWrapping; steelTex.colorSpace = THREE.SRGBColorSpace;
  return steelTex;
}
// thatch has no scan: bundles of straw painted in layers, each course overlapping the one below
let thatchTex = null;
function thatchTexture() {
  if (thatchTex) return thatchTex;
  const cv = document.createElement("canvas"); cv.width = cv.height = 256;
  const g = cv.getContext("2d");
  g.fillStyle = "#8a6f3a"; g.fillRect(0, 0, 256, 256);
  let seed = 77; const R = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let course = 0; course < 8; course++) for (let i = 0; i < 260; i++) {
    const x = R() * 256, y = course * 32 + R() * 10, len = 24 + R() * 18, l = 42 + R() * 22;
    g.strokeStyle = `hsl(${40 + R() * 10},${45 + R() * 20}%,${l}%)`; g.lineWidth = 1 + R() * 1.5;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x + (R() - 0.5) * 4, y + len); g.stroke();
  }
  thatchTex = new THREE.CanvasTexture(cv);
  thatchTex.wrapS = thatchTex.wrapT = THREE.RepeatWrapping; thatchTex.colorSpace = THREE.SRGBColorSpace; thatchTex.anisotropy = 8;
  return thatchTex;
}

// ---- the picture: ambient occlusion, bloom, anti-aliasing ("overall not impressive", operator 2026-11-06) ---------------
// GTAO from a depth + normal pre-pass darkens what the sky cannot reach — the foot of a wall, the inside of a doorway, the
// ground under a tree — through builtinAOContext, i.e. on INDIRECT light only (the sun's own shadow map handles direct);
// a soft bloom lets the sun and lit glass glow; FXAA smooths edges after tone mapping. A touch device gets the plain
// render: two scene passes are more than a phone's GPU should pay for its first impression.
// COLOUR GRADING ("we need professional color grading too", operator 2026-11-07): a filmic grade on the finished,
// tone-mapped image — a gentle S-curve for contrast, a touch more saturation, split toning (shadows a little cool,
// highlights a little warm, as film and most graded games read daylight) and a soft vignette that draws the eye in.
const GRADE = { sat: 1.12, curve: 0.22, cool: [0.965, 0.99, 1.05], warm: [1.05, 1.0, 0.93], vignette: 0.42 };
function grade(img) {
  const c0 = img.rgb, luma = c0.dot(TSL.vec3(0.2126, 0.7152, 0.0722));
  let c = TSL.mix(TSL.vec3(luma), c0, GRADE.sat);
  const s = c.clamp(0, 1);
  c = TSL.mix(c, s.mul(s).mul(TSL.float(3).sub(s.mul(2))), GRADE.curve);              // the S-curve (smoothstep), blended
  c = c.mul(TSL.mix(TSL.vec3(...GRADE.cool), TSL.vec3(...GRADE.warm), TSL.smoothstep(0.15, 0.85, luma)));
  const d = TSL.screenUV.sub(0.5), vig = TSL.float(1).sub(d.dot(d).mul(GRADE.vignette));
  return TSL.vec4(c.mul(vig), img.a);
}
function buildPipeline() {
  if (pipeline && pipeline.dispose) pipeline.dispose();   // built again when the effects setting changes (#166)
  if (!SET.effects || new URLSearchParams(location.search).has("plain")) return null;   // off: a phone's default
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
    pl.outputColorTransform = false;                       // tone map + sRGB first, grade, then anti-alias the finished image
    pl.outputNode = fxaa(grade(TSL.renderOutput(lit)));
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
  nightH: new THREE.Color(0x0b1424), moonFill: new THREE.Color(0x4a5f8a), dusk: new THREE.Color(0xf0874a), duskZ: new THREE.Color(0x29386d), white: new THREE.Color(0xfff8ee) };
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
  torchNight = 1 - day;
  sun.position.copy(sd).multiplyScalar(150);
  sun.color.setRGB(1, 0.62 + 0.35 * smooth01(0, 0.4, elev), 0.38 + 0.55 * smooth01(0, 0.5, elev));
  sun.intensity = 2.4 * Math.min(1.6, star.flux) * day;
  // shadows only once the sun is well up: at a grazing sun the shadow map streaks the ground (acne), and real dusk
  // shadows are long and faint anyway
  sun.castShadow = elev > 0.12 && !!SET.shadows;
  moon.position.copy(sd).multiplyScalar(-150);
  // A NIGHT YOU CAN FIND YOUR WAY IN: half of every 40-minute day is night, and it was all but black — the ground at
  // 6 of 255 away from the town's lamps, no tree to be found to fell (walking the live page as the town agent,
  // 2026-11-08). Moonlight and a blue sky fill now light it the way a game's night reads: dim, blue, readable.
  moon.intensity = 0.9 * (1 - day);
  hemi.position.copy(up);                                   // three's hemisphere light assumes +Y; here "up" is radial
  hemi.intensity = 1.1 + 1.1 * day;                         // the sky lights what the sun does not reach: a wall in its own
                                                            // shade is dim, never black (the first house render was)
  hemi.color.copy(SKY.moonFill).lerp(SKY.horizon, day);
  const zen = SKY.nightZ.clone().lerp(SKY.zenith, day).lerp(SKY.duskZ, dusk * 0.5);
  const hor = SKY.nightH.clone().lerp(SKY.horizon, day).lerp(SKY.dusk, dusk * 0.6);
  scene.fog.color.copy(hor); waterSky.copy(hor);
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
// the torches nearest the player, re-chosen twice a second from the loaded plots' pieces; [x, y, z] world metres
const TORCH_LIGHTS = PHONE ? 2 : 6, torchLights = [];
// LIGHTS by source: how bright, how far it reaches (m), how much it flickers, and the height of its flame in its piece
// (cm). A lantern lights a yard, a street lamp a street ("townhall disappears after walking 20 meters at night",
// operator 2026-11-07); the pool is given to the sources whose light reaches the player soonest (distance / reach).
const LIGHTS = { torch: { i: 3, d: 9, f: 1, y: 112 }, fire: { i: 3, d: 9, f: 1, y: 0 },
                 lantern: { i: 20, d: 18, f: 0.25, y: 18 }, lamppost: { i: 60, d: 26, f: 0.12, y: 297 } };
let torchNear = [], torchAt = 0, torchNight = 0;
function torchTick(now, cam) {
  if (now - torchAt > 500) {
    torchAt = now;
    const all = [];
    for (const [plot, rec] of plotBoxes) {
      const q = Wd.plotCoords(plot);
      for (const b of rec.list) {
        const kind = b[6] === Wd.B.torch ? "torch" : b[6] === Wd.B.lantern ? "lantern" : b[6] === Wd.B.lamppost ? "lamppost" : null;
        if (!kind) continue;
        const w = Wd.posOf(q.face, q.u0 + (b[0] + b[3] / 2) / Wd.CM, q.v0 + (b[1] + b[4] / 2) / Wd.CM, (b[2] + LIGHTS[kind].y) / Wd.CM);
        all.push([Math.hypot(w[0] - cam[0], w[1] - cam[1], w[2] - cam[2]), w, kind]);
      }
    }
    // a burning cell lights its surroundings as a torch does (#124), from the edits the world server sent
    for (const [k, b] of edits) if (b === Wd.B.fire) {
      const [f, u, v, h] = k.split(":").map(Number);
      if (f !== P.face) continue;
      const w = Wd.posOf(f, u + 0.5, v + 0.5, h + 0.6);
      all.push([Math.hypot(w[0] - cam[0], w[1] - cam[1], w[2] - cam[2]), w, "fire"]);
    }
    torchNear = all.filter((t) => t[0] < LIGHTS[t[2]].d + 40).sort((a, b) => a[0] / LIGHTS[a[2]].d - b[0] / LIGHTS[b[2]].d)
      .slice(0, TORCH_LIGHTS).map((t) => [t[1], LIGHTS[t[2]]]);
  }
  torchLights.forEach((l, i) => {
    const n = torchNear[i];
    // a flame flickers (a lantern's glass steadies it); by day a light is no match for the sun, so it fades in at dusk
    if (!n) { l.intensity = 0; return; }
    const [w, L] = n, flick = 1 + L.f * (0.2 * Math.sin(now / 90 + i * 1.7) + 0.13 * Math.sin(now / 37 + i));
    l.intensity = L.i * flick * (0.15 + 0.85 * torchNight);
    l.distance = L.d;
    l.position.set(w[0] - cam[0], w[1] - cam[1], w[2] - cam[2]);
  });
}
// STATS (/set stats 1, or tap the renderer's name in the corner): frames a second, and what the last frame drew —
// triangles and draw calls — so a slow phone can say what is slow ("very laggy on a phone", 2026-11-08)
let statFrames = 0, statAt = 0;
function statsTick(now) {
  statFrames++;
  if (now - statAt < 1000 && statFrames > 1) return;
  const fps = Math.round((statFrames * 1000) / (now - statAt));
  statFrames = 0; statAt = now;
  const gpu = renderer.backend && renderer.backend.isWebGPUBackend ? "WebGPU" : "WebGL2";
  if (!SET.stats) { $("hudGpu").textContent = gpu; return; }
  const r = renderer.info.render;
  $("hudGpu").textContent = `${gpu} · ${fps} fps · ${Math.round(r.triangles / 1000)}k tris · ${r.drawCalls ?? r.calls} calls · ${chunks.size} chunks`;
}
// ---- THE PROFILER (` the key left of 1, ?prof=1, or /prof; "work on performance, take a hint from true wind", operator
// 2026-11-09 — True Wind's js/profiler.js, "measure performance; don't guess"): where the frame's time goes, live — the
// frame rate over the last 2 s, the frame's work (mean and p99), the ms a frame of every timed part (the frame's own
// parts, the 4-a-second tick's, and the meshes the workers hand back), the rest as "other", and the last frame over
// PROF_LONG ms with its breakdown and how long ago. Closed, it costs nothing: pt() just calls through.
const PROF = { on: false, cur: {}, ring: [], last: null, shown: 0, wall: 0 };
const PROF_WINDOW = 2000, PROF_LONG = 250, PROF_EVERY = 250;
function pt(label, fn) {
  if (!PROF.on) return fn();
  const t0 = performance.now(), r = fn();
  PROF.cur[label] = (PROF.cur[label] || 0) + performance.now() - t0;
  return r;
}
function profFrame(now, workMs) {
  if (!PROF.on) return;
  const dt = PROF.wall ? now - PROF.wall : 0; PROF.wall = now;
  const per = PROF.cur; PROF.cur = {};
  // "other": the frame's own untimed work — the 4-a-second tick and the workers' meshes run between frames, apart
  const timed = ["step", "break", "sky", "aim", "render"].reduce((a, k) => a + (per[k] || 0), 0);
  per.other = Math.max(0, workMs - timed);
  PROF.ring.push({ now, dt, ms: workMs, per });
  while (PROF.ring.length > 1 && now - PROF.ring[0].now > PROF_WINDOW) PROF.ring.shift();
  if (workMs > PROF_LONG || dt > PROF_LONG * 2) PROF.last = { now, ms: workMs, dt, per };
  if (now - PROF.shown > PROF_EVERY) { PROF.shown = now; profShow(now); }
}
function profShow(now) {
  const el = $("prof"), R = PROF.ring;
  if (!el || !R.length) return;
  const wall = R.reduce((a, r) => a + r.dt, 0), ms = R.map((r) => r.ms).sort((a, b) => a - b);
  const mean = ms.reduce((a, b) => a + b, 0) / ms.length, p99 = ms[Math.min(ms.length - 1, Math.ceil(0.99 * ms.length) - 1)];
  const per = {};
  for (const r of R) for (const [k, v] of Object.entries(r.per)) per[k] = (per[k] || 0) + v / R.length;
  const f = (v) => (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2));
  const rows = Object.entries(per).filter(([, v]) => v >= 0.05).sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k.padEnd(9)} ${f(v).padStart(6)} ms ${"▇".repeat(Math.min(30, Math.round((v / Math.max(mean, 1)) * 30)))}`);
  const r = renderer.info.render, last = PROF.last;
  el.textContent = [
    T("profHead", "{f} fps · frame {m} ms (p99 {p}) · {t}k tris · {c} calls", { f: wall > 0 ? (1000 * R.length / wall).toFixed(1) : "–", m: f(mean), p: f(p99), t: Math.round(r.triangles / 1000), c: r.drawCalls ?? r.calls }),
    ...rows,
    last ? T("profLong", "last frame over {n} ms: {t} ms, {s} s ago — {w}", { n: PROF_LONG, t: f(last.ms), s: ((now - last.now) / 1000).toFixed(0),
      w: Object.entries(last.per).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${k} ${f(v)}`).join(", ") }) : "",
  ].join("\n");
}
function profToggle(on = !PROF.on) {
  PROF.on = on; PROF.ring = []; PROF.cur = {}; PROF.wall = 0;
  $("prof").classList.toggle("hidden", !on);
}
function frame(now) {
  if (shotTick(now)) return;
  // REAL TIME, IN STEPS: a frame's time used to be cut to 0.05 s, so below 20 fps the whole game ran in slow motion — a
  // phone at 8 fps walked, fell and broke blocks at 40 % speed ("very laggy on a phone", 2026-11-08; found playing the
  // live page in a software-rendered browser at 2 fps, where nine seconds of walking moved a metre). The body now moves
  // the whole elapsed time in steps of at most STEP_DT, so its collisions stay exact; a stall past FRAME_MAX (a hidden
  // tab, a long pause) is not caught up.
  // A FRAME-RATE CAP (#166, SET.fps): a frame that comes sooner than the cap allows is skipped whole (a little early is
  // let through, or a 60 Hz screen capped at 60 would drop every other frame on its own jitter)
  if (SET.fps && now - lastT < 1000 / SET.fps - 2) return;
  const work0 = performance.now();
  const gap = lastT ? now - lastT : 0;
  const dt = Math.min(FRAME_MAX, (now - lastT) / 1000 || 0); lastT = now;
  govTick(now, gap);                                       // the graphics governor (#166), decided before this frame
  pt("step", () => { for (let left = dt; left > 1e-6; left -= STEP_DT) step(Math.min(STEP_DT, left)); });
  pt("break", () => { breakTick(dt); levelTick(now); });
  const cam = eyePos(), { fr, fw } = look();
  camera.up.set(fr.up[0], fr.up[1], fr.up[2]);
  camera.lookAt(fw[0], fw[1], fw[2]);
  hemi.position.set(fr.up[0], fr.up[1], fr.up[2]);     // "up" is radial on a planet: three's hemisphere light assumes +Y
  for (const c of chunks.values()) if (c.anchor) for (const me of c.meshes) me.position.set(c.anchor[0] - cam[0], c.anchor[1] - cam[1], c.anchor[2] - cam[2]);
  for (const m of [farMesh, farSea, borderMesh]) if (m) { const a = m.userData.anchor; m.position.set(a[0] - cam[0], a[1] - cam[1], a[2] - cam[2]); }
  for (const [id, c] of crafts) if (c.pose) { craftPlace(c.mesh, c.pose, cam); engineFrame(id, c, cam, now); }
  animalsFrame(Math.min(0.1, (now - (frame.lastAnimals || now)) / 1000), cam); frame.lastAnimals = now;
  npcsFrame(cam); arrowsFrame(now, cam); dropsFrame(now, cam);
  for (const r of others.values()) {
    if (!r.p) continue;
    const [f, u, v, h, yaw] = r.p, q = Wd.posOf(f, u, v, h), ofr = Wd.frameOf(f, u, v);
    r.mesh.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    r.mesh.up.set(ofr.up[0], ofr.up[1], ofr.up[2]);
    const fx = Math.sin(yaw) * ofr.east[0] + Math.cos(yaw) * ofr.north[0], fy = Math.sin(yaw) * ofr.east[1] + Math.cos(yaw) * ofr.north[1], fz = Math.sin(yaw) * ofr.east[2] + Math.cos(yaw) * ofr.north[2];
    r.mesh.lookAt(r.mesh.position.x + fx, r.mesh.position.y + fy, r.mesh.position.z + fz);
  }
  pt("sky", () => { sky(fr); torchTick(now, cam); });
  // the aimed block's outline
  const a = pt("aim", () => aim());
  // a cell's outline, or the piece's own box; and where the chosen piece would go (green: it fits, red: it does not)
  const frameBox = (obj, plot, b) => {
    const q = Wd.plotCoords(plot), cx = q.u0 + (b[0] + b[3] / 2) / Wd.CM, cz = q.v0 + (b[1] + b[4] / 2) / Wd.CM, cy = (b[2] + b[5] / 2) / Wd.CM;
    const c = Wd.posOf(P.face, cx, cz, cy);
    obj.position.set(c[0] - cam[0], c[1] - cam[1], c[2] - cam[2]);
    obj.up.set(fr.up[0], fr.up[1], fr.up[2]);
    obj.lookAt(obj.position.x + fr.north[0], obj.position.y + fr.north[1], obj.position.z + fr.north[2]);
    // a turned piece (#169): the outline turns with it — its width along its turned east, its height along its turned up
    if (Wd.isTurned(b)) obj.quaternion.copy(turnQuat(b, (v) => [0, 1, 2].map((i) => fr.east[i] * v[0] + fr.north[i] * v[1] + fr.up[i] * v[2])));
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
  // a block of earth, stone, sand…: the cell it goes into, outlined before the tap (aim → placeCell), green where it goes
  // and red where it cannot ("impossible to judge what will happen upon placing a block", operator 2026-11-08). The cell
  // is also written on the page (data-place) — what a test, or a screen reader, can read back.
  let shown = "";
  if (a && a.prev && id && NATURAL_ITEMS.has(id) && net.me) {
    const [cu, cv, ch] = a.prev, cp = Wd.plotOf(P.face, cu, cv), q = Wd.plotCoords(cp);
    frameBox(ghost, cp, [(cu - q.u0) * Wd.CM, (cv - q.v0) * Wd.CM, ch * Wd.CM, Wd.CM, Wd.CM, Wd.CM]);
    const go = roomFor(a.prev) && rootsIn(a.prev) && (ch < 0 || mayBuild(cp));
    ghost.material.color.setHex(go ? 0x33dd77 : 0xdd4433);
    shown = `${cu},${cv},${ch}${go ? "" : ",no"}`;
  }
  if (document.body.dataset.place !== shown) document.body.dataset.place = shown;
  pt("render", () => { if (pipeline) pipeline.render(); else renderer.render(scene, camera); });
  statsTick(now);                                         // after the draw: what this frame drew
  profFrame(now, performance.now() - work0);
}
let tick = 0;
// ---- OWNERSHIP BORDERS ("there should be some kind of a visual cue marking the ownership borders", operator 2026-11-07):
// every titled plot around the player is outlined on the ground just inside its edges, in the colour of whose it is —
// yours green, one you were invited to build on blue, one for sale gold, anyone else's orange (titled, owner not yet
// known: grey). Wilderness has none. The line follows the drawn ground and rides over pieces (a street slab), so it is
// seen where it runs. On by default (/set borders 0 hides it). Photo mode outlines only the plot it photographs (#127).
const BORDER = { mine: 0x3ddc84, build: 0x4aa3ff, sale: 0xffd24a, owned: 0xff8a3d, titled: 0xbdbdbd, shot: 0xfff1b0 };
const BORDER_R = 3;                                         // plots around the player's that show their borders
let borderMesh = null, borderOwn = "", borderSig = "", borderAt = 0;
function borderKind(plot) {
  if (SHOT !== null) return plot === SHOT ? "shot" : null;
  const t = titles.get(plot);
  if (!t) return null;
  if (mine.has(plot) || (t.sale && t.sale.seller && t.sale.seller === (net.me || dapp.me))) return "mine";
  if (t.sale) return "sale";
  if (builds.has(plot)) return "build";
  return t.holder ? "owned" : "titled";
}
function pieceTopAt(plot, x, z) {                          // the highest piece over a point of a plot (cm in the plot), m
  const rec = plotBoxes.get(plot);
  let top = -Infinity;
  if (rec) for (const b of rec.list)
    if (x >= b[0] && x < b[0] + b[3] && z >= b[1] && z < b[1] + b[4]) top = Math.max(top, (b[2] + b[5]) / Wd.CM);
  return top;
}
/** The drawn ground's height at (face, u, v): the smooth field's zero crossing — never a tree trunk, a built block or a
 *  player (a border followed groundAt up every trunk on its line). */
function earthAt(f, u, v) {
  let h = Wd.column(f, Math.floor(u), Math.floor(v)).height;
  const inside = (y) => fieldAt(f, u, v, y) > 0;
  let a, b;
  if (inside(h)) { a = h; b = h + 0.25; while (inside(b) && b < h + 40) { a = b; b += 0.25; } }
  else { b = h; a = h - 0.25; while (!inside(a) && a > h - 64) { b = a; a -= 0.25; } }
  for (let n = 0; n < 6; n++) { const m = (a + b) / 2; if (inside(m)) a = m; else b = m; }
  return b;
}
function updateBorders() {
  if (!scene) return;
  const on = SHOT !== null || SET.borders;
  const w = Wd.wrap(P.face, Math.floor(P.u), Math.floor(P.v)), here = Wd.plotCoords(Wd.plotOf(w.face, w.u, w.v));
  const list = [];
  if (on) for (let dr = -BORDER_R; dr <= BORDER_R; dr++) for (let dc = -BORDER_R; dc <= BORDER_R; dc++) {
    const r = here.prow + dr, c = here.pcol + dc;
    if (r < 0 || c < 0 || r >= Wd.FACE_N || c >= Wd.FACE_N) continue;
    const p = Wd.plotId(here.face, r, c), t = titles.get(p);
    if (t && SHOT === null && !mine.has(p) && !t.asked) { t.asked = true; holderOf(p).then(() => { borderOwn = ""; }); }   // whose it is: its colour
    const k = borderKind(p);
    if (k) list.push([p, k, (plotBoxes.get(p) || { list: [] }).list.length, (plotEdit.get(p) || new Map()).size]);
  }
  // where they are and whose — re-drawn at once when that changes; a build changing the ground under them, at most
  // every 2 s
  const own = here.face + ":" + here.prow + ":" + here.pcol + "|" + list.map((x) => x[0] + ":" + x[1]).join(","), sig = list.map((x) => x.join(":")).join(",");
  if (own === borderOwn && (sig === borderSig || performance.now() - borderAt < 2000)) return;
  borderOwn = own; borderSig = sig; borderAt = performance.now();
  if (borderMesh) { scene.remove(borderMesh); borderMesh.geometry.dispose(); borderMesh = null; }
  if (!list.length) return;
  const anchor = Wd.posOf(here.face, here.u0, here.v0, Wd.SEA), pos = [], col = [], idx = [];
  const wd = SHOT !== null ? 0.18 : 0.09, e = 0.04, STEP_M = 0.5;
  for (const [p, k] of list) {
    const q = Wd.plotCoords(p), c = new THREE.Color(BORDER[k]);
    const at = (u, v) => {
      const g = earthAt(q.face, u, v), t = pieceTopAt(p, (u - q.u0) * Wd.CM, (v - q.v0) * Wd.CM);
      return Math.max(g, t) + 0.04;
    };
    const edges = [[[q.u0 + e, q.v0 + e], [1, 0], [0, 1], [-1, 0]], [[q.u0 + 16 - e, q.v0 + e], [0, 1], [-1, 0], [0, 1]],
                   [[q.u0 + 16 - e, q.v0 + 16 - e], [-1, 0], [0, -1], [1, 0]], [[q.u0 + e, q.v0 + 16 - e], [0, -1], [1, 0], [0, -1]]];
    // no border between two plots of one holder: their edge is no border at all (the town's four plots draw one outline,
    // not a double line down the middle of its street)
    const holder = (titles.get(p) || {}).holder;
    for (const [[u0, v0], [du, dv], [iu, iv], [nr, nc]] of edges) {
      const n = q.prow + nr >= 0 && q.pcol + nc >= 0 && q.prow + nr < Wd.FACE_N && q.pcol + nc < Wd.FACE_N ? Wd.plotId(q.face, q.prow + nr, q.pcol + nc) : -1;
      // (plots on sale keep each their own: the market escrows them all, and a buyer needs to see each one's edges)
      if (SHOT === null && k !== "sale" && holder && n >= 0 && (titles.get(n) || {}).holder === holder && borderKind(n) === k) continue;
      for (let s0 = 0; s0 < 16 - 2 * e - 1e-6; s0 += STEP_M) {
        const s1 = Math.min(16 - 2 * e, s0 + STEP_M), n = pos.length / 3;
        for (const [ss, inn] of [[s0, 0], [s1, 0], [s1, wd], [s0, wd]]) {
          const u = u0 + du * ss + iu * inn, v = v0 + dv * ss + iv * inn, x = Wd.posOf(q.face, u, v, at(u0 + du * ss, v0 + dv * ss));
          pos.push(x[0] - anchor[0], x[1] - anchor[1], x[2] - anchor[2]); col.push(c.r, c.g, c.b);
        }
        idx.push(n, n + 1, n + 2, n, n + 2, n + 3);
      }
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  borderMesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85, depthWrite: false, side: THREE.DoubleSide }));
  borderMesh.userData.anchor = anchor;
  borderMesh.renderOrder = 2;
  scene.add(borderMesh);
}
function slow() {
  pt("chunks", updateChunks);
  pt("borders", updateBorders);
  pt("net", netTick);
  if (!farAt || farAt.face !== P.face || Math.abs(farAt.u - P.u) > 400 || Math.abs(farAt.v - P.v) > 400) pt("far", buildFar);
  pt("hud", hud);                                          // (4 a second; flying, its line too)
  if (++tick % 20 === 0) save();
}

// ---- PHOTO MODE (#125, "the land plot should have a screenshot attached like in a realtor ad"): ?shot=<plot> shows the
// plot as an aerial photo — from off its south-west corner, 16 m up, at the moment the sun stands highest over it — with
// nothing of the page on it, and says "shot-ready" in the title once the world around it has meshed and settled. The
// world server photographs plots this way (scripts/land_shot.mjs) for their market listing.
const SHOT = (() => { const s = new URLSearchParams(location.search).get("shot"); return s && /^\d{1,10}$/.test(s) && Number(s) < Wd.PLOT_MAX ? Number(s) : null; })();
let shotBusyAt = 0, shotFrames = 0;
function shotSetup() {
  const q = Wd.plotCoords(SHOT), cu = q.u0 + 8, cv = q.v0 + 8, top = Wd.column(q.face, cu, cv).top;
  P.face = q.face; P.u = q.u0 - 7; P.v = q.v0 - 11; P.h = top + 16; P.fly = true; P.vh = P.vu = P.vv = 0;
  P.yaw = Math.atan2(cu - P.u, cv - P.v);
  P.pitch = -Math.atan2(P.h + EYE - top, Math.hypot(cu - P.u, cv - P.v));
  const up = Wd.frameOf(q.face, cu, cv).up, now = Date.now() / 1000;
  let best = now, high = -2;
  for (let k = 0; k < 120; k++) {
    const t = now + (k * Cosmos.DAY_S) / 120, d = Cosmos.sunFrom(Wd.PLANET, t - Cosmos.EPOCH).dir, e = d[0] * up[0] + d[1] * up[1] + d[2] * up[2];
    if (e > high) { high = e; best = t; }
  }
  const real = Date.now.bind(Date), off = best * 1000 - real();
  Date.now = () => real() + off;                     // the plot's noon (the photo takes a minute; the sun barely moves)
  document.body.classList.add("shot");
  viewDist = 3;                                      // the plot and its neighbours in full; the far land draws the rest
}
// true = skip drawing this frame: until the world has meshed and stayed settled 4 s nothing is drawn — a headless
// browser draws in software, and every frame drawn while loading only slowed the meshing (a photo took ~10 minutes)
function shotTick(now) {
  if (SHOT === null || document.title === "shot-ready") return false;
  if (queue.length || inflight.size || !chunks.size) { shotBusyAt = now; return true; }
  if (now - shotBusyAt < 4000) return true;
  if (++shotFrames > 3) document.title = "shot-ready";             // a few frames drawn first: shaders compiled, shadows cast
  return false;
}
// ---- start -----------------------------------------------------------------------------------------------------
async function start() {
  load();
  viewDist = SET.view;                                      // the view distance setting (#166); a photo shot takes its own
  if (SHOT !== null) shotSetup();
  RULES = await (await fetch("/static/land-recipes.json", { cache: "no-cache" })).json();
  const canvas = $("world");
  renderer = new THREE.WebGPURenderer({ canvas, antialias: true });
  renderer.setPixelRatio(basePR() * SET.res / 100);          // render resolution (#166): a share of the screen's pixels
  renderer.setSize(innerWidth, innerHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;            // r187's WebGPU renderer has no PCFSoftShadowMap
  await renderer.init();
  $("hudGpu").textContent = renderer.backend && renderer.backend.isWebGPUBackend ? "WebGPU" : "WebGL2";
  $("hudGpu").onclick = () => { SET.stats = SET.stats ? 0 : 1; saveSet(); };
  scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xb7d6ef, viewDist * CHUNK * 0.9, 2900);
  camera = new THREE.PerspectiveCamera(SET.fov, innerWidth / innerHeight, 0.08, 4000);
  camera.position.set(0, 0, 0);
  sun = new THREE.DirectionalLight(0xfff4e0, 3);
  Object.assign(sun.shadow.camera, { near: 10, far: 320 });
  shadowQuality();                                          // map size and reach by SET.shadows (#166); off: medium's, unused
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.04;
  scene.add(sun, sun.target);                               // the target stays at the origin: the player
  moon = new THREE.DirectionalLight(0x8fa8d8, 0.3); scene.add(moon, moon.target);
  hemi = new THREE.HemisphereLight(0xcfe8ff, 0x5a4a38, 0.9); scene.add(hemi);
  scene.add(new THREE.AmbientLight(0x8090b0, 0.45));      // a night is dark, never black
  // torchlight: a FIXED pool of warm point lights given to the torches nearest the player (a changing light count would
  // recompile every material); unused ones sit at intensity 0
  for (let i = 0; i < TORCH_LIGHTS; i++) { const l = new THREE.PointLight(0xffa04a, 0, 9, 2); torchLights.push(l); scene.add(l); }
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
  matWater = waterMaterial();
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
  // GLASS ("windows on the house look weird": a flat blue tile with its frame lines): clear, faintly green-grey, and more
  // of a mirror the more glancing the view (fresnel), so a pane shows the room behind it head-on and the sky at an angle
  // FIRE (#124): flames are light, not lit — additive, both sides, fading from a white-yellow base to red tips, flickering
  // at each cell's own phase (the colour's red channel, land-mesher.js) and licking sideways as they rise
  matFlame = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending });
  {
    const uv = TSL.uv(), ph = TSL.attribute("color", "vec3").x.mul(6.283), t = TSL.time;
    const flick = TSL.sin(t.mul(13).add(ph)).mul(0.25).add(TSL.sin(t.mul(7.3).add(ph.mul(1.7))).mul(0.2)).add(0.75);
    // tongues: the flame's width wavers up its height, so it reads as licking flames rather than a smooth cone; the
    // colour is a saturated orange (a white-hot additive washed out under the bloom — the first fire render)
    const tongue = TSL.sin(uv.y.mul(9).sub(t.mul(7)).add(ph)).mul(0.18).add(TSL.sin(uv.y.mul(17).sub(t.mul(11)).add(ph.mul(2.3))).mul(0.08));
    const tip = TSL.float(1).sub(uv.y), body = TSL.float(1).sub(uv.x.sub(0.5).add(tongue.mul(uv.y)).abs().mul(2.2).pow(1.4)).clamp(0, 1);
    const a = tip.pow(1.5).mul(body).mul(flick);
    matFlame.colorNode = TSL.mix(TSL.vec3(1.0, 0.62, 0.16), TSL.vec3(0.85, 0.16, 0.02), uv.y.pow(0.6)).mul(a.mul(0.9));
    matFlame.opacityNode = a;
    matFlame.positionNode = TSL.positionLocal.add(TSL.vec3(TSL.sin(t.mul(5).add(ph).add(uv.y.mul(4))).mul(uv.y.mul(0.08)), 0, 0));
  }
  matGlassy = new THREE.MeshStandardNodeMaterial({ roughness: 0.04, metalness: 0, transparent: true, depthWrite: false });
  const glassView = TSL.positionView.normalize().negate(), glassFres = TSL.float(1).sub(TSL.normalView.dot(glassView).abs()).pow(3);
  matGlassy.colorNode = TSL.mix(TSL.vec3(0.70, 0.78, 0.80), TSL.uniform(waterSky), glassFres.mul(0.8)).mul(shade);
  matGlassy.opacityNode = TSL.float(0.16).add(glassFres.mul(0.62));
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
  try { if (new URLSearchParams(location.search).get("prof") === "1") profToggle(true); } catch (e) {}
  renderer.setAnimationLoop(frame);
  // the first-run benchmark (#166): a device that never chose its graphics measures them once, a little after it starts
  if (SHOT === null && !SET_CHOSEN && !benchLast() && !/HeadlessChrome/.test(navigator.userAgent)) setTimeout(bench, 15000);
  connect();
  $("loading").classList.add("hidden");
  try { await dapp.init(); } catch (e) { alertBar(T("cryptoFail", "The wallet bundle failed to load — reload to sign in.")); return; }
  wireWallet(dapp, () => { renderWallet(dapp); refreshTitles(); });
  renderWallet(dapp);
  refreshTitles();
  setInterval(refreshTitles, 30000);
}
dapp.onReturn((pend, ok, err, err2) => {
  dapp.showReturn(pend, ok, err, { anchor: T("anchorSent", "Anchoring — confirming…"), allow: T("inviteSent", "Invitation sent — confirming…"),
    list: T("sellSent", "Listed — confirming…"), reprice: T("repriceSent", "New price sent — confirming…"), unlist: T("unlistSent", "Taking it off sale — confirming…") });
  listingCache.clear();                                    // a sale call just changed the market: read it again
  refreshTitles();
});
start().catch((e) => {
  $("loading").textContent = T("noGpu", "This browser cannot draw the planet ({e}). Try a current Chrome, Edge, Firefox or Safari.", { e: String(e && e.message || e) });
});
