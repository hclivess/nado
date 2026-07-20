/*
 * assets_ui_e2e.mjs — drives the REAL wallet page over CDP to prove the Assets tab (doc/assets.md)
 * renders and behaves: the token list, the decimal conversion on both edges, the Max button, the
 * select population, and the client-side guards that must fire BEFORE anything is signed.
 *
 * The exec node's /exec/assets is INTERCEPTED and fulfilled with a fixture, so this tests the wallet
 * against a known ledger without needing assets to exist on whatever chain the node is following. The
 * fixture deliberately includes a balance above 2^53 — the case the endpoint sends as a string, and the
 * one a plain JSON number would silently round.
 *
 * Run:  node tests/assets_ui_e2e.mjs [walletUrl]      (needs chromium + a node serving /static)
 */
import { spawn } from "node:child_process";

const PORT = 9372;
const URL0 = process.argv[2] || "http://127.0.0.1:9173/";
const chrome = spawn("chromium-browser", ["--headless", "--disable-gpu", "--no-sandbox",
  "--remote-debugging-port=" + PORT, "--user-data-dir=/tmp/cdp-assets-ui", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0, pend = new Map(), sid;
const send = (m, p) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p, sessionId: sid })); });
const pageErrors = [];

// A wallet the page can boot with. The keys are throwaway and never sign anything here — every assertion
// below stops at a client-side guard or a read, on purpose: this suite must not be able to move funds.
const WALLET = {
  address: "mldsa440cc39948f96514d79d58cc591fa38519b36e0d86e03520",
  publicKey: "aa".repeat(650),
  privateKey: "bb".repeat(32),
};
// a REAL address (valid prefix + checksum) — the wallet's own validateAddress rejects a made-up one,
// so a fake here would make every guard below fire for the wrong reason
const PAYEE = "mldsa44e9cedd20a480703e1f0d957219fdfa8d768e6e1d7efacd";
const BIG = "1152921504606846976";                       // 2^60 — beyond IEEE-double integer precision
const ASSETS = {
  held: [
    { issuer: WALLET.address, seed: 1, name: "Demo Coin", sym: "DEMO", dec: 4, supply: "50000000000",
      mintable: true, id: "4566492408191623015", holders: 2, balance: "49987660000" },
    { issuer: PAYEE, seed: 1, name: "Big Units", sym: "BIG", dec: 0, supply: BIG,
      mintable: false, id: "9450293", holders: 1, balance: BIG },
  ],
  issued: [
    { issuer: WALLET.address, seed: 1, name: "Demo Coin", sym: "DEMO", dec: 4, supply: "50000000000",
      mintable: true, id: "4566492408191623015", holders: 2 },
    { issuer: WALLET.address, seed: 2, name: "Fixed Thing", sym: "FIX", dec: 2, supply: "2100000000",
      mintable: false, id: "777777", holders: 1 },
  ],
};

async function evl(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error("page threw: " + JSON.stringify(r.result.exceptionDetails.exception).slice(0, 300));
  return r.result.result.value;
}
const text = (sel) => evl(`((document.querySelector(${JSON.stringify(sel)})||{}).textContent||"").trim()`);
const click = (sel) => evl(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return "MISSING"; b.click(); return "ok"; })()`);
const setVal = (sel, v) => evl(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); e.value = ${JSON.stringify(v)}; return e.value; })()`);

/* Clear the message slot, click, then POLL for it to fill. The guards are not all synchronous — the
 * alias-shaped path does a relay round-trip first — so reading the message a fixed sleep after the click
 * reads whatever the PREVIOUS scenario left there, and the suite silently grades the wrong string. */
async function clickForMsg(btnSel, msgSel, timeoutMs = 8000) {
  await evl(`document.querySelector(${JSON.stringify(msgSel)}).textContent = ""`);
  const c = await click(btnSel);
  if (c !== "ok") throw new Error("missing button " + btnSel);
  for (let waited = 0; waited < timeoutMs; waited += 200) {
    await sleep(200);
    const m = await text(msgSel);
    if (m) return m;
  }
  return "";
}

let fails = 0;
async function scenario(name, fn) {
  try { await fn(); console.log("PASS  " + name); }
  catch (e) { fails++; console.log("FAIL  " + name + ": " + (e.message || e)); }
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }

