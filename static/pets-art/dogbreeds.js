// pets-art/dogbreeds.js — BESPOKE hand-drawn SVG art for CLASSIC DOG BREEDS (NADO Pets).
// House-style (see METHOD.md): ONE continuous head+body silhouette (c.body fill, c.line outline, sw 3.2),
// two-tone shading via belly(c)/c.shade/tint/deepen, cute glossy ceye faces, appendages tucked/overlapping
// so nothing floats, floorShadow grounds every dog. Coat is recoloured at hatch — NEVER hardcode breed
// hues; only fixed accents (nose/eyes INK, teeth #fff, tongue) are constant. Each breed is drawn from
// scratch with its signature (ears, muzzle, coat pattern, build, tail) so all 20 read distinct at a glance.
import { INK, ceye, floorShadow, belly, tint, deepen, tube, pom, mirror, eye, eyes } from "../pets-draw.js";

const TONGUE = "#eb8f8f", TLINE = "#c56d86";

// ── shared cute-face + paw bits (generic mascot parts, NOT species bodies) ───────────────────
const paw = (c, x, y, w = 9) => `<ellipse cx="${x}" cy="${y}" rx="${w}" ry="${(w * 0.78).toFixed(1)}" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><g stroke="${c.line}" stroke-width="1.1" opacity=".5" stroke-linecap="round"><path d="M${x - 3} ${y - 1} v4 M${x} ${y} v4 M${x + 3} ${y - 1} v4"/></g>`;
const nose = (x, y, w = 3.8) => `<ellipse cx="${x}" cy="${y}" rx="${w}" ry="${(w * 0.74).toFixed(1)}" fill="${INK}"/><circle cx="${(x - w * 0.32).toFixed(1)}" cy="${(y - w * 0.3).toFixed(1)}" r="${(w * 0.26).toFixed(1)}" fill="#fff" opacity=".55"/>`;
const mouth = (c, x, y, s = 8) => `<path d="M${x} ${y} v2.5 M${x} ${y + 2.5} q-${(s * 0.55).toFixed(1)} ${(s * 0.5).toFixed(1)} -${s} ${(s * 0.28).toFixed(1)} M${x} ${y + 2.5} q${(s * 0.55).toFixed(1)} ${(s * 0.5).toFixed(1)} ${s} ${(s * 0.28).toFixed(1)}" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>`;
const smileMouth = (c, x, y, s = 9) => `<path d="M${x} ${y} v2 M${x - s} ${y + 1} Q${x} ${y + 7} ${x + s} ${y + 1}" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`;
const tongue = (x, y, w = 3.6) => `<path d="M${x - w} ${y} q0 ${(w * 1.7).toFixed(1)} ${w} ${(w * 1.7).toFixed(1)} q${w} 0 ${w} -${(w * 1.7).toFixed(1)} Z" fill="${TONGUE}" stroke="${TLINE}" stroke-width="1" stroke-linejoin="round"/><path d="M${x} ${y} v${(w * 1.3).toFixed(1)}" stroke="${TLINE}" stroke-width="0.9"/>`;
const iceEye = (x, y, r = 4) => `<g class="blink"><circle cx="${x}" cy="${y}" r="${r}" fill="#6fb2e0"/><circle cx="${x}" cy="${y}" r="${(r * 0.52).toFixed(1)}" fill="${INK}"/><circle cx="${(x - r * 0.3).toFixed(1)}" cy="${(y - r * 0.36).toFixed(1)}" r="${(r * 0.3).toFixed(1)}" fill="#fff"/></g>`;

