// pets-art/woodland.js — BESPOKE hand-drawn SVG art for FOREST & WOODLAND animals (NADO Pets).
// Each value: (c, v) => "<svg inner markup>" for viewBox 0 0 120 120, animal centered ~ (60,62), within
// x,y ∈ [8,112]. Colours come from the coat object c (c.body / c.shade / c.line); the palette is applied
// at runtime, so real colours are NOT hardcoded (antlers/teeth/claws may use fixed warm tones + #fff).
// Animate: torso <g class="breathe">, head <g class="head-tilt">, tails/ears/wings <g class="tail-wag">.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

// warm fixed accents that stay constant across coats
const ANTLER = "#d9b98a", CLAW = "#e9e4d8", TUSK = "#f4efe2", BEAK = "#f2a03b";

export const ART_WOODLAND = {
  // ── Red Fox — pointed snout, dark-tipped triangular ears, bushy white-tipped tail curled to the side
  redfox: (c) => `
    <g class="tail-wag"><path d="M34 86 C8 92 2 66 18 52 C24 62 30 74 42 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M20 56 C10 66 8 80 17 86 C22 78 26 70 32 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5"/></g>
    <g class="breathe"><ellipse cx="62" cy="86" rx="24" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M50 94 q12 8 24 0" fill="${c.shade}" opacity=".8"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 50}" y="94" width="7" height="15" rx="3.2" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <g class="tail-wag"><path d="M52 48 L44 22 L64 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M53 44 L49 28 L60 39 Z" fill="${INK}"/>
        ${mirror(`<path d="M52 48 L44 22 L64 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M53 44 L49 28 L60 39 Z" fill="${INK}"/>`)}</g>
      <path d="M42 52 Q42 78 60 78 Q78 78 78 52 Q60 42 42 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 60 Q60 84 70 60 Q66 72 60 72 Q54 72 50 60 Z" fill="${c.shade}"/>
      <path d="M60 70 l-8 5 M60 70 l8 5" stroke="${INK}" stroke-width="1.4"/>
      <ellipse cx="60" cy="68" rx="2.8" ry="2.2" fill="${INK}"/>
      ${eyes(51, 69, 56, 2.8, eyeInk(c))}
    </g>`,

  // ── Gray Wolf — bigger, thick neck ruff, upright ears, long muzzle, amber gaze
  graywolf: (c) => `
    <g class="tail-wag"><path d="M30 96 C8 96 6 74 22 66 C26 76 30 86 40 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M40 90 C32 88 26 80 24 72" stroke="${INK}" stroke-width="1.6" fill="none" opacity=".5"/></g>
    <g class="breathe"><path d="M36 96 Q36 68 60 66 Q84 68 84 96 Q60 104 36 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 47}" y="94" width="8" height="16" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M44 48 L40 24 L58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M46 44 L44 30 L54 40 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M44 48 L40 24 L58 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M46 44 L44 30 L54 40 Z" fill="${c.shade}"/>`)}
      <path d="M38 56 Q38 74 48 82 L44 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6"/>
      ${mirror(`<path d="M38 56 Q38 74 48 82 L44 60 Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6"/>`)}
      <path d="M40 54 Q40 74 60 78 Q80 74 80 54 Q60 44 40 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 60 Q60 72 68 60 Q68 84 60 84 Q52 84 52 60 Z" fill="${c.shade}"/>
      <path d="M54 76 l6 6 l6 -6 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="74" rx="3" ry="2.4" fill="${INK}"/>
      <path d="M60 76 l-7 6 M60 76 l7 6" stroke="${INK}" stroke-width="1.4"/>
      ${eyes(50, 70, 58, 2.8, eyeInk(c))}
    </g>`,

  // ── Brown Bear — big round ears, heavy shoulders, broad tan muzzle, tiny nose (tier 3 heavyweight)
  brownbear: (c) => `
    <g class="breathe"><ellipse cx="60" cy="86" rx="31" ry="21" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M31 86 Q23 58 45 64 Q43 78 41 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${mirror(`<path d="M31 86 Q23 58 45 64 Q43 78 41 90 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="94" rx="16" ry="11" fill="${c.shade}" opacity=".75"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 74 : 46}" cy="103" rx="9" ry="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <circle cx="46" cy="46" r="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/><circle cx="46" cy="46" r="3.6" fill="${c.shade}"/>
      ${mirror(`<circle cx="46" cy="46" r="8.5" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/><circle cx="46" cy="46" r="3.6" fill="${c.shade}"/>`)}
      <ellipse cx="60" cy="56" rx="26" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <ellipse cx="60" cy="66" rx="16" ry="11" fill="${c.shade}"/>
      <ellipse cx="60" cy="60" rx="6" ry="4" fill="${INK}"/>
      <path d="M60 63 v6 M60 69 q-5 3 -9 1 M60 69 q5 3 9 1" stroke="${INK}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      ${eyes(49, 71, 50, 2.8, eyeInk(c))}
    </g>`,

  // ── Black Bear — leaner build, taller ears, pale muzzle, longer snout than brown bear (tier 2)
  blackbear: (c) => `
    <g class="breathe"><path d="M36 96 Q34 62 60 60 Q86 62 84 96 Q60 106 36 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 68 : 44}" y="94" width="9" height="14" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <circle cx="41" cy="35" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/><circle cx="41" cy="35" r="5.5" fill="${c.shade}"/>
      ${mirror(`<circle cx="41" cy="35" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/><circle cx="41" cy="35" r="5.5" fill="${c.shade}"/>`)}
      <path d="M41 50 Q41 76 60 78 Q79 76 79 50 Q60 41 41 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M50 62 Q50 78 60 80 Q70 78 70 62 Q60 56 50 62 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="62" rx="4.2" ry="3" fill="${INK}"/>
      <path d="M60 65 v5 M60 70 q-4 3 -7 1 M60 70 q4 3 7 1" stroke="${INK}" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      ${eyes(51, 69, 52, 2.6, eyeInk(c))}
    </g>`,

  // ── Raccoon — black bandit MASK, ringed bushy tail, rounded ears, cheeky grin (unmistakable)
  raccoon: (c) => `
    <g class="tail-wag"><path d="M28 94 C8 90 8 66 24 62 C30 66 32 78 40 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${[0, 1, 2].map(i => `<path d="M${24 - i * 4} ${86 - i * 8} q6 6 12 3" stroke="${INK}" stroke-width="4" fill="none" stroke-linecap="round"/>`).join("")}</g>
    <g class="breathe"><ellipse cx="62" cy="88" rx="24" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="62" cy="92" rx="13" ry="9" fill="${c.shade}" opacity=".7"/></g>
    <g class="head-tilt">
      <path d="M44 44 Q40 30 52 34 Q52 42 56 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      ${mirror(`<path d="M44 44 Q40 30 52 34 Q52 42 56 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="56" rx="22" ry="19" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 52 Q50 44 54 56 Q50 64 42 62 Q38 56 40 52 Z" fill="${INK}"/>
      ${mirror(`<path d="M40 52 Q50 44 54 56 Q50 64 42 62 Q38 56 40 52 Z" fill="${INK}"/>`)}
      <path d="M60 46 Q54 46 55 40 M60 46 Q66 46 65 40" stroke="${INK}" stroke-width="1.4" fill="none"/>
      <path d="M52 66 Q60 74 68 66 Q60 70 52 66 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="65" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(50, 70, 54, 3, "#f7f4ec")}
      <path d="M60 67 v3" stroke="${INK}" stroke-width="1.3"/>
    </g>`,

  // ── Red Squirrel — huge bushy tail arcing over the back, ear tufts, clutching an acorn
  redsquirrel: (c) => `
    <g class="tail-wag"><path d="M40 92 C14 96 8 56 30 30 C40 40 34 62 46 74 C40 82 40 88 40 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M32 34 C18 54 20 82 34 88" stroke="${c.shade}" stroke-width="3" fill="none" opacity=".6"/></g>
    <g class="breathe"><path d="M48 96 Q44 66 62 66 Q80 68 78 96 Q62 102 48 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="62" cy="88" rx="10" ry="12" fill="${c.shade}" opacity=".7"/>
      <ellipse cx="62" cy="90" rx="7" ry="8" fill="#c98a4a" stroke="${c.line}" stroke-width="1.8"/>
      <path d="M62 82 q0 -4 4 -4 M55 84 h14" stroke="${c.line}" stroke-width="1.6" fill="none"/></g>
    <g class="head-tilt">
      <path d="M50 44 Q48 28 58 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M52 40 q-1 -6 3 -4" stroke="${INK}" stroke-width="2" fill="none"/>
      ${mirror(`<path d="M50 44 Q48 28 58 36 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M52 40 q-1 -6 3 -4" stroke="${INK}" stroke-width="2" fill="none"/>`)}
      <circle cx="62" cy="54" r="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M55 60 q7 8 14 0 Z" fill="${c.shade}"/>
      <ellipse cx="62" cy="60" rx="2.4" ry="1.8" fill="${INK}"/>
      ${eyes(55, 69, 52, 2.8, eyeInk(c))}
    </g>`,

  // ── Chipmunk — small, dark racing STRIPES down the back, fat cheek pouches, perky short tail
  chipmunk: (c) => `
    <g class="tail-wag"><path d="M34 88 C16 84 16 60 30 56 C34 64 34 78 44 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="62" cy="84" rx="22" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M62 68 v34" stroke="${INK}" stroke-width="2.6"/>
      <path d="M52 70 q-2 15 0 30 M72 70 q2 15 0 30" stroke="${INK}" stroke-width="2" fill="none" opacity=".85"/>
      <ellipse cx="62" cy="90" rx="10" ry="8" fill="${c.shade}" opacity=".6"/></g>
    <g class="head-tilt">
      <circle cx="52" cy="42" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="52" cy="42" r="3" fill="${c.shade}"/>
      ${mirror(`<circle cx="52" cy="42" r="7" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><circle cx="52" cy="42" r="3" fill="${c.shade}"/>`)}
      <ellipse cx="62" cy="56" rx="18" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="49" cy="60" rx="6" ry="5" fill="${c.shade}" opacity=".8"/>${mirror(`<ellipse cx="49" cy="60" rx="6" ry="5" fill="${c.shade}" opacity=".8"/>`)}
      <path d="M52 52 q4 3 0 6 M72 52 q-4 3 0 6" stroke="#fff" stroke-width="2" fill="none" opacity=".7"/>
      <ellipse cx="62" cy="60" rx="2.4" ry="1.8" fill="${INK}"/>
      ${eyes(55, 69, 52, 2.6, eyeInk(c))}
    </g>`,

  // ── Hedgehog — dome of triangular SPIKES over the back, tiny pointed pink face poking out
  hedgehog: (c) => `
    <g class="breathe">
      <path d="M26 84 Q22 46 60 44 Q98 46 94 84 Q60 96 26 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4"/>
      ${Array.from({ length: 22 }).map((_, i) => { const a = (200 + i * 6.6) * Math.PI / 180, r = 26; const x = 60 + Math.cos(a) * (r + 8), y = 66 + Math.sin(a) * (r * 0.7 + 6); const bx = 60 + Math.cos(a) * r, by = 66 + Math.sin(a) * r * 0.7; return `<path d="M${(bx - 3).toFixed(1)} ${by.toFixed(1)} L${x.toFixed(1)} ${y.toFixed(1)} L${(bx + 3).toFixed(1)} ${by.toFixed(1)} Z" fill="${c.body}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`; }).join("")}
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 74 : 46}" cy="90" rx="6" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M84 70 Q104 62 108 76 Q104 88 86 84 Q80 78 84 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <circle cx="106" cy="75" r="2.4" fill="${INK}"/>
      ${eye(94, 72, 2.6, eyeInk(c))}
      <path d="M96 80 q3 3 6 0" stroke="${INK}" stroke-width="1.3" fill="none"/>
    </g>`,

  // ── Badger — bold white face with two black eye-STRIPES, low stocky body, digging claws
  badger: (c) => `
    <g class="breathe"><ellipse cx="60" cy="86" rx="30" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="90" rx="18" ry="10" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<g><rect x="${i ? 70 : 42}" y="96" width="9" height="10" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
        ${[0, 1, 2].map(j => `<path d="M${(i ? 71 : 43) + j * 3} 105 v4" stroke="${CLAW}" stroke-width="2" stroke-linecap="round"/>`).join("")}</g>`).join("")}</g>
    <g class="head-tilt">
      <ellipse cx="44" cy="46" rx="6" ry="5" fill="${INK}"/>${mirror(`<ellipse cx="44" cy="46" rx="6" ry="5" fill="${INK}"/>`)}
      <path d="M42 54 Q40 74 60 76 Q80 74 78 54 Q60 46 42 54 Z" fill="#f4efe6" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M52 52 Q48 66 54 72 Q58 66 56 54 Z" fill="${INK}"/>${mirror(`<path d="M52 52 Q48 66 54 72 Q58 66 56 54 Z" fill="${INK}"/>`)}
      <path d="M56 68 q4 4 8 0 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="66" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(52, 68, 60, 2.4, INK)}
    </g>`,

  // ── Deer — slender neck, elegant branching ANTLERS, big ears, dappled spots (tier 2)
  deer: (c) => `
    <g class="breathe"><path d="M46 100 Q44 72 60 70 Q76 72 74 100 Q60 106 46 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[[52, 84], [66, 80], [58, 90]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.4" fill="${c.shade}"/>`).join("")}
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 50}" y="96" width="5" height="12" rx="2" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M55 47 Q51 26 46 15 M52 30 Q45 26 40 28 M53 37 Q46 35 42 39" stroke="${ANTLER}" stroke-width="3" fill="none" stroke-linecap="round"/>
      ${mirror(`<path d="M55 47 Q51 26 46 15 M52 30 Q45 26 40 28 M53 37 Q46 35 42 39" stroke="${ANTLER}" stroke-width="3" fill="none" stroke-linecap="round"/>`)}
      <path d="M44 46 Q34 40 34 52 Q40 56 46 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M44 46 Q34 40 34 52 Q40 56 46 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <path d="M50 48 Q48 66 60 72 Q72 66 70 48 Q60 42 50 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="68" rx="6" ry="5" fill="${c.shade}"/>
      <ellipse cx="60" cy="66" rx="3" ry="2.2" fill="${INK}"/>
      ${eyes(52, 68, 55, 2.6, eyeInk(c))}
    </g>`,

  // ── Moose — massive PALMATE (flat paddle) antlers, bulbous drooping snout, dewlap bell (tier 3)
  moose: (c) => `
    <g class="breathe"><path d="M40 100 Q38 68 60 66 Q82 68 80 100 Q60 108 40 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 68 : 46}" y="96" width="7" height="12" rx="2.6" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M56 44 Q32 38 20 44 Q26 28 50 34 Z" fill="${ANTLER}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M24 44 l-6 -2 M30 38 l-6 -4 M36 33 l-4 -6 M46 33 l-2 -6" stroke="${c.line}" stroke-width="1.6"/>
      ${mirror(`<path d="M56 44 Q32 38 20 44 Q26 28 50 34 Z" fill="${ANTLER}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M24 44 l-6 -2 M30 38 l-6 -4 M36 33 l-4 -6 M46 33 l-2 -6" stroke="${c.line}" stroke-width="1.6"/>`)}
      <path d="M50 46 Q46 42 42 46 Q46 52 50 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>${mirror(`<path d="M50 46 Q46 42 42 46 Q46 52 50 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M50 46 Q48 60 54 66 L54 82 Q60 88 66 82 L66 62 Q72 58 70 46 Q60 40 50 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M55 74 Q60 84 65 74 Q60 78 55 74 Z" fill="${c.shade}"/>
      <path d="M56 66 h8" stroke="${INK}" stroke-width="1.4"/>
      <ellipse cx="60" cy="70" rx="4.4" ry="3.4" fill="${INK}"/>
      <path d="M60 86 Q56 96 60 100 Q64 96 60 86 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      ${eyes(53, 67, 56, 2.6, eyeInk(c))}
    </g>`,

  // ── Elk — tall multi-tined sweeping ANTLERS, shaggy neck mane, pale rump (tier 3)
  elk: (c) => `
    <g class="breathe"><path d="M44 100 Q42 70 60 68 Q78 70 76 100 Q60 106 44 100 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="94" rx="12" ry="9" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 50}" y="96" width="6" height="12" rx="2.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M54 47 Q46 20 38 10 M49 30 Q39 26 33 30 M51 21 Q43 17 37 19 M46 38 Q38 36 34 42" stroke="${ANTLER}" stroke-width="2.8" fill="none" stroke-linecap="round"/>
      ${mirror(`<path d="M54 47 Q46 20 38 10 M49 30 Q39 26 33 30 M51 21 Q43 17 37 19 M46 38 Q38 36 34 42" stroke="${ANTLER}" stroke-width="2.8" fill="none" stroke-linecap="round"/>`)}
      <path d="M48 52 Q40 68 48 84 Q52 70 54 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>
      <path d="M50 48 Q48 66 60 74 Q72 66 70 48 Q60 42 50 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M54 68 q6 5 12 0 Q60 74 54 68 Z" fill="${c.shade}"/>
      <path d="M55 62 h10" stroke="${INK}" stroke-width="1.3"/>
      <ellipse cx="60" cy="68" rx="3.4" ry="2.6" fill="${INK}"/>
      ${eyes(53, 67, 55, 2.6, eyeInk(c))}
    </g>`,

  // ── Wild Boar — curved TUSKS, flat disc snout, bristly mane ridge, stocky (tier 2)
  wildboar: (c) => `
    <g class="breathe"><ellipse cx="60" cy="82" rx="30" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${Array.from({ length: 7 }).map((_, i) => `<path d="M${44 + i * 6} 62 l-2 -8" stroke="${INK}" stroke-width="2" stroke-linecap="round"/>`).join("")}
      <ellipse cx="60" cy="90" rx="16" ry="9" fill="${c.shade}" opacity=".6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 70 : 42}" y="96" width="8" height="10" rx="2" fill="${INK}" stroke="${c.line}" stroke-width="1.6"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M40 42 Q36 32 44 34 Q46 42 48 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>${mirror(`<path d="M40 42 Q36 32 44 34 Q46 42 48 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M40 50 Q38 72 60 74 Q82 72 80 50 Q60 42 40 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="60" cy="66" rx="12" ry="9" fill="${c.shade}"/>
      <ellipse cx="55" cy="66" rx="2" ry="2.6" fill="${INK}"/><ellipse cx="65" cy="66" rx="2" ry="2.6" fill="${INK}"/>
      <path d="M50 70 Q52 82 56 74 Z" fill="${TUSK}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M70 70 Q68 82 64 74 Z" fill="${TUSK}" stroke="${c.line}" stroke-width="1.6"/>
      ${eyes(50, 70, 54, 2.4, eyeInk(c))}
    </g>`,

  // ── Beaver — big orange buck TEETH, flat cross-hatched PADDLE tail, round ears
  beaver: (c) => `
    <g class="tail-wag"><path d="M26 96 Q6 92 8 76 Q22 74 48 85 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M14 80 l14 6 M12 86 l16 4 M18 76 l10 8" stroke="${c.line}" stroke-width="1.2" opacity=".6"/></g>
    <g class="breathe"><ellipse cx="64" cy="84" rx="24" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="64" cy="90" rx="13" ry="9" fill="${c.shade}" opacity=".6"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 76 : 52}" cy="100" rx="6" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}</g>
    <g class="head-tilt">
      <circle cx="50" cy="42" r="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>${mirror(`<circle cx="50" cy="42" r="6" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <ellipse cx="60" cy="54" rx="19" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="58" rx="9" ry="7" fill="${c.shade}"/>
      <ellipse cx="60" cy="55" rx="3.4" ry="2.4" fill="${INK}"/>
      <rect x="56" y="62" width="8" height="9" rx="1.6" fill="#f2c94c" stroke="${c.line}" stroke-width="1.6"/><path d="M60 62 v9" stroke="${c.line}" stroke-width="1.2"/>
      ${eyes(52, 68, 48, 2.6, eyeInk(c))}
    </g>`,

  // ── Otter — sleek horizontal swimmer, whiskered muzzle, paws on belly, thick tapering tail (float)
  otter: (c) => `
    <g class="tail-wag"><path d="M96 74 Q116 70 112 84 Q104 90 92 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe"><ellipse cx="62" cy="76" rx="34" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="62" cy="82" rx="22" ry="8" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<ellipse cx="${i ? 70 : 54}" cy="88" rx="5" ry="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6"/>`).join("")}</g>
    <g class="head-tilt">
      <circle cx="28" cy="58" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><circle cx="28" cy="58" r="2.2" fill="${c.shade}"/>
      <path d="M40 58 q-8 4 0 8 M40 58 q8 4 0 8" stroke="${c.line}" stroke-width="0.1" fill="none"/>
      <ellipse cx="34" cy="62" rx="16" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="24" cy="66" rx="7" ry="6" fill="${c.shade}"/>
      <ellipse cx="21" cy="66" rx="2.6" ry="2" fill="${INK}"/>
      <path d="M22 66 l-9 -2 M22 68 l-9 1 M22 70 l-8 4" stroke="${INK}" stroke-width="0.9" opacity=".7"/>
      ${eyes(30, 42, 58, 2.4, eyeInk(c))}
      <path d="M20 70 q4 3 8 0" stroke="${INK}" stroke-width="1.2" fill="none"/>
    </g>`,

  // ── Skunk — bold white STRIPE running head-to-tail over a black body, huge plume tail
  skunk: (c) => `
    <g class="tail-wag"><path d="M46 74 C18 78 8 44 30 34 C40 46 34 66 52 70 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M30 40 C14 54 22 68 46 74" stroke="#f4efe6" stroke-width="5" fill="none" opacity=".9"/></g>
    <g class="breathe"><ellipse cx="64" cy="84" rx="24" ry="17" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M52 68 Q54 84 52 100 M76 68 Q74 84 76 100" fill="none"/>
      <path d="M58 68 Q60 84 58 101 L70 101 Q68 84 70 68 Z" fill="#f4efe6" opacity=".92"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 70 : 50}" y="96" width="6" height="10" rx="2.4" fill="${c.body}" stroke="${c.line}" stroke-width="1.8"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M50 44 Q48 34 56 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>${mirror(`<path d="M50 44 Q48 34 56 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`)}
      <path d="M46 52 Q44 72 60 74 Q76 72 74 52 Q60 44 46 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M58 46 Q60 60 58 68 L62 68 Q64 60 62 46 Z" fill="#f4efe6" opacity=".92"/>
      <path d="M52 66 q8 6 16 0 Z" fill="${c.shade}"/>
      <ellipse cx="60" cy="66" rx="2.6" ry="2" fill="${INK}"/>
      ${eyes(52, 68, 56, 2.4, "#f7f4ec")}
    </g>`,

  // ── Mole — velvety, near-blind (tiny eyes), star-pink snout, giant pink shovel CLAWS
  mole: (c) => `
    <g class="breathe"><ellipse cx="58" cy="78" rx="30" ry="20" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="58" cy="84" rx="18" ry="10" fill="${c.shade}" opacity=".7"/></g>
    <g class="tail-wag">
      <g><ellipse cx="30" cy="92" rx="12" ry="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" transform="rotate(-18 30 92)"/>
        ${[0, 1, 2, 3].map(i => `<path d="M${20 + i * 5} 96 l-3 6" stroke="#e79fae" stroke-width="3.4" stroke-linecap="round"/>`).join("")}</g>
      <g><ellipse cx="86" cy="92" rx="12" ry="8" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" transform="rotate(18 86 92)"/>
        ${[0, 1, 2, 3].map(i => `<path d="M${82 + i * 5} 96 l3 6" stroke="#e79fae" stroke-width="3.4" stroke-linecap="round"/>`).join("")}</g>
    </g>
    <g class="head-tilt">
      <path d="M40 62 Q22 60 18 68 Q22 76 40 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M22 68 m-5 0 a5 5 0 1 0 10 0 a5 5 0 1 0 -10 0" fill="#e79fae" stroke="${c.line}" stroke-width="1.6"/>
      ${[0, 1, 2, 3, 4].map(i => `<path d="M17 68 l-4 ${(-4 + i * 2)}" stroke="#e79fae" stroke-width="2" stroke-linecap="round"/>`).join("")}
      ${eyes(40, 46, 62, 1.6, INK)}
    </g>`,

  // ── Bat — spread membranous WINGS with finger struts, big ears, fangs, hanging cute (float)
  bat: (c) => `
    <g class="tail-wag">
      <path d="M50 60 Q20 40 8 58 Q22 58 20 68 Q32 62 34 72 Q42 64 50 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M14 55 L34 66 M24 52 L40 68 M34 54 L46 68" stroke="${c.line}" stroke-width="1.4" opacity=".7"/>
      ${mirror(`<path d="M50 60 Q20 40 8 58 Q22 58 20 68 Q32 62 34 72 Q42 64 50 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/><path d="M14 55 L34 66 M24 52 L40 68 M34 54 L46 68" stroke="${c.line}" stroke-width="1.4" opacity=".7"/>`)}
    </g>
    <g class="breathe"><ellipse cx="60" cy="70" rx="15" ry="16" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <ellipse cx="60" cy="76" rx="8" ry="8" fill="${c.shade}" opacity=".6"/></g>
    <g class="head-tilt">
      <path d="M50 52 L46 34 L58 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M51 48 L49 40 L55 47 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M50 52 L46 34 L58 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M51 48 L49 40 L55 47 Z" fill="${c.shade}"/>`)}
      <ellipse cx="60" cy="58" rx="14" ry="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${eyes(54, 66, 56, 2.6, eyeInk(c))}
      <path d="M56 64 l2 5 l2 -5 Z" fill="#fff"/><path d="M64 64 l-2 5 l-2 -5 Z" fill="#fff"/>
      <ellipse cx="60" cy="62" rx="2" ry="1.6" fill="${INK}"/>
    </g>`,

  // ── Owl — huge round facial discs + eyes, ear tufts, hooked beak, scalloped feather breast (tier 2)
  owl: (c) => `
    <g class="breathe"><path d="M36 88 Q32 56 60 54 Q88 56 84 88 Q60 98 36 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      ${[0, 1, 2].map(r => `<path d="M${46} ${68 + r * 8} q7 6 14 0 q7 6 14 0" stroke="${c.shade}" stroke-width="1.6" fill="none" opacity=".8"/>`).join("")}
      ${["", "s"].map((_, i) => `<path d="M${i ? 66 : 46} 92 l3 6 l3 -6" stroke="${BEAK}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`).join("")}</g>
    <g class="head-tilt">
      <path d="M42 40 L46 26 L52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${mirror(`<path d="M42 40 L46 26 L52 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>`)}
      <ellipse cx="60" cy="48" rx="26" ry="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <circle cx="50" cy="48" r="11" fill="${c.shade}"/>${mirror(`<circle cx="50" cy="48" r="11" fill="${c.shade}"/>`)}
      <circle cx="50" cy="48" r="9" fill="#fbf6e8" stroke="${c.line}" stroke-width="1.4"/>${mirror(`<circle cx="50" cy="48" r="9" fill="#fbf6e8" stroke="${c.line}" stroke-width="1.4"/>`)}
      <circle cx="50" cy="48" r="5" fill="${INK}"/><circle cx="52" cy="46" r="1.6" fill="#fff"/>
      <circle cx="70" cy="48" r="5" fill="${INK}"/><circle cx="72" cy="46" r="1.6" fill="#fff"/>
      <path d="M60 50 l-4 6 h8 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.4"/>
    </g>`,

  // ── Woodpecker — clinging vertical to a bark trunk, long chisel BEAK, spiky red crest, stiff tail
  woodpecker: (c) => `
    <path d="M78 20 Q92 20 92 40 L92 100 Q92 108 82 108 L78 108 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" opacity=".55"/>
    <path d="M82 34 h8 M82 52 h8 M82 74 h8 M82 90 h6" stroke="${c.line}" stroke-width="1.2" opacity=".4"/>
    <g class="tail-wag"><path d="M56 92 Q52 108 60 112 Q68 108 64 92 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe"><path d="M44 84 Q42 54 60 52 Q78 54 76 88 Q60 96 44 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M56 62 Q60 66 64 62 M56 72 Q60 76 64 72" stroke="${c.shade}" stroke-width="1.6" fill="none"/>
      <path d="M70 60 Q84 66 82 78 Q76 72 70 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/></g>
    <g class="head-tilt">
      <path d="M46 42 Q44 30 54 26 Q52 34 56 40 Z" fill="#e2513e" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="52" cy="46" rx="16" ry="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M40 48 L14 44 L40 54 Z" fill="${BEAK}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(50, 44, 3, eyeInk(c))}
      <path d="M44 52 q4 3 8 1" stroke="${INK}" stroke-width="1.2" fill="none" opacity=".6"/>
    </g>`,

  // ── Porcupine — dense field of long banded QUILLS bristling off the back, small blunt face (tier 2)
  porcupine: (c) => `
    <g class="breathe">
      ${Array.from({ length: 34 }).map((_, i) => { const a = (182 + i * 5) * Math.PI / 180; const bx = 62 + Math.cos(a) * 25, by = 67 + Math.sin(a) * 20; const L = 20 + (i % 3) * 6; const tx = 62 + Math.cos(a) * (25 + L), ty = 67 + Math.sin(a) * (20 + L * 0.8); return `<line x1="${bx.toFixed(1)}" y1="${by.toFixed(1)}" x2="${tx.toFixed(1)}" y2="${ty.toFixed(1)}" stroke="${c.line}" stroke-width="2.4" stroke-linecap="round"/><line x1="${bx.toFixed(1)}" y1="${by.toFixed(1)}" x2="${((bx + tx) / 2).toFixed(1)}" y2="${((by + ty) / 2).toFixed(1)}" stroke="#f4efe6" stroke-width="1.3" stroke-linecap="round"/>`; }).join("")}
      <path d="M28 82 Q26 48 62 46 Q98 48 96 82 Q62 94 28 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M36 84 Q62 93 88 84 Q62 90 36 84 Z" fill="${c.shade}" opacity=".5"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 72 : 44} 87 q-3 9 1 13 l6 0 q3 -5 1 -13 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M32 68 Q12 64 14 80 Q20 90 36 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M31 64 Q27 59 32 57 Q36 60 35 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="15" cy="77" rx="3.4" ry="2.8" fill="${INK}"/>
      <path d="M21 82 q5 3 9 -1" stroke="${INK}" stroke-width="1.2" fill="none"/>
      ${eye(30, 72, 2.6, eyeInk(c))}
    </g>`,
};

export const ROSTER_WOODLAND = [
  { n: "Red Fox",     e: "🦊", tier: 1, float: false },
  { n: "Gray Wolf",   e: "🐺", tier: 2, float: false },
  { n: "Brown Bear",  e: "🐻", tier: 3, float: false },
  { n: "Black Bear",  e: "🐻‍⬛", tier: 2, float: false },
  { n: "Raccoon",     e: "🦝", tier: 1, float: false },
  { n: "Red Squirrel",e: "🐿️", tier: 1, float: false },
  { n: "Chipmunk",    e: "🐿️", tier: 1, float: false },
  { n: "Hedgehog",    e: "🦔", tier: 1, float: false },
  { n: "Badger",      e: "🦡", tier: 2, float: false },
  { n: "Deer",        e: "🦌", tier: 2, float: false },
  { n: "Moose",       e: "🫎", tier: 3, float: false },
  { n: "Elk",         e: "🦌", tier: 3, float: false },
  { n: "Wild Boar",   e: "🐗", tier: 2, float: false },
  { n: "Beaver",      e: "🦫", tier: 1, float: false },
  { n: "Otter",       e: "🦦", tier: 1, float: true  },
  { n: "Skunk",       e: "🦨", tier: 1, float: false },
  { n: "Mole",        e: "🐭", tier: 1, float: false },
  { n: "Bat",         e: "🦇", tier: 1, float: true  },
  { n: "Owl",         e: "🦉", tier: 2, float: false },
  { n: "Woodpecker",  e: "🪶", tier: 1, float: false },
  { n: "Porcupine",   e: "🦔", tier: 2, float: false },
];
