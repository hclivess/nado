// pets-art/fantasybeasts.js — BESPOKE hand-drawn SVG art for FANTASYBEASTS (NADO Pets).
// Folklore/fantasy humanoids & beasts. HOUSE STYLE (see METHOD): ONE continuous silhouette per
// body, two-tone shading (belly()+c.shade), a clean cute face (ceye), appendages tucked behind so
// NOTHING floats, everything grounded with floorShadow. viewBox 0 0 120 120, centred ~(60,64),
// kept within x,y ∈ [8,114]. Colours come from the coat c (c.body main / c.shade accent / c.line
// outline) so the game recolours every pet at hatch; only universal accents are fixed
// (horns #f2c94c, magic fire #ff7a1a / #ffd24a, glow #eafff4, tusks #fff).
import { INK, ceye, floorShadow, belly, tint, deepen, tube, pom, mirror, eye, eyes, smile } from "../pets-draw.js";

const HORN = "#f2c94c", TUSK = "#ffffff", FIRE = "#ff7a1a", FIRE2 = "#ffd24a", GLOW = "#eafff4";
const fist = (x, y, c, r = 6) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>`;
const foot = (x, y, c, rx = 9, ry = 6) => `<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>`;

export const ART_FANTASYBEASTS = {
  // ── Ogre — hulking brute, tusked underbite, heavy brow, club over the shoulder (front)
  ogre: (c) => { const B = belly(c), D = deepen(c.body, .16); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      ${tube("M74 74 Q92 56 98 40", c.shade, c.line, 6)}
      ${pom(99, 34, 11, c.shade, c.line, 7, 2.6)}
    </g>
    <g class="breathe">
      <path d="M60 18 C45 18 39 29 41 41 C34 44 30 54 33 66 C35 82 44 100 60 100 C76 100 85 82 87 66 C90 54 86 44 79 41 C81 29 75 18 60 18 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${foot(48, 106, c, 10, 6)}${foot(72, 106, c, 10, 6)}
      ${tube("M42 52 Q29 62 30 80", c.body, c.line, 8)}${fist(30, 82, c, 7)}
      ${tube("M78 52 Q82 64 74 74", c.body, c.line, 8)}${fist(74, 74, c, 7)}
      <ellipse cx="60" cy="80" rx="20" ry="15" fill="${B}"/>
      <path d="M42 46 q8 -4 15 -1 M63 45 q8 -3 15 1" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      ${ceye(52, 52, 3.8)}${ceye(68, 52, 3.8)}
      <ellipse cx="60" cy="61" rx="5" ry="3.6" fill="${D}"/>
      <path d="M48 68 Q60 78 72 68 Q60 72 48 68 Z" fill="${D}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M53 69 l1 -6 l2.6 6 Z M64 69 l2.6 -6 l1 6 Z" fill="${TUSK}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
    </g>`; },

  // ── Troll — hunched, long drooping nose, pointed ears, warts, snaggletooth (front)
  troll: (c) => { const B = belly(c), D = deepen(c.body, .16); return `
    ${floorShadow(60, 112, 28)}
    <g class="breathe">
      <path d="M58 18 C44 18 38 29 40 42 C31 46 29 58 33 72 C37 90 47 102 60 102 C73 102 84 90 87 72 C89 60 85 48 78 44 C80 30 72 18 58 18 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 40 L24 28 L44 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M78 40 L94 28 L74 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${foot(48, 106, c, 9, 6)}${foot(72, 106, c, 9, 6)}
      ${tube("M40 54 Q26 68 30 86", c.body, c.line, 7)}${fist(31, 88, c, 6.5)}
      ${tube("M80 54 Q94 68 90 86", c.body, c.line, 7)}${fist(89, 88, c, 6.5)}
      <ellipse cx="60" cy="82" rx="18" ry="14" fill="${B}"/>
      ${ceye(50, 48, 3.6)}${ceye(70, 48, 3.6)}
      <path d="M58 48 Q70 60 60 74 Q52 66 52 54 Q54 48 58 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 76 Q60 80 67 76" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M64 78 l0 -5 l2.4 5 Z" fill="${TUSK}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      <circle cx="46" cy="40" r="2.2" fill="${D}"/><circle cx="66" cy="52" r="2" fill="${D}"/><circle cx="50" cy="66" r="1.8" fill="${D}"/>
    </g>`; },

  // ── Goblin — wiry, HUGE pointed ears, wide toothy grin, big eyes (front)
  goblin: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="breathe">
      <path d="M60 46 C50 46 45 52 45 62 C45 74 41 92 47 100 Q60 106 73 100 C79 92 75 74 75 62 C75 52 70 46 60 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${foot(50, 104, c, 7, 5)}${foot(70, 104, c, 7, 5)}
      ${tube("M46 64 Q34 74 36 88", c.body, c.line, 6)}${fist(37, 90, c, 5.5)}
      ${tube("M74 64 Q86 74 84 88", c.body, c.line, 6)}${fist(83, 90, c, 5.5)}
      <path d="M46 42 L18 26 L48 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M41 40 L24 30 L46 50 Z" fill="${c.shade}" opacity=".65"/>
      <path d="M74 42 L102 26 L72 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M79 40 L96 30 L74 50 Z" fill="${c.shade}" opacity=".65"/>
      <circle cx="60" cy="42" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <ellipse cx="60" cy="50" rx="13" ry="9" fill="${B}"/>
      ${ceye(53, 40, 4.4)}${ceye(67, 40, 4.4)}
      <path d="M58 46 l-2.4 2.4 h4.8 Z" fill="${INK}"/>
      <path d="M47 52 Q60 64 73 52 Q60 58 47 52 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M52 53 l2 5 l2 -5 Z M64 53 l2 5 l2 -5 Z" fill="${TUSK}"/>
      <path d="M52 55 h16" stroke="${TUSK}" stroke-width="2" stroke-linecap="round"/>
    </g>`; },

  // ── Imp — little devil, small horns, arrow-tip tail, cheeky grin (front)
  imp: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      ${tube("M66 94 Q88 92 88 74", c.body, c.line, 5)}
      <path d="M84 74 l9 -3 l-3 10 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 46 C51 46 46 52 46 62 C46 74 43 92 49 100 Q60 106 71 100 C77 92 74 74 74 62 C74 52 69 46 60 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${foot(51, 104, c, 6.5, 5)}${foot(69, 104, c, 6.5, 5)}
      ${tube("M47 64 Q37 72 39 84", c.body, c.line, 5.5)}${fist(40, 86, c, 5)}
      ${tube("M73 64 Q83 72 81 84", c.body, c.line, 5.5)}${fist(80, 86, c, 5)}
      <path d="M49 30 Q44 18 52 20 Q54 26 55 32 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M71 30 Q76 18 68 20 Q66 26 65 32 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="60" cy="44" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <path d="M45 42 L34 34 L47 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M75 42 L86 34 L73 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="50" rx="11" ry="7" fill="${B}"/>
      ${ceye(53, 42, 4)}${ceye(67, 42, 4)}
      <path d="M50 52 Q60 61 70 52 Q60 58 50 52 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M55 53 l1.8 4 l1.8 -4 Z" fill="${TUSK}"/>
    </g>`; },

  // ── Satyr — human torso, curly ram horns, furry goat legs & cloven hooves, pan flute (front)
  satyr: (c) => { const B = belly(c), D = deepen(c.body, .22); return `
    ${floorShadow(60, 112, 26)}
    <g class="breathe">
      <path d="M46 58 Q44 52 50 52 Q58 60 70 52 Q76 52 76 64 Q78 80 72 88 L70 96 L62 96 L60 86 L58 96 L50 96 L48 88 Q42 80 44 64 Q44 60 46 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M52 64 Q60 70 68 64 M52 74 Q60 80 68 74" fill="none" stroke="${D}" stroke-width="1.4" opacity=".6"/>
      <path d="M49 94 h9 l-1 9 h-7 Z M62 94 h9 l-1 9 h-7 Z" fill="${D}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M48 42 Q48 32 60 32 Q72 32 72 42 L74 58 Q60 66 46 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M50 58 Q60 64 70 58" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
      ${tube("M50 46 Q42 52 42 62", c.body, c.line, 6)}${fist(42, 63, c, 5)}
      ${tube("M70 46 Q78 52 78 62", c.body, c.line, 6)}${fist(78, 63, c, 5)}
      <circle cx="60" cy="26" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <path d="M53 17 Q42 9 37 18 Q34 26 41 27 Q37 22 42 19 Q48 17 53 21 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M67 17 Q78 9 83 18 Q86 26 79 27 Q83 22 78 19 Q72 17 67 21 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${ceye(55, 26, 3.4)}${ceye(65, 26, 3.4)}
      <path d="M58 30 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 33, 2.8, INK)}
      <g class="tail-wag"><rect x="29" y="52" width="14" height="13" rx="2" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><path d="M33 52 v13 M37 52 v13 M41 52 v13" stroke="${c.line}" stroke-width="1"/></g>
    </g>`; },

  // ── Centaur — horse body & four legs, human torso rising at the front, sweeping tail (profile, right)
  centaur: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 32)}
    <g class="tail-wag">
      <path d="M26 66 Q10 64 8 84 Q16 78 22 74 Q12 90 22 96 Q24 78 34 72 Q40 68 32 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M26 74 C26 60 42 56 62 57 C78 58 86 62 86 72 C86 84 74 86 60 86 C40 86 26 84 26 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M34 82 Q56 90 82 82 Q56 88 34 82 Z" fill="${B}"/>
      <rect x="32" y="82" width="9" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="46" y="84" width="9" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="66" y="84" width="9" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="76" y="82" width="9" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="31" y="101" width="11" height="5" rx="1.5" fill="${c.line}"/><rect x="45" y="101" width="11" height="5" rx="1.5" fill="${c.line}"/>
      <rect x="65" y="101" width="11" height="5" rx="1.5" fill="${c.line}"/><rect x="75" y="101" width="11" height="5" rx="1.5" fill="${c.line}"/>
    </g>
    <g class="breathe">
      <path d="M70 60 Q70 42 82 40 Q94 40 96 52 L94 64 Q84 68 74 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M76 50 Q84 56 92 50" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
      ${tube("M78 46 Q72 54 70 62", c.body, c.line, 5)}${fist(70, 63, c, 4.5)}
      ${tube("M92 46 Q100 52 100 62", c.body, c.line, 5)}${fist(100, 63, c, 4.5)}
      <circle cx="86" cy="30" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M77 26 Q74 16 82 18 Q80 22 82 27 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${ceye(83, 30, 2.8)}${ceye(91, 30, 2.8)}
      ${smile(86, 33, 2.4, INK)}
    </g>`; },

  // ── Harpy — bird-woman, broad feathered wings, flowing hair, taloned bird legs (float)
  harpy: (c) => { const B = belly(c); const wing = `
      <path d="M58 56 Q32 40 16 50 Q28 54 30 60 Q18 62 14 74 Q30 74 42 66 Q34 76 36 86 Q50 76 58 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M52 58 Q36 48 24 52 M48 64 Q34 60 26 66" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".55"/>`; return `
    ${floorShadow(60, 114, 20)}
    <g class="tail-wag">${wing}</g>
    ${mirror(`<g class="tail-wag">${wing}</g>`)}
    <g class="breathe">
      <path d="M60 40 Q76 44 76 64 Q76 84 60 90 Q44 84 44 64 Q44 44 60 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M52 66 q8 4 16 0 M54 74 q6 3 12 0 M56 82 q4 2 8 0" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".7"/>
      ${tube("M52 88 Q50 98 52 105", HORN, c.line, 4)}<path d="M52 105 l-4 4 M52 105 l0 5 M52 105 l4 4" stroke="${HORN}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      ${tube("M68 88 Q70 98 68 105", HORN, c.line, 4)}<path d="M68 105 l-4 4 M68 105 l0 5 M68 105 l4 4" stroke="${HORN}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      <circle cx="60" cy="34" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M46 32 Q46 18 60 18 Q74 18 74 32 Q68 24 60 26 Q52 24 46 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M45 34 Q40 44 44 54 M75 34 Q80 44 76 54" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round"/>
      ${ceye(54, 33, 3.6)}${ceye(66, 33, 3.6)}
      <path d="M58 37 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 40, 2.4, INK)}
    </g>`; },

  // ── Gargoyle — crouching stone guardian, scalloped bat wings, back-swept horns, fanged, cracked (front)
  gargoyle: (c) => { const B = belly(c), D = deepen(c.body, .15); const wing = `<g class="tail-wag"><path d="M50 56 Q28 34 14 42 Q24 46 24 54 Q14 54 10 64 L22 60 Q16 68 18 78 L28 66 Q28 74 36 74 L40 60 Q46 58 52 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>`; return `
    ${floorShadow(60, 112, 28)}
    ${wing}
    ${mirror(wing)}
    <g class="breathe">
      <path d="M44 62 Q42 50 60 50 Q78 50 76 62 Q80 76 72 84 L72 98 L62 98 L62 88 L58 88 L58 98 L48 98 L48 84 Q40 76 44 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 98 l-4 3 m4 -3 l0 5 m0 -5 l4 3 M62 98 l-4 3 m4 -3 l0 5 m0 -5 l4 3 M58 98 l-4 3 m4 -3 l0 5 m0 -5 l4 3 M72 98 l-4 3 m4 -3 l0 5 m0 -5 l4 3" stroke="${D}" stroke-width="2" stroke-linecap="round"/>
      <ellipse cx="60" cy="70" rx="13" ry="10" fill="${B}"/>
      <path d="M48 40 Q42 28 36 26 Q42 34 44 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M72 40 Q78 28 84 26 Q78 34 76 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M44 42 Q44 28 60 28 Q76 28 76 42 Q76 54 60 56 Q44 54 44 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${ceye(53, 40, 3.6)}${ceye(67, 40, 3.6)}
      <path d="M50 47 Q60 56 70 47 Q60 51 50 47 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M52 48 l2 4 l2 -4 Z M64 48 l2 4 l2 -4 Z" fill="${TUSK}"/>
      <path d="M50 62 l6 3 M70 62 l-6 3" stroke="${c.line}" stroke-width="1" opacity=".5"/>
    </g>`; },

  // ── Treant — walking tree, leafy crown, bark trunk with a knothole face, branch arms, root legs (front)
  treant: (c) => { const B = belly(c), D = deepen(c.body, .18); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      ${tube("M48 60 Q34 52 26 40", c.body, c.line, 6)}${pom(24, 36, 10, c.shade, c.line, 7, 2.2)}
      ${tube("M72 60 Q86 52 94 40", c.body, c.line, 6)}${pom(96, 36, 10, c.shade, c.line, 7, 2.2)}
    </g>
    <g class="breathe">
      ${pom(60, 32, 26, c.shade, c.line, 12, 2.8)}
      ${pom(50, 26, 13, B, c.line, 8, 2)}
      <path d="M46 44 Q44 62 46 84 L40 104 Q46 108 52 104 L54 86 L66 86 L68 104 Q74 108 80 104 L74 84 Q76 62 74 44 Q60 38 46 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 50 Q54 70 52 88 M68 50 Q66 70 68 88 M60 54 v34" fill="none" stroke="${D}" stroke-width="1.6" opacity=".55"/>
      ${ceye(53, 60, 3.8)}${ceye(67, 60, 3.8)}
      <path d="M54 70 Q60 77 66 70 Q60 80 54 70 Z" fill="${D}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>`; },

  // ── Nymph — graceful nature spirit, flowing side-locks, flower crown, lit face, leaf-petal gown (front)
  nymph: (c) => { const B = belly(c), D = deepen(c.body, .15); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      <path d="M48 38 Q34 48 34 68 Q34 84 42 94 Q40 78 46 66 Q43 78 50 86 Q49 62 52 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M72 38 Q86 48 86 68 Q86 84 78 94 Q80 78 74 66 Q77 78 70 86 Q71 62 68 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M52 46 Q52 42 60 42 Q68 42 68 46 L74 66 Q80 90 60 104 Q40 90 46 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M56 48 Q60 46 64 48 L70 72 Q66 92 60 100 Q54 92 50 72 Z" fill="${B}"/>
      <path d="M46 66 l-7 8 l9 -2 M74 66 l7 8 l-9 -2 M50 86 l-8 8 l10 -1 M70 86 l8 8 l-10 -1" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${tube("M54 50 Q46 58 46 68", c.body, c.line, 4.5)}${fist(46, 70, c, 4)}
      ${tube("M66 50 Q74 58 74 68", c.body, c.line, 4.5)}${fist(74, 70, c, 4)}
      <circle cx="60" cy="33" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <ellipse cx="60" cy="37" rx="10" ry="8" fill="${B}"/>
      ${[46,53,60,67,74].map((x,i)=>`<circle cx="${x}" cy="${23-(i===2?3:i===1||i===3?1:0)}" r="4.2" fill="${B}" stroke="${c.line}" stroke-width="1.4"/><circle cx="${x}" cy="${23-(i===2?3:i===1||i===3?1:0)}" r="1.7" fill="${HORN}"/>`).join("")}
      ${ceye(54, 34, 3.4)}${ceye(66, 34, 3.4)}
      <ellipse cx="49" cy="39" rx="2.6" ry="1.8" fill="${HORN}" opacity=".35"/><ellipse cx="71" cy="39" rx="2.6" ry="1.8" fill="${HORN}" opacity=".35"/>
      <path d="M58 38 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 41, 2.6, INK)}
    </g>`; },

  // ── Pixie — tiny chibi sprite, big head, pointed ears, little round wings, rosy cheeks (float)
  pixie: (c) => { const B = belly(c); const wing = `<g class="tail-wag"><path d="M56 56 Q42 42 34 52 Q40 58 46 58 Q38 66 44 74 Q52 68 56 60 Z" fill="${B}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round" opacity=".85"/></g>`; return `
    ${floorShadow(60, 114, 18)}
    ${wing}
    ${mirror(wing)}
    <g class="breathe">
      <path d="M60 60 Q50 60 50 72 Q50 84 60 84 Q70 84 70 72 Q70 60 60 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${tube("M54 82 Q52 90 54 96", c.body, c.line, 4)}${tube("M66 82 Q68 90 66 96", c.body, c.line, 4)}
      <circle cx="60" cy="42" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M44 42 L34 32 L47 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M76 42 L86 32 L73 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M46 40 Q46 26 60 26 Q74 26 74 40 Q68 33 60 34 Q52 33 46 40 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="50" rx="10" ry="6" fill="${B}"/>
      ${ceye(53, 44, 4.4)}${ceye(67, 44, 4.4)}
      <path d="M58 50 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 53, 3, INK)}
      <circle cx="49" cy="50" r="2.2" fill="${HORN}" opacity=".4"/><circle cx="71" cy="50" r="2.2" fill="${HORN}" opacity=".4"/>
    </g>`; },

  // ── Kobold — little lizard-dog, snouted muzzle, small head-spikes, scaly belly, tapering tail (front)
  kobold: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      ${tube("M64 96 Q86 96 92 78 Q94 70 88 68", c.body, c.line, 6)}
      <path d="M88 68 l6 -3 l-1 8 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 50 C50 50 45 56 45 66 C45 78 42 92 48 100 Q60 106 72 100 C78 92 75 78 75 66 C75 56 70 50 60 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M52 66 h16 M52 74 h16 M54 82 h12" stroke="${c.shade}" stroke-width="2" stroke-linecap="round" opacity=".65"/>
      ${foot(50, 104, c, 7, 5)}${foot(70, 104, c, 7, 5)}
      ${tube("M47 66 Q38 74 40 84", c.body, c.line, 5)}${fist(41, 86, c, 4.5)}
      ${tube("M73 66 Q82 74 80 84", c.body, c.line, 5)}${fist(79, 86, c, 4.5)}
      <path d="M46 30 l-4 -11 l9 7 Z M74 30 l4 -11 l-9 7 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M48 44 Q48 30 60 30 Q72 30 72 44 Q72 50 66 52 L66 59 Q60 63 54 59 L54 52 Q48 50 48 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M54 52 Q60 58 66 52 L66 59 Q60 63 54 59 Z" fill="${B}"/>
      <ellipse cx="56" cy="57" rx="1.4" ry="1.1" fill="${INK}"/><ellipse cx="64" cy="57" rx="1.4" ry="1.1" fill="${INK}"/>
      ${ceye(53, 42, 3.4)}${ceye(67, 42, 3.4)}
    </g>`; },

  // ── Bugbear — big hairy goblinoid, shaggy fur, pointed ears, broad nose, fangs (front)
  bugbear: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      ${pom(30, 70, 11, c.body, c.line, 8, 2.6)}${pom(90, 70, 11, c.body, c.line, 8, 2.6)}
    </g>
    <g class="breathe">
      ${pom(60, 82, 27, c.body, c.line, 13, 2.8)}
      <ellipse cx="60" cy="86" rx="15" ry="13" fill="${c.shade}" opacity=".45"/>
      ${pom(46, 104, 9, c.body, c.line, 7, 2.4)}${pom(74, 104, 9, c.body, c.line, 7, 2.4)}
      <path d="M40 46 L26 30 L48 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M39 44 L30 33 L46 47 Z" fill="${c.shade}" opacity=".65"/>
      <path d="M80 46 L94 30 L72 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M81 44 L90 33 L74 47 Z" fill="${c.shade}" opacity=".65"/>
      ${pom(60, 48, 20, c.body, c.line, 11, 2.6)}
      <ellipse cx="60" cy="54" rx="13" ry="10" fill="${B}"/>
      ${ceye(53, 46, 4)}${ceye(67, 46, 4)}
      <ellipse cx="60" cy="54" rx="3.4" ry="2.6" fill="${INK}"/>
      <path d="M50 60 Q60 70 70 60 Q60 64 50 60 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M53 61 l2 5 l2 -5 Z M63 61 l2 5 l2 -5 Z" fill="${TUSK}"/>
    </g>`; },

  // ── Gremlin — small manic critter, big floppy bat-ears, back spikes, wide toothy grin, claws (front)
  gremlin: (c) => { const B = belly(c), D = deepen(c.body, .18); return `
    ${floorShadow(60, 112, 24)}
    <g class="breathe">
      <path d="M60 48 C50 48 45 54 45 64 C43 66 43 70 46 70 C45 82 42 94 48 100 Q60 106 72 100 C78 94 75 82 74 70 C77 70 77 66 75 64 C75 54 70 48 60 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M51 52 l-3 -6 l5 3 Z M60 50 l0 -7 l3 6 Z M69 52 l3 -6 l-5 3 Z" fill="${D}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${foot(50, 104, c, 7, 5)}${foot(70, 104, c, 7, 5)}
      ${tube("M46 66 Q35 72 34 84", c.body, c.line, 5)}<path d="M34 84 l-3 5 m3 -5 l0 6 m0 -6 l3 5" stroke="${c.line}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      ${tube("M74 66 Q85 72 86 84", c.body, c.line, 5)}<path d="M86 84 l-3 5 m3 -5 l0 6 m0 -6 l3 5" stroke="${c.line}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <path d="M45 44 Q22 40 16 52 Q28 52 34 50 Q26 58 30 66 Q40 56 48 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M75 44 Q98 40 104 52 Q92 52 86 50 Q94 58 90 66 Q80 56 72 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 48 Q26 48 22 56 M80 48 Q94 48 98 56" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".55"/>
      <circle cx="60" cy="44" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <ellipse cx="60" cy="50" rx="11" ry="7" fill="${B}"/>
      ${ceye(53, 42, 4.6)}${ceye(67, 42, 4.6)}
      <path d="M58 48 l-2 2 h4 Z" fill="${INK}"/>
      <path d="M48 53 Q60 64 72 53 Q60 60 48 53 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M50 54 h20" stroke="${TUSK}" stroke-width="2" stroke-linecap="round"/>
      <path d="M53 54 v4 M58 54.5 v5 M63 54.5 v5 M68 54 v4" stroke="${c.line}" stroke-width="0.8"/>
    </g>`; },

  // ── Leprechaun — wee fellow, buckled top-hat, big curly beard, buttoned coat & belt (front)
  leprechaun: (c) => { const B = belly(c), D = deepen(c.body, .2); return `
    ${floorShadow(60, 112, 22)}
    <g class="breathe">
      <path d="M60 54 C50 54 46 60 46 70 C46 82 43 94 49 100 Q60 106 71 100 C77 94 74 82 74 70 C74 60 70 54 60 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 58 L60 100" stroke="${D}" stroke-width="1.6" opacity=".5"/>
      <circle cx="60" cy="66" r="1.6" fill="${HORN}"/><circle cx="60" cy="74" r="1.6" fill="${HORN}"/>
      <rect x="54" y="80" width="12" height="7" rx="1" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/><rect x="58" y="81.5" width="4" height="4" fill="${HORN}"/>
      ${foot(50, 104, c, 7, 5)}${foot(70, 104, c, 7, 5)}
      ${tube("M47 68 Q37 74 39 86", c.body, c.line, 5)}${fist(40, 88, c, 4.5)}
      ${tube("M73 68 Q83 74 81 86", c.body, c.line, 5)}${fist(80, 88, c, 4.5)}
      <circle cx="60" cy="44" r="15" fill="${B}" stroke="${c.line}" stroke-width="2.8"/>
      ${pom(60, 56, 15, c.shade, c.line, 10, 2.4)}
      <path d="M46 50 Q44 60 50 66 M74 50 Q76 60 70 66" fill="none" stroke="${c.shade}" stroke-width="4" stroke-linecap="round"/>
      ${ceye(54, 42, 3.4)}${ceye(66, 42, 3.4)}
      <ellipse cx="49" cy="48" rx="3" ry="2" fill="${HORN}" opacity=".4"/><ellipse cx="71" cy="48" rx="3" ry="2" fill="${HORN}" opacity=".4"/>
      <path d="M58 46 l-2 2 h4 Z" fill="${INK}"/>
      <g class="tail-wag">
        <ellipse cx="60" cy="28" rx="20" ry="4.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
        <rect x="48" y="11" width="24" height="18" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
        <rect x="48" y="22" width="24" height="6" fill="${D}"/>
        <rect x="55" y="22" width="10" height="6" fill="${HORN}" stroke="${c.line}" stroke-width="1.4"/>
      </g>
    </g>`; },

  // ── Djinn — genie rising from a wisp of smoke, broad folded-arm torso, waist sash, topknot, hoops (float)
  djinn: (c) => { const B = belly(c), D = deepen(c.body, .15); return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      <path d="M48 74 Q40 90 48 102 Q53 95 57 102 Q60 96 63 102 Q67 95 72 102 Q80 88 72 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M54 84 Q60 90 66 84" fill="none" stroke="${D}" stroke-width="1.6" opacity=".55"/>
    </g>
    <g class="breathe">
      <path d="M60 40 Q86 42 84 62 Q82 72 60 74 Q38 72 36 62 Q34 42 60 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 56 Q30 58 30 66 Q35 62 42 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 56 Q90 58 90 66 Q85 62 78 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="53" rx="16" ry="9" fill="${B}"/>
      <path d="M42 60 Q60 70 78 60 Q74 66 60 67 Q46 66 42 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <rect x="45" y="70" width="30" height="7" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <path d="M60 70 l-4 7 h8 Z" fill="${D}"/>
      <circle cx="60" cy="28" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      ${tube("M60 16 L60 7", c.body, c.line, 3)}<circle cx="60" cy="6" r="3.6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M47 28 Q42 28 42 32 Q47 32 47 28 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M73 28 Q78 28 78 32 Q73 32 73 28 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.4"/>
      ${ceye(54, 28, 3.6)}${ceye(66, 28, 3.6)}
      <path d="M58 32 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 35, 2.4, INK)}
      <path d="M55 38 Q60 44 65 38" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>`; },

  // ── Will-o'-Wisp — floating flame spirit, glowing aura, cute face, trailing sparks (float)
  willowisp: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 16)}
    <ellipse cx="60" cy="58" rx="30" ry="34" fill="${GLOW}" opacity=".18"/>
    <g class="tail-wag">
      <circle cx="52" cy="98" r="3.5" fill="${c.body}" stroke="${c.line}" stroke-width="1.6"/>
      <circle cx="66" cy="104" r="2.6" fill="${c.body}" stroke="${c.line}" stroke-width="1.4"/>
    </g>
    <g class="breathe">
      <path d="M60 22 Q78 44 74 66 Q72 86 60 90 Q48 86 46 66 Q42 44 60 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M60 40 Q70 54 67 70 Q65 82 60 84 Q55 82 53 70 Q50 54 60 40 Z" fill="${B}"/>
      <path d="M60 54 Q66 64 64 74 Q62 80 60 80 Q58 80 56 74 Q54 64 60 54 Z" fill="${FIRE2}" opacity=".85"/>
      ${ceye(54, 62, 4)}${ceye(66, 62, 4)}
      <path d="M55 71 Q60 76 65 71" fill="none" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="49" cy="66" r="2.4" fill="${FIRE}" opacity=".3"/><circle cx="71" cy="66" r="2.4" fill="${FIRE}" opacity=".3"/>
    </g>`; },

  // ── Mandrake — pulled-up root creature, leafy sprout, forked root legs & arms, wailing knot face (front)
  mandrake: (c) => { const B = belly(c), D = deepen(c.body, .18); return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      <path d="M60 22 Q54 6 60 4 Q66 6 60 22 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M50 26 Q38 12 44 8 Q52 14 56 26 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M70 26 Q82 12 76 8 Q68 14 64 26 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 28 C46 28 42 40 44 56 C45 70 40 78 42 88 Q46 96 52 90 Q54 100 60 100 Q66 100 68 90 Q74 96 78 88 Q80 78 75 70 Q78 40 60 28 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 82 L46 96 M60 88 L60 100 M70 82 L74 96" fill="none" stroke="${D}" stroke-width="2" stroke-linecap="round"/>
      ${tube("M46 54 Q36 60 34 72", c.body, c.line, 5)}
      ${tube("M74 54 Q84 60 86 72", c.body, c.line, 5)}
      <ellipse cx="60" cy="56" rx="15" ry="14" fill="${B}"/>
      <path d="M46 48 q6 -3 11 0 M63 48 q6 -3 11 0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${ceye(53, 52, 4)}${ceye(67, 52, 4)}
      <ellipse cx="60" cy="61" rx="5" ry="6" fill="${INK}"/>
      <ellipse cx="60" cy="60" rx="2.4" ry="2.6" fill="${B}"/>
    </g>`; },

  // ── Homunculus — little alchemical humanoid, oversized head, body seams, glowing chest rune, topknot (front)
  homunculus: (c) => { const B = belly(c), D = deepen(c.body, .15); return `
    ${floorShadow(60, 112, 22)}
    <g class="breathe">
      <path d="M60 54 C51 54 47 60 47 68 C47 80 44 94 50 100 Q60 106 70 100 C76 94 73 80 73 68 C73 60 69 54 60 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M52 66 L68 66 M56 60 v40 M64 60 v40" fill="none" stroke="${D}" stroke-width="1" opacity=".5" stroke-dasharray="2 2"/>
      <path d="M60 72 l6 6 l-6 6 l-6 -6 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${foot(51, 104, c, 6.5, 5)}${foot(69, 104, c, 6.5, 5)}
      ${tube("M48 66 Q38 72 40 84", c.body, c.line, 4.5)}${fist(41, 86, c, 4)}
      ${tube("M72 66 Q82 72 80 84", c.body, c.line, 4.5)}${fist(79, 86, c, 4)}
      <circle cx="60" cy="40" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      ${tube("M60 22 L60 12", c.body, c.line, 3)}<circle cx="60" cy="11" r="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M43 40 q-3 0 -3 3 M77 40 q3 0 3 3" fill="none" stroke="${D}" stroke-width="1.2" stroke-dasharray="2 2"/>
      <ellipse cx="60" cy="46" rx="12" ry="8" fill="${B}"/>
      ${ceye(53, 40, 4.6)}${ceye(67, 40, 4.6)}
      <path d="M58 46 l-2 2 h4 Z" fill="${INK}"/>
      ${smile(60, 49, 3, INK)}
    </g>`; },

  // ── Golem Knight — armoured construct, crested helm with glowing visor, pauldrons, greatsword (front)
  golemknight: (c) => { const B = belly(c), D = deepen(c.body, .15), M = tint(c.body, .22); return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M80 70 L86 40 L92 40 L90 72 Z" fill="${M}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M83 40 L89 40 L86 24 Z" fill="${M}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <rect x="80" y="68" width="14" height="5" rx="1.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
    </g>
    <g class="breathe">
      <path d="M40 60 L58 55 L80 60 L84 92 L60 100 L36 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 60 L58 58 L66 60 L64 78 L56 78 Z" fill="${M}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="60" cy="68" r="2.6" fill="${GLOW}"/>
      <path d="M42 90 L38 100 L48 100 Z M78 90 L72 100 L82 100 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M34 60 L24 66 L26 82 L38 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M86 60 L96 66 L94 82 L82 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <circle cx="30" cy="82" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="90" cy="82" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 40 L60 34 L76 40 L78 54 Q60 60 42 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 46 L76 46 L74 52 Q60 56 46 52 Z" fill="${INK}"/>
      <circle cx="53" cy="49" r="2.4" fill="${GLOW}"/><circle cx="67" cy="49" r="2.4" fill="${GLOW}"/>
      <path d="M60 34 L60 26 M52 37 L48 30 M68 37 L72 30" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      <rect x="55" y="54" width="10" height="4" fill="${D}"/>
    </g>`; },
};

export const ROSTER_FANTASYBEASTS = [
  { n: "Ogre",        e: "👹", tier: 3, float: false },
  { n: "Troll",       e: "🧌", tier: 3, float: false },
  { n: "Goblin",      e: "👺", tier: 2, float: false },
  { n: "Imp",         e: "😈", tier: 2, float: false },
  { n: "Satyr",       e: "🐐", tier: 3, float: false },
  { n: "Centaur",     e: "🏹", tier: 4, float: false },
  { n: "Harpy",       e: "🪶", tier: 3, float: true },
  { n: "Gargoyle",    e: "🦇", tier: 3, float: false },
  { n: "Treant",      e: "🌳", tier: 4, float: false },
  { n: "Nymph",       e: "🌸", tier: 3, float: false },
  { n: "Pixie",       e: "✨", tier: 2, float: true },
  { n: "Kobold",      e: "🦎", tier: 2, float: false },
  { n: "Bugbear",     e: "🐻", tier: 3, float: false },
  { n: "Gremlin",     e: "👾", tier: 2, float: false },
  { n: "Leprechaun",  e: "🍀", tier: 3, float: false },
  { n: "Djinn",       e: "🧞", tier: 4, float: true },
  { n: "Will-o-Wisp", e: "🔥", tier: 2, float: true },
  { n: "Mandrake",    e: "🌱", tier: 3, float: false },
  { n: "Homunculus",  e: "🧪", tier: 3, float: false },
  { n: "Golem Knight",e: "🛡️", tier: 4, float: false },
];
