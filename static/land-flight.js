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

import { gravityAt, airAt, FLAT_PLATE_CD, SEA_LEVEL } from "./land-planet.js";
import * as Shapes from "./land-shapes.js";

// ---- A WINGED CRAFT FLIES AS AN AIRCRAFT (#191; operator 2026-11-11, after the X-wing's first flight: "it does not react
// to turning at all, there is absolutely no aerodynamic system", "vertical movement is laughable and only works on
// rockets with bottom engine", "gravity does not affect the x fighter at all"). Until then every craft was the hovering
// point below (craftStep's rocket branch): yaw snapped to the mouse, the velocity ignored the nose, nothing depended on
// airspeed. Now a craft's PARTS say how it flies (aeroOf):
//   * every ENGINE part pushes along its own length, from its exhaust toward its intake (land-shapes ENGINE_PROFILE: the
//     glow at z 0, the throat at z 1); a unit thruster block pushes up (a rocket's bottom engine). Their sum is the
//     craft's thrust vector in its own frame — the X-wing's four engines push along its nose and give it NO lift;
//   * every WING part is lifting area S (its planform: span × chord × (1 + taper) / 2) and the wings' reach is the span b;
//   * with S > 0 or a nose-ward thrust the craft is an aircraft (c.aero.winged): it has an attitude (pose[5] pitch,
//     pose[6] roll), gravity always pulls, and the forces are the textbook ones, each cited to the research mirror
//     (/root/land-research/flight/, INDEX.md): lift L = ½ρv²SC_L (Lift (force) l.202), C_L = 2πα for a thin aerofoil
//     (Lift coefficient l.56) reduced for the finite wing by AR/(AR + 2) [a textbook (lifting-line) approximation — NOT
//     in the mirror, labelled as such], a stall past the critical angle (Stall l.6-8: "a sudden reduction in lift";
//     l.27: 17.5° in the example, "varies from airfoil to airfoil"), drag C_D = C_D0 + C_L²/(π·AR·e) (Lift-induced drag
//     l.39, AR = b²/S l.42; C_D0 0.021 = the F-4 Phantom subsonic, Drag coefficient l.115; e 0.7–0.85, Oswald efficiency
//     number l.25), a bank that turns the path with the lift's horizontal part and needs n = 1/cos φ of it (Banked turn
//     l.118, l.130), and a limiter that holds the angle of attack where the structure's load factor allows (Angle of
//     attack l.26: fly-by-wire aircraft limit the angle of attack regardless of pilot input).
//   * the pilot's stick PITCHES and ROLLS it, the rudder yaws it (Flight control surfaces l.8: aileron, rudder, elevator
//     control roll, yaw, pitch) — with an AUTHORITY that grows with airspeed, as a control surface only works in a
//     flow (l.4): at a standstill nothing turns, at V_CTRL everything does; and the nose weathervanes toward the
//     velocity (static stability), so a stalled craft drops its nose into its fall by itself;
//   * on the ground it rolls along its nose on its gear, steers with the rudder, brakes with the throttle shut, and
//     rotates only once its wings can carry it — it leaves the ground when lift beats weight, never on a key.
// The numbers the sources do not give are DESIGN CHOICES in land-recipes.json "flight".aero, each labelled there.
// NOT yet: wind, ground effect, the wings' own tilt (the X-wing's are rolled ±18° — all their area counts as level),
// collision with pitch and roll (bodyHits turns the body by yaw alone), damage.
const DEG = Math.PI / 180;
/** The aero defaults — the recipes' "flight".aero overrides any of them (every one labelled there). */
export const AERO_DEF = { cd0: 0.021, e: 0.8, stall_deg: 15, n_max: 9, v_ctrl: 40, roll_dps: 150, pitch_dps: 40, yaw_dps: 20, stab: 1.5, roll_damp: 2.0, gear_brake: 3.0, gear_roll: 0.6, side_cd: FLAT_PLATE_CD };
/** A piece's tilt (land-world rotOf: yaw, pitch, roll in tenths of a degree) applied to a direction in the piece's own
 *  frame (x east, y north, z up): yaw about z (from north toward east), then pitch about x (nose up), then roll about y. */
