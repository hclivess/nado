/*
 * test_a_cross_chain_market_lists_its_settled_swaps.mjs — the DEX's ETH and BTC markets (operator 2026-11-22: "there is no
 * trade history"): the trades table was the AMM pools' alone, so a settled cross-chain swap showed nowhere but as a price
 * on the chart. The real xTrades / renderXTrades, lifted from static/dex.js and run against stub orders:
 *   1. a trade is an order the swap contract holds SETTLED in this market — open, taken, refunded and cancelled ones are
 *      not, another market's are not, an intra-chain token order is not — newest first, at most 40;
 *   2. each row: when it filled, who bought (the taker of an ask bought NADO; of a bid, sold it), the price in NADO per
 *      coin as the book shows it, both amounts, the taker;
 *   3. a market with none says so; the market card shows the table in the cross-chain view and fills it there.
 * Run: node tests/test_a_cross_chain_market_lists_its_settled_swaps.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const SRC = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "dex.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = SRC.indexOf("function xTrades(key) {"), b = SRC.indexOf("function renderXMarket() {");
ok(a > 0 && b > a, "dex.js carries xTrades and renderXTrades before the cross-chain market");
const OD = (o, st, kind, key, fillh, namt, wamt, taker) => ({ o, st, kind, key, fillh, namtRaw: BigInt(namt) * 10n ** 10n, wamt, taker });
const orders = [OD(1, 3, 1, "eth", 100, 10, "0.0067", "t1"), OD(2, 3, 2, "eth", 300, 5, "0.004", "t2"), OD(3, 1, 1, "eth", 0, 50, "0.0335", ""),
  OD(4, 4, 1, "eth", 50, 1, "0.001", "t4"), OD(5, 5, 1, "eth", 0, 1, "0.001", ""), OD(6, 3, 1, "btc", 200, 10, "0.00014", "t6"), OD(7, 3, 3, "eth", 250, 1, "1", "t7")];
const box = { innerHTML: "" };
const env = {
  otcOrders: () => orders, mktKeyOf: (od) => od.key, OTC_ASK: 1, OTC_INTRA: 3, $: () => box, dapp: { cursor: 400 },
  esc: (x) => String(x), LT: (k, en) => en, fmtAgo: (t) => Math.round((Date.now() - t) / 1000) + "s ago",
  fmtPrice: (x) => x.toFixed(2), otcPrice: (od) => Number(od.namtRaw / 10n ** 10n) / Number(od.wamt),
  rawToNado: (r) => String(BigInt(r) / 10n ** 10n), shortAddr: (x) => x || "—",
};
const lib = new Function(...Object.keys(env), SRC.slice(a, b) + "; return { xTrades, renderXTrades };")(...Object.values(env));
const t = lib.xTrades("eth");
ok(t.map((x) => x.o).join() === "2,1", `only this market's settled swaps, newest first: ${t.map((x) => "#" + x.o).join(", ")} (open, refunded, cancelled, BTC and intra-chain left out)`);
lib.renderXTrades("mktTrades", "eth", "ETH");
const rows = box.innerHTML.split("<tr>").slice(2);
ok(rows.length === 2 && /class="dn">Sell/.test(rows[0]) && /class="up">Buy/.test(rows[1]), "the taker of a bid sold NADO, of an ask bought it");
ok(/<td>1250\.00<\/td><td>5<\/td><td>0\.004<\/td>/.test(rows[0]) && /<td>1492\.54<\/td><td>10<\/td><td>0\.0067<\/td>/.test(rows[1]),
  "each row: the price in NADO per coin as the book shows it (10 NADO for 0.0067 ETH = 1,492.54), then both amounts");
ok(/600s ago/.test(rows[0]) && /1800s ago/.test(rows[1]) && /t2/.test(rows[0]), "…when it filled (its fill height at ~6 s a block) and its taker");
box.innerHTML = ""; orders.length = 0; lib.renderXTrades("mktTrades", "eth", "ETH");
ok(/No swap has settled in this market yet\./.test(box.innerHTML), "a market with none says so");
ok(SRC.includes("await otcRefresh();\n    // the chain's height for a visitor too") && SRC.includes("await dapp._cursor().catch(() => {});"),
  "a signed-out visitor's page learns the chain's height too, so each swap's \"when\" has something to measure from");
ok(SRC.includes('show("mktTradesWrap", true);') && SRC.includes('renderXTrades("mktTrades", xsel, net.coin);'), "the market card shows the table in the cross-chain view and fills it there");
const L = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "i18n_games", "dex.json"), "utf8"));
ok(Object.keys(L).length === 17 && Object.values(L).every((x) => x["dex.tNoneX"] && x["dex.tTaker"]), "its two new words are in all 17 languages");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
