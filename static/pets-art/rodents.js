// pets-art/rodents.js — BESPOKE hand-drawn SVG art for RODENTS & SMALL MAMMALS (NADO Pets).
// Each entry is an original, on-spot drawing of ONE species — no shared/parameterized bodies.
// Contract: inner markup of <svg viewBox="0 0 120 120">, animal centered ~(60,62), within x,y ∈ [8,112].
// Coat comes from `c`: c.body (fill), c.shade (accent/underside/belly/spots/dark legs), c.line (outline).
// Nose/eyes = INK/eyeInk; teeth = #fff; fixed off-white (WHT) only for markings that are a highlight,
// not the coat (e.g. the red panda's white face). Animate: torso <g class="breathe">, head
// <g class="head-tilt">, tails/ears-that-flick <g class="tail-wag">. Gliders set float:true (they drift).
import { pom, tube, eyes, eye, eyeInk, INK, mirror } from "../pets-draw.js";

const WHT = "#fbf6ee";   // white face markings / blaze (a highlight, not the coat)

// a round rodent ear: outer coat disc + inner darker cup
const rEar = (x, y, r, c) =>
  `<circle cx="${x}" cy="${y}" r="${r}" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="${x}" cy="${y}" r="${(r * 0.5).toFixed(1)}" fill="${c.shade}" opacity=".7"/>`;
// a pair of buck incisors under a nose point
const buck = (x, y) =>
  `<path d="M${x - 2.6} ${y} h5.2 v4.5 q-2.6 2 -5.2 0 Z" fill="#fff" stroke="${INK}" stroke-width="0.9" stroke-linejoin="round"/><line x1="${x}" y1="${y}" x2="${x}" y2="${y + 4.5}" stroke="${INK}" stroke-width="0.8"/>`;
// fanned whiskers sweeping left / right from a muzzle point
const whiskersL = (x, y) =>
  `<path d="M${x} ${y} q-9 -2 -18 -4 M${x} ${y + 2} q-9 0 -18 2 M${x} ${y + 4} q-9 3 -17 7" stroke="${INK}" stroke-width="0.9" fill="none" opacity=".4" stroke-linecap="round"/>`;
const whiskersR = (x, y) =>
  `<path d="M${x} ${y} q9 -2 18 -4 M${x} ${y + 2} q9 0 18 2 M${x} ${y + 4} q9 3 17 7" stroke="${INK}" stroke-width="0.9" fill="none" opacity=".4" stroke-linecap="round"/>`;

