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
import * as THREE from "/static/vendor/three/three.webgpu.js";
import * as Wd from "./land-world.js";
import { NadoDapp, wireWallet, renderWallet, alertBar, notify, uiConfirm, uiPrompt, isAddress, esc, base, disp, $ } from "./nadodapp.js";

const CID = "0000000000000000000000000000000c";      // set by execnode/games/redeploy.py wire() at deploy
const ISSUER = "3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f";   // land.py ISSUER — every title's issuer
const NFT_URL = "https://nft.nadochain.com/";
const dapp = new NadoDapp({ cid: CID, app: "Land" });
const T = (k, en, v) => window.t("land." + k, en, v);

const { CHUNK, PLOT, W, H, B, BLOCKS } = Wd;
const EYE = 1.62, HALF = 0.3, TALL = 1.8, REACH = 7;
const GRAV = 26, JUMP = 8.4, WALK = 4.6, RUN = 7.5, FLY = 14, FLY_FAST = 60;

// ---- state ------------------------------------------------------------------------------------------------------
const P = { face: Wd.SPAWN_FACE, u: 0, v: 0, h: 0, yaw: 0, pitch: -0.15, vu: 0, vv: 0, vh: 0, fly: false, ground: false };
const edits = new Map();              // "face:u:v:h" -> block id: every known edit (mine and, with the server, everyone's)
const plotEdit = new Map();           // plot -> Map(local key "x:z:y" -> block)
const salts = new Map();              // plot -> Uint8Array(32), the commitment salt (kept with the plot's edits)
const titles = new Map();             // plot -> { aid, holder } for every issued title
const mine = new Set();               // plots whose title the signed-in address holds
const builds = new Set();             // plots the world server says the signed-in address was invited to build on
let hot = [B.grass, B.dirt, B.stone, B.planks, B.cobble, B.brick, B.glass, B.tiles, B.lamp], slot = 0;
let renderer, scene, camera, sun, hemi, atlasTex, matSolid, matClear, farMesh = null, farAt = null;
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
  33: ["#2a2a2a", 0.3],
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
const solidAt = (f, u, v, h) => BLOCKS[blockAt(f, Math.floor(u), Math.floor(v), Math.floor(h))].solid;

// ---- camera frame -----------------------------------------------------------------------------------------------
function look() {
  const fr = Wd.frameOf(P.face, P.u, P.v), cp = Math.cos(P.pitch), sy = Math.sin(P.yaw), cy = Math.cos(P.yaw);
  const fw = [0, 1, 2].map((i) => cp * (sy * fr.east[i] + cy * fr.north[i]) + Math.sin(P.pitch) * fr.up[i]);
  return { fr, fw };
}
/** World position (metres, doubles) of the eye. */
function eyePos() { return Wd.posOf(P.face, P.u, P.v, P.h + EYE); }

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
  if (P.fly) {
    P.vu = wu; P.vv = wv;
    P.vh = ((keys.has("Space") || (touch && touch.up) ? 1 : 0) - (keys.has("KeyC") || keys.has("ControlLeft") || (touch && touch.down) ? 1 : 0)) * sp;
  } else {
    const k = P.ground ? 1 : 0.25;                      // a little air control
    P.vu += (wu - P.vu) * Math.min(1, dt * 12 * k); P.vv += (wv - P.vv) * Math.min(1, dt * 12 * k);
    P.vh -= GRAV * dt;
    if ((keys.has("Space") || (touch && touch.up)) && P.ground) { P.vh = JUMP; P.ground = false; }
  }
  // per axis, so a wall stops one direction and the player slides along it
  const nu = P.u + P.vu * dt; if (!collides(nu, P.v, P.h)) P.u = nu; else P.vu = 0;
  const nv = P.v + P.vv * dt; if (!collides(P.u, nv, P.h)) P.v = nv; else P.vv = 0;
  const nh = P.h + P.vh * dt;
  if (!collides(P.u, P.v, nh)) { P.h = nh; P.ground = false; }
  else {
    if (P.vh < 0) {                                   // landed: stand exactly on the top of the block below
      P.ground = true;
      const snap = Math.floor(nh + 0.01) + 1;
      if (snap <= P.h + 1e-6 && !collides(P.u, P.v, snap)) P.h = snap;
    }
    P.vh = 0;
  }
  if (P.h < 1) { P.h = Wd.column(P.face, Math.floor(P.u), Math.floor(P.v)).top + 1; P.vh = 0; }
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

