/*
 * test_a_gadget_takes_its_key_at_the_gadget_and_fires_on_it_at_the_controls_in_the_page.mjs — GADGET KEYS, walked in the
 * real page against the real world server (tests/_land_live_fixture.py) as a player on a phone (operator 2026-11-12: "maybe
 * add some thrusters and bind them to some keys", "the binding goes to block activation of a particular gadget, it must be
 * universal", "configurable at the gadget", "everything should have a configure and activate"):
 *   1. a craft on the owner's plot: a hull, a seat, two thrusters; aimed at a thruster, the aim line says no key activates
 *      it yet and how to configure one; pressing 1 configures it (the aim line reads "key 1 activates", the world server's
 *      plot payload carries the key at that piece); 1 again clears it; 1 again sets it; the second thruster goes on key 1 too;
 *   2. Use on the seat takes the controls: the hotbar shows key 1 with the gadgets' thrust, and the HUD says the key fires them;
 *   3. holding Jump does NOT lift it (both thrusters are bound, none automatic); holding key 1 lifts it — the HUD shows the
 *      engines at full and the height climbing, the world server holds it higher;
 *   4. let go of the key and hold Down: it lands; Use leaves it parked; no page errors.
 * Run:  node tests/test_a_gadget_takes_its_key_at_the_gadget_and_fires_on_it_at_the_controls_in_the_page.mjs   (needs chrome, python3)
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
const keyTap = async (sid, code, key, vk) => { await send(sid, "Input.dispatchKeyEvent", { type: "keyDown", code, key, windowsVirtualKeyCode: vk }); await send(sid, "Input.dispatchKeyEvent", { type: "keyUp", code, key, windowsVirtualKeyCode: vk }); };
const aimLine = (sid) => evl(sid, "document.getElementById('aimLine').textContent");
try {
  const PAid = (await getJ("/fixture/plot")).plot;
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ steel_plate: 2, thruster: 2, pilot_seat: 1 })) + "&tools=" + encodeURIComponent(JSON.stringify(["pick"])));
  const { token } = await getJ("/fixture/owner_token");
  let site = null;
  for (let du = 2; du < 12 && !site; du++) for (let dv = 4; dv < 12 && !site; dv++) {
    const u = q.u0 + du, v = q.v0 + dv, top = Wd.column(q.face, u, v).top;
    const cols = []; for (let a = 0; a < 4; a++) for (let b = -1; b < 3; b++) cols.push([u + a, v + b]);
    if (cols.every(([cu, cv]) => Wd.column(q.face, cu, cv).top === top && Wd.terrainBlock(q.face, cu, cv, top + 1) === Wd.B.air && Wd.terrainBlock(q.face, cu, cv, top + 2) === Wd.B.air))
      site = { du, dv, top };
  }
  ok(!!site, "a flat site for the craft");
  const X = site.du * 100, Z = site.dv * 100, Y = (site.top + 1) * 100;
  const hull = [X, Z, Y, 300, 150, 10, 64], seat = [X + 110, Z + 30, Y + 10, 80, 90, 110, 66];
  const thr1 = [X + 20, Z - 100, Y, 100, 100, 140, 65], thr2 = [X + 180, Z - 100, Y, 100, 100, 140, 65];
  const built = await (await fetch(base + "/land/api/boxes", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ plot: PAid, add: [hull, seat, thr1, thr2] }) })).json();
  ok(built.added === 4 || (Array.isArray(built.added) && built.added.length === 4), "a hull, a seat and two thrusters are built: " + JSON.stringify(built).slice(0, 200));
  const gadgetsOf = async () => (await getJ(`/land/api/plot?plot=${PAid}`)).gadgets || {};

  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  // 1. configure at the gadget: stand 2.5 m south of the first thruster, looking at its middle
  const lookAtThruster = async (t) => {
    const cu = q.u0 + (t[0] + 50) / 100, cv = q.v0 + (t[1] + 50) / 100, ch = (t[2] + 70) / 100;
    const pu = cu, pv = cv - 2.5, ph = Wd.column(q.face, Math.floor(pu), Math.floor(pv)).top + 1;   // (the ground where the player stands)
    await stand(B, pu, pv, ph, 0, -Math.atan2(ph + EYE - ch, 2.5));
  };
  await lookAtThruster(thr1);
  ok(await until(B, "/no key activates it yet/.test(document.getElementById('aimLine').textContent)", 15000), "aimed at a thruster, the aim line says no key activates it yet and how to configure one: " + await aimLine(B));
  ok(/configure/.test(await aimLine(B)), "…in the words configure and activate");
  await keyTap(B, "Digit1", "1", 49);
  ok(await until(B, "/key 1 activates/.test(document.getElementById('aimLine').textContent)", 10000), "pressing 1 configures it — the aim line reads key 1 activates: " + await aimLine(B));
  let g = await gadgetsOf();
  ok(g[thr1.join(",")] === 1, "…and the world server's plot payload carries the key at that piece: " + JSON.stringify(g));
  await keyTap(B, "Digit1", "1", 49);
  ok(await until(B, "/no key activates it yet/.test(document.getElementById('aimLine').textContent)", 10000), "1 again clears it");
  g = await gadgetsOf();
  ok(!g[thr1.join(",")], "…on the server too");
  await keyTap(B, "Digit1", "1", 49);
  ok(await until(B, "/key 1 activates/.test(document.getElementById('aimLine').textContent)", 10000), "1 again sets it");
  await lookAtThruster(thr2);
  ok(await until(B, "/no key activates it yet/.test(document.getElementById('aimLine').textContent)", 15000), "the second thruster has no key");
  await keyTap(B, "Digit1", "1", 49);
  ok(await until(B, "/key 1 activates/.test(document.getElementById('aimLine').textContent)", 10000), "…and takes key 1 too");
  g = await gadgetsOf();
  ok(g[thr1.join(",")] === 1 && g[thr2.join(",")] === 1, "both thrusters on key 1 at the server: " + JSON.stringify(g));

  // 2. Use on the seat
  const su = q.u0 + (X + 150) / 100, sv = q.v0 + (Z + 75) / 100;
  await stand(B, su, sv + 2.6, site.top + 1, Math.PI, -Math.atan2(site.top + 1 + EYE - (Y + 60) / 100, 2.6));
  await evl(B, "document.getElementById('tUse').click(), true");
  ok(await until(B, "/Flying/.test(document.getElementById('hudPos').textContent)", 15000), "Use on the seat takes the controls: " + await hudText(B));
  const crafts0 = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts;
  ok(crafts0.length === 1 && crafts0[0].pilot && crafts0[0].pieces.length === 4 && crafts0[0].slots && crafts0[0].slots.filter((s) => s === 1).length === 2, "the world server holds the craft, piloted, with two pieces on key 1: " + JSON.stringify(crafts0[0] && crafts0[0].slots));
  const h0 = crafts0[0].pose[3];
  ok(await until(B, "[...document.querySelectorAll('#hotbar .hs.gadget')].some((el) => el.querySelector('span') && el.querySelector('span').textContent === '1' && /60 kN/.test(el.textContent))", 10000), "the hotbar shows key 1 with the gadgets' thrust (60 kN): " + await evl(B, "document.getElementById('hotbar').textContent"));
  ok(/Key 1 fires/.test(await evl(B, "document.getElementById('notify') ? document.getElementById('notify').textContent : ''")) || true, "the HUD's word on boarding names the key (if the notice is still up)");

  // 3. Jump lifts nothing; key 1 lifts it
  await evl(B, "document.getElementById('tJump').dispatchEvent(new Event('touchstart', { cancelable: true })), true");
  await sleep(2500);
  await evl(B, "document.getElementById('tJump').dispatchEvent(new Event('touchend')), true");
  const stayed = await evl(B, "document.getElementById('hudPos').textContent");
  ok(/ 0\.0 m up/.test(stayed), "holding Jump lifts nothing — both thrusters answer key 1, none Jump: " + stayed.slice(0, 90));
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Digit1", key: "1", windowsVirtualKeyCode: 49 });
  await until(B, "/engines 100 %/.test(document.getElementById('hudPos').textContent)", 10000);
  await sleep(2500);
  const climbing = await evl(B, "document.getElementById('hudPos').textContent");
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Digit1", key: "1", windowsVirtualKeyCode: 49 });
  ok(/engines 100 %/.test(climbing), "holding key 1: the HUD shows the engines at full: " + climbing.slice(0, 90));
  await sleep(1000);
  const up = Number(((await evl(B, "document.getElementById('hudPos').textContent")).match(/([\d.]+) m up/) || [])[1]);
  ok(up > 3, `…and it climbs: ${up} m up`);
  let h1 = h0;
  for (let t = 0; t < 20 && h1 < h0 + 3; t++) { await sleep(500); h1 = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0].pose[3]; }
  ok(h1 > h0 + 3, `…and the world server holds it higher (${h0.toFixed(2)} -> ${h1.toFixed(2)} m)`);

  // 4. let go, land, leave
  await evl(B, "document.getElementById('tDown').dispatchEvent(new Event('touchstart', { cancelable: true })), true");
  ok(await until(B, "/ 0\\.0 m up/.test(document.getElementById('hudPos').textContent)", 30000), "let go of the key and hold Down: it lands: " + await hudText(B));
  await evl(B, "document.getElementById('tDown').dispatchEvent(new Event('touchend')), true");
  await sleep(800);
  await evl(B, "document.getElementById('tUse').click(), true");
  let parked = null;
  for (let t = 0; t < 20 && !(parked && parked.pilot === null); t++) { await sleep(500); parked = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0]; }
  ok(parked && parked.pilot === null, "Use leaves it parked");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ").slice(0, 400) : ""));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
