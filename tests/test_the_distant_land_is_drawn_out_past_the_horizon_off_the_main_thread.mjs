/*
 * test_the_distant_land_is_drawn_out_past_the_horizon_off_the_main_thread.mjs — "we need to improve drawing of distance
 * without perf impact.. right now it is very stupid and short" (operator 2026-11-23). Measured before: the land ended in a
 * rim 3.8 km out, inside a 4 km far plane, where from 560 m up this planet's horizon is ~10 km off; and the far land was
 * sampled on the main thread, ~9,000 columns every 400 m walked. Now (static/land-far.js):
 *   1. the rings reach past the horizon from 2,000 m up, and past what a range's crest shows over it; the camera's far
 *      plane holds the last ring;
 *   2. the rings tile: a ring's hole is the square of the ring inside it, on its own grid, for any place the player stands
 *      — no gap, no double — and the vertices on the shared edge are the same points;
 *   3. the page never samples the planet for the far land: it queues one job (farland) for a mesher worker, ahead of the
 *      chunks, swaps the pieces it returns together, keeps one job in flight, and rebuilds a ring with the ring inside it;
 *   4. the cost: the far ground and the four rings are under 45,000 triangles; and a whole build's worker time is printed.
 * Run: node tests/test_the_distant_land_is_drawn_out_past_the_horizon_off_the_main_thread.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8"), mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8");
const Far = await import(join(ROOT, "static", "land-far.js")), Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const R = Wd.R0 + Wd.SEA, last = Far.RINGS[Far.RINGS.length - 1];
// 1. reach: the horizon from 2,000 m over the sea, plus how far past it a 250 m crest stands up
const horizon = (h) => Math.sqrt((R + h) ** 2 - R * R), reach = horizon(2000) + horizon(250);
const farPlane = Number((page.match(/const FAR_PLANE = (\d+);/) || [])[1]);
ok(last.half > reach, `the last ring reaches ${last.half} m: past the horizon from 2,000 m up (${Math.round(horizon(2000))} m) and a 250 m crest over it (${Math.round(reach)} m)`);
ok(farPlane > last.half && /new THREE\.PerspectiveCamera\(SET\.fov, innerWidth \/ innerHeight, 0\.08, FAR_PLANE\)/.test(page), `the camera's far plane (${farPlane} m) holds it (was 4,000 m)`);
// 2. tiling: for many places, ring k's hole (ring k-1's square) lies on ring k's own grid, inside ring k
let bad = 0, n = 0;
for (let t = 0; t < 400; t++) {
  const u = 3000 + ((t * 7919.37) % 120000), v = 3000 + ((t * 104729.11) % 120000);
  for (let k = 1; k < Far.RINGS.length; k++) {
    const [au, av] = Far.ringAnchor(k, u, v), [pu, pv] = Far.ringAnchor(k - 1, u, v), { step, half } = Far.RINGS[k], h = Far.RINGS[k - 1].half;
    for (const e of [pu - h - (au - half), pu + h - (au - half), pv - h - (av - half), pv + h - (av - half)]) { n++; if (e % step !== 0 || e <= 0 || e >= 2 * half) bad++; }
  }
}
ok(bad === 0, `a ring's hole is the ring inside it, on the ring's own grid and inside it, at 400 places (${n - bad} of ${n} edges)`);
// …and the shared edge's points are the same: ring 1 at its hole's border against ring 0's outer border
{ const u = 55660, v = 80600, [a0u, a0v] = Far.ringAnchor(0, u, v), [a1u, a1v] = Far.ringAnchor(1, u, v), h0 = Far.RINGS[0].half;
  const r0 = Far.farRing(0, 0, a0u, a0v, null, null, false), r1 = Far.farRing(1, 0, a1u, a1v, [a0u - h0, a0u + h0, a0v - h0, a0v + h0], null, false);
  const at = (r, k, uu, vv) => { const { step, half } = Far.RINGS[k], M = 2 * half / step + 1, i = (uu - (r.au - half)) / step, j = (vv - (r.av - half)) / step, q = j * M + i; return [0, 1, 2].map((d) => r.pos[q * 3 + d] + r.anchor[d]); };
  let worst = 0, m = 0;
  for (let s = -h0; s <= h0; s += Far.RINGS[1].step) for (const [uu, vv] of [[a0u + s, a0v - h0], [a0u + s, a0v + h0], [a0u - h0, a0v + s], [a0u + h0, a0v + s]]) {
    const p = at(r0, 0, uu, vv), q = at(r1, 1, uu, vv); worst = Math.max(worst, Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])); m++;
  }
  ok(worst < 0.01, `the ${m} points ring 0 and ring 1 share are the same points (${worst.toFixed(4)} m apart at most)`); }
// 3. off the main thread
const upd = page.slice(page.indexOf("function updateFar("), page.indexOf("// ---- titles"));
ok(!/Wd\.(column|terrainBlock|treeAt)\(/.test(upd) && /queue\.push\(\{ id: \+\+reqId, k: "D", farland: true/.test(upd) && /if \(m\.farland\) \{[\s\S]{0,200}farJob\(m\)/.test(mesher),
  "the page samples nothing for the far land: it queues one job a mesher worker builds (land-far.js farJob)");
ok(/if \(farPending \|\| !scene\) return;/.test(upd) && /farForce = false; farPending = true;/.test(upd) && /function farDone\(m\) \{\n  farPending = false;/.test(upd)
  && /!queue\[i\]\.farland && !want\.has\(queue\[i\]\.k\)/.test(page) && /if \(k === "D"\) return farDone\(m\);/.test(page),
  "one far job at a time; the chunk sweep never drops it; its result is handed to farDone");
{ const rank = Number((page.match(/const FAR_RANK = (-?[\d.]+);/) || [])[1]);
  ok(rank < 0 && /return q\.farland \? FAR_RANK :/.test(page), `the far job goes before every chunk (rank ${rank}): behind the chunks beside the player a slow page showed the sky through the ground`); }
ok(/redo\.add\(k\); if \(k \+ 1 < Far\.RINGS\.length\) redo\.add\(k \+ 1\);/.test(upd) && /if \(groundDue\) redo\.add\(0\);/.test(upd),
  "a ring is rebuilt with the ring inside it, and ring 0 with the far ground it sinks under");
ok(!/Wd\.column\(/.test(page.slice(page.indexOf("function slow()"), page.indexOf("function slow()") + 800)), "the 4-a-second tick samples nothing for it either");
// 5. from the ground: the planet falls away too fast (R0 ~83 km, the land under ~150 m over the sea) for any range to stand
// over the near land — the rings past HORIZON_FROM are lifted by HORIZON_K of that fall, the near land untouched, the lift
// fading as the eye climbs; then from a meadow by the town the distant land stands over the near skyline
{ const m = page.match(/const HORIZON_K = ([\d.]+), HORIZON_FROM = (\d+), HORIZON_TO = (\d+), HORIZON_EYE = \[(\d+), (\d+)\];/);
  const [K, FROM, TO, E0, E1] = m ? m.slice(1).map(Number) : [];
  ok(!!m && K >= 0.8 && K < 1 && FROM >= Far.FAR_N / 2 * Far.FAR_STEP && TO <= 6000 && E0 < E1 && /m\.positionNode = TSL\.positionLocal\.add\(upv\.mul\(lift\)\)/.test(page),
    `past ${FROM} m the distant land reads as on a planet ${m ? (1 / (1 - K)).toFixed(1) : "?"}x the size (the far ground, to ${Far.FAR_N / 2 * Far.FAR_STEP} m, untouched); lifted less from ${E0} m up, not at all from ${E1} m`);
  // meadow views round the town (every 2 km, 8 ways): how many see the land past 2 km over the near skyline (to 2 km)
  const Fo = await import(join(ROOT, "static", "land-forest.js")), RR = Wd.R0 + Wd.SEA;
  const share = (k) => { let views = 0, wins = 0;
    for (let u = 40000; u <= 70000; u += 2000) for (let v = 65000; v <= 95000; v += 2000) {
      const c0 = Wd.column(0, u, v); if (c0.biome !== "grass" || c0.wild < 1) continue; const eye = c0.height + 1.7;
      for (let a = 0; a < 8; a++) { const yaw = a * Math.PI / 4; let near = -9, far = -9;
        for (let d = 60; d <= 25000; d += d < 2000 ? 30 : 200) { const c = Wd.column(0, Math.round(u + Math.sin(yaw) * d), Math.round(v + Math.cos(yaw) * d)), can = c.top <= Wd.SEA ? 0 : Fo.canopyHeight(c);
          const s = Math.min(1, Math.max(0, (d - FROM) / (TO - FROM))), ang = Math.atan2(c.height + can - d * d / (2 * RR) + k * s * s * (3 - 2 * s) * d * d / (2 * RR) - eye, d);
          if (d < 2000) near = Math.max(near, ang); else far = Math.max(far, ang); }
        views++; if (far > near) wins++; } }
    return wins / views; };
  const s0 = share(0), s1 = share(K);
  ok(s1 > s0 * 1.4, `from the meadows round the town the distant land stands over the near skyline in ${(100 * s1).toFixed(0)} % of views (${(100 * s0).toFixed(0)} % unlifted)`); }
// 4. the cost
{ const u = 55660, v = 80600, t0 = performance.now(), fu = Math.round(u / Far.FAR_STEP) * Far.FAR_STEP, fv = Math.round(v / Far.FAR_STEP) * Far.FAR_STEP;
  const res = Far.farJob({ face: 0, ground: { fu, fv, nearHalf: 96 }, rings: Far.RINGS.map((_, k) => {
    const [au, av] = Far.ringAnchor(k, u, v); if (!k) { const r = Far.FAR_N / 2 * Far.FAR_STEP - Far.RINGS[0].step; return { k, au, av, hole: [fu - r, fu + r, fv - r, fv + r], sink: [fu, fv, r] }; }
    const [pu, pv] = Far.ringAnchor(k - 1, u, v), h = Far.RINGS[k - 1].half; return { k, au, av, hole: [pu - h, pu + h, pv - h, pv + h], sink: null }; }) });
  const ms = performance.now() - t0, tris = res.ground.idx.length / 3 + res.rings.reduce((a, r) => a + r.idx.length / 3, 0);
  ok(tris < 45000, `the far ground and the four rings: ${tris} triangles (a whole build: ${ms.toFixed(0)} ms of one worker)`); }
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
