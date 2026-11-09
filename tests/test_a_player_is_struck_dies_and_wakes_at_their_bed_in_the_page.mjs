/*
 * test_a_player_is_struck_dies_and_wakes_at_their_bed_in_the_page.mjs — HEALTH, DEATH AND RESPAWN (#162: "add
 * aggressive deer and death/respawn mechanism", operator 2026-11-09), walked in the real page against the real world
 * server (tests/_land_live_fixture.py) as a player on a phone, with taps only. The fixture strikes the player as a
 * charging stag would (land_server Hub.hurt, the herd's own path):
 *   1. signed in, the HUD shows the player's hearts; struck, they drop and the screen flashes red;
 *   2. Use on a bed built on the plot: "Your bed: you will wake here";
 *   3. struck to death: a card says what killed them and that they wake at their bed; Wake up puts them beside the bed,
 *      their bag kept, their hearts full;
 *   4. no page errors.
 *
 * Run:  node tests/test_a_player_is_struck_dies_and_wakes_at_their_bed_in_the_page.mjs   (needs chrome, python3)
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
  const R = await (await fetch(base + "/static/land-recipes.json")).json(), MAX = R.health.max;
  const { token } = await getJ("/fixture/owner_token");
  const PAid = (await getJ("/fixture/plot")).plot;
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ bed: 1, planks: 7 })));
  // the herd held still, with its only animal far off: the fixture strikes the player itself (a real stag charging the
  // player while they stood about could kill them a second time, and the card would rightly come back)
  await getJ(`/fixture/animal?kind=rabbit&u=${q.u0 + 400}&v=${q.v0 + 400}`);
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const hud = () => evl(B, "(document.getElementById('hudHp') || {}).textContent || ''");
  // an open site: the bed's two columns and the three south of it, flat, with nothing over them for 5 m (a tree's crown
  // stood over the first site, and the look found its leaves before the bed)
  let site = null;
  for (let du = 2; du < 12 && !site; du++) for (let dv = 4; dv < 12 && !site; dv++) {
    const cols = []; for (let a = 0; a < 2; a++) for (let b = -3; b <= 0; b++) cols.push([q.u0 + du + a, q.v0 + dv + b]);
    const tops = cols.map(([cu, cv]) => Wd.column(q.face, cu, cv).top);
    if (Math.max(...tops) - Math.min(...tops) <= 1 && cols.every(([cu, cv], k) => [1, 2, 3, 4, 5].every((dh) => Wd.terrainBlock(q.face, cu, cv, tops[k] + dh) === Wd.B.air)))
      site = { du, dv, top: Math.max(...tops) };
  }
  ok(!!site, "an open site for a bed");
  const top = site.top;
  // a bed on the plot, the player two metres south of it looking at it
  const box = [site.du * 100, site.dv * 100, (top + 1) * 100].concat(R.items.bed.unit).concat([Wd.B.bed]);
  const built = await (await fetch(base + "/land/api/boxes", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ plot: PAid, add: [box] }) })).json();
  ok(built.added === 1, "a bed is built on the plot");
  const bu = q.u0 + site.du + 1, bv = q.v0 + site.dv + 0.5;          // its middle
  await stand(B, bu, bv - 2.2, top + 1, 0, -0.35);

  // 1. hearts, and a strike
  ok(await until(B, `/ ${MAX}\\/${MAX}$/.test((document.getElementById('hudHp') || {}).textContent || '') && !document.getElementById('hudHp').classList.contains('hidden')`, 10000),
     "signed in, the HUD shows full hearts: " + await hud());
  await getJ("/fixture/hurt?dmg=3&by=deer");
  ok(await until(B, `/ ${MAX - 3}\\/${MAX}$/.test(document.getElementById('hudHp').textContent)`, 8000), "struck by a stag, the hearts drop: " + await hud());
  ok(await evl(B, "!!document.getElementById('hurtFlash')"), "…and the screen has its red flash");

  // 2. the bed: look at it — checked with /aim, tilting until the crosshair is on it, as a player would — and Use it
  const aimSays = async () => {
    await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
    await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
    await until(B, "document.activeElement && document.activeElement.id === 'conIn'", 5000);
    await send(B, "Input.insertText", { text: "aim" });
    await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
    await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
    await sleep(800);
    return evl(B, "(() => { const l = Array.from(document.getElementById('conLog').children).map((e) => e.textContent).filter((t) => /^Aiming at|^Nothing within/.test(t)); return l[l.length - 1] || ''; })()");
  };
  const tilt = async (dy) => {
    await send(B, "Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: 700, y: 200, id: 4 }] });
    await send(B, "Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: 700, y: 200 + dy, id: 4 }] });
    await send(B, "Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await sleep(600);
  };
  await stand(B, bu, bv - 2.2, top + 1, 0, -Math.atan2(1.62 - 0.45, 2.2));
  let said = await aimSays();
  for (const dy of [-15, 30, -45, 60, -75, 90]) { if (said.startsWith("Aiming at Bed")) break; await tilt(dy); said = await aimSays(); }
  console.log("  aim: " + said);
  let set = false;
  for (let i = 0; i < 4 && !set; i++) {
    await evl(B, "document.getElementById('tUse').click(), true");
    set = await until(B, "/Your bed: you will wake here/.test((document.getElementById('alertBar') || {}).textContent || '')", 4000);
  }
  ok(set, "Use on the bed: the player will wake there");

  // 3. death and waking
  await stand(B, bu + 30, bv + 30, Wd.column(q.face, Math.floor(bu + 30), Math.floor(bv + 30)).top + 1, 0, -0.2);   // away from the bed
  await getJ("/fixture/hurt?dmg=99&by=deer");
  ok(await until(B, "!document.getElementById('deathCard').classList.contains('hidden')", 8000), "struck to death, the death card shows");
  const card = await evl(B, "document.getElementById('deathCard').textContent");
  ok(/You were killed by a deer/.test(card) && /You wake at your bed/.test(card), "…saying what killed them, and that they wake at their bed: " + card.replace(/\s+/g, " ").trim());
  await evl(B, "document.getElementById('deathGo').click(), true");
  await sleep(2500);
  const at = await evl(B, "JSON.parse(localStorage.getItem('nado_land_v1')).p");
  ok(Math.hypot(at[1] - bu, at[2] - bv) < 3, `Wake up puts them beside their bed (${at[1].toFixed(1)}, ${at[2].toFixed(1)}; the bed at ${bu}, ${bv})`);
  const died = [...frames.values()].flat().filter((f) => f.includes('"t": "died"') || f.includes('"t":"died"')).length;
  ok(await evl(B, "document.getElementById('deathCard').classList.contains('hidden')"), `…the card gone (${died} death message${died === 1 ? "" : "s"} heard)`);
  ok(await until(B, `/ ${MAX}\\/${MAX}$/.test(document.getElementById('hudHp').textContent)`, 8000), "…with full hearts");
  await evl(B, "document.getElementById('tPal').click(), true"); await sleep(900);
  ok(/7 × Planks/.test(await evl(B, "document.getElementById('palGrid').textContent")), "…and their bag kept");
  await evl(B, "document.getElementById('palClose').click(), true");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
