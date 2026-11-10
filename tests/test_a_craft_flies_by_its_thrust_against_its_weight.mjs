/*
 * test_a_craft_flies_by_its_thrust_against_its_weight.mjs — static/land-flight.js, the physics the pilot's page flies a
 * craft by (#147, "you must add actual physics like engines and gravity to the game and build a real usable xfighter",
 * operator 2026-11-09), with the numbers from static/land-recipes.json "flight":
 *   1. a craft whose thrusters beat its weight climbs on Up, hovers when let go (the climb damps out), sinks on Down;
 *   2. one too heavy for its thrust never leaves the ground, whatever the pilot asks — and gravity brings a craft down;
 *   3. forward pushes along the facing; it never passes the top speed; drag slows it;
 *   4. the ground holds it: it never sinks below the surface by its lowest piece, and it lands at rest;
 *   5. the engines' work: the share of its thrust it uses, idle, climbing, hovering, pushing, sinking, straining;
 *   6. its body meets the world (#171, "x has no collision in the air"): a wall stops it — by any piece, not only its
 *      seat, and turned with its yaw — it slides along a wall and under a roof, and a craft already inside something
 *      flies out of it.
 *
 * Run: node tests/test_a_craft_flies_by_its_thrust_against_its_weight.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const { craftStep, flightOf, craftBody, bodyHits, bodyInside } = await import(join(ROOT, "static", "land-flight.js"));
const Wd = await import(join(ROOT, "static", "land-world.js"));
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

// 5. THE ENGINES' WORK (#171: "it should be visible that x is 'fighting gravity'"): the share of its thrust a craft uses
const e = craft(8.8, 4);                                          // the rebuilt X fighter: 8.8 t, 120 kN
run(e, {}, 0.5);
ok(e.engine && e.engine.throttle === 0, "resting on the ground, the engines idle (throttle 0)");
run(e, { up: true }, 1);
ok(e.engine.lift === 1 && e.engine.throttle === 1, "climbing, they give all they have (throttle 1)");
run(e, {}, 2);
const wShare = 8.8 * F.g / e.thrust;
ok(!e.grounded && Math.abs(e.engine.throttle - wShare) < 1e-9, `hovering, they hold exactly its weight: ${(e.engine.throttle * 100).toFixed(0)} % (${(8.8 * F.g).toFixed(0)} of ${e.thrust} kN)`);
run(e, { fwd: 1 }, 0.5);
ok(e.engine.throttle > wShare && e.engine.push > 0 && Math.abs(Math.hypot(...e.engine.dir) - 1) < 1e-9, `pushing forward adds to it (${(e.engine.throttle * 100).toFixed(0)} %), along the facing`);
run(e, { down: true }, 0.3);
ok(Math.abs(e.engine.lift - wShare * 0.2) < 1e-9, "sinking, they hold a fifth of its weight");
const strain = craft(10, 1);
run(strain, { up: true }, 0.5);
ok(strain.grounded && strain.engine.throttle === 1, "a craft too heavy to lift strains at full throttle and stays down");

// 6. ITS BODY (#171): a craft 4 m long — a hull 300 x 150 cm, its seat 40 cm from the back, a nose 3 m ahead of the seat
const pieces = [[-150, -40, 0, 300, 150, 10, 64], [-40, -45, 10, 80, 90, 110, 66], [-30, 110, 0, 60, 300, 60, 64], [-130, -140, 0, 100, 100, 140, 65]];
const body = craftBody(pieces, Wd.boxAabb);
const inBox = (p) => pieces.some((b) => p[0] >= b[0] / 100 && p[0] <= (b[0] + b[3]) / 100 && p[1] >= b[1] / 100 && p[1] <= (b[1] + b[4]) / 100 && p[2] >= b[2] / 100 && p[2] <= (b[2] + b[5]) / 100);
ok(body.length > 8 && body.every(inBox), `its body is ${body.length} points, every one inside a piece`);
ok(body.some((p) => p[1] > 3.5) && body.some((p) => p[1] < -1), "…reaching its nose 4 m ahead and its thruster behind");
ok(body.every((p) => p[2] >= 0.05), "…none at its very bottom: resting on the ground is not being inside it");
// a wall: solid where v >= 520 (north), at any height
const wall = (f, u, v, h) => v >= 520 || h < 100;
const hits = (pose) => bodyHits(body, pose, wall), inside = (pose) => bodyInside(body, pose, wall);   // how many in; which
const w = { pose: [0, 500, 510, 105, 0], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false };
for (let t = 0; t < 6; t += 0.05) craftStep(w, { fwd: 1 }, 0.05, F, flat, inside);
ok(w.pose[2] + 4.1 > 520 - 0.7 && w.pose[2] + 4.1 < 520 + 0.2 && !hits(w.pose), `flying north at a wall, its nose stops at it — not its seat (its nose at v ${(w.pose[2] + 4.1).toFixed(2)}, the wall at 520)`);
ok(Math.abs(w.vel[1]) < 1e-9 && w.bumped, "…and it loses the speed it hit with");
const noHit = { pose: [0, 500, 510, 105, 0], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false };
for (let t = 0; t < 6; t += 0.05) craftStep(noHit, { fwd: 1 }, 0.05, F, flat);
ok(noHit.pose[2] > 530, "(without its body it flew through: the bug)");
// turned to face east, the same wall is beside it: it flies on along it
const e2 = { pose: [0, 500, 518, 105, Math.PI / 2], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false };
ok(!hits(e2.pose), "facing east, 2 m from the wall to its left, it is clear of it — its body turns with its yaw");
for (let t = 0; t < 2; t += 0.05) craftStep(e2, { fwd: 1, side: -0.3 }, 0.05, F, flat, inside);
ok(e2.pose[1] > 510 && !hits(e2.pose), `pressed against the wall as it flies, it slides along it (${(e2.pose[1] - 500).toFixed(1)} m east)`);
// a roof at 112 m: it climbs to it, not through it, and still flies along under it
const roof = (f, u, v, h) => h >= 112 || h < 100;
const r = { pose: [0, 500, 500, 105, 0], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false };
for (let t = 0; t < 4; t += 0.05) craftStep(r, { up: true, fwd: 1 }, 0.05, F, flat, (p) => bodyInside(body, p, roof));
ok(r.pose[3] < 112 && r.pose[3] > 107 && r.pose[2] > 505, `climbing under a roof at 112 m it stops beneath it (${r.pose[3].toFixed(2)} m) and flies on under it`);
// at speed: a step is longer than a plate is thick — the points jumped over a 20 cm wall in the first page walk
const plate = (f, u, v, h) => (v >= 520 && v < 520.2) || h < 100;
const fast = { pose: [0, 500, 480, 105, 0], vel: [0, 55, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false };
for (let t = 0; t < 3; t += 0.05) craftStep(fast, { fwd: 1 }, 0.05, F, flat, (p) => bodyInside(body, p, plate));
ok(fast.pose[2] + 4.1 < 520.3, `at 55 m/s into a 20 cm plate it stops at it, not past it (nose at ${(fast.pose[2] + 4.1).toFixed(2)})`);
// turning into a wall is not taken: 2 m short of the wall facing east, its 4 m nose would swing into it
const tw = { pose: [0, 500, 518, 105, Math.PI / 2], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false };
ok(!hits(tw.pose) && hits([0, 500, 518, 105, 0]), "beside a wall, facing along it — turned north its nose would be in it");
craftStep(tw, { yaw: 0 }, 0.05, F, flat, inside);
ok(tw.pose[4] === Math.PI / 2 && !hits(tw.pose) && tw.bumped, "…so it does not turn into it");
// already inside (built through a wall): it moves, so it can always fly out
const s2 = { pose: [0, 500, 519, 105, 0], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false };
ok(hits(s2.pose), "a craft whose nose is in the wall…");
const s3 = { pose: [0, 500, 519, 105, 0], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false }, in0 = hits(s3.pose);
for (let t = 0; t < 2; t += 0.05) craftStep(s3, { fwd: 1 }, 0.05, F, flat, inside);
ok(hits(s3.pose) <= in0 && s3.pose[2] < 519.2, `…cannot push on further into it (${in0} points in, then ${hits(s3.pose)}; seat at ${s3.pose[2].toFixed(2)})`);
for (let t = 0; t < 2; t += 0.05) craftStep(s2, { fwd: -1 }, 0.05, F, flat, inside);
ok(!hits(s2.pose), "…backs out of it");
// a thin wall that appears where the craft is (built through it, or it arrived late): it cannot slide on through it row
// by row, the points in front going in as fast as those behind come out
const noseN = Math.max(...body.map((p) => p[1])), rowN = Math.max(...body.map((p) => p[1]).filter((n) => n < noseN - 0.05));   // its nose's row, the next
const thin = (f, u, v, h) => (v >= 511 + noseN - 0.1 && v < 511 + noseN + 0.1) || h < 100, tin = (p) => bodyInside(body, p, thin);
const th = { pose: [0, 500, 511, 105, 0], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: false };
const caught = new Set(tin(th.pose));
for (let t = 0; t < 4; t += 0.05) craftStep(th, { fwd: 1 }, 0.05, F, flat, tin);
ok(caught.size > 0 && tin(th.pose).every((i) => caught.has(i)) && th.pose[2] + rowN < 511 + noseN - 0.1,
  `a wall built through its nose holds it: the nose may come out of it, no point that was clear goes in (seat ${th.pose[2].toFixed(2)})`);
// a wall standing on the ground the craft rests on: its belly is at the wall's very foot — the first point in under the
// foot carried the whole hull through it in the page walk
const foot = (f, u, v, h) => (v >= 520 && v < 520.2 && h >= 100.05) || h < 100;
const g = { pose: [0, 500, 510, 100, 0], vel: [0, 0, 0], mass: 2, thrust: 2 * F.thrust_kn, bottom: 0, grounded: true };
for (let t = 0; t < 6; t += 0.05) craftStep(g, { fwd: 1 }, 0.05, F, flat, (p) => bodyInside(body, p, foot));
ok(g.pose[2] + 4.1 < 520.35, `driven along the ground at a wall standing on it, it stops at the wall (nose at ${(g.pose[2] + 4.1).toFixed(2)})`);

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
