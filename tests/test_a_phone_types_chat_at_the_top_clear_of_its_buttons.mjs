/*
 * test_a_phone_types_chat_at_the_top_clear_of_its_buttons.mjs — playtest 2026-11-15 on the phone layout: the open chat
 * input sat 150 px up, across the left row of buttons (Chat, Run, Turn at 162 px up) — Chat, which closes it, half under
 * the box — and a phone's own keyboard covers the bottom half while one types. On a touch screen the OPEN console docks
 * at the top, the input first and the newest line under it; closed, it stays where it was. Previewed on the live page
 * before the change: every button clear.
 * Run: node tests/test_a_phone_types_chat_at_the_top_clear_of_its_buttons.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const px = (re) => Number((html.match(re) || [])[1]);
const leftRow = px(/#tChat\{left:18px;bottom:(\d+)px\}/), closedAt = px(/body\.touch #console\{bottom:(\d+)px\}/);
ok(leftRow > 0 && closedAt > 0 && closedAt < leftRow + 58, `the phone's console line sits ${closedAt} px up, inside the button row at ${leftRow}–${leftRow + 58} px — the open input there covered the buttons`);
ok(/body\.touch #console\.open\{top:52px;bottom:auto;display:flex;flex-direction:column-reverse\}/.test(html), "open on a touch screen, it docks at the top (52 px, under the title bar), the input first");
ok(/body\.touch #console\.open #conLog\.show\{flex-direction:column-reverse\}/.test(html), "…the newest line right under the input");
ok(/body\.touch #console\.open #conIn\{margin:0 0 6px\}/.test(html), "…with the gap below the input, not above it");
ok(/<div id="console"><div id="conLog" aria-live="polite"><\/div><input id="conIn"/.test(html), "(the log before the input in the page, as the reversed order assumes)");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
