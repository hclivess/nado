/*
 * test_a_piece_is_tilted_in_the_bag_placed_turned_and_aimed_at_in_the_page.mjs — ROTATION (#169: "maybe add fine
 * rotation if needed", operator 2026-11-10), walked in the real page against the real world server
 * (tests/_land_live_fixture.py) as a player on a phone, with taps only:
 *   1. the bag has Yaw, Pitch and Roll (degrees, to a tenth); set to 30°, 0°, 20° the piece info says "tilt 30° 0° 20°";
 *   2. Place puts a plank down turned so: the world server holds it with yaw 300, pitch 0, roll 200 (tenths);
 *   3. the player aims at the turned plank itself (/aim names it);
 *   4. /tilt 0 0 0 squares the piece in hand again; no page errors.
 *
 * Run:  node tests/test_a_piece_is_tilted_in_the_bag_placed_turned_and_aimed_at_in_the_page.mjs   (needs chrome, python3)
 */
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PROTOCOL_JS } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- the fixture: page + world server + fake exec on one origin ----------------------------------------------------
const work = mkdtempSync(join(tmpdir(), "nado-land-live-"));
writeFileSync(join(work, "protocol.js"), PROTOCOL_JS);
// TMPDIR: everything the fixture makes (its HOME, the world server's) lands in work, which cleanup removes — it is killed,
// so its own exit handlers never run (640 such directories were left in /tmp by 2026-11-08)
const fx = spawn("python3", [join(ROOT, "tests", "_land_live_fixture.py"), join(work, "protocol.js")], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, TMPDIR: work } });
let fxOut = "";
fx.stdout.on("data", (d) => { fxOut += d; });
fx.stderr.on("data", (d) => { fxOut += d; });
let HTTP = 0;
for (let i = 0; i < 240 && !HTTP; i++) { const m = fxOut.match(/PORT (\d+)/); if (m) HTTP = Number(m[1]); else await sleep(250); }
if (!HTTP) { console.log("FAIL the fixture did not start:\n" + fxOut.slice(-2000)); fx.kill("SIGKILL"); process.exit(1); }
const base = `http://127.0.0.1:${HTTP}`;
const getJ = async (p) => (await fetch(base + p)).json();
const { plot: PA } = await getJ("/fixture/plot");
const q = Wd.plotCoords(PA);
function spot(du, dv) {
  for (let d = 0; d < 8; d++) {
    const u = q.u0 + du + d, v = q.v0 + dv, top = Wd.column(q.face, u, v).top;
    if (Wd.terrainBlock(q.face, u, v, top + 1) === Wd.B.air && Wd.terrainBlock(q.face, u, v, top + 2) === Wd.B.air
        && Wd.column(q.face, u, v + 1).top === top && Wd.terrainBlock(q.face, u, v + 1, top + 1) === Wd.B.air)
      return { u: u + 0.5, v: v + 0.5, h: top + 1 };
  }
  throw new Error("no standing spot");
}

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 491) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landlive-"));
let chrome = null, ver = null;
const tried = [];
for (const bin of [process.env.CHROME, "google-chrome", "google-chrome-stable", "chromium-browser", "chromium"].filter(Boolean)) {
  const c = spawn(bin, ["--headless", "--disable-gpu", "--no-sandbox", "--use-angle=swiftshader", "--remote-debugging-port=" + PORT,
    "--user-data-dir=" + prof, "about:blank"], { stdio: "ignore" });
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
let id = 0; const pend = new Map(), frames = new Map(), errors = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
  if (m.method === "Network.webSocketFrameReceived") (frames.get(m.sessionId) || frames.set(m.sessionId, []).get(m.sessionId)).push(m.params.response.payloadData);
  if (m.method === "Runtime.exceptionThrown") errors.push(JSON.stringify(m.params.exceptionDetails).slice(0, 300));
});
const send = (sid, method, params) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params, sessionId: sid })); });
async function tab() {
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const sid = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  for (const d of ["Runtime", "Page", "Network"]) await send(sid, d + ".enable", {});
  await send(sid, "Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await send(sid, "Emulation.setDeviceMetricsOverride", { width: 900, height: 600, deviceScaleFactor: 1, mobile: true });
  return sid;
}
const evl = async (sid, expr) => {
  const r = await send(sid, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result.result.value;
};
const until = async (sid, expr, ms = 20000) => { for (let t = 0; t < ms; t += 250) { if (await evl(sid, expr).catch(() => false)) return true; await sleep(250); } return false; };
const hudText = (sid) => evl(sid, "document.getElementById('hudPos').textContent + ' | ' + document.getElementById('hudPlot').textContent");
async function open(sid, s) {
  await send(sid, "Page.navigate", { url: base + "/" });
  await until(sid, "document.readyState === 'complete'");
  await evl(sid, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${q.face}, ${s.u}, ${s.v}, ${s.h}, 0, -1.0] })); true`);
  await send(sid, "Page.reload", {});
  await until(sid, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 30000);
}



const EYE = 1.62;
async function stand(sid, u, v, h, yaw, pitch) {
  // the place is written from a page of the same origin that runs no game: written from the game page, the game still
  // booting there could save its own place over it before the reload (a test stood where the last one left it)
  await send(sid, "Page.navigate", { url: base + "/static/land-world.js" });
  await until(sid, "document.readyState === 'complete'");
  await evl(sid, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${q.face}, ${u}, ${v}, ${h}, ${yaw}, ${pitch}] })); true`);
  await send(sid, "Page.navigate", { url: base + "/" });
  await until(sid, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 30000);
  await until(sid, "/Your plot/.test(document.getElementById('hudPlot').textContent)", 20000);
  await evl(sid, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");
  await sleep(2500);
}
const shot = async (sid, name) => {
  if (!process.env.SHOTS) return;
  const r = await send(sid, "Page.captureScreenshot", { format: "png" });
  writeFileSync(join(process.env.SHOTS, name + ".png"), Buffer.from(r.result.data, "base64"));
};
const conType = async (sid, text) => {
  await send(sid, "Input.dispatchKeyEvent", { type: "keyDown", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await send(sid, "Input.dispatchKeyEvent", { type: "keyUp", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await until(sid, "document.activeElement && document.activeElement.id === 'conIn'", 8000);
  await send(sid, "Input.insertText", { text });                 // the / that opened the console is already in it
  await send(sid, "Input.dispatchKeyEvent", { type: "keyDown", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  await send(sid, "Input.dispatchKeyEvent", { type: "keyUp", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  await sleep(1500);
  return evl(sid, "document.getElementById('conLog').textContent.slice(-400)");
};
try {
  const { token } = await getJ("/fixture/owner_token");
  const PAid = (await getJ("/fixture/plot")).plot;
  await getJ(`/fixture/animal?kind=rabbit&u=${q.u0 + 400}&v=${q.v0 + 400}`);   // the herd held still and far off
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ planks: 10 })));
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const s0 = spot(4, 6);
  // looking down at the ground 2.5 m ahead (north)
  await stand(B, s0.u, s0.v, s0.h, 0, -Math.atan2(s0.h + EYE - Wd.column(q.face, Math.floor(s0.u), Math.floor(s0.v + 2.5)).height, 2.5));
  const tap = (sel) => evl(B, `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.click(); return true; })()`);

  // 1. tilt in the bag
  await tap("#tPal"); await sleep(800);
  ok(await evl(B, "!!document.getElementById('pzYaw') && !!document.getElementById('pzPitch') && !!document.getElementById('pzRoll')"), "the bag has Yaw, Pitch and Roll");
  await evl(B, `(() => { for (const [id, v] of [["pzYaw", 30], ["pzPitch", 0], ["pzRoll", 20]]) { const e = document.getElementById(id); e.value = String(v); e.dispatchEvent(new Event("change")); } return true; })()`);
  await tap("#palClose"); await sleep(500);
  await until(B, "!!document.querySelector('#hotbar .hs[title=\"Planks\"]')", 10000);
  await tap('#hotbar .hs[title="Planks"]');
  ok(await until(B, "document.getElementById('hotName').textContent === 'Planks'", 5000), "planks are in hand");
  const info = await evl(B, "document.getElementById('pieceInfo').textContent");
  ok(/tilt 30° 0° 20°/.test(info), "set to 30°, 0°, 20°, the piece info says so: " + info);

  // 2. placed turned
  await tap("#tPlace");
  let box = null;
  for (let t = 0; t < 30 && !box; t++) { await sleep(500); box = ((await getJ("/land/api/plot?plot=" + PAid)).boxes || []).find((b) => b[6] === Wd.B.planks) || null; }
  ok(box && box.length === 11 && box[8] === 300 && box[9] === 0 && box[10] === 200, "Place puts the plank down turned: the world server holds yaw 300, pitch 0, roll 200 — " + JSON.stringify(box));
  await sleep(2500);
  await shot(B, "tilted");

  // 3. aimed at
  const said = await conType(B, "aim");
  ok(/Aiming at Planks/.test(said), "the player aims at the turned plank itself: " + said.slice(-160));

  // 4. squared again
  const sq = await conType(B, "tilt 0 0 0");
  ok(!/tilt/.test(await evl(B, "document.getElementById('pieceInfo').textContent")), "/tilt 0 0 0 squares the piece in hand: " + sq.slice(-80));
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