export function tiltDir(b, d) {
  const r = b.length > 8 ? [b[8] || 0, b[9] || 0, b[10] || 0] : [0, 0, 0];
  let [x, y, z] = d;
  const [ya, pa, ra] = r.map((t) => (t / 10) * DEG);
  // yaw: a vector along north turns toward east
  [x, y] = [x * Math.cos(ya) + y * Math.sin(ya), -x * Math.sin(ya) + y * Math.cos(ya)];
  // pitch: north rises toward up
  [y, z] = [y * Math.cos(pa) - z * Math.sin(pa), y * Math.sin(pa) + z * Math.cos(pa)];
  // roll: east dips toward -up
  [x, z] = [x * Math.cos(ra) - z * Math.sin(ra), x * Math.sin(ra) + z * Math.cos(ra)];
  return [x, y, z];
}
/** What a craft's parts make of it in the air: { winged, S (m² of wing), b (m span), AR, T: [right, nose, up] kN of thrust
 *  by direction in the craft's frame, side (m² the body shows the side wind), len (m nose to tail) }. `thrustOf(b)` gives a
 *  piece's thrust in kN (land.js: the thruster count × thrust_kn; a test passes its own). */
export function aeroOf(pieces, boxAabb, thrustOf) {
  let S = 0, lo = Infinity, hi = -Infinity, T = [0, 0, 0], ylo = Infinity, yhi = -Infinity, zlo = Infinity, zhi = -Infinity;
  for (const b of pieces) {
    const a = boxAabb(b), part = b.length > 7 ? Shapes.decode(b[7]) : null;
    ylo = Math.min(ylo, a[1]); yhi = Math.max(yhi, a[1] + a[4]); zlo = Math.min(zlo, a[2]); zhi = Math.max(zhi, a[2] + a[5]);
    if (part && part.type === Shapes.WING) {
      const t = (part.v + 1) / 10;                                 // Shapes.tapered: variant = taper × 10 − 1
      S += (b[3] / 100) * (b[4] / 100) * (1 + t) / 2;
      lo = Math.min(lo, a[0]); hi = Math.max(hi, a[0] + a[3]);
    }
    const kn = thrustOf(b);
    if (kn > 0) {
      const d = part && part.type === Shapes.ENGINE ? tiltDir(b, [0, 1, 0]) : [0, 0, 1];   // an engine along its length; a thruster block up
      T[0] += kn * d[0]; T[1] += kn * d[1]; T[2] += kn * d[2];
    }
  }
  const b = S > 0 ? (hi - lo) / 100 : 0, len = isFinite(yhi) ? (yhi - ylo) / 100 : 0, tall = isFinite(zhi) ? (zhi - zlo) / 100 : 0;
  return { winged: S > 0 || Math.abs(T[1]) > 1e-9, S, b, AR: S > 0 ? (b * b) / S : 0, T, side: len * tall, len };
}
/** The craft's axes in the local frame (east, north, up) for yaw ψ (from north toward east), pitch θ (nose up), roll φ
 *  (right wing down): { nose, right, up } as [e, n, u] unit vectors. */
