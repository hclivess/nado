// waterfowl.js — BESPOKE hand-drawn SVG art for WATERFOWL (ducks, geese, seabirds & waders, NADO Pets).
// Each entry is an original, on-spot drawing of ONE species — no shared/parameterized bodies.
// House style (METHOD): ONE continuous body silhouette (c.body + c.line), a pale two-tone belly (belly(c)) and
// a darker folded wing/back (c.shade), a clean cute face (big glossy eye), warm-accent bill + feet, and a
// ground/water shadow so it sits — nothing floats. All face RIGHT (head+bill on the right, tail on the left).
// Coat from `c`: c.body fill / c.shade accent / c.line outline; dark species marks derive via deepen(c.body,f)
// so they recolour at hatch. Bills & feet use fixed warm accents; bare-skin species marks (booby feet, loon
// eye, frigate pouch) use fixed non-coat colours.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const BEAK = "#f2a03b";    // orange duck bill / paddle bill
const BEAKD = "#d97b2c";   // lower-mandible / bill shading / hook
const DAGGER = "#f2c94c";  // yellow dagger / hooked seabird bill
const LEG = "#e79a3a";     // webbed feet / long wader legs (warm)
const LEGD = "#b06f22";    // web / foot outline
const BLUE = "#4f8fd0";    // blue-footed booby bare-skin feet
const RED = "#d8534b";     // frigatebird throat pouch / loon eye / accents
const WHT = "#fbf6ee";     // cheek / neck-ring / coot bill / eye-ring highlight (not coat)
const YEL = "#f4c84a";     // gannet golden nape / warm flash

// two faint ripple strokes where a floating water-bird meets the surface
const water = (cx, y, w) =>
  `<path d="M${cx - w} ${y} q${(w * 0.5).toFixed(0)} 4 ${w} 0 q${(w * 0.5).toFixed(0)} -4 ${w} 0" fill="none" stroke="${WHT}" stroke-width="1.4" opacity=".13" stroke-linecap="round"/>` +
  `<path d="M${cx - w + 6} ${y + 6} q${(w * 0.5).toFixed(0)} 3 ${w - 8} 0" fill="none" stroke="${WHT}" stroke-width="1.2" opacity=".1" stroke-linecap="round"/>`;
// webbed paddle feet under a short leg (facing right); col lets booby go blue
const webfeet = (xs, y, col = LEG) => xs.map((x) =>
  `<path d="M${x} ${y} l-8 6 q8 3 16 0 z" fill="${col}" stroke="${LEGD}" stroke-width="1.6" stroke-linejoin="round"/>` +
  `<line x1="${x}" y1="${y - 6}" x2="${x}" y2="${y}" stroke="${col}" stroke-width="2.8" stroke-linecap="round"/>`).join("");
// long slender wading legs with a soft knee-kink and splayed forward toes near y
const wlegs = (xs, top, y = 112) => xs.map((x) =>
  `<path d="M${x} ${top} Q${x - 3} ${((top + y) / 2).toFixed(1)} ${x} ${y - 6} Q${x + 1} ${y - 2} ${x} ${y}" stroke="${LEG}" stroke-width="2.4" fill="none" stroke-linecap="round"/>` +
  `<path d="M${x} ${y} l-6 4 M${x} ${y} l6 4 M${x} ${y} l-1 5" stroke="${LEG}" stroke-width="2" fill="none" stroke-linecap="round"/>`).join("");

