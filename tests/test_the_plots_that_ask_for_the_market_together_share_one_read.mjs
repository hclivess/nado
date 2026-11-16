/*
 * test_the_plots_that_ask_for_the_market_together_share_one_read.mjs — #150, measured 2026-11-16 on a fresh phone load
 * of land.nadochain.com: 41 reads of the same market contract (/exec/contract), 670 KB — every for-sale plot round the
 * player asked whether it was listed at the same moment, before the first answer reached the minute's cache, and each
 * fetched the whole contract. land.js listingsOf keeps the read in flight and shares it; a failed read is forgotten so
 * the next ask tries again. The page's listingsOf runs here against a counted fetch.
 * Run: node tests/test_the_plots_that_ask_for_the_market_together_share_one_read.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = page.indexOf("const listingCache = new Map();"), b = page.indexOf("\n}\n", page.indexOf("function listingsOf(cid) {")) + 2;
const src = page.slice(a, b);
const make = (fetch) => new Function("fetch", "base", "exactSeeds", src + "\nreturn { listingsOf, listingCache };")(fetch, () => "", (t) => JSON.parse(t));
let n = 0, fail = false, release;
const gate = () => new Promise((r) => { release = r; });
const fetch = async () => { n++; if (fail) throw new Error("offline"); await gate(); return { text: async () => JSON.stringify({ storage: { l_asset: { 1: "7" } } }) }; };
const M = make(fetch);
const asks = Array.from({ length: 41 }, () => M.listingsOf("b0162eda"));
await new Promise((r) => setTimeout(r, 0)); release();
const got = await Promise.all(asks);
ok(n === 1, `41 plots asking at once: ${n} read of the market (was 41, 670 KB on a phone's first load)`);
ok(got.every((st) => st.l_asset["1"] === "7"), "…and every one of them gets its answer");
await M.listingsOf("b0162eda");
ok(n === 1, "asked again within the minute: from the cache, no read");
M.listingCache.clear(); fail = true;
let threw = false; try { await M.listingsOf("b0162eda"); } catch (e) { threw = true; }
ok(threw && !M.listingCache.has("b0162eda"), "a failed read is not kept (the next ask reads again)");
fail = false; const before = n; const p2 = M.listingsOf("b0162eda"); await new Promise((r) => setTimeout(r, 0)); release(); await p2;
ok(n === before + 1, "…and the next ask does read again");
ok(/listingCache\.clear\(\);/.test(page), "a sale call that returns still clears the cache (the market is read afresh)");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
