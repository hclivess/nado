// Headless-browser smoke of the dex dApp's Cross-chain mode against the LIVE site.
// Usage: node scripts/testnet/otc_ui_smoke.mjs [url]     (exit 0 iff every step passed)
import { createRequire } from "module";
const require = createRequire("/root/.npm/_npx/7d92d9a2d2ccc630/node_modules/");
const puppeteer = require("puppeteer-core");
const CHROME = "/root/.cache/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome";
const url = process.argv[2] || "https://dex.nadochain.com/";
const results = []; const errs = [];
const step = (n, ok, d = "") => { results.push({ step: n, ok: !!ok, detail: String(d).slice(0, 140) }); console.log(JSON.stringify(results.at(-1))); };
const browser = await puppeteer.launch({ headless: true, executablePath: CHROME, args: ["--no-sandbox", "--disable-dev-shm-usage", "--ignore-certificate-errors"] });
try {
  const page = await browser.newPage();
  page.on("pageerror", (e) => errs.push(String(e).slice(0, 200)));
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForSelector("#modeBar", { timeout: 30000 });
  step("page + mode bar load", true);
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll("#modeBar button, #modeBar [role=button], #modeBar *")].find((e) => /Cross-chain/i.test(e.textContent) && e.click);
    if (b) { b.click(); return true; } return false;
  });
  step("Cross-chain mode button found + clicked", clicked);
  await new Promise((r) => setTimeout(r, 2500));
  const vis = await page.evaluate(() => ({
    book: !!document.getElementById("otcBookCard") && !document.getElementById("otcBookCard").classList.contains("hidden"),
    post: !!document.getElementById("otcPostCard") && !document.getElementById("otcPostCard").classList.contains("hidden"),
    my: !!document.getElementById("otcMyCard") && !document.getElementById("otcMyCard").classList.contains("hidden"),
    swapHidden: document.getElementById("swapCard").classList.contains("hidden") || document.getElementById("poolsCard").classList.contains("hidden"),
    bookText: (document.getElementById("otcBook") || {}).textContent || "",
  }));
  step("book/post/my cards shown", vis.book && vis.post && vis.my, JSON.stringify(vis).slice(0, 120));
  step("AMM cards hidden in cross-chain mode", vis.swapHidden);
  step("book rendered (orders or empty-state)", /#\d+|No open orders/.test(vis.bookText), vis.bookText.slice(0, 100));
  step("no page errors", errs.length === 0, errs.join(" | "));
} catch (e) {
  step("browser flow", false, e.message || String(e));
} finally { await browser.close(); }
const fails = results.filter((r) => !r.ok).length;
console.log(JSON.stringify({ result: fails ? fails + " FAILURES" : "PASS" }));
process.exit(fails ? 2 : 0);
