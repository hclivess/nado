/*
 * test_a_turned_piece_is_drawn_held_and_overlapped_as_the_box_it_turns_into.mjs — ROTATION (#169: "maybe add fine
 * rotation if needed", operator 2026-11-10; the evidence: a fighter's 40° swept wing, land research fighter/GEOMETRY.md).
 * static/land-world.js and static/land-mesher.js, in node:
 *   1. the format: yaw, pitch, roll in tenths of a degree as 9th-11th numbers; a turn of 0 is the plain piece; out of
 *      range, or turned out of the plot, is no piece; the canonical order keeps every square plot's order;
 *   2. inPiece: a point is inside a turned piece exactly when, turned back about its centre, it is inside the square one;
 *   3. overlap: the oriented-box test agrees with dense point sampling over 300 random pairs of turned pieces (touching
 *      is not overlapping); square pieces keep the old test;
 *   4. boxAabb holds every corner of the turned piece and no more than it needs;
 *   5. the commitment of a plot with no turned piece is the v3 bytes it always was (tag and length); with one, v4;
 *   6. the mesher draws a turned piece whole, once (the chunk its centre is in), as six faces whose corners are the
 *      turned piece's eight corners on the planet, and never hides a square piece's face behind it.
 *
 * Run: node tests/test_a_turned_piece_is_drawn_held_and_overlapped_as_the_box_it_turns_into.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };
let seed = 7;
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const PL = 9;                                                // planks

// 1. the format
const wing = [500, 500, 10200, 300, 100, 10, PL, 0, 400, 0, 150];
ok(W.boxOk(wing) && W.isTurned(wing) && W.rotOf(wing).join() === "400,0,150", "a piece turned 40° in yaw and 15° in roll is a piece");
ok(W.normalBox([1, 2, 3, 4, 5, 6, PL, 0, 0, 0, 0]).length === 7 && W.normalBox([1, 2, 3, 4, 5, 6, PL, 2, 0, 0, 0]).length === 8, "a turn of 0 is the plain piece (7 numbers, or 8 with a shape)");
ok(!W.boxOk([1, 2, 10000, 4, 5, 6, PL, 0, 0, 0, 0]), "…and 11 numbers with no turn is not a spelling of it");
ok(!W.boxOk([500, 500, 10000, 10, 10, 10, PL, 0, 1801, 0, 0]) && !W.boxOk([500, 500, 10000, 10, 10, 10, PL, 0, -1800, 0, 0]) && W.boxOk([500, 500, 10000, 10, 10, 10, PL, 0, 1800, 0, 0]), "yaw, pitch, roll lie in -1799..1800 tenths");
ok(!W.boxOk([0, 0, 10000, 300, 20, 20, PL, 0, 450, 0, 0]) && W.boxOk([0, 0, 10000, 300, 20, 20, PL]), "turned so it reaches out of the plot, it is no piece (square, it is)");
const sq = [[3, 3, 3, 1, 1, 1, PL], [3, 3, 3, 1, 1, 1, PL, 2], [1, 1, 1, 1, 1, 1, PL]];
ok(JSON.stringify(W.canonicalBoxes(sq)) === JSON.stringify([[1, 1, 1, 1, 1, 1, PL], [3, 3, 3, 1, 1, 1, PL], [3, 3, 3, 1, 1, 1, PL, 2]]), "the canonical order of square pieces is as it was");

// 2. inPiece
let agree = 0, tried = 0;
for (let n = 0; n < 2000; n++) {
  const p = [500 + rnd() * 400, 500 + rnd() * 200, 10100 + rnd() * 250];
  const c = [wing[0] + wing[3] / 2, wing[1] + wing[4] / 2, wing[2] + wing[5] / 2];
  const l = W.turnVec(W.rotOf(wing), [p[0] - c[0], p[1] - c[1], p[2] - c[2]], true);
  const want = Math.abs(l[0]) < wing[3] / 2 && Math.abs(l[1]) < wing[4] / 2 && Math.abs(l[2]) < wing[5] / 2;
  const edge = Math.min(wing[3] / 2 - Math.abs(l[0]), wing[4] / 2 - Math.abs(l[1]), wing[5] / 2 - Math.abs(l[2]));
  if (Math.abs(edge) < 0.01) continue;
  tried++; if (W.inPiece(wing, p[0], p[1], p[2]) === want) agree++;
}
ok(agree === tried && tried > 1500, `a point is in the turned piece exactly when, turned back, it is in the square one (${agree}/${tried})`);
ok(W.turnVec([400, 250, 150], W.turnVec([400, 250, 150], [3, -7, 11]), true).every((x, i) => Math.abs(x - [3, -7, 11][i]) < 1e-9), "turning back undoes a turn");

// 3. overlap against sampling
const randTurned = () => {
  const w = 20 + Math.floor(rnd() * 200), d = 20 + Math.floor(rnd() * 200), h = 5 + Math.floor(rnd() * 100);
  return [600 + Math.floor(rnd() * 200), 600 + Math.floor(rnd() * 200), 10000 + Math.floor(rnd() * 200), w, d, h, PL, 0,
    Math.floor(rnd() * 3600) - 1799, Math.floor(rnd() * 3600) - 1799, Math.floor(rnd() * 3600) - 1799];
};
const inside = (b, p) => {
  const c = [b[0] + b[3] / 2, b[1] + b[4] / 2, b[2] + b[5] / 2], l = W.turnVec(W.rotOf(b), [p[0] - c[0], p[1] - c[1], p[2] - c[2]], true);
  return Math.abs(l[0]) < b[3] / 2 - 0.5 && Math.abs(l[1]) < b[4] / 2 - 0.5 && Math.abs(l[2]) < b[5] / 2 - 0.5;
};
let pairs = 0, wrong = 0, both = 0;
for (let n = 0; n < 300; n++) {
  const a = randTurned(), b = randTurned();
  const sat = W.boxesOverlap(a, b);
  // sample a's interior densely along its own axes; a sample deep in both is an overlap no test may miss
  let shared = false;
  const c = [a[0] + a[3] / 2, a[1] + a[4] / 2, a[2] + a[5] / 2];
  for (let i = 0; i <= 12 && !shared; i++) for (let j = 0; j <= 12 && !shared; j++) for (let k = 0; k <= 12 && !shared; k++) {
    const l = [(i / 12 - 0.5) * (a[3] - 1), (j / 12 - 0.5) * (a[4] - 1), (k / 12 - 0.5) * (a[5] - 1)], t = W.turnVec(W.rotOf(a), l);
    if (inside(b, [c[0] + t[0], c[1] + t[1], c[2] + t[2]])) shared = true;
  }
  pairs++; if (shared) both++;
  if (shared && !sat) wrong++;                               // sampling found a shared point: the test must say overlap
}
ok(wrong === 0 && both > 20, `the oriented-box test never misses an overlap sampling finds (${pairs} pairs, ${both} overlapping)`);
const p1 = [200, 1200, 10000, 300, 100, 10, PL, 0, 0, 0, 300], p2 = [200, 1200, 10020, 300, 100, 10, PL, 0, 0, 0, 300];
ok(!W.boxesOverlap(p1, p2), "two plates rolled 30°, 20 cm apart, do not overlap (the boxes around them do)");
ok(!W.boxesOverlap([0, 0, 0, 100, 100, 100, PL], [100, 0, 0, 100, 100, 100, PL]) && W.boxesOverlap([0, 0, 0, 100, 100, 100, PL], [99, 0, 0, 100, 100, 100, PL]), "square pieces: touching is not overlapping, a centimetre in is");
ok(!W.boxesOverlap([0, 0, 0, 100, 100, 100, PL, 0, 1800, 0, 0], [100, 0, 0, 100, 100, 100, PL]), "a piece turned half round touching a square one does not overlap it");

// 4. boxAabb
for (const b of [wing, ...Array.from({ length: 50 }, randTurned)]) {
  const a = W.boxAabb(b), c = [b[0] + b[3] / 2, b[1] + b[4] / 2, b[2] + b[5] / 2];
  let inAll = true, reach = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
    const t = W.turnVec(W.rotOf(b), [sx * b[3] / 2, sy * b[4] / 2, sz * b[5] / 2]), p = [c[0] + t[0], c[1] + t[1], c[2] + t[2]];
    for (let k = 0; k < 3; k++) { reach[k] = Math.min(reach[k], p[k]); reach[k + 3] = Math.max(reach[k + 3], p[k]); if (p[k] < a[k] - 1e-6 || p[k] > a[k] + a[k + 3] + 1e-6) inAll = false; }
  }
  if (!inAll || [0, 1, 2].some((k) => reach[k] - a[k] > 1 || a[k] + a[k + 3] - reach[k + 3] > 1)) { ok(false, "boxAabb " + JSON.stringify(b)); break; }
}
ok(true, "boxAabb holds every turned corner, within a centimetre of the farthest (51 pieces)");

// 5. the commitment's version
const salt = new Uint8Array(32).fill(3), tag = (bytes) => new TextDecoder().decode(bytes.slice(0, 17));
const sqBytes = W.commitmentBytes(7, salt, [], [[1, 1, 1, 1, 1, 1, PL]]), tBytes = W.commitmentBytes(7, salt, [], [[1, 1, 1, 1, 1, 1, PL], wing]);
ok(tag(sqBytes) === "nado-land-plot-v3" && sqBytes.length === 17 + 4 + 32 + 4 + 4 + 14, "a plot with no turned piece commits the same v3 bytes it always did");
ok(tag(tBytes) === "nado-land-plot-v4" && tBytes.length === 17 + 4 + 32 + 4 + 4 + 2 * 20, "…with one, v4: every piece 20 bytes (its yaw, pitch, roll as i16)");

// 6. the mesher
const face = 0, cu = 3435, cv = 4995, u0 = cu * W.CHUNK, v0 = cv * W.CHUNK;
const piece = [500, 500, 10380, 300, 100, 10, PL, 0, 400, 0, 150];            // centre at 10385 cm: chunk 6 (96-112 m)
const square = [100, 100, 10380, 100, 100, 100, PL];
const ch = Math.floor((piece[2] + piece[5] / 2) / (W.CHUNK * W.CM));
const drawn = [ch - 1, ch, ch + 1].map((c) => M.meshChunk(face, cu, cv, c, new Map(), [piece], 0, false));
const quads = drawn.map((r) => (r.empty || !r.pieces ? 0 : r.pieces.idx.length / 6));
ok(quads[1] === 6 && quads[0] === 0 && quads[2] === 0, `drawn whole, once: six faces in the chunk its centre is in (${quads.join(", ")})`);
const r = drawn[1], anchor = r.anchor, c = [piece[0] + piece[3] / 2, piece[1] + piece[4] / 2, piece[2] + piece[5] / 2];
const corners = [];
for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
  const t = W.turnVec(W.rotOf(piece), [sx * piece[3] / 2, sy * piece[4] / 2, sz * piece[5] / 2]);
  const gu = u0 + (c[0] + t[0]) / W.CM, gv = v0 + (c[1] + t[1]) / W.CM, gh = (c[2] + t[2]) / W.CM, d = W.dirOf(face, gu, gv), R = W.R0 + gh;
  corners.push([d[0] * R - anchor[0], d[1] * R - anchor[1], d[2] * R - anchor[2]]);
}
const P = r.pieces.pos, used = new Set();
let off = 0;
for (let i = 0; i < P.length; i += 3) {
  const k = corners.findIndex((q) => Math.hypot(q[0] - P[i], q[1] - P[i + 1], q[2] - P[i + 2]) < 1e-3);
  if (k < 0) off++; else used.add(k);
}
ok(off === 0 && used.size === 8, `every drawn corner is one of the turned piece's eight corners on the planet (${used.size} used, ${off} off)`);
const withSq = M.meshChunk(face, cu, cv, ch, new Map(), [square, [200, 100, 10380, 100, 100, 100, PL, 0, 50, 0, 0]], 0, false);
const alone = M.meshChunk(face, cu, cv, ch, new Map(), [square], 0, false);
ok(withSq.pieces.idx.length / 6 === alone.pieces.idx.length / 6 + 6, "a turned piece flush against a square one hides none of its faces, and draws all six of its own");

console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