export function axesOf(yaw, pitch, roll) {
  const n0 = [Math.sin(yaw), Math.cos(yaw), 0], r0 = [Math.cos(yaw), -Math.sin(yaw), 0], u0 = [0, 0, 1];
  const cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
  const nose = [n0[0] * cp, n0[1] * cp, sp], upP = [-n0[0] * sp, -n0[1] * sp, cp];
  // positive roll: the right wing DOWN (the right axis dips below the pitched-up plane), the up axis leans to the right
  const right = [r0[0] * cr - upP[0] * sr, r0[1] * cr - upP[1] * sr, r0[2] * cr - upP[2] * sr];
  const up = [upP[0] * cr + r0[0] * sr, upP[1] * cr + r0[1] * sr, upP[2] * cr + r0[2] * sr];
  return { nose, right, up };
}
/** yaw, pitch, roll back from the axes (the inverse of axesOf). */
export function anglesOf({ nose, right }) {
  const yaw = Math.atan2(nose[0], nose[1]), pitch = Math.asin(Math.max(-1, Math.min(1, nose[2])));
  const r0 = [Math.cos(yaw), -Math.sin(yaw), 0], n0 = [Math.sin(yaw), Math.cos(yaw), 0], sp = Math.sin(pitch), cp = Math.cos(pitch);
  const upP = [-n0[0] * sp, -n0[1] * sp, cp];
  return [yaw, pitch, Math.atan2(-dot(right, upP), dot(right, r0))];
}
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]); return l > 0 ? [a[0] / l, a[1] / l, a[2] / l] : [0, 0, 0]; };
const add = (a, b, k = 1) => [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k];
/** The lift coefficient at angle of attack α (rad) for aspect ratio AR: 2πα (thin aerofoil) × AR / (AR + 2) up to the
 *  critical angle, then the sudden fall of a stall to a third of the peak over the next ten degrees, and from there
 *  down to NOTHING at 60° and beyond (a plate broadside to the flow lifts nothing; a craft rising straight up on a
 *  lifting engine met its wings at −90° and was flung sideways by a third of their lift, 2026-11-12). */
export function liftCoef(alpha, AR, stallDeg) {
  const slope = 2 * Math.PI * (AR > 0 ? AR / (AR + 2) : 0), as = stallDeg * DEG, a = Math.abs(alpha), sg = Math.sign(alpha);
  if (a <= as) return slope * alpha;
  const post = slope * as * Math.max(0.33, 1 - (a - as) / (10 * DEG) * 0.67);
  return sg * post * Math.max(0, Math.min(1, (60 * DEG - a) / (60 * DEG - as - 10 * DEG)));
}
/** The wing's drag coefficient past the stall: a plate's form drag grows with the square of the sine of its angle to
 *  the flow, to a flat plate's broadside value at 90° (Drag coefficient: 1.28 for a flat plate square to the flow). */
export const stallDrag = (alpha) => FLAT_PLATE_CD * Math.sin(alpha) * Math.sin(alpha);
/** The speed (m/s) at which the wings carry the weight at the critical angle in the air at height h: the lowest it flies. */
export function stallSpeed(c, F, h = c.pose[3]) {
  const A = { ...AERO_DEF, ...(F.aero || {}) }, rho = airAt(h - SEA_LEVEL).rho, clmax = liftCoef(A.stall_deg * DEG, c.aero.AR, A.stall_deg);
  return rho > 0 && c.aero.S > 0 && clmax > 0 ? Math.sqrt((2 * c.mass * 1000 * gravityAt(h)) / (rho * c.aero.S * clmax)) : Infinity;
}
/**
 * One step of an aircraft (c.aero.winged): input = { pitch (-1..1, pull +), roll (-1..1, right +), yaw (rudder, right +),
 * throttle (0..1), up/down (the vertical thrusters, if any) }. Pose [face, u, v, h, yaw, pitch, roll]; vel [east, north, up].
 */
