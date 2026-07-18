// pets-art/crustaceans.js — BESPOKE hand-drawn SVG art for the CRUSTACEANS & MOLLUSKS batch of NADO Pets.
// Each entry: slug -> (c) => "<svg inner markup string>" for <svg viewBox="0 0 120 120">.
// Coat: c.body (main fill), c.shade (underside/accent), c.line (outline). ALL aquatic => float:true, so no
// ground shadow (matches sea.js / reef.js). ONE continuous silhouette per body; claws/legs/antennae/cirri
// are rooted INSIDE the body so nothing floats. Two-tone shading + a clean cute face on every one.
// Helpers from ../pets-draw.js. Fixed white pearl/tooth accents only; nose/eyes = INK/eyeInk.
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const PEARL = "#f5f2ea"; // nacre / pearl

export const ART_CRUSTACEANS = {
  // Krill — tiny translucent shrimp: curved body, big single eye, feathery swimmerets, tail fan, long antennae
  krill: (c) => { const E = eyeInk(c), B = belly(c);
    const legs = Array.from({ length: 6 }, (_, i) => `<path d="M${42 + i * 7} 68 q-2 8 -4 11 M${44 + i * 7} 68 q1 9 0 12 M${46 + i * 7} 68 q3 8 4 10" stroke="${c.line}" stroke-width="1" fill="none" stroke-linecap="round" opacity=".8"/>`).join("");
    return `
    <g class="tail-wag">
      <path d="M40 62 Q22 50 12 54 Q22 60 16 62 Q22 64 12 70 Q22 74 40 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M38 62 L16 55 M38 62 L14 62 M38 62 L16 69" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>
    </g>
    <g class="tail-wag">${legs}</g>
    <g class="breathe">
      <path d="M34 54 Q56 46 78 50 Q92 53 92 62 Q92 71 78 74 Q56 78 34 70 Q26 62 34 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M40 69 Q60 74 82 70 Q60 76 40 69 Z" fill="${B}" opacity=".85"/>
      ${[48, 58, 68, 78].map((x) => `<path d="M${x} 52 q-2 10 0 20" stroke="${c.line}" stroke-width="1.1" fill="none" opacity=".5"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M88 54 Q100 46 110 40 M90 58 Q102 52 112 48" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".85"/>
      ${eye(84, 58, 3.8, E)}
      ${smile(90, 65, 2.2, E)}
    </g>`; },

  // Barnacle — volcano-cone shell of overlapping plates, dark aperture at the top, feathery cirri sweeping out
  barnacle: (c) => { const E = eyeInk(c), B = belly(c);
    const cirri = [[-24, -22], [-13, -30], [0, -34], [13, -30], [24, -22]].map(([dx, dy]) => {
      const ex = 60 + dx, ey = 44 + dy, cx = 60 + dx * 0.45, cy = 44 + dy * 0.6;
      const bx = dx > 0 ? -4 : 4;
      return `<path d="M60 45 Q${cx.toFixed(0)} ${cy.toFixed(0)} ${ex} ${ey}" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
        <path d="M${cx.toFixed(0)} ${cy.toFixed(0)} l${bx} -2 M${((cx + ex) / 2).toFixed(0)} ${((cy + ey) / 2).toFixed(0)} l${bx} -2 M${ex} ${ey} l${bx} -2" stroke="${c.line}" stroke-width="1" stroke-linecap="round" opacity=".8"/>`;
    }).join("");
    return `
    <g class="tail-wag">${cirri}</g>
    <g class="breathe">
      <path d="M26 104 L46 46 Q60 40 74 46 L94 104 Q60 112 26 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 108 L60 46 M46 104 Q52 74 50 47 M74 104 Q68 74 70 47 M35 104 Q45 74 48 55 M85 104 Q75 74 72 55" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".5"/>
      <path d="M30 100 Q60 108 90 100 Q60 96 30 100 Z" fill="${B}" opacity=".7"/>
      <ellipse cx="60" cy="46" rx="15" ry="6" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="60" cy="46" rx="9" ry="3.4" fill="${deepen(c.body, 0.45)}"/>
    </g>
    <g class="head-tilt">
      ${eye(51, 76, 3.6, E)}${eye(69, 76, 3.6, E)}
      ${smile(60, 82, 3, E)}
    </g>`; },

  // Crayfish — slender freshwater lobster (faces LEFT): two forward pincers, long antennae, up-flipped tail fan
  crayfish: (c) => { const E = eyeInk(c), B = belly(c);
    const legs = Array.from({ length: 3 }, (_, i) => `<path d="M${54 + i * 9} 72 q-2 9 -6 13" stroke="${c.line}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`).join("");
    const claw = (y) => `
      <path d="M42 ${y} Q28 ${y - 4} 20 ${y}" fill="none" stroke="${c.line}" stroke-width="5.5" stroke-linecap="round"/>
      <path d="M42 ${y} Q28 ${y - 4} 20 ${y}" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/>
      <path d="M24 ${y - 10} Q8 ${y - 12} 8 ${y} Q10 ${y + 8} 20 ${y + 6} Q12 ${y + 2} 22 ${y} Q12 ${y - 3} 24 ${y - 5} Q28 ${y - 8} 24 ${y - 10} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`;
    return `
    <g class="tail-wag">
      <path d="M84 62 Q100 46 110 50 Q100 58 106 62 Q100 66 110 74 Q100 78 84 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
      <path d="M86 62 L106 54 M86 62 L108 62 M86 62 L106 70" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".6"/>
      ${legs}${legs.replace(/72 q-2 9 -6 13/g, "52 q-2 -9 -6 -13")}
    </g>
    <g class="breathe">
      <path d="M34 62 Q40 50 66 50 Q86 50 90 62 Q86 74 66 74 Q40 74 34 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${[64, 72, 80, 87].map((x) => `<path d="M${x} 51 q3 11 0 22" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".6"/>`).join("")}
      <path d="M42 68 q24 6 46 0 q-24 4 -46 0 Z" fill="${B}" opacity=".7"/>
    </g>
    ${claw(66)}${claw(58)}
    <g class="head-tilt">
      <path d="M40 55 Q22 42 9 32 M40 59 Q24 50 10 43" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M34 51 L27 44" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(41, 55, 2.8, E)}
    </g>`; },

  // Prawn — big arch-backed shrimp, long saw-toothed rostrum, many feathery legs, broad tail fan, whip antennae
  prawn: (c) => { const E = eyeInk(c), B = belly(c);
    const legs = Array.from({ length: 6 }, (_, i) => `<path d="M${40 + i * 7} 70 q-1 8 -4 12 M${42 + i * 7} 70 q2 8 1 12" stroke="${c.line}" stroke-width="1.2" fill="none" stroke-linecap="round" opacity=".85"/>`).join("");
    return `
    <g class="tail-wag">
      <path d="M38 62 Q22 48 10 50 Q20 56 14 62 Q20 68 10 76 Q22 78 38 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
      <path d="M36 62 L14 53 M36 62 L12 62 M36 62 L14 73" stroke="${c.line}" stroke-width="1.1" opacity=".55"/>
    </g>
    <g class="tail-wag">${legs}</g>
    <g class="breathe">
      <path d="M32 63 Q42 47 62 47 Q82 48 90 61 Q88 71 76 73 Q56 77 38 73 Q26 71 32 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 71 Q60 76 80 70 Q60 77 40 71 Z" fill="${B}" opacity=".8"/>
      ${[46, 54, 62, 70, 78].map((x) => `<path d="M${x} 50 q-3 11 0 22" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".5"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M84 54 L108 43 L102 48 L109 49 Q94 54 84 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      <path d="M88 51 l3 -2 M94 48 l3 -2 M100 45 l3 -2" stroke="${c.line}" stroke-width="0.9" stroke-linecap="round" opacity=".7"/>
      <path d="M84 60 Q100 68 112 64 M84 63 Q98 74 108 79" fill="none" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round" opacity=".8"/>
      ${eye(80, 58, 3.4, E)}
      ${smile(86, 64, 2, E)}
    </g>`; },

  // Mantis Shrimp — armored segmented body, colorful banding, a folded raptorial striking club, stalked swivel eyes
  mantisshrimp: (c) => { const E = eyeInk(c), B = belly(c), T = tint(c.body, 0.4), D = deepen(c.body, 0.22);
    return `
    <g class="tail-wag">
      <path d="M32 62 L16 48 Q22 62 16 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M30 62 L18 52 M30 62 L14 62 M30 62 L18 72" stroke="${c.line}" stroke-width="1.1" opacity=".6"/>
    </g>
    <g class="tail-wag">
      <path d="M76 68 Q84 76 82 84 Q86 82 90 86 Q88 90 82 90 Q74 90 72 80 Q71 72 76 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 74 q3 3 6 2 M77 79 q3 3 6 2" stroke="${c.line}" stroke-width="1" fill="none" opacity=".6"/>
    </g>
    <g class="breathe">
      <path d="M28 62 Q30 51 48 50 Q72 48 86 53 Q93 56 93 62 Q93 68 86 71 Q72 76 48 74 Q30 73 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[42, 52, 62, 72].map((x, i) => `<path d="M${x} 51 q4 11 0 22" stroke="${i % 2 ? c.shade : D}" stroke-width="3.4" fill="none" opacity=".65" stroke-linecap="round"/>`).join("")}
      <path d="M40 70 Q62 76 84 70 Q62 74 40 70 Z" fill="${B}" opacity=".8"/>
    </g>
    <g class="head-tilt">
      <path d="M88 53 Q94 44 90 40 M92 55 Q100 46 96 42" stroke="${c.line}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <ellipse cx="89" cy="39" rx="3.4" ry="4" fill="${T}" stroke="${c.line}" stroke-width="1.6"/><ellipse cx="97" cy="41" rx="3.4" ry="4" fill="${T}" stroke="${c.line}" stroke-width="1.6"/>
      ${eye(89, 39, 1.7, INK)}${eye(97, 41, 1.7, INK)}
      ${smile(90, 60, 2.4, E)}
    </g>`; },

  // Horseshoe Crab — top-down: big helmet dome, spined mid-plate, long rigid spike tail (telson), twin dome eyes
  horseshoecrab: (c) => { const E = eyeInk(c), B = belly(c);
    const spines = [46, 54, 62, 70].flatMap((y) => [`<path d="M40 ${y} l-6 -2 l4 4 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`]).join("");
    return `
    <g class="tail-wag">
      <path d="M40 62 L6 54 L6 58 L38 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M52 34 Q88 34 100 62 Q88 90 52 90 Q40 90 40 74 L36 74 L38 66 L34 62 L38 58 L36 50 L40 50 Q40 34 52 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M56 36 Q84 40 92 62 Q84 84 56 88 Q48 62 56 36 Z" fill="${c.shade}" opacity=".4"/>
      <path d="M64 34 Q66 62 64 90" stroke="${c.line}" stroke-width="1.4" fill="none" opacity=".5"/>
      ${spines}
      <path d="M52 46 Q60 42 68 46 M52 78 Q60 82 68 78" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".45"/>
    </g>
    <g class="head-tilt">
      ${eye(74, 54, 3, E)}${eye(74, 70, 3, E)}
      ${smile(88, 62, 2.6, E)}
    </g>`; },

  // Spider Crab — small round body, TWO tiny claws, eight very long spindly kneed legs radiating out
  spidercrab: (c) => { const E = eyeInk(c), B = belly(c);
    const leg = (y, kx, ky, fx, fy) => tube(`M56 ${y} Q${kx} ${ky} ${fx} ${fy}`, c.body, c.line, 3);
    const legs = [
      leg(56, 40, 40, 20, 34), leg(60, 36, 54, 12, 54),
      leg(64, 38, 68, 16, 78), leg(68, 44, 78, 26, 96),
    ].join("");
    const claw = (y) => `${tube(`M56 ${y} Q46 ${y - 6} 40 ${y - 10}`, c.body, c.line, 3)}<path d="M40 ${y - 10} q-6 -3 -8 -8 q6 1 8 3 q-4 -4 -2 -8 q4 4 4 9 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`;
    return `
    <g class="tail-wag">${legs}${mirror(legs)}</g>
    <g class="tail-wag">${claw(58)}${mirror(claw(58))}</g>
    <g class="breathe">
      <path d="M46 62 Q46 46 60 44 Q74 46 76 62 Q76 76 60 78 Q46 76 46 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M60 44 l-3 -8 l3 3 l3 -3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="11" ry="7" fill="${B}" opacity=".75"/>
    </g>
    <g class="head-tilt">
      ${eyes(54, 66, 58, 3, E)}
      ${smile(60, 64, 3, E)}
    </g>`; },

  // King Crab — robust spiny carapace, thick spiked legs, one oversized pincer, knobbly armor
  kingcrab: (c) => { const E = eyeInk(c), B = belly(c);
    const spikeLeg = (y, kx, ky, fx, fy) => `${tube(`M52 ${y} Q${kx} ${ky} ${fx} ${fy}`, c.body, c.line, 5)}<path d="M${kx - 2} ${ky - 4} l2 -4 l3 3 Z M${(kx + fx) / 2 - 2} ${(ky + fy) / 2 - 3} l2 -4 l3 3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`;
    const legs = [spikeLeg(58, 34, 52, 16, 58), spikeLeg(64, 32, 68, 14, 80), spikeLeg(70, 40, 82, 26, 98)].join("");
    const bigClaw = `
      ${tube("M72 62 Q86 60 94 62", c.body, c.line, 6)}
      <path d="M92 48 Q112 48 112 64 Q110 74 96 72 Q106 66 94 63 Q106 60 94 55 Q88 51 92 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M99 54 l4 1 M99 60 l5 1 M99 66 l4 1" stroke="${c.line}" stroke-width="1" opacity=".6"/>`;
    const smallClaw = `${tube("M70 72 Q80 78 86 84", c.body, c.line, 5)}<path d="M86 84 q6 2 8 8 q-6 -1 -9 -4 q4 5 1 9 q-4 -4 -4 -10 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`;
    const carapace = Array.from({ length: 9 }, (_, i) => { const a = (-90 + i * 40) * Math.PI / 180; const x1 = 52 + 20 * Math.cos(a), y1 = 62 + 18 * Math.sin(a), x2 = 52 + 27 * Math.cos(a), y2 = 62 + 25 * Math.sin(a); return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)} l3 3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`; }).join("");
    return `
    <g class="tail-wag">${legs}${mirror(legs)}${bigClaw}${smallClaw}</g>
    <g class="tail-wag">${legs.replace(/M52 58/g, "M52 60").replace(/16 58/g, "16 56")}</g>
    <g class="breathe">
      ${carapace}
      <path d="M30 62 Q30 44 52 44 Q76 44 76 62 Q76 78 52 80 Q30 78 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 68 q14 6 30 0" stroke="${c.shade}" stroke-width="1.8" fill="none" opacity=".6"/>
      ${[[44, 56], [56, 54], [50, 66], [62, 64]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.2" fill="${c.shade}"/>`).join("")}
      <ellipse cx="52" cy="72" rx="14" ry="5" fill="${B}" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M46 46 L44 38 M58 46 L60 38" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${eyes(46, 58, 40, 2.8, E)}
      ${smile(52, 52, 3, E)}
    </g>`; },

  // Coconut Crab — massive robust body, ONE enormous crushing pincer on each side, thick legs, stalked eyes
  coconutcrab: (c) => { const E = eyeInk(c), B = belly(c);
    const legs = Array.from({ length: 3 }, (_, i) => tube(`M50 ${66 + i * 5} Q34 ${76 + i * 4} 22 ${84 + i * 4}`, c.body, c.line, 5)).join("");
    const claw = `
      ${tube("M68 62 Q84 60 92 62", c.body, c.line, 8)}
      <path d="M88 45 Q116 45 116 64 Q114 80 94 78 Q110 69 91 65 Q110 58 91 54 Q84 50 88 45 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M98 53 l8 1 M98 62 l9 1 M98 71 l8 1" stroke="${c.line}" stroke-width="1.1" opacity=".55"/>`;
    return `
    <g class="tail-wag">${legs}${mirror(legs)}</g>
    <g class="tail-wag">${claw}${mirror(claw)}</g>
    <g class="breathe">
      <path d="M30 62 Q30 42 60 42 Q90 42 90 62 Q90 80 60 82 Q30 80 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 50 Q60 44 80 50 Q60 54 50 56 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M42 70 q18 8 36 0" stroke="${c.shade}" stroke-width="2" fill="none" opacity=".6"/>
      <ellipse cx="60" cy="74" rx="17" ry="6" fill="${B}" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M50 46 L48 36 M70 46 L72 36" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <circle cx="48" cy="35" r="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/><circle cx="72" cy="35" r="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>
      ${eye(48, 35, 1.9, INK)}${eye(72, 35, 1.9, INK)}
      ${smile(60, 54, 3.4, E)}
    </g>`; },

  // Clam — two hinged fan valves slightly agape, growth rings, a pale foot peeking, cute eyes at the gap
  clam: (c) => { const E = eyeInk(c), B = belly(c);
    return `
    <g class="breathe">
      <path d="M22 58 Q22 34 60 34 Q98 34 98 58 Q80 52 60 52 Q40 52 22 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M22 66 Q22 92 60 92 Q98 92 98 66 Q80 74 60 74 Q40 74 22 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M30 56 Q60 40 90 56" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".55"/>
      <path d="M38 53 Q60 42 82 53" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".45"/>
      <path d="M30 68 Q60 84 90 68" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".55"/>
      <path d="M38 71 Q60 82 82 71" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".45"/>
      <path d="M52 72 Q52 86 60 86 Q68 86 68 72 Z" fill="${B}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M28 62 Q60 56 92 62 Q60 66 28 62 Z" fill="${deepen(c.body, 0.35)}" opacity=".7"/>
      ${eyes(50, 70, 60, 3.2, E)}
    </g>`; },

  // Oyster — rough craggy shell hinged open, pale nacre lining, a glossy pearl nestled inside
  oyster: (c) => { const E = eyeInk(c), B = belly(c);
    return `
    <g class="breathe">
      <path d="M18 76 Q14 62 30 58 Q46 55 60 56 Q80 55 98 62 Q108 66 100 78 Q88 86 60 88 Q34 88 18 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M22 72 Q40 70 40 76 Q52 70 54 76 Q66 70 70 76 Q82 70 88 76" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".55"/>
      <path d="M26 72 Q60 62 96 72 Q60 82 26 72 Z" fill="${B}"/>
      <circle cx="60" cy="72" r="7" fill="${PEARL}" stroke="${c.line}" stroke-width="1.6"/>
      <circle cx="57.5" cy="69.5" r="2.4" fill="#fff"/>
    </g>
    <g class="tail-wag">
      <path d="M20 60 Q14 40 40 34 Q64 30 88 38 Q106 44 100 60 Q80 50 58 50 Q36 50 20 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M30 52 Q40 48 40 54 Q52 46 56 52 Q68 46 74 52 Q84 48 90 54" stroke="${c.line}" stroke-width="1.4" fill="none" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${eye(40, 78, 2.6, E)}${eye(80, 78, 2.6, E)}
      ${smile(60, 82, 2.4, E)}
    </g>`; },

  // Scallop — classic fan shell: apex hinge with twin ears, scalloped top rim, radiating ribs, a row of tiny eyes
  scallop: (c) => { const E = eyeInk(c), B = belly(c);
    const N = 8, x0 = 26, x1 = 94, yT = 52, bw = (x1 - x0) / N;
    const bumps = Array.from({ length: N }, () => `q${(bw / 2).toFixed(1)} -7 ${bw.toFixed(1)} 0`).join(" ");
    const ribs = Array.from({ length: N + 1 }, (_, i) => `<path d="M60 86 L${(x0 + i * bw).toFixed(1)} ${yT + 3}" stroke="${c.shade}" stroke-width="1.7" opacity=".5"/>`).join("");
    const dots = Array.from({ length: 9 }, (_, i) => `<circle cx="${(30 + i * 7.5).toFixed(1)}" cy="57" r="1.6" fill="${INK}"/>`).join("");
    const tent = Array.from({ length: 5 }, (_, i) => `<path d="M${34 + i * 12} 55 q-1 -6 1 -9" stroke="${c.line}" stroke-width="1.3" fill="none" stroke-linecap="round" opacity=".7"/>`).join("");
    return `
    <g class="breathe">
      <path d="M58 87 L45 82 L51 91 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M62 87 L75 82 L69 91 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M60 88 L${x0} ${yT} ${bumps} L60 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${ribs}
      <path d="M60 88 Q50 72 48 58 Q60 62 72 58 Q70 72 60 88 Z" fill="${B}" opacity=".4"/>
    </g>
    <g class="head-tilt">
      ${tent}
      ${dots}
      ${smile(60, 72, 3.2, E)}
    </g>`; },

  // Conch — big knobbed spiral shell, flared pink aperture lip, pointed canal, a shy snail peeking with eyestalks
  conch: (c) => { const E = eyeInk(c), B = belly(c);
    const knobs = [[62, 30], [78, 36], [88, 50], [90, 66]].map(([x, y]) => `<path d="M${x} ${y} l-5 -6 l8 1 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("");
    return `
    <g class="breathe">
      <path d="M44 94 Q30 80 34 58 Q40 34 62 30 Q86 28 92 52 Q98 74 82 90 Q72 100 60 98 Q68 88 60 84 Q52 90 44 94 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${knobs}
      <path d="M56 40 Q78 42 82 62 Q84 78 74 88" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".5"/>
      <path d="M50 52 Q66 54 70 70" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".45"/>
      <path d="M46 90 Q38 76 42 60 Q46 46 60 44 Q72 46 72 62 Q72 78 60 84 Q52 88 46 90 Z" fill="${B}" opacity=".85"/>
    </g>
    <g class="head-tilt">
      <path d="M52 78 Q46 92 52 96 M60 80 Q58 94 64 96" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
      ${eye(52, 96, 2.4, INK)}${eye(64, 96, 2.4, INK)}
      ${eye(58, 66, 3, E)}
      ${smile(58, 72, 2.6, E)}
    </g>`; },

  // Cone Snail — smooth tapering cone shell with the classic triangular tent-net pattern, siphon + eyestalks up top
  conesnail: (c) => { const E = eyeInk(c), B = belly(c);
    const net = [[44, 50], [56, 50], [68, 50], [46, 60], [58, 60], [68, 60], [50, 70], [62, 70], [55, 80]].map(([x, y]) => `<path d="M${x} ${y} l4 6 l4 -6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="0.8" stroke-linejoin="round" opacity=".8"/>`).join("");
    return `
    <g class="breathe">
      <path d="M34 44 Q60 30 86 44 Q80 60 72 84 Q66 100 60 102 Q54 100 48 84 Q40 60 34 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M34 44 Q60 54 86 44" stroke="${c.line}" stroke-width="1.6" fill="none" opacity=".5"/>
      <path d="M38 42 Q60 30 82 42 Q60 48 38 42 Z" fill="${tint(c.body, 0.3)}"/>
      ${net}
      <path d="M46 84 Q60 92 74 84" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M50 38 Q46 26 50 22 M58 37 Q58 24 62 20" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
      ${eye(50, 22, 2.2, INK)}${eye(62, 20, 2.2, INK)}
      <path d="M64 40 Q76 34 84 36" stroke="${c.line}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      ${eye(56, 48, 2.8, E)}
      ${smile(56, 53, 2.4, E)}
    </g>`; },

  // Sea Slug — smooth soft body ringed by a ruffled mantle skirt, two rhinophore horns, a feathery gill rosette
  seaslug: (c) => { const E = eyeInk(c), B = belly(c), T = tint(c.body, 0.4);
    const skirt = Array.from({ length: 9 }, (_, i) => `M${24 + i * 8} 73 q4 8 8 0`).join(" ");
    return `
    <g class="tail-wag">
      <path d="${skirt} L88 73 Q90 80 80 80 Q52 84 40 82 Q26 82 24 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M22 66 Q26 52 46 50 Q70 48 86 54 Q94 57 92 65 Q90 72 80 73 Q56 76 40 75 Q26 74 22 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M28 60 Q56 52 86 60 Q56 66 28 60 Z" fill="${T}" opacity=".8"/>
      ${[42, 52, 62, 72].map((x) => `<path d="M${x} 53 q2 8 0 15" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".45"/>`).join("")}
    </g>
    <g class="tail-wag">
      ${pom(34, 51, 7, T, c.line, 8, 1.8)}
      <path d="M34 51 l-4 -4 M34 51 l4 -4 M34 51 l0 -6 M34 51 l-5 1 M34 51 l5 1" stroke="${c.line}" stroke-width="1" stroke-linecap="round" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M82 56 Q84 44 80 36 M90 58 Q94 44 90 38" stroke="${c.line}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
      <path d="M79 37 q1 -4 4 -4 M89 39 q1 -4 4 -4" stroke="${c.shade}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
      ${eye(84, 60, 2.8, E)}
      ${smile(88, 65, 2.2, E)}
    </g>`; },

  // Nudibranch — soft body BRISTLING with a forest of club-tipped cerata on its back, two rhinophores, ruffled
  nudibranch: (c) => { const E = eyeInk(c), B = belly(c), T = tint(c.body, 0.45), D = deepen(c.body, 0.15);
    const cerata = Array.from({ length: 11 }, (_, i) => { const x = 30 + i * 5.5, h = 12 + (i % 3) * 4; return `<path d="M${x} 58 Q${x - 2} ${58 - h} ${x} ${58 - h - 2}" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/><path d="M${x} 58 Q${x - 2} ${58 - h} ${x} ${58 - h - 2}" fill="none" stroke="${i % 2 ? T : c.shade}" stroke-width="1.8" stroke-linecap="round"/><circle cx="${x}" cy="${58 - h - 2}" r="2.4" fill="${i % 2 ? T : c.shade}" stroke="${c.line}" stroke-width="1"/>`; }).join("");
    return `
    <g class="tail-wag">${cerata}</g>
    <g class="breathe">
      <path d="M20 68 Q24 56 46 55 Q72 54 88 58 Q96 61 93 68 Q90 74 78 75 Q54 78 38 77 Q24 76 20 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M28 71 Q56 78 86 70 Q56 74 28 71 Z" fill="${B}" opacity=".8"/>
      <path d="M26 66 Q56 60 88 65" stroke="${D}" stroke-width="2" fill="none" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M84 54 Q86 44 82 40 M92 56 Q96 46 92 42" stroke="${c.line}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
      <path d="M81 41 q1 -4 4 -3 M91 43 q1 -4 4 -3" stroke="${c.shade}" stroke-width="2.4" fill="none" stroke-linecap="round"/>
      ${eye(85, 64, 2.8, E)}
      ${smile(89, 69, 2.2, E)}
    </g>`; },

  // Chiton — oval top-down mollusk armored by eight overlapping shell plates, ringed by a ticked girdle
  chiton: (c) => { const E = eyeInk(c), B = belly(c);
    const plates = Array.from({ length: 8 }, (_, i) => { const x = 28 + i * 7.5; return `<path d="M${x} 46 Q${x + 4} 62 ${x} 78" stroke="${c.line}" stroke-width="1.6" fill="none" opacity=".7"/>`; }).join("");
    const ticks = Array.from({ length: 22 }, (_, i) => { const a = i / 22 * 2 * Math.PI; const x1 = 60 + 32 * Math.cos(a), y1 = 62 + 20 * Math.sin(a), x2 = 60 + 36 * Math.cos(a), y2 = 62 + 23 * Math.sin(a); return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${c.line}" stroke-width="1" opacity=".5"/>`; }).join("");
    return `
    <g class="breathe">
      <ellipse cx="60" cy="62" rx="35" ry="22" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      ${ticks}
      <path d="M28 62 Q28 46 60 46 Q92 46 92 62 Q92 78 60 78 Q28 78 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${plates}
      <path d="M32 62 Q60 68 88 62" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".4"/>
      <ellipse cx="60" cy="58" rx="20" ry="6" fill="${B}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${eyes(80, 88, 60, 2.6, E)}
      ${smile(84, 65, 2.4, E)}
    </g>`; },

  // Abalone — flat ear-shaped shell with a spiral whorl at one end and the signature row of respiratory holes
  abalone: (c) => { const E = eyeInk(c), B = belly(c);
    const holes = Array.from({ length: 5 }, (_, i) => { const t = i / 4; const x = 46 + t * 42, y = 44 + t * 4 - Math.sin(t * Math.PI) * 4; return `<ellipse cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" rx="2.6" ry="2" fill="${INK}" opacity=".8"/>`; }).join("");
    return `
    <g class="breathe">
      <path d="M22 68 Q18 46 46 40 Q82 35 100 54 Q108 66 94 80 Q64 92 40 86 Q26 82 22 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 74 Q30 66 34 56 Q40 48 50 50 Q58 52 56 62 Q54 70 46 72 Q40 74 40 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M44 62 Q46 56 52 56" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".6"/>
      <path d="M56 78 Q76 82 94 72" stroke="${c.shade}" stroke-width="2" fill="none" opacity=".5"/>
      <path d="M60 84 Q80 84 96 72 Q86 82 68 84 Z" fill="${B}" opacity=".6"/>
      ${holes}
    </g>
    <g class="head-tilt">
      ${eye(84, 66, 2.8, E)}
      ${smile(88, 71, 2.4, E)}
    </g>`; },

  // Limpet — simple low cone-hat shell with radiating ridges, sitting on a soft foot; eyes peeking under the rim
  limpet: (c) => { const E = eyeInk(c), B = belly(c);
    const ridges = Array.from({ length: 11 }, (_, i) => { const x = 20 + i * 8; return `<path d="M62 40 L${x} 80" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>`; }).join("");
    return `
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="40" ry="9" fill="${B}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M20 82 Q28 44 60 40 Q94 44 100 82 Q60 92 20 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${ridges}
      <path d="M60 40 Q48 46 44 66 Q42 76 48 82" fill="${c.shade}" opacity=".3" stroke="none"/>
      <ellipse cx="60" cy="42" rx="4" ry="2.4" fill="${c.shade}"/>
    </g>
    <g class="head-tilt">
      ${eyes(52, 68, 82, 2.8, E)}
      ${smile(60, 86, 2.6, E)}
    </g>`; },

  // Slipper Lobster — flat squat body, segmented armored tail, and the signature broad shovel-plate antennae
  slipperlobster: (c) => { const E = eyeInk(c), B = belly(c);
    const legs = Array.from({ length: 3 }, (_, i) => `<path d="M${44 + i * 9} 72 q-1 8 -4 12" stroke="${c.line}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`).join("");
    return `
    <g class="tail-wag">
      <path d="M30 62 Q16 50 8 52 Q16 60 10 62 Q16 64 8 72 Q16 74 30 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 52 q-2 10 0 20 M32 54 q-2 8 0 16" stroke="${c.line}" stroke-width="1.4" fill="none" opacity=".6"/>
      ${legs}${legs.replace(/72 q-1 8 -4 12/g, "52 q-1 -8 -4 -12")}
    </g>
    <g class="breathe">
      <path d="M28 62 Q30 50 50 49 Q74 48 86 53 Q92 56 92 62 Q92 68 86 71 Q74 76 50 75 Q30 74 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[46, 56, 66].map((x) => `<path d="M${x} 51 q3 11 0 22" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".55"/>`).join("")}
      <path d="M40 69 q26 6 48 0 q-26 4 -48 0 Z" fill="${B}" opacity=".7"/>
    </g>
    <g class="tail-wag">
      <path d="M84 56 Q104 50 110 58 Q104 64 90 63 Q84 60 84 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 68 Q104 62 110 70 Q104 76 90 73 Q84 72 84 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M90 57 l14 1 M90 69 l14 1" stroke="${c.line}" stroke-width="1" opacity=".55"/>
    </g>
    <g class="head-tilt">
      ${eyes(80, 88, 62, 2.6, E)}
      ${smile(84, 66, 2.4, E)}
    </g>`; },
};

export const ROSTER_CRUSTACEANS = [
  { n: "Krill",           e: "🦐", tier: 1, float: true },
  { n: "Barnacle",        e: "🐚", tier: 1, float: true },
  { n: "Crayfish",        e: "🦞", tier: 2, float: true },
  { n: "Prawn",           e: "🦐", tier: 1, float: true },
  { n: "Mantis Shrimp",   e: "🦐", tier: 3, float: true },
  { n: "Horseshoe Crab",  e: "🦀", tier: 2, float: true },
  { n: "Spider Crab",     e: "🦀", tier: 2, float: true },
  { n: "King Crab",       e: "🦀", tier: 3, float: true },
  { n: "Coconut Crab",    e: "🦀", tier: 3, float: true },
  { n: "Clam",            e: "🦪", tier: 1, float: true },
  { n: "Oyster",          e: "🦪", tier: 1, float: true },
  { n: "Scallop",         e: "🐚", tier: 1, float: true },
  { n: "Conch",           e: "🐚", tier: 2, float: true },
  { n: "Cone Snail",      e: "🐚", tier: 2, float: true },
  { n: "Sea Slug",        e: "🐌", tier: 2, float: true },
  { n: "Nudibranch",      e: "🐌", tier: 2, float: true },
  { n: "Chiton",          e: "🐚", tier: 1, float: true },
  { n: "Abalone",         e: "🐚", tier: 1, float: true },
  { n: "Limpet",          e: "🐚", tier: 1, float: true },
  { n: "Slipper Lobster", e: "🦞", tier: 2, float: true },
];
