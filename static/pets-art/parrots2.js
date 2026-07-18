// parrots2.js — BESPOKE hand-drawn SVG art for PARROTS & PARAKEETS (NADO Pets), batch PARROTS2.
// Each entry is an original, on-spot drawing of ONE species — no shared/parameterized bodies.
// Distinct from birds.js (parrot/macaw/cockatoo/toucan) and exoticbirds.js (budgie/lovebird/cockatiel…).
// Contract: inner markup of <svg viewBox="0 0 120 120">, animal centered ~(60,64), within x,y ∈ [8,114].
// Coat comes from `c`: c.body (fill), c.shade (accent/underside/wing/markings), c.line (outline stroke).
// Body ALWAYS from c (the game recolours every pet) — species must read from SHAPE: crest/beak/tail/markings.
// Fixed warm accents only for universal hooked beaks / feet / eye-rings; nose/eyes = INK/eyeInk.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk } from "../pets-draw.js";

const BEAK = "#f2a03b";   // hooked beak (orange)
const BEAKD = "#d97b2c";  // beak lower-hook shading
const HORN = "#f2c94c";   // yellow eye-ring / cere / lappet
const LEG = "#e79a3a";    // scaly zygodactyl feet
const WHT = "#fbf6ee";    // bare eye-ring / cheek highlight (not coat)
const TIP = "#e0564d";    // red flash (vent / ring accent)

// zygodactyl parrot foot: short leg + splayed grip (roots inside the body at y)
const feet = (xs, y) => xs.map((x) =>
  `<path d="M${x} ${y} l0 6 M${x - 4} ${y + 6} h8 M${x - 4} ${y + 6} l-3 4 M${x + 4} ${y + 6} l3 4 M${x} ${y + 6} l0 4" stroke="${LEG}" stroke-width="2.2" fill="none" stroke-linecap="round"/>`).join("");
// a stout hooked beak on a FRONT face, centred at cx
const hookF = (cx, y, line) =>
  `<path d="M${cx - 7} ${y} Q${cx} ${y - 4} ${cx + 7} ${y} Q${cx + 7} ${y + 10} ${cx} ${y + 14} Q${cx - 7} ${y + 10} ${cx - 7} ${y} Z" fill="${BEAK}" stroke="${line}" stroke-width="2" stroke-linejoin="round"/>` +
  `<path d="M${cx - 4} ${y + 6} Q${cx} ${y + 10} ${cx + 4} ${y + 6} Q${cx + 3} ${y + 13} ${cx} ${y + 14} Q${cx - 3} ${y + 13} ${cx - 4} ${y + 6} Z" fill="${BEAKD}"/>`;
// a hooked beak in 3/4 view, hook pointing down-right from head at (x,y)
const hookR = (x, y, line, fill = BEAK) =>
  `<path d="M${x} ${y - 6} Q${x + 15} ${y - 6} ${x + 13} ${y + 6} Q${x + 10} ${y + 13} ${x + 1} ${y + 11} Q${x - 2} ${y + 3} ${x} ${y - 4} Z" fill="${fill}" stroke="${line}" stroke-width="2" stroke-linejoin="round"/>` +
  `<path d="M${x + 1} ${y + 5} Q${x + 10} ${y + 7} ${x + 12} ${y + 3} Q${x + 10} ${y + 12} ${x + 2} ${y + 10} Q${x - 1} ${y + 8} ${x + 1} ${y + 5} Z" fill="${BEAKD}"/>`;
// scalloped chevron rows for a scaly bib/back (x0→x1 across; ys array of row-baselines)
const scale = (x0, x1, ys, col) => { const q = (x1 - x0) / 4; return ys.map((y) =>
  `<path d="M${x0} ${y} q${q} 5 ${q * 2} 0 q${q} 5 ${q * 2} 0" stroke="${col}" stroke-width="1.3" fill="none" opacity=".6"/>`).join(""); };

