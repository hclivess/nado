// pets-art/undead.js — BESPOKE hand-drawn SVG art for the UNDEAD batch (NADO Pets).
// Spooky-but-cute mascots. ONE continuous c.body silhouette (thick rounded outline) per creature;
// tails/capes/sleeves/wisps tucked into <g class="tail-wag"> so nothing floats; two-tone shading via
// belly()/c.shade; cute glossy faces (ceye) or eerie glowing sockets. Eerie accents used SPARINGLY:
//   GLOW (eyes/aura), BONE (teeth/bone bits), FIRE/FIRE2 (necro/lich magic), GOLD (crowns/belts).
// The MAIN body always recolours via the coat object c = { body, shade, line } (applied at runtime).
// viewBox 0 0 120 120, creature centered ~ (60,64), within x,y ∈ [8,116].
import { INK, ceye, floorShadow, belly, tint, deepen, tube, pom, mirror, eye, eyes, smile } from "../pets-draw.js";

// fixed eerie accents that stay constant across coats
const GLOW = "#eafff4", BONE = "#f4efe2", FIRE = "#ff7a1a", FIRE2 = "#ffd24a", GOLD = "#f2c94c", TOOTH = "#ffffff";

// hollow eye-socket with a tiny spark of soul-light (skeletons / skulls)
const socket = (x, y, r = 5) => `<ellipse cx="${x}" cy="${y}" rx="${r}" ry="${(r * 1.1).toFixed(1)}" fill="${INK}"/><circle cx="${x}" cy="${(y + r * 0.15).toFixed(1)}" r="${(r * 0.3).toFixed(1)}" fill="${GLOW}"/>`;
// a glowing eerie eye (bright halo, glow disc, dark pupil) — menacing undead stare
const glowEye = (x, y, r = 4) => `<circle cx="${x}" cy="${y}" r="${(r + 1.6).toFixed(1)}" fill="${GLOW}" opacity=".3"/><circle cx="${x}" cy="${y}" r="${r}" fill="${GLOW}" stroke="${INK}" stroke-width="1.4"/><circle cx="${x}" cy="${y}" r="${(r * 0.42).toFixed(1)}" fill="${INK}"/>`;

