/*
 * test_an_upright_phones_buttons_do_not_overlap_at_any_width.mjs — measured live 2026-11-16 at 412 × 915 in all 17
 * languages: on an upright phone the Bag button lay over Turn (Turn's right edge 208 px, Bag's left 204; at 360 px wide
 * by 52 px). Narrower than 600 px the left cluster goes up a row, off the right cluster's rows, and the goal line rises
 * with it. Here every round button's box is built from land.html's own rules, with the narrow-screen rules on, at every
 * width from 360 to 600: no two overlap, every one is on the screen, and the goal line is above them all.
 * Run: node tests/test_an_upright_phones_buttons_do_not_overlap_at_any_width.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const S = Number((html.match(/#touchUi button\{position:fixed;z-index:5;width:(\d+)px;height:(\d+)px/) || [])[1]);
const ids = [...html.matchAll(/<button id="(t[A-Z][a-zA-Z]*)"/g)].map((m) => m[1]);
const pos = {};
for (const id of ids) {                               // the wide-screen rule: #tX{left|right:Npx;bottom:Npx}
  const m = html.match(new RegExp(`#${id}\\{(left|right):(\\d+)px;bottom:(\\d+)px\\}`));
  if (m) pos[id] = { side: m[1], x: +m[2], bottom: +m[3] };
}
// the narrow-screen block, to its closing brace (since 2026-11-22 it holds only the goal line: the left cluster sits above
// the right cluster's rows at every width — land.html "FEWER BUTTONS" — so no button moves when the screen narrows)
const n0 = html.indexOf("@media (max-width:600px){body.touch #goal"), narrow = html.slice(n0, html.indexOf("\n  }", n0) + 4);
for (const m of narrow.matchAll(/((?:body\.touch #t[A-Za-z]+,?)+)\{bottom:(\d+)px\}/g)) for (const id of m[1].match(/#t[A-Za-z]+/g)) if (pos[id.slice(1)]) pos[id.slice(1)].bottom = +m[2];
const goal = Number((narrow.match(/body\.touch #goal\{[^}]*bottom:(\d+)px/) || [])[1]);
ok(S === 58 && Object.keys(pos).length >= 14 && goal > 0, `${Object.keys(pos).length} round buttons, ${S} px, read from the page; the goal line at ${goal} px on an upright phone`);
let worst = null, offs = null, under = null;
for (let W = 360; W <= 600; W++) {
  const box = Object.entries(pos).map(([id, p]) => ({ id, l: p.side === "left" ? p.x : W - p.x - S, b: p.bottom }));
  for (let i = 0; i < box.length; i++) for (let j = i + 1; j < box.length; j++) {
    const a = box[i], c = box[j];
    if (a.l < c.l + S && c.l < a.l + S && a.b < c.b + S && c.b < a.b + S) worst ||= `${W} px: ${a.id} over ${c.id}`;
  }
  for (const a of box) { if (a.l < 0 || a.l + S > W) offs ||= `${W} px: ${a.id}`; if (a.b + S > goal) under ||= `${W} px: ${a.id} reaches ${a.b + S}`; }
}
ok(!worst, worst ? `two buttons overlap — ${worst}` : "at every width from 360 to 600 px no two buttons overlap");
ok(!offs, offs ? `a button off the screen — ${offs}` : "…every one is on the screen");
ok(!under, under ? `a button above the goal line — ${under}` : `…and the goal line (${goal} px) is above them all`);
{ // the measured case: the wide-screen rows alone at 412 px put Bag over Turn
  const turn = 150 + S, bag = 412 - 150 - S;
  ok(bag < turn, `(without the narrow rules, at 412 px Bag's left edge ${bag} is inside Turn's right edge ${turn} — the overlap measured live)`);
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