export const ART_PARROTS2 = {
  // Rainbow Lorikeet — front, streaked head, scalloped bib, medium double pointed tail
  rainbowlorikeet: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 25)}
    <g class="tail-wag"><path d="M55 96 Q49 115 58 113 L61 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M61 96 Q69 114 71 110 L64 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 46 Q81 50 81 78 Q79 101 60 103 Q41 101 39 78 Q39 50 60 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 66 Q60 60 74 66 Q76 90 60 97 Q44 90 46 66 Z" fill="${B}"/>
      ${scale(48, 72, [68, 74, 80, 86], c.shade)}
      <path d="M74 58 Q86 74 79 96 Q71 84 66 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="60" cy="40" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[34, 38, 42].map((y) => `<path d="M48 ${y} q12 -3 24 0" stroke="${c.shade}" stroke-width="1.2" fill="none" opacity=".5"/>`).join("")}
      ${hookF(60, 47, c.line)}
      ${ceye(52, 42, 3.5)}${ceye(68, 42, 3.5)}
    </g>`; },

  // Sun Conure — 3/4, radiant eye-ring face patch, sunburst belly, medium-long pointed tail
  sunconure: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag"><path d="M55 94 Q50 116 59 114 L62 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q78 52 78 78 Q76 101 59 102 Q45 100 44 78 Q44 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 66 Q60 60 70 66 Q72 90 59 96 Q48 90 50 66 Z" fill="${B}"/>
      ${[62, 70, 78, 86].map((y) => `<path d="M50 ${y} q10 4 20 0" stroke="${c.shade}" stroke-width="1.3" fill="none" opacity=".5"/>`).join("")}
      <path d="M42 60 Q34 76 44 92 Q48 76 48 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="58" cy="42" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="44" rx="10" ry="9" fill="${B}"/>
      ${hookR(69, 44, c.line)}
      ${eye(58, 42, 3.3, eyeInk(c))}
    </g>`; },

  // Green-cheeked Conure — 3/4, small, grey crown cap, cheek patch, VERY long thin tail
  greencheekedconure: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 21)}
    <g class="tail-wag"><path d="M56 90 Q53 114 60 113 L62 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 52 Q74 55 74 76 Q72 96 59 97 Q47 96 46 76 Q46 55 60 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M51 66 Q60 61 68 66 Q69 86 59 91 Q50 86 51 66 Z" fill="${B}"/>
      <path d="M45 62 Q38 76 46 90 Q50 76 50 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    ${feet([55, 65], 95)}
    <g class="head-tilt">
      <circle cx="58" cy="44" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 40 Q58 33 70 40 Q68 46 58 46 Q49 46 46 40 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="53" cy="48" rx="4.5" ry="3.6" fill="${B}"/>
      ${hookR(67, 45, c.line)}
      ${eye(56, 44, 3, eyeInk(c))}
    </g>`; },

  // Amazon Parrot — front, chunky broad body, SHORT square tail, forehead patch, stout head
  amazonparrot: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 27)}
    <g class="tail-wag"><path d="M48 96 Q48 110 60 110 Q72 110 72 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M52 100 h16" stroke="${c.line}" stroke-width="1.2" opacity=".4"/></g>
    <g class="breathe">
      <path d="M60 44 Q84 48 84 78 Q82 102 60 104 Q38 102 36 78 Q36 48 60 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 66 Q60 60 74 66 Q76 92 60 98 Q44 92 46 66 Z" fill="${B}"/>
      <path d="M74 58 Q88 76 80 98 Q72 86 66 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([53, 67], 102)}
    <g class="head-tilt">
      <circle cx="60" cy="40" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 30 Q60 24 70 30 Q66 38 60 38 Q54 38 50 30 Z" fill="${c.shade}" opacity=".7"/>
      ${hookF(60, 46, c.line)}
      ${ceye(51, 41, 3.6)}${ceye(69, 41, 3.6)}
    </g>`; },

  // Eclectus — 3/4, sleek glossy (no wing bars), SHORT tail, candy-corn 2-band beak, slim head
  eclectus: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag"><path d="M50 98 Q50 110 60 110 Q70 110 70 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q77 52 77 78 Q75 101 60 103 Q45 101 43 78 Q43 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 66 Q60 61 68 66 Q69 90 60 96 Q51 90 52 66 Z" fill="${B}" opacity=".85"/>
      <path d="M42 62 Q36 78 45 94 Q49 78 48 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    ${feet([54, 66], 101)}
    <g class="head-tilt">
      <ellipse cx="58" cy="42" rx="14" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M69 42 Q84 42 82 54 Q79 60 71 58 Q68 50 70 44 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M76 45 Q84 46 82 54 Q79 58 74 56 Z" fill="${HORN}"/>
      ${eye(58, 41, 3.2, eyeInk(c))}
    </g>`; },

  // Kakapo — front, BIG round green owl-parrot: pale facial discs, whiskers, mottled spots, tiny beak, stubby tail
  kakapo: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag"><path d="M50 98 Q50 108 60 108 Q70 108 70 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 50 Q90 54 90 80 Q88 104 60 106 Q32 104 30 80 Q30 54 60 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 72 Q60 66 76 72 Q78 96 60 102 Q42 96 44 72 Z" fill="${B}"/>
      ${[36, 46, 56, 64, 72, 78].map((x, i) => `<path d="M${34 + (i % 3) * 18} ${64 + ((i / 3) | 0) * 14} q3 -5 6 0" stroke="${c.shade}" stroke-width="1.5" fill="none" opacity=".55"/>`).join("")}</g>
    ${feet([50, 70], 102)}
    <g class="head-tilt">
      <circle cx="60" cy="44" r="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="50" cy="46" rx="9" ry="11" fill="${B}" stroke="${c.line}" stroke-width="1.2"/>
      ${mirror(`<ellipse cx="50" cy="46" rx="9" ry="11" fill="${B}" stroke="${c.line}" stroke-width="1.2"/>`)}
      <path d="M56 50 Q60 47 64 50 Q64 57 60 60 Q56 57 56 50 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M40 52 l-9 2 M41 56 l-9 4 M79 52 l9 2 M78 56 l9 4" stroke="${c.line}" stroke-width="1.1" stroke-linecap="round" opacity=".55"/>
      ${ceye(50, 45, 3.4)}${ceye(70, 45, 3.4)}
    </g>`; },

  // Kea — 3/4, olive streaky alpine parrot: LONG narrow strongly-hooked beak, orange underwing flash
  kea: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 25)}
    <g class="tail-wag"><path d="M52 96 Q46 112 56 111 L60 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 96 Q68 110 70 106 L64 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q80 52 80 78 Q78 100 59 102 Q44 100 43 78 Q43 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[62, 70, 78, 86].map((y) => `<path d="M48 ${y} q12 4 24 0" stroke="${deepen(c.body, 0.22)}" stroke-width="1.3" fill="none" opacity=".55"/>`).join("")}
      <path d="M42 62 Q34 80 46 96 Q49 80 49 68 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round" opacity=".9"/></g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="56" cy="44" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[40, 44, 48].map((y) => `<path d="M46 ${y} q9 -2 18 0" stroke="${deepen(c.body, 0.22)}" stroke-width="1" fill="none" opacity=".5"/>`).join("")}
      <path d="M66 40 Q97 36 96 51 Q95 67 82 79 Q77 73 80 60 Q71 55 67 46 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M80 58 Q91 60 94 53 Q93 67 82 78 Q78 71 80 58 Z" fill="${BEAKD}"/>
      ${eye(56, 43, 3.2, eyeInk(c))}
    </g>`; },

  // Rosella — 3/4, mosaic scalloped back, white cheek patch, medium pointed tail
  rosella: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag"><path d="M55 94 Q50 114 59 113 L62 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M61 94 Q68 112 71 108 L64 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q79 52 79 78 Q77 100 60 102 Q43 100 41 78 Q41 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 68 Q60 63 70 68 Q71 90 60 96 Q49 90 50 68 Z" fill="${B}"/>
      ${scale(44, 76, [58, 65, 72], c.shade)}
      <path d="M72 58 Q84 74 78 94 Q71 84 66 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="58" cy="42" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="55" cy="49" rx="6" ry="5" fill="${WHT}" stroke="${c.line}" stroke-width="1.2"/>
      ${hookR(69, 43, c.line)}
      ${eye(57, 41, 3.2, eyeInk(c))}
    </g>`; },

  // Caique — front, small stocky, bold head cap, strong WHITE belly, short tail, perky
  caique: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag"><path d="M52 96 Q52 108 60 108 Q68 108 68 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q80 52 80 78 Q78 100 60 102 Q42 100 40 78 Q40 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M45 64 Q60 57 75 64 Q77 92 60 98 Q43 92 45 64 Z" fill="${tint(c.body, 0.86)}"/>
      <path d="M74 58 Q86 74 79 96 Q72 84 67 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="60" cy="40" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 40 Q44 24 60 24 Q76 24 76 40 Q68 34 60 34 Q52 34 44 40 Z" fill="${c.shade}"/>
      ${hookF(60, 46, c.line)}
      ${ceye(51, 42, 3.5)}${ceye(69, 42, 3.5)}
    </g>`; },

  // Quaker Parrot — front, grey scaled bib across face+chest, plain crown, long tail
  quakerparrot: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 23)}
    <g class="tail-wag"><path d="M56 94 Q52 114 60 113 L62 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 94 Q68 112 70 108 L64 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q78 52 78 78 Q76 100 60 102 Q44 100 42 78 Q42 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 62 Q60 56 74 62 Q76 88 60 94 Q44 88 46 62 Z" fill="${B}"/>
      ${scale(46, 74, [62, 68, 74, 80], c.shade)}</g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="60" cy="40" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 46 Q60 42 74 46 Q73 54 60 56 Q47 54 46 46 Z" fill="${B}"/>
      ${scale(48, 72, [47, 51], c.shade)}
      ${hookF(60, 45, c.line)}
      ${ceye(51, 40, 3.4)}${ceye(69, 40, 3.4)}
    </g>`; },

  // Indian Ringneck — 3/4, slim, neck ring collar, red hooked beak, VERY long thin pointed tail
  indianringneck: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 21)}
    <g class="tail-wag"><path d="M57 92 Q54 114 60 114 L62 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 92 Q65 112 68 108 L63 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 50 Q76 54 76 77 Q74 97 59 98 Q46 97 45 77 Q45 54 60 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M51 66 Q60 61 68 66 Q69 86 59 92 Q50 86 51 66 Z" fill="${B}"/>
      <path d="M44 62 Q37 77 46 92 Q50 77 49 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/></g>
    ${feet([55, 65], 96)}
    <g class="head-tilt">
      <circle cx="58" cy="44" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M47 54 Q58 61 70 53" stroke="${deepen(c.body, 0.28)}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
      <path d="M47 56 Q58 62 70 55" stroke="${TIP}" stroke-width="1.4" fill="none" stroke-linecap="round" opacity=".7"/>
      ${hookR(67, 44, c.line)}
      ${eye(57, 43, 3.1, eyeInk(c))}
    </g>`; },

  // Galah — front cockatoo, small soft recurved crest, pink belly + grey back two-tone, rounded
  galah: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag"><path d="M52 96 Q50 110 60 110 Q70 110 68 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 46 Q82 50 82 78 Q80 102 60 104 Q40 102 38 78 Q38 50 60 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 62 Q60 54 78 62 Q80 94 60 100 Q40 94 42 62 Z" fill="${tint(c.body, 0.3)}"/></g>
    ${feet([54, 66], 102)}
    <g class="head-tilt">
      ${[-16, -4, 8].map((a) => `<g transform="rotate(${a} 60 30)"><path d="M60 30 Q54 14 60 10 Q66 15 62 30 Z" fill="${tint(c.body, 0.3)}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/></g>`).join("")}
      <circle cx="60" cy="40" r="16" fill="${tint(c.body, 0.3)}" stroke="${c.line}" stroke-width="2.4"/>
      ${hookF(60, 46, c.line)}
      ${ceye(51, 41, 3.4)}${ceye(69, 41, 3.4)}
    </g>`; },

  // Corella — front white cockatoo, short recurved crest, bare eye-rings, stout beak, small
  corella: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag"><path d="M52 96 Q52 108 60 108 Q68 108 68 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q79 52 79 78 Q77 101 60 103 Q43 101 41 78 Q41 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 66 Q60 60 70 66 Q71 92 60 98 Q49 92 50 66 Z" fill="${B}"/></g>
    ${feet([54, 66], 101)}
    <g class="head-tilt">
      ${[-20, -6, 8, 20].map((a) => `<g transform="rotate(${a} 60 30)"><path d="M60 30 Q53 8 60 2 Q67 8 62 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/></g>`).join("")}
      <circle cx="60" cy="41" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="52" cy="43" rx="4.5" ry="5" fill="${WHT}" stroke="${c.line}" stroke-width="1"/>
      ${mirror(`<ellipse cx="52" cy="43" rx="4.5" ry="5" fill="${WHT}" stroke="${c.line}" stroke-width="1"/>`)}
      ${hookF(60, 46, c.line)}
      ${ceye(52, 42, 3.1)}${ceye(68, 42, 3.1)}
    </g>`; },

  // Kaka — 3/4, bushy streaked crown, hooked beak, orange collar/underwing flash, chunky forest parrot
  kaka: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag"><path d="M52 96 Q47 112 57 111 L60 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 96 Q69 110 71 106 L64 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q82 52 82 78 Q80 101 60 103 Q42 101 40 78 Q40 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 66 Q58 60 68 66 Q69 90 59 96 Q46 90 46 66 Z" fill="${tint(c.body, 0.4)}"/>
      <path d="M46 60 Q60 66 74 60" stroke="${BEAK}" stroke-width="3" fill="none" stroke-linecap="round" opacity=".8"/>
      <path d="M74 58 Q88 76 80 98 Q72 86 66 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([54, 66], 101)}
    <g class="head-tilt">
      <circle cx="58" cy="42" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[34, 38, 42].map((y) => `<path d="M46 ${y} q11 -3 22 0" stroke="${tint(c.body, 0.45)}" stroke-width="1.2" fill="none" opacity=".6"/>`).join("")}
      <path d="M67 38 Q88 38 86 54 Q84 66 68 60 Q65 50 67 40 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M69 52 Q80 56 84 50 Q82 64 69 59 Z" fill="${BEAKD}"/>
      ${eye(56, 42, 3.2, eyeInk(c))}
    </g>`; },

  // Alexandrine — 3/4, large ringneck: shoulder patch, neck ring, big red beak, very long broad tail
  alexandrine: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 23)}
    <g class="tail-wag"><path d="M55 92 Q51 114 60 114 L63 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M62 92 Q70 112 72 107 L65 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q80 52 80 78 Q78 100 59 101 Q45 100 44 78 Q44 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M51 66 Q60 61 68 66 Q69 88 59 94 Q50 88 51 66 Z" fill="${B}"/>
      <ellipse cx="71" cy="67" rx="10.5" ry="8.5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M64 62 q6 4 12 1" stroke="${TIP}" stroke-width="1.6" fill="none" stroke-linecap="round" opacity=".6"/>
      <path d="M42 60 Q35 78 46 94 Q50 78 49 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="58" cy="43" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 54 Q58 61 71 52" stroke="${deepen(c.body, 0.3)}" stroke-width="2.8" fill="none" stroke-linecap="round"/>
      <path d="M66 38 Q90 38 88 55 Q86 68 70 62 Q66 52 68 40 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M69 54 Q82 58 86 51 Q84 66 70 61 Z" fill="${BEAKD}"/>
      ${eye(57, 42, 3.2, eyeInk(c))}
    </g>`; },

  // Meyer's Parrot — 3/4 small dusky African, yellow crown bar + yellow wing-bend, teal belly hint
  meyersparrot: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag"><path d="M52 94 Q49 110 58 109 L61 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 50 Q77 54 77 78 Q75 98 59 99 Q46 98 45 78 Q45 54 60 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M51 68 Q60 63 68 68 Q69 88 59 93 Q50 88 51 68 Z" fill="${tint(c.body, 0.4)}"/>
      <path d="M43 64 Q37 78 46 92 Q50 78 49 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="48" cy="66" rx="4" ry="3" fill="${HORN}"/></g>
    ${feet([55, 65], 97)}
    <g class="head-tilt">
      <circle cx="58" cy="44" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 36 q10 -3 20 0" stroke="${HORN}" stroke-width="3" fill="none" stroke-linecap="round"/>
      ${hookR(67, 45, c.line)}
      ${eye(56, 44, 3.1, eyeInk(c))}
    </g>`; },

  // Pionus — front stocky, bare eye-ring, short square tail, red vent patch, pale dark-based beak
  pionus: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 25)}
    <g class="tail-wag"><path d="M50 96 Q50 108 60 108 Q70 108 70 96 Z" fill="${TIP}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".85"/>
      <path d="M50 96 Q50 103 60 103 Q70 103 70 96 Z" fill="${c.shade}"/></g>
    <g class="breathe">
      <path d="M60 48 Q81 52 81 78 Q79 100 60 102 Q41 100 39 78 Q39 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 66 Q60 60 74 66 Q76 90 60 96 Q44 90 46 66 Z" fill="${B}"/>
      <path d="M74 58 Q86 76 79 96 Q72 84 67 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="60" cy="41" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="52" cy="42" rx="4.5" ry="5" fill="${WHT}" stroke="${c.line}" stroke-width="1"/>
      ${mirror(`<ellipse cx="52" cy="42" rx="4.5" ry="5" fill="${WHT}" stroke="${c.line}" stroke-width="1"/>`)}
      <path d="M53 47 Q60 43 67 47 Q67 57 60 61 Q53 57 53 47 Z" fill="${tint(BEAK, 0.35)}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M55 47 Q60 45 65 47 Q64 51 60 52 Q56 51 55 47 Z" fill="${BEAKD}"/>
      ${ceye(52, 41, 3.1)}${ceye(68, 41, 3.1)}
    </g>`; },

  // Hyacinth Macaw — front, LARGE, long double streaming tail, massive dark hook beak, yellow eye-ring + chin lappet
  hyacinthmacaw: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag"><path d="M54 92 Q40 116 48 114 L60 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 92 Q54 116 66 112 L64 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 46 Q84 50 84 78 Q82 102 60 104 Q38 102 36 78 Q36 50 60 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 66 Q60 60 74 66 Q76 92 60 98 Q44 92 46 66 Z" fill="${B}"/>
      <path d="M74 56 Q90 76 81 100 Q73 86 66 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    ${feet([52, 68], 102)}
    <g class="head-tilt">
      <circle cx="60" cy="38" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M51 44 Q60 42 69 44 Q68 52 60 53 Q52 52 51 44 Z" fill="${HORN}"/>
      <path d="M51 42 Q60 38 69 42 Q69 54 60 60 Q51 54 51 42 Z" fill="${INK}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M55 50 Q60 55 65 50 Q64 57 60 59 Q56 57 55 50 Z" fill="#3a3f47"/>
      <ellipse cx="49" cy="36" rx="4.2" ry="4.6" fill="${HORN}"/><circle cx="49" cy="36" r="2.4" fill="${INK}"/><circle cx="50.2" cy="34.8" r="1" fill="#fff"/>
      <ellipse cx="71" cy="36" rx="4.2" ry="4.6" fill="${HORN}"/><circle cx="71" cy="36" r="2.4" fill="${INK}"/><circle cx="72.2" cy="34.8" r="1" fill="#fff"/>
    </g>`; },

  // Senegal Parrot — front small stocky, grey hood over head, orange/yellow V-vest belly, short tail
  senegalparrot: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag"><path d="M52 96 Q52 108 60 108 Q68 108 68 96 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 48 Q79 52 79 78 Q77 100 60 102 Q43 100 41 78 Q41 52 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M45 60 L60 96 L75 60 Q60 66 45 60 Z" fill="${tint(c.body, 0.55)}"/>
      <path d="M50 60 L60 88 L70 60 Q60 64 50 60 Z" fill="${B}"/></g>
    ${feet([54, 66], 100)}
    <g class="head-tilt">
      <circle cx="60" cy="40" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M45 40 Q45 25 60 25 Q75 25 75 40 Q75 48 60 50 Q45 48 45 40 Z" fill="${c.shade}"/>
      ${hookF(60, 45, c.line)}
      ${ceye(51, 40, 3.2)}${ceye(69, 40, 3.2)}
    </g>`; },

  // Budgerigar Flock — three little budgies on a perch: barred foreheads, cere+hook, throat spots, long tails
  budgerigarflock: (c) => { const B = belly(c); const budgie = (x, y, s, fl) => {
    const w = fl ? 1 : -1; return `
    <g class="tail-wag"><path d="M${x - 2 * s} ${y + 20 * s} Q${x - 3 * s} ${y + 34 * s} ${x + s} ${y + 33 * s} L${x + 2 * s} ${y + 20 * s} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="${x}" cy="${y + 6 * s}" rx="${11 * s}" ry="${14 * s}" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M${x - 8 * s} ${y - 2 * s} Q${x} ${y - 6 * s} ${x + 8 * s} ${y - 2 * s} Q${x + 6 * s} ${y + 16 * s} ${x} ${y + 18 * s} Q${x - 6 * s} ${y + 16 * s} ${x - 8 * s} ${y - 2 * s} Z" fill="${B}"/></g>
    <g class="head-tilt"><circle cx="${x + 3 * s * w}" cy="${y - 12 * s}" r="${9 * s}" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      ${[-15, -12, -9].map((dy) => `<path d="M${x + (3 * w - 6) * s} ${y + dy * s} q${6 * s} -2 ${12 * s} 0" stroke="${c.line}" stroke-width="0.8" fill="none" opacity=".4"/>`).join("")}
      <path d="M${x + 3 * s * w} ${y - 8 * s} Q${x + (3 * w + 4 * w) * s} ${y - 8 * s} ${x + (3 * w + 3 * w) * s} ${y - 3 * s} Q${x + 3 * s * w} ${y} ${x + (3 * w - 3 * w) * s} ${y - 3 * s} Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      <circle cx="${x + (3 * w - 5 * w) * s}" cy="${y - 2 * s}" r="${1.6 * s}" fill="${INK}" opacity=".4"/><circle cx="${x + (3 * w + 5 * w) * s}" cy="${y - 2 * s}" r="${1.6 * s}" fill="${INK}" opacity=".4"/>
      ${eye(x + (3 * w + 3 * w) * s, y - 13 * s, 2.4 * s, eyeInk(c))}</g>`; };
    return `
    ${floorShadow(60, 112, 27)}
    <line x1="20" y1="100" x2="100" y2="100" stroke="${LEG}" stroke-width="4" stroke-linecap="round"/>
    ${budgie(36, 62, 0.82, true)}
    ${budgie(86, 60, 0.82, false)}
    ${budgie(60, 52, 1, true)}`; },
};

export const ROSTER_PARROTS2 = [
  { n: "Rainbow Lorikeet", e: "🦜", tier: 2, float: false },
  { n: "Sun Conure", e: "🦜", tier: 2, float: false },
  { n: "Green-cheeked Conure", e: "🦜", tier: 1, float: false },
  { n: "Amazon Parrot", e: "🦜", tier: 2, float: false },
  { n: "Eclectus", e: "🦜", tier: 2, float: false },
  { n: "Kakapo", e: "🦜", tier: 3, float: false },
  { n: "Kea", e: "🦜", tier: 2, float: false },
  { n: "Rosella", e: "🦜", tier: 2, float: false },
  { n: "Caique", e: "🦜", tier: 1, float: false },
  { n: "Quaker Parrot", e: "🦜", tier: 1, float: false },
  { n: "Indian Ringneck", e: "🦜", tier: 2, float: false },
  { n: "Galah", e: "🦜", tier: 2, float: false },
  { n: "Corella", e: "🦜", tier: 1, float: false },
  { n: "Kaka", e: "🦜", tier: 2, float: false },
  { n: "Alexandrine", e: "🦜", tier: 2, float: false },
  { n: "Meyer's Parrot", e: "🦜", tier: 1, float: false },
  { n: "Pionus", e: "🦜", tier: 1, float: false },
  { n: "Hyacinth Macaw", e: "🦜", tier: 3, float: false },
  { n: "Senegal Parrot", e: "🦜", tier: 1, float: false },
  { n: "Budgerigar Flock", e: "🦜", tier: 1, float: false },
];
