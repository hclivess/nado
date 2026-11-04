/*
 * test_nft_market_live_e2e.mjs — LIVE (tests/test_tests_are_isolated.py LIVE; scripts/run_tests.sh skips it). The NFT
 * marketplace walked end to end on the REAL site, as its users: nft.nadochain.com in headless Chromium, every signature
 * through the real wallet at get.nadochain.com, every step read back from the exec node.
 *   seller: sign in -> drop a file on the upload zone (pinned on IPFS) -> mint + royalty in ONE wallet approval
 *           -> list 1 edition at 0.5 NADO
 *   buyer:  sign in -> deposit with the slider -> buy -> holds the NFT; the token page's history shows mint, list, sale
 * It moves real coins: run it with two THROWAWAY wallets, each funded with ~2 NADO, never a real wallet or a node key
 * (CLAUDE.md rule 8). NADO_E2E_WALLETS names a JSON file {"seller": W, "buyer": W}, W = {address, publicKey,
 * privateKey} as the wallet stores it (ops/key_ops.generate_keys gives the three). First run 2026-11-02: every step
 * passed; it found the finance pages' "Buy in" wording (tests/test_every_finance_app_says_deposit_not_buy_in.py).
 * Run on the relay host:  NADO_E2E_WALLETS=/path/wallets.json node tests/test_nft_market_live_e2e.mjs
 */
import { spawn } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
if (!process.env.NADO_E2E_WALLETS) { console.log("SKIP  NADO_E2E_WALLETS is not set (two funded throwaway wallets; see the header)"); process.exit(0); }
const WALLETS = JSON.parse(readFileSync(process.env.NADO_E2E_WALLETS, "utf8"));
let ROLE = "seller", W = WALLETS.seller;
const st = {};
const save = () => {};
const CID = "b0162edacd9f4c6c6a27391c692d90c5";
const EX = "http://127.0.0.1:9273";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

// the snap Chromium can only write under its own common dir; each role gets a fresh profile, removed afterwards
const SNAP = (process.env.HOME || "/root") + "/snap/chromium/common";
let PORT, PROF, chrome;
let ws, id = 0, sid; const pend = new Map();
const send = (m, p) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p, sessionId: sid })); });
async function evl(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (!r.result) return undefined;
  if (r.result.exceptionDetails) return undefined;
  return r.result.result.value;
}
const consoleLines = [];
async function boot() {
  sid = undefined; pend.clear(); id = 0;   // a fresh browser per role: the last role's session id names a dead target
  PORT = 9500 + Math.floor(Math.random() * 300); PROF = SNAP + "/nft-e2e-" + ROLE + "-" + process.pid;
  chrome = spawn("chromium-browser", ["--headless", "--disable-gpu", "--no-sandbox", "--window-size=1200,1600",
    "--remote-debugging-port=" + PORT, "--user-data-dir=" + PROF, "about:blank"], { stdio: "ignore" });
  let v = null;
  for (let i = 0; i < 80 && !v; i++) { try { v = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch (e) { await sleep(250); } }
  ws = new WebSocket(v.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown") consoleLines.push("EXC " + JSON.stringify(m.params.exceptionDetails).slice(0, 300));
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") consoleLines.push("ERR " + m.params.args.map((a) => a.value || a.description).join(" ").slice(0, 300));
  });
  const t = await send("Target.createTarget", { url: "about:blank" });
  sid = (await send("Target.attachToTarget", { targetId: t.result.targetId, flatten: true })).result.sessionId;
  await send("Runtime.enable", {}); await send("Page.enable", {});
}
const go = async (url) => { await send("Page.navigate", { url }); await sleep(2500); };
const href = () => evl("location.href");
// the autopilot: confirm whatever modal is open (wallet .modal-ok, SDK .sdk-modal .ok), logging what it said
async function autopilot() {
  const r = await evl(`(() => { const vis = (e) => e && e.offsetParent !== null;
    for (const sel of [".modal-ok", ".sdk-modal .ok"]) { const b = [...document.querySelectorAll(sel)].find(vis);
      if (b) { const box = b.closest(".modal, .sdk-modal, [role=dialog]") || b.parentNode.parentNode;
        const txt = (box ? box.textContent : "").replace(/\\s+/g, " ").trim().slice(0, 220); b.click(); return location.host + " | " + txt; } }
    return ""; })()`);
  if (r) log("  confirm:", r);
  return !!r;
}
async function until(desc, fn, ms = 600000, pilot = true) {   // pilot false: read a dialog before anything confirms it
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (pilot) await autopilot();
    let v; try { v = await fn(); } catch (e) {}
    if (v) { console.log("PASS  " + desc + (typeof v === "string" ? " — " + v.slice(0, 120) : "")); return v; }
    await sleep(1500);
  }
  throw new Error("timed out: " + desc + " at " + (await href()));
}
const exj = async (p) => (await fetch(EX + p)).json();
const storage = async () => (await exj("/exec/contract?cid=" + CID)).storage || {};

