// pets-art/celestial.js — BESPOKE hand-drawn SVG art for CELESTIAL beasts (NADO Pets).
// Cosmic/starry mythical creatures — the rare chase pets (tier 3–6). Each value: (c) => "<svg inner
// markup>" for viewBox 0 0 120 120, creature centered ~ (60,64), within x,y ∈ [8,114]. Palette-driven:
// colours come from the coat object c (c.body main / c.shade accent / c.line outline); real hues are NOT
// hardcoded (every pet is recoloured at hatch). Only the fixed COSMIC accents stay constant across coats:
// glow #eafff4, star #ffd24a, aura #bfe3ff / #a15cf0, plus universal horn/tooth/fire tints. Method:
// ONE continuous silhouette + two-tone shading (c.shade + belly) + clean cute face + every appendage
// tucked so nothing floats. Animate: torso .breathe, head .head-tilt, tails/wings/fins .tail-wag.
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

// fixed cosmic + universal accents (constant across coats)
const GLOW = "#eafff4", STAR = "#ffd24a", AURA = "#bfe3ff", NEBULA = "#a15cf0",
  HORN = "#f2c94c", TOOTH = "#ffffff", FIRE = "#ff7a1a", FIRE2 = "#ffd24a", MANE = "#f2a03b";

// ── local drawing helpers ────────────────────────────────────────────────────────────────
const floor = (cx, y, w) => `<ellipse cx="${cx}" cy="${y}" rx="${w}" ry="${(w * 0.18).toFixed(1)}" fill="#000" opacity=".2"/>`;
const dot = (x, y, r = 1.4, f = STAR) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${f}"/>`;
const neb = (x, y, r, f = NEBULA) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${f}" opacity=".3"/>`;
const freckles = (pts, r = 1.3, f = STAR) => pts.map(([x, y]) => dot(x, y, r, f)).join("");
const spark = (x, y, s = 4, f = STAR) => { const i = s * 0.36, P = (a, b) => `${(+a).toFixed(1)} ${(+b).toFixed(1)}`;
  return `<path d="M${P(x, y - s)} L${P(x + i, y - i)} L${P(x + s, y)} L${P(x + i, y + i)} L${P(x, y + s)} L${P(x - i, y + i)} L${P(x - s, y)} L${P(x - i, y - i)} Z" fill="${f}"/>`; };