// ---- aiming: a voxel walk along the look direction --------------------------------------------------------------
function aim() {
  const { fr, fw } = look();
  const d = [fw[0] * fr.east[0] + fw[1] * fr.east[1] + fw[2] * fr.east[2], fw[0] * fr.north[0] + fw[1] * fr.north[1] + fw[2] * fr.north[2],
             fw[0] * fr.up[0] + fw[1] * fr.up[1] + fw[2] * fr.up[2]];
  const o = [P.u, P.v, P.h + EYE];
  let c = o.map(Math.floor), prev = null;
  const st = d.map((x) => (x > 0 ? 1 : -1)), tD = d.map((x) => Math.abs(1 / (x || 1e-9)));
  let tM = d.map((x, i) => (x > 0 ? c[i] + 1 - o[i] : o[i] - c[i]) * tD[i]), t = 0;
  for (let i = 0; i < 64 && t <= REACH; i++) {
    const b = blockAt(P.face, c[0], c[1], c[2]);
    if (b !== B.air && !BLOCKS[b].liquid) return { hit: c.slice(), prev };
    prev = c.slice();
    const a = tM[0] < tM[1] ? (tM[0] < tM[2] ? 0 : 2) : (tM[1] < tM[2] ? 1 : 2);
    c[a] += st[a]; t = tM[a]; tM[a] += tD[a];
  }
  return null;
}

// ---- edits ------------------------------------------------------------------------------------------------------
function plotEditsList(plot) { return [...(plotEdit.get(plot) || new Map())].map(([k, b]) => { const [x, z, y] = k.split(":").map(Number); return [x, z, y, b]; }); }
function saltOf(plot) {
  let s = salts.get(plot);
  if (!s) { s = crypto.getRandomValues(new Uint8Array(32)); salts.set(plot, s); }
  return s;
}
const mayBuild = (plot) => mine.has(plot) || builds.has(plot);
/** Record one cell. `mirror`: the world server's list, kept exactly as it sent it (an edit back to the terrain's own
 *  block stays listed there, so it stays listed here — the commitment is computed over the server's list). */
