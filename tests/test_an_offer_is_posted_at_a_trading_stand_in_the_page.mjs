/*
 * test_an_offer_is_posted_at_a_trading_stand_in_the_page.mjs — MARKETS (#161: "local markets first, global only with
 * the invention of the internet", "trading stands", operator 2026-11-09), walked in the real page against the real world
 * server (tests/_land_live_fixture.py) as a player on a phone, with taps only:
 *   1. away from any stand the bag says offers are made at a trading stand, and Post offer is off;
 *   2. a stand built on the plot; standing at it the bag says this is a market (its reach and its share), Post offer is
 *      on, and an offer posted there shows as the player's own — its planks held in escrow;
 *   3. Withdraw gives them back; a gift to someone who is not beside the player is turned away in the player's language;
 *   4. no page errors.
 *
 * Run:  node tests/test_an_offer_is_posted_at_a_trading_stand_in_the_page.mjs   (needs chrome, python3)
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
try {
  const R = await (await fetch(base + "/static/land-recipes.json")).json();
  const { token } = await getJ("/fixture/owner_token");
  const PAid = (await getJ("/fixture/plot")).plot, other = (await getJ("/fixture/plot")).other;
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ planks: 10, stand: 1 })));
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const openBag = async () => { await evl(B, "document.getElementById('tPal').click(), true"); await sleep(900); return evl(B, "document.getElementById('palGrid').textContent"); };
  const closeBag = () => evl(B, "document.getElementById('palClose').click(), true");
  const postOff = () => evl(B, "document.getElementById('ofPost').disabled");
  // a stand site: two metres of open air over the plot's ground at its middle
  const su = q.u0 + 6, sv = q.v0 + 6, top = Math.max(...[0, 1, 2].map((d) => Wd.column(q.face, su + d, sv).top));

  // 1. away from any stand
  await stand(B, su + 1, sv + 3, top + 1, Math.PI, -0.2);
  let t = await openBag();
  ok(/Offers are made and taken at a trading stand/.test(t) && await postOff(), "away from a stand the bag says offers are made at a trading stand, and Post offer is off");
  await closeBag();

  // 2. a stand, and an offer at it
  const box = [600, 600, (top + 1) * 100].concat(R.items.stand.unit).concat([Wd.B.stand]);
  const built = await (await fetch(base + "/land/api/boxes", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ plot: PAid, add: [box] }) })).json();
  ok(built.added === 1, "a trading stand is built on the plot");
  await stand(B, su + 1, sv + 2.2, top + 1, Math.PI, -0.2);
  t = await openBag();
  ok(new RegExp(`At a market: offers made here are seen at the stands within ${R.market.reach} m; the market keeps ${Math.round(R.market.fee * 100)}%`).test(t) && !(await postOff()),
     "at the stand the bag says it is a market, its reach and its share, and Post offer is on");
  await evl(B, `(() => { const s = (id, v) => { const e = document.getElementById(id); e.value = v; e.dispatchEvent(new Event("change")); };
    s("ofG", "planks"); s("ofGN", "4"); s("ofW", "sand"); s("ofWN", "6"); document.getElementById("ofPost").click(); return true; })()`);
  ok(await until(B, "/Your offer/.test(document.getElementById('palGrid').textContent)", 10000), "an offer posted there shows as the player's own");
  ok(await until(B, "/\\b6 × Planks/.test(document.getElementById('palGrid').textContent)", 8000), "…its planks held in escrow (6 of 10 left)");

  // 3. withdraw; a gift to someone far away
  await evl(B, "(() => { const b = document.querySelector('[data-cancel]'); b && b.click(); return !!b; })()");
  ok(await until(B, "/\\b10 × Planks/.test(document.getElementById('palGrid').textContent) && !/Your offer/.test(document.getElementById('palGrid').textContent)", 10000), "Withdraw gives the planks back");
  await evl(B, `(() => { document.getElementById("gvTo").value = ${JSON.stringify(other)}; document.getElementById("gvGo").click(); return true; })()`);
  ok(await until(B, "/A gift is handed over in person/.test((document.getElementById('alertBar') || {}).textContent || '')", 6000), "a gift to someone not beside the player is turned away, in the player's language");
  await closeBag();
  await shot(B, "market");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
