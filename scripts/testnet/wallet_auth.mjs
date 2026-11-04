// Headless-browser drive of the wallet's Account keys panel against a live node (doc/key-rotation.md).
// Usage: node wallet_auth.mjs <wallet_url> <seed_hex> <payee_address>
// Prints JSON lines {step, ok, detail}; exit 0 iff every step passed. Real DOM, real clicks, real network.
import { createRequire } from "module";
const require = createRequire("/root/.npm/_npx/7d92d9a2d2ccc630/node_modules/");
const puppeteer = require("puppeteer-core");
const CHROME = "/root/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome";

const [url, seed, payee, chainId] = process.argv.slice(2);
const results = [];
const step = (name, ok, detail = "") => { results.push({ step: name, ok: !!ok, detail: String(detail).slice(0, 160) }); console.log(JSON.stringify(results[results.length - 1])); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const api = url.replace(/\/wallet.*$/, "");

async function getAccount(addr) {
  const r = await fetch(`${api}/get_account?address=${addr}`);
  return r.ok ? await r.json() : null;
}
// the chain id the NODE's page is built for (its rendered /protocol.js) — what a dApp page served by it would send. A
// testnet's id differs from the Python constant, and the wallet answers a mismatched id "reload", never a signature.
async function pageChain() {
  const js = await (await fetch(`${api}/protocol.js`)).text();
  const m = js.match(/CHAIN_ID\s*=\s*"([^"]+)"/);
  return m ? m[1] : chainId;
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

  // --- import the seed (64-hex) the way a person who already owns a wallet does: the wallet auto-creates one for a
  // newcomer (2026-10-08), so the way in is Settings → "Import an existing wallet", not the old onboarding screen.
  await page.waitForSelector("#walAddr", { visible: true, timeout: 60000 });
  const auto = (await page.$eval("#walAddr", (e) => e.textContent)).trim();
  await page.$eval("#btnImportExisting", (e) => e.click());
  await page.waitForSelector("#importKey", { visible: true, timeout: 20000 });
  await page.type("#importKey", seed);
  await page.$eval("#btnImport", (e) => e.click());
  await sleep(1500);
  if (await page.$(".modal-ok")) { try { await page.$eval(".modal-ok", (e) => e.click()); } catch (e) {} }   // replace the empty auto wallet
  await waitFor(async () => { const a = (await page.$eval("#walAddr", (e) => e.textContent)).trim(); return a && a !== auto; }, "imported address shown", 60000);
  const addr = (await page.$eval("#walAddr", (e) => e.textContent)).trim();
  step("wallet imported", addr.length >= 40 && addr !== auto, addr);

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

  // --- Send with the rotated-in key (the normal Send tab), must land. DOM-level clicks throughout:
  // puppeteer's clickable-point check trips on covered/animated elements, and what we test is the app's
  // handlers, not Chrome's hit-testing.
  const before = Number(((await getAccount(payee)) || {}).balance || 0);
  await page.$eval('[data-tabbtn="send"]', (e) => e.click());
  await page.waitForSelector("#sendTo", { visible: true, timeout: 20000 });
  step("send tab open", true);
  await page.type("#sendTo", payee);
  await page.type("#sendAmount", "0.5");
  await page.$eval("#btnSend", (e) => e.click());
  step("review clicked", true);
  await page.waitForSelector(".modal-ok", { visible: true, timeout: 20000 });
  await page.$eval(".modal-ok", (e) => e.click());
  step("confirm clicked", true);
  const sent = await waitFor(async () => Number(((await getAccount(payee)) || {}).balance || 0) >= before + 5_000_000_000, "send landed");
  step("send signed by the rotated-in key landed", sent);

  // --- a dApp signing request (the NFT page's mint), as a user arrives at it: a FRESH load of the wallet carrying
  // ?exec_sign=, exactly what nadodapp.js _goRedirect navigates to. The wallet used to pick its signer before authSync
  // had found the protected account's HD child, so it signed with the BASE key and every relay refused the mint
  // ("signature by a key that does not authorize this account", 2026-11-03). The answer must be ok=1, and the tx must land.
  const payload = Buffer.from(JSON.stringify({ blob: { op: "asset_create", seed: 4242, name: "auth e2e", sym: "NFT", dec: 0,
    supply: 1, mintable: false, uri: "ipfs://bafkreibg6q77z5g4becu7dwji4valvbjzznjyicmbxvo62rnpnllcrfam4" },
    label: "create NFT", confirm: 1, chain: await pageChain(),
    // ONE APPROVAL, TWO STEPS (nadodapp signBlob opts.then): the royalty `register` rides the mint's confirm. The testnet
    // has no NFT contract, so the call is a no-op on the exec layer — what is proven here is the WALLET: one confirm
    // shows both, signs both with the protected account's signer, and both transactions land on L1.
    then: { op: "call", contract: "0".repeat(32), method: "register", args: [7, "1", 4242, 1000, 0] } })).toString("base64");
  const ret = "https://nft.nadochain.com/";
  let answer = null;
  await page.setRequestInterception(true);
  page.on("request", (r) => {               // the bounce back to the dApp: read its answer, never leave the testnet
    if (r.url().startsWith(ret)) { answer = answer || r.url(); r.abort(); } else r.continue();
  });
  await page.goto(url.replace(/\/wallet.*$/, "/wallet") + "?exec_sign=" + encodeURIComponent(payload) + "&ret=" + encodeURIComponent(ret) + "&app=NFT",
                  { waitUntil: "domcontentloaded", timeout: 60000 });
  // the wallet shows its confirm (confirm: 1) unless it refuses outright — then it answers at once with ok=0
  await waitFor(async () => answer || await page.$(".modal-ok"), "the wallet showed the mint confirm", 60000);
  if (!answer) {
    const shown = await page.evaluate(() => (document.querySelector(".modal") || document.body).innerText);
    step("the one confirm shows the follow-up step", /Then, in the same approval/.test(shown) && /register/.test(shown), shown.slice(0, 400));
    await page.$eval(".modal-ok", (e) => e.click()); step("dApp mint request confirmed", true);
  }
  await waitFor(async () => !!answer, "the wallet answered the dApp", 120000);
  const q = new URL(answer || ret).searchParams;
  step("the wallet answered ok=1 (signed by the protected account's signer)", q.get("ok") === "1", decodeURIComponent(q.get("err") || answer || ""));
  const txid = q.get("txid") || "";
  const landed = !!txid && await waitFor(async () => { const r = await fetch(`${api}/get_transaction?txid=${txid}`); return r.ok && !!(await r.json()); },
                                         "mint landed", 240000);
  step("the mint landed on chain", landed, txid);
  const txid2 = q.get("txid2") || "";
  step("the follow-up was submitted from the same confirm (txid2, no err2)", !!txid2 && !q.get("err2"), answer || "");
  const landedThen = !!txid2 && await waitFor(async () => { const r = await fetch(`${api}/get_transaction?txid=${txid2}`); return r.ok && !!(await r.json()); },
                                           "follow-up landed", 240000);
  step("the follow-up landed on chain", landedThen, txid2);
} catch (e) {
  step("browser flow", false, e && e.message ? e.message : String(e));
} finally {
  await browser.close();
}
const fails = results.filter((r) => !r.ok).length;
console.log(JSON.stringify({ result: fails ? `${fails} FAILURES` : "PASS" }));
process.exit(fails ? 2 : 0);
