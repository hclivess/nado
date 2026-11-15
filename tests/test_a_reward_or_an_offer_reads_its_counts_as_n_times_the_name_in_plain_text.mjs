/*
 * test_a_reward_or_an_offer_reads_its_counts_as_n_times_the_name_in_plain_text.mjs — playtest 2026-11-15: handing in
 * the stone errand said "Done: +20 experience. The town pays 1 Berries." Every count in the game reads "n × name" (#179:
 * a number before a noun needs its plural, and "×" needs none), and bagText said "1 Berries". It also escaped the names
 * for HTML while both its uses take plain text — a notice (alertBar's textContent) and the offer line (escaped whole
 * by esc) — so a name with & would have read "&amp;". The page's own bagText runs here.
 * Run: node tests/test_a_reward_or_an_offer_reads_its_counts_as_n_times_the_name_in_plain_text.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const dapp = readFileSync(join(ROOT, "static", "nadodapp.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const line = page.split("\n").find((l) => l.startsWith("const bagText = "));
const bagText = new Function("nameOf", "esc", line + "\nreturn bagText;")((id) => ({ berries: "Berries", stone: "Stone", rope: "Salt & rope" }[id]), () => { throw new Error("escaped"); });
ok(bagText({ berries: 1 }) === "1 × Berries", `a reward of one: "${bagText({ berries: 1 })}", not "1 Berries"`);
ok(bagText({ stone: 6, berries: 2 }) === "6 × Stone, 2 × Berries", "several, each as n × name");
ok(bagText({ rope: 2 }) === "2 × Salt & rope", "plain text: a name with & is not escaped here");
ok(/notify\(T\("qDone", [^\n]*T\("qPaid", "The town pays \{p\}\.", \{ p: bagText\(m\.paid\) \}\)/.test(page) && /el\.textContent = t\.icon \+ msg/.test(dapp), "…the reward goes to a notice, which shows text as text");
ok(/\$\{esc\(T\("offerLine", "\{g\} for \{w\}", \{ g: bagText\(o\.give\), w: bagText\(o\.want\) \}\)\)\}/.test(page), "…and the offer line escapes its whole sentence, once");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
