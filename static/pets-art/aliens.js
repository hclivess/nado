// aliens.js — BESPOKE hand-drawn SVG art for ALIENS (extraterrestrial creatures — NADO Pets).
// Each entry is an original, on-spot drawing of ONE creature — no shared/parameterized bodies.
// Contract: inner markup of <svg viewBox="0 0 120 120">, creature centered ~(60,64), within x,y ∈ [8,114].
// HOUSE STYLE: ONE continuous silhouette (c.body fill + c.line outline sw 3.2, linejoin round);
// appendages (tentacles/legs/arms/antennae) tuck BEHIND the body rooted inside it — NOTHING floats;
// two-tone depth via belly(c) + c.shade; a clean cute face. Coats recolour at hatch, so hues come
// from `c` (c.body/c.shade/c.line) — only alien GLOW accents are fixed tints.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const GLOW = "#7fe3ff";   // cyan energy glow / cores / slit eyes
const GLOWG = "#eafff4";  // pale bio-luminescent sheen
const VOID = "#a15cf0";   // cosmic purple / nebula accent

// a glowing energy orb (soft halo + disc + catchlight)
const core = (x, y, r, col = GLOW) =>
  `<circle cx="${x}" cy="${y}" r="${(r + 2.6).toFixed(1)}" fill="${col}" opacity=".22"/>` +
  `<circle cx="${x}" cy="${y}" r="${r}" fill="${col}" stroke="${INK}" stroke-width="1.2"/>` +
  `<circle cx="${(x - r * 0.3).toFixed(1)}" cy="${(y - r * 0.3).toFixed(1)}" r="${(r * 0.32).toFixed(1)}" fill="#fff"/>`;
// a tiny 4-point sparkle star
const star = (x, y, s, col = "#fff") =>
  `<path d="M${x} ${(y - s).toFixed(1)} L${(x + s * 0.3).toFixed(1)} ${(y - s * 0.3).toFixed(1)} L${(x + s).toFixed(1)} ${y} L${(x + s * 0.3).toFixed(1)} ${(y + s * 0.3).toFixed(1)} L${x} ${(y + s).toFixed(1)} L${(x - s * 0.3).toFixed(1)} ${(y + s * 0.3).toFixed(1)} L${(x - s).toFixed(1)} ${y} L${(x - s * 0.3).toFixed(1)} ${(y - s * 0.3).toFixed(1)} Z" fill="${col}"/>`;
// a big glossy eyeball (white sclera + coloured/ink iris) — for stalk & compound eyes
const ball = (x, y, r, iris = INK, line) =>
  `<circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${line}" stroke-width="2.4"/>` +
  `<circle cx="${x}" cy="${(y + r * 0.12).toFixed(1)}" r="${(r * 0.48).toFixed(1)}" fill="${iris}"/>` +
  `<circle cx="${(x - r * 0.28).toFixed(1)}" cy="${(y - r * 0.28).toFixed(1)}" r="${(r * 0.2).toFixed(1)}" fill="#fff"/>`;

