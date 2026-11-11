/*
 * test_the_clouds_stand_in_the_pages_sky_where_the_reference_puts_them.mjs — #183 step 2, in the real page against the
 * real world server (operator 2026-11-11: "compared to this our game looks like from 1996"; the sky had no cloud).
 * The page marches land-clouds.js's density on the GPU into a sky map, a tile a frame, and draws it over the dome. A
 * player in the meadow looks up, with the clock held still (so the drifting field stands where the test computes it):
 *   1. the page finishes sky maps (the stats readout counts them) with no page error — a TSL march that fails to compile
 *      is an error in the console and an empty sky, not a failed build;
 *   2. the clouds are WHERE the JS reference (land-clouds.js march) puts them: the same view drawn again with the clouds
 *      turned off (/set clouds 0) differs strongly where the reference sees a heap and hardly at all where it sees clear
 *      sky — a map read upside down, turned, or in another frame than it was marched in fails this, and none of those is
 *      visible to a test that only counts.
 * SHOTS=<dir> writes both views for a pair of eyes.
 *
 * Run: node tests/test_the_clouds_stand_in_the_pages_sky_where_the_reference_puts_them.mjs   (needs chrome, python3)
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

// the place: the #183 meadow, looking up into the sky, the clock held at a moment the sun stands high
const FACE = 0, U = 54260.5, V = 80600.5, H = Wd.column(FACE, Math.floor(U), Math.floor(V)).top + 1, YAW = 0.4, PITCH = 0.75;
const W = 640, HH = 360;
const up = Wd.frameOf(FACE, U, V).up;
let T0 = Date.now() / 1000;
for (let k = 0; k < 4000; k++) {                 // the next moment the sun is 40°+ up here (a day is 40 minutes)
  const t = Date.now() / 1000 + k * 2, s = Cosmos.sunFrom(Wd.PLANET, t - Cosmos.EPOCH).dir;
  if (s[0] * up[0] + s[1] * up[1] + s[2] * up[2] > Math.sin(0.7)) { T0 = t; break; }
}
const HOLD = Math.round(T0 * 1000);

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 811) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landclouds-"));
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
  // the clock, held: Date.now() stands at HOLD (it creeps a millisecond a thousand, so nothing that waits on it hangs)
  await send(S, "Page.addScriptToEvaluateOnNewDocument", { source: `{ const r = Date.now.bind(Date), r0 = r(); Date.now = () => Math.round(${HOLD} + (r() - r0) / 1000); }` });
  await send(S, "Page.navigate", { url: base + "/static/land-world.js" });
  await until(S, "document.readyState === 'complete'");
  await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${FACE}, ${U}, ${V}, ${H}, ${YAW}, ${PITCH}] }));
    localStorage.setItem("nado_land_settings", JSON.stringify({ fov: 72, sens: 1, invert: 0, grass: 0, shadows: 0, effects: 0, borders: 0, stats: 1, res: 100, view: 2, fps: 0, auto: 0, sv: 2, clouds: 1 })); true`);
  await send(S, "Page.navigate", { url: base + "/" });
  ok(await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 60000), "the page loads in the meadow");
  await evl(S, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");

  // 1. sky maps are finished
  ok(await until(S, "/[1-9]\\d* sky maps/.test(document.getElementById('hudGpu').textContent)", 600000), "the page finishes a sky map (the stats readout counts it)");
  const n0 = await maps(S);
  ok(await until(S, `/(\\d+) sky maps/.exec(document.getElementById('hudGpu').textContent)[1] > ${n0}`, 600000), "…and marches the next one behind it");
  const place = await evl(S, "JSON.parse(localStorage.getItem('nado_land_v1') || '{}').p || null");

  // 2. where the reference puts them: the view with clouds, then without
  const withC = await shot(S);
  await evl(S, `(() => { const i = document.getElementById('conIn'); i.value = '/set clouds 0'; i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); i.value = ''; return true; })()`);
  await sleep(4000);
  const noC = await shot(S);
  if (process.env.SHOTS) { writeFileSync(join(process.env.SHOTS, "clouds_on.png"), withC); writeFileSync(join(process.env.SHOTS, "clouds_off.png"), noC); }
  const A = decodePng(withC), B = decodePng(noC);
  // the camera, as land.js builds it (eyePos, look, a 72° vertical field) at the place the page holds
  const [f, u, v, h, yaw, pitch] = place || [FACE, U, V, H, YAW, PITCH], fr = Wd.frameOf(f, u, v), eye = Wd.posOf(f, u, v, h + 1.62);
  const cp = Math.cos(pitch), fw = [0, 1, 2].map((i) => cp * (Math.sin(yaw) * fr.east[i] + Math.cos(yaw) * fr.north[i]) + Math.sin(pitch) * fr.up[i]);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]], norm = (a) => { const l = Math.hypot(...a); return a.map((x) => x / l); };
  const right = norm(cross(fw, fr.up)), cu = cross(right, fw), th = Math.tan((36 * Math.PI) / 180);
  const sun = Cosmos.sunFrom(Wd.PLANET, HOLD / 1000 - Cosmos.EPOCH).dir;
  const L = C.light(sun, [2.4, 2.3, 2.1], [0.47, 0.67, 0.86], [0.03, 0.16, 0.58]), dr = C.drift(HOLD / 1000 - Cosmos.EPOCH), vol = C.noiseVolume();
  let inN = 0, inD = 0, outN = 0, outD = 0;
  for (let y = 110; y < A.h - 40; y += 6) for (let x = 8; x < A.w - 8; x += 6) {      // (clear of the corner texts)
    const sx = ((2 * (x + 0.5)) / A.w - 1) * th * (A.w / A.h), sy = (1 - (2 * (y + 0.5)) / A.h) * th;
    const d = norm([0, 1, 2].map((i) => fw[i] + right[i] * sx + cu[i] * sy));
    if (d[0] * fr.up[0] + d[1] * fr.up[1] + d[2] * fr.up[2] < 0.12) continue;      // the sky only
    const a = C.march(vol, eye, d, L, dr)[3], o = (y * A.w + x) * 4;
    const diff = (Math.abs(A.px[o] - B.px[o]) + Math.abs(A.px[o + 1] - B.px[o + 1]) + Math.abs(A.px[o + 2] - B.px[o + 2])) / 3;
    if (a > 0.8) { inN++; inD += diff; } else if (a < 0.02) { outN++; outD += diff; }
  }
  ok(inN > 40 && outN > 40, `the view holds both heaps and clear sky by the reference (${inN} and ${outN} sampled pixels)`);
  ok(inN > 0 && inD / inN > 25, `the page draws a cloud where the reference sees a heap (mean change ${(inD / Math.max(1, inN)).toFixed(1)} of 255)`);
  ok(outN > 0 && outD / outN < 8, `…and clear sky where it sees none (mean change ${(outD / Math.max(1, outN)).toFixed(1)} of 255)`);
  ok(errors.length === 0, "no page error (the march compiles, the map is drawn)" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