try {
  let v = null;
  for (let i = 0; i < 30 && !v; i++) {
    await sleep(1500);
    try { v = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch {}
  }
  if (!v) throw new Error("chromium debugger never came up on :" + PORT);
  ws = new WebSocket(v.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = async (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
    if (d.method === "Runtime.exceptionThrown") {
      const ex = d.params.exceptionDetails;
      pageErrors.push(String((ex.exception && ex.exception.description) || ex.text).slice(0, 200));
    }
    if (d.method === "Fetch.requestPaused") {
      const u = d.params.request.url;
      const body = u.includes("issuer=") ? { assets: ASSETS.issued } : { assets: ASSETS.held };
      await send("Fetch.fulfillRequest", {
        requestId: d.params.requestId, responseCode: 200,
        responseHeaders: [{ name: "content-type", value: "application/json" },
                          { name: "access-control-allow-origin", value: "*" }],
        body: Buffer.from(JSON.stringify({ ...body, cursor: 1 })).toString("base64"),
      });
    }
  };
  const t = await send("Target.createTarget", { url: "about:blank" });
  const a = await send("Target.attachToTarget", { targetId: t.result.targetId, flatten: true });
  sid = a.result.sessionId;
  await send("Runtime.enable", {});
  await send("Page.enable", {});
  // seed the wallet BEFORE any of the page's own scripts run, so it boots straight past the setup card
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: `try { localStorage.setItem("nado_miner_wallet", ${JSON.stringify(JSON.stringify(WALLET))});
             localStorage.setItem("nado_miner_relay", ${JSON.stringify(URL0.replace(/\/+$/, ""))}); } catch (e) {}`,
  });
  await send("Fetch.enable", { patterns: [{ urlPattern: "*/exec/assets*" }] });
  await send("Page.navigate", { url: URL0 });
  await sleep(9000);

  await scenario("wallet booted with the Assets tab present", async () => {
    assert(await evl(`!!document.querySelector('[data-tabbtn="assets"]')`), "no Assets tab button");
    assert(await evl(`!!document.getElementById("assetsCard")`), "no assets card");
  });

  await scenario("Assets tab renders the held tokens from /exec/assets", async () => {
    assert(await click('[data-tabbtn="assets"]') === "ok", "could not click the Assets tab");
    await sleep(2500);
    assert(await evl(`!document.getElementById("assetsCard").classList.contains("hidden")`), "card stayed hidden");
    const list = await text("#assetsList");
    assert(list.includes("DEMO") && list.includes("Demo Coin"), "held list missing DEMO: " + list.slice(0, 200));
    // 49987660000 raw at dec=4 -> 4998766
    assert(list.includes("4998766"), "decimal conversion wrong: " + list.slice(0, 200));
    assert(list.includes("mintable"), "mintable flag not shown: " + list.slice(0, 200));
  });

  await scenario("a balance beyond 2^53 survives exactly (string amounts)", async () => {
    const list = await text("#assetsList");
    assert(list.includes(BIG), "2^60 balance was rounded — string amounts are not reaching BigInt: " + list.slice(0, 300));
  });

  await scenario("issued list + selects are populated", async () => {
    const issued = await text("#assetIssuedList");
    assert(issued.includes("FIX") && issued.includes("fixed supply"), "issued list wrong: " + issued.slice(0, 200));
    const send1 = await evl(`[...document.querySelectorAll("#assetSendId option")].map((o) => o.textContent).join("|")`);
    assert(send1.includes("DEMO") && send1.includes("BIG"), "send select not filled: " + send1);
    // only MINTABLE issued assets may be minted, so FIX must not be offered
    const mintSel = await evl(`[...document.querySelectorAll("#assetIssuedId option")].map((o) => o.textContent).join("|")`);
    assert(mintSel.includes("DEMO") && !mintSel.includes("FIX"), "a fixed-supply asset was offered for minting: " + mintSel);
  });

  await scenario("Max fills the exact held balance", async () => {
    await evl(`document.getElementById("assetSendId").value = "4566492408191623015"`);
    assert(await click("#btnAssetSendMax") === "ok", "no Max button");
    await sleep(200);
    const v2 = await evl(`document.getElementById("assetSendAmt").value`);
    assert(v2 === "4998766", "Max filled " + v2 + ", expected 4998766");
  });

  // The guards below must all reject BEFORE the confirm dialog — nothing gets signed in this suite.
  await scenario("rejects a bad recipient", async () => {
    // "!!bad" cannot be an alias either, so this lands on the address check rather than alias resolution
    await setVal("#assetSendTo", "!!bad");
    await setVal("#assetSendAmt", "1");
    const m = await clickForMsg("#btnAssetSend", "#assetSendMsg");
    assert(/valid address|registered alias/i.test(m), "expected a recipient error, got: " + m);
  });

  await scenario("an alias-shaped recipient that is not registered says so", async () => {
    await setVal("#assetSendTo", "definitely-not-registered");
    await setVal("#assetSendAmt", "1");
    const m = await clickForMsg("#btnAssetSend", "#assetSendMsg");
    assert(/isn't registered|is not registered/i.test(m), "expected an alias error, got: " + m);
  });

  await scenario("rejects more decimals than the asset has", async () => {
    await setVal("#assetSendTo", PAYEE);
    await setVal("#assetSendAmt", "1.123456789");
    const m = await clickForMsg("#btnAssetSend", "#assetSendMsg");
    assert(/decimal/i.test(m), "expected a decimals error, got: " + m);
  });

  await scenario("rejects more than the holder actually holds", async () => {
    await setVal("#assetSendTo", PAYEE);
    await setVal("#assetSendAmt", "999999999");
    const m = await clickForMsg("#btnAssetSend", "#assetSendMsg");
    assert(/more than you hold/i.test(m), "expected an overdraft error, got: " + m);
  });

  await scenario("issue form validates symbol / name / decimals", async () => {
    await setVal("#assetNewSym", "");
    await setVal("#assetNewName", "Whatever");
    let m = await clickForMsg("#btnAssetCreate", "#assetCreateMsg");
    assert(/symbol/i.test(m), "expected a symbol error, got: " + m);
    await setVal("#assetNewSym", "OK");
    await setVal("#assetNewName", "");
    m = await clickForMsg("#btnAssetCreate", "#assetCreateMsg");
    assert(/name/i.test(m), "expected a name error, got: " + m);
  });

  await scenario("the tab is a real route (deep-linkable)", async () => {
    assert((await evl(`location.pathname`)) === "/assets", "tab did not push /assets");
  });

  const shot = await send("Page.captureScreenshot", { format: "png" });
  if (shot.result && shot.result.data) {
    const { writeFileSync } = await import("node:fs");
    writeFileSync("/tmp/assets-tab.png", Buffer.from(shot.result.data, "base64"));
    console.log("screenshot: /tmp/assets-tab.png");
  }

  console.log("page errors:", pageErrors.slice(0, 4));
  if (pageErrors.length) fails++;
  console.log(fails ? fails + " FAILURES" : "ALL PASS");
} catch (e) {
  console.error("HARNESS FAILED:", e.message || e);
  fails++;
} finally {
  chrome.kill();
  process.exit(fails ? 1 : 0);
}
