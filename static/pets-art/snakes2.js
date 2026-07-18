// pets-art/snakes2.js — BESPOKE hand-drawn SVG art for the SNAKES2 batch (NADO Pets).
// House style (tmp/METHOD.md): ONE continuous silhouette per animal, grounded with floorShadow, a pale
// two-tone belly/underside via belly(c), a clean cute face, forked tongue/coil TUCKED — nothing floats.
// viewBox 0 0 120 120, animal centered ~ (60,64), kept within x,y ∈ [8,114]. Colours come from the coat
// object c (c.body / c.shade / c.line) applied at runtime — real hues are NOT hardcoded; only the forked
// tongue uses a fixed warm tint. Each of the 20 is a DISTINCT silhouette (reared, S-curve, coil, loop,
// striking, knot, festoon, ribbon, spiky ball, egg-bulge) and none duplicate reptiles.js / reptiles2.js.
// Animate: torso <g class="breathe">, head <g class="head-tilt">, loose tails <g class="tail-wag">.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const TONGUE = "#e0564d"; // forked tongue (fixed warm accent, same across coats)

// ── on-body marking helpers: sample a chain of quadratic segments [[P0,P1,P2],…] and place each
// marking AT a point on the body centerline, oriented to the LOCAL tangent so bands cross the body
// (never a fixed grid that ignores where the tube actually curves).
const qPt  = (P0, P1, P2, t) => { const u = 1 - t; return [u*u*P0[0]+2*u*t*P1[0]+t*t*P2[0], u*u*P0[1]+2*u*t*P1[1]+t*t*P2[1]]; };
const qTan = (P0, P1, P2, t) => { const u = 1 - t; return [2*u*(P1[0]-P0[0])+2*t*(P2[0]-P1[0]), 2*u*(P1[1]-P0[1])+2*t*(P2[1]-P1[1])]; };
// short strokes crossing the tube perpendicular to its local direction (rings / cross-bands)
const bandsOn = (segs, spots, col, w = 4, h = 7) => spots.map(([si, t]) => {
  const s = segs[si], [x, y] = qPt(...s, t), [tx, ty] = qTan(...s, t), L = Math.hypot(tx, ty) || 1, nx = -ty/L, ny = tx/L;
  return `<path d="M${(x-nx*h).toFixed(1)} ${(y-ny*h).toFixed(1)} L${(x+nx*h).toFixed(1)} ${(y+ny*h).toFixed(1)}" stroke="${col}" stroke-width="${w}" stroke-linecap="round"/>`;
}).join("");
// forward-pointing chevrons riding the centerline (arrow / pit-viper dorsal marks)
const chevronsOn = (segs, spots, col, w = 3, h = 6) => spots.map(([si, t]) => {
  const s = segs[si], [x, y] = qPt(...s, t), [tx, ty] = qTan(...s, t), L = Math.hypot(tx, ty) || 1;
  const ux = tx/L, uy = ty/L, nx = -uy, ny = ux, ax = x+ux*h*0.7, ay = y+uy*h*0.7;
  const l1x = x-ux*h*0.4+nx*h, l1y = y-uy*h*0.4+ny*h, l2x = x-ux*h*0.4-nx*h, l2y = y-uy*h*0.4-ny*h;
  return `<path d="M${l1x.toFixed(1)} ${l1y.toFixed(1)} L${ax.toFixed(1)} ${ay.toFixed(1)} L${l2x.toFixed(1)} ${l2y.toFixed(1)}" fill="none" stroke="${col}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;
}).join("");
// tangent-aligned hourglass saddles (copperhead "Hershey-kiss" crossbands, pinched at the spine)
const hourglassOn = (segs, spots, col, line, hw = 6, hh = 7) => spots.map(([si, t]) => {
  const s = segs[si], [x, y] = qPt(...s, t), [tx, ty] = qTan(...s, t), L = Math.hypot(tx, ty) || 1;
  const ux = tx/L, uy = ty/L, nx = -uy, ny = ux, P = (a, b) => `${(x+ux*a+nx*b).toFixed(1)} ${(y+uy*a+ny*b).toFixed(1)}`;
  return `<path d="M${P(-hw,-hh)} L${P(hw,-hh)} L${P(hw*0.3,0)} L${P(hw,hh)} L${P(-hw,hh)} L${P(-hw*0.3,0)} Z" fill="${col}" stroke="${line}" stroke-width="1" stroke-linejoin="round"/>`;
}).join("");

export const ART_SNAKES2 = {
  // ── Boomslang — slim TALL upright S rising from a base coil, short head with two BIG round eyes
  boomslang: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 110, 24)}
    <g class="breathe">
      <ellipse cx="60" cy="102" rx="26" ry="9" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="60" cy="99" rx="15" ry="5.5" fill="${c.shade}" opacity=".55"/>
      ${tube("M50 98 Q40 82 52 72 Q66 62 56 48 Q50 40 60 34", c.body, c.line, 10)}
      ${tube("M50 96 Q44 84 52 76", B, "none", 3)}
    </g>
    <g class="head-tilt">
      <path d="M48 34 Q46 20 60 18 Q74 20 72 34 Q62 44 48 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 18 q0 -6 0 -9 M60 9 l-3.4 -4 M60 9 l3.4 -4" fill="none" stroke="${TONGUE}" stroke-width="1.7" stroke-linecap="round"/>
      ${eyes(52, 68, 30, 4, E)}
    </g>`;
  },

  // ── Copperhead — relaxed body lying in a shallow wave, three pinched HOURGLASS bands, head resting right
  copperhead: (c) => {
    const B = belly(c), E = eyeInk(c);
    const WAVE = [[[14, 82], [32, 66], [50, 82]], [[50, 82], [66, 96], [82, 82]]];
    return `
    ${floorShadow(58, 108, 32)}
    <g class="breathe">
      ${tube("M14 82 Q32 66 50 82 Q66 96 82 82", c.body, c.line, 13)}
      ${tube("M18 83 Q32 71 46 83", B, "none", 2.4)}
      ${hourglassOn(WAVE, [[0, 0.28], [0, 0.72], [1, 0.35], [1, 0.75]], c.shade, c.line, 6, 7)}
    </g>
    <g class="head-tilt">
      <path d="M78 80 Q96 74 100 84 Q96 92 80 90 Q72 85 78 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M100 84 q6 1 10 0 M110 84 l4 -3 M110 84 l4 3" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(88, 82, 2.8, E)}
    </g>`;
  },

  // ── Cottonmouth — thick low coil mound, head reared back with the defining GAPING white mouth
  cottonmouth: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(58, 110, 34)}
    <g class="breathe">
      <ellipse cx="58" cy="79" rx="30" ry="24" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <path d="M31 74 Q27 84 34 93" fill="none" stroke="${B}" stroke-width="6" stroke-linecap="round" opacity=".55"/>
      <path d="M57.3 58.5 L62.7 59.2 L67.7 60.8 L72.2 63.2 L75.7 66.3 L78.4 70.0 L79.9 74.0 L80.4 78.0 L79.7 82.0 L78.0 85.7 L75.4 89.0 L72.1 91.7 L68.2 93.6 L63.9 94.8 L59.5 95.2 L55.2 94.8 L51.2 93.6 L47.6 91.8 L44.7 89.4 L42.6 86.6 L41.3 83.5 L40.9 80.4 L41.3 77.3 L42.5 74.5 L44.4 71.9 L46.9 69.9 L49.8 68.4 L53.0 67.4 L56.2 67.1 L59.4 67.4 L62.4 68.2 L65.0 69.5 L67.1 71.2 L68.6 73.2 L69.6 75.4 L69.9 77.6 L69.6 79.7 L68.8 81.7 L67.5 83.4 L65.8 84.8 L63.8 85.8 L61.7 86.4 L59.6 86.6 L57.5 86.4 L55.7 85.9 L54.0 85.0 L52.8 83.9 L51.9 82.7 L51.4 81.4 L51.3 80.1 L51.5 78.8 L52.1 77.8 L52.9 76.9 L53.9 76.2 L54.9 75.8" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" opacity=".7"/>
    </g>
    <g class="head-tilt">
      ${tube("M82 66 Q94 50 78 44", c.body, c.line, 12)}
      <path d="M62 44 Q60 30 76 28 Q90 28 90 40 Q84 50 72 50 Q62 50 62 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M64 42 Q76 38 88 42 Q84 50 74 50 Q66 48 64 42 Z" fill="#f6f3ec" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M66 44 Q76 48 86 44" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".55"/>
      ${eye(78, 36, 2.8, E)}
    </g>`;
  },

  // ── Bushmaster — LONG sweeping C-arc across the frame, big diamond blotches, arrow head raised top-right
  bushmaster: (c) => {
    const B = belly(c), E = eyeInk(c);
    const dia = (x, y) => `<path d="M${x} ${y - 7} l7 7 l-7 7 l-7 -7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(56, 110, 34)}
    <g class="tail-wag">${tube("M30 100 Q22 96 26 88", c.body, c.line, 7)}</g>
    <g class="breathe">
      ${tube("M30 100 Q8 76 26 52 Q44 30 72 34 Q94 38 94 58", c.body, c.line, 16)}
      ${[[20, 74], [34, 50], [58, 36], [84, 42]].map(([x, y]) => dia(x, y)).join("")}
      ${tube("M28 96 Q14 78 24 60", B, "none", 4)}
    </g>
    <g class="head-tilt">
      <path d="M86 52 Q100 46 106 56 Q104 66 90 66 Q80 60 86 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M84 54 l-2 -7 l6 3 Z M94 52 l2 -7 l-6 3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <path d="M106 56 q6 1 10 0 M116 56 l4 -3 M116 56 l4 3" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(94, 56, 2.8, E)}
    </g>`;
  },

  // ── Fer-de-lance — coiled defensive body with the head THRUST forward striking, sharp arrow head
  ferdelance: (c) => {
    const B = belly(c), E = eyeInk(c);
    const BODY = [[[30, 100], [10, 90], [20, 72]], [[20, 72], [30, 56], [50, 62]], [[50, 62], [68, 68], [60, 84]], [[60, 84], [54, 96], [76, 92]]];
    return `
    ${floorShadow(56, 110, 33)}
    <g class="breathe">
      ${tube("M30 100 Q10 90 20 72 Q30 56 50 62 Q68 68 60 84 Q54 96 76 92", c.body, c.line, 13)}
      ${tube("M30 98 Q16 88 22 74", B, "none", 3)}
      ${chevronsOn(BODY, [[0, 0.55], [1, 0.35], [1, 0.8], [2, 0.5], [3, 0.4]], c.shade, 3, 6)}
    </g>
    <g class="head-tilt">
      ${tube("M72 92 Q84 88 90 90", c.body, c.line, 11)}
      <path d="M84 88 L108 84 Q112 92 104 96 L84 96 Q80 92 84 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M84 88 L100 87 M84 96 L100 92" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>
      <path d="M108 88 q6 0 10 -1 M118 87 l4 -3 M118 87 l4 3" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(92, 89, 2.6, E)}
    </g>`;
  },

  // ── Taipan — sleek slim body resting in a wide flat hammock U, smooth two-tone, head lifted at right
  taipan: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 110, 34)}
    <g class="breathe">
      ${tube("M16 62 Q18 96 60 96 Q98 96 100 66 Q101 54 92 50", c.body, c.line, 12)}
      ${tube("M22 70 Q26 90 60 90 Q92 90 94 68", B, "none", 3.5)}
    </g>
    <g class="head-tilt">
      <path d="M84 52 Q82 38 96 36 Q108 38 106 50 Q98 58 88 58 Q84 56 84 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="95" cy="46" rx="7" ry="4" fill="${B}" opacity=".45"/>
      <path d="M96 36 q0 -6 0 -9 M96 27 l-3.4 -4 M96 27 l3.4 -4" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(90, 46, 2.8, E)}
    </g>`;
  },

  // ── Tiger Snake — flat concentric spiral coil (cinnamon-roll) with radial TIGER cross-bands, head on rim
  tigersnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    // one continuous spiral coiling inward, filled behind with a disc so the centre never shows through
    const SP = [
      [[60, 32], [96, 32], [96, 66]], [[96, 66], [96, 98], [60, 98]], [[60, 98], [28, 98], [28, 66]],
      [[28, 66], [28, 40], [54, 42]], [[54, 42], [74, 44], [74, 66]], [[74, 66], [74, 82], [58, 80]],
    ];
    return `
    ${floorShadow(60, 110, 34)}
    <g class="breathe">
      <ellipse cx="60" cy="66" rx="34" ry="33" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      ${tube("M60 32 Q96 32 96 66 Q96 98 60 98 Q28 98 28 66 Q28 40 54 42 Q74 44 74 66 Q74 82 58 80", c.body, c.line, 13)}
      ${bandsOn(SP, [[0, 0.4], [0, 0.85], [1, 0.4], [1, 0.85], [2, 0.4], [2, 0.85], [3, 0.5], [4, 0.5], [5, 0.5]], c.shade, 6, 6)}
    </g>
    <g class="head-tilt">
      <path d="M50 36 Q48 24 60 22 Q72 24 70 36 Q60 44 50 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 22 q0 -6 0 -9 M60 13 l-3 -4 M60 13 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(54, 30, 2.6, E)}${eye(66, 30, 2.6, E)}
    </g>`;
  },

  // ── Death Adder — very fat short C-curl, bold chevrons, thin worm-like caudal LURE tail held up
  deathadder: (c) => {
    const B = belly(c), E = eyeInk(c);
    const chev = (x, y) => `<path d="M${x - 8} ${y - 5} L${x} ${y} L${x + 8} ${y - 5}" fill="none" stroke="${c.shade}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(58, 110, 34)}
    <g class="tail-wag">
      ${tube("M34 92 Q20 96 20 84 Q20 76 28 78", c.body, c.line, 5)}
      <ellipse cx="21" cy="82" rx="3.4" ry="2.6" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>
    </g>
    <g class="breathe">
      ${tube("M38 96 Q14 86 24 66 Q34 50 60 54 Q84 58 86 80", c.body, c.line, 19)}
      ${[[30, 72], [48, 58], [70, 64]].map(([x, y]) => chev(x, y)).join("")}
      ${tube("M40 92 Q24 82 32 66", B, "none", 4)}
    </g>
    <g class="head-tilt">
      <path d="M72 74 L96 66 Q104 74 98 84 L78 88 Q70 82 72 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M74 76 L94 70 M74 84 L96 80" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>
      <path d="M100 76 q5 1 8 0 M108 76 l4 -3 M108 76 l4 3" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(84, 74, 2.6, E)}
    </g>`;
  },

  // ── Hognose — plump loose S with a mildly spread neck and the signature UPTURNED pointed pig snout
  hognose: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(58, 110, 32)}
    <g class="breathe">
      ${tube("M40 102 Q16 94 26 74 Q36 58 58 62 Q78 66 70 48", c.body, c.line, 15)}
      ${tube("M42 98 Q26 88 32 72", B, "none", 4)}
    </g>
    <g class="head-tilt">
      <path d="M56 52 Q48 40 60 34 Q74 30 82 40 Q86 48 80 54 Q70 60 60 58 Q56 56 56 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M80 40 Q90 34 90 42 Q88 47 82 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M84 40 l3 -1" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M88 44 q5 0 8 -2 M96 42 l4 -2 M96 42 l3 3" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(66, 44, 3, E)}
      ${smile(74, 50, 2.2, E)}
    </g>`;
  },

  // ── Milk Snake — body folded into stacked rows (festoon), vivid tricolour ring-BANDS wrapping around
  milksnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    // tricolour ring-bands clamped ON each straight festoon row (never off the body, never on the turns)
    const seg = (y, xs, o) => xs.map((x, i) => `<rect x="${x - 3}" y="${y - 6}" width="6" height="12" rx="1.5" fill="${(i + o) % 2 ? c.shade : B}"/>`).join("");
    const bands = seg(48, [30, 43, 56, 69, 82], 0) + seg(66, [82, 69, 56, 43, 34], 1) + seg(84, [34, 47, 60, 73], 0);
    return `
    ${floorShadow(58, 110, 36)}
    <g class="breathe">
      ${tube("M24 48 H92 Q104 48 104 57 Q104 66 92 66 H28 Q16 66 16 75 Q16 84 28 84 H86", c.body, c.line, 13)}
      ${bands}
    </g>
    <g class="head-tilt">
      <path d="M80 84 Q96 80 100 88 Q96 96 82 94 Q74 89 80 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M100 88 q6 1 10 0 M110 88 l4 -3 M110 88 l4 3" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(88, 86, 2.6, E)}
    </g>`;
  },

  // ── Kingsnake — body tied in a loose overhand KNOT (two crossing arcs), chain-link band pattern
  kingsnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    const A1 = [[[32, 94], [6, 74], [32, 52]], [[32, 52], [54, 34], [76, 52]], [[76, 52], [92, 66], [80, 82]]];
    const A2 = [[[46, 44], [72, 26], [94, 52]], [[94, 52], [112, 76], [82, 96]], [[82, 96], [60, 106], [52, 86]]];
    return `
    ${floorShadow(60, 110, 33)}
    <g class="tail-wag">${tube("M34 98 Q22 92 28 82", c.body, c.line, 6)}</g>
    <g class="breathe">
      ${tube("M32 94 Q6 74 32 52 Q54 34 76 52 Q92 66 80 82", c.body, c.line, 13)}
      ${tube("M46 44 Q72 26 94 52 Q112 76 82 96 Q60 106 52 86", c.body, c.line, 13)}
      ${bandsOn(A1, [[0, 0.5], [1, 0.5], [2, 0.4], [2, 0.8]], B, 4.5, 7)}
      ${bandsOn(A2, [[0, 0.45], [1, 0.4], [1, 0.75], [2, 0.5]], B, 4.5, 7)}
    </g>
    <g class="head-tilt">
      <path d="M40 46 Q34 34 46 30 Q58 28 60 40 Q58 50 48 50 Q42 50 40 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M46 30 q-2 -6 -1 -9 M45 21 l-4 -2 M45 21 l1 -4" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(50, 40, 2.8, E)}
    </g>`;
  },

  // ── Corn Snake — relaxed lying S with big dorsal SADDLE blotches, friendly head lifted at right
  cornsnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    const saddle = (x, y) => `<ellipse cx="${x}" cy="${y}" rx="8" ry="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/><ellipse cx="${x}" cy="${y}" rx="3.5" ry="2.6" fill="${B}" opacity=".5"/>`;
    return `
    ${floorShadow(58, 108, 33)}
    <g class="breathe">
      ${tube("M14 86 Q34 70 52 84 Q70 96 84 78 Q90 70 98 60", c.body, c.line, 13)}
      ${[[26, 78], [46, 82], [64, 86], [82, 74]].map(([x, y]) => saddle(x, y)).join("")}
      ${tube("M18 88 Q34 76 50 86", B, "none", 3)}
    </g>
    <g class="head-tilt">
      <path d="M90 58 Q88 44 102 42 Q113 44 111 56 Q104 64 94 64 Q90 62 90 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M102 42 q0 -6 0 -9 M102 33 l-3 -4 M102 33 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(98, 52, 2.8, E)}
      ${smile(105, 56, 2, E)}
    </g>`;
  },

  // ── Vine Snake — extremely THIN body in a gentle wave with a very long sharply POINTED head
  vinesnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(58, 106, 30)}
    <g class="breathe">
      ${tube("M12 76 Q34 58 56 72 Q76 84 90 72", c.body, c.line, 6)}
      <path d="M12 76 Q34 58 56 72 Q76 84 90 72" fill="none" stroke="${B}" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M84 70 L112 67 Q115 72 108 76 L84 78 Q80 74 84 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M112 69 q3 0 5 -1 M117 68 l3 -2" fill="none" stroke="${TONGUE}" stroke-width="1.3" stroke-linecap="round"/>
      ${eye(92, 71, 2.4, E)}
    </g>`;
  },

  // ── Flying Snake — flattened wide RIBBON gliding in an S, pale flat belly, faint cross-scales, small head
  flyingsnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 108, 34)}
    <g class="breathe">
      <path d="M12 58 Q36 42 60 58 Q84 74 106 58 L106 72 Q84 88 60 72 Q36 56 12 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M12 66 Q36 50 60 66 Q84 82 106 66" fill="none" stroke="${B}" stroke-width="3" stroke-linecap="round" opacity=".75"/>
      <g opacity=".5">${bandsOn([[[12, 65], [36, 49], [60, 65]], [[60, 65], [84, 81], [106, 65]]], [[0, 0.22], [0, 0.5], [0, 0.78], [1, 0.22], [1, 0.5], [1, 0.78]], c.shade, 2.4, 6)}</g>
    </g>
    <g class="head-tilt">
      <path d="M96 58 Q112 54 114 64 Q112 72 98 72 Q90 65 96 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M114 62 q4 1 7 0 M121 62 l3 -2" fill="none" stroke="${TONGUE}" stroke-width="1.4" stroke-linecap="round"/>
      ${eye(104, 62, 2.6, E)}
    </g>`;
  },

  // ── Green Mamba — elegant TALL slim reach rising from a small base coil, head lifted high, bright & clean
  greenmamba: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(56, 110, 26)}
    <g class="breathe">
      ${tube("M30 100 Q12 94 22 80 Q32 70 48 78 Q68 88 62 56 Q58 34 78 26", c.body, c.line, 11)}
      ${tube("M64 60 Q60 40 74 30", B, "none", 3)}
    </g>
    <g class="head-tilt">
      <path d="M70 30 Q66 16 82 14 Q96 16 94 30 Q86 38 76 36 Q70 36 70 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="82" cy="24" rx="7" ry="4" fill="${B}" opacity=".45"/>
      <path d="M92 26 q6 -1 10 -3 M102 23 l4 -1 M102 23 l3 3" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(84, 26, 2.8, E)}
    </g>`;
  },

  // ── Puff Adder — extremely FAT low broad squat S, bold chevron markings, small blunt head lifted at right
  puffadder: (c) => {
    const B = belly(c), E = eyeInk(c);
    const BODY = [[[22, 98], [12, 78], [34, 74]], [[34, 74], [56, 70], [56, 90]], [[56, 90], [56, 100], [78, 96]], [[78, 96], [98, 92], [90, 72]]];
    return `
    ${floorShadow(58, 112, 36)}
    <g class="breathe">
      ${tube("M22 98 Q12 78 34 74 Q56 70 56 90 Q56 100 78 96 Q98 92 90 72", c.body, c.line, 22)}
      ${chevronsOn(BODY, [[0, 0.5], [1, 0.5], [2, 0.5], [3, 0.55]], c.shade, 4, 9)}
      ${tube("M26 96 Q20 82 36 80", B, "none", 5)}
    </g>
    <g class="head-tilt">
      <path d="M80 66 Q78 52 94 50 Q108 52 106 66 Q98 76 86 74 Q80 72 80 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M84 60 q10 -3 18 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
      <path d="M94 50 q0 -5 0 -8 M94 42 l-3 -4 M94 42 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(90, 60, 2.8, E)}
    </g>`;
  },

  // ── Bush Viper — round coiled BALL bristling all over with spiky keeled scales, spiky-browed head on top
  bushviper: (c) => {
    const B = belly(c), E = eyeInk(c);
    const spike = (x, y, ang) => {
      const a = ang * Math.PI / 180, tx = x + Math.cos(a) * 6, ty = y + Math.sin(a) * 6, px = -Math.sin(a) * 2.4, py = Math.cos(a) * 2.4;
      return `<path d="M${(x + px).toFixed(1)} ${(y + py).toFixed(1)} L${tx.toFixed(1)} ${ty.toFixed(1)} L${(x - px).toFixed(1)} ${(y - py).toFixed(1)} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`;
    };
    const scales = [];
    for (let r = 0; r < 3; r++) { const rr = 16 + r * 8, n = 8 + r * 3; for (let k = 0; k < n; k++) { const a = k * 360 / n + r * 12, rad = a * Math.PI / 180; scales.push(spike(60 + rr * Math.cos(rad), 64 + rr * Math.sin(rad), a)); } }
    return `
    ${floorShadow(60, 110, 32)}
    <g class="breathe">
      <circle cx="60" cy="64" r="30" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      ${tube("M60 90 Q40 86 42 68 Q44 54 60 56 Q76 58 74 70", c.shade, "none", 10)}
      ${scales.join("")}
    </g>
    <g class="head-tilt">
      <path d="M50 34 Q48 22 62 20 Q76 22 74 34 Q64 44 50 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      ${[42, 54, 66, 78].map((x) => `<path d="M${x} 30 l-2 -6 l4 2 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="0.9" stroke-linejoin="round"/>`).join("")}
      <path d="M62 20 q0 -6 0 -9 M62 11 l-3 -4 M62 11 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(55, 30, 2.6, E)}${eye(69, 30, 2.6, E)}
    </g>`;
  },

  // ── Eyelash Viper — smooth compact coil, head reared with prominent bristly EYELASH brow scales over eyes
  eyelashviper: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(58, 110, 32)}
    <g class="breathe">
      ${tube("M16 92 Q30 76 48 84 Q66 92 80 80 Q92 70 86 54", c.body, c.line, 14)}
      ${tube("M20 90 Q32 80 46 86", B, "none", 4)}
    </g>
    <g class="head-tilt">
      <path d="M74 52 Q70 36 86 34 Q100 34 98 48 Q92 58 80 58 Q74 58 74 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M78 40 l-4 -6 l6 2 Z M86 37 l-2 -7 l5 3 Z M94 39 l3 -6 l1 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <path d="M98 48 q6 0 10 -2 M108 46 l4 -2 M108 46 l3 3" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(86, 48, 3, E)}
    </g>`;
  },

  // ── Rat Snake — the plain everyman: a simple round single coil, gentle front face + smile, subtle sheen
  ratsnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 110, 36)}
    <g class="breathe">
      <ellipse cx="60" cy="74" rx="42" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <path d="M60 78 L60.3 78 L60.5 78.1 L60.8 78.2 L60.9 78.4 L61 78.6 L60.9 78.8 L60.8 79.1 L60.5 79.3 L60.2 79.5 L59.7 79.6 L59.2 79.7 L58.6 79.8 L57.9 79.8 L57.2 79.7 L56.5 79.5 L55.9 79.2 L55.3 78.8 L54.9 78.4 L54.5 77.9 L54.3 77.4 L54.3 76.8 L54.5 76.2 L54.9 75.6 L55.5 75 L56.3 74.5 L57.2 74 L58.4 73.7 L59.6 73.4 L61 73.3 L62.5 73.3 L63.9 73.4 L65.4 73.7 L66.7 74.2 L68 74.8 L69.1 75.5 L70 76.4 L70.6 77.3 L70.9 78.3 L71 79.4 L70.7 80.5 L70.1 81.5 L69.1 82.5 L67.8 83.5 L66.3 84.3 L64.5 84.9 L62.4 85.4 L60.3 85.7 L58 85.8 L55.6 85.7 L53.3 85.3 L51.1 84.7 L49.1 83.9 L47.3 82.8 L45.8 81.6 L44.7 80.3 L43.9 78.8 L43.6 77.3 L43.8 75.7 L44.4 74.1 L45.5 72.6 L47.1 71.2 L49.1 69.9 L51.4 68.9 L54.1 68 L57 67.4 L60.1 67.1 L63.3 67.1 L66.5 67.5 L69.6 68.1 L72.6 69 L75.2 70.2 L77.5 71.7 L79.4 73.4 L80.7 75.2 L81.5 77.2 L81.8 79.3 L81.4 81.4 L80.4 83.4 L78.7 85.4 L76.5 87.2 L73.8 88.7 L70.6 90 L67.1 91 L63.2 91.7 L59.2 92 L55.1 91.9 L51.1 91.4 L47.1 90.5 L43.5 89.2 L40.3 87.6 L37.5 85.7 L35.3 83.5 L33.8 81.1 L33 78.6 L32.9 76 L33.6 73.4 L35 70.9 L37.2 68.5" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" opacity=".65"/>
      <path d="M28 66 Q36 62 44 66 M76 66 Q84 62 92 66" fill="none" stroke="${B}" stroke-width="2" stroke-linecap="round" opacity=".4"/>
    </g>
    <g class="head-tilt">
      <path d="M48 50 Q46 36 60 34 Q74 36 72 50 Q62 58 48 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 34 q0 -6 0 -9 M60 25 l-3 -4 M60 25 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(54, 44, 3, E)}${eye(66, 44, 3, E)}
      ${smile(60, 50, 2.4, E)}
    </g>`;
  },

  // ── Egg-eating Snake — thin body with a huge round mid-body BULGE (a swallowed egg showing through), thin head
  eggeatingsnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 108, 33)}
    <g class="breathe">
      ${tube("M16 92 Q22 70 40 64", c.body, c.line, 8)}
      ${tube("M80 64 Q98 70 104 90", c.body, c.line, 8)}
      <ellipse cx="60" cy="62" rx="24" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="60" cy="60" rx="14" ry="12" fill="${B}" opacity=".5"/>
      <path d="M42 54 Q60 48 78 54" fill="none" stroke="${c.shade}" stroke-width="1.6" stroke-linecap="round" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M96 84 Q92 96 102 98 Q110 94 106 84 Q101 80 96 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M102 98 q2 5 -2 8 M100 99 l-1 5" fill="none" stroke="${TONGUE}" stroke-width="1.4" stroke-linecap="round"/>
      ${eye(101, 88, 2.4, E)}
    </g>`;
  },
};

