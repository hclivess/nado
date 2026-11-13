/*
 * test_the_suns_shadows_reach_the_meadow_through_the_cascades.mjs — #183 step 4, in the real page against the real world
 * server: the concept picture has long tree shadows across the far ground; the game's sun cast shadows in one 64 m box
 * round the player and the meadow beyond it had none, and the far trees (cards past the meshed chunks) cast none at
 * all. land.js now gives the sun cascaded shadow maps (three's CSMShadowNode, vendored) reaching 320 m on the top preset,
 * and the far trees cast. A player hangs 135 m over the meadow in free flight, the clock held, the clouds off:
 *   1. the page draws with the cascades and no page error;
 *   2. the shadows lie WHERE the sun puts them: for the planet's trees 40–250 m from the eye's column (past the old box,
 *      past the chunks: far cards) the ground on the side away from the sun, within the tree's shadow length, is darker
 *      with the shadows on than off, and the ground beside it (sunward of the trunk) is not.
 * SHOTS=<dir> writes both views.
 *
 * Run: node tests/test_the_suns_shadows_reach_the_meadow_through_the_cascades.mjs   (needs chrome, python3)
 */
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";
import { PROTOCOL_JS } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js")), C = await import(join(ROOT, "static", "land-clouds.js"));
const Cosmos = await import(join(ROOT, "static", "land-cosmos.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** An 8-bit RGB(A) PNG (what Page.captureScreenshot gives) -> { w, h, px (RGBA) }. */
function decodePng(buf) {
  let o = 8, w = 0, h = 0, ct = 0;
  const idat = [];
  while (o < buf.length) {
    const len = buf.readUInt32BE(o), type = buf.toString("ascii", o + 4, o + 8), d = buf.subarray(o + 8, o + 8 + len);
    if (type === "IHDR") { w = d.readUInt32BE(0); h = d.readUInt32BE(4); ct = d[9]; }
    if (type === "IDAT") idat.push(d);
    o += 12 + len;
  }
  const bpp = ct === 6 ? 4 : 3, raw = inflateSync(Buffer.concat(idat)), px = new Uint8Array(w * h * 4), line = w * bpp;
  let prev = new Uint8Array(line);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (line + 1)], cur = Uint8Array.from(raw.subarray(y * (line + 1) + 1, (y + 1) * (line + 1)));
    for (let i = 0; i < line; i++) {
      const a = i >= bpp ? cur[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
      const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
      cur[i] = (cur[i] + [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][f]) & 255;
    }
    for (let x = 0; x < w; x++) for (let k = 0; k < 3; k++) px[(y * w + x) * 4 + k] = cur[x * bpp + k];
    prev = cur;
  }
  return { w, h, px };
}

// ---- the fixture: page + world server + fake exec on one origin ----------------------------------------------------
const work = mkdtempSync(join(tmpdir(), "nado-land-live-"));
writeFileSync(join(work, "protocol.js"), PROTOCOL_JS);
const fx = spawn("python3", [join(ROOT, "tests", "_land_live_fixture.py"), join(work, "protocol.js")], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, TMPDIR: work } });
let fxOut = "";
fx.stdout.on("data", (d) => { fxOut += d; });
fx.stderr.on("data", (d) => { fxOut += d; });
let HTTP = 0;
for (let i = 0; i < 240 && !HTTP; i++) { const m = fxOut.match(/PORT (\d+)/); if (m) HTTP = Number(m[1]); else await sleep(250); }
if (!HTTP) { console.log("FAIL the fixture did not start:\n" + fxOut.slice(-2000)); fx.kill("SIGKILL"); process.exit(1); }
const base = `http://127.0.0.1:${HTTP}`;

