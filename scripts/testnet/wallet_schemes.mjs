// Headless-browser walk of user-selectable signature schemes in the REAL wallet (doc/signature-schemes.md).
// Usage: node wallet_schemes.mjs <wallet_url> <master_seed_hex> <master_pubkey_hex> <master_address> <expected_slh_address> <payee_address> [keys]
// The wallet starts on the given master (localStorage, as a returning user's), then — as a user would — opens
// Account -> "+ Add", picks SLH-DSA-128s in the picker, lands on the new account, and sends from it (the harness funded
// it). With `keys` (the tree's SIG_SCHEME_KEYS_HEIGHT is live from block 1) it goes on, as the same user: a 2-of-2
// multisig of Main (ML-DSA-44) and the SLH-DSA account — proposed and signed by the SLH-DSA account, co-signed and
// submitted from Main — then protects the SLH-DSA account with a recovery phrase of its own scheme, rotates its key with
// that phrase, and sends from the protected account. Prints JSON lines {step, ok, detail}; exit 0 iff every step passed.
// Real DOM, real clicks, real network.
import { createRequire } from "module";
const require = createRequire("/root/.npm/_npx/7d92d9a2d2ccc630/node_modules/");
const puppeteer = require("puppeteer-core");
const CHROME = "/root/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome";

const [url, seed, masterPub, masterAddr, expected, payee, keys] = process.argv.slice(2);
const results = [];
const step = (name, ok, detail = "") => { results.push({ step: name, ok: !!ok, detail: String(detail).slice(0, 200) }); console.log(JSON.stringify(results[results.length - 1])); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = url.replace(/\/wallet.*$/, "");
const errors = [];
async function getAccount(addr) { try { const r = await fetch(`${api}/get_account?address=${addr}`); return r.ok ? await r.json() : null; } catch (e) { return null; } }
async function waitFor(fn, ms = 300000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { const v = await fn(); if (v) return v; } catch (e) {} await sleep(3000); }
  return null;
}
const SLHK = (k) => Array.isArray(k) && k[0] === "slhdsa128s" && k[1].length === 64;