export const ART_WATERFOWL = {
  // ── DABBLING & DIVING DUCKS (float on water: boat hull, head upper-right) ────────────────
  // Mallard — classic dabbler: glossy dark head, white neck-ring, flat orange bill, curled drake tail
  mallard: (c) => { const B = belly(c), D = deepen(c.body, 0.55); return `
    ${floorShadow(58, 101, 33)}
    ${water(58, 97, 34)}
    <g class="tail-wag">
      <path d="M30 78 Q14 74 18 85 Q27 84 35 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M27 76 q-5 -7 2 -9 q4 4 1 9 Z" fill="${D}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 84 Q30 67 56 67 Q83 67 91 82 Q85 95 56 95 Q31 95 26 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 85 Q56 93 84 85 Q77 91 56 92 Q40 91 40 85 Z" fill="${B}" opacity=".85"/>
      <path d="M46 73 Q68 69 84 80 Q71 87 52 84 Q44 79 46 73 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M58 78 h16" stroke="${WHT}" stroke-width="1.6" opacity=".65"/></g>
    <g class="head-tilt">
      ${tube("M80 74 Q84 63 84 55", c.body, c.line, 8)}
      <circle cx="86" cy="49" r="13" fill="${D}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M74 58 q12 4 24 0" stroke="${WHT}" stroke-width="2.6" fill="none"/>
      <path d="M96 46 L110 49 Q112 52 109 55 L96 54 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M96 53 L109 54 L96 55 Z" fill="${BEAKD}"/>
      ${eye(89, 46, 3, "#e9edf2")}
    </g>`; },

  // Wood Duck — ornate: long swept-back drooping crest off the nape, bold face teardrop, short bill
  woodduck: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(58, 101, 33)}
    ${water(58, 97, 34)}
    <g class="tail-wag"><path d="M30 78 Q15 76 18 87 Q27 85 36 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 84 Q30 67 56 67 Q83 67 91 82 Q85 95 56 95 Q31 95 26 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 85 Q56 93 84 85 Q77 91 56 92 Q40 91 40 85 Z" fill="${B}" opacity=".85"/>
      <path d="M46 73 Q68 69 84 80 Q71 87 52 84 Q44 79 46 73 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      ${tube("M79 74 Q83 63 84 55", c.body, c.line, 8)}
      <path d="M86 42 Q70 40 58 52 Q66 56 80 54 Q90 52 86 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <circle cx="86" cy="49" r="13" fill="${D}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M80 40 Q88 42 92 50" stroke="${WHT}" stroke-width="1.8" fill="none" opacity=".85"/>
      <path d="M82 52 q4 6 0 10" stroke="${WHT}" stroke-width="1.6" fill="none" opacity=".8"/>
      <path d="M97 47 L109 49 Q111 52 108 55 L97 54 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M105 48 q4 1 3 5 q-3 0 -4 -3 Z" fill="${RED}"/>
      ${eye(88, 46, 3, "#e9edf2")}
    </g>`; },

  // Mandarin Duck — flamboyant: two upright orange "sail" fins standing on the back, fluffy cheek ruff, short bill
  mandarinduck: (c) => { const B = belly(c), D = deepen(c.body, 0.4); return `
    ${floorShadow(58, 101, 33)}
    ${water(58, 97, 34)}
    <g class="tail-wag"><path d="M30 80 Q16 78 19 88 Q27 86 36 83 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 85 Q30 68 56 68 Q83 68 91 83 Q85 95 56 95 Q31 95 26 85 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 86 Q56 93 84 86 Q77 91 56 92 Q40 91 40 86 Z" fill="${B}" opacity=".85"/></g>
    <g class="tail-wag">
      <path d="M48 74 Q40 48 56 42 Q62 48 58 76 Z" fill="${tint(c.shade, 0.2)}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M58 76 Q54 46 72 48 Q76 60 68 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M50 66 q4 -8 4 -16 M62 66 q4 -8 6 -12" stroke="${c.line}" stroke-width="1" fill="none" opacity=".45"/></g>
    <g class="head-tilt">
      ${tube("M80 76 Q84 66 85 58", c.body, c.line, 8)}
      <circle cx="87" cy="50" r="12.5" fill="${D}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M77 55 Q72 66 81 68 Q88 65 86 55 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M79 40 Q87 40 93 46" stroke="${WHT}" stroke-width="2.4" fill="none" opacity=".9"/>
      <path d="M83 52 q5 3 4 9" stroke="${WHT}" stroke-width="1.8" fill="none" opacity=".75"/>
      <path d="M98 48 L110 50 Q112 53 109 56 L98 55 Z" fill="${RED}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(89, 47, 3, "#e9edf2")}
    </g>`; },

  // Teal — small compact dabbler: round head, short neat bill, bright speculum wing-patch flash
  teal: (c) => { const B = belly(c), D = deepen(c.body, 0.45); return `
    ${floorShadow(58, 100, 29)}
    ${water(58, 96, 30)}
    <g class="tail-wag"><path d="M34 78 Q22 76 25 85 Q32 84 40 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M32 83 Q36 69 56 69 Q80 69 86 81 Q81 92 56 92 Q37 92 32 83 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 84 Q56 90 80 84 Q74 89 56 90 Q44 89 44 84 Z" fill="${B}" opacity=".85"/>
      <path d="M48 74 Q66 71 80 79 Q69 85 54 83 Q47 79 48 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M60 76 q7 -1 12 3" stroke="${WHT}" stroke-width="2.4" fill="none" opacity=".8"/>
      <path d="M60 79 q7 -1 12 3" stroke="${D}" stroke-width="1.8" fill="none" opacity=".6"/></g>
    <g class="head-tilt">
      ${tube("M78 74 Q82 66 82 60", c.body, c.line, 7)}
      <circle cx="84" cy="55" r="11.5" fill="${D}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M79 49 Q86 55 82 63" stroke="${WHT}" stroke-width="1.6" fill="none" opacity=".65"/>
      <path d="M93 53 L106 55 Q108 58 105 60 L93 59 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(87, 52, 2.9, "#e9edf2")}
    </g>`; },

  // Merganser — fish-duck: shaggy double-spiked crest off the nape, THIN serrated saw-bill (not flat)
  merganser: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(58, 101, 32)}
    ${water(58, 97, 33)}
    <g class="tail-wag"><path d="M30 78 Q16 76 19 87 Q28 85 37 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M27 84 Q31 68 56 68 Q82 68 90 82 Q84 94 56 94 Q32 94 27 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 85 Q56 92 83 85 Q76 90 56 91 Q40 90 40 85 Z" fill="${B}" opacity=".85"/>
      <path d="M46 74 Q68 70 83 80 Q70 86 52 84 Q44 79 46 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      ${tube("M80 74 Q84 64 84 56", c.body, c.line, 8)}
      <path d="M84 40 Q72 42 68 50 Q78 50 84 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M88 40 Q79 44 76 52 M92 42 Q86 46 84 54" stroke="${c.shade}" stroke-width="3.4" fill="none" stroke-linecap="round"/>
      <circle cx="86" cy="50" r="12" fill="${D}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M97 48 Q112 49 112 52 Q112 55 97 54 Q94 51 97 48 Z" fill="${RED}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M99 51 h11" stroke="${BEAKD}" stroke-width="0.9" opacity=".7"/>
      ${eye(88, 47, 3, "#e9edf2")}
    </g>`; },

  // Grebe — dainty diver riding LOW: slim neck, sharp thin pointed bill, sleek round head, small tuft
  grebe: (c) => { const B = belly(c), D = deepen(c.body, 0.45); return `
    ${floorShadow(58, 99, 28)}
    ${water(58, 95, 30)}
    <g class="tail-wag"><path d="M34 80 Q26 82 30 86 Q36 84 40 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M32 84 Q38 72 58 72 Q80 72 84 82 Q80 91 56 91 Q37 91 32 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 84 Q58 89 78 84 Q72 88 56 89 Q44 88 44 84 Z" fill="${B}" opacity=".85"/>
      <path d="M48 77 Q66 74 80 81 Q68 85 54 84 Q48 81 48 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      ${tube("M78 78 Q84 66 84 56", c.body, c.line, 6)}
      <circle cx="86" cy="50" r="10.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M84 40 Q86 34 90 39 Q88 43 85 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M80 48 Q88 44 96 47" stroke="${YEL}" stroke-width="1.4" fill="none" opacity=".6"/>
      <path d="M95 48 L110 50 L95 53 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M95 50 L110 50 L95 53 Z" fill="${BEAKD}"/>
      ${eye(88, 48, 2.9, RED)}
    </g>`; },

  // Loon — bold diver: checkerboard-spotted back, straight dagger bill, red eye, rides low & sleek
  loon: (c) => { const B = belly(c), D = deepen(c.body, 0.55); return `
    ${floorShadow(58, 100, 33)}
    ${water(58, 96, 34)}
    <g class="tail-wag"><path d="M30 80 Q20 82 24 87 Q31 85 37 83 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M27 85 Q32 70 56 70 Q83 70 90 82 Q85 93 56 93 Q32 93 27 85 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 86 Q56 92 84 86 Q77 91 56 92 Q40 91 40 86 Z" fill="${B}" opacity=".85"/>
      <path d="M44 76 Q66 72 84 81 Q70 86 52 85 Q44 81 44 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${[[50, 78], [58, 76], [66, 78], [74, 80], [54, 82], [62, 82], [70, 83]].map(([x, y]) => `<rect x="${x}" y="${y}" width="2.4" height="2.4" fill="${WHT}" opacity=".85"/>`).join("")}</g>
    <g class="head-tilt">
      ${tube("M80 75 Q84 65 84 57", c.body, c.line, 8)}
      <circle cx="86" cy="51" r="12.5" fill="${D}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M78 62 q8 3 16 0" stroke="${WHT}" stroke-width="1.4" fill="none" opacity=".5"/>
      <path d="M97 49 L112 51 L97 55 Z" fill="${D}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(88, 48, 3, RED)}
    </g>`; },

  // Coot — sooty round waterbird with a bright WHITE frontal shield + pointed white bill; slaty body
  coot: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(58, 100, 29)}
    ${water(58, 96, 30)}
    <g class="tail-wag"><path d="M34 78 Q24 78 27 85 Q34 83 40 81 Z" fill="${D}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M32 82 Q36 68 57 68 Q81 68 86 80 Q81 91 56 91 Q37 91 32 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 83 Q57 89 79 83 Q73 88 56 89 Q44 88 44 83 Z" fill="${B}" opacity=".6"/>
      <path d="M48 73 Q66 70 80 78 Q68 84 54 82 Q48 78 48 73 Z" fill="${D}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round" opacity=".8"/></g>
    <g class="head-tilt">
      ${tube("M78 73 Q82 64 83 57", c.body, c.line, 7)}
      <circle cx="85" cy="52" r="11.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M89 42 Q94 42 93 51 Q90 52 87 50 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M93 49 L107 51 Q109 54 106 56 L93 55 Z" fill="${WHT}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(88, 50, 3, RED)}
    </g>`; },

  // ── LONG-NECKED FISH-EATERS (stand upright, hold neck high) ─────────────────────────────
  // Cormorant — upright, snaky neck held erect, HOOK-tipped bill, pale throat patch, wings held close
  cormorant: (c) => { const B = belly(c), D = deepen(c.body, 0.4); return `
    ${floorShadow(60, 110, 24)}
    <g class="tail-wag"><path d="M44 92 Q34 108 46 106 L54 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M46 90 Q42 62 60 58 Q80 62 78 90 Q62 100 46 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 70 Q62 64 70 70 Q72 86 60 92 Q50 86 54 70 Z" fill="${B}" opacity=".55"/>
      <path d="M62 64 Q80 68 78 90 Q70 80 60 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${webfeet([54, 66], 104)}
    <g class="head-tilt">
      ${tube("M62 62 Q66 44 74 34", c.body, c.line, 7)}
      <circle cx="76" cy="30" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M74 36 q6 2 12 -1" stroke="${WHT}" stroke-width="2.2" fill="none" opacity=".7"/>
      <path d="M84 27 L100 29 Q102 32 99 33 L96 33 Q98 37 93 37 Q90 34 84 33 Z" fill="${DAGGER}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(78, 27, 2.9, RED)}
    </g>`; },

  // Anhinga — "snakebird": very long thin kinked S-neck, tiny head, straight spear bill, silvered wing
  anhinga: (c) => { const B = belly(c), D = deepen(c.body, 0.45); return `
    ${floorShadow(60, 110, 24)}
    <g class="tail-wag"><path d="M44 92 Q32 112 46 110 L54 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 100 h14 M42 106 h12" stroke="${c.line}" stroke-width="1.1" opacity=".4"/></g>
    <g class="breathe">
      <path d="M46 90 Q42 64 60 60 Q80 64 78 90 Q62 100 46 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 72 Q62 66 70 72 Q72 86 60 92 Q50 86 54 72 Z" fill="${B}" opacity=".5"/>
      <path d="M62 66 Q80 70 78 90 Q70 80 60 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${[66, 71, 76].map((y) => `<path d="M64 ${y} h12" stroke="${WHT}" stroke-width="1.3" opacity=".7"/>`).join("")}</g>
    ${webfeet([54, 66], 104)}
    <g class="head-tilt">
      ${tube("M62 64 Q78 52 66 38 Q60 30 72 24", c.body, c.line, 5)}
      <ellipse cx="75" cy="22" rx="7.5" ry="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M81 20 L102 22 L81 25 Z" fill="${DAGGER}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${eye(77, 21, 2.5, eyeInk(c))}
    </g>`; },

  // ── OPEN-OCEAN SEABIRDS (stand upright) ─────────────────────────────────────────────────
  // Albatross — vast outstretched wings rooted at the shoulders, long pale tubenose hook bill
  albatross: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(60, 111, 30)}
    <g class="tail-wag">
      <path d="M56 56 Q28 46 9 62 Q30 64 52 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M16 59 L34 60 M20 64 L36 65" stroke="${D}" stroke-width="1.5" opacity=".55"/></g>
    <g class="tail-wag">
      <path d="M64 56 Q92 46 111 62 Q90 64 68 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 59 L104 60 M84 64 L100 65" stroke="${D}" stroke-width="1.5" opacity=".55"/></g>
    <g class="breathe">
      <path d="M60 48 Q79 52 79 78 Q79 101 60 103 Q41 101 41 78 Q41 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 60 Q72 64 71 84 Q66 95 60 97 Q54 95 49 84 Q48 64 60 60 Z" fill="${B}"/></g>
    ${webfeet([54, 66], 105)}
    <g class="head-tilt">
      <circle cx="60" cy="39" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M72 34 L98 37 Q102 40 98 43 L72 43 Z" fill="${WHT}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M94 37 Q101 39 97 44 Q93 43 93 39 Z" fill="${BEAKD}"/>
      <path d="M74 37 h20" stroke="${c.line}" stroke-width="0.9" opacity=".5"/>
      ${eye(64, 37, 3, eyeInk(c))}
    </g>`; },

  // Petrel — small dark ocean glider: slim body, short tubenose bill, neat folded pointed wing
  petrel: (c) => { const B = belly(c), D = deepen(c.body, 0.45); return `
    ${floorShadow(60, 110, 22)}
    <g class="tail-wag"><path d="M44 88 Q34 104 46 102 L54 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M48 88 Q44 62 60 58 Q78 62 76 88 Q62 97 48 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 70 Q60 64 68 70 Q70 84 60 90 Q52 84 54 70 Z" fill="${B}"/>
      <path d="M62 62 Q82 68 74 90 Q68 80 58 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${webfeet([55, 65], 102)}
    <g class="head-tilt">
      <circle cx="63" cy="46" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M74 44 L90 46 Q92 49 89 50 L86 50 Q88 53 84 52 Q80 49 74 48 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M75 45 h12" stroke="${c.line}" stroke-width="0.8" opacity=".5"/>
      ${eye(65, 44, 3, eyeInk(c))}
    </g>`; },

  // Blue-footed Booby — comical upright poser with big bright BLUE webbed feet, long dagger bill
  bluefootedbooby: (c) => { const B = belly(c), D = deepen(c.body, 0.4); return `
    ${floorShadow(60, 111, 24)}
    ${webfeet([50, 70], 104, BLUE)}
    <g class="tail-wag"><path d="M46 90 Q36 106 48 104 L56 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M46 88 Q42 60 60 56 Q80 60 78 88 Q62 98 46 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 68 Q60 62 70 68 Q72 84 60 90 Q49 84 52 68 Z" fill="${B}"/>
      <path d="M62 60 Q80 64 78 86 Q70 76 60 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      <circle cx="62" cy="42" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 40 q6 -3 12 0" stroke="${D}" stroke-width="1.6" fill="none" opacity=".55"/>
      <path d="M73 38 L98 41 Q101 44 98 47 L73 47 Z" fill="${DAGGER}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 43 h22" stroke="${c.line}" stroke-width="0.9" opacity=".5"/>
      ${eye(64, 40, 3.2, eyeInk(c))}
    </g>`; },

  // Gannet — sleek plunge-diver: pointed body & tail, golden nape wash, dark wingtips, long dagger bill
  gannet: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(60, 111, 24)}
    <g class="tail-wag"><path d="M46 90 Q36 110 50 108 L56 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M48 88 Q42 58 60 54 Q80 58 76 88 Q62 98 48 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 68 Q60 62 68 68 Q70 84 60 90 Q51 84 54 68 Z" fill="${B}"/>
      <path d="M62 58 Q82 64 76 90 L70 80 Q66 74 58 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M72 86 L78 92 L74 82 Z" fill="${D}"/></g>
    ${webfeet([55, 65], 104)}
    <g class="head-tilt">
      <circle cx="62" cy="42" r="12.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 36 Q62 32 71 38 Q62 40 53 43 Z" fill="${YEL}" opacity=".8"/>
      <path d="M73 39 L99 41 Q102 43 99 46 L73 46 Z" fill="${DAGGER}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 43 h23" stroke="${c.line}" stroke-width="0.9" opacity=".5"/>
      ${eye(64, 40, 3, eyeInk(c))}
    </g>`; },

  // Frigatebird — angular pirate: big inflated RED throat pouch, long hooked bill, deeply forked tail
  frigatebird: (c) => { const B = belly(c), D = deepen(c.body, 0.45); return `
    ${floorShadow(58, 111, 24)}
    <g class="tail-wag">
      <path d="M42 88 L30 110 L42 102 L52 110 L54 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="tail-wag">
      <path d="M60 58 Q86 50 104 60 Q84 66 62 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M46 88 Q42 62 60 58 Q78 62 76 86 Q62 96 46 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M62 62 Q78 66 76 86 Q68 78 58 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${webfeet([55, 65], 102)}
    <g class="head-tilt">
      <circle cx="60" cy="42" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M58 50 Q74 52 74 64 Q66 72 58 68 Q52 60 58 50 Z" fill="${RED}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M62 54 q6 3 6 8" stroke="${deepen(RED, 0.25)}" stroke-width="1.2" fill="none" opacity=".7"/>
      <path d="M71 38 L94 41 Q97 44 94 45 L91 45 Q94 49 89 48 Q84 44 71 43 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(62, 40, 3, eyeInk(c))}
    </g>`; },

  // Skua — bulky brown ocean-pirate: stocky build, broad folded wings, blunt HOOK bill, pale wing-flash
  skua: (c) => { const B = belly(c), D = deepen(c.body, 0.4); return `
    ${floorShadow(60, 110, 26)}
    <g class="tail-wag"><path d="M42 90 Q30 104 44 102 L54 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M42 88 Q38 60 60 56 Q84 60 80 88 Q62 100 42 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 68 Q60 62 70 68 Q72 84 60 92 Q49 84 52 68 Z" fill="${B}" opacity=".7"/>
      <path d="M62 60 Q84 66 80 90 Q72 78 60 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M68 66 Q78 72 78 82 Q72 76 66 74 Z" fill="${WHT}" opacity=".85"/></g>
    ${webfeet([54, 66], 104)}
    <g class="head-tilt">
      <circle cx="60" cy="44" r="13.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 42 q6 -3 12 0" stroke="${D}" stroke-width="1.6" fill="none" opacity=".55"/>
      <path d="M72 40 L91 42 Q94 45 90 47 L86 46 Q89 50 84 49 Q80 46 72 46 Z" fill="${BEAKD}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(63, 42, 3.1, eyeInk(c))}
    </g>`; },

  // Tern — elegant slim flier: crisp dark cap, thin sharp pointed bill, deeply FORKED streamer tail
  tern: (c) => { const B = belly(c), D = deepen(c.body, 0.55); return `
    ${floorShadow(58, 110, 22)}
    <g class="tail-wag">
      <path d="M44 84 L28 108 L40 100 L48 108 L54 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M48 86 Q44 62 60 58 Q78 62 76 86 Q62 95 48 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 70 Q60 64 68 70 Q70 82 60 88 Q52 82 54 70 Z" fill="${B}"/>
      <path d="M62 62 Q84 66 76 88 Q69 78 58 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${webfeet([55, 65], 100)}
    <g class="head-tilt">
      <circle cx="63" cy="46" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M53 43 Q55 34 65 34 Q76 35 75 45 Q64 38 53 43 Z" fill="${D}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M74 45 L96 47 L74 50 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${eye(66, 46, 3, eyeInk(c))}
    </g>`; },

  // ── SHOREBIRDS & WADERS (long legs, plump body up high, long specialised bill) ───────────
  // Avocet — elegant wader: very long legs, slender neck, fine UP-curved needle bill
  avocet: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(58, 112, 24)}
    ${wlegs([54, 66], 74)}
    <g class="tail-wag"><path d="M40 66 Q28 72 30 62 Q36 64 45 63 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="62" rx="20" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 64 Q56 70 68 64 Q64 70 56 71 Q48 70 46 64 Z" fill="${B}"/>
      <path d="M50 56 Q64 52 74 58 Q66 63 54 62 Q49 60 50 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      ${tube("M66 54 Q70 40 78 32", c.body, c.line, 6)}
      <circle cx="80" cy="29" r="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M86 27 Q98 26 106 16" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M86 27 Q98 26 106 16" fill="none" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(81, 27, 2.6, eyeInk(c))}
    </g>`; },

  // Sandpiper — small busy shorebird: plump body, medium straight bill, longish legs, alert tilt
  sandpiper: (c) => { const B = belly(c), D = deepen(c.body, 0.45); return `
    ${floorShadow(58, 112, 22)}
    ${wlegs([55, 65], 82, 110)}
    <g class="tail-wag"><path d="M40 76 Q30 82 32 72 Q37 74 45 73 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="56" cy="72" rx="19" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 74 Q56 81 68 74 Q63 80 56 81 Q48 80 46 74 Z" fill="${B}"/>
      <path d="M50 64 Q66 60 76 68 Q66 73 54 72 Q49 68 50 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${[54, 62, 70].map((x) => `<path d="M${x} 62 l2 6" stroke="${D}" stroke-width="1.2" opacity=".55" stroke-linecap="round"/>`).join("")}</g>
    <g class="head-tilt">
      <circle cx="70" cy="56" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M64 51 q6 -2 11 1" stroke="${WHT}" stroke-width="1.6" fill="none" opacity=".7"/>
      <path d="M80 55 L98 57 L80 60 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M80 57 L98 57 L80 60 Z" fill="${BEAKD}"/>
      ${eye(72, 54, 3, eyeInk(c))}
    </g>`; },

  // Curlew — big wader: long legs & neck, streaky plumage, VERY long down-curved sickle bill
  curlew: (c) => { const B = belly(c), D = deepen(c.body, 0.5); return `
    ${floorShadow(56, 112, 24)}
    ${wlegs([54, 66], 74)}
    <g class="tail-wag"><path d="M40 66 Q28 72 30 62 Q36 64 45 63 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <ellipse cx="55" cy="62" rx="20" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M45 64 Q55 71 67 64 Q62 70 55 71 Q47 70 45 64 Z" fill="${B}"/>
      <path d="M49 55 Q64 51 74 58 Q65 63 53 62 Q48 59 49 55 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${[[50, 58], [58, 56], [66, 60], [54, 64], [62, 65]].map(([x, y]) => `<path d="M${x} ${y} l2 5" stroke="${D}" stroke-width="1.2" opacity=".6" stroke-linecap="round"/>`).join("")}</g>
    <g class="head-tilt">
      ${tube("M65 54 Q69 42 76 34", c.body, c.line, 6)}
      <circle cx="78" cy="31" r="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M84 33 Q100 36 102 54 Q101 60 97 58 Q98 44 88 38 Q83 36 82 33 Z" fill="${BEAKD}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(79, 29, 2.7, eyeInk(c))}
    </g>`; },
};