export const ART_UNDEAD = {
  // ── Skeleton — bare skull + ribcage, hollow soul-lit sockets, bone teeth, thin bone limbs (front)
  skeleton: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      ${tube("M44 62 Q30 66 30 82", c.body, c.line, 5)}
      ${tube("M76 62 Q90 66 90 82", c.body, c.line, 5)}
    </g>
    <g class="breathe">
      ${tube("M52 88 L50 108", c.body, c.line, 6)}${tube("M68 88 L70 108", c.body, c.line, 6)}
      <ellipse cx="49" cy="110" rx="6" ry="3.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <ellipse cx="71" cy="110" rx="6" ry="3.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M38 42 Q38 18 60 18 Q82 18 82 42 Q82 54 74 58 L74 62 Q86 66 86 82 Q86 94 60 94 Q34 94 34 82 Q34 66 46 62 L46 58 Q38 54 38 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M42 66 Q60 74 78 66 Q80 84 60 90 Q40 84 42 66 Z" fill="${B}"/>
      <path d="M48 70 Q60 76 72 70 M46 76 Q60 83 74 76 M48 82 Q60 88 72 82" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" opacity=".6"/>
      <path d="M60 66 V90" stroke="${c.line}" stroke-width="1.6" opacity=".45"/>
      ${socket(51, 41, 5)}${socket(69, 41, 5)}
      <path d="M60 46 l-2.5 5 h5 Z" fill="${INK}"/>
      ${[52, 56, 60, 64, 68].map(x => `<rect x="${x - 1.4}" y="53" width="2.8" height="4.4" rx="0.6" fill="${BONE}" stroke="${c.line}" stroke-width="0.6"/>`).join("")}
    </g>`;
  },

  // ── Zombie — slouched, stitched, droopy asymmetric eyes, gaping toothy moan, arms outstretched (front)
  zombie: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${tube("M40 66 Q26 68 20 76", c.body, c.line, 8)}
      ${tube("M80 66 Q94 68 100 76", c.body, c.line, 8)}
      <rect x="13" y="72" width="10" height="9" rx="2" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <rect x="97" y="72" width="10" height="9" rx="2" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    </g>
    <g class="breathe">
      ${tube("M52 96 L51 110", c.body, c.line, 7)}${tube("M68 96 L69 110", c.body, c.line, 7)}
      <path d="M40 46 Q38 24 60 22 Q82 22 82 44 Q82 54 76 58 Q84 62 84 82 Q84 100 60 100 Q36 100 36 82 Q36 62 44 58 Q40 54 40 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="80" rx="18" ry="15" fill="${B}"/>
      <path d="M46 74 H74" stroke="${c.line}" stroke-width="1.4"/>
      ${[48, 54, 60, 66, 72].map(x => `<path d="M${x} 71 v6" stroke="${c.line}" stroke-width="1.2"/>`).join("")}
      <circle cx="52" cy="46" r="6" fill="#fff" stroke="${c.line}" stroke-width="1.6"/><circle cx="52" cy="48" r="2.6" fill="${INK}"/>
      <circle cx="69" cy="44" r="4.4" fill="#fff" stroke="${c.line}" stroke-width="1.6"/><circle cx="69" cy="45" r="2" fill="${INK}"/>
      <path d="M43 53 l4 4 M45 51 v8 M73 39 l4 4 M75 37 v8" stroke="${c.line}" stroke-width="1.1" stroke-linecap="round"/>
      <path d="M50 60 Q60 70 70 60 Q60 66 50 60 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M55 61 v4 M61 62 v4" stroke="${TOOTH}" stroke-width="1.4"/>
      <path d="M55 22 l1 -6 l3 5 l3 -6 l2 6" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Ghost — classic sheeted spook, scalloped wispy hem, little arm nubs, big cute eyes, "boo" mouth (float)
  ghost: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 16)}
    <g class="tail-wag">
      <path d="M46 92 Q40 104 44 114 Q48 106 50 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".9"/>
      <path d="M74 92 Q80 104 76 114 Q72 106 70 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".9"/>
    </g>
    <g class="breathe">
      <path d="M28 66 Q28 26 60 26 Q92 26 92 66 L92 96 Q86 90 80 96 Q74 90 68 96 Q62 90 60 96 Q58 90 52 96 Q46 90 40 96 Q34 90 28 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".96"/>
      <path d="M28 60 Q18 62 20 72 Q26 68 30 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M92 60 Q102 62 100 72 Q94 68 90 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="22" ry="20" fill="${B}" opacity=".65"/>
      ${ceye(50, 54, 5)}${ceye(70, 54, 5)}
      <ellipse cx="60" cy="72" rx="6" ry="8" fill="${INK}"/>
      <circle cx="42" cy="64" r="3" fill="${c.shade}" opacity=".4"/><circle cx="78" cy="64" r="3" fill="${c.shade}" opacity=".4"/>
    </g>`;
  },

  // ── Lich — crowned skull sorcerer in a robe, glowing eyes, floating foxfire wisp (front)
  lich: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 26)}
    <g class="tail-wag">
      <path d="M22 72 Q17 61 24 54 Q21 63 28 67 Q26 74 22 72 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <circle cx="24" cy="61" r="2" fill="${FIRE2}"/>
    </g>
    <g class="breathe">
      <path d="M60 52 Q46 52 40 70 L30 108 Q60 116 90 108 L80 70 Q74 52 60 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 58 L52 108 Q60 111 68 108 Z" fill="${B}" opacity=".55"/>
      <path d="M46 78 Q60 84 74 78 M44 92 Q60 99 76 92" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      <path d="M40 66 Q28 74 30 90 Q36 82 44 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M80 66 Q92 74 90 90 Q84 82 76 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M42 46 Q42 60 60 60 Q78 60 78 46 Q76 60 68 62 L52 62 Q44 60 42 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M44 40 Q44 20 60 20 Q76 20 76 40 Q76 50 70 54 L70 58 Q60 62 50 58 L50 54 Q44 50 44 40 Z" fill="${BONE}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 24 L44 12 L50 20 L54 10 L60 20 L66 10 L70 20 L76 12 L78 24 Q60 30 42 24 Z" fill="${GOLD}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${[50, 60, 70].map(x => `<circle cx="${x}" cy="16" r="1.7" fill="${FIRE2}"/>`).join("")}
      ${glowEye(52, 40, 4)}${glowEye(68, 40, 4)}
      <path d="M60 44 l-2 5 h4 Z" fill="${INK}"/>
      <path d="M52 55 h16" stroke="${c.line}" stroke-width="1"/>
      ${[54, 58, 62, 66].map(x => `<path d="M${x} 53 v4" stroke="${c.line}" stroke-width="1"/>`).join("")}
    </g>`;
  },

  // ── Vampire — high-collared cape, pale face, slicked widow's-peak hair, fangs (front)
  vampire: (c) => {
    const P = belly(c);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M56 46 Q20 50 14 96 Q30 84 44 84 Q34 92 40 100 Q52 86 60 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M64 46 Q100 50 106 96 Q90 84 76 84 Q86 92 80 100 Q68 86 60 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M42 60 Q40 50 60 50 Q80 50 78 60 L84 104 Q60 110 36 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 56 L40 40 Q60 52 80 40 L76 56 Q60 62 44 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 60 L60 96 L68 60 Q60 66 52 60 Z" fill="${P}"/>
      <circle cx="60" cy="74" r="1.6" fill="${c.line}"/><circle cx="60" cy="84" r="1.6" fill="${c.line}"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="34" r="17" fill="${P}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M43 32 Q42 16 60 14 Q78 16 77 32 Q70 24 60 30 Q50 24 43 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 22 V30" stroke="${c.line}" stroke-width="1.2"/>
      ${ceye(53, 36, 3.6)}${ceye(67, 36, 3.6)}
      <path d="M49 30 l7 2 M71 30 l-7 2" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M52 42 Q60 48 68 42" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M55 43 l1.5 4 l1.5 -4 Z M63 43 l1.5 4 l1.5 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Mummy — wrapped from head to toe, one peeking soul-lit eye, loose trailing bandage (front)
  mummy: (c) => {
    const W = tint(c.body, 0.5);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      <path d="M78 84 Q96 88 98 104 Q92 96 84 96 Q90 102 86 108 Q80 98 74 92 Z" fill="${W}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${tube("M42 64 Q28 66 22 76", W, c.line, 8)}
      ${tube("M78 64 Q92 66 98 76", W, c.line, 8)}
      <path d="M40 50 Q38 30 60 30 Q82 30 80 50 L86 104 Q60 110 34 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[38, 48, 58, 68, 78, 88, 98].map((y, i) => `<path d="M34 ${y} Q60 ${y + (i % 2 ? 6 : -2)} 86 ${y}" fill="none" stroke="${c.line}" stroke-width="1.5" opacity=".5"/>`).join("")}
      <path d="M36 60 L84 66 M36 78 L86 72 M34 92 L86 96" stroke="${W}" stroke-width="3" stroke-linecap="round" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="36" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M44 30 Q60 34 76 28 M43 40 Q60 46 77 40 M46 48 Q60 52 74 48" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".55"/>
      <path d="M44 34 L76 32 M45 44 L75 44" stroke="${W}" stroke-width="2.6" stroke-linecap="round" opacity=".7"/>
      <path d="M50 36 Q56 32 62 36 Q56 40 50 36 Z" fill="${INK}"/>
      <circle cx="56" cy="36" r="2.4" fill="${GLOW}"/><circle cx="56" cy="36" r="1.1" fill="${INK}"/>
      <path d="M66 34 l6 3" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Wraith — hooded void, pointed cowl, tattered flowing hem, empty grasping sleeves, glowing stare (float)
  wraith: (c) => {
    return `
    ${floorShadow(60, 114, 16)}
    <g class="tail-wag">
      <path d="M40 86 Q34 104 40 116 Q44 106 48 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 86 Q86 104 80 116 Q76 106 72 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 14 Q40 20 38 44 Q36 60 44 70 L34 100 Q42 92 48 98 Q54 90 60 98 Q66 90 72 98 Q78 92 86 100 L76 70 Q84 60 82 44 Q80 20 60 14 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 26 Q46 30 46 46 Q46 58 60 60 Q74 58 74 46 Q74 30 60 26 Z" fill="${INK}"/>
      <circle cx="53" cy="44" r="3.4" fill="${GLOW}"/><circle cx="67" cy="44" r="3.4" fill="${GLOW}"/>
      <circle cx="53" cy="45" r="1.4" fill="${INK}"/><circle cx="67" cy="45" r="1.4" fill="${INK}"/>
      <path d="M40 60 Q26 66 22 80 Q30 74 38 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M80 60 Q94 66 98 80 Q90 74 82 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Banshee — wailing spirit, long streaming hair, anguished hollow eyes, screaming mouth (float)
  banshee: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 16)}
    <g class="tail-wag">
      <path d="M40 40 Q18 54 16 86 Q26 70 36 66 Q26 82 30 96 Q40 70 46 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 40 Q102 54 104 86 Q94 70 84 66 Q94 82 90 96 Q80 70 74 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M44 46 Q44 30 60 30 Q76 30 76 46 L84 96 Q72 88 66 96 Q60 88 54 96 Q48 88 36 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".96"/>
      <path d="M52 50 L56 92 M68 50 L64 92" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
    </g>
    <g class="head-tilt">
      <path d="M42 40 Q40 18 60 16 Q80 18 78 40 Q70 30 60 32 Q50 30 42 40 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="60" cy="42" r="15" fill="${B}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="53" cy="40" rx="3.2" ry="4" fill="${INK}"/><ellipse cx="67" cy="40" rx="3.2" ry="4" fill="${INK}"/>
      <circle cx="53" cy="41" r="1.2" fill="${GLOW}"/><circle cx="67" cy="41" r="1.2" fill="${GLOW}"/>
      <path d="M48 34 q5 -3 9 -1 M63 33 q5 -2 9 1" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <ellipse cx="60" cy="52" rx="5" ry="7" fill="${INK}"/>
      <ellipse cx="60" cy="49" rx="2.6" ry="2" fill="${c.shade}" opacity=".5"/>
    </g>`;
  },

  // ── Ghoul — gaunt hunched flesh-eater, sunken cheeks, raised bone claws, wide fanged maw (front)
  ghoul: (c) => {
    const S = deepen(c.body, 0.16);
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      ${tube("M44 66 Q30 58 26 46", c.body, c.line, 6)}
      ${tube("M76 66 Q90 58 94 46", c.body, c.line, 6)}
      <path d="M26 46 l-3 -6 M26 46 v-7 M26 46 l3 -6" stroke="${BONE}" stroke-width="2" stroke-linecap="round"/>
      <path d="M94 46 l-3 -6 M94 46 v-7 M94 46 l3 -6" stroke="${BONE}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      ${tube("M52 92 L50 108", c.body, c.line, 6)}${tube("M68 92 L70 108", c.body, c.line, 6)}
      <path d="M46 64 Q42 78 48 94 Q60 100 72 94 Q78 78 74 64 Q60 70 46 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 74 Q60 78 70 74 M50 82 Q60 86 70 82" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      <path d="M40 44 Q38 22 60 22 Q82 22 80 44 Q80 58 60 64 Q40 58 40 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 46 Q50 54 48 60 Q42 54 44 46 Z" fill="${S}"/><path d="M76 46 Q70 54 72 60 Q78 54 76 46 Z" fill="${S}"/>
      <ellipse cx="51" cy="42" rx="5" ry="4" fill="${S}"/><ellipse cx="69" cy="42" rx="5" ry="4" fill="${S}"/>
      <circle cx="51" cy="42" r="2.4" fill="${GLOW}"/><circle cx="69" cy="42" r="2.4" fill="${GLOW}"/>
      <circle cx="51" cy="42" r="1" fill="${INK}"/><circle cx="69" cy="42" r="1" fill="${INK}"/>
      <path d="M46 52 Q60 62 74 52 Q60 58 46 52 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${[50, 55, 60, 65, 70].map((x, i) => `<path d="M${x} 52 l1.4 ${i % 2 ? 4 : 3} l1.4 -${i % 2 ? 4 : 3} Z" fill="${BONE}" stroke="${c.line}" stroke-width="0.5"/>`).join("")}
    </g>`;
  },

  // ── Revenant — armored risen warrior, crested helm, glowing eye-slits, plated torso, gauntlet fists (front)
  revenant: (c) => {
    const M = tint(c.body, 0.3);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="breathe">
      ${tube("M50 98 L48 110", c.shade, c.line, 8)}${tube("M70 98 L72 110", c.shade, c.line, 8)}
      ${tube("M40 66 Q30 76 32 90", c.body, c.line, 8)}${tube("M80 66 Q90 76 88 90", c.body, c.line, 8)}
      <circle cx="33" cy="92" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><circle cx="87" cy="92" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <path d="M42 58 Q40 50 60 50 Q80 50 78 58 L82 98 Q60 104 38 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M42 58 Q28 56 30 70 Q40 64 46 66 Z" fill="${M}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 58 Q92 56 90 70 Q80 64 74 66 Z" fill="${M}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 70 Q60 76 80 70 M42 84 Q60 90 78 84" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".55"/>
      <path d="M60 60 V98" stroke="${c.line}" stroke-width="1.4" opacity=".45"/>
      <circle cx="60" cy="66" r="4" fill="${M}" stroke="${c.line}" stroke-width="1.4"/>
    </g>
    <g class="head-tilt">
      <path d="M44 40 Q44 22 60 22 Q76 22 76 40 Q76 52 60 56 Q44 52 44 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M56 22 Q60 10 64 22 Z" fill="${M}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M48 40 Q48 34 60 34 Q72 34 72 40 L72 48 Q60 52 48 48 Z" fill="${INK}"/>
      <rect x="50" y="41" width="8" height="3.4" rx="1.5" fill="${GLOW}"/><rect x="62" y="41" width="8" height="3.4" rx="1.5" fill="${GLOW}"/>
      <path d="M60 34 V52" stroke="${c.line}" stroke-width="1.6"/>
    </g>`;
  },

  // ── Wight — grave-shrouded lord, dark cowl over a gaunt pale face, glowing narrow eyes, clasped bone hands (front)
  wight: (c) => {
    const S = deepen(c.body, 0.16);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      <path d="M36 84 Q26 98 30 110 Q34 100 40 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 84 Q94 98 90 110 Q86 100 80 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 18 Q40 24 40 46 L34 104 Q60 110 86 104 L80 46 Q80 24 60 18 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 54 L44 100 M60 58 L60 104 M74 54 L76 100" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".4"/>
      <ellipse cx="60" cy="80" rx="11" ry="7" fill="${S}"/>
      <path d="M54 78 l2 6 M58 77 l1 7 M62 77 l-1 7 M66 78 l-2 6" stroke="${BONE}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M46 40 Q46 24 60 24 Q74 24 74 40 Q74 54 60 58 Q46 54 46 40 Z" fill="${INK}"/>
      <path d="M50 40 Q50 30 60 30 Q70 30 70 40 Q70 50 60 54 Q50 50 50 40 Z" fill="${belly(c)}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M53 40 q3 -2 6 0 M61 40 q3 -2 6 0" stroke="${GLOW}" stroke-width="3" stroke-linecap="round" fill="none"/>
      <path d="M55 48 q5 2 10 0" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" fill="none"/>
    </g>`;
  },

  // ── Draugr — viking undead, horned helm, glowing eyes, braided beard, rusted axe & belt (front)
  draugr: (c) => {
    const S = deepen(c.body, 0.15);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${tube("M84 60 L92 100", BONE, c.line, 3)}
      <path d="M84 56 Q98 54 98 68 Q90 64 84 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${tube("M52 96 L50 110", c.shade, c.line, 7)}${tube("M68 96 L70 110", c.shade, c.line, 7)}
      ${tube("M42 66 Q32 76 34 88", c.body, c.line, 7)}${tube("M78 66 Q86 74 86 82", c.body, c.line, 7)}
      <path d="M42 58 Q40 50 60 50 Q80 50 78 58 L82 98 Q60 104 38 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 82 H80" stroke="${c.line}" stroke-width="3.4"/>
      <rect x="56" y="79" width="8" height="6" rx="1" fill="${GOLD}" stroke="${c.line}" stroke-width="1.2"/>
      <path d="M52 62 Q60 66 68 62 M50 70 Q60 74 70 70" fill="none" stroke="${S}" stroke-width="2" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M40 40 Q26 30 26 18 Q34 24 44 32 Z" fill="${BONE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M80 40 Q94 30 94 18 Q86 24 76 32 Z" fill="${BONE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M42 36 Q42 20 60 20 Q78 20 78 36 L78 40 Q60 44 42 40 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 38 Q60 44 78 38" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M44 40 Q44 50 60 56 Q76 50 76 40 Q60 46 44 40 Z" fill="${belly(c)}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="52" cy="42" r="2.6" fill="${GLOW}"/><circle cx="68" cy="42" r="2.6" fill="${GLOW}"/>
      <circle cx="52" cy="42" r="1" fill="${INK}"/><circle cx="68" cy="42" r="1" fill="${INK}"/>
      <path d="M50 48 Q52 62 60 66 Q68 62 70 48 Q60 54 50 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M56 50 L55 64 M60 52 V66 M64 50 L65 64" stroke="${c.line}" stroke-width="1" opacity=".5"/>
    </g>`;
  },

  // ── Specter — ethereal hovering spirit, flowing wisp-trail, translucent form, calm glowing gaze (float)
  specter: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 15)}
    <g class="tail-wag">
      <path d="M48 96 Q42 110 48 116 Q52 106 54 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".88"/>
      <path d="M60 98 Q58 112 62 116 Q64 108 64 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".88"/>
      <path d="M72 96 Q78 110 72 116 Q68 106 66 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".88"/>
    </g>
    <g class="breathe">
      <path d="M60 14 Q38 18 36 42 Q34 58 44 68 Q34 78 34 96 Q44 90 50 96 Q56 88 60 96 Q64 88 70 96 Q76 90 86 96 Q86 78 76 68 Q86 58 84 42 Q82 18 60 14 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".9"/>
      <path d="M40 60 Q26 66 24 82 Q34 74 44 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".9"/>
      <path d="M80 60 Q94 66 96 82 Q86 74 76 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round" opacity=".9"/>
      <ellipse cx="60" cy="40" rx="16" ry="18" fill="${B}" opacity=".5"/>
      <ellipse cx="52" cy="38" rx="3.4" ry="4.4" fill="${INK}"/><ellipse cx="68" cy="38" rx="3.4" ry="4.4" fill="${INK}"/>
      <circle cx="52" cy="39" r="1.6" fill="${GLOW}"/><circle cx="68" cy="39" r="1.6" fill="${GLOW}"/>
      <path d="M50 32 q3 -2 6 0 M64 32 q3 -2 6 0" fill="none" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round" opacity=".5"/>
      <path d="M55 50 q5 3 10 0" stroke="${c.line}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
    </g>`;
  },

  // ── Poltergeist — small mischievous wisp, curled tail, arms flung up, winking grin & tongue (float)
  poltergeist: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 14)}
    <g class="tail-wag">
      <circle cx="24" cy="50" r="3" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" opacity=".8"/>
      <circle cx="96" cy="58" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" opacity=".8"/>
      <path d="M90 92 q5 -5 7 0 q-2 5 -6 3" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M32 62 Q32 34 60 34 Q88 34 88 62 Q88 82 78 92 Q84 96 82 104 Q74 100 70 94 Q60 90 50 94 Q40 100 34 96 Q40 88 36 84 Q32 74 32 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".96"/>
      <path d="M32 56 Q22 50 22 40 Q30 48 36 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M88 56 Q98 50 98 40 Q90 48 84 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="62" rx="20" ry="18" fill="${B}" opacity=".6"/>
      ${ceye(50, 56, 4.5)}
      <path d="M65 56 q5 -1 9 2" stroke="${INK}" stroke-width="2" fill="none" stroke-linecap="round"/>
      <path d="M48 66 Q60 80 72 66 Q60 74 48 66 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M58 74 Q60 80 64 76 Q64 72 60 72 Z" fill="${belly(c)}"/>
    </g>`;
  },

  // ── Bone Dragon — skeletal wyrm, vertebra tail, membraneless bone wing, exposed ribcage, fanged skull (side)
  bonedragon: (c) => {
    return `
    ${floorShadow(58, 112, 32)}
    <g class="tail-wag">
      ${tube("M40 76 Q18 82 12 62", c.body, c.line, 7)}
      ${[[34, 78], [27, 79], [21, 74], [16, 66]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.4" fill="${BONE}" stroke="${c.line}" stroke-width="1"/>`).join("")}
      <path d="M12 62 l-5 -5 l6 1 l-2 -6" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M58 52 Q40 24 20 22 Q34 34 40 48 M40 48 L22 40 M40 48 L30 60 M40 48 Q52 44 60 50" fill="none" stroke="${c.line}" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M58 52 Q40 24 20 22 Q34 34 40 48 M40 48 L22 40 M40 48 L30 60 M40 48 Q52 44 60 50" fill="none" stroke="${BONE}" stroke-width="1.8" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M36 66 Q36 50 60 50 Q84 50 88 66 Q84 82 60 82 Q36 82 36 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M42 56 Q60 52 82 56" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      ${[44, 52, 60, 68, 76].map(x => `<path d="M${x} 56 Q${x - 2} 70 ${x} 80" fill="none" stroke="${BONE}" stroke-width="2.4" stroke-linecap="round"/>`).join("")}
      ${tube("M50 80 L48 100", c.body, c.line, 5)}${tube("M72 80 L74 100", c.body, c.line, 5)}
      <path d="M48 100 l-3 3 m3 -3 v4 m0 -4 l3 3 M74 100 l-3 3 m3 -3 v4 m0 -4 l3 3" stroke="${BONE}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M82 48 Q78 34 88 32 Q98 32 100 44 L112 52 Q108 60 100 58 L100 62 Q90 66 82 60 Q78 54 82 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M86 34 Q84 22 92 20 Q90 30 92 36 Z" fill="${BONE}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="90" cy="46" rx="4" ry="4.4" fill="${INK}"/><circle cx="90" cy="47" r="1.6" fill="${GLOW}"/>
      <path d="M100 58 l1.4 4 l1.4 -4 Z M105 56 l1.2 4 l1.4 -3.6 Z" fill="${BONE}" stroke="${c.line}" stroke-width="0.6"/>
      <path d="M100 54 L112 55" stroke="${c.line}" stroke-width="1"/>
    </g>`;
  },

  // ── Death Knight — sleek dark armor, horned great-helm, spiked pauldrons, flowing cape, raised greatsword (front)
  deathknight: (c) => {
    const M = tint(c.body, 0.28);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M46 48 Q28 60 26 104 Q40 92 50 92 L52 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M74 48 Q92 60 94 104 Q80 92 70 92 L68 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M92 94 L96 38 L100 94 Z" fill="${M}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M85 92 H105" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      ${tube("M50 98 L48 110", c.shade, c.line, 8)}${tube("M70 98 L72 110", c.shade, c.line, 8)}
      ${tube("M42 66 Q34 78 36 92", c.body, c.line, 8)}${tube("M78 66 Q88 76 90 92", c.body, c.line, 8)}
      <path d="M42 58 Q40 48 60 48 Q80 48 78 58 L82 98 Q60 104 38 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M42 58 Q26 54 26 66 Q30 60 38 60 L34 52 Q40 56 46 60 Z" fill="${M}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 58 Q94 54 94 66 Q90 60 82 60 L86 52 Q80 56 74 60 Z" fill="${M}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M44 72 Q60 78 76 72 M46 86 Q60 92 74 86" fill="none" stroke="${c.line}" stroke-width="1.5" opacity=".5"/>
      <path d="M60 58 V98" stroke="${c.line}" stroke-width="1.3" opacity=".4"/>
      <path d="M52 62 L60 70 L68 62" fill="none" stroke="${M}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M40 34 Q30 26 32 16 Q40 22 46 30 Z" fill="${M}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M80 34 Q90 26 88 16 Q80 22 74 30 Z" fill="${M}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M44 42 Q44 22 60 22 Q76 22 76 42 Q76 54 60 58 Q44 54 44 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M48 40 Q48 34 60 34 Q72 34 72 40 L70 50 Q60 54 50 50 Z" fill="${INK}"/>
      <path d="M50 42 l7 3 M70 42 l-7 3" stroke="${GLOW}" stroke-width="3" stroke-linecap="round"/>
      <path d="M60 34 V52" stroke="${c.line}" stroke-width="1.6"/>
    </g>`;
  },

  // ── Phantom — cloaked opera-spirit, pale theatrical half-mask (glowing eye holes, crack), flowing sleeves (float)
  phantom: (c) => {
    return `
    ${floorShadow(60, 114, 16)}
    <g class="tail-wag">
      <path d="M42 90 Q34 106 40 116 Q46 106 50 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 90 Q86 106 80 116 Q74 106 70 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 16 Q42 20 42 42 Q42 54 48 62 L38 100 Q46 92 52 98 Q56 92 60 98 Q64 92 68 98 Q74 92 82 100 L72 62 Q78 54 78 42 Q78 20 60 16 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 56 Q42 40 42 18 Q49 34 57 48 Z" fill="${deepen(c.body, 0.18)}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M68 56 Q78 40 78 18 Q71 34 63 48 Z" fill="${deepen(c.body, 0.18)}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 40 Q50 58 60 62 Q70 58 70 40 Q60 46 50 40 Z" fill="${c.shade}" opacity=".65"/>
      <path d="M48 58 Q38 66 40 80 Q46 72 52 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M72 58 Q82 66 80 80 Q74 72 68 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M48 34 Q48 22 60 22 Q72 22 72 34 Q72 46 60 50 Q48 46 48 34 Z" fill="${BONE}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 21 Q47 23 47 35 Q47 47 60 50 Z" fill="#fff" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M60 21 V50" stroke="${c.line}" stroke-width="1" opacity=".45"/>
      <path d="M52 32 q4 -3 7 0 q-4 4 -7 0 Z" fill="${INK}"/>
      <path d="M61 32 q3 -3 7 0 q-3 4 -7 0 Z" fill="${INK}"/>
      <circle cx="55" cy="32" r="1" fill="${GLOW}"/><circle cx="64" cy="32" r="1" fill="${GLOW}"/>
      <path d="M60 34 L58 40 h4 Z" fill="${c.shade}"/>
      <path d="M54 44 q6 3 12 0" stroke="${c.line}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      <path d="M69 25 q6 4 4 13 q-4 -7 -7 -9 Z" fill="${c.line}" opacity=".75"/>
    </g>`;
  },

  // ── Shade — amorphous living-shadow blob, wispy horn-tips, drippy tendrils, two glowing void-eyes (float)
  shade: (c) => {
    const S = deepen(c.body, 0.25);
    return `
    ${floorShadow(60, 114, 18)}
    <g class="tail-wag">
      <path d="M40 92 Q36 106 42 114 Q46 104 48 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 92 Q84 106 78 114 Q74 104 72 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M30 60 Q28 34 60 32 Q92 34 90 62 Q90 82 82 94 Q76 88 70 94 Q64 88 60 94 Q56 88 50 94 Q44 88 38 94 Q30 82 30 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M42 34 Q40 22 46 16 Q46 26 50 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 34 Q80 22 74 16 Q74 26 70 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="64" rx="24" ry="22" fill="${S}" opacity=".5"/>
      <ellipse cx="50" cy="58" rx="5" ry="7" fill="${GLOW}"/><ellipse cx="70" cy="58" rx="5" ry="7" fill="${GLOW}"/>
      <ellipse cx="50" cy="60" rx="2" ry="2.6" fill="${INK}"/><ellipse cx="70" cy="60" rx="2" ry="2.6" fill="${INK}"/>
    </g>`;
  },

  // ── Grim Reaper — hooded skull under a flowing cloak, bony hand gripping a curved bone scythe (front)
  grimreaper: (c) => {
    return `
    ${floorShadow(60, 113, 26)}
    <g class="tail-wag">
      ${tube("M92 108 L88 26", c.shade, c.line, 3)}
      <path d="M88 26 Q70 22 60 34 Q74 30 84 38 Q86 30 88 26 Z" fill="${BONE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 16 Q40 22 40 44 Q40 58 48 66 L32 106 Q46 100 52 104 Q56 98 60 104 Q64 98 68 104 Q74 100 88 106 L72 66 Q80 58 80 44 Q80 22 60 16 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 68 L46 104 M60 66 V104 M70 68 L74 104" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".4"/>
      <path d="M48 62 Q38 70 40 84 Q46 76 52 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="88" cy="66" rx="5" ry="4" fill="${BONE}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M85 64 l1 4 M88 63 v5 M91 64 l-1 4" stroke="${c.line}" stroke-width="0.9"/>
    </g>
    <g class="head-tilt">
      <path d="M46 38 Q46 22 60 22 Q74 22 74 38 Q74 54 60 58 Q46 54 46 38 Z" fill="${INK}"/>
      <path d="M50 38 Q50 28 60 28 Q70 28 70 38 Q70 46 66 50 L66 52 Q60 55 54 52 L54 50 Q50 46 50 38 Z" fill="${BONE}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="55" cy="38" rx="3" ry="3.4" fill="${INK}"/><ellipse cx="65" cy="38" rx="3" ry="3.4" fill="${INK}"/>
      <circle cx="55" cy="38" r="1.4" fill="${GLOW}"/><circle cx="65" cy="38" r="1.4" fill="${GLOW}"/>
      <path d="M60 42 l-1.5 3.5 h3 Z" fill="${INK}"/>
      <path d="M55 49 h10" stroke="${c.line}" stroke-width="0.9"/>
      ${[57, 60, 63].map(x => `<path d="M${x} 47 v4" stroke="${c.line}" stroke-width="0.9"/>`).join("")}
    </g>`;
  },

  // ── Necromancer — hooded robed caster, gaunt glowing-eyed face, skull-orb staff, rising fire wisps (front)
  necromancer: (c) => {
    const B = belly(c);
    const S = deepen(c.body, 0.15);
    return `
    ${floorShadow(60, 113, 26)}
    <g class="tail-wag">
      ${tube("M28 106 L32 34", c.shade, c.line, 3)}
      <circle cx="31" cy="30" r="9" fill="${GLOW}" opacity=".25"/>
      <circle cx="31" cy="30" r="6" fill="${GLOW}" stroke="${c.line}" stroke-width="1.8"/>
      <ellipse cx="29" cy="29" rx="1" ry="1.4" fill="${INK}"/><ellipse cx="33" cy="29" rx="1" ry="1.4" fill="${INK}"/>
      <path d="M28 32 q3 2 6 0" stroke="${INK}" stroke-width="0.8" fill="none"/>
    </g>
    <g class="tail-wag">
      <path d="M92 96 Q88 84 94 78 Q92 88 98 90 Q96 96 92 96 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      <circle cx="93" cy="84" r="1.8" fill="${FIRE2}"/>
    </g>
    <g class="breathe">
      <path d="M60 44 Q44 46 40 66 L32 106 Q60 114 88 106 L80 66 Q76 46 60 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 50 L52 106 Q60 109 68 106 Z" fill="${B}" opacity=".5"/>
      <path d="M44 78 Q60 84 76 78 M42 94 Q60 100 78 94" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      <path d="M78 60 Q92 62 94 78 Q86 70 76 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 60 Q30 66 30 80 Q38 72 46 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M42 44 Q40 22 60 20 Q80 22 78 44 Q78 56 60 60 Q42 56 42 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M48 42 Q48 30 60 30 Q72 30 72 42 Q72 52 60 56 Q48 52 48 42 Z" fill="${S}"/>
      <path d="M50 44 Q50 54 60 58 Q70 54 70 44 Q60 48 50 44 Z" fill="${belly(c)}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <circle cx="54" cy="42" r="2.6" fill="${GLOW}"/><circle cx="66" cy="42" r="2.6" fill="${GLOW}"/>
      <circle cx="54" cy="42" r="1" fill="${INK}"/><circle cx="66" cy="42" r="1" fill="${INK}"/>
      <path d="M56 50 q4 2 8 0" stroke="${c.line}" stroke-width="1.3" fill="none" stroke-linecap="round"/>
    </g>`;
  },
};

