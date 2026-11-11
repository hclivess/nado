// land-shapes.js — PARTS (#175; operator 2026-11-11: "this is xwing … not your shitty jet full of fucking disconnect metal
// plates", "your whole fucking building system is fuck", "there are gaps between every fucking part"). A box cannot be a
// round engine, a tapering fuselage, a nose or a thin swept wing — out of boxes those were 267 stepped plates with a seam
// at every step. A PART is one modelled solid filling its own box: the box (x, z, y, w, d, h) still places, turns, collides
// and joins a craft exactly as every piece does; what is drawn inside it, what is solid inside it and how much material
// it takes follow its shape. Parts may run INTO one another (land-world.js piecesClash: a part never refuses a neighbour
// and is refused by none), which is what closes the gaps: a wing is rooted inside the hull, an engine sits half in its wing.
//
// THE CODE. A piece's shape is one byte (land-world.js commitmentBytes carried it from the start, so a part changes no
// format). 0 is a box and 1..4 the slopes, as before; from 16 a part: 16 + 10 × type + variant. A CODE'S MEANING IS
// PERMANENT once a plot holds it — a new part is a new type appended to TYPES, never a change to an old one's outline.
// Every part is laid out in its piece's own frame — x across its width, y up its height, z along its depth, 0 at the BACK
// and the depth at the FRONT — and turned with it (yaw, pitch, roll) like any turned piece.
//
//   0 tube     round (oval: its width and height) along z, narrowing to the taper at the front: a cylinder at 1.0, nearly
//              a cone at 0.1; closed at both ends                                        variant 0..9: taper (v + 1) / 10
//   1 body     a box narrowing about its middle to the taper at the front                variant: taper
//   2 hull     a fuselage: eight-sided — a flat deck, a shoulder each side, tall sides leaning out a little down to the
//              chine, lower sides curling under to a flat belly — narrowing about its middle to the taper at the front in
//              WIDTH and half as much in height (a fuselage narrows more than it lowers: the side photographs)
//                                                                                        variant: taper
//   3 wing     a panel: its whole depth the chord at the root (x = 0), the taper of it at the tip (x = width), the trailing
//              edge straight across the back, the leading edge swept; chamfered edges; thinning to 0.6 at the tip about
//              its middle plane (so the same wing rolled half a turn is the other side's wing)  variant: taper
//   4 engine   a nacelle: a cowl with a rounded lip round a dark throat, a ringed centre cone behind cross struts, a
//              narrower ribbed turbine and a nozzle with a glowing exit (variant 0 only)
//   5 cannon   a housing, a spoked collar, a sleeve, a long barrel, a two-armed flash suppressor and a tip (variant 0)
//   6 dome     half an ellipsoid on its base (variant 0)
//   7 nose     a hull's nose cone: the hull's eight sides drawn in along a curve to a blunt, wide and low tip
//                                                        variant 0..9: droop — 0 the tip on the middle line, 9 a flat belly
//   8 canopy   a cockpit's glazing: a roof at the back, a long windscreen sloping down to the front, two panes a side, in
//              a dark frame over a dark floor (variant 0); in glass
//   9 ring     a hoop round z: a tube with a hole through it — a painted band round an engine, a pipe, a rim
//                                                        variant 0..9: the hole 0.50, 0.55 … 0.95 of the outside
//
// PROPORTIONS. The outlines below (where the hull's ridge sits, how deep the engine's throat is, the cannon's stations)
// are DESIGN CHOICES taken by eye from pictures — the operator's reference and the Commons photographs mirrored in the
// land research (xwing/, INDEX.md) — not measurements: no dimensioned drawing was found. Sizes are the builder's: a part
// takes its piece's width, depth and height, whatever they are.
export const FIRST = 16;
export const TYPES = ["tube", "body", "hull", "wing", "engine", "cannon", "dome", "nose", "canopy", "ring"];
export const TUBE = 0, BODY = 1, HULL = 2, WING = 3, ENGINE = 4, CANNON = 5, DOME = 6, NOSE = 7, CANOPY = 8, RING = 9;
// how many variants each type has: a byte outside them is no part (and is refused: boxOk), so an unused variant stays
// free to be given a meaning later
export const VARIANTS = [10, 10, 10, 10, 1, 1, 1, 10, 1, 10];
/** The shape byte of a type's variant (0..9). */
export const code = (type, variant = 0) => FIRST + 10 * type + variant;
/** The shape byte of a tapering type (tube, body, hull, wing) at a taper 0.1..1.0, to the nearest tenth. */
export const tapered = (type, taper = 1) => code(type, Math.max(0, Math.min(9, Math.round(taper * 10) - 1)));
/** { type, v } of a shape byte, or null for a box, a slope and any byte that is no part. */
export function decode(s) {
  if (!Number.isInteger(s) || s < FIRST) return null;
  const type = Math.floor((s - FIRST) / 10), v = (s - FIRST) % 10;
  return type < TYPES.length && v < VARIANTS[type] ? { type, v } : null;
}
export const isPart = (s) => decode(s) !== null;

