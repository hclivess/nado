/*
 * test_the_clouds_cast_their_shadows_over_the_land_in_the_page.mjs — #183 step 4, in the real page against the real world
 * server: the concept picture's far ground is mottled with cloud shadows; the game's light was one value for the whole
 * scene. land.js now renders a cloud shadow map (each texel land-clouds.js sunLit at that ground point) and shades every
 * lit material of the land by it. A player hangs 400 m over the meadow in free flight, looking down, the clock held:
 *   1. the page renders shadow maps (the stats readout counts them) with no page error — a TSL shadow march that fails
 *      to compile is an error in the console and an unshaded land, not a failed build;
 *   2. the shade lies WHERE the reference puts it: the same view drawn again with the clouds off (/set clouds 0) is
 *      brighter where the reference's sunLit says the ground is in a heap's shadow, and about the same where it says
 *      the sun reaches — each pixel's ray dropped to the ground's sphere, the point read in the reference. A map read in
 *      the wrong frame, mirrored, or scaled to the wrong span fails this, and none of those is visible to a count.
 * SHOTS=<dir> writes both views.
 *
 * Run: node tests/test_the_clouds_cast_their_shadows_over_the_land_in_the_page.mjs   (needs chrome, python3)
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
const PORT = 9300 + ((process.pid + 613) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landshadow-"));
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
    localStorage.setItem("nado_land_settings", JSON.stringify({ fov: 72, sens: 1, invert: 0, grass: 0, shadows: 0, effects: 0, borders: 0, stats: 1, res: 100, view: 2, fps: 0, auto: 0, sv: 2, clouds: 1 })); true`);
  await send(S, "Page.navigate", { url: base + "/" });
  ok(await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 60000), "the page loads over the meadow");
  await evl(S, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");
  // free flight, at once: the player would fall the 400 m otherwise (the console's /fly, as a player types it)
  const con = (line) => evl(S, `(() => { const i = document.getElementById('conIn'); i.value = ${JSON.stringify(line)}; i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); i.value = ''; return true; })()`);
  await con("/fly");
  ok(await until(S, "/Flying/.test(document.getElementById('conLog').textContent)", 10000), "…and hangs in free flight (/fly)");

  // 1. shadow maps are rendered
  ok(await until(S, "/[1-9]\\d* shadow maps/.test(document.getElementById('hudGpu').textContent)", 300000), "the page renders a cloud shadow map (the stats readout counts it)");
  await sleep(4000);                                                                 // a second map at the eye where it hangs

  // 2. where the reference puts the shade: the view with the clouds, then without
  // the eye's height: the HUD's "height N m" over the sea (the saved place is written on events only — it read the
  // height set before the fall the page took until /fly caught it)
  const hudH = async () => Number((/height (-?\d+) m/.exec(await evl(S, "document.getElementById('hudPos').textContent")) || [])[1]);
  const h1 = await hudH();
  const withC = await shot(S);
  await con("/set clouds 0");
  await sleep(4000);
  const noC = await shot(S);
  const h2 = await hudH();
  ok(Number.isFinite(h1) && h1 === h2 && h1 + Wd.SEA > TOP + 60, `the eye hung still between the two views, ${h1} m over the sea (${h1 + Wd.SEA - TOP} m over the meadow)`);
  const place = [FACE, U, V, h1 + Wd.SEA, YAW, PITCH];
  if (process.env.SHOTS) { writeFileSync(join(process.env.SHOTS, "shadows_on.png"), withC); writeFileSync(join(process.env.SHOTS, "shadows_off.png"), noC); }
  const A = decodePng(withC), B = decodePng(noC);
  const [f, u, v, h, yaw, pitch] = place || [FACE, U, V, H, YAW, PITCH], fr = Wd.frameOf(f, u, v), eye = Wd.posOf(f, u, v, h + 1.62);
  const cp = Math.cos(pitch), fw = [0, 1, 2].map((i) => cp * (Math.sin(yaw) * fr.east[i] + Math.cos(yaw) * fr.north[i]) + Math.sin(pitch) * fr.up[i]);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]], norm = (a) => { const l = Math.hypot(...a); return a.map((x) => x / l); };
  const right = norm(cross(fw, fr.up)), cu = cross(right, fw), th = Math.tan((36 * Math.PI) / 180);
  const sun = Cosmos.sunFrom(Wd.PLANET, HOLD / 1000 - Cosmos.EPOCH).dir, dr = C.drift(HOLD / 1000 - Cosmos.EPOCH), vol = C.noiseVolume();
  const Rg = Math.hypot(...Wd.posOf(f, u, v, TOP)), E2 = eye[0] * eye[0] + eye[1] * eye[1] + eye[2] * eye[2];
  let shadeN = 0, shadeOn = 0, shadeOff = 0, litN = 0, litOn = 0, litOff = 0, lo = 1, hi = 0;
  for (let y = 110; y < A.h - 40; y += 4) for (let x = 8; x < A.w - 8; x += 4) {          // (clear of the corner texts)
    const sx = ((2 * (x + 0.5)) / A.w - 1) * th * (A.w / A.h), sy = (1 - (2 * (y + 0.5)) / A.h) * th;
    const d = norm([0, 1, 2].map((i) => fw[i] + right[i] * sx + cu[i] * sy));
    const ed = eye[0] * d[0] + eye[1] * d[1] + eye[2] * d[2], disc = ed * ed - (E2 - Rg * Rg);
    if (disc <= 0) continue;
    const tt = -ed - Math.sqrt(disc);                                                  // the ray's drop to the ground's sphere at the meadow's height
    if (tt <= 0 || tt > 900) continue;                                                 // near the nadir: the relief's error in the point stays small
    const P = [eye[0] + d[0] * tt, eye[1] + d[1] * tt, eye[2] + d[2] * tt], l = C.sunLit(vol, P, sun, dr), o = (y * A.w + x) * 4;
    lo = Math.min(lo, l); hi = Math.max(hi, l);
    const on = (A.px[o] + A.px[o + 1] + A.px[o + 2]) / 3, off = (B.px[o] + B.px[o + 1] + B.px[o + 2]) / 3;
    if (off < 12) continue;                                                            // (black: nothing drawn there)
    if (l < 0.35) { shadeN++; shadeOn += on; shadeOff += off; } else if (l > 0.97) { litN++; litOn += on; litOff += off; }
  }
  const rS = shadeOn / Math.max(1, shadeOff), rL = litOn / Math.max(1, litOff);
  ok(shadeN > 40 && litN > 40, `the view holds ground in a heap's shadow and ground in the sun by the reference (${shadeN} and ${litN} sampled pixels; sunLit ${lo.toFixed(2)}..${hi.toFixed(2)})`);
  ok(litN > 0 && rL > 0.82 && rL < 1.12, `where the sun reaches, the clouds change the ground little (on/off brightness ${rL.toFixed(3)})`);
  ok(shadeN > 0 && rS < rL - 0.12, `where the reference puts a heap's shadow the ground is darker with the clouds on (on/off ${rS.toFixed(3)} against ${rL.toFixed(3)} in the sun)`);
  ok(errors.length === 0, "no page error (the shadow march compiles, the map is read)" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
