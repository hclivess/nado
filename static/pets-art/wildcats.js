// pets-art/wildcats.js — BESPOKE hand-drawn SVG art for WILD CATS & CANINES (NADO Pets).
// Each entry: slug -> (c, v) => "<svg inner markup>" for viewBox 0 0 120 120, animal centered ~ (60,62),
// within x,y ∈ [8,112]. Palette-driven: c.body (main fill) · c.shade (underside/spots/patches) · c.line
// (outline). Real hues are NOT hardcoded (the same drawing serves many coats); only fixed accents (black
// ear-tufts/mask via INK, white teeth #fff, glowing panther eyes) stay constant. Animate: torso .breathe,
// head .head-tilt, tails/ears .tail-wag. Keys are name-slugs matching every ROSTER_WILDCATS `n` slugified.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

const TOOTH = "#ffffff", TONGUE = "#e8788a";

export const ART_WILDCATS = {
  // ── Jaguar — robust powerful cat, broad head, dense rosettes each with a CENTRAL spot (tier 4) ──
  jaguar: (c) => {
    const rose = (x, y, r) => `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="${c.shade}" stroke-width="1.7"/><circle cx="${x}" cy="${y}" r="${(r * 0.28).toFixed(1)}" fill="${c.shade}"/><circle cx="${(x - r * 0.5).toFixed(1)}" cy="${(y + r * 0.4).toFixed(1)}" r="1" fill="${c.shade}"/>`;
    return `
    <g class="tail-wag"><path d="M84 92 Q112 92 112 66 Q112 58 105 60 Q108 74 96 84 Q88 90 80 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
      ${rose(103, 68, 3.2)}${rose(99, 79, 3)}</g>
    <g class="breathe"><ellipse cx="58" cy="84" rx="29" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M38 90 q20 12 40 0" fill="${c.shade}" opacity=".55"/>
      ${rose(44, 80, 3.6)}${rose(57, 78, 3.8)}${rose(70, 81, 3.6)}${rose(50, 89, 3.2)}${rose(64, 90, 3.2)}${rose(76, 86, 3)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 42}" y="92" width="11" height="17" rx="4.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M44 34 Q40 24 50 26 Q54 32 52 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="31" r="2.4" fill="${c.shade}"/>`)}
      <path d="M44 34 Q40 24 50 26 Q54 32 52 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="31" r="2.4" fill="${c.shade}"/>
      <ellipse cx="60" cy="52" rx="25" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M45 54 Q60 72 75 54 Q75 64 60 67 Q45 64 45 54 Z" fill="${c.shade}"/>
      ${rose(49, 45, 2.4)}${rose(71, 45, 2.4)}${rose(60, 39, 2.3)}
      <path d="M60 54 L54 61 L66 61 Z" fill="${INK}"/><path d="M60 61 v4" stroke="${c.line}" stroke-width="1.5"/>
      <g stroke="${c.line}" stroke-width="1" opacity=".6"><path d="M54 60 l-9 1 M54 63 l-8 3 M66 60 l9 1 M66 63 l8 3"/></g>
      ${eyes(51, 69, 48, 3, eyeInk(c))}
    </g>`;
  },

  // ── Cougar / mountain lion — plain tawny, NO spots, small round head, long body & tail (tier 3) ──
  cougar: (c) => `
    <g class="tail-wag"><path d="M84 90 Q112 92 114 62 Q114 54 107 56 Q110 72 97 82 Q88 88 80 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
      <path d="M108 58 Q114 60 112 68" fill="none" stroke="${INK}" stroke-width="3" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="58" cy="86" rx="27" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M40 92 q18 11 36 0" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 42}" y="93" width="11" height="17" rx="4.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M46 38 Q42 28 52 30 Q56 36 54 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M48 33 Q45 37 47 40 Z" fill="${INK}" opacity=".5"/>`)}
      <path d="M46 38 Q42 28 52 30 Q56 36 54 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M48 33 Q45 37 47 40 Z" fill="${INK}" opacity=".5"/>
      <ellipse cx="60" cy="54" rx="20" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M50 58 Q60 70 70 58 Q70 66 60 68 Q50 66 50 58 Z" fill="${c.shade}"/>
      <path d="M53 50 Q54 58 58 60 M67 50 Q66 58 62 60" stroke="${INK}" stroke-width="1.8" fill="none" stroke-linecap="round" opacity=".55"/>
      <path d="M60 56 L55 61 L65 61 Z" fill="${INK}"/><path d="M60 61 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(52, 68, 50, 2.9, eyeInk(c))}
    </g>`,

  // ── Lynx — long black EAR TUFTS, flaring cheek ruff (mutton chops), stubby tail, spotted flanks (tier 2) ──
  lynx: (c) => {
    const spot = (x, y) => `<circle cx="${x}" cy="${y}" r="2" fill="${c.shade}"/>`;
    return `
    <g class="tail-wag"><path d="M80 82 Q94 80 94 70 Q94 64 88 66 Q90 74 82 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M86 66 Q92 66 92 71" fill="none" stroke="${INK}" stroke-width="3.4" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="58" cy="84" rx="25" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${spot(46, 82)}${spot(56, 80)}${spot(66, 83)}${spot(52, 88)}${spot(63, 88)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 63 : 44}" y="92" width="10" height="16" rx="4.4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M45 32 Q43 20 52 24 Q54 30 54 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M49 21 l-1 -10 l5 9 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`)}
      <path d="M45 32 Q43 20 52 24 Q54 30 54 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M49 21 l-1 -10 l5 9 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="52" rx="20" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 52 Q33 61 40 67 Q46 60 48 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${mirror(`<path d="M40 52 Q33 61 40 67 Q46 60 48 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`)}
      <path d="M48 56 Q60 70 72 56 Q72 64 60 66 Q48 64 48 56 Z" fill="${c.shade}"/>
      <path d="M60 55 L55 60 L65 60 Z" fill="${INK}"/><path d="M60 60 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(52, 68, 49, 2.8, eyeInk(c))}
    </g>`;
  },

  // ── Bobcat — smaller cousin, SHORT ear tufts, stubby black-tipped bobtail, cheek ruff, spots (tier 2) ──
  bobcat: (c) => {
    const spot = (x, y) => `<circle cx="${x}" cy="${y}" r="1.9" fill="${c.shade}"/>`;
    return `
    <g class="tail-wag"><path d="M82 80 Q92 80 92 72 Q92 68 87 69 Q88 74 82 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M87 69 l2 -3 l1 4 Z" fill="${INK}"/></g>
    <g class="breathe"><ellipse cx="58" cy="85" rx="24" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${spot(46, 82)}${spot(55, 80)}${spot(65, 82)}${spot(50, 88)}${spot(61, 89)}${spot(71, 85)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 63 : 44}" y="93" width="10" height="15" rx="4.2" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M46 34 Q44 24 53 27 Q55 32 54 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M49 26 l-1 -6 l4 6 Z" fill="${INK}"/>`)}
      <path d="M46 34 Q44 24 53 27 Q55 32 54 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M49 26 l-1 -6 l4 6 Z" fill="${INK}"/>
      <ellipse cx="60" cy="54" rx="20" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M41 54 Q35 61 41 66 Q46 60 47 57 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      ${mirror(`<path d="M41 54 Q35 61 41 66 Q46 60 47 57 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>`)}
      ${spot(50, 47)}${spot(70, 47)}
      <path d="M49 58 Q60 70 71 58 Q71 65 60 67 Q49 65 49 58 Z" fill="${c.shade}"/>
      <path d="M60 56 L55 61 L65 61 Z" fill="${INK}"/><path d="M60 61 v3.5" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(52, 68, 51, 2.8, eyeInk(c))}
    </g>`;
  },

  // ── Ocelot — CHAIN-like open rosettes & elongated streaks (not round dots), cheek stripes (tier 3) ──
  ocelot: (c) => {
    const streak = (x, y, l) => `<path d="M${x} ${y} q${l} -1 ${l + 2} 4" fill="none" stroke="${c.shade}" stroke-width="2" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag"><path d="M82 88 Q108 90 110 64 Q110 56 104 58 Q106 72 95 82 Q87 88 79 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
      <g stroke="${c.shade}" stroke-width="2.2"><path d="M99 66 h5 M96 74 h5 M92 81 h4"/></g></g>
    <g class="breathe"><ellipse cx="58" cy="85" rx="26" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${streak(42, 78, 6)}${streak(55, 76, 7)}${streak(68, 79, 6)}${streak(46, 86, 6)}${streak(60, 87, 6)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 63 : 43}" y="92" width="10" height="16" rx="4.2" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M45 34 Q41 24 51 26 Q55 32 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="31" r="2" fill="${c.shade}"/>`)}
      <path d="M45 34 Q41 24 51 26 Q55 32 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="31" r="2" fill="${c.shade}"/>
      <ellipse cx="60" cy="53" rx="20" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 55 Q60 68 72 55 Q72 64 60 66 Q48 64 48 55 Z" fill="${c.shade}"/>
      <g stroke="${c.shade}" stroke-width="1.8" fill="none" stroke-linecap="round"><path d="M50 44 q4 -2 6 2 M70 44 q-4 -2 -6 2 M60 38 v4"/></g>
      <path d="M60 55 L55 60 L65 60 Z" fill="${INK}"/><path d="M60 60 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(52, 68, 49, 2.8, eyeInk(c))}
    </g>`;
  },

  // ── Caracal — very LONG black EAR TUFTS, sleek uniform coat, slender, dark eye-lines (tier 3) ──
  caracal: (c) => `
    <g class="tail-wag"><path d="M82 84 Q98 82 98 66 Q98 60 92 62 Q94 74 84 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="58" cy="85" rx="24" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 90 q16 10 32 0" fill="${c.shade}" opacity=".6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 63 : 44}" y="93" width="9" height="16" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M46 34 Q44 26 52 28 Q54 33 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M49 28 l-3 -17 l7 15 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`)}
      <path d="M46 34 Q44 26 52 28 Q54 33 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M49 28 l-3 -17 l7 15 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="54" rx="18" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 57 Q60 68 70 57 Q70 64 60 66 Q50 64 50 57 Z" fill="${c.shade}"/>
      <path d="M53 48 Q55 44 58 46 M67 48 Q65 44 62 46" stroke="${INK}" stroke-width="1.8" fill="none" stroke-linecap="round" opacity=".7"/>
      <path d="M60 56 L56 60 L64 60 Z" fill="${INK}"/><path d="M60 60 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(53, 67, 50, 2.8, eyeInk(c))}
    </g>`,

  // ── Serval — HUGE oval ears (black-backed), very long legs, slim black-spotted body (tier 3) ──
  serval: (c) => {
    const spot = (x, y, r = 2) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${INK}"/>`;
    return `
    <g class="tail-wag"><path d="M80 78 Q96 76 96 60 Q96 54 90 56 Q92 68 82 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <g stroke="${INK}" stroke-width="2"><path d="M89 60 h4 M86 68 h4"/></g></g>
    <g class="breathe"><ellipse cx="58" cy="78" rx="23" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${spot(46, 74)}${spot(56, 72)}${spot(66, 75)}${spot(51, 80)}${spot(62, 81)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 46}" y="86" width="8" height="24" rx="3.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <g stroke="${INK}" stroke-width="1.6"><path d="M49 96 h5 M65 96 h5"/></g></g>
    <g class="head-tilt">
      ${mirror(`<path d="M44 34 Q34 20 46 18 Q54 24 54 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M46 24 Q42 27 45 33 L48 32 Z" fill="${INK}"/><path d="M45 21 q6 0 8 4" fill="none" stroke="${INK}" stroke-width="1.6"/>`)}
      <path d="M44 34 Q34 20 46 18 Q54 24 54 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M46 24 Q42 27 45 33 L48 32 Z" fill="${INK}"/><path d="M45 21 q6 0 8 4" fill="none" stroke="${INK}" stroke-width="1.6"/>
      <ellipse cx="60" cy="52" rx="16" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M51 55 Q60 65 69 55 Q69 62 60 64 Q51 62 51 55 Z" fill="${c.shade}"/>
      ${spot(53, 46, 1.6)}${spot(67, 46, 1.6)}
      <path d="M60 54 L56 58 L64 58 Z" fill="${INK}"/><path d="M60 58 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(53, 67, 49, 2.6, eyeInk(c))}
    </g>`;
  },

  // ── Snow Leopard — thick FLUFFY coat, big pale rosettes, enormous plush tail, small ears (tier 4) ──
  snowleopard: (c) => {
    const rose = (x, y, r) => `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="${c.shade}" stroke-width="1.8"/><circle cx="${x}" cy="${y}" r="${(r * 0.3).toFixed(1)}" fill="${c.shade}"/>`;
    return `
    <g class="tail-wag"><path d="M78 88 Q106 96 112 68 Q116 52 104 48 Q108 62 100 74 Q92 84 76 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${rose(105, 58, 3)}${rose(104, 70, 3)}${rose(96, 80, 2.8)}</g>
    <g class="breathe"><ellipse cx="56" cy="84" rx="27" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M36 90 q20 12 40 0" fill="${c.shade}" opacity=".4"/>
      ${rose(44, 80, 3.6)}${rose(57, 78, 3.8)}${rose(69, 81, 3.6)}${rose(50, 89, 3.2)}${rose(63, 90, 3.2)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 42}" y="92" width="11" height="17" rx="4.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M46 36 Q44 27 52 29 Q55 34 53 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="48" cy="33" r="2" fill="${c.shade}"/>`)}
      <path d="M46 36 Q44 27 52 29 Q55 34 53 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="48" cy="33" r="2" fill="${c.shade}"/>
      ${pom(60, 54, 21, c.body, c.line, 13, 2.4)}
      <path d="M47 56 Q60 72 73 56 Q73 66 60 69 Q47 66 47 56 Z" fill="${c.shade}"/>
      ${rose(50, 46, 2.4)}${rose(70, 46, 2.4)}${rose(60, 40, 2.2)}
      <path d="M60 56 L55 62 L65 62 Z" fill="${INK}"/><path d="M60 62 v4" stroke="${c.line}" stroke-width="1.5"/>
      ${eyes(51, 69, 50, 3, eyeInk(c))}
    </g>`;
  },

  // ── Black Panther — sleek melanistic cat, faint GHOST rosettes, glowing slit-pupil eyes (tier 4) ──
  blackpanther: (c) => {
    const ghost = (x, y, r) => `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>`;
    const GLOW = "#c8f065";
    return `
    <g class="tail-wag"><path d="M84 88 Q114 90 116 60 Q116 52 108 54 Q111 72 98 82 Q89 88 80 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="58" cy="84" rx="28" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      ${ghost(46, 80, 4)}${ghost(58, 78, 4)}${ghost(70, 81, 4)}${ghost(52, 88, 3.4)}${ghost(65, 89, 3.4)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 42}" y="92" width="11" height="17" rx="4.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M45 34 Q41 25 51 27 Q55 32 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M45 34 Q41 25 51 27 Q55 32 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="60" cy="53" rx="21" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M48 56 Q60 70 72 56 Q72 65 60 68 Q48 65 48 56 Z" fill="${c.shade}" opacity=".6"/>
      <path d="M60 55 L55 61 L65 61 Z" fill="${INK}"/><path d="M60 61 v4" stroke="${c.line}" stroke-width="1.4"/>
      <g class="blink"><path d="M50 49 q4 -4 8 0 q-4 4 -8 0 Z" fill="${GLOW}"/><path d="M62 49 q4 -4 8 0 q-4 4 -8 0 Z" fill="${GLOW}"/>
        <ellipse cx="54" cy="49" rx="1.2" ry="2.6" fill="${INK}"/><ellipse cx="66" cy="49" rx="1.2" ry="2.6" fill="${INK}"/></g>
    </g>`;
  },

  // ── Coyote — slender canine, big pointed ears, narrow snout, low bushy tail (tier 2) ──
  coyote: (c) => `
    <g class="tail-wag"><path d="M30 92 C10 96 8 72 24 64 C28 74 30 84 40 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M18 78 q4 8 12 8" fill="none" stroke="${INK}" stroke-width="3" stroke-linecap="round" opacity=".5"/></g>
    <g class="breathe"><path d="M38 96 Q38 70 60 68 Q82 70 82 96 Q60 104 38 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M48 92 q12 8 24 0" fill="${c.shade}" opacity=".6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 47}" y="94" width="8" height="16" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M45 54 L41 22 L57 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M47 42 L45 28 L54 40 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M45 54 L41 22 L57 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M47 42 L45 28 L54 40 Z" fill="${c.shade}"/>`)}
      <path d="M42 54 Q42 74 60 76 Q78 74 78 54 Q60 46 42 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 60 Q60 78 66 60 Q64 82 60 82 Q56 82 54 60 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="74" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M60 76 l-7 5 M60 76 l7 5" stroke="${INK}" stroke-width="1.4"/>
      ${eyes(51, 69, 58, 2.8, eyeInk(c))}
    </g>`,

  // ── Jackal — slim, very erect pointed ears, black saddle patch across the back (tier 2) ──
  jackal: (c) => `
    <g class="tail-wag"><path d="M30 90 C12 92 10 72 24 66 C28 74 30 82 40 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe"><path d="M40 96 Q40 70 60 68 Q80 70 80 96 Q60 103 40 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M44 72 Q60 62 76 72 Q72 86 60 86 Q48 86 44 72 Z" fill="${INK}" opacity=".82"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 65 : 47}" y="94" width="8" height="15" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M46 54 L44 12 L58 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 42 L47 26 L55 40 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M46 54 L44 12 L58 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 42 L47 26 L55 40 Z" fill="${c.shade}"/>`)}
      <path d="M44 54 Q46 70 60 76 Q74 70 76 54 Q60 46 44 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M53 60 Q60 76 67 60 Q65 80 60 80 Q55 80 53 60 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="72" rx="2.6" ry="2" fill="${INK}"/>
      <path d="M60 74 l-6 5 M60 74 l6 5" stroke="${INK}" stroke-width="1.3"/>
      ${eyes(51, 69, 57, 2.6, eyeInk(c))}
    </g>`,

  // ── Dingo — lean athletic dog, pricked ears, bushy tail, pale socks & muzzle (tier 2) ──
  dingo: (c) => `
    <g class="tail-wag"><path d="M30 88 C14 88 10 68 26 62 C30 70 30 80 40 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M22 66 C16 74 18 82 28 84" stroke="${c.shade}" stroke-width="2.6" fill="none" opacity=".7"/></g>
    <g class="breathe"><path d="M40 96 Q40 68 60 66 Q80 68 80 96 Q60 103 40 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M48 90 q12 9 24 0" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<g><rect x="${i ? 65 : 47}" y="94" width="8" height="15" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><rect x="${i ? 65 : 47}" y="104" width="8" height="5" rx="2.4" fill="${c.shade}"/></g>`).join("")}</g>
    <g class="head-tilt">
      <path d="M46 44 L43 22 L58 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 40 L47 28 L54 37 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M46 44 L43 22 L58 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 40 L47 28 L54 37 Z" fill="${c.shade}"/>`)}
      <path d="M43 52 Q43 72 60 76 Q77 72 77 52 Q60 44 43 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 58 Q52 76 60 78 Q68 76 68 58 Q60 52 52 58 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="72" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M60 74 l-6 5 M60 74 l6 5" stroke="${INK}" stroke-width="1.3"/>
      ${eyes(51, 69, 57, 2.7, eyeInk(c))}
    </g>`,

  // ── Hyena — LAUGHING open grin (teeth + tongue), sloping back, spiky nape mane, round ears, spots (tier 3) ──
  hyena: (c) => {
    const spot = (x, y) => `<circle cx="${x}" cy="${y}" r="2.2" fill="${INK}"/>`;
    return `
    <g class="tail-wag"><path d="M84 94 Q100 92 98 78 Q96 72 90 74 Q94 82 84 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M92 74 q4 4 3 9" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M36 66 Q40 92 62 94 Q86 96 84 80 Q70 88 56 84 Q42 80 42 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="56" cy="82" rx="25" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      ${spot(46, 80)}${spot(57, 78)}${spot(68, 82)}${spot(50, 88)}${spot(62, 88)}${spot(72, 83)}
      <g stroke="${INK}" stroke-width="3" stroke-linecap="round"><path d="M40 66 q2 -6 8 -7 M44 62 q2 -5 7 -6 M48 60 q2 -4 7 -5"/></g>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 44}" y="90" width="9" height="18" rx="3.8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<ellipse cx="46" cy="34" rx="7.5" ry="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><ellipse cx="46" cy="34" rx="3.4" ry="4" fill="${c.shade}"/>`)}
      <ellipse cx="46" cy="34" rx="7.5" ry="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><ellipse cx="46" cy="34" rx="3.4" ry="4" fill="${c.shade}"/>
      <path d="M42 48 Q42 60 50 64 Q46 70 52 74 Q60 78 68 74 Q74 70 70 64 Q78 60 78 48 Q60 40 42 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 64 Q60 62 70 64 Q68 76 60 78 Q52 76 50 64 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M52 65 l2.5 4 l2.5 -4 l2.5 4 l2.5 -4 l2.5 4 l2.5 -4" fill="none" stroke="${TOOTH}" stroke-width="1.5"/>
      <path d="M56 73 q4 4 8 0 q-2 4 -4 4 q-2 0 -4 -4 Z" fill="${TONGUE}"/>
      <ellipse cx="60" cy="56" rx="3.4" ry="2.6" fill="${INK}"/>
      ${eyes(51, 69, 50, 2.8, eyeInk(c))}
    </g>`;
  },

  // ── Fennec Fox — ENORMOUS ears (taller than the body), tiny face, dainty body (tier 3) ──
  fennecfox: (c) => `
    <g class="tail-wag"><path d="M40 96 C22 98 20 78 34 72 C38 80 40 88 48 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M34 74 l-2 -4 l4 2 Z" fill="${INK}"/></g>
    <g class="breathe"><ellipse cx="60" cy="90" rx="19" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 94 q12 7 24 0" fill="${c.shade}" opacity=".8"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 50}" y="97" width="7" height="12" rx="3.2" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <g class="tail-wag">
        <path d="M50 56 Q30 44 26 14 Q46 22 56 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
        <path d="M48 52 Q34 42 31 22 Q44 30 52 48 Z" fill="${c.shade}"/>
        ${mirror(`<path d="M50 56 Q30 44 26 14 Q46 22 56 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M48 52 Q34 42 31 22 Q44 30 52 48 Z" fill="${c.shade}"/>`)}
      </g>
      <ellipse cx="60" cy="62" rx="18" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 66 Q60 78 70 66 Q68 74 60 76 Q52 74 50 66 Z" fill="${c.shade}"/>
      <path d="M60 66 l-6 4 M60 66 l6 4" stroke="${INK}" stroke-width="1.4"/>
      <ellipse cx="60" cy="65" rx="2.6" ry="2" fill="${INK}"/>
      ${eyes(52, 68, 58, 3, eyeInk(c))}
    </g>`,

  // ── Arctic Fox — plush round fluff-ball, small ears, thick coat, huge bushy tail (tier 2) ──
  arcticfox: (c) => `
    <g class="tail-wag">${pom(30, 80, 15, c.body, c.line, 9, 2.4)}
      ${pom(30, 80, 8, c.shade, c.line, 7, 1.4)}</g>
    <g class="breathe">${pom(60, 86, 22, c.body, c.line, 12, 2.5)}
      <path d="M46 92 q14 9 28 0" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 48}" y="96" width="8" height="13" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M48 44 Q46 34 54 36 Q56 42 56 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <path d="M48 44 Q46 34 54 36 Q56 42 56 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${pom(60, 58, 19, c.body, c.line, 12, 2.4)}
      <path d="M50 62 Q60 74 70 62 Q68 70 60 72 Q52 70 50 62 Z" fill="${c.shade}"/>
      <path d="M60 62 l-5 4 M60 62 l5 4" stroke="${INK}" stroke-width="1.3"/>
      <ellipse cx="60" cy="61" rx="2.4" ry="1.9" fill="${INK}"/>
      ${eyes(52, 68, 54, 2.8, eyeInk(c))}
    </g>`,

  // ── Dhole — Asian wild dog, rounded bell ears, athletic body, dark bushy tail-tip (tier 3) ──
  dhole: (c) => `
    <g class="tail-wag"><path d="M30 92 C12 94 10 72 26 66 C30 74 30 84 40 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M26 66 C18 74 18 84 30 88 Q24 78 26 66 Z" fill="${INK}" opacity=".7"/></g>
    <g class="breathe"><path d="M40 96 Q40 70 60 68 Q80 70 80 96 Q60 103 40 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M48 90 q12 9 24 0" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 65 : 47}" y="94" width="8" height="15" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M46 40 Q42 28 54 30 Q56 38 54 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 33 Q46 37 49 41 Z" fill="${c.shade}"/>`)}
      <path d="M46 40 Q42 28 54 30 Q56 38 54 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 33 Q46 37 49 41 Z" fill="${c.shade}"/>
      <path d="M44 54 Q44 74 60 78 Q76 74 76 54 Q60 46 44 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M53 60 Q60 78 67 60 Q65 82 60 82 Q55 82 53 60 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="74" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M60 76 l-6 5 M60 76 l6 5" stroke="${INK}" stroke-width="1.4"/>
      ${eyes(51, 69, 58, 2.7, eyeInk(c))}
    </g>`,

  // ── Maned Wolf — unmistakable stilt-like LONG BLACK LEGS, red coat, big ears, black nape mane (tier 4) ──
  manedwolf: (c) => `
    <g class="tail-wag"><path d="M34 78 C18 78 16 62 28 58 Q30 66 40 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M28 58 q-4 8 2 12" fill="none" stroke="${TOOTH}" stroke-width="3" stroke-linecap="round" opacity=".85"/></g>
    <g stroke="${INK}" stroke-width="7" stroke-linecap="round"><path d="M48 76 V106 M72 76 V106"/></g>
    <g class="breathe">
      <ellipse cx="60" cy="66" rx="24" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M42 56 Q60 48 78 56 Q76 66 60 66 Q44 66 42 56 Z" fill="${INK}" opacity=".78"/>
    </g>
    <g class="head-tilt">
      <path d="M46 44 L42 18 L58 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 40 L46 24 L55 37 Z" fill="${INK}" opacity=".7"/>
      ${mirror(`<path d="M46 44 L42 18 L58 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M48 40 L46 24 L55 37 Z" fill="${INK}" opacity=".7"/>`)}
      <path d="M44 50 Q44 68 60 72 Q76 68 76 50 Q60 42 44 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M53 56 Q60 72 67 56 Q65 76 60 76 Q55 76 53 56 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="68" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M60 70 l-6 5 M60 70 l6 5" stroke="${INK}" stroke-width="1.4"/>
      ${eyes(51, 69, 54, 2.7, eyeInk(c))}
    </g>`,

  // ── African Wild Dog — huge ROUND satellite ears, mottled patchwork blotches, white tail-tip (tier 3) ──
  africanwilddog: (c) => {
    const blot = (x, y, r, f) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${f}"/>`;
    return `
    <g class="tail-wag"><path d="M30 90 C14 92 12 72 26 66 C30 74 30 84 40 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M22 70 q-4 8 4 14" fill="none" stroke="${TOOTH}" stroke-width="4" stroke-linecap="round" opacity=".9"/></g>
    <g class="breathe"><path d="M40 96 Q40 70 60 68 Q80 70 80 96 Q60 103 40 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${blot(50, 80, 5, INK)}${blot(70, 82, 5, c.shade)}${blot(60, 90, 5, INK)}${blot(46, 90, 3.4, c.shade)}${blot(74, 90, 3, INK)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 65 : 47}" y="94" width="8" height="15" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<ellipse cx="42" cy="36" rx="9" ry="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><ellipse cx="42" cy="36" rx="4.5" ry="6" fill="${INK}"/>`)}
      <ellipse cx="42" cy="36" rx="9" ry="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><ellipse cx="42" cy="36" rx="4.5" ry="6" fill="${INK}"/>
      <path d="M44 52 Q44 72 60 76 Q76 72 76 52 Q60 44 44 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 46 Q60 40 70 46 Q72 56 60 58 Q48 56 50 46 Z" fill="${INK}" opacity=".78"/>
      <path d="M53 60 Q60 76 67 60 Q65 80 60 80 Q55 80 53 60 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="72" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M60 74 l-6 5 M60 74 l6 5" stroke="${INK}" stroke-width="1.4"/>
      ${eyes(51, 69, 56, 2.7, eyeInk(c))}
    </g>`;
  },

  // ── Fossa — Madagascar cat-like carnivore, small round head, low slinky body, VERY long thick tail (tier 4) ──
  fossa: (c) => `
    <g class="tail-wag"><path d="M80 84 Q112 84 112 56 Q112 40 98 42 Q108 50 104 64 Q100 78 80 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="54" cy="82" rx="26" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 86 q18 9 36 0" fill="${c.shade}" opacity=".6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 60 : 40}" y="88" width="8" height="21" rx="3.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<circle cx="48" cy="40" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="48" cy="40" r="2.8" fill="${c.shade}"/>`)}
      <circle cx="48" cy="40" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="48" cy="40" r="2.8" fill="${c.shade}"/>
      <ellipse cx="60" cy="56" rx="16" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M51 59 Q60 70 69 59 Q69 66 60 68 Q51 66 51 59 Z" fill="${c.shade}"/>
      <path d="M55 52 Q54 56 57 58 M65 52 Q66 56 63 58" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round" opacity=".55"/>
      <path d="M60 58 L56 62 L64 62 Z" fill="${INK}"/><path d="M60 62 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(53, 67, 52, 2.7, eyeInk(c))}
    </g>`,

  // ── Wolverine — stocky low mustelid, pale lateral flank stripe, dark stubby legs, small ears (tier 3) ──
  wolverine: (c) => `
    <g class="tail-wag"><path d="M30 84 C12 84 10 66 24 60 Q28 70 40 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M24 60 q-4 8 2 14" fill="none" stroke="${c.shade}" stroke-width="4" stroke-linecap="round" opacity=".6"/></g>
    <g class="breathe">
      <ellipse cx="58" cy="80" rx="30" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M32 74 Q58 62 86 76 Q80 84 58 82 Q40 82 32 74 Z" fill="${c.shade}"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 68 : 38}" y="90" width="11" height="18" rx="4.4" fill="${INK}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<circle cx="47" cy="46" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="47" cy="46" r="3" fill="${c.shade}"/>`)}
      <circle cx="47" cy="46" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="47" cy="46" r="3" fill="${c.shade}"/>
      <path d="M42 58 Q42 74 60 76 Q78 74 78 58 Q72 48 60 48 Q48 48 42 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M48 50 Q60 44 72 50 Q72 60 60 62 Q48 60 48 50 Z" fill="${INK}" opacity=".7"/>
      <path d="M50 64 Q60 74 70 64 Q66 72 60 72 Q54 72 50 64 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="63" rx="3.4" ry="2.6" fill="${INK}"/>
      <path d="M60 66 v4 M60 70 q-4 3 -7 1 M60 70 q4 3 7 1" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      ${eyes(51, 69, 54, 2.7, eyeInk(c))}
    </g>`,
};

export const ROSTER_WILDCATS = [
  { n: "Jaguar",            e: "🐆",  tier: 4, float: false },
  { n: "Cougar",            e: "🐆",  tier: 3, float: false },
  { n: "Lynx",              e: "🐈",  tier: 2, float: false },
  { n: "Bobcat",            e: "🐈",  tier: 2, float: false },
  { n: "Ocelot",            e: "🐆",  tier: 3, float: false },
  { n: "Caracal",           e: "🐈",  tier: 3, float: false },
  { n: "Serval",            e: "🐈",  tier: 3, float: false },
  { n: "Snow Leopard",      e: "🐆",  tier: 4, float: false },
  { n: "Black Panther",     e: "🐈‍⬛", tier: 4, float: false },
  { n: "Coyote",            e: "🐺",  tier: 2, float: false },
  { n: "Jackal",            e: "🐕",  tier: 2, float: false },
  { n: "Dingo",             e: "🐕",  tier: 2, float: false },
  { n: "Hyena",             e: "🐕",  tier: 3, float: false },
  { n: "Fennec Fox",        e: "🦊",  tier: 3, float: false },
  { n: "Arctic Fox",        e: "🦊",  tier: 2, float: false },
  { n: "Dhole",             e: "🐕",  tier: 3, float: false },
  { n: "Maned Wolf",        e: "🐺",  tier: 4, float: false },
  { n: "African Wild Dog",  e: "🐕",  tier: 3, float: false },
  { n: "Fossa",             e: "🐈",  tier: 4, float: false },
  { n: "Wolverine",         e: "🦡",  tier: 3, float: false },
];