// the place: 250 m over the #183 meadow — well under the cloud base, 419 m over the sea (a first try at 400 m hung the
// eye in the layer) — looking nearly straight down (not quite: a look straight along the up vector has no right-hand),
// the clock held at a moment the sun stands high — the same moment and field the cloud test uses
const FACE = 0, U = 54260.5, V = 80600.5, TOP = Wd.column(FACE, Math.floor(U), Math.floor(V)).top + 1, H = TOP + 250, YAW = 0.4, PITCH = -1.45;
if (H + 20 >= Wd.SEA + C.BASE) { console.log("FAIL the eye would hang in the cloud layer"); process.exit(1); }
const W = 640, HH = 360;
const up = Wd.frameOf(FACE, U, V).up;
let T0 = Date.now() / 1000;
for (let k = 0; k < 4000; k++) {                 // the next moment the sun is 40°+ up here (a day is 40 minutes)
  const t = Date.now() / 1000 + k * 2, s = Cosmos.sunFrom(Wd.PLANET, t - Cosmos.EPOCH).dir;
  if (s[0] * up[0] + s[1] * up[1] + s[2] * up[2] > Math.sin(0.7)) { T0 = t; break; }
}
const HOLD = Math.round(T0 * 1000);

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 727) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landcsm-"));
let chrome = null, ver = null;
const tried = [];
for (const bin of [process.env.CHROME, "google-chrome", "google-chrome-stable", "chromium-browser", "chromium"].filter(Boolean)) {
  const c = spawn(bin, ["--headless", "--disable-gpu", "--no-sandbox", "--use-angle=swiftshader", "--remote-debugging-port=" + PORT,
    "--user-data-dir=" + prof, `--window-size=${W},${HH}`, "about:blank"], { stdio: "ignore" });
  let gone = false;
  c.on("error", () => { gone = true; }); c.on("exit", () => { gone = true; });
  for (let i = 0; i < 60 && !ver && !gone; i++) { try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch (e) { await sleep(250); } }
  if (ver) { chrome = c; break; }
  tried.push(bin + (gone ? " (exited)" : " (no CDP in 15 s)"));
  try { c.kill("SIGKILL"); } catch (e) {}
  await sleep(300);
}
function cleanup() { try { chrome && chrome.kill("SIGKILL"); } catch (e) {} try { fx.kill("SIGKILL"); } catch (e) {} for (const d of [prof, work]) try { rmSync(d, { recursive: true, force: true }); } catch (e) {} }
if (!chrome) { cleanup(); console.log(`SKIP  no browser served CDP (tried ${tried.join(", ") || "none"})`); process.exit(0); }

