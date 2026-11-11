// land-planet.js — the planet as a physical body (operator 2026-11-11: "we need proper planetary physical properties like
// in Kerbal space"). Pure: the page, the tests and the world server's numbers all come from here. Every real-world
// constant is cited to the land research mirror (planet/, INDEX.md); every number the game sets is labelled a DESIGN
// CHOICE. doc/land-planet.md is the long form.
//
// THE BODY. The planet keeps its size (83,443 m, land-world.js R0) and its surface gravity (9.8 m/s², land-recipes.json
// flight.g) — the operator's choice (2026-11-11), as Kerbal's planets keep theirs. Its mass follows from them by Newton's
// law, and so do its density, escape speed, orbits and the gravity at any height (GM / r²): a small world with a
// strong pull is a very dense one, and that is stated, not hidden.
//
// THE AIR. A real atmosphere cannot stay on this planet (doc/land-planet.md: the pull weakens so fast with height that a
// standard atmosphere never thins out — no orbit would be free of drag — and its molecules move too near the escape
// speed to be kept). So, as Kerbal does, the air is real near the ground and ends at a set height: the 1976 standard
// atmosphere's whole profile, ground to its 86 km top, fitted between the ground and ATM_TOP — its temperatures, its
// pressures, its density by the barometric formula — and vacuum above. ATM_TOP is the one non-physical number here.

export const G = 6.6743e-11;                  // m³/(kg·s²) (Gravitational constant l.9: 6.67430(15) × 10⁻⁸ cm³ g⁻¹ s⁻²)
export const RADIUS = 83443;                  // m: land-world.js R0, land-cosmos.js planets[0].radius
export const SURFACE_G = 9.8;                 // m/s²: land-recipes.json flight.g (kept, the operator's choice)
export const DAY_S = 40 * 60;                 // s: land-cosmos.js DAY_S — one turn
export const GM = SURFACE_G * RADIUS * RADIUS;            // g = GM / R²
export const MASS = GM / G;
export const DENSITY = MASS / ((4 / 3) * Math.PI * RADIUS ** 3);
export const EARTH_DENSITY = 5513;            // kg/m³: Earth's mean density (Earth l.51, from NASA's Earth fact sheet)

/** Gravity (m/s²) at height h (m) above the planet's radius: GM / r². */
export const gravityAt = (h) => GM / (RADIUS + h) ** 2;
/** Escape speed (m/s) from height h: √(2GM / r). */
export const escapeSpeed = (h = 0) => Math.sqrt((2 * GM) / (RADIUS + h));
/** Circular orbital speed (m/s) at height h: √(GM / r) (Orbital speed l.51). */
export const orbitSpeed = (h) => Math.sqrt(GM / (RADIUS + h));
/** Period (s) of a circular orbit at height h: 2π r / v. */
export const orbitPeriod = (h) => (2 * Math.PI * (RADIUS + h)) / orbitSpeed(h);
/** The synchronous orbit: the height (m) whose period is one turn of the planet, r = (GM T² / 4π²)^⅓. */
export const SYNC_HEIGHT = Math.cbrt((GM * DAY_S * DAY_S) / (4 * Math.PI * Math.PI)) - RADIUS;
/** The speed (m/s) of the ground at the equator from the planet's turning: 2π R / day. */
export const EQUATOR_SPIN = (2 * Math.PI * RADIUS) / DAY_S;

// ---- THE ATMOSPHERE ---------------------------------------------------------------------------------------------------
// The 1976 standard atmosphere's layers (International Standard Atmosphere, the layer table): base geopotential height
// (m), temperature lapse (K/m; + is warming with height, as the table's lapse note), base temperature (K), base
// pressure (Pa); and the barometric formula's constants (Barometric formula l.8-10: R* = 8.31432 J/(mol·K) as the 1976
// standard takes it, M₀ = 0.0289644 kg/mol, g₀' = 9.80665 m/s²). Ground: 288.15 K, 101,325 Pa, 1.225 kg/m³.
const ISA = [[0, -0.0065, 288.15, 101325], [11000, 0, 216.65, 22632], [20000, 0.001, 216.65, 5474.9], [32000, 0.0028, 228.65, 868.02],
  [47000, 0, 270.65, 110.91], [51000, -0.0028, 270.65, 66.939], [71000, -0.002, 214.65, 3.9564]];
const ISA_TOP = 86000;                         // m geopotential: the table's last layer (Mesopause) — where its profile ends
const RSTAR = 8.31432, M0 = 0.0289644, G0P = 9.80665;
export const ATM_TOP = 30000;                  // m: the air's top here — DESIGN CHOICE (the one non-physical number; the
                                               // positioning satellites, 52,077 m up, are well above it)
