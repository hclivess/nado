/*
 * test_a_signed_out_player_is_not_shown_a_bar_of_empty_items.mjs — playtest 2026-11-16: the agent's 7-day sign-in ran
 * out, and the page showed its own hotbar — torch, plates, earth — with a 0 under every one and "Torch · Piece 10 × 10 ×
 * 120 cm" beneath: read as a bag that had been emptied. Signed out, the bar says "Sign in to gather" (as it does for a
 * visitor who never had a bar) and the piece line is empty; the bar itself is kept (`hot`, saved) and comes back with
 * the sign-in, when the bag arrives and the bar is drawn again.
 * Run: node tests/test_a_signed_out_player_is_not_shown_a_bar_of_empty_items.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const hb = page.slice(page.indexOf("function hotbar()"), page.indexOf("\n}\n", page.indexOf("function hotbar()")));
ok(/  if \(!RULES \|\| !hot\.length \|\| !net\.me\) \{/.test(hb), "signed out, the bar takes the empty branch whatever it remembers");
ok(/!net\.me \? T\("signInGather", "Sign in to gather"\)/.test(hb), "…which says \"Sign in to gather\"");
ok(!/hot = \[\]|hot\.length = 0/.test(hb), "…and the remembered bar is not thrown away (it returns with the sign-in)");
ok(/el\.textContent = net\.me && id && RULES && !NATURAL_ITEMS\.has\(id\) \? T\("pieceInfo",/.test(page), "the piece line under the bar is empty while signed out");
ok(/if \(!net\.me\) \{ inv\.items = \{\}; inv\.tools = \[\]; inv\.stations = \[\]; hotbar\(\); \}/.test(page), "(a sign-out empties the page's copy of the bag and redraws the bar)");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
