// Headless-browser walk of user-selectable signature schemes in the REAL wallet (doc/signature-schemes.md).
// Usage: node wallet_schemes.mjs <wallet_url> <master_seed_hex> <master_pubkey_hex> <master_address> <expected_slh_address> <payee_address>
// The wallet starts on the given master (localStorage, as a returning user's), then — as a user would — opens
// Account -> "+ Add", picks SLH-DSA-128s in the picker, lands on the new account, and sends from it (the harness funded
// it). Prints JSON lines {step, ok, detail}; exit 0 iff every step passed. Real DOM, real clicks, real network.
import { createRequire } from "module";
const require = createRequire("/root/.npm/_npx/7d92d9a2d2ccc630/node_modules/");
const puppeteer = require("puppeteer-core");
const CHROME = "/root/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome";

const [url, seed, masterPub, masterAddr, expected, payee] = process.argv.slice(2);
const results = [];
const step = (name, ok, detail = "") => { results.push({ step: name, ok: !!ok, detail: String(detail).slice(0, 200) }); console.log(JSON.stringify(results[results.length - 1])); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = url.replace(/\/wallet.*$/, "");
const errors = [];

const browser = await puppeteer.launch({ headless: true, executablePath: CHROME, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 412, height: 915 });
  page.on("pageerror", (e) => { errors.push(String(e)); console.log(JSON.stringify({ pageerror: String(e).slice(0, 200) })); });
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) console.log(JSON.stringify({ console: m.type(), text: m.text().slice(0, 240) })); });
  // a returning user: the master seed is already on this device (the wallet persists exactly this shape)
  await page.evaluateOnNewDocument((s, pk, a) => {
    try { if (!localStorage.getItem("nado_miner_wallet")) localStorage.setItem("nado_miner_wallet", JSON.stringify({ privateKey: s, publicKey: pk, address: a })); } catch (e) {}
  }, seed, masterPub, masterAddr);
  await page.goto(url, { waitUntil: "networkidle2", timeout: 90000 });
  await page.waitForSelector("#walAddr", { visible: true, timeout: 60000 });
  const main = (await page.$eval("#walAddr", (e) => e.textContent)).trim();
  step("the wallet opens on the master (Main, ML-DSA-44)", main === masterAddr, `${main} vs ${masterAddr}`);

  // Account -> "+ Add" opens the scheme picker once the gate is live (gen 29: from block 1)
  // "+ Add" is the bar's button labelled Add (the account <select> renders its own dropdown button beside it)
  await page.waitForFunction(() => [...document.querySelectorAll("#accountBar button")].some((b) => /Add/.test(b.textContent)), { timeout: 30000 });
  await sleep(1500);                                  // the bar re-renders once its labels are translated; click the settled one
  await page.evaluate(() => [...document.querySelectorAll("#accountBar button")].find((b) => /Add/.test(b.textContent)).click());
  try { await page.waitForSelector(".modal-choices", { visible: true, timeout: 15000 }); }
  catch (e) {
    const shot = (process.env.NADO_WALK_SHOTS || "/tmp") + "/scheme-add-no-picker.png";
    await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
    const bar = await page.$eval("#accountBar", (b) => b.outerHTML.slice(0, 600)).catch(() => "");
    const modal = await page.$eval(".modal-backdrop", (m) => m.className + " " + m.textContent.slice(0, 300)).catch(() => "no modal");
    step("+ Add opens the scheme picker", false, `bar=${bar} | modal=${modal} | shot=${shot}`);
    throw e;
  }
  const labels = await page.$$eval(".modal-choices label", (ls) => ls.map((l) => l.textContent));
  step("+ Add offers the schemes, the default first", labels.length === 4 && /ML-DSA-44/.test(labels[0]) && labels.some((l) => /SLH-DSA/.test(l)), labels.join(" | "));
  const checked0 = await page.$eval(".modal-choices input:checked", (i) => i.value);
  step("...with ML-DSA-44 preselected", checked0 === "mldsa44", checked0);
  await page.click('.modal-choices input[value="slhdsa128s"]');
  await page.click(".modal-ok");
  await page.waitForFunction((m) => { const a = document.querySelector("#walAddr"); return a && a.textContent.trim() && a.textContent.trim() !== m; }, { timeout: 30000 }, main);
  const slh = (await page.$eval("#walAddr", (e) => e.textContent)).trim();
  step("the new account is the SLH-DSA address the node derives for this seed", slh === expected, `${slh} vs ${expected}`);
  const label = await page.$eval("#accountBar select", (s) => s.options[s.selectedIndex].textContent);
  step("the account bar names its scheme", /SLH-DSA/.test(label), label);

  // the harness funded the SLH-DSA address; wait until the wallet shows it
  const t0 = Date.now();
  let bal = "";
  while (Date.now() - t0 < 240000) {
    bal = await page.$eval("#walBalance", (e) => e.textContent).catch(() => "");
    if (/[1-9]/.test(bal)) break;
    await sleep(3000);
  }
  step("the funded balance shows", /[1-9]/.test(bal), bal);

  // Send tab: the fee shown is the scheme's (3 x MIN_TX_FEE), then the transfer lands
  // as a user: open the "Wallet" menu, then its Send item (the tab bar groups tabs into menus)
  await page.evaluate(() => [...document.querySelectorAll(".tabgroup-btn")].find((b) => b.getAttribute("data-i18n") === "tab.wallet").click());
  await page.waitForSelector('[data-tabbtn="send"]', { visible: true, timeout: 10000 });
  await page.click('[data-tabbtn="send"]');
  await page.waitForSelector("#sendTo", { visible: true, timeout: 15000 });
  await page.type("#sendTo", payee);
  await page.type("#sendAmount", "1");
  await page.click("#btnSend");
  await page.waitForSelector(".modal-rows .modal-row", { visible: true, timeout: 30000 });
  const rows = await page.$$eval(".modal-rows .modal-row", (rs) => rs.map((r) => r.textContent));
  const feeRow = rows.find((r) => /fee/i.test(r)) || "";
  step("the confirm dialog shows the SLH-DSA fee (0.0000003 NADO)", /0\.0000003/.test(feeRow), feeRow);
  await page.click(".modal-ok");
  const t1 = Date.now();
  let landed = null;
  while (Date.now() - t1 < 300000) {
    try {
      const r = await fetch(`${api}/get_account?address=${payee}`);
      if (r.ok) { const a = await r.json(); if (BigInt(a.balance || 0) >= 10n ** 10n) { landed = a; break; } }
    } catch (e) {}
    await sleep(4000);
  }
  step("the transfer from the SLH-DSA account lands on chain", !!landed, landed ? landed.balance : "not landed");
  const msg = await page.$eval("#sendMsg", (e) => e.textContent).catch(() => "");
  step("...and the wallet says so", !/fail|error|invalid/i.test(msg), msg);
  step("no page errors", errors.length === 0, errors.join(" | "));
} catch (e) {
  step("walk completed", false, e && e.message);
} finally {
  await browser.close();
}
process.exit(results.every((r) => r.ok) ? 0 : 1);