export const ART_RODENTS = {
  // ── MUSTELIDS ───────────────────────────────────────────────────────────────
  // Ferret — long slinky low body, front-facing bandit mask across pale eyes, small round ears, four short legs
  ferret: (c) => `
    <g class="tail-wag">${tube("M34 80 Q14 84 10 66 Q9 58 15 56", c.body, c.line, 7)}</g>
    ${[46, 72].map((x) => `<rect x="${x}" y="82" width="7" height="16" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    <g class="breathe">
      <path d="M28 76 Q32 58 56 58 Q84 58 86 74 Q86 90 56 90 Q30 90 28 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M38 82 Q56 90 72 83 Q68 90 56 90 Q42 90 38 82 Z" fill="${c.shade}" opacity=".7"/>
    </g>
    ${[52, 64].map((x) => `<rect x="${x}" y="82" width="7" height="16" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    <g class="head-tilt">
      ${rEar(60, 38, 6, c)}${rEar(84, 38, 6, c)}
      <circle cx="72" cy="52" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M58 54 Q72 48 86 54 Q86 66 72 68 Q58 66 58 54 Z" fill="${c.shade}" opacity=".85"/>
      <path d="M56 50 Q72 44 88 50 Q88 58 82 58 Q72 54 62 58 Q56 58 56 50 Z" fill="${INK}" opacity=".8"/>
      <circle cx="64" cy="52" r="2.7" fill="#fff"/><circle cx="64" cy="52" r="1.4" fill="${INK}"/>
      <circle cx="80" cy="52" r="2.7" fill="#fff"/><circle cx="80" cy="52" r="1.4" fill="${INK}"/>
      <ellipse cx="72" cy="60" rx="2.6" ry="2" fill="${INK}"/>
      <path d="M72 62 q0 3 -3 4 M72 62 q0 3 3 4" stroke="${INK}" stroke-width="1.2" fill="none"/>
      ${whiskersL(68, 61)}${whiskersR(76, 61)}
    </g>`,

  // Weasel — slender upright "periscope" pose on hind feet, long neck, tiny front paws, small head, plain tail
  weasel: (c) => `
    <g class="tail-wag">${tube("M50 92 Q30 100 26 84 Q25 78 30 78", c.body, c.line, 6)}</g>
    ${[54, 66].map((x) => `<ellipse cx="${x}" cy="100" rx="4.5" ry="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="breathe">
      <path d="M46 98 Q40 60 52 48 Q60 42 68 48 Q80 60 74 98 Q60 106 46 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 60 Q60 56 66 60 Q68 88 60 96 Q52 88 54 60 Z" fill="${c.shade}"/>
    </g>
    <ellipse cx="55" cy="76" rx="3.2" ry="4.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    <ellipse cx="65" cy="76" rx="3.2" ry="4.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    <g class="head-tilt">
      ${rEar(52, 28, 5, c)}${rEar(68, 28, 5, c)}
      <path d="M48 40 Q48 26 60 24 Q72 26 72 40 Q72 52 60 56 Q48 52 48 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 44 Q60 40 66 44 Q66 52 60 56 Q54 52 54 44 Z" fill="${c.shade}" opacity=".8"/>
      <ellipse cx="60" cy="52" rx="2.4" ry="1.8" fill="${INK}"/>
      ${eyes(54, 66, 40, 2.6, eyeInk(c))}
      ${whiskersL(56, 51)}${whiskersR(64, 51)}
    </g>`,

  // Stoat — low bounding arch mid-leap, four striding legs, alert pointed head at right, BLACK-TIPPED tail
  stoat: (c) => `
    <g class="tail-wag">
      ${tube("M40 78 Q22 76 15 62", c.body, c.line, 6)}
      ${tube("M19 68 Q14 62 12 55", INK, INK, 6)}
    </g>
    <rect x="36" y="80" width="6" height="16" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
    <rect x="46" y="82" width="6" height="15" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <g class="breathe">
      <path d="M36 78 Q34 50 62 48 Q88 50 88 74 Q78 88 60 86 Q44 88 36 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 80 Q64 88 80 78 Q76 86 62 86 Q52 86 50 80 Z" fill="${c.shade}" opacity=".7"/>
    </g>
    <rect x="70" y="80" width="6" height="16" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    <rect x="80" y="78" width="6" height="16" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
    <g class="head-tilt">
      ${rEar(80, 44, 5, c)}
      <path d="M74 56 Q74 44 88 42 Q102 44 102 58 Q102 70 90 72 Q76 70 74 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M92 62 Q104 62 104 70 Q96 74 88 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="103" cy="66" rx="2.4" ry="1.8" fill="${INK}"/>
      ${eye(88, 54, 2.8, eyeInk(c))}
      ${whiskersR(100, 66)}
    </g>`,

  // ── CHINCHILLA & LARGE RODENTS ────────────────────────────────────────────────
  // Chinchilla — plush round ball, HUGE round mouse-ears, big eyes, bushy squirrel-tail, tiny hands (tier 2)
  chinchilla: (c) => `
    <g class="tail-wag">
      <path d="M40 84 Q18 84 16 62 Q16 50 28 50 Q24 62 30 74 Q34 82 44 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M22 56 q6 10 14 18" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".4"/>
    </g>
    <g class="breathe">
      ${pom(60, 74, 26, c.body, c.line, 12, 2.4)}
      <path d="M44 78 Q60 92 76 78 Q74 90 60 92 Q46 90 44 78 Z" fill="${c.shade}" opacity=".55"/>
    </g>
    <ellipse cx="52" cy="87" rx="4" ry="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    <ellipse cx="68" cy="87" rx="4" ry="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    <g class="head-tilt">
      ${rEar(39, 33, 13, c)}${rEar(81, 33, 13, c)}
      <circle cx="60" cy="52" r="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 58 Q60 52 68 58 Q68 68 60 72 Q52 68 52 58 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="60" cy="61" rx="2.6" ry="2" fill="${INK}"/>
      <path d="M60 63 q0 3 -3 4 M60 63 q0 3 3 4" stroke="${INK}" stroke-width="1.1" fill="none"/>
      ${eyes(52, 68, 50, 4, eyeInk(c))}
      ${whiskersL(56, 60)}${whiskersR(64, 60)}
    </g>`,

  // Capybara — huge barrel body in profile, blocky rectangular head, tiny ears, small eye, no tail, zen calm (tier 2)
  capybara: (c) => `
    ${[46, 74].map((x) => `<rect x="${x}" y="86" width="9" height="18" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    <g class="breathe">
      <path d="M26 66 Q26 52 48 52 L82 52 Q98 54 98 72 Q98 90 72 90 L40 90 Q26 88 26 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M34 86 Q60 92 86 86 Q82 90 60 90 Q40 90 34 86 Z" fill="${c.shade}" opacity=".5"/>
    </g>
    ${[40, 68].map((x) => `<rect x="${x}" y="86" width="9" height="18" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    <g class="head-tilt">
      <path d="M82 52 Q84 40 98 40 Q110 42 108 60 Q108 74 94 76 Q82 74 82 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M102 54 Q110 56 108 66 Q102 70 98 66 Z" fill="${c.shade}" opacity=".6"/>
      <circle cx="88" cy="40" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="88" cy="40" r="2" fill="${c.shade}"/>
      <ellipse cx="106" cy="58" rx="2" ry="1.4" fill="${INK}"/>
      ${eye(93, 52, 2.8, eyeInk(c))}
      <path d="M99 67 q4 2 8 0" stroke="${INK}" stroke-width="1.2" fill="none"/>
    </g>`,

  // ── MICE & KIN ────────────────────────────────────────────────────────────────
  // Gerbil — upright on big hind feet, TUFT-tipped tail, clutching a seed, round ears, big dark eyes
  gerbil: (c) => `
    <g class="tail-wag">${tube("M46 88 Q26 92 20 76", c.body, c.line, 4)}${pom(18, 72, 7, c.body, c.line, 7, 2)}</g>
    <g class="breathe">
      <path d="M44 92 Q40 60 60 56 Q80 60 78 92 Q62 100 44 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 74 Q60 70 68 74 Q70 90 60 96 Q50 90 52 74 Z" fill="${c.shade}" opacity=".7"/>
    </g>
    <path d="M46 94 Q40 100 50 102 L58 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    <path d="M74 94 Q80 100 70 102 L62 98 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    <ellipse cx="60" cy="80" rx="4" ry="3.4" fill="#f2c94c" stroke="${c.line}" stroke-width="1.4"/>
    <path d="M54 78 q4 4 4 6 M66 78 q-4 4 -4 6" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      ${rEar(50, 40, 7, c)}${rEar(70, 40, 7, c)}
      <circle cx="60" cy="52" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 56 Q60 52 64 56 Q66 64 60 68 Q54 64 56 56 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="60" cy="60" rx="2.2" ry="1.7" fill="${INK}"/>
      ${eyes(53, 67, 50, 3.4, eyeInk(c))}
      ${whiskersL(56, 60)}${whiskersR(64, 60)}
    </g>`,

  // Rat — sitting with paws up, big round hairless ears, long pointed snout, bare scaly whip-tail, bright eyes
  rat: (c) => `
    <g class="tail-wag">${tube("M48 90 Q22 96 14 74 Q12 66 18 64", c.shade, c.line, 3)}</g>
    <g class="breathe">
      <path d="M42 92 Q38 62 60 58 Q82 62 78 92 Q60 100 42 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 76 Q60 72 70 76 Q72 90 60 96 Q48 90 50 76 Z" fill="${c.shade}" opacity=".6"/>
    </g>
    ${[50, 70].map((x) => `<ellipse cx="${x}" cy="96" rx="5" ry="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <path d="M56 80 q-3 5 -6 6 M64 80 q3 5 6 6" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      ${rEar(48, 42, 9, c)}${rEar(72, 42, 9, c)}
      <path d="M46 52 Q46 40 60 38 Q74 40 76 54 Q80 66 60 74 Q44 66 46 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 64 Q60 58 66 64 Q66 74 60 76 Q54 74 54 64 Z" fill="${c.shade}" opacity=".8"/>
      <ellipse cx="60" cy="70" rx="2.8" ry="2.2" fill="${INK}"/>
      ${eyes(53, 67, 50, 2.8, eyeInk(c))}
      ${whiskersL(56, 68)}${whiskersR(64, 68)}
    </g>`,

  // Prairie Dog — upright sentinel on haunches, paws pressed together at chest, small ears, buck teeth, short tail
  prairiedog: (c) => `
    <g class="tail-wag"><path d="M74 96 Q86 98 84 88 Q78 90 72 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M46 98 Q42 58 60 50 Q78 58 76 98 Q62 106 46 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 68 Q60 64 68 68 Q70 94 60 100 Q50 94 52 68 Z" fill="${c.shade}" opacity=".6"/>
    </g>
    ${[50, 70].map((x) => `<ellipse cx="${x}" cy="100" rx="5" ry="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <path d="M56 72 q4 6 0 12 M64 72 q-4 6 0 12" stroke="${c.line}" stroke-width="2.2" fill="none" stroke-linecap="round"/>
    <ellipse cx="60" cy="85" rx="4" ry="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    <g class="head-tilt">
      <circle cx="47" cy="44" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="44" r="2" fill="${c.shade}"/>
      <circle cx="73" cy="44" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="73" cy="44" r="2" fill="${c.shade}"/>
      <circle cx="60" cy="46" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 50 Q60 46 64 50 Q66 58 60 62 Q54 58 56 50 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="60" cy="55" rx="2.4" ry="1.8" fill="${INK}"/>
      ${buck(60, 57)}
      ${eyes(53, 67, 44, 3, eyeInk(c))}
      ${whiskersL(56, 56)}${whiskersR(64, 56)}
    </g>`,

  // Groundhog — chunky woodchuck rearing out of a burrow hole, chubby cheeks, small ears, buck teeth
  groundhog: (c) => `
    <path d="M14 104 Q40 92 60 94 Q80 92 106 104 Z" fill="${c.shade}" opacity=".45"/>
    <ellipse cx="60" cy="100" rx="30" ry="8" fill="${INK}" opacity=".25"/>
    <g class="breathe">
      <path d="M40 100 Q34 62 60 54 Q86 62 80 100 Q60 96 40 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 72 Q60 66 70 72 Q72 96 60 100 Q48 96 50 72 Z" fill="${c.shade}" opacity=".55"/>
    </g>
    ${[50, 70].map((x) => `<ellipse cx="${x}" cy="92" rx="5" ry="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="head-tilt">
      <circle cx="48" cy="46" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="48" cy="46" r="2.2" fill="${c.shade}"/>
      <circle cx="72" cy="46" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="72" cy="46" r="2.2" fill="${c.shade}"/>
      <path d="M40 52 Q40 34 60 32 Q80 34 80 52 Q80 66 60 70 Q40 66 40 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 54 Q60 48 70 54 Q72 66 60 70 Q48 66 50 54 Z" fill="${c.shade}" opacity=".6"/>
      <ellipse cx="60" cy="58" rx="3" ry="2.2" fill="${INK}"/>
      ${buck(60, 60)}
      ${eyes(52, 68, 48, 2.8, eyeInk(c))}
      ${whiskersL(56, 59)}${whiskersR(64, 59)}
    </g>`,

  // Marmot — robust alpine sunbather lounging along a boulder (profile), stubby tail, stretched fore-paw, relaxed
  marmot: (c) => `
    <path d="M14 96 Q20 82 40 82 L86 84 Q104 86 106 100 Q106 106 60 106 Q16 106 14 96 Z" fill="${c.shade}" opacity=".4" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    <g class="tail-wag"><path d="M30 80 Q14 78 12 66 Q22 70 34 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 78 Q30 58 58 56 Q90 56 94 74 Q94 88 60 88 Q34 88 28 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 82 Q60 88 84 82 Q80 88 60 88 Q44 88 40 82 Z" fill="${c.shade}" opacity=".5"/>
    </g>
    <path d="M84 82 q10 2 14 6 l-9 3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    <g class="head-tilt">
      ${rEar(80, 40, 6, c)}${rEar(94, 41, 5.5, c)}
      <path d="M74 58 Q74 43 90 42 Q104 44 103 60 Q103 73 88 75 Q74 72 74 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M94 60 Q103 62 101 70 Q95 72 90 68 Z" fill="${c.shade}" opacity=".6"/>
      <ellipse cx="101" cy="63" rx="3" ry="2.4" fill="${INK}"/>
      <path d="M91 68 q4 3 8 1" stroke="${INK}" stroke-width="1.1" fill="none"/>
      ${eye(87, 55, 2.8, eyeInk(c))}
      ${whiskersR(99, 66)}
    </g>`,

  // Dormouse — tiny, HUGE eyes, small round ears, and a big fluffy curled squirrel-like tail wrapped beside it
  dormouse: (c) => `
    <g class="tail-wag">
      <path d="M46 88 Q22 96 22 72 Q22 54 40 52 Q30 64 34 78 Q38 88 50 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M30 60 q6 12 12 20" stroke="${c.line}" stroke-width="1.1" fill="none" opacity=".4"/>
    </g>
    <g class="breathe">
      <path d="M46 90 Q42 64 60 60 Q78 64 74 90 Q60 98 46 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 74 Q60 70 68 74 Q70 88 60 94 Q50 88 52 74 Z" fill="${c.shade}" opacity=".7"/>
    </g>
    ${[54, 66].map((x) => `<ellipse cx="${x}" cy="92" rx="3.6" ry="2.6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>`).join("")}
    <g class="head-tilt">
      ${rEar(50, 46, 6, c)}${rEar(70, 46, 6, c)}
      <circle cx="60" cy="56" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 60 Q60 56 64 60 Q66 68 60 72 Q54 68 56 60 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="60" cy="64" rx="2.2" ry="1.7" fill="${INK}"/>
      ${eyes(52, 68, 54, 4.2, eyeInk(c))}
      ${whiskersL(56, 64)}${whiskersR(64, 64)}
    </g>`,

  // Muskrat — semi-aquatic, back & head above a waterline, small ears, long laterally-flattened scaly tail
  muskrat: (c) => `
    <path d="M8 92 Q30 88 52 92 Q74 96 112 92" stroke="${c.shade}" stroke-width="2.4" fill="none" opacity=".6" stroke-linecap="round"/>
    <path d="M8 100 Q34 96 60 100 Q86 104 112 100" stroke="${c.shade}" stroke-width="2" fill="none" opacity=".4" stroke-linecap="round"/>
    <g class="tail-wag"><path d="M40 82 Q20 84 12 70 Q10 64 16 62 Q18 72 30 78 Q36 82 44 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M34 86 Q34 60 62 58 Q88 60 88 84 Q70 92 34 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 66 Q60 60 74 66 M46 74 Q60 70 74 74" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <circle cx="80" cy="51" r="4.2" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="80" cy="51" r="1.9" fill="${c.shade}"/>
      <path d="M74 58 Q74 47 90 45 Q102 46 106 56 L114 62 L106 67 Q100 73 88 74 Q74 70 74 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M98 61 Q108 62 112 62 Q108 68 100 68 Z" fill="${c.shade}" opacity=".6"/>
      <ellipse cx="112" cy="62" rx="2.2" ry="1.7" fill="${INK}"/>
      ${eye(88, 54, 2.6, eyeInk(c))}
      ${whiskersR(108, 64)}
    </g>`,

  // Pika — round potato "rock rabbit": big rounded mouse-ears, NO tail, short legs, compact and chunky
  pika: (c) => `
    <g class="breathe">
      ${pom(60, 72, 24, c.body, c.line, 11, 2.4)}
      <path d="M46 78 Q60 90 74 78 Q72 88 60 90 Q48 88 46 78 Z" fill="${c.shade}" opacity=".6"/>
    </g>
    ${[50, 70].map((x) => `<ellipse cx="${x}" cy="92" rx="5" ry="3.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="head-tilt">
      ${rEar(47, 45, 8, c)}${rEar(73, 45, 8, c)}
      <circle cx="60" cy="54" r="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 58 Q60 54 66 58 Q68 68 60 72 Q52 68 54 58 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="60" cy="62" rx="2.4" ry="1.8" fill="${INK}"/>
      <path d="M60 64 q0 3 -3 4 M60 64 q0 3 3 4" stroke="${INK}" stroke-width="1.1" fill="none"/>
      ${eyes(52, 68, 52, 3, eyeInk(c))}
      ${whiskersL(56, 62)}${whiskersR(64, 62)}
    </g>`,

  // Degu — Andean caviomorph: upright, larger pointed ears, and a long brush-TIPPED tail; front paws down
  degu: (c) => `
    <g class="tail-wag">${tube("M48 90 Q26 92 18 76", c.shade, c.line, 3.5)}${pom(15, 72, 6, c.body, c.line, 7, 2)}</g>
    <g class="breathe">
      <path d="M44 92 Q40 60 60 56 Q80 60 76 92 Q60 100 44 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 74 Q60 70 68 74 Q70 90 60 96 Q50 90 52 74 Z" fill="${c.shade}" opacity=".6"/>
    </g>
    ${[50, 70].map((x) => `<ellipse cx="${x}" cy="96" rx="4.6" ry="3.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <path d="M56 78 q-3 6 -6 8 M64 78 q3 6 6 8" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M46 40 Q42 24 52 26 Q56 34 54 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 40 Q78 24 68 26 Q64 34 66 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="60" cy="52" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 56 Q60 52 64 56 Q66 64 60 68 Q54 64 56 56 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="60" cy="60" rx="2.2" ry="1.7" fill="${INK}"/>
      ${eyes(52, 68, 50, 3, eyeInk(c))}
      ${whiskersL(56, 60)}${whiskersR(64, 60)}
    </g>`,

  // Vole — stubby compact loaf, BLUNT rounded nose, tiny ears buried in fur, short stubby tail (profile)
  vole: (c) => `
    <g class="tail-wag"><path d="M40 84 Q26 90 22 80 Q30 80 40 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M32 80 Q34 62 58 60 Q86 60 88 78 Q88 92 58 92 Q34 92 32 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M42 84 Q60 92 80 84 Q76 92 58 92 Q44 92 42 84 Z" fill="${c.shade}" opacity=".55"/>
    </g>
    ${[52, 72].map((x) => `<ellipse cx="${x}" cy="90" rx="4" ry="2.6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>`).join("")}
    <g class="head-tilt">
      <circle cx="79" cy="50" r="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/><circle cx="79" cy="50" r="1.4" fill="${c.shade}"/>
      <path d="M73 61 Q73 48 86 47 Q99 48 99 61 Q99 74 86 75 Q73 74 73 61 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M92 60 Q99 61 99 65 Q95 69 90 67 Z" fill="${c.shade}" opacity=".55"/>
      <ellipse cx="98" cy="62" rx="3.2" ry="2.8" fill="${INK}"/>
      <path d="M92 67 q3 2 6 1" stroke="${INK}" stroke-width="1.1" fill="none"/>
      ${eye(87, 58, 2.4, eyeInk(c))}
      ${whiskersR(96, 65)}
    </g>`,

  // Shrew — tiny insectivore with an absurdly long pointed proboscis-snout, pin-prick eyes, velvety, thin tail
  shrew: (c) => `
    <g class="tail-wag">${tube("M38 82 Q24 88 20 78", c.shade, c.line, 2.6)}</g>
    <g class="breathe">
      <path d="M30 80 Q32 64 54 62 Q78 62 80 78 Q80 90 54 90 Q32 90 30 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 84 Q56 90 74 84 Q70 90 54 90 Q42 90 40 84 Z" fill="${c.shade}" opacity=".5"/>
    </g>
    ${[46, 66].map((x) => `<ellipse cx="${x}" cy="88" rx="3.4" ry="2.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>`).join("")}
    <g class="head-tilt">
      <circle cx="70" cy="58" r="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/><circle cx="70" cy="58" r="1.4" fill="${c.shade}"/>
      <path d="M66 66 Q66 54 80 52 Q92 54 92 66 Q92 76 80 78 Q68 76 66 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M88 60 Q104 62 110 70 Q104 72 90 70 Q86 66 88 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="109" cy="70" rx="2.2" ry="1.6" fill="${INK}"/>
      <circle cx="82" cy="62" r="1.8" fill="${INK}"/>
      ${whiskersR(106, 71)}
    </g>`,

  // ── GLIDERS (float) ─────────────────────────────────────────────────────────
  // Sugar Glider — marsupial: HUGE eyes, big ears, dark dorsal stripe, triangular gliding flaps, fluffy round tail
  sugarglider: (c) => `
    <g class="tail-wag">${tube("M72 78 Q98 84 100 62", c.body, c.line, 5)}${pom(100, 58, 7, c.body, c.line, 8, 2)}</g>
    <g class="breathe">
      <path d="M48 58 Q20 60 22 88 Q40 82 52 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M72 58 Q100 60 98 88 Q80 82 68 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M22 86 l-4 4 M26 88 l-3 5 M98 86 l4 4 M94 88 l3 5" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M60 46 Q78 48 78 74 Q76 92 60 94 Q44 92 42 74 Q42 48 60 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 58 Q72 60 70 78 Q66 90 60 92 Q54 90 50 78 Q48 60 60 58 Z" fill="${c.shade}" opacity=".55"/>
    </g>
    <g class="head-tilt">
      ${rEar(48, 34, 7, c)}${rEar(72, 34, 7, c)}
      <circle cx="60" cy="42" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 26 Q57 40 60 54 Q63 40 60 26 Z" fill="${INK}" opacity=".7"/>
      <path d="M54 46 Q60 42 66 46 Q66 54 60 58 Q54 54 54 46 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="60" cy="50" rx="2.4" ry="1.8" fill="${INK}"/>
      ${eyes(51, 69, 40, 4.4, eyeInk(c))}
      ${whiskersL(56, 50)}${whiskersR(64, 50)}
    </g>`,

  // Flying Squirrel — full square patagium kite (wrist-to-ankle), broad FLAT rudder tail, huge nocturnal eyes
  flyingsquirrel: (c) => `
    <g class="tail-wag">
      <path d="M50 88 Q40 108 60 106 Q80 108 70 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 92 q6 8 12 0" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".4"/>
    </g>
    <g class="breathe">
      <path d="M56 50 Q18 56 24 92 L52 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M64 50 Q102 56 96 92 L68 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M18 54 l-4 -3 M20 58 l-5 -1 M22 92 l-4 4 M26 94 l-2 5" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${mirror(`<path d="M18 54 l-4 -3 M20 58 l-5 -1 M22 92 l-4 4 M26 94 l-2 5" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`)}
      <path d="M60 46 Q76 48 76 72 Q74 90 60 92 Q46 90 44 72 Q44 48 60 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M60 58 Q70 60 68 78 Q64 88 60 90 Q56 88 52 78 Q50 60 60 58 Z" fill="${c.shade}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${rEar(50, 36, 6, c)}${rEar(70, 36, 6, c)}
      <circle cx="60" cy="44" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M55 48 Q60 44 65 48 Q66 56 60 60 Q54 56 55 48 Z" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="60" cy="52" rx="2.4" ry="1.8" fill="${INK}"/>
      ${eyes(52, 68, 42, 4.6, eyeInk(c))}
      ${whiskersL(56, 52)}${whiskersR(64, 52)}
    </g>`,

  // ── FLAGSHIP ─────────────────────────────────────────────────────────────────
  // Red Panda — white face-mask + tear stripes, white-rimmed pointed ears, dark legs, ringed bushy tail (tier 2)
  redpanda: (c) => `
    <g class="tail-wag">
      ${tube("M44 92 Q20 96 16 74 Q15 62 26 60", c.body, c.line, 9)}
      <path d="M24 62 q-4 6 0 12 M20 70 q-4 5 0 11 M20 82 q2 6 8 8" stroke="${INK}" stroke-width="3" fill="none" opacity=".5" stroke-linecap="round"/>
      ${pom(20, 62, 7, c.shade, c.line, 8, 2)}
    </g>
    <g class="breathe">
      <path d="M44 96 Q40 62 60 56 Q80 62 76 96 Q60 104 44 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 84 Q60 92 70 84 Q72 98 60 102 Q48 98 50 84 Z" fill="${c.shade}" opacity=".8"/>
    </g>
    ${[50, 70].map((x) => `<ellipse cx="${x}" cy="98" rx="5" ry="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    <g class="head-tilt">
      <path d="M42 38 L46 20 L56 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M46 32 L47 26 L52 33 Z" fill="${WHT}"/>
      <path d="M78 38 L74 20 L64 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M74 32 L73 26 L68 33 Z" fill="${WHT}"/>
      <path d="M40 48 Q40 32 60 30 Q80 32 80 48 Q80 66 60 70 Q40 66 40 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M44 48 Q52 40 60 46 Q68 40 76 48 Q78 62 60 68 Q42 62 44 48 Z" fill="${WHT}"/>
      <path d="M60 32 Q64 40 60 46 Q56 40 60 32 Z" fill="${WHT}"/>
      <path d="M50 50 Q52 58 50 63" stroke="${c.line}" stroke-width="1.4" fill="none" opacity=".35"/>
      ${mirror(`<path d="M50 50 Q52 58 50 63" stroke="${c.line}" stroke-width="1.4" fill="none" opacity=".35"/>`)}
      <path d="M56 52 Q60 48 64 52 L62 58 Q60 60 58 58 Z" fill="${INK}"/>
      ${eyes(52, 68, 48, 3, INK)}
    </g>`,
};

export const ROSTER_RODENTS = [
  { n: "Ferret", e: "🐾", tier: 1, float: false },
  { n: "Weasel", e: "🐾", tier: 1, float: false },
  { n: "Stoat", e: "🐾", tier: 1, float: false },
  { n: "Chinchilla", e: "🐭", tier: 2, float: false },
  { n: "Capybara", e: "🦫", tier: 2, float: false },
  { n: "Gerbil", e: "🐹", tier: 1, float: false },
  { n: "Rat", e: "🐀", tier: 1, float: false },
  { n: "Prairie Dog", e: "🐿️", tier: 1, float: false },
  { n: "Groundhog", e: "🦫", tier: 1, float: false },
  { n: "Marmot", e: "🦫", tier: 1, float: false },
  { n: "Dormouse", e: "🐭", tier: 1, float: false },
  { n: "Muskrat", e: "🦫", tier: 1, float: false },
  { n: "Pika", e: "🐹", tier: 1, float: false },
  { n: "Degu", e: "🐭", tier: 1, float: false },
  { n: "Vole", e: "🐭", tier: 1, float: false },
  { n: "Shrew", e: "🐁", tier: 1, float: false },
  { n: "Sugar Glider", e: "🐿️", tier: 2, float: true },
  { n: "Flying Squirrel", e: "🐿️", tier: 2, float: true },
  { n: "Red Panda", e: "🦊", tier: 2, float: false },
];
