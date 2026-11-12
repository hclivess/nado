/*
 * test_a_winged_craft_flies_by_lift_and_thrust_banks_to_turn_stalls_and_falls_under_gravity.mjs — #191 (operator
 * 2026-11-11 after the X-wing's first flight: "it does not react to turning at all, there is absolutely no aerodynamic
 * system", "vertical movement is laughable and only works on rockets with bottom engine", "gravity does not affect the x
 * fighter at all"). static/land-flight.js aeroOf / aircraftStep, driven with the X-wing's own figures where the reference
 * gives them (X-wing fighter infobox: 10 t, 11.76 m wide, 1,050 km/h) and the mirror's formulas:
 *   1. the parts say how it flies: four engine parts along the nose give thrust along the nose and none up; four wings
 *      give ~50 m² of lifting area and a span the width of the craft; a thruster block gives thrust up;
 *   2. gravity always pulls: a winged craft let go in still air with no speed falls — Space does nothing for it (no
 *      vertical thrusters), while a rocket with a bottom engine still climbs on Space;
 *   3. lift is L = ½ρv²SC_L: at its stall speed with the nose at the critical angle the wings carry its weight (n ≈ 1),
 *      at twice that speed they carry four times as much before the limiter (q ∝ v²);
 *   4. on the ground it rolls along its nose under throttle, and it leaves the ground only once lift beats weight —
 *      not before, whatever the stick says;
 *   5. at a bank the path turns: 60° of roll in level flight needs n = 2 (Banked turn l.130) and the heading swings
 *      toward the lowered wing; with wings level the heading holds;
 *   6. the controls need airflow: the stick does nothing at a standstill and turns the craft at V_CTRL;
 *   7. the velocity follows the nose: pitched up at speed it climbs and the velocity vector turns up with it — not
 *      instantly (the first model snapped yaw to the mouse and left the velocity where it was);
 *   8. a stall: past the critical angle C_L falls, and a craft hauled past it at low speed drops and its nose comes
 *      down toward its fall by itself (the weathervane);
 *   9. drag along the body: side-slipping, the sideways speed is killed faster than the forward speed.
 * Run: node tests/test_a_winged_craft_flies_by_lift_and_thrust_banks_to_turn_stalls_and_falls_under_gravity.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Fl = await import(join(ROOT, "static", "land-flight.js")), Wd = await import(join(ROOT, "static", "land-world.js"));
const Shapes = await import(join(ROOT, "static", "land-shapes.js")), Pl = await import(join(ROOT, "static", "land-planet.js"));
const RULES = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8")), F = RULES.flight;
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const DEG = Math.PI / 180;

// ---- the craft: the X-wing as it stands on the live server (its engine and wing parts), 12.2 t, 240 kN ----------------
const THR = Wd.B.thruster, PLATE = 28;
const ENG = Shapes.code(Shapes.ENGINE), WING = Shapes.tapered(Shapes.WING, 0.6);
const xwing = [
  [-40, -45, 0, 80, 90, 110, 66],                                      // the seat
  [-95, -105, -12, 190, 670, 150, PLATE, Shapes.tapered(Shapes.HULL, 1)],  // the hull
  [45, -533, 100, 130, 440, 130, THR, ENG, 0, 0, 180], [45, -533, -94, 130, 440, 130, THR, ENG, 0, 0, -180],
  [-175, -533, 100, 130, 440, 130, THR, ENG, 0, 0, 1620], [-175, -533, -94, 130, 440, 130, THR, ENG, 0, 0, -1620],
  [30, -383, 165, 535, 300, 28, PLATE, WING, 0, 0, 180], [30, -383, -57, 535, 300, 28, PLATE, WING, 0, 0, -180],
  [-565, -383, 165, 535, 300, 28, PLATE, WING, 0, 0, 1620], [-565, -383, -57, 535, 300, 28, PLATE, WING, 0, 0, -1620],
];
const thrustOf = (b) => (b[6] === THR ? Wd.engineCount(b) * F.thrust_kn : 0);
const aero = Fl.aeroOf(xwing, Wd.boxAabb, thrustOf);
const MASS = 12.2, THRUST = aero.T.reduce((s, x) => s + Math.abs(x), 0);
ok(aero.winged && aero.S > 40 && aero.S < 60, `four wings give the lifting area of a fighter: ${aero.S.toFixed(1)} m² (the X-wing's: ~51)`);
ok(aero.b > 10.5 && aero.b < 12.5, `…and a span the width of the craft: ${aero.b.toFixed(2)} m (the reference: 11.76 m wide)`);
ok(Math.abs(aero.T[1]) > 200 && Math.abs(aero.T[2]) < 1e-9 && Math.abs(aero.T[0]) < 1e-9, `four engines along the nose push along the nose and not up: [${aero.T.map((x) => x.toFixed(0))}] kN`);
const rocket = Fl.aeroOf([[0, 0, 0, 80, 90, 110, 66], [0, 100, 0, 100, 100, 140, THR]], Wd.boxAabb, thrustOf);
ok(!rocket.winged && rocket.T[2] === F.thrust_kn && rocket.S === 0, `a thruster block pushes up, and a craft of them has no wings: [${rocket.T}] kN`);
const tilted = Fl.tiltDir([0, 0, 0, 1, 1, 1, THR, ENG, 900, 0, 0], [0, 1, 0]);
ok(Math.abs(tilted[0] - 1) < 1e-9 && Math.abs(tilted[1]) < 1e-9, `an engine turned 90° about up pushes east: [${tilted.map((x) => x.toFixed(2))}]`);

// ---- a flat world at the sea's height + 30 m, no obstacles --------------------------------------------------------
const G = Pl.SEA_LEVEL + 30, groundAt = () => G;
const craft = (pose, vel, aeroOf = aero, mass = MASS, thrust = THRUST) => ({ pose: pose.slice(), vel: vel.slice(), mass, thrust, bottom: -1.6, grounded: false, aero: aeroOf, throttle: 0 });
const fly = (c, input, secs, dt = 1 / 60) => { for (let t = 0; t < secs; t += dt) Fl.craftStep(c, input, dt, F, groundAt); return c; };
const H = G + 300, vs = Fl.stallSpeed(craft([0, 1000, 1000, H, 0, 0, 0], [0, 0, 0]), F, H);
ok(vs > 40 && vs < 90, `its stall speed in this air is that of a fighter: ${vs.toFixed(1)} m/s (an F-16 lifts off near 70)`);

// 2. gravity always pulls
let c = fly(craft([0, 1000, 1000, H, 0, 0, 0], [0, 0, 0]), { up: true, throttle: 0 }, 2);
ok(c.pose[3] < H - 15 && c.vel[2] < -15, `let go with no speed, the winged craft falls, Space or not: ${(H - c.pose[3]).toFixed(1)} m in 2 s`);
c = fly(craft([0, 1000, 1000, H, 0, 0, 0], [0, 0, 0], rocket, 0.5, F.thrust_kn), { up: true }, 2);
ok(c.pose[3] > H + 5, `…while a rocket with a bottom engine climbs on Space: +${(c.pose[3] - H).toFixed(1)} m`);

// 3. lift
const rho = Pl.airAt(H - Pl.SEA_LEVEL).rho, W = MASS * 1000 * Pl.gravityAt(H);
const A = { ...Fl.AERO_DEF, ...(F.aero || {}) };
const lift = (V, alphaDeg) => 0.5 * rho * V * V * aero.S * Fl.liftCoef(alphaDeg * DEG, aero.AR, A.stall_deg);
ok(Math.abs(lift(vs, A.stall_deg) / W - 1) < 1e-6, `L = ½ρv²SC_L: at the stall speed and the critical angle the wings carry exactly the weight (n = ${(lift(vs, A.stall_deg) / W).toFixed(3)})`);
ok(Math.abs(lift(2 * vs, A.stall_deg) / W - 4) < 1e-6, `…and four times it at twice the speed (n = ${(lift(2 * vs, A.stall_deg) / W).toFixed(2)})`);
// one step at speed, nose level: the velocity gets the lift's upward kick and the drag's backward one
c = craft([0, 1000, 1000, H, 0, 10 * DEG, 0], [0, 1.5 * vs, 0]);
Fl.craftStep(c, { throttle: 0 }, 1 / 60, F, groundAt);
ok(c.air.n > 1.3 && c.vel[2] > 0 && c.vel[1] < 1.5 * vs, `at 1.5× the stall speed with 10° of nose-up, the wings carry ${c.air.n.toFixed(2)} g (2.25 × 10/15): it is pushed up and slowed by drag`);

// 4. the gear: rolling, and lift-off only when lift beats weight
c = craft([0, 1000, 1000, G + 1.6, 0, 0, 0], [0, 0, 0]); c.grounded = true;
fly(c, { throttle: 1, pitch: 1 }, 2);
ok(c.grounded && c.vel[1] > 10 && Math.abs(c.vel[0]) < 1e-6 && c.pose[5] === 0, `under full throttle it rolls along its nose on the ground (${c.vel[1].toFixed(1)} m/s after 2 s), the stick pulled and the nose still down (too slow to rotate)`);
let left = null, speedAtLiftoff = 0;
for (let t = 0; t < 40 && left === null; t += 1 / 60) { Fl.craftStep(c, { throttle: 1, pitch: 1 }, 1 / 60, F, groundAt); if (!c.grounded) { left = t; speedAtLiftoff = Math.hypot(c.vel[0], c.vel[1]); } }
ok(left !== null && speedAtLiftoff > 0.8 * vs, `…and leaves the ground at ${speedAtLiftoff.toFixed(1)} m/s (stall speed ${vs.toFixed(1)}; the engines' upward part helps), ${(2 + left).toFixed(1)} s down the strip — when the wings carry it, not on a key`);
fly(c, { throttle: 1, pitch: 0.4 }, 3);
ok(c.pose[3] > G + 10 && c.vel[2] > 0, `…then climbs away: ${(c.pose[3] - G).toFixed(0)} m up, ${c.vel[2].toFixed(1)} m/s of climb`);

// 5. a bank turns the path
const level = () => craft([0, 1000, 1000, H, 0, 3 * DEG, 0], [0, 1.6 * vs, 0]);
c = level(); fly(c, { throttle: 0.5, roll: 0 }, 2);
const heading0 = Math.atan2(c.vel[0], c.vel[1]);
ok(Math.abs(heading0) < 2 * DEG, `wings level, the heading holds (${(heading0 / DEG).toFixed(2)}° off after 2 s)`);
c = craft([0, 1000, 1000, H, 0, 3 * DEG, 60 * DEG], [0, 1.6 * vs, 0]);
let nMax = 0; for (let t = 0; t < 3; t += 1 / 60) { Fl.craftStep(c, { throttle: 0.7, pitch: 0.6 }, 1 / 60, F, groundAt); nMax = Math.max(nMax, c.air.n); }
const heading = Math.atan2(c.vel[0], c.vel[1]);
ok(heading > 15 * DEG, `rolled 60° right and pulling, the path turns right: ${(heading / DEG).toFixed(0)}° in 3 s`);
ok(nMax >= 1.8, `…under a load near n = 1 / cos 60° = 2 (peak ${nMax.toFixed(2)} g; Banked turn l.130)`);

// 6. the controls need airflow
c = craft([0, 1000, 1000, H, 0, 0, 0], [0, 0, 0]); Fl.craftStep(c, { roll: 1, pitch: 1 }, 0.5, F, groundAt);
ok(Math.abs(c.pose[6]) < 1e-9 && Math.abs(c.pose[5]) < 1e-9, "at a standstill the stick turns nothing");
c = craft([0, 1000, 1000, H, 0, 0, 0], [0, A.v_ctrl, 0]); fly(c, { roll: 1 }, 0.2);
ok(Math.abs(c.pose[6] / DEG - A.roll_dps * 0.2) < 3.5, `at V_CTRL it rolls at the full rate: ${(c.pose[6] / DEG).toFixed(1)}° in 0.2 s (${A.roll_dps}°/s), the right wing down`);

// 7. the velocity follows the nose, not at once
c = craft([0, 1000, 1000, H, 0, 0, 0], [0, 1.6 * vs, 0]);
Fl.craftStep(c, { throttle: 0.6, pitch: 1 }, 0.3, F, groundAt);
const climbAngle = (cc) => Math.atan2(cc.vel[2], Math.hypot(cc.vel[0], cc.vel[1]));
ok(c.pose[5] > 5 * DEG && climbAngle(c) < c.pose[5] * 0.6, `pulled up for 0.3 s the nose is ${(c.pose[5] / DEG).toFixed(1)}° up and the path only ${(climbAngle(c) / DEG).toFixed(1)}°: the velocity lags the nose`);
fly(c, { throttle: 0.6, pitch: 0.3 }, 2);
ok(climbAngle(c) > 3 * DEG && c.pose[3] > H + 5, `…and follows it: held a little nose-up, climbing at ${(climbAngle(c) / DEG).toFixed(1)}°, ${(c.pose[3] - H).toFixed(0)} m higher after 2 s more`);

// 8. a stall
ok(Fl.liftCoef((A.stall_deg + 8) * DEG, aero.AR, A.stall_deg) < 0.7 * Fl.liftCoef(A.stall_deg * DEG, aero.AR, A.stall_deg), "past the critical angle the lift coefficient falls");
c = craft([0, 1000, 1000, H, 0, 25 * DEG, 0], [0, 0.6 * vs, 0]);
Fl.craftStep(c, { throttle: 0 }, 1 / 60, F, groundAt);
ok(c.air.stalled, `too slow with the nose hauled up (${(c.air.alpha / DEG).toFixed(0)}° of attack) it is stalled`);
fly(c, { throttle: 0 }, 2.5);
ok(c.pose[3] < H - 10 && c.pose[5] < 10 * DEG, `…it drops (${(H - c.pose[3]).toFixed(0)} m in 2.5 s) and the nose comes down into the fall by itself (${(c.pose[5] / DEG).toFixed(0)}°)`);

// 9. the body drags sideways more than forward
c = craft([0, 1000, 1000, H, 0, 0, 0], [20, 60, 0]);     // flying north at 60 with 20 m/s of sideways drift
Fl.craftStep(c, { throttle: 0 }, 1 / 60, F, groundAt);
const beta0 = Math.abs(c.air.beta), yaw0 = c.pose[4];
fly(c, { throttle: 0 }, 1.5);
ok(beta0 > 15 * DEG && Math.abs(c.air.beta) < 0.5 * beta0 && c.pose[4] > yaw0 + 5 * DEG, `side-slipping ${(beta0 / DEG).toFixed(0)}°, the body's side drag and the weathervane bring the nose into the flow: ${(Math.abs(c.air.beta) / DEG).toFixed(1)}° of slip left, the nose ${((c.pose[4] - yaw0) / DEG).toFixed(0)}° round toward it`);

// ---- 10. stepping off (#194: "i exited the xfighter and fell into the townhall wall") -------------------------------
{
  const wallAt = (u, v) => u > 1001;                              // a wall just east of the seat at (1000, 1000), facing north
  const open = Fl.stepOffSpot(1000, 1000, 0, () => true);
  ok(open && Math.abs(open.u - 1001.5) < 1e-9 && Math.abs(open.v - 1000) < 1e-9 && open.tried === 1, `with room all round, the pilot steps off 1.5 m to the right (${open.u}, ${open.v})`);
  const byWall = Fl.stepOffSpot(1000, 1000, 0, (u, v) => !wallAt(u, v));
  ok(byWall && byWall.u < 1000 && byWall.tried === 2, `a wall on the right: the left side instead (${byWall.u.toFixed(1)}, tried ${byWall.tried})`);
  const boxed = Fl.stepOffSpot(1000, 1000, 0, (u, v) => Math.abs(u - 1000) > 3.2 && Math.abs(v - 1000) < 0.1);
  ok(boxed && boxed.tried === 9, `walls close on both sides and ahead and behind: the first wider spot (tried ${boxed.tried})`);
  ok(Fl.stepOffSpot(1000, 1000, 0, () => false) === null, "nowhere free: null — the pilot stays in the seat");
  const turned = Fl.stepOffSpot(1000, 1000, Math.PI / 2, () => true);
  ok(Math.abs(turned.u - 1000) < 1e-9 && Math.abs(turned.v - 998.5) < 1e-9, `facing east, the right side is south (${turned.u}, ${turned.v})`);
}

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
