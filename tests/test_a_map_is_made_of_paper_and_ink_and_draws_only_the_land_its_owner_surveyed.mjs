/*
 * test_a_map_is_made_of_paper_and_ink_and_draws_only_the_land_its_owner_surveyed.mjs — FINDING THE WAY, rung 2 (#173,
 * doc/land-navigation.md 1.3; operator 2026-11-10: "i cant find the way home", "you need to invent maps"):
 *   1. bark stripped from a log is tanbark (oak and hemlock bark tan: Tanbark l.3, l.12); iron steeped with it over a fire
 *      is ink (iron gall ink is tannin with any iron ion donor: Iron gall ink l.9); a mould — a frame with a wire screen
 *      (Papermaking l.25) — makes paper of plant fibre or linen rags; paper and ink at the workbench are a map;
 *   2. every new item and tool has its name in all 17 languages;
 *   3. walked in the page through the world server's craft API: without a map there is no Map button and /map says how
 *      to make one; with it the button is there, and the map shows the squares its owner passed through CARRYING it —
 *      not those visited before — painted from the planet's generator, the rest left blank.
 *
 * Run: node tests/test_a_map_is_made_of_paper_and_ink_and_draws_only_the_land_its_owner_surveyed.mjs
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

// 1. the chain
const rec = (id) => R.recipes.find((r) => r.id === id);
const has = (r, i) => r && r.uses.some(([x]) => x === i);
ok(rec("tanbark") && has(rec("tanbark"), "wood") && rec("tanbark").with.includes("knife") && rec("tanbark").makes[0][0] === "tanbark", "bark stripped from a log with a knife is tanbark");
ok(has(rec("ink"), "iron") && has(rec("ink"), "tanbark") && has(rec("ink"), "water") && rec("ink").with.includes("campfire"), "iron steeped with tanbark in water over a fire is ink");
ok(has(rec("paper_mould"), "wire") && R.tools.paper_mould, "a paper mould is a frame with a wire screen — a tool");
ok(has(rec("paper"), "fiber") && has(rec("paper_linen"), "linen") && rec("paper").with.includes("paper_mould"), "paper is made in the mould of plant fibre or linen rags");
ok(has(rec("map"), "paper") && has(rec("map"), "ink") && rec("map").with.includes("workbench"), "paper and ink at the workbench are a map");
// 2. names
const I18 = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
const named = ["i.tanbark", "i.ink", "i.paper", "i.map", "t.paper_mould"].every((k) => Object.values(I18).every((t) => t["land." + k]));
ok(named && Object.keys(I18).length === 17, "every new item and tool has its name in all 17 languages");

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
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ wood: 1, iron: 1, water: 3, planks: 2, wire: 2, fiber: 8 }))
    + "&tools=" + encodeURIComponent(JSON.stringify(["knife"])) + "&stations=" + encodeURIComponent(JSON.stringify(["campfire", "workbench"])));
  const { token } = await getJ("/fixture/owner_token");
  const craft = async (recipe) => (await fetch(base + "/land/api/craft", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ recipe }) })).json();
  const T = await tab();
  await send(T, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const s = spot(4, 4);
  // the page once, at home; the other places are walked to through the world server's own move API (what an agent
  // client does) — a page reload per place took the walk past the push hook's 900 s
  const move = async (u, v) => (await fetch(base + "/land/api/move", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ p: [q.face, u, v, Wd.column(q.face, Math.floor(u), Math.floor(v)).top + 1, 0] }) })).json();
  await stand(T, s.u, s.v, s.h, 0, -0.2);
  ok(await evl(T, "document.getElementById('mapBtn').classList.contains('hidden')"), "without a map there is no Map button");
  // before the map: 300 m east — a place the map must NOT show
  ok((await move(s.u + 300, s.v)).ok, "walked 300 m east before the map was made");
  await sleep(500);
  ok((await move(s.u, s.v)).ok, "…and home again before it is made (standing there with it would survey it)");
  for (const r of ["tanbark", "ink", "paper_mould", "paper", "paper", "map"]) {
    const x = await craft(r);
    if (!x.ok) ok(false, `craft ${r}: ${x.error}`);
  }
  const inv = (await getJ("/fixture/seed?who=owner&items=%7B%7D"));
  ok((inv.items || {}).map === 1, "tanbark, ink, a paper mould, paper and a map are made through the world server: " + JSON.stringify(inv.items));
  // with the map: home, and 130 m north and south — these it must show
  const placesWith = [s, { u: s.u, v: s.v + 130 }, { u: s.u, v: s.v - 130 }];
  for (const p of [...placesWith, s]) { ok((await move(p.u, p.v)).ok, `walked to ${(p.v - s.v).toFixed(0)} m north of home with the map`); await sleep(500); }
  await until(T, "!document.getElementById('mapBtn').classList.contains('hidden')", 10000);
  ok(!(await evl(T, "document.getElementById('mapBtn').classList.contains('hidden')")), "with a map, the Map button is there");
  await evl(T, "document.getElementById('mapBtn').click(), true");
  ok(await until(T, "/km² surveyed/.test(document.getElementById('mapLegend').textContent)", 15000), "the button opens the map: " + await evl(T, "document.getElementById('mapLegend').textContent"));
  const area = Number((await evl(T, "document.getElementById('mapLegend').textContent")).match(/([\d.]+) km²/)[1]);
  const tiles = new Set(placesWith.map((p) => `${Math.floor(p.u / 64)}:${Math.floor(p.v / 64)}`)).size;
  ok(Math.abs(area - tiles * 64 * 64 / 1e6) < 0.0006, `it shows the squares passed through carrying it — ${tiles} squares, ${area} km² — not the ones visited before it was made`);
  const px = await evl(T, "(() => { const c = document.getElementById('mapCanvas'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let land = 0, blank = 0; for (let i = 0; i < d.length; i += 4) { if (d[i] === 0x1b && d[i + 1] === 0x24 && d[i + 2] === 0x30) blank++; else land++; } return [land, blank]; })()");
  ok(px[0] > 2000 && px[1] > px[0], `the surveyed squares are painted from the planet, the rest left blank (${px[0]} painted, ${px[1]} blank pixels)`);
  // THE PLANET (operator 2026-11-11: "proper planetary physical properties like in Kerbal space"): from the Map, its facts
  await evl(T, "document.getElementById('mapPlanet').click(), true");
  ok(await until(T, "!document.getElementById('planetPanel').classList.contains('hidden') && /Escape speed/.test(document.getElementById('planetGrid').textContent)", 10000), "the Map opens the planet's facts");
  const pf = await evl(T, "document.getElementById('planetGrid').textContent");
  ok(/Radius: 83\.4 km/.test(pf) && /Escape speed: 1,279 m\/s/.test(pf) && /Synchronous orbit.*131\.7 km up/.test(pf) && /none above 30 km/.test(pf),
    "…its radius, escape speed, synchronous orbit and the air's top, as land-planet.js computes them: " + pf.slice(0, 160));
  await evl(T, "document.getElementById('planetClose').click(), document.getElementById('mapBtn').click(), true");
  await until(T, "/km² surveyed/.test(document.getElementById('mapLegend').textContent)", 10000);
  // on a short phone screen the whole map and its legend are in view (the live 800 x 480 page cut the card off below)
  await send(T, "Emulation.setDeviceMetricsOverride", { width: 800, height: 480, deviceScaleFactor: 1, mobile: true });
  await sleep(800);
  const fit = await evl(T, "(() => { const c = document.querySelector('#mapPanel .card').getBoundingClientRect(), l = document.getElementById('mapLegend').getBoundingClientRect(); return [Math.round(c.bottom), Math.round(l.bottom), innerHeight]; })()");
  ok(fit[0] <= fit[2] && fit[1] <= fit[2], `on an 800 x 480 phone screen the whole map and its legend are in view (card to ${fit[0]}, legend to ${fit[1]}, screen ${fit[2]})`);
  await shot(T, "map");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
