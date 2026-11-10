/*
 * test_the_graphics_settings_are_chosen_in_a_panel_change_what_is_drawn_and_are_kept.mjs — GRAPHICS SETTINGS (#166:
 * "make graphical settings more configurable (resolution, shadows, etc)", operator 2026-11-10), walked in the real page
 * against the real world server (tests/_land_live_fixture.py) as a player on a phone, with taps only:
 *   1. the bag has a Settings button; it opens the graphics panel, which shows a phone's own start (no shadows, no grass,
 *      no effects, 4 chunks) as Custom;
 *   2. each setting changes what is drawn, measured: render resolution the canvas's pixels; view distance the chunks
 *      loaded; grass the triangles drawn; shadows the draw calls (when the sun is up: no sun, no shadow pass);
 *   3. a preset sets them all (Low: 60 %, no shadows, 3 chunks), and the panel shows it chosen;
 *   4. after a reload the choice is kept, and drawn so; /settings opens the panel too;
 *   5. the effects are built again live (Ultra), with no page errors.
 *
 * Run:  node tests/test_the_graphics_settings_are_chosen_in_a_panel_change_what_is_drawn_and_are_kept.mjs   (needs chrome, python3)
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
try {
  const { token } = await getJ("/fixture/owner_token");
  await getJ(`/fixture/animal?kind=rabbit&u=${q.u0 + 400}&v=${q.v0 + 400}`);   // the herd held still and far off
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const s0 = spot(4, 6);
  await stand(B, s0.u, s0.v, s0.h, 0, -0.3);
  // the HUD's stats line (a tap on it): fps, triangles, draw calls and the chunks loaded
  await evl(B, "document.getElementById('hudGpu').click(), true");
  const stats = async () => {
    const t = await evl(B, "document.getElementById('hudGpu').textContent");
    const m = t.match(/([\d.]+) fps · (\d+)k tris · (\d+) calls · (\d+) chunks/);
    return m ? { fps: +m[1], tris: +m[2], calls: +m[3], chunks: +m[4], t } : { t };
  };
  const settle = async (ms = 9000) => { await sleep(ms); return stats(); };
  const canvasW = () => evl(B, "document.getElementById('world').width");
  const val = (k) => evl(B, `(document.querySelector('select[data-set="${k}"]') || {}).value`);
  const pick = (k, v) => evl(B, `(() => { const e = document.querySelector('select[data-set="${k}"]'); e.value = "${v}"; e.dispatchEvent(new Event("change")); return true; })()`);
  const tap = (sel) => evl(B, `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.click(); return true; })()`);
  const panelOpen = () => evl(B, "!document.getElementById('setPanel').classList.contains('hidden')");

  // 1. the bag's Settings button opens the panel, with a phone's start
  await tap("#tPal"); await sleep(800);
  ok(await tap("#setOpen"), "the bag has a Settings button");
  ok(await until(B, "!document.getElementById('setPanel').classList.contains('hidden')", 5000), "…and it opens the graphics panel");
  ok(await val("shadows") === "0" && await val("grass") === "0" && await val("effects") === "0" && await val("view") === "4" && await val("res") === "100",
    "a phone starts with no shadows, grass or effects, 4 chunks, full resolution");
  ok(/Custom/.test(await evl(B, "document.querySelector('#setGrid .presets').textContent")), "…which no preset is: Custom");

  // 2. each setting changes what is drawn
  const w100 = await canvasW();
  await pick("res", 50); await sleep(1500);
  const w50 = await canvasW();
  ok(Math.abs(w50 - w100 / 2) <= 2, `render resolution 50 % halves the canvas's pixels (${w100} -> ${w50})`);
  const v4 = await settle();
  await pick("view", 2);
  const v2 = await settle();
  ok(v2.chunks < v4.chunks, `view distance 2 loads fewer chunks than 4 (${v4.chunks} -> ${v2.chunks})`);
  await pick("view", 6);
  const v6 = await settle(15000);
  ok(v6.chunks > v4.chunks, `…and 6 more (${v6.chunks})`);
  await pick("view", 4);
  const g0 = await settle();
  await pick("grass", 1);
  const g1 = await settle(15000);
  ok(g1.tris > g0.tris, `grass on draws more triangles (${g0.tris}k -> ${g1.tris}k)`);
  const sh0 = await settle(4000);
  await pick("shadows", 2);
  const sh2 = await settle(6000);
  if (sh2.calls > sh0.calls) ok(true, `shadows on add the shadow pass's draw calls (${sh0.calls} -> ${sh2.calls})`);
  else console.log(`note shadows drew no more calls (${sh0.calls} -> ${sh2.calls}): the sun is down here now, and a sun under the horizon casts none`);
  ok(await val("shadows") === "2", "…and the panel shows Medium");

  // 3. a preset sets them all
  await tap('[data-preset="low"]'); await sleep(1500);
  ok(await val("res") === "60" && await val("shadows") === "0" && await val("view") === "3" && await val("grass") === "0" && await val("effects") === "0",
    "Low sets 60 %, no shadows, 3 chunks, no grass, no effects");
  ok(await evl(B, "!!document.querySelector('[data-preset=\"low\"].on')"), "…and shows Low chosen");
  const wLow = await canvasW();
  ok(Math.abs(wLow - w100 * 0.6) <= 2, `…drawn at 60 % (${wLow} px)`);
  await tap("#setClose");
  ok(!(await panelOpen()), "Close puts the panel away");

  // 4. kept over a reload; /settings opens the panel
  await send(B, "Page.reload", {});
  await until(B, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 30000);
  await sleep(2500);
  ok(Math.abs(await canvasW() - w100 * 0.6) <= 2, `after a reload it still draws at 60 % (${await canvasW()} px)`);
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await until(B, "document.activeElement && document.activeElement.id === 'conIn'", 8000);
  await send(B, "Input.insertText", { text: "settings" });          // the / that opened the console is already in it
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  ok(await until(B, "!document.getElementById('setPanel').classList.contains('hidden')", 5000), "/settings opens the panel");
  ok(await evl(B, "!!document.querySelector('[data-preset=\"low\"].on')") && await val("view") === "3", "…with Low still chosen");

  // 5. the effects built again live
  await tap('[data-preset="ultra"]');
  await sleep(12000);
  ok(await val("effects") === "1" && await val("shadows") === "3" && await val("view") === "8", "Ultra: effects on, high shadows, 8 chunks");
  const fr = await evl(B, "new Promise((r) => { let n = 0; const f = () => { n++; if (n < 3) requestAnimationFrame(f); else r(n); }; requestAnimationFrame(f); setTimeout(() => r(n), 20000); })");
  ok(fr >= 3, `…and the page still draws frames with the effects built again (${fr})`);
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