export const ART_ALIENS = {
  // ── Grey Alien — classic bulb-head visitor: huge cranium, black slanted almond eyes, thin limbs (front)
  greyalien: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      ${tube("M46 68 Q32 72 27 84", c.body, c.line, 4.5)}
      ${tube("M74 68 Q88 72 93 84", c.body, c.line, 4.5)}
      <path d="M27 84 l-3.5 4 m3.5 -4 l0 5 m0 -5 l3.5 4 M93 84 l-3.5 4 m3.5 -4 l0 5 m0 -5 l3.5 4" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round" fill="none"/>
      ${tube("M50 92 Q46 102 44 110", c.shade, c.line, 4.5)}
      ${tube("M70 92 Q74 102 76 110", c.shade, c.line, 4.5)}
    </g>
    <g class="breathe">
      <path d="M34 44 Q34 16 60 16 Q86 16 86 44 Q86 60 73 65 Q80 74 77 92 Q74 106 60 106 Q46 106 43 92 Q40 74 47 65 Q34 60 34 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="88" rx="12" ry="14" fill="${B}"/>
      <path d="M42 38 Q51 29 60 31 Q53 34 48 43 Z" fill="#fff" opacity=".2"/>
      <path d="M43 48 Q52 41 56 51 Q52 60 44 55 Q39 51 43 48 Z" fill="${INK}"/>
      <path d="M77 48 Q68 41 64 51 Q68 60 76 55 Q81 51 77 48 Z" fill="${INK}"/>
      <circle cx="47" cy="49" r="1.3" fill="#fff" opacity=".85"/><circle cx="73" cy="49" r="1.3" fill="#fff" opacity=".85"/>
      <circle cx="57" cy="62" r="0.9" fill="${c.line}"/><circle cx="63" cy="62" r="0.9" fill="${c.line}"/>
      <path d="M54 68 q6 3.5 12 0" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
    </g>`;
  },

  // ── Little Green Man — cheery pint-size humanoid: round head, bobbing antennae, stubby arms & legs (front)
  littlegreenman: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 20)}
    <g class="tail-wag">
      <path d="M52 30 Q46 14 40 9" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M68 30 Q74 14 80 9" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      ${core(40, 9, 3.2, GLOW)}${core(80, 9, 3.2, GLOW)}
      ${tube("M44 70 Q30 74 26 86", c.body, c.line, 5)}
      ${tube("M76 70 Q90 74 94 86", c.body, c.line, 5)}
      <circle cx="26" cy="87" r="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <circle cx="94" cy="87" r="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
    </g>
    <g class="breathe">
      <rect x="49" y="92" width="9" height="18" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="62" y="92" width="9" height="18" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 44 Q40 24 60 24 Q80 24 80 44 Q80 54 72 58 Q82 62 82 80 Q82 98 60 100 Q38 98 38 80 Q38 62 48 58 Q40 54 40 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="80" rx="15" ry="13" fill="${B}"/>
      <path d="M44 36 Q53 28 61 30 Q54 33 49 41 Z" fill="#fff" opacity=".2"/>
      ${ceye(52, 44, 4.2)}${ceye(68, 44, 4.2)}
      <path d="M53 53 q7 5 14 0" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
    </g>`;
  },

  // ── Xeno Hound — sleek predatory alien beast: raised elongated crest-skull, glowing eye, fanged jaw, whip tail (profile)
  xenohound: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      ${tube("M38 82 Q16 86 12 66 Q10 54 22 54", c.body, c.line, 6)}
      <path d="M22 54 l-9 -5 l3 8 l-8 2 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <rect x="40" y="82" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <rect x="62" y="82" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M28 82 Q24 60 46 56 Q60 54 72 56 Q77 43 90 43 Q106 43 109 58 Q110 63 103 63 L98 57 Q94 66 85 66 Q88 78 80 82 Q54 88 38 84 Q28 86 28 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 56 Q66 46 84 49 Q70 51 60 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M42 80 Q60 86 78 80 Q60 84 42 80 Z" fill="${B}"/>
      <rect x="48" y="82" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <rect x="70" y="82" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      ${core(96, 55, 3.6, GLOW)}
      <path d="M97 61 q5 1 9 -1" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M99 62 l1.2 3 l1.3 -3 Z M103 62 l1.2 3 l1.3 -3 Z" fill="#fff" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Tentacle Beast — one huge cyclopean eye above a nest of suckered tentacles, round gelatin body
  tentaclebeast: (c) => {
    const B = belly(c);
    const arm = (d) => tube(d, c.body, c.line, 6);
    return `
    ${floorShadow(60, 114, 28)}
    <g class="tail-wag">
      ${arm("M42 82 Q34 98 28 110")}
      ${arm("M52 86 Q48 100 44 113")}
      ${arm("M60 88 Q60 102 60 114")}
      ${arm("M68 86 Q72 100 76 113")}
      ${arm("M78 82 Q86 98 92 110")}
      ${[[35, 96], [45, 104], [60, 104], [75, 104], [85, 96]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.8" fill="${c.shade}"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M28 58 Q28 28 60 28 Q92 28 92 58 Q92 82 60 88 Q28 82 28 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="74" rx="22" ry="11" fill="${B}" opacity=".7"/>
      <path d="M38 46 Q52 36 66 40 Q52 44 46 54 Z" fill="#fff" opacity=".18"/>
      <circle cx="60" cy="53" r="16" fill="#fff" stroke="${c.line}" stroke-width="2.6"/>
      <circle cx="60" cy="54" r="9" fill="${GLOW}"/>
      <circle cx="60" cy="55" r="5" fill="${INK}"/>
      <circle cx="56.5" cy="51" r="2.2" fill="#fff"/>
    </g>`;
  },

  // ── Blob Alien — happy gooey glob: wobbly translucent body with drippy base, trio of stalkless eyes, sheen
  blobalien: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M92 50 Q102 50 102 60 Q102 70 92 68 Q88 60 92 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".92"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="70" rx="37" ry="31" fill="${GLOWG}" opacity=".18"/>
      <path d="M26 62 Q26 34 60 34 Q94 34 94 62 Q94 88 88 98 Q82 92 76 98 Q70 92 64 98 Q58 92 52 98 Q46 92 40 98 Q34 92 30 96 Q23 90 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".93"/>
      <path d="M40 46 Q54 38 66 42 Q52 46 46 56 Z" fill="#fff" opacity=".4"/>
      <ellipse cx="50" cy="80" rx="10" ry="6" fill="${c.shade}" opacity=".4"/>
      ${ceye(46, 58, 3.8)}${ceye(60, 54, 4.4)}${ceye(74, 58, 3.8)}
      <path d="M52 70 q8 6 16 0" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
    </g>`;
  },

  // ── Insectoid — upright mantis-alien: heart-shaped head, giant glossy compound eyes, folded raptorial arms, thin legs
  insectoid: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 20)}
    <g class="tail-wag">
      <path d="M50 74 L34 88 M50 82 L36 100 M70 74 L86 88 M70 82 L84 100" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round" fill="none"/>
      ${tube("M54 66 Q44 70 46 80", c.shade, c.line, 4)}
      ${tube("M46 80 Q50 86 58 83", c.shade, c.line, 4)}
      ${tube("M66 66 Q76 70 74 80", c.shade, c.line, 4)}
      ${tube("M74 80 Q70 86 62 83", c.shade, c.line, 4)}
    </g>
    <g class="breathe">
      <path d="M50 40 Q60 27 70 40 Q68 49 61 51 L63 60 Q75 62 73 84 Q71 102 60 104 Q49 102 47 84 Q45 62 57 60 L59 51 Q52 49 50 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="80" rx="9" ry="15" fill="${B}"/>
      <path d="M54 68 h12 M53 76 h14 M54 88 h12" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
      <ellipse cx="51" cy="42" rx="6.5" ry="8" fill="${deepen(c.body, 0.25)}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="69" cy="42" rx="6.5" ry="8" fill="${deepen(c.body, 0.25)}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="49" cy="39" r="2" fill="${GLOW}" opacity=".85"/><circle cx="67" cy="39" r="2" fill="${GLOW}" opacity=".85"/>
      <circle cx="52.5" cy="44" r="1.2" fill="#fff"/><circle cx="70.5" cy="44" r="1.2" fill="#fff"/>
      <path d="M55 51 q5 3 10 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Crystal Alien — living gemstone: faceted diamond body, glowing inner core, shard limbs, bright gem eyes
  crystalalien: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      <path d="M40 62 L24 58 L30 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 62 L96 58 L90 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M40 96 L34 108 L48 106 Z M80 96 L86 108 L72 106 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 26 L84 50 L78 92 L60 104 L42 92 L36 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 26 L60 104 M36 50 L60 60 M84 50 L60 60 M42 92 L60 60 L78 92" stroke="${c.line}" stroke-width="1.3" opacity=".4" fill="none"/>
      <path d="M60 26 L36 50 L60 60 Z" fill="${tint(c.body, 0.22)}"/>
      <path d="M84 50 L60 60 L78 92 Z" fill="${deepen(c.body, 0.14)}"/>
      ${core(60, 74, 5.5, GLOW)}
      <path d="M49 48 l4 5 l-5 3 l-3 -6 Z" fill="${GLOWG}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M71 48 l-4 5 l5 3 l3 -6 Z" fill="${GLOWG}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <circle cx="50" cy="51" r="1.5" fill="${INK}"/><circle cx="70" cy="51" r="1.5" fill="${INK}"/>
      <path d="M54 58 q6 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Floating Brain — psychic hovering brain: wrinkled twin-lobe dome, dangling nerve tendrils, little face (float)
  floatingbrain: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 20)}
    <g class="tail-wag">
      ${tube("M46 74 Q42 92 38 106", c.shade, c.line, 4.5)}
      ${tube("M56 78 Q54 94 52 110", c.shade, c.line, 4.5)}
      ${tube("M64 78 Q66 94 68 110", c.shade, c.line, 4.5)}
      ${tube("M74 74 Q78 92 82 106", c.shade, c.line, 4.5)}
    </g>
    <g class="breathe">
      <path d="M30 54 Q30 30 60 30 Q90 30 90 54 Q90 74 74 80 Q60 84 46 80 Q30 74 30 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 32 Q55 52 60 82" fill="none" stroke="${c.line}" stroke-width="2.2" opacity=".7"/>
      <path d="M36 48 q6 -6 11 0 q5 6 11 0 M35 60 q6 -5 11 0 q5 5 11 0" fill="none" stroke="${c.line}" stroke-width="1.5" opacity=".5"/>
      <path d="M62 48 q6 -6 11 0 q5 6 10 0 M62 60 q6 -5 11 0 q5 5 10 0" fill="none" stroke="${c.line}" stroke-width="1.5" opacity=".5"/>
      <ellipse cx="60" cy="72" rx="16" ry="9" fill="${B}" opacity=".7"/>
      ${ceye(52, 68, 3.6)}${ceye(68, 68, 3.6)}
      <path d="M54 76 q6 4 12 0" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
    </g>`;
  },

  // ── Eye Stalk — a plump body sprouting two long stalks each capped by a big watchful eyeball (front)
  eyestalk: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      ${tube("M52 66 Q45 44 47 30", c.body, c.line, 5)}
      ${tube("M68 66 Q75 44 73 30", c.body, c.line, 5)}
      ${ball(47, 28, 10, INK, c.line)}
      ${ball(73, 28, 10, INK, c.line)}
    </g>
    <g class="breathe">
      <path d="M32 80 Q32 60 60 60 Q88 60 88 80 Q88 100 60 102 Q32 100 32 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="20" ry="11" fill="${B}"/>
      <path d="M40 72 Q52 64 66 68 Q52 72 46 80 Z" fill="#fff" opacity=".16"/>
      <path d="M50 84 Q60 92 70 84 Q60 88 50 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Slime Alien — translucent jelly critter: glossy wobble dome, inner bubbles, glowing sheen, sweet face (front)
  slimealien: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M90 46 Q100 46 100 56 Q100 66 90 64 Q86 56 90 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".9"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="70" rx="37" ry="31" fill="${GLOWG}" opacity=".22"/>
      <path d="M28 64 Q28 38 60 38 Q92 38 92 64 Q92 92 86 98 Q80 92 74 98 Q68 92 62 98 Q56 92 50 98 Q44 92 38 98 Q32 92 28 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".9"/>
      <path d="M40 48 Q54 39 67 43 Q52 47 46 57 Z" fill="#fff" opacity=".5"/>
      <circle cx="72" cy="66" r="5.5" fill="#fff" opacity=".2"/>
      <circle cx="44" cy="76" r="3.4" fill="${GLOW}" opacity=".35"/><circle cx="76" cy="82" r="2.6" fill="${GLOW}" opacity=".35"/>
      ${ceye(51, 66, 4)}${ceye(69, 66, 4)}
      ${smile(60, 74, 4.2, INK)}
    </g>`;
  },

  // ── Bug-eyed Alien — tiny visitor overwhelmed by two enormous glassy compound eyes, dot antennae (front)
  bugeyedalien: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 20)}
    <g class="tail-wag">
      <path d="M50 24 Q46 12 40 8" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      <path d="M70 24 Q74 12 80 8" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      ${core(40, 8, 2.6, GLOW)}${core(80, 8, 2.6, GLOW)}
      ${tube("M44 72 Q32 78 30 90", c.body, c.line, 4.5)}
      ${tube("M76 72 Q88 78 90 90", c.body, c.line, 4.5)}
    </g>
    <g class="breathe">
      <rect x="50" y="94" width="8" height="16" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <rect x="62" y="94" width="8" height="16" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M40 46 Q40 24 60 24 Q80 24 80 46 Q80 56 72 60 Q80 64 80 82 Q80 98 60 100 Q40 98 40 82 Q40 64 48 60 Q40 56 40 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="82" rx="14" ry="12" fill="${B}"/>
      <circle cx="48" cy="44" r="14" fill="${deepen(c.body, 0.3)}" stroke="${c.line}" stroke-width="2.6"/>
      <circle cx="72" cy="44" r="14" fill="${deepen(c.body, 0.3)}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M40 40 Q46 34 54 36 M64 40 Q70 34 78 36" fill="none" stroke="${GLOW}" stroke-width="2.4" stroke-linecap="round" opacity=".7"/>
      <circle cx="43" cy="49" r="3" fill="#fff" opacity=".8"/><circle cx="67" cy="49" r="3" fill="#fff" opacity=".8"/>
      <path d="M55 68 q5 3 10 0" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
    </g>`;
  },

  // ── Reptilian — upright lizard-man: scaled snout, crest ridge, slit-pupil eyes, plated belly, whip tail (front)
  reptilian: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      ${tube("M50 92 Q28 96 24 78 Q22 68 32 68", c.body, c.line, 7)}
      <path d="M32 68 l-9 -3 l4 8 l-8 2 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${tube("M46 70 Q34 78 34 90", c.body, c.line, 5)}
      ${tube("M74 70 Q86 78 86 90", c.body, c.line, 5)}
      <path d="M46 100 l-3 4 m3 -4 l0 5 m0 -5 l4 4 M74 100 l-3 4 m3 -4 l0 5 m0 -5 l4 4" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" fill="none"/>
      <path d="M44 98 Q40 62 48 54 Q42 48 44 38 Q46 24 60 24 Q74 24 76 38 Q78 48 72 54 Q80 62 76 98 Q60 106 44 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M54 20 l3 -6 l3 6 M62 20 l3 -6 l3 6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M50 62 Q60 58 70 62 L68 92 Q60 96 52 92 Z" fill="${B}"/>
      <path d="M52 70 h16 M52 78 h16 M53 86 h14" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>
      <path d="M44 44 Q42 36 36 34 Q42 40 44 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <ellipse cx="52" cy="41" rx="4.4" ry="3.6" fill="#fff" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="68" cy="41" rx="4.4" ry="3.6" fill="#fff" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M52 38 v6 M68 38 v6" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="41" cy="46" r="0.9" fill="${c.line}"/>
      <path d="M46 50 q6 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Star Spawn — brooding cosmic-horror godling: bulky hunched body, small membrane wings, face full of tentacles
  starspawn: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 30)}
    <g class="tail-wag">
      <path d="M40 60 Q18 46 14 58 Q24 60 30 66 Q20 66 18 76 Q34 72 44 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 60 Q102 46 106 58 Q96 60 90 66 Q100 66 102 76 Q86 72 76 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M36 100 Q30 64 48 56 Q42 48 44 38 Q46 24 60 24 Q74 24 76 38 Q78 48 72 56 Q90 64 84 100 Q60 108 36 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="18" ry="14" fill="${B}"/>
      <path d="M44 34 Q53 27 60 29 Q52 32 47 41 Z" fill="#fff" opacity=".16"/>
      ${ceye(51, 40, 3.6)}${ceye(69, 40, 3.6)}
      <path d="M45 35 q5 -3 10 -1 M65 34 q5 -2 10 1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" opacity=".55"/>
    </g>
    <g class="tail-wag">
      ${tube("M48 50 Q44 68 40 84", c.shade, c.line, 4.5)}
      ${tube("M54 52 Q52 70 50 88", c.shade, c.line, 4.5)}
      ${tube("M60 52 Q60 72 60 90", c.shade, c.line, 4.5)}
      ${tube("M66 52 Q68 70 70 88", c.shade, c.line, 4.5)}
      ${tube("M72 50 Q76 68 80 84", c.shade, c.line, 4.5)}
    </g>`;
  },

  // ── Void Crawler — dark many-legged skitterer: segmented low body, ranks of thin legs, cluster of glowing eyes
  voidcrawler: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 32)}
    <g class="tail-wag">
      ${[28, 40, 52, 64].map((x) => `<path d="M${x} 76 Q${x - 8} 86 ${x - 12} 100 M${x} 76 Q${x - 2} 88 ${x} 100" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round" fill="none"/>`).join("")}
      ${[40, 52, 64, 76].map((x) => `<path d="M${x} 76 Q${x + 8} 86 ${x + 12} 100 M${x} 76 Q${x + 2} 88 ${x} 100" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round" fill="none"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M22 64 Q22 48 42 48 L78 48 Q100 48 100 66 Q100 82 78 82 L42 82 Q22 82 22 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M36 50 Q36 82 36 82 M50 49 Q50 82 50 82 M64 49 Q64 82 64 82 M78 50 Q78 82 78 82" stroke="${c.line}" stroke-width="1.3" opacity=".35" fill="none"/>
      <path d="M30 74 Q60 82 92 74 Q60 78 30 74 Z" fill="${B}" opacity=".6"/>
      <path d="M100 60 Q112 56 116 62 Q112 66 104 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${[[90, 58], [98, 60], [90, 66], [98, 68]].map(([x, y]) => core(x, y, 2.4, GLOW)).join("")}
    </g>`;
  },

  // ── Cosmic Jelly — luminous alien jellyfish: glowing translucent bell, frilled + trailing tentacles, starlit dome (float)
  cosmicjelly: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 22)}
    <g class="tail-wag">
      ${tube("M42 66 Q38 88 34 106", c.body, c.line, 4.5)}
      ${tube("M50 68 Q48 90 46 110", c.body, c.line, 4.5)}
      ${tube("M60 68 Q60 92 60 112", c.body, c.line, 4.5)}
      ${tube("M70 68 Q72 90 74 110", c.body, c.line, 4.5)}
      ${tube("M78 66 Q82 88 86 106", c.body, c.line, 4.5)}
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="56" rx="36" ry="32" fill="${GLOW}" opacity=".16"/>
      <path d="M28 60 Q28 30 60 30 Q92 30 92 60 Q92 68 86 70 Q80 64 74 70 Q68 64 62 70 Q56 64 50 70 Q44 64 38 70 Q32 66 28 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".92"/>
      <path d="M40 44 Q54 35 67 39 Q52 43 46 53 Z" fill="#fff" opacity=".4"/>
      ${star(44, 50, 2.4, GLOWG)}${star(76, 46, 2, GLOWG)}${star(66, 58, 1.6, "#fff")}
      ${ceye(51, 52, 3.8)}${ceye(69, 52, 3.8)}
      ${smile(60, 60, 3.6, INK)}
    </g>`;
  },

  // ── Astro Hound — space-suited pup: bubble helmet, padded suit with chest gauge, boots, aerial tail (front)
  astrohound: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${tube("M80 88 Q98 84 96 68", c.body, c.line, 6)}
      <circle cx="96" cy="67" r="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
    </g>
    <g class="breathe">
      <rect x="44" y="98" width="13" height="14" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      <rect x="63" y="98" width="13" height="14" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M38 96 Q34 68 60 66 Q86 68 82 96 Q60 104 38 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="86" rx="15" ry="12" fill="${B}"/>
      <rect x="52" y="78" width="16" height="12" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      ${core(60, 84, 2.6, GLOW)}
      <path d="M40 74 q6 3 0 8 M80 74 q-6 3 0 8" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".45"/>
    </g>
    <g class="head-tilt">
      <path d="M40 44 L34 26 L52 38 Z M80 44 L86 26 L68 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <circle cx="60" cy="46" r="21" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="60" cy="54" rx="12" ry="9" fill="${B}"/>
      ${ceye(52, 44, 4)}${ceye(68, 44, 4)}
      <path d="M60 52 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 55 v3 M60 58 q-4 2 -7 1 M60 58 q4 2 7 1" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="60" cy="46" r="27" fill="#fff" opacity=".1" stroke="${GLOW}" stroke-width="2.2"/>
      <path d="M44 34 Q40 46 46 58" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" opacity=".55"/>
    </g>`;
  },

  // ── Nebula Bug — glowing moth-alien: broad luminous wings with star-ocelli, fuzzy body, feathered antennae (float)
  nebulabug: (c) => {
    const B = belly(c);
    const wing = `
      <path d="M58 62 Q28 40 14 52 Q22 62 32 62 Q20 70 24 84 Q44 78 58 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M56 64 Q38 52 26 56 Q36 60 40 66 Z" fill="${c.shade}"/>
      ${core(32, 58, 3.4, GLOW)}${star(26, 72, 2.4, VOID)}${star(44, 60, 1.8, "#fff")}`;
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M60 42 Q72 44 72 60 L70 88 Q60 96 50 88 L48 60 Q48 44 60 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M53 62 h14 M52 70 h16 M52 78 h16 M53 86 h14" stroke="${c.line}" stroke-width="1.3" opacity=".45"/>
      <path d="M55 60 Q60 58 65 60 L64 86 Q60 90 56 86 Z" fill="${B}" opacity=".65"/>
    </g>
    <g class="head-tilt">
      <path d="M52 42 Q46 28 38 24 Q46 30 47 42 M52 42 Q48 32 43 30" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <path d="M68 42 Q74 28 82 24 Q74 30 73 42 M68 42 Q72 32 77 30" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="60" cy="47" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      ${ceye(55, 46, 3.4)}${ceye(65, 46, 3.4)}
      ${smile(60, 51, 3, INK)}
    </g>`;
  },

  // ── Comet Rider — tiny grey visitor surfing a glowing comet with a sparkling ice-fire trail (float)
  cometrider: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(58, 112, 24)}
    <g class="tail-wag">
      <path d="M40 76 Q14 78 6 86 Q22 86 30 82 Q16 92 12 100 Q30 90 44 86 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".55"/>
      ${star(20, 82, 2.4, "#fff")}${star(28, 94, 2, GLOWG)}${star(12, 90, 1.6, VOID)}
    </g>
    <g class="breathe">
      <circle cx="60" cy="78" r="24" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="60" cy="86" rx="15" ry="9" fill="${B}" opacity=".7"/>
      <circle cx="50" cy="72" r="3" fill="${c.shade}"/><circle cx="70" cy="82" r="2.4" fill="${c.shade}"/><circle cx="62" cy="70" r="2" fill="${c.shade}"/>
      <path d="M44 66 Q56 58 68 62 Q54 66 48 76 Z" fill="#fff" opacity=".18"/>
    </g>
    <g class="head-tilt">
      ${tube("M50 58 Q42 50 36 46", c.shade, c.line, 3.6)}
      ${tube("M70 58 Q78 50 84 46", c.shade, c.line, 3.6)}
      <path d="M48 52 Q48 36 60 36 Q72 36 72 52 Q72 60 60 62 Q48 60 48 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M52 50 Q50 45 54 46 Q52 49 54 52 Z" fill="${INK}"/>
      <path d="M68 50 Q70 45 66 46 Q68 49 66 52 Z" fill="${INK}"/>
      <path d="M56 55 q4 2 8 0" fill="none" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>
    </g>`;
  },

  // ── Meteor Slug — cosmic mollusc: soft gliding foot, cratered rocky meteor shell, curious eye-stalks (profile)
  meteorslug: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 32)}
    <g class="tail-wag">
      ${tube("M84 72 Q88 54 86 42", c.body, c.line, 4)}
      ${tube("M92 74 Q98 58 98 46", c.body, c.line, 4)}
      ${ball(86, 40, 6, INK, c.line)}
      ${ball(98, 44, 6, INK, c.line)}
    </g>
    <g class="breathe">
      <path d="M18 90 Q16 78 32 76 L84 74 Q104 76 104 88 Q102 96 86 96 L28 98 Q18 98 18 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M26 92 Q60 98 100 90" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
      <path d="M34 78 Q38 48 60 46 Q82 48 86 78 Q60 86 34 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <circle cx="52" cy="62" r="5" fill="${deepen(c.body, 0.22)}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="68" cy="58" r="4" fill="${deepen(c.body, 0.22)}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="62" cy="72" r="3.4" fill="${deepen(c.body, 0.22)}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="44" cy="72" r="2.6" fill="${deepen(c.body, 0.22)}" stroke="${c.line}" stroke-width="1.2"/>
      <path d="M84 84 Q92 82 96 86" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
      <path d="M88 88 q5 2 9 -1" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Galaxy Squid — drifting star-filled cephalopod: pointed starry mantle, side fins, dangling arms, big eyes (float)
  galaxysquid: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 22)}
    <g class="tail-wag">
      ${tube("M46 74 Q40 92 34 106", c.body, c.line, 4.5)}
      ${tube("M53 78 Q50 94 47 110", c.body, c.line, 4.5)}
      ${tube("M60 80 Q60 96 60 112", c.body, c.line, 4.5)}
      ${tube("M67 78 Q70 94 73 110", c.body, c.line, 4.5)}
      ${tube("M74 74 Q80 92 86 106", c.body, c.line, 4.5)}
    </g>
    <g class="breathe">
      <path d="M32 60 Q30 46 40 40 Q34 54 44 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M88 60 Q90 46 80 40 Q86 54 76 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 18 Q82 30 82 58 Q82 76 60 80 Q38 76 38 58 Q38 30 60 18 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 34 Q58 24 68 30 Q54 32 48 44 Z" fill="#fff" opacity=".16"/>
      ${star(50, 40, 2.4, "#fff")}${star(70, 36, 2, GLOWG)}${star(62, 50, 1.8, VOID)}${star(44, 54, 1.6, "#fff")}${star(74, 54, 1.6, GLOW)}
      ${ceye(51, 66, 4)}${ceye(69, 66, 4)}
      ${smile(60, 73, 3.4, INK)}
    </g>`;
  },
};

export const ROSTER_ALIENS = [
  { n: "Grey Alien",       e: "👽", tier: 3, float: false },
  { n: "Little Green Man", e: "👽", tier: 2, float: false },
  { n: "Xeno Hound",       e: "👾", tier: 3, float: false },
  { n: "Tentacle Beast",   e: "👾", tier: 3, float: false },
  { n: "Blob Alien",       e: "👾", tier: 2, float: false },
  { n: "Insectoid",        e: "👾", tier: 3, float: false },
  { n: "Crystal Alien",    e: "👾", tier: 3, float: false },
  { n: "Floating Brain",   e: "👾", tier: 3, float: true },
  { n: "Eye Stalk",        e: "👾", tier: 2, float: false },
  { n: "Slime Alien",      e: "👾", tier: 2, float: false },
  { n: "Bug-eyed Alien",   e: "👽", tier: 2, float: false },
  { n: "Reptilian",        e: "👽", tier: 3, float: false },
  { n: "Star Spawn",       e: "👾", tier: 4, float: false },
  { n: "Void Crawler",     e: "👾", tier: 3, float: false },
  { n: "Cosmic Jelly",     e: "🛸", tier: 3, float: true },
  { n: "Astro Hound",      e: "🛸", tier: 3, float: false },
  { n: "Nebula Bug",       e: "🛸", tier: 2, float: true },
  { n: "Comet Rider",      e: "🛸", tier: 3, float: true },
  { n: "Meteor Slug",      e: "👾", tier: 2, float: false },
  { n: "Galaxy Squid",     e: "🛸", tier: 3, float: true },
];
