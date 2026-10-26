// Headless-browser walk of the Stwo shielded pool in the REAL wallet, two users (G6 exit test, doc/stwo-migration.md §9.5).
// Usage: node wallet_shield.mjs <urlA> <seedA> <pubA> <addrA> <urlB> <seedB> <pubB> <addrB>
// A and B are DIFFERENT origins (two nodes), so their wallets keep separate storage, as two people's would.
// A shields 2 NADO, sends 1 NADO privately to B's zaddr and delivers the payment code; B receives it, unshields 0.5 NADO
// to B's own public address and claims it once the quorum settled the exit. Prints JSON lines {step, ok, detail};
// exit 0 iff every step passed. Real DOM, real clicks, real proofs (the Stwo WASM prover in the page), real network.
import { createRequire } from "module";
const require = createRequire("/root/.npm/_npx/7d92d9a2d2ccc630/node_modules/");
const puppeteer = require("puppeteer-core");
const CHROME = "/root/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome";

const [urlA, seedA, pubA, addrA, urlB, seedB, pubB, addrB] = process.argv.slice(2);
const results = [];
const step = (name, ok, detail = "") => { results.push({ step: name, ok: !!ok, detail: String(detail).slice(0, 240) }); console.log(JSON.stringify(results[results.length - 1])); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const errors = [];
const SHOTS = process.env.NADO_WALK_SHOTS || "/tmp";
const T0 = Date.now();
const mark = (what) => console.log(JSON.stringify({ t: Math.round((Date.now() - T0) / 1000), at: what }));
// every browser action runs under its own time limit, so a frozen page names the step it froze in
async function within(label, ms, page, fn) {
  mark(label);
  let timer;
  const limit = new Promise((_, rej) => { timer = setTimeout(() => rej(new Error(`${label}: no answer in ${ms / 1000}s`)), ms); });
  // the page acted on comes to the FRONT: a background tab runs no requestAnimationFrame, which puppeteer's waits poll on
  // (A sat behind B and every wait on A hung — a harness artifact, not the wallet)
  if (page) await page.bringToFront().catch(() => {});
  try { return await Promise.race([fn(), limit]); }
  catch (e) { if (page) await page.screenshot({ path: `${SHOTS}/shield-stuck-${label.replace(/\W+/g, "_")}.png`, fullPage: true }).catch(() => {}); throw e; }
  finally { clearTimeout(timer); }
}

async function openWallet(browser, url, seed, pub, addr, who) {
  const page = await browser.newPage();
  await page.setViewport({ width: 412, height: 915 });
  page.on("pageerror", (e) => { errors.push(`${who}: ${e}`); console.log(JSON.stringify({ who, pageerror: String(e).slice(0, 200) })); });
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) console.log(JSON.stringify({ who, console: m.text().slice(0, 200) })); });
  page.on("response", (res) => { if (res.status() >= 400) console.log(JSON.stringify({ who, http: res.status(), url: res.url().slice(0, 160) })); });
  page.on("dialog", async (d) => { await d.accept(); });
  await page.evaluateOnNewDocument((s, pk, a) => {
    try { if (!localStorage.getItem("nado_miner_wallet")) localStorage.setItem("nado_miner_wallet", JSON.stringify({ privateKey: s, publicKey: pk, address: a })); } catch (e) {}
  }, seed, pub, addr);
  await page.goto(url, { waitUntil: "networkidle2", timeout: 120000 });
  await page.waitForSelector("#walAddr", { visible: true, timeout: 60000 });
  const shown = (await page.$eval("#walAddr", (e) => e.textContent)).trim();
  step(`${who}: the wallet opens on its own account`, shown === addr, `${shown} vs ${addr}`);
  return page;
}
// as a user: the "Rollups" menu, then its "Shield (private)" item
async function openShield(page) {
  await page.evaluate(() => [...document.querySelectorAll(".tabgroup-btn")].find((b) => b.getAttribute("data-i18n") === "tab.rollups").click());
  await page.waitForSelector('[data-tabbtn="shield"]', { timeout: 10000 });
  await page.click('[data-tabbtn="shield"]');
  await page.waitForFunction(() => { const c = document.querySelector("#shieldCard"); return c && !c.classList.contains("hidden") && c.getBoundingClientRect().height > 0; }, { timeout: 30000 });
}
async function confirmAll(page, ms = 20000) {       // accept every confirm the action raises (each money move has one)
  const t0 = Date.now(); let n = 0;
  while (Date.now() - t0 < ms) {
    const open = await page.$(".modal-backdrop:not(.hidden) .modal-ok");
    if (open) { await open.click(); n++; await sleep(800); } else await sleep(500);
  }
  return n;
}
// AS A USER: do `act`, and when the wallet says to try again (a note not yet in the pool — the exec node applies only
// FINALIZED blocks, so a fresh deposit or payment takes about the finality depth to land), wait and do it again
const TRY_AGAIN = /not in the pool yet|try again in a minute|unreachable right now/i;
async function untilDone(page, label, act, done, totalMs, gapMs = 20000) {
  const t0 = Date.now(); let tries = 0;
  while (Date.now() - t0 < totalMs) {
    tries++;
    await page.bringToFront().catch(() => {});
    await page.evaluate(() => { const l = document.querySelector("#log"); if (l) l.dataset.walkMark = String(l.textContent.length); });
    await act();
    const t1 = Date.now();
    while (Date.now() - t1 < gapMs * 3) {
      if (await done()) { mark(`${label}: done after ${tries} attempt(s)`); return true; }
      const fresh = await page.evaluate(() => { const l = document.querySelector("#log"); return l ? l.textContent.slice(Number(l.dataset.walkMark || 0)) : ""; });
      if (TRY_AGAIN.test(fresh)) break;               // the wallet said to try again: do so after a pause
      await sleep(3000);
    }
    await sleep(gapMs);
  }
  return false;
}
const num = (s) => { const m = String(s || "").replace(/,/g, "").match(/[0-9]+(\.[0-9]+)?/); return m ? Number(m[0]) : 0; };
async function waitText(page, sel, pred, ms, label) {
  mark("wait: " + label);
  await page.bringToFront().catch(() => {});
  const t0 = Date.now(); let last = "";
  while (Date.now() - t0 < ms) {
    last = await page.$eval(sel, (e) => e.textContent).catch(() => "");
    if (pred(last)) return last;
    await sleep(4000);
  }
  await page.screenshot({ path: `${SHOTS}/shield-${label}.png`, fullPage: true }).catch(() => {});
  return null;
}
async function l1Balance(url, addr) {
  try { const r = await fetch(url.replace(/\/wallet.*$/, "") + "/get_account?address=" + addr); return r.ok ? BigInt((await r.json()).balance || 0) : 0n; }
  catch (e) { return 0n; }
}