export const ROSTER_UNDEAD = [
  { n: "Skeleton",     e: "💀",  tier: 2, float: false },
  { n: "Zombie",       e: "🧟",  tier: 2, float: false },
  { n: "Ghost",        e: "👻",  tier: 3, float: true },
  { n: "Lich",         e: "👑",  tier: 5, float: false },
  { n: "Vampire",      e: "🧛",  tier: 4, float: false },
  { n: "Mummy",        e: "🩹",  tier: 3, float: false },
  { n: "Wraith",       e: "🌫️",  tier: 4, float: true },
  { n: "Banshee",      e: "😱",  tier: 4, float: true },
  { n: "Ghoul",        e: "🧌",  tier: 2, float: false },
  { n: "Revenant",     e: "🛡️",  tier: 3, float: false },
  { n: "Wight",        e: "⚰️",  tier: 3, float: false },
  { n: "Draugr",       e: "🪓",  tier: 3, float: false },
  { n: "Specter",      e: "🫥",  tier: 3, float: true },
  { n: "Poltergeist",  e: "😈",  tier: 2, float: true },
  { n: "Bone Dragon",  e: "🦴",  tier: 5, float: false },
  { n: "Death Knight", e: "⚔️",  tier: 4, float: false },
  { n: "Phantom",      e: "🎭",  tier: 3, float: true },
  { n: "Shade",        e: "🌑",  tier: 2, float: true },
  { n: "Grim Reaper",  e: "☠️",  tier: 5, float: false },
  { n: "Necromancer",  e: "🧙",  tier: 4, float: false },
];
