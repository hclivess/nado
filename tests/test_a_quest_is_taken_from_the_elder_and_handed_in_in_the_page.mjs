/*
 * test_a_quest_is_taken_from_the_elder_and_handed_in_in_the_page.mjs — NPCS AND QUESTS (#165: "we may need npcs and
 * quests and move this a little towards world of warcraft as well", operator 2026-11-09), walked in the real page
 * against the real world server (tests/_land_live_fixture.py) as a player on a phone, with taps only:
 *   1. the elder stands in the street; Use on her opens her talk: the work she offers (the fixture names two quests);
 *   2. Accept "Bring 3 × Sticks" and "Carry a parcel to Tobin": both in the bag's quest log, the parcel in the bag;
 *   3. with the sticks, Use on her: Hand in — "Done: +20 experience", and the HUD shows the player's level;
 *   4. up to the trader: Use, Hand in the parcel — done, the parcel gone;
 *   5. no page errors.
 *
 * Run:  node tests/test_a_quest_is_taken_from_the_elder_and_handed_in_in_the_page.mjs   (needs chrome, python3)
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
  const R = await (await fetch(base + "/static/land-recipes.json")).json(), NPC = Object.fromEntries(R.quests.npcs.map((n) => [n.id, n]));
  const { token } = await getJ("/fixture/owner_token");
  await getJ("/fixture/quests");
  await getJ(`/fixture/animal?kind=rabbit&u=${q.u0 + 400}&v=${q.v0 + 400}`);   // the herd held still: nothing charges the walk
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const panel = () => evl(B, "document.getElementById('npcPanel').classList.contains('hidden') ? '' : document.getElementById('npcGrid').textContent");
  const tap = (sel) => evl(B, `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e || e.disabled) return false; e.click(); return true; })()`);
  const bag = () => evl(B, "document.getElementById('tPal').click(), new Promise((r) => setTimeout(() => { const t = document.getElementById('palGrid').textContent; document.getElementById('palClose').click(); r(t); }, 900))");
  // stand 2 m east of an NPC, facing them; Use until their talk opens (the first tap can land before the page is ready)
  const talkTo = async (id) => {
    const n = NPC[id], gh = Wd.column(n.at[0], Math.floor(n.at[1] + 2), Math.floor(n.at[2])).height;
    await stand(B, n.at[1] + 2, n.at[2], gh, -Math.PI / 2, -0.25);
    for (let i = 0; i < 6; i++) {
      await evl(B, "document.getElementById('tUse').click(), true");
      if (await until(B, "!document.getElementById('npcPanel').classList.contains('hidden') && document.getElementById('npcGrid').textContent.length > 3", 4000)) return true;
      if (i % 2) await stand(B, n.at[1] + 2, n.at[2], gh, -Math.PI / 2, i % 4 === 1 ? -0.05 : -0.4);   // another tilt
    }
    return false;
  };

  // 1. the elder's talk
  ok(await talkTo("elder"), "Use on the elder opens her talk");
  let t = await panel();
  ok(/Work offered/.test(t) && /Bring 3 × Sticks/.test(t) && /Carry a parcel to Tobin/.test(t), "she offers the work: " + t.slice(0, 160));

  // 2. accept both
  await tap('[data-qaccept="qb"]');
  ok(await until(B, "!/Bring 3 × Sticks/.test(document.getElementById('npcGrid').textContent) || /Your quests here/.test(document.getElementById('npcGrid').textContent)", 15000), "Accept takes the bring quest");
  await tap('[data-qaccept="qd"]');
  await sleep(2500);
  await evl(B, "document.getElementById('npcClose').click(), true");
  t = await bag();
  ok(/Quests/.test(t) && /Bring 3 × Sticks/.test(t) && /Carry a parcel to Tobin/.test(t), "both are in the bag's quest log");
  ok(/1 × Parcel/.test(t), "…and the parcel is in the bag");

  // 3. the sticks, handed in
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ sticks: 3 })));
  await sleep(1000);
  ok(await talkTo("elder"), "Use on the elder again");
  ok(await until(B, "!!document.querySelector('[data-turnin=\"qb\"]:not([disabled])')", 10000), "with the sticks, Hand in is there");
  await evl(B, "document.getElementById('alertBar') && (document.getElementById('alertBar').textContent = ''), true");
  await tap('[data-turnin="qb"]');
  ok(await until(B, "/Done: \\+20 experience/.test((document.getElementById('alertBar') || {}).textContent || '')", 15000), "Hand in: done, +20 experience");
  ok(await until(B, "/Level 1/.test(document.getElementById('hudHp').textContent)", 8000), "the HUD shows the player's level: " + await evl(B, "document.getElementById('hudHp').textContent"));
  await evl(B, "document.getElementById('npcClose').click(), true");

  // 4. the parcel to the trader
  ok(await talkTo("trader"), "Use on the trader opens his talk");
  ok(await until(B, "!!document.querySelector('[data-turnin=\"qd\"]:not([disabled])')", 10000), "the parcel can be handed to him");
  await tap('[data-turnin="qd"]');
  ok(await until(B, "/Done: \\+15 experience/.test((document.getElementById('alertBar') || {}).textContent || '')", 15000), "…delivered: +15 experience");
  await evl(B, "document.getElementById('npcClose').click(), true");
  t = await bag();
  ok(!/\d+ × Parcel/.test(t) && !/Carry a parcel/.test(t), "the parcel and the quest are gone from the bag");
  await shot(B, "quests");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
