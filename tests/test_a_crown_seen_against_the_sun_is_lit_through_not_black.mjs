/*
 * test_a_crown_seen_against_the_sun_is_lit_through_not_black.mjs — #183 step 4, in the real page against the real world
 * server: the concept picture's trees have airy crowns, lit through; the game's leaf cards were lit by their normals alone
 * and a crown's far side was black ("bushes near-black inside"). land.js now adds the light coming THROUGH a leaf — in its
 * own colour, at LEAF_THROUGH of what a front-lit leaf reflects (a leaf absorbs ~85 % of 400–700 nm light, reflects ~10 %,
 * lets 2–5 % through: Notton & Blanke 1992) — where the viewer looks toward the sun through it. A player stands 7 m from
 * the fixture plot's tree, the clock held with the sun 40°+ up:
 *   1. the crown against the sun (the eye on the far side from it) and the crown with the sun behind the viewer are both
 *      photographed, the eye at the same distance, looking at the crown's middle;
 *   2. from each eye the view is photographed with the leaves lit through and with the setting off (Settings: Leaves lit
 *      through, /set leaves 0): against the sun the leaves are brighter by LEAF_LIFT_MIN of 255 at least (25 measured),
 *      and with the sun behind the viewer about as much (25): the sun stands over the crown and the viewer under it, so a
 *      leaf transmits diffusely to the viewer from either side.
 * SHOTS=<dir> writes both views.
 *
 * Run: node tests/test_a_crown_seen_against_the_sun_is_lit_through_not_black.mjs   (needs chrome, python3)
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

// the place: the fixture plot's one broadleaf, seen from 7 m on the side away from the sun (the crown against the sun)
// and from 7 m on the sun's side (the sun behind the viewer), the clock held at a moment the sun stands high over it
const { plot: PA } = await getJ("/fixture/plot"), q = Wd.plotCoords(PA);
const root = Wd.treeRoots(q.face, q.u0, q.v0, Wd.PLOT).find((r) => r.tree.kind !== "bush");
if (!root) { console.log("FAIL the fixture plot has no tree"); process.exit(1); }
const FACE = q.face, TU = root.wu + 0.5, TV = root.wv + 0.5, TOP = root.col.top + 1, CROWN = TOP + 0.75 * root.tree.height + 0.5;
const up = Wd.frameOf(FACE, TU, TV).up;
const W = 640, HH = 360;
let T0 = Date.now() / 1000;
for (let k = 0; k < 4000; k++) {                 // the next moment the sun is 40°+ up here (a day is 40 minutes)
  const t = Date.now() / 1000 + k * 2, s = Cosmos.sunFrom(Wd.PLANET, t - Cosmos.EPOCH).dir;
  if (s[0] * up[0] + s[1] * up[1] + s[2] * up[2] > Math.sin(0.7)) { T0 = t; break; }
}
const HOLD = Math.round(T0 * 1000);

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 839) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landleaf-"));
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

const LEAF_LIFT_MIN = 10;                                     // of 255: measured 28 on the fixture's broadleaf (2026-11-13)
try {
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const S = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  for (const d of ["Runtime", "Page"]) await send(S, d + ".enable", {});
  await send(S, "Emulation.setDeviceMetricsOverride", { width: W, height: HH, deviceScaleFactor: 1, mobile: false });
  await send(S, "Page.addScriptToEvaluateOnNewDocument", { source: `{ const r = Date.now.bind(Date), r0 = r(); Date.now = () => Math.round(${HOLD} + (r() - r0) / 1000); }` });
  // the sun over the tree: where its light comes from along the ground
  const fr = Wd.frameOf(FACE, TU, TV), sun = Cosmos.sunFrom(Wd.PLANET, HOLD / 1000 - Cosmos.EPOCH).dir;
  const sE = sun[0] * fr.east[0] + sun[1] * fr.east[1] + sun[2] * fr.east[2], sN = sun[0] * fr.north[0] + sun[1] * fr.north[1] + sun[2] * fr.north[2], sh = Math.hypot(sE, sN);
  const gE = sE / sh, gN = sN / sh, D = 7;
  const views = { against: [TU - gE * D, TV - gN * D], withSun: [TU + gE * D, TV + gN * D] };      // the eye away from the sun looks toward it through the crown; the other has it at its back
  const shots = {};
  for (const [name, [eu, ev]] of Object.entries(views)) {
    const eh = Wd.column(FACE, Math.floor(eu), Math.floor(ev)).top + 1, yaw = Math.atan2(TU - eu, TV - ev), pitch = Math.atan2(CROWN - (eh + 1.62), D);
    await send(S, "Page.navigate", { url: base + "/static/land-world.js" });
    await until(S, "document.readyState === 'complete'");
    await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${FACE}, ${eu}, ${ev}, ${eh}, ${yaw}, ${pitch}], at: 9e12 }));
      localStorage.setItem("nado_land_settings", JSON.stringify({ fov: 72, sens: 1, invert: 0, grass: 0, shadows: 0, effects: 0, borders: 0, stats: 1, res: 100, view: 2, fps: 0, auto: 0, sv: 2, clouds: 0 })); true`);
    await send(S, "Page.navigate", { url: base + "/" });
    ok(await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 60000), `the page loads ${name === "against" ? "on the far side of the tree from the sun" : "on the sun's side of the tree"}`);
    await evl(S, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");
    await until(S, "/ [1-9]\\d* chunks/.test(document.getElementById('hudGpu').textContent)", 120000);
    await sleep(8000);                                                                 // the tree's chunk meshed and drawn
    const hud = await evl(S, "document.getElementById('hudPos').textContent");
    // the overlays at the screen's middle (the aim line, the cross, the goal, the notices) are hidden for the photo
    await evl(S, "for (const id of ['aimLine', 'cross', 'goal', 'pickup', 'hudInfo', 'hotwrap', 'breakBar']) { const e = document.getElementById(id); if (e) e.style.visibility = 'hidden'; } true");
    await sleep(1500);
    const con = (line) => evl(S, `(() => { const i = document.getElementById('conIn'); i.value = ${JSON.stringify(line)}; i.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); i.value = ''; return true; })()`);
    await con("/set leaves 1"); await sleep(3000);
    const on = await shot(S);
    await con("/set leaves 0"); await sleep(3000);
    const off = await shot(S);
    shots[name] = { on: decodePng(on), off: decodePng(off) };
    if (process.env.SHOTS) { writeFileSync(join(process.env.SHOTS, `crown_${name}_on.png`), on); writeFileSync(join(process.env.SHOTS, `crown_${name}_off.png`), off); }
    console.log(`     ${name}: eye (${eu.toFixed(1)}, ${ev.toFixed(1)}, ${eh}) yaw ${yaw.toFixed(2)} pitch ${pitch.toFixed(2)} · ${hud.slice(0, 60)}`);
  }
  // the crown's LEAVES: the leaf-coloured pixels (green over red and blue) in a patch 160 px square at the screen's centre
  // (a broadleaf's crown at 7 m is ~25° across at 5 px/°) — the sky shows through a crown and must not be counted. From
  // each eye the same view with the leaves lit through and with the setting off: the difference is the light through them.
  const leaves = (I, J) => { let n = 0, s = 0; for (let y = I.h / 2 - 80; y < I.h / 2 + 80; y++) for (let x = I.w / 2 - 80; x < I.w / 2 + 80; x++) { const o = (y * I.w + x) * 4, r = J.px[o], g = J.px[o + 1], b = J.px[o + 2]; if (g > r + 8 && g > b + 8) { s += (I.px[o] + I.px[o + 1] + I.px[o + 2]) / 3 - (r + g + b) / 3; n++; } } return { n, d: s / Math.max(1, n) }; };
  const A = leaves(shots.against.on, shots.against.off), F = leaves(shots.withSun.on, shots.withSun.off);
  ok(A.n > 300 && F.n > 300, `leaf pixels found in both views (${A.n} against the sun, ${F.n} with it)`);
  ok(A.d >= LEAF_LIFT_MIN, `against the sun the leaves are lit through: ${A.d.toFixed(1)} of 255 brighter than with the light through them off (at least ${LEAF_LIFT_MIN})`);
  ok(F.d >= 5 && A.d >= F.d * 0.8, `with the sun behind the viewer the leaves lift too (${F.d.toFixed(1)} of 255): the sun stands over the crown and the viewer under it, so its undersides are lit through from either side (25 and 25 measured; a build with the normal flipped once more read 19 and 12 and left a bush's inside black)`);
  ok(A.d < 80, `…and no glare: the lift stays under 80 of 255 (${A.d.toFixed(1)})`);
  ok(errors.length === 0, "no page error" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
