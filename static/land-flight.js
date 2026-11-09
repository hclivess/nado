// land-flight.js — how a craft moves (#147, doc/land-tech-to-flight.md; "you must add actual physics like engines and
// gravity to the game and build a real usable xfighter", operator 2026-11-09). Pure, so tests drive it directly; the page
// (land.js) steps the craft its player flies, and the world server (scripts/land_server.py fly) bounds what it claims.
//
// A craft has a mass (t) and thrust (kN) — land-recipes.json "flight": a thruster pushes thrust_kn, each piece weighs its
// volume x its material's density — so thrust / mass is the acceleration it can make (m/s²). Gravity always pulls (g).
//   * it leaves the ground only when that beats gravity; under it, it stays down whatever the pilot asks;
//   * Up climbs with what is left over gravity, Down sinks, neither hovers (the thrusters hold it, the climb damps out);
//   * forward / back / sideways push along the pilot's facing, at most a horizontal share of the thrust; air drags;
//   * never faster than vmax; at the ground it stops falling, and on the ground it slides to a stop.

/** The flight numbers a craft flies by, from the recipes' "flight" block. */
export function flightOf(F, mass, thrust) {
  const acc = mass > 0 ? thrust / mass : 0;
  return { acc, lifts: acc > F.g, weight: mass * F.g };
}

/**
 * Advance craft c by dt seconds. c = { pose: [face, u, v, h, yaw], vel: [vu, vv, vh], mass, thrust, bottom (m: its
 * lowest piece below the seat, ≤ 0), grounded }. input = { fwd: -1..1, side: -1..1, up: bool, down: bool, yaw }.
 * groundAt(u, v): the surface height there. Returns c.
 */
export function craftStep(c, input, dt, F, groundAt) {
  const { acc, lifts } = flightOf(F, c.mass, c.thrust);
  const [face, u0, v0, h0] = c.pose;
  let [vu, vv, vh] = c.vel;
  const yaw = input.yaw ?? c.pose[4];
  const airborne = !c.grounded;
  // horizontal: along the facing; the thrusters push it only once it can fly (on the ground a craft that cannot lift
  // does not drive about either)
  if (lifts || airborne) {
    const push = Math.min(acc, 14) * 0.9;
    const fwd = Math.max(-1, Math.min(1, input.fwd || 0)), side = Math.max(-1, Math.min(1, input.side || 0));
    const su = Math.sin(yaw), cu = Math.cos(yaw);
    vu += (su * fwd + cu * side) * push * dt;
    vv += (cu * fwd - su * side) * push * dt;
  }
  const drag = Math.exp(-(c.grounded ? 4 : 0.35) * dt);
  vu *= drag; vv *= drag;
  // vertical
  if (input.up && lifts) vh += (acc - F.g) * dt;
  else if (input.down) vh -= F.g * 0.8 * dt;
  else if (lifts && airborne) vh *= Math.exp(-2.5 * dt);              // hovering: the thrusters hold it
  else vh -= F.g * dt;                                                 // falling, or resting on the ground
  // top speed
  const sp = Math.hypot(vu, vv, vh);
  if (sp > F.vmax) { const k = F.vmax / sp; vu *= k; vv *= k; vh *= k; }
  let u = u0 + vu * dt, v = v0 + vv * dt, h = h0 + vh * dt;
  // the ground: never through it; on it, no falling
  const g = groundAt(u, v);
  if (h + c.bottom <= g) { h = g - c.bottom; if (vh < 0) vh = 0; c.grounded = true; }
  else c.grounded = false;
  c.pose = [face, u, v, h, yaw];
  c.vel = [vu, vv, vh];
  return c;
}
