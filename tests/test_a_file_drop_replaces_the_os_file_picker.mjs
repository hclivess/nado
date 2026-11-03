/*
 * test_a_file_drop_replaces_the_os_file_picker.mjs — the SDK's enhanceFile turns a native <input type="file"> into a drop
 * zone, and the NFT mint form uses it (operator 2026-11-01: "did you really have to use a system default picker?").
 *
 * Drives the REAL nadodapp.js in headless Chromium over CDP, served from this checkout's static/ by a throwaway
 * server (nothing here talks to a node), and proves:
 *   1. the operating-system control is not what the user sees: the input is visually gone, the zone is there
 *   2. a dropped file reaches onFile — a drop bypasses the browser's `accept`, so the zone re-checks it and a
 *      dropped .txt never reaches onFile
 *   3. a pasted file reaches onFile too
 *   4. busy shows progress, done shows the preview with Replace/Remove, Remove calls onRemove and resets
 *   5. static/nft.js mounts the zone on its file input (and restores no value into a file input on re-render)
 *
 * Run:  node tests/test_a_file_drop_replaces_the_os_file_picker.mjs        (needs chromium)
 */
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
// the SDK imports the relay's /protocol.js: serve the module the relay itself would render (tests/protocol_hook.mjs)
import { PROTOCOL_JS } from "./protocol_hook.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const STATIC = join(ROOT, "static");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 5. the page wiring, read from source
const nftJs = readFileSync(join(STATIC, "nft.js"), "utf8");
ok(/enhanceFile\(\$\("mFile"\)/.test(nftJs), "nft.js mounts the SDK drop zone on its file input");
ok(/el\.type !== "file"/.test(nftJs), "nft.js never writes a remembered value back into a file input (that throws)");

const PAGE = `<!doctype html><meta charset="utf-8"><body><label>f</label>
<input id="f" type="file" accept="image/png,image/jpeg,video/mp4,.glb">
<script type="module">
import { enhanceFile } from "/static/nadodapp.js";
window.got = []; window.removed = 0;
window.zone = enhanceFile(document.getElementById("f"), { hint: "max 5 MB",
  onFile: (f) => window.got.push(f.name), onRemove: () => window.removed++ });
window.ready = true;
</script>`;
const srv = createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/") { res.setHeader("content-type", "text/html"); return res.end(PAGE); }
  if (u.pathname === "/protocol.js") { res.setHeader("content-type", "text/javascript"); return res.end(PROTOCOL_JS); }
  const p = normalize(join(ROOT, u.pathname));
  if (!p.startsWith(STATIC + "/")) { res.statusCode = 404; return res.end(); }
  try { const b = readFileSync(p); res.setHeader("content-type", p.endsWith(".js") ? "text/javascript" : "application/octet-stream"); res.end(b); }
  catch (e) { res.statusCode = 404; res.end(); }
});
await new Promise((r) => srv.listen(0, "127.0.0.1", r));
const HTTP = srv.address().port;

// a machine with no Chromium (the CI runner) cannot drive this walk: a declared SKIP, never a FAIL that reads as a broken
// drop zone. Only the binary's absence skips; a Chromium that is present but fails to start is still a FAIL below.
import { execFileSync } from "node:child_process";
try { execFileSync("sh", ["-c", "command -v chromium-browser"], { stdio: "ignore" }); }
catch (e) { console.log(`SKIP  chromium-browser is not installed: the drop zone walk needs it (${fails} source check(s) failed)`); process.exit(fails ? 1 : 0); }

const PORT = 9300 + (process.pid % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-filedrop-"));
const chrome = spawn("chromium-browser", ["--headless", "--disable-gpu", "--no-sandbox",
  "--remote-debugging-port=" + PORT, "--user-data-dir=" + prof, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0; const pend = new Map(); let sid;
const send = (m, p) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p, sessionId: sid })); });
async function evl(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result.result.value;
}
function cleanup() { try { chrome.kill("SIGKILL"); } catch (e) {} try { srv.close(); } catch (e) {} try { rmSync(prof, { recursive: true, force: true }); } catch (e) {} }

