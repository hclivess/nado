/*
 * test_the_sun_is_a_real_star_at_a_real_distance_and_the_planet_turns_under_it.mjs — static/land-cosmos.js, the sky as a
 * real place ("make sun a real object in a real distance, we are going interstellar in the end", operator 2026-11-06):
 *   1. the star is real-sized at a real distance: ~0.8 AU in metres, and its apparent size follows from the two (asin of
 *      radius over distance), about 0.6° as the Sun is from Earth; its light falls off with the square of distance;
 *   2. day and night are the planet TURNING: a place on the equator sees the star rise and set once per DAY_S, and the
 *      star's direction is a unit vector in the planet's own frame;
 *   3. the orbit is real: the planet moves around the star over its year (its position after half a year is opposite),
 *      and the axial tilt makes seasons — the noon sun stands higher over one hemisphere half a year apart;
 *   4. the fixed stars' rotation is a proper rotation (orthonormal) and the inverse of the planet's turn;
 *   5. the page draws the star from this module, at its true angle and size, not a light on a circle.
 *
 * Run: node tests/test_the_sun_is_a_real_star_at_a_real_distance_and_the_planet_turns_under_it.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const C = await import(join(ROOT, "static", "land-cosmos.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const deg = (r) => (r * 180) / Math.PI;
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// 1. a real star at a real distance
const s0 = C.sunFrom(0, 0);
ok(Math.abs(s0.distance / C.AU - 0.8) < 1e-9, `the star is ${(s0.distance / C.AU).toFixed(3)} AU (${(s0.distance / 1e9).toFixed(1)} million km) away`);
ok(Math.abs(s0.angularRadius - Math.asin(C.SYSTEMS[0].star.radius / s0.distance)) < 1e-15 && deg(2 * s0.angularRadius) > 0.5 && deg(2 * s0.angularRadius) < 0.7,
   `its apparent size is what its radius at that distance makes it: ${deg(2 * s0.angularRadius).toFixed(3)}°`);
ok(Math.abs(s0.flux - C.SYSTEMS[0].star.luminosity / 0.64) < 1e-12, `its light falls off with the square of distance (flux ${s0.flux.toFixed(3)} of the Sun at 1 AU)`);

// 2. day and night: the planet turns
const eq = [1, 0, 0];                                   // a place on the equator (the planet frame's +x)
const elev = (t) => dot(C.sunFrom(0, t).dir, eq);
let rises = 0, prev = elev(0);
for (let k = 1; k <= 400; k++) { const e = elev((k * C.DAY_S) / 400); if (prev <= 0 && e > 0) rises++; prev = e; }
ok(rises === 1, `a place on the equator sees the star rise once per ${C.DAY_S / 60}-minute day (${rises})`);
ok(Math.abs(Math.hypot(...C.sunFrom(0, 1234.5).dir) - 1) < 1e-12, "the star's direction is a unit vector in the planet's frame");
const later = C.sunFrom(0, C.DAY_S * 0.5).dir;
ok(dot(later, s0.dir) < 0, "half a day later the star stands on the other side of the planet");

// 3. the orbit and the seasons
const pl = C.SYSTEMS[0].planets[0], year = pl.yearDays * pl.day;
const p0 = C.planetPosition(pl, 0), p1 = C.planetPosition(pl, year / 2);
ok(Math.abs(dot(p0, p1) / (pl.a * pl.a) + 1) < 1e-9, "after half a year the planet is on the opposite side of its star");
const noonHigh = (t0) => { let best = -2; for (let k = 0; k < 200; k++) best = Math.max(best, dot(C.sunFrom(0, t0 + (k * C.DAY_S) / 200).dir, [0, 0.7071, 0.7071])); return best; };
const nA = noonHigh(year / 4), nB = noonHigh((3 * year) / 4);
ok(Math.abs(nA - nB) > 0.2, `the tilt makes seasons: the noon sun at 45° north stands ${deg(Math.asin(nA)).toFixed(0)}° in one season, ${deg(Math.asin(nB)).toFixed(0)}° half a year later`);

// 4. the fixed stars
const R = C.skyRotation(0, 777), M = C.planetToInertial(pl, 777);
let orth = 0, inv = 0;
for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) {
  orth = Math.max(orth, Math.abs(R[r * 3] * R[c * 3] + R[r * 3 + 1] * R[c * 3 + 1] + R[r * 3 + 2] * R[c * 3 + 2] - (r === c ? 1 : 0)));
  inv = Math.max(inv, Math.abs(R[r * 3] * M[c] + R[r * 3 + 1] * M[3 + c] + R[r * 3 + 2] * M[6 + c] - (r === c ? 1 : 0)));
}
ok(orth < 1e-12 && inv < 1e-12, "the fixed stars turn by a proper rotation, the inverse of the planet's own");

// 5. the page draws this star
const land = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok(/Cosmos\.sunFrom\(/.test(land) && /Math\.tan\(star\.angularRadius\)/.test(land) && /Cosmos\.skyRotation\(/.test(land),
   "the page places the star by its real direction and draws it at its true apparent size, the stars by the planet's turn");
ok(!/new THREE\.Vector3\(Math\.cos\(ang\), 0\.35, Math\.sin\(ang\)\)/.test(land), "no light circling on a fixed path anymore");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