const starEye = (x, y, r = 3) => `<circle cx="${x}" cy="${y}" r="${r + 2}" fill="${STAR}" opacity=".4"/><circle cx="${x}" cy="${y}" r="${r}" fill="${STAR}"/><circle cx="${x}" cy="${y}" r="${(r * 0.42).toFixed(1)}" fill="${INK}"/>`;
const rays = (cx, cy, r0, r1, n, col, w = 3) => Array.from({ length: n }, (_, k) => {
  const a = (k * 360 / n) * Math.PI / 180, x1 = cx + r0 * Math.cos(a), y1 = cy + r0 * Math.sin(a), x2 = cx + r1 * Math.cos(a), y2 = cy + r1 * Math.sin(a);
  return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${col}" stroke-width="${w}" stroke-linecap="round"/>`; }).join("");

export const ART_CELESTIAL = {
  // ── Star Dragon — chubby side-standing dragon, golden horns, spine ridges, star-freckled hide, glowing eye (grounded, head right)
  stardragon: (c) => { const B = belly(c); return `
    ${floor(58, 111, 30)}
    <g class="tail-wag">
      <path d="M42 84 Q16 88 14 66 Q13 54 25 55 Q17 63 24 72 Q31 79 42 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${spark(12, 60, 4.4, STAR)}
    </g>
    <g class="tail-wag"><path d="M60 52 Q42 26 36 44 Q49 43 55 55 Q45 50 42 62 Q56 54 66 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M34 84 C34 62 48 54 66 54 C74 54 80 57 84 62 L92 54 C104 52 108 62 103 70 C99 76 91 74 88 70 C88 82 82 90 72 90 L72 104 L64 104 L64 90 L48 90 L48 104 L40 104 L40 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[46, 58, 70].map(x => `<path d="M${x} 56 l4 -8 l4 8 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
      <path d="M52 84 Q66 92 84 84 Q68 88 52 84 Z" fill="${B}" opacity=".85"/>
      ${freckles([[46, 70], [58, 74], [70, 68], [54, 82], [78, 66]], 1.3, GLOW)}
      <path d="M88 56 Q84 42 76 40 Q82 48 82 58 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M97 56 Q95 42 86 38 Q90 48 91 58 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="90" cy="64" r="5.6" fill="${STAR}" opacity=".4"/>
      ${ceye(90, 64, 3.2)}
      <path d="M99 71 l1.4 3.4 l1.6 -3 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>
      ${spark(30, 40, 4, STAR)}${spark(106, 46, 3, GLOW)}
    </g>`; },

  // ── Moon Rabbit — plush bunny sitting cradled in a glowing crescent, tall ears, star-freckled coat (grounded)
  moonrabbit: (c) => { const B = belly(c); const ear = `<path d="M52 40 Q46 14 53 8 Q60 18 58 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M53 38 Q50 18 54 13 Q57 20 56 40 Z" fill="${B}"/>`;
    return `
    <path d="M26 92 Q60 118 94 92 Q60 100 26 92 Z" fill="${AURA}" stroke="${HORN}" stroke-width="2" stroke-linejoin="round" opacity=".92"/>
    ${freckles([[34, 94], [86, 94]], 1.4, STAR)}${spark(60, 103, 3, STAR)}
    <g class="tail-wag">${ear}${mirror(ear)}</g>
    <g class="breathe">
      <path d="M60 30 C46 30 42 42 46 52 C36 56 32 72 36 84 C39 95 48 98 60 98 C72 98 81 95 84 84 C88 72 84 56 74 52 C78 42 74 30 60 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 60 C50 60 46 74 50 86 Q60 94 70 86 C74 74 70 60 60 60 Z" fill="${B}"/>
      <ellipse cx="48" cy="94" rx="7" ry="4.5" fill="${B}" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="72" cy="94" rx="7" ry="4.5" fill="${B}" stroke="${c.line}" stroke-width="1.6"/>
      ${freckles([[42, 66], [78, 66], [54, 78], [66, 80]], 1.2, GLOW)}
    </g>
    <g class="head-tilt">
      ${eyes(52, 68, 54, 4, eyeInk(c))}
      <path d="M60 60 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 63 v3 M60 66 q-4 3 -7 2 M60 66 q4 3 7 2" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="45" cy="60" r="3" fill="${STAR}" opacity=".25"/><circle cx="75" cy="60" r="3" fill="${STAR}" opacity=".25"/>
    </g>`; },

  // ── Sun Bird — round radiant songbird ringed by a corona of golden sun-rays, tiny beak (grounded)
  sunbird: (c) => { const B = belly(c); return `
    ${floor(60, 110, 20)}
    <g class="breathe">
      ${rays(60, 60, 24, 36, 14, STAR, 3)}
      <circle cx="60" cy="60" r="7" fill="${STAR}" opacity=".3"/>
    </g>
    <g class="tail-wag"><path d="M52 82 L36 96 Q46 94 54 88 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 38 C43 38 39 56 41 70 C43 84 52 90 60 90 C68 90 77 84 79 70 C81 56 77 38 60 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 60 C52 60 49 72 51 82 Q60 88 69 82 C71 72 68 60 60 60 Z" fill="${B}"/>
      <path d="M48 60 Q42 72 49 82 Q54 72 54 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M56 62 L60 68 L64 62 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      ${eyes(53, 67, 54, 3.2, eyeInk(c))}
      ${spark(60, 42, 3.4, GLOW)}
    </g>`; },

  // ── Comet Fox — sitting fox whose tail is a glowing comet streak trailing sparks (grounded)
  cometfox: (c) => { const B = belly(c); return `
    ${floor(60, 110, 22)}
    <g class="tail-wag">
      <circle cx="50" cy="90" r="9" fill="${STAR}" opacity=".26"/>
      <path d="M50 88 Q34 96 12 110 Q30 100 41 98 Q24 104 15 112 Q40 102 52 94 Z" fill="${AURA}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round" opacity=".92"/>
      <path d="M49 90 Q34 98 18 108" fill="none" stroke="${GLOW}" stroke-width="2.2" stroke-linecap="round" opacity=".85"/>
      ${spark(50, 90, 4.4, STAR)}${dot(30, 100, 1.6, STAR)}${dot(20, 106, 1.3, GLOW)}
    </g>
    <g class="breathe">
      <path d="M60 106 C34 106 30 88 34 70 C36 60 39 55 43 51 L35 28 L55 45 Q60 42 65 45 L85 28 L77 51 C81 55 84 60 86 70 C90 88 86 106 60 106 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 33 L52 46 Q46 49 44 53 Z" fill="${c.shade}"/><path d="M80 33 L68 46 Q74 49 76 53 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="82" rx="17" ry="16" fill="${B}"/>
      <path d="M44 62 Q52 70 60 68 Q52 66 46 58 Z" fill="${B}"/><path d="M76 62 Q68 70 60 68 Q68 66 74 58 Z" fill="${B}"/>
      ${freckles([[46, 88], [72, 88]], 1.2, GLOW)}
    </g>
    <g class="head-tilt">
      ${eyes(51, 69, 63, 3.6, eyeInk(c))}
      <path d="M60 70 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 73 v3 M60 76 q-4 3 -7 2 M60 76 q4 3 7 2" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${spark(60, 44, 3.4, STAR)}
    </g>`; },

  // ── Nebula Whale — serene drifting whale, star-speckled hide with soft nebula clouds, twin fluke (float, head right)
  nebulawhale: (c) => { const B = belly(c); return `
    <g class="tail-wag">
      <path d="M30 64 L12 52 Q7 60 11 66 Q7 72 12 80 L30 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M52 78 Q56 92 68 88 Q60 82 58 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M26 66 Q22 48 46 44 Q74 40 98 52 Q108 57 108 66 Q108 75 98 80 Q74 84 46 82 Q28 80 26 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 74 Q66 84 100 72 Q98 78 92 79 Q64 82 44 80 Q40 78 40 74 Z" fill="${B}"/>
      <path d="M46 66 Q70 62 96 66" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
      ${neb(52, 58, 6)}${neb(74, 56, 7, AURA)}${neb(66, 62, 5)}
      ${freckles([[48, 56], [60, 52], [72, 58], [84, 60], [58, 64], [78, 66]], 1.3, STAR)}
      <path d="M96 58 q6 -6 4 -14 q6 5 4 14" fill="none" stroke="${AURA}" stroke-width="2" stroke-linecap="round" opacity=".8"/>
      <circle cx="98" cy="66" r="4.4" fill="${STAR}" opacity=".35"/>
      ${eye(98, 66, 3, eyeInk(c))}
      <path d="M100 72 q6 2 8 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`; },

  // ── Galaxy Cat — front-sitting cat with a starry, nebula-speckled coat and glossy eyes (grounded)
  galaxycat: (c) => { const B = belly(c); return `
    ${floor(60, 112, 28)}
    <g class="tail-wag"><path d="M80 98 Q104 94 100 74 Q98 64 88 66 Q96 72 90 82 Q84 90 76 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      ${freckles([[95, 78], [90, 86]], 1.2, STAR)}</g>
    <g class="breathe">
      <path d="M60 112 C30 112 26 92 31 72 C33 60 36 54 41 49 L33 24 L54 43 Q60 39 66 43 L87 24 L79 49 C84 54 87 60 89 72 C94 92 90 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M39 30 L50 44 Q44 47 41 51 Z" fill="${c.shade}"/><path d="M81 30 L70 44 Q76 47 79 51 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="80" rx="21" ry="16" fill="${B}"/>
      ${[[42, 74], [78, 74], [50, 92], [70, 92], [60, 96]].map(([x, y]) => neb(x, y, 5)).join("")}
      ${freckles([[40, 66], [80, 66], [46, 88], [74, 88], [60, 92], [52, 78], [68, 78]], 1.4, STAR)}
    </g>
    <g class="head-tilt">
      ${ceye(51, 66, 4.2)}${ceye(69, 66, 4.2)}
      <path d="M60 74 l-3.2 3 h6.4 Z" fill="${INK}"/>
      <path d="M60 77 v3 M60 80 q-4 3 -8 2 M60 80 q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M34 68 h-13 M35 73 h-14 M86 68 h13 M85 73 h14" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round" opacity=".5"/>
      ${dot(48, 58, 1.2, STAR)}${dot(72, 58, 1.2, STAR)}
    </g>`; },

  // ── Aurora Deer — slender fawn with white star-spots and softly glowing aurora-ribbon antlers (grounded)
  auroradeer: (c) => { const B = belly(c); return `
    ${floor(60, 111, 22)}
    <g class="tail-wag">
      <path d="M42 40 Q34 30 30 20 M46 38 Q40 26 40 16 M46 38 Q48 26 52 18" fill="none" stroke="${AURA}" stroke-width="3.4" stroke-linecap="round" opacity=".9"/>
      <path d="M78 40 Q86 30 90 20 M74 38 Q80 26 80 16 M74 38 Q72 26 68 18" fill="none" stroke="${GLOW}" stroke-width="3.4" stroke-linecap="round" opacity=".9"/>
      ${dot(30, 20, 1.6, STAR)}${dot(40, 16, 1.6, STAR)}${dot(90, 20, 1.6, STAR)}${dot(80, 16, 1.6, STAR)}
    </g>
    <g class="breathe">
      <path d="M60 104 C44 104 40 88 44 74 C46 64 52 58 60 58 C68 58 74 64 76 74 C80 88 76 104 60 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 76 C52 76 49 88 52 96 Q60 100 68 96 C71 88 68 76 60 76 Z" fill="${B}"/>
      ${freckles([[50, 74], [70, 74], [56, 86], [66, 86], [60, 94]], 1.6, tint(c.body, 0.75))}
      <rect x="49" y="98" width="7" height="10" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <rect x="64" y="98" width="7" height="10" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
    </g>
    <g class="head-tilt">
      <path d="M40 50 Q30 46 26 40 Q36 42 44 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M80 50 Q90 46 94 40 Q84 42 76 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="50" rx="16" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M50 54 Q60 66 70 54 Q68 62 60 64 Q52 62 50 54 Z" fill="${B}"/>
      <path d="M60 55 l-3 3 h6 Z" fill="${INK}"/>
      ${eyes(52, 68, 48, 3, eyeInk(c))}
    </g>`; },

  // ── Solar Lion — front-sitting lion whose mane is a blazing sun-disc of rays and flame tufts (grounded)
  solarlion: (c) => { const B = belly(c); return `
    ${floor(60, 112, 26)}
    <g class="tail-wag"><path d="M82 100 Q102 96 100 78 Q98 70 90 72 Q96 78 92 86 Q86 92 78 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M90 74 Q98 68 100 60 Q104 70 96 78 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M60 112 C36 112 32 92 37 76 C40 66 48 62 60 62 C72 62 80 66 83 76 C88 92 84 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="90" rx="16" ry="13" fill="${B}"/>
      <ellipse cx="47" cy="106" rx="7" ry="5" fill="${B}" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="73" cy="106" rx="7" ry="5" fill="${B}" stroke="${c.line}" stroke-width="1.6"/>
    </g>
    <g class="head-tilt">
      ${rays(60, 50, 22, 33, 16, STAR, 3)}
      ${pom(60, 50, 20, MANE, c.line, 12, 2.4)}
      <circle cx="60" cy="50" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 40 l-4 -3 l5 -1 Z M70 40 l4 -3 l-5 -1 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M48 52 Q60 66 72 52 Q72 60 60 62 Q48 60 48 52 Z" fill="${B}"/>
      <path d="M60 52 l-3.4 3 h6.8 Z" fill="${INK}"/>
      <path d="M60 55 v3 M60 58 q-4 3 -7 2 M60 58 q4 3 7 2" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eyes(52, 68, 46, 3, eyeInk(c))}
    </g>`; },

  // ── Lunar Owl — round owl with a facial disc, big eyes, ear-tufts and a crescent-moon breast mark (grounded)
  lunarowl: (c) => { const B = belly(c); return `
    ${floor(60, 110, 22)}
    <g class="tail-wag">
      <path d="M38 62 Q30 80 40 94 Q46 80 46 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M82 62 Q90 80 80 94 Q74 80 74 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 32 C40 32 34 54 36 74 C38 92 48 100 60 100 C72 100 82 92 84 74 C86 54 80 32 60 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 76 Q60 70 80 76 Q78 92 60 94 Q42 92 40 76 Z" fill="${B}"/>
      <path d="M60 78 q-9 4 -6 12 q6 4 12 0 q3 -8 -6 -12 Z" fill="${AURA}" opacity=".85"/>
      ${freckles([[48, 84], [72, 84], [60, 90]], 1.2, STAR)}
      <path d="M52 100 l-3 6 m3 -6 l3 6 M68 100 l-3 6 m3 -6 l3 6" stroke="${HORN}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M44 34 l-2 -10 l7 6 Z M76 34 l2 -10 l-7 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="52" rx="24" ry="18" fill="${B}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="50" cy="52" r="9" fill="${tint(c.body, 0.4)}"/><circle cx="70" cy="52" r="9" fill="${tint(c.body, 0.4)}"/>
      ${ceye(50, 52, 5)}${ceye(70, 52, 5)}
      <path d="M56 56 L60 64 L64 56 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      ${spark(60, 30, 3, STAR)}
    </g>`; },

  // ── Cosmic Turtle — dome-shelled turtle whose shell holds a star-constellation, poking head (grounded, head right)
  cosmicturtle: (c) => { const B = belly(c); return `
    ${floor(58, 108, 30)}
    <g class="breathe">
      <path d="M22 88 Q22 98 38 98 L82 98 Q98 98 98 88 Q60 82 22 88 Z" fill="${B}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <rect x="26" y="92" width="9" height="14" rx="3.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <rect x="82" y="92" width="9" height="14" rx="3.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <path d="M24 86 Q24 48 60 48 Q96 48 96 86 Q60 94 24 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 50 v40 M40 54 Q42 74 48 88 M80 54 Q78 74 72 88 M26 78 Q60 84 94 78" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".55"/>
      <path d="M42 70 L58 60 L74 72 L64 82" fill="none" stroke="${STAR}" stroke-width="1.3" opacity=".8"/>
      ${freckles([[42, 70], [58, 60], [74, 72], [64, 82], [50, 78]], 1.7, STAR)}
    </g>
    <g class="head-tilt">
      ${tube("M92 80 Q104 78 106 70", c.body, c.line, 9)}
      <ellipse cx="106" cy="70" rx="8" ry="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M104 74 q4 3 7 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="107" cy="69" r="4.4" fill="${STAR}" opacity=".3"/>
      ${eye(107, 69, 2.8, eyeInk(c))}
    </g>`; },

  // ── Meteor Hound — stocky side-standing hound with a floppy ear, blazing a fiery meteor tail-streak (grounded, head right)
  meteorhound: (c) => { const B = belly(c); return `
    ${floor(58, 110, 30)}
    <g class="tail-wag">
      <path d="M32 74 Q8 68 3 44 Q16 56 27 56 Q7 46 5 30 Q24 48 36 60 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M30 70 Q13 61 9 44 Q22 54 30 60 Z" fill="${FIRE2}" opacity=".9"/>
      ${dot(11, 37, 1.7, STAR)}${dot(19, 27, 1.4, FIRE2)}
    </g>
    <g class="breathe">
      <path d="M26 82 C26 66 44 60 62 61 C80 62 88 68 90 80 Q90 88 82 88 L82 102 L72 102 L72 90 L52 90 L52 102 L42 102 L42 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M38 84 Q60 92 84 84 Q62 90 38 84 Z" fill="${B}"/>
      ${freckles([[46, 76], [60, 78], [74, 76]], 1.2, FIRE2)}
    </g>
    <g class="head-tilt">
      <path d="M84 54 L80 38 L94 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M85 51 L82 42 L90 48 Z" fill="${c.shade}"/>
      <path d="M76 62 Q76 46 94 46 Q112 46 112 62 Q112 70 104 74 L114 74 Q112 80 102 78 Q78 78 76 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M92 46 Q106 44 108 60 Q104 66 96 62 Q90 54 92 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M98 66 Q98 76 112 74 Q112 68 110 64 Q104 62 98 66 Z" fill="${B}"/>
      <path d="M108 74 l1.4 4 l1.4 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>
      <ellipse cx="111" cy="66" rx="2" ry="1.6" fill="${INK}"/>
      <circle cx="89" cy="59" r="4.6" fill="${FIRE2}" opacity=".35"/>
      ${eye(89, 59, 3, eyeInk(c))}
    </g>`; },

  // ── Eclipse Serpent — coiled serpent rearing before a ringed eclipse-corona halo, forked tongue (grounded)
  eclipseserpent: (c) => { const B = belly(c); return `
    ${floor(56, 108, 26)}
    <g class="tail-wag">
      <path d="M64 86 Q88 90 90 72 Q90 60 78 60 Q86 66 84 74 Q80 82 64 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M90 66 l6 -3 l-2 7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M30 82 Q28 60 52 60 Q74 60 76 78 Q76 90 60 90 Q46 90 46 80 Q46 72 56 72 Q64 72 64 78" fill="none" stroke="${c.line}" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M30 82 Q28 60 52 60 Q74 60 76 78 Q76 90 60 90 Q46 90 46 80 Q46 72 56 72 Q64 72 64 78" fill="none" stroke="${c.body}" stroke-width="8.4" stroke-linecap="round" stroke-linejoin="round"/>
      ${freckles([[38, 74], [52, 66], [66, 76], [58, 84]], 1.2, GLOW)}
    </g>
    <g class="head-tilt">
      <circle cx="44" cy="42" r="17" fill="none" stroke="${STAR}" stroke-width="2.6" opacity=".85"/>
      ${rays(44, 42, 18, 24, 12, STAR, 2)}
      <circle cx="44" cy="42" r="12" fill="${deepen(c.body, 0.45)}" opacity=".55"/>
      <path d="M38 44 Q38 30 52 30 Q64 30 64 42 Q64 52 50 52 Q38 52 38 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M38 46 Q26 46 20 42 M38 49 Q26 51 20 55" fill="none" stroke="${c.body}" stroke-width="2" stroke-linecap="round"/>
      <path d="M20 42 l-5 -1 l4 3 Z M20 55 l-5 1 l4 -3 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="0.6"/>
      <circle cx="52" cy="41" r="4.4" fill="${STAR}" opacity=".4"/>
      ${eye(52, 41, 3, eyeInk(c))}
    </g>`; },

  // ── Nova Phoenix — brilliant reborn firebird, blazing spread wings and plumes over a nova star-burst (float)
  novaphoenix: (c) => { const E = eyeInk(c);
    const wing = `<path d="M60 58 Q42 36 22 28 Q35 43 35 52 Q24 47 16 49 Q31 58 44 60 Q31 63 24 71 Q46 67 60 62 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M58 58 Q44 44 30 40 Q40 49 43 56 Z" fill="${FIRE2}" opacity=".9"/>`;
    const plume = (x, s) => `<path d="M${x} 80 Q${x - s * 5} 102 ${x - s * 1.5} 116 Q${x + s * 3} 102 ${x + s * 5} 82 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M${x} 84 Q${x - s * 3} 100 ${x} 110" fill="none" stroke="${FIRE2}" stroke-width="1.8"/>`;
    return `
    <g class="breathe">${rays(60, 58, 30, 44, 12, STAR, 2.4)}<circle cx="60" cy="58" r="10" fill="${STAR}" opacity=".25"/></g>
    <g class="tail-wag">${plume(48, 1)}${plume(72, -1)}${plume(60, 0.3)}</g>
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M60 42 Q78 46 76 68 Q72 88 60 90 Q48 88 44 68 Q42 46 60 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 56 Q69 60 67 76 Q64 86 60 86 Q56 86 53 76 Q51 60 60 56 Z" fill="${FIRE2}" opacity=".85"/>
      ${freckles([[54, 66], [66, 66], [60, 78]], 1.2, GLOW)}
    </g>
    <g class="head-tilt">
      <path d="M51 28 Q46 12 39 8 Q49 18 52 30 Z M60 24 Q60 8 60 4 Q67 14 66 27 Z M69 28 Q74 12 81 8 Q71 18 68 30 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="60" cy="40" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M56 46 L60 53 L64 46 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eyes(54, 66, 38, 3.2, E)}
      ${spark(60, 12, 3, STAR)}
    </g>`; },

  // ── Void Panther — sleek prowling panther, star-field speckled hide, blazing star eyes (grounded, head right)
  voidpanther: (c) => { const D = deepen(c.body, 0.35); return `
    ${floor(58, 108, 30)}
    <g class="tail-wag"><path d="M84 88 Q114 90 116 60 Q116 52 108 54 Q111 72 98 82 Q89 88 80 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${freckles([[112, 66], [106, 76], [98, 82]], 1.2, STAR)}</g>
    <g class="breathe">
      <ellipse cx="58" cy="84" rx="28" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M34 82 Q58 92 82 82 Q58 88 34 82 Z" fill="${D}" opacity=".6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 42}" y="92" width="11" height="17" rx="4.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      ${freckles([[46, 80], [58, 78], [70, 81], [52, 88], [65, 88], [76, 84], [40, 86]], 1.3, STAR)}
    </g>
    <g class="head-tilt">
      <path d="M45 34 Q41 25 51 27 Q55 32 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${mirror(`<path d="M45 34 Q41 25 51 27 Q55 32 53 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <ellipse cx="60" cy="53" rx="21" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M48 56 Q60 70 72 56 Q72 65 60 68 Q48 65 48 56 Z" fill="${D}" opacity=".6"/>
      <path d="M60 55 L55 61 L65 61 Z" fill="${INK}"/><path d="M60 61 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${starEye(53, 50, 2.7)}${starEye(67, 50, 2.7)}
      ${dot(60, 40, 1.2, STAR)}
    </g>`; },

  // ── Astral Stag — robust side-standing stag with branching constellation antlers (grounded, head right)
  astralstag: (c) => { const B = belly(c); return `
    ${floor(58, 110, 26)}
    <g class="tail-wag">
      <path d="M92 42 L86 26 M92 42 L100 28 M86 34 L80 24 M100 34 L106 24 M92 42 L92 30" fill="none" stroke="${STAR}" stroke-width="1.6" opacity=".8"/>
      ${freckles([[86, 26], [100, 28], [80, 24], [106, 24], [92, 30], [86, 34], [100, 34]], 1.7, STAR)}
    </g>
    <g class="breathe">
      <path d="M28 74 C28 60 44 56 62 57 C74 58 80 62 80 70 C80 82 70 84 58 84 C40 84 28 82 28 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M34 80 Q56 88 76 80 Q56 84 34 80 Z" fill="${B}"/>
      <rect x="35" y="80" width="7" height="24" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <rect x="63" y="80" width="7" height="24" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <rect x="46" y="82" width="7" height="22" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <rect x="70" y="82" width="7" height="22" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
    </g>
    <g class="head-tilt">
      ${tube("M74 66 Q84 56 90 48", c.body, c.line, 12)}
      <path d="M84 48 Q80 38 90 35 Q99 35 103 42 L106 50 Q109 54 104 58 Q98 60 92 58 Q83 56 84 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M104 52 Q109 54 106 60 Q101 61 98 57 Z" fill="${c.shade}"/>
      <ellipse cx="105" cy="54" rx="1.3" ry="1" fill="${INK}"/>
      <path d="M86 40 Q82 30 89 27 Q94 34 93 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(96, 49, 2.8, eyeInk(c))}
    </g>`; },

  // ── Zenith Eagle — soaring eagle, broad spread wings, pale head, hooked beak, star crest (float)
  zenitheagle: (c) => { const B = belly(c);
    const wing = `<path d="M58 56 Q36 40 8 42 Q22 50 32 56 Q14 56 6 62 Q26 66 40 64 Q26 74 20 86 Q44 74 60 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M52 57 Q34 48 16 50 M50 61 Q32 60 20 66" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".55"/>`;
    return `
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M60 50 Q73 54 71 72 Q67 88 60 90 Q53 88 49 72 Q47 54 60 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 64 Q67 68 65 80 Q62 88 60 88 Q58 88 55 80 Q53 68 60 64 Z" fill="${B}"/>
      <path d="M50 86 L46 102 L60 94 L74 102 L70 86 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="42" r="12" fill="${tint(c.body, 0.55)}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M56 46 Q51 49 56 55 Q60 53 60 48 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M50 40 q4 -3 8 1 M62 41 q4 -4 8 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" opacity=".6"/>
      ${eyes(54, 66, 40, 3, eyeInk(c))}
      ${spark(60, 26, 4, STAR)}
    </g>`; },

  // ── Celestial Koi — drifting koi with flowing fins, barbels and glinting star-scales (float, head right)
  celestialkoi: (c) => { const B = belly(c); return `
    <g class="tail-wag">
      <path d="M34 62 L12 46 Q7 55 12 62 Q7 69 12 78 L34 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M20 54 Q26 60 22 68 M28 56 Q32 62 28 70" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
    </g>
    <g class="tail-wag">
      <path d="M48 44 Q56 30 68 40 Q58 44 54 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M52 80 Q58 92 68 82 Q60 78 56 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M30 62 Q34 44 60 44 Q88 46 98 60 Q88 78 60 78 Q36 78 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 68 Q64 76 96 66 Q94 72 88 73 Q62 76 42 74 Q40 72 40 68 Z" fill="${B}"/>
      ${[[46, 58], [58, 54], [70, 58], [82, 60], [54, 64], [72, 66]].map(([x, y]) => spark(x, y, 2.4, STAR)).join("")}
      <path d="M94 58 q7 1 9 5 M94 62 q7 3 8 7" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="92" cy="60" r="4.6" fill="${TOOTH}" stroke="${c.line}" stroke-width="1.8"/><circle cx="93" cy="61" r="2.4" fill="${INK}"/>
    </g>`; },

  // ── Starlight Sprite — tiny glowing teardrop wisp, big cute eyes, a crowning star and sparkle motes (float)
  starlightsprite: (c) => { const B = belly(c); return `
    <g class="breathe">
      <circle cx="60" cy="62" r="28" fill="${GLOW}" opacity=".22"/>
      <circle cx="60" cy="62" r="20" fill="${STAR}" opacity=".14"/>
    </g>
    <g class="tail-wag">
      <path d="M46 66 Q34 66 30 76" fill="none" stroke="${c.line}" stroke-width="4.6" stroke-linecap="round"/>
      <path d="M46 66 Q34 66 30 76" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
      <path d="M74 66 Q86 66 90 76" fill="none" stroke="${c.line}" stroke-width="4.6" stroke-linecap="round"/>
      <path d="M74 66 Q86 66 90 76" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M60 40 C47 42 43 58 46 70 C48 82 54 88 60 88 C66 88 72 82 74 70 C77 58 73 42 60 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 60 C53 60 50 70 52 80 Q60 85 68 80 C70 70 67 60 60 60 Z" fill="${B}"/>
    </g>
    <g class="head-tilt">
      ${ceye(53, 62, 4.2)}${ceye(67, 62, 4.2)}
      ${smile(60, 70, 3.2, INK)}
      <circle cx="47" cy="68" r="2.4" fill="${STAR}" opacity=".4"/><circle cx="73" cy="68" r="2.4" fill="${STAR}" opacity=".4"/>
      ${spark(60, 30, 6, STAR)}${spark(30, 44, 3, GLOW)}${spark(92, 48, 3, GLOW)}
    </g>`; },

  // ── Twilight Moth — plush front-facing moth with four galaxy-speckled wings and feathery antennae (float)
  twilightmoth: (c) => { const B = belly(c);
    const wingU = `<path d="M58 56 Q34 34 20 44 Q26 56 40 58 Q26 64 26 78 Q46 74 58 62 Z" fill="${AURA}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".92"/>`;
    const wingL = `<path d="M58 66 Q40 80 40 96 Q52 92 58 82 Z" fill="${NEBULA}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".55"/>`;
    return `
    <g class="tail-wag">${wingU}${wingL}${mirror(wingU)}${mirror(wingL)}
      ${freckles([[34, 48], [44, 54], [30, 66], [40, 70], [86, 48], [76, 54], [90, 66], [80, 70], [50, 88], [70, 88]], 1.3, STAR)}
    </g>
    <g class="breathe">
      ${pom(60, 74, 8, c.shade, c.line, 8, 2.2)}
      ${pom(60, 62, 9, c.body, c.line, 8, 2.2)}
      ${pom(60, 50, 8, c.body, c.line, 8, 2.2)}
      <path d="M60 66 v14" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
    </g>
    <g class="head-tilt">
      <path d="M55 44 Q46 30 40 24 M65 44 Q74 30 80 24" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="40" cy="24" r="2.4" fill="${STAR}"/><circle cx="80" cy="24" r="2.4" fill="${STAR}"/>
      ${eyes(54, 66, 49, 3, eyeInk(c))}
      ${smile(60, 54, 2.6, INK)}
    </g>`; },

  // ── Dawn Pegasus — winged stallion rising over a sunrise glow, streaming mane and tail (float, head right)
  dawnpegasus: (c) => { const E = eyeInk(c);
    const wing = `<path d="M66 60 Q46 30 16 22 Q28 40 33 52 Q21 47 11 51 Q27 61 42 62 Q27 66 19 76 Q45 76 68 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M60 60 Q44 42 28 36 M58 62 Q44 54 32 54 M56 64 Q44 61 34 65" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".55"/>`;
    return `
    <g class="breathe">${rays(60, 96, 30, 44, 9, STAR, 2.4)}<path d="M30 96 A30 30 0 0 1 90 96 Z" fill="${FIRE2}" opacity=".22"/></g>
    <g class="tail-wag">
      <path d="M30 66 Q13 65 8 84 Q16 78 22 74 Q12 89 22 95 Q24 78 34 73 Q42 69 34 63 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M28 72 C28 58 44 54 62 55 C74 56 80 60 80 68 C80 80 70 82 58 82 C40 82 28 80 28 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <rect x="36" y="78" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><rect x="35.5" y="97" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="62" y="78" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><rect x="61.5" y="97" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="46" y="80" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><rect x="45.5" y="96" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="70" y="80" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><rect x="69.5" y="96" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
    </g>
    <g class="head-tilt">
      ${tube("M72 64 Q80 54 88 46", c.body, c.line, 13)}
      <path d="M83 46 Q80 36 89 33 Q97 33 101 40 L105 49 Q108 53 103 57 Q97 59 91 57 Q82 55 83 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M101 51 Q108 53 105 59 Q100 61 96 57 Z" fill="${c.shade}"/>
      <ellipse cx="102" cy="53" rx="1.3" ry="1" fill="${INK}"/>
      <path d="M85 37 Q81 27 88 23 Q93 31 92 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M84 40 Q75 43 78 54 Q70 50 66 58 Q75 56 78 63 Q67 63 63 71 Q77 65 85 59 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(94, 47, 2.8, E)}
      ${spark(90, 20, 3, STAR)}
    </g>
    <g class="tail-wag">${wing}</g>`; },
};

export const ROSTER_CELESTIAL = [
  { n: "Star Dragon",      e: "🐉", tier: 5, float: false },
  { n: "Moon Rabbit",      e: "🌙", tier: 3, float: false },
  { n: "Sun Bird",         e: "☀️", tier: 4, float: false },
  { n: "Comet Fox",        e: "☄️", tier: 4, float: false },
  { n: "Nebula Whale",     e: "🐋", tier: 5, float: true },
  { n: "Galaxy Cat",       e: "🌌", tier: 4, float: false },
  { n: "Aurora Deer",      e: "🦌", tier: 4, float: false },
  { n: "Solar Lion",       e: "🦁", tier: 5, float: false },
  { n: "Lunar Owl",        e: "🦉", tier: 3, float: false },
  { n: "Cosmic Turtle",    e: "🐢", tier: 4, float: false },
  { n: "Meteor Hound",     e: "☄️", tier: 3, float: false },
  { n: "Eclipse Serpent",  e: "🐍", tier: 4, float: false },
  { n: "Nova Phoenix",     e: "🔥", tier: 6, float: true },
  { n: "Void Panther",     e: "🐆", tier: 5, float: false },
  { n: "Astral Stag",      e: "🦌", tier: 4, float: false },
  { n: "Zenith Eagle",     e: "🦅", tier: 4, float: true },
  { n: "Celestial Koi",    e: "🐟", tier: 3, float: true },
  { n: "Starlight Sprite", e: "✨", tier: 3, float: true },
  { n: "Twilight Moth",    e: "🦋", tier: 3, float: true },
  { n: "Dawn Pegasus",     e: "🐴", tier: 5, float: true },
];
