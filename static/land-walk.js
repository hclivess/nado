// land-walk.js — how a walker moves over the Land planet (static/land.js calls it once a frame). Pure: the world comes in
// as `collides(u, v, h)` (does a body standing at h there overlap anything solid), so tests walk it over real slopes.
//
// THE WALK IS SMOOTH ("the walking animation includes some fucking jitterjumping", operator 2026-11-06). The old step
// lifted a walker up a slope in 5 cm notches, which left them hovering a few centimetres up, so the next frame counted them
// AIRBORNE — and an airborne walker may not step up, so every other frame uphill stopped dead, and downhill was a fall
// and a landing per frame. Now:
//   * climbing finds the surface EXACTLY (a bisection between blocked and free, never a notch above it);
//   * a grounded walker stays on the ground going downhill (snapped down up to SNAP), so only a real drop is a fall;
//   * the eye follows the body through a short smoothing (eyeH), so a step onto a block glides instead of snapping.
export const SNAP = 0.6;              // how far below a grounded walker the ground may fall away and still be walked on
const BISECT = 14;
const UNBURY = 4;                     // how far up a buried walker is lifted to find free room                    // 2^-14 of a step: well under a millimetre

/** Lowest free height in (lo, hi] at (u, v) — `lo` is blocked, `hi` free. */
function surface(collides, u, v, lo, hi) {
  for (let n = 0; n < BISECT; n++) { const mid = (lo + hi) / 2; if (collides(u, v, mid)) lo = mid; else hi = mid; }
  return hi;
}

/** Advance walker P by dt. wish: [du, dv] wished velocity (grid units/s); jump: pressed; C: { GRAV, JUMP, STEP }. */
export function walk(P, wish, jump, dt, collides, C) {
  // buried (a block placed into the body — by this player before that was refused, or by anyone else; ground that rose
  // under them): rise to the nearest free height rather than stay stuck inside ("build oneself into the terrain")
  if (!P.fly && collides(P.u, P.v, P.h)) {
    for (let lift = 0.05; lift <= UNBURY; lift += 0.05) if (!collides(P.u, P.v, P.h + lift)) { P.h = surface(collides, P.u, P.v, P.h + lift - 0.05, P.h + lift); P.vh = 0; P.ground = true; break; }
  }
  if (P.fly) {
    P.vu = wish[0]; P.vv = wish[1];
  } else {
    const k = P.ground ? 1 : 0.25;                       // a little air control
    P.vu += (wish[0] - P.vu) * Math.min(1, dt * 12 * k); P.vv += (wish[1] - P.vv) * Math.min(1, dt * 12 * k);
    P.vh -= C.GRAV * dt;
    if (jump && P.ground) { P.vh = C.JUMP; P.ground = false; }
  }
  // per axis, so a wall stops one direction and the player slides along it; a slope or a low step is climbed (up to
  // STEP) to the exact surface
  const move = (nu, nv) => {
    if (!collides(nu, nv, P.h)) return true;
    if (!P.fly && !P.ground) return false;
    if (collides(nu, nv, P.h + C.STEP)) return false;
    P.h = surface(collides, nu, nv, P.h, P.h + C.STEP);
    return true;
  };
  const nu = P.u + P.vu * dt; if (move(nu, P.v)) P.u = nu; else P.vu = 0;
  const nv = P.v + P.vv * dt; if (move(P.u, nv)) P.v = nv; else P.vv = 0;
  if (!P.fly && P.ground && P.vh <= 0 && !collides(P.u, P.v, P.h - 1e-4) && collides(P.u, P.v, P.h - SNAP)) {
    P.h = surface(collides, P.u, P.v, P.h - SNAP, P.h);  // downhill: stay on the ground
    P.vh = 0;
  } else {
    const nh = P.h + P.vh * dt;
    if (!collides(P.u, P.v, nh)) { P.h = nh; P.ground = false; }
    else {
      if (P.vh < 0) { P.ground = true; P.h = surface(collides, P.u, P.v, nh, P.h); }   // landed, exactly on the surface
      P.vh = 0;
    }
  }
  // the eye: follows the body, smoothing a sudden step (a block climbed, a ledge stepped off); a fall or a jump is followed
  // at once, so nothing lags what the player is doing
  if (P.eyeH === undefined || P.fly || !P.ground || Math.abs(P.h - P.eyeH) > 1.2) P.eyeH = P.h;
  else P.eyeH += (P.h - P.eyeH) * Math.min(1, dt * 14);
}

// TREE TRUNKS ARE SOLID ("trees have no collision", operator 2026-11-06): a log cell is a cylinder of TRUNK_R round its
// cell's centre, as the model draws it (land-trees.js), tested against the body's square — a body's corner points sit
// 0.6 m apart and would let a trunk through between them. Leaves stay walk-through.
export const TRUNK_R = 0.26;
/** Does a body (half-width `half`, height `tall`) standing at (u, v, h) touch a trunk? isLog(cu, cv, ch): a log cell. */
export function trunkAt(u, v, h, half, tall, isLog) {
  for (let cu = Math.floor(u - half - TRUNK_R); cu <= Math.floor(u + half + TRUNK_R); cu++)
    for (let cv = Math.floor(v - half - TRUNK_R); cv <= Math.floor(v + half + TRUNK_R); cv++) {
      const x = Math.max(u - half, Math.min(cu + 0.5, u + half)) - (cu + 0.5), y = Math.max(v - half, Math.min(cv + 0.5, v + half)) - (cv + 0.5);
      if (x * x + y * y >= TRUNK_R * TRUNK_R) continue;
      for (let ch = Math.floor(h); ch <= Math.floor(h + tall - 0.01); ch++) if (isLog(cu, cv, ch)) return true;
    }
  return false;
}