export const ART_DOGBREEDS = {
  // ── Labrador — friendly blocky head, medium rounded drop ears, thick otter tail, happy grin (t1) ──
  labrador: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 30)}
    <g class="tail-wag"><path d="M38 99 Q17 101 18 84 Q19 74 28 78 Q23 87 34 92 Q39 95 45 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 17 C74 17 83 27 83 41 C83 48 80 54 75 58 C81 61 88 68 90 80 C93 98 86 115 60 115 C34 115 27 98 30 80 C32 68 39 61 45 58 C40 54 37 48 37 41 C37 27 46 17 60 17 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 66 Q60 60 70 66 Q73 94 60 100 Q47 94 50 66 Z" fill="${B}"/>
      <path d="M46 26 Q31 30 32 51 Q33 59 43 55 Q44 40 51 33 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${mirror(`<path d="M46 26 Q31 30 32 51 Q33 59 43 55 Q44 40 51 33 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="49" rx="12" ry="9.5" fill="${B}"/>
      ${nose(60, 45)}${mouth(c, 60, 49)}${tongue(60, 55, 3.2)}
      ${ceye(52, 39, 4.2)}${ceye(68, 39, 4.2)}
      ${paw(c, 50, 109)}${paw(c, 70, 109)}
    </g>`; },

  // ── Husky — erect triangle ears, dark facial mask + white blaze/goggles, ICY BLUE eyes, curl tail (t2) ──
  husky: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 30)}
    <g class="tail-wag"><path d="M37 98 Q15 94 17 74 Q18 63 30 67 Q22 78 35 87 Q41 91 46 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M24 72 Q19 80 27 86" fill="none" stroke="${B}" stroke-width="4" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M60 18 C74 18 83 28 83 42 C83 49 80 54 75 58 C81 61 88 68 90 80 C93 98 86 115 60 115 C34 115 27 98 30 80 C32 68 39 61 45 58 C40 54 37 49 37 42 C37 28 46 18 60 18 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 64 Q60 58 70 64 Q73 96 60 102 Q47 96 50 64 Z" fill="${B}"/>
      <path d="M45 23 L41 5 L57 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/><path d="M46 20 L44 9 L52 20 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M45 23 L41 5 L57 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/><path d="M46 20 L44 9 L52 20 Z" fill="${c.shade}"/>`)}
      <path d="M40 30 Q50 24 52 40 Q46 44 42 42 Z" fill="${c.shade}"/>${mirror(`<path d="M40 30 Q50 24 52 40 Q46 44 42 42 Z" fill="${c.shade}"/>`)}
      <path d="M60 24 Q52 38 55 52 Q60 58 65 52 Q68 38 60 24 Z" fill="${B}"/>
      <ellipse cx="60" cy="52" rx="12" ry="9" fill="${B}"/>
      ${nose(60, 48)}${mouth(c, 60, 52)}
      ${iceEye(51, 40, 4)}${iceEye(69, 40, 4)}
      ${paw(c, 50, 109)}${paw(c, 70, 109)}
    </g>`; },

  // ── German Shepherd — big erect pointed ears, black SADDLE over back, long dark muzzle, bushy tail (t2) ──
  germanshepherd: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 31)}
    <g class="tail-wag"><path d="M36 100 Q13 100 15 80 Q16 69 28 73 Q20 84 34 92 Q40 96 46 92 Z" fill="${deepen(c.body, 0.28)}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 19 C73 19 82 28 82 41 C82 47 80 52 76 56 C82 60 88 68 90 82 C93 100 86 115 60 115 C34 115 27 100 30 82 C32 68 38 60 44 56 C40 52 38 47 38 41 C38 28 47 19 60 19 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M35 58 Q60 50 85 58 Q90 82 82 100 Q60 90 38 100 Q30 82 35 58 Z" fill="${deepen(c.body, 0.32)}"/>
      <path d="M50 66 Q60 62 70 66 Q71 84 60 90 Q49 84 50 66 Z" fill="${tint(c.body, 0.4)}"/>
      <path d="M46 24 L44 3 L60 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/><path d="M47 21 L46 8 L55 21 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M46 24 L44 3 L60 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/><path d="M47 21 L46 8 L55 21 Z" fill="${c.shade}"/>`)}
      <path d="M50 46 Q60 42 70 46 Q72 60 60 66 Q48 60 50 46 Z" fill="${deepen(c.body, 0.3)}"/>
      <ellipse cx="55" cy="40" rx="2.4" ry="1.7" fill="${tint(c.body, 0.45)}"/><ellipse cx="65" cy="40" rx="2.4" ry="1.7" fill="${tint(c.body, 0.45)}"/>
      ${nose(60, 52)}${mouth(c, 60, 57)}
      ${ceye(52, 40, 4)}${ceye(68, 40, 4)}
      ${paw(c, 50, 109)}${paw(c, 70, 109)}
    </g>`; },

  // ── Bulldog — squat & wide, deep wrinkles, UNDERBITE with teeth, rose ears, huge jowls, flat face (t1) ──
  bulldog: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 33)}
    <g class="tail-wag"><path d="M86 96 q8 -1 8 -8 q0 -5 -6 -4 q3 4 -2 9 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 26 C79 26 89 36 89 50 C89 57 86 62 82 65 C89 69 96 77 97 91 C99 107 88 116 60 116 C32 116 21 107 23 91 C24 77 31 69 38 65 C34 62 31 57 31 50 C31 36 41 26 60 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 74 Q60 68 74 74 Q76 98 60 104 Q44 98 46 74 Z" fill="${B}"/>
      <path d="M45 33 Q34 30 34 43 Q35 50 44 47 Q44 39 50 37 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${mirror(`<path d="M45 33 Q34 30 34 43 Q35 50 44 47 Q44 39 50 37 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>`)}
      <path d="M39 54 Q35 72 48 76 Q56 72 53 56 Z" fill="${B}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M39 54 Q35 72 48 76 Q56 72 53 56 Z" fill="${B}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <g stroke="${c.line}" stroke-width="1.6" fill="none" stroke-linecap="round" opacity=".7"><path d="M49 41 Q60 37 71 41 M51 46 Q60 43 69 46 M53 60 Q60 57 67 60"/></g>
      ${nose(60, 52, 4.6)}
      <path d="M52 62 Q60 67 68 62" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <rect x="54.5" y="59.5" width="2.8" height="3.4" rx="0.6" fill="#fff" stroke="${c.line}" stroke-width="0.7"/><rect x="62.7" y="59.5" width="2.8" height="3.4" rx="0.6" fill="#fff" stroke="${c.line}" stroke-width="0.7"/>
      ${ceye(48, 45, 4)}${ceye(72, 45, 4)}
      ${paw(c, 44, 110, 10)}${paw(c, 76, 110, 10)}
    </g>`; },

  // ── Chihuahua — apple-dome head, ENORMOUS erect bat-ears, tiny body, huge eyes, thin tail (t1) ──
  chihuahua: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 22)}
    <g class="tail-wag"><path d="M42 96 Q26 100 25 86 Q25 79 33 81 Q30 88 40 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 40 C70 40 77 47 77 56 C77 61 75 65 72 68 C77 71 82 78 83 90 C85 104 77 114 60 114 C43 114 35 104 37 90 C38 78 43 71 48 68 C45 65 43 61 43 56 C43 47 50 40 60 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 74 Q60 70 68 74 Q69 96 60 101 Q51 96 52 74 Z" fill="${B}"/>
      <path d="M53 45 L25 22 L47 57 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M50 47 L33 31 L46 53 Z" fill="${tint(c.body, 0.5)}"/>
      ${mirror(`<path d="M53 45 L25 22 L47 57 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M50 47 L33 31 L46 53 Z" fill="${tint(c.body, 0.5)}"/>`)}
      <ellipse cx="60" cy="60" rx="9" ry="7" fill="${B}"/>
      ${nose(60, 57, 3.2)}${mouth(c, 60, 60, 6)}
      ${ceye(51, 52, 4.6)}${ceye(69, 52, 4.6)}
      ${paw(c, 51, 110, 7.5)}${paw(c, 69, 110, 7.5)}
    </g>`; },

  // ── Pug — flat wrinkly face, dark mask muzzle, big round eyes, curly pigtail, button ears (t1) ──
  pug: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 29)}
    <g class="tail-wag"><path d="M80 94 q12 -2 11 -13 q-1 -8 -9 -7 q-6 1 -5 7 q1 5 6 4" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M80 94 q12 -2 11 -13 q-1 -8 -9 -7 q-6 1 -5 7 q1 5 6 4" fill="none" stroke="${c.body}" stroke-width="3.4" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M60 22 C75 22 85 32 85 46 C85 53 82 58 78 61 C84 65 90 73 91 87 C93 104 85 116 60 116 C35 116 27 104 29 87 C30 73 36 65 42 61 C38 58 35 53 35 46 C35 32 45 22 60 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M49 68 Q60 63 71 68 Q73 96 60 102 Q47 96 49 68 Z" fill="${B}"/>
      <path d="M44 28 Q35 26 35 40 Q42 44 50 38 Z" fill="${deepen(c.body, 0.35)}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      ${mirror(`<path d="M44 28 Q35 26 35 40 Q42 44 50 38 Z" fill="${deepen(c.body, 0.35)}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>`)}
      <path d="M45 52 Q60 46 75 52 Q78 66 60 70 Q42 66 45 52 Z" fill="${deepen(c.body, 0.34)}"/>
      <path d="M52 40 Q60 36 68 40" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" opacity=".65"/>
      ${nose(60, 55, 4.4)}${mouth(c, 60, 60, 7)}
      ${ceye(50, 46, 4.6)}${ceye(70, 46, 4.6)}
      ${paw(c, 50, 110, 9)}${paw(c, 70, 110, 9)}
    </g>`; },

  // ── Boxer — athletic build, square head + slight underbite, dark mask, white blaze up muzzle & chest (t2) ──
  boxer: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 30)}
    <g class="tail-wag"><path d="M84 92 q10 -3 8 -12 q-2 -5 -7 -3 q3 4 -1 9 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 19 C74 19 84 29 84 43 C84 50 81 55 77 58 C83 62 89 70 91 83 C94 101 86 115 60 115 C34 115 26 101 29 83 C31 70 37 62 43 58 C39 55 36 50 36 43 C36 29 46 19 60 19 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 66 Q60 61 68 66 Q70 96 60 102 Q50 96 52 66 Z" fill="${B}"/>
      <path d="M45 25 Q33 27 34 44 Q35 51 44 48 Q44 36 51 31 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${mirror(`<path d="M45 25 Q33 27 34 44 Q35 51 44 48 Q44 36 51 31 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>`)}
      <path d="M44 50 Q60 44 76 50 Q78 64 66 68 Q60 64 54 68 Q42 64 44 50 Z" fill="${deepen(c.body, 0.3)}"/>
      <path d="M56 40 Q60 58 60 66 Q64 58 64 40 Z" fill="${B}"/>
      ${nose(60, 54, 4.4)}
      <path d="M52 62 Q60 66 68 62" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <rect x="55.5" y="60" width="2.6" height="3" rx="0.6" fill="#fff" stroke="${c.line}" stroke-width="0.7"/><rect x="61.9" y="60" width="2.6" height="3" rx="0.6" fill="#fff" stroke="${c.line}" stroke-width="0.7"/>
      ${ceye(50, 44, 4)}${ceye(70, 44, 4)}
      ${paw(c, 50, 109)}${paw(c, 70, 109)}
    </g>`; },

  // ── Rottweiler — stocky black body with TAN points (brows, cheeks, chest bib, socks), blocky head (t2) ──
  rottweiler: (c) => { const B = belly(c); const TAN = tint(c.body, 0.55); return `
    ${floorShadow(60, 114, 32)}
    <g class="tail-wag"><path d="M84 95 q9 -2 8 -9 q-1 -5 -6 -3 q2 4 -2 8 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 22 C76 22 86 32 86 47 C86 54 83 59 79 62 C86 66 93 74 94 89 C96 106 87 116 60 116 C33 116 24 106 26 89 C27 74 34 66 41 62 C37 59 34 54 34 47 C34 32 44 22 60 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 70 Q60 65 70 70 Q72 100 60 106 Q48 100 50 70 Z" fill="${TAN}"/>
      <path d="M44 30 Q33 30 33 44 Q34 51 44 48 Q44 38 51 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${mirror(`<path d="M44 30 Q33 30 33 44 Q34 51 44 48 Q44 38 51 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>`)}
      <path d="M47 54 Q60 49 73 54 Q75 66 60 70 Q45 66 47 54 Z" fill="${TAN}"/>
      <ellipse cx="52" cy="45" rx="3" ry="2" fill="${TAN}"/><ellipse cx="68" cy="45" rx="3" ry="2" fill="${TAN}"/>
      ${nose(60, 56, 4.4)}${mouth(c, 60, 61, 7)}
      ${ceye(51, 46, 4)}${ceye(69, 46, 4)}
      ${paw(c, 50, 110)}${paw(c, 70, 110)}
      <path d="M46 106 h8 M66 106 h8" stroke="${TAN}" stroke-width="3" stroke-linecap="round"/>
    </g>`; },

  // ── Doberman — sleek & lean, tall CROPPED erect ears, long muzzle, tan points, docked tail nub (t2) ──
  doberman: (c) => { const B = belly(c); const TAN = tint(c.body, 0.5); return `
    ${floorShadow(60, 113, 27)}
    <g class="tail-wag"><path d="M83 78 q7 -3 6 -9 q-1 -4 -5 -2 q2 4 -2 8 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 20 C71 20 79 28 79 39 C79 45 77 50 73 53 C80 57 87 66 89 82 C92 101 84 115 60 115 C36 115 28 101 31 82 C33 66 40 57 47 53 C43 50 41 45 41 39 C41 28 49 20 60 20 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 62 Q60 57 68 62 Q69 92 60 98 Q51 92 52 62 Z" fill="${TAN}"/>
      <path d="M50 24 L46 2 L58 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M51 21 L49 8 L55 21 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M50 24 L46 2 L58 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M51 21 L49 8 L55 21 Z" fill="${c.shade}"/>`)}
      <path d="M53 46 Q60 43 67 46 Q69 60 60 64 Q51 60 53 46 Z" fill="${TAN}"/>
      <ellipse cx="53" cy="40" rx="2.6" ry="1.7" fill="${TAN}"/><ellipse cx="67" cy="40" rx="2.6" ry="1.7" fill="${TAN}"/>
      ${nose(60, 52, 3.8)}${mouth(c, 60, 57, 6)}
      ${ceye(52, 40, 3.8)}${ceye(68, 40, 3.8)}
      ${paw(c, 51, 109, 8)}${paw(c, 69, 109, 8)}
    </g>`; },

  // ── Greyhound — SIDE: lean racer, deep chest, tucked belly, long legs, rose ears, whip tail (t2) ──
  greyhound: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 33)}
    <g class="tail-wag"><path d="M30 74 Q14 82 15 98 Q22 92 26 84 Q24 92 31 90 Q32 80 40 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    ${tube("M42 76 L39 108", c.body, c.line, 5)}${tube("M76 74 L79 108", c.body, c.line, 5)}
    <g class="breathe">
      <path d="M30 62 Q26 50 42 49 Q56 42 72 47 Q78 37 88 36 Q100 36 99 47 Q99 54 90 54 L86 57 Q84 68 79 71 Q75 60 66 62 Q57 74 46 66 Q40 68 34 66 Q29 66 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 63 Q60 60 74 64 Q72 70 60 70 Q50 70 46 63 Z" fill="${B}"/>
    </g>
    ${tube("M48 72 L45 108", c.body, c.line, 5)}${tube("M70 70 L73 108", c.body, c.line, 5)}
    ${[44, 48, 71, 77].map((x) => paw(c, x, 108, 5.5)).join("")}
    <g class="head-tilt">
      <path d="M86 34 Q78 34 78 44 Q84 48 90 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 36 Q98 34 100 44 Q100 51 92 52 Q94 56 90 58 L86 56 Q80 50 82 42 Q82 37 84 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${nose(99, 47, 3)}
      ${eye(90, 43, 3, INK)}
    </g>`; },

  // ── Shiba Inu — fox-like, erect pointed ears, big curled tail over back, cream urajiro markings (t2) ──
  shibainu: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 29)}
    <g class="tail-wag"><path d="M72 94 Q97 94 97 68 Q97 53 81 56 Q92 63 88 76 Q84 88 70 87 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M80 62 Q90 67 87 78" fill="none" stroke="${B}" stroke-width="4.5" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M60 20 C73 20 82 29 82 42 C82 48 79 53 75 57 C81 60 88 68 90 81 C93 99 86 115 60 115 C34 115 27 99 30 81 C32 68 39 60 45 57 C41 53 38 48 38 42 C38 29 47 20 60 20 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 66 Q60 60 72 66 Q74 98 60 104 Q46 98 48 66 Z" fill="${B}"/>
      <path d="M46 24 L42 5 L58 23 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M47 21 L45 10 L53 21 Z" fill="${B}"/>
      ${mirror(`<path d="M46 24 L42 5 L58 23 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M47 21 L45 10 L53 21 Z" fill="${B}"/>`)}
      <path d="M44 46 Q46 34 52 38 M76 46 Q74 34 68 38" fill="none" stroke="${c.shade}" stroke-width="0" />
      <path d="M42 50 Q60 42 78 50 Q76 62 60 62 Q44 62 42 50 Z" fill="${B}"/>
      <path d="M50 48 Q60 44 70 48 Q72 60 60 66 Q48 60 50 48 Z" fill="${B}"/>
      ${nose(60, 50, 3.6)}${smileMouth(c, 60, 54, 8)}
      ${ceye(51, 42, 3.8)}${ceye(69, 42, 3.8)}
      ${paw(c, 50, 109)}${paw(c, 70, 109)}
    </g>`; },

  // ── Border Collie — black-&-white, white blaze down face + collar + chest, one ear up one flopped (t2) ──
  bordercollie: (c) => { const B = belly(c); const W = tint(c.body, 0.82); return `
    ${floorShadow(60, 113, 31)}
    <g class="tail-wag"><path d="M36 100 Q14 100 16 80 Q17 69 29 73 Q21 84 35 92 Q41 96 47 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M22 74 Q17 82 26 90" fill="none" stroke="${W}" stroke-width="4.5" stroke-linecap="round"/></g>
    <g class="breathe">
      <path d="M60 19 C74 19 83 29 83 43 C83 50 80 55 76 58 C82 62 89 70 91 83 C94 101 86 115 60 115 C34 115 26 101 29 83 C31 70 38 62 44 58 C40 55 37 50 37 43 C37 29 46 19 60 19 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 64 Q60 56 80 64 Q84 78 78 82 Q60 74 42 82 Q36 78 40 64 Z" fill="${W}"/>
      <path d="M50 78 Q60 74 70 78 Q72 100 60 106 Q48 100 50 78 Z" fill="${W}"/>
      <path d="M45 24 Q31 24 32 42 Q33 50 44 47 Q44 34 51 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M75 22 L79 4 L67 24 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/><path d="M74 21 L77 10 L70 22 Z" fill="${c.shade}"/>
      <path d="M60 25 Q54 42 56 56 Q60 62 64 56 Q66 42 60 25 Z" fill="${W}"/>
      <ellipse cx="60" cy="52" rx="11" ry="9" fill="${W}"/>
      ${nose(60, 49, 3.8)}${mouth(c, 60, 53, 7)}
      ${ceye(52, 40, 4)}${ceye(68, 40, 4)}
      ${paw(c, 50, 109)}${paw(c, 70, 109)}
    </g>`; },

  // ── Great Dane — SIDE: towering & elegant, very long legs, big square head, floppy ears, patch (t2) ──
  greatdane: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 34)}
    <g class="tail-wag"><path d="M28 70 Q12 80 14 98 Q21 91 25 82 Q23 91 30 89 Q31 78 39 75 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    ${tube("M40 68 L37 108", c.body, c.line, 6)}${tube("M78 66 L81 108", c.body, c.line, 6)}
    <g class="breathe">
      <path d="M28 56 Q26 44 42 44 Q56 38 74 42 Q80 32 90 32 Q102 32 101 44 Q101 51 92 51 L88 55 Q86 66 80 68 Q76 58 66 60 Q56 66 44 62 Q38 64 32 62 Q27 62 28 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 58 Q60 54 74 60 Q72 66 60 66 Q50 66 46 58 Z" fill="${B}"/>
      <ellipse cx="50" cy="52" rx="8" ry="6" fill="${c.shade}"/>
    </g>
    ${tube("M46 64 L43 108", c.body, c.line, 6)}${tube("M72 62 L75 108", c.body, c.line, 6)}
    ${[41, 47, 72, 78].map((x) => paw(c, x, 108, 6.5)).join("")}
    <g class="head-tilt">
      <path d="M84 30 Q76 32 76 46 Q84 50 90 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M84 30 Q100 30 102 44 Q102 53 94 54 Q96 59 91 61 L86 58 Q79 50 81 38 Q81 32 84 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${nose(101, 46, 3.4)}${eye(91, 42, 3.2, INK)}
    </g>`; },

  // ── Pomeranian — fluffy pom-ball, tiny fox face peeking out, plumed tail up over back, wee ears (t1) ──
  pomeranian: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag">${pom(80, 74, 15, c.body, c.line, 10, 3)}${pom(80, 74, 8, B, c.line, 8, 1.4)}</g>
    <g class="breathe">${pom(60, 84, 27, c.body, c.line, 15, 3.2)}
      ${pom(60, 92, 14, B, c.line, 10, 1.2)}</g>
    <g class="breathe">
      <path d="M47 44 L41 26 L54 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/><path d="M48 41 L45 31 L52 40 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M47 44 L41 26 L54 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/><path d="M48 41 L45 31 L52 40 Z" fill="${c.shade}"/>`)}
      ${pom(60, 52, 18, c.body, c.line, 12, 2.8)}
      <path d="M52 54 Q60 50 68 54 Q70 62 60 66 Q50 62 52 54 Z" fill="${B}"/>
      ${nose(60, 55, 3.2)}${smileMouth(c, 60, 58, 6)}
      ${ceye(52, 49, 4)}${ceye(68, 49, 4)}
    </g>`; },

  // ── Shih Tzu — long silky draping fur, flat face, top-knot, floppy fur-buried ears, big eyes (t1) ──
  shihtzu: (c) => { const B = belly(c); return `
    ${floorShadow(60, 114, 31)}
    <g class="breathe">
      <path d="M60 30 C74 30 84 38 86 50 C97 52 100 64 96 76 Q101 92 94 108 Q88 104 84 108 Q80 103 74 108 Q68 102 62 108 Q56 102 50 108 Q44 103 38 108 Q34 104 28 108 Q19 92 26 76 Q21 62 34 50 C36 38 46 30 60 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 70 Q60 62 80 70 Q84 92 78 104 Q60 96 42 104 Q36 92 40 70 Z" fill="${B}"/>
      <g stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".55" stroke-linecap="round"><path d="M34 66 Q32 84 30 100 M48 72 Q47 88 46 104 M72 72 Q73 88 74 104 M86 66 Q88 84 90 100 M60 70 V104"/></g>
      <path d="M35 46 Q26 52 30 68 Q38 66 42 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${mirror(`<path d="M35 46 Q26 52 30 68 Q38 66 42 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>`)}
      <path d="M52 30 Q56 20 60 28 Q64 20 68 30 Q64 36 60 34 Q56 36 52 30 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="52" rx="18" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="58" rx="10" ry="7.5" fill="${B}"/>
      ${nose(60, 55, 3.6)}${mouth(c, 60, 59, 6)}
      ${ceye(51, 49, 4.4)}${ceye(69, 49, 4.4)}
    </g>`; },

  // ── Cocker Spaniel — very LONG wavy feathered ears, domed head, feathered chest, sweet soft eyes (t1) ──
  cockerspaniel: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 30)}
    <g class="tail-wag"><path d="M84 92 q9 -2 8 -10 q-1 -5 -6 -3 q2 4 -2 9 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 24 C73 24 82 33 82 46 C82 52 80 57 76 60 C82 64 88 72 90 84 C93 101 85 115 60 115 C35 115 27 101 30 84 C32 72 38 64 44 60 C40 57 38 52 38 46 C38 33 47 24 60 24 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 68 Q60 62 72 68 Q74 98 60 104 Q46 98 48 68 Z" fill="${B}"/>
      <path d="M44 40 Q24 46 24 72 Q26 92 38 90 Q34 74 42 62 Q40 74 46 76 Q48 58 50 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${mirror(`<path d="M44 40 Q24 46 24 72 Q26 92 38 90 Q34 74 42 62 Q40 74 46 76 Q48 58 50 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="50" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="57" rx="11" ry="8.5" fill="${B}"/>
      ${nose(60, 53, 3.8)}${mouth(c, 60, 57, 6)}${tongue(60, 62, 2.8)}
      ${ceye(51, 47, 4.4)}${ceye(69, 47, 4.4)}
      ${paw(c, 50, 109)}${paw(c, 70, 109)}
    </g>`; },

  // ── Saint Bernard — massive, droopy jowls, big floppy ears, white blaze, dark eye-patches, gentle (t2) ──
  saintbernard: (c) => { const B = belly(c); const W = tint(c.body, 0.8); return `
    ${floorShadow(60, 114, 34)}
    <g class="tail-wag"><path d="M86 96 Q98 92 96 80 Q90 84 84 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 22 C78 22 89 33 89 48 C89 55 86 60 82 63 C90 67 97 76 98 91 C100 108 89 117 60 117 C31 117 20 108 22 91 C23 76 30 67 38 63 C34 60 31 55 31 48 C31 33 42 22 60 22 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 72 Q60 66 74 72 Q76 102 60 108 Q44 102 46 72 Z" fill="${W}"/>
      <path d="M43 28 Q28 30 27 52 Q28 62 40 58 Q42 42 50 36 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${mirror(`<path d="M43 28 Q28 30 27 52 Q28 62 40 58 Q42 42 50 36 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>`)}
      <path d="M60 26 Q53 42 55 54 Q60 60 65 54 Q67 42 60 26 Z" fill="${W}"/>
      <path d="M44 44 Q38 40 36 48 Q40 54 46 52 Z" fill="${c.shade}"/>${mirror(`<path d="M44 44 Q38 40 36 48 Q40 54 46 52 Z" fill="${c.shade}"/>`)}
      <path d="M42 58 Q40 76 52 78 Q58 74 55 60 Z" fill="${W}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${mirror(`<path d="M42 58 Q40 76 52 78 Q58 74 55 60 Z" fill="${W}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="58" rx="11" ry="8" fill="${W}"/>
      ${nose(60, 55, 4.6)}${mouth(c, 60, 60, 7)}
      ${ceye(50, 47, 4)}${ceye(70, 47, 4)}
      ${paw(c, 48, 111, 10)}${paw(c, 72, 111, 10)}
    </g>`; },

  // ── Basset Hound — SIDE: long low body, tiny legs, HUGE dragging ears, droopy sad face, domed head (t1) ──
  bassethound: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 35)}
    <g class="tail-wag"><path d="M22 80 Q10 74 10 62 Q18 68 26 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    ${[30, 42, 66, 78].map((x) => tube(`M${x} 88 L${x} 106`, c.body, c.line, 6)).join("")}
    <g class="breathe">
      <path d="M24 78 Q22 62 40 62 Q60 56 80 62 Q92 60 94 72 Q96 88 82 90 Q60 84 38 90 Q26 90 24 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 84 Q60 78 84 84 Q82 90 60 90 Q40 90 34 84 Z" fill="${B}"/>
    </g>
    ${[30, 42, 66, 78].map((x) => paw(c, x, 106, 6.5)).join("")}
    <g class="head-tilt">
      <path d="M82 54 Q94 52 96 66 Q96 76 86 78 Q76 76 76 64 Q76 56 82 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M86 74 Q98 74 100 84 Q100 92 92 90 Q88 82 86 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <g class="tail-wag"><path d="M79 62 Q66 66 62 92 Q60 104 70 104 Q74 92 74 78 Q74 68 80 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/></g>
      ${nose(98, 82, 3.4)}
      <path d="M86 70 q-3 3 -6 2" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round" opacity=".7"/>
      ${eye(87, 64, 3.2, INK)}
    </g>`; },

  // ── Samoyed — fluffy snow-white cloud, "Sammy smile", erect fluffy ears, plumed tail curled up (t2) ──
  samoyed: (c) => { const B = belly(c); return `
    ${floorShadow(60, 113, 29)}
    <g class="tail-wag">${pom(78, 72, 15, c.body, c.line, 11, 3)}${pom(78, 72, 8, B, c.line, 8, 1.2)}</g>
    <g class="breathe">${pom(60, 84, 27, c.body, c.line, 15, 3.2)}
      ${pom(60, 92, 13, B, c.line, 10, 1.2)}</g>
    <g class="breathe">
      <path d="M46 42 Q40 26 51 30 Q54 38 54 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/><path d="M48 40 Q45 30 50 33 Q52 39 51 45 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M46 42 Q40 26 51 30 Q54 38 54 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/><path d="M48 40 Q45 30 50 33 Q52 39 51 45 Z" fill="${c.shade}"/>`)}
      ${pom(60, 54, 19, c.body, c.line, 13, 3)}
      <path d="M50 56 Q60 52 70 56 Q72 64 60 68 Q48 64 50 56 Z" fill="${B}"/>
      ${nose(60, 56, 3.8)}
      <path d="M60 58 v3 M48 60 Q60 72 72 60" fill="none" stroke="${c.line}" stroke-width="1.9" stroke-linecap="round"/>
      ${ceye(51, 50, 4)}${ceye(69, 50, 4)}
    </g>`; },

  // ── Australian Shepherd — MERLE mottled coat, copper points + white blaze, one BLUE eye, semi-erect ears (t2) ──
  australianshepherd: (c) => { const B = belly(c); const W = tint(c.body, 0.82); const COP = tint(c.body, 0.42); return `
    ${floorShadow(60, 113, 31)}
    <g class="tail-wag"><path d="M84 94 q9 -2 8 -9 q-1 -5 -6 -3 q2 4 -2 8 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 20 C74 20 83 30 83 43 C83 50 80 55 76 58 C82 62 89 70 91 83 C94 101 86 115 60 115 C34 115 26 101 29 83 C31 70 38 62 44 58 C40 55 37 50 37 43 C37 30 46 20 60 20 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <g fill="${deepen(c.body, 0.35)}"><ellipse cx="44" cy="74" rx="8" ry="6"/><ellipse cx="76" cy="86" rx="9" ry="6.5"/><ellipse cx="58" cy="94" rx="7" ry="5"/><ellipse cx="72" cy="70" rx="5" ry="4"/></g>
      <g fill="${c.shade}"><ellipse cx="52" cy="88" rx="5" ry="4"/><ellipse cx="82" cy="74" rx="4.5" ry="3.5"/><ellipse cx="40" cy="60" rx="4" ry="3"/></g>
      <path d="M50 78 Q60 74 70 78 Q72 100 60 106 Q48 100 50 78 Z" fill="${W}"/>
      <path d="M45 24 Q32 26 33 42 Q34 49 44 46 Q44 34 51 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${mirror(`<path d="M45 24 Q32 26 33 42 Q34 49 44 46 Q44 34 51 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>`)}
      <path d="M60 26 Q54 40 56 54 Q60 60 64 54 Q66 40 60 26 Z" fill="${W}"/>
      <path d="M46 50 Q52 46 55 51 M74 50 Q68 46 65 51" fill="none" stroke="${COP}" stroke-width="3" stroke-linecap="round"/>
      <ellipse cx="60" cy="55" rx="10" ry="8" fill="${W}"/>
      ${nose(60, 51, 3.8)}${mouth(c, 60, 55, 6)}
      ${iceEye(52, 42, 3.8)}${ceye(68, 42, 3.8)}
      ${paw(c, 50, 109)}${paw(c, 70, 109)}
    </g>`; },
};

