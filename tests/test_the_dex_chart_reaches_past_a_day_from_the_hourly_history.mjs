/*
 * test_the_dex_chart_reaches_past_a_day_from_the_hourly_history.mjs — #185 (operator 2026-11-11: "can you add at least
 * some market history? last 24 hours is kinda weak right now"). Measured on the live page: the node's samples are capped
 * at 2,880 a market, so ETH's chart ended 24 hours back whichever range was pressed. The node now keeps hourly candles
 * for the life of the chain (ops/dex_prices.py, tests/test_dex_prices_in_node.py); here, the page's half:
 *   1. a range that reaches behind the oldest sample is drawn from the hourly history — 1W, the new 1M and ALL reach
 *      as far as the history does, each hour at its closing price, and with no history the old 24-hour wall is back;
 *   2. 1H and 1D are the samples alone, and no hour is drawn twice where the samples take over;
 *   3. an AMM pool's history is scaled to the token's decimals exactly like its samples;
 *   4. the page says where the record starts (in 17 languages), and it is the oldest hour or the oldest sample;
 *   5. the drawn path is bounded however long the history grows, and thinning keeps both ends and every extreme;
 *   6. the history is its own file asked for every ten minutes (again within a minute after a miss), not at every
 *      refresh, and the range buttons carry 1M.
 *
 * Run: node tests/test_the_dex_chart_reaches_past_a_day_from_the_hourly_history.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const js = readFileSync(join(ROOT, "static", "dex.js"), "utf8"), html = readFileSync(join(ROOT, "static", "dex.html"), "utf8");
const cut = (a, b) => { const i = js.indexOf(a), j = js.indexOf(b, i); if (i < 0 || j < 0) throw new Error("not found: " + a + " … " + b); return js.slice(i, j); };

// the page's own functions, lifted from its source and run against a state this test owns
const NOW = 1_800_000_000_000 + 1234567, H = 3600;
const env = { lastSto: null, sharedPrices: {}, sharedHistory: { tf: H, pools: {} }, mktRange: 3600, local: {},
  priceStore: () => env.local, pScale: () => 100, poolOf: () => ({ asset: "7" }), Date: { now: () => NOW } };
const P = new Function("env", "with (env) {" + cut("const unitScale = ", "function stats24(") +
  "; return { priceSeriesAll, priceHistory, seriesStart, priceSeries, thinSeries }; }")(env);

const nowS = Math.floor(NOW / 1000), hour = nowS - nowS % H;
const samples = [], candles = [];
for (let i = 2879; i >= 0; i--) samples.push([nowS - i * 30, 40 + (i % 13) / 10]);            // a day of 30-second samples
for (let h = hour - 30 * 24 * H; h < hour; h += H) candles.push([h, 30, 33, 29, 31 + (h / H) % 5, 0.5]);   // thirty days of hours
env.sharedPrices = { "x:eth": samples };
const days = (s) => (NOW - s[0][0]) / 86400000;

// 1. the wall, then the history behind it
env.mktRange = 604800;
ok(Math.abs(days(P.priceSeries("x:eth")) - 1) < 0.01, "with no history a week's range ends a day back — the samples' cap (the defect measured live)");
env.sharedHistory = { tf: H, pools: { "x:eth": candles } };
let wk = P.priceSeries("x:eth");
ok(days(wk) > 6.95 && days(wk) <= 7, `1W reaches a week back from the hourly history (${days(wk).toFixed(2)} days)`);
env.mktRange = 2592000;
const mo = P.priceSeries("x:eth");
ok(days(mo) > 29.9 && days(mo) <= 30, `1M reaches as far as the history does (${days(mo).toFixed(2)} days)`);
env.mktRange = 0;
const all = P.priceSeries("x:eth");
ok(all[0][0] === (candles[0][0] + H) * 1000 && all[0][1] === candles[0][4], "ALL starts at the oldest hour, drawn at its end with its closing price");
ok(all.every((p, i) => !i || p[0] > all[i - 1][0]), "the series only goes forward in time");

// 2. the short ranges are the samples; the samples take over where they begin
const fine = new Set(samples.map((x) => x[0] * 1000)), first = samples[0][0] * 1000;
env.mktRange = 3600;
const h1 = P.priceSeries("x:eth");
ok(h1.length === 120 && h1.every((p) => fine.has(p[0])), "1H is the last hour of samples, nothing else");
env.mktRange = 86400;
ok(P.priceSeries("x:eth").every((p) => fine.has(p[0])), "1D is the samples alone");
ok(all.filter((p) => !fine.has(p[0])).every((p) => p[0] < first) && all.filter((p) => fine.has(p[0])).length === samples.length,
   "no hour of the history is drawn at or after the first sample: nothing is drawn twice");

// 3. an AMM pool: its history is scaled like its samples
env.lastSto = {}; env.mktRange = 0;
env.sharedPrices["5"] = [[nowS - 60, 2]]; env.sharedHistory.pools["5"] = [[hour - 5 * H, 1, 3, 1, 3, 0]];
ok(JSON.stringify(P.priceSeries("5").map((p) => p[1])) === "[300,200]", "a pool's history is scaled to the token's decimals exactly like its samples");
env.lastSto = null;

// 4. where the record starts
ok(P.seriesStart("x:eth") === candles[0][0] * 1000, "the record starts at the oldest hour of the history");
env.sharedPrices["x:sol"] = [[nowS - 500, 1]];
ok(P.seriesStart("x:sol") === (nowS - 500) * 1000 && P.seriesStart("x:none") === 0, "…or at the oldest sample when there is no hour yet; a market with no record has no start");
ok(/LT\("capFrom", "[^"]*\{ago\}[^"]*", \{ ago: fmtAgo\(since\) \}\)/.test(js) && /const since = seriesStart\(XKEY\(xsel\)\)/.test(js),
   "the cross-chain card says where the price record starts");
const tr = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "dex.json"), "utf8"));
const langs = Object.keys(tr);
ok(langs.length === 17 && langs.every((l) => (tr[l]["dex.capFrom"] || "").includes("{ago}")), "…in all 17 languages, each keeping {ago}");

// 5. the drawn path is bounded
const long = [];
for (let i = 0; i < 90000; i++) long.push([i * 3600000, 50 + Math.sin(i / 700) * 5]);            // ten years of hours
long[40123] = [40123 * 3600000, 999]; long[70001] = [70001 * 3600000, 0.001];                 // one spike up, one down
const thin = P.thinSeries(long);
ok(thin.length <= 802, `ten years of hours draw through ${thin.length} points`);
ok(thin[0] === long[0] && thin[thin.length - 1] === long[long.length - 1], "both ends are kept (the change's sign is the line's colour)");
ok(thin.includes(long[40123]) && thin.includes(long[70001]), "a single spike up and a single spike down both survive");
ok(thin.every((p, i) => !i || p[0] > thin[i - 1][0]) && thin.every((p) => long[p[0] / 3600000] === p), "thinning only drops points: what is left is the data, in order");
ok(P.thinSeries(samples) !== samples && P.thinSeries(samples.slice(0, 800)).length === 800 && P.thinSeries(long.slice(0, 5)).length === 5, "a short series is drawn whole");
ok(/const data = thinSeries\(priceSeries\(key\)\);/.test(js), "the chart draws the thinned series");

// 6. its own file, every ten minutes
{
  let clock = NOW, calls = 0, fail = false;
  const st = { Date: { now: () => clock }, fetch: async (url, o) => { calls++; st.url = url; st.opt = o; if (fail) throw new Error("404");
    return { json: async () => ({ tf: H, pools: { k: [[1, 2, 3, 4, 5, 6]] } }) }; } };
  const R = new Function("st", "with (st) {" + cut("let sharedHistory = ", "let mktRange = ") + "; return { refreshSharedHistory, get: () => sharedHistory }; }")(st);
  await R.refreshSharedHistory(); await R.refreshSharedHistory();
  clock += 9 * 60000; await R.refreshSharedHistory();
  ok(calls === 1 && st.url === "/static/market/history.json" && R.get().pools.k.length === 1, "the history is its own file, fetched once — not at every 3-second refresh");
  clock += 61000; await R.refreshSharedHistory();
  ok(calls === 2, "…and again ten minutes later");
  fail = true; clock += 601000; await R.refreshSharedHistory();
  const before = calls; clock += 30000; await R.refreshSharedHistory(); clock += 31000; await R.refreshSharedHistory();
  ok(before === 3 && calls === 4 && R.get().pools.k.length === 1, "a miss keeps what was loaded and is asked again within a minute, not hammered");
}
ok(/await refreshSharedPrices\(\);\s*await refreshSharedHistory\(\);/.test(js), "the page's refresh asks for it");
ok(!/history\.json/.test(cut("async function refreshSharedPrices()", "// THE LONG HISTORY")), "prices.json's fetch stays what it was");
const ranges = [...html.slice(html.indexOf('id="mktRanges"'), html.indexOf('id="mktTf"')).matchAll(/data-range="(\d+)"[^>]*>([^<]+)</g)].map((m) => m[1] + ":" + m[2]);
ok(ranges.join(" ") === "3600:1H 86400:1D 604800:1W 2592000:1M 0:ALL", "the range buttons are 1H 1D 1W 1M ALL");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
