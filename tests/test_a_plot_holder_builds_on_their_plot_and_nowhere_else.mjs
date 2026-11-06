/*
 * test_a_plot_holder_builds_on_their_plot_and_nowhere_else.mjs — the Land page walked as a player, on a touch screen:
 * signed in, standing on a plot whose title the wallet holds, Place puts the selected block where they look and keeps it,
 * Break takes it back out (the plot is unchanged again), Break once more digs the ground; standing on a plot someone else
 * holds, the same buttons change nothing and the page says why.
 *
 * Drives the REAL static/land.html + land.js + land-world.js + land-mesher.js in headless Chromium over CDP, served from
 * this checkout by a throwaway server that answers the exec node's title reads with a fixture (two titled plots of the
 * first wave: one held by the signed-in address, one by someone else). Nothing here talks to a node or a wallet.
 * "Kept" is read where the page keeps a plot's edits between visits (localStorage nado_land_v1, the same record the
 * anchor commits); the HUD's plot line is read as the player sees it.
 *
 * Run:  node tests/test_a_plot_holder_builds_on_their_plot_and_nowhere_else.mjs        (needs chromium)
 */
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { PROTOCOL_JS } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const STATIC = join(ROOT, "static");
const Wd = await import(join(STATIC, "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

const landJs = readFileSync(join(STATIC, "land.js"), "utf8");
const ISSUER = landJs.match(/^const ISSUER = "([0-9a-z]+)";/m)[1];
const ME = "3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f";            // any valid address: the page only DISPLAYS as it
const OTHER = "6c29de76c487be78f3af402f892fe80c0eb7d9a9d92093f1ac";
const wave = Wd.firstWave(), MINE = wave[44], THEIRS = wave[46];
const seedOf = (p) => ((0x4c414e44n << 32n) | BigInt(p)).toString();
const title = (p) => ({ id: String(900000 + p), issuer: ISSUER, seed: seedOf(p), dec: 0, supply: "1", name: "Plot", sym: "LAND", holders: 1 });

// a standing spot in a plot: its centre column, on the ground, with air above (no tree trunk there)
function spot(plot) {
  const q = Wd.plotCoords(plot);
  for (let d = 0; d < 6; d++) for (const [du, dv] of [[d, 0], [0, d], [-d, 0], [0, -d]]) {
    const u = q.u0 + 7 + du, v = q.v0 + 6 + dv, top = Wd.column(q.face, u, v).top;
    if (Wd.terrainBlock(q.face, u, v, top + 1) === Wd.B.air && Wd.terrainBlock(q.face, u, v + 1, top + 1) === Wd.B.air
        && Wd.column(q.face, u, v + 1).top === top && Wd.terrainBlock(q.face, u, v + 1, top + 2) === Wd.B.air)
      return { face: q.face, u: u + 0.5, v: v + 0.5, h: top + 1, top, cu: u, cv: v + 1 };
  }
  throw new Error("no flat standing spot in plot " + plot);
}
const S1 = spot(MINE), S2 = spot(THEIRS);

const json = (res, v) => { res.setHeader("content-type", "application/json"); res.end(JSON.stringify(v)); };
const srv = createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/") { res.setHeader("content-type", "text/html"); return res.end(readFileSync(join(STATIC, "land.html"))); }
  if (u.pathname === "/protocol.js") { res.setHeader("content-type", "text/javascript"); return res.end(PROTOCOL_JS); }
  if (u.pathname === "/exec/assets" && u.searchParams.get("issuer") === ISSUER) return json(res, { assets: [title(MINE), title(THEIRS)], cursor: 1000 });
  if (u.pathname === "/exec/assets" && u.searchParams.get("holder") === ME) return json(res, { assets: [title(MINE)], cursor: 1000 });
  if (u.pathname === "/exec/asset" && u.searchParams.get("id") === String(900000 + THEIRS)) return json(res, { asset: title(THEIRS), holders: { [OTHER]: "1" }, cursor: 1000 });   // the live shape
  if (u.pathname.startsWith("/static/")) {
    const p = normalize(join(ROOT, u.pathname));
    if (!p.startsWith(STATIC + "/")) { res.statusCode = 404; return res.end(); }
    try {
      const b = readFileSync(p);
      res.setHeader("content-type", p.endsWith(".js") ? "text/javascript" : p.endsWith(".wasm") ? "application/wasm" : "application/octet-stream");
      return res.end(b);
    } catch (e) { res.statusCode = 404; return res.end(); }
  }
  return json(res, {});
});
await new Promise((r) => srv.listen(0, "127.0.0.1", r));
const HTTP = srv.address().port;

