/*
 * test_building_pieces_snap_to_their_neighbours.mjs — static/land-snap.js ("could building have some sort of snapping to
 * other pieces ... when like two poles are placed, they have the same levelled height", "at least same-type blocks
 * should snap", "yeah we definitely need snapping", operator 2026-11-06). Pieces are [x, z, y, w, d, h, m] in cm:
 *   1. two poles of the same wood placed 7 cm apart in height stand level (bottoms and tops);
 *   2. a plank laid 5 cm short of the last one in a row closes the gap (flush), and one 9 cm off the row's line joins it;
 *   3. a same-material neighbour snaps from 20 cm, any other only from 6 cm — a brick does not jump to planks 12 cm away;
 *   4. the axis a piece was placed against (its face on a face) keeps;
 *   5. nothing far away moves it, and a snap that would overlap another piece is not taken;
 *   6. the page places what it snapped (static/land.js placement()).
 *
 * Run: node tests/test_building_pieces_snap_to_their_neighbours.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const { snapBox, SAME_TOL, OTHER_TOL, restOnGround } = await import(join(ROOT, "static", "land-snap.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const WOOD = 7, PLANK = 9, BRICK = 11;

// 1
const pole = [100, 100, 300, 10, 10, 250, WOOD];
let s = snapBox([180, 100, 307, 10, 10, 250, WOOD], [pole]);
ok(s[2] === 300 && s[2] + s[5] === pole[2] + pole[5], `two poles placed 7 cm apart in height stand level (bottom ${s[2]})`);
// 2
const row = [[0, 0, 300, 100, 20, 3, PLANK], [100, 0, 300, 100, 20, 3, PLANK]];
s = snapBox([205, 0, 300, 100, 20, 3, PLANK], row);
ok(s[0] === 200, `a plank laid 5 cm short of the row closes the gap (x ${s[0]})`);
s = snapBox([200, 9, 300, 100, 20, 3, PLANK], row);
ok(s[1] === 0, `a plank 9 cm off the row's line joins it (z ${s[1]})`);
// 3
s = snapBox([212, 0, 300, 100, 20, 3, BRICK], row);
ok(s[0] === 212, `a brick 12 cm from planks stays where it was put (x ${s[0]}; other materials snap within ${OTHER_TOL} cm)`);
s = snapBox([218, 0, 300, 100, 20, 3, PLANK], row);
ok(s[0] === 200, `a plank 18 cm off snaps to its own kind (within ${SAME_TOL} cm)`);
// 4
s = snapBox([100, 20, 305, 100, 20, 3, PLANK], row, 1);
ok(s[1] === 20 && s[2] === 300, "the axis it was placed against keeps; the others line up");
// 5
s = snapBox([800, 800, 300, 10, 10, 10, WOOD], [pole]);
ok(s.join() === [800, 800, 300, 10, 10, 10, WOOD].join(), "nothing far away moves it");
// the fourth corner post of a 3 m frame lines up with the posts across it — they are 2.3-2.6 m away, and with a 2 m reach
// it stood 20 cm out of line (the pavilion built by hand on the live page, 2026-11-08)
const BEAM = 38, posts = [[1010, 810, 13710, 15, 15, 240, BEAM], [1270, 810, 13710, 15, 15, 240, BEAM], [1270, 1070, 13710, 15, 15, 240, BEAM]];
s = snapBox([1030, 1060, 13710, 15, 15, 240, BEAM], posts);
ok(s[0] === 1010 && s[1] === 1070, `the fourth post of a 3 m frame lines up with the others (x ${s[0]}, z ${s[1]})`);
const wall = [[0, 0, 0, 100, 100, 100, BRICK], [104, 0, 0, 100, 100, 100, BRICK]];
s = snapBox([110, 0, 0, 100, 100, 100, BRICK], [wall[0]]);
ok(s[0] === 100, "a brick 10 cm from its neighbour closes the gap");
s = snapBox([210, 0, 0, 100, 100, 100, BRICK], wall);
ok(!(s[0] < 204), `a snap that would overlap another piece is not taken (x ${s[0]})`);

// 6
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8"), pl = land.slice(land.indexOf("function placement("), land.indexOf("function startBreak"));
ok(/box = snapBox\(box, rec0\.list, a\.box \? ax : -1\)/.test(pl) && pl.indexOf("snapBox") < pl.indexOf("const clash"),
   "the page snaps a piece before it checks room for it and places what it snapped");

// 6. a piece set on the ground rests on the LOWEST ground under its footprint ("there's a gap under your floor",
//    operator 2026-11-07): never a gap under it anywhere, and on flat ground it sits exactly on it
{
  const slope = (x, z) => 4000 + 0.3 * x - 0.12 * z + 8 * Math.sin(x / 37) * Math.cos(z / 53);     // a bumpy hillside, cm
  const fl = restOnGround([120, 80, 4500, 300, 300, 4, PLANK], slope);
  let gap = 0;
  for (let x = 120; x <= 420; x += 5) for (let z = 80; z <= 380; z += 5) gap = Math.max(gap, fl[2] - slope(x, z));
  ok(gap <= 3, `a 3 x 3 m floor on a bumpy slope has no gap under it anywhere (worst ${gap.toFixed(1)} cm, sampling every 50 cm)`);
  const dip = (x, z) => (x > 300 && x < 330 && z > 200 && z < 230 ? 3990 : 4000);   // a dip just inside the edge
  ok(restOnGround([100, 100, 4500, 260, 200, 4, PLANK], dip)[2] <= 4000, "it never floats over the ground it sampled");
  ok(restOnGround([100, 100, 4500, 260, 200, 4, PLANK], () => 4000)[2] === 4000, "on flat ground it sits exactly on it");
  const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
  ok(/if \(!a\.box\) \{[^}]*restOnGround\(box, \(x, z\) => groundAt\(/.test(page), "the page places a piece on the ground that way");
}
if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
