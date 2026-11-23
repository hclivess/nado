// test_the_wilderness_is_laid_out_as_continents_ranges_and_rivers.mjs — the large-scale world (operator 2026-11-22: "take
// a look at large scale world design because it feels lackluster", then "just build it"). A map of 160 km round the town
// was one even texture: an archipelago of puddle seas (the largest water 9 % of the sea, 696 bodies in 120 km), rock and
// snow in blotches, no river. In the wilderness the land is now laid out as land is (land-world.js largeScale):
//   1. CONTINENTS: across 120 km, the largest water is most of the sea (an ocean) and the largest land most of the land;
//   2. the town stands on its continent, the ocean's coast within 20 km of it;
//   3. RIVERS: where a river's line runs through the lowlands, the ground is water, its banks dry just beside it — and
//      there are kilometres of them round the town;
//   4. RANGES: the ground climbs over SEA + 95 (rock, snow-capped) inside the mountain belts, seldom outside them;
//   5. CLIMATE: snow is toward the pole, not the equator; desert is a few per cent and lies inland, not on a coast;
//   6. owned ground is the planet it was titled on (the fingerprint: test_the_wilderness_rolls_in_hills_and_owned_ground_never_moves).
// Run: node tests/test_the_wilderness_is_laid_out_as_continents_ranges_and_rivers.mjs
import * as W from "../static/land-world.js";
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. continents: a 200 x 200 grid, 600 m apart (120 km), its connected water and land
{ const N = 200, STEP = 600, wet = new Uint8Array(N * N);
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) wet[j * N + i] = W.column(0, 5000 + i * STEP, 15000 + j * STEP).top < W.SEA ? 1 : 0;
  const largest = (want) => { const seen = new Uint8Array(N * N); let best = 0, total = 0;
    for (let s = 0; s < N * N; s++) { if (wet[s] !== want) continue; total++; if (seen[s]) continue; let sz = 0; const st = [s]; seen[s] = 1;
      while (st.length) { const k = st.pop(); sz++; const i = k % N, j = (k - i) / N;
        for (const [a, b] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const x = i + a, y = j + b; if (x < 0 || y < 0 || x >= N || y >= N) continue; const q = y * N + x; if (!seen[q] && wet[q] === want) { seen[q] = 1; st.push(q); } } }
      best = Math.max(best, sz); } return best / total; };
  const sea = largest(1), land = largest(0);
  ok(sea > 0.6 && land > 0.6, `1. across 120 km one ocean holds ${(100 * sea).toFixed(0)} % of the sea (was 9 %) and one landmass ${(100 * land).toFixed(0)} % of the land`); }

// 2. the town on its continent, the coast within reach
{ const t = W.largeScaleAt(0, 55050, 79990); let coast = null;
  for (let r = 1000; r <= 20000 && coast === null; r += 1000) for (let a = 0; a < 48; a++) if (W.largeScaleAt(0, 55050 + r * Math.cos(a * Math.PI / 24), 79990 + r * Math.sin(a * Math.PI / 24)).cont < 0) { coast = r; break; }
  ok(t.cont > 0.1 && coast !== null, `2. the town stands ${t.cont.toFixed(2)} inland on its continent, the ocean ${coast} m off`); }

// 3. rivers round the town: points on a river's line in the lowlands are water, 60 m to the side is dry
{ let seed = 5; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  let line = 0, water = 0, dry = 0, side = 0;
  for (let i = 0; i < 400000 && line < 300; i++) {
    const u = Math.floor(40000 + rnd() * 30000), v = Math.floor(65000 + rnd() * 30000);
    if (W.wildMask(0, u, v) < 1) continue;
    const ls = W.largeScaleAt(0, u, v); if (ls.river > 0.0008 || ls.cont < 0.06) continue;
    const c = W.column(0, u, v); if (c.top > W.SEA + 40) continue;          // (a river fades out into a range)
    line++; if (c.top < W.SEA) water++;
    // 60 m across the river's line, whichever way it runs: the further of the two sides
    const far = [[60, 0], [0, 60], [-60, 0], [0, -60]].map(([a, b]) => W.largeScaleAt(0, u + a, v + b).river).reduce((m, x, k, A) => (x > A[m] ? k : m), 0);
    const [a, b] = [[60, 0], [0, 60], [-60, 0], [0, -60]][far]; side++; if (W.column(0, u + a, v + b).top >= W.SEA) dry++;
  }
  ok(line >= 100 && water / line > 0.9 && dry / side > 0.8, `3. ${line} points on rivers' lines round the town: ${(100 * water / line).toFixed(0)} % water, ${(100 * dry / side).toFixed(0)} % dry ground 60 m to the side`); }

// 4. ranges: high ground inside the belts
{ let seed = 9; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  let hiIn = 0, hiOut = 0, inBelt = 0, outBelt = 0, hiNone = 0, none = 0;
  for (let i = 0; i < 30000; i++) {
    const u = Math.floor(10000 + rnd() * 110000), v = Math.floor(10000 + rnd() * 110000); if (W.wildMask(0, u, v) < 1) continue;
    const ls = W.largeScaleAt(0, u, v); if (ls.cont < 0.12) continue;
    const high = W.column(0, u, v).top > W.SEA + 95, belt = ls.belt > 0.2;
    if (belt) { inBelt++; if (high) hiIn++; } else { outBelt++; if (high) hiOut++; }
    if (ls.belt < 0.05) { none++; if (high) hiNone++; }   // no range at all (a range rises from belt 0.05)
  }
  // …and outside the belts a hill stays under the rock line: a snow-capped knoll by the town (2.7 % of that land) was a
  // lowland hill, not a range — at most 1 % where no range rises
  ok(hiNone / none < 0.01, `4'. where no range rises ${(100 * hiNone / none).toFixed(1)} % of the land is rock over SEA + 95 (a hill wears woods)`);
  ok(hiIn / inBelt > 5 * (hiOut / outBelt) && hiIn / inBelt > 0.05, `4. inland, ${(100 * hiIn / inBelt).toFixed(1)} % of a mountain belt stands over SEA + 95, ${(100 * hiOut / outBelt).toFixed(1)} % outside the belts`); }

// 5. climate: snow toward the pole; desert inland and rare
{ let seed = 13; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const snow = [0, 0], all = [0, 0]; let desert = 0, land = 0, desertCoast = 0;
  for (let i = 0; i < 30000; i++) {
    const u = Math.floor(rnd() * W.W), v = Math.floor(rnd() * W.W); if (W.wildMask(0, u, v) < 1) continue;
    const c = W.column(0, u, v); if (c.top < W.SEA) continue; land++;
    const polar = Math.abs(W.dirOf(0, u, v)[1]) > 0.5 ? 1 : 0; all[polar]++; if (c.biome === "snow") snow[polar]++;
    if (c.biome === "desert") { desert++; if (W.largeScaleAt(0, u, v).cont < 0.05) desertCoast++; }
  }
  ok(snow[1] / all[1] > 4 * (snow[0] / all[0]), `5. snow on ${(100 * snow[1] / all[1]).toFixed(0)} % of the land toward the pole, ${(100 * snow[0] / all[0]).toFixed(1)} % toward the equator`);
  ok(desert / land < 0.06 && desertCoast / Math.max(1, desert) < 0.1, `…desert on ${(100 * desert / land).toFixed(1)} % of the land, ${(100 * desertCoast / Math.max(1, desert)).toFixed(0)} % of it by a coast`); }

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
