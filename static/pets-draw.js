// pets-draw.js — shared, dependency-free SVG drawing helpers for the HAND-DRAWN pet art (pets-art/*.js).
// Pure functions returning SVG-markup strings; no game state. viewBox convention: 0 0 120 120, animal
// centered ~ (60, 62), kept within x,y ∈ [8, 112]. Colours come from the coat object `c`:
//   c.body  = main fill    c.shade = darker accent/underside    c.line = outline stroke
// Animate for life with these CSS classes (defined in the pets page): wrap the torso in
//   <g class="breathe">…</g>, the head in <g class="head-tilt">…</g>, tails/wings/fins in
//   <g class="tail-wag">…</g>. `eyes()`/`eye()` already blink on their own.
export const INK = "#20242a";

// perceptual luminance of a #rrggbb — used to flip eye colour on dark coats so eyes never vanish
export const lum = (hex) => { const n = parseInt(hex.slice(1), 16); return ((n >> 16) * 3 + ((n >> 8) & 255) * 6 + (n & 255)) / 2550; };
export const eyeInk = (c) => lum(c.body) < 0.32 ? "#e9edf2" : INK;

// a fluffy blob outline (n bumps) — heads, tails, fur, wool, clouds of down
function pomPath(cx, cy, r, n = 8) {
  const pts = [];
  for (let k = 0; k < n; k++) { const a = (-90 + 360 * k / n) * Math.PI / 180; pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); }
  const ar = (r * Math.sin(Math.PI / n) * 1.35).toFixed(1);
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let k = 1; k <= n; k++) { const [x, y] = pts[k % n]; d += `A${ar} ${ar} 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}`; }
  return d + "Z";
}
export const pom = (cx, cy, r, fill, line, n = 8, w = 2) => `<path d="${pomPath(cx, cy, r, n)}" fill="${fill}" stroke="${line}" stroke-width="${w}" stroke-linejoin="round"/>`;

// an outlined "sausage" stroke: line colour laid down first, fill over it — limbs, tails, necks, coils
export const tube = (d, fill, line, w = 6) => `<path d="${d}" fill="none" stroke="${line}" stroke-width="${w + 3}" stroke-linecap="round"/><path d="${d}" fill="none" stroke="${fill}" stroke-width="${w}" stroke-linecap="round"/>`;

// a pair of glossy eyes that blink; `eye()` is the single-eye version (profile animals)
export const eyes = (x1, x2, y, r = 2.6, col = INK) => `<g class="blink">${[[x1, 1], [x2, -1]].map(([x]) =>
  `<circle cx="${x}" cy="${y}" r="${r}" fill="${col}"/><circle cx="${(x + r * 0.38).toFixed(1)}" cy="${(y - r * 0.38).toFixed(1)}" r="${(r * 0.34).toFixed(2)}" fill="#fff" opacity=".9"/>`).join("")}</g>`;
export const eye = (x, y, r = 3, col = INK) => `<g class="blink"><circle cx="${x}" cy="${y}" r="${r}" fill="${col}"/><circle cx="${(x + r * 0.38).toFixed(1)}" cy="${(y - r * 0.38).toFixed(1)}" r="${(r * 0.34).toFixed(2)}" fill="#fff" opacity=".9"/></g>`;

// a gentle smile (two curved strokes down from the nose point)
export const smile = (x, y, w2 = 3.4, col = INK) => `<path d="M${x} ${y} q0 ${w2} -${w2} ${w2 + 1} M${x} ${y} q0 ${w2} ${w2} ${w2 + 1}" stroke="${col}" stroke-width="1.5" fill="none" stroke-linecap="round"/>`;

// mirror any markup around the vertical centre x=60 (symmetric wings, ears, legs)
export const mirror = (inner) => `<g transform="translate(120 0) scale(-1 1)">${inner}</g>`;

// ── NEW HOUSE STYLE helpers (continuous-silhouette method) ───────────────────────────────
// mix a #rrggbb toward white by f∈[0,1] (bellies, cheeks, muzzle, eye-ring highlights)
export const tint = (hex, f) => { const n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255,
  m = (x) => Math.round(x + (255 - x) * f).toString(16).padStart(2, "0"); return "#" + m(r) + m(g) + m(b); };
// mix a #rrggbb toward black by f∈[0,1] (extra-dark shading, inner ears)
export const deepen = (hex, f) => { const n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255,
  m = (x) => Math.round(x * (1 - f)).toString(16).padStart(2, "0"); return "#" + m(r) + m(g) + m(b); };
// coat-appropriate pale belly/underside (relates to the coat so colour variety still reads)
export const belly = (c) => tint(c.body, 0.72);
// a big, cute, glossy eye with a catchlight (the house-style eye) — blinks with the page CSS
export const ceye = (x, y, r = 4) => `<g class="blink"><ellipse cx="${x}" cy="${y}" rx="${r}" ry="${(r * 1.15).toFixed(1)}" fill="${INK}"/><circle cx="${(x - r * 0.32).toFixed(1)}" cy="${(y - r * 0.42).toFixed(1)}" r="${(r * 0.38).toFixed(1)}" fill="#fff"/></g>`;
// soft contact shadow on the ground under the animal
export const floorShadow = (cx, y, w) => `<ellipse cx="${cx}" cy="${y}" rx="${w}" ry="${(w * 0.18).toFixed(1)}" fill="#000" opacity=".22"/>`;
