/*
 * test_a_craft_with_a_nav_unit_tells_its_pilot_the_way_to_the_town_hall.mjs — FINDING THE WAY, rung 3 (#173,
 * doc/land-navigation.md 1.4; operator 2026-11-10: "install that nav system into the x and give it townhall destination"),
 * walked in the real page against the real world server:
 *   1. a nav unit is made of circuits, a compass, gears and glass at the machine shop, and is a craft part (a unit piece);
 *   2. built into a craft, at the controls the HUD gives the way to the town hall — distance and bearing from where the
 *      unit believes the craft is, which way to turn, and how far out it may be: nothing at its fix (take-off);
 *   3. the distance it gives is the real distance to the town hall's door (land.js townSpawn) within its error;
 *   4. with 24 satellites in orbit it says whether it has a satellite fix as the orbits give it for that place and moment,
 *      and with a fix the Map shows the whole planet (#173 rung 5).
 *
 * Run: node tests/test_a_craft_with_a_nav_unit_tells_its_pilot_the_way_to_the_town_hall.mjs   (needs chrome, python3)
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

const RJ = JSON.parse((await import("node:fs")).readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
const nr = RJ.recipes.find((r) => r.id === "nav_unit");
ok(nr && ["circuit", "compass", "gear", "glass"].every((i) => nr.uses.some(([x]) => x === i)) && nr.with.includes("machine_shop"), "a nav unit is circuits, a compass, gears and glass at the machine shop");
ok(RJ.items.nav_unit && RJ.items.nav_unit.places === Wd.B.navunit && RJ.items.nav_unit.unit && RJ.flight.unit_mass[String(Wd.B.navunit)] > 0, "…a craft part with its own size and mass");
try {
  const PAid = (await getJ("/fixture/plot")).plot;
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ steel_plate: 2, thruster: 2, pilot_seat: 1, nav_unit: 1 })) + "&tools=" + encodeURIComponent(JSON.stringify(["pick"])));
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
  const nav = [X + 220, Z + 40, Y + 10, 40, 30, 30, 78];                    // the nav unit, on the hull beside the seat
  const built = await (await fetch(base + "/land/api/boxes", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ plot: PAid, add: [hull, seat, thr1, thr2, nav] }) })).json();
  ok(built.added === 5 || (Array.isArray(built.added) && built.added.length === 5), "a hull, a seat, two thrusters and a nav unit are built: " + JSON.stringify(built).slice(0, 200));

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
  // 2. at the controls: the nav line
  ok(await until(B, "/Nav: town hall/.test(document.getElementById('hudPos').textContent)", 15000), "with a nav unit, the HUD gives the way to the town hall: " + await evl(B, "document.getElementById('hudPos').textContent"));
  const line = await evl(B, "document.getElementById('hudPos').textContent");
  const m = line.match(/town hall ([\d.]+) (km|m), bearing (\d+)° — (.+?) · ±(\d+) m/);
  ok(m && Number(m[5]) <= 1, "…taking off is its fix: it may be out by nothing yet (±" + (m && m[5]) + " m)");
  const dist = m ? Number(m[1]) * (m[2] === "km" ? 1000 : 1) : -1;
  ok(m && /ahead|right|left/.test(m[4]), "…and which way to turn: " + (m && m[4]));
  // the real distance, from where the world server holds the craft to the town hall's door (land.js townSpawn)
  const TOWN = Wd.plotCoords(Number((await import("node:fs")).readFileSync(join(ROOT, "static", "land.js"), "utf8").match(/const TOWN_HALL_PLOT = (\d+)/)[1]));
  const cp = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0].pose;
  const real = Math.hypot(TOWN.u0 + 8.5 - cp[1], TOWN.v0 + 1.5 - cp[2]);
  ok(m && Math.abs(dist - real) <= (m[2] === "km" ? 60 : 2) + Number(m[5]), `…and the distance it gives is the real one to the town hall's door (${m && m[1]} ${m && m[2]}; measured ${real.toFixed(0)} m)`);
  // 4. SATELLITES (#173, rung 5): 24 in orbit — the nav unit says whether it has a fix exactly as the orbits give it for
  // this place and moment (four in view), and with one the Map shows the whole planet; without one it says why
  await getJ("/fixture/sats?n=24");
  await evl(B, "location.reload(), true");                                  // the page asks how many are up as it starts
  await until(B, "/Nav: town hall/.test(document.getElementById('hudPos').textContent)", 30000);
  await sleep(2000);
  const C = await import(join(ROOT, "static", "land-cosmos.js"));
  const cp2 = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0].pose;
  const view = C.satsInView(24, Wd.posOf(cp2[0], cp2[1], cp2[2], cp2[3]), Date.now() / 1000 - C.EPOCH).length;
  const hud2 = await evl(B, "document.getElementById('hudPos').textContent");
  ok(view >= 4 ? new RegExp(`satellite fix \\(${view} in view\\)`).test(hud2) : new RegExp(`dead reckoning \\(${view} of 4`).test(hud2),
    `with 24 satellites up, the nav unit says what the orbits give here and now (${view} in view): ` + hud2.split("\n")[1]);
  await evl(B, "document.getElementById('mapBtn').click(), true");
  if (view >= 4) {
    ok(await until(B, "/The whole planet/.test(document.getElementById('mapLegend').textContent)", 15000), "…with a fix the Map shows the whole planet");
    const px = await evl(B, "(() => { const c = document.getElementById('mapCanvas'), g = c.getContext('2d'), h = c.width / 2; const cnt = (x0) => { const d = g.getImageData(x0, 0, h, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (!(d[i] === 0x1b && d[i + 1] === 0x24 && d[i + 2] === 0x30)) n++; return n; }; return [cnt(0), cnt(h)]; })()");
    ok(px[0] > 20000 && px[1] > 20000, `…both hemispheres painted from the planet's ground (${px[0]} and ${px[1]} pixels)`);
  } else {
    ok(await until(B, "/four satellites in view/.test(document.getElementById('mapLegend').textContent)", 15000), "…without a fix the Map says it needs four satellites in view");
  }
  await shot(B, "planet");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
