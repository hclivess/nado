/*
 * test_far_trees_stand_on_the_page_beyond_the_view_distance.mjs — #183, in the real page against the real world server
 * (operator 2026-11-11: "compared to this our game looks like from 1996"; measured: no tree drawn past 128 m).
 * A player in a meadow by a wood, the view distance at 3 chunks (48 m):
 *   1. the page bakes the far trees' atlas and its mesher workers build the forest tiles — the stats readout counts far
 *      trees, and comes to exactly the trees the world grows in every tile within the page's far-tree range;
 *   2. neither the bake (a render target read back from the GPU) nor the far-tree material throws or logs an error —
 *      a material that fails to compile is an error in the console and an invisible forest, not a failed build;
 *   3. the count holds still once the tiles are in (nothing is built again every tick).
 * The count is WAITED FOR, never judged by a quiet moment: a page hands out one mesher job a worker a frame, and on a
 * loaded machine the tiles behind the nearer chunks arrive after a pause longer than any "nothing changed for 4 s" —
 * this test failed that way in the suite (3,837 of 4,240, three jobs beside it) while the page was right.
 * SHOTS=<dir> writes the view for a pair of eyes: the test cannot tell a tree line from a green smear.
 *
 * Run: node tests/test_far_trees_stand_on_the_page_beyond_the_view_distance.mjs   (needs chrome, python3)
 */
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PROTOCOL_JS } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js")), F = await import(join(ROOT, "static", "land-forest.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- the fixture: page + world server + fake exec on one origin ----------------------------------------------------
const work = mkdtempSync(join(tmpdir(), "nado-land-live-"));
writeFileSync(join(work, "protocol.js"), PROTOCOL_JS);
// TMPDIR: everything the fixture makes lands in work, which cleanup removes (it is killed; its exit handlers never run)
const fx = spawn("python3", [join(ROOT, "tests", "_land_live_fixture.py"), join(work, "protocol.js")], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, TMPDIR: work } });
let fxOut = "";
fx.stdout.on("data", (d) => { fxOut += d; });
fx.stderr.on("data", (d) => { fxOut += d; });
let HTTP = 0;
for (let i = 0; i < 240 && !HTTP; i++) { const m = fxOut.match(/PORT (\d+)/); if (m) HTTP = Number(m[1]); else await sleep(250); }
if (!HTTP) { console.log("FAIL the fixture did not start:\n" + fxOut.slice(-2000)); fx.kill("SIGKILL"); process.exit(1); }
const base = `http://127.0.0.1:${HTTP}`;

// the place: a meadow with a wood ahead (the #183 viewpoint), looking north
const FACE = 0, U = 54260.5, V = 80600.5, H = Wd.column(FACE, Math.floor(U), Math.floor(V)).top + 1;
const tu = Math.floor(U / F.TILE), tv = Math.floor(V / F.TILE);
let around = 0;
for (let dv = -1; dv <= 1; dv++) for (let du = -1; du <= 1; du++) around += F.forestTile(FACE, tu + du, tv + dv).n;
// every tile the page wants (land.js updateForest: a tile whose nearest point is within the range), and its trees
const { readFileSync } = await import("node:fs");
// the page's full range, HALVED at the view this test loads with (view 3 = the Low preset: forestRange() in land.js,
// #150 — 26k far trees were nearly half the frame on Low); the settings below set view 3
const FULL = Number((/FOREST_RANGE = PHONE \? \d+ : (\d+)/.exec(readFileSync(join(ROOT, "static", "land.js"), "utf8")) || [])[1]);
const VIEW = 3, RANGE = VIEW <= 3 ? FULL / 2 : FULL;
let inRange = 0, tiles = 0;
for (let y = Math.floor((V - RANGE) / F.TILE); y <= Math.floor((V + RANGE) / F.TILE); y++)
  for (let x = Math.floor((U - RANGE) / F.TILE); x <= Math.floor((U + RANGE) / F.TILE); x++) {
    const du = Math.max(x * F.TILE - U, 0, U - (x + 1) * F.TILE), dv = Math.max(y * F.TILE - V, 0, V - (y + 1) * F.TILE);
    if (du * du + dv * dv <= RANGE * RANGE) { inRange += F.forestTile(FACE, x, y).n; tiles++; }
  }

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 523) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landlive-"));
let chrome = null, ver = null;
const tried = [];
for (const bin of [process.env.CHROME, "google-chrome", "google-chrome-stable", "chromium-browser", "chromium"].filter(Boolean)) {
  const c = spawn(bin, ["--headless", "--disable-gpu", "--no-sandbox", "--use-angle=swiftshader", "--remote-debugging-port=" + PORT,
    "--user-data-dir=" + prof, "--window-size=1280,720", "about:blank"], { stdio: "ignore" });
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
const farTrees = (sid) => evl(sid, "(() => { const m = /(\\d+) far trees/.exec(document.getElementById('hudGpu').textContent); return m ? Number(m[1]) : -1; })()");

try {
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const S = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  for (const d of ["Runtime", "Page"]) await send(S, d + ".enable", {});
  await send(S, "Emulation.setDeviceMetricsOverride", { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
  // the place and the settings are written from a page of the same origin that runs no game (the game would save over them)
  await send(S, "Page.navigate", { url: base + "/static/land-world.js" });
  await until(S, "document.readyState === 'complete'");
  await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${FACE}, ${U}, ${V}, ${H}, 0, -0.06] }));
    localStorage.setItem("nado_land_settings", JSON.stringify({ fov: 72, sens: 1, invert: 0, grass: 0, shadows: 0, effects: 0, borders: 0, stats: 1, res: 60, view: ${VIEW}, fps: 0, auto: 0, sv: 2 })); true`);
  await send(S, "Page.navigate", { url: base + "/" });
  ok(await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 60000), "the page loads in the meadow");
  await evl(S, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");

  // 1. the far trees arrive
  ok(await until(S, "/[1-9]\\d* far trees/.test(document.getElementById('hudGpu').textContent)", 180000), "the stats readout counts far trees");
  ok(RANGE > 0 && tiles > 9 && inRange > around && around > 100, `the page's reach at view ${VIEW} is read from land.js (${RANGE} m of ${FULL}: ${tiles} tiles, ${inRange} trees; ${around} in the player's tile and its neighbours)`);
  await until(S, `(() => { const m = /(\\d+) far trees/.exec(document.getElementById('hudGpu').textContent); return m && Number(m[1]) >= ${inRange}; })()`, 600000);
  const n = await farTrees(S);
  ok(n === inRange, `…exactly the trees the world grows within the range (${n} drawn, ${inRange} grow there)`);
  if (process.env.SHOTS) writeFileSync(join(process.env.SHOTS, "far_forest.png"), Buffer.from((await send(S, "Page.captureScreenshot", { format: "png" })).result.data, "base64"));

  // 3. the count holds still
  await sleep(6000);
  ok(await farTrees(S) === n, `the count holds still once the tiles are in (${n})`);

  // 2. no error from the bake or the material
  ok(errors.length === 0, "no page error (the atlas bakes, the far-tree material compiles)" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
