/*
 * test_the_dex_board_prices_every_market_in_nado_per_coin_and_charts_indexed_trades.mjs — the DEX page's board
 * ("a DEX price/chart dashboard like Dexscreener", operator 2026-11-07; static/dex.js THE BOARD):
 *   1. every price on the board is NADO per coin: the page's nadoPerTok is EXACTLY the inverse of its own
 *      "1 NADO buys" (midPrice) for any reserves and any decimals, and a spot from the trade index (pn/pt) prices
 *      the same pool to the same number — so the board, the pair header and the trades table agree;
 *   2. with no index history, candles are built from the node's 30-s samples (tokens per NADO, inverted): every
 *      candle's high/low bound its open/close, each opens at the previous close, and the live spot closes the newest;
 *   3. the board reads the index (/exec/dex_stats, /exec/dex_candles, /exec/dex_trades), lists the launch curves
 *      beside the pools, shows the Dexscreener columns (txns, volume, makers, 5M 1H 6H 24H, liquidity, FDV), and the
 *      market card draws candles with timeframes and recent trades for an AMM pool, the line chart for the
 *      cross-chain book; the launch coin card has its chart and trades.
 *
 * Run: node tests/test_the_dex_board_prices_every_market_in_nado_per_coin_and_charts_indexed_trades.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const js = readFileSync(join(ROOT, "static", "dex.js"), "utf8"), html = readFileSync(join(ROOT, "static", "dex.html"), "utf8");
const line = (re) => { const m = js.match(re); if (!m) throw new Error("not found: " + re); return m[0]; };

// 1. the page's own functions, lifted from its source
const src = [line(/^const pScale = .*$/m), line(/^const midPrice = .*$/m), line(/^const pxOf = .*$/m), line(/^const nadoPerTok = .*$/m)].join("\n");
let dec = 8;
const F = new Function("tokDec", src + "; return { pScale, midPrice, pxOf, nadoPerTok };")(() => dec);
let worst = 0, n = 0;
for (const d of [0, 2, 6, 8, 10, 18]) {
  dec = d;
  for (let i = 0; i < 200; i++) {
    const rn = BigInt(1 + Math.floor(Math.random() * 2 ** 31)), rt = BigInt(1 + Math.floor(Math.random() * 2 ** 31));
    const p = { rn, rt, asset: "1" }, a = F.nadoPerTok(p), b = 1 / F.midPrice(p), c = F.pxOf(rn, rt, "1");
    worst = Math.max(worst, Math.abs(a / b - 1), Math.abs(c / a - 1)); n++;
  }
}
ok(worst < 1e-12, `NADO per coin is exactly the inverse of "1 NADO buys", and the index's spot gives the same price (${n} pools, worst ${worst.toExponential(1)})`);

// 2. candles from samples: lift candlesFor and drive it with a synthetic series
{
  const body = js.slice(js.indexOf("function candlesFor("), js.indexOf("const _cBound"));
  const now = Math.floor(Date.now() / 1000), tf = 300, series = [];
  for (let t = now - 6 * 3600; t < now - 60; t += 30) series.push([t * 1000, 2 + Math.sin(t / 900) + (t % 7) / 50]);   // tokens per NADO
  const make = new Function("IX", "ixTf", "pScale", "unitsNado", "priceSeriesAll", body + "; return candlesFor;");
  const candlesFor = make({ candles: {} }, tf, () => 1, (u) => Number(u) / 100, () => series);
  const spot = 0.31;
  const cs = candlesFor(5, "1", spot, 0);
  const inv = series.map((x) => 1 / x[1]);
  ok(cs.length > 60 && cs.every((c) => c[2] >= Math.max(c[1], c[4]) - 1e-12 && c[3] <= Math.min(c[1], c[4]) + 1e-12),
     `${cs.length} candles from the samples; every high/low bounds its open/close`);
  ok(cs.slice(1).every((c, i) => Math.abs(c[1] - cs[i][4]) < 1e-12), "each candle opens at the previous close");
  ok(Math.min(...inv) >= Math.min(...cs.map((c) => c[3])) - 1e-12 && cs.slice(0, -1).every((c) => c[0] % tf === 0),
     "the samples are inverted to NADO per coin, bucketed on the timeframe");
  ok(cs[cs.length - 1][4] === spot, "the live spot closes the newest candle");
  const ix = make({ candles: { "candles:5:300": { rows: [[now - 600, 100, 120, 90, 110, 500, 2, 1], [now - 300, 110, 130, 100, 125, 800, 3, 0]] } } }, tf,
                  () => 10, (u) => Number(u) / 100, () => series)(5, "1", 0, 0);
  ok(ix.length === 2 && ix[1][4] === 12.5 && ix[1][5] === 8 && ix[0][6] === 2, "index candles are scaled to NADO per coin and keep volume (NADO) and buy/sell counts");
}

// 3. wiring
ok(/ixGet\("dex_stats"\)/.test(js) && /`dex_candles\?pid=\$\{pid\}&tf=\$\{q\}/.test(js) && /`dex_trades\?pid=\$\{pid\}&limit=\$\{q\}`/.test(js),
   "the board reads the trade index: stats, candles and trades");
ok(/venue: kind === 1 \? "launch" : "swap"/.test(js) && /Object\.keys\(_m\(lastSto, "ast"\) \|\| \{\}\)/.test(js.slice(js.indexOf("function marketRows("))),
   "the Markets table lists the launch curves beside the pools");
const cols = js.slice(js.indexOf("const MT_COLS = () => ["), js.indexOf("function marketRows("));
ok(["txns", "vol", "makers", "m5", "h1", "h6", "h24", "liq", "fdv", "age"].every((k) => cols.includes(`["${k}"`)), "the Dexscreener columns: age, txns, volume, makers, 5M 1H 6H 24H, liquidity, FDV");
ok(/renderPairBoard\(p\.id, p\.asset, px, p\.kind, \{ tf: "mktTf", svg: "mktChart"/.test(js) && /id="mktTf"/.test(html) && /id="mktTrades"/.test(html)
   && /function boardFor\(amm\)/.test(js) && /boardFor\(false\);/.test(js) && /boardFor\(true\);/.test(js),
   "an AMM pool's card draws candles with timeframes and its trades; the cross-chain book keeps its line chart");
ok(/renderPairBoard\(c\.id, c\.asset, lpSpot\(c\) \? lpPrice\(c\) : 0, c\.kind, \{ tf: "lpTf", svg: "lpChart"/.test(js), "the launch coin card has its chart and trades");
ok(/\$\("mktPrice"\)\.textContent = live \? fmtShort\(px\) \+ " NADO"/.test(js) && /const price = live \? nadoPerTok\(p\) : 0;/.test(js),
   "the pair header and the pool list price in NADO per coin");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
