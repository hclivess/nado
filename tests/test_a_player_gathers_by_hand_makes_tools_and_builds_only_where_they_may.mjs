/*
 * test_a_player_gathers_by_hand_makes_tools_and_builds_only_where_they_may.mjs — the Land page walked as a signed-in
 * player on a touch screen, against the REAL world server (tests/_land_live_fixture.py: the page, scripts/land_server.py
 * with its terrain oracle, and a fake exec node: the player holds plot PA, someone else holds PB, the rest is wilderness):
 *   1. on their own plot, Break by hand takes the ground they look at — the bag gains earth (and the hotbar offers it);
 *   2. Place puts that earth back from the hotbar and the count drops;
 *   3. in the bag, fiber twists into cordage and sticks + stone + cordage make a stone axe — the bag shows the tool;
 *   3b. with planks, a chosen piece size (a 100 x 10 x 100 cm wall panel from the bag's presets) is placed on their plot:
 *       the server holds exactly that piece and charged exactly its volume (0.1 of a block); taking it down refunds it;
 *   4. on unowned land they gather and build too ("you can build anywhere unless it is owned");
 *   5. on someone else's plot nothing they tap changes anything, and the page says why.
 * Every check reads what the player sees (HUD, hotbar, bag) or what the server holds (its inventory over the API).
 *
 * Run:  node tests/test_a_player_gathers_by_hand_makes_tools_and_builds_only_where_they_may.mjs   (needs chromium, python3, node)
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

const work = mkdtempSync(join(tmpdir(), "nado-land-gather-"));
writeFileSync(join(work, "protocol.js"), PROTOCOL_JS);
// TMPDIR: everything the fixture makes (its HOME, the world server's) lands in work, which cleanup removes — it is killed,
// so its own exit handlers never run (640 such directories were left in /tmp by 2026-11-08)
const fx = spawn("python3", [join(ROOT, "tests", "_land_live_fixture.py"), join(work, "protocol.js")], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, TMPDIR: work } });
let fxOut = "";
fx.stdout.on("data", (d) => { fxOut += d; }); fx.stderr.on("data", (d) => { fxOut += d; });
let HTTP = 0;
for (let i = 0; i < 240 && !HTTP; i++) { const m = fxOut.match(/PORT (\d+)/); if (m) HTTP = Number(m[1]); else await sleep(250); }
if (!HTTP) { console.log("FAIL the fixture did not start:\n" + fxOut.slice(-2000)); fx.kill("SIGKILL"); process.exit(1); }
const base = `http://127.0.0.1:${HTTP}`;
const getJ = async (p) => (await fetch(base + p)).json();
const { plot: PA, other_plot: PB } = await getJ("/fixture/plot");

// a flat standing spot in a plot, looking at grass one step ahead
function spot(plot) {
  const q = Wd.plotCoords(plot);
  for (let d = 0; d < 10; d++) {
    const u = q.u0 + 5 + d, v = q.v0 + 4, c0 = Wd.column(q.face, u, v), c1 = Wd.column(q.face, u, v + 1);
    if (Wd.terrainBlock(q.face, u, v, c0.top + 1) === Wd.B.air && Wd.terrainBlock(q.face, u, v, c0.top + 2) === Wd.B.air
        && c1.top === c0.top && Wd.terrainBlock(q.face, u, v + 1, c1.top + 1) === Wd.B.air && Wd.terrainBlock(q.face, u, v + 1, c1.top + 2) === Wd.B.air)
      return { face: q.face, u: u + 0.5, v: v + 0.5, h: c0.height + 0.05 };
  }
  throw new Error("no flat spot in plot " + plot);
}
const WILD = Wd.plotId(0, Wd.plotCoords(PA).prow + 6, Wd.plotCoords(PA).pcol);   // untitled: wilderness

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 523) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landgather-"));
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
let id = 0; const pend = new Map(), errors = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
  if (m.method === "Runtime.exceptionThrown") errors.push(JSON.stringify(m.params.exceptionDetails).slice(0, 300));
});
const send = (sid, method, params) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params, sessionId: sid })); });
const evl = async (sid, expr) => {
  const r = await send(sid, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result.result.value;
};
const until = async (sid, expr, ms = 20000) => { for (let t = 0; t < ms; t += 250) { if (await evl(sid, expr).catch(() => false)) return true; await sleep(250); } return false; };
const tap = (sid, b) => evl(sid, `document.getElementById("${b}").click(), true`);
const bodyHas = (sid, re) => evl(sid, `${re}.test(document.body.textContent)`);

try {
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const S = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  for (const d of ["Runtime", "Page", "Network"]) await send(S, d + ".enable", {});
  await send(S, "Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await send(S, "Emulation.setDeviceMetricsOverride", { width: 900, height: 700, deviceScaleFactor: 1, mobile: true });
  const { token } = await getJ("/fixture/owner_token");
  const { owner } = await getJ("/fixture/plot");
  await send(S, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  const standAt = async (s) => {
    await send(S, "Page.navigate", { url: base + "/" });
    await until(S, "document.readyState === 'complete'");
    await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${s.face}, ${s.u}, ${s.v}, ${s.h}, 0, -1.0] })); true`);
    await send(S, "Page.reload", {});
    await until(S, "document.getElementById('loading').classList.contains('hidden')", 30000);
  };
  const serverInv = async () => (await (await fetch(base + "/land/api/inventory", { headers: { Authorization: "Bearer " + token } })).json()).items || {};

  // 1. gather by hand on their own plot
  await standAt(spot(PA));
  ok(await until(S, "/Your plot/.test(document.getElementById('hudPlot').textContent) && /Empty hands/.test(document.getElementById('hotbar').textContent)"),
     "signed in on their plot, with empty hands");
  await tap(S, "tBreak");
  ok(await until(S, "/Earth/.test(document.getElementById('hotName').textContent)", 8000), "Break by hand gathers the ground: the hotbar now offers earth");
  const inv1 = await serverInv();
  ok(inv1.dirt === 1, "…and the world server holds it in their inventory: " + JSON.stringify(inv1));

  // 2. place it back
  await tap(S, "tPlace");
  ok(await until(S, "document.querySelector('#hotbar .hs b') && document.querySelector('#hotbar .hs b').textContent === '0'", 8000),
     "Place puts the earth down from the hotbar and the count drops to 0");
  ok((await serverInv()).dirt === undefined, "…the server agrees: no earth left");

  // 3. make things in the bag
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ fiber: 3, sticks: 2, stone: 1 })));
  await tap(S, "tPal");
  ok(await until(S, "!!document.querySelector('[data-make=\"cordage\"]:not([disabled])')"), "the bag offers cordage once there is fiber");
  await evl(S, "document.querySelector('[data-make=\"cordage\"]').click(), true");
  ok(await until(S, "!!document.querySelector('[data-make=\"axe\"]:not([disabled])')"), "…and then the stone axe");
  await evl(S, "document.querySelector('[data-make=\"axe\"]').click(), true");
  ok(await until(S, "[...document.querySelectorAll('.chip.tool')].some((c) => /Stone axe/.test(c.textContent))"), "the bag shows the stone axe it made");
  // 3b. a piece of a chosen size
  await getJ("/fixture/seed?who=owner&items=" + encodeURIComponent(JSON.stringify({ planks: 2 })));
  ok(await until(S, "!!document.querySelector('[data-preset=\"2\"]')"), "the bag offers piece sizes");
  await evl(S, "document.querySelector('[data-preset=\"2\"]').click(), true");
  await evl(S, "document.getElementById('palClose').click(), true");
  ok(await until(S, "[...document.querySelectorAll('#hotbar .hs')].some((h) => h.title === 'Planks')"), "planks are on the hotbar");
  await evl(S, "[...document.querySelectorAll('#hotbar .hs')].find((h) => h.title === 'Planks').click(), true");
  ok(await until(S, "/Piece 100 × 10 × 100 cm/.test(document.getElementById('pieceInfo').textContent)"), "the chosen size shows under the hotbar: " + await evl(S, "document.getElementById('pieceInfo').textContent"));
  await tap(S, "tPlace");
  const plotNow = async () => (await (await fetch(base + "/land/api/plot?plot=" + PA, { headers: { Authorization: "Bearer " + token } })).json());
  let pj = null;
  for (let i = 0; i < 40; i++) { pj = await plotNow(); if ((pj.boxes || []).length) break; await sleep(250); }
  const box = (pj.boxes || [])[0];
  ok(box && box[3] === 100 && box[4] === 10 && box[5] === 100 && box[6] === Wd.B.planks, "Place puts exactly that piece on the plot: " + JSON.stringify(pj.boxes));
  const invP = await (await fetch(base + "/land/api/inventory", { headers: { Authorization: "Bearer " + token } })).json();
  ok(invP.items.planks === 1 && invP.vol.planks === 900000, "…charging exactly its volume, a tenth of a block: " + JSON.stringify(invP));
  await tap(S, "tBreak");
  for (let i = 0; i < 40; i++) { pj = await plotNow(); if (!(pj.boxes || []).length) break; await sleep(250); }
  const invQ = await (await fetch(base + "/land/api/inventory", { headers: { Authorization: "Bearer " + token } })).json();
  ok(!(pj.boxes || []).length && invQ.items.planks === 2 && !(invQ.vol || {}).planks, "taking it down removes it and refunds its volume: " + JSON.stringify(invQ));

  // 4. the wilderness
  await standAt(spot(WILD));
  ok(await until(S, "/Wilderness/.test(document.getElementById('hudPlot').textContent)"), "in the wilderness");
  await tap(S, "tBreak");
  // the earth slot, whichever slot is selected (planks were chosen for the piece above)
  ok(await until(S, "[...document.querySelectorAll('#hotbar .hs')].some((h) => h.title === 'Earth' && h.querySelector('b').textContent === '1')", 8000),
     "they gather there too");
  await evl(S, "[...document.querySelectorAll('#hotbar .hs')].find((h) => h.title === 'Earth').click(), true");
  await tap(S, "tPlace");
  ok(await until(S, "[...document.querySelectorAll('#hotbar .hs')].some((h) => h.title === 'Earth' && h.querySelector('b').textContent === '0')", 8000)
     && (await serverInv()).dirt === undefined, "and build there: unowned land is open to everyone signed in");

  // 5. someone else's plot
  await standAt(spot(PB));
  ok(await until(S, "/Owned by/.test(document.getElementById('hudPlot').textContent)"), "on someone else's plot");
  await tap(S, "tBreak");
  await sleep(1500);
  await tap(S, "tPlace");
  await sleep(800);
  ok((await serverInv()).dirt === undefined && await bodyHas(S, "/belongs to someone else|not your plot/"), "nothing they tap changes anything there, and the page says why");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  void owner;
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