// TONES: what a triangle is made of. 0 the piece's own material; the others are fixed, whatever the piece is made of —
// an engine's throat is dark and its exit glows in any skin. land-world.js TONE_BLOCK names the block each is drawn as.
export const MATERIAL = 0, DARK = 1, STEEL = 2, GLOW = 3;

// the hull's section, right side, from the belly's edge up to the deck's: [half width, height] as shares of its width
// and height — the belly's edge, the chine (the widest), the shoulder, the deck's edge. The tall side between the chine
// and the shoulder is the facet a stripe is laid on.
export const HULL_SECTION = [[0.26, 0], [0.5, 0.36], [0.46, 0.82], [0.34, 1]];
// the nose's tip against its base: wide and low
const NOSE_TIP_W = 0.6, NOSE_TIP_H = 0.36;
// a wing's thickness at the tip against the root's
const WING_TIP_THICK = 0.6;
// an engine, back to front (z as a share of its length, radius as a share of its half width): [z, r, tone of the surface
// from this station to the next]. It runs out along the nozzle, over the turbine's ribs and the cowl to the lip, then
// back down the throat and out along the centre cone — one closed outline, so the inside walls face inward by themselves
const ENGINE_PROFILE = [
  [0.035, 0, GLOW], [0.035, 0.58, DARK], [0, 0.64, STEEL], [0, 0.7, STEEL], [0.15, 0.66, DARK],
  [0.15, 0.57, DARK], [0.19, 0.57, DARK], [0.19, 0.61, DARK], [0.215, 0.61, DARK], [0.215, 0.57, DARK], [0.27, 0.57, DARK],
  [0.27, 0.61, DARK], [0.295, 0.61, DARK], [0.295, 0.57, DARK], [0.35, 0.57, DARK], [0.35, 0.63, DARK], [0.39, 0.63, DARK],
  [0.39, 0.57, DARK], [0.46, 0.57, MATERIAL], [0.52, 0.93, MATERIAL], [0.545, 1, MATERIAL], [0.965, 1, MATERIAL],
  [0.99, 0.985, MATERIAL], [1, 0.95, MATERIAL], [0.995, 0.915, DARK], [0.8, 0.88, DARK],
  [0.8, 0.5, STEEL], [0.825, 0.5, STEEL], [0.825, 0.43, STEEL], [0.85, 0.43, STEEL], [0.85, 0.36, STEEL], [0.875, 0.36, STEEL],
  [0.875, 0.29, STEEL], [0.9, 0.29, STEEL], [0.9, 0.22, STEEL], [0.925, 0.22, STEEL], [0.925, 0.14, STEEL], [0.95, 0.14, STEEL],
  [0.95, 0, STEEL],
];
const ENGINE_STRUT_Z = [0.95, 0.972], ENGINE_STRUT_R = 0.93, ENGINE_STRUT_T = 0.045;
// a cannon, back to front, the same way
const CANNON_PROFILE = [
  [0, 0, DARK], [0, 0.55, DARK], [0.012, 0.76, DARK], [0.03, 0.86, DARK], [0.3, 0.86, MATERIAL], [0.3, 1, MATERIAL],
  [0.335, 1, MATERIAL], [0.335, 0.93, MATERIAL], [0.322, 0.93, DARK], [0.322, 0.5, MATERIAL], [0.36, 0.44, MATERIAL],
  [0.56, 0.44, MATERIAL], [0.56, 0.36, MATERIAL], [0.855, 0.36, MATERIAL], [0.855, 0.5, MATERIAL], [0.875, 0.5, MATERIAL],
  [0.875, 0.24, MATERIAL], [1, 0.24, MATERIAL], [1, 0, MATERIAL],
];
const CANNON_SPOKES = 12, CANNON_SPOKE = [[0.322, 0.5], [0.333, 0.5], [0.333, 0.93], [0.322, 0.93]];
// the suppressor's arm in (z, r): a blade curving forward and outward, swept through CANNON_ARM_DEG either side of up and
// of down
const CANNON_ARM = [[0.857, 0.45], [0.866, 0.66], [0.883, 0.84], [0.905, 0.96], [0.93, 1], [0.93, 0.93], [0.912, 0.88], [0.895, 0.76], [0.882, 0.6], [0.876, 0.45]];
const CANNON_ARM_DEG = 38;
// a canopy, as shares of its width, height and depth: the roof's edges, the side post's foot, the windscreen's foot
const GLAZING = { roofX: 0.2, roofBack: 0.06, roofFront: 0.4, post: 0.42, frontX: 0.25, frame: 4 };
const profileR = (prof, z) => { let r = 0; for (let i = 0; i + 1 < prof.length; i++) { const [z0, r0] = prof[i], [z1, r1] = prof[i + 1]; if (z1 > z0 && z >= z0 && z <= z1) r = Math.max(r, r0 + ((r1 - r0) * (z - z0)) / (z1 - z0)); } return r; };

