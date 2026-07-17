// pets-art/kaiju.js — BESPOKE hand-drawn SVG art for the KAIJU batch (giant-monster TITANS, the rare
// chase pets). Each entry: slug -> (c) => "<svg inner markup>" for viewBox 0 0 120 120, titan centred
// ~ (60,64), within x,y ∈ [8,114]. House style (see METHOD): ONE continuous silhouette filled c.body with
// a thick rounded c.line outline; appendages (tails/wings/claws/legs) OVERLAP & tuck (nothing floats);
// two-tone shading via belly(c) + c.shade; a clean fierce-but-cute face with big ceye eyes + a ground
// shadow. Colours come from the coat object c (body/shade/line); only universal accents are fixed:
// glow #7fe3ff / #eafff4, fire #ff7a1a, teeth #fff, horns #f2c94c. Titans are chunky & imposing but still
// cute mascots. Fliers set float:true. Keys match every ROSTER_KAIJU `n` slugified 1:1.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const GLOW = "#7fe3ff", GLOW2 = "#eafff4", FIRE = "#ff7a1a", FIRE2 = "#ffd24a", TOOTH = "#ffffff", HORN = "#f2c94c";
// upward triangle path d (spike/plate/tooth)
const tri = (x, y, h, w) => `M${x - w} ${y} L${x} ${y - h} L${x + w} ${y} Z`;
// fierce angled brows sitting above two eyes at x1,x2 (gives the mean-but-cute glare)
const brow = (x1, x2, y, line) => `<path d="M${x1 - 6} ${y} Q${x1} ${y - 3.5} ${x1 + 5} ${y - 1} M${x2 + 6} ${y} Q${x2} ${y - 3.5} ${x2 - 5} ${y - 1}" stroke="${line}" stroke-width="2.2" stroke-linecap="round" fill="none"/>`;