try {
  let ver = null;
  for (let i = 0; i < 60 && !ver; i++) { try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch (e) { await sleep(250); } }
  if (!ver) throw new Error("chromium did not start");
  ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
  const t = await send("Target.createTarget", { url: "about:blank" });
  sid = (await send("Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  await send("Runtime.enable", {}); await send("Page.enable", {});
  await send("Page.navigate", { url: `http://127.0.0.1:${HTTP}/` });
  for (let i = 0; i < 40 && !(await evl("!!window.ready").catch(() => false)); i++) await sleep(150);
  ok(await evl("!!window.ready"), "the page imported the SDK and mounted the zone");

  // 1. what the user sees
  const vis = await evl(`(() => { const i = document.getElementById("f"), r = i.getBoundingClientRect(), z = document.querySelector(".fdrop");
    return { iw: r.width, op: getComputedStyle(i).opacity, zone: !!z && z.contains(i), zh: z ? z.getBoundingClientRect().height : 0,
             txt: z ? z.textContent.replace(/\\s+/g, " ").trim() : "" }; })()`);
  ok(vis.iw <= 1 && vis.op === "0", "the native file control is visually gone (" + vis.iw + "px, opacity " + vis.op + ")");
  ok(vis.zone && vis.zh > 60, "a drop zone wraps it, " + Math.round(vis.zh) + "px tall");
  ok(/Drag and drop/.test(vis.txt) && /max 5 MB/.test(vis.txt), "the zone says what to do and shows the hint: " + vis.txt);

  // 2. a real drop event carrying a DataTransfer
  const drop = (name, type) => evl(`(() => { const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array([1,2,3])], ${JSON.stringify(name)}, { type: ${JSON.stringify(type)} }));
    const z = document.querySelector(".fdrop");
    z.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt, bubbles: true, cancelable: true }));
    const over = z.classList.contains("over");
    z.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
    return { over, after: z.classList.contains("over"), got: window.got.slice() }; })()`);
  let r = await drop("art.png", "image/png");
  ok(r.over && !r.after, "dragging over highlights the zone, dropping clears it");
  ok(r.got.join() === "art.png", "a dropped PNG reaches onFile");
  r = await drop("notes.txt", "text/plain");
  ok(r.got.join() === "art.png", "a dropped .txt is refused by the zone's own accept check");
  r = await drop("model.glb", "");
  ok(r.got.join() === "art.png,model.glb", "a typeless .glb is accepted by its extension");

  // 3. paste
  const pasted = await evl(`(() => { const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array([9])], "shot.png", { type: "image/png" }));
    const e = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }); document.body.dispatchEvent(e);
    return window.got.slice(); })()`);
  ok(pasted[pasted.length - 1] === "shot.png", "a pasted image reaches onFile");

  // 4. the states
  const st = await evl(`(() => { const z = window.zone, out = {};
    z.busy(42, "Uploading art.png"); out.bar = document.querySelector(".fdbar i").style.width; out.busy = z.el.classList.contains("busy");
    z.done('<img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">', "art.png · 3 KB");
    out.prev = !!document.querySelector(".fdprev img"); out.btns = [...document.querySelectorAll("[data-fd]")].map((b) => b.dataset.fd).join();
    document.querySelector('[data-fd="remove"]').click();
    out.removed = window.removed; out.reset = !!document.querySelector(".fdicon") && !z.el.classList.contains("has");
    return out; })()`);
  ok(st.busy && st.bar === "42%", "busy shows a progress bar at the given percent (" + st.bar + ")");
  ok(st.prev && st.btns === "replace,remove", "done shows the preview with Replace and Remove");
  ok(st.removed === 1 && st.reset, "Remove calls onRemove and returns to the empty zone");
} catch (e) {
  ok(false, "harness: " + (e && e.message || e));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
