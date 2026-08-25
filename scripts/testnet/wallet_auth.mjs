// Headless-browser drive of the wallet's Account keys panel against a live node (doc/key-rotation.md).
// Usage: node wallet_auth.mjs <wallet_url> <seed_hex> <payee_address>
// Prints JSON lines {step, ok, detail}; exit 0 iff every step passed. Real DOM, real clicks, real network.
import { createRequire } from "module";
const require = createRequire("/root/.npm/_npx/7d92d9a2d2ccc630/node_modules/");
const puppeteer = require("puppeteer-core");
const CHROME = "/root/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome";

const [url, seed, payee] = process.argv.slice(2);
const results = [];
const step = (name, ok, detail = "") => { results.push({ step: name, ok: !!ok, detail: String(detail).slice(0, 160) }); console.log(JSON.stringify(results[results.length - 1])); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = url.replace(/\/wallet.*$/, "");

async function getAccount(addr) {
  const r = await fetch(`${api}/get_account?address=${addr}`);
  return r.ok ? await r.json() : null;
}
async function waitFor(fn, label, ms = 240000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await fn()) return true; } catch (e) {} await sleep(3000); }
  step(label, false, "timeout"); return false;
}

const browser = await puppeteer.launch({ headless: true, executablePath: CHROME, args: ["--no-sandbox", "--disable-dev-shm-usage"] });
try {
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.log(JSON.stringify({ pageerror: String(e).slice(0, 200) })));
  page.on("dialog", async (d) => { await d.accept(); });
  await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });

  // --- import the seed (64-hex) through the onboarding UI
  await page.waitForSelector("#btnShowImport", { visible: true, timeout: 30000 });
  await page.click("#btnShowImport");
  await page.waitForSelector("#importKey", { visible: true });
  await page.type("#importKey", seed);
  await page.click("#btnImport");
  await page.waitForSelector("#walAddr", { visible: true, timeout: 30000 });
  const addr = (await page.$eval("#walAddr", (e) => e.textContent)).trim();
  step("wallet imported", addr.length === 46, addr);

  // --- Settings tab: the Account keys panel must be present (auth_active on this chain)
  await page.click('[data-tabbtn="settings"]');
  await page.waitForSelector("#authWrap", { visible: true, timeout: 30000 });
  await waitFor(async () => (await page.$eval("#authStatus", (e) => e.textContent)).length > 0, "auth status rendered", 20000);
  step("Account keys panel shown", true, await page.$eval("#authStatus", (e) => e.textContent));

  // --- Protect: phrase shown once, acknowledged, submitted; must land on chain
  await page.click("#btnAuthProtect");
  await page.waitForSelector("#authNewPhrase", { visible: true });
  let phrase = "";
  await waitFor(async () => { phrase = (await page.$eval("#authNewPhrase", (e) => e.textContent)).trim(); return phrase.split(/\s+/).length === 24; }, "phrase generated", 20000);
  step("recovery phrase generated (24 words)", phrase.split(/\s+/).length === 24);
  await page.click("#authPhraseAck");
  await page.click("#btnAuthPhraseGo");
  const landed1 = await waitFor(async () => { const a = await getAccount(addr); return a && a.auth && a.auth.v === 1 && a.auth.keys.length === 2; }, "protect landed");
  step("protect landed on chain (v1, 2 keys)", landed1);
  await waitFor(async () => /Protected/.test(await page.$eval("#authStatus", (e) => e.textContent)), "panel shows Protected", 60000);
  step("panel shows Protected", /Protected/.test(await page.$eval("#authStatus", (e) => e.textContent)));
  const a1 = await getAccount(addr); const hot0 = a1.auth.keys[0];

  // --- Rotate with the recovery phrase: immediate (hot + recovery), signer moves to HD child #1
  await page.click("#btnAuthRotate");
  await page.waitForSelector("#authRecoveryBox", { visible: true });
  await page.type("#authRecoveryPhrase", phrase);
  await page.click("#btnAuthGo");
  const landed2 = await waitFor(async () => { const a = await getAccount(addr); return a && a.auth && a.auth.v === 2 && a.auth.keys[0] !== hot0 && a.auth.keys[1] === a1.auth.keys[1]; }, "rotation landed");
  step("rotation landed (v2, new hot key, same recovery key)", landed2);
  await waitFor(async () => /signing key #1/.test(await page.$eval("#authStatus", (e) => e.textContent)), "panel shows signer #1", 90000);
  step("panel shows signing key #1 and the SAME address", /signing key #1/.test(await page.$eval("#authStatus", (e) => e.textContent)) && (await page.$eval("#walAddr", (e) => e.textContent)).trim() === addr);

  // --- Wrong phrase must be refused client-side (no tx)
  await page.click("#btnAuthRotate");
  await page.waitForSelector("#authRecoveryBox", { visible: true });
  await page.$eval("#authRecoveryPhrase", (e) => { e.value = ""; });
  await page.type("#authRecoveryPhrase", phrase.split(" ").reverse().join(" "));
  await page.click("#btnAuthGo");
  await sleep(4000);
  const a2 = await getAccount(addr);
  step("a wrong recovery phrase changes nothing", a2.auth.v === 2 && !a2.auth_pending);

  // --- Reload: the signer must be re-found from the seed (binding scan), address unchanged.
  // domcontentloaded, not networkidle2 — the wallet polls forever, so "network idle" never arrives.
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
  const reOk = await waitFor(async () => {
    const t = await page.evaluate(() => {
      const el = document.getElementById("walAddr");
      const onboard = document.getElementById("onboard");
      return { addr: el ? el.textContent.trim() : "", onboarding: !!(onboard && !onboard.classList.contains("hidden")) };
    });
    if (t.onboarding) { step("after reload", false, "onboarding shown — wallet was not persisted"); return true; }
    return t.addr === addr;
  }, "address after reload", 60000);
  step("after reload the wallet shows the same address", reOk && (await page.$eval("#walAddr", (e) => e.textContent)).trim() === addr);

  // --- Send with the rotated-in key (the normal Send tab), must land
  const before = Number(((await getAccount(payee)) || {}).balance || 0);
  await page.click('[data-tabbtn="send"]');
  await page.waitForSelector("#sendTo", { visible: true });
  await page.type("#sendTo", payee);
  await page.type("#sendAmount", "0.5");
  await page.click("#btnSend");
  await page.waitForSelector(".modal-ok", { visible: true, timeout: 20000 });
  await page.click(".modal-ok");
  const sent = await waitFor(async () => Number(((await getAccount(payee)) || {}).balance || 0) >= before + 5_000_000_000, "send landed");
  step("send signed by the rotated-in key landed", sent);
} catch (e) {
  step("browser flow", false, e && e.message ? e.message : String(e));
} finally {
  await browser.close();
}
const fails = results.filter((r) => !r.ok).length;
console.log(JSON.stringify({ result: fails ? `${fails} FAILURES` : "PASS" }));
process.exit(fails ? 2 : 0);