async function signIn() {
  await go("https://get.nadochain.com/");
  await evl(`localStorage.setItem("nado_miner_wallet", ${JSON.stringify(JSON.stringify({ address: W.address, publicKey: W.publicKey, privateKey: W.privateKey }))}); true`);
  await go("https://nft.nadochain.com/#explore");
  await until("page booted", () => evl(`!!document.getElementById("btnSignIn")`));
  const signed = await evl(`(document.getElementById("who")||{}).textContent||""`);
  if (!/not signed/i.test(signed) && signed.trim()) { log("already signed in:", signed); return; }
  await evl(`document.getElementById("btnSignIn").click(); true`);
  await until("signed in as " + W.address.slice(0, 8), async () => {
    const h = await href(); if (!h || !h.startsWith("https://nft.")) return false;
    const w = await evl(`(document.getElementById("who")||{}).textContent||""`);
    return w && !/not signed/i.test(w) ? w : false;
  }, 180000);
}

async function seller() {
  await boot(); await signIn();
  // 1. upload through the drop zone: a real PNG drawn on a canvas, dropped as a File
  await go("https://nft.nadochain.com/#create");
  await until("create form", () => evl(`!!document.querySelector(".fdrop")`));
  await evl(`(async () => { const c = document.createElement("canvas"); c.width = c.height = 256; const g = c.getContext("2d");
    const gr = g.createLinearGradient(0, 0, 256, 256); gr.addColorStop(0, "#00ad93"); gr.addColorStop(1, "#e3b341"); g.fillStyle = gr; g.fillRect(0, 0, 256, 256);
    g.fillStyle = "#0b0f14"; g.font = "bold 40px sans-serif"; g.fillText("NADO e2e", 30, 140); g.fillText(${JSON.stringify(new Date().toISOString().slice(0, 16))}.slice(11), 60, 190);
    const blob = await new Promise((r) => c.toBlob(r, "image/png")); const dt = new DataTransfer(); dt.items.add(new File([blob], "e2e-art.png", { type: "image/png" }));
    document.querySelector(".fdrop").dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true })); return true; })()`);
  const uri = await until("uploaded, media link filled", () => evl(`(() => { const v = document.getElementById("mUri").value; return v.startsWith("ipfs://") ? v : ""; })()`), 60000);
  st.uri = uri; save();
  log("  zone shows:", await evl(`document.querySelector(".fdrop").textContent.replace(/\\s+/g," ").trim().slice(0,160)`));
  const r = await fetch("https://nft.nadochain.com/ipfs/" + uri.slice(7)); log("  public /ipfs/ fetch:", r.status, r.headers.get("content-type"));
  // 2. mint: asset_create and the royalty register, both from ONE wallet approval (nadodapp signBlob opts.then)
  await evl(`document.getElementById("mName").value = "NADO e2e #1"; document.getElementById("mRoyalty").value = "10"; document.getElementById("btnMint").click(); true`);
  const asset = await until("asset created on chain", async () => {
    const a = await exj("/exec/assets?issuer=" + W.address); const list = Array.isArray(a) ? a : (a.assets || a.issued || []);
    const x = list.find((z) => z.uri === uri); return x ? String(x.id) : false;
  });
  st.asset = asset; save();
  await until("royalty registered (t_* row)", async () => {
    const s = await storage(); const t = s.t_asset || s.t_aid || null;
    const hit = JSON.stringify(s).includes(asset); if (!hit) { const h = await href(); if (h && !h.startsWith("https://nft.") && !h.startsWith("https://get.")) return false; }
    return hit ? "asset id present in contract storage" : false;
  });
  // 3. list 1 unit at 0.5 NADO from the token page
  await go("https://nft.nadochain.com/#token/" + asset);
  await until("token page", () => evl(`!!document.querySelector('[data-act="list"]')`));
  await evl(`document.getElementById("sUnits").value = "1"; document.getElementById("sPrice").value = "0.5"; document.querySelector('[data-act="list"]').click(); true`);
  const said = await until("the wallet's listing confirm names the NFT's units, not NADO", async () => {
    const t = await evl(`(() => { const b = [...document.querySelectorAll(".modal-ok")].find((e) => e.offsetParent !== null); const m = b && b.closest(".modal, [role=dialog]"); return m ? m.textContent.replace(/\\s+/g, " ") : ""; })()`);
    if (!t) return false;
    if (/ESCROWS [0-9.]+ NADO/.test(t)) throw new Error("the listing confirm says NADO: " + t.slice(0, 200));
    return /units of asset/.test(t) ? t.slice(0, 160) : false;
  }, 120000, false);
  await until("listed on chain (an open listing of this asset)", async () => {
    const s = await storage(); const la = s.l_asset || {};
    return Object.keys(la).some((l) => la[l] === asset && Number((s.l_left || {})[l] || 0) > 0) ? "listing open" : false;
  });
  log("  token page:", (await evl(`document.getElementById("view").textContent.replace(/\\s+/g," ").trim().slice(0,400)`)));
}

