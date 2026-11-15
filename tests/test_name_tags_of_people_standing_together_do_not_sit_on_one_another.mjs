/*
 * test_name_tags_of_people_standing_together_do_not_sit_on_one_another.mjs — playtest 2026-11-15: Maren's and Ida's
 * name tags, two people side by side by the town hall, were drawn over each other into one unreadable word. land.js
 * platesFrame measures every shown tag's box on screen and declutterPlates lifts the crowded ones: the nearest tag never
 * moves; a farther one that would overlap a tag already placed rises just clear of it (not whole heights), at most
 * PLATE_LIFT steps; tags that do not touch stay where they hang. The page's own function runs here.
 * Run: node tests/test_name_tags_of_people_standing_together_do_not_sit_on_one_another.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const i0 = page.indexOf("const PLATE_LIFT = "), src = page.slice(i0, page.indexOf("const _pv = ", i0));
const declutter = new Function(src + "\nreturn declutterPlates;")();
const tag = (d, x, y, w = 0.2, h = 0.05) => ({ d, x0: x - w / 2, x1: x + w / 2, y0: y, y1: y + h, step: h });

// Maren and Ida by the hall: 6 m and 6.5 m off, their tags 0.005 apart in height on screen
const clear = (items, lift) => items.every((a, i) => items.every((b, j) => i === j || !(a.x0 < b.x1 && b.x0 < a.x1 && a.y0 + lift[i] * a.step < b.y1 + lift[j] * b.step && b.y0 + lift[j] * b.step < a.y1 + lift[i] * a.step)));
{ const it = [tag(6, 0, 0.3), tag(6.5, 0.05, 0.305)], L = declutter(it);
  ok(L[0] === 0 && clear(it, L) && L[1] > 0.85 && L[1] < 0.95, `two tags drawn over each other: the nearer stays, the farther rises just clear of it (${L[1].toFixed(2)} of its height, not a whole one)`); }
{ const it = [tag(6.5, 0.05, 0.305), tag(6, 0, 0.3)], L = declutter(it);
  ok(L[1] === 0 && L[0] > 0 && clear(it, L), "…whichever order they come in: it is the farther that moves"); }
ok(declutter([tag(6, -0.3, 0.3), tag(7, 0.3, 0.3)]).join() === "0,0", "tags apart on screen stay where they hang");
ok(declutter([tag(6, 0, 0.3), tag(7, 0, 0.38)]).join() === "0,0", "…and so does one already clear above another");
{ const it = [tag(5, 0, 0.3), tag(6, 0.02, 0.3), tag(7, -0.02, 0.3)], L = declutter(it);
  ok(L[0] === 0 && L[1] > 0.95 && L[2] > L[1] && clear(it, L), "three people together: their tags stack, nearest lowest, each clear"); }
{ // a tag behind someone carrying a quest mark (its box twice as tall): it rises just past the mark, not three heights
  const marked = { d: 6, x0: -0.1, x1: 0.1, y0: 0.3, y1: 0.3 + 0.1075, step: 0.05 }, it = [marked, tag(8, 0.02, 0.3)], L = declutter(it);
  ok(clear(it, L) && L[1] < 2.3, `…behind a person with a quest mark it clears the mark and stops there (${L[1].toFixed(2)} heights)`); }
ok(declutter([1, 2, 3, 4, 5, 6].map((d) => tag(d, 0, 0.3))).every((L) => L <= 3) && declutter([1, 2, 3, 4, 5, 6].map((d) => tag(d, 0, 0.3)))[5] === 3,
  "a crowd lifts its tags at most PLATE_LIFT heights — kept near their people, not stacked into the sky");
// the page measures and applies it
ok(/sp\.userData\.textW = Math\.min\(1, \(tw \+ 10\) \/ 256\);/.test(page), "a tag knows how much of its width its words take (a short name's empty canvas does not crowd its neighbour)");
ok(/for \(const r of npcs\.values\(\)\) add\(r\.mesh\);\n  for \(const r of others\.values\(\)\) if \(r\.p && r\.mesh\) add\(r\.mesh\);/.test(page) && /name\.center\.y = -L;/.test(page) && /mark\.center\.y = -1\.15 - L \* name\.scale\.y \/ mark\.scale\.y;/.test(page),
  "townspeople's and other players' tags are measured and lifted, a quest mark going up with its name");
ok(/r\.mark\.userData\.mark = true; r\.mark\.userData\.textW = 0;/.test(page), "…and a quest mark is never taken for the name itself");
ok(page.indexOf("platesFrame();") > page.indexOf("for (const r of others.values()) {\n    if (!r.p) continue;"), "the pass runs after every tag of the frame is sized");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
