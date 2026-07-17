// pets-art/yokai.js — BESPOKE hand-drawn SVG art for the YOKAI batch (NADO Pets).
// Japanese/Asian folklore spirits. ONE continuous c.body silhouette (thick rounded outline) per
// creature; tails/necks/legs/wings tucked into <g class="tail-wag"> so nothing floats; two-tone
// shading via belly()/c.shade; cute glossy faces (ceye/eyes) or eerie spirit-glow eyes.
// Fixed accents used SPARINGLY: HORN/beak GOLD, FIRE/FIRE2 (foxfire/lightning), GLOW (spirit).
// The MAIN body always recolours via the coat object c = { body, shade, line } (applied at runtime).
// viewBox 0 0 120 120, creature centered ~ (60,64), within x,y ∈ [8,114].
// Floaters (amabie, yukionna, kodama) set float:true.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

// fixed folklore accents that stay constant across coats
const HORN = "#f2c94c", FIRE = "#ff7a1a", FIRE2 = "#ffd24a", GLOW = "#eafff4", TOOTH = "#ffffff";

export const ART_YOKAI = {
  // ── Tengu — red long-nosed mountain goblin, small feathered wings, angry brows, comically long nose (front)
  tengu: (c) => {
    const B = belly(c), E = eyeInk(c);
    const wing = `<path d="M42 54 Q22 44 12 54 Q26 56 30 64 Q20 62 16 70 Q34 68 46 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M40 60 Q38 50 60 50 Q82 50 80 60 L86 102 Q60 110 34 102 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${tube("M42 62 Q30 74 34 90", c.body, c.line, 8)}${tube("M78 62 Q90 74 86 90", c.body, c.line, 8)}
      <circle cx="34" cy="91" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><circle cx="86" cy="91" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <path d="M52 60 L60 100 L68 60 Q60 66 52 60 Z" fill="${B}"/>
      <path d="M40 84 Q60 92 80 84" fill="none" stroke="${c.shade}" stroke-width="4" stroke-linecap="round"/>
      ${tube("M52 100 L50 110", c.shade, c.line, 7)}${tube("M68 100 L70 110", c.shade, c.line, 7)}
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="38" r="17" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <path d="M44 28 Q46 16 60 16 Q74 16 76 28 Q68 22 60 24 Q52 22 44 28 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M57 16 Q60 8 63 16 Q65 21 60 23 Q55 21 57 16 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M43 36 q6 -3 12 1 M65 37 q6 -4 12 -1" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      ${ceye(50, 42, 4)}${ceye(70, 42, 4)}
      <path d="M60 40 Q66 44 66 56 Q66 66 60 70 Q54 66 54 56 Q54 44 60 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M62 43 Q65 53 63 64" fill="none" stroke="#fff" stroke-width="1.3" stroke-linecap="round" opacity=".3"/>
      <ellipse cx="57.6" cy="66" rx="1.1" ry="1.4" fill="${c.line}" opacity=".6"/><ellipse cx="62.4" cy="66" rx="1.1" ry="1.4" fill="${c.line}" opacity=".6"/>
      <path d="M50 60 Q54 63 58 62 M70 60 Q66 63 62 62" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    </g>`;
  },

  // ── Oni — horned ogre brute, spiked club (kanabo), fanged snarl, loincloth, big fists (front)
  oni: (c) => {
    const E = eyeInk(c);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M84 96 L96 40 Q92 38 88 40 L80 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[44, 52, 60, 68].map((y) => `<circle cx="${(90 - (y - 44) * 0.14).toFixed(1)}" cy="${y}" r="3" fill="${c.body}" stroke="${c.line}" stroke-width="1.4"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M38 64 Q36 52 60 52 Q84 52 82 64 L86 102 Q60 108 34 102 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 66 Q60 74 70 66 M50 74 Q60 82 70 74" fill="none" stroke="${c.shade}" stroke-width="2" stroke-linecap="round" opacity=".7"/>
      ${tube("M40 66 Q28 76 30 90", c.body, c.line, 9)}${tube("M80 66 Q92 76 90 90", c.body, c.line, 9)}
      <circle cx="30" cy="91" r="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="90" cy="91" r="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M40 90 Q60 98 80 90 L80 100 Q60 106 40 100 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${[48, 60, 72].map((x) => `<path d="M${x} 92 v8" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>`).join("")}
      ${tube("M50 100 L48 110", c.body, c.line, 8)}${tube("M70 100 L72 110", c.body, c.line, 8)}
    </g>
    <g class="head-tilt">
      <path d="M40 30 Q34 16 42 12 Q46 22 50 30 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M80 30 Q86 16 78 12 Q74 22 70 30 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M40 40 Q40 22 60 22 Q80 22 80 40 Q80 56 60 60 Q40 56 40 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M42 28 Q52 22 58 28 Q50 26 42 30 Z M78 28 Q68 22 62 28 Q70 26 78 30 Z" fill="${c.shade}"/>
      <path d="M45 36 q7 -3 13 1 M62 37 q7 -4 13 -1" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      ${eyes(52, 68, 42, 3.4, E)}
      <path d="M46 50 Q60 62 74 50 Q60 56 46 50 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M50 50 l2 5 l2 -5 Z M66 50 l2 5 l2 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Tanuki — round raccoon-dog with a huge belly, masked eyes, bushy tail, little paws (front sitting)
  tanuki: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M84 96 Q104 92 100 72 Q98 62 88 66 Q96 74 90 84 Q84 92 76 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M96 80 Q99 74 95 70" fill="none" stroke="${B}" stroke-width="3" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M60 112 C32 112 26 92 30 76 C32 66 36 60 42 56 L36 30 L52 44 Q60 40 68 44 L84 30 L78 56 C84 60 88 66 90 76 C94 92 88 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M39 34 L49 46 Q44 49 42 53 Z" fill="${c.shade}"/><path d="M81 34 L71 46 Q76 49 78 53 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="88" rx="24" ry="20" fill="${B}"/>
      ${tube("M40 82 Q34 94 40 104", c.body, c.line, 6)}${tube("M80 82 Q86 94 80 104", c.body, c.line, 6)}
      <ellipse cx="51" cy="64" rx="7.5" ry="6" fill="${c.shade}" opacity=".55"/><ellipse cx="69" cy="64" rx="7.5" ry="6" fill="${c.shade}" opacity=".55"/>
      ${ceye(51, 64, 4.2)}${ceye(69, 64, 4.2)}
      <path d="M60 70 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 73 v2 M60 75 q-4 3 -8 2 M60 75 q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`;
  },

  // ── Nekomata — two-tailed cat spirit, forked bushy tails, sleek cat face, whiskers (front sitting)
  nekomata: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <path d="M72 94 Q84 98 90 80 Q94 68 84 66 Q90 74 84 84 Q78 92 68 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M84 90 Q106 84 104 62 Q103 52 93 56 Q100 64 94 76 Q88 86 78 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M97 66 Q101 58 95 56" fill="none" stroke="${c.shade}" stroke-width="2.6" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M60 112 C32 112 28 92 33 74 C35 62 38 56 43 51 L35 26 L56 45 Q60 41 64 45 L85 26 L77 51 C82 56 85 62 87 74 C92 92 88 112 60 112 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 32 L51 46 Q45 49 42 53 Z" fill="${c.shade}"/><path d="M80 32 L69 46 Q75 49 78 53 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="74" rx="20" ry="15" fill="${B}"/>
      ${ceye(51, 66, 4.2)}${ceye(69, 66, 4.2)}
      <path d="M60 74 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 77 v2 M60 79 q-4 3 -8 2 M60 79 q4 3 8 2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M34 70 h-13 M35 75 h-14 M86 70 h13 M85 75 h14" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round" opacity=".55"/>
    </g>`;
  },

  // ── Bakeneko — cat spirit dancing upright, foxfire wisp, glowing slit eyes, single curled tail (front bipedal)
  bakeneko: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      <path d="M76 90 Q100 90 102 66 Q102 52 90 54 Q100 62 94 76 Q88 86 74 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M96 68 Q99 60 93 56" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      <path d="M30 52 Q24 40 30 32 Q30 44 38 46 Q34 52 30 52 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="31" cy="42" r="2" fill="${FIRE2}"/>
    </g>
    <g class="breathe">
      <path d="M42 62 Q40 52 60 52 Q80 52 78 62 L82 100 Q60 108 38 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="82" rx="15" ry="16" fill="${B}"/>
      ${tube("M42 64 Q30 54 34 44", c.body, c.line, 7)}${tube("M78 64 Q92 60 90 50", c.body, c.line, 7)}
      <circle cx="34" cy="43" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/><circle cx="90" cy="49" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>
      ${tube("M52 100 L50 110", c.body, c.line, 7)}${tube("M68 100 L70 110", c.body, c.line, 7)}
    </g>
    <g class="head-tilt">
      <path d="M42 40 L34 20 L52 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M43 37 L39 25 L49 34 Z" fill="${c.shade}"/>
      <path d="M78 40 L86 20 L68 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M77 37 L81 25 L71 34 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="42" rx="19" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <ellipse cx="60" cy="46" rx="12" ry="9" fill="${B}"/>
      <path d="M51 40 Q51 34 56 40 Q54 45 51 40 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="1.2"/><path d="M69 40 Q69 34 64 40 Q66 45 69 40 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="1.2"/>
      <ellipse cx="53.5" cy="40" rx="1.4" ry="2.4" fill="${INK}"/><ellipse cx="66.5" cy="40" rx="1.4" ry="2.4" fill="${INK}"/>
      <path d="M60 48 l-2.4 2.4 h4.8 Z" fill="${INK}"/>
      <path d="M60 50 q-4 4 -8 3 M60 50 q4 4 8 3" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M40 44 h-12 M40 49 h-13 M80 44 h12 M80 49 h13" stroke="${c.line}" stroke-width="1.2" stroke-linecap="round" opacity=".5"/>
    </g>`;
  },

  // ── Karakasa — one-eyed paper umbrella, single geta leg, lolling tongue, radiating ribs (front hopping)
  karakasa: (c) => {
    return `
    ${floorShadow(60, 113, 18)}
    <g class="tail-wag">
      ${tube("M60 66 L60 104", c.body, c.line, 8)}
      <rect x="47" y="103" width="26" height="7" rx="2" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M54 110 v5 M66 110 v5" stroke="${c.line}" stroke-width="2.8" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M61 16 L61 8 Q66 8 66 13 L66 19 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M60 16 Q96 24 96 56 Q96 72 88 70 Q80 64 73 70 Q66 64 60 70 Q54 64 47 70 Q40 64 32 70 Q24 72 24 56 Q24 24 60 16 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[34, 47, 60, 73, 86].map((x) => `<path d="M60 18 Q${x} 36 ${x} 60" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".45"/>`).join("")}
      <path d="M28 40 Q60 34 92 40" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".7"/>
      <ellipse cx="60" cy="42" rx="13" ry="12" fill="#fff" stroke="${c.line}" stroke-width="2.8"/>
      <circle cx="60" cy="43" r="6.4" fill="${INK}"/><circle cx="62.4" cy="40.4" r="2.1" fill="#fff"/>
      <path d="M47 58 Q60 70 73 58 Q60 66 47 58 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M55 63 Q53 80 60 84 Q67 80 65 63 Q60 67 55 63 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M60 66 V82" stroke="${c.line}" stroke-width="1.1" opacity=".5"/>
    </g>`;
  },

  // ── Rokurokubi — kimono woman with an impossibly long stretching neck, calm face, hair bun (front)
  rokurokubi: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 113, 26)}
    <g class="breathe">
      <path d="M40 96 Q38 76 60 74 Q82 76 80 96 L84 106 Q60 112 36 106 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${tube("M44 82 Q34 92 36 102", c.body, c.line, 7)}${tube("M76 82 Q86 92 84 102", c.body, c.line, 7)}
      <path d="M50 78 L60 104 L70 78 Q60 84 50 78 Z" fill="${c.shade}"/>
      <path d="M40 90 Q60 98 80 90" fill="none" stroke="${c.shade}" stroke-width="5" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      ${tube("M60 76 Q48 62 58 48 Q68 36 60 26", c.body, c.line, 9)}
    </g>
    <g class="head-tilt">
      <path d="M46 26 Q44 10 60 8 Q76 10 74 26 Q68 18 60 20 Q52 18 46 26 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="60" cy="28" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M46 24 Q48 40 54 44 M74 24 Q72 40 66 44" fill="none" stroke="${c.shade}" stroke-width="4" stroke-linecap="round"/>
      <ellipse cx="60" cy="31" rx="8" ry="6" fill="${B}"/>
      ${eyes(54, 66, 29, 2.8, E)}
      <path d="M60 33 l-1.6 2 h3.2 Z" fill="${INK}"/>
      <path d="M56 37 q4 3 8 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M52 20 Q56 26 60 20 Q64 18 60 15 Q54 15 52 20 Z" fill="${c.shade}"/>
    </g>`;
  },

  // ── Nurikabe — great plaster wall spirit with a face, tiny stubby feet & arms, cracks (front)
  nurikabe: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 32)}
    <g class="tail-wag">
      ${tube("M22 56 Q12 60 14 72", c.body, c.line, 7)}${tube("M98 56 Q108 60 106 72", c.body, c.line, 7)}
    </g>
    <g class="breathe">
      <path d="M22 30 Q22 24 28 24 L92 24 Q98 24 98 30 L98 96 Q98 102 92 102 L28 102 Q22 102 22 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <rect x="34" y="40" width="52" height="42" rx="4" fill="${B}"/>
      <path d="M30 52 L50 52 M60 34 L60 52 M74 62 L92 62 M40 84 L40 96 M70 84 L86 94" fill="none" stroke="${c.shade}" stroke-width="2" stroke-linecap="round" opacity=".55"/>
      ${tube("M40 100 L40 110", c.shade, c.line, 8)}${tube("M80 100 L80 110", c.shade, c.line, 8)}
      <ellipse cx="40" cy="111" rx="7" ry="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/><ellipse cx="80" cy="111" rx="7" ry="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <ellipse cx="41" cy="66" rx="4" ry="3" fill="${c.shade}" opacity=".5"/><ellipse cx="79" cy="66" rx="4" ry="3" fill="${c.shade}" opacity=".5"/>
      ${ceye(48, 58, 4.6)}${ceye(72, 58, 4.6)}
      <path d="M52 68 Q60 74 68 68" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>
    </g>`;
  },

  // ── Jorogumo — spider-woman, bulbous abdomen, eight tucked legs, cute lashes + tiny fangs, extra spider-eyes (front)
  jorogumo: (c) => {
    const B = belly(c), E = eyeInk(c);
    const leg = (sx, sy, mx, my, ex, ey) => tube(`M${sx} ${sy} Q${mx} ${my} ${ex} ${ey}`, c.body, c.line, 5);
    return `
    ${floorShadow(60, 113, 32)}
    <g class="tail-wag">
      ${leg(46, 74, 24, 58, 14, 66)}${leg(46, 80, 22, 74, 10, 84)}${leg(46, 86, 24, 90, 12, 102)}${leg(48, 90, 36, 98, 30, 110)}
      ${leg(74, 74, 96, 58, 106, 66)}${leg(74, 80, 98, 74, 110, 84)}${leg(74, 86, 96, 90, 108, 102)}${leg(72, 90, 84, 98, 90, 110)}
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="26" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="60" cy="86" rx="14" ry="16" fill="${B}"/>
      <path d="M60 74 L56 84 L60 88 L64 84 Z M60 90 L56 96 L60 100 L64 96 Z" fill="${c.shade}"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="56" rx="16" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M46 50 Q44 36 52 32 Q52 42 56 48 Z M74 50 Q76 36 68 32 Q68 42 64 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="60" rx="11" ry="8" fill="${B}"/>
      <circle cx="50" cy="49" r="1.6" fill="${INK}"/><circle cx="70" cy="49" r="1.6" fill="${INK}"/><circle cx="56" cy="47" r="1.4" fill="${INK}"/><circle cx="64" cy="47" r="1.4" fill="${INK}"/>
      ${ceye(53, 56, 4)}${ceye(67, 56, 4)}
      <path d="M60 63 l-2 2 h4 Z" fill="${INK}"/>
      <path d="M54 67 q6 4 12 0" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M55 67 l-1 3 M65 67 l1 3" stroke="${TOOTH}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Amabie — prophetic beaked mermaid, three big fins, scaled body, thin trailing hair, gold beak (float front)
  amabie: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 20)}
    <g class="tail-wag">
      <path d="M46 44 Q30 62 26 100 Q34 84 44 80 Q34 94 38 108 Q48 82 54 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M74 44 Q90 62 94 100 Q86 84 76 80 Q86 94 82 108 Q72 82 66 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 34 Q76 36 76 56 Q76 74 70 84 L80 104 Q70 100 66 92 L62 104 Q60 96 60 92 Q60 96 58 104 L54 92 Q50 100 40 104 L50 84 Q44 74 44 56 Q44 36 60 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 48 Q70 52 68 70 Q66 84 60 88 Q54 84 52 70 Q50 52 60 48 Z" fill="${B}"/>
      ${[58, 68, 78].map((y) => `<path d="M46 ${y} q14 5 28 0" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M46 34 Q46 20 60 20 Q74 20 74 34 Q68 28 60 30 Q52 28 46 34 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="38" rx="13" ry="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${eyes(54, 66, 37, 3, eyeInk(c))}
      <path d="M56 44 L60 52 L64 44 Q60 47 56 44 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Baku — tapir dream-eater, long drooping trunk-snout, chunky stub-legs, small ear (side)
  baku: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(58, 112, 32)}
    <g class="tail-wag">
      ${tube("M32 76 Q20 78 22 66", c.body, c.line, 5)}
    </g>
    <g class="breathe">
      <path d="M28 76 Q28 54 54 52 Q78 50 88 62 Q92 68 88 74 L88 96 L78 96 L78 82 L60 84 L60 96 L50 96 L50 82 Q38 82 34 88 L34 96 L26 96 L26 78 Q26 76 28 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 78 Q60 86 82 78 Q60 82 40 78 Z" fill="${B}"/>
      <path d="M50 96 h10 v6 h-10 Z M78 96 h10 v6 h-10 Z M26 96 h8 v6 h-8 Z" fill="${c.shade}"/>
    </g>
    <g class="head-tilt">
      <path d="M78 56 Q76 44 86 42 Q90 50 88 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M84 52 Q104 52 106 66 Q106 76 96 78 Q94 84 88 82 Q84 78 86 72 Q80 64 84 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M96 76 Q98 84 94 88 Q90 84 92 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="94" cy="86" rx="1.4" ry="1" fill="${INK}"/>
      ${eye(94, 64, 3, E)}
      <path d="M84 46 Q80 60 86 66" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".6"/>
    </g>`;
  },

  // ── Kirin — scaled deer-dragon, single gold antler, flowing mane, flame tail, hooves & scales (side, t5)
  kirin: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(58, 112, 30)}
    <g class="tail-wag">
      ${tube("M30 70 Q14 72 12 58", c.body, c.line, 5)}
      <path d="M12 58 Q6 50 10 42 Q10 50 16 52 Q10 46 12 58 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="12" cy="52" r="2" fill="${FIRE2}"/>
    </g>
    <g class="breathe">
      <path d="M28 70 C28 56 44 52 62 53 C76 54 82 58 82 66 C82 78 72 80 60 80 C42 80 28 78 28 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 74 Q56 82 78 74 Q56 80 34 74 Z" fill="${B}"/>
      ${[38, 50, 62, 72].map((x) => `<path d="M${x} 58 q4 3 8 0" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".5"/>`).join("")}
      ${[34, 64].map((x) => `<rect x="${x}" y="78" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><path d="M${x - 0.5} 100 h9 l-1 3 h-7 Z" fill="${INK}"/>`).join("")}
      ${[46, 74].map((x) => `<rect x="${x}" y="80" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><path d="M${x - 0.5} 100 h9 l-1 3 h-7 Z" fill="${INK}"/>`).join("")}
    </g>
    <g class="head-tilt">
      ${tube("M74 64 Q82 54 88 46", c.body, c.line, 12)}
      <path d="M82 46 Q80 34 90 32 Q99 33 102 42 L104 52 Q106 56 101 59 Q94 60 88 57 Q80 54 82 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M100 52 Q106 55 102 60 Q97 61 94 57 Z" fill="${c.shade}"/>
      <ellipse cx="101" cy="54" rx="1.4" ry="1" fill="${INK}"/>
      <path d="M88 34 Q84 18 92 10 Q94 22 98 30 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M82 42 Q72 44 74 56 Q66 50 62 58 Q72 56 74 63 Q64 63 60 71 Q74 65 84 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(94, 48, 2.8, E)}
      <path d="M86 40 Q84 34 88 30" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Komainu — shrine guardian lion-dog, curly mane, single horn, pointed ears, regal calm (front sitting)
  komainu: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag">
      ${pom(90, 80, 10, c.shade, c.line, 7, 2.6)}
      ${tube("M78 84 Q88 82 90 78", c.body, c.line, 6)}
    </g>
    <g class="breathe">
      <path d="M40 104 Q34 78 44 66 Q52 58 60 58 Q68 58 76 66 Q86 78 80 104 Q60 110 40 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="92" rx="15" ry="14" fill="${B}"/>
      ${tube("M46 80 L44 104", c.body, c.line, 8)}${tube("M74 80 L76 104", c.body, c.line, 8)}
      <path d="M40 104 q4 4 9 3 M80 104 q-4 4 -9 3" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${pom(60, 46, 22, c.shade, c.line, 12, 2.6)}
      <path d="M44 40 L38 24 L52 34 Z M76 40 L82 24 L68 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 20 Q56 10 60 6 Q64 10 60 20 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="48" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <ellipse cx="60" cy="54" rx="11" ry="8" fill="${B}"/>
      ${eyes(52, 68, 44, 3.4, E)}
      <path d="M46 40 q6 -3 11 1 M63 41 q6 -4 11 -1" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M60 52 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 55 q-5 5 -10 3 M60 55 q5 5 10 3" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`;
  },

  // ── Nue — chimera: monkey face, striped tiger legs, snake for a tail (front)
  nue: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(58, 112, 30)}
    <g class="tail-wag">
      ${tube("M40 78 Q18 82 16 64 Q16 54 26 56", c.body, c.line, 6)}
      <path d="M26 56 Q16 50 18 42 Q22 48 28 48 Q34 46 34 52 Q34 58 28 58 Q23 58 26 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M22 48 l-3 -3 M30 48 l3 -3" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <ellipse cx="26" cy="51" rx="1.2" ry="1" fill="${INK}"/>
    </g>
    <g class="breathe">
      <path d="M34 78 Q34 58 60 58 Q84 58 86 74 Q84 90 58 90 Q34 90 34 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M42 82 Q60 90 80 82 Q60 88 42 82 Z" fill="${B}"/>
      ${[44, 74].map((x) => `<rect x="${x}" y="84" width="10" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
      <path d="M45 90 h8 M45 96 h8 M75 90 h8 M75 96 h8" stroke="${c.shade}" stroke-width="2" stroke-linecap="round" opacity=".7"/>
      <path d="M44 104 l-2 3 m2 -3 l0 4 m0 -4 l2 3 M52 104 l-2 3 m2 -3 l0 4 m0 -4 l2 3 M74 104 l-2 3 m2 -3 l0 4 m0 -4 l2 3 M82 104 l-2 3 m2 -3 l0 4 m0 -4 l2 3" stroke="${INK}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M66 60 Q60 48 72 44 Q84 44 90 52 Q94 60 88 68 Q80 74 72 70 Q64 68 66 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <circle cx="72" cy="48" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="90" cy="54" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="80" cy="62" rx="11" ry="9" fill="${B}"/>
      ${eyes(74, 86, 58, 3, E)}
      <ellipse cx="80" cy="65" rx="2.4" ry="1.8" fill="${INK}"/>
      <path d="M74 68 q6 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
    </g>`;
  },

  // ── Raiju — thunder beast, jagged lightning-bolt tail, spiky electric fur, fierce yellow eyes (front quadruped)
  raiju: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(58, 112, 28)}
    <g class="tail-wag">
      <path d="M78 80 L96 62 L86 66 L100 48 L88 52 L98 38" fill="none" stroke="${c.line}" stroke-width="5.4" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M78 80 L96 62 L86 66 L100 48 L88 52 L98 38" fill="none" stroke="${FIRE2}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M32 96 Q28 70 42 62 L36 50 L48 58 Q54 54 60 54 Q66 54 72 58 L84 50 L78 62 Q92 70 88 96 Q60 104 32 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="84" rx="16" ry="14" fill="${B}"/>
      ${[40, 60, 80].map((x) => `<rect x="${x - 4}" y="92" width="9" height="14" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M42 44 L34 26 L52 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M43 40 L39 30 L49 38 Z" fill="${c.shade}"/>
      <path d="M78 44 L86 26 L68 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M77 40 L81 30 L71 38 Z" fill="${c.shade}"/>
      <path d="M40 50 Q40 68 60 70 Q80 68 80 50 Q60 42 40 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="60" rx="12" ry="8" fill="${B}"/>
      ${eyes(52, 68, 54, 3.2, "#ffd24a")}
      <path d="M60 62 l-2.4 2.4 h4.8 Z" fill="${INK}"/>
      <path d="M48 66 Q60 76 72 66 Q60 72 48 66 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M53 66 l1.6 4 l1.6 -4 Z M65 66 l-1.6 4 l-1.6 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Yuki-onna — serene snow woman, long black hair, trailing wispy kimono, half-lidded calm eyes, snowflakes (float)
  yukionna: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 115, 18)}
    <g class="tail-wag">
      <path d="M44 92 Q36 108 42 116 Q48 106 50 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M76 92 Q84 108 78 116 Q72 106 70 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M44 54 Q42 44 60 44 Q78 44 76 54 L84 96 Q78 90 72 96 Q66 90 60 96 Q54 90 48 96 Q42 90 36 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 52 L60 92 L68 52 Q60 58 52 52 Z" fill="${B}"/>
      ${tube("M46 56 Q36 68 40 84", c.body, c.line, 7)}${tube("M74 56 Q84 68 80 84", c.body, c.line, 7)}
      <path d="M40 66 Q60 72 80 66" fill="none" stroke="${c.shade}" stroke-width="4" stroke-linecap="round" opacity=".7"/>
    </g>
    <g class="tail-wag">
      <path d="M42 38 Q22 52 24 84 Q32 70 42 66 M78 38 Q98 52 96 84 Q88 70 78 66" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/>
      <path d="M42 38 Q22 52 24 84 Q32 70 42 66 M78 38 Q98 52 96 84 Q88 70 78 66" fill="none" stroke="${c.shade}" stroke-width="4.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M44 34 Q42 16 60 14 Q78 16 76 34 Q68 24 60 26 Q52 24 44 34 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="36" rx="15" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <ellipse cx="60" cy="42" rx="9" ry="6" fill="${B}"/>
      <path d="M50 34 q5 3 10 0 M60 34 q5 3 10 0" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>
      <path d="M55 44 q5 3 10 0" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M30 22 l1 3 l3 1 l-3 1 l-1 3 l-1 -3 l-3 -1 l3 -1 Z" fill="${GLOW}" opacity=".85"/>
      <path d="M90 30 l1 3 l3 1 l-3 1 l-1 3 l-1 -3 l-3 -1 l3 -1 Z" fill="${GLOW}" opacity=".85"/>
    </g>`;
  },

  // ── Zashiki-warashi — child house-spirit, bobbed hair with fringe, rosy cheeks, big smile, little kimono (front)
  zashikiwarashi: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 24)}
    <g class="breathe">
      <path d="M42 66 Q40 58 60 58 Q80 58 78 66 L84 102 Q60 108 36 102 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 62 L60 100 L68 62 Q60 68 52 62 Z" fill="${B}"/>
      ${tube("M44 68 Q34 78 38 90", c.body, c.line, 7)}${tube("M76 68 Q86 78 82 90", c.body, c.line, 7)}
      <path d="M40 80 Q60 88 80 80" fill="none" stroke="${c.shade}" stroke-width="5" stroke-linecap="round"/>
      ${tube("M52 102 L50 110", c.shade, c.line, 7)}${tube("M68 102 L70 110", c.shade, c.line, 7)}
    </g>
    <g class="head-tilt">
      <path d="M40 40 Q36 18 60 16 Q84 18 80 40 Q80 30 72 28 L48 28 Q40 30 40 40 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <circle cx="60" cy="40" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M42 34 Q42 24 52 24 L68 24 Q78 24 78 34 Q70 28 60 28 Q50 28 42 34 Z" fill="${c.shade}"/>
      <path d="M42 34 Q44 44 40 50 M78 34 Q76 44 80 50" fill="none" stroke="${c.shade}" stroke-width="5" stroke-linecap="round"/>
      ${ceye(52, 42, 4.4)}${ceye(68, 42, 4.4)}
      <circle cx="45" cy="49" r="3.4" fill="${c.shade}" opacity=".45"/><circle cx="75" cy="49" r="3.4" fill="${c.shade}" opacity=".45"/>
      <path d="M54 50 Q60 56 66 50" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>
    </g>`;
  },

  // ── Inugami — loyal dog spirit, floppy ears, will-o'-wisp foxfire, single tail (front sitting)
  inugami: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 113, 26)}
    <g class="tail-wag">
      <path d="M22 60 Q16 50 22 44 Q22 52 28 54 Q22 48 22 60 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round" opacity=".9"/>
      <circle cx="23" cy="53" r="1.6" fill="#fff"/>
      <path d="M78 96 Q98 96 98 76 Q97 66 88 70 Q94 76 90 84 Q86 92 76 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M40 104 Q34 80 44 66 Q52 58 60 58 Q68 58 76 66 Q86 80 80 104 Q60 110 40 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="90" rx="15" ry="14" fill="${B}"/>
      ${tube("M46 82 L44 104", c.body, c.line, 8)}${tube("M74 82 L76 104", c.body, c.line, 8)}
      <path d="M40 104 q4 4 9 3 M80 104 q-4 4 -9 3" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M42 38 Q34 20 46 18 Q52 30 54 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M45 26 Q42 34 48 40 Z" fill="${c.shade}"/>
      <path d="M78 38 Q86 20 74 18 Q68 30 66 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M75 26 Q78 34 72 40 Z" fill="${c.shade}"/>
      <path d="M42 44 Q42 62 60 66 Q78 62 78 44 Q60 38 42 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M50 54 Q50 66 60 70 Q70 66 70 54 Q60 58 50 54 Z" fill="${B}"/>
      ${eyes(52, 68, 50, 3.4, E)}
      <path d="M60 58 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M60 61 q-5 5 -9 3 M60 61 q5 5 9 3" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`;
  },

  // ── Shisa — Okinawan lion-dog, spiky radiating mane, wide toothy grin, curled tail (front sitting)
  shisa: (c) => {
    const B = belly(c), E = eyeInk(c);
    const spikes = Array.from({ length: 11 }, (_, i) => {
      const a = (-90 + i * 32.7) * Math.PI / 180;
      const x1 = 60 + 16 * Math.cos(a), y1 = 48 + 16 * Math.sin(a), x2 = 60 + 26 * Math.cos(a), y2 = 48 + 26 * Math.sin(a);
      return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${(y2 - 3).toFixed(1)} L${(x2 + 3).toFixed(1)} ${(y2 + 2).toFixed(1)} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`;
    }).join("");
    return `
    ${floorShadow(60, 113, 28)}
    <g class="tail-wag">
      <path d="M80 98 Q100 96 98 74 Q96 62 86 68 Q94 74 90 84 Q86 92 78 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M92 78 Q95 70 89 66" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M40 104 Q34 80 44 68 Q52 60 60 60 Q68 60 76 68 Q86 80 80 104 Q60 110 40 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="90" rx="15" ry="14" fill="${B}"/>
      ${tube("M46 82 L44 104", c.body, c.line, 8)}${tube("M74 82 L76 104", c.body, c.line, 8)}
      <path d="M39 104 l3 3 m-3 -3 l0 4 m0 -4 l3 3 M81 104 l-3 3 m3 -3 l0 4 m0 -4 l-3 3" stroke="${c.shade}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      ${spikes}
      <circle cx="60" cy="48" r="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M46 40 L40 28 L52 36 Z M74 40 L80 28 L68 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eyes(52, 68, 42, 3.4, E)}
      <path d="M46 38 q6 -3 11 1 M63 39 q6 -4 11 -1" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M60 48 l-3 3 h6 Z" fill="${INK}"/>
      <path d="M44 54 Q60 72 76 54 Q60 64 44 54 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M50 55 l2 5 l2 -5 Z M66 55 l2 5 l2 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>
      <path d="M56 66 q4 3 8 0" fill="none" stroke="${TOOTH}" stroke-width="2.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Kodama — pale forest tree-spirit, round three-hole face, leaf sprouts, wispy base (float)
  kodama: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 18)}
    <g class="tail-wag">
      <path d="M52 30 Q46 18 40 20 Q46 24 48 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M68 30 Q74 18 80 20 Q74 24 72 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M60 26 Q60 14 60 12 Q66 16 64 26 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M34 58 Q34 30 60 30 Q86 30 86 58 Q86 84 74 92 Q76 100 68 98 Q64 92 60 98 Q56 92 52 98 Q44 100 46 92 Q34 84 34 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="60" rx="20" ry="22" fill="${B}"/>
      <circle cx="50" cy="52" r="6" fill="${INK}"/><circle cx="70" cy="52" r="6" fill="${INK}"/>
      <ellipse cx="60" cy="72" rx="6" ry="8" fill="${INK}"/>
      <circle cx="51.6" cy="50" r="1.8" fill="#fff" opacity=".8"/><circle cx="71.6" cy="50" r="1.8" fill="#fff" opacity=".8"/>
    </g>`;
  },
};

export const ROSTER_YOKAI = [
  { n: "Tengu",            e: "👺", tier: 3, float: false },
  { n: "Oni",              e: "👹", tier: 4, float: false },
  { n: "Tanuki",           e: "🦝", tier: 2, float: false },
  { n: "Nekomata",         e: "🐈", tier: 3, float: false },
  { n: "Bakeneko",         e: "🐱", tier: 3, float: false },
  { n: "Karakasa",         e: "☂️", tier: 2, float: false },
  { n: "Rokurokubi",       e: "👤", tier: 3, float: false },
  { n: "Nurikabe",         e: "🧱", tier: 2, float: false },
  { n: "Jorogumo",         e: "🕷️", tier: 4, float: false },
  { n: "Amabie",           e: "🧜", tier: 3, float: true },
  { n: "Baku",             e: "💤", tier: 3, float: false },
  { n: "Kirin",            e: "🦌", tier: 5, float: false },
  { n: "Komainu",          e: "🦁", tier: 3, float: false },
  { n: "Nue",              e: "🐒", tier: 4, float: false },
  { n: "Raiju",            e: "⚡", tier: 4, float: false },
  { n: "Yuki-onna",        e: "❄️", tier: 4, float: true },
  { n: "Zashiki-warashi",  e: "🧒", tier: 2, float: false },
  { n: "Inugami",          e: "🐕", tier: 3, float: false },
  { n: "Shisa",            e: "🐶", tier: 3, float: false },
  { n: "Kodama",           e: "🌳", tier: 2, float: true },
];
