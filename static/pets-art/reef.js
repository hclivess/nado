// pets-art/reef.js — BESPOKE hand-drawn SVG art for the OCEAN FISH & CORAL REEF batch of NADO Pets.
// Each entry: slug -> (c) => "<svg inner markup string>" for <svg viewBox="0 0 120 120">.
// Coat: c.body (main fill), c.shade (underside/accent), c.line (outline). All aquatic => float:true,
// bodies oriented HORIZONTALLY, head to the RIGHT (nautilus / sea dragon stand upright). Helpers from
// ../pets-draw.js. Fixed bone/tooth/venom/spark accents below; nose/eyes = INK/eyeInk.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror, belly } from "../pets-draw.js";

const IVORY = "#f2e6c8"; // bills / swords / beaks / tusk-ivory
const TOOTH = "#fff";    // teeth / fangs
const SPARK = "#f7d038"; // electric-eel lightning
const VENOM = "#f4c84a"; // lionfish venom-spine tips
const GILL = "#bcd6ea";  // pale wash highlight

export const ART_REEF = {
  // Manta Ray — top-down glider: vast triangular pectoral wings, forward cephalic head-fins, whip tail
  // Manta — flat winged diamond seen from above, gliding right: swept pectoral wings, forward cephalic
  // horns (the "devil ray" signature), tiny side eyes, a long whip tail trailing behind.
  mantaray: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      <path d="M46 60 Q28 60 12 63" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M46 60 Q28 60 12 63" fill="none" stroke="${c.body}" stroke-width="1.7" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M98 60 Q88 44 58 24 Q48 44 44 58 L44 62 Q48 76 58 96 Q88 76 98 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M92 60 Q80 47 62 35 Q54 48 50 58 L50 62 Q54 72 62 85 Q80 73 92 60 Z" fill="${B}" opacity=".4"/>
      <path d="M84 54 Q70 44 60 32 M84 66 Q70 76 60 88" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".35"/>
    </g>
    <g class="head-tilt">
      <path d="M96 55 Q105 51 108 53 Q104 56 98 57 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M96 65 Q105 69 108 67 Q104 64 98 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M95 60 q5 0 8 0" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".5"/>
      ${eye(87, 54, 2.3, E)}${eye(87, 66, 2.3, E)}
    </g>`; },

  // Hammerhead Shark — torpedo body + the mallet cephalofoil head with an eye at each far tip
  hammerheadshark: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M30 62 L10 40 Q18 62 10 84 L28 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q42 48 72 50 Q84 52 88 60 Q84 72 72 76 Q42 78 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M40 70 Q62 80 86 66 Q62 76 40 70 Z" fill="${c.shade}"/>
      <path d="M54 50 L60 30 L70 49 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M50 74 L56 88 L66 76 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M46 54 q-2 8 0 16 M52 54 q-2 8 0 16" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M84 46 Q96 40 102 46 Q104 62 102 78 Q96 84 84 78 Q80 62 84 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M85 52 q-3 10 0 20" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
      <ellipse cx="98" cy="47" rx="4" ry="4" fill="${c.shade}"/><ellipse cx="98" cy="77" rx="4" ry="4" fill="${c.shade}"/>
      ${eye(98, 47, 2.4, E)}${eye(98, 77, 2.4, E)}
      <path d="M84 66 q6 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`; },

  // Whale Shark — vast broad body, checker of pale spots, wide flat terminal mouth, tiny eye
  whaleshark: (c) => { const E = eyeInk(c);
    const spots = [];
    for (let r = 0; r < 4; r++) for (let q = 0; q < 6; q++) { const x = 38 + q * 10 + (r % 2 ? 5 : 0), y = 50 + r * 7; if (x > 92) continue; spots.push(`<circle cx="${x}" cy="${y}" r="1.9" fill="${c.shade}"/>`); }
    return `
    <g class="tail-wag"><path d="M26 62 L8 40 Q18 62 8 84 L26 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 62 Q36 42 74 44 Q98 46 104 62 Q98 80 74 82 Q36 82 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 76 Q70 88 100 68 Q70 82 40 76 Z" fill="${c.shade}"/>
      <path d="M56 46 L62 28 L74 47 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M46 78 L52 92 L64 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M34 56 q4 3 4 12 M40 54 q4 3 4 14" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".45"/>
      ${spots.join("")}
    </g>
    <g class="head-tilt">
      <path d="M90 64 Q98 61 104 64 Q104 71 98 71 Q92 71 90 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(94, 56, 2.2, E)}
    </g>`; },

  // Moray Eel — long body snaking from its lair, ridged dorsal, wide gaping fanged jaw
  morayeel: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag">
      ${tube("M12 76 Q6 68 14 62", c.body, c.line, 9)}
      <path d="M20 68 Q36 52 50 62 Q66 72 78 60" fill="none" stroke="${c.shade}" stroke-width="2.4" opacity=".55" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      ${tube("M12 76 Q28 52 46 64 Q66 78 80 60", c.body, c.line, 18)}
      <circle cx="34" cy="64" r="2" fill="${c.shade}" opacity=".7"/><circle cx="50" cy="67" r="1.8" fill="${c.shade}" opacity=".7"/><circle cx="24" cy="70" r="1.6" fill="${c.shade}" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M72 52 Q94 46 98 60 Q99 76 82 78 Q70 76 68 64 Q68 56 72 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M74 60 Q94 54 100 64 Q94 76 76 72 Q71 66 74 60 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 6 }, (_, i) => `<path d="M${77 + i * 4} 60 l1.4 4 l1.6 -4 Z" fill="${TOOTH}"/>`).join("")}
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${79 + i * 4} 71 l1.4 -4 l1.6 4 Z" fill="${TOOTH}"/>`).join("")}
      ${eye(82, 55, 2.6, E)}
    </g>`; },

  // Barracuda — long silver torpedo, twin dorsal fins, pointed snout, protruding fanged underbite
  barracuda: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M20 62 L8 50 Q14 62 8 74 L20 62 L8 62 Z M20 62 L10 50 Q16 62 10 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M20 62 Q42 52 80 55 Q100 57 108 61 Q100 65 80 69 Q42 72 20 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 66 Q72 71 104 61" fill="none" stroke="${c.shade}" stroke-width="4" opacity=".5" stroke-linecap="round"/>
      <path d="M46 56 L52 44 L58 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M64 56 L70 46 L76 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M50 68 L54 78 L62 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${[38, 52, 66].map((x) => `<circle cx="${x}" cy="60" r="1.6" fill="${c.shade}" opacity=".7"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M90 57 L108 61 L90 65 Q86 61 90 57 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M90 63 L106 62 M92 64 l3 3 M96 64 l3 3" stroke="${c.line}" stroke-width="1.1" opacity=".7"/>
      <path d="M91 60 l3 -3 M95 60 l3 -3" stroke="${TOOTH}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(84, 58, 2.8, E)}
    </g>`; },

  // Swordfish — long flat rigid sword bill, tall stiff sickle dorsal, forked tail, big eye
  swordfish: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M22 62 L8 48 Q16 62 8 76 Z M22 62 L14 55 L22 62 L14 69 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 62 Q40 48 66 50 Q82 52 90 60 Q82 70 66 74 Q40 76 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M40 70 Q64 78 88 64 Q64 74 40 70 Z" fill="${c.shade}"/>
      <path d="M52 50 Q56 22 66 34 Q62 44 60 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M50 72 Q54 88 64 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M88 58 L116 60 L116 62 L88 66 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M84 62 q4 3 8 1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(82, 56, 3.2, E)}
    </g>`; },

  // Marlin — round spear bill + huge raised sail dorsal, cobalt body with pale vertical bars
  marlin: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M22 62 L8 46 Q16 62 8 78 Z M20 62 L10 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 62 Q40 50 64 52 Q82 54 90 60 Q82 68 64 72 Q40 74 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M46 54 Q52 20 62 22 Q72 24 74 52 Q60 46 46 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${[50, 58, 66].map((x) => `<path d="M${x} 26 L${x - 2} 52" stroke="${c.line}" stroke-width="1" opacity=".5"/>`).join("")}
      <path d="M44 72 Q46 88 54 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${[36, 48, 60].map((x) => `<path d="M${x} 55 q-1 8 0 14" stroke="${GILL}" stroke-width="1.6" fill="none" opacity=".6"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M88 59 Q102 59 112 60 Q102 63 88 63 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(82, 57, 3, E)}
    </g>`; },

  // Tuna — muscular fusiform football, row of finlets to the lunate tail, sickle pectoral
  tuna: (c) => { const E = eyeInk(c);
    const finlets = Array.from({ length: 5 }, (_, i) => `<path d="M${30 + i * 6} 48 l3 -3 l0 5 Z" fill="${VENOM}" stroke="${c.line}" stroke-width="1"/><path d="M${30 + i * 6} 76 l3 3 l0 -5 Z" fill="${VENOM}" stroke="${c.line}" stroke-width="1"/>`).join("");
    return `
    <g class="tail-wag"><path d="M26 62 Q12 46 6 48 Q14 62 6 76 Q12 78 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q40 42 68 44 Q92 46 100 62 Q92 78 68 80 Q40 82 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 74 Q68 84 96 66 Q68 80 40 74 Z" fill="${c.shade}"/>
      <path d="M46 48 Q58 40 70 46 Q60 50 54 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M56 76 Q68 66 82 74 Q70 74 62 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${finlets}
    </g>
    <g class="head-tilt">
      <path d="M84 50 Q100 52 100 62 Q100 72 86 74 Q80 62 84 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M92 66 q6 3 8 -2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(90, 58, 3.2, E)}
    </g>`; },

  // Cuttlefish — broad flat mantle rimmed by an undulating fin skirt, zebra bands, W-pupil, arms
  cuttlefish: (c) => { const E = eyeInk(c);
    const skirt = (yb, dir) => Array.from({ length: 8 }, (_, i) => `M${26 + i * 8} ${yb} q4 ${dir * 5} 8 0`).join(" ");
    return `
    <g class="tail-wag">
      <path d="${skirt(50, -1)}" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".8"/>
      <path d="${skirt(74, 1)}" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".8"/>
    </g>
    <g class="breathe">
      <path d="M24 62 Q30 50 62 50 Q90 50 92 62 Q90 74 62 74 Q30 74 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${[36, 46, 56, 66].map((x) => `<path d="M${x} 54 q-2 8 0 16" stroke="${c.shade}" stroke-width="2" fill="none" opacity=".55"/>`).join("")}
    </g>
    <g class="head-tilt">
      ${[64, 70, 76, 82].map((x, i) => tube(`M${x} 68 Q${x + 8} ${74 + i} ${x + 14} ${70 + i * 2}`, c.body, c.line, 3)).join("")}
      ${tube("M82 60 Q98 58 104 50", c.shade, c.line, 3)}
      ${tube("M82 64 Q98 66 104 74", c.shade, c.line, 3)}
      <circle cx="80" cy="58" r="5.4" fill="${TOOTH}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M77 58 q3 3 6 0 q-3 -3 -6 0 Z" fill="${E}"/>
    </g>`; },

  // Nautilus — coiled striped spiral shell (upright), tentacle crown + leathery hood at the aperture
  nautilus: (c) => { const E = eyeInk(c);
    const cx = 50, cy = 60;
    const seam = []; for (let i = 0; i <= 44; i++) { const a = i / 44 * Math.PI * 2.7 - 0.5; const rr = 4 + i * 0.62; seam.push(`${(cx + rr * Math.cos(a)).toFixed(1)} ${(cy + rr * Math.sin(a)).toFixed(1)}`); }
    const stripes = []; for (let k = 0; k < 16; k++) { const a = (-170 + k * 17) * Math.PI / 180; if (a > -0.5 && a < 1.05) continue; const x1 = cx + 10 * Math.cos(a), y1 = cy + 10 * Math.sin(a), x2 = cx + 29 * Math.cos(a), y2 = cy + 29 * Math.sin(a); stripes.push(`<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${c.shade}" stroke-width="2.6" opacity=".55" stroke-linecap="round"/>`); }
    const tent = Array.from({ length: 7 }, (_, t) => { const a = (-34 + t * 15) * Math.PI / 180; return tube(`M78 63 Q${(90 + 4 * Math.cos(a)).toFixed(1)} ${(63 + 12 * Math.sin(a)).toFixed(1)} ${(96 + 6 * Math.cos(a)).toFixed(1)} ${(63 + 18 * Math.sin(a)).toFixed(1)}`, c.shade, c.line, 3); }).join("");
    return `
    <g class="tail-wag">${tent}</g>
    <g class="breathe">
      <circle cx="${cx}" cy="${cy}" r="30" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${stripes.join("")}
      <path d="M${seam.join(" L")}" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".7"/>
      <circle cx="${cx}" cy="${cy}" r="30" fill="none" stroke="${c.line}" stroke-width="2.6"/>
    </g>
    <g class="head-tilt">
      <path d="M72 46 Q92 48 90 62 Q88 78 72 78 Q66 62 72 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M74 48 Q86 50 85 60" fill="none" stroke="${c.shade}" stroke-width="2.2" opacity=".6"/>
      ${eye(80, 56, 2.8, E)}
    </g>`; },

  // Lionfish — striped body haloed by long banded venomous fin-rays, tips glowing gold
  lionfish: (c) => { const E = eyeInk(c);
    const ray = (x1, y1, x2, y2) => { const mx = (x1 + x2) / 2, my = (y1 + y2) / 2; return `${tube(`M${x1} ${y1} L${x2} ${y2}`, c.shade, c.line, 2.4)}<circle cx="${x2}" cy="${y2}" r="2.2" fill="${VENOM}" stroke="${c.line}" stroke-width="0.8"/><line x1="${(mx - 2).toFixed(1)}" y1="${my.toFixed(1)}" x2="${(mx + 2).toFixed(1)}" y2="${my.toFixed(1)}" stroke="${c.line}" stroke-width="1"/>`; };
    const dorsal = Array.from({ length: 7 }, (_, i) => { const a = (-140 + i * 15) * Math.PI / 180; return ray(46 + i * 5, 50, (46 + i * 5 + 30 * Math.cos(a)).toFixed(1), (50 + 30 * Math.sin(a)).toFixed(1)); }).join("");
    const pect = Array.from({ length: 6 }, (_, i) => { const a = (110 + i * 22) * Math.PI / 180; return ray(48, 68, (48 + 28 * Math.cos(a)).toFixed(1), (68 + 28 * Math.sin(a)).toFixed(1)); }).join("");
    return `
    <g class="tail-wag">${dorsal}${pect}</g>
    <g class="breathe">
      <ellipse cx="62" cy="62" rx="22" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.5"/>
      ${[50, 58, 66, 74].map((x) => `<path d="M${x} 50 q-3 12 0 24" stroke="${c.shade}" stroke-width="3" fill="none" opacity=".7" stroke-linecap="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M82 56 q-2 -8 4 -10 M86 58 q2 -8 8 -8" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M82 62 q8 3 14 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(80, 58, 3, E)}
    </g>`; },

  // Angelfish — tall laterally-flat disc, long trailing dorsal+anal sails, ventral filaments, bars
  angelfish: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag">
      <path d="M52 40 Q30 14 42 12 Q58 20 60 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M52 84 Q30 110 42 112 Q58 104 60 82 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 62 Q22 54 14 62 Q22 70 40 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M46 40 Q60 30 76 44 Q86 54 86 62 Q86 70 76 80 Q60 94 46 84 Q40 62 46 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${[56, 66, 76].map((x, i) => `<path d="M${x} ${38 + i * 2} Q${x - 3} 62 ${x} ${86 - i * 2}" stroke="${c.shade}" stroke-width="3.4" fill="none" opacity=".6"/>`).join("")}
      <path d="M56 80 Q54 100 58 104 M62 82 Q62 102 66 106" stroke="${c.shade}" stroke-width="2" fill="none" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 58 L94 62 L84 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${smile(88, 63, 2.2, E)}
      ${eye(80, 56, 3, E)}
    </g>`; },

  // Blue Tang — flat oval palette, pointed snout, comma "palette" mark, bright yellow crescent tail
  bluetang: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M30 62 Q16 46 10 50 Q18 62 10 74 Q16 78 30 62 Z" fill="${VENOM}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M30 62 Q44 46 70 48 Q92 50 100 60 Q92 72 70 76 Q44 78 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M48 50 Q66 44 80 52 Q70 66 58 76 Q48 66 48 50 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M40 48 Q54 42 68 48 M40 76 Q54 82 68 76" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".5" stroke-linecap="round"/>
      <path d="M32 62 q4 -4 4 -8 M32 62 q4 4 4 8" stroke="${c.shade}" stroke-width="1.4" fill="none"/>
    </g>
    <g class="head-tilt">
      <path d="M92 55 Q101 58 100 62 Q101 66 92 69 Q88 62 92 55 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${smile(96, 63, 2.2, E)}
      ${eye(88, 57, 3, E)}
    </g>`; },

  // Parrotfish — chunky reef fish with a fused-plate BEAK, blunt brow, big scales, fan tail
  parrotfish: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M28 62 Q12 48 8 52 Q16 62 8 72 Q12 76 28 62 L18 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q40 46 66 46 Q88 48 96 60 Q88 74 66 78 Q40 78 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 54 Q56 60 42 66 M52 50 Q66 60 52 70 M62 50 Q76 60 62 70" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".6"/>
      <path d="M50 46 Q62 38 74 46 Q64 50 58 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M52 78 Q62 86 74 78 Q64 80 58 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 52 Q98 52 98 60 Q94 62 84 62 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M84 64 Q96 64 96 72 Q90 74 84 72 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M88 54 v6 M92 54 v6 M88 66 v5 M92 66 v5" stroke="${c.line}" stroke-width="0.9" opacity=".6"/>
      ${eye(80, 56, 3, E)}
    </g>`; },

  // Triggerfish — rhomboid compressed body, erect first-dorsal trigger spine, undulating soft fins
  triggerfish: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag">
      <path d="M30 62 Q18 52 14 56 Q20 62 14 68 Q18 72 30 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 50 q8 -4 16 0 q8 -4 14 0" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".7" stroke-linecap="round"/>
      <path d="M40 74 q8 4 16 0 q8 4 14 0" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".7" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M30 62 L58 42 Q80 44 94 60 Q80 78 58 82 L30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M44 60 L62 50 L74 62 L62 74 Z" fill="${c.shade}" opacity=".45"/>
      ${[46, 54, 62].map((x) => `<path d="M${x} 50 l6 24" stroke="${c.shade}" stroke-width="1.4" opacity=".5"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M60 46 L58 30 L66 44 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M86 62 q6 2 10 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(78, 54, 3, E)}
    </g>`; },

  // Mahi Mahi — steep blunt forehead, single dorsal fin the whole back-length, slender forked tail
  mahimahi: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M22 62 Q10 48 6 50 Q14 62 6 74 Q10 76 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 62 Q42 56 66 54 Q82 50 88 34 Q96 40 96 56 Q96 68 88 72 Q60 76 42 70 Q30 66 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M30 60 Q50 52 74 46 Q84 42 88 36 L86 48 Q66 54 44 62 Q34 64 30 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round" opacity=".9"/>
      <path d="M46 70 Q52 84 60 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${[40, 52, 64].map((x, i) => `<circle cx="${x}" cy="${64 - i}" r="1.6" fill="${GILL}" opacity=".7"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M84 68 q6 2 10 -2" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
      ${eye(84, 60, 3.2, E)}
    </g>`; },

  // Grouper — heavy-bodied bass, thick protruding lower lip, big rounded fins, mottled blotches
  grouper: (c) => { const E = eyeInk(c);
    const blot = [[44, 56], [56, 66], [50, 70], [62, 54], [66, 68], [40, 64]].map(([x, y]) => `<ellipse cx="${x}" cy="${y}" rx="3.4" ry="2.6" fill="${c.shade}" opacity=".55"/>`).join("");
    return `
    <g class="tail-wag"><path d="M26 62 Q14 50 10 54 Q16 62 10 70 Q14 74 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q36 42 66 44 Q90 46 98 62 Q90 80 66 82 Q36 82 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 48 Q56 42 72 48 Q56 52 48 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M46 78 Q60 86 76 78 Q62 82 54 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M38 66 Q30 60 26 66 Q30 72 38 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${blot}
    </g>
    <g class="head-tilt">
      <path d="M82 52 Q98 54 98 62 Q98 74 84 76 Q76 70 78 58 Q78 54 82 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M80 68 Q90 76 100 68 Q98 74 90 75 Q83 74 80 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(88, 56, 3.2, E)}
    </g>`; },

  // Coelacanth — living fossil: armoured flecked body, stalked lobed fins, the famous trilobed tail
  coelacanth: (c) => { const E = eyeInk(c);
    const flecks = [[46, 54], [58, 50], [66, 60], [52, 66], [40, 62], [62, 70], [48, 58]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.7" fill="${TOOTH}" opacity=".7"/>`).join("");
    const lobe = (d, tx, ty) => `${tube(d, c.body, c.line, 5)}<ellipse cx="${tx}" cy="${ty}" rx="7" ry="4.5" fill="${c.shade}" stroke="${c.line}" stroke-width="2" transform="rotate(30 ${tx} ${ty})"/>`;
    return `
    <g class="tail-wag">
      <path d="M28 62 Q14 46 8 48 Q16 60 10 62 Q16 64 8 76 Q14 78 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M26 62 Q18 62 12 62" stroke="${c.line}" stroke-width="2" fill="none"/>
      ${lobe("M52 76 Q50 92 44 96", 42, 98)}
      ${lobe("M66 76 Q68 90 76 92", 78, 94)}
    </g>
    <g class="breathe">
      <path d="M28 62 Q40 44 68 46 Q90 48 96 62 Q90 78 68 80 Q40 80 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M44 52 Q60 58 44 64 M54 50 Q70 60 54 70 M64 52 Q80 62 64 72" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>
      ${flecks}
      ${lobe("M48 48 Q44 34 36 32", 34, 30)}
      ${lobe("M84 54 Q94 46 98 40", 100, 38)}
    </g>
    <g class="head-tilt">
      <path d="M82 52 Q96 54 96 62 Q95 72 84 74 Q78 62 82 52 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 66 q7 4 12 -1" fill="none" stroke="${c.line}" stroke-width="1.7" stroke-linecap="round"/>
      ${eye(88, 57, 3, E)}
    </g>`; },

  // Sea Dragon — leafy dragon (upright): tubular snout, crest, leaf-blade appendages, curled tail
  seadragon: (c) => { const E = eyeInk(c);
    const leaf = (x, y, a) => `<g transform="rotate(${a} ${x} ${y})"><path d="M${x} ${y} q-4 -8 0 -16 q4 8 0 16 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/></g>`;
    return `
    <g class="tail-wag">
      ${tube("M58 92 Q74 94 74 82 Q74 72 64 74", c.body, c.line, 8)}
      ${leaf(70, 88, 40)}${leaf(52, 96, -20)}
    </g>
    <g class="breathe">
      ${tube("M64 28 Q80 40 68 58 Q52 74 60 90", c.body, c.line, 13)}
      ${leaf(58, 40, -50)}${leaf(74, 46, 40)}${leaf(56, 56, -70)}${leaf(70, 62, 60)}${leaf(52, 72, -40)}${leaf(64, 80, 30)}
      <path d="M62 44 q4 0 5 4 M60 56 q4 0 5 4 M58 68 q4 0 5 4" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M62 26 q-4 -8 2 -11 q3 4 6 4 q4 -3 6 0 q-1 6 -7 7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${tube("M64 36 Q82 32 92 40", c.body, c.line, 6)}
      ${leaf(58, 30, -30)}
      ${eye(66, 38, 2.6, E)}
    </g>`; },

  // Electric Eel — long dark body, pale belly, underside fin frill, crackling lightning bolts
  electriceel: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag">
      ${tube("M12 66 Q8 62 12 58", c.body, c.line, 8)}
      <path d="M24 74 Q48 82 72 74 Q88 70 92 66" fill="none" stroke="${c.shade}" stroke-width="3" opacity=".6" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      ${tube("M12 66 Q40 58 70 62 Q86 64 94 62", c.body, c.line, 16)}
      <path d="M26 66 Q56 70 88 64" fill="none" stroke="${c.shade}" stroke-width="4" opacity=".5" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      <path d="M40 44 l6 6 l-4 2 l6 8" fill="none" stroke="${SPARK}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M66 42 l5 6 l-4 2 l6 7" fill="none" stroke="${SPARK}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M52 80 l5 6 l-4 2 l5 7" fill="none" stroke="${SPARK}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/>
    </g>
    <g class="head-tilt">
      <path d="M84 54 Q98 56 98 64 Q98 72 86 74 Q80 64 84 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 68 q7 3 12 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(89, 60, 2.8, E)}
    </g>`; },

  // Piranha — deep angry body, red belly, jutting toothy underbite, spiky fins, forked tail
  piranha: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M28 62 Q14 50 10 54 Q16 62 10 70 Q14 74 28 62 L18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q38 42 62 42 Q84 44 92 58 Q88 66 90 74 Q78 82 58 82 Q38 80 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 72 Q62 84 88 74 Q64 80 48 78 Z" fill="${c.shade}"/>
      <path d="M44 46 L50 34 L58 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M66 44 l4 -6 l1 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M50 80 Q56 90 64 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 56 Q94 58 92 66 Q90 74 82 76 L80 68 Q78 60 84 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M78 66 Q88 70 94 66 L92 72 Q86 76 80 72 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${80 + i * 3} 66 l1.2 4 l1.4 -4 Z" fill="${TOOTH}"/>`).join("")}
      <path d="M80 52 q6 -1 9 2" stroke="${c.line}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eye(84, 56, 2.8, E)}
    </g>`; },

  // Betta Fish — small body drowned in flowing veil fins: huge caudal fan, long dorsal + anal drapes
  bettafish: (c) => { const E = eyeInk(c);
    const rays = (cx, cy, r, a0, a1, n) => Array.from({ length: n }, (_, i) => { const a = (a0 + (a1 - a0) * i / (n - 1)) * Math.PI / 180; return `<line x1="${cx}" y1="${cy}" x2="${(cx + r * Math.cos(a)).toFixed(1)}" y2="${(cy + r * Math.sin(a)).toFixed(1)}" stroke="${c.line}" stroke-width="1" opacity=".45"/>`; }).join("");
    return `
    <g class="tail-wag">
      <path d="M50 62 Q20 26 10 36 Q22 50 16 62 Q22 74 10 88 Q20 98 50 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${rays(50, 62, 40, 150, 210, 7)}
      <path d="M52 50 Q40 20 54 14 Q60 30 62 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M52 74 Q40 104 56 110 Q62 92 62 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${rays(56, 50, 30, 250, 285, 4)}${rays(56, 74, 30, 75, 110, 4)}
    </g>
    <g class="breathe">
      <path d="M48 62 Q56 48 78 50 Q92 52 96 60 Q92 70 78 74 Q56 76 48 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M60 56 Q74 54 84 60 Q74 66 62 68 Z" fill="${c.shade}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M88 58 q6 2 8 4 q-6 2 -8 4" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M78 56 q-2 8 0 14" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
      ${eye(86, 59, 3, E)}
    </g>`; },
};

export const ROSTER_REEF = [
  { n: "Manta Ray",       e: "🐟", tier: 4, float: true },
  { n: "Hammerhead Shark", e: "🦈", tier: 3, float: true },
  { n: "Whale Shark",     e: "🐋", tier: 4, float: true },
  { n: "Moray Eel",       e: "🐍", tier: 2, float: true },
  { n: "Barracuda",       e: "🐟", tier: 2, float: true },
  { n: "Swordfish",       e: "🗡️", tier: 3, float: true },
  { n: "Marlin",          e: "🐟", tier: 3, float: true },
  { n: "Tuna",            e: "🐟", tier: 2, float: true },
  { n: "Cuttlefish",      e: "🦑", tier: 2, float: true },
  { n: "Nautilus",        e: "🐚", tier: 3, float: true },
  { n: "Lionfish",        e: "🐡", tier: 3, float: true },
  { n: "Angelfish",       e: "🐠", tier: 2, float: true },
  { n: "Blue Tang",       e: "🐠", tier: 2, float: true },
  { n: "Parrotfish",      e: "🐠", tier: 2, float: true },
  { n: "Triggerfish",     e: "🐠", tier: 2, float: true },
  { n: "Mahi Mahi",       e: "🐟", tier: 2, float: true },
  { n: "Grouper",         e: "🐟", tier: 2, float: true },
  { n: "Coelacanth",      e: "🐟", tier: 4, float: true },
  { n: "Sea Dragon",      e: "🐉", tier: 4, float: true },
  { n: "Electric Eel",    e: "⚡", tier: 2, float: true },
  { n: "Piranha",         e: "🐟", tier: 2, float: true },
  { n: "Betta Fish",      e: "🐠", tier: 2, float: true },
];