export const ART_KAIJU = {
  // ── Rex Kaiju — Godzilla-type biped, glowing dorsal spines, atomic-glow belly, tiny arms, thick tail (front) ──
  rexkaiju: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 32)}
    <g class="tail-wag">
      <path d="M36 90 Q13 96 8 74 Q6 62 18 66 Q10 74 18 83 Q28 90 39 85 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[[16, 69], [11, 80]].map(([x, y]) => `<path d="M${x} ${y} l-6 -3 l3 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="tail-wag">
      ${[46, 56, 66].map(x => `<path d="${tri(x + 5, 25, 15, 5)}" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/><path d="${tri(x + 5, 13, 4, 2)}" fill="${GLOW}"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M44 26 Q58 12 74 25 Q82 31 82 43 Q90 49 90 63 Q90 81 84 89 L82 107 Q82 111 76 111 L68 111 L68 89 Q60 85 52 89 L52 111 L44 111 Q38 111 38 107 L38 89 Q30 81 30 63 Q30 49 38 43 Q38 31 44 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="76" rx="16" ry="16" fill="${GLOW}" opacity=".5"/>
      <ellipse cx="60" cy="76" rx="9" ry="9" fill="${GLOW2}" opacity=".7"/>
      <path d="M50 72 q10 5 20 0 M52 80 q8 4 16 0" fill="none" stroke="${GLOW}" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>
      <g class="tail-wag">${tube("M42 55 Q34 59 34 67", c.body, c.line, 5)}${tube("M78 55 Q86 59 86 67", c.body, c.line, 5)}</g>
      <path d="M33 66 l-3 4 m3 -4 l0 5 m0 -5 l3 4 M87 66 l-3 4 m3 -4 l0 5 m0 -5 l3 4" stroke="${TOOTH}" stroke-width="1.4" stroke-linecap="round"/>
      ${ceye(51, 34, 4.3)}${ceye(69, 34, 4.3)}
      ${brow(51, 69, 28, c.line)}
      <ellipse cx="55" cy="41" rx="1.1" ry="1.4" fill="${INK}"/><ellipse cx="65" cy="41" rx="1.1" ry="1.4" fill="${INK}"/>
      <path d="M47 45 Q60 57 73 45 Q60 51 47 45 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M51 46 l2 4 l2 -4 M58 47 l2 4 l2 -4 M65 46 l2 4 l2 -4" fill="${TOOTH}"/>
    </g>`; },

  // ── Turtle Titan — chunky shelled biped, spiked-crown shell, plated plastron, head peeking out (front) ──
  turtletitan: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 31)}
    <g class="breathe">
      <path d="M26 82 Q23 58 32 46 L38 30 L46 44 L54 28 L62 42 L70 28 L78 44 L86 46 Q95 60 90 82 Q88 94 60 96 Q32 94 26 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M36 62 Q60 52 84 62 Q84 78 60 82 Q36 78 36 62 Z" fill="${c.body}"/>
      <path d="M60 54 V82 M40 66 Q60 74 80 66 M44 76 Q60 82 76 76" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      <path d="M31 86 Q23 88 23 98 Q23 107 32 107 Q41 105 39 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M89 86 Q97 88 97 98 Q97 107 88 107 Q79 105 81 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M46 84 Q43 110 60 110 Q77 110 74 84 Q60 91 46 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M49 94 q11 6 22 0" fill="${B}" opacity=".7"/>
      ${ceye(53, 96, 4.3)}${ceye(67, 96, 4.3)}
      ${brow(53, 67, 90, c.line)}
      <path d="M54 103 q6 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`; },

  // ── Moth Titan — Mothra-type, big fuzzy body, broad patterned wings, feathery antennae (front, float) ──
  mothtitan: (c) => { const B = belly(c); const wing = `
      <path d="M60 60 Q86 34 104 50 Q110 62 98 70 Q108 80 96 94 Q76 88 60 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <circle cx="90" cy="58" r="6" fill="${GLOW}" opacity=".8" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M64 70 Q82 82 96 88" fill="none" stroke="${c.shade}" stroke-width="2.4" opacity=".6"/>
      <path d="M74 66 Q84 62 94 64" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5"/>`;
    return `
    ${floorShadow(60, 111, 26)}
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      ${pom(60, 84, 13, c.body, c.line, 9, 2.6)}
      ${pom(60, 62, 15, c.body, c.line, 10, 2.8)}
      <ellipse cx="60" cy="84" rx="8" ry="9" fill="${c.shade}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${pom(60, 44, 11, c.body, c.line, 8, 2.6)}
      <path d="M52 36 Q40 22 30 24 M68 36 Q80 22 90 24" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M52 36 Q40 22 30 24 M68 36 Q80 22 90 24" fill="none" stroke="${c.shade}" stroke-width="1.6" stroke-linecap="round"/>
      ${pom(30, 24, 4, c.shade, c.line, 6, 1.6)}${pom(90, 24, 4, c.shade, c.line, 6, 1.6)}
      ${ceye(54, 44, 4)}${ceye(66, 44, 4)}
      ${smile(60, 50, 3.2)}
    </g>`; },

  // ── Ape Titan — Kong-type giant gorilla, huge knuckle arms, broad chest, small head, brow (front) ──
  apetitan: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 32)}
    <g class="tail-wag">
      ${tube("M42 48 Q24 62 26 92", c.body, c.line, 9)}${tube("M78 48 Q96 62 94 92", c.body, c.line, 9)}
      <circle cx="26" cy="94" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="3"/><circle cx="94" cy="94" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <path d="M20 92 h12 M20 96 h12 M88 92 h12 M88 96 h12" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
    </g>
    <g class="breathe">
      <path d="M48 34 Q46 18 60 17 Q74 18 72 34 Q82 36 84 50 Q86 66 80 86 L78 104 Q78 108 70 108 L66 108 Q64 102 66 90 Q60 92 54 90 Q56 102 54 108 L50 108 Q42 108 42 104 L40 86 Q34 66 36 50 Q38 36 48 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 58 Q60 50 74 58 Q74 78 60 84 Q46 78 46 58 Z" fill="${B}"/>
      <path d="M60 52 V82" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="30" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <circle cx="44" cy="30" r="4.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><circle cx="76" cy="30" r="4.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <path d="M48 34 Q60 28 72 34 Q72 44 60 46 Q48 44 48 34 Z" fill="${c.shade}"/>
      ${ceye(53, 28, 3.8)}${ceye(67, 28, 3.8)}
      ${brow(53, 67, 22, c.line)}
      <path d="M56 38 q4 2 8 0" fill="none" stroke="${INK}" stroke-width="1.2" stroke-linecap="round"/>
      <path d="M54 42 q6 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`; },

  // ── Squid Titan — colossal squid, bullet mantle, big glow eyes, fanned arms + two feeder tentacles (front, float) ──
  squidtitan: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${[[50, 40, 100], [56, 52, 108], [60, 60, 110], [64, 68, 108], [70, 80, 100]].map(([rx, ex, ey]) => tube(`M${rx} 66 Q${(rx + ex) / 2} ${ey - 12} ${ex} ${ey}`, c.body, c.line, 6)).join("")}
      ${tube("M46 64 Q28 82 34 104", c.shade, c.line, 4)}${tube("M74 64 Q92 82 86 104", c.shade, c.line, 4)}
      <circle cx="34" cy="104" r="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/><circle cx="86" cy="104" r="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
    </g>
    <g class="breathe">
      <path d="M52 16 L60 8 L68 16 Q80 26 78 50 Q76 66 60 68 Q44 66 42 50 Q40 26 52 16 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 22 Q60 16 68 22 Q64 34 60 34 Q56 34 52 22 Z" fill="${B}" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <circle cx="51" cy="48" r="7.5" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/><circle cx="51" cy="49" r="3.4" fill="${INK}"/><circle cx="49.6" cy="47.4" r="1.2" fill="#fff"/>
      <circle cx="69" cy="48" r="7.5" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/><circle cx="69" cy="49" r="3.4" fill="${INK}"/><circle cx="67.6" cy="47.4" r="1.2" fill="#fff"/>
      <path d="M54 60 q6 4 12 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`; },

  // ── Bat Kaiju — huge membrane wings with finger-struts, fuzzy body, big ears, little fangs (front, float) ──
  batkaiju: (c) => { const B = belly(c); const wing = `
      <path d="M60 56 Q84 40 104 44 L97 53 Q106 55 101 63 L93 65 Q101 70 95 79 Q76 74 60 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M62 60 Q80 52 98 49 M64 64 Q82 60 96 61" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".5"/>`;
    return `
    ${floorShadow(60, 111, 25)}
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M46 68 Q46 56 60 56 Q74 56 74 68 Q74 82 60 86 Q46 82 46 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 70 Q60 66 68 70 Q68 78 60 82 Q52 78 52 70 Z" fill="${B}"/>
    </g>
    <g class="head-tilt">
      <path d="M44 42 L36 20 L54 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/><path d="M76 42 L84 20 L66 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M45 38 L41 27 L51 34 Z M75 38 L79 27 L69 34 Z" fill="${c.shade}"/>
      <path d="M42 46 Q42 30 60 30 Q78 30 78 46 Q78 58 60 60 Q42 58 42 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="49" rx="15" ry="11" fill="${B}"/>
      ${ceye(53, 47, 4.4)}${ceye(67, 47, 4.4)}
      ${brow(53, 67, 41, c.line)}
      <path d="M60 53 l-2.5 3 h5 Z" fill="${INK}"/>
      <path d="M54 57 l1.5 4 l1.5 -4 M63 57 l1.5 4 l1.5 -4" fill="${TOOTH}"/>
    </g>`; },

  // ── Crab Titan — armored carapace, two towering pincer claws, eyestalks, little walking legs (front) ──
  crabtitan: (c) => { const B = belly(c); const claw = (sx, sy, cx, cy, dir) => `
      ${tube(`M${sx} ${sy} Q${cx} ${cy + 14} ${cx} ${cy}`, c.body, c.line, 6)}
      <path d="M${cx} ${cy} Q${cx - dir * 12} ${cy - 6} ${cx - dir * 12} ${cy + 6} Q${cx - dir * 6} ${cy + 10} ${cx} ${cy + 6} Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M${cx} ${cy - 2} Q${cx - dir * 10} ${cy - 12} ${cx - dir * 13} ${cy - 4} Q${cx - dir * 8} ${cy} ${cx} ${cy + 2} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 111, 32)}
    <g class="tail-wag">
      ${[[34, 92], [40, 96], [80, 92], [86, 96]].map(([x, y]) => tube(`M${x < 60 ? 40 : 80} 84 Q${x} ${y - 6} ${x} ${y}`, c.body, c.line, 4)).join("")}
    </g>
    <g class="tail-wag">${claw(34, 66, 20, 42, 1)}${claw(86, 66, 100, 42, -1)}</g>
    <g class="breathe">
      <path d="M24 78 Q22 58 60 56 Q98 58 96 78 Q96 92 60 94 Q24 92 24 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 80 Q60 90 86 80 Q60 86 34 80 Z" fill="${B}" opacity=".8"/>
      <path d="M40 70 q8 -5 16 0 M64 70 q8 -5 16 0" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${tube("M50 60 Q48 50 48 44", c.body, c.line, 3.4)}${tube("M70 60 Q72 50 72 44", c.body, c.line, 3.4)}
      ${ceye(48, 42, 4)}${ceye(72, 42, 4)}
      ${brow(48, 72, 37, c.line)}
      <path d="M52 78 q8 4 16 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="46" cy="82" r="1.4" fill="#fff" opacity=".7"/><circle cx="42" cy="79" r="1" fill="#fff" opacity=".6"/>
    </g>`; },

  // ── Serpent Kaiju — sea-serpent, coiled humped body, frilled crest, raised head, big eye (side) ──
  serpentkaiju: (c) => { const B = belly(c); return `
    ${floorShadow(58, 110, 34)}
    <g class="tail-wag">
      ${tube("M12 92 Q22 78 34 90 Q46 100 58 86 Q68 74 74 62", c.body, c.line, 12)}
      <path d="M12 92 l-4 -2 l2 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      ${[[30, 82], [46, 90], [60, 76]].map(([x, y]) => `<path d="${tri(x, y - 8, 9, 4)}" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M68 46 Q68 30 84 28 Q100 28 102 44 Q104 58 90 62 L104 64 Q102 72 90 70 Q70 68 68 54 Q66 48 68 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M96 64 l1.5 4 l1.5 -4 M100 64 l1.5 4 l1.5 -4" fill="${TOOTH}"/>
      <path d="M76 28 Q74 16 82 12 Q84 22 86 28 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M86 27 Q86 15 94 12 Q94 22 94 28 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M70 50 Q80 56 92 52" fill="none" stroke="${B}" stroke-width="2.4" stroke-linecap="round" opacity=".7"/>
      ${ceye(88, 46, 3.8)}
      ${brow(88, 88, 40, c.line)}
    </g>`; },

  // ── Beetle Mech — armored rhino-beetle, domed elytra, single forked horn, six legs, glow visor (front) ──
  beetlemech: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 30)}
    <g class="tail-wag">
      ${[[24, 74], [20, 86], [24, 96], [96, 74], [100, 86], [96, 96]].map(([x, y]) => tube(`M${x < 60 ? 38 : 82} ${y - 10} Q${x} ${y - 6} ${x} ${y}`, c.shade, c.line, 4)).join("")}
    </g>
    <g class="breathe">
      <path d="M28 80 Q26 52 60 50 Q94 52 92 80 Q92 96 60 98 Q28 96 28 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 52 V96" fill="none" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 66 Q60 60 80 66 M38 80 Q60 74 82 80" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      ${[[42, 62], [78, 62], [42, 88], [78, 88], [48, 76], [72, 76]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M46 52 Q46 40 60 40 Q74 40 74 52 Q74 58 60 58 Q46 58 46 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M58 43 Q56 26 46 14 Q59 18 62 33 Q65 18 74 14 Q66 26 64 43 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 40 L60 31" stroke="${c.line}" stroke-width="1.1" opacity=".5"/>
      <rect x="49" y="47" width="22" height="6" rx="3" fill="${GLOW}" stroke="${c.line}" stroke-width="1.8"/>
      <circle cx="55" cy="50" r="1.5" fill="${INK}"/><circle cx="65" cy="50" r="1.5" fill="${INK}"/>
    </g>`; },

  // ── Dino Mech — Mechagodzilla-type armored biped, panel plates, bolts, glow visor & reactor, mech jaw (front) ──
  dinomech: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 31)}
    <g class="tail-wag">
      <path d="M38 90 L14 100 L20 90 L12 82 L34 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      ${[46, 56, 66].map(x => `<path d="${tri(x + 5, 26, 12, 4.5)}" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M44 30 L44 22 L60 18 L76 22 L76 30 L86 40 L83 58 L88 74 L82 90 L82 108 L68 108 L68 90 L52 90 L52 108 L38 108 L38 90 L32 74 L37 58 L34 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <circle cx="60" cy="66" r="8" fill="${GLOW}" stroke="${c.line}" stroke-width="2.2"/><circle cx="60" cy="66" r="3.4" fill="${GLOW2}"/>
      <path d="M44 46 L76 46 M40 78 L80 78" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".55"/>
      ${[[46, 44], [74, 44], [42, 80], [78, 80]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.8" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>`).join("")}
      <g class="tail-wag">${tube("M40 52 L30 62", c.body, c.line, 5)}${tube("M80 52 L90 62", c.body, c.line, 5)}</g>
    </g>
    <g class="head-tilt">
      <rect x="46" y="26" width="28" height="9" rx="2" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/>
      <rect x="50" y="28.5" width="6" height="4" fill="${INK}"/><rect x="64" y="28.5" width="6" height="4" fill="${INK}"/>
      <path d="M48 36 L72 36 L70 42 L50 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M52 37 v4 M58 37 v4 M64 37 v4 M68 37 v4" stroke="${TOOTH}" stroke-width="2" stroke-linecap="round"/>
      <path d="M60 18 L60 10" stroke="${c.line}" stroke-width="2"/><circle cx="60" cy="9" r="2.4" fill="${GLOW}" stroke="${c.line}" stroke-width="1.4"/>
    </g>`; },

  // ── Golem Titan — living boulder, glowing cracks & eyes, mossy patches, blocky fists & stubby legs (front) ──
  golemtitan: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 32)}
    <g class="tail-wag">
      <path d="M22 62 L14 70 L18 84 L30 82 L30 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M98 62 L106 70 L102 84 L90 82 L90 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M30 62 Q28 40 50 34 Q74 30 90 44 Q100 58 92 78 Q86 96 60 98 Q32 96 27 74 Q26 66 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 100 L40 110 L52 110 L50 100 Z M76 100 L70 110 L82 110 L80 100 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M42 46 Q54 42 58 52 M70 42 Q80 48 78 60 M50 76 Q58 82 70 78" fill="none" stroke="${GLOW}" stroke-width="2" stroke-linecap="round" opacity=".85"/>
      <path d="M34 52 Q44 50 48 56 Q40 60 34 56 Z" fill="${c.shade}" opacity=".6"/><path d="M78 70 Q88 68 90 76 Q82 80 78 74 Z" fill="${c.shade}" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <circle cx="50" cy="56" r="5.5" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/><circle cx="50" cy="56" r="2.2" fill="${INK}"/>
      <circle cx="72" cy="56" r="5.5" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/><circle cx="72" cy="56" r="2.2" fill="${INK}"/>
      ${brow(50, 72, 48, c.line)}
      <path d="M50 70 L56 68 L60 72 L66 68 L72 70" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </g>`; },

  // ── Wyrm Kaiju — burrowing drill-worm rising from the ground, ringed segments, round toothy maw (front) ──
  wyrmkaiju: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 30)}
    <g class="breathe">
      <path d="M42 108 Q38 60 46 38 Q50 18 60 18 Q70 18 74 38 Q82 60 78 108 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M45 68 Q60 62 75 68 M44 82 Q60 76 76 82 M44 96 Q60 90 76 96" fill="none" stroke="${c.shade}" stroke-width="2.4" opacity=".55"/>
      <circle cx="60" cy="54" r="17" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8"/>
      <circle cx="60" cy="54" r="9" fill="${INK}"/>
      ${Array.from({ length: 12 }, (_, i) => { const a = i * 30 * Math.PI / 180, d = 13 * Math.PI / 180;
        const bx1 = 60 + 15.5 * Math.cos(a - d), by1 = 54 + 15.5 * Math.sin(a - d);
        const bx2 = 60 + 15.5 * Math.cos(a + d), by2 = 54 + 15.5 * Math.sin(a + d);
        const tx = 60 + 7 * Math.cos(a), ty = 54 + 7 * Math.sin(a);
        return `<path d="M${bx1.toFixed(1)} ${by1.toFixed(1)} L${tx.toFixed(1)} ${ty.toFixed(1)} L${bx2.toFixed(1)} ${by2.toFixed(1)} Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>`; }).join("")}
    </g>
    <g class="head-tilt">
      ${ceye(50, 32, 3.8)}${ceye(70, 32, 3.8)}
      ${brow(50, 70, 26, c.line)}
    </g>`; },

  // ── Spider Titan — round abdomen + head, eight jointed legs, cluster of eyes, small fangs (front) ──
  spidertitan: (c) => { const B = belly(c); const leg = (sx, sy, kx, ky, fx, fy) => `${tube(`M${sx} ${sy} L${kx} ${ky}`, c.body, c.line, 5)}${tube(`M${kx} ${ky} L${fx} ${fy}`, c.body, c.line, 4)}`;
    return `
    ${floorShadow(60, 111, 34)}
    <g class="tail-wag">
      ${leg(46, 58, 26, 44, 14, 60)}${leg(46, 66, 22, 62, 12, 80)}${leg(46, 74, 24, 82, 16, 100)}${leg(50, 82, 34, 96, 28, 110)}
      ${leg(74, 58, 94, 44, 106, 60)}${leg(74, 66, 98, 62, 108, 80)}${leg(74, 74, 96, 82, 104, 100)}${leg(70, 82, 86, 96, 92, 110)}
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="82" rx="24" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M60 66 Q68 82 60 98 Q52 82 60 66 Z" fill="${B}"/>
      <ellipse cx="60" cy="48" rx="17" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
    </g>
    <g class="head-tilt">
      ${ceye(53, 46, 4)}${ceye(67, 46, 4)}
      ${brow(53, 67, 40, c.line)}
      <circle cx="49" cy="53" r="1.6" fill="${INK}"/><circle cx="60" cy="55" r="1.6" fill="${INK}"/><circle cx="71" cy="53" r="1.6" fill="${INK}"/>
      <path d="M55 58 l-2 4 M65 58 l2 4" stroke="${TOOTH}" stroke-width="2" stroke-linecap="round"/>
    </g>`; },

  // ── Scorpion Mech — armored body, forward pincer claws, segmented tail arching over a glow stinger (front) ──
  scorpionmech: (c) => { const B = belly(c); const claw = (sx, sy, cx, cy, dir) => `
      ${tube(`M${sx} ${sy} Q${(sx + cx) / 2} ${cy + 4} ${cx} ${cy}`, c.body, c.line, 5)}
      <path d="M${cx} ${cy} Q${cx + dir * 12} ${cy - 4} ${cx + dir * 13} ${cy + 5} Q${cx + dir * 7} ${cy + 8} ${cx} ${cy + 4} Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M${cx} ${cy - 1} Q${cx + dir * 11} ${cy - 11} ${cx + dir * 14} ${cy - 3} Q${cx + dir * 9} ${cy + 1} ${cx} ${cy + 3} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      ${[[36, 88], [42, 96], [78, 96], [84, 88]].map(([x, y]) => tube(`M${x < 60 ? 46 : 74} 80 Q${x} ${y - 6} ${x} ${y}`, c.shade, c.line, 4)).join("")}
    </g>
    <g class="tail-wag">${claw(40, 66, 22, 52, -1)}${claw(80, 66, 98, 52, 1)}</g>
    <g class="tail-wag">
      ${tube("M60 72 Q86 66 90 44 Q92 30 80 28", c.body, c.line, 7)}
      ${[[86, 60], [90, 48]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>`).join("")}
      <path d="M80 28 Q70 22 74 34 Q78 30 80 28 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="80" cy="30" r="3" fill="${GLOW2}" opacity=".9"/>
    </g>
    <g class="breathe">
      <path d="M40 74 Q38 58 60 56 Q82 58 80 74 Q80 88 60 90 Q40 88 40 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M48 64 Q60 60 72 64 M46 78 Q60 74 74 78" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <circle cx="52" cy="70" r="4.5" fill="${GLOW}" stroke="${c.line}" stroke-width="1.8"/><circle cx="52" cy="70" r="1.8" fill="${INK}"/>
      <circle cx="68" cy="70" r="4.5" fill="${GLOW}" stroke="${c.line}" stroke-width="1.8"/><circle cx="68" cy="70" r="1.8" fill="${INK}"/>
      ${brow(52, 68, 63, c.line)}
    </g>`; },

  // ── Bird Titan — thunderbird, broad layered feather wings, crest, hooked beak, talons, storm glow (front, float) ──
  birdtitan: (c) => { const B = belly(c); const wing = `
      <path d="M60 58 Q40 38 18 32 Q30 46 32 56 Q22 50 12 52 Q26 60 40 62 Q26 65 18 74 Q42 70 60 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M56 58 Q40 44 26 40 M54 61 Q40 54 30 55" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      <circle cx="24" cy="42" r="2" fill="${GLOW}" opacity=".8"/>`;
    return `
    ${floorShadow(60, 111, 27)}
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M46 44 Q46 30 60 30 Q74 30 74 44 Q80 62 74 84 L72 98 Q66 96 64 88 Q60 92 56 88 Q54 96 48 98 L46 84 Q40 62 46 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 52 Q60 48 68 52 Q68 74 60 82 Q52 74 52 52 Z" fill="${B}"/>
      <path d="M56 98 l-3 6 m3 -6 l0 6 m0 -6 l3 6 M64 98 l-3 6 m3 -6 l0 6 m0 -6 l3 6" stroke="${HORN}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M52 30 L48 18 L58 26 L60 14 L62 26 L72 18 L68 30 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="60" cy="38" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M56 44 L60 52 L64 44 Q60 47 56 44 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${ceye(54, 36, 4)}${ceye(66, 36, 4)}
      ${brow(54, 66, 30, c.line)}
    </g>`; },

  // ── Whale Kaiju — armored leviathan, finned back plates, pectoral fin, glowing spout, big eye (side, float) ──
  whalekaiju: (c) => { const B = belly(c); return `
    ${floorShadow(58, 108, 34)}
    <g class="tail-wag">
      <path d="M28 70 L10 52 Q6 66 10 82 Q22 80 30 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      ${[[42, 54], [56, 50], [70, 52]].map(([x, y]) => `<path d="${tri(x, y, 12, 6)}" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M26 64 Q30 40 62 40 Q96 40 104 64 Q98 88 62 88 Q30 88 26 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 78 Q64 90 96 78 Q64 84 40 78 Z" fill="${B}" opacity=".85"/>
      <path d="M46 82 h44" stroke="${c.line}" stroke-width="1.2" opacity=".45"/>
      <path d="M62 76 Q72 84 84 78 Q76 82 68 80 Q66 78 62 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M62 40 Q60 24 66 16 M66 16 q-5 -6 -2 -10 M66 16 q6 -4 5 -10" fill="none" stroke="${GLOW}" stroke-width="2.6" stroke-linecap="round" opacity=".85"/>
      <circle cx="63" cy="6" r="2.6" fill="${GLOW2}" opacity=".8"/><circle cx="71" cy="7" r="2.2" fill="${GLOW2}" opacity=".7"/>
      <path d="M84 62 Q96 66 104 62" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${ceye(88, 56, 4.2)}
      ${brow(88, 88, 50, c.line)}
    </g>`; },

  // ── Sludge Titan — towering ooze, glossy dripping body, glow core, two pseudopod arms, bubbles (front) ──
  sludgetitan: (c) => { const B = belly(c); return `
    ${floorShadow(60, 112, 32)}
    <g class="tail-wag">
      ${tube("M40 66 Q22 62 18 78", c.body, c.line, 8)}${tube("M80 66 Q98 62 102 78", c.body, c.line, 8)}
      <circle cx="18" cy="80" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="102" cy="80" r="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="66" rx="38" ry="32" fill="${GLOW}" opacity=".18"/>
      <path d="M28 60 Q26 34 60 32 Q94 34 92 60 Q94 86 90 102 Q84 94 78 102 Q72 94 66 102 Q60 94 54 102 Q48 94 42 102 Q36 94 30 102 Q26 86 28 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round" opacity=".95"/>
      <path d="M40 44 Q54 34 66 38 Q52 42 46 52 Z" fill="#fff" opacity=".4"/>
      <ellipse cx="60" cy="72" rx="12" ry="12" fill="${GLOW}" opacity=".55"/><ellipse cx="60" cy="72" rx="6" ry="6" fill="${GLOW2}" opacity=".8"/>
      <circle cx="42" cy="60" r="3" fill="#fff" opacity=".22"/><circle cx="76" cy="80" r="4" fill="#fff" opacity=".2"/>
    </g>
    <g class="head-tilt">
      ${ceye(51, 58, 4.4)}${ceye(69, 58, 4.4)}
      ${brow(51, 69, 51, c.line)}
      <path d="M48 68 Q60 82 72 68 Q60 76 48 68 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>`; },

  // ── Rock Titan — towering craggy stone giant, jagged crystal crown, faceted body, blocky fists (front) ──
  rocktitan: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 32)}
    <g class="tail-wag">
      <path d="M28 56 L16 62 L18 78 L30 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M92 56 L104 62 L102 78 L90 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M38 40 L30 22 L44 34 L50 16 L58 32 L64 14 L70 32 L78 20 L82 40 L88 52 L82 84 L82 108 L68 108 L68 90 L52 90 L52 108 L38 108 L38 84 L32 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 46 L60 42 L54 60 L64 58 L56 76 M74 46 L80 60 L70 64" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".5"/>
      <path d="M40 44 L52 42 L48 56 Z" fill="${c.shade}" opacity=".5"/><path d="M78 50 L84 62 L74 60 Z" fill="${c.shade}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${ceye(51, 52, 3.8)}${ceye(69, 52, 3.8)}
      ${brow(51, 69, 46, c.line)}
      <path d="M52 66 L58 64 L62 68 L68 64" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </g>`; },

  // ── Storm Kaiju — living thundercloud, fluffy body, glow eyes, forked lightning bolts, raindrops (front, float) ──
  stormkaiju: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 30)}
    <g class="tail-wag">
      <path d="M50 84 L58 84 L52 96 L60 96 L48 112 L54 100 L46 100 Z" fill="${FIRE2}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M70 82 L78 82 L72 92 L80 92 L68 108 L74 96 L66 96 Z" fill="${FIRE2}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="36" cy="96" r="2.2" fill="${GLOW}" opacity=".8"/><circle cx="86" cy="98" r="2.2" fill="${GLOW}" opacity=".8"/>
    </g>
    <g class="breathe">
      ${pom(60, 64, 34, c.body, c.line, 14, 3)}
      <path d="M32 74 Q60 88 88 74 Q60 82 32 74 Z" fill="${c.shade}" opacity=".5"/>
      <g class="tail-wag">${tube("M32 66 Q20 70 22 80", c.body, c.line, 6)}${tube("M88 66 Q100 70 98 80", c.body, c.line, 6)}</g>
    </g>
    <g class="head-tilt">
      <circle cx="50" cy="60" r="6" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/><circle cx="50" cy="61" r="2.6" fill="${INK}"/><circle cx="48.6" cy="59" r="1" fill="#fff"/>
      <circle cx="70" cy="60" r="6" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/><circle cx="70" cy="61" r="2.6" fill="${INK}"/><circle cx="68.6" cy="59" r="1" fill="#fff"/>
      ${brow(50, 70, 52, c.line)}
      <path d="M52 72 Q60 78 68 72" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
    </g>`; },

  // ── Volcano Titan — walking magma mountain, crater vent glow, glowing lava cracks, smoke, craggy limbs (front) ──
  volcanotitan: (c) => { const B = belly(c); return `
    ${floorShadow(60, 111, 34)}
    <g class="tail-wag">
      <path d="M24 74 L14 78 L16 92 L28 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M96 74 L106 78 L104 92 L92 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M52 30 Q50 20 56 14 M60 28 Q60 16 60 10 M68 30 Q70 20 66 14" fill="none" stroke="${c.shade}" stroke-width="3.4" stroke-linecap="round" opacity=".55"/>
    </g>
    <g class="breathe">
      <path d="M28 100 L40 40 Q44 28 60 28 Q76 28 80 40 L92 100 Q92 106 60 106 Q28 106 28 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 32 Q60 26 74 32 Q68 40 60 40 Q52 40 46 32 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M52 33 Q60 30 68 33 Q60 36 52 33 Z" fill="${FIRE2}"/>
      <path d="M48 52 L56 58 L50 68 L58 74 M74 54 L68 64 L76 70" fill="none" stroke="${FIRE}" stroke-width="2.2" stroke-linecap="round" opacity=".9"/>
      <path d="M40 84 Q60 92 80 84" fill="none" stroke="${FIRE}" stroke-width="1.8" opacity=".7"/>
    </g>
    <g class="head-tilt">
      ${ceye(51, 58, 4)}${ceye(69, 58, 4)}
      ${brow(51, 69, 52, c.line)}
      <path d="M50 70 Q60 78 70 70 Q60 74 50 70 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>`; },
};

