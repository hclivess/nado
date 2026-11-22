/*
 * test_a_phone_shows_few_buttons_and_more_opens_the_rest.mjs — operator 2026-11-22, a phone's screenshot: "too many
 * buttons" — thirteen round buttons over half the view, most of which a signed-out player could only be told "sign in"
 * by, and Down, which on the ground did nothing. land.html "FEWER BUTTONS": Down only while flying, the gathering and
 * building buttons only once signed in (body.guest), the left cluster folded behind More (body.more). land.js keeps
 * body.flying / body.guest in step every frame. Walked in the real page as a signed-out phone, with real taps (a CSS
 * rule that hides a button the code still needs, or a More that lights but opens nothing, would pass a source check):
 *   1. on load the round buttons a player sees are Jump, Fly and More — 3, where there were 13;
 *   2. a tap on More opens Chat and Run (5) and lights More; the gathering and building buttons stay hidden for a guest;
 *      a second tap folds them again (3);
 *   3. a tap on Fly shows Down (Fly lit); a second tap walks again and Down goes;
 *   4. no page error.
 * And from the page's own rules (the walk is signed out): a signed-in phone on the ground shows Jump, Fly, Break, Place,
 * Use, Bag and More — 7 — none of the right cluster behind a guest-only or a More-only rule.
 * Run: node tests/test_a_phone_shows_few_buttons_and_more_opens_the_rest.mjs   (needs chrome, python3)
 */
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PROTOCOL_JS } from "./protocol_hook.mjs";
import { sweepStaleProfiles } from "./_cdp_profiles.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const LABEL = { tJump: "Jump", tDown: "Down", tFly: "Fly", tBreak: "Break", tPlace: "Place", tPal: "Bag", tUse: "Use", tMore: "More",
  tChat: "Chat", tRun: "Run", tTurn: "Turn", tFire: "Fire", tWard: "Wear", tLevel: "Flatten" };
const names = (ids) => ids.map((i) => LABEL[i] || i).join(", ");
const same = (a, b) => a.length === b.length && [...a].sort().join() === [...b].sort().join();