export function aircraftStep(c, input, dt, F, groundAt, hits) {
  const A = { ...AERO_DEF, ...(F.aero || {}) }, ae = c.aero;
  const gr = gravityAt(c.pose[3]), [face, u0, v0, h0] = c.pose;
  let yaw = c.pose[4], pitch = c.pose[5] || 0, roll = c.pose[6] || 0;
  let v = c.vel.slice();
  const V = Math.hypot(v[0], v[1], v[2]), rho = airAt(h0 - SEA_LEVEL).rho, q = 0.5 * rho * V * V;
  const m = c.mass * 1000, W = m * gr, auth = Math.min(1, V / A.v_ctrl);
  let ax = axesOf(yaw, pitch, roll);
  c.throttle = Math.max(0, Math.min(1, input.throttle ?? c.throttle ?? 0));
  // ---- the attitude: the pilot's rates (in the flow), the weathervane toward the velocity, the gear on the ground
  const vhat = V > 0.5 ? norm(v) : null;
  let w = [0, 0, 0];                                                    // angular velocity (rad/s) in the local frame
  const cmd = (k, axis, rate) => { w = add(w, axis, k * rate * DEG * auth); };
  if (!c.grounded) {
    cmd(Math.max(-1, Math.min(1, input.roll || 0)), ax.nose, A.roll_dps);
    cmd(Math.max(-1, Math.min(1, input.pitch || 0)), ax.right, A.pitch_dps);
    cmd(Math.max(-1, Math.min(1, input.yaw || 0)), ax.up, -A.yaw_dps);     // rudder right: the nose turns toward the right wing
    // static stability: the nose follows the flow — the tail's doing, which works while the flow is near the nose's
    // line and not at all broadside (a craft rising straight up on a lifting engine weathervaned its nose into its own
    // climb, tilted its thrust back and was flung off at 75 m/s, 2026-11-12): full under 20° off the nose, none at 60°
    if (vhat) {
      const off = Math.acos(Math.max(-1, Math.min(1, dot(vhat, ax.nose)))), weather = Math.max(0, 1 - Math.max(0, off - 20 * DEG) / (40 * DEG));
      w = add(w, cross(ax.nose, vhat), A.stab * auth * weather);
    }
    if (!input.roll) w = add(w, ax.nose, 0);                              // (no self-levelling: a bank is the pilot's to hold)
  } else {
    // on its gear: level, the rudder steers, and the nose comes up only when the wings nearly carry it
    const vs = stallSpeed(c, F, h0);
    w = add(w, ax.up, -(input.yaw || 0) * A.gear_roll * Math.min(1, V / 5));
    const wantPitch = V >= 0.7 * vs && (input.pitch || 0) > 0 ? 12 * DEG * input.pitch : 0;
    pitch += (wantPitch - pitch) * Math.min(1, 4 * dt);
    roll += (0 - roll) * Math.min(1, 4 * dt);
    ax = axesOf(yaw, pitch, roll);
  }
  if (w[0] || w[1] || w[2]) {
    const rot = (p) => norm(add(p, cross(w, p), dt));
    ax = { nose: rot(ax.nose), right: rot(ax.right), up: rot(ax.up) };
    // re-squared after the small turns: right stays square to the nose, up = right × nose (nose × right points DOWN —
    // the first run flew with its lift inverted on that one sign, 2026-11-11)
    ax.right = norm(add(ax.right, ax.nose, -dot(ax.right, ax.nose))); ax.up = cross(ax.right, ax.nose);
    [yaw, pitch, roll] = anglesOf(ax);
  }
  // ---- the forces (N), in the local frame
  let Fv = [0, 0, -W];                                                   // gravity always pulls (the operator's third point)
  const Tn = ae.T[1] * 1000 * c.throttle, Tr = ae.T[0] * 1000 * c.throttle;
  const Tu = ae.T[2] * 1000 * (input.up ? 1 : input.down ? 0 : (c.grounded ? 0 : Math.min(1, W / Math.max(1, ae.T[2] * 1000))));
  Fv = add(Fv, ax.nose, Tn); Fv = add(Fv, ax.right, Tr); Fv = add(Fv, ax.up, Tu);
  let alpha = 0, beta = 0, CL = 0, n = 0, stalled = false;
  if (vhat && rho > 0) {
    alpha = Math.atan2(-dot(vhat, ax.up), dot(vhat, ax.nose));
    beta = Math.asin(Math.max(-1, Math.min(1, dot(vhat, ax.right))));
    CL = liftCoef(alpha, ae.AR, A.stall_deg);
    stalled = Math.abs(alpha) > A.stall_deg * DEG;
    // the load limiter: no more lift than the structure's n_max weights (Angle of attack l.26)
    const Lmax = A.n_max * W;
    if (Math.abs(q * ae.S * CL) > Lmax) CL = Math.sign(CL) * Lmax / (q * ae.S);
    const L = q * ae.S * CL, lhat = norm(add(ax.up, vhat, -dot(ax.up, vhat)));
    const CD = A.cd0 + (ae.AR > 0 ? (CL * CL) / (Math.PI * ae.AR * A.e) : 0) + (stalled ? stallDrag(alpha) : 0), D = q * ae.S * CD;
    const Y = -q * ae.side * A.side_cd * Math.sin(beta);
    Fv = add(Fv, lhat, L); Fv = add(Fv, vhat, -D); Fv = add(Fv, ax.right, Y);
    n = L / W;
  }
  v = add(v, Fv, dt / m);
  // ---- the gear: on the ground it rolls along its nose OVER THE GROUND, brakes with the throttle shut; it rises only
  // when the forces on it point up (lift and the thrust's upward part over its weight) — never by the nose's angle alone:
  // projecting the velocity onto a pitched nose bounced it off the strip every other step and ate the thrust (the first
  // run froze at 46 m/s, 2026-11-11)
  if (c.grounded) {
    const nh = norm([ax.nose[0], ax.nose[1], 0]), along = dot(v, nh), fr = (c.throttle > 0.05 ? 0.3 : A.gear_brake) * dt;
    const kept = Math.sign(along) * Math.max(0, Math.abs(along) - fr);
    v = [nh[0] * kept, nh[1] * kept, Fv[2] > 0 ? v[2] : 0];
  }
  const sp = Math.hypot(v[0], v[1], v[2]);
  if (sp > F.vmax) { const k = F.vmax / sp; v = [v[0] * k, v[1] * k, v[2] * k]; }
  let u = u0 + v[0] * dt, vv = v0 + v[1] * dt, h = h0 + v[2] * dt;
  const g = groundAt(u, vv);
  if (h + c.bottom <= g) { h = g - c.bottom; if (v[2] < 0) v[2] = 0; if (!c.grounded) { pitch = Math.max(0, pitch); } c.grounded = true; }
  else c.grounded = false;
  // its body against the world: as craftStep (turned by yaw alone — a known limit)
  c.bumped = false;
  if (hits) {
    let base = new Set(hits([face, u0, v0, h0, c.pose[4]]));
    const into = (pose) => { const ins = hits(pose); if (ins.some((i) => !base.has(i))) return true; base = new Set(ins); return false; };
    const du = u - u0, dv = vv - v0, dh = h - h0, N = Math.max(1, Math.ceil(Math.hypot(du, dv, dh) / SWEEP)), keep = [1, 1, 1];
    let pu = u0, pv = v0, ph = h0;
    for (let k = 0; k < N; k++) {
      const tu = pu + keep[0] * du / N, tv = pv + keep[1] * dv / N, th = ph + keep[2] * dh / N;
      if (!into([face, tu, tv, th, yaw])) { pu = tu; pv = tv; ph = th; continue; }
      c.bumped = true;
      const tries = [[1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 0, 0], [0, 1, 0], [0, 0, 1]];
      const t = tries.find(([a, b, d]) => !into([face, a ? tu : pu, b ? tv : pv, d ? th : ph, yaw])) || [0, 0, 0];
      for (let i = 0; i < 3; i++) if (!t[i]) keep[i] = 0;
      if (t[0]) pu = tu; if (t[1]) pv = tv; if (t[2]) ph = th;
      if (!keep[0] && !keep[1] && !keep[2]) break;
    }
    if (!keep[0]) v[0] = 0; if (!keep[1]) v[1] = 0; if (!keep[2]) v[2] = 0;
    if (!keep[2] && dh < 0) c.grounded = true;
    u = pu; vv = pv; h = ph;
  }
  c.pose = [face, u, vv, h, yaw, pitch, roll];
  c.vel = v;
  c.air = { V, alpha, beta, n, stalled, auth, q };
  // the engines' work, for the exhaust everyone sees (#171): the throttle, and the thrust's direction in the ground plane
  const dir = Math.hypot(ax.nose[0], ax.nose[1]) > 1e-6 ? norm([ax.nose[0], ax.nose[1], 0]) : [0, 0, 0];
  const lift = ae.T[2] > 0 ? Tu / (ae.T[2] * 1000) : 0, push = Math.abs(ae.T[1]) > 0 ? c.throttle : 0;
  c.engine = { lift, push, throttle: Math.min(1, lift + push), dir: [dir[0], dir[1]] };
  return c;
}