export const ROSTER_DOGBREEDS = [
  { n: "Labrador", e: "🐶", tier: 1, float: false },
  { n: "Husky", e: "🐺", tier: 2, float: false },
  { n: "German Shepherd", e: "🐕", tier: 2, float: false },
  { n: "Bulldog", e: "🐶", tier: 1, float: false },
  { n: "Chihuahua", e: "🐕", tier: 1, float: false },
  { n: "Pug", e: "🐶", tier: 1, float: false },
  { n: "Boxer", e: "🐕", tier: 2, float: false },
  { n: "Rottweiler", e: "🐕", tier: 2, float: false },
  { n: "Doberman", e: "🐕", tier: 2, float: false },
  { n: "Greyhound", e: "🐕", tier: 2, float: false },
  { n: "Shiba Inu", e: "🐕", tier: 2, float: false },
  { n: "Border Collie", e: "🐕", tier: 2, float: false },
  { n: "Great Dane", e: "🐕", tier: 2, float: false },
  { n: "Pomeranian", e: "🐶", tier: 1, float: false },
  { n: "Shih Tzu", e: "🐶", tier: 1, float: false },
  { n: "Cocker Spaniel", e: "🐶", tier: 1, float: false },
  { n: "Saint Bernard", e: "🐕", tier: 2, float: false },
  { n: "Basset Hound", e: "🐶", tier: 1, float: false },
  { n: "Samoyed", e: "🐕", tier: 2, float: false },
  { n: "Australian Shepherd", e: "🐕", tier: 2, float: false },
];
