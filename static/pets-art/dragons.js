// dragons.js — BESPOKE hand-drawn SVG art for the DRAGONS batch (NADO Pets) — the rare chase pets (tier 3–6).
// HOUSE STYLE: ONE continuous body+head silhouette (fill c.body, outline c.line sw 3.2, round joins);
// appendages (wings/tails/horns) tuck behind / overlap ≥6px so NOTHING floats; two-tone via belly(c)+c.shade;
// big glossy ceye/eye face; grounded with floorShadow. Colours come from the coat `c` (recoloured at hatch);
// only universal accents are fixed: horns #f2c94c, magic fire #ff7a1a, glow #eafff4, teeth #fff (sparingly).
// viewBox 0 0 120 120, dragon centred ~ (60,64), within x,y ∈ [8,114]. Each is a DISTINCT dragon body-plan.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const HORN = "#f2c94c", FIRE = "#ff7a1a", GLOW = "#eafff4", TOOTH = "#fff";

// three splayed claws at a foot tip (x,y = foot bottom centre)
const claw = (x, y) => `<path d="M${x} ${y} l-3 4 m3 -4 l0 5 m0 -5 l3 4" stroke="${TOOTH}" stroke-width="1.5" stroke-linecap="round" fill="none"/>`;
// a row of back spikes (triangles apex-up) along baseline y, height h
const ridge = (xs, y, h, fill, line, w = 1.6) => xs.map((x) => `<path d="M${x - 4} ${y} l4 -${h} l4 ${h} Z" fill="${fill}" stroke="${line}" stroke-width="${w}" stroke-linejoin="round"/>`).join("");

// shared side-standing drake/western torso facing right: ONE path incl. 2 legs + neck + head bump.
// head centre ~ (95,62), snout tip (108,62), eye ~ (90,64), horns root ~ (88–97,54), feet (44,104)&(68,104).
const SIDE = "M32 84 C32 62 46 54 66 54 C74 54 80 57 84 62 L92 54 C104 52 108 62 103 70 C99 76 91 74 88 70 C88 82 82 90 72 90 L72 104 L64 104 L64 90 L48 90 L48 104 L40 104 L40 84 Z";
const sideBody = (c) => `<path d="${SIDE}" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`;

