/*
 * test_the_planet_is_a_physical_body_whose_gravity_orbits_and_air_follow_from_its_size_and_pull.mjs — the planet's
 * physical properties (operator 2026-11-11: "we need proper planetary physical properties like in Kerbal space").
 * static/land-planet.js, land research planet/:
 *   1. its mass follows from its radius and surface gravity by Newton's law (G = 6.67430e-11, Gravitational constant l.9),
 *      and so its density — stated, 76 times Earth's (5,513 kg/m³, Earth l.51);
 *   2. gravity falls as 1/r² with height; escape speed is √2 times the circular speed; the synchronous orbit's period is
 *      one turn of the planet; the satellites' orbit (land-cosmos.js) is the one two orbits a day asks;
 *   3. the air is the 1976 standard atmosphere (International Standard Atmosphere, the layer table): 101,325 Pa,
 *      288.15 K and 1.225 kg/m³ at sea level, each layer's base temperature and pressure at its share of the height,
 *      thinner with height without a step, and vacuum from ATM_TOP up — above it the satellites fly;
 *   4. drag is ½ρu²c_dA (Drag equation l.6) and is nothing above the air; an engine's Isp runs from its sea-level figure
 *      at sea-level pressure to its vacuum figure in vacuum.
 *
 * Run: node tests/test_the_planet_is_a_physical_body_whose_gravity_orbits_and_air_follow_from_its_size_and_pull.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const P = await import(join(ROOT, "static", "land-planet.js"));
const C = await import(join(ROOT, "static", "land-cosmos.js"));
const W = await import(join(ROOT, "static", "land-world.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const near = (a, b, rel = 1e-9) => Math.abs(a - b) <= rel * Math.abs(b);

// 1. the body
const pos = W.posOf(0, 0, 0, 0);
ok(P.RADIUS === Math.round(Math.hypot(...pos)) && P.RADIUS === C.SYSTEMS[0].planets[0].radius && P.SURFACE_G === R.flight.g && P.DAY_S === C.DAY_S,
  "its radius, gravity and day are the world's own (land-world R0, land-recipes flight.g, land-cosmos)");
ok(near(P.MASS, (9.8 * 83443 ** 2) / 6.6743e-11), `its mass is g R² / G: ${P.MASS.toExponential(3)} kg`);
ok(near(P.DENSITY, P.MASS / ((4 / 3) * Math.PI * 83443 ** 3)) && Math.round(P.DENSITY / 5513) === 76, `its density is mass over volume: ${Math.round(P.DENSITY)} kg/m³, 76 times Earth's 5,513`);
// 2. gravity and orbits
ok(near(P.gravityAt(0), 9.8) && near(P.gravityAt(83443), 9.8 / 4), "gravity falls as 1/r²: a quarter at one radius up");
ok(near(P.escapeSpeed(0), Math.SQRT2 * P.orbitSpeed(0)) && Math.round(P.escapeSpeed(0)) === 1279, `escape speed is √2 times the circular speed: ${P.escapeSpeed(0).toFixed(1)} m/s`);
ok(near(P.orbitPeriod(P.SYNC_HEIGHT), P.DAY_S, 1e-9), `the synchronous orbit, ${(P.SYNC_HEIGHT / 1000).toFixed(1)} km up, goes round once a day`);
ok(near(P.orbitPeriod(C.ORBIT.r - P.RADIUS), C.ORBIT.T, 1e-4), "the satellites' orbit goes round twice a day (land-cosmos ORBIT)");
// 3. the air
const sea = P.airAt(0);
ok(sea.p === 101325 && sea.T === 288.15 && Math.abs(sea.rho - 1.225) < 5e-4, `sea level is the standard's: ${sea.p} Pa, ${sea.T} K, ${sea.rho.toFixed(4)} kg/m³`);
const layers = [[11000, 216.65, 22632], [20000, 216.65, 5474.9], [32000, 228.65, 868.02], [47000, 270.65, 110.91], [51000, 270.65, 66.939], [71000, 214.65, 3.9564]];
ok(layers.every(([H, T, p]) => { const a = P.airAt((H / 86000) * P.ATM_TOP); return Math.abs(a.T - T) < 0.01 && Math.abs(a.p - p) / p < 2e-3; }),
  "each layer of the standard atmosphere is met at its share of the air's height, its base temperature and pressure");
let smooth = true, prev = P.airAt(0).p;
for (let h = 50; h < P.ATM_TOP; h += 50) { const p = P.airAt(h).p; if (!(p < prev) || p / prev < 0.97) smooth = false; prev = p; }
ok(smooth && P.airAt(P.ATM_TOP - 1).p < 1, `the air thins with every metre, no step anywhere, to ${P.airAt(P.ATM_TOP - 1).p.toFixed(2)} Pa at its top`);
ok(P.airAt(P.ATM_TOP).rho === 0 && P.airAt(C.ORBIT.r - P.RADIUS).rho === 0 && P.ATM_TOP < C.ORBIT.r - P.RADIUS, "vacuum from the air's top up — the satellites fly above it");
// 4. drag and engines
ok(near(P.dragAt(0, 100, 1.28, 2), 0.5 * sea.rho * 100 * 100 * 1.28 * 2) && P.dragAt(P.ATM_TOP + 1, 700, 1.28, 2) === 0, "drag is ½ρu²c_dA, and none above the air");
ok(P.ispAt(101325, 366, 452.3) === 366 && P.ispAt(0, 366, 452.3) === 452.3, "an engine gives its sea-level Isp at sea-level pressure and its vacuum Isp in vacuum");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
