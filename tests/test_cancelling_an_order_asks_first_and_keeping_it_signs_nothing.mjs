/*
 * test_cancelling_an_order_asks_first_and_keeping_it_signs_nothing.mjs — a click on Cancel in the trading page's order list
 * opens a confirm naming the order, "Keep it" signs nothing, and only "Cancel the order" hands the cancel to the wallet.
 *
 * Why: a value-free call (cancel, release) is signed in the BACKGROUND by a wallet with auto-sign on — no wallet dialog —
 * so the page's own confirm is the only thing between one click and an order gone for good. 2026-11-05: two open ETH asks
 * (#933940343, #664875090, ~9 days left) were cancelled by their owner's key a minute after posting, by a click the owner
 * never meant; the Cancel button signed on the spot.
 *
 * Drives the REAL static/dex.html + dex.js in headless Chromium over CDP, served from this checkout by a throwaway server
 * that answers the page's reads with a fixture book (one open ASK of the signed-in address) — nothing here talks to a
 * node, and every request to the wallet origin is failed at the browser, so no signer can ever load. "Signed" is observed
 * as the SDK's hidden background-signer iframe appearing (nadodapp _ensureBgSvc creates it on the first background call).
 *
 * Run:  node tests/test_cancelling_an_order_asks_first_and_keeping_it_signs_nothing.mjs        (needs chromium)
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
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// the page wiring, read from source: every order-ending value-free call confirms before it signs
const dexJs = readFileSync(join(STATIC, "dex.js"), "utf8");
for (const what of ["cancel", "release"]) {
  const m = dexJs.match(new RegExp(`if \\(what === "${what}"\\) \\{([\\s\\S]*?)\\n  \\}`));
  ok(m && /await uiConfirm\(/.test(m[1]) && m[1].indexOf("uiConfirm") < m[1].indexOf("dapp.call"),
     `dex.js confirms a ${what} before dapp.call signs it`);
}

const OTC_CID = dexJs.match(/^const OTC_CID = "([0-9a-z]+)";/m)[1];
const ME = "3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f";     // any valid address: the page only DISPLAYS as it
const O = 4265607589, now = Math.floor(Date.now() / 1000);
const one = (v) => ({ [O]: v });
const STORAGE = { mk: one(1), kind: one(1), maker: one(ME), namt: one(20000000000), esc: one(20000000000), wch: one("eth"),
  wamt: one("0.006"), wadr: one("0x406Ed37679f237EA099985D8C9CE96B538F916b0"), hsha: one("ab".repeat(32)),
  expn: one(50000), expf: one(String(now + 86400)), st: one(1) };
const json = (res, v) => { res.setHeader("content-type", "application/json"); res.end(JSON.stringify(v)); };
const srv = createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/" || u.pathname === "/dex.html") { res.setHeader("content-type", "text/html"); return res.end(readFileSync(join(STATIC, "dex.html"))); }
  if (u.pathname === "/protocol.js") { res.setHeader("content-type", "text/javascript"); return res.end(PROTOCOL_JS); }
  if (u.pathname === "/exec/contract" && u.searchParams.get("cid") === OTC_CID) return json(res, { storage: STORAGE });
  if (u.pathname === "/exec/root") return json(res, { cursor: 1000, block_ts: now, root: "00" });
  if (u.pathname.startsWith("/static/")) {
    const p = normalize(join(ROOT, u.pathname));
    if (!p.startsWith(STATIC + "/")) { res.statusCode = 404; return res.end(); }
    try {
      const b = readFileSync(p);
      res.setHeader("content-type", p.endsWith(".js") || p.endsWith(".mjs") ? "text/javascript" : p.endsWith(".css") ? "text/css"
        : p.endsWith(".wasm") ? "application/wasm" : p.endsWith(".json") ? "application/json" : "application/octet-stream");
      return res.end(b);
    } catch (e) { res.statusCode = 404; return res.end(); }
  }
  return json(res, {});                                   // every other read: an empty answer, as from a quiet chain
});
await new Promise((r) => srv.listen(0, "127.0.0.1", r));
const HTTP = srv.address().port;

// THE BROWSER: the first candidate that actually serves CDP (tests/test_a_file_drop_replaces_the_os_file_picker.mjs has
// the history); none → a declared SKIP after the source checks, never a FAIL that reads as a broken page.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = 9300 + ((process.pid + 211) % 600);
const prof = mkdtempSync(join(tmpdir(), "cdp-dexcancel-"));
let chrome = null, ver = null;
const tried = [];
for (const bin of [process.env.CHROME, "chromium-browser", "chromium", "google-chrome", "google-chrome-stable"].filter(Boolean)) {
  const c = spawn(bin, ["--headless", "--disable-gpu", "--no-sandbox", "--remote-debugging-port=" + PORT,
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
  console.log(`SKIP  no browser served CDP (tried ${tried.join(", ") || "none"}): the cancel walk needs one (${fails} source check(s) failed)`);
  process.exit(fails ? 1 : 0);
}
let ws, id = 0; const pend = new Map(); let sid; const walletHits = [];
const send = (m, p) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p, sessionId: sid })); });
async function evl(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  return r.result.result.value;
}
async function until(expr, ms = 15000) {
  for (let t = 0; t < ms; t += 200) { if (await evl(expr).catch(() => false)) return true; await sleep(200); }
  return false;
}
function cleanup() { try { chrome.kill("SIGKILL"); } catch (e) {} try { srv.close(); } catch (e) {} try { rmSync(prof, { recursive: true, force: true }); } catch (e) {} }

const SIGNER = `!!document.querySelector('iframe[src*="bgsvc"]')`;
const clickCancel = `(() => { const b = document.querySelector('#otcMine [data-otc="cancel"][data-o="${O}"]'); if (!b) return false; b.click(); return true; })()`;
const modal = `(() => { const m = [...document.querySelectorAll(".sdk-modal")].find((e) => e.offsetParent !== null);
  return m ? { text: m.textContent.replace(/\\s+/g, " "), ok: m.querySelector("button.ok").textContent, no: m.querySelector("button.cancel").textContent } : null; })()`;
const press = (cls) => `(() => { const m = [...document.querySelectorAll(".sdk-modal")].find((e) => e.offsetParent !== null);
  if (!m) return false; m.querySelector("button.${cls}").click(); return true; })()`;

try {
  ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
    if (m.method === "Fetch.requestPaused") {           // the wallet origin never loads: nothing could sign even if asked
      walletHits.push(m.params.request.url);
      send("Fetch.failRequest", { requestId: m.params.requestId, errorReason: "BlockedByClient" });
    }
  });
  const t = await send("Target.createTarget", { url: "about:blank" });
  sid = (await send("Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  await send("Runtime.enable", {}); await send("Page.enable", {});
  await send("Fetch.enable", { patterns: [{ urlPattern: "*nadochain.com*" }] });
  await send("Page.navigate", { url: `http://127.0.0.1:${HTTP}/static/nadodapp.js` });   // same origin, to seed the session
  await until("document.readyState === 'complete'");
  await evl(`localStorage.setItem("nado_dex_me_v2", ${JSON.stringify(ME)}); localStorage.setItem("nado_dex_mode", "otc"); true`);
  await send("Page.navigate", { url: `http://127.0.0.1:${HTTP}/` });
  await until("!!document.getElementById('modeBar')");
  await evl(`(() => { const b = [...document.querySelectorAll("#modeBar *")].find((e) => /Cross-chain/i.test(e.textContent) && e.click && !e.children.length) ||
    [...document.querySelectorAll("#modeBar button")].find((e) => /Cross-chain/i.test(e.textContent)); if (b) b.click(); return !!b; })()`);
  ok(await until(`!!document.querySelector('#otcMine [data-otc="cancel"][data-o="${O}"]')`, 20000),
     "the signed-in maker sees a Cancel button on their open order");

  // 1. a click opens the confirm; nothing has been handed to a signer
  ok(await evl(clickCancel), "clicked Cancel");
  ok(await until(`!!(${modal})`), "a confirm opens");
  const m1 = await evl(modal);
  ok(m1 && /#4265607589/.test(m1.text) && /2 NADO for 0\.006 ETH/.test(m1.text), "it names the order and its terms: " + (m1 && m1.text.slice(0, 120)));
  ok(m1 && m1.ok === "Cancel the order" && m1.no === "Keep it", `its buttons say what they do ("${m1 && m1.ok}" / "${m1 && m1.no}")`);
  ok(!(await evl(SIGNER)), "while the confirm is open, nothing is handed to the wallet");

  // 2. Keep it → nothing signs
  ok(await evl(press("cancel")), "pressed Keep it");
  await sleep(1500);
  ok(!(await evl(SIGNER)) && walletHits.length === 0, "Keep it signs nothing: no signer, no wallet request");

  // 3. confirm → only now the cancel goes to the wallet (whose origin the browser refuses — nothing can sign)
  ok(await evl(clickCancel), "clicked Cancel again");
  ok(await until(`!!(${modal})`), "the confirm opens again");
  ok(await evl(press("ok")), "pressed Cancel the order");
  ok(await until(SIGNER, 5000), "only after confirming is the cancel handed to the wallet's background signer");
} catch (e) {
  ok(false, "harness: " + (e && e.message || e));
} finally { cleanup(); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
