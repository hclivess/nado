// pets-art/savanna.js — bespoke hand-drawn SVG art for AFRICAN / SAVANNA & EXOTIC MAMMALS.
// Each entry: slug -> (c, v) => "<svg inner markup>" for viewBox 0 0 120 120. Palette-driven:
//   c.body (main fill) · c.shade (underside/patches/spots) · c.line (outline). Horns/tusks/claws use
//   fixed warm ivory; teeth #fff; nose INK. Torso wrapped in .breathe, head in .head-tilt, tails/ears
//   in .tail-wag. Keys are name-slugs and match every ROSTER_SAVANNA `n` slugified.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

const IVORY = "#f0e6d2";   // tusks / horns / big teeth
const HORN  = "#d9c9a3";   // shaded horn
const TEETH = "#ffffff";

export const ART_SAVANNA = {
  // ── Lion — full shaggy mane ring, tufted ears, broad muzzle, tail with tuft ───────────────
  lion: (c) => `
    <g class="tail-wag"><path d="M86 92 Q108 88 106 66 Q104 58 98 60 Q104 70 96 80 Q90 88 82 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${pom(103, 60, 7, c.shade, c.line, 7, 2)}</g>
    <g class="breathe"><ellipse cx="60" cy="86" rx="26" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 92 q20 12 40 0" fill="${c.shade}" opacity=".75"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 43}" y="94" width="10" height="16" rx="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${pom(60, 48, 30, c.shade, c.line, 14, 2.4)}
      ${mirror(`<path d="M46 30 Q40 22 48 20 Q54 24 54 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M46 30 Q40 22 48 20 Q54 24 54 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="60" cy="49" rx="21" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 54 Q60 68 74 54 Q74 62 60 64 Q46 62 46 54 Z" fill="${c.shade}"/>
      <path d="M52 55 Q60 60 68 55" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M60 51 L55 57 L65 57 Z" fill="${INK}"/>
      <path d="M60 57 v5" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(51, 69, 45, 3, eyeInk(c))}
      <g stroke="${c.line}" stroke-width="1" opacity=".7"><path d="M48 56 l-9 -2 M48 59 l-9 2 M72 56 l9 -2 M72 59 l9 2"/></g>
    </g>`,

  // ── Tiger — bold vertical stripes on body & face, white muzzle, round ears ────────────────
  tiger: (c) => `
    <g class="tail-wag"><path d="M84 96 Q106 96 106 74 Q106 66 100 68 Q102 78 92 84 Q86 88 80 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="2"><path d="M97 71 h6 M94 78 h7 M89 84 h6"/></g></g>
    <g class="breathe"><ellipse cx="58" cy="86" rx="26" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 90 q18 11 36 0" fill="${c.shade}" opacity=".8"/>
      <g stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"><path d="M44 74 q-2 8 0 16 M56 71 q-1 9 0 18 M68 72 q2 8 0 16 M78 76 q3 6 1 12"/></g>
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 42}" y="94" width="11" height="15" rx="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M44 30 Q40 20 50 22 Q54 28 52 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="27" r="2.6" fill="${c.shade}"/>`)}
      <path d="M44 30 Q40 20 50 22 Q54 28 52 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="27" r="2.6" fill="${c.shade}"/>
      <ellipse cx="60" cy="50" rx="23" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 52 Q60 70 74 52 Q74 62 60 66 Q46 62 46 52 Z" fill="${c.shade}"/>
      <g stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"><path d="M60 30 v9 M50 32 q-1 6 -2 9 M70 32 q1 6 2 9 M40 46 h7 M40 52 h6 M80 46 h-7 M80 52 h-6"/></g>
      <path d="M60 52 L54 59 L66 59 Z" fill="${INK}"/><path d="M60 59 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(51, 69, 47, 3, eyeInk(c))}
    </g>`,

  // ── Leopard — dense rosette clusters over a sleek body, small round ears ──────────────────
  leopard: (c) => {
    const rose = (x, y, r) => `<circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="${c.shade}" stroke-width="1.6"/><circle cx="${x}" cy="${y}" r="${(r * 0.35).toFixed(1)}" fill="${c.shade}"/>`;
    return `
    <g class="tail-wag"><path d="M82 90 Q108 92 110 64 Q110 56 104 58 Q106 72 94 82 Q86 88 78 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${rose(102, 66, 3)}${rose(99, 76, 3)}</g>
    <g class="breathe"><ellipse cx="58" cy="86" rx="26" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${rose(46, 82, 3.5)}${rose(58, 80, 3.5)}${rose(70, 83, 3.5)}${rose(52, 90, 3)}${rose(65, 91, 3)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 44}" y="94" width="9" height="15" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<circle cx="45" cy="34" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="45" cy="34" r="3" fill="${c.shade}"/>`)}
      <circle cx="45" cy="34" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="45" cy="34" r="3" fill="${c.shade}"/>
      <ellipse cx="60" cy="52" rx="20" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 54 Q60 68 72 54 Q72 62 60 65 Q48 62 48 54 Z" fill="${c.shade}"/>
      ${rose(50, 46, 2.4)}${rose(70, 46, 2.4)}${rose(60, 40, 2.4)}
      <path d="M60 54 L55 60 L65 60 Z" fill="${INK}"/><path d="M60 60 v4" stroke="${c.line}" stroke-width="1.4"/>
      ${eyes(52, 68, 49, 2.8, eyeInk(c))}
    </g>`;
  },

  // ── Cheetah — solid round spots, black tear-lines from eye to mouth, slim tall body ───────
  cheetah: (c) => {
    const dot = (x, y) => `<circle cx="${x}" cy="${y}" r="2.4" fill="${c.shade}"/>`;
    return `
    <g class="tail-wag"><path d="M84 88 Q110 88 112 62 Q112 55 106 57 Q108 70 96 80 Q88 86 80 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${dot(101, 64)}${dot(98, 74)}<path d="M100 58 q6 -1 6 5" fill="none" stroke="${c.line}" stroke-width="2"/></g>
    <g class="breathe"><ellipse cx="56" cy="86" rx="23" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${dot(44,82)}${dot(54,80)}${dot(64,82)}${dot(49,89)}${dot(60,90)}${dot(70,86)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 60 : 42}" y="94" width="8" height="16" rx="3.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<circle cx="48" cy="36" r="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <circle cx="48" cy="36" r="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="60" cy="52" rx="17" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 55 Q60 66 70 55 Q70 61 60 63 Q50 61 50 55 Z" fill="${c.shade}"/>
      ${dot(52,44)}${dot(68,44)}
      <path d="M55 52 Q54 58 58 62 M65 52 Q66 58 62 62" stroke="${INK}" stroke-width="2" fill="none" stroke-linecap="round"/>
      <path d="M60 53 L56 58 L64 58 Z" fill="${INK}"/>
      ${eyes(53, 67, 49, 2.7, eyeInk(c))}
    </g>`;
  },

  // ── Elephant — huge flappy ears, curling trunk, two tusks, stumpy legs ────────────────────
  elephant: (c) => `
    <g class="breathe"><ellipse cx="60" cy="72" rx="30" ry="26" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 84 q24 16 48 0" fill="${c.shade}" opacity=".6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 40}" y="92" width="16" height="18" rx="6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><path d="M${i ? 66 : 44} 108 h9" stroke="${c.line}" stroke-width="1.6"/>`).join("")}</g>
    <g class="tail-wag">
      ${mirror(`<path d="M52 46 Q14 42 14 70 Q14 90 52 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M45 54 Q24 58 24 70 Q24 82 45 80" fill="${c.shade}" opacity=".5"/>`)}
      <path d="M52 46 Q14 42 14 70 Q14 90 52 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M45 54 Q24 58 24 70 Q24 82 45 80" fill="${c.shade}" opacity=".5"/></g>
    <g class="head-tilt">
      <ellipse cx="60" cy="56" rx="22" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${mirror(`<path d="M54 68 Q50 84 56 92 L60 88 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`)}
      <path d="M54 68 Q50 84 56 92 L60 88 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M60 64 Q60 78 52 92 Q48 100 56 102 Q62 100 62 92 Q66 80 66 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="1.2" opacity=".6"><path d="M60 70 h5 M59 76 h6 M56 82 h6"/></g>
      ${eyes(50, 70, 52, 2.8, eyeInk(c))}
    </g>`,

  // ── Giraffe — long spotted neck, ossicones, small head, long legs ─────────────────────────
  giraffe: (c) => {
    const patch = (x, y) => `<path d="M${x} ${y} q4 -3 8 0 q3 4 0 8 q-4 3 -8 0 q-3 -4 0 -8 Z" fill="${c.shade}" opacity=".75"/>`;
    return `
    <g class="breathe"><ellipse cx="56" cy="88" rx="20" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${patch(48,84)}${patch(60,86)}
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 42}" y="96" width="7" height="15" rx="2.4" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <path d="M52 82 Q46 54 54 30" fill="none" stroke="${c.line}" stroke-width="16" stroke-linecap="round"/>
    <path d="M52 82 Q46 54 54 30" fill="none" stroke="${c.body}" stroke-width="12" stroke-linecap="round"/>
    ${patch(48,64)}${patch(46,48)}${patch(50,36)}
    <path d="M46 46 Q40 44 40 54" fill="none" stroke="${c.shade}" stroke-width="4" stroke-linecap="round" opacity=".7"/>
    <g class="head-tilt">
      <line x1="55" y1="26" x2="52" y2="15" stroke="${c.line}" stroke-width="3"/><circle cx="51" cy="13" r="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <line x1="64" y1="27" x2="63" y2="16" stroke="${c.line}" stroke-width="3"/><circle cx="63" cy="14" r="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <path d="M50 30 Q41 27 41 34 Q46 36 51 33 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M68 30 Q77 27 77 34 Q72 36 67 33 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M51 26 Q59 21 67 26 Q72 34 68 43 Q59 48 51 43 Q46 34 51 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M56 42 Q59 47 63 42 Q59 45 56 42 Z" fill="${c.shade}"/>
      <ellipse cx="56" cy="40" rx="1.5" ry="1.2" fill="${INK}"/><ellipse cx="62" cy="40" rx="1.5" ry="1.2" fill="${INK}"/>
      ${eyes(54, 64, 32, 2.4, eyeInk(c))}
    </g>`;
  },

  // ── Zebra — pony build, bold black stripes, upright mane, big ears ─────────────────────────
  zebra: (c) => `
    <g class="tail-wag"><path d="M84 84 Q94 86 96 100" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      ${pom(96, 102, 5, c.shade, c.line, 6, 2)}</g>
    <g class="breathe"><ellipse cx="58" cy="82" rx="25" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <g stroke="${c.line}" stroke-width="3" stroke-linecap="round"><path d="M42 72 q-2 8 0 18 M52 70 q-1 10 0 20 M63 71 q1 9 0 18 M73 74 q2 7 0 14"/></g>
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 44}" y="92" width="8" height="17" rx="2.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><path d="M${i ? 65 : 45} 84 q1 6 0 10" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M50 48 Q47 68 58 72 Q69 68 70 48 Q60 56 50 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <g stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"><path d="M54 50 q-1 8 0 16 M64 50 q1 8 0 16"/></g>
      ${mirror(`<path d="M46 28 Q40 16 50 20 Q54 26 52 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M48 24 q3 4 2 8" stroke="${c.line}" stroke-width="1.6"/>`)}
      <path d="M46 28 Q40 16 50 20 Q54 26 52 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M48 24 q3 4 2 8" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M48 34 Q48 26 60 26 Q72 26 72 40 Q72 56 60 58 Q48 56 48 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M56 52 Q60 60 66 52 Q66 57 60 58 Q54 57 56 52 Z" fill="${c.shade}"/>
      <g stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"><path d="M60 26 v20 M50 32 q-2 6 -1 12 M70 32 q2 6 1 12"/></g>
      <path d="M60 30 Q52 20 58 12 Q62 18 62 28" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="57" cy="55" rx="1.6" ry="1.2" fill="${INK}"/><ellipse cx="63" cy="55" rx="1.6" ry="1.2" fill="${INK}"/>
      ${eyes(53, 67, 40, 2.6, eyeInk(c))}
    </g>`,

  // ── Rhino — big nose horn + small second horn, armored bulk, tiny ears ────────────────────
  rhino: (c) => `
    <g class="tail-wag"><path d="M86 84 Q96 86 96 98" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="56" cy="80" rx="30" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M34 86 q22 12 44 0" fill="${c.shade}" opacity=".55"/>
      <path d="M52 60 q4 6 0 14" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".5"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 60 : 40}" y="94" width="14" height="16" rx="5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<ellipse cx="46" cy="44" rx="4" ry="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <ellipse cx="46" cy="44" rx="4" ry="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M40 58 Q40 44 60 44 Q80 44 80 60 Q80 78 60 80 Q40 78 40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="72" rx="13" ry="8" fill="${c.shade}"/>
      <path d="M55 71 Q60 66 65 71" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      <ellipse cx="54" cy="73" rx="1.8" ry="2.4" fill="${INK}"/><ellipse cx="66" cy="73" rx="1.8" ry="2.4" fill="${INK}"/>
      <path d="M55 72 Q60 50 65 72 Q60 66 55 72 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M57 54 Q60 42 63 54 Q60 52 57 54 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eyes(50, 70, 56, 2.6, eyeInk(c))}
    </g>`,

  // ── Hippo — enormous wide muzzle, big nostrils, tiny top ears & eyes, bottom teeth ────────
  hippo: (c) => `
    <g class="breathe"><ellipse cx="60" cy="82" rx="30" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 88 q24 12 48 0" fill="${c.shade}" opacity=".55"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 64 : 42}" y="92" width="14" height="16" rx="6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<circle cx="47" cy="34" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="34" r="2" fill="${c.shade}"/>`)}
      <circle cx="47" cy="34" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="47" cy="34" r="2" fill="${c.shade}"/>
      <ellipse cx="60" cy="55" rx="27" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M38 60 Q60 76 82 60 Q80 70 60 72 Q40 70 38 60 Z" fill="${c.shade}"/>
      <path d="M42 60 Q60 70 78 60" fill="none" stroke="${c.line}" stroke-width="2"/>
      <rect x="50" y="66" width="4" height="6" rx="1.5" fill="${TEETH}" stroke="${c.line}" stroke-width="1"/>
      <rect x="66" y="66" width="4" height="6" rx="1.5" fill="${TEETH}" stroke="${c.line}" stroke-width="1"/>
      <ellipse cx="51" cy="52" rx="3" ry="4" fill="${INK}"/><ellipse cx="69" cy="52" rx="3" ry="4" fill="${INK}"/>
      ${eyes(53, 67, 42, 2.8, eyeInk(c))}
    </g>`,

  // ── Cape Buffalo — heavy fused-boss horns sweeping down and up, broad head, drooping ears ─
  capebuffalo: (c) => `
    <g class="breathe"><ellipse cx="58" cy="86" rx="27" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 90 q18 11 36 0" fill="${c.shade}" opacity=".6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 44}" y="94" width="12" height="15" rx="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M40 44 Q26 46 24 60 Q34 62 42 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M40 44 Q26 46 24 60 Q34 62 42 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="60" cy="58" rx="21" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 40 Q60 32 74 40 Q74 47 60 47 Q46 47 46 40 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M48 44 Q32 44 24 56 Q20 62 23 51 Q27 46 39 46 Q45 46 48 44 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M48 44 Q32 44 24 56 Q20 62 23 51 Q27 46 39 46 Q45 46 48 44 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <path d="M50 40 q10 -4 20 0" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".6"/>
      <path d="M50 62 Q60 74 70 62 Q70 70 60 72 Q50 70 50 62 Z" fill="${c.shade}"/>
      <ellipse cx="54" cy="66" rx="2" ry="1.4" fill="${INK}"/><ellipse cx="66" cy="66" rx="2" ry="1.4" fill="${INK}"/>
      ${eyes(52, 68, 54, 2.8, eyeInk(c))}
    </g>`,

  // ── Meerkat — upright sentinel, slim, dark eye-mask, pointed snout, long tail ─────────────
  meerkat: (c) => `
    <g class="tail-wag"><path d="M74 96 Q92 92 88 68" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/>
      <path d="M74 96 Q92 92 88 68" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/><circle cx="88" cy="68" r="2.6" fill="${INK}"/></g>
    <g class="breathe"><path d="M50 96 Q44 62 60 58 Q76 62 70 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M55 92 Q60 70 65 92 Z" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 66 : 54} 82 q${i ? -8 : 8} 8 ${i ? -3 : 3} 16" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>`).join("")}
      <rect x="52" y="96" width="7" height="8" rx="2" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><rect x="61" y="96" width="7" height="8" rx="2" fill="${c.body}" stroke="${c.line}" stroke-width="2"/></g>
    <g class="head-tilt">
      ${mirror(`<circle cx="52" cy="38" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <circle cx="52" cy="38" r="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M48 44 Q48 34 60 34 Q72 34 72 46 Q72 56 60 58 Q52 56 50 50 Q48 48 48 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M56 50 Q60 60 68 50 L72 54 Q66 58 60 58 Q54 57 54 52 Z" fill="${c.shade}"/>
      <ellipse cx="53" cy="45" rx="4" ry="5" fill="${c.shade}" opacity=".8"/><ellipse cx="67" cy="45" rx="4" ry="5" fill="${c.shade}" opacity=".8"/>
      <path d="M60 52 L57 56 L63 56 Z" fill="${INK}"/>
      ${eyes(53, 67, 45, 2.6, eyeInk(c))}
    </g>`,

  // ── Warthog — boar snout with upward tusks, spiky mane, facial warts, stocky ─────────────
  warthog: (c) => `
    <g class="tail-wag"><path d="M84 82 Q94 82 94 100" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><path d="M92 100 l2 5 l3 -4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/></g>
    <g class="breathe"><ellipse cx="56" cy="84" rx="26" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 42}" y="94" width="10" height="15" rx="3.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<path d="M46 34 Q42 22 50 24 Q54 30 52 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M46 34 Q42 22 50 24 Q54 30 52 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M60 32 Q50 30 48 40 M60 32 Q70 30 72 40" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round"/>
      <path d="M46 48 Q46 36 60 36 Q74 36 74 50 Q74 66 60 70 Q52 70 48 62 L54 60 Q46 56 46 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="62" cy="64" rx="9" ry="7" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="59" cy="64" rx="1.6" ry="2.4" fill="${INK}"/><ellipse cx="65" cy="64" rx="1.6" ry="2.4" fill="${INK}"/>
      <path d="M54 66 Q52 78 48 74" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M70 66 Q72 78 76 74" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="52" cy="52" r="2.4" fill="${c.shade}"/><circle cx="68" cy="52" r="2.4" fill="${c.shade}"/>
      ${eyes(53, 67, 48, 2.6, eyeInk(c))}
    </g>`,

  // ── Gorilla — massive shoulders, crested head, brow ridge, flat nose, dark face ──────────
  gorilla: (c) => `
    <g class="breathe"><path d="M28 96 Q26 66 46 62 Q60 60 74 62 Q94 66 92 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M46 92 Q60 82 74 92" fill="${c.shade}" opacity=".55"/></g>
    <g class="tail-wag">
      ${mirror(`<path d="M32 66 Q18 74 26 92 Q34 90 38 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
      <path d="M32 66 Q18 74 26 92 Q34 90 38 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      <path d="M44 44 Q44 22 60 22 Q76 22 76 44 Q76 62 60 62 Q44 62 44 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 22 Q60 16 64 22" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${mirror(`<ellipse cx="45" cy="42" rx="3.5" ry="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <ellipse cx="45" cy="42" rx="3.5" ry="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M48 44 Q48 34 60 34 Q72 34 72 46 Q72 58 60 60 Q48 58 48 44 Z" fill="${c.shade}"/>
      <path d="M50 40 q10 -4 20 0" fill="none" stroke="${INK}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M56 48 Q60 52 64 48 M58 48 v4 M62 48 v4" stroke="${INK}" stroke-width="1.6" fill="none"/>
      <path d="M52 54 Q60 60 68 54" fill="none" stroke="${INK}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(53, 67, 44, 2.6, eyeInk(c))}
    </g>`,

  // ── Chimpanzee — big round ears, protruding pale muzzle, expressive brow ─────────────────
  chimpanzee: (c) => `
    <g class="breathe"><ellipse cx="60" cy="84" rx="22" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="88" rx="12" ry="9" fill="${c.shade}" opacity=".55"/></g>
    <g class="tail-wag">
      ${mirror(`<path d="M40 78 Q22 80 26 96 Q34 96 42 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
      <path d="M40 78 Q22 80 26 96 Q34 96 42 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      ${mirror(`<circle cx="41" cy="44" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="41" cy="44" r="4" fill="${c.shade}"/>`)}
      <circle cx="41" cy="44" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="41" cy="44" r="4" fill="${c.shade}"/>
      <ellipse cx="60" cy="48" rx="19" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 50 Q46 40 60 40 Q74 40 74 52 Q74 64 60 66 Q46 64 46 50 Z" fill="${c.shade}"/>
      <path d="M50 44 q4 -3 8 0 M62 44 q4 -3 8 0" fill="none" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M56 52 q4 3 8 0 M59 51 v4 M61 51 v4" stroke="${INK}" stroke-width="1.4" fill="none"/>
      <path d="M52 58 Q60 63 68 58" fill="none" stroke="${INK}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(54, 66, 47, 2.7, eyeInk(c))}
    </g>`,

  // ── Kangaroo — upright, joey in pouch, huge feet, thick tail, long ears ──────────────────
  kangaroo: (c) => `
    <g class="tail-wag"><path d="M64 92 Q92 96 100 76" fill="none" stroke="${c.line}" stroke-width="10" stroke-linecap="round"/>
      <path d="M64 92 Q92 96 100 76" fill="none" stroke="${c.body}" stroke-width="6.5" stroke-linecap="round"/></g>
    <path d="M54 100 Q42 100 40 92 Q52 88 58 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    <g class="breathe"><path d="M48 92 Q42 58 62 52 Q80 56 74 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 88 Q52 66 66 68 Q72 84 68 88 Z" fill="${c.shade}"/>
      <path d="M56 74 Q62 70 68 74 Q66 84 60 82 Q56 80 56 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      <circle cx="62" cy="76" r="3.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M60 72 Q56 60 62 62 M64 72 Q68 62 66 62" stroke="${c.line}" stroke-width="2.4" fill="none" stroke-linecap="round"/></g>
    <g class="head-tilt">
      ${mirror(`<path d="M52 34 Q48 16 56 20 Q60 28 58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M54 24 q2 8 1 14" stroke="${c.shade}" stroke-width="2"/>`)}
      <path d="M52 34 Q48 16 56 20 Q60 28 58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M54 24 q2 8 1 14" stroke="${c.shade}" stroke-width="2"/>
      <path d="M50 40 Q50 30 62 30 Q74 30 74 44 Q74 52 66 52 L60 56 L58 50 Q50 48 50 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="59" cy="53" rx="2.4" ry="1.8" fill="${INK}"/>
      ${eyes(56, 68, 40, 2.6, eyeInk(c))}
    </g>`,

  // ── Koala — oversized fluffy ears, big dark nose, round hugging body ─────────────────────
  koala: (c) => `
    <g class="breathe"><ellipse cx="60" cy="84" rx="21" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M42 88 q18 11 36 0" fill="${c.shade}" opacity=".5"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 70 : 50} 78 q${i ? 8 : -8} 6 ${i ? 4 : -4} 16" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M${i ? 70 : 50} 78 q${i ? 8 : -8} 6 ${i ? 4 : -4} 16" fill="none" stroke="${c.body}" stroke-width="3.5" stroke-linecap="round"/>`).join("")}</g>
    <g class="tail-wag">
      ${mirror(`${pom(40, 42, 12, c.body, c.line, 10, 2.4)}${pom(40, 42, 6, c.shade, c.line, 8, 1.4)}`)}
      ${pom(40, 42, 12, c.body, c.line, 10, 2.4)}${pom(40, 42, 6, c.shade, c.line, 8, 1.4)}</g>
    <g class="head-tilt">
      <ellipse cx="60" cy="50" rx="20" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M54 50 Q60 48 66 50 Q68 60 60 62 Q52 60 54 50 Z" fill="${INK}"/>
      <path d="M56 46 q4 -2 8 0" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      ${eyes(52, 68, 46, 3, eyeInk(c))}
    </g>`,

  // ── Panda — round body, dark ears, teardrop eye-patches, dark arms ───────────────────────
  panda: (c) => `
    <g class="breathe"><ellipse cx="60" cy="84" rx="24" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 76 : 44} 80 Q${i ? 96 : 24} 84 ${i ? 88 : 32} 98 Q${i ? 80 : 40} 99 ${i ? 76 : 44} 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`).join("")}
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 68 : 52}" cy="102" rx="7" ry="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <g class="head-tilt">
      ${mirror(`<circle cx="44" cy="34" r="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>`)}
      <circle cx="44" cy="34" r="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="60" cy="48" rx="21" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${mirror(`<path d="M50 42 Q46 46 48 52 Q54 54 56 48 Q56 42 50 42 Z" fill="${c.shade}"/>`)}
      <path d="M50 42 Q46 46 48 52 Q54 54 56 48 Q56 42 50 42 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="53" rx="4" ry="3" fill="${INK}"/>
      <path d="M60 56 q0 4 -4 5 M60 56 q0 4 4 5" stroke="${c.line}" stroke-width="1.4" fill="none"/>
      ${eyes(51, 69, 47, 2.8, eyeInk(c))}
    </g>`,

  // ── Camel — two Bactrian humps, long curved neck, drooping lip, knobby knees ─────────────
  camel: (c) => `
    <g class="tail-wag"><path d="M84 76 Q92 80 90 94" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/><circle cx="90" cy="94" r="2.6" fill="${c.shade}"/></g>
    <g class="breathe">
      <path d="M32 84 Q34 72 44 70 Q47 55 54 70 L64 70 Q67 55 74 70 Q86 72 86 84 Q86 92 60 92 Q34 92 32 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 58 : 48}" y="90" width="7" height="20" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>`).join("")}
      ${["", "s"].map((_, i) => `<rect x="${i ? 68 : 40}" y="88" width="8" height="22" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><rect x="${i ? 67 : 39}" y="106" width="10" height="4" rx="1.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>`).join("")}
    </g>
    <path d="M40 80 Q28 54 42 34" fill="none" stroke="${c.line}" stroke-width="13" stroke-linecap="round"/>
    <path d="M40 80 Q28 54 42 34" fill="none" stroke="${c.body}" stroke-width="9" stroke-linecap="round"/>
    <g class="head-tilt">
      <path d="M45 30 Q41 22 48 22 Q50 27 49 33 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M53 29 Q50 21 56 22 Q57 27 55 33 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M42 34 Q40 24 48 24 Q56 26 56 36 Q58 47 49 50 Q41 50 39 42 Q39 36 42 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M42 46 Q47 52 40 51 Q37 48 39 45 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="42" cy="45" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(49, 36, 2.6, eyeInk(c))}
    </g>`,

  // ── Llama — long upright neck, tall banana ears, fluffy topknot, calm long face ──────────
  llama: (c) => `
    <g class="breathe"><ellipse cx="58" cy="86" rx="22" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 88 q16 10 34 0" fill="${c.shade}" opacity=".5"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 44}" y="94" width="8" height="16" rx="2.6" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}</g>
    <path d="M52 84 Q46 54 54 32" fill="none" stroke="${c.line}" stroke-width="15" stroke-linecap="round"/>
    <path d="M52 84 Q46 54 54 32" fill="none" stroke="${c.body}" stroke-width="11" stroke-linecap="round"/>
    <path d="M48 60 Q42 58 42 66 M50 46 Q44 46 44 54" fill="none" stroke="${c.shade}" stroke-width="3.5" stroke-linecap="round" opacity=".7"/>
    <g class="head-tilt">
      ${mirror(`<path d="M52 28 Q49 12 56 18 Q58 26 56 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M52 28 Q49 12 56 18 Q58 26 56 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${pom(60, 26, 7, c.shade, c.line, 8, 1.8)}
      <path d="M52 32 Q52 24 62 24 Q72 26 70 40 Q68 50 58 50 Q50 48 50 38 Q50 34 52 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M58 44 Q64 48 66 42 Q62 42 58 44 Z" fill="${c.shade}"/>
      <ellipse cx="62" cy="43" rx="1.4" ry="1" fill="${INK}"/><ellipse cx="59" cy="45" rx="1.4" ry="1" fill="${INK}"/>
      <path d="M54 35 q-4 1 -4 3" stroke="${c.line}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      ${eyes(54, 62, 34, 2.4, eyeInk(c))}
    </g>`,

  // ── Sloth — hanging from a branch, long clawed arms, dark eye-mask, sleepy smile (float) ─
  sloth: (c) => `
    <path d="M14 30 Q60 22 106 30" fill="none" stroke="#8a6a4a" stroke-width="6" stroke-linecap="round"/>
    <g class="tail-wag">
      ${mirror(`<path d="M46 40 Q30 34 30 28" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/><path d="M46 40 Q30 34 30 28" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/><path d="M30 28 l-4 -4 M30 28 l0 -6 M30 28 l4 -3" stroke="${IVORY}" stroke-width="2" stroke-linecap="round"/>`)}
      <path d="M46 40 Q30 34 30 28" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/><path d="M46 40 Q30 34 30 28" fill="none" stroke="${c.body}" stroke-width="4.5" stroke-linecap="round"/><path d="M30 28 l-4 -4 M30 28 l0 -6 M30 28 l4 -3" stroke="${IVORY}" stroke-width="2" stroke-linecap="round"/></g>
    <g class="breathe"><ellipse cx="60" cy="66" rx="19" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 60 q12 14 24 0" fill="${c.shade}" opacity=".5"/></g>
    <g class="head-tilt">
      <ellipse cx="60" cy="52" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 50 Q46 44 50 42 Q56 44 56 50 Q54 56 50 50 Z" fill="${c.shade}"/>
      <path d="M70 50 Q74 44 70 42 Q64 44 64 50 Q66 56 70 50 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="52" rx="4" ry="3" fill="${c.shade}"/><path d="M60 51 L57 54 L63 54 Z" fill="${INK}"/>
      <path d="M52 58 Q60 63 68 58" fill="none" stroke="${INK}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(52, 68, 49, 2.6, eyeInk(c))}
    </g>`,
};

export const ROSTER_SAVANNA = [
  { n: "Lion",         e: "🦁", tier: 4, float: false },
  { n: "Tiger",        e: "🐯", tier: 4, float: false },
  { n: "Leopard",      e: "🐆", tier: 3, float: false },
  { n: "Cheetah",      e: "🐆", tier: 3, float: false },
  { n: "Elephant",     e: "🐘", tier: 4, float: false },
  { n: "Giraffe",      e: "🦒", tier: 3, float: false },
  { n: "Zebra",        e: "🦓", tier: 3, float: false },
  { n: "Rhino",        e: "🦏", tier: 3, float: false },
  { n: "Hippo",        e: "🦛", tier: 3, float: false },
  { n: "Cape Buffalo", e: "🐃", tier: 3, float: false },
  { n: "Meerkat",      e: "🐾", tier: 2, float: false },
  { n: "Warthog",      e: "🐗", tier: 2, float: false },
  { n: "Gorilla",      e: "🦍", tier: 3, float: false },
  { n: "Chimpanzee",   e: "🐒", tier: 2, float: false },
  { n: "Kangaroo",     e: "🦘", tier: 3, float: false },
  { n: "Koala",        e: "🐨", tier: 2, float: false },
  { n: "Panda",        e: "🐼", tier: 3, float: false },
  { n: "Camel",        e: "🐫", tier: 2, float: false },
  { n: "Llama",        e: "🦙", tier: 2, float: false },
  { n: "Sloth",        e: "🦥", tier: 2, float: true  },
];