function putCell(face, u, v, h, b, mirror) {
  const plot = Wd.plotOf(face, u, v), k = key(face, u, v, h);
  const pc = Wd.plotCoords(plot), lk = (u - pc.u0) + ":" + (v - pc.v0) + ":" + h;
  let pe = plotEdit.get(plot); if (!pe) { pe = new Map(); plotEdit.set(plot, pe); }
  if (!mirror && b === Wd.terrainBlock(face, u, v, h, colAt)) { edits.delete(k); pe.delete(lk); } else { edits.set(k, b); pe.set(lk, b); }
  remeshAround(face, u, v, h);
}
function setBlock(f, u, v, h, b) {
  const w = Wd.wrap(f, u, v), plot = Wd.plotOf(w.face, w.u, w.v);
  if (!mayBuild(plot)) return explainNoBuild(plot);
  if (h <= 0 || h >= H) return false;
  if (net.online) {                                 // the world server decides; the cell shows at once and is put back if refused
    putCell(w.face, w.u, w.v, h, b, true);
    net.send({ t: "set", cells: [[w.face, w.u, w.v, h, b]], req: ++net.req });
    net.pending.set(net.req, plot);
  } else {
    putCell(w.face, w.u, w.v, h, b, false);
    saltOf(plot);
    save();
  }
  return true;
}
function explainNoBuild(plot) {
  const t = titles.get(plot);
  if (net.online && !net.me) notify(T("needSignIn", "Sign in to build — only a plot's owner and the builders they invite can change it."));
  else if (!net.online && !dapp.me) notify(T("needSignIn", "Sign in to build — only a plot's owner and the builders they invite can change it."));
  else if (!t) notify(T("notForSale", "This land has no title yet — it is wilderness. Plots open for sale in waves."));
  else notify(T("notYours", "Plot {p} belongs to someone else. Buy a plot, or ask its owner to invite you.", { p: t ? plotLabel(plot) : "" }));
  return false;
}
function save() {
  try {
    const out = {};
    for (const [plot, pe] of plotEdit) if (pe.size) out[plot] = { e: [...pe], s: btoa(String.fromCharCode(...saltOf(plot))) };
    localStorage.setItem(LS, JSON.stringify({ p: [P.face, P.u, P.v, P.h, P.yaw, P.pitch], plots: out, hot }));
  } catch (e) {}
}
function load() {
  let d = null;
  try { d = JSON.parse(localStorage.getItem(LS) || "null"); } catch (e) {}
  if (d && d.plots) for (const [plot, rec] of Object.entries(d.plots)) {
    const id = Number(plot), pc = Wd.plotCoords(id), pe = new Map(rec.e || []);
    plotEdit.set(id, pe);
    if (rec.s) salts.set(id, Uint8Array.from(atob(rec.s), (c) => c.charCodeAt(0)));
    for (const [lk, b] of pe) { const [x, z, y] = lk.split(":").map(Number); edits.set(key(pc.face, pc.u0 + x, pc.v0 + z, y), b); }
  }
  if (d && Array.isArray(d.hot) && d.hot.length === 9) hot = d.hot.map((b) => (BLOCKS[b] && BLOCKS[b].build ? b : B.stone));
  if (d && Array.isArray(d.p)) { [P.face, P.u, P.v, P.h, P.yaw] = d.p; if (typeof d.p[5] === "number") P.pitch = d.p[5]; return; }
  const sp = Wd.plotCoords(Wd.plotId(Wd.SPAWN_FACE, Wd.SPAWN_PLOT_ROW + 5, Wd.SPAWN_PLOT_COL + 5));
  P.face = sp.face; P.u = sp.u0 + 0.5; P.v = sp.v0 - 6.5;            // amid the first wave of plots
  P.h = Wd.column(P.face, Math.floor(P.u), Math.floor(P.v)).top + 1;
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
  queue.push({ id: ++reqId, k, face, cu, cv, ch, edits: editsFor(face, cu, cv) });
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
  g.setAttribute("uv", new THREE.BufferAttribute(part.uv, 2));
  g.setAttribute("color", new THREE.BufferAttribute(part.col, 3));
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
    if (m.solid) c.meshes.push(new THREE.Mesh(geom(m.solid), matSolid));
    if (m.clear) { const me = new THREE.Mesh(geom(m.clear), matClear); me.renderOrder = 1; c.meshes.push(me); }
    for (const me of c.meshes) { me.matrixAutoUpdate = true; scene.add(me); }
  }
  if (c.dirty) request(k);
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
    for (let ch = lo; ch <= hi; ch++) want.add(face + ":" + cu + ":" + cv + ":" + ch);
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
    const h = Math.max(c.top, Wd.SEA) + 0.5 - (near ? 6 : 0);           // tucked under the chunks it overlaps
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
  farMesh = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true }));
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
  let list = plotEditsList(plot), commit;
  if (net.online) {
    // the world server holds the plot's list and salt; recompute its commitment here before the wallet signs it
    const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin" })).json();
    list = r.edits || [];
    commit = r.salt ? await Wd.plotCommitment(plot, Uint8Array.from(r.salt.match(/../g).map((x) => parseInt(x, 16))), list) : null;
    if (!commit || commit !== r.commitment) return alertBar(T("anchorMismatch", "The world server's copy of this plot does not match its fingerprint — not anchoring. Reload and try again."));
  } else commit = await Wd.plotCommitment(plot, saltOf(plot), list);
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
// Without it (the page served elsewhere, or the server down) the page still runs: edits stay in this browser.
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
      // the server is the record now: drop the plots this browser cached, the server sends each watched one back
      for (const [plot, pe] of plotEdit) { const q = Wd.plotCoords(plot); for (const lk of pe.keys()) { const [x, z, y] = lk.split(":").map(Number); edits.delete(key(q.face, q.u0 + x, q.v0 + z, y)); } }
      plotEdit.clear();
      if (net.me !== was) refreshTitles();
      hud();
    } else if (m.t === "plot") {
      applyPlot(m.plot, m.edits || []);
    } else if (m.t === "edit") {
      for (const [f, u, v, h, b] of m.cells || []) putCell(f, u, v, h, b, true);
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
  for (const [x, z, y, b] of list) putCell(q.face, q.u0 + x, q.v0 + z, y, b, true);
  if (old) for (let ch = 0; ch < H / CHUNK; ch++) { const k = q.face + ":" + q.u0 / CHUNK + ":" + q.v0 / CHUNK + ":" + ch; if (chunks.has(k)) request(k); }
}
async function resync(plot) {
  try { const r = await (await fetch("/land/api/plot?plot=" + plot, { cache: "no-store", credentials: "same-origin" })).json(); applyPlot(plot, r.edits || []); } catch (e) {}
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
    + (changed ? " · " + T("changed", "{n} {n|one:changed block|other:changed blocks}", { n: changed }) : "");
  const st = $("hudPlot");
  // the owner is looked up once the plot's title is KNOWN (titles load after the first frames), once per refresh
  if (t && !mine.has(plot) && !t.asked) { t.asked = true; holderOf(plot).then(hud); }
  let html;
  if (t && net.online && net.me && !t.checked) { t.checked = true; builderCheck(plot); }
  const signIn = net.online && !net.me ? ` <a class="btn" href="/land/api/login">${esc(T("signInBuild", "Sign in to build"))}</a>` : "";
  if (!t) html = `<span class="pill">${esc(T("wild", "Wilderness"))}</span> <span class="dim">${esc(T("wildHint", "No title yet — this land opens in a later wave."))}</span>${signIn}`;
  else if (builds.has(plot) && !mine.has(plot)) html = `<span class="pill ok">${esc(T("invited", "You may build here"))}</span> <span class="dim">${esc(t.holder ? T("owned", "Owned by {o}", { o: disp(t.holder) }) : "")}</span>`;
  else if (mine.has(plot)) html = `<span class="pill ok">${esc(T("yours", "Your plot"))}</span> <button id="btnAnchor" class="ghost">${esc(T("anchorBtn", "Anchor build"))}</button> <button id="btnInvite" class="ghost">${esc(T("inviteBtn", "Invite a builder"))}</button>`;
  else html = `<span class="pill">${esc(t.holder ? T("owned", "Owned by {o}", { o: disp(t.holder) }) : T("titled", "Titled"))}</span> <a class="btn" target="_blank" rel="noopener" href="${NFT_URL}#token/${esc(t.aid)}">${esc(T("market", "View on the market"))}</a>${signIn}`;
  if (st.dataset.html !== html) {
    st.innerHTML = html; st.dataset.html = html;
    const b = $("btnAnchor"); if (b) b.onclick = () => anchor(plot);
    const iv = $("btnInvite"); if (iv) iv.onclick = () => invite(plot);
  }
}
function hotbar() {
  const bar = $("hotbar");
  bar.innerHTML = hot.map((b, i) => `<div class="hs${i === slot ? " on" : ""}" data-i="${i}" title="${esc(T("b." + BLOCKS[b].key, BLOCKS[b].name))}"><canvas width="32" height="32"></canvas><span>${i + 1}</span></div>`).join("");
  bar.querySelectorAll(".hs").forEach((el) => {
    const i = Number(el.dataset.i), cv = el.querySelector("canvas"), tile = BLOCKS[hot[i]].tex[1];
    cv.getContext("2d").imageSmoothingEnabled = false;
    cv.getContext("2d").drawImage(atlasTex.image, (tile % TCOLS) * TILE, Math.floor(tile / TCOLS) * TILE, TILE, TILE, 0, 0, 32, 32);
    el.onclick = (e) => { e.stopPropagation(); slot = i; hotbar(); };
  });
  $("hotName").textContent = T("b." + BLOCKS[hot[slot]].key, BLOCKS[hot[slot]].name);
}
function palette(open) {
  const pal = $("palette");
  pal.classList.toggle("hidden", !open);
  if (!open) return;
  if (document.pointerLockElement) document.exitPointerLock();
  const list = BLOCKS.map((b, i) => [b, i]).filter(([b]) => b.build);
  $("palGrid").innerHTML = list.map(([b, i]) => `<button class="pb" data-b="${i}"><canvas width="40" height="40"></canvas><span>${esc(T("b." + b.key, b.name))}</span></button>`).join("");
  $("palGrid").querySelectorAll(".pb").forEach((el) => {
    const id = Number(el.dataset.b), cv = el.querySelector("canvas"), tile = BLOCKS[id].tex[1], g = cv.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.drawImage(atlasTex.image, (tile % TCOLS) * TILE, Math.floor(tile / TCOLS) * TILE, TILE, TILE, 0, 0, 40, 40);
    el.onclick = () => { hot[slot] = id; save(); hotbar(); palette(false); };
  });
}