export const ROSTER_KAIJU = [
  { n: "Rex Kaiju",     e: "🦖", tier: 5, float: false },
  { n: "Turtle Titan",  e: "🐲", tier: 4, float: false },
  { n: "Moth Titan",    e: "👹", tier: 4, float: true  },
  { n: "Ape Titan",     e: "👹", tier: 5, float: false },
  { n: "Squid Titan",   e: "🐲", tier: 4, float: true  },
  { n: "Bat Kaiju",     e: "👹", tier: 4, float: true  },
  { n: "Crab Titan",    e: "🐲", tier: 4, float: false },
  { n: "Serpent Kaiju", e: "🐲", tier: 4, float: false },
  { n: "Beetle Mech",   e: "👹", tier: 3, float: false },
  { n: "Dino Mech",     e: "🦖", tier: 4, float: false },
  { n: "Golem Titan",   e: "👹", tier: 4, float: false },
  { n: "Wyrm Kaiju",    e: "🐲", tier: 4, float: false },
  { n: "Spider Titan",  e: "👹", tier: 4, float: false },
  { n: "Scorpion Mech", e: "👹", tier: 3, float: false },
  { n: "Bird Titan",    e: "🐲", tier: 4, float: true  },
  { n: "Whale Kaiju",   e: "🐲", tier: 4, float: true  },
  { n: "Sludge Titan",  e: "👹", tier: 3, float: false },
  { n: "Rock Titan",    e: "👹", tier: 4, float: false },
  { n: "Storm Kaiju",   e: "🐲", tier: 4, float: true  },
  { n: "Volcano Titan", e: "🦖", tier: 5, float: false },
];