async function buyer() {
  await boot(); await signIn();
  // deposit 1 NADO into the execution layer so the buy can pay
  log("  page shows: bal=", await evl(`(document.getElementById("bal")||{}).textContent`), " l1bal=", await evl(`(document.getElementById("l1bal")||{}).textContent`));
  const have = BigInt(((await exj("/exec/bridge?provisional=1")).balances || {})[W.address] || 0);
  if (have > 0n) log("  usable balance already on the exec layer:", String(have)); else {
  await until("wallet balance shown", async () => { const t = await evl(`(document.getElementById("l1bal")||{}).textContent||""`); return /[1-9]/.test(t) ? t : false; }, 60000);
  await evl(`(() => { const s = document.getElementById("buyinSlider"); s.value = "60"; s.dispatchEvent(new Event("input", {bubbles:true})); return document.getElementById("buyinSliderP").textContent; })()`).then((t) => log("  slider:", t));
  await evl(`document.getElementById("btnDeposit").click(); true`);
  await until("deposit landed (usable balance > 0)", async () => {
    const h = await href(); if (h && h.startsWith("https://nft.")) { const b = await evl(`(document.getElementById("bal")||{}).textContent||""`); return /[1-9]/.test(b) ? b : false; }
    return false;
  });
  }
  await until("page shows the usable balance", async () => { const b = await evl(`(document.getElementById("bal")||{}).textContent||""`); return /[1-9]/.test(b) ? b : false; }, 120000);
  await go("https://nft.nadochain.com/#token/" + st.asset);
  await until("buy button", () => evl(`!!document.querySelector('[data-act="buy"]')`));
  await evl(`document.querySelector('[data-act="buy"]').click(); true`);
  await until("bought: buyer holds the NFT", async () => {
    const a = await exj("/exec/assets?holder=" + W.address); const list = Array.isArray(a) ? a : (a.held || a.assets || []);
    const x = list.find((z) => String(z.id) === st.asset && BigInt(z.balance || 0) > 0n); return x ? "balance " + x.balance : false;
  });
  await go("https://nft.nadochain.com/#token/" + st.asset);
  await sleep(6000);
  log("  token page after sale:", (await evl(`document.getElementById("view").textContent.replace(/\\s+/g," ").trim().slice(0,900)`)));
}

async function shutdown() { try { ws && ws.close(); } catch (e) {} try { chrome && chrome.kill("SIGKILL"); } catch (e) {} await sleep(500); try { rmSync(PROF, { recursive: true, force: true }); } catch (e) {} }
let failed = false;
for (const role of ["seller", "buyer"]) {
  ROLE = role; W = WALLETS[role];
  try { await (role === "seller" ? seller() : buyer()); }
  catch (e) { failed = true; console.log("FAIL  " + role + ": " + e.message); log("  page:", (await evl(`document.body.innerText.slice(0,600)`).catch(() => "")) || ""); }
  finally { if (consoleLines.length) log("page errors:\n  " + consoleLines.splice(0).slice(-15).join("\n  ")); await shutdown(); }
  if (failed) break;
}
if (!failed) {   // the money, read back from the exec node
  const b = (await exj("/exec/bridge")).balances || {};
  const sale = Object.entries(((await storage()).s_asset) || {}).find(([, a]) => a === st.asset);
  console.log((sale ? "PASS" : "FAIL") + "  the sale is in the contract's sales log");
  console.log((b[CID] == null || BigInt(b[CID]) === 0n ? "PASS" : "FAIL") + "  the marketplace keeps nothing (0 % fee): " + (b[CID] || 0));
}
console.log(failed ? "FAILED" : "ALL PASS");
process.exit(failed ? 1 : 0);