// ---- input -----------------------------------------------------------------------------------------------------
function act(place) {
  const a = aim();
  if (!a) return;
  if (place) {
    if (!a.prev) return;
    const [u, v, h] = a.prev;
    const pu = Math.floor(P.u), pv = Math.floor(P.v);           // never inside the player
    if (u === pu && v === pv && (h === Math.floor(P.h) || h === Math.floor(P.h + 1))) return;
    setBlock(P.face, u, v, h, hot[slot]);
  } else {
    const [u, v, h] = a.hit;
    if (blockAt(P.face, u, v, h) === B.bedrock) return;
    setBlock(P.face, u, v, h, B.air);
  }
}
function wireInput(canvas) {
  canvas.addEventListener("click", () => { if (!locked && !touch) canvas.requestPointerLock(); });
  document.addEventListener("pointerlockchange", () => { locked = document.pointerLockElement === canvas; $("help").classList.toggle("hidden", locked); });
  document.addEventListener("mousemove", (e) => {
    if (!locked) return;
    P.yaw += e.movementX * 0.0024; P.pitch = Math.max(-1.55, Math.min(1.55, P.pitch - e.movementY * 0.0024));
  });
  document.addEventListener("mousedown", (e) => { if (locked) act(e.button === 2); });
  document.addEventListener("contextmenu", (e) => { if (locked) e.preventDefault(); });
  document.addEventListener("wheel", (e) => { if (!locked) return; slot = (slot + (e.deltaY > 0 ? 1 : 8)) % 9; hotbar(); }, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
    keys.add(e.code);
    if (/^Digit[1-9]$/.test(e.code)) { slot = Number(e.code.slice(5)) - 1; hotbar(); }
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
    $("tBreak").onclick = () => act(false);
    $("tPlace").onclick = () => act(true);
    $("tPal").onclick = () => palette(true);
  }
  $("palClose").onclick = () => palette(false);
}

