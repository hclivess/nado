/*
 * test_a_player_drills_down_into_the_deep_and_stands_in_their_mine.mjs — THE DEEP (#129) walked in the real page against
 * the real world server (tests/_land_live_fixture.py):
 *   1. the plot's owner, with an iron pick and a drill, digs a shaft from the surface through the bedrock floor into
 *      the deep and a room there, through the world server's own API — every cell accepted;
 *   2. standing in that room, more than 100 m under the sea, the page draws the mine around them, they stand on its
 *      floor (they do not fall through the planet) and the HUD says how deep they are. No page errors.
 * SHOTS=<dir> also saves the view.
 *
 * Run:  node tests/test_a_player_drills_down_into_the_deep_and_stands_in_their_mine.mjs     (needs chromium, python3)
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
const fx = spawn("python3", [join(ROOT, "tests", "_land_live_fixture.py"), join(work, "protocol.js")], { stdio: ["ignore", "pipe", "pipe"] });
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
const SV = spot(3, 3), SO = spot(9, 3);

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 491) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landlive-"));
let chrome = null, ver = null;
const tried = [];
for (const bin of [process.env.CHROME, "chromium-browser", "chromium", "google-chrome", "google-chrome-stable"].filter(Boolean)) {
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



try {
  await getJ("/fixture/seed?who=owner&items=%7B%7D&tools=" + encodeURIComponent(JSON.stringify(["iron_pick", "shovel", "axe", "drill"])));
  const { token } = await getJ("/fixture/owner_token");
  // 1. the shaft and the room, cell by cell through the API (breaking takes time: a refusal for speed is waited out)
  const u = Math.floor(SO.u), v = Math.floor(SO.v), top = Math.floor(SO.h) - 1, FLOOR = -12;
  const cells = [];
  for (let h = top; h >= FLOOR; h--) cells.push([q.face, u, v, h]);
  for (let h = FLOOR; h <= FLOOR + 2; h++) for (let du = -1; du <= 1; du++) for (let dv = -1; dv <= 1; dv++) if (du || dv) cells.push([q.face, u + du, v + dv, h]);
  let refusedOther = null;
  for (const c of cells) {
    for (let tries = 0; tries < 40; tries++) {
      const r = await (await fetch(base + "/land/api/set", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({ cells: [[...c, 0]] }) })).json();
      if (!r.refused.length) break;
      const why = String(r.refused[0][1]);
      if (!/too fast|rate limited/.test(why)) { refusedOther = c.join(",") + ": " + why; break; }
      await sleep(400);
    }
    if (refusedOther) break;
  }
  ok(!refusedOther, `a shaft from the surface through the bedrock to layer ${FLOOR}, and a room there, are dug (${cells.length} cells)` + (refusedOther ? ": " + refusedOther : ""));

  // 2. standing in the mine
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  await open(B, { u: u + 0.5, v: v + 0.5, h: FLOOR });
  await evl(B, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");
  // the saved place underground is taken once the world server has sent the plot's edits (land.js pendingPlace)
  const depth = Math.round(FLOOR - Wd.SEA);
  await until(B, `document.getElementById('hudPos').textContent.includes('height ${depth} m')`, 30000);
  await sleep(3000);                                    // a few seconds standing there: still on the floor
  const hud = await hudText(B);
  ok(hud.includes(`height ${depth} m`), "they stand on the mine's floor, " + (-depth) + " m under the sea, and do not fall through: " + hud);
  // what is on screen (a WebGL canvas cannot be read back): a screenshot, decoded by the page itself
  const png = (await send(B, "Page.captureScreenshot", { format: "png" })).result.data;
  const px = await evl(B, `new Promise((res) => { const im = new Image(); im.onload = () => { const g = document.createElement('canvas'); g.width = 90; g.height = 60;
    const x = g.getContext('2d'); x.drawImage(im, 0, 0, 90, 60); const d = x.getImageData(0, 15, 90, 30).data; let rock = 0, sky = 0;
    for (let i = 0; i < d.length; i += 4) { const s = d[i] + d[i + 1] + d[i + 2]; if (s > 12 && s < 300 && d[i + 2] <= d[i] + 10) rock++; if (d[i + 2] > 150 && d[i + 2] > d[i] + 30) sky++; }
    res({ rock, sky }); }; im.src = 'data:image/png;base64,${png}'; })`);
  ok(px.rock > 300 && px.sky < 50, "the page draws the mine's rock around them, not open sky: " + JSON.stringify(px));
  if (process.env.SHOTS) { const r = await send(B, "Page.captureScreenshot", { format: "png" }); writeFileSync(join(process.env.SHOTS, "deep.png"), Buffer.from(r.result.data, "base64")); }
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