// ---- what a part takes -----------------------------------------------------------------------------------------------
// The share of its box a part fills, in THOUSANDTHS and in whole numbers only: scripts/land_server.py part_fill computes
// the same number the same way (integer arithmetic on both sides — a float product could round apart on the two), and a
// piece is charged, refunded and weighed by it (land-world.js boxVolume). The parts test holds each against the drawn
// solid's real volume.
//
// SHELLS (a DESIGN CHOICE, labelled): a hull, a nose, a wing, a canopy and a dome are SKINS — hollow, as an aircraft's
// are — and take a TENTH of the material their solid would (SHELL). A tube, a body, a ring and a cannon are solid: a body
// at taper 1.0 is exactly a box, and must not be a cheaper box. The check on the tenth: a 12.5 m fighter of these parts
// (a 9.6 m hull and nose, four 5.35 m wings) is ~30 m³ as solids, so ~3 m³ of steel plate at 1.5 t/m³ (land-recipes.json
// flight.density) = ~4.5 t of structure, ~8 t with four engines and its cannons — the empty weight of a real single-seat
// fighter of that size (the F-16C Block 50: 18,900 lb empty = 8,573 kg, 49 ft 5 in long = 15.06 m — the specification
// box of land research fighter/wikipedia-F-16_Fighting_Falcon.wikitext).
// Solid, the same craft would weigh 45 t and no engine in the rules would lift it.
//
// An ENGINE is a thruster: it is made of the thruster's material, and counts as as many thrusters as its volume holds
// (land-world.js engineCount) — for what it costs, what it weighs and what it pushes.
export const SHELL = 10;
export const hollow = (s) => { const p = decode(s); return !!p && (p.type === HULL || p.type === NOSE || p.type === WING || p.type === CANOPY || p.type === DOME); };
const HULL_FILL = 859;                                     // the eight-sided section's share of its box: 2 × 0.4296
const FIXED_FILL = { [ENGINE]: 415, [CANNON]: 260, [DOME]: 523, [CANOPY]: 510 };
export function fill(s) {
  const p = decode(s);
  if (!p) return null;
  const k = p.v + 1;                                       // the taper in tenths
  switch (p.type) {
    case TUBE: return Math.floor((785 * (100 + 10 * k + k * k)) / 300);      // an oval frustum: π/4 · (1 + t + t²) / 3
    case BODY: return Math.floor((1000 * (100 + 10 * k + k * k)) / 300);
    case HULL: return Math.floor((HULL_FILL * (250 + 25 * k + k * k)) / 600);     // ∫ (1 − az)(1 − az/2) dz, a = 1 − taper
    case WING: return wingFill(k);
    case NOSE: return 527;                                 // measured: the hull's section drawn in to the blunt tip
    case RING: { const h = 10 + p.v; return Math.floor((785 * (400 - h * h)) / 400); }   // π/4 · (1 − hole²), hole = h / 20
  }
  return FIXED_FILL[p.type];
}
// a wing: ∫ chord(x) · thick(x) dx for a chord 1 → t and a thickness 1 → 0.6, both straight — (2.6 + 2.2 t) / 6 of the
// plain slab — less its chamfers (0.98 of it left, measured on a wing fifteen times as deep as thick)
const wingFill = (k) => Math.floor((980 * (260 + 22 * k)) / 600);

