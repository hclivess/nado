// land-clouds.js — THE SKY'S CLOUDS (#183 step 2; operator 2026-11-11, beside a concept picture of a meadow under
// scattered fair-weather clouds: "compared to this our game looks like from 1996"). Until this file the sky was a
// painted dome with a sun on it: not one cloud, anywhere, ever.
//
// WHAT IS BUILT is fair-weather cumulus — "flattened, wider than it is tall, fluffy heaps" (Cumulus humilis l.15), on a
// flat base, in loose fields with clear gaps about as wide as the heaps (the Brittany aerial). Every real-world number
// below is cited to the land research mirror (/root/land-research/clouds/, INDEX.md), and every number the game sets is
// labelled a DESIGN CHOICE. The pictures the result is judged against are the mirror's three photographs (a heap from
// the side, a field from above, a field from below) and the operator's concept picture (look/).
//
// THE LAYER IS IN THIS PLANET'S AIR. The planet's atmosphere is the 1976 standard atmosphere's 86 km fitted under
// ATM_TOP (land-planet.js airAt), so a height in the real air is that height × ATM_TOP / ISA_TOP here — and the cloud
// layer is moved the same way, base, heap size and drift alike. That keeps the ANGLES the real sky has from the ground:
// a 600 m heap under a 1,200 m base and a 209 m heap under a 419 m base fill the same part of the sky.
//
// ONE DEFINITION, TWO READERS. The clouds are a density in space — density(p) below — over a small tiling noise volume
// (noiseVolume). The page marches rays through it on the GPU (cloudLayer, the same constants and the same formulas in
// TSL); `march` here is the same march in plain JS, the reference a test measures (cover in oktas, flat base, lit top
// over a shaded belly) and the tool the look was tuned with. A number changed in one and not the other is two skies.
//
// THE FIELD DRIFTS as a rigid turn about the planet's spin axis, a function of the wall clock alone (drift), so every
// player sees the same cloud over the same hill at the same moment, and it needs no message from the world server.
import { R0, SEA } from "./land-world.js";
import { ATM_TOP, ISA_TOP } from "./land-planet.js";
import { EPOCH } from "./land-cosmos.js";

/** This planet's air against the real one: a real height × AIR is the matching height here (land-planet.js airAt). */
export const AIR = ATM_TOP / ISA_TOP;
/** The real numbers, with their sources. */
export const REAL = {
  base: 1200,       // m above the ground — "in temperate regions, the cloud bases studied ranged from 500 to 1500 m above
                    // ground level" (Cumulus cloud l.48); 1,200 is a DESIGN CHOICE inside that range
  wind: 5,          // m/s — a gentle breeze, Beaufort force 3: 3.4–5.4 m/s (Beaufort scale l.64); a DESIGN CHOICE inside it
  oktas: [3, 4],    // eighths of the sky covered — "scattered", SCT: 3–4 oktas (Okta l.19), the concept picture's sky
};
export const BASE = REAL.base * AIR;             // 418.6 m above the sea: the flat base every heap stands on
export const WIND = REAL.wind * AIR;             // 1.74 m/s along the latitudes, with the planet's turn
// DESIGN CHOICES (no source gives them; they are bounded by "wider than it is tall" and by the photographs):
export const THICK = 130;                        // m: the tallest heap, base to top
export const HEAP = 1500;                        // m: the heap noise's period — heaps 150–350 m wide, gaps about as wide
export const FIELD = 5300;                       // m: the period of the fields the heaps gather in (cloud streets, l.42)
export const BILLOW = 240;                       // m: the period of the billows that eat the heaps' edges
export const RB = R0 + SEA + BASE, RT = RB + THICK, RG = R0 + SEA;   // radii (m): base, top, the sea (the ground a ray stops at)
// the density's shape — DESIGN CHOICES, tuned against the photographs (THR is set by the cover: see the test)
export const K = {
  heapW: 0.7,       // the heap noise's share of a column's cover (the rest is the field's)
  thr: 0.495,       // cover above this is cloud: gives 3–4 oktas (measured by test_clouds…, never assumed)
  rise: 0.2,        // cover above thr that makes a heap of full height
  dome: 0.55,       // a heap's top against its cover: < 1 = steep sides under a rounded top
  soft: 0.3,        // the share of THICK over which a heap thins out toward its top surface
  foot: 0.1,        // the share of THICK over which the base thins out (a flat base with a soft underside)
  erode: 0.62,      // how deep the billows eat a heap's edge
  sigma: 0.045,     // 1/m: how fast a full-density cloud dims what is behind it (a RENDER number, not a measured one)
  deep: 1 / AIR,    // sunlight crosses a heap as it crosses the real one it stands for: 1/AIR times the path (a heap here
                    // is the real one scaled into this air, and a scaled heap let the sun through its belly)
  steps: 40,        // march steps through the layer along one ray
  path: 4500,       // m: the longest stretch of layer a ray is marched through
  sun: [18, 48, 110],   // m: where a sample looks toward the sun for the cloud in its light's way
  haze: 3600,       // m: the distance over which a cloud pales into the horizon's colour (distant ones "pale into the haze")
  silver: 0.9,      // how much brighter a cloud is toward the sun (light scattered forward: the bright rim)
};
/** How the sky map spends its rows: elevation = 90° · s · (BEND + (1 − BEND)·|s|) for s in −1..1 — twice the rows a
 *  degree at the horizon, where the far clouds are small, for two thirds at the zenith, where they are near and large. */
