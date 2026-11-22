/*
 * test_the_dex_range_buttons_line_up_with_the_chart.mjs — operator 2026-11-22, a screenshot of the DEX chart's 1H 1D 1W 1M
 * ALL buttons: "this align is not so great". Every card child takes 16 px side margins (.card>*); a later .rangebtns rule
 * set `margin: 8px 0`, which won, so the button row ran to the card's border — measured 16 px past the chart's right edge
 * at every width (1366, 1100, 820, 390 px). The row keeps the card's 16 px sides, so its last button ends where the chart
 * does (measured equal after, at all four widths).
 * Run: node tests/test_the_dex_range_buttons_line_up_with_the_chart.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const html = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "static", "dex.html"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const css = html.slice(0, html.indexOf("</style>", html.lastIndexOf("<style")) + 8);
ok(/\.card>\*\{margin-left:16px;margin-right:16px\}/.test(css), "every card child takes 16 px side margins");
// every later rule that sets .rangebtns's margin must keep 16 px sides (the last such rule wins over .card>*)
const rules = [...css.matchAll(/(?:^|\n)\s*\.rangebtns\{([^}]*)\}/g)].map((m) => m[1]).filter((r) => /margin:/.test(r));
const last = rules[rules.length - 1] || "", m = last.match(/margin:\s*([^;}]+)/), parts = m ? m[1].trim().split(/\s+/) : [];
ok(parts.length >= 2 && parts[1] === "16px", `the range buttons keep the card's 16 px sides, so they end where the chart does (margin: ${m ? m[1].trim() : "?"})`);
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