/** Is the point (x, y, z), each 0..1 across the piece's own box (z = 1 its front), inside the part? An outline for
 *  walking into it and aiming at it — the drawn surface is tris(). */
export function inside(s, x, y, z) {
  const p = decode(s);
  if (!p) return true;
  const t = (p.v + 1) / 10, cx = x - 0.5, cy = y - 0.5;
  switch (p.type) {
    case TUBE: { const r = 0.5 * (1 - (1 - t) * z); return cx * cx + cy * cy <= r * r; }
    case RING: { const q = cx * cx + cy * cy, hole = 0.25 + 0.025 * p.v; return q <= 0.25 && q >= hole * hole; }
    case ENGINE: { const r = 0.5 * profileR(ENGINE_PROFILE.slice(0, 24), z); return cx * cx + cy * cy <= r * r; }
    case CANNON: { const r = 0.5 * profileR(CANNON_PROFILE, z); return cx * cx + cy * cy <= r * r; }
    case BODY: { const k = 1 - (1 - t) * z; return Math.abs(cx) <= 0.5 * k && Math.abs(cy) <= 0.5 * k; }
    case HULL: return hullHas(cx / (1 - (1 - t) * z), cy / (1 - ((1 - t) * z) / 2));
    case NOSE: { const [sw, sh, dy] = noseAt(z, p.v); return hullHas(cx / sw, (cy - dy) / sh); }
    case WING: { const k = 1 - (1 - WING_TIP_THICK) * x; return z <= 1 - (1 - t) * x && Math.abs(cy) <= 0.5 * k; }
    case DOME: return cx * cx * 4 + (z - 0.5) * (z - 0.5) * 4 + y * y <= 1;
    case CANOPY: {
      const c = GLAZING, top = z <= c.roofFront ? 1 : (1 - z) / (1 - c.roofFront);       // under the roof, then the windscreen
      const half = z <= c.post ? 0.5 : 0.5 - ((0.5 - c.frontX) * (z - c.post)) / (1 - c.post);
      return y <= top && Math.abs(cx) <= half - (half - (0.5 - c.roofX)) * Math.min(1, y);
    }
  }
  return true;
}
// inside the hull's eight-sided section? (cx, cy about the middle of a unit square)
function hullHas(cx, cy) {
  const y = cy + 0.5, S = HULL_SECTION;
  if (!(y >= 0 && y <= 1)) return false;
  for (let i = 0; i + 1 < S.length; i++) if (y <= S[i + 1][1]) return Math.abs(cx) <= S[i][0] + ((S[i + 1][0] - S[i][0]) * (y - S[i][1])) / (S[i + 1][1] - S[i][1]);
  return false;
}
// a nose's section at z (0 its base, 1 its tip): [width, height] against the base's and how far its middle has dropped
function noseAt(z, v) {
  const e = Math.pow(Math.min(1, z / 0.94), 1.45);                          // drawn in along a curve…
  let sw = 1 - (1 - NOSE_TIP_W) * e, sh = 1 - (1 - NOSE_TIP_H) * e;
  if (z > 0.94) { const q = (z - 0.94) / 0.06, round = Math.sqrt(1 - 0.45 * q * q); sw *= round; sh *= round; }   // …and rounded off blunt
  return [sw, sh, -(v / 9) * 0.5 * (1 - sh)];
}