// ---- from the page's rules: what a SIGNED-IN phone shows on the ground (the walk below can only be a guest) --------
// Every rule that hides a phone button is read as body(.class|:not(.class))* #tX and evaluated for a state; a hiding
// rule of any other shape naming a button fails, so a new kind of rule cannot slip past this model unread.
const html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
const css = (html.match(/<style>([\s\S]*?)<\/style>/) || [, ""])[1].replace(/\/\*[\s\S]*?\*\//g, "");
const ui = (html.match(/<div id="touchUi">([\s\S]*?)<\/div>/) || [, ""])[1];
const BUTTONS = [...ui.matchAll(/<button id="(t\w+)"/g)].map((m) => m[1]);
const hiders = [], odd = [];
for (const [, sels, body] of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
  if (!/display:\s*none/.test(body)) continue;
  for (const s of sels.split(",").map((x) => x.trim())) {
    if (!/#t[A-Z]\w*\b/.test(s) || !BUTTONS.some((b) => new RegExp("#" + b + "\\b").test(s))) continue;
    const m = s.match(/^body((?:\.[\w-]+|:not\(\.[\w-]+\))*)\s+#(t\w+)$/);
    if (!m) { odd.push(s); continue; }
    hiders.push({ id: m[2], need: [...m[1].matchAll(/\.([\w-]+)/g)].map((x) => x[1]), not: [...m[1].matchAll(/:not\(\.([\w-]+)\)/g)].map((x) => x[1]) });
  }
}
const shownFor = (cls) => BUTTONS.filter((b) => !hiders.some((h) => h.id === b
  && h.need.filter((c) => !h.not.includes(c)).every((c) => cls.has(c)) && h.not.every((c) => !cls.has(c))));
ok(odd.length === 0, "every rule that hides a phone button has the body-classes form this test reads" + (odd.length ? ": " + odd.join(" | ") : ""));
const signedIn = shownFor(new Set(["touch"]));
ok(same(signedIn, ["tJump", "tFly", "tBreak", "tPlace", "tUse", "tPal", "tMore"]),
  `signed in, on the ground, a phone shows 7 — the right cluster and More: ${names(signedIn)}`);
const guestRules = shownFor(new Set(["touch", "guest"]));
ok(same(guestRules, ["tJump", "tFly", "tMore"]), `(the same rules for a guest: ${names(guestRules)} — what the walk measures)`);

// ---- the fixture: page + world server + fake exec on one origin (tests/_land_live_fixture.py assigns its own HOME) ----
const work = mkdtempSync(join(tmpdir(), "nado-land-live-"));
writeFileSync(join(work, "protocol.js"), PROTOCOL_JS);
// TMPDIR and HOME: everything the fixture makes lands in work, which cleanup removes (CLAUDE.md rule 4)
const fx = spawn("python3", [join(ROOT, "tests", "_land_live_fixture.py"), join(work, "protocol.js")], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, TMPDIR: work, HOME: work } });
let fxOut = "";
fx.stdout.on("data", (d) => { fxOut += d; });
fx.stderr.on("data", (d) => { fxOut += d; });
let HTTP = 0;
for (let i = 0; i < 240 && !HTTP; i++) { const m = fxOut.match(/PORT (\d+)/); if (m) HTTP = Number(m[1]); else await sleep(250); }
if (!HTTP) { console.log("FAIL the fixture did not start:\n" + fxOut.slice(-2000)); fx.kill("SIGKILL"); process.exit(1); }
const base = `http://127.0.0.1:${HTTP}`;
const getJ = async (p) => (await fetch(base + p)).json();

const { plot: PA } = await getJ("/fixture/plot"), q = Wd.plotCoords(PA);
const FACE = q.face, U = q.u0 + 8.5, V = q.v0 + 8.5, TOP = Wd.column(FACE, Math.floor(U), Math.floor(V)).top + 1;
const W = 412, HH = 915;

// ---- the browser -----------------------------------------------------------------------------------------------
const PORT = 9300 + ((process.pid + 433) % 600);
sweepStaleProfiles();                                     // what a killed run left (tests/_cdp_profiles.mjs)
const prof = mkdtempSync(join(tmpdir(), "cdp-landfew-"));
let chrome = null, ver = null;
const tried = [];
for (const bin of [process.env.CHROME, "google-chrome", "google-chrome-stable", "chromium-browser", "chromium"].filter(Boolean)) {
  const c = spawn(bin, ["--headless", "--disable-gpu", "--no-sandbox", "--use-angle=swiftshader", "--remote-debugging-port=" + PORT,
    "--user-data-dir=" + prof, `--window-size=${W},${HH}`, "about:blank"], { stdio: "ignore", detached: true });   // its own group: the helpers die with it
  let gone = false;
  c.on("error", () => { gone = true; }); c.on("exit", () => { gone = true; });
  for (let i = 0; i < 60 && !ver && !gone; i++) { try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch (e) { await sleep(250); } }
  if (ver) { chrome = c; break; }
  tried.push(bin + (gone ? " (exited)" : " (no CDP in 15 s)"));
  try { process.kill(-c.pid, "SIGKILL"); } catch (e) {}
  await sleep(300);
}
function cleanup() { try { chrome && process.kill(-chrome.pid, "SIGKILL"); } catch (e) {} try { fx.kill("SIGKILL"); } catch (e) {} for (const d of [prof, work]) try { rmSync(d, { recursive: true, force: true }); } catch (e) {} }
if (!chrome) { cleanup(); console.log(`SKIP  no browser served CDP (tried ${tried.join(", ") || "none"})`); process.exit(0); }

const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0; const pend = new Map(), errors = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
  if (m.method === "Runtime.exceptionThrown") errors.push(JSON.stringify(m.params.exceptionDetails).slice(0, 300));
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push("console: " + m.params.args.map((a) => a.value || a.description).join(" ").slice(0, 400));
});
const send = (sid, method, params) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params, sessionId: sid })); });
const evl = async (sid, expr) => {
  const r = await send(sid, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result.result.value;
};
const until = async (sid, expr, ms = 20000) => { for (let t = 0; t < ms; t += 250) { if (await evl(sid, expr).catch(() => false)) return true; await sleep(250); } return false; };

// what a player sees: a button laid out and not display:none (#touchUi buttons are position:fixed, so offsetParent is
// null for them even when drawn — the box and the computed display are the measure)
const VISIBLE = "[...document.querySelectorAll('#touchUi button')].filter((b) => { const s = getComputedStyle(b), r = b.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0; }).map((b) => b.id)";
const seen = (sid) => evl(sid, VISIBLE);
const lit = (sid, bid) => evl(sid, `document.getElementById('${bid}').classList.contains('on')`);
// a tap as a finger makes it: a touch at the button's centre, down and up — the browser's own click follows, which is
// what the page listens to (.click() would reach a button a finger could not, under another element or off screen)
async function tap(sid, bid) {
  const c = await evl(sid, `(() => { const r = document.getElementById('${bid}').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()`);
  await send(sid, "Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: c[0], y: c[1], id: 1 }] });
  await sleep(60);
  await send(sid, "Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await sleep(700);                                       // a few frames: body.flying follows P.fly in the frame
}

try {
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const S = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  for (const d of ["Runtime", "Page"]) await send(S, d + ".enable", {});
  await send(S, "Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await send(S, "Emulation.setDeviceMetricsOverride", { width: W, height: HH, deviceScaleFactor: 1, mobile: true });
  // the place is written from a page of the same origin that runs no game (the booting game could save over it)
  await send(S, "Page.navigate", { url: base + "/static/land-world.js" });
  await until(S, "document.readyState === 'complete'");
  await evl(S, `localStorage.setItem("nado_land_v1", JSON.stringify({ p: [${FACE}, ${U}, ${V}, ${TOP}, 0, -0.1], at: 9e12 })); true`);
  await send(S, "Page.navigate", { url: base + "/" });
  ok(await until(S, "document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden') && document.body.classList.contains('touch')", 90000),
    `the page loads as a phone (${W} × ${HH}, touch)`);
  ok(await until(S, "document.body.classList.contains('guest')", 20000), "…signed out: the page marks the player a guest");
  await evl(S, "document.getElementById('help') && document.getElementById('help').classList.add('hidden'), true");
  await sleep(1500);

  const v0 = await seen(S);
  ok(same(v0, ["tJump", "tFly", "tMore"]), `on load a guest sees 3 round buttons, where there were 13: ${names(v0)}`);

  await tap(S, "tMore");
  const v1 = await seen(S);
  ok(same(v1, ["tJump", "tFly", "tMore", "tChat", "tRun"]), `a tap on More opens Chat and Run (5): ${names(v1)}`);
  ok(await lit(S, "tMore"), "…and More is lit while open");
  const leaked = v1.filter((b) => ["tBreak", "tPlace", "tPal", "tUse", "tTurn", "tFire", "tWard", "tLevel"].includes(b));
  ok(leaked.length === 0, "…the gathering and building buttons stay hidden for a guest" + (leaked.length ? ": " + names(leaked) : ""));
  await tap(S, "tMore");
  const v2 = await seen(S);
  ok(same(v2, ["tJump", "tFly", "tMore"]) && !(await lit(S, "tMore")), `a second tap folds them again, More unlit: ${names(v2)}`);

  await tap(S, "tFly");
  const v3 = await seen(S), fl = await evl(S, "document.body.classList.contains('flying')");
  ok(fl && v3.includes("tDown") && (await lit(S, "tFly")), `a tap on Fly flies, shows Down and lights Fly: ${names(v3)}`);
  await tap(S, "tFly");
  const v4 = await seen(S);
  ok(!v4.includes("tDown") && !(await lit(S, "tFly")) && same(v4, ["tJump", "tFly", "tMore"]), `a second tap walks again and Down goes: ${names(v4)}`);

  ok(errors.length === 0, "no page error" + (errors.length ? ": " + errors.slice(0, 4).join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
