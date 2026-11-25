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
// every "/static/…" and "./…" import with the file's version and leaves bare names alone: a path here became a
// versioned three.webgpu.js while the add-ons' "three/webgpu" stayed three.webgpu.js — two URLs, two module instances, two TSL node stacks, and
// the page drew nothing ("pitch black", 2026-11-06; THREE.TSL "Cannot read properties of null (reading 'If')").
// tests/test_the_land_page_loads_one_copy_of_three.py serves the page through the real stamper and pins this.
import * as THREE from "three/webgpu";
import * as TSL from "three/tsl";
// r187's post-processing add-ons (static/vendor/three/addons, pinned like the core); they import "three/webgpu" and
// "three/tsl", which land.html's import map points at the same vendored files
import { ao } from "three/addons/tsl/display/GTAONode.js";
import { bloom } from "three/addons/tsl/display/BloomNode.js";
import { fxaa } from "three/addons/tsl/display/FXAANode.js";
import { CSMShadowNode } from "three/addons/csm/CSMShadowNode.js";   // the sun's shadow in cascades, out to the meadow (#183 step 4)
import * as Wd from "./land-world.js";
import * as Shapes from "./land-shapes.js";
import * as Cosmos from "./land-cosmos.js";
import * as Planet from "./land-planet.js";
import { walk, trunkAt, TRUNK_R, restorePlace } from "./land-walk.js";
import { snapBox, piecesFor, restOnGround, attachTo } from "./land-snap.js";
import { levelOps, earthNeeded, trunkIn, siteLayer, topFirst } from "./land-level.js";
import * as Far from "./land-far.js";
import * as Forest from "./land-forest.js";
import * as Clouds from "./land-clouds.js";
import { treeModel } from "./land-trees.js";
import { craftStep, flightOf, craftBody, bodyInside, navSays, craftArea, craftFeet, restAt, aeroOf, axesOf, tiltDir, stallSpeed, stepOffSpot, surfaceBelow} from "./land-flight.js";
import { Sound, windLevel } from "./land-sound.js";
import { GFX_PRESETS, BENCH_ORDER, benchTarget, frameStats, holds, pickPreset, LADDER, governor, govStep } from "./land-gfx.js";
import { NadoDapp, wireWallet, renderWallet, alertBar, notify, okBar, uiConfirm, uiPrompt, isAddress, esc, base, disp, rawToNado, nadoToRaw, randId, $ } from "./nadodapp.js";

const CID = "e7dfe9aa3cbb4b0c9293caeaf992a041";      // the land title contract (deployed 2026-11-07, scripts/land_first_wave.py); redeploy.py wire() repoints it
const ISSUER = "3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f";   // land.py ISSUER — every title's issuer
/** "Owned by …": the town's own four plots (their holder is the issuer itself) say so, not the issuer's address — a
 *  newcomer's first screen read "Owned by 3cc4c4…3572f" over the square (playtest 2026-11-16) */
const ownedBy = (holder) => holder === ISSUER ? T("ownedTown", "Owned by the town") : T("owned", "Owned by {o}", { o: disp(holder) });
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
// THE EVENT TRACE (#194; operator 2026-11-12: "i hope there is tracing so you can trace these events back to the root
// cause. if not, add them"): what happened to this player and why — boarding and leaving a craft with both poses,
// every move of the body the player did not make (pos_fix, craft_fix, waking), hurt and death, the socket going,
// every page error — the last TRACE_MAX kept here (/trace prints them) and sent to the world server, which keeps a
// bounded file a player (scripts/land_trace.py <address>). Nothing goes unlogged (True Wind's rule).
const TRACE = { ring: [], pending: [], max: 500, sentAt: 0 };
function trace(kind, data) {
  const e = { t: Date.now(), k: kind, ...(data || {}) };
  TRACE.ring.push(e); if (TRACE.ring.length > TRACE.max) TRACE.ring.shift();
  TRACE.pending.push(e); if (TRACE.pending.length > 200) TRACE.pending.shift();
  return e;
}
// FRAME RATE FROM REAL PLAYERS (2026-11-23, "smooth user experience": the server renders in software — its frame times
// say nothing of a player's GPU, and every claim about smoothness was a guess): once a minute a playing page traces its
// frame rate as the player saw it — the mean, the 95th-percentile frame and the worst, with the renderer, the view
// preset, the resolution scale and the screen — so it is read from trace/<address>.jsonl, not guessed. A gap over a
// second (a hidden tab, a breakpoint) is no frame.
// WHERE A LONG FRAME WENT (2026-11-24): the first traces held minutes at a p95 of 300 ms on a GPU that drew Ultra at 90 fps
// the hour before — not the graphics, and nothing said what. Every part the profiler times (pt) is timed always, a few
// clock reads a frame; a frame over PERF_LONG ms adds what ran since the one before it, part by part, and "rest" what no
// part holds (the GPU, a garbage collection, the browser), and the minute's trace carries the count and the top parts.
const PERF = { last: 0, at: 0, dts: [], cur: {}, long: 0, in: {} }, PERF_EVERY = 60000, PERF_GAP = 1000, PERF_LONG = 100;
function perfSample(now) {
  const gap = PERF.last ? now - PERF.last : 0;
  if (PERF.last && gap < PERF_GAP) PERF.dts.push(gap);
  if (gap >= PERF_LONG && gap < PERF_GAP) {
    PERF.long++;
    // THE BENCHMARK'S OWN FRAMES (2026-11-25): the first real trace's first minute held 18 long frames, worst 842 ms, 5.4 s of it
    // "rest" — while the first-run benchmark (bench, 15 s in) cycles presets and each switch compiles new shaders. Its frames are
    // counted as "bench", so a trace tells a one-time measurement from a stutter a player keeps meeting.
    if (typeof benching !== "undefined" && benching) { PERF.in.bench = (PERF.in.bench || 0) + gap; PERF.cur = {}; PERF.last = now; if (!PERF.at) PERF.at = now; return null; }
    let timed = 0;
    for (const [k, v] of Object.entries(PERF.cur)) { PERF.in[k] = (PERF.in[k] || 0) + v; timed += v; }
    PERF.in.rest = (PERF.in.rest || 0) + Math.max(0, gap - timed);
  }
  PERF.cur = {};
  PERF.last = now;
  if (!PERF.at) PERF.at = now;
  if (now - PERF.at < PERF_EVERY || PERF.dts.length < 30) return null;
  const d = PERF.dts.slice().sort((x, y) => x - y), mean = d.reduce((x, y) => x + y, 0) / d.length;
  const top = Object.fromEntries(Object.entries(PERF.in).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k, v]) => [k, Math.round(v)]));
  const long = PERF.long;
  PERF.at = now; PERF.dts = []; PERF.long = 0; PERF.in = {};
  const gpu = (typeof document !== "undefined" && document.getElementById("hudGpu") || {}).textContent || "";
  return trace("perf", { fps: +(1000 / mean).toFixed(1), p95: +d[Math.floor(d.length * 0.95)].toFixed(1), worst: +d[d.length - 1].toFixed(1), n: d.length,
    gpu, view: SET.view, res: SET.res, px: [innerWidth, innerHeight, +devicePixelRatio.toFixed(2)], long, in: top });
}
const tracePose = (p) => (p ? p.slice(0, 7).map((x, i) => (i ? +Number(x).toFixed(2) : x)) : null);
window.addEventListener("error", (e) => trace("error", { msg: String(e.message || e).slice(0, 300), src: String(e.filename || "").slice(-60), line: e.lineno }));
window.addEventListener("unhandledrejection", (e) => trace("error", { msg: String(e.reason && e.reason.message || e.reason).slice(0, 300) }));
const GRAV = 26, JUMP = 8.4, WALK = 4.6, RUN = 7.5, FLY = 14, FLY_FAST = 60;   // (#170: FLY and FLY_FAST are GAME RULES — free flight is a builder's convenience, its speed chosen for play)

// ---- state ------------------------------------------------------------------------------------------------------
const P = { face: Wd.SPAWN_FACE, u: 0, v: 0, h: 0, yaw: 0, pitch: -0.15, vu: 0, vv: 0, vh: 0, fly: false, ground: false };
const edits = new Map();              // "face:u:v:h" -> block id: every known edit (mine and, with the server, everyone's)
const plotEdit = new Map();           // plot -> Map(local key "x:z:y" -> block)
const plotList = new Map();           // plot -> [[key, block], …] for the mesher's jobs (editsFor: made once a plot)
const titles = new Map();             // plot -> { aid, holder } for every issued title
const mine = new Set();               // plots whose title the signed-in address holds
const builds = new Set();             // plots the world server says the signed-in address was invited to build on
const builderKnown = new Set();       // plots whose builder answer is in — until then a refusal says "checking", not "someone else's"
let titlesVer = 0, titlesSig = "";       // the titles' version: 0 until the first answer is in (hud, sourceHint); bumped when they change
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
let piece = { w: 100, d: 100, h: 100, snap: 10, shape: 0, rot: 0, tilt: [0, 0, 0], part: 0, mirror: false, attach: false };   // shape: 0 box, 1 slope, 2 stairs (G cycles; T turns); tilt: yaw, pitch, roll in tenths of a degree (#169); part: a land-shapes.js shape byte, 0 for none (#175)
const plotBoxes = new Map();          // plot -> { list, idx: Map(1 m bucket -> [box]) }
let pipeline = null;                  // the post-processed render (or null: the plain render on a weak device)
let renderer, scene, camera, sun, hemi, atlasTex, matSolid, matClear, matGround, matTrees, matPieces, matGlassy, matBark, matLeaves, matWater, matFlame, matSmoke, ghost, ghost2, farMesh = null, farAt = null;
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
  // #173, colours measured off photographs (land research ore/OBSERVED.md): magnetite dark grey with fine metallic glints
  // (median #596565, glints #c3c5c0); lodestone near-black and dull (median #16160a) with rust specks and iron filings
  // caught on it. Given as the hex that STORES as the measured colour: THREE.Color takes a hex as sRGB and paintAtlas
  // writes its linear value, so "#596565" painted as #2c3434 — reviewed side by side with the photos, 2026-11-10.
  54: ["#9fa9a9", 0.12, "magnetite"], 55: ["#535338", 0.1, "lodestone"],
  56: ["#3b3f45", 0.06, "navunit"],
  57: ["#8a96a3", 0.06, "electrolyser"], 58: ["#d6dde4", 0.05, "liquefier"],
  59: ["#3a3d42", 0.08, "rocketengine"], 60: ["#e8e4dc", 0.05, "proptank"], 61: ["#c9b26a", 0.06, "satellite"], 62: ["#7c7f84", 0.1, "launchpad"],
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
      if (kind === "magnetite" && rnd() < 0.16) col = new THREE.Color("#e3e4e1").multiplyScalar(0.8 + 0.4 * rnd());   // fine metallic glints (#c3c5c0 stored)
      if (kind === "lodestone" && rnd() < 0.07) col = new THREE.Color("#93765d").multiplyScalar(k);                    // rust specks
      if (kind === "lodestone" && ((x - y === 3 && x > 4 && x < 11) || (x + y === 20 && x > 8 && x < 14))) col = new THREE.Color("#dad8ce").multiplyScalar(k);   // filings caught on it
      if (kind === "thruster" && Math.hypot(x - 7.5, y - 7.5) < 4.5) col = new THREE.Color("#ff8a3a").multiplyScalar(k * (1.3 - Math.hypot(x - 7.5, y - 7.5) / 7));   // the nozzle's glow
      if (kind === "seat" && y < 7 && x > 2 && x < 13) col = new THREE.Color("#6fd3e8").multiplyScalar(k * 0.9);             // the canopy glass
      if (kind === "smelter" && y > 8 && y < 13 && x > 4 && x < 11) col = new THREE.Color("#ff7a2a").multiplyScalar(k * 1.2);   // its mouth, glowing
      if (kind === "assembler" && (x === 7 || y === 7)) col = new THREE.Color("#e8c547").multiplyScalar(k);                   // a hazard cross
      if (kind === "generator" && Math.hypot(x - 7.5, y - 7.5) < 3) col = new THREE.Color("#6fe39a").multiplyScalar(k * 1.1);  // a green lamp
      if (kind === "electrolyser" && (x === 4 || x === 11) && y > 2 && y < 13) col = new THREE.Color("#c87533").multiplyScalar(k);   // two copper electrodes
      if (kind === "liquefier" && (y === 4 || y === 8 || y === 12) && x > 1 && x < 14) col = new THREE.Color("#7fb8e0").multiplyScalar(k);   // frosted coils
      if (kind === "rocketengine" && Math.hypot(x - 7.5, y - 9) < 4.5) col = new THREE.Color(Math.hypot(x - 7.5, y - 9) < 2.5 ? "#2a2a2a" : "#9a6a44").multiplyScalar(k);   // its bell
      if (kind === "proptank" && y % 5 === 0) col = new THREE.Color("#c8c2b6").multiplyScalar(k);                     // its weld seams
      if (kind === "satellite" && (x < 4 || x > 11)) col = new THREE.Color("#2a3f7a").multiplyScalar(k * (y % 3 ? 1 : 0.7));   // solar panels
      if (kind === "launchpad" && (x + y) % 6 === 0) col = new THREE.Color("#e8c547").multiplyScalar(k);                // hazard stripes
      if (kind === "navunit" && x > 2 && x < 13 && y > 3 && y < 11) col = new THREE.Color(Math.abs(x - 7.5) + Math.abs(y - 7) < 2 ? "#9cf2b4" : "#1f4a32").multiplyScalar(k);   // its display, a mark at its centre
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
  plotBoxes.set(plot, { list, idx: indexBoxes(list), gadgets: old && old.gadgets || {} }); topSeq++;   // (the gadgets' keys stay)
  // a ?plot= link stood the player half a metre inside this plot before its pieces were known (linkPlace): standing in
  // one of them now, they step out over the south edge, onto the ground (its edits are applied just before this)
  if (linkArrive === plot) {
    linkArrive = null;
    if (collides(P.u, P.v, P.h)) { P.v = Wd.plotCoords(plot).v0 - 1.5; P.h = groundAt(P.face, P.u, P.v); save(); }
  }
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
// CLOUD SHADOWS (#183 step 4, "soft long shadows", the far ground mottled in the concept picture): a map of Clouds.sunLit
// over the ground round the player — each texel how much of the sun the layer lets through to that point, the reference's
// own formula marched on the GPU (buildClouds: shadowFn) — rendered every CLOUD_SHADOW_MS, or once the eye has moved an
// eighth of its span, and read by every lit material of the land (shadeByClouds) as mix(1, lit, share): share is the
// sun's part of the light on level ground this frame (sky()), so under a thick heap the sun's part goes and the sky's
// stays, and in the clear nothing changes. The sun's intensity itself is no longer dimmed for the player's own spot: the
// shadows move over the land as the clouds drift, and a field a kilometre off is sunlit while the player stands in shade.
// NOT in it: the sun's cast shadows (the shadow map's box) do not fade under a cloud; the map is flat over its span (the
// planet drops 54 m across 6 km: a shadow's edge is placed to a few metres, finer than a heap's 150 m).
// 512 a side (2026-11-25, was 256): 12 m a texel. The heaps went from a median 250 m across to 140 m, and at 23 m a texel
// a heap's dark core was a few texels the filter smeared into the sun round it (the shadow walk read 1.121 where it should
// darken). 512² texels × 8 samples every 1.5 s is still a small pass.
const CLOUD_SHADOW_N = 512, CLOUD_SHADOW_SPAN = 6000, CLOUD_SHADOW_MS = 1500;   // texels a side; m a side; ms between renders
const shadowBlank = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1); shadowBlank.needsUpdate = true;   // until the first map: full sun
const shadowO = { share: TSL.uniform(0), shift: TSL.uniform(new THREE.Vector3()), east: TSL.uniform(new THREE.Vector3(1, 0, 0)), north: TSL.uniform(new THREE.Vector3(0, 0, 1)) };
const shadowTex = [];                                        // every material's texture node of the map (its value is swapped in once the map exists)
// LEAVES LIT THROUGH (#183 step 4, "leaves lit through (translucency) instead of black cores"): a leaf is no shutter. It
// absorbs ~85 % of the light between 400 and 700 nm and reflects ~10 % (Golden Delicious sun and shade leaves, mean
// absorptance > 85 % over 400–700 nm), and lets the rest through — whole apple leaves up to 2 % of the incident PAR
// (Notton & Blanke 1992, Scientia Horticulturae) — so a leaf seen against the sun shows the light coming THROUGH it, in
// its own green, at LEAF_THROUGH of what a front-lit leaf reflects (2–5 % against 10 %). The first leaf cards were lit
// by their normals alone and a crown's far side was black. The sun's direction and light are uniforms set by sky().
const LEAF_THROUGH = 0.35;
const leafSun = { dir: TSL.uniform(new THREE.Vector3(0, 1, 0)), rgb: TSL.uniform(new THREE.Vector3()) };   // toward the sun (world); its colour × intensity
let shadowRT = null, shadowScene = null, shadowU = null, shadowCentre = null, shadowAt = 0, shadowMaps = 0;
/** A lit material's colour under the cloud shadow at the fragment: positionWorld is eye-relative and the map was
 *  rendered about shadowCentre (the ground under the player), so the fragment's place in the map's frame is
 *  positionWorld + shift (eye − centre); east and north drop the height. */
function shadeByClouds(color) {
  const d = TSL.positionWorld.add(shadowO.shift);
  const uv = TSL.vec2(TSL.dot(d, shadowO.east), TSL.dot(d, shadowO.north)).div(CLOUD_SHADOW_SPAN).add(0.5);
  const n = TSL.texture(shadowRT ? shadowRT.texture : shadowBlank, uv); shadowTex.push(n);
  return color.mul(TSL.mix(TSL.float(1), n.r, shadowO.share));
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
/** The plots a craft's body may reach (the corners of its reach round its pose). */
function plotsUnder(c) {
  const [f, u, v] = c.pose, r = c.bodyR || 0, out = new Set();
  for (const du of [-r, 0, r]) for (const dv of [-r, 0, r])
    out.add(Wd.plotOf(f, Math.max(0, Math.min(W - 1, Math.floor(u + du))), Math.max(0, Math.min(W - 1, Math.floor(v + dv)))));
  return [...out];
}
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
function craftSolid(f, u, v, h) {                                     // 2: a piece or a crisp block; 1 (true): the ground (bodyInside keeps the kind)
  if (boxAt(f, u, v, h)) return 2;
  const cu = Math.floor(u), cv = Math.floor(v), ch = Math.floor(h), b = blockAt(f, cu, cv, ch);
  // A CRAFT TEARS THROUGH TREES (tearCells): the planet's own trunk and crown cells are no wall to a flown craft where
  // its pilot may build — they are noted here and torn after the step. An edit (a log someone placed) and a stranger's
  // plot's trees stay what they are to it: solid, through the field below.
  if (tearing && Wd.isTree(b) && ch >= 0) {
    const k = key(f, cu, cv, ch);
    if (!edits.has(k) && mayBuild(Wd.plotOf(f, cu, cv))) { tearing.add(k); return false; }
  }
  if (crispB(b)) return BLOCKS[b].solid ? 2 : false;
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
  const { fw, up } = chase || chaseView(0);
  return [0, 1, 2].map((i) => e[i] - fw[i] * CHASE_BACK + up[i] * CHASE_UP);
}
const CHASE_BACK = 9, CHASE_UP = 2.5;
// A SPRUNG CHASE VIEW (operator 2026-11-22: the X fighter is "shaky" in flight): the camera hung rigidly off the craft's
// nose and roll, 9 m back, so every twitch of the attitude — the stick's deflections, the physics' own small swings —
// moved the whole view, 9 m of lever magnifying it. The view's direction and up now follow the craft's with a lag of
// CHASE_LAG s (an exponential ease, the frame's dt): a turn is followed within a fraction of a second, a twitch is not.
const CHASE_LAG = 0.15;
let chase = null;                       // { fw, up } the eased view while flying; null on foot (the walker's view is its own)
const unit = (a) => { const m = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / m, a[1] / m, a[2] / m]; };
/** The view's forward and up this frame: the look's own on foot; flying, eased toward the craft's by dt seconds. */
function chaseView(dt) {
  const { fr, fw } = look(), up = craftUp || fr.up;
  if (!flying) { chase = null; return { fw, up }; }
  if (!chase || !(dt > 0)) { chase = chase || { fw: fw.slice(), up: up.slice() }; return chase; }
  const k = 1 - Math.exp(-dt / CHASE_LAG);
  chase = { fw: unit(chase.fw.map((x, i) => x + (fw[i] - x) * k)), up: unit(chase.up.map((x, i) => x + (up[i] - x) * k)) };
  return chase;
}
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
let stepDist = 0;                                // m of ground covered since the last footfall cue (#113)
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
/** The direction the player asks to go, at most full strength (length 1). FORWARD AND SIDEWAYS TOGETHER WERE √2 TIMES
 *  FASTER (playtest 2026-11-16, a player's own trace: pulled back by the world server eleven times in free flight —
 *  fast flight is 60 m/s straight, 85 m/s on a diagonal, and the server allows 65; running diagonally was 10.6 m/s
 *  against 7.5): the sum is cut to length 1, a joystick's partial tilt kept as it is. */
function moveDir(fwd, side) {
  const m = Math.hypot(fwd, side);
  return m > 1 ? [fwd / m, side / m] : [fwd, side];
}
function step(dt) {
  pillarTick();
  const f0 = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0) + (touch ? touch.my : 0);
  const s0 = (keys.has("KeyD") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("KeyA") || keys.has("ArrowLeft") ? 1 : 0) + (touch ? touch.mx : 0);
  // (a craft takes them as they are: to a pilot forward and sideways are throttle and turn, not one diagonal)
  if (flying) return flyStep(dt, f0, s0);                   // at the controls of a craft: it moves, the pilot rides
  const [fwd, side] = moveDir(f0, s0);
  const fast = keys.has("ShiftLeft") || keys.has("ShiftRight") || !!(touch && touch.run);   // (Run held on a phone, #139)
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
  // a footfall every 0.35 m of ground covered (half a 0.7 m gait cycle), on the ground only
  if (P.ground && !P.fly) { stepDist += Math.hypot(P.vu || 0, P.vv || 0) * dt; if (stepDist >= 0.35) { stepDist = 0; sound.cue("step", 0.8, 120); } } else stepDist = 0;
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
// THE STICK (#191): flying an aircraft, the mouse (or the touch look-drag) is a stick, not a view — moving it deflects
// the stick, which centres itself again (STICK_PX pixels = full deflection; it relaxes in about a third of a second —
// DESIGN CHOICES); W / S open and shut the throttle, A / D are the rudder; Space / C work only the vertical thrusters.
// The camera then looks along the nose (P.yaw, P.pitch follow the craft) and rolls with it (craftUp).
const stick = { x: 0, y: 0 }, STICK_PX = 160, STICK_RELAX = 3;
let craftUp = null;                      // the flown aircraft's up in the planet frame, for the camera; null: the ground's
/** A CRAFT TEARS THROUGH TREES (operator 2026-11-13, the X fighter wedged in a broadleaf after a landing: "x fighter
 *  should tear trees down through sheer force (minor damage perhaps)"): the planet's own trunk and crown cells its body
 *  meets are no wall to it (craftSolid) — they are TORN: taken out here at once and sent to the world server as the
 *  craft's set (land_server.py apply craft=: no tool, no time, nothing gathered; a torn trunk brings its tree down), which
 *  puts them back if it refuses (set_ok). The minor damage: each cell costs speed — a trunk TEAR_COST[0], a crown cell
 *  TEAR_COST[1] of it — so a grove slows a craft and never stops it (at least half the speed is kept a step). Only where
 *  the pilot may build: a stranger's plot keeps its trees, and to the craft they stand as walls. */
const TEAR_COST = [0.04, 0.01];
let tearing = null;                                        // while the flown craft steps: the tree cells it met (keys)
function tearCells(c, torn) {
  const byPlot = new Map(); let wood = 0, crown = 0;
  for (const k of torn) {
    const [f, u, v, h] = k.split(":").map(Number), b = blockAt(f, u, v, h);
    if (Wd.TREE_WOOD.has(b)) wood++; else crown++;
    const plot = Wd.plotOf(f, u, v);
    putCell(f, u, v, h, B.air);
    (byPlot.get(plot) || byPlot.set(plot, []).get(plot)).push([f, u, v, h, B.air]);
  }
  for (const [plot, cells] of byPlot) { net.send({ t: "set", cells, craft: c.id, req: ++net.req }); net.pending.set(net.req, plot); }
  const k = Math.max(0.5, 1 - TEAR_COST[0] * wood - TEAR_COST[1] * crown);
  c.vel = c.vel.map((x) => x * k);
}
function flyStep(dt, fwd, side) {
  const c = flying, F = FLIGHT();
  const upK = keys.has("Space") || !!(touch && touch.up), downK = keys.has("KeyC") || keys.has("ControlLeft") || !!(touch && touch.down);
  let input;
  if (c.aero && c.aero.winged) {
    // the throttle: W opens it, S shuts it, half a throttle a second. On a phone Jump / Down are the vertical thrusters
    // when the craft has any, else the throttle (one pair of buttons; the stick's forward/back is the throttle too)
    const vert = c.aero.T[2] > 0, tUp = !!(touch && touch.up), tDown = !!(touch && touch.down);
    const open = (keys.has("KeyW") || keys.has("ArrowUp") || (touch && touch.my > 0.5) || (tUp && !vert)), shut = (keys.has("KeyS") || keys.has("ArrowDown") || (touch && touch.my < -0.5) || (tDown && !vert));
    c.throttle = Math.max(0, Math.min(1, (c.throttle || 0) + (open ? 0.5 : shut ? -0.5 : 0) * dt));
    input = { pitch: Math.max(-1, Math.min(1, stick.y)), roll: Math.max(-1, Math.min(1, stick.x)), yaw: side, throttle: c.throttle,
      up: vert && (upK || tUp), down: vert && (downK || tDown), slots: heldSlots() };
    const k = Math.exp(-STICK_RELAX * dt); stick.x *= k; stick.y *= k;
  } else input = { fwd, side, yaw: P.yaw, up: upK, down: downK, slots: heldSlots() };
  tearing = new Set();                                       // the tree cells its body meets this step (craftSolid)
  craftStep(c, input, dt, F, (u, v) => craftGround(c.pose[0], u, v) - 0.05, (pose) => craftHits(c, pose));
  const torn = tearing; tearing = null;
  if (torn.size) tearCells(c, torn);
  // ALREADY INSIDE (playtest 2026-11-16, the X fighter parked at 0·4729·4162 with a pine through it): the step tears what
  // the body meets as it MOVES, and tears go from this page — the pilot's page closed in the last dive, so the tree it came
  // to rest in was never sent and stands through the hull for every visitor. Once a boarding, when the plots under the
  // craft hold their edits (a tree already torn is no tree), the body at rest tears what it stands in — on the next boarding
  // or reload such a craft frees itself.
  if (!c.cleared && plotsUnder(c).every((p) => plotsApplied.has(p))) {
    c.cleared = true;
    tearing = new Set(); craftHits(c, c.pose);
    const inside = tearing; tearing = null;
    if (inside.size) tearCells(c, inside);
  }
  cannonTick(c, input.slots || heldSlots());
  if (c.aero && c.aero.winged) {
    P.yaw = c.pose[4]; P.pitch = c.pose[5] || 0;             // the camera looks along the nose
    const fr = Wd.frameOf(c.pose[0], c.pose[1], c.pose[2]), ax = axesOf(c.pose[4], c.pose[5] || 0, c.pose[6] || 0);
    craftUp = [0, 1, 2].map((i) => fr.east[i] * ax.up[0] + fr.north[i] * ax.up[1] + fr.up[i] * ax.up[2]);
  } else craftUp = null;
  // the craft stays on its face of the planet (crossing an edge flying is for later)
  c.pose[1] = Math.max(1, Math.min(W - 1, c.pose[1])); c.pose[2] = Math.max(1, Math.min(W - 1, c.pose[2]));
  pendingPlace = null;   // (a place set here wins over a saved place still waiting for its plot's edits — pendingPlace — #180 item 3)
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
/** The atlas tiles of a box's 24 corners in BoxGeometry's order of faces (+x -x +y -y +z -z): its top's on the top, its
 *  bottom's underneath, its sides' round it — as the chunk mesher lays a docked piece (land-mesher.js). `tex` = [top, side, bottom]. */
const boxTiles = (tex) => [1, 1, 0, 2, 1, 1].flatMap((t) => [tex[t], tex[t], tex[t], tex[t]]);
/** What a craft's piece of block `blk` is drawn in: what the chunks draw it in while it is docked. A see-through block
 *  (glass, ice) is the glass material, every other its own (pieceMaterial).
 *  INVARIANT (#188): a craft is drawn as it was built. pieceMaterial alone gave glass the atlas material, and a craft's
 *  geometry carried no atlas tile, so the X-wing's clear canopy became a solid black wedge the moment it was boarded
 *  (photographed 2026-11-11) and every material without a scan (the colours, marble, the ores, a nav unit) drew tile 0.
 *  Every geometry a craft is made of carries its `tile`, and every material it is given comes from here. */
function craftMaterial(blk) { return Wd.opaque(blk) ? pieceMaterial(blk) : matGlassy; }
/** A box geometry whose texture is tiled once per metre on every face (as the mesher tiles a piece), white vertex
 *  colours (the piece materials multiply by them) and the atlas tiles of `blk` (the atlas material reads them: a block
 *  with no scanned texture). w, h, d in metres. */
function pieceBox(w, h, d, blk) {
  const g = new THREE.BoxGeometry(w, h, d), uv = g.attributes.uv;
  const size = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];          // BoxGeometry faces: +x -x +y -y +z -z
  for (let f = 0; f < 6; f++) for (let k = 0; k < 4; k++) { const i = f * 4 + k; uv.setXY(i, uv.getX(i) * size[f][0], uv.getY(i) * size[f][1]); }
  g.setAttribute("color", new THREE.Float32BufferAttribute(new Array(g.attributes.position.count * 3).fill(1), 3));
  g.setAttribute("tile", new THREE.Float32BufferAttribute(boxTiles(Wd.BLOCKS[blk].tex), 1));
  return g;
}
/** A craft as drawn: its pieces in their materials, relative to the seat (x east, z north of a level craft facing north;
 *  local -Z is its nose, so the basis below stays right-handed). */
function craftMesh(pieces) {
  const g = new THREE.Group(), toCraft = (v) => [v[0], v[2], -v[1]];   // the craft's frame: x east, y up, z south
  for (const b of pieces) {
    const centre = [(b[0] + b[3] / 2) / Wd.CM, (b[2] + b[5] / 2) / Wd.CM, -(b[1] + b[4] / 2) / Wd.CM];
    // a PART (#175) is its modelled solid, a mesh for each of its tones; anything else the box it is
    for (const m of Wd.isPart(b) ? partMeshes(b) : [new THREE.Mesh(pieceBox(b[3] / Wd.CM, b[5] / Wd.CM, b[4] / Wd.CM, b[6]), craftMaterial(b[6]))]) {
      m.position.set(centre[0], centre[1], centre[2]);
      if (m.material === matGlassy) m.renderOrder = 1;          // glass after what is seen through it, as the chunks draw it (#188)
      if (Wd.isTurned(b)) m.quaternion.copy(turnQuat(b, toCraft));
      g.add(m);
    }
    if (b[6] === B.thruster) {                    // its exhaust (#171): a cone from the thruster's underside, drawn per frame
      const pl = new THREE.Mesh(plumeGeo(), new THREE.MeshBasicMaterial({ color: 0xffb060, transparent: true, opacity: 0, depthWrite: false,
        blending: THREE.AdditiveBlending, side: THREE.DoubleSide }));
      if (Wd.isEngine(b)) {
        // an ENGINE's exhaust leaves its nozzle — the back end of its depth — along its own axis, as wide as the nozzle,
        // wherever the piece is turned (engineFrame keeps it there: a thruster box's plume swings with the thrust instead)
        const back = toCraft(Wd.turnVec(Wd.rotOf(b), [0, -b[4] / 2, 0])), l = Math.hypot(...back) || 1;
        pl.position.set(centre[0] + back[0] / Wd.CM, centre[1] + back[1] / Wd.CM, centre[2] + back[2] / Wd.CM);
        pl.userData.axis = new THREE.Vector3(back[0] / l, back[1] / l, back[2] / l);
        pl.userData.wide = (0.64 * Math.min(b[3], b[5])) / Wd.CM / 0.84;       // the nozzle's width (land-shapes.js ENGINE_PROFILE: 0.64) over the cone's own
      } else pl.position.set(centre[0], b[2] / Wd.CM, centre[2]);
      pl.visible = false; g.add(pl); (g.userData.plumes ||= []).push(pl);
    }
  }
  mergeByMaterial(g, new Set(g.userData.plumes || []));
  g.matrixAutoUpdate = false;
  return g;
}
/** ONE DRAW A MATERIAL (#139, measured with /draws on a phone at the landing: 551 draw calls a frame, 220 of them one
 *  craft's painted plate — a craft was a mesh a piece and a mesh a tone of each part, so a 60-piece X-wing cost hundreds
 *  of draws): the pieces of a craft that share a material are baked, each in its own place and turn, into one geometry.
 *  Nothing reads a piece's mesh (the cannons, the seat, the collisions read c.pieces); the plumes stay their own, as
 *  engineFrame lights and aims each. Geometries are merged only with the same attributes (a box's and a part's are). */
function mergeByMaterial(g, keep) {
  const groups = new Map();
  for (const m of g.children) {
    if (keep.has(m) || !m.isMesh) continue;
    const key = m.material.uuid + "|" + Object.keys(m.geometry.attributes).sort().join(",");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(m);
  }
  for (const list of groups.values()) {
    if (list.length < 2) continue;
    const parts = list.map((m) => { m.updateMatrix(); const q = m.geometry.index ? m.geometry.toNonIndexed() : m.geometry.clone(); q.applyMatrix4(m.matrix); return q; });
    const out = new THREE.BufferGeometry();
    for (const name of Object.keys(parts[0].attributes)) {
      const size = parts[0].attributes[name].itemSize, arr = new Float32Array(parts.reduce((t, q) => t + q.attributes[name].count * size, 0));
      let at = 0; for (const q of parts) { arr.set(q.attributes[name].array, at); at += q.attributes[name].count * size; }
      out.setAttribute(name, new THREE.BufferAttribute(arr, size));
    }
    const one = new THREE.Mesh(out, list[0].material);
    one.renderOrder = list[0].renderOrder; one.castShadow = list[0].castShadow; one.receiveShadow = list[0].receiveShadow;
    for (const m of list) { g.remove(m); m.geometry.dispose(); }
    for (const q of parts) q.dispose();
    g.add(one);
  }
}
/** A part (land-shapes.js, #175) as three.js meshes about its piece's centre, one for each tone it has: x across, y up
 *  and the piece's depth along -z (the craft's frame; a mirror of the part's own, so two corners of every triangle swap).
 *  The texture is laid per metre onto the side of the box a triangle mostly faces, as the chunk mesher lays it
 *  (land-mesher.js meshPart), so a craft looks the same flying as it did docked. */
function partMeshes(b) {
  const T = Shapes.tris(b[7], b[3], b[4], b[5]), [w, d, h] = [b[3], b[4], b[5]], out = [], pos = T.pos, nor = T.nor;
  for (const tone of new Set(T.tone)) {
    const P = [], N = [], U = [];
    for (let i = 0; i < T.n; i++) {
      if (T.tone[i] !== tone) continue;
      const t = i * 9, ux = pos[t + 3] - pos[t], uy = pos[t + 4] - pos[t + 1], uz = pos[t + 5] - pos[t + 2], vx = pos[t + 6] - pos[t], vy = pos[t + 7] - pos[t + 1], vz = pos[t + 8] - pos[t + 2];
      const fx = Math.abs(uy * vz - uz * vy), fy = Math.abs(uz * vx - ux * vz), fz = Math.abs(ux * vy - uy * vx), side = fx >= fy && fx >= fz ? 0 : fy >= fz ? 1 : 2;
      for (const k of [0, 2, 1]) {
        const q = t + k * 3, x = pos[q], y = pos[q + 1], z = pos[q + 2];
        P.push((x - w / 2) / Wd.CM, (y - h / 2) / Wd.CM, -(z - d / 2) / Wd.CM); N.push(nor[q], nor[q + 1], -nor[q + 2]);
        U.push((side === 0 ? z : x) / Wd.CM, (side === 1 ? z : y) / Wd.CM);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(P, 3)); g.setAttribute("normal", new THREE.Float32BufferAttribute(N, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(U, 2)); g.setAttribute("color", new THREE.Float32BufferAttribute(new Array(P.length).fill(1), 3));
    // a part shows its material's SIDE tile on every face, as the mesher's meshPart gives it docked (#188: see craftMaterial)
    const blk = Wd.toneBlock(b, tone);
    g.setAttribute("tile", new THREE.Float32BufferAttribute(new Array(P.length / 3).fill(Wd.BLOCKS[blk].tex[1]), 1));
    out.push(new THREE.Mesh(g, craftMaterial(blk)));
  }
  return out;
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
    pl.quaternion.setFromUnitVectors(new THREE.Vector3(0, -1, 0), pl.userData.axis || ex);   // an engine part's: out of its nozzle (craftMesh)
    const flick = 0.9 + 0.2 * Math.random(), wide = pl.userData.wide || 1;
    pl.scale.set((0.7 + 0.5 * thr) * wide, (0.3 + 3.2 * thr) * flick * wide, (0.7 + 0.5 * thr) * wide);
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
  // an aircraft's pose carries pitch and roll (#191): the craft is drawn in its attitude, as its pilot sees it
  const ax = axesOf(yaw, pose[5] || 0, pose[6] || 0), W3 = (a) => new THREE.Vector3(...[0, 1, 2].map((i) => fr.east[i] * a[0] + fr.north[i] * a[1] + fr.up[i] * a[2]));
  mesh.matrix.makeBasis(W3(ax.right), W3(ax.up), W3(ax.nose).negate()).setPosition(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
  mesh.matrixWorldNeedsUpdate = true;
}
function craftsSeen(list) {
  const seen = new Set();
  for (const o of list || []) {
    seen.add(o.id);
    let c = crafts.get(o.id);
    if (!c) { if (!o.pieces) continue; c = { pieces: o.pieces, slots: o.slots || [], mesh: craftMesh(o.pieces) }; scene.add(c.mesh); crafts.set(o.id, c); }
    else if (o.pieces) { c.pieces = o.pieces; c.slots = o.slots || []; }   // sent again (a key set at a gadget): the slots are new
    Object.assign(c, { owner: o.owner, pilot: o.pilot, mass: o.mass, thrust: o.thrust, eng: o.eng || null });
    if (!(flying && flying.id === o.id)) c.pose = o.pose;        // the craft I fly goes where I fly it
  }
  for (const [id, c] of crafts) if (!seen.has(id) && !(flying && flying.id === id)) { scene.remove(c.mesh); if (c.dust) scene.remove(c.dust); crafts.delete(id); }
}
// the materials a craft is made of (land-world.js: steel plate, glass, thruster): Use on one of them may mean "fly this"
const CRAFT_SKIN = new Set([B.steelplate, B.glass, B.thruster, B.white, B.red, B.yellow, B.black, B.orange, B.green, B.blue, B.purple]);   // …and painted plate (#175; orange, green, blue and purple since #187)
/** Where each of my crafts is from where I stand, nearest first (#171): d metres over the ground (null on another face), b
 *  the bearing in whole degrees clockwise from north, h its height over the untouched ground under it. */
function craftsBearing(list) {
  return list.map((c) => {
    const [f, u, v, h] = c.pose;
    if (f !== P.face) return { id: c.id, d: null };
    const du = u - P.u, dv = v - P.v;
    return { id: c.id, d: Math.round(Math.hypot(du, dv)), b: (Math.round(Math.atan2(du, dv) * 180 / Math.PI) + 360) % 360,
      h: Math.max(0, Math.round(h - Wd.column(f, Math.floor(u), Math.floor(v)).height)) };
  }).sort((a, b) => (a.d === null) - (b.d === null) || a.d - b.d);
}
/** The pilot seat among the pieces touching piece b on its plot (and those touching them…, as the world server joins a
 *  craft: land_server.py connected, CRAFT_PAD 2 cm), or null. */
/** craftSeat for the aim line, remembered for the piece until its plot's pieces change (the line is written ~6 times a
 *  second; the walk reaches up to 400 pieces). A painted plate offered "Use board" on its own on the ground, with no
 *  seat to board (playtest 2026-11-15) — Use boards only when a seat is joined to it (act), so the line says so only then. */
const seatMemo = new WeakMap();
function seatOfAimed(plot, b) {
  const rec = plotBoxes.get(plot), m = seatMemo.get(b);
  if (m && m.rec === rec && m.n === (rec ? rec.list.length : 0)) return m.seat;
  const seat = craftSeat(plot, b);
  seatMemo.set(b, { rec, n: rec ? rec.list.length : 0, seat });
  return seat;
}
function craftSeat(plot, b) {
  const rec = plotBoxes.get(plot);
  if (!rec) return null;
  const grow = (p) => [p[0] - 2, p[1] - 2, p[2] - 2, p[3] + 4, p[4] + 4, p[5] + 4, ...p.slice(6)];   // CRAFT_PAD 2 cm, as the server (a docked craft's rounding)
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
  if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
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
  const c = flying;
  // STEPPING OFF (#194: "i exited the xfighter and fell into the townhall wall"): onto the first free spot round the
  // seat (land-flight.js stepOffSpot — the body clear of every piece and cell at the ground's height there), and only
  // from a craft on or near the ground: from one hovering high the pilot stays in the seat and is told to land
  // the height is measured to what the craft actually rests on — a roof, a deck, a built floor (land-flight.js
  // surfaceBelow) — not to the ground under it: on the town hall's roof the pilot was "too high to step off" against
  // the ground 5 m below the tiles and could neither leave nor land (operator, 2026-11-12)
  const bottom = c.pose[3] + c.bottom, floorAt = (u, v) => groundAt(P.face, u, v);
  const under = surfaceBelow((h) => solidAt(P.face, c.pose[1], c.pose[2], h), bottom - 0.05, floorAt(c.pose[1], c.pose[2])), hover = bottom - under;
  if (hover > 2.5) { notify(T("fTooHigh", "Too high to step off — land first ({h} m up).", { h: hover.toFixed(1) })); trace("leave_refused", { craft: c.id, why: "high", hover: +hover.toFixed(2), pose: tracePose(c.pose) }); return; }
  // the spot's height is the surface under it too (the roof beside the seat), so the pilot steps onto the roof, not
  // through it to the ground inside the building
  const spotH = (u, v) => surfaceBelow((h) => solidAt(P.face, u, v, h), bottom + 0.5, floorAt(u, v));
  const spot = stepOffSpot(c.pose[1], c.pose[2], c.pose[4], (u, v) => !collides(u, v, spotH(u, v)));
  if (!spot) { notify(T("fNoSpot", "Nowhere to step off here — move the craft first.")); trace("leave_refused", { craft: c.id, why: "no_spot", pose: tracePose(c.pose) }); return; }
  flying = null; lastCraft = c.id; craftUp = null; P.pitch = 0;
  net.send({ t: "fly", craft: c.id, pose: c.pose });
  net.send({ t: "leave", craft: c.id, req: ++net.req });
  const own = crafts.get(c.id); if (own) { own.pilot = null; own.pose = c.pose; }
  pendingPlace = null;   // (a place set here wins over a saved place still waiting for its plot's edits — pendingPlace — #180 item 3)
  P.u = spot.u; P.v = spot.v; P.h = spotH(P.u, P.v); P.vh = 0; P.eyeH = P.h;
  trace("leave", { craft: c.id, from: tracePose(c.pose), to: tracePose([P.face, P.u, P.v, P.h, P.yaw]), tried: spot.tried });
  notify(T("fParked", "Parked. Use it again to fly; /dock sets it down here as pieces."));
  hud(); hotbar();                                                          // (the bar goes back to the placeable things)
}
function startFlying(c) {
  const bottom = Math.min(0, ...c.pieces.map((b) => Wd.boxAabb(b)[2])) / Wd.CM;   // a turned piece: its lowest reach
  flying = { id: c.id, pose: c.pose.slice(), vel: [0, 0, 0], mass: c.mass, thrust: c.thrust, bottom, grounded: true,
    body: craftBody(c.pieces, Wd.boxAabb),                                // what of it meets the world (#171)
    feet: craftFeet(c.pieces, Wd.boxAabb),                                // what it stands on: it lands on the highest ground under them (#184)
    cannons: cannonsOf(c.pieces, c.slots),                                // its weapons, by key (#171)
    area: craftArea(c.pieces, Wd.boxAabb),                                // what the air pushes on (#174)
    aero: aeroOf(c.pieces, Wd.boxAabb, (b) => (b[6] === B.thruster ? Wd.engineCount(b) * FLIGHT().thrust_kn : 0), c.slots),   // wings and engines (#191); the gadgets' keys
    throttle: 0 };
  // GADGET KEYS: the thrust the hovering model lifts by is the automatic thrust alone — a bound thruster pushes only on its key
  flying.thrust = Math.max(0, c.thrust - Object.values(flying.aero.gadgets || {}).reduce((m, g) => m + Math.hypot(g[0], g[1], g[2]), 0));
  hotbar();                                                                 // the bar shows the gadgets' keys at the controls
  stick.x = stick.y = 0;
  flying.bodyLow = Math.min(0, ...flying.body.map((p) => p[2]));
  // a NAV UNIT among its pieces (#173): dead reckoning from here, the place it took off from — its fix — with an error
  // that grows along a direction fixed at the fix (land-flight.js navSays)
  if (c.pieces.some((b) => b[6] === B.navunit)) { const a = Math.random() * 2 * Math.PI; flying.nav = { t0: performance.now(), dir: [Math.sin(a), Math.cos(a)] }; }
  flying.bodyR = Math.max(1, ...flying.body.map((p) => Math.hypot(p[0], p[1])));
  trace("board", { craft: c.id, pose: tracePose(c.pose), winged: !!flying.aero.winged, from: tracePose([P.face, P.u, P.v, P.h, P.yaw]) });
  P.yaw = c.pose[4]; P.fly = false;
  const k = crafts.get(c.id) || { pieces: c.pieces, mesh: craftMesh(c.pieces) };
  if (!crafts.has(c.id)) { scene.add(k.mesh); crafts.set(c.id, k); }
  Object.assign(k, { owner: c.owner, pilot: c.pilot, mass: c.mass, thrust: c.thrust, pose: flying.pose });
  const f = flightOf(FLIGHT(), c.mass, c.thrust);
  if (flying.aero.winged) {
    P.pitch = flying.pose[5] || 0;
    const vs = stallSpeed(flying, FLIGHT());
    notify(T("fBoardWing", "At the controls of an aircraft — mouse: pitch and roll · A D: rudder · W S: throttle · Use: leave. Its wings carry it from about {v} m/s: throttle up, roll, then pull.", { v: Math.round(isFinite(vs) ? vs : 0) }) + gadgetKeysLine(), 9000);
  } else notify((f.lifts ? T("fBoard", "At the controls — look to steer, stick/W A S D to push, Jump to climb, Down to sink, Use to leave.")
    : T("fHeavy", "Too heavy to lift: {t} kN of thrust against {w} kN of weight — add thrusters or make it lighter.", { t: Math.round(flying.thrust), w: Math.round(f.weight) })) + gadgetKeysLine(), 6000);
}
/** " · Keys 1, 3 fire the gadgets you bound." for the craft flown, or "" when none is bound (GADGET KEYS). */
function gadgetKeysLine() {
  const ks = Object.keys(flying && flying.aero && flying.aero.gadgets || {}).map(Number).sort();
  return !ks.length ? "" : " · " + (ks.length === 1 ? T("fKey1", "Key {k} fires the gadgets you bound to it.", { k: ks[0] }) : T("fKeysN", "Keys {k} fire the gadgets you bound to them.", { k: ks.join(", ") }));
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
  edits.set(k, b); pe.set(lk, b); plotList.delete(plot); topSeq++;
  remeshAround(face, u, v, h);
}
/** A cell back to the untouched planet (the wilderness regrew it). */
function dropCell(face, u, v, h) {
  const plot = Wd.plotOf(face, u, v), pc = Wd.plotCoords(plot), pe = plotEdit.get(plot);
  edits.delete(key(face, u, v, h));
  if (pe) pe.delete((u - pc.u0) + ":" + (v - pc.v0) + ":" + h);
  plotList.delete(plot);
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
  // the plot's real state, at once (#177: "belongs to someone else" came only after the whole hold, while the HUD said
  // "For sale" for the same plot) — for sale at its price, or whose it is; the old line when the title is not known yet
  const t = titles.get(plot);
  // an invited builder who tapped before the server's answer came in was told "belongs to someone else" on the plot they
  // were invited to (playtest 2026-11-15, plot 0·4999·3438): until that answer is in, say so and ask at once
  if (net.me && net.online && t && !mine.has(plot) && !builderKnown.has(plot)) {
    builderCheck(plot);
    return notify(T("checkingBuild", "Checking whether you may build on plot {p} — try again in a moment.", { p: plotLabel(plot) })), false;
  }
  if (!net.me) signInNotice(T("signInBuild2", "Sign in to gather and build."));
  else if (t && t.sale) notify(T("notYoursSale", "Plot {p} is for sale · {n} NADO — buy it on the market to gather and build here.", { p: plotLabel(plot), n: rawToNado(t.sale.price.toString()) }));
  // (the town's own plots by name, not the issuer's address — see ownedBy)
  else if (t && t.holder === ISSUER) notify(T("notYoursTown", "Plot {p} belongs to the town — gather and build on open land, or on a plot of your own.", { p: plotLabel(plot) }));
  else if (t && t.holder) notify(T("notYoursOwned", "Plot {p} is owned by {o} — ask them to invite you to build here.", { p: plotLabel(plot), o: disp(t.holder) }));
  else notify(T("notYours", "Plot {p} belongs to someone else. Buy a plot, or ask its owner to invite you.", { p: plotLabel(plot) }));
  return false;
}
function save() {
  try { localStorage.setItem(LS, JSON.stringify({ p: [P.face, P.u, P.v, P.h, P.yaw, P.pitch], at: Math.floor(Date.now() / 1000), hot, piece })); } catch (e) {}
}
/** The chosen piece size and snap, under the hotbar. */
function pieceInfo(pressed) {
  const id = hot[slot], el = $("pieceInfo");
  if (!el) return;
  // R, G and T with nothing placeable on the bar changed something invisible (#177): say what they are for
  if (pressed && !(id && RULES && !NATURAL_ITEMS.has(id))) notify(T("pieceNoItem", "Piece size, shape and turn apply to a block or piece on the bar — hold one (1–9)."));
  const [w, d, h] = pieceDims();
  const part = partFor(id && RULES && RULES.items[id]);
  const shapeName = part ? partName(part) : [T("shapeBox", "box"), T("shapeSlope", "slope"), T("shapeStairs", "stairs")][piece.shape || 0];
  const tl = piece.tilt || [0, 0, 0], tilted = tl.some((t) => t);
  el.textContent = net.me && id && RULES && !NATURAL_ITEMS.has(id) ? T("pieceInfo", "Piece {w} × {d} × {h} cm · snap {s} cm", { w, d, h, s: piece.snap }) + " · " + shapeName
    + (tilted ? " · " + T("tiltInfo", "tilt {y}° {p}° {r}°", { y: tl[0] / 10, p: tl[1] / 10, r: tl[2] / 10 }) : "") + (piece.mirror ? " · " + T("mirrorOn", "mirrored") : "") + (piece.attach ? " · " + T("attachOn", "centred on what it is set against") : "") : "";
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
/** A LINK TO A PLOT (?plot=N, the address every plot's title carries — nft.js "Walk it in Land"): where it puts the player,
 *  [face, u, v, yaw], or null. The market's link opened the landing instead (playtest 2026-11-16: a fresh browser asked
 *  for 0·4999·3438 stood at 0·5000·3440) — the page read no ?plot= at all. Half a metre inside the plot's south edge,
 *  looking north across it, so the HUD names the plot asked for (1.5 m off the edge it named the neighbour, 0·4998·3438);
 *  if the plot's pieces, once they arrive, stand there, the player steps out over the edge (linkArrive, setPlotBoxes). */
function linkPlace(search) {
  const s = new URLSearchParams(search).get("plot");
  if (!s || !/^\d{1,10}$/.test(s) || Number(s) >= Wd.PLOT_MAX) return null;
  const q = Wd.plotCoords(Number(s));
  return [q.face, q.u0 + Wd.PLOT / 2, q.v0 + 0.5, 0, Number(s)];
}
/** The address's query without ?plot=, the rest kept as it was (load). */
function withoutPlot(search) {
  const q = new URLSearchParams(search); q.delete("plot");
  const s = q.toString();
  return s ? "?" + s : "";
}
function townSpawn() {
  const q = Wd.plotCoords(TOWN_HALL_PLOT);
  // the door is 8.05-8.95 m in, the street 0-2 m. The landing FACES WEST along the street (yaw -π/2), where Maren the
  // elder stands 2.5 m off and the square runs on: a newcomer who faced +v stood nose to the hall's wall with nothing
  // to do in sight (#178, playtest 2026-11-11); the test holds a townsperson in the landing's view
  return [q.face, q.u0 + 8.5, q.v0 + 1.5, -Math.PI / 2];
}
function load() {
  let d = null;
  try { d = JSON.parse(localStorage.getItem(LS) || "null"); } catch (e) {}
  localPlace = d && Array.isArray(d.p) ? (Number.isFinite(d.at) ? d.at : Infinity) : 0;   // when this browser last saved a place
  if (d && Array.isArray(d.hot)) hot = d.hot.filter((x) => typeof x === "string").slice(0, 9);
  if (d && d.piece && [d.piece.w, d.piece.d, d.piece.h].every((x) => Number.isInteger(x) && x >= 1 && x <= Wd.PLOT_CM) && SNAPS.includes(d.piece.snap)) {
    piece = d.piece;
    if (!Shapes.isPart(piece.part)) piece.part = 0;       // no part, or a byte that is none (#175): a plain piece
    if (!(Array.isArray(piece.tilt) && piece.tilt.length === 3 && piece.tilt.every((t) => Number.isInteger(t) && t > -1800 && t <= 1800))) piece.tilt = [0, 0, 0];
    piece.mirror = piece.mirror === true;
    piece.attach = piece.attach === true;
  }
  const link = linkPlace(location.search);
  if (link) {                                            // a link wins over a saved place and the server's kept one
    [P.face, P.u, P.v, P.yaw] = link; P.h = groundAt(P.face, P.u, P.v); P.pitch = -0.2;
    linkArrive = link[4];                                // checked against the plot's pieces when they arrive
    localPlace = Infinity;                               // (the greeting takes the server's place only when it is newer)
    // a reload stays where they walked. Only ?plot= goes: the rest is read after this (?prof=1, ?plain, ?gov), and a
    // plot link with ?prof=1 came up with no profiler while the landing's had one (measuring #150, 2026-11-16)
    try { history.replaceState(null, "", location.pathname + withoutPlot(location.search) + location.hash); } catch (e) {}
    return;
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

/** A chunk's level of detail by its distance in chunks: 0 near (full tree models, grass), 1 the middle band (the trees'
 *  middle model, a third of the grass), 2 far (far trees, small pieces skipped). A phone never takes 0; nor does LOW
 *  (view ≤ 3 chunks, #150: measured 2026-11-12 at the landing on Low, bark was the frame's top item at 79k triangles
 *  — every near tree the full model on the preset meant for weak devices). The chunk request and the re-check as the
 *  player moves both read this, so a chunk is never meshed at one level and kept at another. */
const chunkLod = (dist) => (PHONE ? (dist <= 1 ? 1 : 2) : SET.view <= 3 ? (dist <= 2 ? 1 : 2) : dist <= 2 ? 0 : dist <= 3 ? 1 : 2);
// ---- chunks: a pool of mesher workers ---------------------------------------------------------------------------
const chunks = new Map();                      // "face:cu:cv:ch" -> { meshes: [], anchor, busy, dirty }
let pendingPlace = null, localPlace = 0, linkArrive = null;   // linkArrive: the plot a ?plot= link stood the player in (load)                       // a saved place underground, until its plot's edits arrive (load)
const workers = [], queue = [], inflight = new Map();
let reqId = 0;
function startWorkers() {
  const n = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 4) - 1));
  for (let i = 0; i < n; i++) {
    const w = new Worker("/static/land-mesher.js", { type: "module" });
    w.busy = false;
    w.onmessage = (e) => { w.busy = false; finished.push(e.data); pump(); };   // applied within the frame's mesh budget (applyFinished)
    w.onerror = () => { w.busy = false; pump(); };
    workers.push(w);
  }
}
// A PLOT'S EDITS AS THE MESHER TAKES THEM, MADE ONCE (2026-11-24): every chunk's job carried the edits of the nine plots
// around it, each one's key built afresh — by the town hall ~5,000 a job, for every chunk of every column, and a flight
// past the town asks for dozens of jobs a tick (the 100-500 ms updateChunks a profiled flight measured). Each plot's list
// is made once and kept until that plot's edits change: putCell, dropCell, applyPlot and the first hello drop it (plotList).
function editsFor(face, cu, cv) {
  // the chunk's columns and their one-block border: the plots around it (border cells across a seam are rare and
  // carried by their own face's key; wrap() resolves them in the worker the same way)
  let out = [];
  const pc0 = Math.floor(cu * CHUNK / PLOT), pr0 = Math.floor(cv * CHUNK / PLOT);
  for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
    const pr = pr0 + dr, pc = pc0 + dc;
    if (pr < 0 || pc < 0 || pr >= Wd.FACE_N || pc >= Wd.FACE_N) continue;
    const plot = Wd.plotId(face, pr, pc), pe = plotEdit.get(plot);
    if (!pe || !pe.size) continue;
    let list = plotList.get(plot);
    if (!list) {
      const q = Wd.plotCoords(plot);
      list = [];
      for (const [lk, b] of pe) { const [x, z, y] = lk.split(":").map(Number); list.push([key(face, q.u0 + x, q.v0 + z, y), b]); }
      plotList.set(plot, list);
    }
    out = out.length ? out.concat(list) : list.slice();
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
  c.lod = chunkLod(dist);                                   // 0: grass too (not on a phone); 2: far trees, small pieces skipped
  queue.push({ id: ++reqId, k, face, cu, cv, ch, edits: editsFor(face, cu, cv), boxes: pb ? pb.list : null, lod: c.lod, grass: !!SET.grass });   // no blades with grass off (a phone's default, #166)
  pump();
}
/** Which mesher job goes first: the smallest rank. A chunk's is its distance from the player in chunks (+3 on another
 *  face). A forest tile's (#183) is 3 + a thirty-second of its centre's distance, so the whole tree line is built after
 *  the ground underfoot and before the chunks eight away — a design choice (81 tiles cost ~3 s of worker time in all;
 *  a far chunk's trees are the same trees, and until it is meshed the forest's cards stand in for them).
 *  A page hands out one job a worker a FRAME (a result is taken between frames), so a slow page is slow at this too:
 *  measured under a software renderer at 0.4 frames a second, 1.6 jobs a second.
 *  INVARIANT: a forest tile never ranks behind every chunk. It did (+12), and on a page whose chunk queue never empties —
 *  measured at view 8 under a software renderer: still meshing after 8 minutes — the far forest never arrived at all:
 *  "0 far trees" on the readout, and the bare horizon the forest was written to end. */
function jobRank(q, pcu, pcv, face) {
  const d = Math.abs(q.cu - pcu) + Math.abs(q.cv - pcv);
  return q.farland ? FAR_RANK : q.forest ? 3 + d / 32 : d + (q.face === face ? 0 : 3);
}
function pump() {
  for (const w of workers) {
    if (w.busy || !queue.length) continue;
    // nearest first: the player sees the ground under them before the far hills
    let bi = 0, bd = Infinity;
    const pcu = Math.floor(P.u / CHUNK), pcv = Math.floor(P.v / CHUNK);
    for (let i = 0; i < queue.length; i++) { const q = queue[i], d = jobRank(q, pcu, pcv, P.face); if (d < bd) { bd = d; bi = i; } }
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
  if (part.w2) g.setAttribute("w2", new THREE.BufferAttribute(part.w2, 3));   // snow, gravel, forest floor
  if (part.wind) g.setAttribute("wind", new THREE.BufferAttribute(part.wind, 4));
  g.setIndex(new THREE.BufferAttribute(part.idx, 1));
  g.computeBoundingSphere();
  return g;
}
// THE MESH BUDGET (#150; operator 2026-11-12: "the performance varies, there are severe staggers"; measured on the live
// page: "mesh 31.8 ms" in one frame): every worker that finished in the same frame had its chunk — several geometries,
// a chunk of grass blades among them — built and handed to the GPU in that one frame. Finished results now wait in
// `finished` and are applied one after another until MESH_BUDGET_MS of the frame is spent (always at least one), the
// rest next frame: the same work, spread so no frame carries three chunks at once. A result for a chunk no longer
// wanted is dropped by done() as before.
const finished = [], MESH_BUDGET_MS = 6;                   // ms a frame — DESIGN CHOICE (a third of a 60 Hz frame)
function applyFinished() {
  const t0 = performance.now();
  let n = 0;
  while (finished.length && (n === 0 || performance.now() - t0 < MESH_BUDGET_MS)) { done(finished.shift()); n++; }
}
function done(m) {
  const k = inflight.get(m.id); inflight.delete(m.id);
  if (k === "D") return farDone(m);                         // the far ground and the distant land (land-far.js)
  if (k && k[0] === "F") return forestDone(k.slice(2), m);  // a tile of the forest beyond the chunks (#183)
  if (k && k[0] === "C") return canopyDone(k.slice(2), m);  // a tile of the canopy beyond the far trees
  const c = chunks.get(k);
  if (!c) return;
  c.busy = false; c.ready = true;                           // (ready: meshed once — updateForest hides the far trees it now draws)
  for (const me of c.meshes) { scene.remove(me); me.geometry.dispose(); }
  c.meshes = [];
  if (!m.empty && !m.error) {
    c.anchor = m.anchor;
    if (m.smooth) c.meshes.push(new THREE.Mesh(geom(m.smooth), matGround));
    if (m.trees) c.meshes.push(new THREE.Mesh(geom(m.trees), matTrees));
    if (m.bark) c.meshes.push(new THREE.Mesh(geom(m.bark), matBark));
    if (m.foliage) c.meshes.push(new THREE.Mesh(geom(m.foliage), matLeaves));
    if (m.stones) c.meshes.push(new THREE.Mesh(geom(m.stones), matGround));
    if (m.boulders) { const me = new THREE.Mesh(geom(m.boulders), boulderMaterial()); me.castShadow = true; c.meshes.push(me); }   // (#183 step 5: a grey rock)
    if (m.flames) { const me = new THREE.Mesh(geom(m.flames), matFlame); me.renderOrder = 2; c.meshes.push(me); }
    if (m.smoke) { const me = new THREE.Mesh(geom(m.smoke), matSmoke); me.renderOrder = 3; c.meshes.push(me); }   // over the flames (#124)
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
    // flames and smoke cast no shadow and take none: a smoke card's flat shadow on the ground would show it as a card (#124)
    for (const me of c.meshes) { const glow = me.material === matFlame || me.material === matSmoke; me.castShadow = me.material !== matClear && me.material !== matWater && !glow && !me.isInstancedMesh; me.receiveShadow = !glow; scene.add(me); }
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
    const dd = Math.max(Math.abs(dx), Math.abs(dy)), lodNow = chunkLod(dd);
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
  // (a forest tile's job is not a chunk's: updateForest drops it — pruned here, the far forest never arrived, #183)
  // (a far job is no chunk: dropped here it would never land, and farPending would hold every later one back)
  for (let i = queue.length - 1; i >= 0; i--) if (!queue[i].forest && !queue[i].farland && !want.has(queue[i].k)) { const c = chunks.get(queue[i].k); if (c) c.busy = false; queue.splice(i, 1); }
}

// ---- THE FOREST BEYOND THE CHUNKS (#183; operator 2026-11-11, beside a concept picture: "compared to this our game looks
// like from 1996"). Measured at Ultra from a meadow with a wood 144 m ahead: not one tree was drawn past the chunks — the
// land beyond was bare ground to the horizon. land-forest.js builds, a TILE at a time in the mesher workers, every tree
// the world grows as two crossed cards carrying a PICTURE OF ITS OWN MODEL (bakeForest), out to FOREST_RANGE.
// INVARIANTS — each one a way this shipped wrong or would:
//  * a far tree is hidden exactly where its chunk's own meshes are in the scene (forestSeen, a map of meshed chunk
//    columns the material reads in the vertex stage), never by distance alone: a chunk still in the mesher's queue
//    would show a ring of bare ground at the view's edge with every step forward;
//  * the atlas is read BACK from the GPU and laid out by a marker the bake draws: a render target's rows run top-down
//    on WebGPU and bottom-up on WebGL2, and a forest standing on its crowns in one of the two is not a thing a
//    headless (WebGL2) test can catch;
//  * the cards are indexed from both sides and drawn front-face only: a double-sided material flips the normal of a
//    back face, and a crown seen from behind went dark.
const forest = new Map();                      // "face:tu:tv" -> { mesh, busy, n }
const FOREST_RANGE = PHONE ? 640 : 1152;       // m of far trees around the player — a design choice: 81 tiles, ~60 000 trees, ~36 ms a tile in a worker
/** The far trees' reach for the current preset: the full range, halved on Low (view ≤ 3 chunks) — a quarter of the tiles.
 *  Measured 2026-11-12 at the landing on Low: 26,452 far trees at 8 triangles each were 212k of a 474k frame, nearly
 *  half of it, on the preset meant for weak devices (#150). updateForest prunes the tiles outside the reach. */
const forestRange = () => (SET.view <= 3 ? FOREST_RANGE / 2 : FOREST_RANGE);
const SEEN = 64;                               // the meshed-chunk map's edge, in chunks (the view disc is 17 across at most)
// (0.5, 14 m and (0.03, 0.055, 0.016), was 0.35, 9 m and (0.012, 0.022, 0.007) — 2026-11-25: the conifers' bare trunks between
// 9 m and their crowns read as a near-black band half the wood's height at the vale, where the shot's wood edge is leaves to the
// ground; the foot is now a dark understorey green up to 14 m)
const UNDER_SHADE = 0.5, UNDER_FROM = 3, UNDER_TO = 14, UNDER_COL = [0.03, 0.055, 0.016];   // a far tree's foot in the canopy's shade: half its own colour x UNDER_SHADE, half the understorey's green, up to 3 m; full light by 14 m
let matForest = null, forestNear = null, forestSeen = null, forestSeenTex = null, forestTrees = 0;
/** The map of meshed chunk columns the far trees and the far boxes (#193) read: allocated once, by whichever asks first. */
function ensureSeen() {
  if (forestSeen) return;
  forestSeen = new Uint8Array(SEEN * SEEN);
  forestSeenTex = new THREE.DataTexture(forestSeen, SEEN, SEEN, THREE.RedFormat, THREE.UnsignedByteType);
  forestSeenTex.wrapS = forestSeenTex.wrapT = THREE.RepeatWrapping; forestSeenTex.magFilter = forestSeenTex.minFilter = THREE.NearestFilter; forestSeenTex.needsUpdate = true;
  forestNear = TSL.uniform(new THREE.Vector3(0, 0, -1));
}
/** 1 where a far thing is drawn, 0 where its chunk (the vertex attribute `root`: cu, cv) is inside the view disc AND that
 *  chunk's meshes are in the scene — the near thing stands there (the invariant above). */
function seenShow() {
  const root = TSL.attribute("root", "vec2"), d = root.sub(forestNear.xy);
  const meshed = TSL.texture(forestSeenTex, root.add(0.5).div(SEEN)).level(0).r;
  return TSL.select(d.dot(d).lessThanEqual(forestNear.z).and(meshed.greaterThan(0.5)), 0, 1);
}
/** The far trees' pictures: every (species, height) of land-forest SLOTS, its own land-trees model seen from the side
 *  under an even sky, drawn once into a render target and read back into the atlas texture. */
async function bakeForest() {
  // the scanned leaves first (paintLeaves), so the far cards are pictures of the crowns a player walks up to — at most 8 s
  if (matLeaves && matLeaves.userData.ready) await Promise.race([matLeaves.userData.ready, new Promise((r) => setTimeout(r, 8000))]);
  const { cols, rows, wide, tall, foot } = Forest.ATLAS, pw = PHONE ? 768 : 1536, ph = Math.round(pw * rows * tall / (cols * wide));   // (a width whose rows need no padding: 4·pw is a multiple of 256)
  const rt = new THREE.RenderTarget(pw, ph), sc = new THREE.Scene(), cam = new THREE.OrthographicCamera(0, cols * wide, rows * tall, 0, 1, 100);
  cam.position.set(0, 0, 50);
  // (1.5, was 2.6: the far card is lit AGAIN in the scene — the picture is close to the leaves' own colour, not a sunlit
  // photograph of them; at 2.6 the far forest read pale lime, measured 64, 96, 61 against the reference's 44, 56, 30)
  sc.add(new THREE.HemisphereLight(0xffffff, 0x8c8c84, 1.5));
  // bark in its texture's own mean colour (measured, linear: bark_col 0.126 0.104 0.063, birch_col 0.056 0.037 0.025) —
  // the scans load after this runs, and a far trunk is a few pixels wide
  const flat = new THREE.MeshStandardNodeMaterial({ roughness: 0.92, metalness: 0 });
  flat.colorNode = TSL.mix(TSL.vec3(0.126, 0.104, 0.063), TSL.vec3(0.056, 0.037, 0.025), TSL.attribute("tile", "float")).mul(TSL.attribute("color", "vec3"));
  const made = [];
  Forest.SLOTS.forEach(([kind, height], i) => {
    const m = treeModel(kind, height, 7919 + height * 131 + kind.length, 2);      // the mesher's far model, variant 0 (placeTree)
    for (const [src, mat] of [[m.bark, flat], [m.leaves, matLeaves]]) {
      if (!src.n) continue;
      const g = new THREE.BufferGeometry(), pos = new Float32Array(src.n * 3), nor = new Float32Array(src.n * 3);
      for (let k = 0; k < src.n; k++) {                    // the model's (x, y, z up) seen along its y: x across, z up
        pos[k * 3] = src.pos[k * 3]; pos[k * 3 + 1] = src.pos[k * 3 + 2]; pos[k * 3 + 2] = -src.pos[k * 3 + 1];
        nor[k * 3] = src.nor[k * 3]; nor[k * 3 + 1] = src.nor[k * 3 + 2]; nor[k * 3 + 2] = -src.nor[k * 3 + 1];
      }
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("normal", new THREE.BufferAttribute(nor, 3));
      g.setAttribute("uv", new THREE.Float32BufferAttribute(src.uv, 2)); g.setAttribute("tile", new THREE.Float32BufferAttribute(src.tile, 1));
      g.setAttribute("color", new THREE.Float32BufferAttribute(src.col, 3)); g.setAttribute("wind", new THREE.BufferAttribute(new Float32Array(src.n * 4), 4));   // (no wind: a still picture)
      g.setIndex(src.idx);
      const me = new THREE.Mesh(g, mat); me.position.set((i % cols + 0.5) * wide, Math.floor(i / cols) * tall + foot, 0); me.frustumCulled = false;
      sc.add(me); made.push(g);
    }
  });
  // the marker: the last slot (no tree's) filled magenta — where it lands in the read-back rows says which way they run
  const mk = new THREE.Mesh(new THREE.PlaneGeometry(wide, tall), new THREE.MeshBasicMaterial({ color: 0xff00ff, fog: false }));
  mk.position.set((cols - 0.5) * wide, (rows - 0.5) * tall, 0); sc.add(mk); made.push(mk.geometry);
  const was = new THREE.Color(); renderer.getClearColor(was); const wasA = renderer.getClearAlpha();
  renderer.setClearColor(0x1c2a10, 0);                     // (leaf-dark, clear: what the edges of a crown blend toward in the small mips)
  renderer.setRenderTarget(rt); renderer.render(sc, cam); renderer.setRenderTarget(null);
  renderer.setClearColor(was, wasA);
  const raw = await renderer.readRenderTargetPixelsAsync(rt, 0, 0, pw, ph), px = new Uint8Array(pw * ph * 4);
  const mag = (row) => { const o = (row * pw + Math.round(pw * (cols - 0.5) / cols)) * 4; return raw[o] > 200 && raw[o + 1] < 60 && raw[o + 2] > 200; };
  const topRow = Math.round(ph * 0.25), flip = mag(topRow) && !mag(ph - 1 - topRow);     // the marker is in the TOP row of slots: found early = rows run top-down
  for (let y = 0; y < ph; y++) px.set(raw.subarray((flip ? ph - 1 - y : y) * pw * 4, ((flip ? ph - 1 - y : y) + 1) * pw * 4), y * pw * 4);
  const x0 = Math.floor(pw * (cols - 1) / cols), y0 = Math.floor(ph * (rows - 1) / rows);
  for (let y = y0; y < ph; y++) px.fill(0, (y * pw + x0) * 4, (y + 1) * pw * 4);       // the marker's slot back to clear
  for (const g of made) g.dispose(); rt.dispose(); flat.dispose();
  const tex = new THREE.DataTexture(px, pw, ph, THREE.RGBAFormat, THREE.UnsignedByteType);
  tex.colorSpace = THREE.NoColorSpace; tex.magFilter = THREE.LinearFilter; tex.minFilter = THREE.LinearMipmapLinearFilter; tex.generateMipmaps = true; tex.needsUpdate = true;
  ensureSeen();
  // A FAR CROWN IS MATTE (2026-11-24, the live vale beside the Chlorophyll shot): with a standard material's specular the
  // whole wood wore a white veil — looking toward the sun the far forest was a pale grey wall, and even front-lit it
  // measured (65, 79, 56), saturation 16, the blue the veil's, against the reference's (46, 58, 36), 24. Diffuse only
  // (Lambert), the same picture measured (47, 64, 36), saturation 28, at the same held moment. (Not the Fresnel of
  // edge-on cards: the eye meets the crown normals at a median |N·V| of 0.53 — a sheen of 6 % against 4 % face on.)
  const m = new THREE.MeshLambertNodeMaterial({ alphaTest: 0.4 }), s = TSL.texture(tex, TSL.uv());
  const show = seenShow();
  m.positionNode = TSL.positionLocal.add(TSL.attribute("off", "vec3").mul(show));
  // a far tree's picture, warmed toward the forest's olive: under the sky's blue fill the far cards read grey cut-outs
  // (measured with the forest band at 72, 86, 76 against the reference's 44, 56, 30, 2026-11-22)
  // (then 0.95, 1.0, 0.55: with the bloom's veil gone and the clouds off, two live photos agreeing to within 1 read the
  // forest (27, 47, 23) against the reference's (43, 54, 28) — too dark and too pure a green: red up ~60 %, green ~15 %)
  // UNDER THE CANOPY IS SHADE (2026-11-23, from a meadow beside the Chlorophyll shot: a wood's edge 300 m off read as a
  // lit brown stripe of trunks under its crowns, where under a real canopy the trunks and the shrubs stand in its shade):
  // a card's lower metres — its height over its root (its vertex's offset along the up there) — darken to UNDER_SHADE
  const up = TSL.positionWorld.sub(hazeCam.c).normalize(), overRoot = TSL.varying(TSL.dot(TSL.attribute("off", "vec3"), up));
  // (darkened alone it still read as a stripe of separate brown trunks: the shade there is leaves and shrubs, so the foot
  // turns toward UNDER_COL, the dark green of a wood's understorey in its own shade)
  // (2.6, 1.75, 1.1, was 2.0, 1.25, 0.75 — 2026-11-25, the vale's wood like for like against the shot's near wood (50, 63, 37):
  // it measured (17, 27, 8) and (27, 47, 17), clouds and shadows off alike — its own colour, not a shadow; now (26, 43, 14) and
  // (31, 58, 20). The shot's remaining blue is its air's haze at that range, which stays as clear as the operator asked)
  const lit = s.rgb.mul(TSL.attribute("color", "vec3")).mul(TSL.vec3(2.6, 1.75, 1.1));
  // (TSL.mix(a, b, t) written out: the chained x.mix(a, b) is mix(a, b, x) — x the factor — and read as mix(x, a, b) it
  // painted every card with its own colour as the factor)
  const underShade = TSL.mix(TSL.mix(TSL.vec3(...UNDER_COL), lit.mul(UNDER_SHADE), 0.5), lit, TSL.smoothstep(UNDER_FROM, UNDER_TO, overRoot));
  m.colorNode = shadeByClouds(underShade);   // (1.45, 1.1, 0.65 measured 31, 48, 24 at one held moment, clouds off: still dark, short of red)
  m.opacityNode = s.a;
  // A CARD'S SHADOW IS ITS CUT-OUT, NOT ITS RECTANGLE: three's shadow pass takes a material's alpha from its colour node
  // and its map, never from opacityNode, so a card with a three-channel colour cast its whole quad — every far tree a
  // dark slab across the meadow (the first cascade shot, 2026-11-13). maskShadowNode discards in the shadow pass alone.
  m.maskShadowNode = s.a.greaterThan(0.4);
  matForest = m;
}
function forestDone(k, m) {
  const f = forest.get(k);
  if (!f) return;
  f.busy = false;
  if (!m.n) return;
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(m.pos, 3)); g.setAttribute("off", new THREE.BufferAttribute(m.off, 3));
  g.setAttribute("normal", new THREE.BufferAttribute(m.nor, 3)); g.setAttribute("uv", new THREE.BufferAttribute(m.uv, 2));
  g.setAttribute("root", new THREE.BufferAttribute(m.root, 2)); g.setAttribute("color", new THREE.BufferAttribute(m.col, 3));
  g.setIndex(new THREE.BufferAttribute(m.idx, 1));
  g.computeBoundingSphere(); g.boundingSphere.radius += 16;   // (position is each tree's ROOT: the cards reach up and out from it)
  f.mesh = new THREE.Mesh(g, matForest); f.mesh.userData.anchor = m.anchor; f.n = m.n; forestTrees += m.n;
  f.mesh.castShadow = true;                                  // the far trees cast too: the long shadows across the far ground (#183 step 4)
  scene.add(f.mesh);
}
/** The forest tiles around the player, and which chunk columns the scene has meshed (their far trees hide). */
function updateForest() {
  if (!forestSeen) return;
  const T = Forest.TILE, face = P.face, pcu = Math.floor(P.u / CHUNK), pcv = Math.floor(P.v / CHUNK), want = new Set();
  const R = forestRange();
  if (matForest) for (let tv = Math.floor((P.v - R) / T); tv <= Math.floor((P.v + R) / T); tv++)   // (no atlas yet: the seen map alone, for the far boxes)
    for (let tu = Math.floor((P.u - R) / T); tu <= Math.floor((P.u + R) / T); tu++) {
      const du = Math.max(tu * T - P.u, 0, P.u - (tu + 1) * T), dv = Math.max(tv * T - P.v, 0, P.v - (tv + 1) * T);
      if (du * du + dv * dv > R * R) continue;
      const k = face + ":" + tu + ":" + tv; want.add(k);
      if (!forest.has(k)) { forest.set(k, { mesh: null, busy: true, n: 0 }); queue.push({ id: ++reqId, k: "F:" + k, forest: 1, face, tu, tv, cu: tu * 16 + 8, cv: tv * 16 + 8 }); }
    }
  pump();
  for (const [k, f] of forest) if (!want.has(k) && !f.busy) {
    if (f.mesh) { scene.remove(f.mesh); f.mesh.geometry.dispose(); forestTrees -= f.n; }
    forest.delete(k);
  }
  const ready = new Map();
  for (const [k, c] of chunks) { const ck = k.slice(0, k.lastIndexOf(":")); ready.set(ck, ready.get(ck) !== false && !!c.ready); }
  let changed = false;
  const mark = (i, v) => { if (forestSeen[i] !== v) { forestSeen[i] = v; changed = true; } };
  const now = new Uint8Array(SEEN * SEEN);
  for (let dx = -viewDist; dx <= viewDist; dx++) for (let dy = -viewDist; dy <= viewDist; dy++) {
    if (dx * dx + dy * dy > viewDist * viewDist + 1) continue;
    let f2 = face, cu = pcu + dx, cv = pcv + dy;              // (the chunk's own key, past a face edge: as updateChunks names it)
    if (cu < 0 || cv < 0 || cu >= W / CHUNK || cv >= W / CHUNK) { const w = Wd.wrap(face, cu * CHUNK + 8, cv * CHUNK + 8); f2 = w.face; cu = Math.floor(w.u / CHUNK); cv = Math.floor(w.v / CHUNK); }
    if (ready.get(f2 + ":" + cu + ":" + cv)) now[(((pcv + dy) % SEEN + SEEN) % SEEN) * SEEN + ((pcu + dx) % SEEN + SEEN) % SEEN] = 255;
  }
  for (let i = 0; i < now.length; i++) mark(i, now[i]);
  if (changed) forestSeenTex.needsUpdate = true;
  forestNear.value.set(pcu, pcv, viewDist * viewDist + 1);
}

// ---- THE CANOPY BEYOND THE FAR TREES (the Chlorophyll bar, operator 2026-11-21: "keep going until you match the graphical
// fidelity"; its engine streams a far tile's trees out and draws the tile "as one aggregate"). The card trees end at
// forestRange(); past them, out to the far ground's edge, the hills were bare — the band where the reference's forests
// stand. A canopy tile (land-forest.js canopyTile, built in the mesher workers) is one heightfield over the forest a tile
// holds, Forest.CANOPY_TILE (1,024 m) a side: one draw for what as cards would be ~60 000 trees. It is drawn from
// CANOPY_NEAR out (canopyIn), under the card trees within their reach and alone beyond it.
const CANOPY_RANGE = PHONE ? 1400 : 1700;      // m — to the far ground's edge (buildFar: 36 cells of 48 m each way)
// FROM 400 m, UNDER THE CARD TREES (the Chlorophyll bar, measured live 2026-11-22: within the card trees' reach the forest
// read as scattered trees over a band, where the reference's is one continuous canopy): the planet grows a tree on ~9 %
// of a forest's columns and none within 2 of a plot edge, so its cards alone leave sky and ground showing between them.
// The canopy now starts CANOPY_NEAR out (past the meshed chunks, ≤128 m, so it never meets a modelled tree) and the cards
// stand in and over it — the mass is continuous, the cards give it its single trees. No longer tied to the cards' reach.
const CANOPY_NEAR = PHONE ? 300 : 400;
const canopy = new Map();                      // "face:tu:tv" -> { mesh, busy, n }
let matCanopy = null, canopyIn = null, canopyCells = 0;
function canopyMaterial() {
  canopyIn = TSL.uniform(CANOPY_NEAR);
  const m = new THREE.MeshStandardNodeMaterial({ roughness: 0.9, metalness: 0, alphaTest: 0.5 });
  // a forest's mass from far off: dark leaf green (the reference's far forest measures rgb 44, 56, 30), each crown its own
  // shade (the vertex colour), lit by the sun and shaded by the clouds as the far trees are
  // (0.035, 0.062, 0.018 read too light; 0.034, 0.05, 0.016 under the sky's blue fill read grey-green, 72, 86, 76 against
  // the reference's 44, 56, 30 — so the blue is all but gone: a dark olive the sky's light cannot grey)
  // (then 0.036, 0.052, 0.006: read with the cards (27, 47, 23), too dark and too pure a green — red up, as the cards')
  m.colorNode = shadeByClouds(TSL.vec3(0.076, 0.066, 0.009).mul(TSL.attribute("color", "vec3")));
  m.opacityNode = TSL.step(canopyIn, TSL.positionWorld.sub(TSL.cameraPosition).length());   // none inside the card trees' reach
  matCanopy = m;
}
function canopyDone(k, m) {
  const f = canopy.get(k);
  if (!f) return;
  f.busy = false;
  if (!m.n) return;
  if (!matCanopy) canopyMaterial();
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(m.pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(m.col, 3));
  g.setIndex(new THREE.BufferAttribute(m.idx, 1)); g.computeVertexNormals(); g.computeBoundingSphere();
  f.mesh = new THREE.Mesh(g, matCanopy); f.mesh.userData.anchor = m.anchor; f.n = m.n; canopyCells += m.n;
  f.mesh.receiveShadow = true;
  scene.add(f.mesh);
}
/** The canopy tiles in the band from the card trees' reach to CANOPY_RANGE, the rest dropped. */
function updateCanopy() {
  const T = Forest.CANOPY_TILE, face = P.face, Rin = CANOPY_NEAR, want = new Set();
  for (let tv = Math.floor((P.v - CANOPY_RANGE) / T); tv <= Math.floor((P.v + CANOPY_RANGE) / T); tv++)
    for (let tu = Math.floor((P.u - CANOPY_RANGE) / T); tu <= Math.floor((P.u + CANOPY_RANGE) / T); tu++) {
      const du = Math.max(tu * T - P.u, 0, P.u - (tu + 1) * T), dv = Math.max(tv * T - P.v, 0, P.v - (tv + 1) * T);
      const fu = Math.max(Math.abs(tu * T - P.u), Math.abs((tu + 1) * T - P.u)), fv = Math.max(Math.abs(tv * T - P.v), Math.abs((tv + 1) * T - P.v));
      if (du * du + dv * dv > CANOPY_RANGE * CANOPY_RANGE || fu * fu + fv * fv < Rin * Rin) continue;   // out of reach, or all within the card trees'
      const k = face + ":" + tu + ":" + tv; want.add(k);
      if (!canopy.has(k)) { canopy.set(k, { mesh: null, busy: true, n: 0 }); queue.push({ id: ++reqId, k: "C:" + k, forest: 1, canopy: 1, face, tu, tv, cu: tu * (T / CHUNK) + T / CHUNK / 2, cv: tv * (T / CHUNK) + T / CHUNK / 2 }); }
    }
  pump();
  for (const [k, f] of canopy) if (!want.has(k) && !f.busy) {
    if (f.mesh) { scene.remove(f.mesh); f.mesh.geometry.dispose(); canopyCells -= f.n; }
    canopy.delete(k);
  }
}

// ---- THE BUILT LAND SEEN FROM FAR (#193; operator 2026-11-12: "the village is only visible from like 50 meters away,
// this means that large cities will be completely invisible - we must fix this, and efficiently so"). Pieces exist only
// in the chunk mesher's disc (48–128 m). Beyond it every built plot's pieces come from the world server's far view
// (GET /land/api/far: each piece as its box and block) and are drawn as ONE instanced mesh of boxes — a whole city in one
// draw call — out to FAR_BUILD, each box in its block's atlas colour, lit and fogged like the far ground, and hidden
// exactly where its chunk's own meshes are in the scene (seenShow, as the far trees). The set is asked for again every
// FAR_BUILD_S seconds with the versions held (unchanged plots come back bare), so a city costs one small request a cycle.
const FAR_BUILD = PHONE ? 800 : 2000, FAR_BUILD_S = 15, FAR_BUILD_MAX = 40000;   // m, s, boxes — design choices (measured: see #193)
const farPlots = new Map();                     // plot -> { ver, boxes }
let farBoxMesh = null, farBoxes = 0, farBuildAt = 0, farBuildBusy = false, farBuildKey = "";
function blockColour(blk) {
  const b = Wd.BLOCKS[blk], t = b && b.tex ? b.tex[1] : 0, pnt = PAINT[t];
  return new THREE.Color(pnt ? pnt[0] : "#8d8a85");
}
async function farBuildTick(now) {
  if (!scene || farBuildBusy || now - farBuildAt < FAR_BUILD_S * 1000) return;
  farBuildAt = now; farBuildBusy = true;
  try {
    const since = {}; for (const [p, r] of farPlots) since[p] = r.ver;
    const q = `face=${P.face}&u=${P.u.toFixed(1)}&v=${P.v.toFixed(1)}&r=${FAR_BUILD}&since=${encodeURIComponent(JSON.stringify(since))}`;
    const res = await fetch("/land/api/far?" + q, { credentials: "same-origin" });
    if (!res.ok) return;
    const got = (await res.json()).plots || [], keep = new Set();
    let changed = false;
    for (const pl of got) {
      keep.add(pl.plot);
      const have = farPlots.get(pl.plot);
      if (pl.boxes) { farPlots.set(pl.plot, { ver: pl.ver, boxes: pl.boxes }); changed = true; }
      else if (!have) changed = true;
    }
    for (const p of [...farPlots.keys()]) if (!keep.has(p)) { farPlots.delete(p); changed = true; }
    if (changed || !farBoxMesh) buildFarBoxes();
  } catch (e) { /* offline: the last set stands */ } finally { farBuildBusy = false; }
}
/** The instanced boxes of every far plot held: built around the player's frame now (a box 2 km off leans 1.4° by the
 *  planet's curve — unseen; its PLACE is exact, posOf). */
function buildFarBoxes() {
  ensureSeen();
  const list = [];
  for (const [plot, r] of farPlots) {
    const q = Wd.plotCoords(plot);
    for (const b of r.boxes) {
      const blk = Wd.BLOCKS[b[6]];
      if (!blk || !blk.solid || blk.see) continue;                          // glass, leaves: nothing to see from afar
      list.push([q, b]);
      if (list.length >= FAR_BUILD_MAX) break;
    }
  }
  if (farBoxMesh) { scene.remove(farBoxMesh); farBoxMesh.geometry.dispose(); farBoxMesh = null; }
  farBoxes = list.length;
  if (!list.length) return;
  const fr = Wd.frameOf(P.face, P.u, P.v), anchor = Wd.posOf(P.face, P.u, P.v, Wd.SEA);
  const n = list.length, off = new Float32Array(n * 3), ext = new Float32Array(n * 3), col = new Float32Array(n * 3), root = new Float32Array(n * 2);
  const c = new THREE.Color();
  list.forEach(([q, b], i) => {
    const u = q.u0 + (b[0] + b[3] / 2) / 100, v = q.v0 + (b[1] + b[4] / 2) / 100, h = (b[2] + b[5] / 2) / 100, p = Wd.posOf(q.face, u, v, h);
    off[i * 3] = p[0] - anchor[0]; off[i * 3 + 1] = p[1] - anchor[1]; off[i * 3 + 2] = p[2] - anchor[2];
    ext[i * 3] = b[3] / 200; ext[i * 3 + 1] = b[4] / 200; ext[i * 3 + 2] = b[5] / 200;
    c.copy(blockColour(b[6])); col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    root[i * 2] = Math.floor(u / CHUNK); root[i * 2 + 1] = Math.floor(v / CHUNK);
  });
  const base = new THREE.BoxGeometry(1, 1, 1), g = new THREE.InstancedBufferGeometry();
  g.setAttribute("position", base.getAttribute("position")); g.setAttribute("normal", base.getAttribute("normal")); g.setAttribute("uv", base.getAttribute("uv")); g.setIndex(base.getIndex());
  g.setAttribute("off", new THREE.InstancedBufferAttribute(off, 3)); g.setAttribute("ext", new THREE.InstancedBufferAttribute(ext, 3));
  g.setAttribute("col", new THREE.InstancedBufferAttribute(col, 3)); g.setAttribute("root", new THREE.InstancedBufferAttribute(root, 2));
  g.instanceCount = n;
  const m = new THREE.MeshStandardNodeMaterial({ roughness: 0.9, metalness: 0 });
  // the unit cube's x, y, z are the plot's east, north, up: scaled to the box, turned into the player's frame, set at
  // its place — and collapsed to nothing where its chunk is meshed (seenShow)
  const E = TSL.uniform(new THREE.Vector3(...fr.east)), N = TSL.uniform(new THREE.Vector3(...fr.north)), U = TSL.uniform(new THREE.Vector3(...fr.up));
  const l = TSL.positionLocal.mul(TSL.attribute("ext", "vec3")).mul(2).mul(seenShow());
  m.positionNode = E.mul(l.x).add(N.mul(l.y)).add(U.mul(l.z)).add(TSL.attribute("off", "vec3"));
  const nl = TSL.normalLocal;
  const nn = E.mul(nl.x).add(N.mul(nl.y)).add(U.mul(nl.z));
  m.setupPosition = function (builder) { TSL.normalLocal.assign(nn); return Object.getPrototypeOf(this).setupPosition.call(this, builder); };
  m.colorNode = shadeByClouds(TSL.attribute("col", "vec3"));
  farBoxMesh = new THREE.Mesh(g, m); farBoxMesh.frustumCulled = false; farBoxMesh.userData.anchor = anchor; farBoxMesh.renderOrder = 0;
  scene.add(farBoxMesh);
}

// ---- the far land: the ground beyond the chunks and the distant land out to 30 km (static/land-far.js) ------------
// In the ground's own material ("did you fix the bland untextured marches?", operator 2026-11-06): the far ground's every
// vertex carries the six texture weights the mesher gives the near ground, and the sea is the near water's own surface.
// Past it, a clipmap of RINGS out to 30 km in the canopy's and the ground's colours (land-far.js says why: "very stupid
// and short", operator 2026-11-23 — the land ended in a rim 3.8 km out).
// OFF THE MAIN THREAD: the pieces are built by a mesher worker as one job (rank FAR_RANK) and swapped in together when it
// lands, so a ring and the ring inside it always share their edge; this page only wraps the buffers it is handed. (Built
// here they cost ~9,000 column samples, a third of a second of frame, every 400 m.)
// INVARIANT: one far job at a time (farPending), and a ring is rebuilt with the ring inside it whenever that ring's
// anchor moves — its hole IS that ring's square. A ring built against an older square would leave a gap or a double.
let farSea = null, farPending = false, farForce = false, matOuter = null;
const ringMeshes = Far.RINGS.map(() => null), ringAt = Far.RINGS.map(() => null);
// a far job's queue rank: FIRST — it is one job (~0.7 s of one worker) and the land to the horizon depends on it; ranked
// after the chunks beside the player (1.5) it waited behind ~80 of them (16 a column), and a software-rendered page
// photographed the sky through the ground where the far ground was still queued (the cloud-shadow walk, 2026-11-23)
const FAR_RANK = -1;
function buildFar() { farForce = true; updateFar(); }   // the view distance changed: the far ground's sunk square follows it
function updateFar() {
  if (farPending || !scene) return;
  const face = P.face, FAR_HALF = Far.FAR_N / 2 * Far.FAR_STEP;
  const groundDue = farForce || !farAt || farAt.face !== face || Math.abs(farAt.u - P.u) > 400 || Math.abs(farAt.v - P.v) > 400;
  const fu = groundDue ? Math.round(P.u / Far.FAR_STEP) * Far.FAR_STEP : farAt.u, fv = groundDue ? Math.round(P.v / Far.FAR_STEP) * Far.FAR_STEP : farAt.v;
  const want = Far.RINGS.map((_, k) => Far.ringAnchor(k, P.u, P.v)), redo = new Set();
  want.forEach((a, k) => { const at = ringAt[k]; if (!at || at.face !== face || at.u !== a[0] || at.v !== a[1]) { redo.add(k); if (k + 1 < Far.RINGS.length) redo.add(k + 1); } });
  if (groundDue) redo.add(0);                                // ring 0 sinks under the far ground's square
  if (!redo.size) return;
  const at = (k) => (redo.has(k) ? want[k] : [ringAt[k].u, ringAt[k].v]);
  const rings = [...redo].sort((x, y) => x - y).map((k) => {
    const [au, av] = at(k);
    if (k === 0) {                                           // inside the far ground, less a cell of overlap that sinks under it
      const r = FAR_HALF - Far.RINGS[0].step;
      return { k, au, av, hole: [fu - r, fu + r, fv - r, fv + r], sink: [fu, fv, FAR_HALF - Far.FAR_STEP] };
    }
    const [pu, pv] = at(k - 1), h = Far.RINGS[k - 1].half;
    return { k, au, av, hole: [pu - h, pu + h, pv - h, pv + h], sink: null };
  });
  farForce = false; farPending = true;
  queue.push({ id: ++reqId, k: "D", farland: true, face, ground: groundDue ? { fu, fv, nearHalf: viewDist * CHUNK } : null, rings });
  pump();
}
// THE DISTANT LAND'S GRAIN ("the photos show the far land as smooth colour patches", 2026-11-23): a ring's vertex is
// 128-1024 m from the next, so its colour alone is one flat olive per forest and one green per field. Noise on the
// vertex's own planet place (uvw, stable as the eye moves) breaks it up: crowns and the gaps between them (25 m), groves
// (120 m) and the lie of the land (500 m) in a forest, patches of lusher and drier grass in a field (50 m, 300 m) — each
// faded out where it would be under ~4 pixels across (RING_PX metres a pixel a metre away), where it could only shimmer.
// The sea keeps its colour.
const RING_PX = 0.0009;                        // m a pixel per m of distance at a 72° view across ~1,400 px (a design choice)
function ringMaterial() {
  const m = new THREE.MeshStandardNodeMaterial({ roughness: 0.95, metalness: 0 });
  const col = TSL.attribute("color", "vec3"), uvw = TSL.attribute("uvw", "vec3"), px = TSL.positionView.length().mul(RING_PX);
  const layer = (wl, amp) => TSL.mx_noise_float(uvw.xy.div(wl)).mul(amp).mul(TSL.smoothstep(px.mul(3), px.mul(6), TSL.float(wl)));
  const forest = TSL.step(col.g, TSL.float(0.07)).mul(TSL.step(col.b, TSL.float(0.02)));      // the canopy's olive (RING_COL.forest)
  const sea = TSL.step(col.g, col.b);                                                          // blue over green: the sea
  const grain = TSL.mix(TSL.float(1).add(layer(50, 0.22)).add(layer(300, 0.16)),               // a field
    TSL.float(1).add(layer(25, 0.45)).add(layer(120, 0.3)).add(layer(500, 0.15)), forest);    // a forest
  m.colorNode = shadeByClouds(col.mul(TSL.mix(grain.max(0.3), TSL.float(1), sea)));
  // A LARGER PLANET'S HORIZON FROM THE GROUND (2026-11-23): on this planet (R0 ~83 km, the land at most ~150 m over the sea
  // in a world 256 blocks high) the ground 5 km off lies 150 m under the horizon, so from a meadow no range anywhere stood
  // over the land in front of it (a search of the face: none 0.6° over, three 0.1°) — the distant land's rings drew what
  // no eye on the ground could see. Past HORIZON_FROM the rings are lifted by HORIZON_K of the planet's fall away (d²/2R),
  // reaching it by HORIZON_TO: the distant land reads as on a planet 1/(1 - K) times the size; the near land and the far
  // ground (to 1.7 km) are untouched. Lifted less as the eye climbs (HORIZON_EYE): from the air the planet is round.
  const wp = TSL.modelWorldMatrix.mul(TSL.vec4(TSL.positionLocal, 1)).xyz, d = wp.length(), upv = wp.sub(hazeCam.c).normalize();
  const lift = d.mul(d).div(2 * (Wd.R0 + Wd.SEA)).mul(HORIZON_K).mul(TSL.smoothstep(HORIZON_FROM, HORIZON_TO, d))
    .mul(TSL.float(1).sub(TSL.smoothstep(HORIZON_EYE[0], HORIZON_EYE[1], hazeCam.h)));
  m.positionNode = TSL.positionLocal.add(upv.mul(lift));
  return m;
}
const HORIZON_K = 0.85, HORIZON_FROM = 2000, HORIZON_TO = 5000, HORIZON_EYE = [300, 2000];   // a design choice: see ringMaterial
function farDone(m) {
  farPending = false;
  if (m.error) { console.warn("far land: " + m.error); return; }
  const anchored = (mesh, anchor) => { mesh.userData.anchor = anchor; scene.add(mesh); return mesh; };
  if (m.ground) {
    const r = m.ground, g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(r.pos, 3)); g.setAttribute("normal", new THREE.BufferAttribute(r.nor, 3));
    g.setAttribute("uvw", new THREE.BufferAttribute(r.uvw, 3)); g.setAttribute("gn", new THREE.BufferAttribute(r.gn, 3));
    g.setAttribute("w1", new THREE.BufferAttribute(r.w1, 4)); g.setAttribute("w2", new THREE.BufferAttribute(r.w2, 3));
    g.setAttribute("color", new THREE.BufferAttribute(r.col, 3)); g.setIndex(new THREE.BufferAttribute(r.idx, 1)); g.computeBoundingSphere();
    const gs = new THREE.BufferGeometry();
    gs.setAttribute("position", new THREE.BufferAttribute(r.sea, 3)); gs.setAttribute("normal", new THREE.BufferAttribute(r.seaNor, 3));
    gs.setAttribute("uvw", new THREE.BufferAttribute(r.suvw, 3)); gs.setIndex(new THREE.BufferAttribute(r.idx, 1)); gs.computeBoundingSphere();
    for (const old of [farMesh, farSea]) if (old) { scene.remove(old); old.geometry.dispose(); }
    farMesh = new THREE.Mesh(g, matGround); farMesh.receiveShadow = true;
    farSea = new THREE.Mesh(gs, matWater); farSea.renderOrder = 1;
    anchored(farMesh, r.anchor); anchored(farSea, r.anchor);
    farAt = { face: r.face, u: r.fu, v: r.fv };
  }
  if (!matOuter && m.rings.length) matOuter = ringMaterial();
  for (const r of m.rings) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(r.pos, 3)); g.setAttribute("normal", new THREE.BufferAttribute(r.nor, 3));
    g.setAttribute("color", new THREE.BufferAttribute(r.col, 3)); g.setAttribute("uvw", new THREE.BufferAttribute(r.uvw, 3)); g.setIndex(new THREE.BufferAttribute(r.idx, 1));
    const old = ringMeshes[r.k]; if (old) { scene.remove(old); old.geometry.dispose(); }
    const mesh = new THREE.Mesh(g, matOuter); mesh.frustumCulled = false;
    ringMeshes[r.k] = anchored(mesh, r.anchor);
    ringAt[r.k] = { face: r.face, u: r.au, v: r.av };
  }
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
    // the titles are known (the nearest-source hint waits for it) — counted again only when they CHANGE: refreshed every
    // few seconds, a bump on every refresh restarted the hint's search before a slow device ever finished one (playtest
    // 2026-11-15: no hint after 9 minutes, the region asked for 30 times)
    const sig = [...titles.keys()].sort((x, y) => x - y).join(",") + "|" + [...mine].sort((x, y) => x - y).join(",");
    if (sig !== titlesSig) { titlesSig = sig; titlesVer++; }
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
// ONE READ FOR THE PLOTS THAT ASK TOGETHER (#150, measured 2026-11-16 on a fresh phone load: 41 reads of the same market
// contract, 670 KB — every for-sale plot round the player asked at once, before the first answer was in the cache): the
// read in flight is kept and shared (`p`), a failed one forgotten so the next asks again
function listingsOf(cid) {
  const c = listingCache.get(cid);
  if (c && (c.p || Date.now() - c.at < 60000)) return c.p || Promise.resolve(c.st);
  const p = fetch(base() + "/exec/contract?cid=" + cid, { cache: "no-store" }).then((r) => r.text()).then((txt) => {
    const st = exactSeeds(txt).storage || {};
    listingCache.set(cid, { at: Date.now(), st });
    return st;
  }, (e) => { listingCache.delete(cid); throw e; });
  listingCache.set(cid, { at: Date.now(), p });
  return p;
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
// A PLAYER'S OWN ACTION SENT WHILE THE SOCKET IS DOWN SAYS SO: send() dropped it in silence, so between a lost connection
// and the page's reconnect (up to 30 s apart) a wardrobe Wear, a craft or a quest did nothing and said nothing (playing
// the agent's page, 2026-11-17: "Wear Leather boots" pressed twice, nothing worn, no word). An action is one carrying a
// request number, or chat, a name, a teleport or a shot; positions, poses and traces stay quiet. Once per 3 s.
const NET_ACTS = new Set(["chat", "name", "tp", "bolt"]);
const net = { ws: null, online: false, me: null, req: 0, pending: new Map(), made: new Map(), lastWatch: "", tries: 0, saidOffline: -1e9,
  send(m) {
    try { if (this.ws && this.ws.readyState === 1) { this.ws.send(JSON.stringify(m)); return true; } } catch (e) {}
    if (m && (m.req || NET_ACTS.has(m.t)) && performance.now() - this.saidOffline > 3000) {
      this.saidOffline = performance.now();
      notify(T("offline", "The world server is out of reach — you can explore, but not gather or build."));
    }
    return false;
  } };
const others = new Map();             // player id -> { mesh, p: [face, u, v, h, yaw], who }
const NET_GRACE = 8000;               // ms the world's figures wait through a dropped socket (ws.onclose)
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
      // the server is the record now: drop the plots this browser cached, the server sends each watched one back — on the
      // page's FIRST hello only. A reconnect keeps them, the server's own from a moment ago, and applyPlot puts in what
      // changed meanwhile: dropping them re-meshed the whole town on every reconnect, and one player's trace held 179
      // reconnects in an evening (their network, 2026-11-24)
      if (!net.helloed) {
        net.helloed = true;
        for (const [plot, pe] of plotEdit) { const q = Wd.plotCoords(plot); for (const lk of pe.keys()) { const [x, z, y] = lk.split(":").map(Number); edits.delete(key(q.face, q.u0 + x, q.v0 + z, y)); } }
        plotEdit.clear(); plotList.clear();
      }
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
      { const rec = plotBoxes.get(m.plot); if (rec) rec.gadgets = m.gadgets || {}; }   // the keys its gadgets carry (GADGET KEYS)
    } else if (m.t === "bind_ok") {
      // GADGET KEYS: the world server set (or refused) a gadget's key — the aim line reads it from the plot or the craft
      if (m.error) notify(String(m.error));
      else {
        if (m.plot !== undefined) { const rec = plotBoxes.get(m.plot); if (rec) { rec.gadgets = rec.gadgets || {}; if (m.slot) rec.gadgets[m.box.join(",")] = m.slot; else delete rec.gadgets[m.box.join(",")]; } }
        if (m.craft !== undefined) { const c = crafts.get(m.craft); if (c) { c.slots = c.slots || []; c.slots[m.i] = m.slot; } }
        const g = gadgetAimed(), what = g ? blockLabel(g.b[6]) : T("gadget", "gadget");
        notify(m.slot ? T("bindSet", "{what} fires on key {n}.", { what, n: m.slot }) : T("bindClear", "{what} fires on no key.", { what }));
      }
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
      // a speaker by their chosen name (#179), else by the start of their address as before
      conLine(`<${m.name ? String(m.name).slice(0, 16) : String(m.who || "").slice(0, 10) + "…"}> ${String(m.text || "")}`);
    } else if (m.t === "chat_ok" && m.error) {
      conLine(T("cSignIn", "Sign in to chat."), "err");
    } else if (m.t === "edit") {
      for (const [f, u, v, h, b] of m.cells || []) putCell(f, u, v, h, b);
    } else if (m.t === "revert") {
      for (const [f, u, v, h] of m.cells || []) dropCell(f, u, v, h);
    } else if (m.t === "inv") {
      const lvl0 = invSeen ? inv.level || 1 : null;              // the level before this update (null: the first one)
      if (invSeen) pickup(inv.items, m.items || {}, inv.tools, m.tools || [], inv.stations, m.stations || []);
      invSeen = true;
      // vol: what is left of blocks a piece was cut from (cm³) — sent all along and never kept, so the page counted only
      // whole blocks and refused a piece the leftover would pay for (2026-11-08)
      // a count that rose is a pickup (a gather finished, a quest's reward, a trade): one cue a message
      if (Object.entries(m.items || {}).some(([k, n]) => n > (inv.items[k] || 0))) sound.cue("pickup", 1, 150);
      inv.items = m.items || {}; inv.tools = m.tools || []; inv.stations = m.stations || []; inv.vol = m.vol || {};
      inv.worn = m.worn || {}; inv.look = m.look || { skin: 0, hair: 0 };
      fedUntil = performance.now() + (m.fed || 0) * 1000;                     // a meal's time left (#155)
      inv.quests = m.quests || []; inv.level = m.level || 1; inv.xp = m.xp || 0;   // the quest log and level (#165)
      // A LEVEL GAINED IS SAID (playtest 2026-11-16: the agent's parcel lifted it to level 2 with only "Done: +15
      // experience" — the HUD's number changed and nothing said that the elder now offers hunts and tool jobs). After the
      // hand-in's own notice has been read; level 2 names what it opens (land_server.py _new_quest: from level 2 the
      // whole book), a higher level only itself.
      if (lvl0 && inv.level > lvl0) { const n = inv.level; setTimeout(() => { okBar(n === 2 ? T("levelUp2", "Level 2! The elder now offers all her work — hunts and jobs that need tools.") : T("levelUpN", "Level {n}!", { n })); sound.cue("pickup", 1, 0); }, 2500); }
      showHp(m.hp, m.hp_max);
      fillHot(); hotbar(); if (bagOpen()) renderBag(); if (!$("wardPanel").classList.contains("hidden")) renderWard();
    } else if (m.t === "offers") {
      offers = m.offers || []; if (bagOpen()) renderBag();
    } else if (m.t === "name_ok") {
      if (m.error === "name_taken") conLine(T("nameTaken", "That name is taken — choose another."));
      else if (m.error === "name_bad") conLine(T("nameBad", "A name is 3–16 letters, digits, spaces, - or _, with no space at either end."));
      else if (m.error) conLine(String(m.error));
      else conLine(m.name ? T("nameSet", "Your name is now {n}.", { n: m.name }) : T("nameCleared", "Your name is cleared: you are shown by your address."));
    } else if (m.t === "done") {
      // A MAKE SAYS WHAT IT MADE (playtest 2026-11-16, the agent's phone page): a craft that worked said nothing — the
      // Bag covers the screen, and a hotbar count changing under it was the only sign that a tap did anything
      const made = net.made.get(m.req); net.made.delete(m.req);
      if (m.error) notify(String(m.error));
      else if (made) { const r = RULES.recipes.find((x) => x.id === made); if (r) okBar(T("madeIt", "Made {what}.", { what: r.makes.map(([id, n]) => `${n} × ${nameOf(id)}`).join(", ") })); }
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
        if (!r) {
          r = { mesh: avatar(o.who || o.id, o.look), who: o.who, sig }; scene.add(r.mesh); others.set(o.id, r);
          // THEIR NAME OVER THEM (#179): a plate as the townspeople carry, when they chose a name
          if (o.look && o.look.name) { const plate = label(String(o.look.name).slice(0, 16), null); plate.position.set(0, 2.25, 0); r.mesh.add(plate); }
        }
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
      trace("hurt", { by: m.by, hp: m.hp, at: tracePose([P.face, P.u, P.v, P.h, P.yaw]) });
      // struck (#162): the hearts drop and the screen flashes red
      showHp(m.hp); const f = $("hurtFlash"); f.classList.add("on"); setTimeout(() => f.classList.remove("on"), 120);
      sound.cue("hit");
      hitFrom(m.at, null, false);
    } else if (m.t === "charge") {
      sound.cue("charge", 1, 1500);
      // an animal turned on this player (#176): said in words and shown by side, while it is still metres off
      notify(T("charging", "A {a} is charging you!", { a: animalName(m.by) }), 3000);
      hitFrom(m.at, m.id, true);
    } else if (m.t === "died") {
      trace("died", { by: m.by, at: tracePose([P.face, P.u, P.v, P.h, P.yaw]), bed: m.bed || null });
      died(m.by, m.bed);
    } else if (m.t === "pos_fix") {
      trace("pos_fix", { why: m.why, from: tracePose([P.face, P.u, P.v, P.h, P.yaw]), to: tracePose(m.p) });
      // TRAVEL (#167): the world server puts the player where it says — after /tp (the landing, or their bed), or back
      // where it last saw them when the page moved faster than anyone can go
      if (m.why === "nobed") { conLine(T("tpNoBed", "You have no bed yet — Use on a bed you built, and /tp bed takes you there."), "err"); return; }
      if (!Array.isArray(m.p) || flying) return;
      // A SERVER'S MOVE ENDS A PENDING PLACE (#180 item 3, playtest: "/tp spawn" seconds after the page loaded said "At the
      // landing." and then the player was back where they had been): a saved place on a built floor or underground waits
      // for its plot's edits (pendingPlace) and was taken back when they arrived — after the teleport. Every move the
      // player did not walk (this, waking, boarding, leaving a craft, the offline /tp) drops it.
      pendingPlace = null;
      P.face = m.p[0]; P.u = m.p[1]; P.v = m.p[2];
      P.h = Number.isFinite(m.p[3]) ? m.p[3] : groundAt(P.face, P.u, P.v); P.vu = P.vv = P.vh = 0;
      save(); updateChunks();
      if (m.why === "tp") conLine(m.to === "bed" ? T("tpBed", "At your bed.") : T("tpSpawn", "At the landing."));
      else notify(T("tpPace", "Faster than anyone can go — back where the world last saw you."), 4000);
    } else if (m.t === "bolt_seen") {
      const [f, a, b] = m.line || [];
      if (f === P.face && Array.isArray(a) && Array.isArray(b)) {
        drawBolt(f, a, b, performance.now());
        sound.cue("bolt", 0.8 * Math.max(0.15, 1 - Math.hypot(a[0] - P.u, a[1] - P.v, a[2] - P.h) / 192), 80);   // fainter farther off
      }
    } else if (m.t === "bolt_ok") {
      if (!m.error && (m.hit || m.killed)) huntSaid(m);              // a bolt that struck an animal says so as an arrow does
    } else if (m.t === "shoot" || m.t === "throw" || m.t === "pickup") {
      if (m.t === "throw" && !m.error && !m.hit && !m.killed && m.end) {   // a thrown spear that missed lies where it fell (#157)
        const a = arrowsInFlight[arrowsInFlight.length - 1];
        if (a && m.flight) a.until = Math.min(a.until, m.flight);
        notify(T("spearMiss", "A miss — the spear fell short or wide. It lies where it fell: walk over it to take it back."));
      } else if (m.t === "throw" && m.error && m.error !== "too fast") notify(m.error === "throwing needs a spear" ? T("huntNeeds", "Hunting needs a spear or a bow.") : String(m.error));
      else if (m.t === "throw") { const a = arrowsInFlight[arrowsInFlight.length - 1]; if (a && m.flight) a.until = Math.min(a.until, m.flight); huntSaid(m); }
      if (m.t === "shoot" && m.flight) {
        // the server's arrow ended after `flight` seconds (in a body, or on the ground): the page's own arrow stops there
        const a = arrowsInFlight[arrowsInFlight.length - 1];
        if (a) a.until = Math.min(a.until, m.flight);
      }
      // (a throw's error is said above; "you carry one already" stays quiet: standing on a spear asks again every second)
      if (m.t !== "throw" && m.error && m.error !== "it is gone" && m.error !== "too far away" && m.error !== "too fast" && m.error !== "you carry one already") notify(m.error === "no arrows" ? T("huntArrows", "No arrows — make some from sticks, stone and fiber.") : String(m.error));
      else if (m.t === "shoot" && !m.error) huntSaid(m);   // (a throw is answered above)
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
    } else if (m.t === "pad") {
      if (pad && m.plot === pad.plot) renderPad(m);
    } else if (m.t === "launched") {
      if (m.error) { notify(padWhy(m.error), 6000); if (pad) net.send({ t: "pad", plot: pad.plot, box: pad.box, req: ++net.req }); return; }
      notify(m.num && m.num.ok ? T("padOrbit", "In orbit! Satellites in the constellation: {n}.", { n: m.num.in_orbit }) : T("padSpent", "It did not reach orbit — the rocket is spent."), 8000);
      hidePanel("padPanel");
    } else if (m.t === "survey") {
      drawMap(m);
    } else if (m.t === "mycrafts") {
      if (m.error) return conLine(String(m.error), "err");
      if (!(m.list || []).length) return conLine(T("fCraftsNone", "You own no craft."));
      for (const c of craftsBearing(m.list)) {
        const id = c.id.slice(0, 6);
        if (flying && flying.id === c.id) conLine(T("fCraftMine", "Your craft {id}: you are flying it.", { id }));
        else if (c.d === null) conLine(T("fCraftOther", "Your craft {id}: on another face of the planet.", { id }));
        else conLine(T("fCraftAt", "Your craft {id}: {d} m away, bearing {b}° (north 0°, east 90°), {h} m up.", { id, d: c.d, b: c.b, h: c.h }));
      }
    } else if (m.t === "given") {
      // a craft handed to me (#171): mine now, and I am at its controls — wherever it is
      const w = String(m.by || "");
      notify(T("fGiven", "{w} gave you a craft — you are at its controls.", { w: w.slice(0, 6) + "…" + w.slice(-5) }), 6000);
      if (!flying) board({ craft: m.craft });
    } else if (m.t === "craft_fix") {
      trace("craft_fix", { craft: m.craft, error: m.error, from: tracePose(flying && flying.pose), to: tracePose(m.pose) });
      // the server held the craft somewhere else (a claim faster than it flies): back to where it holds it — KEEPING its
      // speed (operator 2026-11-14: "at speed the craft gets stopped in place": every refusal zeroed the velocity, and a
      // fighter refused at its ceiling or on a bunched network stopped dead in the air, again and again). And when the
      // server says this page is not its pilot (a leave it took), the page steps out instead of flying on: his trace
      // held 92 refusals in 20 s of a page that kept sending a craft it no longer flew.
      if (flying && flying.id === m.craft) {
        if (m.error === "you are not flying that") { flying = null; craftUp = null; P.pitch = 0; hotbar(); notify(T("fNotPilot", "You are no longer at the controls.")); }
        else flying.pose = m.pose.slice();
      }
    }
  };
  const wsIn = ws.onmessage; ws.onmessage = (ev) => pt("ws", () => wsIn(ev));   // (timed: a long frame's trace names it, PERF)
  ws.onclose = () => {
    trace("net_close", { at: tracePose([P.face, P.u, P.v, P.h, P.yaw]) });
    const was = net.online;
    net.online = false; net.ws = null;
    // THROUGH A RECONNECT THE WORLD STAYS (2026-11-24): the people, the animals and the townsfolk wait NET_GRACE ms for
    // the socket to come back — the first "players" after it drops whoever left meanwhile — instead of every figure
    // vanishing for the second a reconnect takes (one player's evening: 179 of them). Still away by then, they go.
    clearTimeout(net.graceT);
    net.graceT = setTimeout(() => {
      if (net.online) return;
      for (const r of others.values()) scene.remove(r.mesh);
      others.clear();
      for (const r of animals.values()) scene.remove(r.mesh);
      animals.clear();
      for (const r of npcs.values()) scene.remove(r.mesh);
      npcs.clear();
    }, NET_GRACE);
    if (was) hud();
    setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(5, net.tries++)));   // back off; a page without a server stays local
  };
}
/** Replace a plot's cells with the server's list (a pushed "plot", or a resync after a refused change). */
const plotsApplied = new Set();          // plots whose edits this page holds (the nearest-source hint asks before it names one)
function applyPlot(plot, list) {
  plotsApplied.add(plot);
  // ONLY WHAT CHANGED (2026-11-24): a plot's list is put in as a difference — a cell gone is dropped, a new or changed
  // one put, each re-meshing only around itself — not every cell dropped and put back, which re-meshed every chunk of
  // the plot for a list identical to the one held (each reconnect, each resync, the whole town at once)
  const q = Wd.plotCoords(plot), old = plotEdit.get(plot) || new Map(), now = new Map();
  for (const [x, z, y, b] of list) now.set(x + ":" + z + ":" + y, b);
  for (const lk of old.keys()) if (!now.has(lk)) { const [x, z, y] = lk.split(":").map(Number); dropCell(q.face, q.u0 + x, q.v0 + z, y); }
  for (const [lk, b] of now) if (old.get(lk) !== b) { const [x, z, y] = lk.split(":").map(Number); putCell(q.face, q.u0 + x, q.v0 + z, y, b); }
  if (!now.size) { plotEdit.delete(plot); plotList.delete(plot); }
  if (pendingPlace && Wd.plotOf(pendingPlace[0], Math.floor(pendingPlace[1]), Math.floor(pendingPlace[2])) === plot) {
    const [f, u, v, h, yaw, pitch] = pendingPlace, pf = P.face;
    pendingPlace = null;
    P.face = f;
    if (!collides(u, v, h)) { [P.u, P.v, P.h, P.yaw, P.pitch] = [u, v, h, yaw, Number.isFinite(pitch) ? pitch : P.pitch]; P.vh = 0; }
    else P.face = pf;
  }
}
/** The town's plots — the hall's and the ring around it — asked for at once, each on its own (one slow answer holds
 *  no other back); the first frame is not waited on them, they just usually win the race. */
function prefetchTown() {
  const q = Wd.plotCoords(TOWN_HALL_PLOT);
  for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) resync(Wd.plotId(q.face, q.prow + dr, q.pcol + dc));
}
async function resync(plot) {
  try { const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin", priority: "high" })).json(); applyPlot(plot, r.edits || []); setPlotBoxes(plot, r.boxes || []); } catch (e) {}
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
const WEAR = { linen_shirt: 0xe6dcc3, linen_trousers: 0xcabd98, linen_cap: 0xeee5cf, linen_cloak: 0xb9a57c,
  leather_boots: 0x5b3a24, leather_gloves: 0x7a5232,                             // leather: the hunt's hide, tanned (#128)
  woollen_cloak: 0x6e5a44, woollen_cap: 0x8a7458,                                // wool: the sheep's own brown, undyed (#128)
  // DYED WOOL (#128, land-recipes.json "dyes"): weld's clear yellow, woad's indigo blue, madder's red, woad then weld's
  // green — the shades a design choice after the dyes' usual results (CAMEO Weld dye: "golden yellow" with alum); the
  // cap a little lighter than the cloak, as the undyed pair is
  woollen_cloak_yellow: 0xc9a227, woollen_cap_yellow: 0xd8b43c, woollen_cloak_blue: 0x2f4f86, woollen_cap_blue: 0x3d609a,
  woollen_cloak_red: 0x9c2f2a, woollen_cap_red: 0xb03c33, woollen_cloak_green: 0x3f6b35, woollen_cap_green: 0x4d7d42 };
const WEAR_SLOTS = ["head", "body", "legs", "back", "feet", "hands"];          // land_server.py WEAR_SLOTS
function lookColours(seed, look) {
  let h = 0; for (const ch of String(seed)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  look = look || {}; const worn = look.worn || {};
  const under = new THREE.Color().setHSL((h % 360) / 360, 0.35, 0.42).getHex();
  return { skin: SKIN[look.skin] ?? SKIN[0], hair: HAIR[look.hair] ?? HAIR[0], top: WEAR[worn.body] ?? under,
           legs: WEAR[worn.legs] ?? 0x3b3f46, cap: WEAR[worn.head] ?? null, cloak: WEAR[worn.back] ?? null,
           boots: WEAR[worn.feet] ?? null, gloves: WEAR[worn.hands] ?? null };
}
// BACK TO THE KAWAII FIGURES (operator 2026-11-13: "can we replace the human make models in the game? swap them for
// those blocky characters with kawaii faces that were there at the beginning and clean up after ourselves"), and then
// (2026-11-14) "kawaii people yes but the blocky ones were better": the MakeHuman bodies of #172 are gone, and a person
// is the BLOCKY figure of the first days (boxes: legs, torso, arms, a cube head, hair, a cap, a cloak — as on
// 2026-11-07) with the kawaii FACE of #145 drawn flat on the front of the cube head (faceFlat: the face canvas unmirrored,
// for a plane facing +Z, the figure's front). Body type 1 keeps what #145 gave it, in blocks: hair down the back, two
// pigtails, a skirt. One group per person, for players and townspeople alike. Nothing rounded: no capsule, no sphere.
const faceFlatTex = new Map();
function faceFlat(face) {
  if (!faceFlatTex.has(face)) { const t = new THREE.CanvasTexture(faceCanvas(face, null)); t.colorSpace = THREE.SRGBColorSpace; faceFlatTex.set(face, t); }
  return faceFlatTex.get(face);
}
let figureMaterial = null;                         // the one material every figure's body is drawn in (avatar)
function avatar(seed, look) {
  const c = lookColours(seed, look), g = new THREE.Group(), girl = (look && look.body) === 1;
  // ONE DRAW A FIGURE (#139: four people at the landing were 48 draws, a box each in its own material): every box is
  // laid into one geometry in its own place with its colour on its vertices, drawn in one material all figures share;
  // the face stays its own plane (its own texture). Nothing moves a box on its own: a figure moves whole.
  const boxes = [], box = (w, h, d, x, y, z, col) => { const q = new THREE.BoxGeometry(w, h, d).toNonIndexed(); q.translate(x, y, z); boxes.push([q, new THREE.Color(col)]); };
  box(0.22, 0.8, 0.24, -0.13, 0.4, 0, c.legs); box(0.22, 0.8, 0.24, 0.13, 0.4, 0, c.legs);          // legs
  if (girl) box(0.6, 0.32, 0.34, 0, 0.72, 0, c.top);                                               // a skirt
  box(girl ? 0.5 : 0.56, 0.7, 0.3, 0, 1.15, 0, c.top);                                              // torso
  box(0.16, 0.66, 0.2, -0.37, 1.13, 0, c.top); box(0.16, 0.66, 0.2, 0.37, 1.13, 0, c.top);          // arms
  box(0.38, 0.38, 0.38, 0, 1.69, 0, c.skin);                                                        // head
  // the face: the kawaii canvas on a plane just in front of the head's front face (+Z)
  const f = new THREE.Mesh(new THREE.PlaneGeometry(0.38, 0.38), new THREE.MeshLambertMaterial({ map: faceFlat((look && look.face) || 0), transparent: true, depthWrite: false }));
  f.position.set(0, 1.69, 0.192); g.add(f);
  box(0.4, girl ? 0.5 : 0.24, 0.07, 0, girl ? 1.62 : 1.75, -0.19, c.hair);                         // hair, behind (down the back for body type 1)
  if (girl) for (const x of [-0.24, 0.24]) box(0.09, 0.3, 0.09, x, 1.6, -0.05, c.hair);             // two pigtails
  if (c.cap != null) box(0.42, 0.14, 0.42, 0, 1.92, 0, c.cap); else box(0.4, 0.1, 0.4, 0, 1.92, 0, c.hair);
  if (c.cloak != null) box(0.62, 1.15, 0.05, 0, 1.0, -0.19, c.cloak);                              // a cloak hangs behind
  // boots over the foot of each leg and gloves over the end of each arm, a little wider than the limb so they show (#128)
  if (c.boots != null) for (const x of [-0.13, 0.13]) box(0.25, 0.24, 0.29, x, 0.12, 0.01, c.boots);
  if (c.gloves != null) for (const x of [-0.37, 0.37]) box(0.19, 0.18, 0.23, x, 0.86, 0, c.gloves);
  const n = boxes.reduce((t, [q]) => t + q.attributes.position.count, 0), pos = new Float32Array(n * 3), nor = new Float32Array(n * 3), col = new Float32Array(n * 3);
  let at = 0;
  for (const [q, cl] of boxes) {
    pos.set(q.attributes.position.array, at * 3); nor.set(q.attributes.normal.array, at * 3);
    for (let i = 0; i < q.attributes.position.count; i++) { col[(at + i) * 3] = cl.r; col[(at + i) * 3 + 1] = cl.g; col[(at + i) * 3 + 2] = cl.b; }
    at += q.attributes.position.count; q.dispose();
  }
  const body = new THREE.BufferGeometry();
  body.setAttribute("position", new THREE.BufferAttribute(pos, 3)); body.setAttribute("normal", new THREE.BufferAttribute(nor, 3)); body.setAttribute("color", new THREE.BufferAttribute(col, 3));
  body.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(n * 2), 2));   // (unread, but three's material asks for one: a "uv not found" warning a figure, every frame)
  g.add(new THREE.Mesh(body, figureMaterial ||= new THREE.MeshLambertMaterial({ vertexColors: true })));
  g.userData.person = true;                       // /tris and /draws count a figure's meshes as "people" by this mark
  return g;
}
// ---- ANIMALS (#156, "hunting", operator 2026-11-09): the world server keeps them near players (land_server.py herd) and
// sends where each is with the players near; the page draws each kind — a deer, a boar, a rabbit, a sheep — glides it to where
// the server says, stands it on the drawn ground, and swings its legs while it moves. Break on one under the crosshair
// strikes it with a spear (close) or a bow (far, an arrow each). A STAG (antlers) charges a player who comes near, and
// any deer or boar struck fights back (#162: "add aggressive deer and death/respawn mechanism", operator 2026-11-09).
const animals = new Map();                        // id -> { kind, mesh, legs, u, v, h, yaw, cu, cv, cyaw, gh, moving }
const ANIMAL_LOOK = {
  deer: { body: 0x8a5a33, belly: 0xd9c3a0, len: 1.15, high: 0.85, girth: 0.32, head: 0.18, neck: 0.45 },
  boar: { body: 0x4b3b31, belly: 0x5e4c40, len: 0.95, high: 0.5, girth: 0.34, head: 0.22, neck: 0.12 },
  rabbit: { body: 0x9a8a78, belly: 0xe8e0d4, len: 0.3, high: 0.16, girth: 0.13, head: 0.1, neck: 0.06 },
  // a wild sheep (#128): the Soay's colouring — a dark brown fleece, a pale belly — stocky in its wool, on short legs
  sheep: { body: 0x5e4630, belly: 0xd9c9ad, len: 0.85, high: 0.42, girth: 0.36, head: 0.15, neck: 0.16 },
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
  if (kind === "sheep") for (const s of [-1, 1]) {                                                                         // curled horns
    const h = put(new THREE.TorusGeometry(0.07, 0.022, 6, 12, Math.PI * 1.5), 0xb8a888, s * L.head * 0.62, hy + L.head * 0.3, hz - L.head * 0.25);
    h.rotation.y = Math.PI / 2;
  }
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
  bakeColoured(g);
  return { g, legs };
}
/** ONE DRAW FOR WHAT DOES NOT MOVE (#139, /draws on a desktop at the landing: 164 draws of animals, a dozen and more
 *  meshes each): the meshes hung straight on `g` — an animal's body, belly, head, neck, eyes, ears, tusks, tail — are
 *  baked, each with its own place, turn and scale, into one geometry with each one's colour on its vertices, in one
 *  material every animal shares. What moves on its own (a leg on its hip) is not a child of `g` and stays as it is. */
let colouredMaterial = null;
function bakeColoured(g) {
  const list = g.children.filter((m) => m.isMesh && m.material && m.material.color && !m.material.map);
  if (list.length < 2) return;
  const parts = list.map((m) => { m.updateMatrix(); const q = m.geometry.index ? m.geometry.toNonIndexed() : m.geometry.clone(); q.applyMatrix4(m.matrix); return [q, m.material.color]; });
  const n = parts.reduce((t, [q]) => t + q.attributes.position.count, 0), pos = new Float32Array(n * 3), nor = new Float32Array(n * 3), col = new Float32Array(n * 3);
  let at = 0;
  for (const [q, c] of parts) {
    pos.set(q.attributes.position.array, at * 3); nor.set(q.attributes.normal.array, at * 3);
    for (let i = 0; i < q.attributes.position.count; i++) { col[(at + i) * 3] = c.r; col[(at + i) * 3 + 1] = c.g; col[(at + i) * 3 + 2] = c.b; }
    at += q.attributes.position.count; q.dispose();
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3)); geo.setAttribute("normal", new THREE.BufferAttribute(nor, 3)); geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(n * 2), 2));    // (unread, but three's material asks for one: a "uv not found" warning an animal, every frame)
  for (const m of list) { g.remove(m); m.geometry.dispose(); m.material.dispose(); }
  g.add(new THREE.Mesh(geo, colouredMaterial ||= new THREE.MeshLambertMaterial({ vertexColors: true })));
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
let hpMax = 20, lastHp = null;
// A LANGUAGE CHANGE re-renders what T() wrote into the HUD by hand (#179: the hotbar label stayed "Earth" after a switch
// to Čeština, the health line's "Level"): i18n.js announces it on window
window.addEventListener("nado-lang", () => { hotbar(); pieceInfo(); if (lastHp != null) showHp(lastHp); const st = $("hudPlot"); if (st) st.dataset.html = ""; relabelNpcs(); if (touch) fitTouchLabels(); });
/** A phone button's label fits its 58 px circle in every language: the longest word of each is measured, and a label
 *  wider than the button is set smaller (never under TOUCH_MIN_PX) — in Russian "Использовать" ran across into "Сломать"
 *  beside it, read as one word, and "Поставить" into "Полёт" (playtest 2026-11-16). A label that fits keeps its size. */
const TOUCH_MIN_PX = 7, TOUCH_PAD_PX = 2, TOUCH_SQUEEZE_PX = 0.5;
let fitCtx = null;
function fitTouchLabels() {
  fitCtx ||= document.createElement("canvas").getContext("2d");
  for (const b of document.querySelectorAll("#touchUi button")) {
    b.style.fontSize = ""; b.style.paddingLeft = b.style.paddingRight = ""; b.style.letterSpacing = "";
    const cs = getComputedStyle(b), px = parseFloat(cs.fontSize);
    // the room is inside the button's REAL side padding (6 px each: a fixed 8 px allowance let Russian "Использовать"
    // run 6 px past its button at the smallest size, measured live 2026-11-16); a label that must shrink takes the
    // narrow TOUCH_PAD_PX instead, so the longest word fits whole
    const roomPlain = b.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight), roomTight = b.clientWidth - 2 * TOUCH_PAD_PX;
    fitCtx.font = `${cs.fontWeight} ${px}px ${cs.fontFamily}`;
    const w = Math.max(0, ...b.textContent.trim().split(/\s+/).map((x) => fitCtx.measureText(x).width));
    if (roomPlain > 0 && w > roomPlain) {
      b.style.paddingLeft = b.style.paddingRight = TOUCH_PAD_PX + "px";
      const size = Math.max(TOUCH_MIN_PX, Math.floor(Math.min(px, (px * roomTight) / w) * 10) / 10);
      b.style.fontSize = size + "px";
      // still too wide at the smallest size (Russian "Использовать": 2 px over with the narrow padding): the letters close
      // up the rest, at most TOUCH_SQUEEZE_PX each — smaller type would not read on a phone
      const word = b.textContent.trim().split(/\s+/).reduce((x, y) => (y.length > x.length ? y : x), ""), over = (w * size) / px - roomTight;
      if (over > 0 && word.length > 1) b.style.letterSpacing = -Math.min(TOUCH_SQUEEZE_PX, Math.ceil((over / (word.length - 1)) * 100) / 100) + "px";
    }
  }
}
function showHp(hp, max) {
  if (max) hpMax = max;
  const el = $("hudHp");
  if (!el || hp == null) return;
  lastHp = hp;
  el.classList.toggle("hidden", !net.me);
  const full = Math.max(0, Math.ceil(hp / 2)), all = Math.ceil(hpMax / 2);
  el.textContent = "♥".repeat(full) + "♡".repeat(Math.max(0, all - full)) + ` ${hp}/${hpMax}` + (inv.level ? " · " + T("level", "Level {n}", { n: inv.level }) : "");
}
// WHERE IT CAME FROM (#176): an arc on the side of the view the animal is on — ahead at the top, behind at the bottom —
// red for a strike (0.9 s), amber for the charge that precedes it (2.5 s, following the animal). A strike used to be a
// 120 ms flash with no side to it: with a panel open the first a player knew of a stag was the death card.
let hitDir = null;                                 // { at: [u, v], id, until }
function hitFrom(at, id, warn) {
  const el = $("hitDir");
  if (!el || !Array.isArray(at)) return;
  hitDir = { at, id, until: performance.now() + (warn ? 2500 : 900) };
  el.classList.toggle("warn", !!warn); el.classList.add("on");
  hitDirFrame(performance.now());
}
/** Each frame while the arc shows: it turns with the player's view and with the animal. */
function hitDirFrame(now) {
  if (!hitDir) return;
  const el = $("hitDir");
  if (now > hitDir.until) { hitDir = null; el.classList.remove("on"); return; }
  const a = hitDir.id != null && animals.get(hitDir.id), at = a ? [a.u, a.v] : hitDir.at;
  el.style.transform = `rotate(${(Math.atan2(at[0] - P.u, at[1] - P.v) - P.yaw).toFixed(3)}rad)`;   // yaw 0 faces +v, +u to the right
}
/** Every panel shut and what it showed let go (death; nothing may stay open under the card, #176). */
// ONE PANEL AT A TIME (#179, playtest 2026-11-11): opening a panel closes the others and frees the mouse (the Map opened
// with the mouse still captured — nothing on it could be clicked until Escape; E opened the Bag under an open
// townsperson); closing the last one gives the mouse back to the game (a close used to need one more click on the
// world); the death card closes them all (died → closePanels, which never recaptures: the card is about to show).
const PANELS = ["palette", "setPanel", "mapPanel", "wardPanel", "planetPanel", "chestPanel", "machPanel", "npcPanel", "padPanel"];
const anyPanelOpen = () => PANELS.some((id) => { const el = $(id); return el && !el.classList.contains("hidden"); });
function hidePanel(id) {
  const el = $(id);
  if (!el || el.classList.contains("hidden")) return;
  el.classList.add("hidden");
  if (id === "chestPanel") chest = null; else if (id === "machPanel") machine = null; else if (id === "npcPanel") talkingTo = null; else if (id === "padPanel") pad = null;
}
function showPanel(id, open) {
  if (open) {
    for (const o of PANELS) if (o !== id) hidePanel(o);
    const el = $(id); if (el) el.classList.remove("hidden");
    if (document.pointerLockElement) document.exitPointerLock();
  } else {
    hidePanel(id);
    if (!anyPanelOpen() && !conOpen && !touch && $("deathCard").classList.contains("hidden")) lockPointer();
  }
}
function closePanels() {
  for (const id of PANELS) hidePanel(id);
  conShow(false);
}
let wakeAt = null;
/** The body at the place it wakes: the bed, else the landing. */
function toWake() {
  pendingPlace = null;   // (a place set here wins over a saved place still waiting for its plot's edits — pendingPlace — #180 item 3)
  if (wakeAt) { [P.face, P.u, P.v] = [wakeAt[0], wakeAt[1] + 1.2, wakeAt[2]]; }
  else { [P.face, P.u, P.v, P.yaw] = townSpawn(); }
  P.h = groundAt(P.face, P.u, P.v); P.vu = P.vv = P.vh = 0; P.eyeH = P.h;
  save();
}
function died(by, bed) {
  wakeAt = bed || null;
  // THE BODY IS AT THE WAKE PLACE AT ONCE, not when "Wake up" is pressed (#176): left at the death spot behind the card
  // it was struck again every few seconds — nine deaths in a row on the playtest of 2026-11-11. The world server keeps
  // the dead at the wake place too and drops what this page reports until it is there (land_server.py, the "pos" handler).
  closePanels();
  toWake(); updateChunks();
  $("deathBy").textContent = T("diedBy", "You were killed by a {a}.", { a: animalName(by) });
  $("deathWhere").textContent = bed ? T("wakeBed", "You wake at your bed.") : T("wakeLanding", "You wake at the landing — use a bed to wake there instead.");
  if (document.pointerLockElement) document.exitPointerLock();
  $("deathCard").classList.remove("hidden");
}
function wakeUp() {
  $("deathCard").classList.add("hidden");
  toWake();                                                 // again: the ground here is loaded by now (its height is the built one)
  if (!touch) lockPointer();                                // the button's own click: back to play at once
}
// ---- NPCS AND QUESTS (#165, "we may need npcs and quests and move this a little towards world of warcraft as well",
// operator 2026-11-09): the people of the town, kept by the world server, drawn as people with their name over them and
// a mark when they have something for this player — "!" work, "?" a quest to hand in. Use on one talks to them: what
// they offer (Accept), the player's quests that end with them (Hand in). The quest log is in the bag.
const npcs = new Map();                            // id -> { mesh, plate, mark, sig, at }
const PLATE_H = 0.2;                               // a name tag's height in unattenuated sprite units: ~5 % of the view (measured: 0.07 drew 1.7 %, unreadable)
/** The tags a figure carries, sized for its distance (the mesh's camera-relative position): full size within PLATE_NEAR,
 *  then shrinking as PLATE_NEAR / distance, never under a third — a constant size made the tags of people standing
 *  together overlap from across the square ("IdaMa…", playtest 2026-11-15). */
const PLATE_NEAR = 8;
function sizePlates(mesh) {
  const d = mesh.position.length(), f = Math.max(1 / 3, Math.min(1, PLATE_NEAR / Math.max(d, 1e-3)));
  for (const c of mesh.children) if (c.isSprite && c.userData.base) c.scale.set(c.userData.base[0] * f, c.userData.base[1] * f, 1);
}
function label(text, sub, col) {
  const cv = document.createElement("canvas"); cv.width = 256; cv.height = 64;
  const g = cv.getContext("2d");
  g.textAlign = "center"; g.font = "bold 26px sans-serif"; g.lineWidth = 5; g.strokeStyle = "rgba(0,0,0,.75)";
  g.fillStyle = col || "#ffe9a8"; g.strokeText(text, 128, 28); g.fillText(text, 128, 28);
  if (sub) { g.font = "18px sans-serif"; g.fillStyle = "#e8eef4"; g.strokeText(sub, 128, 54); g.fillText(sub, 128, 54); }
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace;
  // A CONSTANT SIZE ON SCREEN (playtest 2026-11-15: a 1.6 m tag beside Maren filled the top of a phone's screen and was
  // cut off behind the HUD): not shrunk with distance, ~5 % of the view's height (PLATE_H, in three's unattenuated
  // sprite units), anchored by its bottom edge (center y 0) at the point it is hung from
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthWrite: false, transparent: true, sizeAttenuation: false }));
  sp.scale.set(PLATE_H * 4, PLATE_H, 1); sp.center.set(0.5, 0); sp.userData.base = [PLATE_H * 4, PLATE_H];
  g.font = "bold 26px sans-serif"; let tw = g.measureText(text).width;
  if (sub) { g.font = "18px sans-serif"; tw = Math.max(tw, g.measureText(sub).width); }
  sp.userData.textW = Math.min(1, (tw + 10) / 256);       // how much of the tag's width its words take (declutterPlates)
  return sp;
}
/** NAME TAGS DO NOT SIT ON ONE ANOTHER (playtest 2026-11-15: Maren's and Ida's tags, two people side by side by the
 *  town hall, were drawn over each other into one unreadable word). `items`: each tag's screen box at its own place —
 *  { d (distance), x0, x1, y0, y1, step (its own height) } in the same units — and how many of its own heights each is
 *  lifted: nearest first, never moved; a farther one rises until it is clear of every tag already placed, at most
 *  PLATE_LIFT steps (a crowd keeps its tags near their people rather than stacking them into the sky). */
const PLATE_LIFT = 3;
function declutterPlates(items) {
  const order = items.map((_, i) => i).sort((a, b) => items[a].d - items[b].d), placed = [], lift = new Array(items.length).fill(0);
  const hit = (r, L) => placed.find((o) => r.x0 < o.x1 && o.x0 < r.x1 && r.y0 + L * r.step < o.y1 && o.y0 < r.y1 + L * r.step);
  for (const i of order) {
    const r = items[i];
    // just clear of what is in the way, not whole heights at a time: a tag behind someone with a quest mark rose three
    // heights to the top of the screen, far from its person (playtest 2026-11-15)
    let L = 0, o;
    while (L < PLATE_LIFT && (o = hit(r, L))) L = Math.min(PLATE_LIFT, (o.y1 - r.y0) / r.step + 0.02);
    lift[i] = L;
    placed.push({ x0: r.x0, x1: r.x1, y0: r.y0 + L * r.step, y1: r.y1 + L * r.step });
  }
  return lift;
}
const _pv = new THREE.Vector3();
/** Each frame, after the tags are sized: measure every shown tag's box on screen (a tag that ignores distance is
 *  scale × the projection's own factor — three's sizeAttenuation false) and lift the crowded ones (declutterPlates). */
function platesFrame() {
  const P0 = camera.projectionMatrix.elements[0], P5 = camera.projectionMatrix.elements[5], items = [], tags = [];
  const add = (mesh) => {
    const name = mesh.children.find((c) => c.isSprite && c.userData.textW), mark = mesh.children.find((c) => c.isSprite && c.userData.mark);
    if (!name || !mesh.visible) return;
    name.getWorldPosition(_pv); const d = _pv.length(); _pv.project(camera);
    if (_pv.z > 1 || Math.abs(_pv.x) > 1.2 || Math.abs(_pv.y) > 1.2) { name.center.y = 0; if (mark) mark.center.y = -1.15; return; }
    const hw = name.scale.x * P0 * name.userData.textW / 2, h = name.scale.y * P5, top = mark ? Math.max(h, 2.15 * mark.scale.y * P5) : h;
    items.push({ d, x0: _pv.x - hw, x1: _pv.x + hw, y0: _pv.y, y1: _pv.y + top, step: h }); tags.push([name, mark]);
  };
  for (const r of npcs.values()) add(r.mesh);
  for (const r of others.values()) if (r.p && r.mesh) add(r.mesh);
  declutterPlates(items).forEach((L, i) => {
    const [name, mark] = tags[i];
    name.center.y = -L;                                                      // its own heights up from where it hangs
    if (mark) mark.center.y = -1.15 - L * name.scale.y / mark.scale.y;      // its "!" or "?" goes up with it
  });
}
const roleName = (r) => T("npc." + r, { elder: "Elder", trader: "Trader", smith: "Smith" }[r] || r);
/** The townspeople's name tags in the language now chosen: a tag is drawn into its own picture once (label), so after a
 *  language change while playing they kept the old role — "Elder", "Smith" over a page in Arabic (playtest 2026-11-16)
 *  until a reload. Each is drawn again in place, its old picture freed. */
function relabelNpcs() {
  for (const r of npcs.values()) {
    const old = r.mesh.children.find((c) => c.isSprite && c.userData.textW && !c.userData.mark);
    if (!old) continue;
    const plate = label(r.name, roleName(r.role));
    plate.position.copy(old.position); r.mesh.remove(old); r.mesh.add(plate);
    old.material.map.dispose(); old.material.dispose();
  }
}
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
      // (the mark rides one tag-height above the name tag, from the same point, so the two never overlap at any distance)
      if (r.mark) { r.mark.userData.mark = true; r.mark.userData.textW = 0; r.mark.scale.set(PLATE_H * 3.5, PLATE_H * 0.875, 1); r.mark.userData.base = [PLATE_H * 3.5, PLATE_H * 0.875]; r.mark.center.set(0.5, -1.15); r.mark.position.set(0, 2.05, 0); r.mesh.add(r.mark); }
      r.markSig = n.mark;
    }
  }
  for (const [id, r] of npcs) if (!seen.has(id)) { scene.remove(r.mesh); npcs.delete(id); }
}
function npcsFrame(cam, dt, now) {
  for (const r of npcs.values()) {
    if (r.gh === undefined) r.gh = groundAt(r.at[0], r.at[1], r.at[2]);
    const q = Wd.posOf(r.at[0], r.at[1], r.at[2], r.gh), ofr = Wd.frameOf(r.at[0], r.at[1], r.at[2]);
    r.mesh.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    r.mesh.up.set(ofr.up[0], ofr.up[1], ofr.up[2]);
    // they face the player when the player is near, the street otherwise
    const du = P.u - r.at[1], dv = P.v - r.at[2], near = Math.hypot(du, dv) < 8, yaw = near ? Math.atan2(du, dv) : 0;
    const sy = Math.sin(yaw), cy = Math.cos(yaw);
    r.mesh.lookAt(r.mesh.position.x + sy * ofr.east[0] + cy * ofr.north[0], r.mesh.position.y + sy * ofr.east[1] + cy * ofr.north[1], r.mesh.position.z + sy * ofr.east[2] + cy * ofr.north[2]);
    sizePlates(r.mesh);
  }
}
/** A block or a piece kind by the item that places it, or the item of its own name (ores, clay, flax), or its own name
 *  (land.b.*) — the /aim command's and the aim line's one naming. */
function blockLabel(b) {
  if (b === B.wheatyoung) return T("b.wheatyoung", "Young wheat");     // a growing crop, not the seed it was sown as
  const k = BLOCKS[b].key, id = RULES && Object.keys(RULES.items).find((i) => RULES.items[i].places === b);
  return id ? nameOf(id) : RULES && RULES.items[k] ? nameOf(k) : T("b." + k, k);
}
// THE AIM LINE (#177, playtest 2026-11-11: "nothing says what you are aiming at or which key acts on it" — talking was
// on Q with no prompt, a pebble and a boulder looked alike, a refused plot said so only after the whole hold): one line
// under the crosshair naming the thing aimed at and what acts on it — "Maren — Q talk", "Door — Q open", "Pebble — hold
// left click to gather", "Timber beam · Owned by … — not yours to gather here". On a phone the key is the button's name.
let aimLineAt = 0, dayNow = 1;
function aimText(a) {
  if (!RULES) return "";
  const k = touch ? T("tUse", "Use") : "Q", b = touch ? T("tBreak", "Break") : T("kLeft", "left click");
  const n = npcAimed();
  if (n) { const r = npcs.get(n); return T("aimFmt", "{what} — {k} {v}", { what: r ? r.name : n, k, v: T("v.talk", "talk") }); }
  const an = animalAimed(8);
  // animalAimed gives { id, kind, d } — its kind names it (looked up as a map key, the object found nothing and every
  // animal was named "deer": a boar, a rabbit, a sheep alike — the sheep's hunt walk, 2026-11-18)
  if (an) return T("aimFmt2", "{what} — {v}", { what: animalName(an.kind), v: T("v.hunt", "a weapon hunts it") });
  { // GADGET KEYS: a thruster or an engine, on a plot or on my parked craft, says the key that fires it and how to set one
    const g = gadgetAimed(a);
    if (g) {
      // CONFIGURE AND ACTIVATE (operator 2026-11-12: "everything should have a configure and activate"): every gadget
      // says what activates it (its key, at the controls) and how it is configured (1–9 at the gadget; a phone: the hotbar)
      const what = blockLabel(g.b[6]), how = touch ? T("v.keyTap", "configure: tap a hotbar key, the same key again clears it") : T("v.keySet", "configure: 1–9, the same key again clears it");
      return g.slot ? T("aimGadget", "{what} — key {n} activates · {how} · {k} {v}", { what, n: g.slot, k, v: T("v.board", "board"), how })
        : T("aimGadgetNone", "{what} — no key activates it yet · {how} · {k} {v}", { what, k, v: T("v.board", "board"), how });
    }
  }
  if (!a) return "";
  // (a titled plot whose holder is not known yet says "Titled", not "Owned by —": the photo of 2026-11-12)
  const notYours = (what, plot) => {
    const t = titles.get(plot);
    // an invited builder's aim read "not yours to gather here" until the server's answer came in (playtest 2026-11-15,
    // plot 0·4999·3438): until it is in, the line says checking, and the plot aimed at is asked about (once a refresh)
    const unsure = net.me && net.online && t && !mine.has(plot) && !builderKnown.has(plot);
    if (unsure && !t.checked) { t.checked = true; builderCheck(plot); }
    return T("aimFmt2", "{what} — {v}", { what: what + " · " + (t && t.sale ? T("forSale", "For sale · {p} NADO", { p: rawToNado(t.sale.price.toString()) }) : t && t.holder ? ownedBy(t.holder) : T("titled", "Titled")), v: unsure ? T("v.checking", "checking whether you may build here") : T("v.notYours", "not yours to gather here") }); };
  if (a.box) {
    const kind = a.box.b[6], what = blockLabel(kind);
    const verb = kind === B.door || kind === B.chest ? T("v.open", "open") : kind === B.bed ? T("v.sleep", "sleep here") : kind === B.well ? T("v.draw", "draw water (a bucket)")
      : kind === B.pilotseat || (CRAFT_SKIN.has(kind) && seatOfAimed(a.box.plot, a.box.b)) ? T("v.board", "board") : kind === B.generator || kind === B.launchpad || isMachine(kind) ? T("v.use", "use") : null;
    if (verb) return T("aimFmt", "{what} — {k} {v}", { what, k, v: verb });
    return mayBuild(a.box.plot) ? T("aimFmt2", "{what} — {v}", { what, v: T("v.take", "hold {b} to take down", { b }) }) : notYours(what, a.box.plot);
  }
  const [u, v, h] = a.hit, what = blockLabel(blockAt(P.face, u, v, h)), plot = Wd.plotOf(P.face, u, v);
  return mayBuild(plot) ? T("aimFmt2", "{what} — {v}", { what, v: T("v.gather", "hold {b} to gather", { b }) }) : notYours(what, plot);
}
// ---- GADGET KEYS (operator 2026-11-12, in an aircraft on a roof with no run to lift from: "maybe add some thrusters and
// bind them to some keys", "the binding goes to block activation of a particular gadget, it must be universal",
// "configurable at the gadget"): a gadget — any piece that does something: every thruster block and engine part (the
// world server's is_gadget) — takes a KEY at the gadget itself: aim at it and press 1–9 (0 for none; on a phone, tap the
// hotbar's key). At the controls that key fires it, full on, as long as it is held (land-flight.js heldThrust); the
// unbound ones stay automatic. The key is kept by the world server with the piece, on the plot or on the craft.
const isGadget = (b) => Wd.engineCount(b) > 0 || Wd.isCannon(b);   // a thruster, an engine part, or a cannon (#171)
/** The gadget under the crosshair: a plot piece { plot, box, b, slot } or a piece of my parked craft { craft, i, b, slot }; null. */
function gadgetAimed(a) {
  a = a === undefined ? aim() : a;
  if (a && a.box && isGadget(a.box.b)) { const rec = plotBoxes.get(a.box.plot); return { plot: a.box.plot, box: a.box.b, b: a.box.b, slot: rec && rec.gadgets && rec.gadgets[a.box.b.join(",")] || 0 }; }
  if (flying) return null;
  const hit = craftPieceAimed();
  return hit && isGadget(hit.b) ? hit : null;
}
/** The nearest piece of one of my parked crafts along the look, within 8 m: { craft, i, b, slot }, or null. The look
 *  is taken into the craft's own frame (yaw only: a parked craft stands level) and tested against each piece's box. */
function craftPieceAimed() {
  const { fr, fw } = look();
  const d = [fr.east, fr.north, fr.up].map((ax) => fw[0] * ax[0] + fw[1] * ax[1] + fw[2] * ax[2]);
  const o = [P.u, P.v, P.h + EYE];
  let best = null;
  for (const [id, c] of crafts) {
    if (c.owner !== net.me || c.pilot || !c.pose || c.pose[0] !== P.face || !c.pieces) continue;
    if (Math.hypot(c.pose[1] - P.u, c.pose[2] - P.v) > 20) continue;
    const yaw = c.pose[4] || 0, sy = Math.sin(yaw), cy = Math.cos(yaw);
    // world (east, north, up) -> the craft's (right, nose, up): x = e·cos − n·sin, z = e·sin + n·cos (land_server turn_pieces)
    const loc = (e, n, h) => [e * cy - n * sy, e * sy + n * cy, h];
    const ro = loc(o[0] - c.pose[1], o[1] - c.pose[2], o[2] - c.pose[3]), rd = loc(d[0], d[1], d[2]);
    for (let i = 0; i < c.pieces.length; i++) {
      const a = Wd.boxAabb(c.pieces[i]).map((x) => x / Wd.CM);     // [x, z, y, w, d, h]: right, nose, up from the seat
      const lo = [a[0], a[1], a[2]], hi = [a[0] + a[3], a[1] + a[4], a[2] + a[5]];
      let t0 = 0, t1 = 8;
      for (let k = 0; k < 3 && t0 <= t1; k++) {
        if (Math.abs(rd[k]) < 1e-9) { if (ro[k] < lo[k] || ro[k] > hi[k]) { t0 = 9; } continue; }
        let ta = (lo[k] - ro[k]) / rd[k], tb = (hi[k] - ro[k]) / rd[k];
        if (ta > tb) [ta, tb] = [tb, ta];
        t0 = Math.max(t0, ta); t1 = Math.min(t1, tb);
      }
      if (t0 <= t1 && (!best || t0 < best.t)) best = { craft: id, i, b: c.pieces[i], slot: c.slots && c.slots[i] || 0, t: t0 };
    }
  }
  return best;
}
/** Give the aimed gadget key n (0: none): the world server keeps it with the piece. */
function bindAimed(n) {
  const g = gadgetAimed();
  if (!g) return false;
  if (!net.online || !net.me) { signInNotice(T("signInFirst", "Sign in first.")); return true; }
  if (n && g.slot === n) n = 0;                                            // its own key again: the key is taken away
  net.send(g.craft !== undefined ? { t: "bind", craft: g.craft, i: g.i, slot: n, req: ++net.req } : { t: "bind", plot: g.plot, box: g.box, slot: n, req: ++net.req });
  return true;
}
/** The key slots held right now: the digits on a keyboard, the hotbar's keys on a phone. */
function heldSlots() {
  const out = new Set();
  for (let n = 1; n <= 9; n++) if (keys.has("Digit" + n) || (touch && touch.slots && touch.slots.has(n))) out.add(n);
  return out;
}
/** The NPC under the crosshair within talking reach: its id, or null. */
function npcAimed() {
  if (!npcs.size) return null;
  const { fr, fw } = look();
  const d = [fr.east, fr.north, fr.up].map((ax) => fw[0] * ax[0] + fw[1] * ax[1] + fw[2] * ax[2]);
  const o = [P.u, P.v, P.h + EYE], reach = RULES && RULES.quests ? RULES.quests.talk : 4;
  let best = null;
  // THE WHOLE BODY CATCHES THE LOOK (#177, measured on the live page 2026-11-12): one point a metre over the feet, 0.55 m
  // round it, missed a player 0.6 m from Tobin with the crosshair on his chest — the aim line stayed empty and Use said
  // "Aim at a door or a chest". The figure is a standing segment: the look's closest approach to its feet-to-head line,
  // sampled at the shins, the belly and the chest, within 0.45 m.
  for (const [id, r] of npcs) {
    const feet = (r.gh ?? P.h);
    for (const up of [0.3, 0.9, 1.5]) {
      const c = [r.at[1], r.at[2], feet + up], w = [c[0] - o[0], c[1] - o[1], c[2] - o[2]], t = w[0] * d[0] + w[1] * d[1] + w[2] * d[2];
      if (t < 0 || t > reach + 0.5) continue;
      if (Math.hypot(w[0] - d[0] * t, w[1] - d[1] * t, w[2] - d[2] * t) < 0.45 && (!best || t < best.t)) best = { id, t };
    }
  }
  return best && best.id;
}
let talkingTo = null;
/** A notice that the player must sign in, with the button that does it (playtest 2026-11-15, a visitor on a phone: Use
 *  on a townsperson said "Sign in first." and nothing more — the only way in was the HUD's link); offline, the words
 *  alone (the link would lead nowhere). The same link and words as the HUD's sign-in. */
function signInNotice(msg) {
  if (!net.online) return notify(msg);
  return alertBar(msg, T("signInBuild", "Sign in to build"), () => location.assign("/land/api/login"), { tone: "info" });
}
function openNpc(id) {
  if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
  talkingTo = id;
  const r = npcs.get(id);
  $("npcTitle").textContent = r ? `${r.name} · ${roleName(r.role)}` : id;
  $("npcGrid").textContent = "…";
  if (document.pointerLockElement) document.exitPointerLock();
  showPanel("npcPanel", true);
  net.send({ t: "talk", npc: id, req: ++net.req });
}
/** Where a bring quest's item is gathered by hand: the first breaking rule that yields it with no tool (its block's name),
 *  or nothing — "no offer says where berries are found" (#165, playtest 2026-11-11). */
function gatheredFrom(item) {
  if (!RULES || !RULES.breaking) return "";
  for (const [b, r] of Object.entries(RULES.breaking)) {
    if (!r || typeof r !== "object" || r.needs || r.class || !Array.isArray(r.yields)) continue;
    if (r.yields.some((y) => Array.isArray(y) && y[0] === item) && BLOCKS[Number(b)]) return blockLabel(Number(b));
  }
  return "";
}
/** The tool an item can only be gathered with, when every block that gives it asks for one ("" when a hand will do):
 *  the first such class's simplest tool — the first in the tools table, its stone one. (Clay is dug, wood chopped,
 *  cobble mined: the line says the tool is needed, not how it is used.) */
function toolFor(item) {
  if (!RULES || !RULES.breaking) return "";
  // (something a recipe makes is made, not gathered: planks come from wood at a workbench, not with an axe)
  if ((RULES.recipes || []).some((r) => r.makes.some(([id]) => id === item))) return "";
  let cls = "";
  for (const r of Object.values(RULES.breaking)) {
    if (!r || typeof r !== "object" || !Array.isArray(r.yields) || !r.yields.some((y) => Array.isArray(y) && y[0] === item)) continue;
    if (!r.class && !r.needs) return "";
    cls = cls || r.class || "";
  }
  return cls;
}
function questText(q) {
  if (q.kind === "bring") {
    // WHAT YOU HOLD OF IT, as a hunt shows its count (playtest 2026-11-15: carrying 2 stones, "Bring 6 × Stone" said
    // nothing of them) — numbers only, the same in every language
    const from = gatheredFrom(q.item), have = Math.min(q.n, (inv.items || {})[q.item] || 0);
    return (from ? T("qBringFrom", "Bring {n} × {i} — found as {b}", { n: q.n, i: nameOf(q.item), b: from }) : T("qBring", "Bring {n} × {i}", { n: q.n, i: nameOf(q.item) })) + ` (${have}/${q.n})`;
  }
  if (q.kind === "hunt") return T("qHunt", "Hunt {n} × {a}", { n: q.n, a: animalName(q.what) }) + (q.got !== undefined && q.got > 0 ? ` (${q.got}/${q.n})` : "");
  const to = RULES.quests.npcs.find((n) => n.id === q.to);
  return T("qDeliver", "Carry a parcel to {who}", { who: to ? `${to.name} (${roleName(to.role)})` : q.to });
}
function renderNpc(m) {
  const g = $("npcGrid");
  if (m.error) { g.textContent = m.error === "too far away — go up to them" ? T("qFar", "Too far — go up to them.") : m.error; return; }
  const greet = { elder: T("npcElderSays", "Work for willing hands — the town pays from its treasury."), trader: T("npcTraderSays", "Trade at the stands; I keep an eye on the prices."), smith: T("npcSmithSays", "Bring me metal and I will show you what it can become.") }[m.role] || "";
  // the trader's word (#165): the nearest stand, or that none is built yet (the server's `stand`)
  const stand = m.stand === undefined ? "" : m.stand ? T("traderStand", "The nearest trading stand is {m} m away, bearing {b}° — stand at it to make an offer.", { m: m.stand.m, b: m.stand.bearing })
    : T("traderNoStand", "No trading stand is built yet — make one at a workbench and set it on your plot.");
  g.innerHTML = `<p class="dim">${esc(greet)}${stand ? " " + esc(stand) : ""}</p>
    ${m.ends.length ? `<h3>${esc(T("qEnds", "Your quests here"))}</h3>` + m.ends.map((q) => `<div class="rcp"><div>${esc(questText(q))}</div>
      <button class="ghost" data-turnin="${q.id}" ${q.ready ? "" : "disabled"}>${esc(q.ready ? T("qTurnIn", "Hand in") : T("qNotYet", "Not done yet"))}</button></div>`).join("") : ""}
    ${m.offers.length ? `<h3>${esc(T("qOffers", "Work offered"))}</h3>` + m.offers.map((q) => `<div class="rcp"><div>${esc(questText(q))}<div class="dim">${esc(T("qPays", "+{x} experience", { x: RULES.quests.xp[q.kind] }))}</div></div>
      <button class="ghost" data-qaccept="${q.id}">${esc(T("qAccept", "Accept"))}</button></div>`).join("") : ""}`;
  g.querySelectorAll("[data-qaccept]").forEach((b) => { b.onclick = () => net.send({ t: "quest", op: "accept", npc: talkingTo, id: b.dataset.qaccept, req: ++net.req }); });
  g.querySelectorAll("[data-turnin]").forEach((b) => { b.onclick = () => net.send({ t: "quest", op: "turnin", npc: talkingTo, id: b.dataset.turnin, req: ++net.req }); });
}
/** What a strike or an arrow did, in the player's language. */
// ---- THE ENERGY CANNON (#171 item 3, approved by the operator 2026-11-14): a cannon part bound to a key at the cannon
// fires a bolt along its barrel while the pilot holds that key, up to four a second a cannon (land_server.py BOLT_EVERY),
// out to BOLT_RANGE. The page finds what the bolt meets — the first animal within a metre of its line, or the first cell of
// the planet's own tree on land the pilot may build on (a stranger's titled plot keeps its trees, as from the craft's body);
// the ground or a built piece ends it — draws it, and names the target to the world server, which checks it (World.bolt).
const BOLT_RANGE = 400, BOLT_EVERY = 250, BOLT_STEP = 0.5, BOLT_LIFE = 140;
/** The cannons of a craft: each bound one's key, its muzzle (m, the craft's frame: right, nose, up) and its barrel's way. */
function cannonsOf(pieces, slots) {
  const out = [];
  pieces.forEach((b, i) => {
    const n = slots && slots[i] > 0 ? slots[i] : 0;
    if (!n || !Wd.isCannon(b)) return;
    const a = Wd.boxAabb(b), d = tiltDir(b, [0, 1, 0]), half = b[4] / 200;   // a cannon's barrel along its length, as an engine's thrust
    const c = [(a[0] + a[3] / 2) / 100, (a[1] + a[4] / 2) / 100, (a[2] + a[5] / 2) / 100];
    out.push({ slot: n, muzzle: [c[0] + d[0] * half, c[1] + d[1] * half, c[2] + d[2] * half], dir: d, at: 0 });
  });
  return out;
}
const bolts = [];                                           // { line, t0 } — what is drawn of a fired bolt
let boltMat = null;
function cannonTick(c, held) {
  if (!c.cannons || !c.cannons.length || !held || !held.size) return;
  const now = performance.now(), [f, u, v, h, yaw] = c.pose, ax = axesOf(yaw, c.pose[5] || 0, c.pose[6] || 0);
  const toLocal = (p) => [0, 1, 2].map((i) => ax.right[i] * p[0] + ax.nose[i] * p[1] + ax.up[i] * p[2]);   // east, north, up
  for (const g of c.cannons) {
    if (!held.has(g.slot) || now - g.at < BOLT_EVERY) continue;
    g.at = now;
    const m = toLocal(g.muzzle), d = toLocal(g.dir), o = [u + m[0], v + m[1], h + m[2]];
    let end = BOLT_RANGE, target = null;
    for (let s = BOLT_STEP; s <= BOLT_RANGE && !target; s += BOLT_STEP) {
      const p = [o[0] + d[0] * s, o[1] + d[1] * s, o[2] + d[2] * s];
      for (const [id, r] of animals) if (Math.hypot(r.cu - p[0], r.cv - p[1], (r.gh ?? r.h) + 0.6 - p[2]) < 1.0) { target = { animal: id }; break; }
      if (target) { end = s; break; }
      const cu = Math.floor(p[0]), cv = Math.floor(p[1]), ch = Math.floor(p[2]), b = blockAt(f, cu, cv, ch);
      if (Wd.isTree(b) && !edits.has(key(f, cu, cv, ch)) && mayBuild(Wd.plotOf(f, cu, cv))) { target = { cell: [f, cu, cv, ch] }; end = s; break; }
      if (solidAt(f, p[0], p[1], p[2])) { end = s; break; }   // the ground, a built piece: the bolt ends there
    }
    drawBolt(f, o, [o[0] + d[0] * end, o[1] + d[1] * end, o[2] + d[2] * end], now);
    sound.cue("bolt", 0.8, 80);
    if (target && target.cell) { const [tf, tu, tv, th] = target.cell; putCell(tf, tu, tv, th, B.air); }   // torn at once, as by the body
    net.send({ t: "bolt", craft: c.id, dir: d, target, len: target ? undefined : end });   // len: where the ground ended it, for the others
  }
}
/** A bolt drawn from `a` to `b` ([u, v, h] on face `f`) — the pilot's own, and every one the world server says another
 *  pilot fired near here ("bolt_seen", Hub.bolt): #171, no one but the pilot ever saw the cannon fire. */
function drawBolt(f, a, b, now) {
  if (!boltMat) boltMat = new THREE.LineBasicMaterial({ color: 0x9ff3ff, transparent: true, depthWrite: false });
  const line = new THREE.Line(new THREE.BufferGeometry(), boltMat.clone());
  line.userData.pts = [a, b].map(([pu, pv, ph]) => Wd.posOf(f, pu, pv, ph)); line.frustumCulled = false; scene.add(line);
  bolts.push({ line, t0: now });
}
function boltsFrame(now, cam) {
  for (let i = bolts.length - 1; i >= 0; i--) {
    const k = bolts[i], age = (now - k.t0) / BOLT_LIFE;
    if (age >= 1) { scene.remove(k.line); k.line.geometry.dispose(); k.line.material.dispose(); bolts.splice(i, 1); continue; }
    const [a, b] = k.line.userData.pts;
    k.line.geometry.setAttribute("position", new THREE.Float32BufferAttribute([a[0] - cam[0], a[1] - cam[1], a[2] - cam[2], b[0] - cam[0], b[1] - cam[1], b[2] - cam[2]], 3));
    k.line.material.opacity = 1 - age;
  }
}
function huntSaid(m) {
  const H = RULES.hunting;
  if (m.killed) {
    const butchered = (H.species[m.killed].drops || []).some(([i]) => (H.butcher || []).includes(i));
    notify(T("huntKilled", "You hunted a {a}.", { a: animalName(m.killed) }) + (!m.knife && butchered ? " " + T("noKnife", "Without a knife you took only the meat.") : ""));
  } else if (m.hit) {
    notify((H.species[m.hit] || {}).damage ? T("huntHitFight", "A hit — the {a} turns on you!", { a: animalName(m.hit) }) : T("huntHit", "A hit — the {a} runs!", { a: animalName(m.hit) }));
  } else if (m.end) notify(T("huntMiss", "A miss — the arrow fell short or wide."));
}
const animalName = (k) => T("a." + k, { deer: "deer", boar: "boar", rabbit: "rabbit", sheep: "sheep" }[k] || k);
/** Break on an animal: a spear strike when it is within the spear's reach; else, with a bow, an arrow loosed along the
 *  look (BALLISTICS #157: it flies, falls and can miss — the world server flies it again and judges the hit). */
function huntAt(an) {
  const H = RULES && RULES.hunting;
  if (!H) return false;
  const spear = hasClass("spear"), bow = hasClass("bow");
  if (!spear && !bow) { notify(T("huntNeeds", "Hunting needs a spear or a bow.")); return true; }
  if (spear && an.d <= H.weapons.spear.reach) { net.send({ t: "hunt", id: an.id, req: ++net.req }); return true; }
  // beyond a strike: a bow with arrows looses one; else a spear is THROWN at an animal within its throwing reach (#157)
  if (bow && inv.items.arrow > 0) return loose();
  if (spear && an.d <= H.ballistics.throw_reach) return throwSpear();
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
// A THROWN SPEAR (#157): out of the hands along the look at the measured throw speed (land-recipes hunting.ballistics
// about_throw), flown here as an arrow is while the world server flies its own; it lies where it ends, to be walked over
function spearMesh() {
  const g = new THREE.Group();
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 1.9, 6), new THREE.MeshLambertMaterial({ color: 0x8a6a42 }));
  shaft.rotation.x = Math.PI / 2; g.add(shaft);
  const tip = new THREE.Mesh(new THREE.ConeGeometry(0.035, 0.16, 6), new THREE.MeshLambertMaterial({ color: 0x6f6a64 }));
  tip.rotation.x = Math.PI / 2; tip.position.z = 1.02; g.add(tip);
  return g;
}
function throwSpear() {
  const B = RULES.hunting.ballistics, cp = Math.cos(P.pitch);
  const vel = [B.throw * cp * Math.sin(P.yaw), B.throw * cp * Math.cos(P.yaw), B.throw * Math.sin(P.pitch)];
  const m = spearMesh(); scene.add(m);
  arrowsInFlight.push({ mesh: m, o: [P.u, P.v, P.h + 1.5], vel, t0: performance.now(), until: 4, face: P.face });
  net.send({ t: "throw", yaw: P.yaw, pitch: P.pitch, req: ++net.req });
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
    if (!groundArrows.has(id)) { const m = RULES && RULES.tools[item] ? spearMesh() : arrowMesh(); scene.add(m); groundArrows.set(id, { mesh: m, u, v, h, item }); }   // a thrown spear lies as a spear (#157)
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
/** A face as a decal for the head's front cap: transparent around it; mirrored, as the sphere's u runs right to left
 *  seen from the front. */
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
  // the trace goes up in batches: ten seconds apart, or at once past twenty events (signed in: the file is theirs)
  if (net.me && TRACE.pending.length && (TRACE.pending.length >= 20 || performance.now() - TRACE.sentAt > 10000)) {
    TRACE.sentAt = performance.now(); net.send({ t: "trace", events: TRACE.pending.splice(0, 50) });
  }
}
async function builderCheck(plot) {
  if (!net.online || !net.me || mine.has(plot) || !titles.has(plot)) return;
  // asked again at every title refresh (t.checked is reset there): an invitation given while you play shows up, and one
  // withdrawn — or ended by a sale — goes away, without a reload
  try {
    const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin" })).json();
    if (r.may_build !== builds.has(plot)) { if (r.may_build) builds.add(plot); else builds.delete(plot); hud(); }
  } catch (e) {}
  builderKnown.add(plot);   // answered or failed: either way a refusal stops saying "checking" (never stuck on it)
}

// ---- THE MAP (#173, doc/land-navigation.md 1.3) ----------------------------------------------------------------
// A map shows the land its owner has SURVEYED — the squares they passed through carrying it (land_server.py survey_at) —
// drawn from the planet's own generator (land-world.js column: its biome, its height), north up, with them, the town
// hall, their bed and their crafts on it. Land they have not been to stays blank: a map is drawn by going there.
const MAP_COL = { grass: [106, 154, 74], forest: [63, 107, 53], desert: [216, 196, 138], beach: [226, 210, 156], rock: [138, 138, 134], snow: [238, 242, 244] };
function mapPanel(open) {
  showPanel("mapPanel", open);
  if (!open) return;
  if (flying && flying.nav && flying.nav.fix) return drawPlanet();          // the nav unit with a fix: the whole planet
  if (flying && flying.nav && !((inv.items.map || 0) > 0)) {                 // …without one, it says what it lacks
    clearMap();
    $("mapLegend").textContent = T("mapNoFix", "Your nav unit shows the whole planet once it has a satellite fix — four satellites in view. In view now: {n}.",
      { n: Cosmos.satsInView(satCount, Wd.posOf(flying.pose[0], flying.pose[1], flying.pose[2], flying.pose[3]), Date.now() / 1000 - Cosmos.EPOCH).length });
    return;
  }
  if (!((inv.items.map || 0) > 0)) { $("mapLegend").textContent = T("mapNone", "You have no map. Paper and ink at the workbench make one."); clearMap(); return; }
  $("mapLegend").textContent = T("mapLoading", "Unrolling the map…");
  net.send({ t: "survey", req: ++net.req });
}
function clearMap() { const c = $("mapCanvas"), g = c.getContext("2d"); g.fillStyle = "#1b2430"; g.fillRect(0, 0, c.width, c.height); }
function drawMap(m) {
  const c = $("mapCanvas"), g = c.getContext("2d"), N = c.width, tile = m.tile || 64, tiles = m.tiles || [];
  clearMap();
  if (m.error) { $("mapLegend").textContent = String(m.error); return; }
  // the window: every surveyed square near, at least 512 m across, centred on me
  let half = 256;
  for (const [tu, tv] of tiles) half = Math.max(half, Math.abs((tu + 0.5) * tile - P.u) + tile, Math.abs((tv + 0.5) * tile - P.v) + tile);
  half = Math.min(half, 4096);
  const px = N / (2 * half), X = (u) => (u - (P.u - half)) * px, Y = (v) => ((P.v + half) - v) * px;   // north up
  const step = tile / 2;
  for (const [tu, tv] of tiles) for (let a = 0; a < 2; a++) for (let b = 0; b < 2; b++) {
    const u = tu * tile + a * step, v = tv * tile + b * step, col = Wd.column(P.face, Math.floor(u + step / 2), Math.floor(v + step / 2));
    const sea = col.top < Wd.SEA, k = sea ? 1 : Math.max(0.7, Math.min(1.3, 0.85 + (col.top - Wd.SEA) / 160));
    const rgb = sea ? [59, 111, 168] : (MAP_COL[col.biome] || MAP_COL.grass).map((x) => Math.min(255, Math.round(x * k)));
    g.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
    g.fillRect(X(u), Y(v + step), Math.ceil(step * px) + 1, Math.ceil(step * px) + 1);
  }
  const MAP_ME = 6, MAP_SQUARE = 10;                       // your dot's radius; a place's square, half its side (px)
  const mark = (u, v, fill, shape) => {
    const x = X(u), y = Y(v);
    if (x < -8 || y < -8 || x > N + 8 || y > N + 8) return;
    g.fillStyle = fill; g.strokeStyle = "#000"; g.lineWidth = 1.5; g.beginPath();
    // A PLACE'S SQUARE IS WIDER THAN YOUR DOT (MAP_SQUARE > MAP_ME): at 12 px it lay wholly under the 6 px dot drawn over
    // it, and standing in the square the town hall was not on the map at all — one pixel of it (playtest 2026-11-16)
    if (shape === "square") g.rect(x - MAP_SQUARE, y - MAP_SQUARE, 2 * MAP_SQUARE, 2 * MAP_SQUARE); else g.arc(x, y, 5, 0, 2 * Math.PI);
    g.fill(); g.stroke();
  };
  if (m.town && m.town[0] === P.face) mark(m.town[1], m.town[2], "#e8c547", "square");
  if (m.bed && m.bed[0] === P.face) mark(m.bed[1], m.bed[2], "#c0392b", "square");
  for (const cr of m.crafts || []) if (cr.pose[0] === P.face) mark(cr.pose[1], cr.pose[2], "#6fd3e8", "dot");
  // me: an arrow along my heading with a compass, a dot without one (a map alone does not say which way you face)
  const mx = X(P.u), my = Y(P.v);
  g.fillStyle = "#fff"; g.strokeStyle = "#000"; g.lineWidth = 1.5; g.beginPath();
  if ((inv.items.compass || 0) > 0) {
    const s = Math.sin(P.yaw), co = Math.cos(P.yaw), pt = (f, r) => [mx + s * f + co * r, my - co * f + s * r];
    const [a1, a2] = pt(10, 0), [b1, b2] = pt(-6, 6), [c1, c2] = pt(-6, -6);
    g.moveTo(a1, a2); g.lineTo(b1, b2); g.lineTo(c1, c2); g.closePath();
  } else g.arc(mx, my, MAP_ME, 0, 2 * Math.PI);
  g.fill(); g.stroke();
  // north, and a scale bar of a round length
  g.fillStyle = "#fff"; g.font = "bold 14px system-ui"; g.textAlign = "center"; g.fillText(T("cpN", "N") + " ↑", N - 24, 22);
  const bar = [50, 100, 200, 500, 1000, 2000].find((x) => x * px >= 60) || 2000;
  g.fillRect(14, N - 18, bar * px, 3); g.textAlign = "left"; g.font = "12px system-ui"; g.fillText(bar >= 1000 ? `${bar / 1000} km` : `${bar} m`, 14, N - 24);
  const a = tiles.length * tile * tile / 1e6, km2 = a.toFixed(a < 1 ? 3 : 2);
  const key = (fill, label) => `<b style="background:${fill}"></b>${esc(label)}`;
  $("mapLegend").innerHTML = (tiles.length ? esc(T("mapArea", "{a} km² surveyed near you", { a: km2 })) : esc(T("mapEmpty", "Nothing surveyed here yet — carry the map and go: it draws the land you pass through.")))
    + "<br>" + key("#fff", T("mapYou", "you")) + key("#e8c547", T("mapTown", "town hall")) + key("#c0392b", T("mapBed", "your bed")) + key("#6fd3e8", T("mapCraft", "your crafts"));
}
// THE PLANET'S FACTS (operator 2026-11-11: "we need proper planetary physical properties like in Kerbal space"): what the
// planet is as a body, every figure computed in land-planet.js from its radius, its gravity and cited constants
function planetPanel(open) {
  showPanel("planetPanel", open);
  if (!open) return;
  if (document.pointerLockElement) document.exitPointerLock();
  const f = Planet.facts(), km = (m) => (m / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 }), n0 = (x) => Math.round(x).toLocaleString();
  const exp = Math.floor(Math.log10(f.mass)), mant = (f.mass / 10 ** exp).toFixed(2);
  const row = (k, d, v) => `<div>${esc(T(k, d, v))}</div>`;
  $("planetGrid").innerHTML = row("plRadius", "Radius: {r} km", { r: km(f.radius) })
    + row("plGravity", "Gravity at the surface: {g} m/s²", { g: f.g })
    + row("plMass", "Mass: {m} × 10^{e} kg", { m: mant, e: exp })
    + row("plDensity", "Density: {d} kg/m³ — {x} times Earth's: a small world with a strong pull is a very dense one", { d: n0(f.density), x: f.densityTimesEarth.toFixed(0) })
    + row("plEscape", "Escape speed: {v} m/s", { v: n0(f.escape) })
    + row("plDay", "A day: {m} minutes — the equator turns at {s} m/s", { m: f.day / 60, s: n0(f.equatorSpin) })
    + row("plAir", "Air at sea level: {p} kPa, {t} °C, {r} kg/m³ — thinner with height, none above {top} km", { p: (f.sea.p / 1000).toFixed(1), t: (f.sea.T - 273.15).toFixed(0), r: f.sea.rho.toFixed(3), top: km(f.airTop) })
    + row("plOrbit", "Lowest orbit, just above the air: {v} m/s, once every {t} minutes", { v: n0(f.orbitLow), t: (f.periodLow / 60).toFixed(1) })
    + row("plSync", "Synchronous orbit, over the same ground all day: {h} km up", { h: km(f.syncHeight) })
    + row("plSats", "Positioning satellites in orbit: {n}", { n: satCount })
    + `<p class="note">${esc(T("plNote", "The air's top is the one number not from physics: a real atmosphere would not stay on so small a world, so here it ends, as in other space games."))}</p>`;
}
// THE WHOLE PLANET (#173: "the nav system should show the entire earth - and requires launching orbital real physical gps
// satellites into orbit"): a craft whose nav unit has a satellite fix shows the planet entire — two hemispheres, the one
// under the craft and the one opposite, each pixel the planet's own ground there (land-world.js column: its biome, sea
// below SEA), with the craft and the town hall on it.
function drawPlanet() {
  const c = $("mapCanvas"), g = c.getContext("2d"), N = c.width, R = N / 4 - 6, step = 3;
  clearMap();
  const fr = Wd.frameOf(flying.pose[0], flying.pose[1], flying.pose[2]);
  const disc = (cx, sign) => {
    for (let py = -R; py < R; py += step) for (let px = -R; px < R; px += step) {
      const x = px / R, y = -py / R, z2 = 1 - x * x - y * y;
      if (z2 <= 0) continue;
      const z = Math.sqrt(z2), d = [0, 1, 2].map((i) => sign * (fr.up[i] * z) + fr.east[i] * x * sign + fr.north[i] * y);
      const q = Wd.gridOf(d), col = Wd.column(q.face, Math.max(0, Math.min(Wd.W - 1, Math.floor(q.u))), Math.max(0, Math.min(Wd.W - 1, Math.floor(q.v))));
      const sea = col.top < Wd.SEA, k = sea ? 1 : Math.max(0.7, Math.min(1.3, 0.85 + (col.top - Wd.SEA) / 160));
      const rgb = sea ? [59, 111, 168] : (MAP_COL[col.biome] || MAP_COL.grass).map((v) => Math.min(255, Math.round(v * k * (0.55 + 0.45 * z))));
      g.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
      g.fillRect(cx + px, N / 2 + py, step, step);
    }
  };
  disc(N / 4, 1); disc((3 * N) / 4, -1);
  // where a planet point falls: on the near disc or the far one (the far one seen from the other side, mirrored)
  const place = (face, u, v, fill) => {
    const p = Wd.posOf(face, u, v, 0), r = Math.hypot(...p), d = p.map((x) => x / r);
    const z = d[0] * fr.up[0] + d[1] * fr.up[1] + d[2] * fr.up[2], x = d[0] * fr.east[0] + d[1] * fr.east[1] + d[2] * fr.east[2], y = d[0] * fr.north[0] + d[1] * fr.north[1] + d[2] * fr.north[2];
    const cx = z >= 0 ? N / 4 + x * R : (3 * N) / 4 - x * R, cy = N / 2 - y * R;
    g.fillStyle = fill; g.strokeStyle = "#000"; g.lineWidth = 1.5; g.beginPath(); g.arc(cx, cy, 6, 0, 2 * Math.PI); g.fill(); g.stroke();
  };
  const town = townSpawn();
  place(town[0], town[1], town[2], "#e8c547");
  place(flying.pose[0], flying.pose[1], flying.pose[2], "#fff");
  const key = (fill, label) => `<b style="background:${fill}"></b>${esc(label)}`;
  $("mapLegend").innerHTML = esc(T("mapPlanet", "The whole planet — this side and the far side — from your nav unit's satellite fix.")) + "<br>" + key("#fff", T("mapYou", "you")) + key("#e8c547", T("mapTown", "town hall"));
}
// ---- HUD -------------------------------------------------------------------------------------------------------
// THE NAV UNIT'S LINE (#173): the way to the town hall from where it believes the craft is, and how far out it may be. In
// sight of the town hall (NAV_SIGHT m) the pilot sees where they are: a fix, the error back to nothing (a design choice).
const NAV_SIGHT = 150;
function navLine(c) {
  const town = townSpawn();
  // A SATELLITE FIX (#173, doc/land-navigation.md 1.6): four in view of the craft give its place outright (three
  // coordinates and the receiver's clock, Global Positioning System l.187, l.216) — dead reckoning's error is gone
  const view = Cosmos.satsInView(satCount, Wd.posOf(c.pose[0], c.pose[1], c.pose[2], c.pose[3]), Date.now() / 1000 - Cosmos.EPOCH).length;
  c.nav.fix = view >= Cosmos.FIX_SATS;
  if (c.nav.fix || (c.pose[0] === town[0] && Math.hypot(town[1] - c.pose[1], town[2] - c.pose[2]) < NAV_SIGHT)) c.nav.t0 = performance.now();
  const n = navSays(c.pose, (performance.now() - c.nav.t0) / 1000, c.nav.dir, [town[1], town[2]]);
  const d = n.dist >= 1000 ? (n.dist / 1000).toFixed(1) + " km" : Math.round(n.dist) + " m", a = Math.round(Math.abs(n.turn));
  const turn = a < 5 ? T("navAhead", "ahead") : n.turn > 0 ? T("navRight", "{a}° right", { a }) : T("navLeft", "{a}° left", { a });
  return T("navTo", "Nav: town hall {d}, bearing {b}° — {turn} · ±{e} m", { d, b: Math.round(n.bearing), turn, e: Math.round(n.err) })
    + " · " + (c.nav.fix ? T("navGps", "satellite fix ({n} in view)", { n: view }) : T("navNoFix", "dead reckoning ({n} of 4 satellites in view)", { n: view }));
}
// A COMPASS (#173, doc/land-navigation.md 1.2): carried, it says which way you face — the bearing clockwise from north and
// its point of eight. North is +v on a face (land-world.js frameOf), the grid's north: no declination (a design choice).
const POINTS = [["cpN", "N"], ["cpNE", "NE"], ["cpE", "E"], ["cpSE", "SE"], ["cpS", "S"], ["cpSW", "SW"], ["cpW", "W"], ["cpNW", "NW"]];
function compassSays(yaw) {
  const b = ((Math.round(yaw * 180 / Math.PI) % 360) + 360) % 360, [k, d] = POINTS[Math.round(b / 45) % 8];
  return T("compass", "compass {b}° {p}", { b, p: T(k, d) });
}
const plotLabel = (plot) => { const q = Wd.plotCoords(plot); return `${q.face}·${q.prow}·${q.pcol}`; };
/** How far the flown craft is over where it would STAND (#184): its height less its resting height on its feet (restAt,
 *  the same measure flyStep lands it by) — 0.0 at rest on a slope too, where the ground under the seat alone read a
 *  craft standing on its uphill foot as hovering. */
function flyingUp() {
  const [f, u, v, , yaw] = flying.pose;
  return flying.pose[3] - restAt(flying, u, v, yaw, (a, b) => craftGround(f, a, b) - 0.05);
}
function hud() {
  const w = Wd.wrap(P.face, Math.floor(P.u), Math.floor(P.v)), plot = Wd.plotOf(w.face, w.u, w.v), t = titles.get(plot);
  const changed = (plotEdit.get(plot) || new Map()).size;
  $("hudPos").textContent = T("where", "Plot {p} · height {h} m", { p: plotLabel(plot), h: Math.round(P.h - Wd.SEA) })
    + (changed ? " · " + T("changed", "{n} {n|one:changed block|other:changed blocks}", { n: changed }) : "")
    + ((plotBoxes.get(plot) || { list: [] }).list.length ? " · " + T("pieces", "{n} {n|one:piece|other:pieces}", { n: plotBoxes.get(plot).list.length }) : "");
  if (flying && flying.aero && flying.aero.winged) {       // an aircraft (#191): airspeed, height, throttle, angle of attack, load
    const sp = Math.hypot(...flying.vel), up = flyingUp(), air = flying.air || {};
    $("hudPos").textContent = T("fHudWing", "Flying · {s} m/s · {a} m up · throttle {t} % · attack {aoa}° · {n} g", { s: sp.toFixed(1), a: Math.max(0, up).toFixed(1), t: Math.round(100 * (flying.throttle || 0)), aoa: ((air.alpha || 0) * 180 / Math.PI).toFixed(0), n: (air.n || 0).toFixed(1) })
      + (air.stalled ? " · " + T("fStall", "STALL — nose down, throttle up") : "");
    if (flying.nav) $("hudPos").textContent += "\n" + navLine(flying);
  } else if (flying) {                                      // at the controls: speed, height over the ground, what lifts it
    const sp = Math.hypot(...flying.vel), up = flyingUp();
    $("hudPos").textContent = T("fHud", "Flying · {s} m/s · {a} m up · thrust {t} kN, weight {w} kN", { s: sp.toFixed(1), a: Math.max(0, up).toFixed(1), t: Math.round(flying.thrust), w: Math.round(flightOf(FLIGHT(), flying.mass, flying.thrust, Planet.gravityAt(flying.pose[3])).weight) })
      + " · " + T("fEngines", "engines {e} %", { e: Math.round(100 * ((flying.engine && flying.engine.throttle) || 0)) });   // the thrust in use (#171)
    if (flying.nav) $("hudPos").textContent += "\n" + navLine(flying);
  }
  if ((inv.items.compass || 0) > 0) $("hudPos").textContent += " · " + compassSays(P.yaw);   // a compass carried (#173)
  $("mapBtn").classList.toggle("hidden", !((inv.items.map || 0) > 0 || (flying && flying.nav)));   // a map carried, or a nav unit flown: its button (#173)
  const st = $("hudPlot");
  // the owner is looked up once the plot's title is KNOWN (titles load after the first frames), once per refresh
  if (t && !mine.has(plot) && !t.asked) { t.asked = true; holderOf(plot).then(hud); }
  let html;
  if (t && net.online && net.me && !t.checked) { t.checked = true; builderCheck(plot); }
  const signIn = net.online && !net.me ? ` <a class="btn" href="/land/api/login">${esc(T("signInBuild", "Sign in to build"))}</a>` : "";
  // the titles not in yet (titlesVer 0: the first answer bumps it, empty or not), no plot is known to be anyone's — a
  // titled plot read "Wilderness" for the first seconds after a load (playtest 2026-11-15, #199)
  if (!t && !titlesVer) html = `<span class="pill">${esc(T("plotLooking", "Looking up who owns this plot…"))}</span>${signIn}`;
  else if (!t) html = `<span class="pill">${esc(T("wild", "Wilderness"))}</span> <span class="dim">${esc(T("wildOpen", "Unowned: anyone may gather and build here. Own a plot to protect what you build."))}</span>${signIn}`;
  else if (builds.has(plot) && !mine.has(plot)) html = `<span class="pill ok">${esc(T("invited", "You may build here"))}</span> <span class="dim">${esc(t.holder ? ownedBy(t.holder) : "")}</span>`;
  else if (mine.has(plot)) html = `<span class="pill ok">${esc(T("yours", "Your plot"))}</span> <button id="btnAnchor" class="ghost">${esc(T("anchorBtn", "Anchor build"))}</button> <button id="btnInvite" class="ghost">${esc(T("inviteBtn", "Invite a builder"))}</button> <button id="btnSell" class="ghost">${esc(T("sellBtn", "Sell"))}</button>`;
  // your own listing: the market holds the title (so it is not in `mine`), and only its seller may reprice or withdraw it
  else if (t.sale && t.sale.seller && t.sale.seller === (net.me || dapp.me)) html = `<span class="pill ok">${esc(T("yourSale", "Your plot · for sale at {p} NADO", { p: rawToNado(t.sale.price.toString()) }))}</span> <button id="btnReprice" class="ghost">${esc(T("repriceBtn", "Change price"))}</button> <button id="btnUnlist" class="ghost">${esc(T("unlistBtn", "Take off sale"))}</button> <a class="btn" target="_blank" rel="noopener" href="${NFT_URL}#token/${esc(t.aid)}">${esc(T("seeListing", "See the listing"))}</a>`;
  // (how NADO is come by goes with the price: the playtest's newcomer had 0 NADO and nothing in the game said where it
  // comes from, #178)
  else if (t.sale) html = `<span class="pill">${esc(T("forSale", "For sale · {p} NADO", { p: rawToNado(t.sale.price.toString()) }))}</span> <span class="dim">${esc(T("nadoHow", "NADO is this chain's coin: get it on the exchange at dex.nadochain.com, or earn it by running a node."))}</span> <a class="btn" target="_blank" rel="noopener" href="${NFT_URL}#token/${esc(t.aid)}">${esc(T("buyMarket", "Buy on the market"))}</a>${signIn}`;
  else html = `<span class="pill">${esc(t.holder ? ownedBy(t.holder) : T("titled", "Titled"))}</span> <a class="btn" target="_blank" rel="noopener" href="${NFT_URL}#token/${esc(t.aid)}">${esc(T("market", "View on the market"))}</a>${signIn}`;
  if (st.dataset.html !== html) {
    st.innerHTML = html; st.dataset.html = html;
    const b = $("btnAnchor"); if (b) b.onclick = () => anchor(plot);
    const iv = $("btnInvite"); if (iv) iv.onclick = () => invite(plot);
    const sl = $("btnSell"); if (sl) sl.onclick = () => sell(plot);
    const rp = $("btnReprice"); if (rp) rp.onclick = () => reprice(plot);
    const ul = $("btnUnlist"); if (ul) ul.onclick = () => unlist(plot);
  }
  if (touch) fitHud();
}
/** On a phone the HUD's lines stop above the buttons under them: in German, signed out, the plot card wrapped onto one
 *  more line and Settings ran 1 px into Fire (playtest 2026-11-16; measured in all 17 languages, only German). Measured
 *  after every redraw; past the top button row, less 4 px, the HUD takes its tighter type (.tight), else its own. */
function fitHud() {
  const h = $("hudInfo"), f = $("tFire");
  // (shown or not by its client rects: the buttons are position:fixed, whose offsetParent is always null — an
  // offsetParent test returned here every time, and German stayed 1 px into Fire on the live page)
  if (!h || !f || !f.getClientRects().length) return;
  h.classList.remove("tight");
  if (h.getBoundingClientRect().bottom > f.getBoundingClientRect().top - 4) h.classList.add("tight");
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
// THE FIRST OBJECTIVE (#178): one line over the bar that says the next thing to do, instead of the welcome card's wall
// of keys — sign in; then talk to the elder (there is work); then the work itself, and that it is done. Refreshed with
// the bar: every inventory message and sign-in change comes through hotbar().
// THE WAY TO A BRING-JOB'S SOURCE (playtest 2026-11-15, the agent's berry errand: "found as Berry bush" — and every
// bush within 84 m of the landing stood on someone's plot, "not yours to gather here", with nothing to say where one
// could be picked): while a bring-job is open the goal line names the nearest source the player MAY gather — the
// planet's own litter of that kind (the page draws the same litter the world server keeps: Wd.litterAt) on land
// mayBuild allows — by distance and compass point, or says none lies within SOURCE_R. The search walks rings outward a
// slice at a time (SOURCE_STEP points a frame) so a phone never stalls, and starts again when the job changes or the
// player has moved SOURCE_MOVE metres.
const SOURCE_R = 160, SOURCE_STEP = 1500, SOURCE_MOVE = 12;
let srcScan = null, goalTick = 0;
function sourceBlocks(item) {
  const out = [];
  if (!RULES || !RULES.breaking) return out;
  for (const [b, r] of Object.entries(RULES.breaking))
    if (r && typeof r === "object" && !r.needs && !r.class && Array.isArray(r.yields) && r.yields.some((y) => Array.isArray(y) && y[0] === item) && Wd.LITTER.has(Number(b))) out.push(Number(b));
  return out;
}
// …AND WHAT IS DUG, once the player holds the tool (playtest 2026-11-16: a clay errand — clay lies in beds two to four
// layers under the grass, land-world terrainBlock, so a shovel at the surface gives earth, and the line named nowhere):
// the ground blocks that give the item to a tool the player has, looked for DIG_DEPTH layers under each cell
const DIG_DEPTH = 4;
function digBlocks(item) {
  const out = [];
  if (!RULES || !RULES.breaking) return out;
  for (const [b, r] of Object.entries(RULES.breaking))
    if (r && typeof r === "object" && !r.needs && r.class && hasClass(r.class) && Array.isArray(r.yields) && r.yields.some((y) => Array.isArray(y) && y[0] === item)
        && Wd.NATURAL.has(Number(b)) && !Wd.LITTER.has(Number(b))) out.push(Number(b));
  return out;
}
function sourceHint(item) {
  const want = sourceBlocks(item), dig = digBlocks(item);
  if (!want.length && !dig.length) return "";
  // NOT BEFORE THE TITLES ARE IN: until they load every plot reads as open land (mayBuild), and the first scan after a
  // load pointed at a bush on a plot for sale (playtest 2026-11-15, "12 m E"); a change of titles starts the scan again
  if (!titlesVer) return "";
  // (and again when the player's own count of it changes: picked, the bush just emptied stayed named — "2 m SE")
  // (…and when the tool to dig it comes into the bag: the scan looks under the ground from then on)
  const job = item + "@" + P.face + "#" + titlesVer + "x" + ((inv.items || {})[item] || 0) + "d" + dig.join(".");   // (not "key": that is the page's cell-key function)
  if (!srcScan || srcScan.job !== job || Math.hypot(P.u - srcScan.u0, P.v - srcScan.v0) > SOURCE_MOVE) {
    // THE PLOTS' EDITS FIRST, in ONE request (playtest 2026-11-15: from the landing the hint said 78 m S, then 24 m
    // further, then 14 m further — each bush the far scan named had been picked, which its plot's edits, not loaded at
    // that distance, would have said; asked plot by plot, a 160 m circle crossing ~100 plots took minutes): the world
    // server's region answer holds every plot in the box with edits or pieces; every other plot in it is untouched
    const s0 = { job, u0: Math.floor(P.u), v0: Math.floor(P.v), d: 0, i: 0, best: null, until: Infinity, found: null, done: false, ready: false };
    srcScan = s0;
    const R = SOURCE_R + 2, q = (x) => Math.max(0, Math.min(W - 1, Math.floor(x)));
    fetch(`/land/api/region?face=${P.face}&u0=${q(P.u - R)}&v0=${q(P.v - R)}&u1=${q(P.u + R)}&v1=${q(P.v + R)}`, { credentials: "same-origin" })
      .then((r) => r.json()).then((j) => {
        for (const [p, e] of Object.entries(j.plots || {})) if (!plotsApplied.has(Number(p))) { applyPlot(Number(p), e.edits || []); setPlotBoxes(Number(p), e.boxes || []); }
      }).catch(() => {}).then(() => { s0.ready = true; });
  }
  const s = srcScan;
  if (!s.ready) return "";                                 // (the plain line until the region's edits are in)
  // EVERY CELL, ring by ring out from the player's own (square rings: the cells at Chebyshev distance d, 8d of them):
  // sampled on 2 m circles from 2 m out, the search skipped the bush a step away and named the next one — followed, the
  // target receded ("16 m SW", there: "22 m W", playtest 2026-11-15). A square ring's corner is d·√2 away, so after the
  // first hit at ring d the rings out to d·√2 are searched too and the truly nearest is named.
  const cellAt = (d, i) => {                               // the i-th cell of ring d (d > 0): top row, right, bottom, left
    const side = 2 * d;
    if (i < side) return [-d + i, d];
    if (i < 2 * side) return [d, d - (i - side)];
    if (i < 3 * side) return [d - (i - 2 * side), -d];
    return [-d, -d + (i - 3 * side)];
  };
  for (let n = 0; n < SOURCE_STEP && !s.done && !s.found; n++) {
    const [du, dv] = s.d === 0 ? [0, 0] : cellAt(s.d, s.i), u = s.u0 + du, v = s.v0 + dv;
    if (u >= 0 && v >= 0 && u < W && v < W && mayBuild(Wd.plotOf(P.face, u, v))) {
      const col = colAt(P.face, u, v), lb = Wd.litterAt(P.face, u, v, col), h = col.top + 1;
      // the planet grows one here — and it is still here: not picked or swept (the plot's edits) and not under a piece
      // (a path laid over it: "8 m N" pointed at a bush under the town's stone path)
      if (want.includes(lb)) {
        // …and it is what actually stands in that cell: a tree's crown wins a cell from the litter under it (land-world
        // terrainBlock), and the hint once named a "bush" that was a low branch — picked, it gave a sapling and a stick
        // (playtest 2026-11-15); blockAt is the page's full answer (the edits included), asked only of a candidate
        if (blockAt(P.face, u, v, h) === lb && !pieceIn([u, v, h])) {
          const dist = Math.hypot(u + 0.5 - P.u, v + 0.5 - P.v);
          if (!s.best || dist < s.best.dist) s.best = { dist, yaw: Math.atan2(u + 0.5 - P.u, v + 0.5 - P.v), down: 0 };
          if (s.until === Infinity) s.until = Math.ceil(s.d * Math.SQRT2) + 1;
        }
      }
      // under the ground: the first layer of it within DIG_DEPTH below the top (the page's full answer: a bed dug out
      // already is not named)
      if (dig.length) for (let k = 1; k <= DIG_DEPTH; k++) {
        if (!dig.includes(blockAt(P.face, u, v, col.top - k))) continue;
        const dist = Math.hypot(u + 0.5 - P.u, v + 0.5 - P.v);
        if (!s.best || dist < s.best.dist) s.best = { dist, yaw: Math.atan2(u + 0.5 - P.u, v + 0.5 - P.v), down: k };
        if (s.until === Infinity) s.until = Math.ceil(s.d * Math.SQRT2) + 1;
        break;
      }
    }
    if (s.d === 0 || ++s.i >= 8 * s.d) { s.d++; s.i = 0; if (s.d > s.until) s.found = { d: Math.round(s.best.dist), yaw: s.best.yaw, down: s.best.down }; else if (s.d > SOURCE_R) s.done = true; }
  }
  const qt = questText({ kind: "bring", item, n: (inv.quests || []).find((x) => x.kind === "bring" && x.item === item)?.n || 1 });
  if (s.found) {
    const pt = POINTS[((Math.round(s.found.yaw / (Math.PI / 4)) % 8) + 8) % 8];
    // one within the player's own metre read "0 m NE" (playtest 2026-11-15, the stone errand): say it is right here
    if (s.found.down) return s.found.d ? T("goalDig", "Your work: {q} · the nearest you may dig: {d} m {p}, {k} m down", { q: qt, d: s.found.d, p: T(pt[0], pt[1]), k: s.found.down })
      : T("goalDigHere", "Your work: {q} · right under you, {k} m down", { q: qt, k: s.found.down });
    if (!s.found.d) return T("goalHere", "Your work: {q} · there is one right here", { q: qt });
    return T("goalNear", "Your work: {q} · the nearest you may pick: {d} m {p}", { q: qt, d: s.found.d, p: T(pt[0], pt[1]) });
  }
  if (s.done) return T("goalNone", "Your work: {q} · none you may pick within {r} m — look in the wilderness, beyond the owned plots", { q: qt, r: SOURCE_R });
  return "";                                               // still searching: the plain line meanwhile
}
/** Who a quest is handed in to: its addressee for a delivery (q.to), else whoever gave it — as the world server ends it. */
function questEnd(q) {
  const n = (RULES.quests && RULES.quests.npcs || []).find((x) => x.id === (q.to || q.giver));
  return n ? `${n.name} (${roleName(n.role)})` : "";
}
function goalLine() {
  const g = $("goal");
  if (!g || !RULES) return;
  let text = "";
  // NOT BEFORE THE SERVER HAS SAID WHO YOU ARE: its greeting carries the sign-in, and until it came every load told a
  // signed-in player "Sign in to gather and build" for a few seconds (playtest 2026-11-16, the agent's phone page)
  if (!net.me) text = net.online ? T("signInBuild2", "Sign in to gather and build.") : "";
  else if ((inv.quests || []).length) {
    const q = inv.quests[0];
    // HANDED IN WHERE IT ENDS (playtest 2026-11-15: a parcel for Ida said "Done — hand it in … (Q at the one who gave
    // it)" the moment it was taken, sending the player back to Maren; the server ends a delivery at its addressee, q.to)
    // (a bring-job not done yet says where the nearest source the player may pick is — sourceHint, below)
    // A TOOL IT NEEDS IS NAMED (playtest 2026-11-16, a real player's trace: "Bring 4 × Clay", no tools in their bag,
    // and they flew kilometres from town — clay is dug with a shovel, the line named no source, and nothing said a
    // shovel was the way; they carried what one is made of): before a source, the tool, and where it is made
    if (!q.ready && q.kind === "bring") {
      const cls = toolFor(q.item);
      if (cls && !hasClass(cls)) {
        const tool = Object.keys(RULES.tools).find((t) => RULES.tools[t].class === cls);
        g.textContent = T("goalTool2", "Your work: {q} · you need a {t} for it — make one in the Bag ({m}).", { q: questText(q), t: nameOf(tool), m: T("make", "Make") });
        return;
      }
      const h = sourceHint(q.item); if (h) { g.textContent = h; return; }
    }
    // the key by name — on a phone the button (there is no Q on a phone: playtest 2026-11-15, the phone layout said
    // "walk up and press Q"), as the aim line names it
    const k = touch ? T("tUse", "Use") : "Q";
    text = q.ready ? T("goalReadyAt", "Done — hand it in to {who}: {q} (walk up and press {k})", { who: questEnd(q), q: questText(q), k }) : T("goalQuest", "Your work: {q}", { q: questText(q) });
  } else {
    const elder = (RULES.quests && RULES.quests.npcs || []).find((n) => n.role === "elder");
    // "First:" only to a newcomer: a player who has earned experience was told "First: talk to Maren" on every load
    // (playtest 2026-11-16, the town agent at level 2) — them it tells there is more work
    if (elder) {
      const who = `${elder.name} (${roleName(elder.role)})`, k = touch ? T("tUse", "Use") : "Q";
      text = (inv.xp || 0) > 0 ? T("goalTalkMore", "More work: talk to {who} — walk up and press {k}.", { who, k })
        : T("goalTalk", "First: talk to {who} — walk up and press {k}. There is work.", { who, k });
    }
  }
  if (g.textContent !== text) g.textContent = text;
}
function hotbar() {
  goalLine();
  const bar = $("hotbar");
  const gunKeys = flying && flying.cannons ? [...new Set(flying.cannons.map((x) => x.slot))] : [];
  if (flying && flying.aero && flying.aero.gadgets && (Object.keys(flying.aero.gadgets).length || gunKeys.length)) {
    // GADGET KEYS at the controls: each bound key with its gadgets' thrust — or ⚡ for a key that fires cannons (#171);
    // held (a phone holds the cell) it fires them
    const g = flying.aero.gadgets, ks = [...new Set([...Object.keys(g).map(Number), ...gunKeys])].sort((a, b) => a - b);
    bar.innerHTML = ks.map((n) => `<div class="hs gadget" data-n="${n}"><span>${n}</span><b>${g[n] ? Math.round(Math.hypot(g[n][0], g[n][1], g[n][2])) + " kN" : ""}${gunKeys.includes(n) ? " ⚡" : ""}</b></div>`).join("");
    bar.querySelectorAll(".hs").forEach((el) => {
      const n = Number(el.dataset.n);
      el.addEventListener("touchstart", (e) => { if (touch) { touch.slots = touch.slots || new Set(); touch.slots.add(n); } e.preventDefault(); }, { passive: false });
      el.addEventListener("touchend", () => { if (touch && touch.slots) touch.slots.delete(n); });
      el.addEventListener("mousedown", () => keys.add("Digit" + n)); el.addEventListener("mouseup", () => keys.delete("Digit" + n)); el.addEventListener("mouseleave", () => keys.delete("Digit" + n));
    });
    $("hotName").textContent = T("hotGadgets", "Hold a key to fire its gadgets");
    return;
  }
  // SIGNED OUT, the bar is not shown (it is kept for the sign-in): a player whose sign-in ran out saw their own items with
  // a 0 under every one — read as an emptied bag (playtest 2026-11-16, the agent's 7-day session ended)
  if (!RULES || !hot.length || !net.me) {
    // the bar holds what can be placed; a bag of berries, sticks and fibre fills none of it, and "gather something"
    // over a full bag sent a newcomer gathering more (#178): say what the bag holds and where it opens
    const held = net.me && RULES ? Object.values(inv.items || {}).filter((n) => n > 0).length : 0;
    bar.innerHTML = `<div class="hs empty">${esc(!net.me ? T("signInGather", "Sign in to gather") : held ? T("bagHeld", "E opens your bag — {n} {n|one:thing|other:things} in it, none of them placeable here", { n: held }) : T("emptyHands", "Empty hands — gather something"))}</div>`;
    $("hotName").textContent = "";
    return;
  }
  bar.innerHTML = hot.map((id, i) => `<div class="hs${i === slot ? " on" : ""}${(inv.items[id] || 0) ? "" : " none"}" data-i="${i}" title="${esc(nameOf(id))}"><canvas width="32" height="32"></canvas><span>${i + 1}</span><b>${inv.items[id] || 0}</b></div>`).join("");
  bar.querySelectorAll(".hs").forEach((el) => {
    const i = Number(el.dataset.i);
    tileIcon(el.querySelector("canvas"), hot[i], 32);
    el.onclick = (e) => { e.stopPropagation(); if (touch && bindAimed(i + 1)) return; slot = i; hotbar(); };   // (a phone sets an aimed gadget's key by its hotbar cell)
  });
  $("hotName").textContent = nameOf(hot[slot]);
  pieceInfo();
}

// ---- the bag: what you have, what you can make, and trade ---------------------------------------------------------
const bagOpen = () => !$("palette").classList.contains("hidden");
function palette(open) {
  showPanel("palette", open);
  if (!open) return;
  if (document.pointerLockElement) document.exitPointerLock();
  makeOrder = null;                                        // (opened: what can be made now goes first again)
  renderBag();
}
// "n × name" as every count in the game reads (#179; a reward said "The town pays 1 Berries", playtest 2026-11-15), and
// PLAIN TEXT: a notice shows it as text and the offer line escapes its whole sentence — escaped here as well, a name with
// & or < read as &amp; on both
const bagText = (bag) => Object.entries(bag).map(([id, n]) => `${n} × ${nameOf(id)}`).join(", ");
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
// THE HUD UNDER THE HEADER (#139, measured on land.nadochain.com at 412 px wide: the header's wallet button wraps onto a
// second line and covered the plot line, which sat at a fixed 52 px): the HUD block is placed 4 px under the lowest of
// the header's contents, whenever the header's size changes (a wrap, a language, signing in), never above its old place.
function hudUnderHeader() {
  const h = document.querySelector("header"), info = $("hudInfo");
  if (!h || !info) return;
  // the lowest of the header's own contents (its box includes empty padding the HUD always sat in: 58 px at 1280 wide,
  // where the HUD's 52 px was right)
  const low = Math.max(0, ...[...h.children].map((e) => e.getBoundingClientRect().bottom));
  info.style.top = Math.max(52, Math.ceil(low) + 4) + "px";
}
try { new ResizeObserver(hudUnderHeader).observe(document.querySelector("header")); } catch (e) {}
addEventListener("resize", hudUnderHeader);

// THE BAG IN TABS (#179 item 4, playtest 2026-11-11: "the Bag is everything at once, one long scroll" — what you hold,
// quests, piece size, every recipe in the game and trade, one under the other): four tabs under the headings the sections
// already had (You have · Piece size · Make · Trade, translated in all 17 languages). Every section is still rendered —
// only the tab's is shown — so every button and its handler below exist whichever tab is open. The tab is remembered
// in this browser (a convenience: it may come back empty). The Make tab lists what can be made now first.
const BAG_TABS = ["have", "build", "make", "trade"];
let makeOrder = null;                                      // the Make list's order while the Bag stays open (renderBag)
let bagTab = (() => { try { const t = localStorage.getItem("nado_land_bagtab"); return BAG_TABS.includes(t) ? t : "have"; } catch (e) { return "have"; } })();
// WHERE THE WATER IS (#206, playtest 2026-11-16: bread wanted water and the nearest was the sea 1.8 km from the town hall,
// which nothing in the game said): a recipe that needs water the player lacks says how far the nearest water is and which
// way. The planet's own water — a column whose ground lies under the sea surface — searched outward in square rings on a
// 16 m grid (a pond narrower than that can be missed), out to WATER_RINGS rings, in slices of WATER_SLICE columns so a
// phone never stalls (393 ms for the town's 1.8 km in node); the answer is kept for the 64 m square the player stands in.
const WATER_RINGS = 200, WATER_SLICE = 1500;
let waterNear = { key: null, res: undefined };            // res: undefined while searching, null if none, else { d, b }
function nearestWater() {
  const key = P.face + ":" + Math.floor(P.u / 64) + ":" + Math.floor(P.v / 64);
  if (waterNear.key === key) return waterNear.res;
  const job = waterNear = { key, res: undefined }, f = P.face, u0 = Math.floor(P.u), v0 = Math.floor(P.v);
  let r = 1, k = 0;                                        // ring r holds 8r cells: 2r a side, k = 0 .. 8r - 1
  // a ring is a square, so the first water on ring r can be a corner √2 r out while an edge of a later ring is nearer
  // (2026-11-22: 815 m given where water lay 785 m off) — the search goes on to ring √2 r and keeps the nearest
  let best = null, until = Infinity;
  const done = (res) => { job.res = res; if (bagOpen()) renderBag(); };
  const step = () => {
    if (waterNear !== job) return;                         // the player moved on: a newer search owns the answer
    for (let n = 0; n < WATER_SLICE; n++) {
      if (k === 8 * r) { r++; k = 0; if (r > until) return done(best); if (r > WATER_RINGS) return done(best); }
      const j = (k % (2 * r)) - r, [du, dv] = [[j, -r], [r, j], [-j, r], [-r, -j]][Math.floor(k / (2 * r))];
      k++;
      const u = u0 + du * 16, v = v0 + dv * 16;      // (the search keeps to this face)
      if (u < 0 || v < 0 || u >= Wd.W || v >= Wd.W) continue;
      if (Wd.column(f, u, v).top < Wd.SEA) {
        const d = Math.hypot(u - P.u, v - P.v);
        if (!best || d < best.dd) best = { dd: d, d: Math.round(d), b: (Math.round(Math.atan2(u - P.u, v - P.v) * 180 / Math.PI) + 360) % 360 };
        if (until === Infinity) until = Math.ceil(r * Math.SQRT2);
      }
    }
    setTimeout(step, 0);
  };
  setTimeout(step, 0);
  return undefined;
}
/** The water hint for recipe r, or "" when it needs none or the player has enough. */
function waterHint(r) {
  const need = (r.uses.find(([id]) => id === "water") || [])[1];
  if (!need || (inv.items.water || 0) >= need) return "";
  const w = nearestWater();
  return " · " + (w === undefined ? T("waterLook", "looking for the nearest water…")
    : w === null ? T("waterNone", "no water within 3 km — a well gives it")
    : T("waterAt", "the nearest water is {d} m away, bearing {b}° (north 0°, east 90°) — a bucket draws it", { d: w.d, b: w.b }));
}
function renderBag() {
  if (!RULES) return;
  // signed out, the way in is HERE (playtest 2026-11-15, a visitor on a phone: the Bag said "Sign in to gather…" with
  // nothing to tap — the only link was the HUD's, behind the panel); the same link as the HUD's, the same words
  if (!net.me) { $("palGrid").innerHTML = `<p class="dim">${esc(T("bagSignIn", "Sign in to gather, make things and trade."))}</p>`
    + (net.online ? `<p><a class="btn" href="/land/api/login">${esc(T("signInBuild", "Sign in to build"))}</a></p>` : ""); return; }
  const items = Object.entries(inv.items).filter(([, n]) => n > 0);
  const atStand = !!standNear(RULES.market ? RULES.market.at : 6);   // MARKETS (#161): trade is done at a trading stand
  // (a quest's parcel is carried, not traded)
  const opts = Object.keys(RULES.items).filter((id) => !RULES.items[id].quest).map((id) => `<option value="${id}">${esc(nameOf(id))}</option>`).join("");
  const tabLabel = { have: T("have", "You have"), build: T("pieceSize", "Piece size"), make: T("make", "Make"), trade: T("trade", "Trade") };
  const sec = (k) => `<section class="bagsec" data-sec="${k}"${k === bagTab ? "" : " hidden"}>`;
  // THE ORDER HOLDS WHILE THE BAG IS OPEN (playtest 2026-11-16, the agent's phone page): sorted afresh after every make,
  // a recipe that ran out of its makings dropped from the top group and the row below slid under the finger — making
  // cordage until the fibre ran out, the next tap on the same spot made planks of the player's wood. Sorted when the Bag
  // opens or the tab changes (makeOrder = null), kept through the redraws a make brings; a row just made impossible
  // stays where it was, its button disabled.
  if (!makeOrder) makeOrder = RULES.recipes.map((r, i) => [r, i]).sort(([a, i], [b, j]) => {
    const ok = (r) => canMake(r) && !r.makes.every(([id]) => inv.tools.includes(id) || inv.stations.includes(id));
    return (ok(b) ? 1 : 0) - (ok(a) ? 1 : 0) || i - j;                         // what can be made now first, else the book's order
  }).map(([r]) => r.id);
  const recipes = makeOrder.map((id) => RULES.recipes.find((r) => r.id === id)).filter(Boolean);
  $("palGrid").innerHTML = `
    <div class="tradeform bagtabs" role="tablist">${BAG_TABS.map((k) => `<button class="chip pl${k === bagTab ? " tool" : ""}" role="tab" data-bagtab="${k}" aria-selected="${k === bagTab}">${esc(tabLabel[k])}</button>`).join("")}</div>
    ${sec("have")}
    <h3>${esc(T("have", "You have"))}</h3>
    <div class="chips">${items.length ? items.map(([id, n]) => `<button class="chip${placeable(id) ? " pl" : ""}" data-pick="${id}">${n} × ${esc(nameOf(id))}</button>`).join("") : `<span class="dim">${esc(T("nothingYet", "Nothing yet — pick up the stones and sticks lying on the ground, and pull grass and leaves by hand."))}</span>`}
      ${inv.tools.map((t) => `<span class="chip tool">${esc(nameOf(t))}</span>`).join("")}${inv.stations.map((t) => `<span class="chip tool">${esc(nameOf(t))}</span>`).join("")}</div>
    ${items.some(([id]) => RULES.food && RULES.food.items[id]) ? `<div class="chips">${items.filter(([id]) => RULES.food.items[id]).map(([id]) =>
      `<button class="chip pl" data-eat="${id}">${esc(T("eatIt", "Eat {i}", { i: nameOf(id) }))}</button>`).join("")}</div>` : ""}
    ${performance.now() < fedUntil ? `<div class="dim">${esc(T("fedFor", "Well fed: work goes quicker for {m} more min.", { m: Math.ceil((fedUntil - performance.now()) / 60000) }))}</div>` : ""}
    <div class="dim">${esc(T("bagHint", "Click a block to put it on your hotbar. Tools work as soon as you have them."))}</div>
    ${(inv.quests || []).length ? `<h3>${esc(T("qLog", "Quests"))}</h3>` + inv.quests.map((q) => `<div class="rcp"><div>${esc(questText(q))}<div class="dim">${esc(q.ready ? T("qReadyAt", "Done — hand it in to {who}", { who: questEnd(q) }) : T("qFrom", "for {who}", { who: (RULES.quests.npcs.find((n) => n.id === (q.to || q.giver)) || {}).name || "" }))}</div></div>
      <button class="ghost" data-qdrop="${q.id}">${esc(T("qDrop", "Drop"))}</button></div>`).join("") : ""}
    </section>${sec("build")}
    <h3>${esc(T("pieceSize", "Piece size"))}</h3>
    <div class="tradeform">${PRESETS.map((x, i) => `<button class="chip pl" data-preset="${i}">${x.join("×")}</button>`).join("")}</div>
    <div class="tradeform"><span>W</span><input id="pzW" type="number" min="1" max="1600" value="${piece.w}"><span>D</span><input id="pzD" type="number" min="1" max="1600" value="${piece.d}">
      <span>H</span><input id="pzH" type="number" min="1" max="25600" value="${piece.h}"><span>cm · ${esc(T("snap", "snap"))}</span>
      <select id="pzS">${SNAPS.map((x) => `<option value="${x}"${x === piece.snap ? " selected" : ""}>${x} cm</option>`).join("")}</select></div>
    <!-- (a chosen part is the piece's shape: no box/slope/stairs chip is lit beside it — the "box" chip stayed lit with a part chosen, #187) -->
    <div class="tradeform">${[T("shapeBox", "box"), T("shapeSlope", "slope"), T("shapeStairs", "stairs")].map((n, i) =>
      `<button class="chip pl${!piece.part && (piece.shape || 0) === i ? " tool" : ""}" data-shape="${i}" aria-pressed="${!piece.part && (piece.shape || 0) === i}">${esc(n)}</button>`).join("")}
      <button class="chip pl" id="pzTurn">${esc(T("turnPiece", "Turn ↻"))}</button></div>
    <div class="tradeform"><span>${esc(T("parts", "Parts"))}</span>${Shapes.TYPES.map((n, i) => { const on = !!piece.part && Shapes.decode(piece.part).type === i;
      return `<button class="chip pl${on ? " tool" : ""}" data-part="${i}" aria-pressed="${on}">${esc(T("part." + n, n))}</button>`; }).join("")}
      ${piece.part && Shapes.VARIANTS[Shapes.decode(piece.part).type] > 1 ? `<span>${esc(partVarLabel(Shapes.decode(piece.part).type))}</span><select id="pzVar">${Array.from({ length: 10 }, (_, v) =>
        `<option value="${v}"${Shapes.decode(piece.part).v === v ? " selected" : ""}>${partVarValue(Shapes.decode(piece.part).type, v)}</option>`).join("")}</select>` : ""}</div>
    ${piece.part ? `<div class="dim">${esc(partHint(piece.part))}</div>` : ""}
    <div class="tradeform"><span>${esc(T("tiltYaw", "Yaw"))}</span><input id="pzYaw" type="number" step="0.1" min="-179.9" max="180" value="${(piece.tilt || [0, 0, 0])[0] / 10}">
      <span>${esc(T("tiltPitch", "Pitch"))}</span><input id="pzPitch" type="number" step="0.1" min="-179.9" max="180" value="${(piece.tilt || [0, 0, 0])[1] / 10}">
      <span>${esc(T("tiltRoll", "Roll"))}</span><input id="pzRoll" type="number" step="0.1" min="-179.9" max="180" value="${(piece.tilt || [0, 0, 0])[2] / 10}"><span>°</span>
      <button class="chip pl" id="pzSquare">${esc(T("tiltSquare", "Square"))}</button></div>
    <div class="tradeform"><button class="chip pl${piece.mirror ? " tool" : ""}" id="pzMirror" aria-pressed="${!!piece.mirror}">${esc(T("mirror", "Mirror"))}</button>
      <span class="dim">${esc(T("mirrorHint", "A piece placed against another gets a twin on that piece's far side, mirrored — wings, engines and cannons in pairs."))}</span></div>
    <div class="tradeform"><button class="chip pl${piece.attach ? " tool" : ""}" id="pzAttach" aria-pressed="${!!piece.attach}">${esc(T("attach", "Attach"))}</button>
      <span class="dim">${esc(T("attachHint", "A piece placed against another is centred on the face it touches — an engine on a wing's end, a cannon on its tip."))}</span></div>
    </section>${sec("make")}
    <h3>${esc(T("make", "Make"))}</h3>
    <div class="recipes">${recipes.map((r) => {
      const out = r.makes.map(([id, n]) => (RULES.items[id] ? n + " " : "") + nameOf(id)).join(", ");
      // COUNTS AS "n × name", TOOLS AS A "needs:" LIST (#179, playtest in Czech: "6 Klacky", "2 Kámen", "s Kamenná sekera" —
      // a number before a noun needs its plural form and "s" the instrumental, in each of 17 languages for ~190 names):
      // the Bag's own quantity notation and a label reads right in every language without declining a single name
      const need = r.uses.map(([id, n]) => `${n} × ${nameOf(id)}`).join(" + ") + ((r.with || []).length ? " · " + T("with", "needs: {w}", { w: r.with.map(nameOf).join(", ") }) : "")
        + waterHint(r);                                                       // (#206) where the water is, when it is lacking
      const own = r.makes.every(([id]) => inv.tools.includes(id) || inv.stations.includes(id));
      return `<div class="rcp${canMake(r) && !own ? "" : " off"}"><div><b>${esc(out)}</b><div class="dim">${esc(need)}</div></div>
        <button class="ghost" data-make="${r.id}" ${canMake(r) && !own ? "" : "disabled"}>${esc(own ? T("haveIt", "You have it") : T("makeGo", "Make"))}</button></div>`;
    }).join("")}</div>
    </section>${sec("trade")}
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
    </div></section>`;
  const g = $("palGrid"), req = (m) => net.send(Object.assign({ req: ++net.req }, m));
  g.querySelectorAll("[data-bagtab]").forEach((b) => { b.onclick = () => { bagTab = b.dataset.bagtab; makeOrder = null; try { localStorage.setItem("nado_land_bagtab", bagTab); } catch (e) {} renderBag(); }; });
  g.querySelectorAll("[data-make]").forEach((b) => { b.onclick = () => { req({ t: "craft", recipe: b.dataset.make }); net.made.set(net.req, b.dataset.make); }; });
  g.querySelectorAll("[data-eat]").forEach((b) => { b.onclick = () => req({ t: "eat", item: b.dataset.eat }); });
  g.querySelectorAll("[data-qdrop]").forEach((b) => { b.onclick = () => req({ t: "quest", op: "drop", id: b.dataset.qdrop }); });
  if ($("pxUnit")) { $("pxUnit").onchange = () => { priceUnit = $("pxUnit").value; showPrices(); }; showPrices(); }
  g.querySelectorAll("[data-pick]").forEach((b) => { b.onclick = () => { const id = b.dataset.pick; if (!placeable(id)) return; if (!hot.includes(id)) { if (hot.length < 9) hot.push(id); else hot[slot] = id; } slot = hot.indexOf(id); save(); hotbar(); }; });
  g.querySelectorAll("[data-accept]").forEach((b) => { b.onclick = () => req({ t: "accept", id: b.dataset.accept }); });
  g.querySelectorAll("[data-cancel]").forEach((b) => { b.onclick = () => req({ t: "cancel_offer", id: b.dataset.cancel }); });
  g.querySelectorAll("[data-preset]").forEach((b) => { b.onclick = () => { [piece.w, piece.d, piece.h] = PRESETS[Number(b.dataset.preset)]; pieceInfo(); renderBag(); }; });
  // SHAPE AND TURN ON A TOUCH SCREEN: box / slope / stairs and a quarter turn were keys only (G, T), so on a phone every
  // piece was a box facing one way — no roof, no stairs, no door turned (building the town pavilion by hand, 2026-11-08)
  g.querySelectorAll("[data-shape]").forEach((b) => { b.onclick = () => { piece.shape = Number(b.dataset.shape); piece.part = 0; pieceInfo(); renderBag(); }; });
  // PARTS (#175): a chip a part type — pressed again, back to a plain piece; the select beside it its variant (a taper,
  // a nose's droop, a ring's hole). A part keeps the size, the snap and the tilt set above: its box is the piece's.
  g.querySelectorAll("[data-part]").forEach((b) => { b.onclick = () => {
    const type = Number(b.dataset.part), was = piece.part ? Shapes.decode(piece.part) : null;
    piece.part = was && was.type === type ? 0 : Shapes.code(type, PART_DEFAULT[type] || 0);
    pieceInfo(); renderBag();
  }; });
  if ($("pzVar")) $("pzVar").onchange = () => { piece.part = Shapes.code(Shapes.decode(piece.part).type, Number($("pzVar").value)); pieceInfo(); renderBag(); };
  $("pzTurn").onclick = () => { turnPiece(); renderBag(); };
  const size = () => {
    const v = (id, max) => Math.max(1, Math.min(max, Math.round(Number($(id).value) || 1)));
    piece = { w: v("pzW", Wd.PLOT_CM), d: v("pzD", Wd.PLOT_CM), h: v("pzH", Wd.H_CM), snap: Number($("pzS").value), shape: piece.shape, rot: piece.rot, turned: piece.turned, part: piece.part, mirror: piece.mirror, attach: piece.attach,
      tilt: ["pzYaw", "pzPitch", "pzRoll"].map((id) => tenths($(id).value)) };
    pieceInfo();
  };
  for (const id of ["pzW", "pzD", "pzH", "pzS", "pzYaw", "pzPitch", "pzRoll"]) $(id).onchange = size;
  $("pzSquare").onclick = () => { piece.tilt = [0, 0, 0]; pieceInfo(); renderBag(); };
  $("pzMirror").onclick = () => { piece.mirror = !piece.mirror; pieceInfo(); renderBag(); };
  $("pzAttach").onclick = () => { piece.attach = !piece.attach; pieceInfo(); renderBag(); };
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
  // ATTACH (#187): with Attach on, a piece set against another is centred on the face it touches (land-snap attachTo),
  // after the edge snapping, which would otherwise pull it to an edge — the Kerbal attach node beside Mirror's symmetry
  if (piece.attach && a.box) box = attachTo(box, a.box.b, ax);
  box[0] = Math.max(0, Math.min(Wd.PLOT_CM - w, box[0])); box[1] = Math.max(0, Math.min(Wd.PLOT_CM - d, box[1]));
  // never inside the player
  const me = plotCm(P.face, P.u, P.v, P.h);
  const body = [me.x - HALF * Wd.CM, me.z - HALF * Wd.CM, me.y, 2 * HALF * Wd.CM, 2 * HALF * Wd.CM, TALL * Wd.CM];
  const rec = plotBoxes.get(c.plot);
  // TILT (#169): a box or a slope is turned about its centre by the piece's yaw, pitch and roll (never a unit part — a
  // seat, a door, a chest stand square — nor a flight of stairs, which is many pieces); it must still fit the plot
  // A PART (#175, land-shapes.js) is one piece with its shape byte; it tilts like a box
  const part = partFor(it);
  const tl = piece.tilt || [0, 0, 0], tilt = (part || (!(it && it.unit) && (piece.shape || 0) !== 2)) && tl.some((t) => t);
  const pieces = (part ? [[...box.slice(0, 7), part]] : shaped(box, it && it.unit ? 0 : piece.shape)).map((p) => (tilt ? [...p.slice(0, 7), p.length > 7 ? p[7] : 0, ...tl] : p));
  if (tilt || part) box = pieces[0];
  // INVARIANT (#175): what refuses a place is piecesClash, not boxesOverlap — a part shares its box with its neighbours
  // (a wing's box is mostly air, and parts are sunk into one another to close the seams); the world server agrees
  // (BoxIndex.overlaps). The body: a box may not take any of it; a part only where the part itself is (its outline).
  const inMe = (p) => (Wd.isPart(p) ? [0.1, 0.5, 0.9].some((f) => Wd.inPiece(p, me.x, me.z, me.y + f * TALL * Wd.CM)) : Wd.boxesOverlap(p, body));
  // (why: "me" when only the player's own body is in the way — Place says so: "No room" alone left a player looking
  // straight down at their feet with a red outline and no idea why, playtest 2026-11-15)
  const inBody = me.plot === c.plot && pieces.some(inMe), onPiece = !!rec && pieces.some((p) => rec.list.some((o) => Wd.piecesClash(p, o) || (o.length === p.length && o.every((x, i) => i === 6 || x === p[i]))));
  const clash = inBody || onPiece;
  const fits = (p) => Wd.boxOk(Wd.normalBox(p.slice(0, 6).concat([p[6] || 1], p.slice(7))));
  // SYMMETRY (#187): with Mirror on, a piece placed against another gets its twin through that piece's middle
  // (land-world.js mirrorPiece) — both or neither: a twin with no room refuses the pair ("twin"), as KSP does. A piece
  // that straddles the middle is its own twin (none is added).
  let twin = null, twinBad = false;
  if (piece.mirror && a.box && a.box.plot === c.plot) {
    const ts = pieces.map((p) => Wd.mirrorPiece(p, a.box.b)), same = ts.every((t, i) => Wd.normalBox(t).join() === Wd.normalBox(pieces[i]).join());
    if (!same) {
      twin = ts;
      twinBad = ts.some((t) => !fits(t) || (me.plot === c.plot && inMe(t)) || pieces.some((p) => Wd.piecesClash(t, p))
        || (!!rec && rec.list.some((o) => Wd.piecesClash(t, o) || (o.length === t.length && o.every((x, i) => i === 6 || x === t[i])))));
    }
  }
  const ok = !clash && pieces.every(fits) && box[2] >= 0 && box[2] + h <= Wd.H_CM;
  return { plot: c.plot, box, pieces: twin ? pieces.concat(twin) : pieces, twin: twin && twin[0], why: inBody && !onPiece ? "me" : ok && twinBad ? "twin" : "", ok: ok && !twinBad };
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
  // a plot you may not touch says so before the hold, not after it (the world server refuses afterwards all the same);
  // the deep (h < 0) is everyone's, as when placing (#129)
  if (c[2] >= 0 && !mayBuild(Wd.plotOf(P.face, c[0], c[1]))) return explainNoBuild(Wd.plotOf(P.face, c[0], c[1]));
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
  if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
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
/** SOWN, IT SAYS WHEN IT IS RIPE (playtest 2026-11-16, the agent's field east of town: tilling named the soil and said
 *  "sow wheat seed on it", and once sown nothing said how long — a new farmer cannot tell twenty minutes from a day):
 *  the world server's own rule (crop_due: crop_s × the soil's time, × moist with water near the field's layer). */
function cropMinutes(u, v, h) {
  const F = RULES.farming, soil = Wd.soilOf(P.face, u, v, colAt(P.face, u, v));
  const s = F.soil[soil] && F.soil[soil].time ? F.soil[soil].time : 1;
  return Math.max(1, Math.round(F.crop_s * s * (moistAt(u, v, h - 1) ? F.moist : 1) / 60));
}
function sownNotice(u, v, h) {
  notify(T("sown", "Sown: ripe in about {n} min — then break it to harvest.", { n: cropMinutes(u, v, h) }), 6000);
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
  if (!(a && a.box && ([B.door, B.chest, B.generator, B.well, B.bed, B.launchpad].includes(a.box.b[6]) || isMachine(a.box.b[6])))) { const mine = nearMyCraft(); if (mine) return board({ craft: mine }); }
  if (a && a.box && a.box.b[6] === B.chest) return openChest(a.box);           // Q uses what you aim at: a door or a chest
  if (a && a.box && a.box.b[6] === B.bed) {                                    // a bed: wake here after a death (#162)
    if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
    return net.send({ t: "bed", plot: a.box.plot, box: a.box.b, req: ++net.req });
  }
  if (a && a.box && a.box.b[6] === B.well) {                                   // a well: a bucketful, if you have a bucket (#155)
    if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
    if (!hasClass("bucket")) return notify(T("wellBucket", "A well is drawn with a bucket — make one at a workbench."));
    return net.send({ t: "well", plot: a.box.plot, box: a.box.b, req: ++net.req });
  }
  if (a && a.box && (a.box.b[6] === B.generator || isMachine(a.box.b[6]))) return openMachine(a.box);   // a machine
  if (a && a.box && a.box.b[6] === B.launchpad) return openPad(a.box);                                    // a launch pad (#173)
  if (!a || !a.box || a.box.b[6] !== B.door) return notify(T("noUse", "Aim at a door or a chest to use it."));
  if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
  net.send({ t: "door", plot: a.box.plot, box: a.box.b, req: ++net.req });
}
// ---- a machine (#148): Use on a smelter or an assembler shows what it makes and why it waits, and the recipes it can
// run — choosing one sets it going (scripts/land_server.py set_machine / factory_tick); on a generator, its power left
let machine = null;                              // { plot, box } of the machine panel open
function openMachine(bx) {
  if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
  machine = { plot: bx.plot, box: bx.b };
  net.send({ t: "machine", plot: bx.plot, box: bx.b, req: ++net.req });
  if (document.pointerLockElement) document.exitPointerLock();
  $("machTitle").textContent = nameOf(Object.keys(RULES.items).find((k) => RULES.items[k].places === bx.b[6]));
  $("machGrid").textContent = "…";
  showPanel("machPanel", true);
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
// ---- A LAUNCH PAD (#173, doc/land-navigation.md 1.5): the rocket built on it, its numbers as the world server computes them
// (land_server.py launch_numbers — the rocket equation from its own masses, less gravity loss, against the orbit's Δv), and
// the launch. Launched without the Δv for orbit, it is spent: the panel says so first and asks.
let pad = null;
function openPad(bx) {
  if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
  pad = { plot: bx.plot, box: bx.b };
  if (document.pointerLockElement) document.exitPointerLock();
  $("padGrid").textContent = "…";
  showPanel("padPanel", true);
  net.send({ t: "pad", plot: pad.plot, box: pad.box, req: ++net.req });
}
const PAD_WHY = { "no rocket engine on the pad": ["padWhyEngine", "No rocket engine on the pad."], "no propellant tank": ["padWhyTank", "No propellant tank."],
  "no satellite to carry": ["padWhySat", "No satellite to carry."], "no propellant in a chest beside the pad": ["padWhyProp", "No propellant in a chest beside the pad."],
  "too heavy to leave the pad: its thrust does not beat its weight": ["padWhyHeavy", "Too heavy to leave the pad: its thrust does not beat its weight."],
  "not enough Δv to reach orbit — more propellant, or less mass": ["padWhyDv", "Not enough Δv to reach orbit — more propellant, or less mass."] };
// the ascent's own verdicts (land-planet.js ascent), said in the player's language
const FLOWN_WHY = { "it ran out of propellant below the orbit": ["padRanOut", "it runs out of propellant below the orbit"],
  "not enough left to circularise": ["padNoCirc", "it reaches the orbit's height without enough left to stay up there"],
  "it fell back": ["padFellBack", "it falls back"], "it did not reach its highest point": ["padFellBack", "it falls back"] };
const flownWhy = (w) => (FLOWN_WHY[w] ? T(FLOWN_WHY[w][0], FLOWN_WHY[w][1]) : String(w));
const padWhy = (w) => (PAD_WHY[w] ? T(PAD_WHY[w][0], PAD_WHY[w][1]) : String(w));
function renderPad(m) {
  const g = $("padGrid");
  if (m.error) { g.textContent = String(m.error); return; }
  const n = m.num, row = (k, d, v) => `<div>${esc(T(k, d, v))}</div>`;
  g.innerHTML = row("padEngines", "Rocket engines: {n}", { n: n.engines }) + row("padTanks", "Propellant tanks: {n}", { n: n.tanks }) + row("padSats", "Satellites: {n}", { n: n.sats })
    + row("padLoad", "Propellant: {kg} kg from the chests beside it", { kg: Math.round(n.load * RULES.rocket.canister_kg) })
    + row("padMass", "Mass: {dry} kg empty, {wet} kg loaded", { dry: Math.round(n.dry_kg), wet: Math.round(n.wet_kg) })
    + row("padThrust", "Thrust {t} kN against its weight {w} kN", { t: n.thrust_kn, w: n.weight_kn })
    + row("padDv", "Δv {dv} m/s − {loss} m/s lost to gravity = {net} m/s; orbit needs {need} m/s", { dv: n.dv, loss: n.loss, net: n.net, need: n.need })
    + (n.flown ? row(n.flown.ok ? "padFlownOk" : "padFlownNo", n.flown.ok ? "Flown: it reaches orbit {h} km up, the air pressing hardest at {q} kPa, {kg} kg of propellant left" : "Flown: {why}, its path topping out {h} km up",
        { h: ((n.flown.apoR - Planet.RADIUS - Planet.SEA_LEVEL) / 1000).toFixed(1), q: (n.flown.maxQ / 1000).toFixed(1), kg: Math.round(n.flown.propLeftKg), why: flownWhy(n.flown.why) }) : "")
    + `<p><b>${esc(n.ok ? T("padOk", "It can reach orbit.") : padWhy(n.why))}</b></p>`
    + (n.engines && n.tanks && n.sats && n.load && n.thrust_kn > n.weight_kn ? `<button id="padGo">${esc(T("padGo", "Launch"))}</button>` : "");
  const go = $("padGo");
  if (go) go.onclick = async () => {
    if (!n.ok && !await uiConfirm({ title: T("padGo", "Launch"), body: T("padConfirm", "It does not have the Δv for orbit — launched, it is spent. Launch anyway?") })) return;
    net.send({ t: "launch", plot: pad.plot, box: pad.box, req: ++net.req });
  };
}
/** A machine block: every one land-recipes.json "machines" lists (the smelter, the assembler, and the electrolyser and the
 *  liquefier that make propellant, #173) — not a hard-coded pair. */
const isMachine = (b) => !!(RULES && RULES.machines[String(b)] && RULES.machines[String(b)].does);
function renderMachine(m) {
  const box = $("machGrid");
  if (m.error) notify(m.error, 5000);
  if (!m.cfg) { box.textContent = m.error || ""; return; }
  if (machine.box[6] === B.generator) {
    box.innerHTML = `<p>${esc(T("mGen", "{n} runs of power left. Put coal (20 runs) or charcoal (10) in a chest beside it.", { n: Math.floor(10 * (m.cfg.charge || 0)) / 10 }))}</p>`;
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
  if (!net.online || !net.me) return signInNotice(T("signInFirst", "Sign in first."));
  chest = { plot: bx.plot, box: bx.b, items: null };
  chestSend({}, {});
  if (document.pointerLockElement) document.exitPointerLock();
  showPanel("chestPanel", true);
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
  showPanel("wardPanel", open);
  if (!open) return;
  if (!net.online || !net.me) { showPanel("wardPanel", false); return signInNotice(T("signInFirst", "Sign in first.")); }
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
    + part(20, 124, 15, 15, c.gloves ?? c.skin, 3, "50%") + part(85, 124, 15, 15, c.gloves ?? c.skin, 3, "50%")   // hands, gloved or bare
    + (girl ? part(30, 112, 60, 30, c.top, 3, "4px", "clip-path:polygon(20% 0,80% 0,100% 100%,0 100%)") : "")
    + part(41, 128, 16, 58, c.legs, 2) + part(63, 128, 16, 58, c.legs, 2) + part(38, c.boots != null ? 168 : 182, 22, c.boots != null ? 24 : 10, c.boots ?? 0x3a2e2a, 3, "6px")
    + part(60, c.boots != null ? 168 : 182, 22, c.boots != null ? 24 : 10, c.boots ?? 0x3a2e2a, 3, "6px");   // shoes, or boots up the shin
  const sw = (list, key) => list.map((col, i) => `<button class="sw${look[key] === i ? " on" : ""}" data-${key}="${i}" style="background:${hex(col)}" aria-label="${i + 1}"></button>`).join("");
  // an empty body or legs slot is not bare: the figure wears its own plain clothes there (lookColours: `under` and the
  // grey legs) — the list said "nothing" beside a figure in a shirt and trousers (playtest 2026-11-15)
  const PLAIN_SLOTS = new Set(["body", "legs"]);
  const slots = WEAR_SLOTS.map((slot) => {
    const on = look.worn[slot], have = Object.entries(inv.items || {}).filter(([id, n]) => n > 0 && RULES.items[id] && RULES.items[id].wear === slot);
    return `<div class="wslot"><b>${esc(T("slot." + slot, slot))}</b> ${on ? `${esc(nameOf(on))} <button class="ghost" data-off="${slot}">${esc(T("wTakeOff", "Take off"))}</button>` : `<span class="dim">${esc(PLAIN_SLOTS.has(slot) ? T("wPlain", "your own plain clothes") : T("wNothing", "nothing"))}</span>`}
      ${have.map(([id]) => `<button data-wear="${esc(id)}" data-slot="${slot}">${esc(T("wWear", "Wear {i}", { i: nameOf(id) }))}</button>`).join(" ")}</div>`;
  }).join("");
  box.innerHTML = `<div class="ward"><div class="fig">${fig}</div><div>
    <h3>${esc(T("wSkin", "Skin"))}</h3><div class="sws">${sw(SKIN, "skin")}</div>
    <h3>${esc(T("wHair", "Hair"))}</h3><div class="sws">${sw(HAIR, "hair")}</div>
    <h3>${esc(T("wBody", "Body"))}</h3><div class="sws">${[T("wBoy", "Boy"), T("wGirl", "Girl")].map((n, i) => `<button class="chip pl${look.body === i ? " tool" : ""}" data-body="${i}" aria-pressed="${look.body === i}">${esc(n)}</button>`).join("")}</div>
    <h3>${esc(T("wFace", "Face"))}</h3><div class="sws">${Array.from({ length: FACES }, (_, i) => `<button class="sw face${look.face === i ? " on" : ""}" data-face="${i}" style="background:url(${faceUrl(i)}) center/cover" aria-label="${i + 1}"></button>`).join("")}</div>
    <h3>${esc(T("wClothes", "Clothes"))}</h3>${slots}</div></div>
    <p class="small dim">${esc(T("wHint", "Sew clothes from linen, wool or leather with a needle — make them in the bag (E). What you wear is what others see."))}</p>`;
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
  if (!mayBuild(bx.plot)) return explainNoBuild(bx.plot);                      // (#177: said before the hold, with the plot's state)
  const rule = RULES.breaking[bx.b[6]] || { hard: 1 };
  if (rule.needs && !hasClass(rule.needs)) return notify(T("needsTool", "That needs a {t}.", { t: nameOf(rule.needs) }));
  const speed = rule.class ? toolSpeed(rule.class) : 1;
  const unit = unitOf(bx.b[6]);
  // an engine (#175) is as many thrusters as its size: taking it down is that many units' work (the server: World.boxes)
  job = { box: bx, need: Math.max(0.05, (rule.hard * (unit ? Math.max(1, Wd.engineCount(bx.b)) * 1e6 : Wd.boxVolume(bx.b))) / 1e6 / speed * fedWork()), done: 0, mouse };
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
  if (!net.me) return signInNotice(T("signInBuild2", "Sign in to gather and build."));
  if (!hasClass("shovel")) return notify(T("levelNeedsShovel", "Flattening needs a shovel."));
  const a = aim();
  if (!a || !a.hit || a.box) return notify(T("levelAim", "Aim at the ground to flatten it."));
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
  // a PART (#175) has a front: a quarter turn swings it round (its yaw), where a box only swaps its width and depth
  if (partFor(RULES && hot[slot] && RULES.items[hot[slot]])) { const t = piece.tilt || [0, 0, 0]; piece.tilt = [tenths(t[0] / 10 + 90), t[1], t[2]]; return pieceInfo(true); }
  [piece.w, piece.d] = [piece.d, piece.w]; piece.turned = !piece.turned;
  if (piece.shape) piece.rot = ((piece.rot || 0) + 1) % 4;
  pieceInfo();
}
function pieceDims() {
  const it = RULES && hot[slot] && RULES.items[hot[slot]];
  if (it && it.unit && !partFor(it)) return piece.turned ? [it.unit[1], it.unit[0], it.unit[2]] : [it.unit[0], it.unit[1], it.unit[2]];
  return [piece.w, piece.d, piece.h];
}
// ---- PARTS (#175, land-shapes.js): the chosen part type and variant ride in piece.part (a shape byte) -------------------
// what a type starts as when its chip is pressed: a straight tube and body, a hull and a wing narrowing as the X-wing's
// do, a level nose, a ring with a hole of 0.8 (design choices: a start, the select changes it)
const PART_DEFAULT = { [Shapes.TUBE]: 9, [Shapes.BODY]: 9, [Shapes.HULL]: 3, [Shapes.WING]: 5, [Shapes.NOSE]: 0, [Shapes.RING]: 6 };
/** The part the held item would be placed as (a shape byte), or 0 for a plain piece. A unit item — a seat, a door, a
 *  chest — is never a part; an ENGINE is made of thrusters and of nothing else (land-world.js boxOk, engineCount), so the
 *  thruster, itself a unit item, is the one that takes a part's shape, and only that shape. */
function partFor(it) {
  const p = piece.part ? Shapes.decode(piece.part) : null;
  if (!p || !it) return 0;
  if (p.type === Shapes.ENGINE) return it.places === B.thruster ? piece.part : 0;
  return it.unit ? 0 : piece.part;
}
const partName = (s) => { const p = Shapes.decode(s); return T("part." + Shapes.TYPES[p.type], Shapes.TYPES[p.type]) + (Shapes.VARIANTS[p.type] > 1 ? " " + partVarValue(p.type, p.v) : ""); };
const partVarLabel = (type) => (type === Shapes.NOSE ? T("partDroop", "droop") : type === Shapes.RING ? T("partHole", "hole") : T("partTaper", "taper"));
const partVarValue = (type, v) => (type === Shapes.NOSE ? String(v) : type === Shapes.RING ? (50 + 5 * v) + " %" : ((v + 1) / 10).toFixed(1));
/** What the chosen part takes of the size set above, in words: an engine in thrusters, anything else in blocks of the
 *  material held (a hollow one a tenth of its solid — land-shapes.js SHELL). */
function partHint(s) {
  const b = [0, 0, 0, piece.w, piece.d, piece.h, Shapes.decode(s).type === Shapes.ENGINE ? B.thruster : B.steelplate, s];
  if (Wd.isEngine(b)) return T("partEngine", "An engine is made of thrusters: at this size it takes {n} and pushes {kn} kN. Hold a thruster to place it.", { n: Wd.engineCount(b), kn: Wd.engineCount(b) * (RULES.flight ? RULES.flight.thrust_kn : 0) });
  return T("partTakes", "At this size it takes {v} of a block of the material you hold. Parts may be sunk into one another.", { v: (Wd.boxVolume(b) / 1e6).toFixed(3) });
}
function act(place, mouse) {
  // signed out, a tap says so whatever it points at: it used to say nothing when the view held no target (sky, a gap in
  // a crown) — a visitor tapping in a forest got silence (the live two-player walk, 2026-11-07)
  if (!net.me) return signInNotice(T("signInBuild2", "Sign in to gather and build."));
  { const n = npcAimed(); if (n) return openNpc(n); }                           // a click on a person talks, as Q does (#177)
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
      if (RULES.items[id].places === B.wheatyoung) sownNotice(cu, cv, ch);
      return;
    }
    const pl = placement(a);
    if (!pl) return;
    if (!mayBuild(pl.plot)) return explainNoBuild(pl.plot);
    // an ENGINE (#175) is made of thrusters and nothing else: say so instead of placing a box of whatever is held — and
    // BEFORE "no room": an engine of another material is no piece at all (boxOk), so the room was never the reason
    if (piece.part && Shapes.decode(piece.part).type === Shapes.ENGINE && RULES.items[id].places !== B.thruster) return notify(T("engineNeeds", "An engine is made of thrusters — hold a thruster to place one."));
    if (!pl.ok) return notify(pl.why === "me" ? T("noRoomMe", "That piece would be where you stand — step back, or aim farther off.") : pl.why === "twin" ? T("noRoomTwin", "No room for its mirrored twin on the far side — or turn Mirror off in the bag.") : T("noRoom", "No room for that piece there."));
    const add = pl.pieces.map((b) => { const x = b.slice(); x[6] = RULES.items[id].places; return x; });
    const vol = add.reduce((a, b) => a + Wd.boxVolume(b), 0);
    // a unit item is paid whole: one a piece — an engine as many thrusters as its size comes to (land-world.js engineCount)
    const units = add.reduce((a, b) => a + (Wd.isEngine(b) ? Wd.engineCount(b) : 1), 0);
    if (RULES.items[id].unit ? !((inv.items[id] || 0) >= units) : haveCm3(id) < vol) return notify(T("notEnough", "Not enough {i} for a piece that size.", { i: nameOf(id) }));
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
const SET_DEF = { fov: 72, sens: 1, invert: 0, grass: 1, shadows: 2, effects: 1, borders: 1, stats: 0, res: 100, view: 6, fps: 0, auto: 1, clouds: 1, leaves: 1, sound: 1, volume: 100 };
const SET_RANGE = { fov: [50, 110], sens: [0.2, 4], invert: [0, 1], sound: [0, 1], volume: [0, 100], grass: [0, 1], shadows: [0, 3], effects: [0, 1], borders: [0, 1], stats: [0, 1],
  res: [50, 100], view: [2, 10], fps: [0, 60], auto: [0, 1], clouds: [0, 1], leaves: [0, 1] };
// GRAPHICS (#166, operator 2026-11-10: "make graphical settings more configurable (resolution, shadows, etc)"): res is the
// render resolution in % of the screen's pixels, shadows off / low / medium / high (the sun's shadow map size and reach),
// view the chunks drawn around you, fps a frame-rate cap (0: none). A phone starts on what it can carry — no shadows,
// grass or effects, 4 chunks — and any of them can be turned on in the panel (they used to be refused on a touch screen).
const SET_PHONE = { shadows: 0, grass: 0, effects: 0, view: 4 };
// by SET.shadows: the map a cascade gets, how many cascades, and how far the last one reaches. SHADOWS REACH THE MEADOW
// (#183 step 4, the concept picture's long tree shadows across the far ground): one box of 64 m round the player gave the
// meadow no shadow at all past it; the sun's shadow is CASCADED now (three's CSMShadowNode, vendored: the camera's frustum
// split 'practically' into cascades, each with its own map, the near one at a centimetre, the far one at the far trees).
const SHADOW_Q = [null, { map: 1024, cascades: 2, far: 90 }, { map: 2048, cascades: 3, far: 200 }, { map: 4096, cascades: 3, far: 320 }];
let csm = null;                                              // the sun's cascades (shadowQuality)
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
  if (k === "fov" && camera) { camera.fov = SET.fov; camera.updateProjectionMatrix(); if (csm) csm.updateFrustums(); }
  if (k === "grass") { grassShade.value = SET.grass ? 1 : 0; for (const key of chunks.keys()) request(key); }   // re-mesh with or without the blades
  if (!renderer) return;                                                       // before start(): start() applies them all
  if (k === "res") { renderer.setPixelRatio(basePR() * SET.res / 100); if (stars) stars.material.size = starPx(1.6); if (satPts) satPts.material.size = starPx(3.2); }
  if (k === "shadows") shadowQuality();
  if (k === "view") { viewDist = SET.view; updateChunks(); buildFar(); updateForest(); }   // (the far trees' reach follows the preset, #150)
  if (k === "effects") pipeline = buildPipeline();                             // the post-processing is built again, or dropped
}
/** The sun's shadow for SET.shadows: the cascades' map size, count and reach. The cascades clone the sun's shadow when
 *  they are built, so a new preset builds them again and has every material take the new node (needsUpdate). Off casts
 *  nothing (frame: sun.castShadow). */
function shadowQuality() {
  const q = SHADOW_Q[SET.shadows];
  if (!q || !sun) return;
  sun.shadow.mapSize.set(q.map, q.map);
  if (sun.shadow.map) { sun.shadow.map.dispose(); sun.shadow.map = null; }
  if (csm) csm.dispose();
  csm = new CSMShadowNode(sun, { cascades: q.cascades, maxFar: q.far, mode: "practical", lightMargin: 200 });
  csm.fade = true;                                           // a cascade's edge blends into the next, not a seam across the ground
  sun.shadow.shadowNode = csm;
  if (scene) scene.traverse((o) => { if (o.material) o.material.needsUpdate = true; });
}
/** The sun's cast shadows fade under a cloud: the shadow's strength is what the layer lets through over the player
 *  (cloudLitNow), on the sun's own shadow and on every cascade's clone of it. */
function shadowStrength(v) {
  sun.shadow.intensity = v;
  if (csm) for (const l of csm.lights) l.shadow.intensity = v;
}
// ---- the graphics panel (#166): presets and each setting, applied at once and kept in this browser ------------------------
const settingsOpen = () => !$("setPanel").classList.contains("hidden");
function settings(open) {
  showPanel("setPanel", open);
  if (!open) return;
  if (document.pointerLockElement) document.exitPointerLock();
  renderSettings();
}
function setSetting(k, v) {
  if (!(k in SET_DEF) || !(Number.isFinite(v) && v >= SET_RANGE[k][0] && v <= SET_RANGE[k][1]) || SET[k] === v) return;
  SET[k] = v; saveSet(); applySetting(k);
}
// NO SHADER WARM-UP (2026-11-25, tried and dropped): the renderer's compileAsync builds a scene with cascaded shadows
// outside a frame, where CSMShadowNode has no camera yet — it threw "Uncaught" in _getBreaks on every page with shadows on
// (tests/test_the_hud_stands_under_the_header_on_a_narrow_phone.mjs). The benchmark's frames are labelled instead (perfSample).
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
    + sel("clouds", T("gClouds", "Clouds"), onOff)
    + sel("leaves", T("gLeaves", "Leaves lit through"), onOff)
    + sel("effects", T("gEffects", "Effects (bloom, ambient light)"), onOff)
    + sel("auto", T("gAuto", "Adjust automatically (presets only)"), onOff)
    + sel("fov", T("gFov", "Field of view"), [60, 66, 72, 80, 90, 100, 110].concat([SET.fov]).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b).map((v) => [v, v + "°"]))
    // the controls and the HUD (#179: sensitivity, invert-Y, plot borders and the stats line existed as settings and
    // were reachable only through /set) — a gear on the HUD opens this panel (land.html #setBtn)
    + sel("sens", T("gSens", "Mouse sensitivity"), [0.5, 0.75, 1, 1.5, 2].concat([SET.sens]).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b).map((v) => [v, v + "×"]))
    + sel("invert", T("gInvert", "Invert look (up is down)"), onOff)
    + sel("borders", T("gBorders", "Plot borders on the ground"), onOff)
    + sel("stats", T("gStats", "Stats line (frame rate, triangles)"), onOff)
    + sel("sound", T("gSound", "Sound (steps, a hit, a charge, a pickup)"), onOff)
    + sel("volume", T("gVolume", "Volume"), [10, 25, 50, 75, 100].concat([SET.volume ?? 100]).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b).map((v) => [v, v + " %"]))
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
  trace("gov", { from: LADDER[at], to: LADDER[to], gap: Math.round(gap) });   // (each step, so a trace shows the governor's walk)
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
    trace("bench", { preset: chosen, fps, tried: Object.keys(measured) });   // (so a trace says the benchmark ran, and what it chose)
    notify(T("benchDone", "Graphics: {p} — {f} fps. Change it in Settings.", { p: presetName(chosen), f: fps }), 6000);
  } finally {
    SET.fps = cap; saveSet(); benching = false;
    if (settingsOpen()) renderSettings();
  }
}
/** What draws a mesh, for /tris and /draws: its material's name in the page, the far boxes, a person (a figure the page
 *  marks), else "other: <material class>". */
function drawKind() {
  const names = [[matGround, "ground, stones, far land"], [matTrees, "trees (cells)"], [matBark, "bark"], [matLeaves, "foliage"], [matSolid, "blocks"], [matClear, "glass blocks"],
    [matPieces, "pieces"], [matGlassy, "glassy pieces"], [matWater, "water"], [matGrass, "grass"], [matFlower, "flowers"], [matForest, "far trees"], [matFlame, "flames"], [matSmoke, "smoke"]];
  // (mat: the material a draw uses — a mesh with a list of materials makes one draw a group, each named by its own)
  return (o, mat = o.material) => {
    let k = (names.find(([m]) => m && m === mat) || [])[1];
    if (!k && o === farBoxMesh) k = "far boxes";
    // A FIGURE IS PEOPLE (the blocky figures of 2026-11-14 carry userData.person; the realistic bodies' human.meshes went
    // with them, and /tris lost its people line to "other")
    if (!k) { let q = o.parent; while (q) { if (q.userData && q.userData.person) { k = "people"; break; } q = q.parent; } }
    return k || "other: " + (mat && mat.constructor ? mat.constructor.name : "?") + (mat && mat.name ? " " + mat.name : "");
  };
}
const CMDS = {
  help: () => [["/help", T("cHelp", "this list")], ["/pos", T("cPos", "where you are")], ["/tp spawn | /tp bed", T("cTpTo", "go to the landing, or to your bed")],
    ["/aim", T("cAim", "what you aim at, and where a block would go")], ["1–9", T("cKeys", "aimed at a thruster, an engine or a cannon: its key; at the controls: fire the gadgets bound to that key")], ["/prof", T("cProf", "the profiler: where each frame's time goes")], ["/name …", T("cName", "your name, shown in chat and over you; /name alone clears it")], ["/trace", T("cTrace", "the last events: boarding, leaving, every teleport, hurt, errors")], ["/dock", T("cDock", "set your landed craft down as pieces")], ["/planet", T("cPlanet", "the planet: its size, gravity, mass, orbits and air")], ["/map", T("cMap", "your map: the land you have surveyed (also M)")], ["/crafts", T("cCrafts", "where your crafts are: distance, bearing, height")], ["/handover <player>", T("cGive", "give your craft to a player — they take its controls")], ["/fly", T("cFly", "fly or walk")], ["/settings", T("cSettings", "your settings")], ["/bench", T("cBench", "measure this device and pick its graphics")], ["/tilt <yaw> <pitch> <roll>", T("cTilt", "turn the piece in hand, in degrees")], ["/set <name> <value>", T("cSet", "change one (e.g. /set fov 90)")],
    ["/clear", T("cClear", "clear this log")], ["…", T("cChat", "anything else is chat to the players around you")]].forEach(([c, d]) => conLine(c + " — " + d)),
  pos: () => conLine(`${T("cFace", "face")} ${P.face} · u ${Math.floor(P.u)} · v ${Math.floor(P.v)} · h ${P.h.toFixed(1)} · ${T("cPlot", "plot")} ${Wd.plotOf(P.face, Math.floor(P.u), Math.floor(P.v))}`),
  // /tp (#167): to the landing or to your own bed — nowhere else; going far is walking, flying, or a craft. Signed in, the
  // world server moves you (and refuses a page that moves itself faster than anyone can go); a visitor goes to the landing
  tp: (a) => {
    const to = (a[0] || "").toLowerCase();
    if (to !== "spawn" && to !== "bed") return conLine(T("cTpUse", "Usage: /tp spawn (the landing), or /tp bed (your bed)."), "err");
    if (net.online && net.me) return net.send({ t: "tp", to });
    if (to === "bed") return conLine(T("signInFirst", "Sign in first."), "err");
    pendingPlace = null;   // (a place set here wins over a saved place still waiting for its plot's edits — pendingPlace — #180 item 3)
    const sp = townSpawn(); P.face = sp[0]; P.u = sp[1]; P.v = sp[2]; P.yaw = sp[3]; P.h = groundAt(P.face, P.u, P.v); P.vu = P.vv = P.vh = 0;
    save(); conLine(T("tpSpawn", "At the landing."));
  },
  // /aim: what the crosshair is on and the cell a block goes into — what the outline shows, in words a report can quote
  // ("it is impossible to judge what will happen upon placing a block", operator 2026-11-08)
  aim: () => {
    const a = aim();
    if (!a) return conLine(T("cAimNone", "Nothing within reach."));
    const named = blockLabel;
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
  // /planet: THE PLANET as a physical body (land-planet.js) — its size, gravity, mass, density, orbits and air
  planet: () => planetPanel(true),
  // /map: THE SURVEYED MAP (#173) — also M, and the Map button a carried map puts under the HUD
  map: () => mapPanel(true),
  // /crafts: WHERE YOUR CRAFTS ARE (#171, operator: "i left the x somewhere") — each one's distance, bearing and height
  crafts: () => net.send({ t: "mycrafts", req: ++net.req }),
  // /name <name>: YOUR NAME (#179) — shown in chat and over you; /name alone clears it. 3–16 letters, digits, space, - _
  name: (a) => {
    if (!net.me) return conLine(T("bagSignIn", "Sign in to gather, make things and trade."));
    net.send({ t: "name", name: (a || []).join(" ").trim(), req: ++net.req });
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
  trace: () => {
    const last = TRACE.ring.slice(-25);
    if (!last.length) return conLine(T("cTraceNone", "No events yet."));
    for (const e of last) conLine(new Date(e.t).toISOString().slice(11, 19) + " " + e.k + " " + JSON.stringify({ ...e, t: undefined, k: undefined }).slice(0, 160));
  },
  // /tris (#150): what the frame's triangles are — by what draws them — so a heavy landing says what is heavy (the stats
  // line gives one number: 557k–638k at the landing on Low, playtest 2026-11-11, and nothing to cut from it)
  tris: () => {
    if (!scene) return;
    const kindOf = drawKind();
    const by = new Map(), add = (k, n) => by.set(k, (by.get(k) || 0) + n);
    scene.traverse((o) => {
      if (!o.isMesh && !o.isPoints && !o.isLine) return;
      let p = o, shown = true; while (p) { if (!p.visible) { shown = false; break; } p = p.parent; }
      if (!shown || !o.geometry) return;
      const g = o.geometry, per = (g.index ? g.index.count : g.attributes.position ? g.attributes.position.count : 0) / 3;
      const inst = g.instanceCount !== undefined && g.instanceCount !== Infinity ? g.instanceCount : o.count !== undefined ? o.count : 1;
      const n = Math.round(per * inst);
      if (!n) return;
      add(kindOf(o), n);
    });
    const rows = [...by.entries()].sort((a, b) => b[1] - a[1]), total = rows.reduce((t, [, n]) => t + n, 0);
    conLine(T("cTris", "Triangles this frame: {n}k — by what draws them:", { n: Math.round(total / 1000) }));
    for (const [k, n] of rows) conLine(`  ${Math.round(n / 1000)}k  ${k}`);
  },
  // /draws (#139: "433 draw calls a frame on a phone" and nothing said which): the draw calls of the next frame by what
  // makes them, the main view's apart from the shadows' — counted where three draws each one (renderObject calls the
  // object's onBeforeRender for every pass, the shadow cascades included), so culled meshes do not count and a mesh drawn
  // into four cascades counts five times, as the GPU sees it
  draws: () => {
    if (!scene) return;
    const kindOf = drawKind(), by = new Map(), hooked = [];
    // ONE FRAME (three's info.frame is the animation frame's id): the hooks stay on across two frames, and counting both
    // read twice the stats line's calls (812 against 365 on a desktop at the landing) — only the first frame seen counts
    let main = 0, shadow = 0, frame = null;
    scene.traverse((o) => {
      if (!o.isMesh && !o.isPoints && !o.isLine) return;
      const was = o.onBeforeRender; hooked.push([o, was]);
      o.onBeforeRender = function (r, sc, cam, ...rest) {
        if (frame === null) frame = r.info.frame;
        if (r.info.frame === frame) {
          const k = kindOf(o, rest[1] || o.material), e = by.get(k) || [0, 0], sh = cam !== camera;   // rest: geometry, material, group
          e[sh ? 1 : 0]++; by.set(k, e); if (sh) shadow++; else main++;
        }
        return was.call(this, r, sc, cam, ...rest);
      };
    });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      for (const [o, was] of hooked) o.onBeforeRender = was;
      const rows = [...by.entries()].sort((a, b) => (b[1][0] + b[1][1]) - (a[1][0] + a[1][1]));
      conLine(T("cDraws", "Draw calls this frame: {n} — {m} in view, {s} for shadows — by what makes them:", { n: main + shadow, m: main, s: shadow }));
      for (const [k, [m, sh]] of rows) conLine(`  ${m + sh}  ${k}${sh ? ` (${sh} shadow)` : ""}`);
    }));
  },
  // /lod (#150): the loaded chunks by their level of detail, and the bark and foliage triangles each level carries —
  // the question "did the near chunks take level 1, and what do their trees cost" answered on the page itself (the
  // chunkLod rule of fe10affa measured no change at the landing on Low, and nothing could say why)
  lod: () => {
    const by = new Map();
    for (const c of chunks.values()) {
      const l = c.lod ?? -1, e = by.get(l) || { chunks: 0, bark: 0, leaves: 0 };
      e.chunks++;
      for (const m of c.meshes || []) {
        const g = m.geometry, n = g && g.index ? g.index.count / 3 : 0;
        if (m.material === matBark) e.bark += n; else if (m.material === matLeaves) e.leaves += n;
      }
      by.set(l, e);
    }
    conLine(T("cLod", "Chunks by level of detail (0 near, 1 middle, 2 far) — bark and foliage triangles each:"));
    for (const [l, e] of [...by.entries()].sort((a, b) => a[0] - b[0])) conLine(`  lod ${l}: ${e.chunks} chunks · ${Math.round(e.bark / 1000)}k bark · ${Math.round(e.leaves / 1000)}k foliage`);
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
// SOUND (#113): synthesised cues (land-sound.js) — the context opens on the first click or key, here and in the touch
// wiring, since a browser refuses audio before a gesture
const sound = new Sound(() => SET.sound ? (SET.volume ?? 100) / 100 : 0);   // on/off times the volume (#113); an older saved setting has no volume: full
function lockPointer() {
  sound.enable();
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
    if (flying && flying.aero && flying.aero.winged) {       // the stick (#191): right rolls right, back (mouse down) pulls up
      stick.x += e.movementX * SET.sens / STICK_PX; stick.y += e.movementY * SET.sens * (SET.invert ? -1 : 1) / STICK_PX;
      return;
    }
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
    if (/^Digit[0-9]$/.test(e.code)) {
      const n = Number(e.code.slice(5));
      if (flying) { /* GADGET KEYS: held digits fire the gadgets bound to them (flyStep heldSlots) */ }
      else if (bindAimed(n)) { /* aimed at a gadget: its key is set */ }
      else if (n >= 1 && n <= hot.length) { slot = n - 1; hotbar(); }
    }
    if (e.code === "KeyR") { const i = PRESETS.findIndex((x) => x[0] === piece.w && x[1] === piece.d && x[2] === piece.h); [piece.w, piece.d, piece.h] = PRESETS[(i + 1) % PRESETS.length]; pieceInfo(true); }
    if (e.code === "KeyT") turnPiece();
    if (e.code === "KeyQ" && !e.repeat) useDoor();   // once a press: a held Q's key repeat boarded and left a craft eight times in a second (his trace, 2026-11-14)
    if (e.code === "Backquote") profToggle();                     // the profiler (True Wind's key)
    if (e.code === "KeyX") ignite();
    if (e.code === "KeyV") wardrobe($("wardPanel").classList.contains("hidden"));
    if (e.code === "KeyL") startLevel();
    if (e.code === "KeyG") { piece.shape = ((piece.shape || 0) + 1) % 3; piece.part = 0; pieceInfo(true); }   // …and back from a part (#175) to a plain piece
    if (e.code === "BracketLeft" || e.code === "BracketRight") { const i = SNAPS.indexOf(piece.snap); piece.snap = SNAPS[Math.max(0, Math.min(SNAPS.length - 1, (i < 0 ? 2 : i) + (e.code === "BracketRight" ? 1 : -1)))]; pieceInfo(); }
    if (e.code === "KeyF") { P.fly = !P.fly; P.vh = 0; notify(P.fly ? T("flyOn", "Flying — Space up, C down, Shift fast") : T("flyOff", "Walking"), 1600); }
    if (e.code === "KeyE") palette($("palette").classList.contains("hidden"));
    if (e.code === "KeyM") mapPanel($("mapPanel").classList.contains("hidden"));
    if (e.code === "Escape" && anyPanelOpen()) { closePanels(); if (!touch && $("deathCard").classList.contains("hidden")) lockPointer(); }   // (a panel open: close them all, mouse back; none: the browser frees the mouse)
    if (e.code === "Space" && locked) e.preventDefault();
  });
  document.addEventListener("keyup", (e) => keys.delete(e.code));
  window.addEventListener("blur", () => keys.clear());
  // touch: the left half steers, the right half looks; buttons jump/fly/break/place
  if ("ontouchstart" in window || navigator.maxTouchPoints > 0) {
    touch = { mx: 0, my: 0, up: false, down: false, run: false };
    document.body.classList.add("touch");
    document.addEventListener("touchstart", () => sound.enable(), { once: true, passive: true });
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
        if (t.identifier === lookId) {
          if (flying && flying.aero && flying.aero.winged) { stick.x += (t.clientX - lx) * 2.5 / STICK_PX; stick.y += (t.clientY - ly) * 2.5 / STICK_PX; }   // the stick (#191)
          else { P.yaw += (t.clientX - lx) * 0.006; P.pitch = Math.max(-1.55, Math.min(1.55, P.pitch - (t.clientY - ly) * 0.006)); }
          lx = t.clientX; ly = t.clientY;
        }
      }
      e.preventDefault();
    }, { passive: false });
    canvas.addEventListener("touchend", (e) => {
      for (const t of e.changedTouches) { if (t.identifier === stickId) { stickId = null; touch.mx = touch.my = 0; } if (t.identifier === lookId) lookId = null; }
    });
    const hold = (id, k) => { const el = $(id); el.addEventListener("touchstart", (e) => { touch[k] = true; e.preventDefault(); }, { passive: false }); el.addEventListener("touchend", () => { touch[k] = false; }); };
    hold("tJump", "up"); hold("tDown", "down");
    // said, as F says it on a keyboard, with the phone's own buttons (playtest 2026-11-16: the phone's Fly toggled free
    // flight in silence, the button the same either way — nothing told the player they were flying); its look follows
    // P.fly every frame (frame), whoever changed it
    fitTouchLabels(); setTimeout(fitTouchLabels, 1500);   // once the labels are in the page's language (i18n.js may run after)
    // More (land.html "FEWER BUTTONS"): opens and folds the left cluster — chat, run, turn, fire, wear, flatten
    $("tMore").onclick = () => { const on = document.body.classList.toggle("more"); $("tMore").classList.toggle("on", on); };
    $("tFly").onclick = () => { P.fly = !P.fly; P.vh = 0; notify(P.fly ? T("flyOnTouch", "Flying — Jump to rise, Down to sink; Fly again to walk") : T("flyOff", "Walking"), 2400); };
    $("tBreak").onclick = () => act(false, false);
    $("tPlace").onclick = () => act(true);
    $("tPal").onclick = () => palette(true);
    // the left cluster (#139): the console (chat and every / command), run while held, the piece turned, fire, the wardrobe
    $("tChat").onclick = () => conShow(!conOpen);
    hold("tRun", "run");
    $("tTurn").onclick = () => turnPiece();
    $("tFire").onclick = () => ignite();
    $("tWard").onclick = () => wardrobe(true);
    $("tLevel").onclick = () => startLevel();              // L on a keyboard (#139: a phone had no way but /level)
    $("tUse").onclick = () => useDoor();                // Q on a keyboard: a door, a chest, a pilot seat; leave a craft
  }
  $("palClose").onclick = () => palette(false);
  $("chestClose").onclick = () => showPanel("chestPanel", false);
  $("machClose").onclick = () => showPanel("machPanel", false);
  $("deathGo").onclick = () => wakeUp();                // the death card (#162)
  $("npcClose").onclick = () => showPanel("npcPanel", false);
  $("wardClose").onclick = () => wardrobe(false);
  $("setOpen").onclick = () => { palette(false); settings(true); };
  $("setClose").onclick = () => settings(false);
  $("mapClose").onclick = () => mapPanel(false);
  $("mapPlanet").onclick = () => { mapPanel(false); planetPanel(true); };
  $("planetClose").onclick = () => planetPanel(false);
  $("padClose").onclick = () => showPanel("padPanel", false);
  $("mapBtn").onclick = () => mapPanel(true);
  $("setBtn").onclick = () => settings(true);           // the gear on the HUD (#179): settings were inside the Bag only
  $("wardOpen").onclick = () => { palette(false); wardrobe(true); };
}

// ---- frame -----------------------------------------------------------------------------------------------------
// ---- the ground's material: six real textures (static/vendor/textures, CC0 Poly Haven) mixed by the weights the mesher
// gives every ground vertex. Each is sampled at two scales and the two mixed, which hides the repetition a single tiling
// shows from any height; rock is projected from three sides by the ground's normal, so a cliff is not a smear.
const GROUND = ["grass", "dirt", "rock", "sand", "snow", "gravel", "forest"];   // ("forest": a wood's floor, 2026-11-25)
const UNDER_BLADES = 0.55;                    // the meadow ground's light under the blades (groundMaterial): a design choice, by the reference's dark-to-the-ground grass
const grassShade = TSL.uniform(1);            // 1 with the blades drawn, 0 without (applySetting "grass", start)
const GROUND_ROUGH = [0.96, 0.95, 0.85, 0.9, 0.55, 0.9, 0.95];
function loadTex(name) {
  // userData.ready: settles when the image is in (or failed) — a material must not sample a texture before then: three
  // binds an empty one meanwhile, and an empty NORMAL map turns every surface away from every light (pieces drew pure
  // black until their scans arrived, seconds on a slow link, playtest 2026-11-15)
  let done; const ready = new Promise((r) => { done = r; });
  // A PHONE GETS THE GROUND AT 512 px (#139/#150, a fresh phone load measured 7 MB; the seven ground maps a page loads
  // were 1.48 MB of it, 0.37 MB at 512 px): drawn at 1.25× it shows no more of them than 512 px holds — tools/land_textures.py PHONE_PX makes the set
  const file = PHONE && GROUND.includes(name.replace(/_(col|nor)$/, "")) ? name + "_512" : name;
  const t = new THREE.TextureLoader().load(`/static/vendor/textures/${file}.jpg`, () => done(true), undefined, () => done(false));
  t.userData.ready = ready;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}
function groundMaterial() {
  const uvw = TSL.attribute("uvw", "vec3"), gn = TSL.attribute("gn", "vec3").abs();
  const w1 = TSL.attribute("w1", "vec4"), w2 = TSL.attribute("w2", "vec3");
  const near = uvw.xy.div(3.2), far = uvw.xy.div(23.0);                // metres per repeat, close up and from afar
  const two = (t) => TSL.mix(TSL.texture(t, near).rgb, TSL.texture(t, far).rgb, 0.35);
  const tex = GROUND.map((k) => loadTex(k + "_col"));
  // rock: three planar projections blended by the normal's weight on each axis
  const tw = gn.pow(4), tws = tw.x.add(tw.y).add(tw.z);
  const rock = TSL.texture(tex[2], TSL.vec2(uvw.y, uvw.z).div(4.5)).rgb.mul(tw.x)
    .add(TSL.texture(tex[2], TSL.vec2(uvw.x, uvw.z).div(4.5)).rgb.mul(tw.y))
    .add(TSL.texture(tex[2], near.mul(3.2 / 4.5)).rgb.mul(tw.z)).div(tws);
  // GRASS AND EARTH ON A SLOPE (#181 item 5, playtest 2026-11-11: "steep slopes smear the ground texture — stretched
  // along the slope"): the two layers a hillside is made of take the rock's three projections too, the side ones
  // weighted in as the face turns from the sky (the flat meadow still costs its two samples' worth: the side weights
  // are ~0 there); sand, snow and clay stay mapped from above
  const tri = (t) => TSL.mix(TSL.texture(t, near).rgb.mul(tw.z).add(TSL.texture(t, TSL.vec2(uvw.y, uvw.z).div(3.2)).rgb.mul(tw.x)).add(TSL.texture(t, TSL.vec2(uvw.x, uvw.z).div(3.2)).rgb.mul(tw.y)).div(tws),
    TSL.texture(t, far).rgb, 0.35);
  // the scanned grass is a forest floor (brown-green); under the blades it is tinted to a living meadow's green
  // the meadow's own colour, varying over tens of metres — lusher, drier, darker patches — so from above it reads as a
  // living field, not one pale wash ("bland untextured marches", operator 2026-11-06)
  const patch = TSL.mx_noise_float(uvw.xy.mul(0.021)).mul(0.5).add(TSL.mx_noise_float(uvw.xy.mul(0.083)).mul(0.25)).add(0.5).clamp(0, 1);
  // (the dry end 0.68, 0.80, 0.30, was 0.78, 0.80, 0.34 — red as strong as green, the patches yellow: 2026-11-24, the red
  // 0.82 of the green the reference's meadow holds at every distance, with the blades' paint and the far tint below)
  // (then both ends' red lower again, 0.50 and 0.60: past the blades' reach and short of the far tint the bare ground is
  // the scanned grass — brown, red-heavy — under this tint, and that strip read red 0.90 of its green, hue 69°, against the
  // reference's middle meadow 0.84, 74°; 0.53 and 0.64 measured 0.87, 72°)
  const meadow = TSL.mix(TSL.vec3(0.50, 0.66, 0.28), TSL.vec3(0.60, 0.80, 0.30), patch)   // (#183 → the Chlorophyll shot: was 0.80, 0.86, 0.38 at the dry end — a yellow field)
    .mul(TSL.float(0.82).add(TSL.mx_noise_float(uvw.xy.mul(0.31)).mul(0.12)))
    // GREEN FROM AFAR (the Chlorophyll shot beside a meadow vale, 2026-11-22): past the blades (the near chunks) the meadow
    // is this ground alone, and the scanned grass is brown — the far field measured (80, 82, 38), red as strong as green,
    // so open slopes read tan, where the reference's far meadow is (98, 118, 38). Beyond the blades it turns to their green.
    // (x 1.15, 1.38, 0.95 measured (86, 93, 38): the haze takes most of a far surface's change; x 1.1, 1.8, 0.9 (86, 104, 39))
    // (red x0.98, was 1.1, 2026-11-24: the far slope read red 0.90 of its green against the reference's 0.85 — after, 0.83)
    .mul(TSL.mix(TSL.vec3(1, 1, 1), TSL.vec3(0.98, 1.8, 0.9), TSL.smoothstep(80, 500, TSL.positionWorld.sub(TSL.cameraPosition).length())));
  // THE GROUND UNDER THE BLADES IS IN THEIR SHADE (2026-11-24): between the grass clumps the meadow ground was lit as
  // open ground, and read as tan patches through the blanket where the reference's grass is dark to the ground. Within
  // the blades' reach (chunkLod: all of them to 2 chunks, a third to 3) the meadow's ground takes UNDER_BLADES of the
  // light, back to full by 56 m — with the grass on (grassShade, applySetting); a page without blades keeps it lit.
  const underBlades = TSL.mix(TSL.float(1), TSL.mix(TSL.float(UNDER_BLADES), TSL.float(1), TSL.smoothstep(30, 56, TSL.positionWorld.sub(TSL.cameraPosition).length())), grassShade);
  const color = tri(tex[0]).mul(meadow).mul(underBlades).mul(w1.x).add(tri(tex[1]).mul(w1.y)).add(rock.mul(w1.z)).add(two(tex[3]).mul(w1.w))
    .add(two(tex[4]).mul(w2.x)).add(two(tex[5]).mul(w2.y)).add(tri(tex[6]).mul(underBlades).mul(w2.z));   // a wood's floor (forestFloor), in the canopy's shade
  const m = new THREE.MeshStandardNodeMaterial({ metalness: 0 });
  m.colorNode = shadeByClouds(color.mul(TSL.attribute("color", "vec3")));
  m.roughnessNode = w1.x.mul(GROUND_ROUGH[0]).add(w1.y.mul(GROUND_ROUGH[1])).add(w1.z.mul(GROUND_ROUGH[2])).add(w1.w.mul(GROUND_ROUGH[3]))
    .add(w2.x.mul(GROUND_ROUGH[4])).add(w2.y.mul(GROUND_ROUGH[5])).add(w2.z.mul(GROUND_ROUGH[6]));
  return m;
}

// ---- grass: instanced clumps of tapered blades, dark at the root and light at the tip, swaying in the wind on the GPU
// (the mesher scatters them over the meadow, near the player only). One clump in twelve is a wildflower.
// THE MEADOW'S GRASS (#183 step 3; the operator's concept picture: a dense blanket of grass in many greens with
// white, yellow and purple flowers through it; the live meadow beside it, 2026-11-11: stiff bright spikes with bare
// ground between them, three small yellow heads on one clump in 25). The same clumps at the same density (the
// triangle budget is #150's), but each clump SPREADS wider and leans more so the blanket closes, the blades run from
// a dark root to a yellow-green tip, every clump carries its own tint (an instance colour), and a flower clump is one
// in twelve with heads of white, yellow or purple (the meadow photographs, land research meadow/). Judged side by side
// with the concept picture, not with the earlier render.
// STEP 3b — GRASS CARDS: a grass clump is three crossed cards carrying a PAINTED cluster of blades (grassCardTexture:
// sixteen tapered blades fanning from the root, dark below and light at the tip, on a clear ground, alpha-tested) —
// twelve triangles a clump against the fifty-four of the nine modelled blades, so the mesher scatters nearly twice the
// clumps (GRASS_DENSITY) at a third of the triangles, and the blanket closes the way the concept picture's does. The
// flower clump keeps its modelled blades and heads (they must stand out from the cards).
let clumpGeo = null, flowerGeo = null, matGrass = null, matFlower = null, cardTex = null;
function grassCardTexture() {
  const N = 256, cv = document.createElement("canvas"); cv.width = cv.height = N;
  const g = cv.getContext("2d");
  let seed = 4242;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  g.clearRect(0, 0, N, N);
  // MEASURED AGAINST THE CHLOROPHYLL SHOT (operator 2026-11-21, "keep going until you match the graphical fidelity"; land
  // research look/ref-chlorophyll-10M-trees-2026-11-21.webp): its near grass averages rgb (50, 62, 20), ours read
  // (110, 133, 24) — twice as bright and a third the blue, so it read lime-yellow; and its blades are fine. Now 28 blades of
  // 4-9 px (was 16 of 7-15: 2-4 cm blades read as straps), dark at the root, the blue a third of the green.
  for (let i = 0; i < 28; i++) {
    const x0 = N / 2 + (rnd() - 0.5) * 140, h = 110 + rnd() * 140, lean = (rnd() - 0.5) * 100, w = 4 + rnd() * 5;
    const segs = 6;
    for (let k = 0; k < segs; k++) {
      const t0 = k / segs, t1 = (k + 1) / segs;                     // the blade as a bent, tapering strip: six strips of a gradient
      const xa = x0 + lean * t0 * t0, ya = N - h * t0, xb = x0 + lean * t1 * t1, yb = N - h * t1, wa = w * (1 - t0), wb = w * (1 - t1);
      // second pass, measured: the first read (78, 111, 31) near and (82, 122, 46) mid against the reference's (50, 62, 20)
      // and (86, 100, 38) — still 1.6x bright near, and too pure a green (red 0.70 of the green against its 0.81-0.86)
      // third pass: (77, 95, 36) near against the reference's (50, 62, 20) — the hue right, still 1.5x bright; fourth, measured
      // LIVE (2026-11-22): (32, 48, 15) near and (52, 77, 34) mid — overshot dark, and green (red 0.65 of the green against 0.81)
      // dark at the root (0.12) to light at the tip (0.49): with the bloom's veil gone (BLOOM_THRESHOLD) the live meadow
      // measured (48, 70, 23) against the reference's sunlit field (86, 100, 38) with tips of 0.43; at 0.56 the near grass
      // in full sun overshot (92, 107, 37 against 50, 62, 20) and read yellow — between the two
      // (0.10 + 0.30, was 0.12 + 0.37, 2026-11-24: in one picture the reference's grass underfoot is 0.56 as light as its
      // middle meadow, ours read 0.81 — the blades lit as tips alone; after, 0.65 and the near grass (62, 78, 25) against
      // the reference's (56, 68, 23). A ratio in one picture holds whatever the sun's height; a lone colour does not.)
      const L = 0.10 + 0.30 * t1 ** 0.8;
      // blue a third of the green, as the reference's grass reads (near 50, 62, 20; mid 86, 100, 38). It was raised to 0.45
      // against a reading of (42, 49, 10), then measured blue-grey (68, 83, 36) — the bloom's veil (BLOOM_THRESHOLD) had
      // added the blue, not the paint; with the veil gone the paint is the reference's own ratio
      // red 0.82 of the green, was 0.92 (2026-11-24, the live vale beside the reference: every band of our meadow read red
      // 0.90-0.94 of its green, hue 66-70°, against the reference's 0.82-0.84, 74-76° — khaki, not a living green;
      // measured after: near grass 0.80, hue 77°)
      g.fillStyle = `rgb(${Math.round(255 * L * 0.82)}, ${Math.round(255 * L)}, ${Math.round(255 * L * 0.34)})`;
      g.beginPath(); g.moveTo(xa - wa / 2, ya); g.lineTo(xa + wa / 2, ya); g.lineTo(xb + wb / 2, yb); g.lineTo(xb - wb / 2, yb); g.closePath(); g.fill();
    }
  }
  const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; t.minFilter = THREE.LinearMipmapLinearFilter; t.magFilter = THREE.LinearFilter; t.anisotropy = 4;
  // PHOTO-SCANNED BLADES, NOT PAINTED STRIPS (operator 2026-11-25: the scene "looks like some fucking Nintendo ripoff", then
  // "Grass" first): the card above is the fallback; the scanned one — Poly Haven grass_medium_02, CC0, built by
  // tools/land_grass.py into static/vendor/grass/ with the painted card's light along the blade and its mean colour — is
  // drawn over it when it arrives
  const img = new Image();
  img.onload = () => { try { g.clearRect(0, 0, N, N); g.drawImage(img, 0, 0, N, N); t.needsUpdate = true; } catch (e) {} };
  img.src = "/static/vendor/grass/grass.png";
  return t;
}
/** Three crossed cards, each `wide` x `tall` metres, their uv the whole card texture; indexed from both sides. */
function cardClump(wide, tall) {
  const pos = [], uv = [], nor = [], col = [], head = [], idx = [];
  for (let c = 0; c < 3; c++) {
    const a = (c * Math.PI) / 3, dx = Math.cos(a) * wide / 2, dz = Math.sin(a) * wide / 2, base = pos.length / 3;
    pos.push(-dx, 0, -dz, dx, 0, dz, dx, tall, dz, -dx, tall, -dz);
    uv.push(0, 0, 1, 0, 1, 1, 0, 1);
    for (let k = 0; k < 4; k++) { nor.push(0, 1, 0); col.push(1, 1, 1); head.push(0); }
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3, base, base + 2, base + 1, base, base + 3, base + 2);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setAttribute("head", new THREE.Float32BufferAttribute(head, 1));
  g.setIndex(idx);
  return g;
}
function bladeClump(blades, flower) {
  const pos = [], col = [], nor = [], idx = [], head = [];
  let seed = flower ? 7 : 3;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < blades; i++) {
    const a = rnd() * Math.PI * 2, r = rnd() * 0.2, h = (flower ? 0.4 : 0.2) + rnd() * 0.3, w = 0.012 + rnd() * 0.01, lean = 0.08 + rnd() * 0.14;   // (a flower clump's stems reach over the cards)
    const bx = Math.cos(a) * r, bz = Math.sin(a) * r, dx = Math.cos(a + 1.3) * w, dz = Math.sin(a + 1.3) * w, lx = Math.cos(a) * lean, lz = Math.sin(a) * lean;
    const base = pos.length / 3;
    pos.push(bx - dx, 0, bz - dz, bx + dx, 0, bz + dz, bx - dx * 0.6 + lx * 0.4, h * 0.55, bz - dz * 0.6 + lz * 0.4,
             bx + dx * 0.6 + lx * 0.4, h * 0.55, bz + dz * 0.6 + lz * 0.4, bx + lx, h, bz + lz);
    const root = [0.04, 0.1, 0.02], mid = [0.12, 0.27, 0.05], tip = [0.36, 0.48, 0.11];     // dark root, yellow-green tip
    col.push(...root, ...root, ...mid, ...mid, ...tip);
    for (let k = 0; k < 5; k++) { nor.push(0, 1, 0); head.push(0); }   // up-facing normals: the blade takes the ground's light
    // both faces, each wound to face out, both with the up normal: a double-sided material would flip the back face's
    // normal downward and the blade's back would render black
    idx.push(base, base + 1, base + 3, base, base + 3, base + 2, base + 2, base + 3, base + 4,
             base, base + 3, base + 1, base, base + 2, base + 3, base + 2, base + 4, base + 3);
  }
  if (flower) for (let i = 0; i < 4; i++) {                        // four heads over the cards' tops, in the instance's colour (head = 1)
    const a = rnd() * Math.PI * 2, r = rnd() * 0.12, h = 0.58 + rnd() * 0.22, s = 0.05, base = pos.length / 3;
    const x = Math.cos(a) * r, z = Math.sin(a) * r;
    pos.push(x - s, h, z - s, x + s, h, z - s, x + s, h, z + s, x - s, h, z + s);
    for (let k = 0; k < 4; k++) { col.push(1, 1, 1); nor.push(0, 1, 0); head.push(1); }
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute("head", new THREE.Float32BufferAttribute(head, 1));
  g.setIndex(idx);
  return g;
}
// the flowers of the meadow photographs and the concept picture: white (yarrow, daisies), yellow (buttercups), purple
// (knapweed, clover) — linear rgb, a head's own colour; the share of each a design choice
const FLOWER_HEADS = [[0.9, 0.9, 0.82], [0.95, 0.72, 0.1], [0.55, 0.3, 0.8], [0.9, 0.9, 0.82]];
function grassMeshes(gr) {
  if (!clumpGeo) {
    cardTex = grassCardTexture();
    clumpGeo = cardClump(0.7, 0.55); flowerGeo = bladeClump(4, true);
    // wind: the tip sways most, the root not at all; each clump in its own phase
    const lp = TSL.positionLocal, sway = TSL.sin(TSL.time.mul(1.7).add(TSL.instanceIndex.toFloat().mul(0.731))).mul(0.06)
      .add(TSL.sin(TSL.time.mul(0.45).add(TSL.instanceIndex.toFloat().mul(0.113))).mul(0.05));
    // the sway's strength comes from the blade's OWN height (the geometry's vertex), not from positionLocal: by here
    // that already includes the instance's place in the chunk, metres up — squared, it threw the grass into the sky
    const tipness = TSL.attribute("position", "vec3").y.div(0.55).clamp(0, 1).pow(2);
    const swayed = lp.add(TSL.vec3(sway, 0, sway.mul(0.6)).mul(tipness));
    // a grass clump: its blades' colours in the clump's own tint (instanceColor); a flower clump: green blades, heads
    // in the instance's colour (head = 1)
    matGrass = new THREE.MeshStandardNodeMaterial({ roughness: 0.9, metalness: 0, alphaTest: 0.5 });
    const card = TSL.texture(cardTex, TSL.uv());
    matGrass.colorNode = shadeByClouds(card.rgb.mul(TSL.instanceColor));            // the painted blades in the clump's own tint
    matGrass.maskShadowNode = card.a.greaterThan(0.5);     // a blade's shadow, not its card's (see matForest)
    matGrass.opacityNode = card.a;
    matGrass.positionNode = swayed;
    matFlower = new THREE.MeshStandardNodeMaterial({ roughness: 0.85, metalness: 0 });
    matFlower.colorNode = shadeByClouds(TSL.attribute("color", "vec3").mul(TSL.mix(TSL.vec3(1), TSL.instanceColor, TSL.attribute("head", "float"))));
    matFlower.positionNode = swayed;
  }
  const n = gr.kind.length, nf = gr.kind.reduce((a, x) => a + x, 0);
  const grass = new THREE.InstancedMesh(clumpGeo, matGrass, n - nf), flowers = new THREE.InstancedMesh(flowerGeo, matFlower, Math.max(1, nf));
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), q2 = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), nv = new THREE.Vector3(), p = new THREE.Vector3(), sc = new THREE.Vector3(), c = new THREE.Color();
  let gi = 0, fi = 0;
  for (let i = 0; i < n; i++) {
    const o = i * 7, r = gr.inst[o + 6];
    p.set(gr.inst[o], gr.inst[o + 1], gr.inst[o + 2]);
    nv.set(gr.inst[o + 3], gr.inst[o + 4], gr.inst[o + 5]).normalize();
    q.setFromUnitVectors(up, nv).multiply(q2.setFromAxisAngle(up, r * Math.PI * 2));
    const s = 0.75 + 0.55 * r;
    m.compose(p, q, sc.set(s, s, s));
    if (gr.kind[i]) {
      const hc = FLOWER_HEADS[Math.floor(((r * 977) % 1) * FLOWER_HEADS.length)];
      flowers.setMatrixAt(fi, m); flowers.setColorAt(fi++, c.setRGB(hc[0], hc[1], hc[2]));
    } else {
      // the tint, by the clump's own number: from a deeper green to a warm yellow-green, and one clump in six the tan of
      // grass gone to seed — the concept picture's meadow is many greens with tan through it, never one green
      const t = (r * 389) % 1, tan = ((r * 613) % 1) < 0.17;
      grass.setMatrixAt(gi, m); grass.setColorAt(gi++, tan ? c.setRGB(1.05, 0.92, 0.55) : c.setRGB(0.92 + 0.16 * t, 0.95 + 0.06 * t, 1.0 - 0.18 * t));   // (was blue 0.85 - 0.4 t: the yellow cast)
    }
  }
  flowers.count = fi;
  if (grass.instanceColor) grass.instanceColor.needsUpdate = true;
  if (flowers.instanceColor) flowers.instanceColor.needsUpdate = true;
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
    // DEEPER GREEN (the Chlorophyll shot's forest measures rgb 44, 56, 30; ours read lime under the sun and the light through
    // the leaf — lightness was 30-44 %, saturation 42-60 %): darker, a touch less saturated, the hue a little bluer
    const a = R() * 6.28, r = Math.sqrt(R()) * 200, l = 22 + R() * 12;
    leaf(256 + Math.cos(a) * r, 256 + Math.sin(a) * r, R() * 6.28, 50 + R() * 34, 16 + R() * 10, hsl(100 + R() * 22, 36 + R() * 16, l), hsl(95, 36, l + 10));
  }
  // 1: birch — smaller, rounder, lighter leaves on fine twigs
  for (let k = 0; k < 9; k++) { const a = R() * 6.28; line(768, 256, 768 + Math.cos(a) * 200, 256 + Math.sin(a) * 200, 2, "#5a4a3a"); }
  for (let k = 0; k < 170; k++) {
    const a = R() * 6.28, r = Math.sqrt(R()) * 210, l = 28 + R() * 12;        // (was 34-48 %: a birch is lighter than an oak, but not lime)
    leaf(768 + Math.cos(a) * r, 256 + Math.sin(a) * r, R() * 6.28, 30 + R() * 16, 15 + R() * 6, hsl(80 + R() * 20, 50 + R() * 15, l), hsl(75, 45, l + 10));
  }
  // 2: needle spray — a twig down the middle (base at the top: v = 0 is the branch's base), side shoots swept toward the
  // tip, each furred in needles, as a spruce spray grows. A FULL SPRAY (the conifer up close, 2026-11-22: in the operator's
  // phone shot and beside the Chlorophyll shot every conifer read as a pole with a few sprays): the spray was needles on
  // the middle twig alone and covered 0.13-0.15 of its card at every mip level (over the leaves' alpha cut; measured by
  // tests/test_a_conifer_reads_as_a_dense_cone_not_a_pole_with_sprays.mjs, which paints this code), so a crown of cards
  // whose outline closes the cone still showed the sky through most of it. Side shoots fill it to 0.45-0.47 — the needles
  // near the twig a little longer, the inner ones darker (shade inside the spray) — and the same cards make a dark cone
  // (inside its own tile: the longest side shoots' needles reach past x = 512, onto the palm's)
  for (const g of [col, msk]) { g.save(); g.beginPath(); g.rect(6, 518, 500, 500); g.clip(); }
  line(256, 520, 256, 1012, 7, "#4a3626");
  for (let y = 530; y < 1004; y += 14) {
    const f = (y - 520) / 492, env = Math.pow(Math.sin(Math.PI * Math.min(1, f * 1.05 + 0.06)), 0.6);
    for (const sg of [-1, 1]) {
      const a = (0.8 + R() * 0.35) * sg, ln = 225 * env * (0.75 + R() * 0.3), dx = Math.sin(a), dy = Math.cos(a) * 0.8;
      line(256, y, 256 + dx * ln, y + dy * ln, 3, "#3e3222");
      for (let s = 3; s < ln; s += 4.5) {
        const px = 256 + dx * s, py = y + dy * s, tl = 20 * (1 + R() * 0.6) * (1 - 0.45 * s / ln) * (1 + 0.6 * Math.max(0, 1 - s / 90));
        const l = 11 + 13 * (s / ln) + R() * 6;
        for (const sd of [-1, 1]) {
          const b = a + sd * (0.6 + R() * 0.3);
          line(px, py, px + Math.sin(b) * tl, py + Math.cos(b) * tl, 2.6, hsl(140 + R() * 25, 32 + R() * 16, l));
        }
      }
    }
  }
  for (const g of [col, msk]) g.restore();
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
  // PHOTO-SCANNED LEAVES, NOT PAINTED SHAPES (operator 2026-11-25: "trees liok like 2002 garbage", "yours looks like some
  // fucking Nintendo ripoff. the reference looks real"): the broadleaf and birch tiles (the atlas's top row) are replaced by
  // clusters of scanned leaves — ambientCG LeafSet009, CC0, built by tools/land_leaves.py into static/vendor/leaves/ —
  // when they load; until then (or if they fail) the painted ones above stand. userData.ready settles either way, and the
  // far forest's bake (bakeForest) waits on it, so the far cards are pictures of the scanned crowns too.
  tex.userData.ready = new Promise((done) => {
    const img = new Image();
    img.onload = () => {
      try {
        const cv = document.createElement("canvas"); cv.width = img.width; cv.height = img.height;
        const g = cv.getContext("2d"); g.drawImage(img, 0, 0);
        const d = g.getImageData(0, 0, Math.min(S, img.width), Math.min(T, img.height)).data, w = Math.min(S, img.width);
        for (let y = 0; y < Math.min(T, img.height); y++) for (let x = 0; x < w; x++) {
          const i = (y * S + x) * 4, j = (y * w + x) * 4;
          out[i] = d[j]; out[i + 1] = d[j + 1]; out[i + 2] = d[j + 2]; out[i + 3] = d[j + 3];
        }
        tex.needsUpdate = true;
        done(true);
      } catch (e) { done(false); }
    };
    img.onerror = () => done(false);
    img.src = "/static/vendor/leaves/leaves.png";
  });
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
  // A FAR LAKE IS SMOOTH, NOT GRAIN (2026-11-23, the lake in a vale photographed from a meadow 1-2 km off read as grey
  // speckle): a ripple 2.2 m or 0.6 m across is under a pixel past ~400 m and ~110 m, where it only aliases — each layer
  // fades out under ~4 pixels, the way the distant land's grain does (RING_PX)
  const px = TSL.positionView.length().mul(RING_PX), fade = (wl) => TSL.smoothstep(px.mul(3), px.mul(6), TSL.float(wl));
  const n = TSL.normalView.add(a.mul(TSL.float(0.14).mul(fade(2.2))).add(b.mul(TSL.float(0.07).mul(fade(0.6))))).normalize();
  const view = TSL.positionView.normalize().negate();
  const fres = TSL.float(1).sub(n.dot(view).clamp(0, 1)).pow(4).mul(0.85).add(0.06);
  const m = new THREE.MeshStandardNodeMaterial({ roughness: 0.05, metalness: 0, transparent: true, depthWrite: false });
  m.normalNode = n;
  m.colorNode = TSL.mix(TSL.color(0x0f3b3f), TSL.uniform(waterSky), fres);
  m.opacityNode = TSL.float(0.78).add(fres.mul(0.2));
  return m;
}
const LEAF_LIT = 1.35;                         // a crown's leaves against their painted colour (see treeMaterials)
function treeMaterials() {
  const wind = TSL.attribute("wind", "vec4"), t = TSL.time, ph = wind.w;
  // a slow sway with a gusting second rhythm, biased downwind; each tree on its own phase
  const gust = TSL.sin(t.mul(1.3).add(ph)).mul(0.55).add(TSL.sin(t.mul(2.7).add(ph.mul(1.7))).mul(0.25)).add(0.35);
  const sway = TSL.positionLocal.add(wind.xyz.mul(gust));
  const lin = (name) => { const x = loadTex(name); x.colorSpace = THREE.NoColorSpace; return x; };
  const uv = TSL.uv(), birch = TSL.attribute("tile", "float");
  const bark = new THREE.MeshStandardNodeMaterial({ roughness: 0.92, metalness: 0 });
  bark.colorNode = shadeByClouds(TSL.mix(TSL.texture(loadTex("bark_col"), uv).rgb, TSL.texture(loadTex("birch_col"), uv).rgb, birch).mul(TSL.attribute("color", "vec3")));
  bark.normalNode = TSL.normalMap(TSL.mix(TSL.texture(lin("bark_nor"), uv), TSL.texture(lin("birch_nor"), uv), birch));
  bark.positionNode = sway;
  const leafTex = paintLeaves(), s = TSL.texture(leafTex, uv);
  const leaves = new THREE.MeshStandardNodeMaterial({ roughness: 0.7, metalness: 0, side: THREE.DoubleSide, alphaTest: 0.42 });
  leaves.userData.ready = leafTex.userData.ready;           // the scanned clusters in (or failed): bakeForest waits on it
  // x LEAF_LIT (2026-11-25): beside the Chlorophyll shot's near wood (50, 63, 37) the vale's wood of near models measured
  // (30, 57, 21) and (27, 47, 10) — its own colour, with clouds and sun shadows off alike; at 1.35, (36, 69, 22) / (32, 55, 11),
  // greener and no paler, the near bushes (another material) unchanged
  leaves.colorNode = shadeByClouds(s.rgb.mul(TSL.attribute("color", "vec3")).mul(LEAF_LIT));
  leaves.opacityNode = s.a;
  leaves.maskShadowNode = s.a.greaterThan(0.42);             // the shadow of the leaves, not of their cards (see matForest)
  // lit through (LEAF_THROUGH): the sun's light through the card, DIFFUSELY — a leaf scatters what it lets through, so a
  // leaf lit on its far side glows on the side the viewer sees from any angle: the sun's strike on the side away from the
  // viewer (the cards are two-sided: the normal the viewer faces is the front's, flipped on a back face), in the leaf's
  // own colour, under the cloud shadow as its reflected light is (the sun's cast shadows do not reach it: a limit). The
  // first term lit a leaf only when the viewer looked toward the sun through it, like forward scatter, and the backs of
  // a bush's far-side cards — what a viewer sees inside it — stayed black at noon (three live photographs, with the
  // occlusion pass off and with the cast shadows off alike, 2026-11-13).
  const sunV = TSL.cameraViewMatrix.mul(TSL.vec4(leafSun.dir, 0)).xyz.normalize();
  // TSL's normalView ALREADY faces the camera on a back face (measured on the WebGL2 backend with one two-sided card
  // read back from both sides, 2026-11-13: on the back, frontFacing 0 and normalView.z +1). So the sun on the far side
  // of the side seen is max(0, −normalView·s) as it stands: 1 for a back seen with the sun behind it, 1 for a front with
  // the sun behind it, 0 with the sun on the viewer's side — all four cases read back. A build that flipped normalView
  // by frontFacing turned it back on back faces and got every back wrong: the backs of a bush's far cards, lit from
  // behind, got nothing — the black bush cores that three live photographs counted alike.
  const through = TSL.clamp(TSL.normalView.dot(sunV).negate(), 0, 1);
  leaves.emissiveNode = shadeByClouds(s.rgb.mul(TSL.attribute("color", "vec3")).mul(leafSun.rgb).mul(through.mul(LEAF_THROUGH)));
  // leaves flutter on top of the sway: a quick small motion along each card's normal
  const flutter = TSL.sin(t.mul(9).add(ph.mul(3)).add(TSL.positionLocal.x.mul(4)).add(TSL.positionLocal.z.mul(3))).mul(wind.xyz.length().mul(0.22));
  leaves.positionNode = sway.add(TSL.attribute("normal", "vec3").mul(flutter));
  return [bark, leaves];
}

// ---- boulders (#183 step 5): a grey rock. The ground material's rock texture is a warm brown (124, 82, 49 on average,
// and its gravel 80, 62, 44), and no tint that multiplies it makes a pale grey of it — a neutral pale tint and then a
// blue-leaning one both photographed as a red-brown lump in the meadow (2026-11-13). So a boulder has its own material:
// the rock texture's BRIGHTNESS (its luminance, the grain without the colour) under the vertex tint the mesher gives it
// (pale grey; green where the moss is), with the rock's normal map, tiled once per 4.5 m as the ground's rock is.
let matBoulder = null;
function boulderMaterial() {
  if (matBoulder) return matBoulder;
  const col = loadTex("rock_col"), nor = loadTex("rock_nor"); nor.colorSpace = THREE.NoColorSpace;
  const uvw = TSL.attribute("uvw", "vec3"), uv = TSL.vec2(uvw.x, uvw.y).div(4.5);
  const m = new THREE.MeshStandardNodeMaterial({ roughness: 0.9, metalness: 0 });
  m.colorNode = shadeByClouds(TSL.luminance(TSL.texture(col, uv).rgb).mul(1.8).clamp(0, 1).mul(TSL.attribute("color", "vec3")));   // ×1.8: pale granite in the sun (the Tahoe erratic); the first build, ×1.35, photographed a notch dark
  m.normalNode = TSL.normalMap(TSL.texture(nor, uv), TSL.float(0.6));
  return (matBoulder = m);
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
  // painted plate (#175): steel plate under a coat of paint — the same panels, matt, in the pigment's colour (a tint
  // given as a colour is the paint's own; land-recipes.json: whitewash, red and yellow ochre, carbon black)
  28: ["paint", "#d9d5c9", 0.62], 21: ["paint", "#9c2428", 0.6], 23: ["paint", "#cfa42c", 0.6], 27: ["paint", "#26272a", 0.66],
};
/** The slow drift a scanned piece surface takes over metres (pieceMaterial): brightness ±~15 % and a faint warm/cool
 *  shift, from two octaves of smooth noise at 0.37 and 0.11 per metre — periods of ~2.7 m and ~9 m, sharing none with
 *  the scans' 1 m repeat — so no two metres of a path or a wall are the same shade. */
function pieceVariation(uv) {
  const n = TSL.mx_noise_float(uv.mul(0.37)).mul(0.6).add(TSL.mx_noise_float(uv.mul(0.11).add(17.3)).mul(0.4));   // ~-1..1
  const w = TSL.mx_noise_float(uv.mul(0.23).add(41.7));
  return TSL.vec3(1, 1, 1).mul(TSL.float(1).add(n.mul(0.15))).add(TSL.vec3(0.03, 0.0, -0.03).mul(w));
}
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
    const scanned = name !== "thatch" && name !== "steel" && name !== "paint";
    const uv = TSL.uv(), col = name === "thatch" ? thatchTexture() : name === "steel" ? steelTexture() : name === "paint" ? paintTexture() : loadTex(name + "_col");
    const hue = typeof tint === "string" ? new THREE.Color(tint) : null;       // a colour (paint) or a plain brightness
    const tintN = hue ? TSL.vec3(hue.r, hue.g, hue.b) : TSL.float(tint), vcol = TSL.attribute("color", "vec3");
    // NO STAMPED REPEAT (operator 2026-11-15: "can you fix the repetitive tiles" — a brick path is one 1 m scan stamped
    // edge to edge, the same bricks in the same shades every metre): a scanned surface drifts in brightness and a little
    // in hue over metres, by smooth noise at scales that share no period with the 1 m repeat — never per tile, which
    // would draw the grid. Pinned by the repeat test (pieceVariation).
    const textured = () => shadeByClouds(TSL.texture(col, uv).rgb.mul(scanned ? pieceVariation(uv) : TSL.float(1)).mul(tintN).mul(vcol));
    if (name === "steel") m.metalness = 0.55;                                 // metal: it takes the sky's colour a little
    if (name === "paint") m.metalness = 0.12;
    if (scanned) {
      // until the scan and its normal map are in, the piece is its block's own flat colour (the atlas's PAINT), lit as a
      // plain surface — never the empty texture three binds meanwhile (black: see loadTex)
      const nor = loadTex(name + "_nor"); nor.colorSpace = THREE.NoColorSpace;
      const flat = new THREE.Color((PAINT[Wd.BLOCKS[blk].tex[1]] || ["#8a8478"])[0]);
      m.colorNode = shadeByClouds(TSL.vec3(flat.r, flat.g, flat.b).mul(tintN).mul(vcol));
      Promise.all([col.userData.ready, nor.userData.ready]).then(([a, b]) => {
        if (!a) return;                                                       // no scan: the flat colour stays
        m.colorNode = textured();
        if (b) m.normalNode = TSL.normalMap(TSL.texture(nor, uv));
        m.needsUpdate = true;
      });
    } else m.colorNode = textured();
  }
  if (m !== matPieces) m.name = "piece " + (spec ? spec[0] : Wd.BLOCKS[blk] ? Wd.BLOCKS[blk].key : blk);   // what /draws calls it
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
// paint has no scan: a near-white coat over 1 m panels — a thin seam round each, faint streaks of weather running down
// and a few scuffs — painted once and tinted by the pigment (PIECE_TEX), so every painted plate is the same sheet
let paintTex = null;
function paintTexture() {
  if (paintTex) return paintTex;
  const cv = document.createElement("canvas"); cv.width = cv.height = 256;
  const g = cv.getContext("2d");
  g.fillStyle = "#f4f4f2"; g.fillRect(0, 0, 256, 256);
  let seed = 53; const R = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < 260; i++) { const x = R() * 256, y = R() * 256, l = 20 + R() * 90; g.strokeStyle = `rgba(90,90,96,${0.03 + R() * 0.05})`; g.lineWidth = 1 + R() * 2.5; g.beginPath(); g.moveTo(x, y); g.lineTo(x + (R() - 0.5) * 3, y + l); g.stroke(); }
  for (let i = 0; i < 40; i++) { g.fillStyle = `rgba(60,60,66,${0.04 + R() * 0.06})`; g.fillRect(R() * 256, R() * 256, 2 + R() * 9, 1 + R() * 2); }
  g.strokeStyle = "rgba(70,72,78,0.5)"; g.lineWidth = 1.5; g.strokeRect(0.75, 0.75, 254.5, 254.5);
  paintTex = new THREE.CanvasTexture(cv); paintTex.wrapS = paintTex.wrapT = THREE.RepeatWrapping; paintTex.colorSpace = THREE.SRGBColorSpace; paintTex.anisotropy = 8;
  return paintTex;
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
const BLOOM_THRESHOLD = 2.0;                 // over the sky's brightness: only the sun and its glints bloom (buildPipeline)
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
    // THE BLOOM CATCHES THE SUN, NOT THE SKY (2026-11-22, beside the Chlorophyll shot): at a threshold of 0.92 the whole
    // bright sky and every cloud bloomed, and blurred over the frame that is a grey veil — the same view drawn with
    // ?plain measured the far forest (32, 51, 27) and a shaded patch (30, 44, 13), with the effects (54, 68, 54) and
    // (75, 84, 47), against the reference's (43, 54, 28). The sun disc is drawn at 6x (sunDisc below), so 2.0 keeps its glow.
    const lit = main.add(bloom(main, 0.18, 0.35, BLOOM_THRESHOLD));
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
let moon, dome, sunDisc, sunGlow, sunHalo, stars, skyAt = 0, satPts = null;
let cloudLitAt = 0, cloudLitWant = 1, cloudLitNow = 1, cloudLitStep = 0;   // the sun through the clouds over the player (#183 step 4)
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
/** A point's size so that it is never under two of the render buffer's pixels: at a lowered render resolution a 1.6-px
 *  star was under one buffer pixel, and the upscale to the screen split it into a pair of dots — "stars are drawn as
 *  short dashes at 60 %" (#181 item 9, playtest 2026-11-11; photographed at 60 % and 100 %, 2026-11-12). */
const starPx = (base) => Math.max(base, (base + 0.6) / (basePR() * SET.res / 100));
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
  stars = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: starPx(1.6), sizeAttenuation: false, transparent: true, fog: false, depthWrite: false }));
  stars.renderOrder = -1;
  scene.add(stars);
  // THE POSITIONING SATELLITES (#173): points crossing the sky where they really are (land-cosmos.js satPosition), seen
  // as the sky darkens, as the stars are
  const sg = new THREE.BufferGeometry(); sg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(3 * 64), 3));
  satPts = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xfff4d6, size: starPx(3.2), sizeAttenuation: false, transparent: true, fog: false, depthWrite: false }));
  satPts.renderOrder = -1; satPts.frustumCulled = false;
  scene.add(satPts);
}
// how many satellites are in orbit (the world server's GET /land/api/sats), asked again every minute
let satCount = 0, satAt = 0;
function satsTick() {
  if (performance.now() - satAt < 60000 && satAt) return;
  satAt = performance.now();
  fetch("/land/api/sats", { credentials: "same-origin" }).then((r) => r.json()).then((j) => { satCount = Math.min(64, (j.sats || []).length); }).catch(() => {});
}
/** Where the satellites in orbit are seen from eye `at` (metres, planet frame): the sky's points; and how many are up. */
function satSky(at, opacity) {
  satsTick();
  if (!satPts) return;
  const t = Date.now() / 1000 - Cosmos.EPOCH, pos = satPts.geometry.attributes.position, r = Math.hypot(...at), up = at.map((x) => x / r);
  let k = 0;
  for (let n = 0; n < satCount; n++) {
    const p = Cosmos.satPosition(n, t), d = [p[0] - at[0], p[1] - at[1], p[2] - at[2]], l = Math.hypot(...d);
    if ((d[0] * up[0] + d[1] * up[1] + d[2] * up[2]) / l <= 0) continue;                    // below this horizon
    pos.setXYZ(k++, (d[0] / l) * SKY_R * 0.97, (d[1] / l) * SKY_R * 0.97, (d[2] / l) * SKY_R * 0.97);
  }
  satPts.geometry.setDrawRange(0, k); pos.needsUpdate = true;
  satPts.material.opacity = opacity;
}
const TWI_LOW = Math.sin(-12 * Math.PI / 180), TWI_HIGH = Math.sin(2 * Math.PI / 180);   // the sky's light: from nautical twilight's end to 2° up
const MOON_I = 1.3, NIGHT_FILL = 1.5;                      // a moonlit night: the moon and the sky's fill at full night (were 0.9, 1.1)
// THE HAZE (scene.fogNode, set where the scene is made): the air's optical depth along a sight line of d metres is
// HAZE_K d^2 / (HAZE_D0 + d) — squared near, so the near land stays clear and the forest at 1 km dark green (6.5 %, the
// measured tune of 2026-11-22: 0.6 % at 300 m, 18 % at 1.7 km under the former squared exponential), and growing only
// in proportion far out, so the distant land (land-far.js, to 30 km) shows as hills in the haze, not as nothing: 43 %
// at 5 km, 70 % at 10 km, 92 % at 20 km. A squared exponential tuned to the same 1 km was 98 % at 6 km — the former
// edge of everything. The air thins with height (HAZE_H) over the lowlands' (HAZE_FLOOR): a pilot sees further.
const FAR_PLANE = 40000;                     // m: the camera's far plane, past the last ring's 30.7 km
const HAZE_K = 0.000134, HAZE_D0 = 1000, HAZE_H = 1200, HAZE_FLOOR = 100;   // per m, m, m, m — design choices (the values above)
// A LITTLE HAZE PAST 500 m (operator 2026-11-25, beside the Chlorophyll shot, whose woods a few hundred metres off wear a light
// blue cast where ours stood clear and dark): an extra optical depth HAZE_MID that fades in from HAZE_MID_FROM to
// HAZE_MID_TO and then stays — ~6 % more at 1 km, a constant few % past 1.5 km, so the distant land stays as far as it was
const HAZE_MID = 0.13, HAZE_MID_FROM = 400, HAZE_MID_TO = 1500;
const hazeCam = { c: TSL.uniform(new THREE.Vector3()), h: TSL.uniform(0) };   // the planet's centre from the eye, the eye over the sea
function hazeFactor() {
  const d = TSL.positionView.length(), hFrag = TSL.positionWorld.sub(hazeCam.c).length().sub(Wd.R0 + Wd.SEA);
  const thin = hazeCam.h.add(hFrag).mul(0.5).sub(HAZE_FLOOR).max(0).div(HAZE_H).negate().exp();
  return d.mul(d).div(d.add(HAZE_D0)).mul(HAZE_K).add(TSL.smoothstep(HAZE_MID_FROM, HAZE_MID_TO, d).mul(HAZE_MID)).mul(thin).negate().exp().oneMinus();
}
function sky(fr) {
  const star = Cosmos.sunFrom(Wd.PLANET), sd = new THREE.Vector3(...star.dir), up = new THREE.Vector3(fr.up[0], fr.up[1], fr.up[2]);
  const elev = sd.dot(up);                                  // the sun's height over this player's horizon (-1..1)
  // A LONGER DAY THAN NIGHT, AND A NIGHT ONE CAN SEE IN (#181 item 1, approved by the operator 2026-11-14): the sky's
  // light follows TWILIGHT — civil twilight lasts while the sun is up to 6° under the horizon, nautical to 12°, and in
  // civil twilight "enough illumination renders artificial sources unnecessary for most outdoor activities" (land
  // research: wikipedia Twilight) — so the sky lights the land from 2° over the horizon down to 12° under it (`day`),
  // where it went dark at 4.6° under. At the landing that makes 57 % of each 40-minute day light, against 50 %. The SUN's
  // own light (`sunUp`) still ends at the horizon: a sun under the ground lights nothing. The night keeps a moonlit
  // ground one can find one's way on (moon and sky fill raised below), and a hand torch is early in the recipes.
  const day = smooth01(TWI_LOW, TWI_HIGH, elev), sunUp = smooth01(-0.02, 0.22, elev), dusk = Math.max(0, 1 - Math.abs(elev) / 0.22);
  dayNow = day;                                             // (the aim outline reads it: dark by day, light by night, #177)
  torchNight = 1 - day;
  sun.position.copy(sd).multiplyScalar(150);
  sun.color.setRGB(1, 0.62 + 0.35 * smooth01(0, 0.4, elev), 0.38 + 0.55 * smooth01(0, 0.5, elev));
  // THE SUN UNDER THE CLOUDS (#183 step 4): the sun's light on the land is shaded per point by the cloud shadow map
  // (shadeByClouds: the sun's share of the light goes where a heap stands between, the sky's stays), so the sun itself is
  // no longer dimmed for the player's spot alone — that darkened a sunlit field a kilometre off along with the shade the
  // player stood in. The sky's fill still eases a little with the cloud over the player (land-clouds.js sunLit, read
  // four times a second, eased over a second — a cloud's edge takes seconds to cross at the breeze's pace).
  if (SET.clouds && performance.now() - cloudLitAt > 250) {
    cloudLitAt = performance.now();
    cloudLitWant = Clouds.sunLit(Clouds.noiseVolume(), Wd.posOf(P.face, P.u, P.v, P.h), star.dir);
  }
  cloudLitNow += ((SET.clouds ? cloudLitWant : 1) - cloudLitNow) * Math.min(1, (performance.now() - cloudLitStep) / 1000); cloudLitStep = performance.now();
  sun.intensity = 2.4 * Math.min(1.6, star.flux) * sunUp;
  // shadows only once the sun is well up: at a grazing sun the shadow map streaks the ground (acne), and real dusk
  // shadows are long and faint anyway
  sun.castShadow = elev > 0.12 && !!SET.shadows;
  moon.position.copy(sd).multiplyScalar(-150);
  // A NIGHT YOU CAN FIND YOUR WAY IN: half of every 40-minute day is night, and it was all but black — the ground at
  // 6 of 255 away from the town's lamps, no tree to be found to fell (walking the live page as the town agent,
  // 2026-11-08). Moonlight and a blue sky fill now light it the way a game's night reads: dim, blue, readable.
  moon.intensity = MOON_I * (1 - sunUp);                 // the moon from sunset, not from twilight's end: 10° under was darker than midnight
  hemi.position.copy(up);                                   // three's hemisphere light assumes +Y; here "up" is radial
  hemi.intensity = (NIGHT_FILL + (2.2 - NIGHT_FILL) * day) * (0.85 + 0.15 * cloudLitNow);   // the sky lights what the sun does not reach: a wall in its own
                                                            // shade is dim, never black (the first house render was)
  hemi.color.copy(SKY.moonFill).lerp(SKY.horizon, day);
  // the sun's share of the light on level ground: its irradiance (intensity × the sine of its height) against the sky's
  // fill — what a cloud takes away where it stands between (shadeByClouds); nothing with the clouds off or before a map
  { const D = sun.intensity * Math.max(0.05, elev), S = hemi.intensity; shadowO.share.value = SET.clouds && shadowCentre && day > 0 ? D / (D + S) : 0; }
  shadowStrength(SET.clouds ? cloudLitNow : 1);             // under a cloud the sun's cast shadows fade with the sun's part
  const lt = SET.leaves ? 1 : 0;                            // the leaves lit through (a graphics setting, #166: a cost a phone may decline)
  leafSun.dir.value.copy(sd); leafSun.rgb.value.set(lt * sun.color.r * sun.intensity, lt * sun.color.g * sun.intensity, lt * sun.color.b * sun.intensity);
  const zen = SKY.nightZ.clone().lerp(SKY.zenith, day).lerp(SKY.duskZ, dusk * 0.5);
  const hor = SKY.nightH.clone().lerp(SKY.horizon, day).lerp(SKY.dusk, dusk * 0.6);
  scene.fog.color.copy(hor); waterSky.copy(hor);
  cloudLit = { sd, hor, zen, sun: [sun.color.r * sun.intensity, sun.color.g * sun.intensity, sun.color.b * sun.intensity] };   // (the clouds, latched each sky map)
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
  satSky(Wd.posOf(P.face, P.u, P.v, P.h + EYE), 1 - smooth01(-0.05, 0.12, elev));          // lit by a sun just below the horizon
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
// ---- THE CLOUDS (#183 step 2; operator 2026-11-11 beside a concept picture of a meadow under scattered fair-weather
// cumulus: "compared to this our game looks like from 1996" — the sky had not one cloud). land-clouds.js defines them as
// a density in this planet's air (cited numbers, labelled choices, and the JS reference a test measures); here the GPU
// marches rays through that density into a SKY MAP — every direction around the eye, its rows bent to spend more of
// them near the horizon (Clouds.mapV) — a TILE a frame, so a full march of the sky costs a frame no more than 1/32 of
// it. The finished map is drawn over the dome as one sphere; the next is marched behind it and swapped in whole.
// INVARIANTS — each one a way this goes wrong:
//  * the march and the map's reader use the SAME latched frame (eye, up, east, north): a map read in today's frame
//    but marched in last cycle's turns the sky by the player's turn on the planet since — copied at the swap only;
//  * the ray/shell sums are made in doubles in JS (cloudC: r² − R² for each shell) and only differences go to the GPU:
//    r² is 7·10⁹ m², and a 32-bit float of it is ±400 m² off — the base would wobble metres from pixel to pixel;
//  * the drift angle is reduced in doubles (Clouds.drift) before it is a uniform, for the same reason;
//  * the overlay is drawn after the sun, its glow and the stars (renderOrder −0.5 > −1) and before anything else
//    transparent: a cloud hides the sun, and water or glass in front of a cloud is drawn over it;
//  * above the cloud tops the overlay comes in front of the ground (renderOrder 10, a radius under the clouds' depth) —
//    looking down on the clouds from a craft, the land is under them, not over them;
//  * the map is READ BACK FROM WHERE ITS EYE WAS (operator 2026-11-13: "at high speeds clouds really stutter" — at 290 m/s
//    every swap moved every cloud by the 150 m flown in the cycle, at once): each texel carries its cloud's mean distance
//    in a second target, and the dome reads the map reprojected from the latched eye to this frame's (Clouds.reproject,
//    line for line, twice over), so the clouds stand still as the eye moves and a swap shows them where they already were.
//    The shift is the difference of two planet-frame eyes taken in doubles here; only the metres go to the GPU.
const CLOUD_MAP = PHONE ? [1024, 512] : [2048, 1024], CLOUD_TILES = [8, 4];   // texels (a design choice), tiles a cycle
const CLOUD_KEEP = 0.75, CLOUD_KEEP_M = [5, 30];           // the sky map's history weight (~4 maps) and the eye travel that drops it
let cloudSky = null, cloudRT = [], cloudFront = 0, cloudTileI = 0, cloudTile = null, cloudScene = null, cloudCam = null;
let cloudU = null, cloudO = null, cloudTex = [], cloudLit = null, cloudMaps = 0, cloudLatch = null, cloudMRT = null, cloudEye = null;
function buildClouds() {
  const { Fn, vec2, vec3, vec4, float, uniform, Loop, If, Break, dot, sqrt, max, min, clamp, exp, pow, sin, cos, asin, atan, smoothstep, select } = TSL;
  const K = Clouds.K, S = Clouds.SIZE, vol = new THREE.Data3DTexture(Clouds.noiseVolume(), S, S, S);
  vol.format = THREE.RGFormat; vol.type = THREE.UnsignedByteType; vol.minFilter = vol.magFilter = THREE.LinearFilter;
  vol.wrapS = vol.wrapT = vol.wrapR = THREE.RepeatWrapping; vol.unpackAlignment = 1; vol.generateMipmaps = false; vol.needsUpdate = true;
  const [mw, mh] = CLOUD_MAP;
  for (let i = 0; i < 2; i++) cloudRT.push(new THREE.RenderTarget(mw, mh, { count: 2, type: THREE.HalfFloatType, depthBuffer: false, generateMipmaps: false,
    minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, wrapS: THREE.RepeatWrapping, wrapT: THREE.ClampToEdgeWrapping }));   // [0] the light, [1] the distance
  // the MRT node finds a target BY ITS TEXTURE'S NAME (three MRTNode.setup getTextureIndex): unnamed, the distance was
  // never written, every texel read 0, the reprojection divided by it and the sky lost its clouds (the page test, 2026-11-13)
  for (const rt of cloudRT) { rt.textures[0].name = "output"; rt.textures[1].name = "dist"; }
  const v3u = () => uniform(new THREE.Vector3());
  // the march's uniforms (latched at a cycle's first tile) and the overlay's (copied from them at the swap)
  cloudU = { eye: v3u(), eyeN: v3u(), r: uniform(0), c: v3u(), kase: uniform(0), up: v3u(), east: v3u(), north: v3u(),
    dr: uniform(new THREE.Vector2(1, 0)), sunU: v3u(), sunDir: v3u(), sun: v3u(), hi: v3u(), lo: v3u(), haze: v3u(),
    seed: uniform(0), keep: uniform(0) };                    // the map's jitter rotation and its history weight (below)
  cloudO = { up: v3u(), east: v3u(), north: v3u(), shift: v3u() };
  const U = cloudU, row = (m, i) => vec3(m[i * 3], m[i * 3 + 1], m[i * 3 + 2]);
  const rot = (m, x, per) => vec3(dot(row(m, 0), x), dot(row(m, 1), x), dot(row(m, 2), x)).div(per);
  const vol3 = (q) => TSL.texture3D(vol, q).level(0);
  const undrift = (p) => vec3(p.x.mul(U.dr.x).sub(p.z.mul(U.dr.y)), p.y, p.x.mul(U.dr.y).add(p.z.mul(U.dr.x)));
  // land-clouds.js heapTop / body / density, line for line
  const heapTop = (p) => {
    const x = p.mul(float(Clouds.RB).div(p.length()));
    const a = vol3(rot(Clouds.M1, x, Clouds.HEAP)).r, b = vol3(rot(Clouds.M2, x, Clouds.FIELD)).r;
    return pow(clamp(a.mul(K.heapW).add(b.mul(1 - K.heapW)).sub(K.thr).div(K.rise), 0, 1), K.dome);
  };
  const body = (p, lift = 0) => { const hN = p.length().sub(Clouds.RB).div(Clouds.THICK); return clamp(heapTop(p).mul(float(1).add(lift)).sub(hN).div(K.soft), 0, 1).mul(smoothstep(0, K.foot, hN)); };
  const density = (p, fine) => {
    const bill = vol3(p.div(Clouds.BILLOW)).g, e = float(1).sub(bill).mul(K.erode * 1).mul(fine);
    return clamp(body(p, bill.sub(0.5).mul(K.lump).mul(fine)).sub(e).div(float(1).sub(e)), 0, 1);   // (K.lump: the billows heave the top)
  };
  const CloudTexel = TSL.struct({ color: "vec4", dist: "float" }, "CloudTexel");
  const march = Fn(([dir, jit]) => {
    // Clouds.span: the stretch of the ray in the layer, for an eye below (kase 0), inside (1) or above (2) it
    const mu = dot(U.eyeN, dir), b = U.r.mul(mu), bb = b.mul(b);
    const Db = bb.sub(U.c.x), Dt = bb.sub(U.c.y), Dg = bb.sub(U.c.z), sDb = sqrt(max(Db, 0)), sDt = sqrt(max(Dt, 0));
    const below = U.kase.equal(0), down = mu.lessThan(0);
    const t0 = select(below, b.negate().add(sDb), select(U.kase.equal(1), float(0), b.negate().sub(sDt)));
    const t1a = select(below, b.negate().add(sDt), select(down.and(Db.greaterThan(0)), b.negate().sub(sDb), b.negate().add(sDt)));
    const t1 = min(t1a, t0.add(K.path));
    const ok = select(below, down.and(Dg.greaterThan(0)).not(), select(U.kase.equal(1), TSL.bool(true), down.and(Dt.greaterThan(0)))).and(t1.greaterThan(t0));
    const T = float(1).toVar(), C = vec3(0).toVar(), D = float(0).toVar(), dist = float(Clouds.FAR).toVar();
    If(ok, () => {
      const dt = t1.sub(t0).div(K.steps), t = t0.add(dt.mul(jit)).toVar();
      const toward = pow(max(dot(dir, U.sunDir), 0), 8).mul(K.silver);
      Loop(K.steps, () => {
        If(T.lessThan(0.01), () => { Break(); });
        const p = undrift(U.eye.add(dir.mul(t))), far = exp(t.negate().div(K.haze)), d = density(p, far);
        If(d.greaterThan(0.001), () => {
          let tau = float(0), last = 0;
          for (const s of K.sun) { tau = tau.add(body(p.add(U.sunU.mul(s))).mul((s - last) * K.deep)); last = s; }
          tau = tau.mul(K.sigma);
          const lit = exp(tau.negate()).mul(toward.add(0.65)).add(exp(tau.mul(-0.25)).mul(0.35));
          const hN = clamp(p.length().sub(Clouds.RB).div(Clouds.THICK), 0, 1), a = float(1).sub(exp(d.mul(K.sigma).mul(dt).negate()));
          const own = U.sun.mul(lit).add(U.lo).add(U.hi.sub(U.lo).mul(hN));
          C.addAssign(U.haze.add(own.sub(U.haze).mul(far)).mul(a).mul(T));
          D.addAssign(t.mul(a).mul(T));
          T.mulAssign(float(1).sub(a));
        });
        t.addAssign(dt);
      });
      // Clouds.march's dist: the light-weighted mean distance; no cloud met: the middle of the stretch
      const al = float(1).sub(T);
      dist.assign(min(float(Clouds.FAR), select(al.greaterThan(0.001), D.div(max(al, 1e-6)), t0.add(t1).mul(0.5))));
    });
    return CloudTexel(vec4(C, float(1).sub(T)), dist);
  });
  // a map texel's direction: u the azimuth from north toward east, v the bent elevation (Clouds.mapEl)
  const dirOf = (uv, B) => {
    const s = uv.y.mul(2).sub(1), el = s.mul(TSL.abs(s).mul(1 - Clouds.BEND).add(Clouds.BEND)).mul(Math.PI / 2), az = uv.x.sub(0.5).mul(2 * Math.PI);
    return B.up.mul(sin(el)).add(B.east.mul(sin(az)).add(B.north.mul(cos(az))).mul(cos(el)));
  };
  const tm = new THREE.MeshBasicNodeMaterial({ depthTest: false, depthWrite: false, blending: THREE.NoBlending });
  // a texel's map uv is three's own screenUV in the target, NOT the tile's position: three samples a render target's
  // texture flipped on one backend and not the other, and screenUV is the coordinate its own passes write and read by —
  // marched at the tile's world y, the map was read upside down on WebGL2 and the sky stayed clear (2026-11-11)
  // THE MARCH'S JITTER IS A HASH, NOT INTERLEAVED GRADIENT NOISE (2026-11-24): IGN's lines run diagonally across the map,
  // and once the heaps grew 200 m tall every cloud's edge wore them as a woven hatch ("////", photographed from the live
  // vale); 56 steps for 40 and a softer top left it as it was — the hatch was the jitter's own pattern. A hash of the
  // texel has none: the same edge reads as a random, fluffy fringe.
  // THE FRINGE IS AVERAGED OVER MAPS (2026-11-25): one march a texel leaves every heap's edge a random fringe however the
  // jitter is laid out, and the four-tap read only spread it. Each map now rotates every texel's jitter by the golden
  // ratio (U.seed — Cranley-Patterson: successive maps sample the step interval evenly) and blends into the map before it
  // (U.keep, an exponential average of ~4 maps), so a standing eye sees the edge converge to its mean. The history is
  // dropped as the eye moves (keep -> 0 by CLOUD_KEEP_M): from another point the old map's directions show other cloud.
  const texel = march(dirOf(TSL.screenUV, U), TSL.hash(TSL.screenCoordinate.x.add(TSL.screenCoordinate.y.mul(4099))).add(U.seed).fract());
  const prevMap = TSL.texture(cloudRT[0].textures[0], TSL.screenUV); cloudTex.push([0, prevMap]);   // the map on the dome now
  const litMap = TSL.mix(texel.get("color"), prevMap, U.keep);
  // the tile writes BOTH targets, by name: the light and the distance. The colour is the material's outputNode, NOT its
  // fragmentNode: three's NodeMaterial applies a renderer MRT only on its lit path (setup: the `fragmentNode === null`
  // branch), so with a fragmentNode the second target was never written and the first held nothing either — the sky lost
  // every cloud ("mean change 9.7 of 255" against a baseline of 44, the page cloud test, 2026-11-13; measured on a tiny
  // page reading the targets back: outputNode writes both, fragmentNode neither). The colour goes into the MRT explicitly
  // too: `TSL.output` is assigned on that path only after the MRT is read.
  tm.outputNode = litMap;
  cloudMRT = TSL.mrt({ output: litMap, dist: vec4(texel.get("dist"), 0, 0, 1) });
  cloudTile = new THREE.Mesh(new THREE.PlaneGeometry(1 / CLOUD_TILES[0], 1 / CLOUD_TILES[1]), tm); cloudTile.frustumCulled = false;
  cloudScene = new THREE.Scene(); cloudScene.add(cloudTile);
  cloudCam = new THREE.OrthographicCamera(0, 1, 1, 0, -1, 1);
  // CLOUD SHADOWS: the map's texel is Clouds.sunLit, line for line, at the ground point CLOUD_SHADOW_SPAN·(uv − ½) east and
  // north of the map's centre — the GROUND under the player, never the eye: a pilot 400 m up hangs in the layer itself
  // (the base is 419 m over the sea), and a map laid through the eye there read full sun at every texel (the first page
  // measurement, 2026-11-13). The sun's ray from the point through the layer (Clouds.span for a point under the base),
  // eight samples of the body along it, tau·sigma, and the reference's two-term transmittance. Its own uniforms: the map
  // is rendered at the frame's sun and drift, not the sky map's latched ones.
  shadowU = { at: uniform(new THREE.Vector3()), east: uniform(new THREE.Vector3()), north: uniform(new THREE.Vector3()), sunDir: uniform(new THREE.Vector3()), dr: uniform(new THREE.Vector2(1, 0)) };
  const shUndrift = (p) => vec3(p.x.mul(shadowU.dr.x).sub(p.z.mul(shadowU.dr.y)), p.y, p.x.mul(shadowU.dr.y).add(p.z.mul(shadowU.dr.x)));
  const shadowFn = Fn(([uv]) => {
    const P = shadowU.at.add(shadowU.east.mul(uv.x.sub(0.5).mul(CLOUD_SHADOW_SPAN))).add(shadowU.north.mul(uv.y.sub(0.5).mul(CLOUD_SHADOW_SPAN)));
    const r = P.length(), mu = dot(P, shadowU.sunDir).div(r), b = r.mul(mu), rr = r.mul(r);
    const Db = b.mul(b).sub(rr.sub(Clouds.RB * Clouds.RB)), Dt = b.mul(b).sub(rr.sub(Clouds.RT * Clouds.RT));
    const t0 = b.negate().add(sqrt(max(Db, 0))), t1 = min(b.negate().add(sqrt(max(Dt, 0))), t0.add(K.path));
    const lit = float(1).toVar();
    If(mu.greaterThan(0.02).and(r.lessThan(Clouds.RB)).and(t1.greaterThan(t0)), () => {
      const dt = t1.sub(t0).div(8), tau = float(0).toVar();
      Loop(8, ({ i }) => { const t = t0.add(dt.mul(float(i).add(0.5))); tau.addAssign(body(shUndrift(P.add(shadowU.sunDir.mul(t)))).mul(dt.mul(K.deep))); });
      tau.mulAssign(K.sigma);
      lit.assign(exp(tau.negate()).mul(0.65).add(exp(tau.negate().mul(0.25)).mul(0.35)));
    });
    return lit;
  });
  const sm = new THREE.MeshBasicNodeMaterial({ depthTest: false, depthWrite: false, blending: THREE.NoBlending });
  sm.outputNode = vec4(shadowFn(TSL.screenUV), 0, 0, 1);
  shadowRT = new THREE.RenderTarget(CLOUD_SHADOW_N, CLOUD_SHADOW_N, { depthBuffer: false });
  shadowRT.texture.name = "lit";
  const shadowQuad = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), sm); shadowQuad.position.set(0.5, 0.5, 0); shadowQuad.frustumCulled = false;
  shadowScene = new THREE.Scene(); shadowScene.add(shadowQuad);
  for (const n of shadowTex) n.value = shadowRT.texture;
  // the overlay: the front map, read by direction in the frame it was marched in — and from the eye it was marched
  // from: Clouds.reproject, line for line, three times over (the first distance read at the direction itself; a heap
  // 150–350 m wide stands 3–10° across a kilometre off, and the first guess from clear sky's distance lands within 5°)
  const om = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false, fog: false, side: THREE.BackSide });
  const B = Clouds.BEND;
  const uvOf = (u) => {
    const el = asin(clamp(dot(u, cloudO.up), -1, 1)).div(Math.PI / 2), sv = sqrt(TSL.abs(el).mul(4 * (1 - B)).add(B * B)).sub(B).div(2 * (1 - B));
    return vec2(atan(dot(u, cloudO.east), dot(u, cloudO.north)).div(2 * Math.PI).add(0.5), TSL.sign(el).mul(sv).mul(0.5).add(0.5));
  };
  const read = (i, u) => { const n = TSL.texture(cloudRT[0].textures[i], uvOf(u)); cloudTex.push([i, n]); return n; };   // (every node's value is swapped with the map)
  const d = TSL.positionWorld.normalize(), reproject = (dist) => d.mul(max(dist, 1)).add(cloudO.shift).normalize();   // (a distance of 0 would be NaN)
  const u1 = reproject(read(1, d).r), u2 = reproject(read(1, u1).r), u3 = reproject(read(1, u2).r);
  // THE LIGHT IS READ AS AN AVERAGE OF FOUR TAPS (2026-11-24): each texel is marched once, at its own random jitter, and
  // read alone the heaps' edges were a grain of single texels — a fringe of fur round every heap (photographed from the
  // live vale; more steps, a softer top, a gentler erosion and a patternless jitter each left it as it was). Four
  // bilinear taps ±0.75 texel apart average the jitter of the texels round the direction (about a 3 × 3 box); the colour
  // is premultiplied by the cover, so the two average together. The distance (the reprojection) stays one read.
  const uv3 = uvOf(u3), tx = 0.75 / CLOUD_MAP[0], ty = 0.75 / CLOUD_MAP[1];
  const tap = (dx, dy) => { const n = TSL.texture(cloudRT[0].textures[0], uv3.add(vec2(dx * tx, dy * ty))); cloudTex.push([0, n]); return n; };
  const lit = tap(-1, -1).add(tap(1, -1)).add(tap(-1, 1)).add(tap(1, 1)).mul(0.25);
  om.colorNode = lit.rgb.div(max(lit.a, 1e-4)); om.opacityNode = lit.a;
  cloudSky = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24), om); cloudSky.frustumCulled = false; cloudSky.visible = false;
  scene.add(cloudSky);
}
/** One frame of the clouds: march the next tile of the back map; at the last, swap it in. */
function cloudsFrame(cam, fr) {
  if (!cloudSky || !cloudLit) return;
  if (!SET.clouds) { cloudSky.visible = false; return; }
  const rr = Math.hypot(cam[0], cam[1], cam[2]);
  if (cloudTileI === 0) {                                   // a new cycle: latch the eye, its frame, the time and the light
    const U = cloudU, sq = (R) => rr * rr - R * R, dr = Clouds.drift(), L = Clouds.light(cloudLit.sd.toArray(), cloudLit.sun, cloudLit.hor.toArray(), cloudLit.zen.toArray());
    U.eye.value.set(cam[0], cam[1], cam[2]); U.eyeN.value.set(cam[0] / rr, cam[1] / rr, cam[2] / rr); U.r.value = rr;
    U.c.value.set(sq(Clouds.RB), sq(Clouds.RT), rr > Clouds.RG ? sq(Clouds.RG) : 1e30);   // (under the sea no ray meets the ground)
    U.kase.value = rr < Clouds.RB ? 0 : rr <= Clouds.RT ? 1 : 2;
    U.up.value.set(...fr.up); U.east.value.set(...fr.east); U.north.value.set(...fr.north);
    U.dr.value.set(dr[0], dr[1]); U.sunU.value.set(...Clouds.undrift(L.sunDir, dr)); U.sunDir.value.set(...L.sunDir);
    U.sun.value.set(...L.sun); U.hi.value.set(...L.hi); U.lo.value.set(...L.lo); U.haze.value.set(...L.haze);
    // the history weight: full while the eye stands (within CLOUD_KEEP_M[0] of the last map's), none past CLOUD_KEEP_M[1]
    const moved = cloudLatch && cloudMaps > 0 ? Math.hypot(cam[0] - cloudLatch.eye[0], cam[1] - cloudLatch.eye[1], cam[2] - cloudLatch.eye[2]) : Infinity;
    U.keep.value = CLOUD_KEEP * Math.max(0, Math.min(1, (CLOUD_KEEP_M[1] - moved) / (CLOUD_KEEP_M[1] - CLOUD_KEEP_M[0])));
    U.seed.value = (cloudMaps * 0.6180339887) % 1;
    cloudLatch = { up: fr.up.slice(), east: fr.east.slice(), north: fr.north.slice(), eye: [cam[0], cam[1], cam[2]] };
  }
  // CLOUD SHADOWS: the map over the ground, every CLOUD_SHADOW_MS or once the eye has moved an eighth of its span
  if (shadowScene && (!shadowCentre || performance.now() - shadowAt > CLOUD_SHADOW_MS || Math.hypot(cam[0] - shadowCentre[0], cam[1] - shadowCentre[1], cam[2] - shadowCentre[2]) > CLOUD_SHADOW_SPAN / 8)) {
    shadowAt = performance.now();
    const dr = Clouds.drift(), at = Wd.posOf(P.face, P.u, P.v, colAt(P.face, Math.floor(P.u), Math.floor(P.v)).height);   // the ground under the player
    shadowU.at.value.set(at[0], at[1], at[2]); shadowU.east.value.set(...fr.east); shadowU.north.value.set(...fr.north);
    shadowU.sunDir.value.copy(cloudLit.sd); shadowU.dr.value.set(dr[0], dr[1]);
    const was0 = renderer.getRenderTarget();
    renderer.setRenderTarget(shadowRT); renderer.render(shadowScene, cloudCam); renderer.setRenderTarget(was0);
    shadowCentre = at; shadowO.east.value.set(...fr.east); shadowO.north.value.set(...fr.north); shadowMaps++;
  }
  if (shadowCentre) shadowO.shift.value.set(cam[0] - shadowCentre[0], cam[1] - shadowCentre[1], cam[2] - shadowCentre[2]);
  const [tx, ty] = CLOUD_TILES, back = cloudRT[1 - cloudFront];
  // a tile a frame — but the FIRST map whole in one frame on a ?settle=1 photo: there the page draws a frame only now and
  // then between meshing, and the 32 tiles never finished (no photo after 33 minutes, 2026-11-21)
  const per = SETTLE && cloudMaps === 0 ? tx * ty - cloudTileI : 1;
  for (let j = 0; j < per; j++) {
    cloudTile.position.set(((cloudTileI % tx) + 0.5) / tx, (Math.floor(cloudTileI / tx) + 0.5) / ty, 0);
    const was = renderer.getRenderTarget(), ac = renderer.autoClear;
    renderer.autoClear = false;                               // the other tiles of the back map stay as they were marched
    const mrt0 = renderer.getMRT(); renderer.setMRT(cloudMRT);   // both targets: the light and the distance
    renderer.setRenderTarget(back); renderer.render(cloudScene, cloudCam); renderer.setRenderTarget(was);
    renderer.setMRT(mrt0); renderer.autoClear = ac;
    if (++cloudTileI === tx * ty) {                           // the back map is whole: it is the sky now
      cloudTileI = 0; cloudFront = 1 - cloudFront; cloudMaps++;
      for (const [i, n] of cloudTex) n.value = cloudRT[cloudFront].textures[i];
      cloudO.up.value.set(...cloudLatch.up); cloudO.east.value.set(...cloudLatch.east); cloudO.north.value.set(...cloudLatch.north);
      cloudEye = cloudLatch.eye;                                // the map on the dome was marched from here
      break;
    }
  }
  if (cloudEye) cloudO.shift.value.set(cam[0] - cloudEye[0], cam[1] - cloudEye[1], cam[2] - cloudEye[2]);   // (doubles, then metres)
  cloudSky.visible = cloudMaps > 0;
  // below or in the layer: behind everything on the ground; above its top: over the ground, under what is near
  const above = rr - Clouds.RT;
  cloudSky.scale.setScalar(above > 0 ? Math.max(20, Math.min(SKY_R * 1.056, above * 0.9)) : SKY_R * 1.056);
  cloudSky.renderOrder = above > 0 ? 10 : -0.5;
}
// the torches nearest the player, re-chosen twice a second from the loaded plots' pieces; [x, y, z] world metres
// eight on a desktop (#181, playtest 2026-11-11: "nothing lights the square" — thirteen torches stand within 30 m of the
// hall and the six nearest were the hall's own, inside it and up its tower, so the square outside them stayed dark); a
// fixed count still: a changing light count would recompile every material
const TORCH_LIGHTS = PHONE ? 2 : 8, torchLights = [];
// LIGHTS by source: how bright, how far it reaches (m), how much it flickers, and the height of its flame in its piece
// (cm). A lantern lights a yard, a street lamp a street ("townhall disappears after walking 20 meters at night",
// operator 2026-11-07); the pool is given to the sources whose light reaches the player soonest (distance / reach).
const LIGHTS = { torch: { i: 3, d: 11, f: 1, y: 112 }, fire: { i: 3, d: 9, f: 1, y: 0 },      // (a torch reaches 11 m: the square's posts are ~9 m apart, #181)
                 lantern: { i: 20, d: 18, f: 0.25, y: 18 }, lamppost: { i: 60, d: 26, f: 0.12, y: 297 },
                 carried: { i: 14, d: 11, f: 1, y: 0 } };   // a torch in the hand — see TORCH_IN_HAND below
// A HAND TORCH (#181 item 1, approved 2026-11-14: "a hand torch early in the recipes"): a torch made by hand from a stick
// and two fibre (land-recipes.json) lights the one who holds it — the selected hotbar item, on foot — as a placed torch
// lights round it, its flame at the hand and moving with it (its place set every frame, below).
const carryingTorch = () => !flying && hot[slot] === "torch" && (inv.items.torch || 0) > 0;
// TORCH_IN_HAND (a game rule, not a measured flame): at a placed torch's 3 the torch in hand added ~9 % to the ground at
// night — measured on the live page 2026-11-15, the same view with and without it, no warm pool at all — because the
// moon (MOON_I) lights the ground about as much as 3 does at the 1.5 m under the hand. It is set so that within 3 m of
// the hand it outshines the moon (i / 3² ≥ MOON_I) and fades back into moonlight by ~4 m: a pool to walk in.
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
    if (carryingTorch()) all.push([0, null, "carried"]);
    torchNear = all.filter((t) => t[0] < LIGHTS[t[2]].d + 40).sort((a, b) => a[0] / LIGHTS[a[2]].d - b[0] / LIGHTS[b[2]].d)
      .slice(0, TORCH_LIGHTS).map((t) => [t[1], LIGHTS[t[2]]]);
  }
  torchLights.forEach((l, i) => {
    const n = torchNear[i];
    // a flame flickers (a lantern's glass steadies it); by day a light is no match for the sun, so it fades in at dusk
    if (!n) { l.intensity = 0; return; }
    const [w0, L] = n, flick = 1 + L.f * (0.2 * Math.sin(now / 90 + i * 1.7) + 0.13 * Math.sin(now / 37 + i));
    const w = w0 || (carryingTorch() ? Wd.posOf(P.face, P.u, P.v, P.h + 1.45) : null);   // the carried torch: at the hand, every frame
    if (!w) { l.intensity = 0; return; }
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
  $("hudGpu").textContent = `${gpu} · ${fps} fps · ${Math.round(r.triangles / 1000)}k tris · ${r.drawCalls ?? r.calls} calls · ${chunks.size} chunks · ${forestTrees} far trees · ${farBoxes} far boxes · ${cloudMaps} sky maps · ${shadowMaps} shadow maps${cloudTileI ? ` +${cloudTileI}/${CLOUD_TILES[0] * CLOUD_TILES[1]}` : ""}`;
}
// ---- THE PROFILER (` the key left of 1, ?prof=1, or /prof; "work on performance, take a hint from true wind", operator
// 2026-11-09 — True Wind's js/profiler.js, "measure performance; don't guess"): where the frame's time goes, live — the
// frame rate over the last 2 s, the frame's work (mean and p99), the ms a frame of every timed part (the frame's own
// parts, the 4-a-second tick's, and the meshes the workers hand back), the rest as "other", and the last frame over
// PROF_LONG ms with its breakdown and how long ago. Closed, pt() still times its part for the frame-rate trace (PERF.cur,
// a few clock reads a frame) and shows nothing.
const PROF = { on: false, cur: {}, ring: [], last: null, shown: 0, wall: 0 };
const PROF_WINDOW = 2000, PROF_LONG = 250, PROF_EVERY = 250;
function pt(label, fn) {
  const t0 = performance.now(), r = fn(), ms = performance.now() - t0;
  PERF.cur[label] = (PERF.cur[label] || 0) + ms;
  if (PROF.on) PROF.cur[label] = (PROF.cur[label] || 0) + ms;
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
  perfSample(now);                                          // (the frame rate a player sees, traced once a minute)
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
  pt("mesh", applyFinished);                               // finished chunks and forest tiles, within the mesh budget (#150)
  pt("step", () => { for (let left = dt; left > 1e-6; left -= STEP_DT) step(Math.min(STEP_DT, left)); });
  pt("break", () => { breakTick(dt); levelTick(now); });
  const { fw, up: cu } = chaseView(dt), { fr } = look();   // flying an aircraft the camera rolls with it (#191), eased (CHASE_LAG)
  const cam = eyePos();
  hazeCam.c.value.set(-cam[0], -cam[1], -cam[2]); hazeCam.h.value = Math.hypot(cam[0], cam[1], cam[2]) - Wd.R0 - Wd.SEA;   // (the haze thins with height)
  camera.up.set(cu[0], cu[1], cu[2]);
  camera.lookAt(fw[0], fw[1], fw[2]);
  hemi.position.set(fr.up[0], fr.up[1], fr.up[2]);     // "up" is radial on a planet: three's hemisphere light assumes +Y
  for (const c of chunks.values()) if (c.anchor) for (const me of c.meshes) me.position.set(c.anchor[0] - cam[0], c.anchor[1] - cam[1], c.anchor[2] - cam[2]);
  for (const m of [farMesh, farSea, borderMesh, farBoxMesh, ...ringMeshes]) if (m) { const a = m.userData.anchor; m.position.set(a[0] - cam[0], a[1] - cam[1], a[2] - cam[2]); }
  for (const f of forest.values()) if (f.mesh) { const a = f.mesh.userData.anchor; f.mesh.position.set(a[0] - cam[0], a[1] - cam[1], a[2] - cam[2]); }
  for (const f of canopy.values()) if (f.mesh) { const a = f.mesh.userData.anchor; f.mesh.position.set(a[0] - cam[0], a[1] - cam[1], a[2] - cam[2]); }   // (the canopy beyond them)
  for (const [id, c] of crafts) if (c.pose) { craftPlace(c.mesh, c.pose, cam); engineFrame(id, c, cam, now); }
  animalsFrame(Math.min(0.1, (now - (frame.lastAnimals || now)) / 1000), cam); frame.lastAnimals = now;
  hitDirFrame(now);
  npcsFrame(cam, dt, now); arrowsFrame(now, cam); dropsFrame(now, cam); boltsFrame(now, cam);
  // (the goal line's nearest-source search runs a slice each half second while a bring-job is open — sourceHint)
  if (now - (goalTick || 0) > 500 && (inv.quests || []).some((q) => q.kind === "bring" && !q.ready)) { goalTick = now; goalLine(); }
  for (const r of others.values()) {
    if (!r.p) continue;
    const [f, u, v, h, yaw] = r.p, q = Wd.posOf(f, u, v, h), ofr = Wd.frameOf(f, u, v);
    r.mesh.position.set(q[0] - cam[0], q[1] - cam[1], q[2] - cam[2]);
    r.mesh.up.set(ofr.up[0], ofr.up[1], ofr.up[2]);
    const fx = Math.sin(yaw) * ofr.east[0] + Math.cos(yaw) * ofr.north[0], fy = Math.sin(yaw) * ofr.east[1] + Math.cos(yaw) * ofr.north[1], fz = Math.sin(yaw) * ofr.east[2] + Math.cos(yaw) * ofr.north[2];
    r.mesh.lookAt(r.mesh.position.x + fx, r.mesh.position.y + fy, r.mesh.position.z + fz);
    sizePlates(r.mesh);
  }
  platesFrame();                                              // after every tag is sized: crowded ones lifted clear
  if (touch) {
    const fb = $("tFly"); if (fb && fb.classList.contains("on") !== !!P.fly) fb.classList.toggle("on", !!P.fly);   // Fly lit while flying
    // the buttons a phone shows follow what it can do (land.html "FEWER BUTTONS"): Down while flying, the gathering and
    // building ones once signed in
    const bc = document.body.classList;
    if (bc.contains("flying") !== !!P.fly) bc.toggle("flying", !!P.fly);
    if (bc.contains("guest") !== !net.me) bc.toggle("guest", !net.me);
  }
  pt("sky", () => { sky(fr); torchTick(now, cam); cloudsFrame(cam, fr); farBuildTick(now); });
  // THE WIND (#113): by the height over the ground and the speed — a craft's airspeed when flying, else the body's
  if (sound.ctx && (!frame.windAt || now - frame.windAt > 100)) {
    frame.windAt = now;
    const at = flying ? flying.pose : [P.face, P.u, P.v, P.h], spd = flying ? Math.hypot(...flying.vel) : Math.hypot(P.vu || 0, P.vv || 0, P.vh || 0);
    sound.wind(windLevel(at[3] - Wd.column(at[0], Math.floor(at[1]), Math.floor(at[2])).height, spd));
    sound.engine(flying && flying.engine ? flying.engine.throttle : 0);   // the pilot's own engines (#171)
  }
  // the aimed block's outline
  const a = pt("aim", () => aim());
  if (now - aimLineAt > 150) { aimLineAt = now; const s = aimText(a), el = $("aimLine"); if (el && el.textContent !== s) el.textContent = s; }   // (#177, ~6×/s)
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
  highlight.visible = ghost.visible = ghost2.visible = false;
  // the outline is dark by day and light by night (a thin black wire was invisible after dark, #177), and on litter it
  // is the litter's own catch box — low in its cell, round its middle — not the whole metre cell
  highlight.material.color.setScalar(0.07 + 0.85 * (1 - dayNow));
  if (a && a.box) frameBox(highlight, a.box.plot, a.box.b);
  else if (a && a.hit) {
    const hp = Wd.plotOf(P.face, a.hit[0], a.hit[1]), q = Wd.plotCoords(hp);
    if (Wd.LITTER.has(blockAt(P.face, a.hit[0], a.hit[1], a.hit[2])))
      frameBox(highlight, hp, [(a.hit[0] - q.u0 + 0.5 - LITTER_R) * Wd.CM, (a.hit[1] - q.v0 + 0.5 - LITTER_R) * Wd.CM, a.hit[2] * Wd.CM, 2 * LITTER_R * Wd.CM, 2 * LITTER_R * Wd.CM, LITTER_H * Wd.CM]);
    else frameBox(highlight, hp, [(a.hit[0] - q.u0) * Wd.CM, (a.hit[1] - q.v0) * Wd.CM, a.hit[2] * Wd.CM, Wd.CM, Wd.CM, Wd.CM]);
  }
  const id = hot[slot];
  if (a && id && !NATURAL_ITEMS.has(id) && net.me) {
    const pl = placement(a);
    if (pl) { frameBox(ghost, pl.plot, pl.box); ghost.material.color.setHex(pl.ok && mayBuild(pl.plot) ? 0x33dd77 : 0xdd4433); }
    if (pl && pl.twin) { frameBox(ghost2, pl.plot, pl.twin); ghost2.material.color.copy(ghost.material.color); }   // the mirrored twin (#187)
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
// THE BORDERS FADE WITH DISTANCE (#181 item 2, playtest 2026-11-11: "thick yellow / orange lines across every meadow,
// visible from the air as a grid"): a border is BORDER_W wide (it was 9 cm) and its opacity falls from 0.85 within
// BORDER_NEAR m of the eye to nothing at BORDER_FAR — the edge of the plot one stands on and its neighbours read at once,
// the meadow beyond is not ruled into squares, and from a craft or a roof the grid is gone. A plot photo (SHOT) keeps its
// own full, wide outline.
const BORDER_W = 0.06, BORDER_NEAR = 16, BORDER_FAR = 48;
let borderMat = null;
function borderMaterial() {
  if (borderMat) return borderMat;
  const m = new THREE.MeshBasicNodeMaterial({ vertexColors: true, transparent: true, depthWrite: false, side: THREE.DoubleSide });
  m.opacityNode = SHOT !== null ? TSL.float(0.85) : TSL.float(0.85).mul(TSL.float(1).sub(TSL.smoothstep(BORDER_NEAR, BORDER_FAR, TSL.positionView.length())));
  return (borderMat = m);
}
let borderMesh = null, borderOwn = "", borderSig = "", borderAt = 0;
const borderCache = new Map();                              // plot -> { key (its shape), kind, pos (planet metres), col } (#150)
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
/** A border's vertex colours: its kind's colour, once a vertex (n = the position array's length). */
function borderColours(k, n) {
  const c = new THREE.Color(BORDER[k]), col = new Float32Array(n);
  for (let i = 0; i < n; i += 3) { col[i] = c.r; col[i + 1] = c.g; col[i + 2] = c.b; }
  return col;
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
  // THE OUTLINES ARE CACHED A PLOT AT A TIME (#150; measured 2026-11-12 on the live page at the town: this rebuild took
  // 358 ms in one frame — every plot's four edges re-sampled against the ground and the pieces, 49 plots, at every plot
  // line the player crossed and every piece anyone placed). A plot's outline is built once for its (kind, pieces,
  // edits, neighbours' kinds) and kept in planet coordinates; a rebuild concatenates the kept ones and samples only the
  // plots that changed.
  const wd = SHOT !== null ? 0.18 : BORDER_W, e = 0.04, STEP_M = 0.5;
  const keep = new Set(), parts = [];
  for (const [p, k, nb, ne] of list) {
    const q = Wd.plotCoords(p), holder = (titles.get(p) || {}).holder;
    const edges = [[[q.u0 + e, q.v0 + e], [1, 0], [0, 1], [-1, 0]], [[q.u0 + 16 - e, q.v0 + e], [0, 1], [-1, 0], [0, 1]],
                   [[q.u0 + 16 - e, q.v0 + 16 - e], [-1, 0], [0, -1], [1, 0]], [[q.u0 + e, q.v0 + 16 - e], [0, -1], [1, 0], [0, -1]]];
    // no border between two plots of one holder: their edge is no border at all (the town's four plots draw one outline,
    // not a double line down the middle of its street); (plots on sale keep each their own: the market escrows them all,
    // and a buyer needs to see each one's edges)
    const drawn = edges.map(([, , , [nr, nc]]) => {
      const n = q.prow + nr >= 0 && q.pcol + nc >= 0 && q.prow + nr < Wd.FACE_N && q.pcol + nc < Wd.FACE_N ? Wd.plotId(q.face, q.prow + nr, q.pcol + nc) : -1;
      return !(SHOT === null && k !== "sale" && holder && n >= 0 && (titles.get(n) || {}).holder === holder && borderKind(n) === k);
    });
    // THE SHAPE IS KEYED APART FROM THE COLOUR (#150; measured 2026-11-16 at the second X fighter's plot, the outline
    // builder instrumented in a test browser): on arrival every plot was sampled as "titled", then AGAIN as each
    // holder's answer came back and turned it "sale" — 49 plots twice, 876 ms and then ~830 ms more in bursts over 2 s,
    // for a change of colour alone. A kind change recolours the kept shape; only the shape's own inputs re-sample.
    const key = [nb, ne, wd, drawn.map((d) => (d ? 1 : 0)).join("")].join("|");
    keep.add(p);
    let part = borderCache.get(p);
    if (part && part.key === key && part.kind !== k) { part = { ...part, kind: k, col: borderColours(k, part.pos.length) }; borderCache.set(p, part); }
    if (!part || part.key !== key) {
      const pos = [];
      const at = (u, v) => Math.max(earthAt(q.face, u, v), pieceTopAt(p, (u - q.u0) * Wd.CM, (v - q.v0) * Wd.CM)) + 0.04;
      edges.forEach(([[u0, v0], [du, dv], [iu, iv]], ei) => {
        if (!drawn[ei]) return;
        let hPrev = at(u0, v0);
        for (let s0 = 0; s0 < 16 - 2 * e - 1e-6; s0 += STEP_M) {
          const s1 = Math.min(16 - 2 * e, s0 + STEP_M), h1 = at(u0 + du * s1, v0 + dv * s1);   // (the ground sampled once a segment end, not once a corner)
          for (const [ss, inn, hh] of [[s0, 0, hPrev], [s1, 0, h1], [s1, wd, h1], [s0, wd, hPrev]]) {
            const x = Wd.posOf(q.face, u0 + du * ss + iu * inn, v0 + dv * ss + iv * inn, hh);
            pos.push(x[0], x[1], x[2]);
          }
          hPrev = h1;
        }
      });
      part = { key, kind: k, pos: new Float64Array(pos), col: borderColours(k, pos.length) };
      borderCache.set(p, part);
    }
    parts.push(part);
  }
  for (const p of [...borderCache.keys()]) if (!keep.has(p)) borderCache.delete(p);
  const anchor = Wd.posOf(here.face, here.u0, here.v0, Wd.SEA);
  let nV = 0; for (const part of parts) nV += part.pos.length / 3;
  const pos = new Float32Array(nV * 3), col = new Float32Array(nV * 3), idx = nV * 1.5 > 65535 ? new Uint32Array(nV * 1.5) : new Uint16Array(nV * 1.5);
  let o = 0, oi = 0;
  for (const part of parts) {
    for (let i = 0; i < part.pos.length; i += 3) { pos[o + i] = part.pos[i] - anchor[0]; pos[o + i + 1] = part.pos[i + 1] - anchor[1]; pos[o + i + 2] = part.pos[i + 2] - anchor[2]; }
    col.set(part.col, o);
    for (let v = o / 3; v < (o + part.pos.length) / 3; v += 4) { idx[oi++] = v; idx[oi++] = v + 1; idx[oi++] = v + 2; idx[oi++] = v; idx[oi++] = v + 2; idx[oi++] = v + 3; }
    o += part.pos.length;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  borderMesh = new THREE.Mesh(g, borderMaterial());
  borderMesh.userData.anchor = anchor;
  borderMesh.renderOrder = 2;
  scene.add(borderMesh);
}
function slow() {
  pt("chunks", updateChunks);
  pt("forest", updateForest);
  pt("canopy", updateCanopy);
  pt("borders", updateBorders);
  pt("net", netTick);
  pt("far", updateFar);                                    // a far job when the far ground or a ring is due (land-far.js)
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
// ?settle=1 — the same wait from the PLAYER'S OWN EYES (the look work, operator 2026-11-21 with a Chlorophyll Engine meadow
// shot: "keep going until you match the graphical fidelity"): a photo of what a player sees, taken by a software-rendered
// browser, came out with no trees and no clouds — the far forest was still queued behind slow frames (one result applied
// a frame at 0.4 frames a second), not missing for players. Nothing drawn until the world has meshed and settled.
const SETTLE = new URLSearchParams(location.search).get("settle") === "1";
function shotTick(now) {
  if ((SHOT === null && !SETTLE) || document.title === "shot-ready") return false;
  applyFinished();                                          // (the frame returns early below while chunks are in flight: their results must still land)
  if (queue.length || inflight.size || !chunks.size) { shotBusyAt = now; return true; }
  if (now - shotBusyAt < 4000) return true;
  // THE SKY TOO: the cloud map is marched a tile a frame (CLOUD_TILES, 32 a cycle) and shown at its first swap — the
  // first settled photo was taken four frames in, with no clouds yet. Frames are drawn until the first map is in.
  if (SET.clouds && cloudSky && cloudMaps === 0) return false;
  if (++shotFrames > 3) document.title = "shot-ready";             // a few frames drawn first: shaders compiled, shadows cast
  return false;
}
// ---- start -----------------------------------------------------------------------------------------------------
async function start() {
  load();
  viewDist = SET.view;                                      // the view distance setting (#166); a photo shot takes its own
  if (SHOT !== null) shotSetup();
  // THE TOWN WITH THE FIRST FRAME (#178): the hall's plot and its eight neighbours are fetched FIRST — before the
  // rules, the renderer and the first chunks — so the first picture holds the hall, not bare ground where it will be
  // (the playtest's newcomer watched the town arrive seconds after the terrain, by the world server's own order of
  // plots; asked for after the rules, the records still came ~4 s after the first frame, 2026-11-12: they queued behind
  // the page's own downloads). The same records come over the socket later and replace these alike (setPlotBoxes /
  // applyPlot are idempotent; the chunks are not there yet, so nothing is remeshed, they are meshed with the pieces).
  prefetchTown();
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
  // CLEARER AIR (the Chlorophyll bar, operator 2026-11-21): linear fog from the view's edge to 2.9 km was already 32 % thick
  // at 1 km, so the forest band read a pale blue-grey (77, 100, 81) where the reference's distant forest is dark green
  // (44, 56, 30); at 0.00036 still (70, 103, 73), measured live 2026-11-22. Aerial haze grows with distance squared: ~7 % at
  // 1 km, ~18 % at the far ground's edge (1.7 km). Kept at 1 km, and no longer white by 6 km: HAZE_K (hazeFactor) says how.
  scene.fog = new THREE.FogExp2(0xb7d6ef, 0);              // its colour is the horizon's (sky); the haze itself is scene.fogNode
  scene.fogNode = TSL.fog(TSL.reference("color", "color", scene.fog), hazeFactor());
  // the far plane past the distant land's last ring (land-far.js, 30 km): at 4 km it cut the land off with its rim
  camera = new THREE.PerspectiveCamera(SET.fov, innerWidth / innerHeight, 0.08, FAR_PLANE);
  camera.position.set(0, 0, 0);
  sun = new THREE.DirectionalLight(0xfff4e0, 3);
  Object.assign(sun.shadow.camera, { near: 1, far: 1200 });   // (the cascades clone it: deep enough for the far cascade plus the light margin)
  shadowQuality();                                          // the cascades by SET.shadows (#166); off: medium's, unused
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.04;
  scene.add(sun, sun.target);                               // the target stays at the origin: the player
  moon = new THREE.DirectionalLight(0x8fa8d8, 0.3); scene.add(moon, moon.target);
  hemi = new THREE.HemisphereLight(0xcfe8ff, 0x5a4a38, 0.9); scene.add(hemi);
  scene.add(new THREE.AmbientLight(0x8090b0, 0.45));      // a night is dark, never black
  // torchlight: a FIXED pool of warm point lights given to the torches nearest the player (a changing light count would
  // recompile every material); unused ones sit at intensity 0
  for (let i = 0; i < TORCH_LIGHTS; i++) { const l = new THREE.PointLight(0xffa04a, 0, 9, 2); torchLights.push(l); scene.add(l); }
  buildSky();
  try { buildClouds(); } catch (e) { console.error("clouds", e); }   // (#183: without them the sky is as it was)
  const atlas = paintAtlas();
  atlasTex = new THREE.CanvasTexture(atlas);
  atlasTex.magFilter = THREE.NearestFilter; atlasTex.minFilter = THREE.NearestFilter; atlasTex.colorSpace = THREE.SRGBColorSpace;
  atlasTex.generateMipmaps = false;
  matSolid = new THREE.MeshStandardMaterial({ map: atlasTex, vertexColors: true, alphaTest: 0.5, roughness: 0.85, metalness: 0 });
  matClear = new THREE.MeshStandardMaterial({ map: atlasTex, vertexColors: true, transparent: true, depthWrite: false, roughness: 0.15, metalness: 0 });
  grassShade.value = SET.grass ? 1 : 0;                      // (the ground under the blades is shaded only where blades are drawn)
  matGround = groundMaterial();
  matTrees = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9, metalness: 0 });
  [matBark, matLeaves] = treeMaterials();
  bakeForest().catch((e) => console.error("far forest", e));   // (#183: without its atlas there is no far forest, and the world is as it was)
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
  matPieces.colorNode = shadeByClouds(sample.rgb.mul(shade));
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
  // SMOKE (#124): grey, NOT additive — smoke dims what is behind it where a flame lights it; puffs billow up the column at
  // each fire's own phase, thickest just over the flames and gone at the top, and drift sideways a little as they rise
  matSmoke = new THREE.MeshBasicNodeMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide });
  {
    const uv = TSL.uv(), ph = TSL.attribute("color", "vec3").x.mul(6.283), t = TSL.time;
    const puff = TSL.sin(uv.y.mul(7).sub(t.mul(1.6)).add(ph)).mul(0.5).add(0.5).mul(TSL.sin(uv.y.mul(3.1).sub(t.mul(0.9)).add(ph.mul(1.9))).mul(0.3).add(0.7));
    const body = TSL.float(1).sub(uv.x.sub(0.5).abs().mul(2)).clamp(0, 1).pow(0.8);
    const fade = TSL.float(1).sub(uv.y).pow(1.3).mul(uv.y.mul(6).clamp(0, 1));          // from nothing at the flames to thick, then thinning out
    const a = body.mul(fade).mul(puff).mul(0.42);   // (0.55 read as a dark stain on a card close to the eye — the first look)
    matSmoke.colorNode = TSL.mix(TSL.vec3(0.46, 0.45, 0.44), TSL.vec3(0.70, 0.70, 0.71), uv.y);   // grey at the fire, paler as it rises
    matSmoke.opacityNode = a;
    matSmoke.positionNode = TSL.positionLocal.add(TSL.vec3(TSL.sin(t.mul(0.7).add(ph).add(uv.y.mul(2))).mul(uv.y.mul(0.35)), 0, 0));
  }
  matGlassy = new THREE.MeshStandardNodeMaterial({ roughness: 0.04, metalness: 0, transparent: true, depthWrite: false });
  const glassView = TSL.positionView.normalize().negate(), glassFres = TSL.float(1).sub(TSL.normalView.dot(glassView).abs()).pow(3);
  matGlassy.colorNode = TSL.mix(TSL.vec3(0.70, 0.78, 0.80), TSL.uniform(waterSky), glassFres.mul(0.8)).mul(shade);
  matGlassy.opacityNode = TSL.float(0.16).add(glassFres.mul(0.62));
  ghost = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), new THREE.LineBasicMaterial({ color: 0x33dd77 }));
  ghost.visible = false;
  scene.add(ghost);
  ghost2 = ghost.clone(); ghost2.material = ghost.material.clone(); scene.add(ghost2);   // a mirrored twin's outline (#187)
  highlight = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1.02, 1.02, 1.02)), new THREE.LineBasicMaterial({ color: 0x111111 }));
  scene.add(highlight);
  addEventListener("resize", () => { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); if (csm) csm.updateFrustums(); });
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
  setInterval(() => pt("titles", refreshTitles), 30000);
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
