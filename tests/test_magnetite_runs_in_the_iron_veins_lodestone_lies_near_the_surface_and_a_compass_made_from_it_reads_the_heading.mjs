/*
 * test_magnetite_runs_in_the_iron_veins_lodestone_lies_near_the_surface_and_a_compass_made_from_it_reads_the_heading.mjs —
 * FINDING THE WAY, rung 1 (#173, doc/land-navigation.md 1.1-1.2; operator 2026-11-10: "i cant find the way home", "you
 * need to invent maps, compasses, navigation systems and give them full research+tech+recipe+ingredient walks"):
 *   1. magnetite runs in a share of the iron veins (an iron ore: Magnetite l.47); lodestone — magnetite magnetised, by
 *      lightning in the leading theory (Lodestone l.66) — only within LODE_DEPTH of the rock's top, never in the deep;
 *   2. both are broken with a pick, as iron ore is (Mohs 5.5-6.5, Lodestone l.32), and yield themselves;
 *   3. magnetite smelts to iron exactly as iron ore does — no iron is lost to it;
 *   4. a needle struck with a lodestone is magnetised and the lodestone is kept (Compass l.28); needle + case + glass
 *      at the workbench is a compass;
 *   5. walked in the page, through the world server's own craft API: without a compass the HUD says no heading; with
 *      one it reads the bearing from north and its point — east facing east, north-west facing north-west.
 *
 * Run: node tests/test_magnetite_runs_in_the_iron_veins_lodestone_lies_near_the_surface_and_a_compass_made_from_it_reads_the_heading.mjs
 */
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PROTOCOL_JS } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 1. the ground
const B = Wd.B, seen = { ironore: 0, magnetite: 0, lodestone: 0 }, lodeDepths = [];
for (let u = 55000; u < 55600; u += 1) for (let v = 80000; v < 80060; v += 3) {
  const c = Wd.column(0, u, v), rockTop = c.top - c.soil;
  for (let h = Math.max(4, rockTop - 40); h <= rockTop; h++) {
    const b = Wd.terrainBlock(0, u, v, h);
    if (b === B.ironore) seen.ironore++;
    if (b === B.magnetite) seen.magnetite++;
    if (b === B.lodestone) { seen.lodestone++; lodeDepths.push(rockTop - h); }
  }
}
ok(seen.magnetite > 0 && seen.lodestone > 0 && seen.ironore > seen.magnetite + seen.lodestone,
  `magnetite runs in a share of the iron veins, lodestone too (iron ${seen.ironore}, magnetite ${seen.magnetite}, lodestone ${seen.lodestone})`);
ok(lodeDepths.every((d) => d < Wd.LODE_DEPTH), `lodestone lies only within ${Wd.LODE_DEPTH} m of the rock's top (deepest ${Math.max(...lodeDepths)} m)`);
let deepLode = 0, deepMag = 0;
for (let u = 55000; u < 55300; u += 2) for (let v = 80000; v < 80030; v += 3) for (let h = -40; h > -400; h -= 3) {
  const b = Wd.deepBlock(0, u, v, h); if (b === B.lodestone) deepLode++; if (b === B.magnetite) deepMag++;
}
ok(deepMag > 0 && deepLode === 0, `the deep holds magnetite (${deepMag}) but never lodestone — lightning does not reach it`);
// 2. breaking
const brk = R.breaking;
for (const k of ["magnetite", "lodestone"]) {
  const e = brk[String(B[k])];
  ok(e && e.needs === "pick" && e.hard === brk[String(B.ironore)].hard && e.yields[0][0] === k, `${k} is broken with a pick, as iron ore is, and yields ${k}`);
}
// 3. smelting
const rec = (id) => R.recipes.find((r) => r.id === id);
for (const [a, b] of [["iron_magnetite", "iron"], ["iron_magnetite_coal", "iron_coal"]]) {
  const x = rec(a), y = rec(b);
  ok(x && JSON.stringify(x.makes) === JSON.stringify(y.makes) && JSON.stringify(x.with) === JSON.stringify(y.with)
    && JSON.stringify(x.uses.map(([i, n]) => [i === "magnetite" ? "ironore" : i, n])) === JSON.stringify(y.uses), `${a}: magnetite smelts to iron exactly as iron ore does (${b})`);
}
// 4. the compass
const cn = rec("compass_needle"), cp = rec("compass");
ok(cn && cn.uses.some(([i]) => i === "lodestone") && cn.makes.some(([i, n]) => i === "lodestone" && n === 1) && cn.uses.some(([i]) => i === "iron"),
  "a needle is struck with a lodestone and the lodestone is kept");
ok(cp && cp.uses.some(([i]) => i === "compass_needle") && cp.uses.some(([i]) => i === "glass"), "the magnetised needle in a case under glass is a compass");

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
const SV = spot(3, 3), SO = spot(9, 3);

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
try {
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ magnetite: 2, charcoal: 2, lodestone: 1, planks: 1, glass: 1 }))
    + "&tools=" + encodeURIComponent(JSON.stringify(["hammer"])) + "&stations=" + encodeURIComponent(JSON.stringify(["bloomery", "anvil", "workbench"])));
  const { token } = await getJ("/fixture/owner_token");
  const craft = async (recipe) => (await fetch(base + "/land/api/craft", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ recipe }) })).json();
  const T = await tab();
  await send(T, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const s = spot(4, 4);
  await stand(T, s.u, s.v, s.h, Math.PI / 2, -0.2);
  ok(!/compass/.test(await evl(T, "document.getElementById('hudPos').textContent")), "without a compass the HUD says no heading");
  const r1 = await craft("iron_magnetite");
  ok(r1.ok && r1.inventory.items.iron === 1, "magnetite smelted at the bloomery gives iron: " + JSON.stringify(r1.error || r1.inventory.items.iron));
  const r2 = await craft("compass_needle");
  ok(r2.ok && r2.inventory.items.compass_needle === 1 && r2.inventory.items.lodestone === 1, "the needle struck with the lodestone is magnetised, the lodestone kept: " + JSON.stringify(r2.error || r2.inventory.items));
  const r3 = await craft("compass");
  ok(r3.ok && r3.inventory.items.compass === 1, "a compass is made at the workbench: " + JSON.stringify(r3.error || r3.inventory.items));
  ok(await until(T, "/compass 90° E/.test(document.getElementById('hudPos').textContent)", 15000), "with it, facing east the HUD reads it: " + await evl(T, "document.getElementById('hudPos').textContent"));
  await stand(T, s.u, s.v, s.h, -Math.PI / 4, -0.2);
  ok(await until(T, "/compass 315° NW/.test(document.getElementById('hudPos').textContent)", 15000), "…facing north-west, north-west: " + await evl(T, "document.getElementById('hudPos').textContent"));
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
