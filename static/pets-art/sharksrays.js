// pets-art/sharksrays.js — BESPOKE hand-drawn SVG art for the SHARKS & RAYS batch of the NADO Pets roster.
// Each entry: slug -> (c) => "<svg inner markup string>" for <svg viewBox="0 0 120 120">.
// Coat: c.body (main fill), c.shade (dark markings/accent), c.line (outline). ALL aquatic => float:true,
// bodies oriented HORIZONTALLY, head to the RIGHT. Float animals never touch a floor -> NO floorShadow.
// ONE continuous silhouette + pale belly (countershading) + dark markings + clean profile face; fins tuck.
// Reference (do NOT duplicate): shark (sea.js), mantaray + hammerhead (reef.js). Helpers from ../pets-draw.js.
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, mirror, eyeInk, smile } from "../pets-draw.js";

const TOOTH = "#fff";   // shark teeth
const SPARK = "#7fe3ff"; // electric-ray discharge (used sparingly)

// underslung toothy shark grin: mouth-left corner at (x,y), n white teeth
const grin = (c, x, y, n = 5) => `<path d="M${x} ${y} q${(n * 1.5).toFixed(1)} 9 ${n * 3} 0 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`
  + Array.from({ length: n }, (_, i) => `<path d="M${x + 2 + i * 3} ${y + 1} l1.2 3 l1.2 -3 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>`).join("");
// three raking gill slits starting at (x,y)
const gills = (c, x, y = 54) => [0, 4.5, 9].map((i) => `<path d="M${x + i} ${y} q-2 8 0 15" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".55"/>`).join("");

