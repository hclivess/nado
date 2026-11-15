/*
 * test_a_piece_placed_with_mirror_on_gets_its_twin_mirrored_through_the_piece_it_was_placed_against.mjs — #187, the
 * Kerbal half: the X-wing on 0·4999·3438 had its four S-foils, engines and cannons placed one at a time. With Mirror on
 * (the bag's Piece size tab), a piece placed against another gets a twin through that piece's middle, as KSP mirrors a
 * part about its parent (land-world.js mirrorPiece):
 *   1. every point of the twin is the mirror image of the original's — for turned hulls (not symmetric front to back)
 *      and for WINGS (not symmetric root to tip: the other side's wing is the same wing rolled half a turn), through an
 *      east-west plane (the parent's nose north or south) and a north-south one (its nose east or west);
 *   2. a square box only moves, a square slope's rise flips on the mirrored axis and not on the other;
 *   3. the page: placement adds the twin (both or neither — "twin" when its far side has no room), a piece straddling
 *      the middle is its own twin, Place says why, the outline shows the twin, the switch survives a size change and a
 *      reload, and its words are in all 17 languages.
 * Run: node tests/test_a_piece_placed_with_mirror_on_gets_its_twin_mirrored_through_the_piece_it_was_placed_against.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js")), S = await import(join(ROOT, "static", "land-shapes.js"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. points: p's local point (in half-extents) turned to the plot, reflected through the parent's middle, against q's
const at = (b, l) => { const c = [b[0] + b[3] / 2, b[1] + b[4] / 2, b[2] + b[5] / 2], t = W.turnVec(W.rotOf(b), [l[0] * b[3] / 2, l[1] * b[4] / 2, l[2] * b[5] / 2]); return [c[0] + t[0], c[1] + t[1], c[2] + t[2]]; };
let seed = 7; const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
const tally = { ew: [0, 0], ns: [0, 0] };
for (let k = 0; k < 4000; k++) {
  const parent = [500 + rnd(300), 500 + rnd(300), 100, 100 + rnd(200), 100 + rnd(400), 80, 64, S.code(S.HULL, 3), rnd(3599) - 1799, 0, 0];
  const wing = k % 2 === 0;
  const p = [300 + rnd(600), 300 + rnd(600), 120, 300, 120, 20, 64, wing ? S.code(S.WING, 4) : S.code(S.HULL, 2), rnd(3599) - 1799, rnd(3599) - 1799, rnd(3599) - 1799];
  const q = W.mirrorPiece(p, parent);
  const pc = [parent[0] + parent[3] / 2, parent[1] + parent[4] / 2], nose = W.turnVec(W.rotOf(parent), [0, 1, 0]), ew = Math.abs(nose[1]) >= Math.abs(nose[0]);
  const refl = (x) => (ew ? [2 * pc[0] - x[0], x[1], x[2]] : [x[0], 2 * pc[1] - x[1], x[2]]);
  // a hull: its local x flips (its front stays its front); a wing: rolled half a turn, its root stays its root
  const pairs = wing ? [[[-1, 0, 0], [-1, 0, 0]], [[-1, 1, 0], [-1, 1, 0]], [[1, -1, 0], [1, -1, 0]], [[0.4, 0.8, 0], [0.4, 0.8, 0]]]
    : [[[1, 0, 0], [-1, 0, 0]], [[0, 1, 0], [0, 1, 0]], [[0.3, 1, 0.7], [-0.3, 1, 0.7]], [[0.5, -0.6, -0.9], [-0.5, -0.6, -0.9]]];
  const good = q.slice(0, 3).every(Number.isInteger) && q.slice(8).every((r) => r > -1800 && r <= 1800) && q[6] === p[6] && q[7] === p[7] && pairs.every(([a, b]) => { const A = refl(at(p, a)), B = at(q, b); return Math.hypot(A[0] - B[0], A[1] - B[1], A[2] - B[2]) < 1e-3; });
  tally[ew ? "ew" : "ns"][good ? 0 : 1]++;
}
ok(tally.ew[1] === 0 && tally.ew[0] > 500, `1. through an east-west plane, every twin is the original's mirror image (whole cm, turns in range), hulls and wings (${tally.ew[0]} pieces, turned every way)`);
ok(tally.ns[1] === 0 && tally.ns[0] > 500, `…and through a north-south plane (${tally.ns[0]} pieces)`);
{ // the X-wing's case, by numbers: a hull nose north at x 700..900; a wing rooted on its east side, rolled 15°
  const hull = [700, 200, 300, 200, 900, 150, 64, S.code(S.HULL, 4)];
  const wingE = [900, 600, 330, 400, 200, 20, 64, S.code(S.WING, 4), 0, 0, 150];
  const wingW = W.mirrorPiece(wingE, hull);
  ok(wingW[0] === 300 && wingW[1] === 600 && wingW[8] === 0 && wingW[10] === 1650, "the X-wing's case: the east wing's twin lies west of the hull (x 300..700), rolled 165° — the same wing half a turn round, its 15° mirrored");
}
// 2. square pieces
const hullN = [700, 200, 300, 200, 900, 150, 64], hullE = [600, 600, 300, 200, 200, 150, 64, 0, -900, 0, 0];   // a parent's nose is its depth: turned a quarter, it points east
ok(W.mirrorPiece([900, 400, 300, 100, 100, 100, 64], hullN).join() === [600, 400, 300, 100, 100, 100, 64].join(), "2. a square box beside a parent nose north moves across, unturned");
ok(W.mirrorPiece([900, 400, 300, 100, 100, 100, 64, 1], hullN).join() === [600, 400, 300, 100, 100, 100, 64, 2].join() && W.mirrorPiece([900, 400, 300, 100, 100, 100, 64, 3], hullN).join() === [600, 400, 300, 100, 100, 100, 64, 3].join(),
  "…a slope rising east becomes one rising west; one rising north stays");
ok(W.mirrorPiece([400, 900, 300, 100, 100, 100, 64, 3], hullE).join() === [400, 400, 300, 100, 100, 100, 64, 4].join(), "…beside a parent nose east, it crosses north to south and a north rise becomes a south one");
ok(W.mirrorPiece([750, 400, 450, 100, 100, 100, 64], hullN).join() === [750, 400, 450, 100, 100, 100, 64].join(), "…a piece across the middle is its own twin");
// 3. the page
const pl = page.slice(page.indexOf("function placement(a) {"), page.indexOf("function riseShape()"));
ok(/if \(piece\.mirror && a\.box && a\.box\.plot === c\.plot\) \{\n    const ts = pieces\.map\(\(p\) => Wd\.mirrorPiece\(p, a\.box\.b\)\), same = /.test(pl) && /pieces: twin \? pieces\.concat\(twin\) : pieces/.test(pl),
  "3. placement adds the twins, mirrored through the piece aimed at, on that piece's plot");
ok(/ok && twinBad \? "twin" : ""/.test(pl) && /ok: ok && !twinBad/.test(pl) && /pieces\.some\(\(p\) => Wd\.piecesClash\(t, p\)\)/.test(pl), "…both or neither: a twin without room (or in the original) refuses the pair, and says so");
ok(/pl\.why === "twin" \? T\("noRoomTwin", /.test(page) && /if \(pl && pl\.twin\) \{ frameBox\(ghost2, pl\.plot, pl\.twin\);/.test(page) && /ghost\.visible = ghost2\.visible = false;/.test(page),
  "…Place says the twin has no room, and the outline shows where the twin goes");
ok(/const units = add\.reduce/.test(page) && /const add = pl\.pieces\.map/.test(page), "…the bag pays for both (Place counts every piece it sends)");
ok(/part: piece\.part, mirror: piece\.mirror,/.test(page) && /piece\.mirror = piece\.mirror === true;/.test(page) && /\$\("pzMirror"\)\.onclick = \(\) => \{ piece\.mirror = !piece\.mirror;/.test(page),
  "…the switch is in the bag, and survives a size change and a reload");
const keys = ["land.mirror", "land.mirrorOn", "land.mirrorHint", "land.noRoomTwin"];
ok(Object.keys(I).length === 17 && Object.values(I).every((t) => keys.every((k) => typeof t[k] === "string" && t[k].length > 1)), "its words are in all 17 languages");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