// THE NAV UNIT (#173, doc/land-navigation.md 1.4): a craft holding one knows where it is by DEAD RECKONING — from a known
// position (a fix), advanced by its measured motion (Dead reckoning l.7) — as an inertial navigation system does, and with
// its fault: small errors in the measured acceleration integrate into a position error that keeps growing, ½·b·t² for an
// accelerometer error b (Inertial navigation system l.30-31: the best, 10 micro-g, are 50 m out after 17 minutes). The
// game's unit is ten times worse than the best — NAV_BIAS, a design choice — until satellites correct it (1.6).
export const NAV_BIAS = 100e-6 * 9.8;                   // m/s²: 100 micro-g
/** What the nav unit believes and says, t seconds after its last fix: its estimate of where the craft is (the true
 *  place pushed along `dir`, a unit vector fixed at the fix, by ½·b·t²), the error it knows it may have, and the bearing
 *  (degrees from north), distance and turn (degrees, + right) to `dest` [u, v] from that estimate for a craft facing yaw. */
export function navSays(pose, t, dir, dest, b = NAV_BIAS) {
  const err = 0.5 * b * t * t, u = pose[1] + dir[0] * err, v = pose[2] + dir[1] * err;
  const du = dest[0] - u, dv = dest[1] - v, dist = Math.hypot(du, dv);
  const bearing = ((Math.atan2(du, dv) * 180 / Math.PI) + 360) % 360, facing = ((pose[4] * 180 / Math.PI) % 360 + 360) % 360;
  const turn = ((bearing - facing + 540) % 360) - 180;
  return { est: [u, v], err, dist, bearing, turn };
}