/** The air at height h (m above sea level): { T (K), p (Pa), rho (kg/m³) } — the standard atmosphere at the matching
 *  fraction of its height (h / ATM_TOP of its 86 km), nothing at or above ATM_TOP. */
export function airAt(h) {
  if (h >= ATM_TOP) return { T: 0, p: 0, rho: 0 };
  const H = (Math.max(0, h) / ATM_TOP) * ISA_TOP;
  let b = ISA[0];
  for (const l of ISA) if (l[0] <= H) b = l;
  const [h0, a, T0, p0] = b, T = T0 + a * (H - h0);
  const p = a === 0 ? p0 * Math.exp((-G0P * M0 * (H - h0)) / (RSTAR * T0)) : p0 * (T0 / T) ** ((G0P * M0) / (RSTAR * a));
  return { T, p, rho: (p * M0) / (RSTAR * T) };
}
/** Drag (N) on a body of frontal area A (m²) and drag coefficient cd moving at u (m/s) through the air at height h:
 *  ½ ρ u² cd A (Drag equation l.6). */
export const dragAt = (h, u, cd, A) => 0.5 * airAt(h).rho * u * u * cd * A;
/** An engine's specific impulse (s) in air of pressure p: a fixed nozzle's thrust falls linearly with the outside
 *  pressure (F = ṁvₑ + (pₑ − pₐ)Aₑ, Rocket engine), so its Isp goes from its vacuum figure at p = 0 to its sea-level
 *  figure at sea-level pressure along a straight line. */
export const ispAt = (p, ispSea, ispVac) => ispVac - (ispVac - ispSea) * (p / 101325);
export const FLAT_PLATE_CD = 1.28;             // a flat face square-on to the flow (Drag coefficient, the table: "Flat plate
                                               // perpendicular to flow (3D)")

export const SEA_LEVEL = 96;                   // m: the game's heights are measured from RADIUS; the sea stands at 96 (land-world.js
                                               // SEA) — the air's "sea level" is there, so a grid height h is airAt(h - SEA_LEVEL)

// ---- AN ASCENT, FLOWN (#174) -------------------------------------------------------------------------------------------
// A rocket from its pad to the satellites' orbit, integrated step by step rather than read off one formula: gravity
// GM/r² at every height; thrust at a constant propellant flow (ṁ = F_sea / (Isp_sea g₀)), rising from its sea-level
// figure to its vacuum one as the air thins (a fixed nozzle: F = ṁvₑ + (pₑ − pₐ)Aₑ, Rocket engine); drag ½ρv²c_dA; up
// first, then a small pitch-over, then a GRAVITY TURN — thrust along the velocity, gravity bending the path over (Gravity
// turn) — burning until the path's highest point reaches the orbit, coasting there, and circularising with what is left
// (the rocket equation at vacuum Isp, Tsiolkovsky l.10). DESIGN CHOICES, labelled: the pitch-over (at KICK_SPEED, KICK_DEG
// for KICK_S), no help from the planet's spin (it launches as if from a pole — conservative), the step ASCENT_DT.
export const G0 = 9.80665, KICK_SPEED = 60, KICK_DEG = 20, KICK_S = 8, ASCENT_DT = 0.05;
/** o: { dryKg, propKg, thrustSeaN, ispSea, ispVac, area (m²), cd, padH (grid height of the pad), targetR (m) }.
 *  Returns { ok, why, apoR, periR, maxQ (Pa), burnS, propLeftKg, path: [[t, height above sea, downrange m, speed]] }. */
