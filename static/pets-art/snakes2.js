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
    const hg = (x, y) => `<path d="M${x - 9} ${y - 7} Q${x} ${y - 2} ${x + 9} ${y - 7} L${x + 9} ${y + 7} Q${x} ${y + 2} ${x - 9} ${y + 7} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(58, 108, 32)}
    <g class="breathe">
      ${tube("M14 82 Q32 66 50 82 Q66 96 82 82", c.body, c.line, 13)}
      ${[[28, 76], [50, 84], [70, 86]].map(([x, y]) => hg(x, y)).join("")}
      ${tube("M16 84 Q32 72 48 84", B, "none", 3)}
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
      ${tube("M58 102 Q20 100 22 74 Q26 54 58 56 Q86 56 90 76 Q92 100 62 100", c.body, c.line, 16)}
      ${tube("M62 100 Q40 94 42 74 Q44 60 58 60 Q72 60 72 72", c.body, c.line, 12)}
      <ellipse cx="58" cy="76" rx="11" ry="8" fill="${c.shade}" opacity=".35"/>
      ${tube("M30 92 Q24 80 30 68", B, "none", 4)}
    </g>
    <g class="head-tilt">
      ${tube("M88 74 Q98 58 82 48", c.body, c.line, 12)}
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
    const mk = (x, y) => `<path d="M${x - 6} ${y - 6} L${x} ${y} L${x - 6} ${y + 6} M${x + 6} ${y - 6} L${x} ${y} L${x + 6} ${y + 6}" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(56, 110, 33)}
    <g class="breathe">
      ${tube("M30 100 Q10 90 20 72 Q30 56 50 62 Q68 68 60 84 Q54 96 76 92", c.body, c.line, 13)}
      ${[[26, 84], [36, 64], [58, 74]].map(([x, y]) => mk(x, y)).join("")}
      ${tube("M30 98 Q16 88 22 74", B, "none", 3)}
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
    const band = (a) => {
      const rad = a * Math.PI / 180, x1 = 60 + 22 * Math.cos(rad), y1 = 64 + 30 * Math.sin(rad), x2 = 60 + 40 * Math.cos(rad), y2 = 64 + 40 * Math.sin(rad);
      return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${c.shade}" stroke-width="6" stroke-linecap="round" opacity=".8"/>`;
    };
    return `
    ${floorShadow(60, 110, 34)}
    <g class="breathe">
      ${tube("M60 98 Q22 96 22 64 Q22 32 60 32 Q98 32 98 64 Q98 92 66 96", c.body, c.line, 15)}
      ${[20, 55, 90, 125, 160, -20, -55].map((a) => band(a)).join("")}
      ${tube("M66 96 Q44 90 46 68 Q48 54 62 54 Q76 56 76 68", c.body, c.line, 13)}
      <ellipse cx="61" cy="70" rx="10" ry="8" fill="${B}" opacity=".4"/>
    </g>
    <g class="head-tilt">
      <path d="M50 34 Q48 22 60 20 Q72 22 70 34 Q60 42 50 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 20 q0 -6 0 -9 M60 11 l-3 -4 M60 11 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(54, 28, 2.6, E)}${eye(66, 28, 2.6, E)}
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
      <ellipse cx="52" cy="82" rx="14" ry="7" fill="${c.shade}" opacity=".28"/>
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
    const rows = [48, 66, 84];
    const bands = rows.map((y, ri) => [32, 44, 56, 68, 80].map((x, i) => {
      const col = (i + ri) % 2 ? c.shade : B;
      return `<rect x="${x - 3}" y="${y - 7.5}" width="6" height="15" rx="2" fill="${col}"/>`;
    }).join("")).join("");
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
    const link = (x, y) => `<path d="M${x - 5} ${y - 4} L${x - 5} ${y + 4} M${x + 5} ${y - 4} L${x + 5} ${y + 4} M${x - 5} ${y} L${x + 5} ${y}" stroke="${B}" stroke-width="2.2" stroke-linecap="round"/>`;
    return `
    ${floorShadow(60, 110, 33)}
    <g class="tail-wag">${tube("M34 98 Q22 92 28 82", c.body, c.line, 6)}</g>
    <g class="breathe">
      ${tube("M32 94 Q6 74 32 52 Q54 34 76 52 Q92 66 80 82", c.body, c.line, 13)}
      ${tube("M46 44 Q72 26 94 52 Q112 76 82 96 Q60 106 52 86", c.body, c.line, 13)}
      ${[[20, 68], [54, 42], [88, 66], [70, 94]].map(([x, y]) => link(x, y)).join("")}
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
      ${[24, 44, 64, 84].map((x) => `<path d="M${x} 52 q3 8 0 20" fill="none" stroke="${c.shade}" stroke-width="2.2" stroke-linecap="round" opacity=".5"/>`).join("")}
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
    const chev = (x, y) => `<path d="M${x - 9} ${y - 6} L${x} ${y} L${x + 9} ${y - 6}" fill="none" stroke="${c.shade}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(58, 112, 36)}
    <g class="breathe">
      ${tube("M22 98 Q12 78 34 74 Q56 70 56 90 Q56 100 78 96 Q98 92 90 72", c.body, c.line, 22)}
      ${[[34, 80], [56, 82], [78, 84]].map(([x, y]) => chev(x, y)).join("")}
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
      <circle cx="60" cy="64" r="12" fill="${B}" opacity=".35"/>
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
    ${floorShadow(60, 110, 33)}
    <g class="breathe">
      ${tube("M60 98 Q24 94 24 66 Q24 38 60 38 Q96 38 96 66 Q96 90 64 96", c.body, c.line, 15)}
      ${tube("M64 96 Q42 90 44 70 Q46 56 60 58 Q74 60 72 72", c.body, c.line, 12)}
      <ellipse cx="60" cy="72" rx="11" ry="8" fill="${B}" opacity=".4"/>
      <path d="M34 62 Q40 58 46 62 M74 62 Q80 58 86 62" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M48 40 Q46 26 60 24 Q74 26 72 40 Q62 48 48 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 24 q0 -6 0 -9 M60 15 l-3 -4 M60 15 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(54, 34, 3, E)}${eye(66, 34, 3, E)}
      ${smile(60, 40, 2.4, E)}
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
