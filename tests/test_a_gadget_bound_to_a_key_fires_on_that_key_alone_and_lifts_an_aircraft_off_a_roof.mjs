/*
 * test_a_gadget_bound_to_a_key_fires_on_that_key_alone_and_lifts_an_aircraft_off_a_roof.mjs — GADGET KEYS (operator
 * 2026-11-12, in an X fighter parked on a roof, an aircraft that needs a run to lift: "maybe add some thrusters and bind
 * them to some keys", "THE BINDING GOES TO BLOCK ACTIVATION OF A PARTICULAR GADGET IT MUST BE UNIVERSAL", "configurable
 * at the gadget"). static/land-flight.js aeroOf / heldThrust / aircraftStep / craftStep:
 *   1. aeroOf keeps a bound gadget apart from the automatic thrust: a thruster block with a slot is in gadgets[slot], not
 *      in T; unbound pieces are in T as before; two pieces on one key add up; an engine part bound keeps its direction;
 *   2. an aircraft (wings, nose engines, no vertical thrust of its own) with bottom thrusters bound to key 1, resting on a
 *      roof: Up does nothing (the bound thrusters are not the automatic vertical ones), key 1 held lifts it straight off
 *      (grounded false, height up) once its thrust beats its weight — and a bound thrust that does not beat the weight
 *      never lifts it, however long the key is held;
 *   3. let go of the key, it falls back (gravity always pulls an aircraft);
 *   4. the hovering craft (craftStep) likewise: a craft whose automatic thrust cannot lift it rises on a bound thruster
 *      that can, and only while the key is held; the engines' work shows the key's lift;
 *   5. a slot of 0 or none binds nothing (aeroOf without slots is aeroOf as it was).
 * Run: node tests/test_a_gadget_bound_to_a_key_fires_on_that_key_alone_and_lifts_an_aircraft_off_a_roof.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const { aeroOf, heldThrust, aircraftStep, craftStep, craftBody } = await import(join(ROOT, "static", "land-flight.js"));
const Wd = await import(join(ROOT, "static", "land-world.js"));
const Sh = await import(join(ROOT, "static", "land-shapes.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8")), F = R.flight;
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const thrustOf = (b) => (b[6] === Wd.B.thruster ? Wd.engineCount(b) * F.thrust_kn : 0);

// the craft: a plate hull, a seat, wings, two engine parts along the nose, four thruster blocks under the hull
const WING = Sh.encode ? null : null;   // (the wing part's code is read off the shapes module below)
const wingCode = (() => { for (let c = 16; c < 256; c++) { if (Sh.isPart(c) && Sh.decode(c).type === Sh.WING) return c; } return null; })();
const engineCode = (() => { for (let c = 16; c < 256; c++) { if (Sh.isPart(c) && Sh.decode(c).type === Sh.ENGINE) return c; } return null; })();
ok(wingCode !== null && engineCode !== null, `the shapes module has a wing part (${wingCode}) and an engine part (${engineCode})`);
const PLATE = 64, THR = Wd.B.thruster, SEAT = 66;
const pieces = [
  [-100, -300, 0, 200, 800, 20, PLATE],                      // the hull: 2 x 8 m, 20 cm, the seat's bottom at y 0
  [-40, -45, 20, 80, 90, 110, SEAT],
  [100, -200, 20, 500, 200, 10, PLATE, wingCode],            // a wing each side
  [-600, -200, 20, 500, 200, 10, PLATE, wingCode],
  [-90, -300, 20, 60, 140, 60, THR, engineCode],             // two engines along the nose (an engine part pushes along its length)
  [30, -300, 20, 60, 140, 60, THR, engineCode],
  [-100, -260, -140, 100, 100, 140, THR],                    // four thruster blocks under the hull (a block pushes up)
  [0, -260, -140, 100, 100, 140, THR],
  [-100, 100, -140, 100, 100, 140, THR],
  [0, 100, -140, 100, 100, 140, THR],
];
const iBottom = [6, 7, 8, 9];
const slots = pieces.map((_, i) => (iBottom.includes(i) ? 1 : 0));

// 1. aeroOf keeps the bound apart
const plain = aeroOf(pieces, Wd.boxAabb, thrustOf), bound = aeroOf(pieces, Wd.boxAabb, thrustOf, slots);
ok(plain.winged && bound.winged, "both readings: an aircraft (wings, engines along the nose)");
ok(plain.T[2] === 4 * F.thrust_kn && Object.keys(plain.gadgets).length === 0, `unbound: the four blocks are the automatic vertical thrust (${plain.T[2]} kN up), no gadgets`);
ok(bound.T[2] === 0 && bound.gadgets[1] && bound.gadgets[1][2] === 4 * F.thrust_kn && bound.T[1] === plain.T[1],
  `bound to key 1: no automatic vertical thrust, key 1 holds ${bound.gadgets[1] && bound.gadgets[1][2]} kN up, the nose engines stay automatic (${bound.T[1]} kN)`);
const mixed = aeroOf(pieces, Wd.boxAabb, thrustOf, pieces.map((_, i) => (i === 6 ? 2 : i === 7 ? 2 : i === 4 ? 3 : 0)));
ok(mixed.gadgets[2][2] === 2 * F.thrust_kn && mixed.gadgets[3][1] > 0 && Math.abs(mixed.gadgets[3][2]) < 1e-9 && mixed.T[2] === 2 * F.thrust_kn,
  "two blocks on one key add up; an engine part bound keeps its direction (along the nose); the rest stay automatic");
const held = heldThrust(bound, new Set([1])), none = heldThrust(bound, new Set([2])), nothing = heldThrust(bound, null);
ok(held[2] === 4 * F.thrust_kn && none[2] === 0 && nothing[2] === 0, "heldThrust: key 1 held fires the four blocks; key 2, or no keys, fire nothing");

// 2. off a roof: resting at 150 m on a roof (the ground function says the roof's height), on Up nothing, on key 1 up
const mass = 3.0;                                              // t: weight 29.4 kN; four blocks 120 kN
const roof = () => 150;
const aircraft = (sl) => ({ pose: [0, 500, 500, 151.4, 0, 0, 0], vel: [0, 0, 0], mass, thrust: 6 * F.thrust_kn, bottom: -1.4, grounded: true, aero: aeroOf(pieces, Wd.boxAabb, thrustOf, sl), throttle: 0 });
const runA = (c, input, secs) => { for (let t = 0; t < secs; t += 0.02) aircraftStep(c, input, 0.02, F, roof); return c; };
const a1 = runA(aircraft(slots), { up: true }, 2);
ok(a1.grounded && Math.abs(a1.pose[3] - 151.4) < 1e-6, `Up alone: the aircraft stays on the roof (its vertical thrusters are bound, not automatic) — at ${a1.pose[3].toFixed(2)} m`);
const a2 = runA(aircraft(slots), { slots: new Set([1]) }, 2);
ok(!a2.grounded && a2.pose[3] > 153 && a2.vel[2] > 0, `key 1 held: it lifts straight off the roof (${a2.pose[3].toFixed(1)} m after 2 s, climbing at ${a2.vel[2].toFixed(1)} m/s)`);
const heavy = Object.assign(aircraft(slots), { mass: 20 });    // 196 kN of weight against 120 kN on the key
runA(heavy, { slots: new Set([1]) }, 3);
ok(heavy.grounded && Math.abs(heavy.pose[3] - 151.4) < 1e-6, "a bound thrust under the weight never lifts it, however long the key is held");
const a3 = runA(aircraft(null), { up: true }, 2);
ok(!a3.grounded && a3.pose[3] > 153, `unbound, the same blocks lift it on Up as before (${a3.pose[3].toFixed(1)} m)`);

// 3. let go: it falls back
const top = a2.pose[3], climb = a2.vel[2];
runA(a2, {}, 12);                                              // (it was climbing at 54 m/s: a ballistic 5 s up before it turns)
ok((a2.grounded && Math.abs(a2.pose[3] - 151.4) < 0.01) || (a2.vel[2] < 0 && a2.pose[3] < top + climb * climb / (2 * 9.8) + 1), `let go of the key, it turns over and falls back onto the roof (${a2.grounded ? "resting again" : "falling at " + (-a2.vel[2]).toFixed(1) + " m/s"}, ${a2.pose[3].toFixed(1)} m)`);

// 4. the hovering craft
const flat = () => 100;
const hover = (sl, m) => { const ae = aeroOf(pieces.slice(0, 2).concat(pieces.slice(6)), Wd.boxAabb, thrustOf, sl); const boundKn = Object.values(ae.gadgets).reduce((s, g) => s + Math.hypot(...g), 0);
  return { pose: [0, 500, 500, 101.4, 0], vel: [0, 0, 0], mass: m, thrust: 4 * F.thrust_kn - boundKn, bottom: -1.4, grounded: true, aero: ae }; };
const runH = (c, input, secs) => { for (let t = 0; t < secs; t += 0.05) craftStep(c, input, 0.05, F, flat); return c; };
const h1 = runH(hover([0, 0, 1, 1, 1, 1], 3), { up: true }, 2);
ok(h1.grounded, "a hovering craft whose thrusters are all bound: Up lifts nothing (no automatic thrust)");
const h2 = runH(hover([0, 0, 1, 1, 1, 1], 3), { slots: new Set([1]) }, 2);
ok(!h2.grounded && h2.pose[3] > 103 && h2.engine.lift === 1, `key 1 held lifts it (${h2.pose[3].toFixed(1)} m), the engines' work shows the lift`);
const h3 = runH(hover([0, 0, 1, 1, 0, 0], 3), { slots: new Set([1]) }, 2);
ok(!h3.grounded && h3.pose[3] > 102, `two bound and two automatic: key 1 alone (${2 * F.thrust_kn} kN against ${(3 * F.g).toFixed(1)} kN) lifts it too`);
const top2 = h2.pose[3], climb2 = h2.vel[2];
runH(h2, {}, 15);
ok((h2.grounded && Math.abs(h2.pose[3] - 101.4) < 0.01) || (h2.vel[2] < 0 && h2.pose[3] < top2 + climb2 * climb2 / (2 * 9.8) + 1), `let go, it comes down (no automatic thrust holds it): ${h2.grounded ? "back on the ground" : "falling at " + (-h2.vel[2]).toFixed(1) + " m/s"}, ${h2.pose[3].toFixed(1)} m`);

// 5. nothing bound
const z = aeroOf(pieces, Wd.boxAabb, thrustOf, pieces.map(() => 0));
ok(JSON.stringify(z.T) === JSON.stringify(plain.T) && Object.keys(z.gadgets).length === 0, "slots of 0 bind nothing: the reading is the plain one");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