export function ascent(o) {
  const mdot = o.thrustSeaN / (o.ispSea * G0), thrustVac = o.thrustSeaN * (o.ispVac / o.ispSea);
  let x = 0, y = RADIUS + o.padH, vx = 0, vy = 0, m = o.dryKg + o.propKg, t = 0, burn = 0, maxQ = 0;
  const path = [], seaH = (r) => r - RADIUS - SEA_LEVEL;
  const orbitOf = () => {                                              // apo- and periapsis of the present path (vis-viva)
    const r = Math.hypot(x, y), v2 = vx * vx + vy * vy, h = x * vy - y * vx, eps = v2 / 2 - GM / r;
    const a = -GM / (2 * eps), e = Math.sqrt(Math.max(0, 1 + (2 * eps * h * h) / (GM * GM)));
    return eps < 0 ? { apo: a * (1 + e), peri: a * (1 - e) } : { apo: Infinity, peri: a * (1 - e) };
  };
  let phase = "burn", kickT = null;
  for (let k = 0; k < 400000; k++) {
    const r = Math.hypot(x, y), air = airAt(seaH(r)), v = Math.hypot(vx, vy), q = 0.5 * air.rho * v * v;
    maxQ = Math.max(maxQ, q);
    if (k % 20 === 0) path.push([Math.round(t * 10) / 10, Math.round(seaH(r)), Math.round(RADIUS * Math.atan2(x, y)), Math.round(v)]);
    let ax = (-GM * x) / r ** 3, ay = (-GM * y) / r ** 3;
    if (v > 0) { const d = (q * o.cd * o.area) / m; ax -= (d * vx) / v; ay -= (d * vy) / v; }
    // thrust whenever the path's highest point is short of the orbit and there is propellant: in the air drag pulls the
    // highest point back down, and a burn cut off once — when it first reached the orbit — left the rocket 94 km short
    // (2026-11-11, the first runs); so it burns again whenever it falls short, coasting only when it is enough
    phase = m - mdot * ASCENT_DT > o.dryKg && orbitOf().apo < o.targetR ? "burn" : "coast";
    if (phase === "burn") {
      {
        const F = o.thrustSeaN + (thrustVac - o.thrustSeaN) * (1 - air.p / 101325);
        let dx = x / r, dy = y / r;                                     // up
        if (v >= KICK_SPEED) {
          if (kickT === null) kickT = t;
          if (t - kickT < KICK_S) {                                  // the pitch-over: KICK_DEG from up, downrange (+x)
            const c = Math.cos((KICK_DEG * Math.PI) / 180), sn = Math.sin((KICK_DEG * Math.PI) / 180), ex = y / r, ey = -x / r;
            dx = c * (x / r) + sn * ex; dy = c * (y / r) + sn * ey;
          } else { dx = vx / v; dy = vy / v; }                          // the gravity turn: along the velocity
        }
        ax += (F / m) * dx; ay += (F / m) * dy;
        m -= mdot * ASCENT_DT; burn += ASCENT_DT;
      }
    }
    vx += ax * ASCENT_DT; vy += ay * ASCENT_DT; x += vx * ASCENT_DT; y += vy * ASCENT_DT; t += ASCENT_DT;
    const rr = Math.hypot(x, y);
    if (rr < RADIUS + o.padH - 1 && t > 1) return { ok: false, why: "it fell back", apoR: 0, periR: 0, maxQ, burnS: burn, propLeftKg: m - o.dryKg, path };
    if (phase === "coast" && vx * x + vy * y <= 0) {                   // at the highest point: circularise if it can
      const ob = orbitOf(), vt = Math.abs(x * vy - y * vx) / rr, need = Math.sqrt(GM / rr) - vt;
      const have = o.ispVac * G0 * Math.log(m / o.dryKg);
      path.push([Math.round(t * 10) / 10, Math.round(seaH(rr)), Math.round(RADIUS * Math.atan2(x, y)), Math.round(Math.hypot(vx, vy))]);
      if (rr < o.targetR * 0.99) return { ok: false, why: "it ran out of propellant below the orbit", apoR: ob.apo, periR: ob.peri, maxQ, burnS: burn, propLeftKg: m - o.dryKg, path };
      if (have < need) return { ok: false, why: "not enough left to circularise", apoR: ob.apo, periR: ob.peri, maxQ, burnS: burn, propLeftKg: m - o.dryKg, path };
      const mAfter = m / Math.exp(need / (o.ispVac * G0));
      return { ok: true, why: null, apoR: rr, periR: rr, maxQ, burnS: burn + (m - mAfter) / mdot, propLeftKg: mAfter - o.dryKg, path };
    }
  }
  return { ok: false, why: "it did not reach its highest point", apoR: 0, periR: 0, maxQ, burnS: burn, propLeftKg: m - o.dryKg, path };
}

/** Everything a page shows about the planet, computed. */
export function facts() {
  return { radius: RADIUS, g: SURFACE_G, mass: MASS, density: DENSITY, densityTimesEarth: DENSITY / EARTH_DENSITY,
    gm: GM, escape: escapeSpeed(0), orbitLow: orbitSpeed(ATM_TOP), periodLow: orbitPeriod(ATM_TOP), day: DAY_S,
    equatorSpin: EQUATOR_SPIN, syncHeight: SYNC_HEIGHT, airTop: ATM_TOP, sea: airAt(0), air10: airAt(10000) };
}
