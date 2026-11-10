/*
 * test_a_deer_is_hunted_with_a_spear_and_a_bow_in_the_page.mjs — HUNTING (#156: "we will need all the civilisation
 * essentials like berries, hunting, crops…", operator 2026-11-09), walked in the real page against the real world server
 * (tests/_land_live_fixture.py) as a player on a phone, with taps only. The fixture holds the herd still and stands an
 * animal where the walk can see it:
 *   1. a deer two and a half metres ahead is drawn; Break on it with no weapon says hunting needs a spear or a bow (the flax and flowers
 *      between take no strike: game is struck through them);
 *   2. with a spear (and a knife): Break strikes it ("a hit — it turns on you"), and again until it falls — its meat, hide
 *      and bone are in the bag;
 *   3. a boar fifteen metres off: a spear does not reach it; with a bow and arrows Break looses an arrow along the look
 *      (BALLISTICS #157: it flies and falls — at fifteen metres the drop is small) and it strikes the boar, spending an
 *      arrow;
 *   4. no page errors.
 *
 * Run:  node tests/test_a_deer_is_hunted_with_a_spear_and_a_bow_in_the_page.mjs   (needs chrome, python3)
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
  const { token } = await getJ("/fixture/owner_token");
  // an open meadow run northwards on the plot: the player at its south end, open air 16 m ahead
  let F = null;
  for (let du = 2; du < 14 && !F; du++) {
    const u = q.u0 + du, v = q.v0 + 0, c0 = Wd.column(q.face, u, v).top;
    let flat = true;
    for (let dv = 0; dv <= 18 && flat; dv++) { const c = Wd.column(q.face, u, v + dv); flat = Math.abs(c.top - c0) <= 1 && !Wd.BLOCKS[Wd.terrainBlock(q.face, u, v + dv, c.top + 1)].solid
      && !Wd.BLOCKS[Wd.terrainBlock(q.face, u, v + dv, c.top + 2)].solid && Wd.terrainBlock(q.face, u, v + dv, c.top + 1) !== Wd.B.berrybush && !Wd.isTree(Wd.terrainBlock(q.face, u, v + dv, c.top + 3)); }
    if (flat) F = { u, v, top: c0 };
  }
  ok(!!F, "an open run of meadow to hunt across");
  const B = await tab();
  await send(B, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const alert = () => evl(B, "(document.getElementById('alertBar') || {}).textContent || ''");
  const bag = () => evl(B, "document.getElementById('tPal').click(), new Promise((r) => setTimeout(() => { const t = document.getElementById('palGrid').textContent; document.getElementById('palClose').click(); r(t); }, 700))");
  const count = (t, name) => Number((t.match(new RegExp("(\\d+) × " + name)) || [0, 0])[1]);
  // every notice the page shows, as it shows it: a notice fades after 4.5 s, and on a headless page drawing under a frame
  // a second the polls between can miss one entirely (the knife-and-arrows walk, 2026-11-10)
  const watchNotices = () => evl(B, `(() => { if (window.__notices) return true; window.__notices = [];
    new MutationObserver(() => { const e = document.getElementById('alertBar'); if (e && e.textContent) window.__notices.push(e.textContent); })
      .observe(document.body, { childList: true, subtree: true, characterData: true }); return true; })()`);
  const strike = async (want) => {
    await watchNotices();
    const n0 = await evl(B, "window.__notices.length");
    await evl(B, "document.getElementById('tBreak').click(), true");
    await until(B, `window.__notices.slice(${n0}).some((t) => ${JSON.stringify(want)}.some((w) => t.includes(w)))`, 30000);
    const t = await evl(B, `window.__notices.slice(${n0}).find((t) => ${JSON.stringify(want)}.some((w) => t.includes(w))) || ""`);
    await sleep(1100);                                              // (a strike costs work: the next waits its turn)
    return t;
  };
  const deer = await getJ(`/fixture/animal?kind=deer&u=${F.u + 0.5}&v=${F.v + 3}`);
  const hEye = Wd.column(q.face, F.u, F.v).height + 1.62, hDeer = Wd.column(q.face, F.u, F.v + 3).height + 0.95;
  await stand(B, F.u + 0.5, F.v + 0.5, F.top + 1, 0, -Math.atan2(hEye - hDeer, 2.5));
  await sleep(2500);                                                 // the animals near come with the players' positions

  // 1. no weapon
  let said = "";
  for (let i = 0; i < 4 && !/spear or a bow/.test(said); i++) said = await strike(["spear or a bow", "Sign in"]);   // (until the deer has come into view)
  ok(/Hunting needs a spear or a bow/.test(said), "Break on a deer with no weapon says hunting needs a spear or a bow: " + said);

  // 2. a spear
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({})) + "&tools=" + encodeURIComponent(JSON.stringify(["spear", "knife"])));   // (hide and bone need a knife, #157)
  await sleep(800);
  said = await strike(["A hit", "You hunted", "Too far"]);
  ok(/A hit — the deer turns on you!/.test(said), "with a spear, Break strikes the deer — and it turns on the hunter (#162): " + said);
  said = await strike(["A hit", "You hunted", "Too far"]);
  ok(/You hunted a deer/.test(said), "…and again until it falls: " + said);
  const t = await bag(), drops = R.hunting.species.deer.drops;
  ok(count(t, "Raw meat") === drops.find(([i]) => i === "meat")[1] && count(t, "Hide") === 1 && count(t, "Bone") === 1, "its meat, hide and bone are in the bag: " + t.slice(0, 200));
  await shot(B, "hunt");

  // 3. a boar fifteen metres off: too far for the spear; a bow and arrows reach it
  await getJ(`/fixture/animal?kind=boar&u=${F.u + 0.5}&v=${F.v + 15.5}`);
  const hBoar = Wd.column(q.face, F.u, F.v + 15).height + 0.6;
  await stand(B, F.u + 0.5, F.v + 0.5, F.top + 1, 0, -Math.atan2(hEye - hBoar, 15));
  said = await strike(["Too far", "A hit", "You hunted"]);
  ok(/Too far/.test(said), "a spear does not reach a boar 15 m off: " + said);
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ arrow: 3 })) + "&tools=" + encodeURIComponent(JSON.stringify(["spear", "bow"])));
  await sleep(800);
  said = await strike(["A hit", "You hunted", "Too far", "No arrows", "A miss"]);
  ok(/A hit — the boar turns on you!/.test(said), "with a bow, Break looses an arrow that flies to the boar 15 m off and strikes it: " + said);
  let arrows = -1;
  for (let i = 0; i < 10 && arrows !== 2; i++) { arrows = count(await bag(), "Arrow"); if (arrows !== 2) await sleep(1500); }
  ok(arrows === 2, "…and spends an arrow (" + arrows + " left of 3)");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
