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
//   * THE ENGINES' WORK (#171, operator: "it should be visible that x is 'fighting gravity' and not just floating
//     effortlessly"): each step says how much of its thrust the craft is using — c.engine = { lift, push, throttle, dir }:
//     lift the share holding it up (hovering: its weight over its thrust; climbing: all of it; sinking: a fifth of its
//     weight; resting on the ground: none), push the share driving it along, throttle their sum (0..1), dir the push's
//     direction [du, dv]. The page draws the exhaust, the dust and the tremble from it.
//   * ITS BODY MEETS THE WORLD (#171, operator: "x has no collision in the air"): the craft was a point at its seat over
//     the ground under the seat, so a 15 m fighter flew through houses, trees and hillsides. Its body is now points over
//     each piece (craftBody), turned with its yaw; a step that would put one inside something solid is not taken — the
//     craft slides along it (the move without its height, or its height alone) and loses the speed it hit with. A craft
//     already partly inside something (a piece was built through it) makes only moves that take no more of it in, so
//     it can always fly out and never further in.

/** The flight numbers a craft flies by, from the recipes' "flight" block. */
export function flightOf(F, mass, thrust) {
  const acc = mass > 0 ? thrust / mass : 0;
  return { acc, lifts: acc > F.g, weight: mass * F.g };
}

const BODY_STEP = 1.0, BODY_INSET = 0.12, BODY_FLOOR = 0.3, SWEEP = 0.15;   // m: points no farther apart than this; kept this far inside
// each piece (and this far above its bottom), so a craft resting on the ground, or a piece touching another, is not "in" it

/** Points (m, the craft's frame: east, north, up from the seat's bottom) over the pieces' boxes (cm, relative to the
 *  seat; boxAabb gives a turned piece's bounding box): each box's surface on a grid no coarser than BODY_STEP, inset. */
export function craftBody(pieces, boxAabb) {
  const pts = new Map();
  for (const b of pieces) {
    const a = boxAabb(b).map((x) => x / 100);
    const lo = [a[0] + BODY_INSET, a[1] + BODY_INSET, a[2] + BODY_FLOOR], hi = [a[0] + a[3] - BODY_INSET, a[1] + a[4] - BODY_INSET, a[2] + a[5] - BODY_INSET];
    const ax = [0, 1, 2].map((i) => {
      if (hi[i] <= lo[i]) return [a[i] + a[i + 3] / 2];          // thinner than the insets (a 10 cm plate): its middle
      const n = Math.ceil((hi[i] - lo[i]) / BODY_STEP);
      return Array.from({ length: n + 1 }, (_, k) => lo[i] + (hi[i] - lo[i]) * k / n);
    });
    for (const x of ax[0]) for (const y of ax[1]) for (const z of ax[2]) {
      const edge = [x, y, z].filter((w, i) => ax[i].length < 3 || w === ax[i][0] || w === ax[i][ax[i].length - 1]).length;
      if (edge === 0) continue;                                   // inside the box: its surface meets the world first
      const k = [x, y, z].map((w) => Math.round(w * 2.5)).join(",");      // points within 0.4 m are one
      if (!pts.has(k)) pts.set(k, [x, y, z]);
    }
  }
  return [...pts.values()];
}

/** How many of the body's points at pose [face, u, v, h, yaw] are inside something solid — solid(face, u, v, h); 0: it
 *  meets nothing. Turned as the page draws the craft: east = x cos(yaw) + n sin(yaw), north = n cos(yaw) - x sin(yaw). */
export function bodyHits(body, pose, solid) {
  const [f, u, v, h, yaw] = pose, cy = Math.cos(yaw), sy = Math.sin(yaw);
  let n = 0;
  for (const [x, y, z] of body) if (solid(f, u + x * cy + y * sy, v + y * cy - x * sy, h + z)) n++;
  return n;
}
/** Which of the body's points (their indices, ascending) are inside something solid at pose — what craftStep's hits gives. */
export function bodyInside(body, pose, solid) {
  const [f, u, v, h, yaw] = pose, cy = Math.cos(yaw), sy = Math.sin(yaw), out = [];
  body.forEach(([x, y, z], i) => { if (solid(f, u + x * cy + y * sy, v + y * cy - x * sy, h + z)) out.push(i); });
  return out;
}

