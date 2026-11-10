/*
 * test_a_pilot_takes_off_flies_lands_and_docks_a_craft_in_the_page.mjs — FLIGHT (#147, "you must add actual physics like
 * engines and gravity to the game and build a real usable xfighter", operator 2026-11-09), walked in the real page
 * against the real world server (tests/_land_live_fixture.py) as a player on a phone, with the on-screen buttons:
 *   1. a small craft built on the owner's plot — a steel-plate hull, a pilot seat on it, two thrusters behind;
 *   (3b: a reload in the air brings the page back to the controls — 2026-11-10; 5: Use on a thruster, not the seat, boards it)
 *   2. Use on the seat takes the controls: the HUD says flying, with its thrust against its weight;
 *   3. holding Jump climbs — the HUD shows the height and the world server holds the craft higher (it was told);
 *   4. holding Down lands it; Use leaves it parked (no pilot); /dock sets it down as pieces on the plot again;
 *   5. no page errors.
 *
 * Run:  node tests/test_a_pilot_takes_off_flies_lands_and_docks_a_craft_in_the_page.mjs   (needs chrome, python3)
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
try {
  const PAid = (await getJ("/fixture/plot")).plot;
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ steel_plate: 2, thruster: 2, pilot_seat: 1 })) + "&tools=" + encodeURIComponent(JSON.stringify(["pick"])));
  const { token } = await getJ("/fixture/owner_token");
  // 1. the craft: on a flat strip, resting on the ground
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

  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  // stand 2.6 m north of the seat, looking at it
  const su = q.u0 + (X + 150) / 100, sv = q.v0 + (Z + 75) / 100;
  const pu = su, pv = sv + 2.6, ph = site.top + 1;
  const pitch = -Math.atan2(ph + EYE - (Y + 60) / 100, 2.6);
  await stand(B, pu, pv, ph, Math.PI, pitch);

  // 2. Use on the seat
  await evl(B, "document.getElementById('tUse').click(), true");
  ok(await until(B, "/Flying/.test(document.getElementById('hudPos').textContent)", 15000), "Use on the seat takes the controls: " + await hudText(B));
  ok(/thrust 60 kN/.test(await evl(B, "document.getElementById('hudPos').textContent")), "…the HUD shows its thrust (two thrusters, 60 kN) against its weight");
  const crafts0 = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts;
  ok(crafts0.length === 1 && crafts0[0].pilot && crafts0[0].pieces.length === 4, "the world server holds one craft of four pieces, piloted");
  const h0 = crafts0[0].pose[3];

  // 3. hold Jump
  await evl(B, "document.getElementById('tJump').dispatchEvent(new Event('touchstart', { cancelable: true })), true");
  await sleep(2500);
  await evl(B, "document.getElementById('tJump').dispatchEvent(new Event('touchend')), true");
  await sleep(1500);
  const up = Number(((await evl(B, "document.getElementById('hudPos').textContent")).match(/([\d.]+) m up/) || [])[1]);
  ok(up > 3, `holding Jump climbs: ${up} m up`);
  await shot(B, "flying");
  let h1 = h0;
  for (let t = 0; t < 20 && h1 < h0 + 3; t++) { await sleep(500); h1 = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0].pose[3]; }
  ok(h1 > h0 + 3, `…and the world server holds it higher (${h0.toFixed(2)} -> ${h1.toFixed(2)} m)`);
  // 3b. RELOADED IN THE AIR ("on respawn i fell out of the x and cannot reenter it … by respawn i mean browser reload",
  // operator 2026-11-10): the page comes back at the controls of the craft it was flying, where the world server holds it
  await send(B, "Page.reload", {});
  await until(B, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 30000);
  ok(await until(B, "/Flying/.test(document.getElementById('hudPos').textContent)", 20000), "reloaded in the air, the page is back at the controls: " + await hudText(B));
  const again = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0];
  ok(again && again.pilot && again.pose[3] > h0 + 2, "…of the same craft, still in the air, still piloted");

  // 4. land, leave, dock
  await evl(B, "document.getElementById('tDown').dispatchEvent(new Event('touchstart', { cancelable: true })), true");
  ok(await until(B, "/ 0\\.0 m up/.test(document.getElementById('hudPos').textContent)", 20000), "holding Down lands it: " + await hudText(B));
  await evl(B, "document.getElementById('tDown').dispatchEvent(new Event('touchend')), true");
  await sleep(800);
  await evl(B, "document.getElementById('tUse').click(), true");
  let parked = null;
  for (let t = 0; t < 20 && !(parked && parked.pilot === null); t++) { await sleep(500); parked = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0]; }
  ok(parked && parked.pilot === null, "Use again leaves it parked");
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await until(B, "document.activeElement && document.activeElement.id === 'conIn'", 8000);
  await send(B, "Input.insertText", { text: "dock" });
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  let boxes = [];
  for (let t = 0; t < 20 && !boxes.some((b) => b[6] === 66); t++) { await sleep(500); boxes = (await getJ("/land/api/plot?plot=" + PAid)).boxes || []; }
  ok(boxes.filter((b) => [64, 65, 66].includes(b[6])).length === 4, "/dock sets it down as its four pieces on the plot again: " + JSON.stringify(boxes.filter((b) => [64, 65, 66].includes(b[6]))));
  if (!boxes.some((b) => b[6] === 66)) console.log("what the page said:", await evl(B, "document.getElementById('conLog').textContent.slice(-300) + ' || ' + document.body.innerText.slice(0, 600)"), JSON.stringify((await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts.map((c) => [c.pose, c.pilot])));
  ok((await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts.length === 0, "…and the craft is gone");
  // 5. USE ON ANY PART OF A CRAFT boards it: a seat inside a closed cockpit cannot be aimed at past its canopy (the X
  // fighter, #169, 2026-11-10) — Use on another part of it (a thruster) takes the seat it is built round
  const part = boxes.filter((b) => b[6] === 65).sort((a, b) => b[0] - a[0])[0];       // the eastmost thruster
  const pc = { u: q.u0 + (part[0] + part[3] / 2) / 100, v: q.v0 + (part[1] + part[4] / 2) / 100, h: (part[2] + part[5] / 2) / 100 };
  const tu = pc.u + 2.6, tv = pc.v, th = Wd.column(q.face, Math.floor(tu), Math.floor(tv)).top + 1;
  await stand(B, tu, tv, th, -Math.PI / 2, -Math.atan2(th + EYE - pc.h, 2.6));
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await until(B, "document.activeElement && document.activeElement.id === 'conIn'", 8000);
  await send(B, "Input.insertText", { text: "aim" });
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  await sleep(1500);
  const aimed = await evl(B, "document.getElementById('conLog').textContent.slice(-120)");
  ok(/Aiming at Thruster/.test(aimed), "aiming at a thruster of the craft, not its seat: " + aimed.slice(-80));
  await evl(B, "document.getElementById('tUse').click(), true");
  ok(await until(B, "/Flying/.test(document.getElementById('hudPos').textContent)", 15000), "Use on it takes the craft's seat: " + await hudText(B));
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  // the pilot sees their craft: flying, the camera hangs behind and above it (from the seat it was never in view)
  const page = (await import("node:fs")).readFileSync(join(ROOT, "static", "land.js"), "utf8");
  ok(/if \(!flying\) return e;[\s\S]{0,300}e\[i\] - fw\[i\] \* CHASE_BACK \+ fr\.up\[i\] \* CHASE_UP/.test(page), "flying, the view is a chase view behind and above the craft");
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
