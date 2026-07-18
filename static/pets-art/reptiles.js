// pets-art/reptiles.js — BESPOKE hand-drawn SVG art for the REPTILES & AMPHIBIANS batch (NADO Pets).
// Each value: (c, v) => "<svg inner markup>" for viewBox 0 0 120 120, animal centered ~ (60,62), within
// x,y ∈ [8,112]. Colours come from the coat object c (c.body / c.shade / c.line); the palette is applied
// at runtime, so real colours are NOT hardcoded (teeth/claws/tongue may use fixed tones).
// Animate: torso <g class="breathe">, head <g class="head-tilt">, tails/crests/hoods <g class="tail-wag">.
// Aquatic (sea snake, axolotl) => float:true in the roster, bodies oriented horizontally.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

// fixed accents that stay constant across coats
const TOOTH = "#fbfbf6", TONGUE = "#e0565b", CLAW = "#e9e4d8";

export const ART_REPTILES = {
  // ── Green Iguana — long profile body, saw-tooth dorsal crest, hanging round dewlap, curling tail
  greeniguana: (c) => {
    const E = eyeInk(c);
    const crest = Array.from({ length: 10 }, (_, i) => {
      const x = 28 + i * 6, y = 56 - Math.sin(i / 9 * Math.PI) * 8, h = 6 + (i < 5 ? i : 9 - i) * 0.9;
      return `<path d="M${x} ${y} l2.4 -${h.toFixed(1)} l2.4 ${h.toFixed(1)} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`;
    }).join("");
    const leg = (x) => `<path d="M${x} 74 q-4 10 -10 12 q4 3 9 1" fill="none" stroke="${c.line}" stroke-width="5.6" stroke-linecap="round"/><path d="M${x} 74 q-4 10 -10 12 q4 3 9 1" fill="none" stroke="${c.body}" stroke-width="3.4" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">
      ${tube("M32 70 Q14 72 10 88 Q9 98 17 96", c.body, c.line, 8)}
      ${tube("M14 92 Q10 96 12 100", c.body, c.line, 4)}
    </g>
    <g class="breathe">
      ${leg(46)}${leg(74)}
      <ellipse cx="58" cy="66" rx="29" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      ${crest}
      <path d="M40 66 q18 8 36 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>
      <path d="M50 60 q6 4 12 0 M64 62 q6 4 12 0" fill="none" stroke="${c.line}" stroke-width="1" opacity=".45"/>
    </g>
    <g class="head-tilt">
      <path d="M82 58 Q100 56 100 66 Q100 76 86 76 Q78 70 82 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M88 74 Q84 92 92 96 Q98 90 96 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="90" cy="72" r="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>
      ${eye(90, 64, 2.8, E)}
      ${smile(98, 68, 2.4, E)}
    </g>`;
  },

  // ── Chameleon — tall casque helmet, cone turret eye, saw-back crest, gripping feet, tight spiral tail
  chameleon: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M40 84 Q28 96 34 104 Q42 110 46 102 Q48 96 42 96", c.body, c.line, 7)}
    </g>
    <g class="breathe">
      <path d="M46 60 Q30 82 40 90 M62 62 Q78 84 70 92" fill="none" stroke="${c.line}" stroke-width="5.6" stroke-linecap="round"/>
      <path d="M46 60 Q30 82 40 90 M62 62 Q78 84 70 92" fill="none" stroke="${c.body}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M36 88 l-6 2 l4 4 M72 90 l6 2 l-4 4" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M40 62 Q40 40 60 40 Q84 42 84 66 Q84 82 60 82 Q40 82 40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${Array.from({ length: 7 }, (_, i) => `<path d="M${44 + i * 6} ${40 + (i - 3) * (i - 3) * 0.9} l2 -5 l2 5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.1" stroke-linejoin="round"/>`).join("")}
      <path d="M50 66 q10 8 22 2" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>
      <ellipse cx="58" cy="70" rx="8" ry="5" fill="${c.shade}" opacity=".4"/>
    </g>
    <g class="head-tilt">
      <path d="M74 38 Q66 20 84 24 Q98 28 96 44 Q90 40 82 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 44 Q94 40 100 50 Q94 58 82 56 Q74 50 78 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M96 52 q6 0 9 -2 M104 50 l3 3 M104 50 l3 -3" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="82" cy="49" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="82" cy="49" r="3.6" fill="${c.shade}"/>
      <circle cx="83" cy="49" r="1.7" fill="${INK}"/>
      <circle cx="84.2" cy="47.5" r="0.7" fill="#fff"/>
    </g>`;
  },

  // ── Gecko — top-down splay, four legs with fat round sticky toe-pads, big lidless eyes, curled tail
  gecko: (c) => {
    const E = eyeInk(c);
    const foot = (x, y, dx, dy) => {
      const fx = x + dx, fy = y + dy;
      const toes = Array.from({ length: 4 }, (_, i) => `<circle cx="${(fx + (i - 1.5) * 3.4).toFixed(1)}" cy="${(fy + Math.abs(i - 1.5) * 1.2).toFixed(1)}" r="2.4" fill="${c.body}" stroke="${c.line}" stroke-width="1.3"/>`).join("");
      return `<path d="M${x} ${y} L${fx} ${fy}" stroke="${c.line}" stroke-width="5.4" stroke-linecap="round"/><path d="M${x} ${y} L${fx} ${fy}" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/>${toes}`;
    };
    return `
    <g class="tail-wag">${tube("M60 88 Q52 102 60 108 Q70 104 66 92", c.body, c.line, 8)}</g>
    <g class="breathe">
      ${foot(46, 58, -14, -10)}${foot(74, 58, 14, -10)}${foot(46, 80, -14, 10)}${foot(74, 80, 14, 10)}
      <ellipse cx="60" cy="70" rx="19" ry="26" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      ${[[54, 62], [66, 62], [60, 72], [52, 80], [68, 80]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.4" fill="${c.shade}" opacity=".7"/>`).join("")}
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="42" rx="16" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <circle cx="50" cy="40" r="6.5" fill="#fff" stroke="${c.line}" stroke-width="2"/>
      <circle cx="70" cy="40" r="6.5" fill="#fff" stroke="${c.line}" stroke-width="2"/>
      <ellipse cx="51" cy="41" rx="1.8" ry="3.2" fill="${INK}"/>
      <ellipse cx="69" cy="41" rx="1.8" ry="3.2" fill="${INK}"/>
      ${smile(60, 47, 3.6, INK)}
    </g>`;
  },

  // ── Komodo Dragon — hefty grey monitor, muscular legs, thick tail, flicking forked tongue, beaded hide
  komododragon: (c) => {
    const E = eyeInk(c);
    const beads = [[40, 66], [52, 60], [64, 62], [72, 68], [48, 72], [60, 72]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.8" fill="${c.shade}" opacity=".75"/>`).join("");
    const leg = (x, fwd) => `<path d="M${x} 76 q${fwd ? 6 : -6} 12 ${fwd ? 2 : -2} 20" fill="none" stroke="${c.line}" stroke-width="7.4" stroke-linecap="round"/><path d="M${x} 76 q${fwd ? 6 : -6} 12 ${fwd ? 2 : -2} 20" fill="none" stroke="${c.body}" stroke-width="4.8" stroke-linecap="round"/><path d="M${x + (fwd ? 2 : -2)} 96 l-4 4 m4 -4 l0 5 m0 -5 l4 4" stroke="${CLAW}" stroke-width="1.6" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">${tube("M34 70 Q14 74 8 92 Q6 100 14 100", c.body, c.line, 11)}</g>
    <g class="breathe">
      ${leg(44, false)}${leg(74, true)}
      <path d="M32 68 Q34 52 62 52 Q88 52 92 66 Q88 82 60 82 Q34 82 32 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${beads}
      <path d="M38 74 q24 8 48 0" fill="none" stroke="${c.shade}" stroke-width="1.5" opacity=".55"/>
    </g>
    <g class="head-tilt">
      <path d="M80 52 Q104 50 110 62 Q104 72 84 72 Q74 64 80 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M92 66 q9 1 16 -1" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M108 65 q3 1 5 -2 M111 63 l3 3 M111 63 l3 -3" fill="none" stroke="${TONGUE}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(90, 58, 2.8, E)}
      <path d="M84 55 q6 -3 12 0" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
    </g>`;
  },

  // ── Crocodile — long narrow toothy snout (upper + lower fangs), armoured ridged back, eyes on top
  crocodile: (c) => {
    const E = eyeInk(c);
    const ridges = Array.from({ length: 7 }, (_, i) => `<path d="M${30 + i * 6} ${68 - Math.sin(i / 6 * Math.PI) * 5} l2.6 -5 l2.6 5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`).join("");
    const upTeeth = Array.from({ length: 6 }, (_, i) => `<path d="M${80 + i * 5} 70 l1.8 5 l1.8 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.7"/>`).join("");
    const loTeeth = Array.from({ length: 5 }, (_, i) => `<path d="M${83 + i * 5} 78 l1.8 -5 l1.8 5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.7"/>`).join("");
    return `
    <g class="tail-wag">${tube("M32 72 Q12 74 8 90 Q6 100 16 98 Q10 88 22 82", c.body, c.line, 9)}</g>
    <g class="breathe">
      ${["M40 80 q-6 12 -2 18", "M72 80 q6 12 2 18"].map((d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="6.6" stroke-linecap="round"/><path d="${d}" fill="none" stroke="${c.body}" stroke-width="4.2" stroke-linecap="round"/>`).join("")}
      <ellipse cx="56" cy="70" rx="28" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${ridges}
      <path d="M32 74 q24 6 48 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M74 62 Q112 60 112 70 Q110 74 96 74 L74 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M78 74 Q96 82 112 74" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      ${upTeeth}${loTeeth}
      <ellipse cx="80" cy="54" rx="6" ry="5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      ${eye(80, 53, 2.6, E)}
      <circle cx="106" cy="66" r="1.4" fill="${INK}"/>
    </g>`;
  },

  // ── Alligator — broad rounded U-snout, big goofy toothy grin (upper teeth), knobbly back, eyes on top
  alligator: (c) => {
    const E = eyeInk(c);
    const knobs = [[38, 66], [48, 62], [58, 62], [68, 64], [44, 72], [56, 72], [66, 72]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.2" fill="${c.shade}" stroke="${c.line}" stroke-width="0.8"/>`).join("");
    const teeth = Array.from({ length: 7 }, (_, i) => `<path d="M${80 + i * 4.5} 70 l1.7 4.5 l1.7 -4.5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.7"/>`).join("");
    return `
    <g class="tail-wag">${tube("M32 70 Q12 72 8 88 Q7 98 16 96", c.body, c.line, 10)}</g>
    <g class="breathe">
      ${["M42 80 q-6 12 -2 18", "M70 80 q6 12 2 18"].map((d) => `<path d="${d}" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/><path d="${d}" fill="none" stroke="${c.body}" stroke-width="4.4" stroke-linecap="round"/>`).join("")}
      <ellipse cx="54" cy="68" rx="27" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${knobs}
    </g>
    <g class="head-tilt">
      <path d="M72 58 Q104 56 108 68 Q106 78 84 78 Q72 74 72 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M76 70 Q94 76 106 68" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${teeth}
      <ellipse cx="80" cy="52" rx="6.5" ry="5.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/>
      <ellipse cx="92" cy="53" rx="5.5" ry="4.5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${eye(80, 51, 2.8, E)}${eye(92, 52, 2.4, E)}
    </g>`;
  },

  // ── Tortoise — high domed shell with hexagon scutes, stumpy elephantine legs, wrinkly wise head
  tortoise: (c) => {
    const E = eyeInk(c);
    const scutes = [[60, 44], [46, 54], [74, 54], [52, 66], [68, 66], [60, 60]].map(([x, y]) =>
      `<path d="M${x} ${y - 6} l6 4 l0 7 l-6 4 l-6 -4 l0 -7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("");
    const leg = (x) => `<path d="M${x} 78 q-3 12 0 16 q6 2 10 0 q2 -10 -1 -16 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M${x} 92 l3 3 m0 -3 l3 3" stroke="${CLAW}" stroke-width="1.4"/>`;
    return `
    <g class="tail-wag">${leg(30)}${leg(78)}</g>
    <g class="breathe">
      <path d="M30 76 Q30 34 60 34 Q90 34 90 76 Q60 88 30 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.7" stroke-linejoin="round"/>
      ${scutes}
      <path d="M32 74 Q60 84 88 74" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M84 66 Q104 62 106 74 Q106 84 92 84 Q82 80 84 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M90 78 q4 2 8 -1 M90 82 q4 2 8 -1" fill="none" stroke="${c.line}" stroke-width="0.9" opacity=".6"/>
      ${eye(96, 72, 2.6, E)}
      ${smile(102, 76, 2.4, E)}
    </g>`;
  },

  // ── Cobra — coiled base, rising S-neck, flared spectacled HOOD, forked tongue, alert stare
  cobra: (c) => {
    const E = eyeInk(c);
    return `
    <g class="breathe">
      ${tube("M40 100 Q22 100 26 86 Q32 74 60 74 Q88 74 94 86 Q98 100 78 100", c.body, c.line, 12)}
      <ellipse cx="60" cy="90" rx="26" ry="11" fill="${c.body}"/>
      <path d="M40 90 Q60 100 80 90" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".4"/>
      <path d="M50 88 Q46 64 60 52 Q74 64 70 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M56 86 q3 -16 0 -30 M64 86 q3 -16 0 -30" fill="none" stroke="${c.shade}" stroke-width="1.3" opacity=".45"/>
    </g>
    <g class="tail-wag">
      <path d="M60 32 Q30 36 38 62 Q60 74 82 62 Q90 36 60 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M52 48 Q60 56 68 48 Q66 42 60 42 Q54 42 52 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="34" rx="12" ry="9.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      <path d="M60 43 q0 7 0 10 M60 53 l-3.5 4 M60 53 l3.5 4" fill="none" stroke="${TONGUE}" stroke-width="1.8" stroke-linecap="round"/>
      ${eyes(54, 66, 32, 2.8, E)}
    </g>`;
  },

  // ── Python — thick heavy oval coil, blotched saddle pattern, blunt head resting on top, small eyes
  python: (c) => {
    const E = eyeInk(c);
    const blotch = [[60, 54], [34, 66], [86, 66], [46, 84], [74, 84], [60, 82]].map(([x, y]) =>
      `<ellipse cx="${x}" cy="${y}" rx="7.5" ry="6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3"/><ellipse cx="${x}" cy="${y}" rx="3.5" ry="2.6" fill="${c.body}" opacity=".5"/>`).join("");
    return `
    <g class="breathe">
      ${tube("M60 94 Q22 94 24 70 Q28 48 60 48 Q92 48 96 70 Q98 94 60 94", c.body, c.line, 20)}
      <ellipse cx="60" cy="71" rx="31" ry="20" fill="${c.body}"/>
      <path d="M30 64 Q60 80 90 64" fill="none" stroke="${c.shade}" stroke-width="1.5" opacity=".4"/>
      <path d="M32 80 Q60 92 88 80" fill="none" stroke="${c.shade}" stroke-width="1.5" opacity=".35"/>
      ${blotch}
    </g>
    <g class="head-tilt">
      <path d="M50 46 Q46 30 60 28 Q74 30 70 46 Q60 54 50 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M60 44 q0 6 0 9 M60 53 l-3 4 M60 53 l3 4" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(54, 66, 38, 2.6, E)}
      ${smile(60, 45, 3, E)}
    </g>`;
  },

  // ── Rattlesnake — tight coil with diamond pattern, raised striking head, forked tongue, segmented rattle
  rattlesnake: (c) => {
    const E = eyeInk(c);
    const diamonds = [[60, 84], [40, 80], [80, 80], [50, 68], [70, 68]].map(([x, y]) =>
      `<path d="M${x} ${y - 6} l6 6 l-6 6 l-6 -6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`).join("");
    const rattle = Array.from({ length: 4 }, (_, i) => `<path d="M${92 - i * 1} ${50 - i * 7} l6 0 l-1 6 l-4 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("");
    return `
    <g class="breathe">
      ${tube("M60 100 Q26 100 28 78 Q32 58 60 58 Q88 58 90 78 Q92 98 62 98", c.body, c.line, 16)}
      <ellipse cx="60" cy="80" rx="27" ry="15" fill="${c.body}"/>
      <path d="M34 74 Q60 90 86 74" fill="none" stroke="${c.shade}" stroke-width="1.5" opacity=".4"/>
      ${diamonds}
    </g>
    <g class="tail-wag">
      ${tube("M86 74 Q98 64 96 52", c.body, c.line, 6)}
      ${rattle}
    </g>
    <g class="head-tilt">
      ${tube("M62 60 Q48 48 46 34 Q45 26 56 24", c.body, c.line, 11)}
      <path d="M58 20 Q40 18 38 32 Q40 44 54 44 Q64 36 58 20 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M52 28 q-4 -3 -9 -2 M45 40 q-4 3 -9 2" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>
      <path d="M40 30 q-6 0 -11 -2 M29 28 l-4 3 M29 28 l-4 -3" fill="none" stroke="${TONGUE}" stroke-width="1.7" stroke-linecap="round"/>
      ${eye(50, 30, 2.6, E)}
    </g>`;
  },

  // ── Sea Snake — banded, flattened paddle tail, undulating body, tiny head; float:true (horizontal)
  seasnake: (c) => {
    const E = eyeInk(c);
    const cx = (t) => 18 + t * 82, cy = (t) => 62 - Math.sin(t * Math.PI * 2.2) * 13;
    const pts = Array.from({ length: 33 }, (_, i) => { const t = i / 32; return `${cx(t).toFixed(1)} ${cy(t).toFixed(1)}`; });
    const bodyD = "M" + pts.join(" L");
    const bands = Array.from({ length: 9 }, (_, i) => {
      const t = 0.06 + i * 0.108, x = cx(t), y = cy(t);
      const dx = 82, dy = -Math.cos(t * Math.PI * 2.2) * 13 * Math.PI * 2.2, L = Math.hypot(dx, dy);
      const px = (-dy / L) * 6, py = (dx / L) * 6;
      return `<path d="M${(x - px).toFixed(1)} ${(y - py).toFixed(1)} L${(x + px).toFixed(1)} ${(y + py).toFixed(1)}" stroke="${c.shade}" stroke-width="4.5" stroke-linecap="round" opacity=".85"/>`;
    }).join("");
    return `
    <g class="tail-wag">
      <path d="M18 62 Q6 54 8 62 Q6 70 18 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${tube(bodyD, c.body, c.line, 13)}
      ${bands}
    </g>
    <g class="head-tilt">
      <path d="M92 54 Q108 52 108 60 Q108 68 96 66 Q88 60 92 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M108 60 q5 1 9 -1 M114 58 l4 3 M114 58 l4 -3" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(98, 57, 2.4, E)}
    </g>`;
  },

  // ── Frog — squat round body, wide happy grin, two bulging eyes on top, folded hind legs, webbed toes
  frog: (c) => {
    const E = eyeInk(c);
    const hind = `<path d="M30 92 Q16 86 24 72 Q34 78 42 88 Q40 96 30 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/><path d="M24 90 l-6 4 m6 -4 l-1 6 m1 -6 l-6 -1" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>`;
    const front = `<path d="M42 82 q-3 10 -8 12" fill="none" stroke="${c.line}" stroke-width="4.6" stroke-linecap="round"/><path d="M42 82 q-3 10 -8 12" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/><path d="M34 94 l-5 2 m5 -2 l-1 5 m1 -5 l-5 -1" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">${hind}${mirror(hind)}</g>
    <g class="breathe">
      ${front}${mirror(front)}
      <path d="M30 82 Q28 56 60 54 Q92 56 90 82 Q60 96 30 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="80" rx="20" ry="10" fill="${c.shade}" opacity=".5"/>
      <path d="M38 72 Q60 90 82 72" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      <circle cx="52" cy="76" r="1.6" fill="${c.line}" opacity=".5"/><circle cx="68" cy="76" r="1.6" fill="${c.line}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <circle cx="45" cy="52" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${mirror(`<circle cx="45" cy="52" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>`)}
      ${eyes(45, 75, 51, 4, E)}
    </g>`;
  },

  // ── Tree Frog — clinging pose, ENORMOUS round eyes, splayed limbs with big sticky toe discs
  treefrog: (c) => {
    const E = eyeInk(c);
    const limb = (x, y, dx, dy) => {
      const ex = x + dx, ey = y + dy;
      const discs = [-1, 0, 1].map((k) => `<circle cx="${(ex + k * 4).toFixed(1)}" cy="${(ey + Math.abs(k) * 2).toFixed(1)}" r="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>`).join("");
      return `<path d="M${x} ${y} Q${x + dx * 0.4} ${y + dy * 0.9} ${ex} ${ey}" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/><path d="M${x} ${y} Q${x + dx * 0.4} ${y + dy * 0.9} ${ex} ${ey}" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>${discs}`;
    };
    return `
    <g class="tail-wag">${limb(40, 62, -16, 6)}${limb(80, 62, 16, 6)}${limb(44, 78, -12, 16)}${limb(76, 78, 12, 16)}</g>
    <g class="breathe">
      <path d="M36 74 Q34 52 60 50 Q86 52 84 74 Q60 88 36 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 78 q18 8 36 0" fill="none" stroke="${c.shade}" stroke-width="1.5" opacity=".5"/>
      ${smile(60, 66, 4.4, INK)}
    </g>
    <g class="head-tilt">
      <circle cx="44" cy="42" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      ${mirror(`<circle cx="44" cy="42" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>`)}
      <circle cx="44" cy="43" r="8" fill="#fff" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="76" cy="43" r="8" fill="#fff" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="45" cy="44" r="4.6" fill="${INK}"/><circle cx="75" cy="44" r="4.6" fill="${INK}"/>
      <circle cx="47" cy="42" r="1.5" fill="#fff"/><circle cx="77" cy="42" r="1.5" fill="#fff"/>
    </g>`;
  },

  // ── Toad — dumpy low body, warty bumps, half-lidded hooded eyes, wide dry grin, stubby legs
  toad: (c) => {
    const E = eyeInk(c);
    const warts = [[38, 74], [50, 70], [66, 70], [78, 74], [44, 82], [60, 84], [76, 82]].map(([x, y]) =>
      `<circle cx="${x}" cy="${y}" r="2.4" fill="${c.shade}" stroke="${c.line}" stroke-width="0.9" opacity=".9"/>`).join("");
    const foot = (x) => `<path d="M${x} 86 q-6 6 -12 6" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/><path d="M${x} 86 q-6 6 -12 6" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">${foot(40)}${mirror(foot(40))}</g>
    <g class="breathe">
      <path d="M26 82 Q26 62 60 60 Q94 62 94 82 Q60 96 26 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.7" stroke-linejoin="round"/>
      <ellipse cx="52" cy="58" rx="10" ry="7" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>
      ${mirror(`<ellipse cx="52" cy="58" rx="10" ry="7" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>`)}
      ${warts}
      <path d="M40 74 Q60 86 80 74" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="48" cy="56" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.3"/>
      ${mirror(`<circle cx="48" cy="56" r="8" fill="${c.body}" stroke="${c.line}" stroke-width="2.3"/>`)}
      ${eyes(48, 72, 57, 3.4, E)}
      <path d="M40 54 q8 -3 16 0 M64 54 q8 -3 16 0" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    </g>`;
  },

  // ── Salamander — long smooth horizontal body, four splayed legs, tapering tail, bright spot rows
  salamander: (c) => {
    const E = eyeInk(c);
    // fire-salamander signature: big bold irregular blotches in two rows
    const spots = [[46, 58], [60, 55], [74, 59], [52, 70], [68, 70]].map(([x, y], i) => `<ellipse cx="${x}" cy="${y}" rx="${i % 2 ? 5 : 4}" ry="3.6" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3"/>`).join("");
    const leg = (x, dy) => `<path d="M${x} ${dy > 0 ? 74 : 54} q${dy > 0 ? -6 : 6} ${dy} ${dy > 0 ? -11 : 11} ${dy * 1.1}" fill="none" stroke="${c.line}" stroke-width="4.6" stroke-linecap="round"/><path d="M${x} ${dy > 0 ? 74 : 54} q${dy > 0 ? -6 : 6} ${dy} ${dy > 0 ? -11 : 11} ${dy * 1.1}" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">${tube("M40 64 Q18 62 12 78 Q10 88 18 88", c.body, c.line, 8)}</g>
    <g class="breathe">
      ${leg(50, 12)}${leg(72, 12)}${leg(50, -12)}${leg(72, -12)}
      <path d="M40 64 Q40 50 62 50 Q86 50 92 64 Q86 78 62 78 Q42 78 40 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${spots}
    </g>
    <g class="head-tilt">
      <ellipse cx="92" cy="63" rx="11" ry="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${eye(94, 59, 2.6, E)}
      ${smile(99, 63, 2.6, E)}
    </g>`;
  },

  // ── Newt — slender, wavy dorsal crest (breeding male), long finned tail, speckled belly
  newt: (c) => {
    const E = eyeInk(c);
    // breeding-male crest: tall jagged zigzag sail (clearly taller than salamander's back)
    const crest = Array.from({ length: 9 }, (_, i) => {
      const x = 36 + i * 5, h = 5 + Math.sin(i / 8 * Math.PI) * 9;
      return `<path d="M${x} 54 l2 -${h.toFixed(1)} l2 ${h.toFixed(1)} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.1" stroke-linejoin="round"/>`;
    }).join("");
    const speck = [[48, 68], [58, 70], [68, 68], [54, 63], [64, 63]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.6" fill="${c.shade}"/>`).join("");
    const leg = (x, dy) => `<path d="M${x} ${dy > 0 ? 70 : 58} l${dy > 0 ? -7 : 7} ${dy}" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/><path d="M${x} ${dy > 0 ? 70 : 58} l${dy > 0 ? -7 : 7} ${dy}" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">
      <path d="M42 62 Q20 56 10 66 Q6 76 12 84 Q26 76 42 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${tube("M42 64 Q26 64 14 72", c.body, c.line, 5)}
    </g>
    <g class="breathe">
      ${leg(50, 11)}${leg(70, 11)}${leg(50, -11)}${leg(70, -11)}
      <path d="M42 64 Q42 54 62 54 Q84 54 90 64 Q84 72 62 72 Q44 72 42 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${crest}${speck}
    </g>
    <g class="head-tilt">
      <ellipse cx="90" cy="63" rx="10" ry="7.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.3"/>
      ${eye(92, 60, 2.4, E)}
      ${smile(97, 63, 2.2, E)}
    </g>`;
  },

  // ── Axolotl — wide beaming face, six feathery external gill fronds, stubby legs, finned tail; float
  axolotl: (c) => {
    const E = eyeInk(c);
    // one feathery external gill-frond: a curved stalk with little branchlets (the axolotl's signature)
    const gillFrond = (bx, by, ang, len) => `<g transform="translate(${bx} ${by}) rotate(${ang})">
      <path d="M0 0 Q-3 ${(-len * 0.5).toFixed(0)} -1 ${-len}" fill="none" stroke="${c.line}" stroke-width="5.6" stroke-linecap="round"/>
      <path d="M0 0 Q-3 ${(-len * 0.5).toFixed(0)} -1 ${-len}" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/>
      ${[0.35, 0.6, 0.85].map((f) => `<path d="M${(-1.5 * f).toFixed(1)} ${(-len * f).toFixed(1)} q-5 -1 -7 -5 M${(-1.5 * f).toFixed(1)} ${(-len * f).toFixed(1)} q5 -2 7 -5" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>`).join("")}
    </g>`;
    const foot = (x, dir) => `<path d="M${x} 78 q${dir * 4} 8 ${dir * 2} 12" fill="none" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/><path d="M${x} 78 q${dir * 4} 8 ${dir * 2} 12" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">
      <path d="M30 64 Q14 50 8 56 Q16 64 8 72 Q14 78 30 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${foot(46, -1)}${foot(66, 1)}
      <path d="M30 64 Q34 46 62 46 Q88 46 92 62 Q88 80 62 80 Q34 80 30 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 72 q22 8 44 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".45"/>
    </g>
    <g class="tail-wag">
      ${gillFrond(80, 52, -52, 20)}${gillFrond(85, 49, -30, 23)}${gillFrond(89, 51, -10, 20)}
    </g>
    <g class="head-tilt">
      <ellipse cx="66" cy="72" rx="6" ry="4" fill="${c.shade}" opacity=".55"/>
      <ellipse cx="86" cy="70" rx="6" ry="4" fill="${c.shade}" opacity=".55"/>
      <path d="M64 66 Q76 78 90 66" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>
      ${eyes(70, 84, 60, 2.4, E)}
    </g>`;
  },

  // ── Gila Monster — chunky beaded lizard, bold banded blotches, fat food-store tail, blunt head
  gilamonster: (c) => {
    const E = eyeInk(c);
    const bands = [30, 44, 58, 72].map((x) => `<path d="M${x} 54 Q${x + 6} 68 ${x} 80 Q${x + 12} 68 ${x + 6} 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round" opacity=".9"/>`).join("");
    const beads = [[38, 60], [50, 62], [62, 62], [70, 66], [44, 72], [58, 74]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.4" fill="${c.line}" opacity=".4"/>`).join("");
    const leg = (x, fwd) => `<path d="M${x} 78 q${fwd ? 5 : -5} 10 ${fwd ? 1 : -1} 16" fill="none" stroke="${c.line}" stroke-width="6.4" stroke-linecap="round"/><path d="M${x} 78 q${fwd ? 5 : -5} 10 ${fwd ? 1 : -1} 16" fill="none" stroke="${c.body}" stroke-width="4" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag"><path d="M32 68 Q14 66 8 78 Q6 90 16 90 Q26 86 34 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/><path d="M14 80 q4 4 10 2" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".7"/></g>
    <g class="breathe">
      ${leg(44, false)}${leg(72, true)}
      <path d="M30 66 Q32 52 60 52 Q86 52 90 64 Q86 80 60 80 Q32 80 30 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${bands}${beads}
    </g>
    <g class="head-tilt">
      <path d="M80 56 Q102 54 104 66 Q102 76 84 76 Q74 68 80 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M90 70 q7 1 13 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M104 68 q4 1 7 -1 M108 66 l3 3 M108 66 l3 -3" fill="none" stroke="${TONGUE}" stroke-width="1.4" stroke-linecap="round"/>
      ${eye(88, 62, 2.6, E)}
    </g>`;
  },

  // ── Bearded Dragon — flat wide body, spiky throat "beard", spiny side fringe, triangular head, calm
  beardeddragon: (c) => {
    const E = eyeInk(c);
    const fringe = (side) => Array.from({ length: 5 }, (_, i) => `<path d="M${(side ? 30 : 90) + (side ? i * 6 : -i * 6)} ${78} l${side ? -2 : 2} 6 l${side ? 4 : -4} 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.1" stroke-linejoin="round"/>`).join("");
    const beard = Array.from({ length: 7 }, (_, i) => `<path d="M${72 + i * 3} 66 l1.6 6 l1.6 -6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`).join("");
    const leg = (x, fwd) => `<path d="M${x} 76 q${fwd ? 5 : -5} 10 ${fwd ? 12 : -12} 12" fill="none" stroke="${c.line}" stroke-width="5.2" stroke-linecap="round"/><path d="M${x} 76 q${fwd ? 5 : -5} 10 ${fwd ? 12 : -12} 12" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">${tube("M30 66 Q12 66 8 82 Q6 92 14 92", c.body, c.line, 7)}</g>
    <g class="breathe">
      ${leg(42, false)}${leg(72, true)}
      <path d="M28 68 Q30 54 60 54 Q88 54 90 66 Q88 80 60 82 Q30 82 28 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${fringe(true)}
      <path d="M38 66 q22 8 44 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
      ${[[44, 62], [56, 62], [68, 64]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.6" fill="${c.shade}" opacity=".7"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M78 52 Q100 50 102 62 Q100 70 88 70 Q76 66 78 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${beard}
      ${eye(90, 58, 2.6, E)}
      ${smile(98, 62, 2.2, E)}
    </g>`;
  },

  // ── Monitor Lizard — sleek long neck, muscular legs, banded flank, long whip tail, forked tongue
  monitorlizard: (c) => {
    const E = eyeInk(c);
    const bands = [36, 46, 56, 66].map((x) => `<path d="M${x} 56 q3 10 0 20" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" opacity=".8"/>`).join("");
    const leg = (x, fwd) => `<path d="M${x} 76 q${fwd ? 6 : -6} 11 ${fwd ? 2 : -2} 18" fill="none" stroke="${c.line}" stroke-width="6.6" stroke-linecap="round"/><path d="M${x} 76 q${fwd ? 6 : -6} 11 ${fwd ? 2 : -2} 18" fill="none" stroke="${c.body}" stroke-width="4.2" stroke-linecap="round"/><path d="M${x + (fwd ? 2 : -2)} 94 l-3 4 m3 -4 l0 5 m0 -5 l3 4" stroke="${CLAW}" stroke-width="1.4" stroke-linecap="round"/>`;
    return `
    <g class="tail-wag">${tube("M32 66 Q10 66 6 84 Q4 96 14 94 Q8 82 20 76", c.body, c.line, 8)}</g>
    <g class="breathe">
      ${leg(42, false)}${leg(70, true)}
      <path d="M30 66 Q32 52 58 52 Q82 52 88 64 Q82 78 58 78 Q32 78 30 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${bands}
    </g>
    <g class="head-tilt">
      ${tube("M80 62 Q90 46 100 42", c.body, c.line, 10)}
      <path d="M94 38 Q108 36 108 46 Q106 52 96 52 Q88 46 94 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M108 46 q3 1 5 -1" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M108 44 q4 1 7 -1 M113 42 l3 3 M113 42 l3 -3" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(100, 43, 2.6, E)}
    </g>`;
  },

  // ── Horned Lizard — flat round toad-like body, crown of spiky horns behind head, fringe of side spines
  hornedlizard: (c) => {
    const E = eyeInk(c);
    const horns = Array.from({ length: 7 }, (_, i) => {
      const a = (-150 + i * 20) * Math.PI / 180, cx = 60 + 15 * Math.cos(a), cy = 42 + 15 * Math.sin(a);
      const tx = 60 + 26 * Math.cos(a), ty = 42 + 26 * Math.sin(a), w = 3.2;
      const px = -Math.sin(a) * w, py = Math.cos(a) * w;
      return `<path d="M${(cx + px).toFixed(1)} ${(cy + py).toFixed(1)} L${tx.toFixed(1)} ${ty.toFixed(1)} L${(cx - px).toFixed(1)} ${(cy - py).toFixed(1)} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`;
    }).join("");
    const fringe = Array.from({ length: 6 }, (_, i) => `<path d="M${24 + i * 4} ${72 + Math.abs(i - 2.5) * 1.5} l-4 3 l3 2 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`).join("");
    return `
    <g class="tail-wag">${tube("M60 90 Q56 102 64 106 Q70 100 66 90", c.body, c.line, 6)}</g>
    <g class="breathe">
      <ellipse cx="60" cy="72" rx="30" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.7"/>
      ${fringe}${mirror(fringe)}
      ${[[48, 66], [60, 64], [72, 66], [54, 76], [66, 76]].map(([x, y]) => `<path d="M${x} ${y} l-2 3 l3 1 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="0.9" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      ${horns}
      <path d="M46 48 Q46 34 60 34 Q74 34 74 48 Q60 58 46 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${eyes(53, 67, 46, 2.8, E)}
      ${smile(60, 52, 3, E)}
    </g>`;
  },

  // ── Basilisk Lizard — tall head crest + back sail, long hind legs (water-runner), whippy long tail
  basilisklizard: (c) => {
    const E = eyeInk(c);
    const sail = Array.from({ length: 6 }, (_, i) => {
      const x = 40 + i * 6, h = 8 + Math.sin(i / 5 * Math.PI) * 6;
      return `<path d="M${x} 58 q3 -${h.toFixed(1)} 6 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`;
    }).join("");
    return `
    <g class="tail-wag">${tube("M40 70 Q18 74 10 92 Q6 104 16 102 Q10 90 24 82", c.body, c.line, 6)}</g>
    <g class="breathe">
      <path d="M46 84 q-8 12 -4 20 M62 86 q8 12 4 20" fill="none" stroke="${c.line}" stroke-width="6.6" stroke-linecap="round"/>
      <path d="M46 84 q-8 12 -4 20 M62 86 q8 12 4 20" fill="none" stroke="${c.body}" stroke-width="4.2" stroke-linecap="round"/>
      <path d="M42 104 l-5 4 m5 -4 l0 6 m0 -6 l5 4 M66 104 l-5 4 m5 -4 l0 6 m0 -6 l5 4" stroke="${CLAW}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M40 70 Q42 56 60 56 Q80 56 84 68 Q80 82 58 84 Q42 82 40 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${sail}
    </g>
    <g class="head-tilt">
      <path d="M76 46 Q66 26 84 30 Q98 34 94 50 Q86 46 78 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M74 52 Q94 48 100 58 Q94 68 80 66 Q72 60 74 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${eye(86, 56, 2.8, E)}
      ${smile(96, 60, 2.4, E)}
    </g>`;
  },
};

