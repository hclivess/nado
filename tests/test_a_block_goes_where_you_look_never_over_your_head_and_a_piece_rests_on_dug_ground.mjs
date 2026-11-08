/*
 * test_a_block_goes_where_you_look_never_over_your_head_and_a_piece_rests_on_dug_ground.mjs — placing, walked in the
 * real page against the real world server (tests/_land_live_fixture.py), as the plot's owner:
 *   1. looking straight down at the cell under their own feet with earth in hand, a tap places nothing — and the page
 *      says they stand there. It used to climb past their body and put the block above their head ("im looking at the
 *      ground, i place a block and it places above my head", operator 2026-11-07);
 *   2. jump and place under ("the jump + place under should work", operator 2026-11-07): holding Jump and tapping Place
 *      while looking down puts the block into the cell they jumped from, and they land on it, a block higher;
 *   3. looking into a pit dug two layers deep, a plank piece goes onto the pit's floor — not onto the ground's
 *      untouched height a metre and more above it, where it hung in the air (land.js groundAt).
 *
 * Run:  node tests/test_a_block_goes_where_you_look_never_over_your_head_and_a_piece_rests_on_dug_ground.mjs   (needs chromium, python3)
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
const plotEdits = async () => (await (await fetch(base + "/land/api/plot?plot=" + PA_ID)).json());
let PA_ID;
try {
  PA_ID = (await getJ("/fixture/plot")).plot;
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ dirt: 5 })) + "&tools=" + encodeURIComponent(JSON.stringify(["shovel", "pick"])));
  const { token } = await getJ("/fixture/owner_token");
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });

  // 1. straight down at the feet, earth in hand: the block goes under them and they stand on it — it used to be refused
  // with "You are standing there" ("very stupid and only hinders", operator 2026-11-08), and before that it went over
  // their head ("im looking at the ground, i place a block and it places above my head", 2026-11-07)
  const vu = Math.floor(SV.u), vv = Math.floor(SV.v), vh = Math.floor(SV.h), hV = Math.round(SV.h - Wd.SEA);
  await stand(B, vu + 0.5, vv + 0.5, SV.h, 0, -1.5707);
  ok(await until(B, "document.getElementById('hotName').textContent === 'Earth'", 10000), "earth is in hand");
  ok(await until(B, `document.body.dataset.place === '${vu},${vv},${vh}'`, 10000),
     `the outline shows the cell at their feet before the tap (${vu},${vv},${vh}): ` + await evl(B, "document.body.dataset.place"));
  await evl(B, "document.getElementById('tPlace').click(), true");
  let e1 = [];
  for (let t = 0; t < 20 && !e1.length; t++) { await sleep(300); e1 = ((await plotEdits()).edits || []).filter(([x, z, y, b]) => b === Wd.B.dirt); }
  ok(e1.length === 1 && e1[0][0] === vu - q.u0 && e1[0][1] === vv - q.v0 && e1[0][2] === vh,
     "looking down at their own feet, the block goes under them — not over their head, and not refused: " + JSON.stringify(e1));
  ok(await until(B, `document.getElementById('hudPos').textContent.includes('height ${hV + 1} m')`, 8000), "…and they stand on it, a block higher: " + await hudText(B));
  ok(!(await evl(B, "/You are standing there/.test(document.body.textContent)")), "…with no 'You are standing there'");

  // 1b. FILLING A HOLE BACK ("filling back in dirt is very inaccurate … sometimes it places it above at other times below,
  // and sometimes both", operator 2026-11-08): a cell dug 2 m ahead, looked into from the side and from above — the
  // outline shows that very cell before the tap, and the block goes exactly there, once
  const fu = Math.floor(SO.u), fv = Math.floor(SO.v);
  // a flat strip of four cells along v (same top, nothing standing on it), clear of the other spots: stand on its first
  // two, the hole in its third
  let strip = null;
  for (let du = 6; du < 15 && !strip; du++) for (let dv = 6; dv < 11 && !strip; dv++) {
    const u = q.u0 + du, v = q.v0 + dv, top = Wd.column(q.face, u, v).top;
    if ([0, 1, 2, 3].every((k) => Wd.column(q.face, u, v + k).top === top && Wd.terrainBlock(q.face, u, v + k, top + 1) === Wd.B.air
        && Wd.terrainBlock(q.face, u, v + k, top + 2) === Wd.B.air)) strip = { u, v };
  }
  ok(!!strip, "a flat strip to dig a hole in");
  const hu = strip.u, hv = strip.v + 2, htop = Wd.column(q.face, hu, hv).top;
  for (let t = 0; t < 40; t++) {
    const r = await (await fetch(base + "/land/api/set", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify({ cells: [[q.face, hu, hv, htop, 0]] }) })).json();
    if (!r.refused.length) break;
    await sleep(400);
  }
  // from 1.8 m back, at the middle of its far wall; and from its edge, straight down at its floor
  for (const [label, du, dv, tv, th] of [["from the side", 0.5, 0.2, hv + 0.95, htop + 0.5], ["from above", 0.5, 1.6, hv + 0.5, htop + 0.02]]) {
    const su = strip.u + du, sv = strip.v + dv, sh = Wd.column(q.face, Math.floor(su), Math.floor(sv)).top + 1, tx = hu + 0.5;
    const yaw = Math.atan2(tx - su, tv - sv), pitch = -Math.atan2(sh + EYE - th, Math.hypot(tx - su, tv - sv));
    await stand(B, su, sv, sh, yaw, pitch);
    const seen = await until(B, `document.body.dataset.place === '${hu},${hv},${htop}'`, 10000);
    ok(seen, `looking into the hole ${label}, the outline shows the hole's cell (${hu},${hv},${htop}): ` + await evl(B, "document.body.dataset.place"));
    if (!seen) continue;
    await evl(B, "document.getElementById('tPlace').click(), true");
    let put = [];
    for (let t = 0; t < 20 && !put.length; t++) { await sleep(300); put = ((await plotEdits()).edits || []).filter(([x, z, y, b]) => b === Wd.B.dirt && x === hu - q.u0 && z === hv - q.v0); }
    ok(put.length === 1 && put[0][2] === htop, `…and the block goes into exactly that cell, once — not above it, not below: ` + JSON.stringify(put));
    // dig it out again for the next look
    for (let t = 0; t < 40; t++) {
      const r = await (await fetch(base + "/land/api/set", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({ cells: [[q.face, hu, hv, htop, 0]] }) })).json();
      if (!r.refused.length) break;
      await sleep(400);
    }
  }

  // 2. jump and place under: hold Jump, tap Place, let go
  const h0 = Math.round(SO.h - Wd.SEA);
  await stand(B, fu + 0.5, fv + 0.5, SO.h, 0, -1.5707);
  await evl(B, "document.getElementById('tJump').dispatchEvent(new Event('touchstart', { cancelable: true })), true");
  await sleep(600);                                    // the jump under way (software rendering runs a few frames a second)
  await evl(B, "document.getElementById('tPlace').click(), true");
  await sleep(300);
  await evl(B, "document.getElementById('tJump').dispatchEvent(new Event('touchend')), true");
  let under = null;
  for (let t = 0; t < 20 && !under; t++) { await sleep(300); under = ((await plotEdits()).edits || []).find(([x, z, y, b]) => b === Wd.B.dirt && x === fu - q.u0 && z === fv - q.v0) || null; }
  const feet = Math.floor(SO.h);
  ok(under && under[2] === feet && under[0] === fu - q.u0 && under[1] === fv - q.v0,
     `jump and place: the block goes into the cell they jumped from (layer ${feet}): ` + JSON.stringify(under));
  ok(await until(B, `document.getElementById('hudPos').textContent.includes('height ${h0 + 1} m')`, 8000),
     "…and they land on it, a block higher: " + await hudText(B));

  // 3. a plank piece into a pit dug two layers deep, 3 m ahead
  const pu = fu, pv = fv + 3, cells = [];
  const tops = {};
  for (let du = -1; du <= 1; du++) for (let dv = -1; dv <= 1; dv++) {
    const u = pu + du, v = pv + dv, c = Wd.column(q.face, u, v); tops[u + ":" + v] = c;
    cells.push([q.face, u, v, c.top + 1, 0], [q.face, u, v, c.top, 0], [q.face, u, v, c.top - 1, 0]);
  }
  for (const c of cells) {
    for (let t = 0; t < 40; t++) {
      const r = await (await fetch(base + "/land/api/set", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({ cells: [c] }) })).json();
      if (!r.refused.length || !/too fast|rate/.test(String(r.refused[0][1]))) break;
      await sleep(400);
    }
  }
  const mid = tops[pu + ":" + pv], floor = mid.top - 1;
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ planks: 10 })));
  await stand(B, SO.u, SO.v, SO.h, 0, -Math.atan2(SO.h + EYE - floor, pv + 0.5 - SO.v));
  await until(B, "!!document.querySelector('#hotbar .hs[title=\"Planks\"]')", 10000);
  await evl(B, "document.querySelector('#hotbar .hs[title=\"Planks\"]').click(), true");
  ok(await until(B, "document.getElementById('hotName').textContent === 'Planks'", 5000), "planks are in hand");
  await evl(B, "document.getElementById('tPlace').click(), true");
  let box = null;
  for (let t = 0; t < 20 && !box; t++) { await sleep(500); box = ((await plotEdits()).boxes || []).find((b) => b[6] === Wd.B.planks) || null; }
  ok(box && Math.abs(box[2] - floor * 100) <= 12, `a plank piece goes onto the pit's floor (${floor * 100} cm), not the untouched ground's height (${Math.round(mid.height * 100)} cm): ` + JSON.stringify(box));
  // 4. REAL TIME AT A LOW FRAME RATE: a frame's time was cut to 0.05 s, so below 20 fps everything ran in slow motion — on
  // the live page at 2 fps, nine seconds of walking moved about a metre ("very laggy on a phone", 2026-11-08). With the
  // processor slowed fourfold, holding Forward for 3 s walks most of the 13.8 m a walker covers in that time.
  const SW = spot(1, 1);                                           // east along the plot's first row, clear of the pits
  await stand(B, SW.u, SW.v, SW.h, Math.PI / 2, 0);
  const posNow = async () => { const p = JSON.parse(await evl(B, "localStorage.getItem('nado_land_v1')")).p; return [p[1], p[2]]; };
  await send(B, "Emulation.setCPUThrottlingRate", { rate: 4 });
  const fps = await evl(B, "new Promise((r) => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < 3000) requestAnimationFrame(f); else r(n / 3); }; requestAnimationFrame(f); })");
  await evl(B, "localStorage.removeItem('nado_land_v1'), true");
  let p0 = null;
  for (let t = 0; t < 120 && !p0; t++) { await sleep(250); p0 = await evl(B, "localStorage.getItem('nado_land_v1')"); }
  const a0 = await posNow();
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "KeyW", key: "w", windowsVirtualKeyCode: 87 });
  await sleep(3000);
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "KeyW", key: "w", windowsVirtualKeyCode: 87 });
  await evl(B, "localStorage.removeItem('nado_land_v1'), true");
  let p1 = null;
  for (let t = 0; t < 120 && !p1; t++) { await sleep(250); p1 = await evl(B, "localStorage.getItem('nado_land_v1')"); }
  const a1 = await posNow(), walked = Math.hypot(a1[0] - a0[0], a1[1] - a0[1]);
  await send(B, "Emulation.setCPUThrottlingRate", { rate: 1 });
  // keys are read once a frame, so the time held is known to a frame either way: at least 60 % of 3 s at WALK (4.6 m/s)
  ok(fps < 20, `the frame rate is low enough to tell (${fps.toFixed(1)} frames a second, under the old 20)`);
  ok(walked > 0.6 * 4.6 * 3, `at ${fps.toFixed(1)} frames a second, 3 s of walking covers ${walked.toFixed(1)} m (a walker: 13.8 m; in slow motion, ${(4.6 * 3 * Math.min(1, fps * 0.05)).toFixed(1)} m)`);
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
