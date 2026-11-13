/*
 * test_a_flown_craft_tears_through_a_tree_in_the_page_and_the_world_server_fells_it.mjs — A CRAFT TEARS THROUGH TREES
 * (operator 2026-11-13, the X fighter wedged in a broadleaf after a landing on grass: "x fighter should tear trees down
 * through sheer force (minor damage perhaps)"), walked in the real page against the real world server
 * (tests/_land_live_fixture.py): static/land.js craftSolid / tearCells, scripts/land_server.py apply(craft=):
 *   1. a small hover craft built on the owner's plot 2.5 m south of the plot's one broadleaf, its nose at the trunk;
 *   2. Use on the seat takes the controls; held forward (W) it drives INTO the tree and THROUGH it — its seat ends up
 *      north of the trunk (a wall would have stopped it: the pilot test's check 6);
 *   3. the world server holds the trunk cell torn (an edit to air on the plot) and the tree above it felled with it, and
 *      the pilot gathered nothing (no wood, no sticks in the inventory);
 *   4. no page errors.
 * Run:  node tests/test_a_flown_craft_tears_through_a_tree_in_the_page_and_the_world_server_fells_it.mjs   (needs chrome, python3)
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
try {
  const PAid = (await getJ("/fixture/plot")).plot;
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ steel_plate: 2, thruster: 2, pilot_seat: 1 })));
  const { token } = await getJ("/fixture/owner_token");
  // 1. the plot's tree, and a flat site south of it for the craft (trees stand 2 columns from a plot's edge, so a hull
  // 1.5 m long fits between the edge and the trunk)
  const roots = Wd.treeRoots(q.face, q.u0, q.v0, Wd.PLOT);
  ok(roots.length >= 1, `the plot has a tree (${roots.length})`);
  const tree = roots[0], lu = tree.wu - q.u0, lv = tree.wv - q.v0, top = tree.col.top;
  const cols = []; for (let a = -1; a <= 3; a++) for (let b = 0; b < lv; b++) cols.push([tree.wu + a, q.v0 + b]);
  ok(cols.every(([cu, cv]) => Wd.column(q.face, cu, cv).top === top), `the ground south of the trunk is flat (${lv} m of it; a tuft or a flower on it is no wall)`);
  const trunk = Wd.terrainBlock(q.face, tree.wu, tree.wv, top + 1);
  ok(Wd.TREE_WOOD.has(trunk), `the planet's own trunk stands at the plot's (${lu}, ${lv}), ${tree.tree.kind} ${tree.tree.height} m`);
  const X = (lu - 1) * 100, Z = 0, Y = (top + 1) * 100;                         // the hull from the plot's south edge, 2.5 m short of the trunk
  const hull = [X, Z, Y, 300, 150, 10, 64], seat = [X + 110, Z + 30, Y + 10, 80, 90, 110, 66];
  const thr1 = [X - 100, Z, Y, 100, 100, 140, 65], thr2 = [X + 300, Z, Y, 100, 100, 140, 65];   // beside the hull (behind it is off the plot)
  const built = await (await fetch(base + "/land/api/boxes", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ plot: PAid, add: [hull, seat, thr1, thr2] }) })).json();
  ok(built.added === 4 || (Array.isArray(built.added) && built.added.length === 4), "a hull, a seat and two thrusters are built south of the tree: " + JSON.stringify(built).slice(0, 200));
  const items0 = (await getJ("/fixture/seed?who=owner&items=%7B%7D")).items || null;

  // 2. Use on the seat; held forward it goes through the tree
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const su = q.u0 + (X + 150) / 100, sv = q.v0 + (Z + 75) / 100;
  await stand(B, su, sv + 2.6, top + 1, Math.PI, -Math.atan2(top + 1 + EYE - (Y + 60) / 100, 2.6));
  await evl(B, "document.getElementById('tUse').click(), true");
  ok(await until(B, "/Flying/.test(document.getElementById('hudPos').textContent)", 15000), "Use on the seat takes the controls: " + await hudText(B));
  const craftNow = async () => (await getJ(`/land/api/crafts?face=${q.face}&u=${su}&v=${sv}`)).crafts[0];
  const c0 = await craftNow();
  ok(c0 && c0.pilot && c0.pieces.length === 4, "the world server holds the craft, piloted");
  const v0 = c0.pose[2];
  await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "KeyW", key: "w", windowsVirtualKeyCode: 87 });
  let c1 = c0;
  for (let t = 0; t < 60 && c1.pose[2] < tree.wv + 1.6; t++) { await sleep(500); c1 = await craftNow(); }
  await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "KeyW", key: "w", windowsVirtualKeyCode: 87 });
  ok(c1.pose[2] > v0 + 1, `held forward, the craft drives toward the tree (${(c1.pose[2] - v0).toFixed(2)} m)`);
  ok(c1.pose[2] > tree.wv + 1.6, `…and THROUGH it: its seat is north of the trunk now (seat v ${(c1.pose[2] - q.v0).toFixed(2)}, trunk at ${lv}..${lv + 1})`);

  // 3. the world server: the trunk torn, the tree felled, nothing gathered
  let edits = [];
  for (let t = 0; t < 20 && !edits.some((e) => e[0] === lu && e[1] === lv && e[2] === top + 1 && e[3] === 0); t++) { await sleep(500); edits = (await getJ(`/land/api/plot?plot=${PAid}`)).edits || []; }
  ok(edits.some((e) => e[0] === lu && e[1] === lv && e[2] === top + 1 && e[3] === 0), "the world server holds the trunk's lowest cell torn to air: " + JSON.stringify(edits.slice(0, 6)));
  const felled = edits.filter((e) => e[2] > top + 1 && e[3] === 0).length;
  ok(felled >= tree.tree.height - 1, `…and the tree above it came down with it (${felled} cells of it)`);
  const items1 = (await getJ("/fixture/seed?who=owner&items=%7B%7D")).items || null;
  ok(!items1 || !(items1.wood > ((items0 || {}).wood || 0)) && !(items1.sticks > ((items0 || {}).sticks || 0)), "…and the pilot gathered nothing of it: " + JSON.stringify(items1));
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ").slice(0, 400) : ""));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