// ---- a part as triangles ---------------------------------------------------------------------------------------------
// tris(s, w, d, h) -> { n, pos, nor, tone }: the part's surface for a piece w across, d deep and h high (cm), in the piece's
// own frame from its low corner — pos and nor hold x (across), y (up), z (forward) for each of a triangle's three corners,
// tone one number a triangle. Built at the piece's REAL size (not a unit shape stretched): a chamfer is as wide as the
// wing is thick, and a normal is the surface's own. Every triangle is wound counter-clockwise seen from outside in this
// right-handed frame; a caller in a mirrored frame (the plot's east, up, north; three.js's −z forward) swaps two corners.
const cache = new Map();
export function tris(s, w, d, h) {
  const p = decode(s);
  if (!p) return null;
  const key = s + "," + w + "," + d + "," + h;
  let got = cache.get(key);
  if (got) return got;
  const M = mesh(), t = (p.v + 1) / 10, cx = w / 2, cy = h / 2;
  const stations = (prof) => prof.map(([z, r, tone]) => [z * d, r, tone]);
  switch (p.type) {
    case TUBE: lathe(M, [[0, 0], [0, 1], [d, t], [d, 0]], cx, cy, cx, cy, round(w, h)); break;
    case RING: { const hole = 0.5 + 0.05 * p.v; lathe(M, [[0, hole], [0, 1], [d, 1], [d, hole], [0, hole]], cx, cy, cx, cy, round(w, h)); break; }
    case BODY: loft(M, [rect(0, cx, cy, w, h), rect(d, cx, cy, w * t, h * t)], { caps: true }); break;
    case HULL: loft(M, [hex(0, cx, cy, w, h), hex(d, cx, cy, w * t, (h * (1 + t)) / 2)], { caps: true }); break;
    case NOSE: {
      const rings = [], N = 14;
      for (let i = 0; i <= N; i++) { const z = i < N - 3 ? (0.94 * i) / (N - 3) : 0.94 + (0.06 * (i - N + 3)) / 3, [sw, sh, dy] = noseAt(z, p.v); rings.push(hex(z * d, cx, cy + dy * h, w * sw, h * sh)); }
      loft(M, rings, { caps: true, smooth: true });
      break;
    }
    case WING: {
      // the section at a station: an octagon in (z, y) — flat faces, a chamfer as long as 0.6 of the thickness at each edge
      const section = (x, chord, thick) => { const e = Math.min(0.6 * thick, 0.3 * chord), a = thick / 2, b = 0.2 * thick; return [[0, -b], [e, -a], [chord - e, -a], [chord, -b], [chord, b], [chord - e, a], [e, a], [0, b]].map(([z, y]) => [x, cy + y, z]); };
      loft(M, [section(0, d, h), section(w, d * t, h * WING_TIP_THICK)], { caps: true });
      break;
    }
    case DOME: {
      const seg = round(w, d), st = Math.max(5, seg >> 2), rings = [];
      for (let i = 0; i < st; i++) { const e = (Math.PI / 2) * (i / st), r = Math.cos(e), y = Math.sin(e) * h; rings.push(Array.from({ length: seg }, (_, k) => { const a = (2 * Math.PI * k) / seg; return [cx + cx * r * Math.cos(a), y, d / 2 + (d / 2) * r * Math.sin(a)]; })); }
      rings.push(Array.from({ length: seg }, () => [cx, h, d / 2]));       // the crown: the last ring drawn to a point
      loft(M, rings, { caps: true, smooth: true });
      break;
    }
    case ENGINE: {
      lathe(M, stations(ENGINE_PROFILE), cx, cy, cx, cy, Math.max(24, round(w, h)));
      const [z0, z1] = ENGINE_STRUT_Z, R = ENGINE_STRUT_R, T = ENGINE_STRUT_T;      // the cross struts before the cone
      cuboid(M, [cx - R * cx, cy - T * cy, z0 * d], [cx + R * cx, cy + T * cy, z1 * d], STEEL);
      cuboid(M, [cx - T * cx, cy - R * cy, z0 * d], [cx + T * cx, cy + R * cy, z1 * d], STEEL);
      break;
    }
    case CANNON: {
      const seg = Math.max(12, round(w, h) - 4);
      lathe(M, stations(CANNON_PROFILE), cx, cy, cx, cy, seg);
      const sp = CANNON_SPOKE.map(([z, r]) => [z * d, r]);
      for (let k = 0; k < CANNON_SPOKES; k++) { const a = (2 * Math.PI * k) / CANNON_SPOKES; sweep(M, sp, cx, cy, cx, cy, a - 0.09, a + 0.09, 1, MATERIAL); }
      const arm = CANNON_ARM.map(([z, r]) => [z * d, r]), half = (CANNON_ARM_DEG * Math.PI) / 180;
      for (const mid of [Math.PI / 2, -Math.PI / 2]) sweep(M, arm, cx, cy, cx, cy, mid - half, mid + half, 8, MATERIAL, true);
      break;
    }
    case CANOPY: canopy(M, w, d, h); break;
  }
  got = M.done();
  if (cache.size > 600) cache.clear();
  cache.set(key, got);
  return got;
}
// how many sides a round part is drawn with: by its girth, so a 30 cm barrel is not drawn as finely as a 2 m tank
const round = (a, b) => Math.max(12, Math.min(40, 4 * Math.round(Math.sqrt(Math.max(a, b)) / 1.6)));
const rect = (z, cx, cy, w, h) => [[cx + w / 2, cy - h / 2, z], [cx + w / 2, cy + h / 2, z], [cx - w / 2, cy + h / 2, z], [cx - w / 2, cy - h / 2, z]];
// the hull's eight corners at z, counter-clockwise from the right edge of the belly
const hex = (z, cx, cy, w, h) => [...HULL_SECTION.map(([a, y]) => [cx + a * w, cy + (y - 0.5) * h, z]), ...HULL_SECTION.slice().reverse().map(([a, y]) => [cx - a * w, cy + (y - 0.5) * h, z])];

