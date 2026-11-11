/*
 * test_a_rocket_is_launched_from_its_pad_in_the_page_and_its_satellite_is_in_orbit.mjs — ROCKETS (#173,
 * doc/land-navigation.md 1.5; operator 2026-11-10: "requires launching orbital real physical gps satellites into orbit"),
 * walked in the real page against the real world server, as a player on a phone:
 *   1. a launch pad with a rocket engine, two propellant tanks and a positioning satellite on it, a chest beside it;
 *   2. Use on the chest: the propellant goes in;
 *   3. Use on the pad: the panel gives the rocket's numbers as the world server computes them — its parts, its mass, its
 *      thrust against its weight, its Δv less the gravity loss against the 1,096 m/s the orbit asks — and that it can
 *      reach orbit;
 *   4. Launch: the page says it is in orbit, the world server holds the satellite, and the rocket has left the pad.
 *
 * Run: node tests/test_a_rocket_is_launched_from_its_pad_in_the_page_and_its_satellite_is_in_orbit.mjs   (needs chrome, python3)
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
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ launch_pad: 1, rocket_engine: 1, propellant_tank: 2, nav_satellite: 1, chest: 1, propellant: 200 })) + "&tools=" + encodeURIComponent(JSON.stringify(["pick", "axe"])));   // the axe fells a tree by the site (below)
  const { token } = await getJ("/fixture/owner_token");
  // 1. on a flat site: smelter and its chest, then 3 m north the generator and its chest
  let site = null;
  for (let du = 2; du < 12 && !site; du++) for (let dv = 2; dv < 10 && !site; dv++) {
    const u = q.u0 + du, v = q.v0 + dv, top = Wd.column(q.face, u, v).top;
    const cols = []; for (let a = 0; a < 3; a++) for (let b = 0; b < 6; b++) cols.push([u + a, v + b]);
    // open ground (nothing standing on it), a metre of rise at most; the pieces stand on its highest point
    const tops = cols.map(([cu, cv]) => Wd.column(q.face, cu, cv).top);
    if (Math.max(...tops) - Math.min(...tops) <= 1 && cols.every(([cu, cv], k) => !Wd.BLOCKS[Wd.terrainBlock(q.face, cu, cv, tops[k] + 1)].solid && !Wd.BLOCKS[Wd.terrainBlock(q.face, cu, cv, tops[k] + 2)].solid))
      site = { du, dv, top: Math.max(...tops) };
  }
  ok(!!site, "an open site for the launch pad");
  // the owner clears the bushes around it: the meadow is thick with them, and leaves just off the site, where the
  // player stands to look in, took the aim off the smelter (2026-11-10, "Aiming at Leaves") though the site was open
  const brush = [];
  for (let cu = Math.max(0, site.du - 3); cu < Math.min(16, site.du + 6); cu++) for (let cv = Math.max(0, site.dv - 3); cv < Math.min(16, site.dv + 9); cv++) {
    const t = Wd.column(q.face, q.u0 + cu, q.v0 + cv).top;
    for (let k = 1; k <= 4; k++) if (Wd.BLOCKS[Wd.terrainBlock(q.face, q.u0 + cu, q.v0 + cv, t + k)].solid) brush.push([q.face, q.u0 + cu, q.v0 + cv, t + k, 0]);
  }
  // the owner stands in the middle of the site to clear it: a block is broken only within reach (#167)
  await fetch(base + "/land/api/move", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ p: [q.face, q.u0 + site.du + 1.5, q.v0 + site.dv + 3, site.top + 1, 0] }) });
  let cleared = brush.length ? null : { refused: [] };
  for (let t = 0; t < 40 && brush.length; t++) {
    cleared = await (await fetch(base + "/land/api/set", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify({ cells: brush }) })).json();
    // a cell the server already holds empty ("nothing here that can be gathered") is as clear as one just cleared
    cleared.refused = cleared.refused.filter(([, why]) => !/nothing here/.test(why));
    if (!cleared.refused.length) break;
    await sleep(400);
  }
  ok(cleared && !cleared.refused.length, `the bushes around it are cleared (${brush.length} blocks): ` + JSON.stringify(cleared && cleared.refused).slice(0, 200));
  const X = site.du * 100, Z = site.dv * 100, Y = (site.top + 1) * 100;
  const padB = [X, Z, Y, 300, 300, 20, 84], eng = [X + 120, Z + 120, Y + 20, 60, 60, 120, 81];
  const tank1 = [X + 100, Z + 100, Y + 140, 100, 100, 220, 82], tank2 = [X + 100, Z + 100, Y + 360, 100, 100, 220, 82];
  const sat = [X + 75, Z + 75, Y + 580, 150, 150, 150, 83], chestP = [X, Z + 300, Y, 90, 50, 55, 54];
  const built = await (await fetch(base + "/land/api/boxes", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ plot: PAid, add: [padB, eng, tank1, tank2, sat, chestP] }) })).json();
  ok(built.added === 6, "a launch pad with an engine, two tanks and a satellite on it, and a chest beside it, are built: " + JSON.stringify(built.refused));

  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  // stand 2.2 m from a box's centre and look at it — east of it by default; the smelter from another side (its chest is east)
  const centreOf = (b) => ({ u: q.u0 + (b[0] + b[3] / 2) / 100, v: q.v0 + (b[1] + b[4] / 2) / 100, h: (b[2] + b[5] / 2) / 100 });
  // …then, as a player would, check with /aim and tilt the view a little up or down until the crosshair is on it: on
  // uneven ground the player stands higher or lower than planned and the look landed on the ground before it (first runs)
  const NAME = { 54: "Chest", 84: "Launch pad" };
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
  // from each side given in turn, until the crosshair is on it (a bush or a tree's crown can stand in the way of one)
  const lookAt = async (b, ...froms) => {
    const c = centreOf(b), ph = site.top + 1;
    let said = "";
    for (const from of froms.length ? froms : ["east"]) {
      const [pu, pv, yaw] = { east: [c.u + 2.2, c.v, -Math.PI / 2], west: [c.u - 2.2, c.v, Math.PI / 2], north: [c.u, c.v + 2.2, Math.PI], south: [c.u, c.v - 2.2, 0] }[from];
      await stand(B, pu, pv, ph, yaw, -Math.atan2(ph + EYE - c.h, 2.2));
      said = await aimSays();
      for (const dy of [-15, 30, -45, 60, -75, 90]) {
        if (said.startsWith("Aiming at " + NAME[b[6]])) break;
        await tilt(dy);
        said = await aimSays();
      }
      if (said.startsWith("Aiming at " + NAME[b[6]])) break;
    }
    console.log(`  aim on ${NAME[b[6]]}: ${said}`);
  };
  // Use, again every 2 s until the panel it should open is open (the first tap can land before the page is ready)
  let panel = "chestPanel";
  const use = async () => { for (let t = 0; t < 8; t++) { await evl(B, "document.getElementById('tUse').click(), true"); if (await until(B, `!document.getElementById('${panel}').classList.contains('hidden')`, 2000)) return; } };
  const tap = (sel) => evl(B, `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.click(); return true; })()`);

  // 2. the propellant into the chest
  await lookAt(chestP, "north", "west"); await use();
  ok(await until(B, "!document.getElementById('chestPanel').classList.contains('hidden') && !!document.querySelector('[data-putall=\"propellant\"]')", 15000), "Use opens the chest beside the pad, with an All button for the propellant");
  await tap('[data-putall="propellant"]');
  ok(await until(B, "!!document.querySelector('[data-takeall=\"propellant\"]')", 10000), "All moves the propellant in");
  await tap("#chestClose");
  // 3. the pad: aimed at its corner, clear of the rocket standing in its middle
  const corner = [X, Z, Y, 60, 60, 20, 84];
  panel = "padPanel";
  await lookAt(corner, "west", "south"); await use();
  ok(await until(B, "/orbit needs 1096 m\\/s/.test(document.getElementById('padGrid').textContent)", 15000), "Use on the pad gives the rocket's numbers: " + (await evl(B, "document.getElementById('padGrid').textContent")).slice(0, 300));
  const txt = await evl(B, "document.getElementById('padGrid').textContent");
  ok(/Rocket engines: 1/.test(txt) && /Propellant tanks: 2/.test(txt) && /Satellites: 1/.test(txt) && /Propellant: 1574 kg/.test(txt), "…its engine, its two tanks, its satellite and the 1,574 kg of propellant it loads");
  ok(/It can reach orbit\./.test(txt), "…and that it can reach orbit");
  ok(/Flown: it reaches orbit 5\d\.\d km up/.test(txt), "…as the ascent flown through the air shows: " + (txt.match(/Flown:[^.]*?left/) || [""])[0]);
  // 4. launch
  await tap("#padGo");
  ok(await until(B, "/In orbit!/.test(document.body.innerText)", 15000), "Launch: the page says it is in orbit");
  const sats = (await getJ("/land/api/sats")).sats;
  ok(sats.length === 1 && sats[0].n === 0, "the world server holds the satellite: " + JSON.stringify(sats));
  const left = ((await getJ("/land/api/plot?plot=" + PAid)).boxes || []).filter((x) => [81, 82, 83].includes(x[6]));
  ok(left.length === 0, "the rocket has left the pad");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
