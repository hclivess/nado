// robots.js — BESPOKE hand-drawn SVG art for ROBOTS (cute mechanical / cyber creatures — NADO Pets).
// Each entry is an original, on-spot drawing of ONE bot — no shared/parameterized bodies.
// Contract: inner markup of <svg viewBox="0 0 120 120">, bot centered ~(60,64), within x,y ∈ [8,114].
// The CHASSIS recolours from the coat `c`: c.body (plate fill), c.shade (accent/underside/panel),
// c.line (outline stroke). Only universal robot lights are fixed tints — glowing eyes #7fe3ff,
// panel highlight #eafff4, warning/thruster #ff7a1a. Bolts/seams derive from the coat via deepen/tint.
import { INK, ceye, floorShadow, belly, tint, deepen, tube, pom, mirror, eye, eyes, smile } from "../pets-draw.js";

const GLOW = "#7fe3ff";  // glowing lens eyes / status core
const HI = "#eafff4";    // bright panel highlight
const WARN = "#ff7a1a";  // warning light / thruster flame

// a steady glowing round robot lens-eye (with soft halo + catchlight)
const reye = (x, y, r = 4) =>
  `<circle cx="${x}" cy="${y}" r="${(r + 2.4).toFixed(1)}" fill="${GLOW}" opacity=".22"/>` +
  `<circle cx="${x}" cy="${y}" r="${r}" fill="${GLOW}" stroke="${INK}" stroke-width="1.4"/>` +
  `<circle cx="${(x - r * 0.3).toFixed(1)}" cy="${(y - r * 0.32).toFixed(1)}" r="${(r * 0.34).toFixed(1)}" fill="#fff"/>`;
const reyes = (x1, x2, y, r = 4) => reye(x1, y, r) + reye(x2, y, r);
// a wide glowing visor eye-bar (single sleek sensor)
const visor = (x, y, w, h) =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${(h / 2).toFixed(1)}" fill="${INK}"/>` +
  `<rect x="${(x + 2.5).toFixed(1)}" y="${(y + 2).toFixed(1)}" width="${(w - 5).toFixed(1)}" height="${(h - 4).toFixed(1)}" rx="${((h - 4) / 2).toFixed(1)}" fill="${GLOW}"/>` +
  `<circle cx="${(x + w * 0.26).toFixed(1)}" cy="${(y + h * 0.42).toFixed(1)}" r="1.4" fill="#fff"/>`;
// a thin antenna ending in a glowing bulb
const antenna = (x1, y1, x2, y2, col = WARN) =>
  `<path d="M${x1} ${y1} L${x2} ${y2}" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>` +
  `<circle cx="${x2}" cy="${y2}" r="4.4" fill="${col}" opacity=".22"/>` +
  `<circle cx="${x2}" cy="${y2}" r="2.4" fill="${col}" stroke="${INK}" stroke-width="0.8"/>`;
// a bolt / rivet dot
const bolt = (x, y, c, r = 1.7) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${deepen(c.body, 0.22)}" stroke="${c.line}" stroke-width="0.8"/>`;
// a status LED
const led = (x, y, col = WARN, r = 1.8) =>
  `<circle cx="${x}" cy="${y}" r="${(r + 1.4).toFixed(1)}" fill="${col}" opacity=".22"/><circle cx="${x}" cy="${y}" r="${r}" fill="${col}" stroke="${INK}" stroke-width="0.7"/>`;