const browser = await puppeteer.launch({ headless: true, executablePath: CHROME, protocolTimeout: 900000,
                                         args: ["--no-sandbox", "--disable-dev-shm-usage"] });
try {
  const A = await openWallet(browser, urlA, seedA, pubA, addrA, "A");
  const B = await openWallet(browser, urlB, seedB, pubB, addrB, "B");
  await within("A opens Shield", 120000, A, () => openShield(A));
  await within("B opens Shield", 120000, B, () => openShield(B));

  // 1. A shields 2 NADO
  await within("A types the deposit", 60000, A, () => A.type("#shieldAmount", "2"));
  await within("A clicks Shield coins", 60000, A, () => A.click("#btnShield"));
  await within("A confirms the deposit", 120000, A, () => confirmAll(A, 15000));
  const balA = await waitText(A, "#shieldBal", (t) => num(t) >= 2, 600000, "A-deposit");
  step("A: the deposit lands in the private balance (2 NADO)", balA !== null, balA);

  // 2. A sends 1 NADO privately to B's zaddr, as B shows it
  const zB = (await within("B reads its zaddr", 120000, B, () => B.$eval("#zaddr", (e) => e.textContent || e.value || ""))).trim();
  step("B: the wallet shows a Stwo zaddr", /^zaddr_/.test(zB), zB.slice(0, 40));
  await within("A fills the private send", 60000, A, async () => { await A.type("#zsendTo", zB); await A.type("#zsendAmount", "1"); });
  mark("A sends privately (retrying while the deposit finalizes)");
  const codeOf = async () => { const t = await A.$eval("#zsendCode", (e) => e.textContent).catch(() => ""); return t && t.trim().length > 20 ? t.trim() : null; };
  await untilDone(A, "A private send", async () => { await A.click("#btnZsend"); await confirmAll(A, 15000); }, codeOf, 1200000);
  const code = await codeOf();
  if (!code) await A.screenshot({ path: `${SHOTS}/shield-A-zsend.png`, fullPage: true }).catch(() => {});
  step("A: the private send is proven in the page and published, and the wallet hands over the payment code", code !== null,
       (code || "").slice(0, 60));

  // 3. B receives with the code
  if (code) {
    await within("B pastes the code", 60000, B, () => B.type("#zrecvCode", code.trim()));
    await untilDone(B, "B receive", async () => { await B.click("#btnZrecv"); await confirmAll(B, 10000); },
                    async () => num(await B.$eval("#shieldBal", (e) => e.textContent).catch(() => "")) >= 1, 1200000);
  }
  const balB = await waitText(B, "#shieldBal", (t) => num(t) >= 1, 60000, "B-receive");
  step("B: the payment shows in B's private balance (1 NADO)", balB !== null, balB);
  const balA2 = await A.$eval("#shieldBal", (e) => e.textContent).catch(() => "");
  step("A: A's private balance is what is left (2 - 1 - the relay fee)", num(balA2) > 0 && num(balA2) < 1, balA2);

  // 4. B unshields 0.5 NADO to B's own public address, then claims it once the exit is settled
  const before = await l1Balance(urlB, addrB);
  await within("B fills the unshield", 60000, B, async () => { await B.type("#unshieldTo", addrB); await B.type("#unshieldAmount", "0.5"); });
  // the unshield is accepted once its proof is published; "no pending withdrawals" until then
  await untilDone(B, "B unshield", async () => { await B.click("#btnUnshield"); await confirmAll(B, 20000); },
                  async () => /0\.5|pending|withdraw/i.test(await B.$eval("#log", (e) => e.textContent.slice(-600)).catch(() => "")) &&
                              num(await B.$eval("#shieldBal", (e) => e.textContent).catch(() => "1")) < 1, 1200000);
  let claimed = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 1200000) {
    await B.bringToFront().catch(() => {});
    await B.click("#btnClaimUnshield").catch(() => {});
    await confirmAll(B, 6000);
    const now = await l1Balance(urlB, addrB);
    if (now > before) { claimed = now - before; break; }
    await sleep(15000);
  }
  if (!claimed) await B.screenshot({ path: `${SHOTS}/shield-B-claim.png`, fullPage: true }).catch(() => {});
  step("B: the unshield is settled by the quorum and claimed to B's public balance", !!claimed, claimed ? `+${claimed} raw` : "not claimed");
  const st = await B.$eval("#shieldStatus", (e) => e.textContent).catch(() => "");
  step("B: the wallet's status line is not an error", !/fail|error|refused/i.test(st), st);
  step("no page errors", errors.length === 0, errors.join(" | "));
} catch (e) {
  step("walk completed", false, e && e.message);
} finally {
  await browser.close();
}
process.exit(results.every((r) => r.ok) ? 0 : 1);
