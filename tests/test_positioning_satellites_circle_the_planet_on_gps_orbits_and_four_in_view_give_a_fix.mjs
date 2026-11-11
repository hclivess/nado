/*
 * test_positioning_satellites_circle_the_planet_on_gps_orbits_and_four_in_view_give_a_fix.mjs — FINDING THE WAY, rung 5
 * (#173, doc/land-navigation.md 1.6; operator 2026-11-10: "requires launching orbital real physical gps satellites into
 * orbit"). static/land-cosmos.js satPosition / satsInView:
 *   1. a satellite keeps its orbit's radius, 135,520 m — two orbits a day round a planet of 83,443 m with g = 9.8;
 *   2. two orbits to the planet's one turn: a day later it is over the same ground (GPS's repeating track, l.232);
 *   3. its plane is inclined 55° (l.230): it reaches 55° of latitude and no further; the six planes' nodes are 60° apart;
 *   4. "in view" is above the local horizon: one overhead is, one over the far side is not;
 *   5. coverage as it measures on this planet: four satellites give a fix almost nowhere, twenty-four almost everywhere,
 *      never fewer than three in view — the orbit is 1.62 planet radii out (GPS's is 4.18), so each sees less of it.
 *
 * Run: node tests/test_positioning_satellites_circle_the_planet_on_gps_orbits_and_four_in_view_give_a_fix.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const C = await import(join(ROOT, "static", "land-cosmos.js"));
const W = await import(join(ROOT, "static", "land-world.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1. the orbit
const GM = 9.8 * 83443 ** 2, T = C.DAY_S / 2, r = Math.cbrt((GM * T * T) / (4 * Math.PI ** 2));
ok(Math.abs(r - C.ORBIT.r) < 1 && C.ORBIT.T === T && JSON.stringify(C.ORBIT) === JSON.stringify(R.rocket.orbit), `two orbits a day round this planet is a radius of ${r.toFixed(0)} m — the constellation's, and the world server's`);
ok([0, 7, 23].every((n) => [0, 333, 1111].every((t) => Math.abs(Math.hypot(...C.satPosition(n, t)) - C.ORBIT.r) < 1e-6)), "every satellite keeps that radius");
// 2. the daily repeat
const a = C.satPosition(5, 1234), b = C.satPosition(5, 1234 + C.DAY_S);
ok(Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) < 1e-6, "a day later it is over the same ground");
const half = C.satPosition(5, 1234 + C.ORBIT.T);
ok(Math.hypot(a[0] - half[0], a[1] - half[1], a[2] - half[2]) > 1000, "…but not after one orbit: the planet has turned half way under it");
// 3. inclination and planes
let maxY = 0; for (let t = 0; t < C.ORBIT.T; t += 2) maxY = Math.max(maxY, Math.abs(C.satPosition(0, t)[1]));
ok(Math.abs(maxY / C.ORBIT.r - Math.sin(55 * Math.PI / 180)) < 1e-3, `it reaches 55° of latitude and no further (${(Math.asin(maxY / C.ORBIT.r) * 180 / Math.PI).toFixed(2)}°)`);
// the node of plane k: where its satellite crosses the equator going north, in the non-spinning frame (t chosen so the
// planet has turned a whole number of times: t = 0)
const nodeOf = (n) => { for (let t = 0; t < 2 * C.ORBIT.T; t += 0.5) { const p = C.satPosition(n, t), q = C.satPosition(n, t + 0.5); if (p[1] < 0 && q[1] >= 0) return [p, t]; } };
const ang = (n) => { const [p, t] = nodeOf(n), th = (2 * Math.PI * t) / C.DAY_S, x = Math.cos(th) * p[0] + Math.sin(th) * p[2], z = -Math.sin(th) * p[0] + Math.cos(th) * p[2]; return Math.atan2(z, x); };
const d01 = ((ang(1) - ang(0)) * 180 / Math.PI + 360) % 360;
ok(Math.abs(d01 - 60) < 0.5, `the planes' nodes are 60° apart round the equator (${d01.toFixed(2)}°)`);
// 4. in view
const top = C.satPosition(0, 0), at = top.map((x) => (x / C.ORBIT.r) * 83443);
ok(C.satsInView(1, at, 0).length === 1 && C.satsInView(1, at.map((x) => -x), 0).length === 0, "a satellite overhead is in view; from the far side of the planet it is not");
// 5. coverage
const share = (n) => { let k = 0, all = 0; for (let f = 0; f < 6; f++) for (let i = 0; i < 6; i++) for (let j = 0; j < 6; j++) { const p = W.posOf(f, (i + 0.5) * W.W / 6, (j + 0.5) * W.W / 6, 140); for (let t = 0; t < C.DAY_S; t += 120) { all++; if (C.satsInView(n, p, t).length >= C.FIX_SATS) k++; } } return k / all; };
const s4 = share(4), s24 = share(24);
let least = 99; for (let f = 0; f < 6; f++) for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) { const p = W.posOf(f, (i + 0.5) * W.W / 8, (j + 0.5) * W.W / 8, 140); for (let t = 0; t < C.DAY_S; t += 60) least = Math.min(least, C.satsInView(24, p, t).length); }
ok(s4 < 0.02, `four satellites give a fix almost nowhere (${(100 * s4).toFixed(1)} % of places and times)`);
ok(s24 > 0.9 && least >= 3, `twenty-four give one almost everywhere (${(100 * s24).toFixed(1)} %), never fewer than ${least} in view`);

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