export const ART_ROBOTS = {
  // ── Robo Dog — friendly boxy pup: cube head, hinged panel ears, antenna, chest light, block legs, aerial tail
  robodog: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 27)}
    <g class="tail-wag">
      <path d="M80 90 L97 82 L101 89 L86 97 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${led(100, 85, WARN, 2.2)}
    </g>
    <g class="breathe">
      <rect x="40" y="98" width="14" height="16" rx="5" fill="${c.shade}" stroke="${c.line}" stroke-width="3"/>
      <rect x="66" y="98" width="14" height="16" rx="5" fill="${c.shade}" stroke="${c.line}" stroke-width="3"/>
      <rect x="34" y="64" width="52" height="42" rx="14" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <rect x="46" y="78" width="28" height="24" rx="8" fill="${B}"/>
      ${led(60, 86, GLOW, 3)}
      <path d="M46 72 h28" stroke="${c.line}" stroke-width="1.2" opacity=".45"/>
      ${bolt(40, 70, c)}${bolt(80, 70, c)}${bolt(40, 100, c)}${bolt(80, 100, c)}
    </g>
    <g class="head-tilt">
      <rect x="33" y="30" width="11" height="22" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8"/>
      <rect x="76" y="30" width="11" height="22" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8"/>
      <rect x="39" y="34" width="42" height="38" rx="13" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      ${antenna(60, 34, 60, 20)}
      <rect x="47" y="56" width="26" height="14" rx="6" fill="${B}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M60 59 l-3.4 3.2 h6.8 Z" fill="${INK}"/>
      <path d="M60 62 v3.4" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${reyes(51, 69, 48, 4.2)}
      ${bolt(43, 38, c)}${bolt(77, 38, c)}
    </g>`;
  },

  // ── Mech Cat — sleek sitting cyber-cat: sharp blade ears, slit-lit face, seam plates, hooked servo tail
  mechcat: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      ${tube("M80 96 Q100 92 96 72", c.body, c.line, 7)}
      <path d="M96 74 l6 -3 l-1 7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M88 90 h6 M91 82 h5" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
    </g>
    <g class="breathe">
      <path d="M60 110 C38 110 34 92 38 76 C40 66 44 60 48 56 L42 34 L58 50 Q60 47 62 50 L78 34 L72 56 C76 60 80 66 82 76 C86 92 82 110 60 110 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M45 40 L54 51 Q49 53 47 57 Z" fill="${c.shade}"/><path d="M75 40 L66 51 Q71 53 73 57 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="80" rx="18" ry="15" fill="${B}"/>
      <path d="M45 74 h30" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
      ${led(60, 90, GLOW, 2.6)}
      <rect x="45" y="58" width="30" height="16" rx="7" fill="${deepen(c.body, 0.12)}" stroke="${c.line}" stroke-width="1.8"/>
      ${reyes(51, 69, 66, 4)}
      <path d="M60 72 l-2.6 2.6 h5.2 Z" fill="${INK}"/>
      <path d="M60 74.6 v2.6" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>
      <path d="M45 68 h-12 M45 72 h-12 M75 68 h12 M75 72 h12" stroke="${GLOW}" stroke-width="1.1" stroke-linecap="round" opacity=".6"/>
      <path d="M48 55 h24" stroke="${c.line}" stroke-width="1.1" opacity=".45"/>
      ${led(43, 37, WARN, 1.5)}${led(77, 37, WARN, 1.5)}
      ${bolt(48, 62, c)}${bolt(72, 62, c)}
    </g>`;
  },

  // ── Cyber Owl — round sentry-owl: twin goggle lenses, ear-tuft antennae, folded plate wings, talon clamps (float)
  cyberowl: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      <path d="M34 62 Q24 48 30 40 Q40 44 44 58 Q40 74 33 82 Q28 72 34 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M86 62 Q96 48 90 40 Q80 44 76 58 Q80 74 87 82 Q92 72 86 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M60 30 Q86 32 86 62 Q86 92 60 96 Q34 92 34 62 Q34 32 60 30 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 60 Q76 62 74 82 Q68 92 60 92 Q52 92 46 82 Q44 62 60 60 Z" fill="${B}"/>
      <path d="M50 78 h20 M52 84 h16" stroke="${c.line}" stroke-width="1" opacity=".4"/>
      ${bolt(40, 50, c)}${bolt(80, 50, c)}
    </g>
    <g class="head-tilt">
      ${antenna(46, 34, 40, 20)}${antenna(74, 34, 80, 20)}
      <circle cx="49" cy="52" r="12" fill="${deepen(c.body, 0.15)}" stroke="${c.line}" stroke-width="2.6"/>
      <circle cx="71" cy="52" r="12" fill="${deepen(c.body, 0.15)}" stroke="${c.line}" stroke-width="2.6"/>
      ${reye(49, 52, 6.5)}${reye(71, 52, 6.5)}
      <path d="M55 60 L60 70 L65 60 Z" fill="#f2a03b" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <path d="M50 96 l-3 8 m3 -8 l0 9 m0 -9 l3 8 M70 96 l-3 8 m3 -8 l0 9 m0 -9 l3 8" stroke="#f2a03b" stroke-width="2.2" stroke-linecap="round"/>`;
  },

  // ── Drone Bee — chubby quad-rotor bee: banded body, glass dome eyes, spinning rotor arms, spark stinger (float)
  dronebee: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 22)}
    <g class="tail-wag">
      <path d="M40 48 L18 40" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>
      <path d="M80 48 L102 40" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>
      <ellipse cx="18" cy="40" rx="16" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" opacity=".9"/>
      <ellipse cx="102" cy="40" rx="16" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" opacity=".9"/>
      ${led(18, 40, WARN, 1.6)}${led(102, 40, WARN, 1.6)}
    </g>
    <g class="breathe">
      <path d="M60 94 L54 106 Q60 110 66 106 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="72" rx="30" ry="26" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M40 62 Q60 58 80 62 L80 68 Q60 64 40 68 Z" fill="${c.shade}"/>
      <path d="M35 78 Q60 74 85 78 L84 86 Q60 82 36 86 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="76" rx="16" ry="12" fill="${B}" opacity=".7"/>
      ${bolt(60, 52, c)}
    </g>
    <g class="head-tilt">
      ${reyes(51, 69, 70, 5)}
      <path d="M53 84 Q60 90 67 84" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${antenna(52, 50, 48, 40)}${antenna(68, 50, 72, 40)}
    </g>`;
  },

  // ── Android — friendly humanoid bot: dome head + antenna, chest core panel, jointed arms & legs, mouth grille
  android: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 24)}
    <g class="breathe">
      ${tube("M40 66 Q30 78 32 92", c.body, c.line, 7)}
      ${tube("M80 66 Q90 78 88 92", c.body, c.line, 7)}
      <circle cx="32" cy="94" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="88" cy="94" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      <rect x="46" y="98" width="12" height="15" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      <rect x="62" y="98" width="12" height="15" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      <rect x="38" y="62" width="44" height="42" rx="12" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <rect x="49" y="72" width="22" height="24" rx="6" fill="${B}"/>
      ${led(60, 84, GLOW, 3.2)}
      <path d="M49 96 h22" stroke="${c.line}" stroke-width="1.1" opacity=".45"/>
      ${bolt(44, 68, c)}${bolt(76, 68, c)}
    </g>
    <g class="head-tilt">
      ${antenna(60, 30, 60, 18)}
      <rect x="42" y="30" width="36" height="32" rx="13" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <rect x="47" y="38" width="26" height="16" rx="7" fill="${deepen(c.body, 0.15)}" stroke="${c.line}" stroke-width="1.8"/>
      ${reyes(53, 67, 46, 3.8)}
      <path d="M52 56 h16 M54 58.5 h12" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".7"/>
      ${bolt(46, 34, c)}${bolt(74, 34, c)}
    </g>`;
  },

  // ── Nanobot — tiny hover-orb: single big lens, bolted equator, thruster fins, orbiting sensor ring, antenna (float)
  nanobot: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 110, 16)}
    <g class="tail-wag">
      <path d="M34 58 L24 52 L26 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M86 58 L96 52 L94 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${led(24, 58, WARN, 1.6)}${led(96, 58, WARN, 1.6)}
    </g>
    <g class="breathe">
      <circle cx="60" cy="62" r="30" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M31 60 Q60 54 89 60 L88 66 Q60 60 32 66 Z" fill="${c.shade}"/>
      ${bolt(34, 56, c)}${bolt(86, 56, c)}${bolt(34, 70, c)}${bolt(86, 70, c)}
      <circle cx="60" cy="62" r="15" fill="${deepen(c.body, 0.15)}" stroke="${c.line}" stroke-width="2.2"/>
      ${reye(60, 61, 9)}
      ${antenna(60, 32, 60, 20, GLOW)}
      <ellipse cx="60" cy="62" rx="40" ry="12" fill="none" stroke="${GLOW}" stroke-width="1.6" opacity=".55"/>
    </g>`;
  },

  // ── Battle Mech — chunky war-frame: hulking pauldrons, cockpit visor head, piston arms & fists, shoulder cannon
  battlemech: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 114, 30)}
    <g class="breathe">
      <rect x="34" y="94" width="20" height="20" rx="5" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2"/>
      <rect x="66" y="94" width="20" height="20" rx="5" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M40 66 L80 66 L86 96 L34 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 74 L70 74 L73 92 L47 92 Z" fill="${B}"/>
      ${led(60, 82, GLOW, 3.6)}
      <path d="M44 70 l4 6 M76 70 l-4 6" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      <path d="M22 58 L44 54 L48 84 L24 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M96 58 L74 54 L70 84 L94 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <rect x="14" y="46" width="16" height="10" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      ${led(22, 51, WARN, 1.8)}
      <rect x="24" y="82" width="16" height="16" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="3"/>
      <rect x="80" y="82" width="16" height="16" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="3"/>
      ${bolt(29, 62, c)}${bolt(91, 62, c)}
    </g>
    <g class="head-tilt">
      <rect x="48" y="40" width="24" height="24" rx="7" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      ${antenna(52, 40, 46, 28)}
      ${visor(52, 48, 16, 9)}
      ${bolt(52, 60, c)}${bolt(68, 60, c)}
    </g>`;
  },

  // ── Servo Bot — cheerful boxy helper: trapezoid head + antenna, twin lenses, button chest, stub arms, rocker base
  servobot: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      ${tube("M40 76 Q28 78 26 88", c.body, c.line, 6)}
      ${tube("M80 76 Q92 78 94 88", c.body, c.line, 6)}
      <circle cx="26" cy="90" r="4.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="94" cy="90" r="4.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
    </g>
    <g class="breathe">
      <path d="M38 104 Q38 72 60 72 Q82 72 82 104 Q60 110 38 104 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <rect x="47" y="82" width="26" height="20" rx="6" fill="${B}"/>
      ${led(53, 89, WARN, 2)}${led(67, 89, GLOW, 2)}
      <path d="M53 97 h14" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      ${bolt(43, 78, c)}${bolt(77, 78, c)}
    </g>
    <g class="head-tilt">
      ${antenna(60, 34, 60, 22, GLOW)}
      <path d="M44 62 L48 38 L72 38 L76 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <rect x="49" y="44" width="22" height="12" rx="6" fill="${deepen(c.body, 0.15)}" stroke="${c.line}" stroke-width="1.8"/>
      ${reyes(55, 65, 50, 3.6)}
      ${bolt(49, 60, c)}${bolt(71, 60, c)}
    </g>`;
  },

  // ── Chrome Fox — sleek cyber-fox: blade ears, tapered snout, chrome cheek streaks, segmented brush tail
  chromefox: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 26)}
    <g class="tail-wag">
      <path d="M78 94 Q104 92 100 68 Q96 58 86 62 Q94 70 88 82 Q82 92 72 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M92 72 Q99 70 99 66 M90 82 Q96 82 97 78" fill="none" stroke="${HI}" stroke-width="1.6" stroke-linecap="round" opacity=".8"/>
      <path d="M86 88 Q92 86 96 82" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
    </g>
    <g class="breathe">
      <path d="M60 110 C40 110 36 92 40 78 C42 68 46 62 50 58 L60 58 L70 58 C74 62 78 68 80 78 C84 92 80 110 60 110 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M50 66 Q60 62 70 66 L66 96 Q60 100 54 96 Z" fill="${B}"/>
      ${led(60, 88, GLOW, 2.6)}
      ${bolt(44, 74, c)}${bolt(76, 74, c)}
    </g>
    <g class="head-tilt">
      <path d="M45 46 L38 20 L58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M47 42 L43 26 L54 40 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M45 46 L38 20 L58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/><path d="M47 42 L43 26 L54 40 Z" fill="${c.shade}"/>`)}
      <path d="M42 50 Q42 66 60 78 Q78 66 78 50 Q60 42 42 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M52 62 L60 78 L68 62 Q60 66 52 62 Z" fill="${B}"/>
      <path d="M60 74 l-2.4 2.4 h4.8 Z" fill="${INK}"/>
      <path d="M46 56 h-10 M78 56 h10" stroke="${HI}" stroke-width="1.4" stroke-linecap="round" opacity=".7"/>
      ${reyes(51, 69, 55, 3.8)}
    </g>`;
  },

  // ── Steel Golem — bolted iron titan: slab body, glowing power-core, riveted brow, block fists, stumpy legs
  steelgolem: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 30)}
    <g class="tail-wag">
      <path d="M30 62 L18 66 L18 82 L32 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M90 62 L102 66 L102 82 L88 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M34 60 L58 55 L86 60 L88 96 L60 102 L32 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 68 L74 68 L76 90 L44 90 Z" fill="${B}"/>
      ${led(60, 79, GLOW, 4)}
      <path d="M46 68 L44 90 M74 68 L76 90" stroke="${c.line}" stroke-width="1.2" opacity=".45"/>
      <path d="M40 90 L34 102 L48 102 Z M74 90 L72 102 L86 102 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      ${bolt(38, 64, c)}${bolt(82, 64, c)}${bolt(38, 92, c)}${bolt(82, 92, c)}
    </g>
    <g class="head-tilt">
      <path d="M42 34 L60 30 L78 34 L78 54 L60 58 L42 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <rect x="47" y="40" width="26" height="10" rx="3" fill="${deepen(c.body, 0.15)}" stroke="${c.line}" stroke-width="1.8"/>
      ${reyes(53, 67, 45, 3.4)}
      <path d="M52 54 h16" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      ${bolt(46, 36, c)}${bolt(74, 36, c)}
    </g>`;
  },

  // ── Circuit Serpent — segmented data-snake: coiled plated body, glowing seams, sensor head, forked scanner
  circuitserpent: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 27)}
    <g class="tail-wag">
      ${tube("M60 92 Q92 94 92 72 Q92 56 74 58", c.body, c.line, 12)}
      <path d="M74 58 l8 -5 l-1 9 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${tube("M74 60 Q40 60 34 76 Q30 92 56 94 Q80 94 60 92", c.body, c.line, 13)}
      <path d="M40 66 h1 M50 62 h1 M62 62 h1 M46 88 h1 M58 90 h1 M70 88 h1" stroke="${c.line}" stroke-width="0.1" opacity="0"/>
      ${[[42, 68], [52, 64], [64, 64], [74, 70], [50, 88], [62, 90]].map(([x, y]) => led(x, y, GLOW, 1.6)).join("")}
      <path d="M40 74 q6 6 12 0 M54 74 q6 6 12 0" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>
    </g>
    <g class="head-tilt">
      <path d="M28 62 Q28 46 44 46 Q58 46 58 60 Q58 72 42 72 Q28 72 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M28 58 L14 54 M28 62 L14 66" stroke="${GLOW}" stroke-width="2" stroke-linecap="round"/>
      ${antenna(44, 46, 40, 32, WARN)}
      <path d="M32 64 Q42 68 52 64" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      ${reye(42, 58, 4.4)}
      ${bolt(50, 52, c)}
    </g>`;
  },

  // ── Laser Hound — sleek attack-dog: swept visor, dorsal fins, shoulder emitter, blade legs, whip aerial tail
  laserhound: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 27)}
    <g class="tail-wag">
      <path d="M78 88 L100 74 L102 80 L84 94 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      ${led(100, 76, WARN, 2)}
    </g>
    <g class="breathe">
      <rect x="42" y="96" width="11" height="17" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8"/>
      <rect x="67" y="96" width="11" height="17" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M52 54 L60 48 L68 54 M60 48 L60 62" stroke="${c.shade}" stroke-width="3" stroke-linecap="round" fill="none"/>
      <path d="M34 78 Q34 60 60 58 Q86 60 86 78 Q84 98 60 100 Q36 98 34 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 70 Q60 66 74 70 L70 94 Q60 98 50 94 Z" fill="${B}"/>
      <rect x="72" y="64" width="12" height="9" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2"/>
      ${led(78, 68, WARN, 2)}
      ${bolt(42, 74, c)}${bolt(60, 90, c)}
    </g>
    <g class="head-tilt">
      <path d="M46 40 L40 26 L54 36 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M74 40 L80 26 L66 36 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 46 Q40 62 60 68 Q80 62 80 46 Q60 38 40 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M54 60 L60 68 L66 60 Z" fill="${INK}"/>
      ${visor(46, 48, 28, 8)}
      ${bolt(45, 44, c)}${bolt(75, 44, c)}
    </g>`;
  },

  // ── Rocket Bunny — hoppy jet-bunny: tall thruster ears with flame, round hull, booster feet, glossy lenses
  rocketbunny: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 113, 24)}
    <g class="tail-wag">
      <path d="M46 32 Q42 12 50 8 Q56 14 54 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M74 32 Q78 12 70 8 Q64 14 66 34 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M47 30 h6 M67 30 h6" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
      <path d="M50 34 Q50 44 50 50 Q46 44 47 36 Z" fill="${WARN}" opacity=".85"/>
      <path d="M70 34 Q70 44 70 50 Q74 44 73 36 Z" fill="${WARN}" opacity=".85"/>
      <circle cx="50" cy="33" r="3" fill="${WARN}"/><circle cx="70" cy="33" r="3" fill="${WARN}"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="76" rx="26" ry="24" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M60 58 Q78 60 76 84 Q70 96 60 96 Q50 96 44 84 Q42 60 60 58 Z" fill="${B}"/>
      ${led(60, 88, GLOW, 2.6)}
      ${bolt(42, 66, c)}${bolt(78, 66, c)}
      <path d="M48 100 Q52 108 46 110 Q42 106 44 100 Z" fill="${WARN}" opacity=".8"/>
      <path d="M72 100 Q68 108 74 110 Q78 106 76 100 Z" fill="${WARN}" opacity=".8"/>
    </g>
    <g class="head-tilt">
      ${reyes(51, 69, 72, 4.2)}
      <path d="M60 80 l-2.6 2.6 h5.2 Z" fill="${INK}"/>
      <path d="M60 82.6 q-4 3 -7 2 M60 82.6 q4 3 7 2" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M44 74 h-10 M46 79 h-11 M76 74 h10 M74 79 h11" stroke="${GLOW}" stroke-width="1" stroke-linecap="round" opacity=".5"/>
    </g>`;
  },

  // ── Turbo Turtle — wheeled roller-turtle: fat tread tire-shell with hub core, poking head, stub feet, bolt tail
  turboturtle: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 30)}
    <g class="tail-wag">
      <path d="M30 84 L18 82 L20 90 L32 90 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <rect x="36" y="94" width="13" height="14" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8"/>
      <rect x="71" y="94" width="13" height="14" rx="4" fill="${c.shade}" stroke="${c.line}" stroke-width="2.8"/>
      <circle cx="60" cy="72" r="34" fill="${deepen(c.body, 0.2)}" stroke="${c.line}" stroke-width="3.2"/>
      ${Array.from({ length: 12 }, (_, i) => { const a = i * 30 * Math.PI / 180, x1 = 60 + 30 * Math.cos(a), y1 = 72 + 30 * Math.sin(a), x2 = 60 + 34 * Math.cos(a), y2 = 72 + 34 * Math.sin(a); return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} L${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${c.line}" stroke-width="2"/>`; }).join("")}
      <circle cx="60" cy="72" r="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <circle cx="60" cy="72" r="10" fill="${B}" stroke="${c.line}" stroke-width="2"/>
      ${led(60, 72, GLOW, 4)}
      ${[0, 90, 180, 270].map((d) => { const a = d * Math.PI / 180; return bolt((60 + 15 * Math.cos(a)).toFixed(1), (72 + 15 * Math.sin(a)).toFixed(1), c); }).join("")}
    </g>
    <g class="head-tilt">
      <path d="M84 68 Q100 66 102 78 Q100 88 88 86 Q80 82 82 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      ${antenna(92, 66, 96, 56, WARN)}
      ${reye(96, 76, 3.6)}
      <path d="M90 82 q6 2 10 -1" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    </g>`;
  },

  // ── Pixel Sprite — voxel critter: stepped blocky body, pixel antenna, square lit eyes, pixel grin, drifting bits
  pixelsprite: (c) => {
    const B = belly(c);
    const px = (x, y, col) => `<rect x="${x}" y="${y}" width="6" height="6" fill="${col}"/>`;
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">
      ${px(20, 44, GLOW)}${px(96, 52, WARN)}${px(26, 92, GLOW)}${px(92, 90, GLOW)}
    </g>
    <g class="breathe">
      <path d="M42 42 L48 42 L48 36 L54 36 L54 42 L66 42 L66 36 L72 36 L72 42 L84 42 L84 96 L36 96 L36 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <rect x="46" y="70" width="28" height="22" fill="${B}"/>
      ${led(60, 81, GLOW, 3)}
      <path d="M46 62 h28" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>
      ${bolt(42, 48, c)}${bolt(78, 48, c)}
    </g>
    <g class="head-tilt">
      <rect x="49" y="50" width="9" height="9" fill="${GLOW}" stroke="${INK}" stroke-width="1.4"/>
      <rect x="62" y="50" width="9" height="9" fill="${GLOW}" stroke="${INK}" stroke-width="1.4"/>
      <rect x="51" y="52" width="3" height="3" fill="#fff"/><rect x="64" y="52" width="3" height="3" fill="#fff"/>
      <path d="M50 62 h4 v4 h4 v-4 h4 v4 h4 v-4 h4" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="square"/>
    </g>`;
  },

  // ── Gear Beetle — clockwork beetle: domed elytra shell with seam, cog side-wings, pincer head, six wire legs
  gearbeetle: (c) => {
    const B = belly(c);
    const cog = (cx, cy, r) => {
      const teeth = Array.from({ length: 8 }, (_, i) => { const a = i * 45 * Math.PI / 180, x = cx + r * Math.cos(a), y = cy + r * Math.sin(a); return `<rect x="${(x - 2.4).toFixed(1)}" y="${(y - 2.4).toFixed(1)}" width="4.8" height="4.8" rx="1" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" transform="rotate(${i * 45} ${x.toFixed(1)} ${y.toFixed(1)})"/>`; }).join("");
      return `${teeth}<circle cx="${cx}" cy="${cy}" r="${r}" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/><circle cx="${cx}" cy="${cy}" r="${(r * 0.4).toFixed(1)}" fill="${deepen(c.body, 0.2)}" stroke="${c.line}" stroke-width="1.4"/>`;
    };
    return `
    ${floorShadow(60, 112, 27)}
    <g class="tail-wag">
      ${cog(28, 66, 12)}${cog(92, 66, 12)}
    </g>
    <g class="breathe">
      <path d="M40 56 L60 46 L80 56 L80 82 Q80 100 60 102 Q40 100 40 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 48 L60 100" stroke="${c.line}" stroke-width="2" opacity=".6"/>
      <path d="M46 62 Q60 58 74 62" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".45"/>
      ${led(50, 74, GLOW, 2.2)}${led(70, 74, GLOW, 2.2)}
      ${[[44, 84], [76, 84], [42, 94], [78, 94]].map(([x, y]) => bolt(x, y, c)).join("")}
      <path d="M40 70 l-14 6 M40 82 l-13 8 M80 70 l14 6 M80 82 l13 8" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M52 40 L48 30 L54 36 M68 40 L72 30 L66 36" stroke="${INK}" stroke-width="2" fill="none" stroke-linecap="round"/>
      <circle cx="60" cy="46" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M50 46 Q60 42 70 46 L68 54 Q60 58 52 54 Z" fill="${B}"/>
      ${reyes(54, 66, 45, 3.6)}
    </g>`;
  },

  // ── Plasma Wisp — floating energy spirit: glowing flame hull, halo aura, inner core, wispy sparks, bright face
  plasmawisp: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 18)}
    <g class="tail-wag">
      <circle cx="34" cy="46" r="3" fill="${GLOW}" opacity=".7"/>
      <circle cx="88" cy="52" r="2.4" fill="${GLOW}" opacity=".7"/>
      <circle cx="80" cy="34" r="2" fill="${WARN}" opacity=".7"/>
      <circle cx="42" cy="30" r="2" fill="${GLOW}" opacity=".6"/>
    </g>
    <g class="breathe">
      <ellipse cx="60" cy="68" rx="34" ry="34" fill="${GLOW}" opacity=".16"/>
      <path d="M60 26 Q74 44 78 62 Q82 84 60 100 Q38 84 42 62 Q46 44 60 26 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 46 Q70 58 70 72 Q70 86 60 92 Q50 86 50 72 Q50 58 60 46 Z" fill="${B}"/>
      <path d="M60 54 Q66 62 66 72 Q66 82 60 86 Q54 82 54 72 Q54 62 60 54 Z" fill="${GLOW}" opacity=".55"/>
    </g>
    <g class="head-tilt">
      ${reyes(53, 67, 66, 4)}
      ${smile(60, 74, 3.6, INK)}
      <circle cx="47" cy="70" r="2.6" fill="${WARN}" opacity=".35"/><circle cx="73" cy="70" r="2.6" fill="${WARN}" opacity=".35"/>
    </g>`;
  },

  // ── Titan Rex — mecha tyrannosaur: armored jaw, cockpit visor, dorsal fins, piston legs, small arms, segmented tail
  titanrex: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(58, 113, 32)}
    <g class="tail-wag">
      ${tube("M40 78 Q16 82 10 62 Q7 52 18 50", c.body, c.line, 10)}
      <path d="M18 50 l-9 -4 l3 9 l-9 0 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      ${[44, 56, 68].map((x) => `<path d="M${x} 58 L${x + 5} 46 L${x + 10} 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`).join("")}
      <path d="M34 82 Q34 60 54 56 Q76 54 84 66 Q90 74 86 82 Q80 92 70 90 L70 104 L60 104 L60 90 L48 90 L48 104 L38 104 L38 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M46 78 Q62 86 82 78 Q64 84 46 78 Z" fill="${B}"/>
      <path d="M50 88 h8 M60 88 h10" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>
      <path d="M70 68 q10 2 12 8" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>
      <path d="M52 100 l-3 4 m3 -4 l0 5 m0 -5 l3 4 M42 100 l-3 4 m3 -4 l0 5 m0 -5 l3 4" stroke="${INK}" stroke-width="1.8" stroke-linecap="round"/>
      ${led(58, 74, WARN, 2.4)}
      ${bolt(42, 70, c)}
    </g>
    <g class="head-tilt">
      <path d="M78 58 Q78 44 96 44 Q112 44 112 58 Q112 66 104 68 L114 70 Q112 78 100 76 Q80 74 78 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M100 70 l2 5 l2 -5 Z M106 70 l2 5 l2 -5 Z" fill="#fff" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      ${visor(88, 52, 20, 8)}
      ${bolt(84, 62, c)}
    </g>`;
  },

  // ── Neon Moth — luminous cyber-moth: broad neon wings with glow ocelli, fuzzy plated body, feathered antennae (float)
  neonmoth: (c) => {
    const B = belly(c);
    const wing = `
      <path d="M58 60 Q30 38 16 48 Q22 58 32 60 Q20 66 22 80 Q40 76 58 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M56 62 Q38 50 28 54 Q36 58 40 64 Z" fill="${c.shade}"/>
      <circle cx="34" cy="56" r="4" fill="${GLOW}" opacity=".8"/><circle cx="30" cy="70" r="3" fill="${WARN}" opacity=".75"/>`;
    return `
    ${floorShadow(60, 112, 24)}
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M60 44 Q72 46 72 62 L70 90 Q60 96 50 90 L48 62 Q48 46 60 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M53 62 h14 M52 70 h16 M52 78 h16 M53 86 h14" stroke="${c.line}" stroke-width="1.4" opacity=".5"/>
      <path d="M55 60 Q60 58 65 60 L64 88 Q60 92 56 88 Z" fill="${B}" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M52 42 Q46 28 38 24 Q44 34 46 44" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>
      <path d="M68 42 Q74 28 82 24 Q76 34 74 44" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>
      <path d="M42 26 l-4 2 m4 -2 l-1 4 M78 26 l4 2 m-4 -2 l1 4" stroke="${INK}" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="60" cy="48" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      ${reyes(54, 66, 47, 3.8)}
      ${smile(60, 53, 3, INK)}
    </g>`;
  },

  // ── Quantum Slime — glitchy digital blob: wobbly hull with chromatic glitch-shift, floating data bits, lit face (float)
  quantumslime: (c) => {
    const B = belly(c);
    return `
    ${floorShadow(60, 112, 28)}
    <g class="tail-wag">
      <rect x="24" y="48" width="6" height="6" fill="${GLOW}" opacity=".8"/>
      <rect x="90" y="44" width="6" height="6" fill="${WARN}" opacity=".8"/>
      <rect x="94" y="70" width="5" height="5" fill="${GLOW}" opacity=".7"/>
      <rect x="22" y="74" width="5" height="5" fill="${GLOW}" opacity=".7"/>
    </g>
    <g class="breathe">
      <path d="M28 66 Q28 40 60 40 Q92 40 92 66 Q92 92 86 98 Q80 92 74 98 Q68 92 62 98 Q56 92 50 98 Q44 92 38 98 Q32 92 34 98 Q26 92 28 66 Z" fill="${GLOW}" opacity=".35" transform="translate(-3 0)"/>
      <path d="M28 66 Q28 40 60 40 Q92 40 92 66 Q92 92 86 98 Q80 92 74 98 Q68 92 62 98 Q56 92 50 98 Q44 92 38 98 Q32 92 34 98 Q26 92 28 66 Z" fill="${WARN}" opacity=".3" transform="translate(3 0)"/>
      <path d="M28 66 Q28 40 60 40 Q92 40 92 66 Q92 92 86 98 Q80 92 74 98 Q68 92 62 98 Q56 92 50 98 Q44 92 38 98 Q32 92 34 98 Q26 92 28 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 50 Q54 42 66 46 Q52 50 46 58 Z" fill="${HI}" opacity=".5"/>
      <rect x="44" y="60" width="7" height="4" fill="${GLOW}" opacity=".5"/><rect x="70" y="78" width="6" height="4" fill="${WARN}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      ${reyes(51, 69, 68, 4.2)}
      <path d="M52 78 h4 v3 h5 v-3 h4 v3 h4" fill="none" stroke="${INK}" stroke-width="2" stroke-linecap="square"/>
      <circle cx="44" cy="72" r="2.6" fill="${GLOW}" opacity=".4"/><circle cx="76" cy="72" r="2.6" fill="${GLOW}" opacity=".4"/>
    </g>`;
  },
};

export const ROSTER_ROBOTS = [
  { n: "Robo Dog",        e: "🤖", tier: 2, float: false },
  { n: "Mech Cat",        e: "🐱", tier: 2, float: false },
  { n: "Cyber Owl",       e: "🦉", tier: 3, float: true },
  { n: "Drone Bee",       e: "🐝", tier: 2, float: true },
  { n: "Android",         e: "🤖", tier: 3, float: false },
  { n: "Nanobot",         e: "⚙️", tier: 2, float: true },
  { n: "Battle Mech",     e: "🦾", tier: 4, float: false },
  { n: "Servo Bot",       e: "🔧", tier: 2, float: false },
  { n: "Chrome Fox",      e: "🦊", tier: 3, float: false },
  { n: "Steel Golem",     e: "🗿", tier: 3, float: false },
  { n: "Circuit Serpent", e: "🐍", tier: 3, float: false },
  { n: "Laser Hound",     e: "🐕", tier: 3, float: false },
  { n: "Rocket Bunny",    e: "🐰", tier: 2, float: false },
  { n: "Turbo Turtle",    e: "🐢", tier: 2, float: false },
  { n: "Pixel Sprite",    e: "👾", tier: 2, float: false },
  { n: "Gear Beetle",     e: "🪲", tier: 2, float: false },
  { n: "Plasma Wisp",     e: "🔮", tier: 3, float: true },
  { n: "Titan Rex",       e: "🦖", tier: 5, float: false },
  { n: "Neon Moth",       e: "🦋", tier: 3, float: true },
  { n: "Quantum Slime",   e: "🟩", tier: 4, float: false },
];
