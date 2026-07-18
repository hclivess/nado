// pets-art/reptiles2.js — BESPOKE hand-drawn SVG art for REPTILES2 (more snakes, lizards & amphibians).
// House style (see tmp/METHOD.md): ONE readable silhouette per animal, grounded with floorShadow, a pale
// two-tone belly/underside via belly(c), a clean cute face. viewBox 0 0 120 120, animal centered ~ (60,64),
// kept within x,y ∈ [8,114]. Colours come from the coat object c (c.body / c.shade / c.line) and are applied
// at runtime, so real hues are NOT hardcoded — only the forked tongue uses a fixed warm tint (and the
// blue-tongue skink's defining blue tongue). Animate: torso <g class="breathe">, head <g class="head-tilt">,
// tails/hoods/frills/flippers <g class="tail-wag">. Leatherback (aquatic) sets float:true, oriented sideways.
import { INK, ceye, eye, eyes, floorShadow, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

const TONGUE = "#e0564d"; // forked tongue (fixed warm accent, same across coats)

export const ART_REPTILES2 = {
  // ── Green Anaconda — massively THICK oval coil, big round dark spots in two rows, blunt head on top
  greenanaconda: (c) => {
    const B = belly(c), E = eyeInk(c);
    const spots = [[34, 66], [52, 54], [78, 54], [96, 66], [40, 88], [80, 88], [60, 96]]
      .map(([x, y]) => `<ellipse cx="${x}" cy="${y}" rx="6.6" ry="5.2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2"/>`).join("");
    return `
    ${floorShadow(60, 110, 35)}
    <g class="breathe">
      ${tube("M60 100 Q18 100 20 70 Q24 44 60 44 Q96 44 100 70 Q102 100 60 100", c.body, c.line, 21)}
      ${tube("M60 92 Q34 90 36 74 Q40 60 60 60", c.shade, "none", 8)}
      ${spots}
      <path d="M32 98 Q60 108 88 98" fill="none" stroke="${B}" stroke-width="4.4" stroke-linecap="round" opacity=".8"/>
    </g>
    <g class="head-tilt">
      <path d="M48 46 Q44 26 60 24 Q76 26 72 46 Q60 54 48 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <ellipse cx="60" cy="40" rx="10" ry="6" fill="${B}" opacity=".5"/>
      <path d="M60 24 q0 -6 0 -9 M60 15 l-3.4 -4 M60 15 l3.4 -4" fill="none" stroke="${TONGUE}" stroke-width="1.7" stroke-linecap="round"/>
      ${eye(53, 40, 3, E)}${eye(67, 40, 3, E)}
    </g>`;
  },

  // ── King Cobra — reared TALL, big elongated flared hood with chevrons, head high on top, flicking tongue
  kingcobra: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="breathe">
      <ellipse cx="60" cy="104" rx="33" ry="11" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <ellipse cx="60" cy="98" rx="21" ry="7.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <path d="M50 100 Q42 70 60 50 Q78 70 70 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M60 30 Q28 34 32 62 Q44 80 60 80 Q76 80 88 62 Q92 34 60 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 40 Q42 44 44 60 Q52 72 60 72 Q68 72 76 60 Q78 44 60 40 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M48 48 Q60 56 72 48 M50 58 Q60 65 70 58" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="60" cy="26" rx="13" ry="10.5" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <ellipse cx="60" cy="24" rx="8" ry="5.5" fill="${B}" opacity=".45"/>
      <path d="M60 36 q0 8 0 12 M60 48 l-3.6 4.4 M60 48 l3.6 4.4" fill="none" stroke="${TONGUE}" stroke-width="1.8" stroke-linecap="round"/>
      ${eyes(53, 67, 24, 2.8, E)}
    </g>`;
  },

  // ── Boa Constrictor — neatly coiled rope (double concentric coil), rectangular saddle marks, head on top
  boaconstrictor: (c) => {
    const B = belly(c), E = eyeInk(c);
    const saddle = (x, y) => `<path d="M${x - 6} ${y - 4} h12 l-3 4 l3 4 h-12 l3 -4 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 110, 34)}
    <g class="breathe">
      ${tube("M60 100 Q20 98 22 72 Q26 50 60 50 Q94 50 98 72 Q100 100 60 100", c.body, c.line, 13)}
      ${tube("M60 92 Q40 90 42 76 Q46 64 60 64 Q74 64 78 76 Q80 90 60 92", c.body, c.line, 12)}
      <ellipse cx="60" cy="78" rx="11" ry="7" fill="${c.body}"/>
      ${[[30, 72], [46, 56], [74, 56], [90, 72]].map(([x, y]) => saddle(x, y)).join("")}
      ${[[48, 82], [72, 82]].map(([x, y]) => saddle(x, y)).join("")}
      <path d="M46 88 Q60 96 74 88" fill="none" stroke="${B}" stroke-width="3" stroke-linecap="round" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M49 50 Q45 32 60 30 Q75 32 71 50 Q60 57 49 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="60" cy="44" rx="9" ry="5" fill="${B}" opacity=".5"/>
      <path d="M60 30 q0 -6 0 -9 M60 21 l-3.2 -4 M60 21 l3.2 -4" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(53, 44, 2.8, E)}${eye(67, 44, 2.8, E)}
    </g>`;
  },

  // ── Black Mamba — SLEEK flowing S, smooth body, coffin head with the dark open mouth, forked tongue
  blackmamba: (c) => {
    const B = belly(c), E = eyeInk(c);
    return `
    ${floorShadow(52, 110, 26)}
    <g class="breathe">
      ${tube("M28 100 Q18 78 40 72 Q64 66 56 46 Q52 34 70 30", c.body, c.line, 13)}
      ${tube("M30 98 Q22 80 40 75", B, "none", 4)}
    </g>
    <g class="head-tilt">
      <path d="M62 36 Q62 20 80 20 Q94 22 92 34 Q86 44 74 44 Q62 44 62 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M84 34 Q94 33 95 39 Q90 43 82 41 Q80 37 84 34 Z" fill="${INK}"/>
      <path d="M92 38 q7 1 11 0 M103 38 l4.4 -3 M103 38 l4.4 3" fill="none" stroke="${TONGUE}" stroke-width="1.7" stroke-linecap="round"/>
      ${eye(76, 30, 3, E)}
    </g>`;
  },

  // ── Gaboon Viper — thick short coil, geometric hourglass pattern, VERY WIDE arrow head, tiny nose horns
  gaboonviper: (c) => {
    const B = belly(c), E = eyeInk(c);
    const hour = (x, y) => `<path d="M${x - 8} ${y - 7} L${x + 8} ${y - 7} L${x + 2} ${y} L${x + 8} ${y + 7} L${x - 8} ${y + 7} L${x - 2} ${y} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 112, 33)}
    <g class="breathe">
      ${tube("M44 104 Q18 98 26 78 Q40 62 60 64 Q82 62 94 78 Q102 98 76 104", c.body, c.line, 20)}
      ${[[40, 88], [60, 84], [78, 90]].map(([x, y]) => hour(x, y)).join("")}
    </g>
    <g class="head-tilt">
      <path d="M60 42 L34 58 Q38 68 60 68 Q82 68 86 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 46 L52 62 M60 46 L68 62" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".55"/>
      <path d="M57 44 l-1.6 -6 l3.6 3 Z M63 44 l1.6 -6 l-3.6 3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <path d="M60 42 q0 -5 0 -8 M60 34 l-3 -4 M60 34 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(46, 57, 2.8, E)}${eye(74, 57, 2.8, E)}
    </g>`;
  },

  // ── Coral Snake — full ring loop with bright cross-BANDS all around (red-black-yellow), small head bump
  coralsnake: (c) => {
    const B = belly(c), E = eyeInk(c);
    const cx = 60, cy = 66, R = 33;
    const bands = Array.from({ length: 18 }, (_, i) => {
      const a = (-70 + i * 20) * Math.PI / 180;
      const x1 = cx + (R - 8) * Math.cos(a), y1 = cy + (R - 8) * Math.sin(a);
      const x2 = cx + (R + 8) * Math.cos(a), y2 = cy + (R + 8) * Math.sin(a);
      const col = i % 2 ? B : c.shade, w = i % 2 ? 2.4 : 5.2;
      return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${col}" stroke-width="${w}" stroke-linecap="round"/>`;
    }).join("");
    return `
    ${floorShadow(60, 108, 32)}
    <g class="breathe">
      ${tube(`M${cx} ${cy - R} A${R} ${R} 0 1 1 ${cx - 0.1} ${cy - R}`, c.body, c.line, 13)}
      ${bands}
    </g>
    <g class="head-tilt">
      <path d="M50 32 Q48 20 60 20 Q72 20 70 32 Q60 40 50 32 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 20 q0 -6 0 -9 M60 11 l-3 -4 M60 11 l3 -4" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(54, 28, 2.4, E)}${eye(66, 28, 2.4, E)}
    </g>`;
  },

  // ── Garter Snake — slim slithering S with LONGITUDINAL stripes running the whole length, small head
  gartersnake: (c) => {
    const E = eyeInk(c);
    const path = "M14 76 Q34 54 54 68 Q74 82 94 62";
    return `
    ${floorShadow(58, 106, 30)}
    <g class="breathe">
      ${tube(path, c.body, c.line, 12)}
      <g transform="translate(0 -4)"><path d="${path}" fill="none" stroke="${c.shade}" stroke-width="2.2" stroke-linecap="round" opacity=".75"/></g>
      <path d="${path}" fill="none" stroke="${belly(c)}" stroke-width="2.6" stroke-linecap="round"/>
      <g transform="translate(0 4)"><path d="${path}" fill="none" stroke="${c.shade}" stroke-width="2.2" stroke-linecap="round" opacity=".75"/></g>
    </g>
    <g class="head-tilt">
      <path d="M90 58 Q104 55 106 65 Q104 73 94 73 Q86 66 90 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M106 64 q6 1 10 0 M116 64 l3 -3 M116 64 l3 3" fill="none" stroke="${TONGUE}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(97, 62, 2.6, E)}
    </g>`;
  },

  // ── Sidewinder — compact J-coil making the classic parallel sand-tracks, supraocular HORNS over the eyes
  sidewinder: (c) => {
    const B = belly(c), E = eyeInk(c);
    const track = [0, 1, 2].map(i => `<path d="M${22 + i * 20} 106 l16 -9" fill="none" stroke="${c.shade}" stroke-width="3.2" stroke-linecap="round" opacity=".4"/>`).join("");
    return `
    ${floorShadow(60, 112, 24)}
    ${track}
    <g class="breathe">
      ${tube("M28 98 Q48 90 40 72 Q34 56 56 52 Q74 48 76 38", c.body, c.line, 12)}
      ${[[46, 66], [56, 78], [66, 56]].map(([x, y]) => `<path d="M${x - 5} ${y} q5 4 10 0" fill="none" stroke="${c.shade}" stroke-width="2.4" opacity=".6"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M64 42 Q64 26 82 26 Q96 28 94 40 Q88 50 76 50 Q64 50 64 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="80" cy="38" rx="8" ry="5" fill="${B}" opacity=".45"/>
      <path d="M72 30 l-2 -7 l5 3 Z M88 30 l2 -7 l-5 3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.1" stroke-linejoin="round"/>
      <path d="M94 40 q6 1 10 0 M104 40 l4 -3 M104 40 l4 3" fill="none" stroke="${TONGUE}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(74, 38, 2.6, E)}${eye(88, 40, 2.4, E)}
    </g>`;
  },

  // ── Green Anole — slim little lizard, long curling tail, a big round throat DEWLAP fanned out beneath
  greenanole: (c) => {
    const B = belly(c), E = eyeInk(c);
    const leg = (x, dy) => `<path d="M${x} ${dy > 0 ? 74 : 62} q${dy > 0 ? -5 : 5} ${dy} ${dy > 0 ? -9 : 9} ${dy * 1.1}" fill="none" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/><path d="M${x} ${dy > 0 ? 74 : 62} q${dy > 0 ? -5 : 5} ${dy} ${dy > 0 ? -9 : 9} ${dy * 1.1}" fill="none" stroke="${c.body}" stroke-width="2.6" stroke-linecap="round"/>`;
    return `
    ${floorShadow(56, 108, 27)}
    <g class="tail-wag">${tube("M40 70 Q16 74 10 62 Q8 54 16 54", c.body, c.line, 6)}</g>
    <g class="breathe">
      ${leg(50, 10)}${leg(70, 10)}${leg(50, -10)}${leg(70, -10)}
      <path d="M36 68 Q38 56 60 56 Q80 56 84 66 Q80 76 58 76 Q40 76 36 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M44 72 q18 6 34 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M80 62 Q98 59 100 69 Q98 77 86 77 Q78 70 80 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M86 76 Q88 94 100 90 Q103 80 98 74 Q92 74 86 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M88 78 Q92 88 98 89 M89 81 Q92 86 96 85" fill="none" stroke="${c.line}" stroke-width="1" opacity=".55"/>
      ${eye(90, 66, 3, E)}
      ${smile(97, 69, 2, E)}
    </g>`;
  },

  // ── Blue-tongue Skink — fat smooth body, banded flanks, stubby legs, broad BLUE tongue lolling out
  bluetongueskink: (c) => {
    const B = belly(c), E = eyeInk(c);
    const leg = (x, fwd) => `<path d="M${x} 76 q${fwd ? 5 : -5} 9 ${fwd ? 2 : -2} 14" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/><path d="M${x} 76 q${fwd ? 5 : -5} 9 ${fwd ? 2 : -2} 14" fill="none" stroke="${c.body}" stroke-width="3.8" stroke-linecap="round"/>`;
    return `
    ${floorShadow(56, 108, 31)}
    <g class="tail-wag">${tube("M32 70 Q14 72 10 62 Q9 56 16 56", c.body, c.line, 9)}</g>
    <g class="breathe">
      ${leg(44, false)}${leg(70, true)}
      <path d="M30 70 Q32 54 58 54 Q84 54 88 68 Q84 82 56 82 Q30 82 30 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[42, 52, 62, 72].map(x => `<path d="M${x} 57 q2 10 0 21" fill="none" stroke="${c.shade}" stroke-width="3.2" opacity=".5"/>`).join("")}
      <path d="M36 78 Q56 86 78 78" fill="none" stroke="${B}" stroke-width="3" stroke-linecap="round" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M78 62 Q98 59 100 70 Q98 78 84 78 Q74 71 78 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M98 72 Q112 70 113 75 Q111 81 100 79 Q96 76 98 72 Z" fill="#3f8fd6" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M105 71 v8" stroke="#2e6ba6" stroke-width="1.2" opacity=".7"/>
      ${eye(88, 66, 3, E)}
    </g>`;
  },

  // ── Frilled Lizard — HUGE circular neck frill spread wide, head & open mouth at the centre, body below
  frilledlizard: (c) => {
    const B = belly(c), E = eyeInk(c);
    const folds = Array.from({ length: 12 }, (_, i) => {
      const a = (i * 30 + 15) * Math.PI / 180, x = 60 + 27 * Math.cos(a), y = 42 + 27 * Math.sin(a);
      return `<path d="M60 42 L${x.toFixed(1)} ${y.toFixed(1)}" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>`;
    }).join("");
    const leg = (x, fwd) => `<path d="M${x} 82 q${fwd ? 5 : -5} 9 ${fwd ? 1 : -1} 15" fill="none" stroke="${c.line}" stroke-width="5.4" stroke-linecap="round"/><path d="M${x} 82 q${fwd ? 5 : -5} 9 ${fwd ? 1 : -1} 15" fill="none" stroke="${c.body}" stroke-width="3.4" stroke-linecap="round"/>`;
    return `
    ${floorShadow(60, 112, 26)}
    <g class="breathe">
      ${tube("M60 92 Q78 98 84 112", c.body, c.line, 7)}
      ${leg(48, false)}${leg(72, true)}
      <path d="M50 84 Q48 64 60 62 Q72 64 70 86 Q60 94 50 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      ${pom(60, 42, 30, c.shade, c.line, 18, 2.4)}
      <circle cx="60" cy="42" r="22" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="60" cy="42" r="13" fill="${B}" opacity=".4"/>
      ${folds}
    </g>
    <g class="head-tilt">
      <path d="M50 40 Q50 28 60 28 Q70 28 70 40 Q70 50 60 54 Q50 50 50 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M56 48 Q60 56 66 50 Q61 51 56 48 Z" fill="${INK}"/>
      <path d="M64 50 l2 4 l1 -3 Z" fill="#fff" stroke="${c.line}" stroke-width="0.4"/>
      ${eyes(54, 66, 38, 2.8, E)}
    </g>`;
  },

  // ── Thorny Devil — squat round lizard bristling with SPIKES all over, big brow horns, stubby legs
  thornydevil: (c) => {
    const B = belly(c), E = eyeInk(c);
    const leg = (x, y, dx, dy) => `<path d="M${x} ${y} q${dx} ${dy} ${dx * 1.4} ${dy * 1.3}" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/><path d="M${x} ${y} q${dx} ${dy} ${dx * 1.4} ${dy * 1.3}" fill="none" stroke="${c.body}" stroke-width="3.2" stroke-linecap="round"/>`;
    const spike = (x, y, dx, dy) => `<path d="M${x - dy * 0.4} ${y + dx * 0.4} L${x + dx} ${y + dy} L${x + dy * 0.4} ${y - dx * 0.4} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 110, 29)}
    <g class="breathe">
      ${leg(42, 80, -5, 8)}${leg(78, 80, 5, 8)}${leg(40, 66, -6, 3)}${leg(80, 66, 6, 3)}
      ${pom(60, 70, 25, c.body, c.line, 16, 3)}
      <ellipse cx="60" cy="74" rx="15" ry="9" fill="${B}" opacity=".45"/>
      ${[[48, 60, 0, -6], [60, 56, 0, -7], [72, 60, 0, -6], [50, 76, -4, 5], [70, 76, 4, 5], [60, 68, 0, 6]].map(([x, y, dx, dy]) => spike(x, y, dx, dy)).join("")}
    </g>
    <g class="head-tilt">
      <path d="M49 50 Q49 40 60 40 Q71 40 71 50 Q65 56 60 56 Q55 56 49 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M51 44 l-5 -9 l7 4 Z M69 44 l5 -9 l-7 4 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.1" stroke-linejoin="round"/>
      ${eyes(54, 66, 48, 2.6, E)}
      ${smile(60, 52, 2, E)}
    </g>`;
  },

  // ── Marine Iguana — sturdy dark lizard, BLUNT deep snout, low spiky dorsal crest, thick tail, salt specks
  marineiguana: (c) => {
    const B = belly(c), E = eyeInk(c);
    const leg = (x, fwd) => `<path d="M${x} 78 q${fwd ? 6 : -6} 11 ${fwd ? 2 : -2} 17" fill="none" stroke="${c.line}" stroke-width="6.6" stroke-linecap="round"/><path d="M${x} 78 q${fwd ? 6 : -6} 11 ${fwd ? 2 : -2} 17" fill="none" stroke="${c.body}" stroke-width="4.2" stroke-linecap="round"/>`;
    const crest = Array.from({ length: 10 }, (_, i) => `<path d="M${32 + i * 6.4} 51 l1.6 -3.4 l1.6 3.4 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`).join("");
    return `
    ${floorShadow(56, 108, 32)}
    <g class="tail-wag">${tube("M34 72 Q14 76 8 90 Q6 100 16 98", c.body, c.line, 11)}</g>
    <g class="breathe">
      ${leg(46, false)}${leg(72, true)}
      <path d="M28 72 Q30 50 60 50 Q88 50 92 66 Q88 84 58 84 Q30 84 28 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${crest}
      <path d="M36 78 q24 7 48 0" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M80 58 Q80 48 92 48 Q105 49 106 63 Q105 76 91 77 Q79 77 79 66 Q77 62 80 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M100 60 Q108 62 107 71 Q100 73 99 68 Z" fill="${c.shade}"/>
      <circle cx="96" cy="58" r="1.5" fill="${B}"/><circle cx="90" cy="55" r="1.3" fill="${B}"/><circle cx="99" cy="64" r="1.3" fill="${B}"/>
      ${eye(89, 62, 2.8, E)}
      ${smile(103, 67, 2, E)}
    </g>`;
  },

  // ── Tuatara — stocky reptile with a bold single-file row of pale spiny CREST scales from head down the back
  tuatara: (c) => {
    const B = belly(c), E = eyeInk(c);
    const leg = (x, fwd) => `<path d="M${x} 78 q${fwd ? 6 : -6} 11 ${fwd ? 2 : -2} 16" fill="none" stroke="${c.line}" stroke-width="6.2" stroke-linecap="round"/><path d="M${x} 78 q${fwd ? 6 : -6} 11 ${fwd ? 2 : -2} 16" fill="none" stroke="${c.body}" stroke-width="4" stroke-linecap="round"/>`;
    const crest = Array.from({ length: 10 }, (_, i) => { const h = 12 - Math.abs(i - 4.5) * 1.1; return `<path d="M${33 + i * 6} 55 l3 -${h.toFixed(1)} l3 ${h.toFixed(1)} Z" fill="${B}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`; }).join("");
    return `
    ${floorShadow(56, 108, 31)}
    <g class="tail-wag">${tube("M34 70 Q14 72 8 86 Q6 96 16 94", c.body, c.line, 9)}</g>
    <g class="breathe">
      ${leg(46, false)}${leg(72, true)}
      <path d="M30 70 Q32 54 60 54 Q86 54 90 66 Q86 80 58 80 Q32 80 30 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${crest}
      ${[[44, 66], [58, 68], [72, 66]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.6" fill="${c.shade}" opacity=".7"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M82 60 Q102 57 104 70 Q102 79 86 79 Q76 71 82 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M82 56 l2.6 -7 l2.6 7 Z M89 55 l2.6 -7 l2.6 7 Z" fill="${B}" stroke="${c.line}" stroke-width="1.2" stroke-linejoin="round"/>
      ${eye(90, 65, 2.8, E)}
      ${smile(101, 69, 2.2, E)}
    </g>`;
  },

  // ── Caiman — chunky little crocodilian facing you, eye-bumps + bony brow ridge, wide toothy snout, curled tail
  caiman: (c) => {
    const B = belly(c), E = eyeInk(c);
    const TOOTH = "#fbfbf6";
    const teeth = Array.from({ length: 5 }, (_, i) => `<path d="M${52 + i * 4} 66 l1.5 4 l1.5 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6"/>`).join("");
    return `
    ${floorShadow(60, 112, 31)}
    <g class="tail-wag">
      ${tube("M76 92 Q102 92 102 74 Q102 64 92 66", c.body, c.line, 8)}
      ${[0, 1, 2].map(i => `<path d="M${96 - i * 8} ${72 - i * 3} l2 -5 l2 5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="breathe">
      ${["", "s"].map((_, i) => `<path d="M${i ? 74 : 46} 84 Q${i ? 98 : 22} 88 ${i ? 92 : 28} 100" fill="none" stroke="${c.line}" stroke-width="7" stroke-linecap="round"/><path d="M${i ? 74 : 46} 84 Q${i ? 98 : 22} 88 ${i ? 92 : 28} 100" fill="none" stroke="${c.body}" stroke-width="4.4" stroke-linecap="round"/>`).join("")}
      <path d="M28 99 l-3 4 m3 -4 l0 5 m0 -5 l3 4 M92 99 l-3 4 m3 -4 l0 5 m0 -5 l3 4" stroke="${TOOTH}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M36 84 Q34 62 60 60 Q86 62 84 84 Q60 96 36 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M44 80 Q60 90 76 80 Q60 86 44 80 Z" fill="${B}" opacity=".7"/>
      ${[[46, 70], [60, 68], [74, 70]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.8" fill="${c.shade}"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M42 50 Q42 34 60 34 Q78 34 78 50 Q78 58 70 60 Q60 62 50 60 Q42 58 42 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <circle cx="50" cy="38" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="70" cy="38" r="6.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${eye(50, 38, 2.8, E)}${eye(70, 38, 2.8, E)}
      <path d="M53 44 Q60 48 67 44" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <path d="M48 56 Q48 72 60 74 Q72 72 72 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M50 65 Q60 69 70 65" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${teeth}
      <ellipse cx="56" cy="70" rx="1.4" ry="1.1" fill="${INK}"/><ellipse cx="64" cy="70" rx="1.4" ry="1.1" fill="${INK}"/>
    </g>`;
  },

  // ── Snapping Turtle — low keeled shell with serrated rear, long saw tail, and a BIG fierce hooked-beak head
  snappingturtle: (c) => {
    const B = belly(c), E = eyeInk(c);
    const leg = (x) => `<path d="M${x} 82 q-3 10 0 14 q5 2 9 0 q2 -8 -1 -14 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(58, 110, 33)}
    <g class="tail-wag">
      ${tube("M32 80 Q14 84 9 98", c.body, c.line, 7)}
      ${[0, 1, 2].map(i => `<path d="M${26 - i * 6} ${84 + i * 4.5} l-1 -5 l4 1 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="breathe">
      ${leg(40)}${leg(74)}
      <path d="M30 80 Q30 50 60 48 Q90 50 90 80 Q60 90 30 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M38 72 Q60 62 82 72 M42 80 Q60 74 78 80" fill="none" stroke="${c.shade}" stroke-width="2.2" stroke-linecap="round" opacity=".8"/>
      <path d="M60 50 Q60 66 60 82" stroke="${c.shade}" stroke-width="1.6" opacity=".55"/>
      ${[0, 1, 2, 3].map(i => `<path d="M${30 + i * 3} ${80 - i * 2} l-4 3 l4 2 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="0.9" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M78 66 Q104 62 106 77 Q104 90 86 90 Q74 82 78 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M84 66 Q92 62 100 67" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" opacity=".6"/>
      <path d="M103 76 Q112 76 108 83 Q103 85 101 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M90 82 Q98 84 102 81" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(91, 73, 3, E)}
    </g>`;
  },

  // ── Leatherback Turtle — SWIMMING sideways, big sweeping flippers, ridged teardrop carapace (float, head right)
  leatherbackturtle: (c) => {
    const B = belly(c), E = eyeInk(c);
    const ridges = Array.from({ length: 5 }, (_, i) => `<path d="M30 ${54 + i * 4.5} Q60 ${48 + i * 4} 88 ${58 + i * 2.2}" fill="none" stroke="${c.shade}" stroke-width="1.5" stroke-linecap="round" opacity=".65"/>`).join("");
    return `
    ${floorShadow(58, 106, 27)}
    <g class="tail-wag">
      <path d="M56 58 Q34 38 16 42 Q28 52 34 60 Q22 58 14 64 Q34 72 58 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M40 76 Q28 90 38 96 Q48 90 50 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M24 64 Q28 44 60 44 Q86 44 94 62 Q86 80 60 82 Q32 80 24 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${ridges}
      <path d="M34 70 Q58 80 82 70" fill="none" stroke="${B}" stroke-width="3" stroke-linecap="round" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M86 56 Q104 54 104 65 Q102 73 90 73 Q82 65 86 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      ${eye(96, 61, 2.8, E)}
      ${smile(103, 64, 2, E)}
    </g>`;
  },

  // ── Poison Dart Frog — smooth alert little frog, bold contrasting SPOTS, eyes up top, wide happy grin
  poisondartfrog: (c) => {
    const B = belly(c), E = eyeInk(c);
    const hind = `<path d="M32 90 Q18 84 26 72 Q36 78 44 88 Q42 96 32 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>`;
    const front = `<path d="M42 84 q-3 9 -8 11" fill="none" stroke="${c.line}" stroke-width="4.6" stroke-linecap="round"/><path d="M42 84 q-3 9 -8 11" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/><path d="M34 95 l-4 2 m4 -2 l-1 4 m1 -4 l-4 -1" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>`;
    const spots = [[46, 66], [74, 66], [54, 80], [68, 80], [60, 62], [38, 76], [82, 76]]
      .map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>`).join("");
    return `
    ${floorShadow(60, 108, 29)}
    <g class="tail-wag">${hind}${mirror(hind)}</g>
    <g class="breathe">
      ${front}${mirror(front)}
      <path d="M32 82 Q30 56 60 54 Q90 56 88 82 Q60 96 32 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 70 Q60 88 80 70" fill="none" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/>
      ${spots}
    </g>
    <g class="head-tilt">
      <circle cx="46" cy="52" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${mirror(`<circle cx="46" cy="52" r="10" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>`)}
      ${eyes(46, 74, 51, 4, E)}
    </g>`;
  },

  // ── Bullfrog — BIG wide low frog, huge grin, prominent round eardrums (tympana) behind the eyes, puffed throat
  bullfrog: (c) => {
    const B = belly(c), E = eyeInk(c);
    const hind = `<path d="M28 92 Q12 86 22 72 Q34 78 44 90 Q42 98 28 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(60, 110, 35)}
    <g class="tail-wag">${hind}${mirror(hind)}</g>
    <g class="breathe">
      <path d="M22 84 Q22 60 60 58 Q98 60 98 84 Q60 98 22 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.4" stroke-linejoin="round"/>
      <path d="M34 72 Q60 92 86 72" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>
      <path d="M44 80 Q60 90 76 80 Q60 85 44 80 Z" fill="${B}"/>
    </g>
    <g class="head-tilt">
      <circle cx="44" cy="54" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      ${mirror(`<circle cx="44" cy="54" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>`)}
      <circle cx="30" cy="70" r="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      ${mirror(`<circle cx="30" cy="70" r="6.5" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`)}
      <circle cx="30" cy="70" r="1.8" fill="${c.line}"/><circle cx="90" cy="70" r="1.8" fill="${c.line}"/>
      ${eyes(44, 76, 52, 4.4, E)}
    </g>`;
  },

  // ── Fire Salamander — glossy stout amphibian, four splayed legs, BOLD irregular blotches, rounded head
  firesalamander: (c) => {
    const B = belly(c), E = eyeInk(c);
    const leg = (x, dy) => `<path d="M${x} ${dy > 0 ? 74 : 58} q${dy > 0 ? -6 : 6} ${dy} ${dy > 0 ? -11 : 11} ${dy * 1.1}" fill="none" stroke="${c.line}" stroke-width="5" stroke-linecap="round"/><path d="M${x} ${dy > 0 ? 74 : 58} q${dy > 0 ? -6 : 6} ${dy} ${dy > 0 ? -11 : 11} ${dy * 1.1}" fill="none" stroke="${c.body}" stroke-width="3" stroke-linecap="round"/>`;
    const blob = (x, y) => `<path d="M${x} ${y} q6 -5 11 0 q4 6 -2 10 q-8 3 -11 -3 q-2 -4 2 -7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`;
    return `
    ${floorShadow(56, 108, 31)}
    <g class="tail-wag">${tube("M38 66 Q16 66 10 82 Q8 92 16 92", c.body, c.line, 8)}</g>
    <g class="breathe">
      ${leg(48, 12)}${leg(72, 12)}${leg(48, -12)}${leg(72, -12)}
      <path d="M36 66 Q38 52 60 52 Q84 52 90 64 Q84 76 60 76 Q38 76 36 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${[[43, 58], [62, 55], [76, 60]].map(([x, y]) => blob(x, y)).join("")}
    </g>
    <g class="head-tilt">
      <path d="M84 60 Q104 57 104 68 Q102 76 88 76 Q78 70 84 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="92" cy="62" rx="4.2" ry="3" fill="${c.shade}" stroke="${c.line}" stroke-width="1.2"/>
      ${eye(95, 64, 2.8, E)}
      ${smile(102, 68, 2.2, E)}
    </g>`;
  },
};

export const ROSTER_REPTILES2 = [
  { n: "Green Anaconda",     e: "🐍", tier: 3, float: false },
  { n: "King Cobra",         e: "🐍", tier: 4, float: false },
  { n: "Boa Constrictor",    e: "🐍", tier: 3, float: false },
  { n: "Black Mamba",        e: "🐍", tier: 3, float: false },
  { n: "Gaboon Viper",       e: "🐍", tier: 3, float: false },
  { n: "Coral Snake",        e: "🐍", tier: 2, float: false },
  { n: "Garter Snake",       e: "🐍", tier: 1, float: false },
  { n: "Sidewinder",         e: "🐍", tier: 2, float: false },
  { n: "Green Anole",        e: "🦎", tier: 1, float: false },
  { n: "Blue-tongue Skink",  e: "🦎", tier: 2, float: false },
  { n: "Frilled Lizard",     e: "🦎", tier: 3, float: false },
  { n: "Thorny Devil",       e: "🦎", tier: 3, float: false },
  { n: "Marine Iguana",      e: "🦎", tier: 2, float: false },
  { n: "Tuatara",            e: "🦎", tier: 3, float: false },
  { n: "Caiman",             e: "🐊", tier: 2, float: false },
  { n: "Snapping Turtle",    e: "🐢", tier: 2, float: false },
  { n: "Leatherback Turtle", e: "🐢", tier: 3, float: true  },
  { n: "Poison Dart Frog",   e: "🐸", tier: 2, float: false },
  { n: "Bullfrog",           e: "🐸", tier: 1, float: false },
  { n: "Fire Salamander",    e: "🐸", tier: 2, float: false },
];