export const BEND = 0.5;
export const mapV = (el) => { const e = el / (Math.PI / 2), s = (-BEND + Math.sqrt(BEND * BEND + 4 * (1 - BEND) * Math.abs(e))) / (2 * (1 - BEND)); return 0.5 + 0.5 * Math.sign(e) * s; };
export const mapEl = (v) => { const s = 2 * v - 1; return (Math.PI / 2) * s * (BEND + (1 - BEND) * Math.abs(s)); };

// ---- the noise volume ------------------------------------------------------------------------------------------------
// SIZE³ voxels, two bytes each, tiling in all three directions:
//   [0] HEAPS — distance-to-a-point noise (each cell one rounded heap) carried and broken by gradient noise;
//   [1] BILLOWS — three octaves of distance-to-a-point noise: the cauliflower surface.
// Seeded and made of +, ×, floor and sqrt alone, so every browser builds the same bytes (the same clouds for everyone).
export const SIZE = 64;
function rng(seed) {
  let a = seed | 0;
  return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const G12 = [1, 1, 0, -1, 1, 0, 1, -1, 0, -1, -1, 0, 1, 0, 1, -1, 0, 1, 1, 0, -1, -1, 0, -1, 0, 1, 1, 0, -1, 1, 0, 1, -1, 0, -1, -1];
/** Gradient (Perlin) noise over an n³ lattice that wraps: about −0.7..0.7. */
function gradNoise(n, seed) {
  const r = rng(seed), g = new Uint8Array(n * n * n);
  for (let i = 0; i < g.length; i++) g[i] = Math.floor(r() * 12) * 3;
  const fade = (t) => t * t * t * (t * (t * 6 - 15) + 10);
  return (x, y, z) => {
    const x0 = Math.floor(x), y0 = Math.floor(y), z0 = Math.floor(z), fx = x - x0, fy = y - y0, fz = z - z0;
    const u = fade(fx), v = fade(fy), w = fade(fz);
    let out = 0;
    for (let c = 0; c < 8; c++) {
      const dx = c & 1, dy = (c >> 1) & 1, dz = c >> 2, o = g[(((z0 + dz) % n + n) % n * n + ((y0 + dy) % n + n) % n) * n + ((x0 + dx) % n + n) % n];
      out += (G12[o] * (fx - dx) + G12[o + 1] * (fy - dy) + G12[o + 2] * (fz - dz)) * (dx ? u : 1 - u) * (dy ? v : 1 - v) * (dz ? w : 1 - w);
    }
    return out;
  };
}
/** Distance to the nearest of one seeded point a cell, over an n³ lattice that wraps: 0 at a point, ~1 between them. */
function pointNoise(n, seed) {
  const r = rng(seed), p = new Float32Array(n * n * n * 3);
  for (let i = 0; i < p.length; i++) p[i] = r();
  return (x, y, z) => {
    const x0 = Math.floor(x), y0 = Math.floor(y), z0 = Math.floor(z);
    let best = 9;
    for (let dz = -1; dz <= 1; dz++) for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const o = ((((z0 + dz) % n + n) % n) * n + ((y0 + dy) % n + n) % n) * n * 3 + (((x0 + dx) % n + n) % n) * 3;
      const ax = x0 + dx + p[o] - x, ay = y0 + dy + p[o + 1] - y, az = z0 + dz + p[o + 2] - z, d = ax * ax + ay * ay + az * az;
      if (d < best) best = d;
    }
    return Math.min(1, Math.sqrt(best));
  };
}
let VOL = null;
/** The noise volume (made once): Uint8Array(SIZE³ · 2), x fastest, [heaps, billows] a voxel. */
export function noiseVolume() {
  if (VOL) return VOL;
  const S = SIZE, out = new Uint8Array(S * S * S * 2);
  const g4 = gradNoise(4, 11), g8 = gradNoise(8, 12), g16 = gradNoise(16, 13), w4 = pointNoise(4, 21), w8 = pointNoise(8, 22);
  const b6 = pointNoise(6, 31), b12 = pointNoise(12, 32), b24 = pointNoise(24, 33);
  const byte = (x) => Math.max(0, Math.min(255, Math.round(x * 255)));
  for (let k = 0, o = 0; k < S; k++) for (let j = 0; j < S; j++) for (let i = 0; i < S; i++, o += 2) {
    const x = (i + 0.5) / S, y = (j + 0.5) / S, z = (k + 0.5) / S;
    const grad = (g4(x * 4, y * 4, z * 4) + 0.5 * g8(x * 8, y * 8, z * 8) + 0.25 * g16(x * 16, y * 16, z * 16)) / 1.2;   // about −1..1
    const heap = 1 - (0.75 * w4(x * 4, y * 4, z * 4) + 0.25 * w8(x * 8, y * 8, z * 8));          // 1 at a heap's middle
    out[o] = byte(0.62 * heap + 0.38 * (0.5 + 0.5 * grad));
    out[o + 1] = byte(1 - (0.6 * b6(x * 6, y * 6, z * 6) + 0.28 * b12(x * 12, y * 12, z * 12) + 0.12 * b24(x * 24, y * 24, z * 24)));
  }
  return (VOL = out);
}
/** Channel `ch` of the volume at (x, y, z) in periods: wrapped and blended between the eight voxels around, as the
 *  GPU's sampler does it (0..1). */