const browser = await puppeteer.launch({ headless: true, executablePath: CHROME, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
let page = null;
try {
  page = await browser.newPage();
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
  // the row LABELLED fee: an address row can contain "fee" in its hex (it did, 2026-11-04 — a random false failure)
  const feeRow = rows.find((r) => /^\s*Network fee/i.test(r)) || "";
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

  if (keys) {
    const tab = async (group, name) => {
      if (group) await page.evaluate((g) => [...document.querySelectorAll(".tabgroup-btn")].find((b) => b.getAttribute("data-i18n") === g).click(), group);
      await page.waitForSelector(`[data-tabbtn="${name}"]`, { visible: true, timeout: 10000 });
      await page.click(`[data-tabbtn="${name}"]`);
    };
    const confirm = async () => { await page.waitForSelector(".modal-ok", { visible: true, timeout: 30000 }); await page.click(".modal-ok"); };
    const send = async (to, amount) => {
      await tab("tab.wallet", "send");
      await page.waitForSelector("#sendTo", { visible: true, timeout: 15000 });
      await page.$eval("#sendTo", (e) => { e.value = ""; }); await page.type("#sendTo", to);
      await page.$eval("#sendAmount", (e) => { e.value = ""; }); await page.type("#sendAmount", amount);
      await page.click("#btnSend");
      // the confirm, or the wallet's reason for not opening one (an invalid recipient, a send still confirming)
      try { await confirm(); }
      catch (e) { throw new Error(`send to ${to.slice(0, 12)}… opened no confirm: ` + await page.$eval("#sendMsg", (m) => m.textContent).catch(() => "?")); }
    };
    const payeeBal = async () => BigInt(((await getAccount(payee)) || {}).balance || 0);

    // ---- MULTISIG: Main (ML-DSA-44) + this SLH-DSA account, 2 of 2 ----
    await tab("tab.govern", "multisig");
    await page.waitForSelector("#msigMembers", { visible: true, timeout: 15000 });
    await page.$eval("#msigMembers", (e) => { e.value = ""; }); await page.type("#msigMembers", masterAddr + "\n" + slh);
    await page.$eval("#msigThreshold", (e) => { e.value = ""; }); await page.type("#msigThreshold", "2");
    await page.click("#btnMsigDerive");
    await page.waitForSelector("#msigDerived", { visible: true, timeout: 15000 });
    const shared = (await page.$eval("#msigAddr", (e) => e.textContent)).trim();
    step("the multisig tab derives the shared address of Main and the SLH-DSA account", shared.length >= 40, shared);
    await send(shared, "3");                                 // fund it from the SLH-DSA account, as a user would
    const funded = await waitFor(async () => BigInt(((await getAccount(shared)) || {}).balance || 0) >= 3n * 10n ** 10n);
    step("the shared account is funded", !!funded, await page.$eval("#sendMsg", (m) => m.textContent).catch(() => ""));
    await tab("tab.govern", "multisig");
    await page.waitForSelector("#msigTo", { visible: true, timeout: 15000 });
    await page.$eval("#msigTo", (e) => { e.value = ""; }); await page.type("#msigTo", payee);
    await page.$eval("#msigAmount", (e) => { e.value = ""; }); await page.type("#msigAmount", "1");
    await page.click("#btnMsigPropose");
    await waitFor(async () => (await page.$eval("#msigBlob", (e) => e.value)).length > 100, 60000);
    const blob = await page.$eval("#msigBlob", (e) => e.value);
    let prop = {}; try { prop = JSON.parse(blob); } catch (e) {}
    step("the SLH-DSA member proposes and signs in its own scheme", (prop.signature || []).length === 1 && prop.signature[0].alg === "slhdsa128s",
         JSON.stringify((prop.signature || []).map((e) => e.alg || "mldsa44")));
    // as the same user on Main: switch, paste the proposal, add the second signature, submit
    await page.select("#accountBar select", "0");
    await page.waitForFunction((m) => document.querySelector("#walAddr").textContent.trim() === m, { timeout: 30000 }, masterAddr);
    await tab("tab.govern", "multisig");
    await page.waitForSelector("#msigBlob", { visible: true, timeout: 15000 });
    await page.$eval("#msigBlob", (e, v) => { e.value = v; e.dispatchEvent(new Event("input", { bubbles: true })); }, blob);
    await page.click("#btnMsigSign"); await confirm();
    await waitFor(async () => { try { return JSON.parse(await page.$eval("#msigBlob", (e) => e.value)).signature.length === 2; } catch (e) { return false; } }, 60000);
    const both = JSON.parse(await page.$eval("#msigBlob", (e) => e.value));
    step("Main co-signs with ML-DSA-44 (its entry names no scheme)", both.signature.length === 2 && !("alg" in both.signature[1]),
         JSON.stringify(both.signature.map((e) => e.alg || "mldsa44")));
    const before = await payeeBal();
    await page.click("#btnMsigSubmit"); await confirm();
    const paid = await waitFor(async () => (await payeeBal()) >= before + 10n ** 10n);
    const mmsg = await page.$eval("#msigMsg", (e) => e.textContent).catch(() => "");
    step("the mixed-scheme multisig transfer lands on chain", !!paid, mmsg);
    await page.select("#accountBar select", "1");
    await page.waitForFunction((m) => document.querySelector("#walAddr").textContent.trim() === m, { timeout: 30000 }, slh);

    // ---- AUTH: the SLH-DSA account protects itself with a recovery phrase of its own scheme, then rotates ----
    await page.click('[data-tabbtn="settings"]');
    await page.waitForSelector("#authWrap", { visible: true, timeout: 30000 });
    await page.waitForSelector("#btnAuthProtect", { visible: true, timeout: 30000 });
    await page.click("#btnAuthProtect");
    await page.waitForSelector("#authNewPhrase", { visible: true, timeout: 15000 });
    let phrase = "";
    await waitFor(async () => { phrase = (await page.$eval("#authNewPhrase", (e) => e.textContent)).trim(); return phrase.split(/\s+/).length === 24; }, 20000);
    step("Protect shows a 24-word recovery phrase", phrase.split(/\s+/).length === 24);
    await page.click("#authPhraseAck");
    await page.click("#btnAuthPhraseGo");
    const prot = await waitFor(async () => { const a = await getAccount(slh); return a && a.auth && a.auth.v === 1 && a.auth.keys.every(SLHK) ? a : null; });
    step("the protect lands: both keys SLH-DSA ([alg, key])", !!prot, prot ? JSON.stringify(prot.auth.keys.map((k) => k[0])) : "not landed");
    await waitFor(async () => /Protected/.test(await page.$eval("#authStatus", (e) => e.textContent)), 60000);
    step("the panel shows Protected", /Protected/.test(await page.$eval("#authStatus", (e) => e.textContent)));
    await page.click("#btnAuthRotate");
    await page.waitForSelector("#authRecoveryBox", { visible: true, timeout: 15000 });
    await page.type("#authRecoveryPhrase", phrase);
    await page.click("#btnAuthGo");
    const rot = await waitFor(async () => { const a = await getAccount(slh); return a && a.auth && a.auth.v === 2 && a.auth.keys.every(SLHK)
      && a.auth.keys[0][1] !== prot.auth.keys[0][1] && a.auth.keys[1][1] === prot.auth.keys[1][1] ? a : null; });
    step("the recovery phrase rotates the key at once (v2, new SLH-DSA hot key, same recovery key)", !!rot);
    await waitFor(async () => /signing key #1/.test(await page.$eval("#authStatus", (e) => e.textContent)), 90000);
    step("the panel shows signing key #1", /signing key #1/.test(await page.$eval("#authStatus", (e) => e.textContent)));
    const before2 = await payeeBal();
    await send(payee, "1");
    const paid2 = await waitFor(async () => (await payeeBal()) >= before2 + 10n ** 10n);
    step("the protected SLH-DSA account sends with its rotated key", !!paid2, await page.$eval("#sendMsg", (e) => e.textContent).catch(() => ""));
  }
  step("no page errors", errors.length === 0, errors.join(" | "));
} catch (e) {
  // what the user would have seen at the failure: a screenshot and which multisig/auth sections were showing
  const shot = (process.env.NADO_WALK_SHOTS || "/tmp") + "/scheme-walk-failure.png";
  if (page) await page.screenshot({ path: shot }).catch(() => {});
  const vis = page ? await page.evaluate(() => ["msigCard", "msigTo", "msigDerived", "authWrap", "sendTo"].map((id) => {
    const el = document.getElementById(id); return id + "=" + (el ? (el.offsetParent !== null ? "shown" : "hidden") : "absent");
  }).join(" ") + " | msigTo chain: " + (() => { let el = document.getElementById("msigTo"), out = [];
    while (el && out.length < 5) { out.push((el.id || el.tagName) + ":" + getComputedStyle(el).display); el = el.parentElement; }
    return out.join("<"); })()).catch(() => "") : "";
  step("walk completed", false, `${e && e.message} | ${vis} | shot=${shot}`);
} finally {
  await browser.close();
}
process.exit(results.every((r) => r.ok) ? 0 : 1);
