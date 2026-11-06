/*
 * test_a_walker_crosses_slopes_and_steps_without_jitter.mjs — static/land-walk.js ("the walking animation includes some
 * fucking jitterjumping", operator 2026-11-06). The old step lifted a walker up a slope in 5 cm notches; the hover it left
 * made the next frame "airborne", an airborne walker may not step up, so every other uphill frame stopped dead and every
 * downhill frame was a fall and a landing. Walked here at 60 frames a second with the page's own body (four corners,
 * three heights) over a smooth 30° hill, a 50 cm step and a 2 m ledge:
 *   1. uphill: the walker advances EVERY frame, is on the ground every frame, and reaches walking speed;
 *   2. downhill: on the ground every frame (no fall-and-land), height never rises;
 *   3. it stands ON the surface, never inside it and never more than a millimetre above it;
 *   4. a 50 cm step is climbed, and the eye glides up it over several frames (none moves it 15 cm; the old step: 50 cm in one);
 *   5. a 2 m ledge is a real fall (airborne, then landed); a jump leaves the ground and lands again.
 *
 * Run: node tests/test_a_walker_crosses_slopes_and_steps_without_jitter.mjs
 */
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const { walk } = await import(join(ROOT, "static", "land-walk.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

const C = { GRAV: 26, JUMP: 8.4, STEP: 0.65 }, WALK = 4.6, HALF = 0.3, TALL = 1.8, dt = 1 / 60;
const body = (ground) => (u, v, h) => {           // static/land.js collides(): four corners at three heights
  for (const du of [-HALF, HALF]) for (const dv of [-HALF, HALF]) for (const dh of [0.01, 0.9, TALL - 0.01])
    if (h + dh < ground(u + du, v + dv)) return true;
  return false;
};
const run = (ground, P, frames, wish, jumpAt = -1) => {
  const col = body(ground), log = [];
  for (let f = 0; f < frames; f++) {
    const u0 = P.u, h0 = P.h, e0 = P.eyeH;
    walk(P, wish, f === jumpAt, dt, col, C);
    log.push({ du: P.u - u0, dh: P.h - h0, de: e0 === undefined ? 0 : P.eyeH - e0, ground: P.ground, h: P.h, u: P.u });
  }
  return log;
};
const start = (ground, u) => { const P = { u, v: 0, h: 0, vu: 0, vv: 0, vh: 0, ground: true, fly: false }; P.h = ground(u - HALF, 0) + 0.0; while (body(ground)(P.u, 0, P.h)) P.h += 0.001; return P; };

// a 30° hill: the highest corner under the body decides; the slope rises with u
const hill = (u) => Math.tan(Math.PI / 6) * u + 0.15 * Math.sin(u * 1.7);
const hillG = (u, v) => hill(u);
let P = start(hillG, 1), L = run(hillG, P, 180, [WALK, 0]);
const moving = L.slice(10);
ok(moving.every((x) => x.du > 0), `uphill: the walker advances every frame (${moving.filter((x) => x.du <= 0).length} stalled frames)`);
ok(L.every((x) => x.ground), `uphill: on the ground every frame (${L.filter((x) => !x.ground).length} airborne)`);
ok(moving[moving.length - 1].du / dt > WALK * 0.95, `uphill: at walking speed (${(moving[moving.length - 1].du / dt).toFixed(2)} of ${WALK})`);
const onSurface = (P, g) => body(g)(P.u, P.v, P.h - 0.001) && !body(g)(P.u, P.v, P.h);
ok(onSurface(P, hillG), "uphill: standing on the surface, within a millimetre");

P = start(hillG, 12); L = run(hillG, P, 180, [-WALK, 0]);
ok(L.every((x) => x.ground), `downhill: on the ground every frame (${L.filter((x) => !x.ground).length} airborne)`);
ok(L.every((x) => x.dh <= 1e-9), "downhill: the height never rises");
ok(L.slice(10).every((x) => x.du < 0), "downhill: advancing every frame");
ok(onSurface(P, hillG), "downhill: standing on the surface, within a millimetre");

// a 50 cm step at u = 3 on flat ground
const stepG = (u, v) => (u >= 3 ? 0.5 : 0);
P = start(stepG, 1); L = run(stepG, P, 120, [WALK, 0]);
ok(P.u > 5 && onSurface(P, stepG) && P.h > 0.4, `a 50 cm step is climbed (at u ${P.u.toFixed(2)}, standing on it)`);
ok(Math.max(...L.map((x) => Math.abs(x.de))) < 0.15, `the eye glides up the step (largest eye move in a frame ${Math.max(...L.map((x) => Math.abs(x.de))).toFixed(3)} m)`);

// a 2 m ledge: a real fall
const ledgeG = (u, v) => (u < 3 ? 2 : 0);
P = start(ledgeG, 1); L = run(ledgeG, P, 120, [WALK, 0]);
ok(L.some((x) => !x.ground) && P.ground && onSurface(P, ledgeG) && P.h < 0.1, "a 2 m ledge is a fall: airborne, then landed on the ground below");

// a jump on the flat
const flat = () => 0;
P = start(flat, 0); L = run(flat, P, 90, [0, 0], 5);
ok(L.some((x) => !x.ground && x.h > 1) && P.ground && onSurface(P, flat), "a jump leaves the ground (over a metre) and lands again");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