/**
 * Advance craft c by dt seconds. c = { pose: [face, u, v, h, yaw], vel: [vu, vv, vh], mass, thrust, bottom (m: its
 * lowest piece below the seat, ≤ 0), grounded }. input = { fwd: -1..1, side: -1..1, up: bool, down: bool, yaw }.
 * groundAt(u, v): the surface height there. hits(pose), if given: which of its body's points are inside something solid
 * there (bodyInside).
 * Returns c.
 */
export function craftStep(c, input, dt, F, groundAt, hits) {
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
  // its body: a step into something solid is not taken — it slides along it, or stops (never once it is already inside)
  // SWEPT, in moves of at most SWEEP: a step at speed is longer than a plate is thick, and the points jumped clean over a
  // 20 cm wall (the first page walk, 2026-11-10). At each one the first of: without the height, without the north-south,
  // without the east-west, with only one of them — the part of the move that goes into it is dropped with its speed (a
  // craft pressed at a slant against a wall goes along it). Turning into something is not taken either.
  // A CRAFT ALREADY PARTLY INSIDE something (built through it; a wall built where it stood; its belly at a wall's very
  // foot) may make any move in which no point outside goes in — out, or along — so it can always fly out and never
  // further in: "inside, it moves freely" let the first point that slipped under a wall's foot carry the whole hull
  // through it, and "no more points inside than before" let a thin wall pass through it row by row (the page walks,
  // 2026-11-10).
  c.bumped = false;
  let turned = yaw;
  let base = new Set(hits ? hits([face, u0, v0, h0, c.pose[4]]) : []);
  const into = (pose) => { const ins = hits(pose); if (ins.some((i) => !base.has(i))) return true; base = new Set(ins); return false; };
  if (hits) {
    let yw = yaw;
    if (into([face, u0, v0, h0, yw])) { yw = c.pose[4]; c.bumped = true; }
    const du = u - u0, dv = v - v0, dh = h - h0, n = Math.max(1, Math.ceil(Math.hypot(du, dv, dh) / SWEEP));
    const keep = [1, 1, 1];
    let pu = u0, pv = v0, ph = h0;
    for (let k = 0; k < n; k++) {
      const tu = pu + keep[0] * du / n, tv = pv + keep[1] * dv / n, th = ph + keep[2] * dh / n;
      if (!into([face, tu, tv, th, yw])) { pu = tu; pv = tv; ph = th; continue; }
      c.bumped = true;
      const tries = [[1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 0, 0], [0, 1, 0], [0, 0, 1]];   // keep [u, v, h]?
      const t = tries.find(([a, b, d]) => !into([face, a ? tu : pu, b ? tv : pv, d ? th : ph, yw])) || [0, 0, 0];
      for (let i = 0; i < 3; i++) if (!t[i]) keep[i] = 0;
      if (t[0]) pu = tu; if (t[1]) pv = tv; if (t[2]) ph = th;
      if (!keep[0] && !keep[1] && !keep[2]) break;
    }
    if (!keep[0]) vu = 0; if (!keep[1]) vv = 0; if (!keep[2]) vh = 0;
    u = pu; v = pv; h = ph; turned = yw;
  }
  c.pose = [face, u, v, h, turned];
  c.vel = [vu, vv, vh];
  // the engines' work this step, as shares of full thrust (acc is thrust / mass; g / acc is the weight's share)
  const wShare = acc > 0 ? Math.min(1, F.g / acc) : 0;
  let lift = 0;
  if (input.up) lift = 1;                                              // climbing — or straining at a load it cannot lift
  else if (c.grounded) lift = 0;                                       // resting: the engines idle
  else if (input.down) lift = lifts ? wShare * 0.2 : 0;                // sinking under a fifth of its weight held
  else if (lifts) lift = wShare;                                       // hovering: holding exactly its weight
  const fwd = Math.max(-1, Math.min(1, input.fwd || 0)), side = Math.max(-1, Math.min(1, input.side || 0));
  const m = Math.min(1, Math.hypot(fwd, side)), su = Math.sin(yaw), cu = Math.cos(yaw);
  const push = (lifts || airborne) && acc > 0 ? m * (Math.min(acc, 14) * 0.9) / acc : 0;
  c.engine = { lift, push, throttle: Math.min(1, lift + push), dir: m ? [(su * fwd + cu * side) / m, (cu * fwd - su * side) / m] : [0, 0] };
  return c;
}