export const ROSTER_SNAKES2 = [
  { n: "Boomslang",         e: "🐍", tier: 2, float: false },
  { n: "Copperhead",        e: "🐍", tier: 2, float: false },
  { n: "Cottonmouth",       e: "🐍", tier: 2, float: false },
  { n: "Bushmaster",        e: "🐍", tier: 3, float: false },
  { n: "Fer-de-lance",      e: "🐍", tier: 3, float: false },
  { n: "Taipan",            e: "🐍", tier: 3, float: false },
  { n: "Tiger Snake",       e: "🐍", tier: 2, float: false },
  { n: "Death Adder",       e: "🐍", tier: 3, float: false },
  { n: "Hognose",           e: "🐍", tier: 1, float: false },
  { n: "Milk Snake",        e: "🐍", tier: 2, float: false },
  { n: "Kingsnake",         e: "🐍", tier: 2, float: false },
  { n: "Corn Snake",        e: "🐍", tier: 1, float: false },
  { n: "Vine Snake",        e: "🐍", tier: 2, float: false },
  { n: "Flying Snake",      e: "🐍", tier: 2, float: false },
  { n: "Green Mamba",       e: "🐍", tier: 2, float: false },
  { n: "Puff Adder",        e: "🐍", tier: 2, float: false },
  { n: "Bush Viper",        e: "🐍", tier: 3, float: false },
  { n: "Eyelash Viper",     e: "🐍", tier: 2, float: false },
  { n: "Rat Snake",         e: "🐍", tier: 1, float: false },
  { n: "Egg-eating Snake",  e: "🐍", tier: 1, float: false },
];
