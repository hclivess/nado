/*
 * test_a_part_is_a_closed_solid_charged_by_what_it_fills_and_sunk_into_its_neighbours.mjs — PARTS (#175; operator
 * 2026-11-11: "this is xwing … not your shitty jet full of fucking disconnect metal plates", "your whole fucking
 * building system is fuck", "there are gaps between every fucking part"). static/land-shapes.js, static/land-world.js
 * and static/land-mesher.js, in node:
 *   1. the codes: exactly the 64 shape bytes of the ten types are parts; every other byte from 5 is no piece;
 *   2. the solids, every one of the 64: closed (its area vectors sum to nothing), inside its piece's box, wound to look
 *      outward (a positive volume; a convex one's faces all look away from its middle), every corner's normal on its
 *      face's side;
 *   3. what it is charged: fill() — whole thousandths — is the drawn solid's real volume to within 3 %;
 *   4. the outline walked into and aimed at (inside) is the drawn solid: sampled points agree;
 *   5. the world's rules: an engine is thruster material and nothing else; a hollow part takes a tenth; an engine is as
 *      many thrusters as its volume; a part never clashes with a neighbour (boxesOverlap stays geometry); inPiece follows
 *      the outline, turned too; a plot of unturned parts still commits v3 with the shape in its byte;
 *   6. the mesher draws a part whole, once, in the chunk of its centre: every corner where the solid's corner is on the
 *      planet, every face looking outward (turned too), its tones as their own blocks' draw groups and a canopy's panes
 *      in the glass.
 *
 * Run: node tests/test_a_part_is_a_closed_solid_charged_by_what_it_fills_and_sunk_into_its_neighbours.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const S = await import(join(ROOT, "static", "land-shapes.js"));
const W = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };
let seed = 11;
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
const B = W.B, ST = B.steelplate, TH = B.thruster;

// 1. the codes
const codes = [];
for (let s = 0; s < 256; s++) if (S.isPart(s)) codes.push(s);
const want = [];
S.TYPES.forEach((_, t) => { for (let v = 0; v < S.VARIANTS[t]; v++) want.push(S.code(t, v)); });
ok(codes.length === 64 && codes.join() === want.join() && S.FIRST === 16 && S.TYPES.length === 10, `the parts are the ${codes.length} codes of ten types from 16`);
let stray = 0;
for (let s = 5; s < 256; s++) if (!S.isPart(s) && W.boxOk([100, 100, 10000, 100, 100, 100, ST, s])) stray++;
ok(stray === 0 && !W.boxOk([100, 100, 10000, 100, 100, 100, ST, 57]) && !W.boxOk([100, 100, 10000, 100, 100, 100, ST, 116]) && !W.boxOk([100, 100, 10000, 100, 100, 100, ST, 15]), "a byte that is no part (15, an unused variant 57, past the last 116) is no piece");
ok(codes.every((s) => W.boxOk([100, 100, 10000, 100, 100, 100, S.decode(s).type === S.ENGINE ? TH : ST, s])), "every part's code is a piece");
ok(S.tapered(S.HULL, 0.7) === S.code(S.HULL, 6) && S.tapered(S.TUBE, 1) === S.code(S.TUBE, 9) && S.tapered(S.WING, 0.04) === S.code(S.WING, 0), "a taper names its variant: 0.7 the seventh, 1.0 the last, nothing under 0.1");

// 2-4. the solids. A part is measured at a size of its own kind: a wing fifteen times as deep as thick, a barrel long
// and thin, a dome half as high as wide; the rest 4 × 9 × 4 m (round ones drawn with their full forty sides).
const SIZE = { [S.WING]: [400, 900, 60], [S.CANNON]: [60, 600, 60], [S.DOME]: [400, 400, 200], [S.CANOPY]: [160, 400, 110] };
const CONVEX = new Set([S.TUBE, S.BODY, S.HULL, S.WING, S.DOME, S.NOSE]);
// the outline is the drawn solid for these; an engine's outline is its cowl filled (nobody walks down its throat), a
// canopy's the panes without their inset: held to less
const OUTLINE = { [S.ENGINE]: 0.8, [S.CANOPY]: 0.9 };
// crossings of the surface by the ray from p along +x (a hair off the axis, so it runs along no edge)
function crossings(T, p) {
  let n = 0;
  const P = T.pos, d = [1, 7.131e-5, 3.713e-5];
  for (let i = 0; i < T.n; i++) {
    const o = i * 9, a = [P[o], P[o + 1], P[o + 2]], e1 = [P[o + 3] - a[0], P[o + 4] - a[1], P[o + 5] - a[2]], e2 = [P[o + 6] - a[0], P[o + 7] - a[1], P[o + 8] - a[2]];
    const h = [d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0]], det = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2];
    if (Math.abs(det) < 1e-12) continue;
    const s = [p[0] - a[0], p[1] - a[1], p[2] - a[2]], u = (s[0] * h[0] + s[1] * h[1] + s[2] * h[2]) / det;
    if (u < 0 || u > 1) continue;
    const q = [s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0]], v = (d[0] * q[0] + d[1] * q[1] + d[2] * q[2]) / det;
    if (v < 0 || u + v > 1) continue;
    if ((e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2]) / det > 0) n++;
  }
  return n;
}
const bad = { open: [], out: [], inward: [], normal: [], fill: [], outline: [] };
let worstFill = 0, worstOutline = 1;
for (const s of codes) {
  const p = S.decode(s), name = S.TYPES[p.type] + p.v, [w, d, h] = SIZE[p.type] || [400, 900, 400], T = S.tris(s, w, d, h), P = T.pos;
  let vol = 0, area = 0, minDot = 1, off = 0, inward = 0;
  const A = [0, 0, 0], mid = [0, 0, 0];
  for (let i = 0; i < T.n * 9; i += 3) for (let k = 0; k < 3; k++) mid[k] += P[i + k] / (T.n * 3);
  for (let i = 0; i < T.n; i++) {
    const o = i * 9, a = [P[o], P[o + 1], P[o + 2]], b = [P[o + 3], P[o + 4], P[o + 5]], c = [P[o + 6], P[o + 7], P[o + 8]];
    const n = [(b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]), (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]), (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])];
    const l = Math.hypot(n[0], n[1], n[2]);
    vol += (a[0] * n[0] + a[1] * n[1] + a[2] * n[2]) / 6; area += l / 2;
    for (let k = 0; k < 3; k++) A[k] += n[k] / 2;
    if (CONVEX.has(p.type) && n[0] * ((a[0] + b[0] + c[0]) / 3 - mid[0]) + n[1] * ((a[1] + b[1] + c[1]) / 3 - mid[1]) + n[2] * ((a[2] + b[2] + c[2]) / 3 - mid[2]) < 0) inward++;
    for (let k = 0; k < 3; k++) {
      const q = o + k * 3;
      minDot = Math.min(minDot, (T.nor[q] * n[0] + T.nor[q + 1] * n[1] + T.nor[q + 2] * n[2]) / l);
      if (P[q] < -1e-3 || P[q] > w + 1e-3 || P[q + 1] < -1e-3 || P[q + 1] > h + 1e-3 || P[q + 2] < -1e-3 || P[q + 2] > d + 1e-3) off++;
    }
  }
  if (!(T.n > 0) || Math.hypot(A[0], A[1], A[2]) > 1e-6 * area) bad.open.push(name);
  if (off) bad.out.push(name);
  if (inward || !(vol > 0)) bad.inward.push(name);
  if (!(minDot > 0.78)) bad.normal.push(name + " " + minDot.toFixed(2));          // a smooth corner's normal is the mean of faces within 38° of its own (cos 38° = 0.788)
  const real = (1000 * vol) / (w * d * h), err = Math.abs(S.fill(s) - real) / real;
  worstFill = Math.max(worstFill, err);
  if (!Number.isInteger(S.fill(s)) || err > 0.03) bad.fill.push(`${name} ${S.fill(s)} vs ${real.toFixed(1)}`);
  let agree = 0;
  const N = 400;
  for (let i = 0; i < N; i++) { const x = rnd(), y = rnd(), z = rnd(); if ((crossings(T, [x * w, y * h, z * d]) % 2 === 1) === S.inside(s, x, y, z)) agree++; }
  worstOutline = Math.min(worstOutline, CONVEX.has(p.type) || p.type === S.RING || p.type === S.BODY ? agree / N : 1);
  if (agree / N < (OUTLINE[p.type] || 0.96)) bad.outline.push(`${name} ${agree}/${N}`);
}
ok(!bad.open.length, "every part is a closed solid: its area vectors sum to nothing" + (bad.open.length ? " — NOT " + bad.open.join(", ") : ""));
ok(!bad.out.length, "…wholly inside its piece's box" + (bad.out.length ? " — NOT " + bad.out.join(", ") : ""));
ok(!bad.inward.length, "…wound to look outward (a positive volume; a convex part's every face looks away from its middle)" + (bad.inward.length ? " — NOT " + bad.inward.join(", ") : ""));
ok(!bad.normal.length, "…every corner's normal on its own face's side" + (bad.normal.length ? " — NOT " + bad.normal.join(", ") : ""));
ok(!bad.fill.length, `what a part is charged (fill, whole thousandths of its box) is the drawn solid's volume within 3 % (worst ${(100 * worstFill).toFixed(1)} %)` + (bad.fill.length ? " — NOT " + bad.fill.join(", ") : ""));
ok(!bad.outline.length, `the outline walked into is the drawn solid (sampled points agree, worst ${(100 * worstOutline).toFixed(1)} %; an engine's is its cowl filled)` + (bad.outline.length ? " — NOT " + bad.outline.join(", ") : ""));
ok(S.fill(S.code(S.BODY, 9)) === 1000 && S.fill(0) === null && S.fill(3) === null, "a body at taper 1.0 is exactly a box's worth; a box and a slope have no fill");
const sizes = [[130, 440, 130], [37, 911, 5], [1, 1, 1]];
ok(sizes.every(([w, d, h]) => { const a = S.tris(S.code(S.ENGINE), w, d, h); return a && a === S.tris(S.code(S.ENGINE), w, d, h) && a.pos.length === a.n * 9 && a.nor.length === a.n * 9 && a.tone.length === a.n && a.pos.every(Number.isFinite) && a.nor.every(Number.isFinite); }),
  "a part is built at any size down to a centimetre, once (the same triangles the second time), with no number lost");
const eng = S.tris(S.code(S.ENGINE), 130, 440, 130), tones = new Set(eng.tone);
ok([S.MATERIAL, S.DARK, S.STEEL, S.GLOW].every((t) => tones.has(t)) && tones.size === 4, "an engine has its skin, a dark throat, a steel cone and a glowing exit");

// 5. the world's rules
const at = (s, m = ST, w = 200, d = 400, h = 100) => [400, 400, 10000, w, d, h, m, s];
ok(!W.boxOk(at(S.code(S.ENGINE), ST)) && W.boxOk(at(S.code(S.ENGINE), TH)) && W.boxOk(at(S.code(S.HULL, 4), TH)), "an engine is made of thrusters and nothing else (any other part may be)");
ok(W.isPart(at(S.code(S.WING, 3))) && !W.isPart([1, 1, 1, 1, 1, 1, ST]) && !W.isPart([1, 1, 1, 1, 1, 1, ST, 2]) && W.isEngine(at(S.code(S.ENGINE), TH)) && !W.isEngine([1, 1, 1, 100, 100, 140, TH]), "a part is a piece with a part's shape; an engine the engine part");
const boxV = 200 * 400 * 100;
ok(W.boxVolume(at(S.code(S.BODY, 9))) === boxV && W.boxVolume(at(S.code(S.TUBE, 9))) === Math.floor((boxV * 785) / 1000) && W.boxVolume([1, 1, 1, 200, 400, 100, ST]) === boxV && W.boxVolume([1, 1, 1, 200, 400, 100, ST, 1]) === boxV / 2,
  "a solid part takes its share of its box (a box its box, a slope half)");
ok(W.boxVolume(at(S.code(S.HULL, 9))) === Math.floor((boxV * 859) / 10000) && W.boxVolume(at(S.code(S.WING, 4))) === Math.floor((boxV * S.fill(S.code(S.WING, 4))) / 10000)
  && [S.HULL, S.NOSE, S.WING, S.CANOPY, S.DOME].every((t) => S.hollow(S.code(t))) && [S.TUBE, S.BODY, S.ENGINE, S.CANNON, S.RING].every((t) => !S.hollow(S.code(t))) && S.SHELL === 10,
  "a hull, a nose, a wing, a canopy and a dome are skins: a tenth of their solid");
ok(W.boxVolume([1, 1, 1, 1, 1, 1, ST, S.code(S.RING, 9)]) === 1, "the smallest part still takes a cubic centimetre");
ok(W.engineCount([0, 0, 10000, 130, 440, 130, TH, S.code(S.ENGINE)]) === 2 && W.engineCount([0, 0, 10000, 100, 100, 140, TH]) === 1 && W.engineCount([0, 0, 10000, 30, 60, 30, TH, S.code(S.ENGINE)]) === 1
  && W.engineCount(at(S.code(S.HULL, 4), ST)) === 0 && W.engineCount([0, 0, 10000, 260, 880, 260, TH, S.code(S.ENGINE)]) === Math.floor((Math.floor((260 * 880 * 260 * 415) / 1000) + 700000) / 1400000),
  "an engine is as many thrusters as its volume holds, never fewer than one (1.3 × 4.4 × 1.3 m: two); a thruster is one; a hull none");
const hull = [400, 400, 10000, 200, 600, 150, ST, S.code(S.HULL, 6)], wingP = [500, 500, 10060, 500, 300, 20, ST, S.code(S.WING, 3)], plate = [450, 450, 10050, 100, 100, 100, ST];
ok(W.boxesOverlap(hull, wingP) && !W.piecesClash(hull, wingP) && !W.piecesClash(wingP, hull), "a wing rooted inside a hull: their boxes overlap, and they do not clash");
ok(W.boxesOverlap(hull, plate) && !W.piecesClash(hull, plate) && !W.piecesClash(plate, hull), "a part and a box may share a place");
ok(W.piecesClash(plate, [500, 500, 10100, 100, 100, 100, ST]) && W.piecesClash(plate, [500, 500, 10100, 100, 100, 100, ST, 2]) && !W.piecesClash(plate, [550, 450, 10050, 100, 100, 100, ST]), "two boxes, or a box and a slope, still may not (touching is not sharing)");
// inPiece: the middle of a tube is in it, its box's corner is not; a ring's hole is not; turned, the same about its centre
const tube = [400, 400, 10000, 100, 300, 100, ST, S.code(S.TUBE, 9)], ring = [400, 400, 10000, 100, 300, 100, ST, S.code(S.RING, 0)];
ok(W.inPiece(tube, 450, 550, 10050) && !W.inPiece(tube, 403, 550, 10003) && W.inPiece([...tube.slice(0, 7)], 403, 550, 10003), "the middle of a tube is in it, the corner of its box is not (of a box, it is)");
ok(!W.inPiece(ring, 450, 550, 10050) && W.inPiece(ring, 450, 550, 10095), "a ring's hole is not in it, its rim is");
const tubeT = [...tube, 900, 0, 0];                       // a quarter turn about up: its length lies east-west now
ok(W.inPiece(tubeT, 330, 550, 10050) && !W.inPiece(tubeT, 450, 430, 10050) && W.inPiece(tube, 450, 430, 10050), "turned a quarter, the tube is where it was turned to — and not where it was");
const cone = [400, 400, 10000, 100, 300, 100, ST, S.code(S.TUBE, 0)];
ok(W.inPiece(cone, 420, 410, 10050) && !W.inPiece(cone, 420, 690, 10050) && W.inPiece(cone, 450, 690, 10050), "a part's front is the far end of its depth: a tube tapered to a tenth is wide at the back, a point at the front");
// the commitment: the shape byte carries the code, the version does not move
const salt = new Uint8Array(32).fill(3), tag = (bytes) => new TextDecoder().decode(bytes.slice(0, 17));
const cb = W.commitmentBytes(7, salt, [], [hull, wingP]), cbT = W.commitmentBytes(7, salt, [], [hull, [...wingP, 0, 0, 150]]);
ok(tag(cb) === "nado-land-plot-v3" && cb.length === 17 + 4 + 32 + 4 + 4 + 2 * 14 && [...cb].includes(S.code(S.HULL, 6)) && [...cb].includes(S.code(S.WING, 3)), "a plot of unturned parts commits v3, 14 bytes a piece, the part in the shape's byte");
ok(tag(cbT) === "nado-land-plot-v4", "…and v4 once a part is turned, as any piece");
ok(JSON.stringify(W.canonicalBoxes([wingP, hull, wingP])) === JSON.stringify([hull, wingP]), "the same part twice is one piece");

// 6. the mesher
const face = 0, cu = 3435, cv = 4995, u0 = cu * W.CHUNK, v0 = cv * W.CHUNK;
const chunkOf = (b) => Math.floor((b[2] + b[5] / 2) / (W.CHUNK * W.CM));
const tall = [500, 500, 10300, 200, 600, 150, ST, S.code(S.HULL, 6)];          // 103.0-104.5 m, its centre in chunk 6 (96-112 m)
const ch = chunkOf(tall);
const drawn = [ch - 1, ch, ch + 1].map((c) => M.meshChunk(face, cu, cv, c, new Map(), [tall], 0, false));
const T = S.tris(tall[7], tall[3], tall[4], tall[5]);
const count = drawn.map((r) => (r.empty || !r.pieces ? 0 : r.pieces.idx.length / 3));
ok(count[1] === T.n && count[0] === 0 && count[2] === 0, `a part is drawn whole, once: its ${T.n} triangles in the chunk of its centre (${count.join(", ")})`);
// where a corner of the solid is on the planet (the piece's frame: x across = east, z forward = north, y up), turned first
const onPlanet = (b, anchor, x, y, z) => {
  let p = [b[0] + x, b[1] + z, b[2] + y];
  if (W.isTurned(b)) { const c = [b[0] + b[3] / 2, b[1] + b[4] / 2, b[2] + b[5] / 2], t = W.turnVec(W.rotOf(b), [p[0] - c[0], p[1] - c[1], p[2] - c[2]]); p = [c[0] + t[0], c[1] + t[1], c[2] + t[2]]; }
  const dir = W.dirOf(face, u0 + p[0] / W.CM, v0 + p[1] / W.CM), R = W.R0 + p[2] / W.CM;
  return [dir[0] * R - anchor[0], dir[1] * R - anchor[1], dir[2] * R - anchor[2]];
};
function drawnRight(b, buf, anchor, tone = null) {
  const Tb = S.tris(b[7], b[3], b[4], b[5]), P = buf.pos, N = buf.nor, I = buf.idx, mid = onPlanet(b, anchor, b[3] / 2, b[5] / 2, b[4] / 2);
  const wantAt = [];
  for (let i = 0; i < Tb.n; i++) if (tone === null || Tb.tone[i] === tone) for (let k = 0; k < 3; k++) wantAt.push(onPlanet(b, anchor, Tb.pos[i * 9 + k * 3], Tb.pos[i * 9 + k * 3 + 1], Tb.pos[i * 9 + k * 3 + 2]));
  let off = 0, inward = 0, dark = 0;
  for (let t = 0; t < I.length; t += 3) {
    const a = I[t] * 3, bb = I[t + 1] * 3, c = I[t + 2] * 3;
    for (const q of [a, bb, c]) if (!wantAt.some((p) => Math.hypot(p[0] - P[q], p[1] - P[q + 1], p[2] - P[q + 2]) < 2e-3)) off++;
    const e1 = [P[bb] - P[a], P[bb + 1] - P[a + 1], P[bb + 2] - P[a + 2]], e2 = [P[c] - P[a], P[c + 1] - P[a + 1], P[c + 2] - P[a + 2]];
    const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]], l = Math.hypot(n[0], n[1], n[2]);
    const g = [(P[a] + P[bb] + P[c]) / 3 - mid[0], (P[a + 1] + P[bb + 1] + P[c + 1]) / 3 - mid[1], (P[a + 2] + P[bb + 2] + P[c + 2]) / 3 - mid[2]];
    if (n[0] * g[0] + n[1] * g[1] + n[2] * g[2] <= 0) inward++;
    for (const q of [a, bb, c]) if ((N[q] * n[0] + N[q + 1] * n[1] + N[q + 2] * n[2]) / l < 0.7) dark++;
  }
  return { off, inward, dark, tris: I.length / 3 };
}
let res = drawnRight(tall, drawn[1].pieces, drawn[1].anchor);
ok(res.off === 0 && res.inward === 0 && res.dark === 0, `every drawn corner is the solid's corner on the planet, every face looks outward and is lit from its own side (${JSON.stringify(res)})`);
const turnedHull = [...tall, 400, 100, 250], rt = M.meshChunk(face, cu, cv, chunkOf(turnedHull), new Map(), [turnedHull], 0, false);
res = drawnRight(turnedHull, rt.pieces, rt.anchor);
ok(res.tris === T.n && res.off === 0 && res.inward === 0 && res.dark === 0, `turned by yaw, pitch and roll it is drawn where it was turned to, still looking outward (${JSON.stringify(res)})`);
// tones: an engine's skin in the thruster's group, its throat in black's, its cone in steel plate's, its exit in the lamp's
const engine = [500, 500, 10300, 130, 440, 130, TH, S.code(S.ENGINE)], Te = S.tris(engine[7], 130, 440, 130);
const re = M.meshChunk(face, cu, cv, chunkOf(engine), new Map(), [engine, [900, 500, 10300, 130, 440, 130, TH, S.code(S.ENGINE)]], 0, false);
const perTone = (t) => 2 * 3 * Te.tone.reduce((a, x) => a + (x === t ? 1 : 0), 0);
const groups = re.pieces.groups || [], byBlock = Object.fromEntries(groups.map((g) => [g[2], g[1]]));
ok(groups.length === 4 && byBlock[TH] === perTone(S.MATERIAL) && byBlock[B.black] === perTone(S.DARK) && byBlock[ST] === perTone(S.STEEL) && byBlock[B.lamp] === perTone(S.GLOW),
  `two engines are four draw groups — thruster, black, steel plate, lamp — one a tone, not one a part (${JSON.stringify(groups)})`);
let covered = 0, next = 0;
for (const g of groups.slice().sort((a, b) => a[0] - b[0])) { if (g[0] === next) covered += g[1]; next = g[0] + g[1]; }
ok(covered === re.pieces.idx.length && re.pieces.idx.length === 2 * 3 * Te.n, "…the groups covering every index exactly once");
ok(W.toneBlock(engine, S.MATERIAL) === TH && W.toneBlock(engine, S.DARK) === B.black && W.toneBlock(engine, S.STEEL) === ST && W.toneBlock(engine, S.GLOW) === B.lamp, "a tone is a block: the piece's own, black, steel plate, a lamp");
// a canopy in glass: its panes in the glass (the clear buffer), its frame and floor in black with the solid pieces
const canopy = [500, 500, 10300, 160, 400, 110, B.glass, S.code(S.CANOPY)], Tc = S.tris(canopy[7], 160, 400, 110);
const rc = M.meshChunk(face, cu, cv, chunkOf(canopy), new Map(), [canopy], 0, false);
const panes = Tc.tone.reduce((a, x) => a + (x === S.MATERIAL ? 1 : 0), 0);
ok(rc.glassy && rc.glassy.idx.length === 3 * panes && rc.pieces && rc.pieces.idx.length === 3 * (Tc.n - panes) && rc.pieces.groups.length === 1 && rc.pieces.groups[0][2] === B.black,
  `a glass canopy's ${panes} pane triangles are drawn in the glass, its frame and floor in black`);
// a part hides nothing: a box flush against a hull's box keeps its face (the hull does not fill its box)
const beside = [700, 500, 10300, 100, 100, 100, ST];
const alone = M.meshChunk(face, cu, cv, ch, new Map(), [beside], 0, false), both = M.meshChunk(face, cu, cv, ch, new Map(), [beside, tall], 0, false);
ok(both.pieces.idx.length === alone.pieces.idx.length + 3 * T.n, "a box flush against a part's box keeps every face (a part does not fill its box)");

console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