/** The flight numbers a craft flies by, from the recipes' "flight" block — weighed against the gravity at its height
 *  (land-planet.js gravityAt: g (R/r)²; the surface's when no height is given). */
export function flightOf(F, mass, thrust, g = F.g) {
  const acc = mass > 0 ? thrust / mass : 0;
  return { acc, lifts: acc > g, weight: mass * g };
}

// THE AIR A CRAFT FLIES THROUGH (#174, doc/land-planet.md): drag ½ρv²c_dA (Drag equation l.6) from the air's density at its
// height (land-planet.js airAt — none above the air's top), with the craft's frontal area A and c_d of a flat face square
// to the flow (1.28, Drag coefficient) — a boxy craft's honest upper figure. It replaced a fixed damping (0.35 a second)
// that slowed a craft the same at 10 m as it would have at 50 km.
/** A craft's frontal area (m²), from its pieces (cm, boxAabb): the mean of its bounding box's three face areas — the
 *  same whichever way it moves (an approximation, a design choice). */
export function craftArea(pieces, boxAabb) {
  let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const b of pieces) { const a = boxAabb(b); for (let i = 0; i < 3; i++) { lo[i] = Math.min(lo[i], a[i]); hi[i] = Math.max(hi[i], a[i] + a[i + 3]); } }
  const [x, y, z] = [0, 1, 2].map((i) => (hi[i] - lo[i]) / 100);
  return (x * y + y * z + z * x) / 3;
}
const AREA_DEFAULT = 4;                       // m²: a craft that has not been measured (tests' bare craft objects)

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

/** STEPPING OFF (#194; operator 2026-11-12: "i exited the xfighter and fell into the townhall wall"): the pilot left the
 *  seat 1.5 m to the craft's right at the ground's height — whatever stood there. Now the spots around the seat are
 *  tried in order (right, left, behind, ahead, then wider) and the first FREE one is taken: `free(u, v)` says whether a
 *  player's body stands clear there (land.js collides at the ground's height). None free: null — the pilot stays put.
 *  Returns { u, v, tried } (tried: how many spots were looked at, for the trace). */
