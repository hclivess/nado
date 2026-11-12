/*
 * test_a_part_is_chosen_in_the_bag_placed_into_its_neighbours_and_flown_as_a_craft_in_the_page.mjs — PARTS (#175: "this is
 * xwing … not your shitty jet full of fucking disconnect metal plates", "there are gaps between every fucking part",
 * operator 2026-11-11), walked in the real page against the real world server (tests/_land_live_fixture.py) as a player
 * on a phone, with taps only:
 *   1. a craft of parts — a hull, a wing sunk into it, an engine standing in its side (pitched up: it pushes up, a
 *      lifting engine), a seat under a glass canopy — is drawn, boarded by Use, is an aircraft (#191: it has a wing)
 *      whose HUD reads the throttle and the angle of attack, the world server holds the engine's two thrusters as its
 *      thrust, Jump works the lifting engine and it climbs with its exhaust lit, Down lands it, and /dock sets every
 *      part down again as the part it was;
 *   2. the bag has the ten parts; hull chosen, its taper is a select and the piece in hand is named "hull 0.4"; Place
 *      puts that hull on the plot (the world server holds its shape byte);
 *   3. a plank is placed INSIDE a part's box (a hoop standing over the spot): the page no longer refuses what merely
 *      shares a part's box;
 *   4. engine chosen with steel plate in hand, Place says an engine is made of thrusters and places nothing; with a
 *      thruster in hand it is placed and costs the thrusters its size comes to; no page errors.
 * SHOTS=<dir> keeps a picture of each step.
 *
 * Run:  node tests/test_a_part_is_chosen_in_the_bag_placed_into_its_neighbours_and_flown_as_a_craft_in_the_page.mjs   (needs chrome, python3)
 */
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PROTOCOL_JS } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const Sh = await import(join(ROOT, "static", "land-shapes.js"));
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
const conType = async (sid, text) => {
  await send(sid, "Input.dispatchKeyEvent", { type: "keyDown", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await send(sid, "Input.dispatchKeyEvent", { type: "keyUp", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
  await until(sid, "document.activeElement && document.activeElement.id === 'conIn'", 8000);
  await send(sid, "Input.insertText", { text });                 // the / that opened the console is already in it
  await send(sid, "Input.dispatchKeyEvent", { type: "keyDown", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  await send(sid, "Input.dispatchKeyEvent", { type: "keyUp", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
  await sleep(1500);
  return evl(sid, "document.getElementById('conLog').textContent.slice(-400)");
};
try {
  const { token } = await getJ("/fixture/owner_token");
  const PAid = (await getJ("/fixture/plot")).plot;
  const enc = (o) => encodeURIComponent(JSON.stringify(o));
  await getJ(`/fixture/animal?kind=rabbit&u=${q.u0 + 400}&v=${q.v0 + 400}`);   // the herd held still and far off
  await getJ("/fixture/seed?who=owner&items=" + enc({ steel_plate: 4, thruster: 4, pilot_seat: 1, glass: 1, planks: 2 }) + "&tools=" + enc(["pick"]));
  const auth = { "Content-Type": "application/json", Authorization: "Bearer " + token };
  const post = async (p, o) => (await fetch(base + p, { method: "POST", headers: auth, body: JSON.stringify(o) })).json();
  const plotBoxes = async () => (await (await fetch(base + "/land/api/plot?plot=" + PAid, { headers: auth })).json()).boxes || [];
  const inv = async () => (await fetch(base + "/land/api/inventory", { headers: auth })).json();
  const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

  // ---- 1. a craft of parts ---------------------------------------------------------------------------------------
  let site = null;
  for (let du = 2; du < 7 && !site; du++) for (let dv = 2; dv < 10 && !site; dv++) {       // level ground under all of it, and to stand on north of it
    const u = q.u0 + du, v = q.v0 + dv, top = Wd.column(q.face, u, v).top;
    const cols = []; for (let a = -2; a < 5; a++) for (let b = -1; b < 6; b++) cols.push([u + a, v + b]);
    if (cols.every(([cu, cv]) => Wd.column(q.face, cu, cv).top === top)) site = { du, dv, top };
  }
  ok(!!site, "a flat site for the craft");
  const X = site.du * 100, Z = site.dv * 100, Y = (site.top + 1) * 100;
  const hull = [X, Z, Y, 200, 300, 120, 64, Sh.code(Sh.HULL, 6)], wing = [X + 150, Z + 60, Y + 50, 300, 200, 20, 64, Sh.code(Sh.WING, 5)];
  const engine = [X - 100, Z - 50, Y + 165, 130, 440, 130, 65, Sh.code(Sh.ENGINE), 0, 900, 0], seat = [X + 60, Z + 100, Y + 120, 80, 90, 110, 66];   // pitched 90° about its centre: a lifting engine standing from Y + 10 to Y + 450 (#191)
  const canopy = [X + 30, Z + 70, Y + 100, 140, 200, 140, 12, Sh.code(Sh.CANOPY)];
  ok(Wd.boxesOverlap(hull, wing) && Wd.boxesOverlap(hull, engine) && Wd.boxesOverlap(canopy, seat), "(the wing and the engine are sunk into the hull, the seat stands in the canopy's box)");
  const built = await post("/land/api/boxes", { plot: PAid, add: [hull, wing, engine, seat, canopy] });
  ok(Array.isArray(built.added) ? built.added.length === 5 : built.added === 5, "a hull, a wing, an engine, a seat and a canopy are built: " + JSON.stringify(built).slice(0, 300));
  ok((await inv()).items.thruster === 2, "…the engine, 1.3 × 4.4 × 1.3 m, for two of the four thrusters");

  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  // stand 2.2 m north of the hull's front, looking back at the canopy over it
  const su = q.u0 + (X + 100) / 100, sv = q.v0 + (Z + 170) / 100;
  const pv = q.v0 + (Z + 300) / 100 + 2.2, ph = site.top + 1;
  await stand(B, su, pv, ph, Math.PI, -Math.atan2(ph + EYE - (Y + 180) / 100, pv - sv));
  await shot(B, "parts-docked");
  const aimed = await conType(B, "aim");
  ok(/Aiming at (Glass|Steel plate|Pilot seat)/.test(aimed), "the player aims at the craft's own parts: " + aimed.slice(-120));
  await evl(B, "document.getElementById('tUse').click(), true");
  ok(await until(B, "/Flying/.test(document.getElementById('hudPos').textContent)", 15000), "Use on a part of it takes the controls: " + await hudText(B));
  ok(/throttle 0 %/.test(await evl(B, "document.getElementById('hudPos').textContent")) && /attack/.test(await evl(B, "document.getElementById('hudPos').textContent")), "…an aircraft's HUD (#191: it has a wing): the throttle shut, the angle of attack");
  const crafts = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts;
  ok(crafts.length === 1 && crafts[0].pieces.length === 5 && crafts[0].pieces.filter((p) => Wd.isPart(p)).length === 4 && crafts[0].thrust === 60,
     "the world server holds one craft of five pieces, four of them parts, pushing 60 kN: " + JSON.stringify(crafts.map((c) => [c.pieces.length, c.thrust, c.mass])));
  const h0 = crafts[0] ? crafts[0].pose[3] : 0;
  await evl(B, "document.getElementById('tJump').dispatchEvent(new Event('touchstart', { cancelable: true })), true");
  await sleep(2500);
  await until(B, "/ [1-9]\\d*\\.\\d m up/.test(document.getElementById('hudPos').textContent)", 10000);
  ok(/ [1-9]\d*\.\d m up/.test(await evl(B, "document.getElementById('hudPos').textContent")), "holding Jump, the lifting engine takes it up: " + await hudText(B));
  await shot(B, "parts-flying");
  await evl(B, "document.getElementById('tJump').dispatchEvent(new Event('touchend', { cancelable: true })), true");
  let h1 = h0;
  for (let t = 0; t < 20 && h1 <= h0 + 1; t++) { await sleep(500); const c = (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0]; h1 = c ? c.pose[3] : h0; }
  ok(h1 > h0 + 1, `…and the craft of parts climbs (${h0.toFixed(2)} -> ${h1.toFixed(2)} m)`);
  await evl(B, "document.getElementById('tDown').dispatchEvent(new Event('touchstart', { cancelable: true })), true");
  ok(await until(B, "/ 0\\.0 m up/.test(document.getElementById('hudPos').textContent)", 30000), "holding Down lands it: " + await hudText(B));
  await evl(B, "document.getElementById('tDown').dispatchEvent(new Event('touchend', { cancelable: true })), true");
  await conType(B, "dock");
  let boxes = [];
  for (let t = 0; t < 20 && !boxes.some((b) => b[6] === 66); t++) { await sleep(500); boxes = await plotBoxes(); }
  const kinds = (bs) => bs.map((b) => [b[3], b[4], b[5], b[6], b.length > 7 ? b[7] : 0].join(",")).sort().join(" ");
  ok(boxes.length === 5 && kinds(boxes) === kinds([hull, wing, engine, seat, canopy]), "/dock sets every part down as the part it was: " + JSON.stringify(boxes));
  ok((await inv()).items.thruster === 2, "…costing no thruster again");

  // ---- 2. the bag ----------------------------------------------------------------------------------------------------
  const s0 = spot(13, 9);                                  // well east of the craft
  const gy = Wd.column(q.face, Math.floor(s0.u), Math.floor(s0.v + 2.5)).height;
  await stand(B, s0.u, s0.v, s0.h, 0, -Math.atan2(s0.h + EYE - gy, 2.5));       // looking down at the ground 2.5 m ahead (north)
  const tap = (sel) => evl(B, `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.click(); return true; })()`);
  const size = (w, d, h) => evl(B, `(() => { for (const [id, v] of [["pzW", ${w}], ["pzD", ${d}], ["pzH", ${h}]]) { const e = document.getElementById(id); e.value = String(v); e.dispatchEvent(new Event("change")); } return true; })()`);
  const hold = async (name) => { await until(B, `!!document.querySelector('#hotbar .hs[title="${name}"]')`, 10000); await tap(`#hotbar .hs[title="${name}"]`); return until(B, `document.getElementById('hotName').textContent === '${name}'`, 5000); };
  await tap("#tPal"); await sleep(800);
  const chips = await evl(B, "[...document.querySelectorAll('[data-part]')].map((e) => e.textContent)");
  ok(same(chips, Sh.TYPES), "the bag has the ten parts: " + chips.join(", "));
  await tap('[data-part="2"]'); await sleep(400);
  ok(await evl(B, "(() => { const s = document.getElementById('pzVar'); return !!s && s.options.length === 10 && s.value === '3' && s.selectedOptions[0].textContent === '0.4'; })()"), "hull chosen, its taper is a select, at 0.4");
  ok(await evl(B, "document.querySelector('[data-part=\"2\"]').getAttribute('aria-pressed') === 'true' && /of a block/.test(document.getElementById('palette').textContent)"), "…the chip is pressed, and the bag says what it takes of a block");
  await size(120, 200, 80);
  await tap("#palClose"); await sleep(500);
  ok(await hold("Steel plate"), "steel plate is in hand");
  const info = await evl(B, "document.getElementById('pieceInfo').textContent");
  ok(/Piece 120 × 200 × 80 cm/.test(info) && /hull 0\.4/.test(info), "the piece in hand is a hull 0.4: " + info);
  await tap("#tPlace");
  let placed = null;
  for (let t = 0; t < 30 && !placed; t++) { await sleep(500); placed = (await plotBoxes()).find((b) => b[6] === 64 && b[7] === Sh.code(Sh.HULL, 3)) || null; }
  ok(placed && same(placed.slice(3, 6), [120, 200, 80]), "Place puts that hull on the plot, the world server holding its shape: " + JSON.stringify(placed));
  if (placed) await post("/land/api/boxes", { plot: PAid, remove: [placed] });

  // ---- 3. a box in a part's box ---------------------------------------------------------------------------------------
  // a thin hoop 4 m across stands over the spot the look meets the ground at (where the hull just went), 30 cm beyond it
  // and sunk 60 cm, so its rim passes under the plank and round it: the plank is in the hoop's box, in none of the hoop
  const ax = placed ? placed[0] + placed[3] / 2 : 0, az = placed ? placed[1] + placed[4] / 2 : 0, ay = placed ? placed[2] : 0;
  const hoop = [ax - 200, az + 20, ay - 60, 400, 20, 400, 64, Sh.code(Sh.RING, 9)];
  const hooped = await post("/land/api/boxes", { plot: PAid, add: [hoop] });
  ok(hooped.added === 1, "(a hoop is built over the spot: " + JSON.stringify(hooped).slice(0, 160) + ")");
  await stand(B, s0.u, s0.v, s0.h, 0, -Math.atan2(s0.h + EYE - gy, 2.5));
  await tap("#tPal"); await sleep(800);
  // (the test's stand() writes a place alone, so the page comes back with a plain piece: the chip is pressed on, then off)
  await tap('[data-part="2"]'); await sleep(300);
  ok(await evl(B, "!!document.getElementById('pzVar') && document.querySelector('[data-part=\"2\"]').getAttribute('aria-pressed') === 'true'"), "(the hull chip is pressed)");
  await tap('[data-part="2"]'); await sleep(300);                                // pressed again: back to a plain piece
  ok(await evl(B, "!document.getElementById('pzVar') && document.querySelector('[data-part=\"2\"]').getAttribute('aria-pressed') === 'false'"), "the chip pressed again is a plain piece");
  await size(100, 100, 100);
  await tap("#palClose"); await sleep(500);
  ok(await hold("Planks"), "planks are in hand");
  await tap("#tPlace");
  let plank = null;
  for (let t = 0; t < 30 && !plank; t++) { await sleep(500); plank = (await plotBoxes()).find((b) => b[6] === Wd.B.planks) || null; }
  ok(plank && Wd.boxesOverlap(plank, hoop), "a plank is placed inside the hoop's box, where the hoop is not: " + JSON.stringify(plank));
  await sleep(1500);
  await shot(B, "parts-hoop");
  // (the plank goes: an engine 3 m long set against its near side would reach back into the player — "no room", rightly)
  if (plank) await post("/land/api/boxes", { plot: PAid, remove: [plank] });
  await sleep(1500);

  // ---- 4. an engine is made of thrusters ---------------------------------------------------------------------------------
  await tap("#tPal"); await sleep(800);
  await tap('[data-part="4"]'); await sleep(300);
  await size(100, 300, 100);
  ok(await evl(B, "/it takes 1 and pushes 30 kN/.test(document.getElementById('palette').textContent)"), "engine chosen at 100 × 300 × 100, the bag says it takes 1 thruster and pushes 30 kN");
  await tap("#palClose"); await sleep(500);
  ok(await hold("Steel plate"), "steel plate is in hand");
  const before = (await plotBoxes()).length;
  await tap("#tPlace"); await sleep(1500);
  ok(/An engine is made of thrusters/.test(await evl(B, "document.body.innerText")) && (await plotBoxes()).length === before, "Place with steel plate says an engine is made of thrusters, and places nothing");
  ok(await hold("Thruster"), "a thruster is in hand");
  const info2 = await evl(B, "document.getElementById('pieceInfo').textContent");
  ok(/Piece 100 × 300 × 100 cm/.test(info2) && /engine/.test(info2), "…the piece in hand an engine of that size: " + info2);
  await tap("#tPlace");
  let eng = null;
  for (let t = 0; t < 30 && !eng; t++) { await sleep(500); eng = (await plotBoxes()).find((b) => b[6] === 65 && b[7] === Sh.code(Sh.ENGINE) && b[3] === 100) || null; }
  ok(eng && same(eng.slice(3, 6), [100, 300, 100]), "Place puts the engine on the plot: " + JSON.stringify(eng));
  ok((await inv()).items.thruster === 1, "…for one of the two thrusters left: " + JSON.stringify((await inv()).items));
  await sleep(2000);
  await shot(B, "parts-engine");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.stack || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
