/*
 * test_the_welcome_card_shows_once_and_play_resumes_after_chat.mjs — the Land page's welcome card and the way back to
 * play after a chat line, walked in the real page against the real world server (tests/_land_live_fixture.py), with
 * real key, click and touch events only:
 *   1. a computer: a first visit shows the card; Play puts it away and captures the mouse; a chat line (Enter, text,
 *      Enter) neither brings the card back nor leaves the mouse free; no error bar; Enter opens the chat again.
 *      ("the popup keeps popping up", "it says this and then i cant type anything: Pointer lock cannot be acquired
 *      immediately after the user has exited the lock", operator 2026-11-09)
 *   2. a phone: a first visit shows the card; a tap on it puts it away; after a reload it stays away
 *      ("on mobile it is permanent").
 *
 * Run:  node tests/test_the_welcome_card_shows_once_and_play_resumes_after_chat.mjs   (needs chrome, python3)
 */
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, rmSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { PROTOCOL_JS } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const work = mkdtempSync(join(tmpdir(), "nado-land-live-"));
writeFileSync(join(work, "protocol.js"), PROTOCOL_JS);
// TMPDIR: everything the fixture makes lands in work, which cleanup removes (it is killed; its exit handlers never run)
const fx = spawn("python3", [join(ROOT, "tests", "_land_live_fixture.py"), join(work, "protocol.js")], { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, TMPDIR: work } });
let fxOut = "";
fx.stdout.on("data", (d) => { fxOut += d; });
fx.stderr.on("data", (d) => { fxOut += d; });
let HTTP = 0;
for (let i = 0; i < 240 && !HTTP; i++) { const m = fxOut.match(/PORT (\d+)/); if (m) HTTP = Number(m[1]); else await sleep(250); }
if (!HTTP) { console.log("FAIL the fixture did not start:\n" + fxOut.slice(-2000)); fx.kill("SIGKILL"); process.exit(1); }
const base = `http://127.0.0.1:${HTTP}`;