export function sample(vol, ch, x, y, z) {
  const S = SIZE, fx = x * S - 0.5, fy = y * S - 0.5, fz = z * S - 0.5, x0 = Math.floor(fx), y0 = Math.floor(fy), z0 = Math.floor(fz);
  const tx = fx - x0, ty = fy - y0, tz = fz - z0, m = (a) => ((a % S) + S) % S;
  const xa = m(x0), xb = m(x0 + 1), ya = m(y0) * S, yb = m(y0 + 1) * S, za = m(z0) * S * S, zb = m(z0 + 1) * S * S;
  const at = (zz, yy, xx) => vol[(zz + yy + xx) * 2 + ch];
  const lo = (at(za, ya, xa) * (1 - tx) + at(za, ya, xb) * tx) * (1 - ty) + (at(za, yb, xa) * (1 - tx) + at(za, yb, xb) * tx) * ty;
  const hi = (at(zb, ya, xa) * (1 - tx) + at(zb, ya, xb) * tx) * (1 - ty) + (at(zb, yb, xa) * (1 - tx) + at(zb, yb, xb) * tx) * ty;
  return (lo * (1 - tz) + hi * tz) / 255;
}

// ---- the density -------------------------------------------------------------------------------------------------
// Two fixed turns (exact: rows of rational unit vectors) put the noise's lattice askew to the planet's axes and to each
// other: a sphere cuts a cubic lattice in a pattern that repeats wherever the two line up, and a sky that repeats every
// HEAP metres along an axis reads as wallpaper.
export const M1 = [0.36, 0.48, -0.8, -0.8, 0.6, 0, 0.48, 0.64, 0.6], M2 = [0.6, 0, 0.8, -0.64, 0.6, 0.48, -0.48, -0.8, 0.36];
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const smooth = (a, b, x) => { const t = clamp01((x - a) / (b - a)); return t * t * (3 - 2 * t); };
/** The field's turn at wall-clock second `t` (default now): [cos, sin] of the angle the clouds have drifted about the
 *  planet's axis since EPOCH, at WIND along the equator of the base. The angle is reduced in doubles BEFORE it becomes
 *  a cosine: the GPU's 32-bit floats cannot hold seconds-since-an-epoch times a small rate. */
