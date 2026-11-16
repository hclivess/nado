/*
 * test_the_town_hall_shows_on_the_map_when_you_stand_at_it.mjs — playtest 2026-11-16, the town agent's phone page in
 * the square: the map's key says "town hall", and the map showed no town hall. Counted on the map's canvas: ONE pixel of
 * its colour. Its square was 12 px across and the player's dot, drawn over it, 6 px in radius with a 1.5 px outline,
 * so standing at the town (or in bed) your own dot hid the place. A place's square is now wider than your dot on every
 * side (land.js MAP_SQUARE > MAP_ME): this test reads both from the page's map code and measures the band left showing.
 * Run: node tests/test_the_town_hall_shows_on_the_map_when_you_stand_at_it.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const k = page.match(/const MAP_ME = (\d+(?:\.\d+)?), MAP_SQUARE = (\d+(?:\.\d+)?);/);
ok(!!k, "(the map's sizes: your dot's radius and a place's half side)");
const me = +k[1], sq = +k[2], stroke = +(page.match(/g\.fillStyle = fill; g\.strokeStyle = "#000"; g\.lineWidth = (\d+(?:\.\d+)?);/) || [0, NaN])[1];
ok(page.includes('g.rect(x - MAP_SQUARE, y - MAP_SQUARE, 2 * MAP_SQUARE, 2 * MAP_SQUARE)') && page.includes("g.arc(mx, my, MAP_ME, 0, 2 * Math.PI)"), "the square and your dot are drawn at those sizes");
// the narrowest part of the place's coloured fill left showing: from the edge of your dot (radius + half its outline)
// to the square's own outline (half side − half its outline), straight out from the middle, where it is thinnest
const band = (sq - stroke / 2) - (me + stroke / 2);
ok(band >= 2, `standing on the place, its colour shows round your dot on every side: a band of ${band} px (was ${6 - 0.75 - 6.75} px — under the dot)`);
// with a compass your mark is an arrow: 6 px to each side and back, 10 px ahead — the band shows at least at its sides
const arrow = page.match(/const \[a1, a2\] = pt\((\d+), 0\), \[b1, b2\] = pt\(-(\d+), (\d+)\)/);
ok(arrow && sq - stroke / 2 > +arrow[3] + stroke / 2, "…and round a compass-holder's arrow, beside it and behind it");
ok(/if \(m\.town && m\.town\[0\] === P\.face\) mark\(m\.town\[1\], m\.town\[2\], "#e8c547", "square"\);/.test(page)
  && page.indexOf('mark(m.town[1]') < page.indexOf("const mx = X(P.u), my = Y(P.v);"), "(the town hall is still drawn, before your mark, which stays on top)");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
