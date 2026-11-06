// land-cosmos.js — the sky as a real place (doc/land.md "The cosmos"): stars and planets with real sizes at real
// distances, in SI units (metres, seconds) and doubles. "make sun a real object in a real distance, we are going
// interstellar in the end" (operator, 2026-11-06).
//
// FRAMES. Each system has an INERTIAL frame (metres, the star at its origin, orbits in the x-z plane). A planet's own
// frame is land-world's (the cube-sphere axes, poles on ±y): it is TILTED about the inertial x axis and SPINS about its
// pole, so day and night are the planet turning under a sun that stays where it is — not a light that circles. Every
// direction the page draws (the sun, the background stars) is the real inertial direction carried into the planet's
// frame; the sun is drawn at its true angle and apparent size (angularRadius), which is what a real distance looks like.
// Travel between planets and systems later moves the OBSERVER through these frames; nothing here assumes planet 0.
//
// Time is wall-clock seconds since EPOCH (the same instant on every screen); a day is DAY_S, a year a set number of days.

export const AU = 1.495978707e11;
export const EPOCH = 1793000000;                 // 2026-10-26: t = 0 of every orbit and spin
export const DAY_S = 40 * 60;                    // one turn of planet 0: 40 minutes (land.js day/night)

// The first system. Its star is a little smaller and cooler than the Sun; planet 0 sits 0.8 AU out, so the star looks
// about the size the Sun looks from Earth (~0.6°). A year is 30 of the planet's days: 20 hours of wall-clock time.
export const SYSTEMS = [{
  id: 0, name: "Nado",
  star: { radius: 6.3e8, luminosity: 0.8, colour: [1.0, 0.94, 0.86] },
  planets: [{ id: 0, radius: 83443, a: 0.8 * AU, yearDays: 30, day: DAY_S, tilt: 0.36, phase: 0.9 }],
}];

const planetOf = (sys, id) => sys.planets.find((p) => p.id === id);

/** The planet's place on its orbit, in the inertial frame (metres). Circular for now: one radius, one speed. */
export function planetPosition(planet, t) {
  const M = planet.phase + (2 * Math.PI * t) / (planet.yearDays * planet.day);
  return [planet.a * Math.cos(M), 0, planet.a * Math.sin(M)];
}

/** Planet frame -> inertial frame, as a 3x3 row-major matrix: tilt about x, then spin about the (tilted) pole. */
export function planetToInertial(planet, t) {
  const th = (2 * Math.PI * t) / planet.day, ct = Math.cos(th), st = Math.sin(th);
  const ca = Math.cos(planet.tilt), sa = Math.sin(planet.tilt);
  // spin S about y, then tilt X about x:  M = X · S
  const S = [ct, 0, st, 0, 1, 0, -st, 0, ct];
  const X = [1, 0, 0, 0, ca, -sa, 0, sa, ca];
  const m = new Array(9).fill(0);
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) for (let k = 0; k < 3; k++) m[r * 3 + c] += X[r * 3 + k] * S[k * 3 + c];
  return m;
}
const mulT = (m, v) => [m[0] * v[0] + m[3] * v[1] + m[6] * v[2], m[1] * v[0] + m[4] * v[1] + m[7] * v[2], m[2] * v[0] + m[5] * v[1] + m[8] * v[2]];

/** What a planet's sky holds at wall-clock second `t` (default now): the star's direction in the planet's frame, its
 *  distance and apparent size, and how bright it is relative to the Sun seen from Earth. */
export function sunFrom(planetId = 0, t = Date.now() / 1000 - EPOCH, sysId = 0) {
  const sys = SYSTEMS[sysId], planet = planetOf(sys, planetId);
  const p = planetPosition(planet, t), toStar = [-p[0], -p[1], -p[2]];
  const dist = Math.hypot(...toStar);
  const dirI = toStar.map((x) => x / dist);
  const dir = mulT(planetToInertial(planet, t), dirI);    // inertial -> planet: the transpose of a rotation
  return { dir, distance: dist, angularRadius: Math.asin(sys.star.radius / dist),
           flux: sys.star.luminosity * (AU / dist) ** 2, colour: sys.star.colour };
}

/** The rotation that carries inertial directions (the fixed stars) into the planet's frame, row-major 3x3. */
export function skyRotation(planetId = 0, t = Date.now() / 1000 - EPOCH, sysId = 0) {
  const m = planetToInertial(planetOf(SYSTEMS[sysId], planetId), t);
  return [m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]];      // the transpose
}