export function drift(t = Date.now() / 1000 - EPOCH) {
  const a = ((t * WIND) / RB) % (2 * Math.PI);
  return [Math.cos(a), Math.sin(a)];
}
/** A point of the planet frame carried back to where its air was at EPOCH (the clouds go round with the planet's turn,
 *  land-cosmos planetToInertial: a surface point moves toward (z, 0, −x)). */
export const undrift = (p, [c, s]) => [p[0] * c - p[2] * s, p[1], p[0] * s + p[2] * c];
/** How high the heap over the column through p stands, as a share of THICK (0: clear sky): p is an undrifted point,
 *  anywhere on the column. A heap is a COLUMN'S property — read on the base shell — so its base is flat and its sides
 *  stand upright, as a heap's do over its level of condensation. */
export function heapTop(vol, p) {
  const k = RB / Math.hypot(p[0], p[1], p[2]), x = p[0] * k, y = p[1] * k, z = p[2] * k;
  const a = sample(vol, 0, (M1[0] * x + M1[1] * y + M1[2] * z) / HEAP, (M1[3] * x + M1[4] * y + M1[5] * z) / HEAP, (M1[6] * x + M1[7] * y + M1[8] * z) / HEAP);
  const b = sample(vol, 0, (M2[0] * x + M2[1] * y + M2[2] * z) / FIELD, (M2[3] * x + M2[4] * y + M2[5] * z) / FIELD, (M2[6] * x + M2[7] * y + M2[8] * z) / FIELD);
  const over = (a * K.heapW + b * (1 - K.heapW) - K.thr) / K.rise;
  return over <= 0 ? 0 : Math.pow(Math.min(1, over), K.dome);
}
/** The heap's body at undrifted p, 0..1, before the billows: nothing below the base or above the top. */
export function body(vol, p) {
  const hN = (Math.hypot(p[0], p[1], p[2]) - RB) / THICK;
  if (hN <= 0 || hN >= 1) return 0;
  const top = heapTop(vol, p);
  return top <= hN ? 0 : clamp01((top - hN) / K.soft) * smooth(0, K.foot, hN);
}
/** The cloud's density at undrifted p, 0..1: the body with the billows eating its edges (`fine` 0..1: how much of them
 *  — the march fades them out with distance, where they are smaller than a pixel of the sky map). */
export function density(vol, p, fine = 1) {
  const d = body(vol, p);
  if (d <= 0) return 0;
  const e = (1 - sample(vol, 1, p[0] / BILLOW, p[1] / BILLOW, p[2] / BILLOW)) * K.erode * fine;
  return clamp01((d - e) / (1 - e));
}

/** The light on the clouds, from what the page's sky() already knows: the sun's direction (unit, planet frame), its
 *  colour × intensity (linear rgb) and the sky's horizon and zenith colours. A heap's top takes the sky's light, its belly
 *  the paler light off the haze — grey, never black, as the Jakarta photograph shows from below. */
export function light(sunDir, sun, hor, zen) {
  return { sunDir, sun: sun.map((c) => c * 0.95), hi: hor.map((c, i) => 0.62 * c + 0.3 * zen[i]), lo: hor.map((c, i) => 0.42 * c + 0.08 * zen[i]), haze: hor };
}