const browsers = [];
async function browser() {
  const prof = mkdtempSync(join(work, "cdp-"));
  let c = null;
  for (const bin of [process.env.CHROME, "google-chrome", "google-chrome-stable", "chromium-browser", "chromium"].filter(Boolean)) {
    const p = spawn(bin, ["--headless=new", "--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu-compositing",
      "--remote-debugging-port=0", "--user-data-dir=" + prof, "about:blank"], { stdio: "ignore", detached: true });
    let gone = false; p.on("error", () => { gone = true; }); p.on("exit", () => { gone = true; });
    for (let i = 0; i < 60 && !gone && !existsSync(join(prof, "DevToolsActivePort")); i++) await sleep(250);
    if (!gone && existsSync(join(prof, "DevToolsActivePort"))) { c = p; break; }
    try { process.kill(-p.pid, "SIGKILL"); } catch (e) {}
  }
  if (!c) return null;
  browsers.push(c);
  const port = Number(readFileSync(join(prof, "DevToolsActivePort"), "utf8").split("\n")[0]);
  const ver = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
  const ws = new WebSocket(ver.webSocketDebuggerUrl); await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0; const pend = new Map(), errs = [];
  ws.addEventListener("message", (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } if (m.method === "Runtime.exceptionThrown") errs.push(JSON.stringify(m.params.exceptionDetails).slice(0, 200)); });
  const send = (sid, method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params, sessionId: sid })); });
  const t = await send(undefined, "Target.createTarget", { url: "about:blank" });
  const S = (await send(undefined, "Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  await send(S, "Runtime.enable"); await send(S, "Page.enable");
  const ev = async (x) => (await send(S, "Runtime.evaluate", { expression: x, returnByValue: true, awaitPromise: true })).result.result?.value;
  const loaded = async () => { for (let i = 0; i < 120; i++) { if (await ev("!!document.getElementById('loading') && document.getElementById('loading').classList.contains('hidden')")) return true; await sleep(500); } return false; };
  const key = async (code, k, vk) => { await send(S, "Input.dispatchKeyEvent", { type: "keyDown", code, key: k, windowsVirtualKeyCode: vk }); await send(S, "Input.dispatchKeyEvent", { type: "keyUp", code, key: k, windowsVirtualKeyCode: vk }); };
  return { send, S, ev, loaded, key, errs };
}
function cleanup() { for (const c of browsers) try { process.kill(-c.pid, "SIGKILL"); } catch (e) {} try { fx.kill("SIGKILL"); } catch (e) {} for (const d of [work]) try { rmSync(d, { recursive: true, force: true }); } catch (e) {} }
const cardShown = "!document.getElementById('help').classList.contains('hidden')";

try {
  const { token } = await (await fetch(base + "/fixture/owner_token")).json();
  // 1. a computer
  const b = await browser();
  if (!b) { cleanup(); console.log("SKIP  no browser served CDP"); process.exit(0); }
  await b.send(b.S, "Emulation.setDeviceMetricsOverride", { width: 1024, height: 640, deviceScaleFactor: 1, mobile: false });
  await b.send(b.S, "Network.setCookie", { name: "land_session", value: token, url: base + "/", httpOnly: true });
  await b.send(b.S, "Page.navigate", { url: base + "/" }); await b.loaded(); await sleep(2000);
  ok(await b.ev(cardShown), "computer: a first visit shows the welcome card");
  const p = await b.ev("(() => { const r = document.getElementById('helpPlay').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()");
  for (const type of ["mousePressed", "mouseReleased"]) await b.send(b.S, "Input.dispatchMouseEvent", { type, x: p[0], y: p[1], button: "left", buttons: type === "mousePressed" ? 1 : 0, clickCount: 1 });
  await sleep(1500);
  ok(!(await b.ev(cardShown)) && await b.ev("!!document.pointerLockElement"), "computer: Play puts the card away and captures the mouse");
  await b.key("Enter", "Enter", 13); await sleep(800);
  await b.send(b.S, "Input.insertText", { text: "hello" });
  await b.key("Enter", "Enter", 13); await sleep(2500);
  ok(!(await b.ev(cardShown)), "computer: after a chat line the card does not come back");
  ok(await b.ev("!!document.pointerLockElement"), "computer: after a chat line the mouse is captured again — play goes on");
  ok(!(await b.ev("!!document.getElementById('alertBar')")), "computer: no error bar");
  await b.key("Enter", "Enter", 13); await sleep(800);
  ok(await b.ev("document.activeElement && document.activeElement.id === 'conIn'"), "computer: Enter opens the chat again — typing works");
  await b.key("Escape", "Escape", 27);
  ok(b.errs.length === 0, "computer: no page errors" + (b.errs.length ? ": " + b.errs.join(" | ") : ""));

  // 2. a phone
  const f = await browser();
  await f.send(f.S, "Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await f.send(f.S, "Emulation.setDeviceMetricsOverride", { width: 412, height: 860, deviceScaleFactor: 1, mobile: true });
  await f.send(f.S, "Page.navigate", { url: base + "/" }); await f.loaded(); await sleep(2000);
  ok(await f.ev(cardShown), "phone: a first visit shows the welcome card");
  const r = await f.ev("(() => { const r = document.querySelector('#help .card').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()");
  await f.send(f.S, "Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: r[0], y: r[1], id: 1 }] });
  await f.send(f.S, "Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await sleep(1500);
  ok(!(await f.ev(cardShown)), "phone: a tap on the card puts it away");
  await f.send(f.S, "Page.reload", {}); await f.loaded(); await sleep(2000);
  ok(!(await f.ev(cardShown)), "phone: after a reload it stays away");
  ok(f.errs.length === 0, "phone: no page errors" + (f.errs.length ? ": " + f.errs.join(" | ") : ""));
} catch (e) {
  ok(false, "harness: " + (e && e.message || e) + "\n" + fxOut.slice(-1500));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
