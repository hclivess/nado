/*
 * test_roofs_slope_and_stairs_climb.mjs — slopes and stairs for "A REAL HOUSE" (operator, 2026-11-06):
 *   1. a slope (land-world SHAPES 1..4) is solid below its sloped face and open above it, rising the way its shape says;
 *      it costs half its box; one spelling (a trailing 0 is the box);
 *   2. the mesher draws a slope as five faces — bottom, tall end, slope, two triangular sides — every one facing out,
 *      and never as the box it sits in;
 *   3. a walker walks up a roof slope (the collision is the slope, not its box);
 *   4. a flight of stairs is solid steps of about 20 cm rise, climbing the way it faces, filling its box's footprint,
 *      every step low enough to walk up; and a walker climbs it;
 *   5. the page places a slope or a flight from one placement (G cycles box, slope, stairs).
 *
 * Run: node tests/test_roofs_slope_and_stairs_climb.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
const { piecesFor } = await import(join(ROOT, "static", "land-snap.js"));
const { walk } = await import(join(ROOT, "static", "land-walk.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const PLANKS = Wd.B.planks;

// 1
const roof = [0, 0, 0, 200, 100, 100, PLANKS, Wd.SLOPE_POS_X];
ok(Wd.inPiece(roof, 150, 50, 60) && !Wd.inPiece(roof, 50, 50, 60) && Wd.inPiece(roof, 50, 50, 10), "a slope rising toward +x is solid below its face, open above it");
const back = [0, 0, 0, 200, 100, 100, PLANKS, Wd.SLOPE_NEG_X];
ok(Wd.inPiece(back, 50, 50, 60) && !Wd.inPiece(back, 150, 50, 60), "…and one rising toward -x the other way round");
ok(Wd.inPiece([0, 0, 0, 100, 200, 100, PLANKS, Wd.SLOPE_POS_Z], 50, 150, 60) && !Wd.inPiece([0, 0, 0, 100, 200, 100, PLANKS, Wd.SLOPE_POS_Z], 50, 50, 60), "…and along z");
ok(Wd.boxVolume(roof) === 1000000 && Wd.boxVolume(roof.slice(0, 7)) === 2000000, "a slope costs half its box");
ok(Wd.boxOk(roof) && !Wd.boxOk(roof.slice(0, 7).concat([5])) && Wd.normalBox(roof.slice(0, 7).concat([0])).length === 7, "shapes 1..4 only; a trailing 0 is the plain box");

// 2
const q = Wd.plotCoords(Wd.firstWave()[44]), top = Wd.column(q.face, q.u0 + 8, q.v0 + 8).top, y0 = (top + 30) * 100;
const piece = [400, 400, y0, 300, 200, 150, PLANKS, Wd.SLOPE_POS_X];
const r = M.meshChunk(q.face, q.u0 / 16, q.v0 / 16, Math.floor(y0 / 1600), null, [piece], 0);
const S = r.pieces;
ok(S && S.idx.length / 3 === 8, `a slope is drawn as five faces, 8 triangles (${S ? S.idx.length / 3 : 0})`);
let outward = 0, tris = 0;
const cen = Wd.posOf(q.face, q.u0 + 4 + 2.0, q.v0 + 4 + 1.0, y0 / 100 + 0.5);
for (let t = 0; t < S.idx.length; t += 3) {
  const P = [0, 1, 2].map((k) => { const i = S.idx[t + k]; return [r.anchor[0] + S.pos[i * 3], r.anchor[1] + S.pos[i * 3 + 1], r.anchor[2] + S.pos[i * 3 + 2]]; });
  const e1 = P[1].map((x, i) => x - P[0][i]), e2 = P[2].map((x, i) => x - P[0][i]);
  const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
  const c = P[0].map((x, i) => (x + P[1][i] + P[2][i]) / 3);
  tris++; if (n[0] * (c[0] - cen[0]) + n[1] * (c[1] - cen[1]) + n[2] * (c[2] - cen[2]) > 0) outward++;
}
ok(outward === tris, `every face of it faces out (${outward} of ${tris})`);

// 3: walk up a 30° roof (the body: the page's four corners at three heights, here against the slope alone)
const HALF = 0.3, TALL = 1.8, C = { GRAV: 26, JUMP: 8.4, STEP: 0.65 }, dt = 1 / 60;
const climbBody = (pieces) => (u, v, h) => {
  if (h < 0) return true;
  for (const du of [-HALF, HALF]) for (const dv of [-HALF, HALF]) for (const dh of [0.01, 0.9, TALL - 0.01])
    if (pieces.some((b) => Wd.inPiece(b, (u + du) * 100, (v + dv) * 100, (h + dh) * 100))) return true;
  return false;
};
const ramp = [200, 0, 0, 400, 300, 230, PLANKS, Wd.SLOPE_POS_X];   // 2.3 m over 4 m: 30°
// (it walks on off the top and drops, so what counts is the height it reached on the way)
let P = { u: 1, v: 1.5, h: 0, vu: 0, vv: 0, vh: 0, ground: true, fly: false }, peak = 0;
for (let f = 0; f < 240; f++) { walk(P, [3, 0], false, dt, climbBody([ramp]), C); peak = Math.max(peak, P.h); }
ok(peak > 1.8, `a walker walks up a roof slope (reached ${peak.toFixed(2)} m of 2.3)`);

// 4
const flight = piecesFor([100, 0, 0, 300, 100, 200, PLANKS], 2, Wd.SLOPE_POS_X);
const rises = flight.map((s) => s[5]).sort((a, b) => a - b), steps = rises.map((h, i) => h - (i ? rises[i - 1] : 0));
ok(flight.length === 10 && Math.max(...steps) <= 21 && flight.every((s) => s[2] === 0 && s[4] === 100), `stairs: ${flight.length} solid steps of ≤ 21 cm rise`);
ok(flight.reduce((a, s) => a + s[3], 0) === 300 && flight.every((s, i) => i === 0 || s[0] >= flight[i - 1][0] + flight[i - 1][3]), "filling the footprint, climbing toward +x");
const down = piecesFor([100, 0, 0, 300, 100, 200, PLANKS], 2, Wd.SLOPE_NEG_X);
ok(down[0][0] + down[0][3] === 400 && down[down.length - 1][0] === 100, "…and a flight facing -x starts at the far end");
P = { u: 0.5, v: 0.5, h: 0, vu: 0, vv: 0, vh: 0, ground: true, fly: false }; peak = 0;
for (let f = 0; f < 240; f++) { walk(P, [2.5, 0], false, dt, climbBody(flight), C); peak = Math.max(peak, P.h); }
ok(peak > 1.9, `a walker climbs the flight (reached ${peak.toFixed(2)} m of 2.0)`);
ok(JSON.stringify(piecesFor([1, 2, 3, 4, 5, 6, PLANKS], 0, 0)) === JSON.stringify([[1, 2, 3, 4, 5, 6, PLANKS]]), "a box is just the box");

// 5
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok(/pieces: shaped\(box, it && it\.unit \? 0 : piece\.shape\)/.test(land) && /const add = pl\.pieces\.map/.test(land) && /KeyG/.test(land),
   "the page places the slope or flight one placement makes (G cycles the shape; a door is never shaped)");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