/** The surface under a point: the height of the first solid thing met scanning down from `top` by `step`, `floor` when
 *  nothing is met (the terrain's height) — a roof, a deck, a built floor counts, not only the ground (a pilot whose
 *  craft came to rest on the town hall's roof was "too high to step off" measured against the ground 5 m under the
 *  roof, and could neither leave nor land — operator, 2026-11-12). `solid(h)` says whether (u, v, h) is inside something. */
export function surfaceBelow(solid, top, floor, step = 0.1) {
  for (let h = top; h > floor; h -= step) if (solid(h)) return Math.min(top, h + step);
  return floor;
}
export function stepOffSpot(u, v, yaw, free) {
  const r = [Math.cos(yaw), -Math.sin(yaw)], f = [Math.sin(yaw), Math.cos(yaw)];
  const spots = [[r, 1.5], [r, -1.5], [f, -2.0], [f, 2.5], [r, 3.0], [r, -3.0], [f, -3.5], [f, 4.0], [r, 4.5], [r, -4.5]];
  for (let i = 0; i < spots.length; i++) {
    const [d, k] = spots[i], su = u + d[0] * k, sv = v + d[1] * k;
    if (free(su, sv)) return { u: su, v: sv, tried: i + 1 };
  }
  return null;
}

/**
 * Advance craft c by dt seconds. c = { pose: [face, u, v, h, yaw], vel: [vu, vv, vh], mass, thrust, bottom (m: its
 * lowest piece below the seat, ≤ 0), grounded }. input = { fwd: -1..1, side: -1..1, up: bool, down: bool, yaw }.
 * groundAt(u, v): the surface height there. hits(pose), if given: which of its body's points are inside something solid
 * there (bodyInside).
 * Returns c.
 */
export function craftStep(c, input, dt, F, groundAt, hits) {
  if (c.aero && c.aero.winged) return aircraftStep(c, input, dt, F, groundAt, hits);   // an aircraft (#191): see above
  const gr = gravityAt(c.pose[3]);                                     // gravity at its height (#174): g (R/r)²
  const { acc, lifts } = flightOf(F, c.mass, c.thrust, gr);
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
  if (c.grounded) { const f = Math.exp(-4 * dt); vu *= f; vv *= f; }   // on the ground: it slides to a stop (friction, not air)
  // vertical
  if (input.up && lifts) vh += (acc - gr) * dt;
  else if (input.down) vh -= gr * 0.8 * dt;
  else if (lifts && airborne) vh *= Math.exp(-2.5 * dt);              // hovering: the thrusters hold it
  else vh -= gr * dt;                                                  // falling, or resting on the ground
  // the air: ½ρv²c_dA against its velocity, as 1 / (1 + k v dt) — the implicit step, stable however thick the air
  // the air at its height above the sea (the game's heights run from the planet's RADIUS; the sea is at SEA_LEVEL)
  const k = (0.5 * airAt(c.pose[3] - SEA_LEVEL).rho * FLAT_PLATE_CD * (c.area || AREA_DEFAULT)) / (c.mass * 1000), sp0 = Math.hypot(vu, vv, vh);
  if (k > 0 && sp0 > 0) { const f = 1 / (1 + k * sp0 * dt); vu *= f; vv *= f; vh *= f; }
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
    // HELD UP BY ITS BODY, IT HAS LANDED: on uneven ground a long craft's belly or wing meets the ground before the
    // ground under its seat — it rested there on its engines, "1.4 m up", Down doing nothing, never landed (the X fighter,
    // live, 2026-11-10). A fall its body stops is a landing: grounded, engines idle.
    if (!keep[2] && dh < 0) c.grounded = true;
    u = pu; v = pv; h = ph; turned = yw;
  }
  c.pose = [face, u, v, h, turned];
  c.vel = [vu, vv, vh];
  // the engines' work this step, as shares of full thrust (acc is thrust / mass; g / acc is the weight's share)
  const wShare = acc > 0 ? Math.min(1, gr / acc) : 0;
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
