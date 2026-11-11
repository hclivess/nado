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

// ---- POSITIONING SATELLITES (#173, doc/land-navigation.md 1.6) ---------------------------------------------------------
// A satellite circles the planet's centre in a plane that does not spin with it: radius ORBIT.r, period ORBIT.T (two
// orbits a day, as GPS's two a sidereal day — Global Positioning System l.232), its plane inclined ORBIT.incl_deg to the
// equator, the constellation laid out as GPS's: six planes 60° apart round the equator, four satellites to each (l.230).
// The n-th launched takes the n-th slot: plane n % 6, place in it ⌊n / 6⌋ % 4, a quarter-orbit apart, each plane a
// twenty-fourth of an orbit on from the last (evenly — GPS's own spacing is uneven, l.230). Pure functions of n and time,
// so every page and the world server agree where each one is. In the planet's frame (land-world's: poles on ±y) only the
// spin matters — the tilt is the same for the orbit and the planet — so a satellite's place there is its orbit's place
// turned back by the spin: Sᵀ·p.
export const ORBIT = { r: 135520, T: 1200, incl_deg: 55, planes: 6, per_plane: 4 };   // land-recipes.json "rocket".orbit
/** Satellite n's place in planet 0's frame (metres from its centre) at wall-clock second t (since EPOCH). */
export function satPosition(n, t, O = ORBIT, planet = SYSTEMS[0].planets[0]) {
  const k = n % O.planes, j = Math.floor(n / O.planes) % O.per_plane, slots = O.planes * O.per_plane;
  const node = (2 * Math.PI * k) / O.planes, inc = (O.incl_deg * Math.PI) / 180;
  const u = (2 * Math.PI * t) / O.T + (2 * Math.PI * j) / O.per_plane + (2 * Math.PI * k) / slots;
  const N = [Math.cos(node), 0, Math.sin(node)];                                           // the ascending node
  const Q = [-Math.sin(node) * Math.cos(inc), Math.sin(inc), Math.cos(node) * Math.cos(inc)];   // 90° on in the plane
  const p = [0, 1, 2].map((i) => O.r * (Math.cos(u) * N[i] + Math.sin(u) * Q[i]));
  const th = (2 * Math.PI * t) / planet.day, c = Math.cos(th), s = Math.sin(th);
  return [c * p[0] - s * p[2], p[1], s * p[0] + c * p[2]];                                   // Sᵀ·p (S: spin about y)
}
/** The satellites above the horizon of a point at `at` (metres, planet frame): those whose direction from it is above
 *  its local horizontal plane — no elevation mask (a design choice; GPS counts those "with a clear horizon", l.234). */
export function satsInView(count, at, t, O = ORBIT) {
  const r = Math.hypot(...at), up = at.map((x) => x / r), out = [];
  for (let n = 0; n < count; n++) {
    const p = satPosition(n, t, O), d = [p[0] - at[0], p[1] - at[1], p[2] - at[2]];
    if (d[0] * up[0] + d[1] * up[1] + d[2] * up[2] > 0) out.push(n);
  }
  return out;
}
export const FIX_SATS = 4;   // three position coordinates and the receiver's clock error (Global Positioning System l.187, l.216)