export const ROSTER_WATERFOWL = [
  { n: "Mallard", e: "🦆", tier: 1, float: false },
  { n: "Wood Duck", e: "🦆", tier: 2, float: false },
  { n: "Mandarin Duck", e: "🦆", tier: 3, float: false },
  { n: "Teal", e: "🦆", tier: 1, float: false },
  { n: "Merganser", e: "🦆", tier: 2, float: false },
  { n: "Grebe", e: "🦆", tier: 1, float: false },
  { n: "Loon", e: "🦆", tier: 2, float: false },
  { n: "Coot", e: "🦆", tier: 1, float: false },
  { n: "Cormorant", e: "🐦", tier: 2, float: false },
  { n: "Anhinga", e: "🐦", tier: 2, float: false },
  { n: "Albatross", e: "🐦", tier: 3, float: false },
  { n: "Petrel", e: "🐦", tier: 1, float: false },
  { n: "Blue-footed Booby", e: "🐦", tier: 2, float: false },
  { n: "Gannet", e: "🐦", tier: 2, float: false },
  { n: "Frigatebird", e: "🐦", tier: 3, float: false },
  { n: "Skua", e: "🐦", tier: 2, float: false },
  { n: "Tern", e: "🐦", tier: 1, float: false },
  { n: "Avocet", e: "🐦", tier: 2, float: false },
  { n: "Sandpiper", e: "🐦", tier: 1, float: false },
  { n: "Curlew", e: "🐦", tier: 2, float: false },
];
