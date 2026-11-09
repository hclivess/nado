/*
 * test_a_craft_flies_by_its_thrust_against_its_weight.mjs — static/land-flight.js, the physics the pilot's page flies a
 * craft by (#147, "you must add actual physics like engines and gravity to the game and build a real usable xfighter",
 * operator 2026-11-09), with the numbers from static/land-recipes.json "flight":
 *   1. a craft whose thrusters beat its weight climbs on Up, hovers when let go (the climb damps out), sinks on Down;
 *   2. one too heavy for its thrust never leaves the ground, whatever the pilot asks — and gravity brings a craft down;
 *   3. forward pushes along the facing; it never passes the top speed; drag slows it;
 *   4. the ground holds it: it never sinks below the surface by its lowest piece, and it lands at rest.
 *
 * Run: node tests/test_a_craft_flies_by_its_thrust_against_its_weight.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const { craftStep, flightOf } = await import(join(ROOT, "static", "land-flight.js"));
const F = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8")).flight;
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

const flat = () => 100;                                         // flat ground at 100 m
const craft = (mass, thrusters) => ({ pose: [0, 500, 500, 100.5, 0], vel: [0, 0, 0], mass, thrust: thrusters * F.thrust_kn, bottom: -0.5, grounded: true });
const run = (c, input, secs) => { for (let t = 0; t < secs; t += 0.05) craftStep(c, input, 0.05, F, flat); return c; };

// 1. a light fighter: 2 t, 2 thrusters (60 kN against 19.6 kN)
const x = craft(2, 2);
ok(flightOf(F, x.mass, x.thrust).lifts, `two thrusters lift 2 t (${x.thrust} kN against ${(x.mass * F.g).toFixed(1)} kN)`);
run(x, { up: true }, 2);
const climbed = x.pose[3];
ok(climbed > 110 && !x.grounded, `Up climbs (to ${climbed.toFixed(1)} m in 2 s)`);
run(x, {}, 3);
ok(Math.abs(x.vel[2]) < 0.5 && x.pose[3] > climbed, `let go, it hovers — the climb damps out (vertical speed ${x.vel[2].toFixed(2)} m/s at ${x.pose[3].toFixed(1)} m)`);
const hov = x.pose[3];
run(x, { down: true }, 1);
ok(x.pose[3] < hov - 1, `Down sinks (${hov.toFixed(1)} -> ${x.pose[3].toFixed(1)} m)`);

// 2. too heavy: 10 t on one thruster (30 kN against 98 kN)
const brick = craft(10, 1);
ok(!flightOf(F, brick.mass, brick.thrust).lifts, "one thruster cannot lift 10 t");
run(brick, { up: true, fwd: 1 }, 3);
ok(brick.grounded && Math.abs(brick.pose[3] - 100.5) < 1e-6 && brick.pose[1] === 500, "…it never leaves the ground, nor drives off, whatever the pilot asks");
const drop = craft(2, 0); drop.pose[3] = 150; drop.grounded = false;
run(drop, {}, 1);
ok(drop.pose[3] < 150 - 4 && drop.vel[2] < -8, `with no thrust gravity brings it down (${drop.pose[3].toFixed(1)} m, ${drop.vel[2].toFixed(1)} m/s after 1 s)`);

// 3. forward, top speed, drag
const f = craft(2, 4); f.pose[3] = 150; f.grounded = false; f.pose[4] = Math.PI / 2;         // facing east
run(f, { fwd: 1, yaw: Math.PI / 2 }, 20);
const sp = Math.hypot(...f.vel);
ok(f.pose[1] > 600 && Math.abs(f.pose[2] - 500) < 1, `forward pushes along the facing (east: u ${f.pose[1].toFixed(0)}, v ${f.pose[2].toFixed(1)})`);
ok(sp <= F.vmax + 1e-9, `never past the top speed (${sp.toFixed(1)} of ${F.vmax} m/s)`);
const v0 = Math.hypot(f.vel[0], f.vel[1]);
run(f, { yaw: Math.PI / 2 }, 3);
ok(Math.hypot(f.vel[0], f.vel[1]) < v0 * 0.5, "let go, the air slows it");

// 4. the ground
const d = craft(2, 2); d.pose[3] = 140; d.grounded = false; d.vel = [0, 0, -30];
let lowest = Infinity;
for (let t = 0; t < 4; t += 0.05) { craftStep(d, {}, 0.05, F, flat); lowest = Math.min(lowest, d.pose[3] + d.bottom); }
ok(lowest >= 100 - 1e-9, `it never sinks below the ground by its lowest piece (lowest ${lowest.toFixed(3)} m over ground at 100)`);
const fall = craft(2, 0); fall.pose[3] = 120; fall.grounded = false;
run(fall, {}, 4);
ok(fall.grounded && fall.vel[2] === 0 && Math.abs(fall.pose[3] + fall.bottom - 100) < 1e-9, "it lands at rest on the ground");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