export const ROSTER_REPTILES = [
  { n: "Green Iguana",    e: "🦎", tier: 2, float: false },
  { n: "Chameleon",       e: "🦎", tier: 3, float: false },
  { n: "Gecko",           e: "🦎", tier: 1, float: false },
  { n: "Komodo Dragon",   e: "🐉", tier: 3, float: false },
  { n: "Crocodile",       e: "🐊", tier: 3, float: false },
  { n: "Alligator",       e: "🐊", tier: 2, float: false },
  { n: "Tortoise",        e: "🐢", tier: 2, float: false },
  { n: "Cobra",           e: "🐍", tier: 3, float: false },
  { n: "Python",          e: "🐍", tier: 2, float: false },
  { n: "Rattlesnake",     e: "🐍", tier: 3, float: false },
  { n: "Sea Snake",       e: "🐍", tier: 3, float: true },
  { n: "Frog",            e: "🐸", tier: 1, float: false },
  { n: "Tree Frog",       e: "🐸", tier: 2, float: false },
  { n: "Toad",            e: "🐸", tier: 1, float: false },
  { n: "Salamander",      e: "🦎", tier: 2, float: false },
  { n: "Newt",            e: "🦎", tier: 1, float: false },
  { n: "Axolotl",         e: "🐟", tier: 4, float: true },
  { n: "Gila Monster",    e: "🦎", tier: 3, float: false },
  { n: "Bearded Dragon",  e: "🦎", tier: 2, float: false },
  { n: "Monitor Lizard",  e: "🦎", tier: 3, float: false },
  { n: "Horned Lizard",   e: "🦎", tier: 2, float: false },
  { n: "Basilisk Lizard", e: "🦎", tier: 3, float: false },
];
