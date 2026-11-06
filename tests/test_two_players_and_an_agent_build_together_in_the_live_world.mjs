/*
 * test_two_players_and_an_agent_build_together_in_the_live_world.mjs — the Land page against the REAL world server
 * (scripts/land_server.py, served by tests/_land_live_fixture.py from one origin with a fake exec node), walked as two
 * players in two browser tabs plus an AI agent on the API:
 *   1. a visitor (not signed in) on plot PA is online and offered "Sign in to build";
 *   2. an agent the plot's owner invited signs in with ITS OWN key and builds a 3 x 3 wall through the API — the
 *      visitor's HUD counts the 9 changed blocks without reloading (the server pushed them);
 *   3. the owner, signed in (their session cookie), sees the plot as theirs and the agent's 9 blocks on arrival;
 *   4. the owner places a block — the visitor sees it arrive (10 changed blocks), and the two players see each other;
 *   5. the visitor taps Place — nothing changes anywhere, and the page says why.
 * Every check reads what a player sees (the HUD) or what crossed the wire (the page's own websocket frames).
 *
 * Run:  node tests/test_two_players_and_an_agent_build_together_in_the_live_world.mjs        (needs chromium, python3)
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
  // 1. a visitor
  const A = await tab();
  await open(A, SV);
  ok(await until(A, "/Sign in to build/.test(document.getElementById('hudPlot').textContent)"),
     "a visitor is online and offered Sign in to build: " + await hudText(A));

  // 2. the owner's invited agent builds through the API
  const built = await getJ("/fixture/agent_build?top=" + Wd.column(q.face, q.u0 + 2, q.v0 + 12).top);
  ok(built.applied === 9 && !built.refused.length, "an invited agent, signed in with its own key, builds a 3 x 3 wall via the API: " + JSON.stringify(built));
  ok(await until(A, "/ · 9 changed blocks$/.test(document.getElementById('hudPos').textContent)", 10000),
     "the visitor sees the agent's 9 blocks arrive, without reloading: " + await hudText(A));

  // 3. the owner, signed in
  const { token } = await getJ("/fixture/owner_token");
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  await open(B, SO);
  ok(await until(B, "/Your plot/.test(document.getElementById('hudPlot').textContent) && / · 9 changed blocks$/.test(document.getElementById('hudPos').textContent)"),
     "the signed-in owner sees the plot as theirs and the agent's blocks on arrival: " + await hudText(B));

  // 4. the owner builds; the visitor sees it; they see each other
  await evl(B, "document.getElementById('tPlace').click(), true");
  ok(await until(A, "/ · 10 changed blocks$/.test(document.getElementById('hudPos').textContent)", 10000),
     "the owner's block reaches the visitor live: " + await hudText(A));
  ok(await until(B, "/ · 10 changed blocks$/.test(document.getElementById('hudPos').textContent)", 5000), "…and the owner's own HUD agrees");
  await sleep(1500);
  const playersA = (frames.get(A) || []).filter((f) => f.includes('"t": "players"') || f.includes('"t":"players"')).map((f) => JSON.parse(f));
  ok(playersA.some((m) => m.list.length === 1), "the visitor's socket is told the owner is standing nearby");

  // 5. the visitor tries
  await evl(A, "document.getElementById('tPlace').click(), true");
  await sleep(1500);
  ok(/ · 10 changed blocks \|/.test(await hudText(A)) && / · 10 changed blocks \|/.test(await hudText(B)), "a visitor's tap changes nothing, for anyone");
  ok(!/[{}]/.test(await hudText(A) + await hudText(B)), "the HUD shows words, never a raw {placeholder} token");
  ok(await evl(A, "/Sign in to build — only a plot/.test(document.body.textContent)"), "and the page tells them to sign in");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