const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0; const pend = new Map(), errors = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
  if (m.method === "Runtime.exceptionThrown") errors.push(JSON.stringify(m.params.exceptionDetails).slice(0, 300));
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push("console: " + m.params.args.map((a) => a.value || a.description).join(" ").slice(0, 400));
});
const send = (sid, method, params) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params, sessionId: sid })); });
const evl = async (sid, expr) => {
  const r = await send(sid, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result.result.value;
};
const until = async (sid, expr, ms = 20000) => { for (let t = 0; t < ms; t += 500) { if (await evl(sid, expr).catch(() => false)) return true; await sleep(500); } return false; };
const maps = (sid) => evl(sid, "(() => { const m = /(\\d+) sky maps/.exec(document.getElementById('hudGpu').textContent); return m ? Number(m[1]) : -1; })()");
const shot = async (sid) => Buffer.from((await send(sid, "Page.captureScreenshot", { format: "png" })).result.data, "base64");

try {
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const S = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  for (const d of ["Runtime", "Page"]) await send(S, d + ".enable", {});
  await send(S, "Emulation.setDeviceMetricsOverride", { width: W, height: HH, deviceScaleFactor: 1, mobile: false });
  await send(S, "Page.addScriptToEvaluateOnNewDocument", { source: `{ const r = Date.now.bind(Date), r0 = r(); Date.now = () => Math.round(${HOLD} + (r() - r0) / 1000); }` });
  await send(S, "Page.navigate", { url: base + "/static/land-world.js" });
  await until(S, "document.readyState === 'complete'");
  await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${FACE}, ${U}, ${V}, ${H}, ${YAW}, ${PITCH}] }));
    localStorage.setItem("nado_land_settings", JSON.stringify({ fov: 72, sens: 1, invert: 0, grass: 0, shadows: 3, effects: 0, borders: 0, stats: 1, res: 100, view: 2, fps: 0, auto: 0, sv: 2, clouds: 0 })); true`);
  await send(S, "Page.navigate", { url: base + "/" });
  ok(await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 60000), "the page loads over the meadow");
  await evl(S, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");
  const con = (line) => evl(S, `(() => { const i = document.getElementById('conIn'); i.value = ${JSON.stringify(line)}; i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); i.value = ''; return true; })()`);
  await con("/fly");
  ok(await until(S, "/Flying/.test(document.getElementById('conLog').textContent)", 10000), "…and hangs in free flight (/fly)");
  // the far trees round the eye are built (the stats readout counts them), and a few frames with the cascades have drawn
  ok(await until(S, "/ [1-9]\\d* far trees/.test(document.getElementById('hudGpu').textContent)", 300000), "the far trees round the eye stand (the stats readout counts them): " + await evl(S, "document.getElementById('hudGpu').textContent"));
  await sleep(6000);
  const hudH = async () => Number((/height (-?\d+) m/.exec(await evl(S, "document.getElementById('hudPos').textContent")) || [])[1]);
  const h1 = await hudH();
  const withS = await shot(S);
  await con("/set shadows 0");
  await sleep(5000);
  const noS = await shot(S);
  const h2 = await hudH();
  ok(Number.isFinite(h1) && h1 === h2 && h1 + Wd.SEA > TOP + 60, `the eye hung still between the two views, ${h1} m over the sea (${h1 + Wd.SEA - TOP} m over the meadow)`);
  if (process.env.SHOTS) { writeFileSync(join(process.env.SHOTS, "shadows3.png"), withS); writeFileSync(join(process.env.SHOTS, "shadows0.png"), noS); }
  const A = decodePng(withS), B = decodePng(noS);
  // the camera, as land.js builds it, at the eye the HUD gives
  const [f, u, v, h, yaw, pitch] = [FACE, U, V, h1 + Wd.SEA, YAW, PITCH], fr = Wd.frameOf(f, u, v), eye = Wd.posOf(f, u, v, h + 1.62);
  const cp = Math.cos(pitch), fw = [0, 1, 2].map((i) => cp * (Math.sin(yaw) * fr.east[i] + Math.cos(yaw) * fr.north[i]) + Math.sin(pitch) * fr.up[i]);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]], norm = (a) => { const l = Math.hypot(...a); return a.map((x) => x / l); };
  const right = norm(cross(fw, fr.up)), cu = cross(right, fw), th = Math.tan((36 * Math.PI) / 180);
  const sun = Cosmos.sunFrom(Wd.PLANET, HOLD / 1000 - Cosmos.EPOCH).dir;
  // the sun over the meadow: its height, and the direction a shadow falls along the ground (away from it)
  const sUp = sun[0] * fr.up[0] + sun[1] * fr.up[1] + sun[2] * fr.up[2], sE = sun[0] * fr.east[0] + sun[1] * fr.east[1] + sun[2] * fr.east[2], sN = sun[0] * fr.north[0] + sun[1] * fr.north[1] + sun[2] * fr.north[2];
  const sh = Math.hypot(sE, sN), gE = -sE / sh, gN = -sN / sh;                  // (east, north) along which a shadow lies
  ok(sUp > 0.5, `the sun stands ${(Math.asin(sUp) * 180 / Math.PI).toFixed(0)}° up (shadows ${(1 / Math.tan(Math.asin(sUp))).toFixed(2)} m long per metre of height)`);
  // a ground point's pixel: (P − eye) in the camera's basis
  const pixelOf = (P) => {
    const d = [P[0] - eye[0], P[1] - eye[1], P[2] - eye[2]], z = d[0] * fw[0] + d[1] * fw[1] + d[2] * fw[2];
    if (z <= 1) return null;
    const x = (d[0] * right[0] + d[1] * right[1] + d[2] * right[2]) / z / (th * (A.w / A.h)), y = (d[0] * cu[0] + d[1] * cu[1] + d[2] * cu[2]) / z / th;
    const px = Math.round(((x + 1) / 2) * A.w), py = Math.round(((1 - y) / 2) * A.h);
    return px >= 8 && px < A.w - 8 && py >= 110 && py < A.h - 40 ? [px, py] : null;
  };
  const bright = (I, [px, py]) => { const o = (py * I.w + px) * 4; return (I.px[o] + I.px[o + 1] + I.px[o + 2]) / 3; };
  // the planet's trees 40–250 m from the eye's column: past the old 64 m box, past the meshed chunks (view 2: 32 m)
  let trees = 0, shadeN = 0, shadeD = 0, ctrlN = 0, ctrlD = 0;
  const R = 260, u0 = Math.floor(U), v0 = Math.floor(V);
  for (const r of Wd.treeRoots(f, u0 - R, v0 - R, 2 * R + 1)) {
    const du = r.wu + 0.5 - U, dv = r.wv + 0.5 - V, dist = Math.hypot(du, dv);
    if (dist < 40 || dist > 250 || r.tree.kind === "bush") continue;
    trees++;
    const top = r.col.top + 1, len = r.tree.height / Math.tan(Math.asin(sUp));        // the shadow of a trunk of its height
    for (let k = 1.5; k < len - 0.5; k += 1) {                                      // along the shadow, on the ground at the tree's foot
      const P = Wd.posOf(f, r.wu + 0.5 + gE * k, r.wv + 0.5 + gN * k, top), px = pixelOf(P);
      if (px) { shadeN++; shadeD += bright(B, px) - bright(A, px); }
    }
    for (let k = 3; k < 8; k += 1) {                                                // sunward of the trunk: no shadow of this tree
      const P = Wd.posOf(f, r.wu + 0.5 - gE * k, r.wv + 0.5 - gN * k, top), px = pixelOf(P);
      if (px) { ctrlN++; ctrlD += bright(B, px) - bright(A, px); }
    }
  }
  const dS = shadeD / Math.max(1, shadeN), dC = ctrlD / Math.max(1, ctrlN);
  ok(trees >= 6 && shadeN >= 40 && ctrlN >= 40, `${trees} far trees 40–250 m out are in the view (${shadeN} points along their shadows, ${ctrlN} sunward of them)`);
  ok(dS > 8 && dS > dC + 6, `along their shadows the ground is darker with the shadows on, by ${dS.toFixed(1)} of 255 (the ground sunward of the trunks by ${dC.toFixed(1)}): the far trees cast, and the cascades reach them`);
  ok(errors.length === 0, "no page error (the cascades compile and draw)" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
  // the page's text: the cascades by preset, the far trees casting, the cards' shadows cut out by their alpha (three's
  // shadow pass reads a material's colour node's alpha and its map, never opacityNode: a mask node is the cut-out)
  const page = (await import("node:fs")).readFileSync(join(ROOT, "static", "land.js"), "utf8");
  ok(/const SHADOW_Q = \[null, \{ map: 1024, cascades: 2, far: 90 \}, \{ map: 2048, cascades: 3, far: 200 \}, \{ map: 4096, cascades: 3, far: 320 \}\];/.test(page) && /csm = new CSMShadowNode\(sun, \{ cascades: q\.cascades, maxFar: q\.far, mode: "practical", lightMargin: 200 \}\);/.test(page) && /sun\.shadow\.shadowNode = csm;/.test(page),
    "the sun's shadow is cascaded by preset (2 cascades to 90 m, 3 to 200 m, 3 to 320 m)");
  ok(/f\.mesh\.castShadow = true;/.test(page) && /m\.maskShadowNode = s\.a\.greaterThan\(0\.4\);/.test(page) && /leaves\.maskShadowNode = s\.a\.greaterThan\(0\.42\);/.test(page) && /matGrass\.maskShadowNode = card\.a\.greaterThan\(0\.5\);/.test(page),
    "the far trees cast, and the far trees', the leaves' and the grass's shadows are their cards' cut-outs, not their rectangles");
  ok(/function shadowStrength\(v\)/.test(page) && /for \(const l of csm\.lights\) l\.shadow\.intensity = v;/.test(page) && /shadowStrength\(SET\.clouds \? cloudLitNow : 1\);/.test(page),
    "the sun's cast shadows fade under a cloud, on every cascade");
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