// A mesh being built: triangles with a tone each, flat or smooth. done() gives every corner its normal — a flat
// triangle its own, a smooth one the mean of the smooth faces meeting at that corner that turn less than CREASE from it
// (so a lathe is round across its sides and still sharp at a step, with no normal worked out by hand for any outline).
const CREASE = Math.cos((38 * Math.PI) / 180);
function mesh() {
  const P = [], TN = [], SM = [];
  const tri = (a, b, c, tone = 0, smooth = false) => {
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2], vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
    if (Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx) < 1e-9) return;      // a sliver at an axis
    P.push(a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]); TN.push(tone); SM.push(smooth ? 1 : 0);
  };
  const quad = (a, b, c, e, tone, smooth) => { tri(a, b, c, tone, smooth); tri(a, c, e, tone, smooth); };
  const done = () => {
    const n = TN.length, pos = new Float32Array(P), nor = new Float32Array(n * 9), tone = new Uint8Array(TN), F = new Float64Array(n * 3);
    for (let i = 0; i < n; i++) {
      const o = i * 9, ux = P[o + 3] - P[o], uy = P[o + 4] - P[o + 1], uz = P[o + 5] - P[o + 2], vx = P[o + 6] - P[o], vy = P[o + 7] - P[o + 1], vz = P[o + 8] - P[o + 2];
      F[i * 3] = uy * vz - uz * vy; F[i * 3 + 1] = uz * vx - ux * vz; F[i * 3 + 2] = ux * vy - uy * vx;      // its length: twice the area
    }
    const at = new Map(), keyOf = (o) => Math.round(P[o] * 50) + "," + Math.round(P[o + 1] * 50) + "," + Math.round(P[o + 2] * 50);
    for (let i = 0; i < n; i++) if (SM[i]) for (let c = 0; c < 3; c++) { const k = keyOf(i * 9 + c * 3); let l = at.get(k); if (!l) at.set(k, l = []); l.push(i); }
    for (let i = 0; i < n; i++) {
      const fx = F[i * 3], fy = F[i * 3 + 1], fz = F[i * 3 + 2], fl = Math.hypot(fx, fy, fz);
      for (let c = 0; c < 3; c++) {
        let nx = fx, ny = fy, nz = fz;
        if (SM[i]) {
          nx = ny = nz = 0;
          for (const j of at.get(keyOf(i * 9 + c * 3))) {
            const gx = F[j * 3], gy = F[j * 3 + 1], gz = F[j * 3 + 2];
            if (fx * gx + fy * gy + fz * gz >= CREASE * fl * Math.hypot(gx, gy, gz)) { nx += gx; ny += gy; nz += gz; }
          }
        }
        const l = Math.hypot(nx, ny, nz) || 1, o = i * 9 + c * 3;
        nor[o] = nx / l; nor[o + 1] = ny / l; nor[o + 2] = nz / l;
      }
    }
    return { n, pos, nor, tone };
  };
  return { tri, quad, done };
}
/** A solid of revolution about the z axis through (cx, cy), `rx` and `ry` its half width and half height: prof is
 *  [z, r as a share of the radius, tone] from the back round the OUTSIDE to the front. Angles run from +x toward +y, so a
 *  station further forward faces out, one stepping outward at the same z faces back, and an outline that turns back down
 *  the inside of a mouth faces inward — the surface is right wherever the outline goes. */
