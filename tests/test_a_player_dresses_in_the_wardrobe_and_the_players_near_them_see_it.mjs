/*
 * test_a_player_dresses_in_the_wardrobe_and_the_players_near_them_see_it.mjs — CLOTHES (#111) walked in the real page
 * against the real world server (tests/_land_live_fixture.py), as two players in two tabs:
 *   1. the owner, signed in with linen garments in their bag, opens the wardrobe from the bag, wears each garment by
 *      its own button and picks a skin — the wardrobe shows each one worn, and the bag no longer holds it;
 *   2. the visitor standing nearby is sent the owner's look with their position (the page's own websocket frames), and
 *      the page draws them;
 *   3. taking a garment off puts it back in the bag. No page errors.
 * SHOTS=<dir> also saves both tabs' screenshots.
 *
 * Run:  node tests/test_a_player_dresses_in_the_wardrobe_and_the_players_near_them_see_it.mjs     (needs chromium, python3)
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


const shot = async (sid, name) => {
  if (!process.env.SHOTS) return;
  const r = await send(sid, "Page.captureScreenshot", { format: "png" });
  writeFileSync(join(process.env.SHOTS, name + ".png"), Buffer.from(r.result.data, "base64"));
};
try {
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ linen_shirt: 1, linen_trousers: 1, linen_cap: 1, linen_cloak: 1 })));
  const { token } = await getJ("/fixture/owner_token");
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  await open(B, SO);
  const A = await tab();
  // the visitor stands 6 m west of the owner, facing them (yaw = atan2(du, dv))
  await send(A, "Page.navigate", { url: base + "/" });
  await until(A, "document.readyState === 'complete'");
  await evl(A, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${q.face}, ${SV.u}, ${SV.v}, ${SV.h}, ${Math.atan2(SO.u - SV.u, SO.v - SV.v)}, -0.12] })); true`);
  await send(A, "Page.reload", {});
  await until(A, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 30000);

  // 1. the wardrobe, from the bag
  ok(await until(B, "/Your plot/.test(document.getElementById('hudPlot').textContent)"), "the owner is signed in on their plot");
  await evl(B, "document.getElementById('tPal').click(), document.getElementById('wardOpen').click(), true");
  ok(await until(B, "!document.getElementById('wardPanel').classList.contains('hidden') && document.querySelectorAll('#wardGrid [data-wear]').length === 4"),
     "the wardrobe opens from the bag and offers the four garments in the bag");
  for (const g of ["linen_shirt", "linen_trousers", "linen_cap", "linen_cloak"]) {
    await evl(B, `document.querySelector('#wardGrid [data-wear="${g}"]').click(), true`);
    ok(await until(B, `!document.querySelector('#wardGrid [data-wear="${g}"]')`, 8000), "wears " + g + " by its own button");
  }
  await evl(B, "document.querySelector('#wardGrid [data-skin=\"3\"]').click(), true");
  ok(await until(B, "document.querySelector('#wardGrid [data-skin=\"3\"]').classList.contains('on')", 8000), "picks a skin");
  const txt = await evl(B, "document.getElementById('wardGrid').textContent");
  ok(["Linen shirt", "Linen trousers", "Linen cap", "Linen cloak"].every((n) => txt.includes(n)) && (txt.match(/Take off/g) || []).length === 4,
     "the wardrobe shows all four worn: " + txt.slice(0, 160));
  ok(await evl(B, "document.querySelectorAll('#wardGrid .fig i').length >= 8"), "…and draws the figure in them");
  await shot(B, "wardrobe");

  // 2. the visitor is sent the look and draws it
  // the hub sends positions every few seconds; under load (the pre-push runs tests side by side) the first one carrying
  // the new look can take a while — wait for it, never a fixed sleep
  const lookSeen = () => { const l = (frames.get(A) || []).filter((f) => /"t": ?"players"/.test(f)).map((f) => JSON.parse(f)).flatMap((m) => m.list).map((o) => o.look).filter(Boolean); return l[l.length - 1] || {}; };
  for (let t = 0; t < 20000 && !(lookSeen().worn && lookSeen().worn.back && lookSeen().skin === 3); t += 250) await sleep(250);
  const last = lookSeen();
  ok(last.worn && last.worn.body === "linen_shirt" && last.worn.legs === "linen_trousers" && last.worn.head === "linen_cap" && last.worn.back === "linen_cloak" && last.skin === 3,
     "the visitor is sent the owner's look: " + JSON.stringify(last));
  await shot(A, "visitor");

  // 3. off again, back into the bag
  await evl(B, "document.querySelector('#wardGrid [data-off=\"back\"]').click(), true");
  ok(await until(B, "!!document.querySelector('#wardGrid [data-wear=\"linen_cloak\"]')", 8000), "taking the cloak off puts it back in the bag");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
