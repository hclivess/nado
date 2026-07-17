// pets-art/deepsea.js — BESPOKE hand-drawn SVG art for the DEEP-SEA / ABYSSAL batch of NADO Pets.
// Each entry: slug -> (c) => "<svg inner markup string>" for <svg viewBox="0 0 120 120">.
// Coat: c.body (main fill), c.shade (underside/accent), c.line (outline). All abyssal => float:true,
// bodies oriented HORIZONTALLY, head to the RIGHT (cephalopods drawn front-cute like sea.js octopus).
// Float animals OMIT floorShadow. Teeth always INSIDE a dark INK mouth cavity. Helpers from ../pets-draw.js.
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, mirror, eyeInk, smile } from "../pets-draw.js";

const GLOW = "#7fe3ff"; // cold bioluminescence (lure bulbs, photophores, glowing eyes)
const PALE = "#eafff4"; // pale glow (photophore cores)
const LURE = "#f2c94c"; // warm lure light
const TOOTH = "#fff";   // teeth / fangs

export const ART_DEEPSEA = {
  // Gulper (pelican) Eel — enormous hinged pouch-jaw taking up the whole head, tiny eye, thin whip tail + glow tip
  gulpereel: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      ${tube("M42 62 Q24 66 12 58 Q8 56 6 60", c.body, c.line, 4)}
      <circle cx="6" cy="60" r="3" fill="${GLOW}" stroke="${c.line}" stroke-width="1"/>
      <circle cx="6" cy="60" r="5.5" fill="${GLOW}" opacity=".3"/>
    </g>
    <g class="breathe">
      <path d="M40 60 Q40 40 66 40 Q98 40 113 58 Q115 60 113 62 Q98 80 66 82 Q40 82 40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M50 72 Q78 82 108 66 Q80 78 52 76 Z" fill="${B}" opacity=".7"/>
      <path d="M52 60 Q80 51 112 59 Q114 60 112 61 Q80 73 52 63 Q50 61 52 60 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 6 }, (_, i) => `<path d="M${64 + i * 7} 58 l1.4 4 l1.6 -4 Z" fill="${TOOTH}"/>`).join("")}
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${68 + i * 7} 68 l1.4 -4 l1.6 4 Z" fill="${TOOTH}"/>`).join("")}
    </g>
    <g class="head-tilt">${eye(56, 50, 2.8, E)}</g>`; },

  // Viperfish — slender body, huge needle fangs in a dark gape, long dorsal lure-ray arching over with a gold bulb
  viperfish: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M22 62 L6 50 Q14 62 6 74 Z M22 62 L14 55 L22 62 L14 69 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 62 Q40 50 74 51 Q96 53 106 62 Q96 73 74 75 Q40 76 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M36 70 Q66 78 100 66 Q66 74 40 72 Z" fill="${B}" opacity=".6"/>
      ${[38, 48, 58, 68].map((x) => `<circle cx="${x}" cy="70" r="1.5" fill="${GLOW}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
      <path d="M58 51 Q60 22 74 13" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      <circle cx="75" cy="12" r="4.5" fill="${LURE}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="75" cy="12" r="8" fill="${LURE}" opacity=".28"/>
      <circle cx="73.5" cy="10.5" r="1.4" fill="#fff" opacity=".9"/>
    </g>
    <g class="head-tilt">
      <path d="M80 56 Q98 54 106 61 Q98 72 80 69 Q76 62 80 56 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 6 }, (_, i) => `<path d="M${82 + i * 3.6} 57 l1.2 6.5 l1.4 -6.5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${84 + i * 3.6} 68 l1.2 -6 l1.4 6 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
      ${eye(78, 54, 2.4, E)}
    </g>`; },

  // Dragonfish — eel-slim body, fangs in a dark gape, and the signature chin BARBEL dangling a glowing lure
  dragonfish: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M18 62 L6 52 Q12 62 6 72 Z M18 62 L10 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M16 62 Q36 54 70 54 Q94 55 104 62 Q94 71 70 72 Q36 72 16 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${[30, 42, 54, 66, 78].map((x) => `<circle cx="${x}" cy="68" r="1.5" fill="${GLOW}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
      <path d="M28 60 Q60 66 96 60" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      <path d="M92 70 Q94 90 82 98" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="81" cy="99" r="4" fill="${GLOW}" stroke="${c.line}" stroke-width="1.3"/>
      <circle cx="81" cy="99" r="7" fill="${GLOW}" opacity=".28"/>
      <circle cx="79.6" cy="97.6" r="1.2" fill="#fff" opacity=".9"/>
    </g>
    <g class="head-tilt">
      <path d="M82 56 Q100 55 106 62 Q100 70 82 69 Q78 62 82 56 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 6 }, (_, i) => `<path d="M${84 + i * 3.4} 57 l1.1 5 l1.3 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${86 + i * 3.4} 68 l1.1 -4.5 l1.3 4.5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
      ${eye(80, 58, 2.4, E)}
    </g>`; },

  // Fangtooth — stubby deep body, disproportionately BIG blocky head, monstrous oversized fangs, small eye
  fangtooth: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M30 62 Q16 50 10 54 Q16 62 10 70 Q16 74 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M30 62 Q34 40 58 40 Q86 42 98 60 Q92 66 94 74 Q80 84 58 84 Q34 82 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 74 Q64 84 92 72 Q66 80 46 78 Z" fill="${B}" opacity=".6"/>
      ${[44, 54, 64].map((x) => `<path d="M${x} 50 q4 3 4 10" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".5"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M74 56 Q94 56 96 66 Q94 78 76 78 Q68 68 70 60 Q71 56 74 56 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${74 + i * 4.4} 58 l1.5 8 l1.7 -8 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>`).join("")}
      ${Array.from({ length: 4 }, (_, i) => `<path d="M${77 + i * 4.4} 76 l1.5 -7 l1.7 7 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5"/>`).join("")}
      ${eye(72, 50, 3.2, E)}
    </g>`; },

  // Frilled Shark — eel-like serpentine shark body, ruffled frilly gill slits at the throat, wide toothy jaw
  frilledshark: (c) => { const E = eyeInk(c), B = belly(c);
    const frill = (x) => `<path d="M${x} 52 q-3 4 0 8 q-3 4 0 8 q-3 4 0 8" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round" opacity=".85"/>`;
    return `
    <g class="tail-wag"><path d="M16 62 L4 52 Q10 62 4 78 L16 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/></g>
    <g class="breathe">
      ${tube("M14 62 Q34 60 54 62", c.body, c.line, 16)}
      <path d="M24 66 Q46 72 66 66 Q90 62 100 60" fill="none" stroke="${B}" stroke-width="4" opacity=".55" stroke-linecap="round"/>
      <path d="M50 54 Q64 46 78 54 Q92 56 100 60 Q100 66 96 70 Q90 76 78 74 Q64 80 50 72 Q44 62 50 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      ${[58, 64, 70].map((x) => frill(x)).join("")}
    </g>
    <g class="head-tilt">
      <path d="M78 58 Q98 56 104 63 Q98 72 78 70 Q74 64 78 58 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 6 }, (_, i) => `<path d="M${80 + i * 3.6} 59 l1 3 l1.2 -3 Z" fill="${TOOTH}"/>`).join("")}
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${82 + i * 3.6} 69 l1 -3 l1.2 3 Z" fill="${TOOTH}"/>`).join("")}
      ${eye(78, 56, 2.4, E)}
    </g>`; },

  // Vampire Squid — dark bell with two ear-fins, HUGE eyes, webbed umbrella cloak of arms with glowing tips
  vampiresquid: (c) => { const E = eyeInk(c);
    const web = "M28 60 Q26 92 60 100 Q94 92 92 60 Q86 68 80 62 Q74 70 68 63 Q60 71 52 63 Q46 70 40 62 Q34 68 28 60 Z";
    return `
    <g class="breathe">
      <path d="${web}" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${[40, 52, 64, 76].map((x) => `<circle cx="${x}" cy="90" r="1.4" fill="${GLOW}" opacity=".7"/>`).join("")}
      <path d="M30 52 Q30 24 60 24 Q90 24 90 52 Q90 66 60 66 Q30 66 30 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M40 30 L34 18 Q44 22 46 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M80 30 L86 18 Q76 22 74 32 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M42 30 Q54 24 62 26 Q52 30 48 36 Z" fill="#fff" opacity=".22"/>
    </g>
    <g class="head-tilt">
      ${ceye(49, 48, 5)}${ceye(71, 48, 5)}
      ${smile(60, 56, 3.4, E)}
    </g>`; },

  // Dumbo Octopus — domed mantle with two big elephant-ear fins, short webbed arm-skirt, big innocent eyes
  dumbooctopus: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      <path d="M32 46 Q10 40 8 54 Q18 58 30 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
      <path d="M88 46 Q110 40 112 54 Q102 58 90 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M30 58 Q30 28 60 28 Q90 28 90 58 Q90 74 78 80 Q80 90 72 88 Q72 96 64 90 Q60 96 56 90 Q48 96 48 88 Q40 90 42 80 Q30 74 30 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M44 70 Q60 80 76 70 Q60 76 44 70 Z" fill="${B}" opacity=".6"/>
      <path d="M42 36 Q52 30 60 32 Q50 36 46 42 Z" fill="#fff" opacity=".2"/>
    </g>
    <g class="head-tilt">
      ${ceye(50, 52, 4.4)}${ceye(70, 52, 4.4)}
      ${smile(60, 60, 3.6, E)}
    </g>`; },

  // Barreleye — normal body but a TRANSPARENT glass dome over the head housing two upward-pointing tube eyes
  barreleye: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M24 66 L10 56 Q16 66 10 78 Z M24 66 L14 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 66 Q40 58 68 58 Q92 60 102 68 Q92 78 68 80 Q40 80 22 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M34 74 Q64 82 98 72 Q66 80 40 78 Z" fill="${B}" opacity=".55"/>
      <ellipse cx="92" cy="72" rx="2" ry="2.6" fill="${INK}"/>
      <path d="M84 74 q6 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M60 62 Q60 40 84 40 Q99 42 99 60 Q99 66 90 66 L64 66 Q60 65 60 62 Z" fill="${GLOW}" opacity=".3" stroke="${GLOW}" stroke-width="2"/>
      <ellipse cx="74" cy="47" rx="11" ry="5" fill="#fff" opacity=".16"/>
      <path d="M60 62 Q60 40 84 40 Q99 42 99 60" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".5"/>
      <g class="blink">
        <ellipse cx="72" cy="52" rx="4" ry="5" fill="${GLOW}" stroke="${c.line}" stroke-width="1.6"/>
        <ellipse cx="84" cy="52" rx="4" ry="5" fill="${GLOW}" stroke="${c.line}" stroke-width="1.6"/>
        <circle cx="72" cy="50" r="1.6" fill="${INK}"/><circle cx="84" cy="50" r="1.6" fill="${INK}"/>
      </g>
    </g>`; },

  // Blobfish — sagging gelatinous blob, big drooping bulbous nose, heavy sad eyelids and a glum downturned frown
  blobfish: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M28 66 Q16 58 10 62 Q16 66 12 74 Q20 74 28 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 64 Q26 46 52 44 Q78 44 92 56 Q100 62 96 72 Q92 82 78 82 Q74 90 66 84 Q60 88 56 82 Q40 82 30 74 Q24 70 26 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 76 Q62 84 88 74 Q64 82 46 80 Z" fill="${B}" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M84 60 Q98 62 96 72 Q92 78 84 76 Q80 68 84 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <ellipse cx="92" cy="70" rx="3.6" ry="2.8" fill="${c.shade}"/>
      <path d="M74 79 Q82 83 90 79" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M66 60 q3 -2 6 0 M78 60 q3 -2 6 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${eye(72, 64, 2.6, E)}${eye(84, 64, 2.6, E)}
    </g>`; },

  // Goblin Shark — long flat paddle snout jutting forward over a protrusible jaw of needle teeth thrust out
  goblinshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M22 60 L8 44 Q16 60 8 78 L22 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 60 Q36 48 60 48 Q78 49 86 58 Q80 66 84 72 Q70 78 52 78 Q34 76 22 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M36 68 Q56 76 82 68 Q58 74 44 72 Z" fill="${B}" opacity=".55"/>
      <path d="M52 48 L58 34 L66 49 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M82 54 Q104 50 116 52 Q106 58 84 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M82 60 Q98 60 104 66 Q98 74 84 74 Q78 68 82 60 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${Array.from({ length: 6 }, (_, i) => `<path d="M${84 + i * 3.2} 61 l1 4 l1.2 -4 Z" fill="${TOOTH}"/>`).join("")}
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${86 + i * 3.2} 72 l1 -4 l1.2 4 Z" fill="${TOOTH}"/>`).join("")}
      ${eye(80, 55, 2.2, E)}
    </g>`; },

  // Lanternfish — small tidy fish studded with rows of glowing photophore lights along belly and flank, big eye
  lanternfish: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M28 62 Q14 50 8 54 Q14 62 8 70 Q14 74 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q42 50 66 50 Q88 52 96 62 Q88 74 66 76 Q42 76 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M56 50 Q60 44 66 50 Q60 52 58 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M50 74 Q58 82 68 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${[36, 44, 52, 60, 68, 76].map((x) => `<circle cx="${x}" cy="70" r="4" fill="${GLOW}" opacity=".22"/><circle cx="${x}" cy="70" r="2" fill="${PALE}" stroke="${c.line}" stroke-width="0.5"/>`).join("")}
      ${[40, 50, 60].map((x) => `<circle cx="${x}" cy="60" r="1.6" fill="${PALE}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M86 62 q6 3 8 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(84, 58, 3.4, E)}
    </g>`; },

  // Hatchetfish — razor-thin silvery hatchet-blade body, deep keeled belly, huge upward-staring tube eye
  hatchetfish: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M40 54 Q28 48 22 52 Q28 56 24 62 Q34 60 42 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M46 46 Q64 42 82 48 Q92 52 92 58 Q92 62 86 62 Q82 78 70 90 Q62 98 54 90 Q44 78 44 62 Q40 52 46 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M52 60 Q66 66 84 58" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".5"/>
      <path d="M54 66 Q64 72 74 66 Q64 76 54 66 Z" fill="${tint(c.body, 0.5)}" opacity=".7"/>
      ${[52, 60, 68].map((x) => `<circle cx="${x}" cy="86" r="1.8" fill="${PALE}" stroke="${c.line}" stroke-width="0.4"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M87 56 q4 2 4 4" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      <g class="blink">
        <circle cx="82" cy="52" r="4.2" fill="#fff" stroke="${c.line}" stroke-width="1.6"/>
        <circle cx="82" cy="49.5" r="2" fill="${INK}"/>
      </g>
    </g>`; },

  // Snipe Eel — thread-thin ribbon body ending in two ultra-long jaws that curve wide APART like open forceps
  snipeeel: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag">${tube("M12 70 Q8 64 14 60", c.body, c.line, 4)}</g>
    <g class="breathe">
      ${tube("M12 68 Q34 60 58 62 Q72 64 80 62", c.body, c.line, 9)}
      <path d="M24 66 Q44 70 66 65" fill="none" stroke="${belly(c)}" stroke-width="2.4" opacity=".5" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M76 58 Q92 54 108 44" fill="none" stroke="${c.line}" stroke-width="4.5" stroke-linecap="round"/>
      <path d="M76 58 Q92 54 108 44" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M76 66 Q92 72 108 82" fill="none" stroke="${c.line}" stroke-width="4.5" stroke-linecap="round"/>
      <path d="M76 66 Q92 72 108 82" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
      ${eye(74, 60, 2.6, E)}
    </g>`; },

  // Coffinfish — boxy inflatable sea-toad, baggy skin folds, stubby walking fins, a little tuft-lure on the head
  coffinfish: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M30 66 Q18 58 12 62 Q18 66 14 74 Q24 74 32 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 52 Q28 44 38 44 Q60 40 82 44 Q94 46 94 58 L94 74 Q94 84 82 84 Q60 88 38 84 Q28 84 28 76 Q24 64 28 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 76 Q60 84 84 74 Q62 82 46 80 Z" fill="${B}" opacity=".55"/>
      <path d="M36 56 Q44 60 40 68 M50 54 Q58 60 52 70" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".5" stroke-linecap="round"/>
      <path d="M56 84 q-2 8 -8 10 M72 84 q2 8 8 10" fill="none" stroke="${c.line}" stroke-width="3" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      <path d="M58 44 Q58 30 66 26" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="67" cy="25" r="3.6" fill="${LURE}" stroke="${c.line}" stroke-width="1.3"/>
      <path d="M64 22 l-3 -4 M70 22 l3 -4 M67 21 l0 -5" stroke="${LURE}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 64 q6 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(80, 58, 3, E)}
    </g>`; },

  // Black Swallower — slim head but a monstrously distended balloon belly with a swallowed fish visible inside
  blackswallower: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M20 58 Q10 50 6 52 Q12 58 6 66 Q12 68 20 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M18 58 Q40 50 64 50 Q84 50 90 58 Q100 68 94 82 Q86 98 62 98 Q40 96 40 78 Q40 66 32 60 Q24 58 18 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="66" cy="78" rx="17" ry="15" fill="${tint(c.body, 0.35)}" opacity=".5"/>
      <path d="M58 70 Q76 74 78 84 Q68 88 60 82 Q56 76 58 70 Z" fill="${c.shade}" opacity=".7" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>
      <path d="M78 82 l6 -3 l-1 4 l5 -1" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M78 54 Q92 53 92 60 Q86 66 78 64 Q75 58 78 54 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${Array.from({ length: 4 }, (_, i) => `<path d="M${79 + i * 3} 55 l1 3 l1.2 -3 Z" fill="${TOOTH}"/>`).join("")}
      ${eye(82, 52, 2.4, E)}
    </g>`; },

  // Sea Pig — plump pink sea-cucumber trundling on stubby inflated tube-feet, papillae on its back, cute snout
  seapig: (c) => { const E = eyeInk(c), B = belly(c);
    const legs = [38, 50, 62, 74].map((x) => `<path d="M${x} 78 q-1 10 3 14 q4 -2 3 -8" fill="${tint(c.body, 0.3)}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`).join("");
    return `
    <g class="tail-wag">${legs}</g>
    <g class="breathe">
      <path d="M26 64 Q26 48 48 46 Q76 44 92 52 Q102 58 98 68 Q92 80 66 80 Q34 80 26 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M38 72 Q64 80 92 66 Q66 76 46 74 Z" fill="${B}" opacity=".55"/>
      <path d="M40 50 q-2 -8 2 -12 M52 47 q0 -9 4 -12 M64 47 q2 -8 6 -10" fill="none" stroke="${c.shade}" stroke-width="2.2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      ${eye(84, 58, 3, E)}${eye(94, 58, 2.4, E)}
      <path d="M86 64 q4 3 8 1" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      <ellipse cx="97" cy="62" rx="2.4" ry="2" fill="${c.shade}"/>
    </g>`; },

  // Yeti Crab — pale carapace crab whose big front pincers are shrouded in shaggy white bristly hair
  yeticrab: (c) => { const E = eyeInk(c);
    const leg = (i) => `<path d="M${44 - i * 2} ${64 + i * 4} Q${30 - i * 3} ${68 + i * 5} ${24 - i * 3} ${78 + i * 4}" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>`;
    const legs = [0, 1, 2].map(leg).join("");
    const hair = (x, y) => Array.from({ length: 7 }, (_, i) => `<path d="M${x + i * 2.2 - 7} ${y} q-1 -6 1 -9" fill="none" stroke="${PALE}" stroke-width="1.6" stroke-linecap="round"/>`).join("");
    const claw = `
      <path d="M44 60 Q32 54 24 58" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M44 60 Q32 54 24 58" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/>
      ${hair(30, 52)}
      <path d="M28 48 Q8 44 8 60 Q10 68 22 66 Q13 61 24 59 Q13 56 26 52 Q30 50 28 48 Z" fill="${tint(c.body, 0.3)}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${hair(15, 47)}${hair(15, 66)}`;
    return `
    <g class="tail-wag">${legs}${mirror(legs)}</g>
    <g class="breathe">
      <path d="M30 66 Q30 48 60 48 Q90 48 90 66 Q90 78 60 80 Q30 78 30 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.5" stroke-linejoin="round"/>
      <path d="M44 70 q16 8 32 0" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".7"/>
    </g>
    ${claw}${mirror(claw)}
    <g class="head-tilt">
      <path d="M52 50 L50 42 M68 50 L70 42" stroke="${c.line}" stroke-width="2"/>
      ${eyes(50, 70, 42, 3, E)}
      ${smile(60, 66, 4, E)}
    </g>`; },

  // Giant Isopod — armoured deep-sea pillbug: segmented overlapping plates, many legs, antennae, big eyes, tail fan
  giantisopod: (c) => { const E = eyeInk(c), B = belly(c);
    const legs = Array.from({ length: 5 }, (_, i) => `<path d="M${40 + i * 10} 78 q-2 8 -6 12" fill="none" stroke="${c.line}" stroke-width="2.6" stroke-linecap="round"/>`).join("");
    return `
    <g class="tail-wag">
      ${legs}${legs.replace(/78 q-2 8 -6 12/g, "46 q-2 -8 -6 -12")}
      <path d="M24 56 L14 50 L18 62 L14 74 L24 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M22 62 Q24 48 40 46 Q64 44 84 48 Q98 52 100 62 Q98 72 84 76 Q64 80 40 78 Q24 76 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[38, 48, 58, 68, 78].map((x) => `<path d="M${x} 48 Q${x - 3} 62 ${x} 76" fill="none" stroke="${c.line}" stroke-width="1.6" opacity=".7"/>`).join("")}
      <path d="M34 70 Q60 78 90 68 Q62 74 44 72 Z" fill="${B}" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M88 52 L98 44 M94 54 L104 50" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(88, 56, 2.6, E)}${eye(88, 68, 2.6, E)}
    </g>`; },

  // Glass Squid — near-transparent barrel mantle you can see through, one opaque organ inside, big eye, tucked arms
  glasssquid: (c) => { const E = eyeInk(c); const G = tint(c.body, 0.55);
    const arms = [72, 76, 80, 84].map((x, i) => tube(`M${x} 68 Q${x + 8} ${70 + i} ${x + 11} ${75 + i * 2}`, G, c.line, 2.6)).join("");
    return `
    <g class="tail-wag">
      <path d="M30 62 L16 50 Q22 62 16 74 Z" fill="${G}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round" opacity=".9"/>
      ${arms}
    </g>
    <g class="breathe">
      <path d="M28 62 Q34 46 62 46 Q84 46 88 62 Q84 78 62 78 Q34 78 28 62 Z" fill="${G}" opacity=".45" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="52" cy="64" rx="5" ry="9" fill="${c.shade}" opacity=".8" stroke="${c.line}" stroke-width="1.2"/>
      <path d="M40 52 Q54 48 66 52" fill="none" stroke="#fff" stroke-width="2" opacity=".4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <g class="blink"><ellipse cx="76" cy="58" rx="4.4" ry="5" fill="#fff" stroke="${c.line}" stroke-width="1.6"/><circle cx="76" cy="59" r="2.4" fill="${INK}"/><circle cx="74.6" cy="57.6" r="1" fill="#fff"/></g>
    </g>`; },

  // Chimaera (ratfish / ghost shark) — glides on big wing-like pectoral fins, tall dorsal spine, long rat-tail, green eye
  chimaera: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${tube("M40 62 Q22 64 10 60 Q6 59 4 62", c.body, c.line, 4)}</g>
    <g class="tail-wag">
      <path d="M56 56 Q40 34 24 30 Q34 48 50 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M58 68 Q42 88 26 92 Q36 74 52 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M38 62 Q42 46 68 46 Q94 48 104 60 Q98 66 100 72 Q86 80 66 80 Q44 78 38 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M48 72 Q70 80 98 68 Q72 76 54 74 Z" fill="${B}" opacity=".55"/>
      <path d="M60 46 L58 30 L68 45 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M92 62 q6 3 10 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <g class="blink"><ellipse cx="90" cy="56" rx="4" ry="4.6" fill="${GLOW}" stroke="${c.line}" stroke-width="1.6"/><circle cx="90" cy="57" r="2" fill="${INK}"/><circle cx="88.8" cy="55" r="0.9" fill="#fff"/></g>
    </g>`; },
};

export const ROSTER_DEEPSEA = [
  { n: "Gulper Eel",      e: "🐍", tier: 3, float: true },
  { n: "Viperfish",       e: "🐟", tier: 3, float: true },
  { n: "Dragonfish",      e: "🐉", tier: 3, float: true },
  { n: "Fangtooth",       e: "🦷", tier: 2, float: true },
  { n: "Frilled Shark",   e: "🦈", tier: 3, float: true },
  { n: "Vampire Squid",   e: "🦑", tier: 3, float: true },
  { n: "Dumbo Octopus",   e: "🐙", tier: 3, float: true },
  { n: "Barreleye",       e: "👁️", tier: 3, float: true },
  { n: "Blobfish",        e: "🐡", tier: 2, float: true },
  { n: "Goblin Shark",    e: "🦈", tier: 4, float: true },
  { n: "Lanternfish",     e: "🏮", tier: 1, float: true },
  { n: "Hatchetfish",     e: "🪓", tier: 2, float: true },
  { n: "Snipe Eel",       e: "🐍", tier: 2, float: true },
  { n: "Coffinfish",      e: "⚰️", tier: 2, float: true },
  { n: "Black Swallower", e: "🐟", tier: 3, float: true },
  { n: "Sea Pig",         e: "🐷", tier: 2, float: true },
  { n: "Yeti Crab",       e: "🦀", tier: 3, float: true },
  { n: "Giant Isopod",    e: "🦠", tier: 2, float: true },
  { n: "Glass Squid",     e: "🦑", tier: 3, float: true },
  { n: "Chimaera",        e: "👻", tier: 3, float: true },
];
