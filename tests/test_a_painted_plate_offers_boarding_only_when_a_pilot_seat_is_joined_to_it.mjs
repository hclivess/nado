/*
 * test_a_painted_plate_offers_boarding_only_when_a_pilot_seat_is_joined_to_it.mjs — playtest 2026-11-15: a black plate
 * standing alone on the ground read "Black plate — Use board", with no seat to board (Use then said "Aim at a door or a
 * chest"). Use boards a painted plate only when craftSeat finds a pilot seat joined to it (land.js act), so the aim line
 * says "board" only then (seatOfAimed, craftSeat remembered per piece until its plot's pieces change); a plate with no
 * seat reads as any piece: hold Break to take it down. The page's own craftSeat, indexBoxes and seatOfAimed run here.
 * Run: node tests/test_a_painted_plate_offers_boarding_only_when_a_pilot_seat_is_joined_to_it.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const cut = (a, b) => { const i = page.indexOf(a); return page.slice(i, page.indexOf(b, i)); };
const src = cut("const bkey = (i, j, k) =>", "\nfunction setPlotBoxes") + "\n" + cut("const seatMemo = new WeakMap();", "\nfunction nearMyCraft()");
const SEAT = Wd.B.pilotseat, PLATE = 27;   // 27: the black plate's block (the plate placed on 0·4999·3434 in the playtest)
const env = { Wd, B: { pilotseat: SEAT }, plotBoxes: new Map() };
const f = new Function(...Object.keys(env), src + "\nreturn { indexBoxes, seatOfAimed, craftSeat };")(...Object.values(env));
const put = (list) => env.plotBoxes.set(7, { list, idx: f.indexBoxes(list) });

const lone = [830, 1260, 13098, 50, 50, 50, PLATE];
put([lone]);
ok(f.seatOfAimed(7, lone) === null, "a plate alone on the ground has no seat joined to it: no \"board\"");
const deck = [600, 600, 2000, 400, 150, 5, PLATE], seat = [760, 640, 2005, 80, 90, 110, SEAT], far = [1300, 1300, 2000, 50, 50, 50, PLATE];
put([deck, seat, far]);
ok(f.seatOfAimed(7, deck) === seat, "a plate with a pilot seat on it: \"board\"");
ok(f.seatOfAimed(7, far) === null, "…and a plate of the same plot not touching that craft: none");
put([deck, far]);
ok(f.seatOfAimed(7, deck) === null, "the seat taken away, the answer follows the plot's new pieces (not the remembered one)");
// the aim line asks it, for painted plates only; a seat itself always boards
ok(/: kind === B\.pilotseat \|\| \(CRAFT_SKIN\.has\(kind\) && seatOfAimed\(a\.box\.plot, a\.box\.b\)\) \? T\("v\.board", "board"\) :/.test(page), "the aim line says \"board\" for a seat, and for a painted plate only when a seat is joined to it");
ok(/if \(a && a\.box && CRAFT_SKIN\.has\(a\.box\.b\[6\]\)\) \{ const st = craftSeat\(a\.box\.plot, a\.box\.b\); if \(st\) return board\(/.test(page), "…the same rule Use acts by");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
