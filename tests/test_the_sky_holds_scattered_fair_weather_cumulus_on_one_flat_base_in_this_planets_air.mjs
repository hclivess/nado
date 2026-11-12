/*
 * test_the_sky_holds_scattered_fair_weather_cumulus_on_one_flat_base_in_this_planets_air.mjs — #183 step 2 (operator
 * 2026-11-11, beside a concept picture of a meadow under scattered fair-weather clouds: "compared to this our game looks
 * like from 1996"; the sky had no cloud at all). static/land-clouds.js is the definition the page's GPU march repeats;
 * this measures it, never assumes it:
 *   1. its real numbers are the cited ones, moved into this planet's air the way land-planet.js airAt moves the air;
 *   2. the sky is SCATTERED: 3–4 oktas of the planet's base shell is under cloud (Okta l.19) — not a clear sky, not
 *      overcast — and no hemisphere is bare (the field is not one heap the size of a continent);
 *   3. every heap stands on the one flat base and under the layer's top: no cloud below the base or above the top, and
 *      every cloudy column's cloud begins within the base's soft underside;
 *   4. heaps are wider than they are tall (Cumulus humilis l.15), measured from above as a photograph would see them;
 *   5. the field drifts at the cited breeze, from the wall clock alone (every player sees one sky), and a stamp in
 *      seconds since the epoch gives the same turn on every machine;
 *   6. the march sees what the photographs show: a ray up under a heap is hidden by it, a ray into the ground or into
 *      the clear sky meets nothing, a heap's sunlit top is brighter than its shaded belly (Jakarta: a grey belly, never
 *      black), and the far clouds pale toward the horizon's colour;
 *   7. the sky map's bent rows come back to the elevation they were made from.
 * Run: node tests/test_the_sky_holds_scattered_fair_weather_cumulus_on_one_flat_base_in_this_planets_air.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const C = await import(join(ROOT, "static", "land-clouds.js"));
const Wd = await import(join(ROOT, "static", "land-world.js"));
const Pl = await import(join(ROOT, "static", "land-planet.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const vol = C.noiseVolume();

// 1. the real numbers, and where they land in this air
ok(C.REAL.base >= 500 && C.REAL.base <= 1500, `the base is a real fair-weather base: ${C.REAL.base} m (Cumulus cloud l.48: 500–1500 m)`);
ok(C.REAL.wind >= 3.4 && C.REAL.wind <= 5.4, `the drift is a gentle breeze: ${C.REAL.wind} m/s (Beaufort scale l.64: 3.4–5.4)`);
ok(Math.abs(C.AIR - Pl.ATM_TOP / Pl.ISA_TOP) < 1e-12 && Math.abs(C.BASE - C.REAL.base * C.AIR) < 1e-9 && Math.abs(C.WIND - C.REAL.wind * C.AIR) < 1e-9,
  `the layer is in this planet's air: base ${C.BASE.toFixed(0)} m, breeze ${C.WIND.toFixed(2)} m/s (× ${C.AIR.toFixed(3)}, as airAt fits 86 km under ${Pl.ATM_TOP} m)`);
ok(Math.abs(C.RB - (Wd.R0 + Wd.SEA + C.BASE)) < 1e-6 && C.RT - C.RB === C.THICK, "the base and top radii stand over the sea");
// the base is in the air the planet actually has: the pressure there is the real pressure at the real base
const real = Pl.airAt(C.BASE).p;
ok(real > 85000 && real < 90000, `the base's pressure is the real one at ${C.REAL.base} m (${Math.round(real)} Pa; the 1976 standard: ~87,700 Pa)`);

// 2. scattered cover over the whole planet, and on both hemispheres
const N = 60000;
let hit = 0, north = 0, nN = 0;
const pts = [];
for (let i = 0; i < N; i++) {
  const z = 1 - (2 * (i + 0.5)) / N, a = i * 2.399963229728653, r = Math.sqrt(1 - z * z), p = [Math.cos(a) * r * C.RB, z * C.RB, Math.sin(a) * r * C.RB];
  const t = C.heapTop(vol, p) > 0.08;            // a heap at least a 13th of the layer tall: a cloud an eye would count
  if (t) hit++;
  if (z > 0) { nN++; if (t) north++; }
  if (i % 20 === 0) pts.push(p);
}
const oktas = (8 * hit) / N, oN = (8 * north) / nN, oS = (8 * (hit - north)) / (N - nN);
ok(oktas >= C.REAL.oktas[0] && oktas <= C.REAL.oktas[1], `the sky is scattered: ${oktas.toFixed(2)} oktas of the base under cloud (SCT: 3–4)`);
ok(oN > 2.5 && oS > 2.5 && oN < 5 && oS < 5, `…on both hemispheres (${oN.toFixed(2)} and ${oS.toFixed(2)} oktas)`);

// 3. one flat base, one top
let under = 0, over = 0, lowest = 0, cloudy = 0;
const len = (p) => Math.hypot(p[0], p[1], p[2]), at = (p, R) => { const k = R / len(p); return [p[0] * k, p[1] * k, p[2] * k]; };
for (const p of pts) {
  if (C.density(vol, at(p, C.RB - 0.5)) > 0) under++;
  if (C.density(vol, at(p, C.RT + 0.5)) > 0) over++;
  if (C.heapTop(vol, p) < 0.3) continue;          // a heap a third of the layer tall or more
  cloudy++;
  let first = -1;
  for (let h = 0; h < C.THICK; h += 1) if (C.body(vol, at(p, C.RB + h)) > 0.05) { first = h; break; }
  if (first >= 0 && first <= C.K.foot * C.THICK + 2) lowest++;
}
ok(under === 0 && over === 0, `no cloud below the base or above the top (${pts.length} columns: ${under} under, ${over} over)`);
ok(cloudy > 100 && lowest === cloudy, `every heap stands on the one flat base: ${lowest} of ${cloudy} begin within the base's ${(C.K.foot * C.THICK).toFixed(0)} m underside`);

// 4. wider than tall, measured from above: the runs of cloud along lines through the field, and the heaps' heights
const fr = Wd.frameOf(0, 54260.5, 80600.5), widths = [], tops = [];
for (let line = 0; line < 40; line++) {
  let run = 0, top = 0;
  for (let e = -12000; e <= 12000; e += 10) {
    const n = (line - 20) * 600, p = [0, 1, 2].map((i) => fr.up[i] * C.RB + fr.east[i] * e + fr.north[i] * n), t = C.heapTop(vol, p);
    if (t > 0.08) { run += 10; top = Math.max(top, t); }
    else if (run) { if (run >= 40) { widths.push(run); tops.push(top * C.THICK); } run = 0; top = 0; }
  }
}
const med = (a) => a.slice().sort((x, y) => x - y)[a.length >> 1];
ok(widths.length > 100 && med(widths) > 1.3 * med(tops), `heaps are wider than they are tall: ${widths.length} heaps, median ${med(widths)} m across, ${med(tops).toFixed(0)} m tall`);
ok(med(widths) >= 100 && med(widths) <= 600, `…and a heap is a few fields wide, as the Brittany photograph shows (median ${med(widths)} m)`);

// 5. the drift
const t0 = 3600, d0 = C.drift(t0), ang = Math.atan2(d0[1], d0[0]);                   // (an hour: less than one turn)
ok(Math.abs(ang * C.RB - t0 * C.WIND) < 1e-6, `the field turns at the breeze: ${(ang * C.RB).toFixed(1)} m along the base's equator in ${t0} s at ${C.WIND.toFixed(2)} m/s`);
const late = 86400 * 365 * 30, dl = C.drift(late), want = ((late * C.WIND) / C.RB) % (2 * Math.PI);
ok(Math.abs(Math.atan2(dl[1], dl[0]) - (want > Math.PI ? want - 2 * Math.PI : want)) < 1e-9, "thirty years on, the turn is still exact (reduced in doubles before it is a cosine)");
ok(JSON.stringify(C.drift(t0)) === JSON.stringify(d0), "the same second gives the same sky");
const back = C.undrift(C.undrift([1, 2, 3], d0), [d0[0], -d0[1]]);
ok(Math.hypot(back[0] - 1, back[1] - 2, back[2] - 3) < 1e-12, "the drift is a turn about the planet's axis (undone exactly by the opposite turn)");

// 6. what the march sees
let col = null;                                   // a column under a full heap near the viewpoint
for (let n = -3000; n < 3000 && !col; n += 25) for (let e = -3000; e < 3000 && !col; e += 25) {
  const p = [0, 1, 2].map((i) => fr.up[i] * C.RB + fr.east[i] * e + fr.north[i] * n);
  if (C.heapTop(vol, p) > 0.85 && C.heapTop(vol, [0, 1, 2].map((i) => p[i] + fr.east[i] * 30)) > 0.85) col = p;
}
ok(!!col, "a full heap stands within 3 km of the viewpoint");
if (col) {
  const up = col.map((x) => x / C.RB), ground = up.map((x) => x * (Wd.R0 + Wd.SEA + 30)), skyEye = up.map((x) => x * (C.RT + 400));
  const L = C.light(up, [2.4, 2.3, 2.1], [0.47, 0.67, 0.86], [0.03, 0.16, 0.58]), dr = [1, 0];
  const lum = (m) => (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / Math.max(m[3], 1e-6);
  const belly = C.march(vol, ground, up, L, dr), topv = C.march(vol, skyEye, up.map((x) => -x), L, dr);
  ok(belly[3] > 0.9, `a ray straight up under a heap is hidden by it (alpha ${belly[3].toFixed(3)})`);
  ok(topv[3] > 0.9 && lum(topv) > 1.5 * lum(belly), `the sun-lit top is brighter than the shaded belly (${lum(topv).toFixed(2)} against ${lum(belly).toFixed(2)})`);
  ok(lum(belly) > 0.15, `…and the belly is grey, not black (${lum(belly).toFixed(2)}; the sky's light reaches it)`);
  const down = C.march(vol, ground, up.map((x) => -x), L, dr);
  ok(down[3] === 0, "a ray into the ground meets no cloud");
  // the far clouds pale: the cloud colour a long ray brings back is nearer the haze than a short one
  const eye = Wd.posOf(0, 54260.5, 80600.5, 126), e0 = Wd.frameOf(0, 54260.5, 80600.5);
  let near = null, farc = null;
  for (let k = 0; k < 720 && (!near || !farc); k++) {
    const az = (k / 720) * 2 * Math.PI;
    for (const [el, slot] of [[1.2, "near"], [0.04, "far"]]) {
      const d = [0, 1, 2].map((i) => e0.up[i] * Math.sin(el) + (e0.east[i] * Math.sin(az) + e0.north[i] * Math.cos(az)) * Math.cos(el));
      const m = C.march(vol, eye, d, L, dr);
      if (m[3] > 0.6) { const c = m.slice(0, 3).map((x) => x / m[3]); if (slot === "near" && !near) near = c; if (slot === "far" && !farc) farc = c; }
    }
  }
  const off = (c) => Math.hypot(c[0] - L.haze[0], c[1] - L.haze[1], c[2] - L.haze[2]);
  ok(near && farc && off(farc) < 0.5 * off(near), `the far clouds pale toward the horizon's colour (${farc && off(farc).toFixed(2)} from it, overhead ${near && off(near).toFixed(2)})`);
}
ok(C.span(C.RT + 50, 0.5) === null && C.span(C.RB - 200, 0.3) !== null && C.span(C.RB + 10, 0.9)[0] === 0, "a ray's stretch in the layer: none up from above it, from the base up from below, from the eye inside it");

// 7. the sky map's rows
let worst = 0;
for (let v = 0; v <= 1; v += 1 / 512) worst = Math.max(worst, Math.abs(C.mapV(C.mapEl(v)) - v));
ok(worst < 1e-9, `the map's bent rows come back to their elevation (worst ${worst.toExponential(1)})`);
const dv = (el) => (C.mapV(el + 1e-4) - C.mapV(el)) / 1e-4;
ok(dv(0.01) > 1.9 * dv(1.5), `the map spends more rows a degree at the horizon than at the zenith (${(dv(0.01) / dv(1.5)).toFixed(2)}×)`);

// ---- 8. the sun under the clouds (#183 step 4) --------------------------------------------------------------------------
{
  const upv = col ? col.map((x) => x / C.RB) : null;
  if (upv) {
    const ground = upv.map((x) => x * (Wd.R0 + Wd.SEA + 30)), dr = [1, 0];
    const under = C.sunLit(vol, ground, upv, dr);                        // the sun straight overhead, a full heap over the player
    ok(under < 0.3, `under a full heap with the sun overhead ${(100 * under).toFixed(0)} % of the direct sun reaches the ground (a cumulus blocks it; the page keeps a floor and the sky's own light)`);
    // clear sky: a ground point whose sun ray crosses the layer where no heap stands (the ray's own stretch, span)
    let clear = null;
    for (let az = 0; az < 2 * Math.PI && clear === null; az += 0.15) for (let k = 1; k < 8 && clear === null; k++) {
      const d0 = [0, 1, 2].map((i) => fr.up[i] * 0.8 + (fr.east[i] * Math.sin(az) + fr.north[i] * Math.cos(az)) * 0.6), dl = Math.hypot(...d0), d = d0.map((x) => x / dl);
      const q = [0, 1, 2].map((i) => col[i] + fr.east[i] * 700 * k * Math.sin(az + k) + fr.north[i] * 700 * k * Math.cos(az + k)), ql = Math.hypot(...q);
      const g = q.map((x) => (x / ql) * (Wd.R0 + Wd.SEA + 30)), r = Math.hypot(...g), mu = (g[0] * d[0] + g[1] * d[1] + g[2] * d[2]) / r, sp = C.span(r, mu);
      if (!sp) continue;
      const free = [0, 0.25, 0.5, 0.75, 1].every((f) => C.heapTop(vol, [0, 1, 2].map((i) => g[i] + d[i] * (sp[0] + (sp[1] - sp[0]) * f))) === 0);
      if (free) clear = C.sunLit(vol, g, d, dr);
    }
    ok(clear === 1, `under clear sky all of it does (${clear})`);
    ok(C.sunLit(vol, ground, upv.map((x) => -x), dr) === 1, "with the sun below the horizon nothing is shaded (the night is the night)");
  }
}

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
