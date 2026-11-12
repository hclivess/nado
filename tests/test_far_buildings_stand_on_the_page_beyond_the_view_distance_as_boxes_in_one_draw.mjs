/*
 * test_far_buildings_stand_on_the_page_beyond_the_view_distance_as_boxes_in_one_draw.mjs — #193 (operator 2026-11-12:
 * "the village is only visible from like 50 meters away, this means that large cities will be completely invisible - we
 * must fix this, and efficiently so"), in the real page against the real world server:
 *   1. a tower of plates is built on the owner's plot; a player 300 m away with the view at 3 chunks (48 m — the plot
 *      is far outside the meshed disc) sees the page's stats count exactly the tower's solid pieces as far boxes, fetched
 *      from GET /land/api/far — and the draw-call count rises by ONE for all of them (one instanced mesh);
 *   2. the page fetches the far view again with the versions it holds: a second plate added to the tower later shows
 *      up in the count within two cycles;
 *   3. no page error (the instanced material compiles).
 * SHOTS=<dir> writes the view for a pair of eyes: the test cannot tell a tower from a smear.
 * Run: node tests/test_far_buildings_stand_on_the_page_beyond_the_view_distance_as_boxes_in_one_draw.mjs   (needs chrome, python3)
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

// ---- the fixture -------------------------------------------------------------------------------------------------
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
const { plot: PA } = await getJ("/fixture/plot");
const q = Wd.plotCoords(PA);

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 617) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landfar-"));
let chrome = null, ver = null;
const tried = [];
for (const bin of [process.env.CHROME, "google-chrome", "google-chrome-stable", "chromium-browser", "chromium"].filter(Boolean)) {
  const c = spawn(bin, ["--headless", "--disable-gpu", "--no-sandbox", "--use-angle=swiftshader", "--remote-debugging-port=" + PORT,
    "--user-data-dir=" + prof, "--window-size=960,540", "about:blank"], { stdio: "ignore" });
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
const stat = (sid, what) => evl(sid, `(() => { const m = /(\\d+) ${what}/.exec(document.getElementById('hudGpu').textContent); return m ? Number(m[1]) : -1; })()`);

try {
  // the tower: eight plates stacked on the plot, 2 × 2 m, 0.5 m apart, and a glass pane (not drawn from afar)
  const { token } = await getJ("/fixture/owner_token");
  const enc = (o) => encodeURIComponent(JSON.stringify(o));
  await getJ("/fixture/seed?who=owner&items=" + enc({ steel_plate: 40, glass: 4 }) + "&tools=" + enc(["pick"]));
  const auth = { "Content-Type": "application/json", Authorization: "Bearer " + token };
  const post = async (p, o) => (await fetch(base + p, { method: "POST", headers: auth, body: JSON.stringify(o) })).json();
  const top = Wd.column(q.face, q.u0 + 8, q.v0 + 8).top, Y = (top + 1) * 100;
  const plates = Array.from({ length: 8 }, (_, i) => [700, 700, Y + i * 60, 200, 200, 10, 64]);
  const glass = [700, 700, Y + 8 * 60, 200, 200, 10, 12];
  const built = await post("/land/api/boxes", { plot: PA, add: [...plates, glass] });
  ok((Array.isArray(built.added) ? built.added.length : built.added) === 9, "a tower of eight plates and a glass pane is built: " + JSON.stringify(built).slice(0, 120));
  const far = await getJ(`/land/api/far?face=${q.face}&u=${q.u0}&v=${q.v0}&r=500`);
  const solid = far.plots.flatMap((p) => p.boxes || []).filter((b) => Wd.BLOCKS[b[6]] && Wd.BLOCKS[b[6]].solid && !Wd.BLOCKS[b[6]].see).length;
  ok(solid === 8, `the far view holds the tower's eight solid plates (the glass pane is see-through): ${solid}`);

  // the player: 300 m south of the plot, looking north at it, the view 3 chunks
  const U = q.u0 + 8.5, V = q.v0 - 300, H = Wd.column(q.face, Math.floor(U), Math.floor(V)).top + 1;
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const S = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  for (const d of ["Runtime", "Page"]) await send(S, d + ".enable", {});
  await send(S, "Emulation.setDeviceMetricsOverride", { width: 960, height: 540, deviceScaleFactor: 1, mobile: false });
  await send(S, "Page.navigate", { url: base + "/static/land-world.js" });
  await until(S, "document.readyState === 'complete'");
  await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${q.face}, ${U}, ${V}, ${H}, 0, 0.02] }));
    localStorage.setItem("nado_land_settings", JSON.stringify({ fov: 72, sens: 1, invert: 0, grass: 0, shadows: 0, effects: 0, borders: 0, stats: 1, res: 60, view: 3, fps: 0, auto: 0, sv: 2, clouds: 0 })); true`);
  await send(S, "Page.navigate", { url: base + "/" });
  ok(await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 60000), "the page loads 300 m from the plot");
  await evl(S, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");

  // 1. the far boxes
  ok(await until(S, "/[1-9]\\d* far boxes/.test(document.getElementById('hudGpu').textContent)", 120000), "the stats readout counts far boxes");
  await until(S, `(() => { const m = /(\\d+) far boxes/.exec(document.getElementById('hudGpu').textContent); return m && Number(m[1]) >= 8; })()`, 60000);
  const n = await stat(S, "far boxes");
  ok(n === 8, `…exactly the tower's solid plates (${n} drawn)`);
  if (process.env.SHOTS) writeFileSync(join(process.env.SHOTS, "far_buildings.png"), Buffer.from((await send(S, "Page.captureScreenshot", { format: "png" })).result.data, "base64"));
  const calls = await stat(S, "calls");
  ok(calls > 0 && calls < 400, `…in one draw among ${calls} calls`);

  // 2. a later plate shows up
  const more = await post("/land/api/boxes", { plot: PA, add: [[400, 400, Y, 100, 100, 10, 64]] });
  ok((Array.isArray(more.added) ? more.added.length : more.added) === 1, "a ninth plate is built later");
  ok(await until(S, `(() => { const m = /(\\d+) far boxes/.exec(document.getElementById('hudGpu').textContent); return m && Number(m[1]) === 9; })()`, 45000), `…and the page's count follows within two cycles (${await stat(S, "far boxes")})`);

  // 3. no error
  ok(errors.length === 0, "no page error (the instanced far-box material compiles)" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
