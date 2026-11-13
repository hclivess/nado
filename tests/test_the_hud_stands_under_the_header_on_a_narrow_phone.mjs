/*
 * test_the_hud_stands_under_the_header_on_a_narrow_phone.mjs — #139 (measured on land.nadochain.com at 412 px wide: the
 * header's wallet button wrapped onto a second line and covered the plot line, which sat at a fixed 52 px). land.js
 * hudUnderHeader places the HUD block 6 px under the header's actual bottom edge whenever the header's size changes.
 * In the real page at 412 × 915, signed out (the button reads "Connect wallet"), and again at 1280 × 720:
 *   1. the wallet button and the HUD block do not overlap; the HUD's top is under the button's bottom;
 *   2. on a wide screen the HUD keeps its place at 52 px (the header is one line there).
 * Run: node tests/test_the_hud_stands_under_the_header_on_a_narrow_phone.mjs   (needs chrome, python3)
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
const getJ = async (p) => (await fetch(base + p)).json();

const { plot: PA } = await getJ("/fixture/plot"), q = Wd.plotCoords(PA);
const FACE = q.face, U = q.u0 + 8.5, V = q.v0 + 8.5, TOP = Wd.column(FACE, Math.floor(U), Math.floor(V)).top + 1;
const W = 412, HH = 915;

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 271) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landhud-"));
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
  await send(S, "Page.navigate", { url: base + "/static/land-world.js" });
  await until(S, "document.readyState === 'complete'");
  await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${FACE}, ${U}, ${V}, ${TOP}, 0, -0.1], at: 9e12 })); true`);
  const rects = () => evl(S, "(() => { const r = (e) => { if (!e) return null; const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; }; return { w: r(document.getElementById('hdrWallet')), hud: r(document.getElementById('hudInfo')), hdr: r(document.querySelector('header')) }; })()");
  const overlap = (a, b) => a && b && a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
  for (const [w, h, mobile] of [[412, 915, true], [1280, 720, false]]) {
    await send(S, "Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile });
    await send(S, "Page.navigate", { url: base + "/" });
    ok(await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden') && !!document.getElementById('hdrWallet')", 90000), `the page loads at ${w} × ${h}`);
    await sleep(2500);
    const r = await rects();
    if (w === 412) {
      ok(r.w && r.hud && !overlap(r.w, r.hud) && r.hud[1] >= r.w[3], `at 412 px the wallet button (${r.w.map(Math.round)}) and the HUD block (top ${Math.round(r.hud[1])}) do not overlap; the HUD starts under the button`);
    } else {
      ok(r.hud && Math.round(r.hud[1]) === 52 && !overlap(r.w, r.hud), `at 1280 px the HUD keeps its place at 52 px (top ${Math.round(r.hud[1])})`);
    }
  }
  ok(errors.length === 0, "no page error" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
