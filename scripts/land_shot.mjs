// land_shot.mjs <page url with ?shot=<plot>> <out.jpg> — a plot's aerial photo for its market listing (#125): opens the
// Land page in PHOTO MODE (static/land.js SHOT: the camera off the plot's south-west corner at the plot's noon, nothing
// of the page drawn) in a headless browser, waits for the page to title itself "shot-ready" (its chunks meshed and
// settled), and saves a JPEG. The world server's photographer (scripts/land_server.py _photographer) runs it, one at a
// time, niced: the browser renders in software.
//
// The browser: $LAND_SHOT_BROWSER, else the first of Brave, Chrome, Chromium on the PATH ("chrome? brave", operator
// 2026-11-07 — whichever is installed; this host has Chrome).
import { spawn, spawnSync } from "node:child_process";
import { writeFileSync, readFileSync, mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, out] = process.argv.slice(2);
if (!url || !out) { console.error("usage: land_shot.mjs <url> <out.jpg>"); process.exit(2); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => { if (process.env.DEBUG) console.log(...a); };
const onPath = (b) => spawnSync("sh", ["-c", `command -v "${b}"`]).status === 0;
const browser = process.env.LAND_SHOT_BROWSER
  || ["brave-browser", "brave", "google-chrome", "chromium", "chromium-browser"].find(onPath);
if (!browser) { console.error("no browser: install Brave or Chrome, or set LAND_SHOT_BROWSER"); process.exit(3); }

// the world server makes the profile and removes it once this process group is gone (land_server.py shoot); run by hand,
// this makes its own
const prof = process.env.LAND_SHOT_PROFILE || mkdtempSync(join(tmpdir(), "land-shot-"));
// --disable-gpu-compositing: without it a headless page's DOM and canvas updates after load are never painted
const proc = spawn(browser, ["--headless=new", "--no-sandbox", "--use-angle=swiftshader", "--disable-gpu-compositing",
  "--remote-debugging-port=0", "--user-data-dir=" + prof, "--window-size=1280,800", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
let code = 1;
try {
  // port 0: the browser picks a free port and writes it to DevToolsActivePort — two shots never collide on one
  let port; for (let i = 0; i < 120 && !port; i++) {
    const f = join(prof, "DevToolsActivePort");
    if (existsSync(f)) port = Number(readFileSync(f, "utf8").split("\n")[0]) || undefined;
    if (!port) await sleep(250);
  }
  const ver = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
  log(browser, ver.Browser);
  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.addEventListener("open", r, { once: true }); ws.addEventListener("error", j, { once: true }); });
  let id = 0, sid; const pend = new Map();
  ws.addEventListener("message", (e) => {
    const m = JSON.parse(e.data);
    if (m.method === "Runtime.exceptionThrown") log("page:", JSON.stringify(m.params.exceptionDetails).slice(0, 400));
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
  });
  const send = (m, p) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p, sessionId: sid })); });
  // a page compiling shaders in software can hold an evaluate a long time: never wait on one past 5 s
  const ask = (m, p, ms = 5000) => Promise.race([send(m, p), sleep(ms).then(() => null)]);
  const t = await send("Target.createTarget", { url: "about:blank" });
  sid = (await send("Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  await send("Page.enable", {}); await send("Runtime.enable", {});
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
  const nav = await send("Page.navigate", { url });
  if (nav.result && nav.result.errorText) throw new Error("the page did not load: " + nav.result.errorText);
  let ready = false;
  for (const end = Date.now() + 1000 * +(process.env.SHOT_S || 600); Date.now() < end && !ready;) {
    await sleep(2000);
    const r = await ask("Runtime.evaluate", { expression: "document.title", returnByValue: true });
    const title = r && r.result && r.result.result && r.result.result.value;
    log(Math.round((end - Date.now()) / 1000), title);
    ready = title === "shot-ready";
  }
  if (!ready) throw new Error("the page never settled");
  await sleep(1500);
  const shot = await send("Page.captureScreenshot", { format: "jpeg", quality: 82 });
  writeFileSync(out, Buffer.from(shot.result.data, "base64"));
  code = 0;
} catch (e) { console.error(String(e)); }
proc.kill("SIGKILL");
// the profile goes only once the browser has exited, with retries: removed at once, a browser's children still writing
// into it left the directory behind on most runs (2026-11-07)
await new Promise((r) => { if (proc.exitCode !== null || proc.signalCode) r(); else { proc.once("exit", r); setTimeout(r, 5000); } });
try { rmSync(prof, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 }); } catch (e) {}
process.exit(code);