// THE BROWSER (tests/test_a_file_drop_replaces_the_os_file_picker.mjs has the history): the first that serves CDP, else SKIP
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9300 + ((process.pid + 377) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-landbuild-"));
let chrome = null, ver = null;
const tried = [];
for (const bin of [process.env.CHROME, "chromium-browser", "chromium", "google-chrome", "google-chrome-stable"].filter(Boolean)) {
  const c = spawn(bin, ["--headless", "--disable-gpu", "--no-sandbox", "--use-angle=swiftshader", "--remote-debugging-port=" + PORT,
    "--user-data-dir=" + prof, "about:blank"], { stdio: "ignore" });
  let gone = false;
  c.on("error", () => { gone = true; });
  c.on("exit", () => { gone = true; });
  for (let i = 0; i < 60 && !ver && !gone; i++) {
    try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch (e) { await sleep(250); }
  }
  if (ver) { chrome = c; break; }
  tried.push(bin + (gone ? " (exited)" : " (no CDP in 15 s)"));
  try { c.kill("SIGKILL"); } catch (e) {}
  await sleep(300);
}
if (!chrome) {
  try { srv.close(); rmSync(prof, { recursive: true, force: true }); } catch (e) {}
  console.log(`SKIP  no browser served CDP (tried ${tried.join(", ") || "none"}): the build walk needs one`);
  process.exit(0);
}
let ws, id = 0; const pend = new Map(); let sid; const errors = [];
const send = (m, p) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p, sessionId: sid })); });
async function evl(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result.result.value;
}
async function until(expr, ms = 20000) {
  for (let t = 0; t < ms; t += 250) { if (await evl(expr).catch(() => false)) return true; await sleep(250); }
  return false;
}
function cleanup() { try { chrome.kill("SIGKILL"); } catch (e) {} try { srv.close(); } catch (e) {} try { rmSync(prof, { recursive: true, force: true }); } catch (e) {} }

const saved = `(() => { try { return JSON.parse(localStorage.getItem("nado_land_v1") || "{}"); } catch (e) { return {}; } })()`;
const editsOf = (plot) => `((${saved}).plots || {})[${plot}] ? (${saved}).plots[${plot}].e : []`;
const tap = (btn) => evl(`(() => { document.getElementById("${btn}").click(); return true; })()`);
async function standAt(s) {
  await evl(`(() => { const d = ${saved}; d.p = [${s.face}, ${s.u}, ${s.v}, ${s.h}, 0, -1.0]; localStorage.setItem("nado_land_v1", JSON.stringify(d));
    localStorage.setItem("nado_land_me_v2", ${JSON.stringify(ME)}); return true; })()`);
  await send("Page.reload", {});
  await until("document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')", 30000);
}

try {
  ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
    if (m.method === "Runtime.exceptionThrown") errors.push(JSON.stringify(m.params.exceptionDetails).slice(0, 300));
  });
  const t = await send("Target.createTarget", { url: "about:blank" });
  sid = (await send("Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  await send("Runtime.enable", {}); await send("Page.enable", {});
  await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await send("Emulation.setDeviceMetricsOverride", { width: 900, height: 600, deviceScaleFactor: 1, mobile: true });
  await send("Page.navigate", { url: `http://127.0.0.1:${HTTP}/` });
  await until("document.readyState === 'complete'");

  // ---- on the plot the wallet holds -------------------------------------------------------------------------------
  await standAt(S1);
  ok(await evl("document.body.classList.contains('touch') && getComputedStyle(document.getElementById('tPlace')).display !== 'none' && document.getElementById('tPlace').getBoundingClientRect().width > 0"),
     "on a touch screen the page shows the Place / Break buttons");
  ok(await until("/Your plot/.test(document.getElementById('hudPlot').textContent)"),
     "standing on a plot the wallet holds, the HUD says it is theirs: " + await evl("document.getElementById('hudPlot').textContent"));
  ok((await evl(editsOf(MINE))).length === 0, "the plot starts untouched");
  await tap("tPlace"); await sleep(300);
  const e1 = await evl(editsOf(MINE));
  ok(e1.length === 1 && e1[0][1] === Wd.B.grass, "Place puts the selected block (grass) on the plot and keeps it: " + JSON.stringify(e1));
  const [lu, lv, lh] = (e1[0] && e1[0][0] || "0:0:0").split(":").map(Number), q = Wd.plotCoords(MINE);
  ok(q.u0 + lu === S1.cu && q.v0 + lv === S1.cv && lh === S1.top + 1, `…exactly where the player looks: on the ground one step ahead (${lu}:${lv}:${lh})`);
  await tap("tBreak"); await sleep(300);
  ok((await evl(editsOf(MINE))).length === 0, "Break takes the placed block back out: the plot is untouched again");
  await tap("tBreak"); await sleep(300);
  const e3 = await evl(editsOf(MINE));
  ok(e3.length === 1 && e3[0][1] === Wd.B.air && e3[0][0] === `${S1.cu - q.u0}:${S1.cv - q.v0}:${S1.top}`, "Break again digs the ground block itself: " + JSON.stringify(e3));
  ok(/^[A-Za-z0-9+/]+=*$/.test(((await evl(saved)).plots[MINE] || {}).s || ""), "the plot's commitment salt is kept with its edits");

  // ---- on a plot someone else holds --------------------------------------------------------------------------------
  await standAt(S2);
  ok(await until("/Owned by/.test(document.getElementById('hudPlot').textContent)", 15000),
     "standing on someone else's plot, the HUD names its owner: " + await evl("document.getElementById('hudPlot').textContent"));
  await tap("tPlace"); await sleep(300);
  await tap("tBreak"); await sleep(300);
  ok((await evl(editsOf(THEIRS))).length === 0, "Place and Break change nothing on a plot the wallet does not hold");
  ok(await evl(`/belongs to someone else/.test(document.body.textContent)`), "and the page says why");
  ok((await evl(editsOf(MINE))).length === 1, "the player's own plot keeps its edit while they are away");
  ok(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