export const ART_DRAGONS = {
  // ── Fire Drake (t4) — chunky four-legged drake, no wings, back-swept horns, spade tail, breathes a curl of flame
  firedrake: (c) => { const B = belly(c); return `
    ${floorShadow(58, 111, 32)}
    <g class="tail-wag"><path d="M40 82 Q16 88 12 66 Q11 55 23 56 Q15 64 22 73 Q30 80 42 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M14 64 l-7 -4 l3 8 l-8 1 l7 5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${sideBody(c)}
      ${ridge([46, 56, 66], 55, 9, c.shade, c.line)}
      <path d="M50 84 Q66 92 84 84 Q68 88 50 84 Z" fill="${B}" opacity=".85"/>
      ${claw(44, 103)}${claw(68, 103)}
      <path d="M88 56 Q84 42 76 40 Q82 48 82 58 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M97 56 Q95 42 86 38 Q90 48 91 58 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="105" cy="60" rx="1.3" ry="1" fill="${INK}"/>
      ${ceye(91, 64, 3.8)}
      <path d="M107 66 Q116 62 113 58 Q114 66 120 66 Q114 72 106 70 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
    </g>`; },

  // ── Ice Wyrm (t4, serpentine) — legless coiled serpent rising in an S, crystalline icicle dorsal spikes, frost breath
  icewyrm: (c) => { const B = belly(c); const F = tint(c.body, 0.55); return `
    ${floorShadow(60, 112, 30)}
    <g class="breathe">
      ${tube("M40 108 Q18 100 30 80 Q42 62 64 68 Q86 74 82 54 Q79 40 62 42", c.body, c.line, 15)}
      <path d="M36 104 q10 3 20 0 M30 90 q10 3 20 -2 M52 74 q10 2 18 -2" fill="none" stroke="${B}" stroke-width="3" stroke-linecap="round" opacity=".7"/>
      ${[[38, 96], [30, 80], [42, 68], [64, 66], [78, 56]].map(([x, y]) => `<path d="M${x - 3} ${y} l3 -9 l3 9 Z" fill="${F}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M50 42 Q50 26 66 26 Q84 26 84 42 Q84 54 74 56 L84 60 Q80 66 70 62 Q52 60 50 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M56 30 l-2 -9 l6 5 Z M68 28 l2 -9 l4 6 Z" fill="${F}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M84 58 q9 1 15 -2 M84 61 q9 3 15 3" fill="none" stroke="${GLOW}" stroke-width="1.6" stroke-linecap="round" opacity=".8"/>
      ${eye(66, 42, 3.4)}
    </g>`; },

  // ── Storm Dragon (t4, float) — western flier, huge swept membrane wings, lightning-bolt crest, cloud puffs at feet
  stormdragon: (c) => { const B = belly(c); return `
    ${floorShadow(58, 112, 30)}
    <g class="tail-wag"><path d="M40 82 Q16 90 12 68 Q11 57 23 58 Q15 66 22 75 Q30 82 42 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M15 66 l6 -8 l1 6 l7 -3 l-3 8 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/></g>
    <g class="tail-wag"><path d="M62 54 Q30 20 6 24 Q24 34 28 48 Q12 42 4 50 Q24 58 40 56 Q22 66 16 82 Q46 68 64 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M56 52 Q34 28 12 26 M54 55 Q34 44 18 46 M52 58 Q34 56 22 62" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".55"/></g>
    <g class="breathe">
      ${sideBody(c)}
      <path d="M50 84 Q66 92 84 84 Q68 88 50 84 Z" fill="${B}" opacity=".85"/>
      ${claw(44, 103)}${claw(68, 103)}
      <path d="M90 55 L97 42 L92 44 L99 32 L86 46 L91 45 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <ellipse cx="105" cy="60" rx="1.3" ry="1" fill="${INK}"/>
      ${ceye(91, 64, 3.6)}
    </g>`; },

  // ── Sea Dragon (t4, finned) — seahorse-dragon, webbed dorsal sail, pectoral fin, curled tail, gill whiskers
  seadragon: (c) => { const B = belly(c); const F = tint(c.body, 0.4); return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${tube("M56 94 Q78 98 78 80 Q78 68 66 70", c.body, c.line, 12)}
      <path d="M66 70 q-11 -2 -13 7 q9 -2 12 3 Z" fill="${F}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M50 48 Q32 42 26 52 Q37 52 40 58 Q27 60 24 70 Q38 66 46 60 Q36 76 40 86 Q52 72 54 56 Z" fill="${F}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round" opacity=".92"/>
    </g>
    <g class="breathe">
      <path d="M48 52 Q46 40 58 38 Q70 37 74 46 Q80 40 80 56 Q82 70 70 84 Q64 92 54 88 Q46 82 48 70 Q46 60 48 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M58 56 Q64 76 64 86 Q56 86 52 76 Q50 64 58 56 Z" fill="${B}" opacity=".8"/>
      <path d="M76 62 q11 -1 15 6 q-10 0 -13 6 Z" fill="${F}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M52 44 Q50 30 62 28 Q74 28 76 40 Q76 48 68 50 L80 54 Q76 60 66 56 Q54 54 52 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M62 29 q-3 -9 5 -10 q3 6 -1 11 Z" fill="${F}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M80 52 q8 1 12 5 M80 55 q7 3 9 7" fill="none" stroke="${B}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(64, 42, 3.2)}
    </g>`; },

  // ── Forest Dragon (t3, mossy/antlered) — earthy drake, branching antlers, moss tufts on the back, leaf-tip tail
  forestdragon: (c) => { const B = belly(c); const M = deepen(c.body, 0.2); return `
    ${floorShadow(58, 111, 32)}
    <g class="tail-wag"><path d="M40 82 Q16 88 12 66 Q11 55 23 56 Q15 64 22 73 Q30 80 42 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M13 63 Q4 60 6 52 Q12 58 18 56 Q10 62 15 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${sideBody(c)}
      ${pom(48, 54, 6, M, c.line, 7, 1.6)}${pom(60, 52, 7, M, c.line, 7, 1.6)}${pom(71, 55, 5.5, M, c.line, 7, 1.6)}
      <path d="M50 84 Q66 92 84 84 Q68 88 50 84 Z" fill="${B}" opacity=".85"/>
      ${claw(44, 103)}${claw(68, 103)}
      <path d="M89 55 Q88 40 80 34 M89 46 l-7 -3 M84 40 l-6 -1" fill="none" stroke="${HORN}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M96 55 Q97 40 105 34 M96 46 l7 -3 M101 40 l6 -1" fill="none" stroke="${HORN}" stroke-width="2.2" stroke-linecap="round"/>
      <ellipse cx="105" cy="60" rx="1.3" ry="1" fill="${INK}"/>
      ${ceye(91, 64, 3.6)}
    </g>`; },

  // ── Desert Wyrm (t3, sand) — serpent surging up out of sand mounds, ridged back-scutes, forked tongue
  desertwyrm: (c) => { const B = belly(c); const S = tint(c.body, 0.35); return `
    ${floorShadow(60, 112, 32)}
    <ellipse cx="34" cy="104" rx="18" ry="6" fill="${c.shade}" opacity=".6"/><ellipse cx="86" cy="106" rx="16" ry="5" fill="${c.shade}" opacity=".55"/>
    <g class="breathe">
      ${tube("M32 106 Q30 84 48 82 Q66 80 62 62 Q60 46 74 44", c.body, c.line, 14)}
      ${[[40, 84], [56, 74], [60, 58]].map(([x, y]) => `<path d="M${x - 3} ${y} l3 -8 l3 8 Z" fill="${S}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("")}
      <path d="M40 92 q9 3 16 -1 M52 76 q9 2 14 -2" fill="none" stroke="${B}" stroke-width="2.6" stroke-linecap="round" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M62 46 Q60 32 74 30 Q88 30 90 42 Q90 50 82 52 L92 56 Q88 62 78 58 Q64 56 62 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M92 56 l9 1 l-8 3 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="0.8" stroke-linejoin="round"/>
      <path d="M70 32 l-2 -7 l5 4 Z" fill="${S}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      ${eye(76, 44, 3.2)}
    </g>`; },

  // ── Shadow Dragon (t5, wispy) — crouched dark drake dissolving into smoke curls, glowing eyes, sharp horns
  shadowdragon: (c) => { const D = deepen(c.body, 0.25); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M46 86 Q26 92 22 80 Q30 84 34 78 Q24 80 24 70 Q32 78 42 78 Q36 84 48 84 Z" fill="${D}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".9"/>
    </g>
    <g class="tail-wag">
      ${tube("M44 64 Q28 58 30 46 Q32 40 39 42", D, c.line, 7)}
      ${tube("M76 64 Q92 58 90 46 Q88 40 81 42", D, c.line, 7)}
    </g>
    <g class="breathe">
      <path d="M34 92 Q30 62 60 60 Q90 62 86 92 Q84 100 74 96 Q78 84 72 74 Q60 96 48 74 Q42 84 46 96 Q36 100 34 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${ridge([50, 60, 70], 62, 8, c.shade, c.line)}
      <path d="M52 46 l-5 -12 l9 7 Z M68 46 l5 -12 l-9 7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M42 66 Q60 58 78 66 Q60 76 42 66 Z" fill="${deepen(c.body, 0.35)}" opacity=".55"/>
      <ellipse cx="52" cy="66" rx="4.2" ry="5" fill="${GLOW}"/><ellipse cx="68" cy="66" rx="4.2" ry="5" fill="${GLOW}"/>
      <ellipse cx="52" cy="67" rx="1.8" ry="2.6" fill="${INK}"/><ellipse cx="68" cy="67" rx="1.8" ry="2.6" fill="${INK}"/>
      <path d="M54 76 q6 4 12 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`; },

  // ── Crystal Dragon (t5, faceted) — geometric gem-scaled dragon, angular shard wings, brow gemstone, faceted body
  crystaldragon: (c) => { const B = belly(c); const F = tint(c.body, 0.4); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M60 70 L34 58 L40 68 L28 66 L36 76 L26 78 L44 84 L60 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${mirror(`<path d="M60 70 L34 58 L40 68 L28 66 L36 76 L26 78 L44 84 L60 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
    </g>
    <g class="breathe">
      <path d="M60 58 L84 68 L82 96 L60 106 L38 96 L36 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 58 L84 68 L60 80 Z" fill="${F}" opacity=".8"/><path d="M60 80 L82 96 L60 106 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M60 58 L36 68 L60 80 Z" fill="${tint(c.body, 0.2)}"/>
      ${claw(50, 105)}${claw(70, 105)}
    </g>
    <g class="head-tilt">
      <path d="M48 40 L60 30 L72 40 L70 56 L60 62 L50 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M48 40 L60 30 L60 46 Z" fill="${F}"/><path d="M60 46 L70 56 L60 62 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M50 38 L46 18 L55 34 Z M70 38 L74 18 L65 34 Z" fill="${F}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M60 34 l3 5 l-3 5 l-3 -5 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="1"/>
      ${eyes(54, 66, 48, 3, eyeInk(c))}
    </g>`; },

  // ── Bronze Dragon (t4, metallic) — burnished dragon, segmented back armour scutes + rivets, sheen, curled ram horns
  bronzedragon: (c) => { const B = belly(c); const M = tint(c.body, 0.5); return `
    ${floorShadow(58, 111, 32)}
    <g class="tail-wag"><path d="M40 84 Q30 86 24 82 Q18 77 23 71 Q27 79 34 79 Q41 80 42 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M14 60 l3 -9 l4 9 Z M10 63 l-9 3 l9 5 Z M13 74 l1 9 l5 -7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      <circle cx="18" cy="67" r="8" fill="${M}" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="14" cy="63" r="2.2" fill="${tint(c.body, 0.7)}" opacity=".7"/></g>
    <g class="breathe">
      ${sideBody(c)}
      ${[44, 55, 66].map((x) => `<path d="M${x - 6} 57 q6 -7 12 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
      ${[[46, 62], [57, 60], [68, 62]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.3" fill="${M}"/>`).join("")}
      <path d="M46 66 Q56 60 66 65 Q56 66 50 72 Z" fill="${M}" opacity=".5"/>
      <path d="M50 84 Q66 92 84 84 Q68 88 50 84 Z" fill="${B}" opacity=".85"/>
      <path d="M56 87 v3 M66 88 v3 M75 86 v3" stroke="${c.line}" stroke-width="1" opacity=".5"/>
      ${claw(44, 103)}${claw(68, 103)}
      <path d="M88 55 Q80 44 88 36 Q94 40 92 48 Q90 53 88 55 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M96 55 Q88 44 96 36 Q102 40 100 48 Q98 53 96 55 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="105" cy="60" rx="1.3" ry="1" fill="${INK}"/>
      ${ceye(91, 64, 3.6)}
    </g>`; },

  // ── Faerie Dragon (t3, tiny + butterfly wings, float) — chibi micro-dragon, huge iridescent butterfly wings, antennae
  faeriedragon: (c) => { const B = belly(c); const W = tint(c.body, 0.5); return `
    ${floorShadow(60, 110, 22)}
    <g class="tail-wag">
      <path d="M58 60 Q30 40 24 56 Q34 60 40 58 Q28 70 36 82 Q52 74 60 64 Z" fill="${W}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round" opacity=".9"/>
      <circle cx="34" cy="56" r="2.4" fill="${GLOW}"/><circle cx="40" cy="76" r="2" fill="${GLOW}"/>
      ${mirror(`<path d="M58 60 Q30 40 24 56 Q34 60 40 58 Q28 70 36 82 Q52 74 60 64 Z" fill="${W}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round" opacity=".9"/><circle cx="34" cy="56" r="2.4" fill="${GLOW}"/><circle cx="40" cy="76" r="2" fill="${GLOW}"/>`)}
    </g>
    <g class="tail-wag"><path d="M58 78 Q52 92 60 96 Q66 90 62 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M46 74 Q44 60 60 58 Q76 60 74 74 Q72 84 60 84 Q48 84 46 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="76" rx="8" ry="6" fill="${B}" opacity=".8"/>
    </g>
    <g class="head-tilt">
      <path d="M50 44 Q48 47 52 49 M70 44 Q72 47 68 49" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="50" cy="42" r="2" fill="${HORN}"/><circle cx="70" cy="42" r="2" fill="${HORN}"/>
      <circle cx="60" cy="54" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M50 46 l-2 -6 l5 4 Z M70 46 l2 -6 l-5 4 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${eyes(54, 66, 54, 3.8, eyeInk(c))}
      ${smile(60, 60, 2.6, eyeInk(c))}
    </g>`; },

  // ── Cave Drake (t3, no wings) — stocky hunched drake, blunt snout, knobby rock-brow, beady eyes, no wings
  cavedrake: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 32)}
    <g class="tail-wag"><path d="M44 88 Q22 92 18 74 Q17 64 28 66 Q20 73 27 80 Q34 86 46 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 94 C26 76 38 68 56 68 C66 68 72 71 76 76 C80 70 92 68 100 74 C108 80 106 92 98 92 C96 96 88 96 86 90 C84 90 80 90 78 88 L78 104 L70 104 L70 92 L52 92 L52 104 L44 104 L44 92 C34 92 28 92 28 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[[44, 74], [56, 71], [68, 73]].map(([x, y]) => `<path d="M${x - 4} ${y + 2} L${x - 2} ${y - 4} L${x + 1} ${y - 2} L${x + 3} ${y - 5} L${x + 4} ${y + 2} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("")}
      <path d="M44 88 Q62 96 80 88 Q62 92 44 88 Z" fill="${B}" opacity=".8"/>
      ${claw(48, 103)}${claw(74, 103)}
      <path d="M90 74 Q86 66 92 64 Q96 68 94 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M100 74 Q97 66 103 65 Q106 70 103 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="106" cy="82" rx="1.3" ry="1" fill="${INK}"/>
      ${ceye(96, 82, 3)}
    </g>`; },

  // ── Bog Dragon (t3) — wide squat swamp drake, warty bumps, droopy half-lidded eyes, webbed feet, lily-pad on back
  bogdragon: (c) => { const B = belly(c); const M = deepen(c.body, 0.2); return `
    ${floorShadow(60, 113, 36)}
    <g class="tail-wag"><path d="M42 96 Q22 100 20 84 Q20 76 30 78 Q23 84 30 90 Q36 94 44 91 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 96 C24 80 40 74 60 74 C74 74 80 77 84 82 L92 76 C104 74 108 84 103 90 C99 95 92 93 89 90 C88 96 82 100 74 100 L74 108 L64 108 L64 100 L44 100 L44 108 L34 108 L34 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[[38, 82], [50, 78], [62, 80], [74, 84]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.6" fill="${M}" stroke="${c.line}" stroke-width="1.2"/>`).join("")}
      <ellipse cx="52" cy="76" rx="9" ry="4" fill="${tint(c.body, 0.3)}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M42 92 Q60 100 82 92 Q60 96 42 92 Z" fill="${B}" opacity=".8"/>
      <path d="M40 108 h9 M60 108 h9" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".6"/>
      <path d="M92 78 Q90 70 96 68 Q99 72 97 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="106" cy="88" rx="1.3" ry="1" fill="${INK}"/>
      <g class="blink"><ellipse cx="96" cy="84" rx="4" ry="4.4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/><ellipse cx="96" cy="85.5" rx="2.6" ry="2.4" fill="${INK}"/><path d="M92 83 q4 -2 8 0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/></g>
    </g>`; },

  // ── Sky Serpent (t4, eastern long, float) — long undulating eastern dragon, flowing whiskers, mane tufts, tiny clawed legs
  skyserpent: (c) => { const B = belly(c); const M = deepen(c.body, 0.18); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      ${tube("M14 78 Q34 92 50 76 Q66 60 84 66 Q102 72 106 54", c.body, c.line, 12)}
      <path d="M14 78 q-7 -2 -9 -9 q7 2 11 -2 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${[[36, 82], [50, 74], [66, 63], [84, 65]].map(([x, y]) => `${pom(x, y - 7, 3.5, M, c.line, 6, 1.2)}`).join("")}
    </g>
    <g class="breathe">
      <path d="M46 82 q-3 8 -9 9 M64 68 q-3 8 -9 9" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M46 82 q-3 8 -9 9 M64 68 q-3 8 -9 9" fill="none" stroke="${c.body}" stroke-width="1.4" stroke-linecap="round"/>
      ${claw(41, 90)}${claw(59, 76)}
    </g>
    <g class="head-tilt">
      ${pom(96, 46, 6, M, c.line, 7, 1.4)}
      <path d="M92 62 Q90 46 104 44 Q116 44 116 56 Q116 64 108 66 L118 70 Q114 76 104 72 Q92 70 92 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M100 48 Q96 38 102 34 Q106 42 104 48 Z" fill="${M}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M94 66 Q84 70 78 66 M94 69 Q86 74 82 72" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(106, 58, 3.2)}
    </g>`; },

  // ── Ember Wyrm (t3) — compact coiled serpent glowing with ember cracks, curled tight, warm face
  emberwyrm: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="breathe">
      ${tube("M74 96 Q100 92 96 66 Q92 44 64 46 Q38 48 40 72 Q42 90 62 88 Q76 86 74 74", c.body, c.line, 15)}
      <path d="M70 92 q14 0 20 -10 M52 84 q-6 -10 2 -20 M56 54 q14 -4 26 4" fill="none" stroke="${FIRE}" stroke-width="2" stroke-linecap="round" opacity=".85"/>
      <circle cx="86" cy="72" r="2" fill="${FIRE}"/><circle cx="50" cy="66" r="1.8" fill="${FIRE}"/>
    </g>
    <g class="head-tilt">
      <path d="M42 74 Q40 60 54 58 Q68 58 70 70 L60 76 Q68 78 68 84 Q62 90 52 86 Q40 84 42 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M48 60 l-3 -8 l7 4 Z M62 58 l3 -8 l-6 5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M42 74 q-8 2 -12 -2" fill="none" stroke="${FIRE}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(54, 72, 3.4)}
    </g>`; },

  // ── Frost Drake (t4) — pale drake, sharp icicle dorsal spikes, frosted belly, cold-breath puff, icy tail shard
  frostdrake: (c) => { const B = belly(c); const F = tint(c.body, 0.55); return `
    ${floorShadow(58, 111, 32)}
    <g class="tail-wag"><path d="M40 82 Q16 88 12 66 Q11 55 23 56 Q15 64 22 73 Q30 80 42 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M13 63 l-8 -6 l3 8 l-6 4 l9 2 Z" fill="${F}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${sideBody(c)}
      ${[[46, 55, 11], [56, 55, 13], [66, 55, 10]].map(([x, y, h]) => `<path d="M${x - 3} ${y} l3 -${h} l3 ${h} Z" fill="${F}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("")}
      <path d="M50 84 Q66 92 84 84 Q68 88 50 84 Z" fill="${F}" opacity=".85"/>
      ${claw(44, 103)}${claw(68, 103)}
      <path d="M88 56 l-3 -13 l6 5 Z" fill="${F}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M97 56 l3 -13 l-6 5 Z" fill="${F}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="105" cy="60" rx="1.3" ry="1" fill="${INK}"/>
      ${ceye(91, 64, 3.6)}
      <circle cx="114" cy="63" r="2.4" fill="${GLOW}" opacity=".8"/><circle cx="118" cy="60" r="1.6" fill="${GLOW}" opacity=".7"/>
    </g>`; },

  // ── Thunder Dragon (t4, float) — front-standing western dragon, raised wings, jagged bolt crest, spark on chest
  thunderdragon: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M56 70 Q30 46 16 52 Q28 58 30 66 Q18 66 12 74 Q30 74 40 70 Q28 78 24 90 Q46 78 58 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${mirror(`<path d="M56 70 Q30 46 16 52 Q28 58 30 66 Q18 66 12 74 Q30 74 40 70 Q28 78 24 90 Q46 78 58 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
    </g>
    <g class="breathe">
      <path d="M40 100 C36 70 44 62 60 62 C76 62 84 70 80 100 L72 108 L64 108 L62 100 L58 100 L56 108 L48 108 L40 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="13" ry="14" fill="${B}" opacity=".8"/>
      <path d="M62 74 l-8 8 l6 1 l-5 8 l11 -10 l-6 -1 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      ${claw(50, 107)}${claw(70, 107)}
    </g>
    <g class="head-tilt">
      <path d="M46 44 l-4 -12 l8 6 Z M74 44 l4 -12 l-8 6 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M44 52 Q44 36 60 36 Q76 36 76 52 Q76 64 60 66 Q44 64 44 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 40 l-6 6 l4 1 l-3 6 l8 -8 l-4 -1 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="0.9" stroke-linejoin="round"/>
      <path d="M48 58 Q60 66 72 58 Q60 62 48 58 Z" fill="${c.shade}" opacity=".6"/>
      ${eyes(53, 67, 52, 3.4, eyeInk(c))}
    </g>`; },

  // ── Void Wyrm (t5, dark + stars, float) — flowing dark serpent flecked with stars, nebula belly, cosmic eyes
  voidwyrm: (c) => { const D = deepen(c.body, 0.35); const N = tint(c.body, 0.35); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      ${tube("M12 66 Q30 54 46 66 Q62 78 80 68 Q100 58 108 72", c.body, c.line, 13)}
      <path d="M12 66 q-6 -4 -6 -11 q7 4 11 1 Z" fill="${D}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${[[30, 60], [46, 65], [64, 72], [82, 66]].map(([x, y]) => `<path d="M${x} ${y - 1} l1 3 l3 1 l-3 1 l-1 3 l-1 -3 l-3 -1 l3 -1 Z" fill="${GLOW}"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M40 66 q-4 6 -2 12 M60 72 q-4 6 -2 12" fill="none" stroke="${N}" stroke-width="2" stroke-linecap="round" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M92 66 Q90 50 104 48 Q116 48 116 60 Q116 68 108 70 L118 74 Q114 80 104 76 Q92 74 92 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M98 52 l-3 -10 l7 5 Z M108 50 l3 -10 l-7 6 Z" fill="${D}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M100 44 l1 3 l3 1 l-3 1 l-1 3 l-1 -3 l-3 -1 l3 -1 Z" fill="${GLOW}"/>
      ${eye(106, 62, 3.4, GLOW)}<circle cx="106" cy="62" r="1.4" fill="${INK}"/>
    </g>`; },

  // ── Sun Dragon (t5, radiant) — front, blazing ray-mane halo, warm plated belly, flame-tipped wings, bright face
  sundragon: (c) => { const B = belly(c); const R = tint(c.body, 0.35); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">${[22, 45, 70, 90, 110, 135, 158].map((a) => { const r = a * Math.PI / 180; return `<path d="M60 52 l${(28 * Math.cos(r)).toFixed(1)} ${(28 * Math.sin(r) - 30).toFixed(1)} l6 6 Z" fill="${R}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`; }).join("")}</g>
    <g class="tail-wag">
      <path d="M56 74 Q28 58 16 66 Q28 70 32 78 Q22 82 28 92 Q46 80 58 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${mirror(`<path d="M56 74 Q28 58 16 66 Q28 70 32 78 Q22 82 28 92 Q46 80 58 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
    </g>
    <g class="breathe">
      <path d="M42 100 C38 74 46 66 60 66 C74 66 82 74 78 100 L70 108 L62 108 L60 100 L58 100 L50 108 L42 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M50 82 q10 6 20 0 M52 90 q8 5 16 0" fill="none" stroke="${R}" stroke-width="2" stroke-linecap="round" opacity=".7"/>
      ${claw(52, 107)}${claw(68, 107)}
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="48" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M48 40 l-4 -9 l8 5 Z M72 40 l4 -9 l-8 5 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M50 52 Q60 62 70 52 Q60 58 50 52 Z" fill="${c.shade}" opacity=".55"/>
      ${eyes(53, 67, 48, 3.4, eyeInk(c))}
      ${smile(60, 54, 2.6, eyeInk(c))}
    </g>`; },

  // ── Moon Dragon (t4, crescent) — slender night dragon, crescent-horns, star freckles, sleepy calm face, folded wing
  moondragon: (c) => { const B = belly(c); return `
    ${floorShadow(58, 111, 30)}
    <g class="tail-wag"><path d="M40 82 Q16 88 12 66 Q11 55 23 56 Q15 64 22 73 Q30 80 42 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M14 64 Q4 62 4 52 Q10 58 14 54 Q10 62 16 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    <g class="tail-wag"><path d="M60 56 Q40 30 20 34 Q34 42 36 54 Q24 50 18 60 Q40 60 56 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 56 Q38 38 24 36" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/></g>
    <g class="breathe">
      ${sideBody(c)}
      ${ridge([48, 60, 70], 55, 7, c.shade, c.line)}
      <path d="M50 84 Q66 92 84 84 Q68 88 50 84 Z" fill="${B}" opacity=".85"/>
      <circle cx="56" cy="80" r="1.1" fill="${tint(c.body, 0.5)}"/><circle cx="66" cy="84" r="1.1" fill="${tint(c.body, 0.5)}"/><circle cx="74" cy="80" r="1" fill="${tint(c.body, 0.5)}"/>
      ${claw(44, 103)}${claw(68, 103)}
      <path d="M88 55 Q82 40 92 36 Q90 44 92 50 Q90 55 88 55 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M97 55 Q91 40 101 36 Q99 44 101 50 Q99 55 97 55 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="105" cy="61" rx="1.3" ry="1" fill="${INK}"/>
      <g class="blink"><path d="M87 63 q4 4 8 0" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/></g>
      <circle cx="100" cy="52" r="1" fill="${GLOW}"/>
    </g>`; },

  // ── Ancient Wyrm (t6, grand horned, float) — flagship: majestic front dragon, massive ram horns, flowing beard, grand wings
  ancientwyrm: (c) => { const B = belly(c); const D = deepen(c.body, 0.15); return `
    ${floorShadow(60, 113, 34)}
    <g class="tail-wag">
      <path d="M56 66 Q22 40 8 50 Q24 54 28 64 Q12 62 6 74 Q26 74 40 68 Q22 80 18 96 Q46 78 58 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M50 64 Q28 46 14 52 M48 68 Q30 60 16 66" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
      ${mirror(`<path d="M56 66 Q22 40 8 50 Q24 54 28 64 Q12 62 6 74 Q26 74 40 68 Q22 80 18 96 Q46 78 58 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M50 64 Q28 46 14 52 M48 68 Q30 60 16 66" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>`)}
    </g>
    <g class="breathe">
      <path d="M38 102 C32 68 44 60 60 60 C76 60 88 68 82 102 L74 110 L64 110 L62 102 L58 102 L56 110 L46 110 L38 102 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 72 Q76 76 74 100 Q68 106 60 106 Q52 106 46 100 Q44 76 60 72 Z" fill="${B}" opacity=".85"/>
      <path d="M50 82 h20 M50 89 h20 M52 96 h16" stroke="${c.line}" stroke-width="1" opacity=".45"/>
      ${ridge([52, 60, 68], 62, 8, D, c.line)}
      ${claw(50, 109)}${claw(70, 109)}
    </g>
    <g class="head-tilt">
      <path d="M44 40 Q30 34 30 20 Q26 34 34 46 Q40 52 46 50 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M76 40 Q90 34 90 20 Q94 34 86 46 Q80 52 74 50 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M44 48 Q44 30 60 30 Q76 30 76 48 Q76 60 68 64 L74 74 Q60 78 46 74 L52 64 Q44 60 44 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M52 64 Q60 82 68 64 Q60 70 52 64 Z" fill="${D}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M56 68 l1.6 5 l1.6 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/><path d="M62 68 l1.6 5 l1.6 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>
      <path d="M46 42 q6 -3 11 0 M63 42 q6 -3 11 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" opacity=".6"/>
      ${eyes(53, 67, 50, 3.6, eyeInk(c))}
    </g>`; },
};

export const ROSTER_DRAGONS = [
  { n: "Fire Drake",     e: "🐲", tier: 4, float: false },
  { n: "Ice Wyrm",       e: "🐉", tier: 4, float: false },
  { n: "Storm Dragon",   e: "🐉", tier: 4, float: true },
  { n: "Sea Dragon",     e: "🐉", tier: 4, float: false },
  { n: "Forest Dragon",  e: "🐉", tier: 3, float: false },
  { n: "Desert Wyrm",    e: "🐉", tier: 3, float: false },
  { n: "Shadow Dragon",  e: "🐉", tier: 5, float: false },
  { n: "Crystal Dragon", e: "🐉", tier: 5, float: false },
  { n: "Bronze Dragon",  e: "🐉", tier: 4, float: false },
  { n: "Faerie Dragon",  e: "🐲", tier: 3, float: true },
  { n: "Cave Drake",     e: "🐲", tier: 3, float: false },
  { n: "Bog Dragon",     e: "🐉", tier: 3, float: false },
  { n: "Sky Serpent",    e: "🐉", tier: 4, float: true },
  { n: "Ember Wyrm",     e: "🐲", tier: 3, float: false },
  { n: "Frost Drake",    e: "🐲", tier: 4, float: false },
  { n: "Thunder Dragon", e: "🐉", tier: 4, float: true },
  { n: "Void Wyrm",      e: "🐉", tier: 5, float: true },
  { n: "Sun Dragon",     e: "🐉", tier: 5, float: false },
  { n: "Moon Dragon",    e: "🐉", tier: 4, float: false },
  { n: "Ancient Wyrm",   e: "🐲", tier: 6, float: true },
];