// ---- frame -----------------------------------------------------------------------------------------------------
const DAY_S = 40 * 60;                       // a day on the planet: 40 minutes
function frame(now) {
  const dt = Math.min(0.05, (now - lastT) / 1000 || 0); lastT = now;
  step(dt);
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
  // the sun turns about the planet's axis; the sky follows its height above the player's horizon
  const ang = (Date.now() / 1000 / DAY_S) * 2 * Math.PI;
  const sd = new THREE.Vector3(Math.cos(ang), 0.35, Math.sin(ang)).normalize();
  sun.position.copy(sd).multiplyScalar(100);
  const elev = sd.x * fr.up[0] + sd.y * fr.up[1] + sd.z * fr.up[2];
  const day = Math.max(0, Math.min(1, elev * 3 + 0.35));
  sun.intensity = 3 * day; hemi.intensity = 0.3 + 1.3 * day;
  const sky = new THREE.Color(0x0a1020).lerp(new THREE.Color(0x8ec5ee), day);
  scene.background = sky; scene.fog.color = sky;
  // the aimed block's outline
  const a = aim();
  if (a) {
    const [u, v, h] = a.hit, c = Wd.posOf(P.face, u + 0.5, v + 0.5, h + 0.5);
    highlight.visible = true;
    highlight.position.set(c[0] - cam[0], c[1] - cam[1], c[2] - cam[2]);
    highlight.up.set(fr.up[0], fr.up[1], fr.up[2]);
    highlight.lookAt(highlight.position.x + fr.north[0], highlight.position.y + fr.north[1], highlight.position.z + fr.north[2]);
  } else highlight.visible = false;
  renderer.render(scene, camera);
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
  const canvas = $("world");
  renderer = new THREE.WebGPURenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.setSize(innerWidth, innerHeight);
  await renderer.init();
  $("hudGpu").textContent = renderer.backend && renderer.backend.isWebGPUBackend ? "WebGPU" : "WebGL2";
  scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x8ec5ee, viewDist * CHUNK * 0.8, 2600);
  camera = new THREE.PerspectiveCamera(72, innerWidth / innerHeight, 0.08, 4000);
  camera.position.set(0, 0, 0);
  sun = new THREE.DirectionalLight(0xfff4e0, 2.4); scene.add(sun);
  hemi = new THREE.HemisphereLight(0xcfe8ff, 0x6a5a48, 0.9); scene.add(hemi);
  scene.add(new THREE.AmbientLight(0xffffff, 0.22));      // a night is dark, never black
  const atlas = paintAtlas();
  atlasTex = new THREE.CanvasTexture(atlas);
  atlasTex.magFilter = THREE.NearestFilter; atlasTex.minFilter = THREE.NearestFilter; atlasTex.colorSpace = THREE.SRGBColorSpace;
  atlasTex.generateMipmaps = false;
  matSolid = new THREE.MeshLambertMaterial({ map: atlasTex, vertexColors: true, alphaTest: 0.5 });
  matClear = new THREE.MeshLambertMaterial({ map: atlasTex, vertexColors: true, transparent: true, depthWrite: false });
  highlight = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1.02, 1.02, 1.02)), new THREE.LineBasicMaterial({ color: 0x111111 }));
  scene.add(highlight);
  addEventListener("resize", () => { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); });
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
