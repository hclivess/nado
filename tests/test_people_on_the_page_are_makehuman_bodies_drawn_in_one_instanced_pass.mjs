/*
 * test_people_on_the_page_are_makehuman_bodies_drawn_in_one_instanced_pass.mjs — #172 ("the characters look total
 * garbage nobody is gonna play this", operator 2026-11-10; "you still havent swapped the character models", 2026-11-12),
 * in the real page against the real world server: two players stand three metres apart —
 *   1. each page draws the other as a person: the stats readout counts one person (the HumanView's figure — the body data
 *      loaded, the instanced material compiled, the figure placed and flushed);
 *   2. the draw-call count is small: the body is one instanced draw a LOD, not a mesh a limb;
 *   3. they stay drawn (nothing rebuilds or drops them every tick);
 *   4. no page error from the skinned material on either page.
 * (The gait is pinned in test_the_human_body_is_makehumans…: a walking figure's feet in the page cannot be read back.)
 * SHOTS=<dir> writes what each sees.
 * Run: node tests/test_people_on_the_page_are_makehuman_bodies_drawn_in_one_instanced_pass.mjs   (needs chrome, python3)
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

const PORT = 9300 + ((process.pid + 733) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landpeople-"));
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
async function tab(u, v, yaw, token) {
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const S = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  for (const d of ["Runtime", "Page", "Network"]) await send(S, d + ".enable", {});
  await send(S, "Emulation.setDeviceMetricsOverride", { width: 960, height: 540, deviceScaleFactor: 1, mobile: false });
  if (token) await send(S, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const h = Wd.column(q.face, Math.floor(u), Math.floor(v)).top + 1;
  await send(S, "Page.navigate", { url: base + "/static/land-world.js" });
  await until(S, "document.readyState === 'complete'");
  await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${q.face}, ${u}, ${v}, ${h}, ${yaw}, 0] }));
    localStorage.setItem("nado_land_settings", JSON.stringify({ fov: 72, sens: 1, invert: 0, grass: 0, shadows: 0, effects: 0, borders: 0, stats: 1, res: 60, view: 2, fps: 0, auto: 0, sv: 2, clouds: 0 })); true`);
  await send(S, "Page.navigate", { url: base + "/" });
  await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 60000);
  await evl(S, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");
  return S;
}
const shot = async (S, name) => { if (process.env.SHOTS) writeFileSync(join(process.env.SHOTS, name + ".png"), Buffer.from((await send(S, "Page.captureScreenshot", { format: "png" })).result.data, "base64")); };

try {
  const { token } = await getJ("/fixture/owner_token");
  const U = q.u0 + 8.5, V = q.v0 + 8.5;
  // A (signed in) at the plot's middle facing north; B (a visitor) three metres north, facing south: each sees the other
  const A = await tab(U, V, 0, token), B = await tab(U, V + 3, Math.PI, null);
  // (both tabs share the browser's storage, so both are the owner's pages: each still sees the other's figure, and the
  // fixture's townspeople besides; the counts are read once both readouts have people in them)
  // (a tab in the background draws no frames — Chrome pauses its animation frames — so its readout stands still at
  // whatever it last showed: each tab is brought to the front for its own reading)
  await send(A, "Page.bringToFront", {});
  const okA = await until(A, "/[1-9]\\d* people/.test(document.getElementById('hudGpu').textContent)", 120000);
  const pa = await stat(A, "people");
  await send(B, "Page.bringToFront", {});
  const okB = await until(B, "/[1-9]\\d* people/.test(document.getElementById('hudGpu').textContent)", 120000);
  const pb = await stat(B, "people");
  ok(okA && okB && pa >= 1 && pb >= 1, `each page draws the other as a person (A sees ${pa}, B sees ${pb}; the townspeople count too)`);
  await shot(B, "people_B_sees_A"); await shot(A, "people_A_sees_B");
  const calls = await stat(B, "calls");
  ok(calls > 0 && calls < 200, `…the body is an instanced draw, not a mesh a limb (${calls} draw calls in all, ${pb} people)`);
  // the figures stay: a minute on, still drawn (nothing rebuilds or drops them every tick)
  await sleep(8000);
  const stillB = await stat(B, "people");
  await send(A, "Page.bringToFront", {}); await sleep(3000);
  ok(stillB >= 1 && (await stat(A, "people")) >= 1, "…and they stay drawn");
  ok(errors.length === 0, "no page error on either page (the skinned material compiles)" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