export const ART_SHARKSRAYS = {
  // Tiger Shark — stocky torpedo, BLUNT broad snout, dark vertical tiger bars on the upper back
  tigershark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M30 62 L11 42 Q19 62 11 82 L28 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q36 44 66 45 Q94 46 104 56 Q107 60 104 64 Q94 78 66 79 Q36 80 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M38 72 Q68 82 104 66 Q68 78 38 72 Z" fill="${B}"/>
      ${[40, 50, 60, 70, 80].map((x) => `<path d="M${x} 47 Q${x - 3} 60 ${x} 71" stroke="${c.shade}" stroke-width="3.4" fill="none" opacity=".7" stroke-linecap="round"/>`).join("")}
      <path d="M52 47 L60 26 L73 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 74 L62 90 L88 73 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${gills(c, 84)}
      ${grin(c, 90, 66, 5)}
      ${eye(94, 55, 2.6, E)}
    </g>`; },

  // Bull Shark — VERY stocky, deep-bodied, short blunt rounded snout, small mean eye, plain grey
  bullshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M28 62 L10 40 Q18 62 10 84 L26 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q30 38 60 40 Q86 41 96 61 Q86 84 60 85 Q30 85 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M38 76 Q64 88 96 66 Q64 82 38 76 Z" fill="${B}"/>
      <path d="M48 43 L56 21 L70 45 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M72 80 L56 96 L84 75 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${gills(c, 80)}
      ${grin(c, 85, 69, 5)}
      ${eye(89, 53, 2.2, E)}
    </g>`; },

  // Nurse Shark — rounded snout with TWO nasal BARBELS, small mouth, two dorsals set well back
  nurseshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M30 62 L12 46 Q20 62 12 84 L28 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q38 47 66 48 Q92 50 103 60 Q94 71 66 75 Q38 77 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M38 71 Q66 80 103 65 Q66 76 38 71 Z" fill="${B}"/>
      <path d="M40 50 Q47 40 54 51 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M56 51 Q63 43 70 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M74 72 Q68 87 84 69 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${gills(c, 82, 56)}
      <path d="M100 66 q-2 7 -5 9 M104 65 q0 7 -2 10" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <path d="M92 68 q6 3 11 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(93, 56, 2.4, E)}
    </g>`; },

  // Reef Shark — the sleek textbook grey reef shark: clean torpedo, dusky trailing fin edges, toothy grin
  reefshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M30 62 L11 41 Q19 62 11 83 L28 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M11 41 L11 83 Q17 62 11 41 Z" fill="${c.line}" opacity=".5"/></g>
    <g class="breathe">
      <path d="M28 62 Q40 47 70 48 Q95 49 107 61 Q95 73 70 76 Q40 77 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 71 Q68 82 105 66 Q68 78 40 71 Z" fill="${B}"/>
      <path d="M52 49 L60 27 L72 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 73 L62 90 L88 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${gills(c, 84)}
      ${grin(c, 90, 66, 5)}
      ${eye(94, 55, 2.6, E)}
    </g>`; },

  // Blacktip Shark — slender torpedo with unmistakable BLACK-tipped dorsal, pectoral and tail lobe
  blacktipshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      <path d="M30 62 L11 41 Q19 62 11 83 L28 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M11 41 L24 58 L16 43 Z" fill="${INK}"/>
      <path d="M11 83 L23 66 L16 81 Z" fill="${INK}"/>
    </g>
    <g class="breathe">
      <path d="M28 62 Q40 49 72 50 Q96 51 108 61 Q96 71 72 74 Q40 75 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 71 Q68 80 106 65 Q68 77 40 71 Z" fill="${B}"/>
      <path d="M52 50 L60 28 L72 51 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M53 43 L60 28 L67 44 Z" fill="${INK}"/>
      <path d="M78 71 L62 89 L88 69 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M62 89 L67 83 L71 82 Z" fill="${INK}"/>
      ${gills(c, 84)}
      ${grin(c, 90, 66, 5)}
      ${eye(94, 55, 2.6, E)}
    </g>`; },

  // Mako Shark — sharp POINTED conical snout, sleek metallic body, big eye, tall keeled lunate tail
  makoshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M32 62 L14 34 L24 58 Q30 62 24 66 L14 90 L32 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q42 50 76 52 Q98 53 113 61 Q98 70 76 73 Q42 75 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 70 Q66 79 111 63 Q66 76 40 70 Z" fill="${B}"/>
      <path d="M54 51 L62 30 L72 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 71 L64 89 L88 69 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M31 60 h-6 M31 64 h-6" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${gills(c, 88, 55)}
      ${grin(c, 96, 66, 4)}
      ${eye(97, 55, 3, E)}
    </g>`; },

  // Thresher Shark — small body but an ENORMOUS scythe upper tail lobe as long as the whole animal
  threshershark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      <path d="M42 58 Q24 40 14 12 Q28 38 36 55 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 66 L24 80 Q32 70 38 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M38 62 Q48 50 74 51 Q96 52 108 61 Q96 70 74 73 Q48 74 38 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M48 70 Q72 78 106 64 Q72 75 48 70 Z" fill="${B}"/>
      <path d="M58 51 L64 32 L74 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M80 70 L68 88 L90 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${gills(c, 86, 55)}
      ${grin(c, 92, 66, 4)}
      ${eye(96, 56, 2.8, E)}
    </g>`; },

  // Wobbegong — flat carpet shark: low wide body, ragged BEARD of dermal tassels round the snout, mottled
  wobbegong: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M28 66 L10 52 Q18 66 10 80 L26 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 66 Q32 55 58 54 Q90 54 103 63 Q92 74 58 76 Q32 76 24 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M36 71 Q64 78 101 67 Q64 75 36 71 Z" fill="${B}"/>
      ${[[42, 60], [56, 58], [70, 62], [50, 66], [64, 68], [78, 60]].map(([x, y]) => `<path d="M${x} ${y} q4 -3 8 0 q-1 4 -5 4 q-4 0 -3 -4 Z" fill="${c.shade}" opacity=".7"/>`).join("")}
      ${Array.from({ length: 5 }, (_, i) => `<path d="M${99 - i * 3} ${57 + i * 2.4} q4 -1 6 2 q-4 2 -6 -0.5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/><path d="M${99 - i * 3} ${71 - i * 2.4} q4 1 6 -2 q-4 -2 -6 0.5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" stroke-linejoin="round"/>`).join("")}
      <path d="M90 65 q7 3 12 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(90, 58, 2.4, E)}
    </g>`; },

  // Angel Shark — flattened, ray-like: broad rounded pectoral wings spread wide, but a real SHARK tail
  angelshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      <path d="M38 62 L18 50 Q26 62 18 74 L38 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M56 60 Q40 40 22 44 Q34 54 50 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M56 64 Q40 84 22 80 Q34 70 50 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M40 62 Q48 51 72 51 Q96 53 105 62 Q96 71 72 73 Q48 73 40 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M50 68 Q74 75 104 64 Q74 72 50 68 Z" fill="${B}"/>
      ${[[58, 58], [70, 60], [64, 66], [80, 60]].map(([x, y]) => `<ellipse cx="${x}" cy="${y}" rx="2.6" ry="2" fill="${c.shade}" opacity=".55"/>`).join("")}
      <path d="M86 66 q8 4 16 0 q-8 5 -16 0 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      <path d="M78 57 q3 -3 7 -2 M78 67 q3 3 7 2" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
      ${eye(80, 57, 2.2, E)}${eye(80, 67, 2.2, E)}
    </g>`; },

  // Sawfish — shark-ray with a long flat rostrum SAW: teeth pegged down BOTH edges of the snout
  sawfish: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M26 62 L9 44 Q17 62 9 80 L24 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 62 Q34 49 60 50 Q84 51 93 60 Q84 71 60 73 Q34 74 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M34 70 Q60 78 92 64 Q60 75 34 70 Z" fill="${B}"/>
      <path d="M40 51 L46 34 L54 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M56 51 L62 36 L70 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M50 72 Q58 84 68 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M91 59 L119 60 L119 63 L91 64 Z" fill="${B}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${Array.from({ length: 8 }, (_, i) => `<path d="M${95 + i * 3} 59 l1 -4 l1 4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.7" stroke-linejoin="round"/><path d="M${95 + i * 3} 64 l1 4 l1 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.7" stroke-linejoin="round"/>`).join("")}
      ${eye(86, 56, 2.4, E)}
    </g>`; },

  // Guitarfish — the ray-shark: broad flat rounded pectoral disc up front, a shark tail with twin dorsals
  guitarfish: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M24 62 L10 48 Q16 62 10 76 L24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q34 57 48 56 Q60 54 72 50 Q94 46 107 61 Q94 76 72 74 Q60 70 48 68 Q34 67 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 66 Q66 76 105 64 Q66 72 40 66 Z" fill="${B}"/>
      <path d="M74 52 Q90 50 102 61 Q90 72 74 70 Q68 61 74 52 Z" fill="${c.shade}" opacity=".4"/>
      <path d="M34 55 L40 42 L48 55 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M48 56 L54 44 L62 57 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M92 66 q6 3 11 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(90, 57, 2.4, E)}
    </g>`; },

  // Eagle Ray — pointed triangular wings, pale SPOTS scattered on the back, protruding duckbill, whip tail
  eagleray: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      ${tube("M46 62 Q26 61 9 61", c.shade, c.line, 2.6)}
      <path d="M13 58 l-5 3 l5 3 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1"/>
      <path d="M62 56 Q42 26 14 22 Q30 44 52 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M62 68 Q42 98 14 102 Q30 80 52 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="68" cy="62" rx="22" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <ellipse cx="66" cy="65" rx="14" ry="8" fill="${B}" opacity=".45"/>
      ${[[58, 54], [68, 52], [76, 58], [60, 64], [72, 66], [52, 60], [64, 70]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2" fill="${B}"/>`).join("")}
      <path d="M86 56 Q98 58 98 62 Q98 66 86 68 Q82 62 86 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${eye(84, 56, 2.4, E)}${eye(84, 68, 2.4, E)}
    </g>`; },

  // Cownose Ray — broad wings, plain, and the signature bilobed NOTCHED "cow-nose" head
  cownoseray: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      ${tube("M46 62 Q28 62 12 62", c.shade, c.line, 2.4)}
      <path d="M60 56 Q40 28 12 26 Q28 46 50 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 68 Q40 96 12 98 Q28 78 50 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="68" cy="62" rx="21" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <ellipse cx="66" cy="65" rx="13" ry="8" fill="${B}" opacity=".45"/>
      <path d="M84 54 Q95 53 97 59 L92 62 L97 65 Q95 71 84 70 Q79 62 84 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${eye(83, 56, 2.4, E)}${eye(83, 68, 2.4, E)}
    </g>`; },

  // Spotted Ray — near-round flat disc peppered evenly with dark SPOTS, a short thorny tail
  spottedray: (c) => { const E = eyeInk(c), B = belly(c);
    const spots = []; for (let r = 0; r < 4; r++) for (let q = 0; q < 5; q++) { const x = 40 + q * 12 + (r % 2 ? 6 : 0), y = 48 + r * 8; if (x > 92 || Math.hypot(x - 60, (y - 62) * 1.3) > 34) continue; spots.push(`<circle cx="${x}" cy="${y}" r="1.9" fill="${c.shade}" opacity=".8"/>`); }
    return `
    <g class="tail-wag">
      ${tube("M38 62 Q26 62 16 62", c.shade, c.line, 3.4)}
      ${[44, 50, 56].map((x) => `<path d="M${x} 55 l1 -4 l1 4 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="0.8"/>`).join("")}
    </g>
    <g class="breathe">
      <path d="M64 38 Q94 44 98 62 Q94 82 64 86 Q30 84 24 62 Q28 42 64 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <ellipse cx="62" cy="66" rx="22" ry="12" fill="${B}" opacity=".4"/>
      ${spots.join("")}
      <path d="M88 57 Q95 59 95 62 Q95 65 88 67 Q85 62 88 57 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(82, 57, 2.2, E)}${eye(82, 67, 2.2, E)}
    </g>`; },

  // Torpedo Ray — plump, perfectly smooth round disc (no spots), a short fleshy tail with a rounded caudal
  torpedoray: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      <path d="M38 62 Q24 55 15 59 Q21 62 15 65 Q24 69 38 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M30 54 Q34 49 40 55 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M62 39 Q92 41 98 62 Q92 85 62 87 Q28 85 22 62 Q26 41 62 39 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="24" ry="14" fill="${B}" opacity=".4"/>
      <path d="M78 54 q4 -1 5 3 M78 70 q4 1 5 -3" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".55"/>
      <path d="M86 58 Q94 60 94 62 Q94 64 86 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(80, 57, 2.4, E)}${eye(80, 67, 2.4, E)}
    </g>`; },

  // Electric Ray — round disc like the torpedo but crackling with blue-white ELECTRIC discharge
  electricray: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      <path d="M38 62 Q24 55 15 59 Q21 62 15 65 Q24 69 38 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M62 39 Q92 41 98 62 Q92 85 62 87 Q28 85 22 62 Q26 41 62 39 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="24" ry="14" fill="${B}" opacity=".35"/>
      <circle cx="58" cy="60" r="12" fill="${SPARK}" opacity=".16"/>
      <path d="M50 50 l5 7 l-4 2 l6 8" fill="none" stroke="${SPARK}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M66 68 l5 6 l-4 2 l5 7" fill="none" stroke="${SPARK}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" opacity=".9"/>
      <path d="M86 58 Q94 60 94 62 Q94 64 86 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(80, 57, 2.4, E)}${eye(80, 67, 2.4, E)}
    </g>`; },

  // Bat Ray — plain, broad ANGULAR bat-like wings and a raised domed forehead, long whip tail
  batray: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      ${tube("M46 62 Q26 62 10 62", c.shade, c.line, 2.4)}
      <path d="M60 56 Q46 34 24 24 Q30 34 30 44 Q22 40 14 40 Q30 50 50 58 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 68 Q46 90 24 100 Q30 90 30 80 Q22 84 14 84 Q30 74 50 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="66" cy="62" rx="21" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <ellipse cx="64" cy="65" rx="13" ry="8" fill="${B}" opacity=".45"/>
      <path d="M78 52 Q88 48 94 54 Q90 60 82 60 Q78 56 78 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M84 60 Q94 60 96 64 Q90 70 82 68 Q80 63 84 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${eye(82, 55, 2.3, E)}${eye(82, 66, 2.3, E)}
    </g>`; },

  // Devil Ray — sleek dark manta-kin with two forward-pointing cephalic HORNS, pointed wings, whip tail
  devilray: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">
      ${tube("M46 62 Q26 61 8 61", c.shade, c.line, 2.4)}
      <path d="M60 55 Q40 24 12 20 Q28 42 50 57 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M60 69 Q40 100 12 104 Q28 82 50 67 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <ellipse cx="66" cy="62" rx="21" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.8"/>
      <path d="M56 54 Q66 50 78 54 Q66 58 56 56 Z" fill="${B}" opacity=".5"/>
      <ellipse cx="64" cy="66" rx="13" ry="7" fill="${B}" opacity=".4"/>
      <path d="M82 56 Q96 50 106 46 Q100 56 90 60 Q84 60 82 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M82 68 Q96 74 106 78 Q100 68 90 64 Q84 64 82 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${eye(82, 56, 2.3, E)}${eye(82, 68, 2.3, E)}
    </g>`; },

  // Blue Shark — extremely slim body, long conical snout, and very long sickle PECTORAL fins
  blueshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M30 62 L10 42 Q18 62 10 84 L28 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q44 52 78 53 Q100 54 113 61 Q100 69 78 71 Q44 72 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 69 Q68 77 111 63 Q68 74 40 69 Z" fill="${B}"/>
      <path d="M56 52 L62 34 L70 53 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.9" stroke-linejoin="round"/>
      <path d="M78 70 Q58 92 42 96 Q64 84 72 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${gills(c, 90, 56)}
      ${grin(c, 98, 66, 4)}
      ${eye(98, 56, 2.8, E)}
    </g>`; },

  // Leopard Shark — slim body decorated with dark rounded SADDLE bands and scattered spots
  leopardshark: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M30 62 L11 42 Q19 62 11 82 L28 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q40 49 70 50 Q95 51 107 61 Q95 71 70 74 Q40 75 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M40 71 Q68 80 105 65 Q68 77 40 71 Z" fill="${B}"/>
      ${[40, 52, 64, 76].map((x) => `<path d="M${x} 50 q7 -1 8 6 q-1 5 -8 5 q-6 -1 -6 -6 q0 -5 6 -5 Z" fill="none" stroke="${c.shade}" stroke-width="2.8" opacity=".75"/>`).join("")}
      ${[[46, 66], [58, 68], [70, 66], [82, 62]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.8" fill="${c.shade}" opacity=".7"/>`).join("")}
      <path d="M52 49 L60 30 L72 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M78 71 L62 90 L88 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${gills(c, 86, 55)}
      ${grin(c, 91, 66, 5)}
      ${eye(94, 55, 2.6, E)}
    </g>`; },
};

export const ROSTER_SHARKSRAYS = [
  { n: "Tiger Shark",    e: "🦈", tier: 3, float: true },
  { n: "Bull Shark",     e: "🦈", tier: 3, float: true },
  { n: "Nurse Shark",    e: "🦈", tier: 2, float: true },
  { n: "Reef Shark",     e: "🦈", tier: 2, float: true },
  { n: "Blacktip Shark", e: "🦈", tier: 2, float: true },
  { n: "Mako Shark",     e: "🦈", tier: 3, float: true },
  { n: "Thresher Shark", e: "🦈", tier: 3, float: true },
  { n: "Wobbegong",      e: "🦈", tier: 2, float: true },
  { n: "Angel Shark",    e: "🦈", tier: 2, float: true },
  { n: "Sawfish",        e: "🌊", tier: 3, float: true },
  { n: "Guitarfish",     e: "🌊", tier: 2, float: true },
  { n: "Eagle Ray",      e: "🌊", tier: 3, float: true },
  { n: "Cownose Ray",    e: "🌊", tier: 2, float: true },
  { n: "Spotted Ray",    e: "🌊", tier: 2, float: true },
  { n: "Torpedo Ray",    e: "🌊", tier: 2, float: true },
  { n: "Electric Ray",   e: "🌊", tier: 2, float: true },
  { n: "Bat Ray",        e: "🌊", tier: 2, float: true },
  { n: "Devil Ray",      e: "🌊", tier: 3, float: true },
  { n: "Blue Shark",     e: "🦈", tier: 2, float: true },
  { n: "Leopard Shark",  e: "🦈", tier: 2, float: true },
];
