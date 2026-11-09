/*
 * test_a_field_is_tilled_sown_and_harvested_in_the_page.mjs — FARMING (#154: "farmland, farming, soil types, etc",
 * operator 2026-11-09), walked in the real page against the real world server (tests/_land_live_fixture.py) as a
 * player on a phone, with taps only:
 *   1. a hoe in the bag: Use on a meadow cell tills it, and the page says what soil it is (/aim says it too);
 *   2. the seed from the bag goes on the hotbar; Place sows it on the field;
 *   3. it ripens (the fixture brings its time forward; the world server's own loop grows it) and the player sees wheat;
 *   4. Break harvests it: the soil's grain and seed go into the bag;
 *   5. BREAD AND A WELL (#155): a well built where the crop stood; Use on it with a bucket draws a bucketful; Eat in the
 *      bag eats bread and the page says the player is well fed; no page errors.
 *
 * Run:  node tests/test_a_field_is_tilled_sown_and_harvested_in_the_page.mjs   (needs chrome, python3)
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
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ seed: 2 })) + "&tools=" + encodeURIComponent(JSON.stringify(["hoe"])));
  const { token } = await getJ("/fixture/owner_token");
  // a field cell: open turf (nothing on it), with turf 2 m east of it at the same layer to stand on, on a soil that tills
  let F = null;
  for (let du = 3; du < 12 && !F; du++) for (let dv = 3; dv < 13 && !F; dv++) {
    const u = q.u0 + du, v = q.v0 + dv, c = Wd.column(q.face, u, v), s = Wd.soilOf(q.face, u, v, c);
    const st = Wd.column(q.face, u + 2, v), mid = Wd.column(q.face, u + 1, v);
    if (Wd.terrainBlock(q.face, u, v, c.top) === Wd.B.grass && Wd.terrainBlock(q.face, u, v, c.top + 1) === Wd.B.air && R.farming.soil[s].till !== false
        && st.top === c.top && mid.top === c.top && [1, 2].every((d) => Wd.terrainBlock(q.face, u + d, v, c.top + 1) === Wd.B.air && Wd.terrainBlock(q.face, u + d, v, c.top + 2) === Wd.B.air))
      F = { u, v, top: c.top, soil: s };
  }
  ok(!!F, "an open meadow cell for a field, on " + (F && F.soil));
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const aimSays = async () => {
    await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
    await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Slash", key: "/", windowsVirtualKeyCode: 191 });
    await until(B, "document.activeElement && document.activeElement.id === 'conIn'", 5000);
    await send(B, "Input.insertText", { text: "aim" });
    await send(B, "Input.dispatchKeyEvent", { type: "keyDown", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
    await send(B, "Input.dispatchKeyEvent", { type: "keyUp", code: "Enter", key: "Enter", windowsVirtualKeyCode: 13 });
    await sleep(800);
    return evl(B, "(() => { const l = Array.from(document.getElementById('conLog').children).map((e) => e.textContent); const i = l.map((t) => /^Aiming at|^Nothing within/.test(t)).lastIndexOf(true); return i < 0 ? '' : l.slice(i).join(' | '); })()");
  };
  const tilt = async (dy) => {
    await send(B, "Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: 700, y: 200, id: 4 }] });
    await send(B, "Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: 700, y: 200 + dy, id: 4 }] });
    await send(B, "Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await sleep(600);
  };
  const at = `u ${F.u} · v ${F.v} · h `;
  // look at the field's cell from 2 m east, tilting until /aim names it (the ground under the crop, or the crop on it)
  const aimAt = async (name, h) => {
    let said = await aimSays();
    for (const dy of [-10, 20, -30, 40, -50, 60, -70]) {
      if (said.startsWith(`Aiming at ${name} — ${at}${h}`)) break;
      await tilt(dy); said = await aimSays();
    }
    console.log("  aim: " + said);
    return said;
  };
  const alert = () => evl(B, "(document.getElementById('alertBar') || {}).textContent || ''");
  const bag = () => evl(B, "document.getElementById('tPal').click(), new Promise((r) => setTimeout(() => { const t = document.getElementById('palGrid').textContent; document.getElementById('palClose').click(); r(t); }, 700))");

  // 1. TILL: Use on the turf with a hoe
  await stand(B, F.u + 2.5, F.v + 0.5, F.top + 1, -Math.PI / 2, -Math.atan2(EYE + 0.2, 2));
  let said = await aimAt("Grass", F.top);
  ok(said.startsWith(`Aiming at Grass — ${at}${F.top}`), "the player looks at a meadow cell");
  ok(new RegExp("Soil: " + { loam: "loam", clay: "clay soil", peat: "peat", sandy: "sandy soil" }[F.soil]).test(said), "/aim says what soil it is: " + said);
  await evl(B, "document.getElementById('tUse').click(), true");
  ok(await until(B, "/^Tilled: /.test((document.getElementById('alertBar') || {}).textContent || '')", 8000), "Use with a hoe tills it, and says the soil: " + await alert());
  await sleep(1500);
  said = await aimAt("Farmland", F.top);
  ok(said.startsWith(`Aiming at Farmland — ${at}${F.top}`), "…the cell is farmland now (the world server agrees: it is drawn from its edit)");

  // 2. SOW: seed from the bag, placed on the field
  await evl(B, "document.getElementById('tPal').click(), true"); await sleep(600);
  ok(await evl(B, "(() => { const b = document.querySelector('[data-pick=\"seed\"]'); if (!b) return false; b.click(); return true; })()"), "the seed is in the bag and goes on the hotbar");
  await evl(B, "document.getElementById('palClose').click(), true"); await sleep(400);
  await evl(B, "document.getElementById('tPlace').click(), true");
  await sleep(2000);
  said = await aimAt("Young wheat", F.top + 1);
  ok(said.startsWith(`Aiming at Young wheat — ${at}${F.top + 1}`), "Place sows it on the field, and a young crop stands there: " + said);

  // 3. it ripens (the fixture brings its time forward; the world server's own loop grows it)
  const due = await getJ("/fixture/ripen");
  ok(due.due >= 1, "the crop is growing on the server (" + due.due + " due)");
  let ripe = false;
  for (let t = 0; t < 8 && !ripe; t++) { await sleep(3000); said = await aimSays(); ripe = said.startsWith(`Aiming at Wheat — ${at}${F.top + 1}`); }
  ok(ripe, "…and ripens into wheat the player sees: " + said);
  await shot(B, "field");

  // 4. HARVEST: Break gives the soil's grain and seed
  const before = await bag();
  const n0 = Number((before.match(/(\d+) × Grain/) || [0, 0])[1]);
  await evl(B, "document.getElementById('tBreak').click(), true");
  await sleep(3000);
  const after = await bag(), n1 = Number((after.match(/(\d+) × Grain/) || [0, 0])[1]);
  ok(n1 - n0 === R.farming.soil[F.soil].grain, `the harvest gives the soil's grain: ${n1 - n0} (${F.soil} gives ${R.farming.soil[F.soil].grain})`);
  ok(/\d+ × Wheat seed/.test(after), "…and seed to sow again");
  // 5. a well where the crop stood, a bucket and a loaf
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ bread: 1, well: 1 })) + "&tools=" + encodeURIComponent(JSON.stringify(["hoe", "bucket"])));
  const U = R.items.well.unit, well = [(F.u - q.u0) * 100, (F.v - q.v0) * 100, (F.top + 1) * 100, U[0], U[1], U[2], Wd.B.well];
  const built = await (await fetch(base + "/land/api/boxes", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
    body: JSON.stringify({ plot: PA, add: [well] }) })).json();
  ok(built.added === 1, "a well is built where the crop stood: " + JSON.stringify(built.refused || ""));
  await stand(B, F.u + 2.6, F.v + 0.6, F.top + 1, -Math.PI / 2, -0.2);
  said = await aimAt("Well", F.top + 1);
  ok(said.startsWith(`Aiming at Well — ${at}${F.top + 1}`), "the player looks at the well");
  const w0 = Number(((await bag()).match(/(\d+) × Water/) || [0, 0])[1]);
  await evl(B, "document.getElementById('tUse').click(), true"); await sleep(1500);
  await evl(B, "document.getElementById('tUse').click(), true"); await sleep(1500);
  const w1 = Number(((await bag()).match(/(\d+) × Water/) || [0, 0])[1]);
  ok(w1 - w0 === 2, `Use on the well with a bucket draws a bucketful, and again (${w0} → ${w1})`);
  await evl(B, "document.getElementById('tPal').click(), true"); await sleep(600);
  ok(await evl(B, "(() => { const b = document.querySelector('[data-eat=\"bread\"]'); if (!b) return false; b.click(); return true; })()"), "the bag offers to eat the bread");
  ok(await until(B, "/^Well fed/.test((document.getElementById('alertBar') || {}).textContent || '')", 8000), "…and eating it says the player is well fed: " + await alert());
  ok(await until(B, "/Well fed: work goes quicker for \\d+ more min/.test(document.getElementById('palGrid').textContent)", 8000), "…which the bag shows, with the minutes left");
  await evl(B, "document.getElementById('palClose').click(), true");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