function lathe(M, prof, cx, cy, rx, ry, seg) {
  const ring = (z, r) => Array.from({ length: seg }, (_, k) => { const a = (2 * Math.PI * k) / seg; return [cx + rx * r * Math.cos(a), cy + ry * r * Math.sin(a), z]; });
  let A = ring(prof[0][0], prof[0][1]);
  for (let i = 0; i + 1 < prof.length; i++) {
    const B = ring(prof[i + 1][0], prof[i + 1][1]), tone = prof[i][2] || 0;
    for (let k = 0; k < seg; k++) { const k1 = (k + 1) % seg; M.quad(A[k], A[k1], B[k1], B[k], tone, true); }
    A = B;
  }
}
/** A skin over rings of as many points each (a section carried along a part), closed at both ends when `caps`. Its
 *  faces are turned to look away from the line through the rings' middles, whichever way the rings were listed. */
function loft(M, rings, { caps = false, smooth = false, tone = 0 } = {}) {
  const mid = (R) => R.reduce((a, q) => [a[0] + q[0] / R.length, a[1] + q[1] / R.length, a[2] + q[2] / R.length], [0, 0, 0]);
  const C = rings.map(mid), m = rings[0].length;
  let out = 0;                                              // which winding looks outward: asked of the widest pair of rings
  for (let i = 0; i + 1 < rings.length; i++) for (let k = 0; k < m; k++) {
    const a = rings[i][k], b = rings[i][(k + 1) % m], c = rings[i + 1][(k + 1) % m];
    const n = [(b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]), (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]), (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])];
    const q = [(a[0] + c[0]) / 2 - (C[i][0] + C[i + 1][0]) / 2, (a[1] + c[1]) / 2 - (C[i][1] + C[i + 1][1]) / 2, (a[2] + c[2]) / 2 - (C[i][2] + C[i + 1][2]) / 2];
    out += n[0] * q[0] + n[1] * q[1] + n[2] * q[2];
  }
  const flip = out < 0;
  for (let i = 0; i + 1 < rings.length; i++) for (let k = 0; k < m; k++) {
    const a = rings[i][k], b = rings[i][(k + 1) % m], c = rings[i + 1][(k + 1) % m], e = rings[i + 1][k];
    flip ? M.quad(a, e, c, b, tone, smooth) : M.quad(a, b, c, e, tone, smooth);
  }
  if (!caps) return;
  const last = rings.length - 1;
  for (const [R, c, toward] of [[rings[0], C[0], C[1]], [rings[last], C[last], C[last - 1]]]) for (let k = 0; k < m; k++) {
    // an end faces away from the ring before it: the same winding the skin has at the far end, the other at the near end
    const a = R[k], b = R[(k + 1) % m];
    const n = [(a[1] - c[1]) * (b[2] - c[2]) - (a[2] - c[2]) * (b[1] - c[1]), (a[2] - c[2]) * (b[0] - c[0]) - (a[0] - c[0]) * (b[2] - c[2]), (a[0] - c[0]) * (b[1] - c[1]) - (a[1] - c[1]) * (b[0] - c[0])];
    const away = n[0] * (c[0] - toward[0]) + n[1] * (c[1] - toward[1]) + n[2] * (c[2] - toward[2]);
    away >= 0 ? M.tri(c, a, b, tone, false) : M.tri(c, b, a, tone, false);
  }
}
/** A section [z, r] (a closed outline in the plane through the axis) swept round the z axis from angle a0 to a1. */
function sweep(M, section, cx, cy, rx, ry, a0, a1, steps, tone, smooth = false) {
  const rings = [];
  for (let i = 0; i <= steps; i++) { const a = a0 + ((a1 - a0) * i) / steps; rings.push(section.map(([z, r]) => [cx + rx * r * Math.cos(a), cy + ry * r * Math.sin(a), z])); }
  loft(M, rings, { caps: true, smooth, tone });
}
function cuboid(M, lo, hi, tone) {
  const q = (x, y, z) => [x ? hi[0] : lo[0], y ? hi[1] : lo[1], z ? hi[2] : lo[2]];
  loft(M, [[q(1, 0, 0), q(1, 1, 0), q(0, 1, 0), q(0, 0, 0)], [q(1, 0, 1), q(1, 1, 1), q(0, 1, 1), q(0, 0, 1)]], { caps: true, tone });
}
// The canopy: flat panes, each drawn as glass inside a dark frame GLAZING.frame cm wide, over a dark floor and a dark back.
function canopy(M, w, d, h) {
  const c = GLAZING, P = (x, y, z) => [x * w, y * h, z * d];
  const B0 = P(0, 0, 0), B1 = P(1, 0, 0), M0 = P(0, 0, c.post), M1 = P(1, 0, c.post), F0 = P(c.frontX, 0, 1), F1 = P(1 - c.frontX, 0, 1);
  const R0 = P(c.roofX, 1, c.roofBack), R1 = P(1 - c.roofX, 1, c.roofBack), R2 = P(c.roofX, 1, c.roofFront), R3 = P(1 - c.roofX, 1, c.roofFront);
  const inner = [w / 2, h * 0.4, d * 0.35];
  const face = (pts, glazed) => {
    // wound to look away from the canopy's inside
    const sub = (p, q) => [p[0] - q[0], p[1] - q[1], p[2] - q[2]], len = (v) => Math.hypot(v[0], v[1], v[2]);
    const cross = (u, v) => [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    let n = cross(sub(pts[1], pts[0]), sub(pts[2], pts[0]));
    const off = sub(pts[0], inner);
    if (n[0] * off[0] + n[1] * off[1] + n[2] * off[2] < 0) { pts = pts.slice().reverse(); n = n.map((x) => -x); }
    if (!glazed) { for (let k = 1; k + 1 < pts.length; k++) M.tri(pts[0], pts[k], pts[k + 1], DARK); return; }
    // the pane: every edge moved in by the frame's width (each corner where its two moved edges meet)
    const m = pts.length, nl = len(n), N = n.map((x) => x / nl);
    const inward = (p, q) => { const e2 = sub(q, p), l = len(e2); return cross(N, e2.map((x) => x / l)); };
    const pane = pts.map((p, k) => {
      const n1 = inward(pts[(k + m - 1) % m], p), n2 = inward(p, pts[(k + 1) % m]), q = 1 + n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2];
      return [p[0] + (c.frame * (n1[0] + n2[0])) / q, p[1] + (c.frame * (n1[1] + n2[1])) / q, p[2] + (c.frame * (n1[2] + n2[2])) / q];
    });
    for (let k = 0; k < m; k++) { const k1 = (k + 1) % m; M.quad(pts[k], pts[k1], pane[k1], pane[k], DARK); }
    for (let k = 1; k + 1 < m; k++) M.tri(pane[0], pane[k], pane[k + 1], MATERIAL);
  };
  face([R0, R1, R3, R2], true);                              // the roof
  face([R2, R3, F1, F0], true);                              // the windscreen
  face([B0, M0, R2, R0], true); face([M0, F0, R2], true);    // the left side: a pane under the roof, one beside the windscreen
  face([B1, R1, R3, M1], true); face([M1, R3, F1], true);    // the right side
  face([B0, R0, R1, B1], false);                             // the back, and the floor (the cockpit reads dark through the glass)
  face([B0, B1, M1, F1, F0, M0], false);
}