// ---- the march (the reference: cloudLayer's TSL is these lines again) -------------------------------------------------
/** The stretch [t0, t1] (m) of the ray from an eye at radius `r` (m from the planet's centre), `mu` = the sine of its
 *  elevation, that lies in the layer — or null. An eye below the base sees no cloud through the ground; an eye above
 *  the top looks down into it. Only the first stretch is marched (a ray that leaves through the base and comes up
 *  again beyond the horizon is not followed). */
export function span(r, mu) {
  const b = r * mu, D = (R) => b * b - (r * r - R * R), Db = D(RB), Dt = D(RT), Dg = D(RG);
  let t0, t1;
  if (r < RB) {
    if (r > RG && mu < 0 && Dg > 0) return null;                       // into the ground
    t0 = -b + Math.sqrt(Db); t1 = -b + Math.sqrt(Dt);
  } else if (r <= RT) { t0 = 0; t1 = mu < 0 && Db > 0 ? -b - Math.sqrt(Db) : -b + Math.sqrt(Dt); }
  else {
    if (!(mu < 0 && Dt > 0)) return null;
    t0 = -b - Math.sqrt(Dt); t1 = Db > 0 ? -b - Math.sqrt(Db) : -b + Math.sqrt(Dt);
  }
  return t1 > t0 ? [t0, Math.min(t1, t0 + K.path)] : null;
}
/** What a ray shows of the clouds: [r, g, b, a] — the light it gathers, already weighted by how much cloud it met
 *  (premultiplied), and a = how much of the sky behind is hidden. `eye` (m, planet frame), `dir` unit, `L` the light:
 *  { sunDir, sun [rgb], hi [rgb] (the sky's light on a heap's top), lo [rgb] (on its belly), haze [rgb] }, `dr` drift(),
 *  `jit` 0..1 where in its first step the march starts. */
export function march(vol, eye, dir, L, dr = drift(), jit = 0.5) {
  const r = Math.hypot(eye[0], eye[1], eye[2]), mu = (eye[0] * dir[0] + eye[1] * dir[1] + eye[2] * dir[2]) / r, sp = span(r, mu);
  if (!sp) return [0, 0, 0, 0];
  const dt = (sp[1] - sp[0]) / K.steps, cs = dir[0] * L.sunDir[0] + dir[1] * L.sunDir[1] + dir[2] * L.sunDir[2];
  const toward = K.silver * Math.pow(Math.max(0, cs), 8);
  let T = 1, t = sp[0] + dt * jit;
  const C = [0, 0, 0];
  for (let i = 0; i < K.steps && T > 0.01; i++, t += dt) {
    const p = undrift([eye[0] + dir[0] * t, eye[1] + dir[1] * t, eye[2] + dir[2] * t], dr), far = Math.exp(-t / K.haze);
    const d = density(vol, p, far);
    if (d <= 0.001) continue;
    // the cloud between this point and the sun: three looks along the sun's way, each standing for the stretch to the next
    const sd = undrift(L.sunDir, dr);
    let tau = 0, last = 0;
    for (const s of K.sun) { tau += body(vol, [p[0] + sd[0] * s, p[1] + sd[1] * s, p[2] + sd[2] * s]) * (s - last) * K.deep; last = s; }
    tau *= K.sigma;
    // light that went straight through, and the light that found its way round (a cloud's shaded side is grey, not black);
    // the bright rim toward the sun is light scattered forward through THIN cloud only — through a whole heap it is gone
    // (it lit the belly from below as brightly as the top, and the Jakarta belly is grey)
    const lit = 0.65 * Math.exp(-tau) + 0.35 * Math.exp(-tau * 0.25) + toward * Math.exp(-tau);
    const hN = clamp01((Math.hypot(p[0], p[1], p[2]) - RB) / THICK), a = 1 - Math.exp(-d * K.sigma * dt);
    for (let c = 0; c < 3; c++) {
      const own = L.sun[c] * lit + L.lo[c] + (L.hi[c] - L.lo[c]) * hN;
      C[c] += T * a * (L.haze[c] + (own - L.haze[c]) * far);
    }
    T *= 1 - a;
  }
  return [C[0], C[1], C[2], 1 - T];
}
