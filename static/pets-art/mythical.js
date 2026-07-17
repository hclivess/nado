// pets-art/mythical.js — BESPOKE hand-drawn SVG art for MYTHICAL & LEGENDARY creatures (NADO Pets).
// These are the rarest chase pets (tier 4–6). Each value: (c, v) => "<svg inner markup>" for
// viewBox 0 0 120 120, creature centered ~ (60,62), within x,y ∈ [8,112]. Colours come from the coat
// object c (c.body main / c.shade accent / c.line outline); the palette is applied at runtime so real
// hues are NOT hardcoded — only magical accents (fire/horns/teeth/runes) use fixed warm/glow tints.
// Animate: torso <g class="breathe">, head <g class="head-tilt">, tails/wings/fins <g class="tail-wag">.
// Fliers/aquatic (dragon, phoenix, pegasus, kraken, wyvern, fairy) set float:true and orient horizontally.
import { pom, tube, eyes, eye, smile, eyeInk, INK, mirror } from "../pets-draw.js";

// fixed magical accents that stay constant across coats
const HORN = "#f2c94c", IVORY = "#f4efe2", TOOTH = "#ffffff", FIRE = "#ff7a1a", FIRE2 = "#ffd24a",
  MANE = "#f2a03b", MAGIC = "#bfe3ff", GLOW = "#eafff4", RUNE = "#7fe3ff", GEM = "#ff5d8f";

export const ART_MYTHICAL = {
  // ── Dragon — chunky winged serpent, golden horns, spine ridges, plated belly, clawed legs, spade tail (float, head right)
  dragon: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M40 74 Q18 84 10 66 Q6 56 18 52", c.body, c.line, 9)}
      <path d="M18 52 l-9 -5 l3 9 l-9 -1 l6 7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M66 50 Q60 12 28 18 Q40 32 46 52 Q40 46 30 44 Q42 56 52 60 Q44 58 36 60 Q52 68 66 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M60 52 Q46 30 34 24 M58 55 Q48 44 40 42" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".65"/>
    </g>
    <g class="breathe">
      ${[46,56,66,76].map(x=>`<path d="M${x} 50 l4 -9 l4 9 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("")}
      <path d="M36 66 Q36 46 62 46 Q86 46 90 66 Q86 84 62 84 Q36 84 36 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 78 Q62 89 82 78 Q62 84 46 78 Z" fill="${c.shade}"/>
      <path d="M50 80 h27 M53 84 h21" stroke="${c.line}" stroke-width="0.9" opacity=".5"/>
      ${tube("M52 82 q-3 11 3 16", c.body, c.line, 6)}${tube("M70 82 q3 11 9 14", c.body, c.line, 6)}
      <path d="M54 100 l-3 3 m3 -3 l0 4 m0 -4 l3 3 M78 98 l-3 3 m3 -3 l0 4 m0 -4 l3 3" stroke="${IVORY}" stroke-width="1.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 42 Q80 24 68 20 Q75 33 77 47 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M93 42 Q92 24 82 18 Q86 32 88 47 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="92" cy="57" rx="15" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M100 51 Q114 51 112 63 Q108 69 99 65 Q96 57 100 51 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M100 64 l1.4 4 l1.4 -4 Z M105 64 l1.4 4 l1.4 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      <ellipse cx="108" cy="56" rx="1.4" ry="1.1" fill="${INK}"/>
      ${eye(93, 53, 3.4, E)}
    </g>`;
  },

  // ── Phoenix — reborn firebird, flaming spread wings, crested crown of flame, plumed fire tail, gold beak (float)
  phoenix: (c) => {
    const E = eyeInk(c);
    const wing = `
      <path d="M64 58 Q86 42 110 28 Q106 46 96 52 Q110 50 116 58 Q100 62 92 58 Q100 68 98 78 Q84 66 64 63 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M66 58 Q86 46 102 38 Q98 50 92 54 Z" fill="${FIRE2}"/>`;
    const plume = (x, s) => `<path d="M${x} 82 Q${x - s*3} 104 ${x - s*1} 114 Q${x + s*2} 102 ${x + s*3} 84 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M${x} 86 Q${x - s*2} 100 ${x} 108" fill="none" stroke="${FIRE2}" stroke-width="1.6"/>`;
    return `
    <g class="tail-wag">${plume(50,1)}${plume(70,-1)}${plume(60,1)}</g>
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M60 44 Q76 46 76 66 Q76 86 60 88 Q44 86 44 66 Q44 46 60 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 58 Q68 60 68 72 Q68 82 60 84 Q52 82 52 72 Q52 60 60 58 Z" fill="${c.shade}"/>
      <path d="M54 62 q6 5 12 0 M56 70 q4 4 8 0" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>
    </g>
    <g class="head-tilt">
      <path d="M52 30 Q48 16 42 12 Q52 20 54 30 Z M60 26 Q60 12 60 8 Q66 16 66 28 Z M68 30 Q72 16 78 12 Q68 20 66 30 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="60" cy="40" r="12" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M56 44 L60 51 L64 44 Z" fill="${MANE}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eyes(55, 65, 38, 3, E)}
    </g>`;
  },

  // ── Griffin — eagle head + wings + lion body, hooked beak, feathered chest, taloned fore-claws, tufted lion tail (profile, right)
  griffin: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M30 78 Q12 82 14 66 Q16 56 26 58", c.body, c.line, 6)}
      ${pom(15, 66, 7, c.shade, c.line, 7, 2)}
    </g>
    <g class="tail-wag">
      <path d="M56 52 Q40 22 22 14 Q30 34 36 46 Q30 40 22 40 Q34 52 42 56 Q34 54 28 58 Q46 66 60 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M52 52 Q40 32 28 24 M50 55 Q40 44 32 42" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
    </g>
    <g class="breathe">
      <path d="M34 74 Q34 54 60 54 Q84 54 88 72 Q84 88 58 88 Q34 88 34 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M44 86 Q56 92 68 86" fill="none" stroke="${c.shade}" stroke-width="1.4" opacity=".6"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 74 : 40}" y="84" width="9" height="18" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
      <path d="M40 102 l-3 3 m3 -3 l0 4 m0 -4 l3 3 M42 102 l0 4" stroke="${IVORY}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M78 46 Q80 34 86 32 Q84 42 86 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="90" cy="56" rx="13" ry="12" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M60 60 Q66 50 78 52 Q72 58 74 66 Q66 62 60 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round" opacity=".85"/>
      <path d="M101 52 Q114 54 111 62 Q106 62 100 62 Q100 56 101 52 Z" fill="${MANE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M100 62 q6 3 10 0" fill="none" stroke="${c.line}" stroke-width="1.2"/>
      ${eye(91, 53, 3, E)}
    </g>`;
  },

  // ── Unicorn — graceful pony, single golden spiral horn, flowing mane + tail, cloven-free hooves, sparkle (profile, right)
  unicorn: (c) => {
    const E = eyeInk(c);
    const spiral = Array.from({ length: 5 }, (_, i) => `<path d="M${88 + i} ${34 - i*3.4} q3 -1 4 -3" fill="none" stroke="${c.line}" stroke-width="0.9" opacity=".8"/>`).join("");
    return `
    <g class="tail-wag">
      <path d="M30 74 Q10 78 12 96 Q18 92 22 84 Q18 96 26 100 Q26 88 34 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M34 72 Q34 54 60 54 Q84 54 86 70 Q84 84 58 84 Q34 84 34 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 72 : 42}" y="82" width="8" height="20" rx="2.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><rect x="${i ? 72 : 42}" y="99" width="8" height="4" rx="1.4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M78 40 Q92 42 92 58 Q92 70 80 70 Q68 68 70 52 Q72 42 78 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M84 58 Q94 58 94 66 Q90 70 82 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="90" cy="64" rx="1.3" ry="1.1" fill="${INK}"/>
      <path d="M72 42 Q66 30 74 22 Q80 30 82 40 Z" fill="${MANE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M84 40 L91 12 L96 40 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${spiral}
      <path d="M70 46 Q52 44 46 58 Q56 52 66 56 Q52 56 48 68 Q60 60 68 62 Z" fill="${MANE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M40 22 l1.5 4 l4 1.5 l-4 1.5 l-1.5 4 l-1.5 -4 l-4 -1.5 l4 -1.5 Z" fill="${GLOW}" stroke="${HORN}" stroke-width="0.8" stroke-linejoin="round"/>
      ${eye(80, 52, 2.8, E)}
    </g>`;
  },

  // ── Pegasus — winged stallion, broad feathered wings, streaming mane + tail, galloping legs (float, head right)
  pegasus: (c) => {
    const E = eyeInk(c);
    const feath = `<path d="M62 56 Q44 30 20 22 Q30 40 34 50 Q26 46 18 48 Q30 56 40 58 Q30 60 24 66 Q44 70 62 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M56 56 Q42 42 28 36 M54 58 Q42 50 32 50 M52 60 Q42 56 34 60" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".6"/>`;
    return `
    <g class="tail-wag">
      <path d="M32 70 Q12 68 8 84 Q16 80 22 74 Q14 86 22 90 Q24 78 36 74 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">${feath}</g>
    <g class="breathe">
      <path d="M36 68 Q36 50 62 50 Q86 50 90 66 Q86 80 60 82 Q36 82 36 68 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 78 q6 10 2 22 M56 80 q4 10 0 20 M68 80 q4 10 8 20 M80 76 q4 10 8 18" fill="none" stroke="${c.line}" stroke-width="6" stroke-linecap="round"/>
      <path d="M42 78 q6 10 2 22 M56 80 q4 10 0 20 M68 80 q4 10 8 20 M80 76 q4 10 8 18" fill="none" stroke="${c.body}" stroke-width="3.6" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M86 48 Q100 50 100 64 Q100 74 90 74 Q80 72 82 58 Q83 50 86 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M92 62 Q102 62 102 70 Q98 74 90 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <ellipse cx="98" cy="67" rx="1.3" ry="1.1" fill="${INK}"/>
      <path d="M82 48 Q76 34 84 28 Q90 36 92 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M80 52 Q64 48 58 60 Q68 55 76 58 Q64 60 60 70 Q72 62 80 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(89, 58, 2.8, E)}
    </g>`;
  },

  // ── Kraken — colossal squid-beast, domed spiky mantle, glowing eyes, eight thick suckered tentacles, hooked beak (float)
  kraken: (c) => {
    const E = eyeInk(c);
    const arms = ["M40 76 Q20 84 14 104 Q12 112 20 110","M50 82 Q38 100 42 112",
      "M58 84 Q54 104 64 112","M66 84 Q70 104 82 110",
      "M74 80 Q94 86 100 106 Q102 112 94 110","M34 70 Q14 70 8 82","M86 70 Q106 70 112 82",
      "M60 86 Q60 106 60 112"];
    const suckers = arms.map((d) => { const m = d.match(/Q(\d+) (\d+)/); return `<circle cx="${+m[1]}" cy="${+m[2]}" r="1.8" fill="${c.shade}"/>`; }).join("");
    const horns = [[38,40],[50,30],[70,30],[82,40]].map(([x,y])=>`<path d="M${x} ${y+8} L${x-2} ${y} L${x+3} ${y+2} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>`).join("");
    return `
    <g class="tail-wag">${arms.map((d) => tube(d, c.body, c.line, 8)).join("")}${suckers}</g>
    <g class="breathe">
      ${horns}
      <path d="M30 62 Q30 28 60 26 Q90 28 90 62 Q90 78 60 80 Q30 78 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M42 36 Q54 28 62 32 Q50 36 46 44 Z" fill="#fff" opacity=".22"/>
      <path d="M46 70 Q60 82 74 70 Q68 66 60 66 Q52 66 46 70 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M54 66 l2 5 l2 -5 Z M62 66 l2 5 l2 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M40 48 q8 -5 14 1 M66 49 q6 -6 14 -1" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="48" cy="56" r="7" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="72" cy="56" r="7" fill="${GLOW}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="48" cy="56" r="3" fill="${INK}"/><circle cx="72" cy="56" r="3" fill="${INK}"/>
      <circle cx="46" cy="54" r="1.1" fill="#fff"/><circle cx="70" cy="54" r="1.1" fill="#fff"/>
    </g>`;
  },

  // ── Cerberus — three-headed hound, one body, three snarling heads with fangs, spiked collar, sturdy legs, tail (front)
  cerberus: (c) => {
    const E = eyeInk(c);
    const head = (cx, cy, r) => `
      <path d="M${cx-r*0.7} ${cy-r*0.7} L${cx-r*1.1} ${cy-r*1.7} L${cx-r*0.1} ${cy-r} Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M${cx+r*0.7} ${cy-r*0.7} L${cx+r*1.1} ${cy-r*1.7} L${cx+r*0.1} ${cy-r} Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M${cx-r*0.5} ${cy+r*0.2} Q${cx} ${cy+r*1.1} ${cx+r*0.5} ${cy+r*0.2} Q${cx} ${cy+r*0.6} ${cx-r*0.5} ${cy+r*0.2} Z" fill="${c.shade}"/>
      <path d="M${cx-4} ${cy+r*0.55} l2 4 l2 -4 Z M${cx} ${cy+r*0.55} l2 4 l2 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>
      <ellipse cx="${cx}" cy="${cy+r*0.15}" rx="2" ry="1.6" fill="${INK}"/>
      ${eyes(cx-r*0.45, cx+r*0.45, cy-r*0.15, 2.4, E)}`;
    return `
    <g class="tail-wag">${tube("M84 92 Q100 90 100 74 Q100 66 92 68", c.body, c.line, 6)}</g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="26" ry="18" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M40 90 Q60 100 80 90 Q60 96 40 90 Z" fill="${c.shade}" opacity=".7"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 66 : 44}" y="94" width="10" height="16" rx="4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
      <path d="M36 74 Q60 84 84 74" fill="none" stroke="${MANE}" stroke-width="3.4" stroke-linecap="round"/>
      ${[42,52,60,68,78].map(x=>`<path d="M${x} ${74+(x===60?4:0)} l0 4" stroke="${HORN}" stroke-width="2.6" stroke-linecap="round"/>`).join("")}
    </g>
    <g class="head-tilt">
      ${head(38, 54, 12)}
      ${head(82, 54, 12)}
      ${head(60, 46, 15)}
    </g>`;
  },

  // ── Hydra — many-necked water-serpent, coiled body, three rearing heads with fins & fangs, scaled belly (profile)
  hydra: (c) => {
    const E = eyeInk(c);
    const neck = (bx, by, hx, hy) => `${tube(`M${bx} ${by} Q${(bx+hx)/2 - 6} ${(by+hy)/2} ${hx} ${hy}`, c.body, c.line, 8)}`;
    const serp = (hx, hy) => `
      <path d="M${hx-4} ${hy-10} Q${hx} ${hy-16} ${hx+6} ${hy-12} Q${hx+2} ${hy-8} ${hx+2} ${hy-6} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M${hx-8} ${hy-4} Q${hx-9} ${hy-13} ${hx-2} ${hy-15} Q${hx+9} ${hy-14} ${hx+10} ${hy-2} Q${hx+12} ${hy+4} ${hx+4} ${hy+5} Q${hx-6} ${hy+5} ${hx-8} ${hy-4} Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M${hx+8} ${hy+2} q6 0 9 3 M${hx+8} ${hy+5} q6 2 10 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <path d="M${hx+13} ${hy+4} l4 -1 l-3 3 Z" fill="${GEM}" stroke="${c.line}" stroke-width="0.6"/>
      ${eye(hx+2, hy-3, 2.4, E)}`;
    return `
    <g class="tail-wag">
      ${neck(48, 68, 22, 34)} ${serp(22, 34)}
    </g>
    <g class="breathe">
      <path d="M32 78 Q32 60 60 60 Q88 60 90 76 Q86 92 58 92 Q32 92 32 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M42 88 Q60 96 80 88 Q60 92 42 88 Z" fill="${c.shade}"/>
      ${[40,52,64,76].map(x=>`<path d="M${x} 84 q4 3 8 0" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>`).join("")}
    </g>
    <g class="head-tilt">
      ${neck(56, 62, 50, 30)} ${serp(50, 30)}
      ${neck(66, 62, 82, 32)} ${serp(82, 32)}
    </g>`;
  },

  // ── Minotaur — bull-headed brute, muscled torso, curved horns, nose ring, snorting nostrils, hooved legs, fists (front)
  minotaur: (c) => {
    const E = eyeInk(c);
    return `
    <g class="breathe">
      <path d="M42 96 Q40 66 60 64 Q80 66 78 96 Q60 104 42 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M52 74 Q60 82 68 74 M52 82 Q60 88 68 82" fill="none" stroke="${c.shade}" stroke-width="1.6" opacity=".7"/>
      ${["", "s"].map((_, i) => `<path d="M${i ? 78 : 30} 70 Q${i ? 92 : 16} 74 ${i ? 88 : 20} 90" fill="none" stroke="${c.line}" stroke-width="8.4" stroke-linecap="round"/><path d="M${i ? 78 : 30} 70 Q${i ? 92 : 16} 74 ${i ? 88 : 20} 90" fill="none" stroke="${c.body}" stroke-width="5.4" stroke-linecap="round"/><circle cx="${i ? 20 : 20}" cy="90" r="0"/>`).join("")}
      <circle cx="20" cy="91" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      <circle cx="100" cy="91" r="5" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 48}" y="94" width="10" height="14" rx="2.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/><path d="M${i ? 62 : 48} 106 h10 l-1 4 h-8 Z" fill="${INK}"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M40 44 Q22 40 18 26 Q30 30 42 38 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M80 44 Q98 40 102 26 Q90 30 78 38 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M40 42 Q40 20 60 20 Q80 20 80 42 Q80 60 60 62 Q40 60 40 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 50 Q60 66 74 50 Q60 60 46 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="53" cy="53" rx="2" ry="1.6" fill="${INK}"/><ellipse cx="67" cy="53" rx="2" ry="1.6" fill="${INK}"/>
      <circle cx="60" cy="61" r="4" fill="none" stroke="${HORN}" stroke-width="2"/>
      <path d="M44 34 q6 -4 12 -1 M64 33 q6 -3 12 1" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${eyes(53, 67, 42, 3, E)}
    </g>`;
  },

  // ── Chimera — lion body + goat head on the back + serpent-headed tail, triple-beast, lion mane & fangs (profile)
  chimera: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M32 80 Q14 84 14 68 Q14 60 22 60", c.body, c.line, 6)}
      <path d="M22 60 Q10 56 8 62 Q10 68 20 66 Q14 62 22 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M12 60 l3 -3 M12 64 l3 3" fill="none" stroke="${c.line}" stroke-width="1"/>
      ${eye(13, 62, 1.6, "#e9edf2")}
    </g>
    <g class="tail-wag">
      <path d="M50 56 Q44 40 34 34 Q40 32 46 34 Q42 26 46 20 Q52 30 54 42 Q56 34 62 32 Q60 44 58 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M40 34 Q36 26 40 22 M46 20 Q44 14 48 12" fill="none" stroke="${IVORY}" stroke-width="2.4" stroke-linecap="round"/>
      <ellipse cx="42" cy="44" rx="1.4" ry="1.2" fill="${INK}"/>
      ${eye(45, 40, 2, E)}
    </g>
    <g class="breathe">
      <path d="M34 78 Q34 58 60 58 Q86 58 88 74 Q84 90 58 90 Q34 90 34 78 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 72 : 42}" y="86" width="9" height="18" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      ${pom(90, 58, 15, MANE, c.line, 10, 2)}
      <circle cx="90" cy="58" r="11" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M92 60 Q100 66 100 58 Q98 62 92 60 Z" fill="${c.shade}"/>
      <path d="M96 62 l1.6 4 l1.6 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      <ellipse cx="98" cy="59" rx="1.6" ry="1.3" fill="${INK}"/>
      ${eye(93, 54, 2.8, E)}
    </g>`;
  },

  // ── Basilisk — serpent-king, crested comb crown, long scaled coil, forked tongue, deadly glowing stare (profile)
  basilisk: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M62 84 Q86 88 88 70 Q88 58 76 58", c.body, c.line, 9)}
      <path d="M88 62 l6 -3 l-2 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M30 66 Q30 84 52 86 Q74 86 76 70 Q76 56 58 56 Q40 56 40 66 Q40 74 52 74 Q62 74 62 68" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${[36,46,56,66].map((x,i)=>`<path d="M${x} ${78+(i%2)*2} q4 3 8 0" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>`).join("")}
    </g>
    <g class="head-tilt">
      ${[0,1,2].map(i=>`<path d="M${34+i*7} 34 L${37+i*7} 22 L${41+i*7} 34 Z" fill="${GEM}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("")}
      <path d="M30 48 Q30 32 48 32 Q64 32 64 46 Q64 58 46 58 Q30 58 30 48 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M30 50 Q16 50 10 46 M30 54 Q16 56 10 60" fill="none" stroke="${GEM}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M28 52 Q34 56 42 54" fill="none" stroke="${c.line}" stroke-width="1.4"/>
      <path d="M36 44 q6 -3 12 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="46" cy="46" r="4.2" fill="${GLOW}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M46 43 v6" stroke="${INK}" stroke-width="1.8"/>
    </g>`;
  },

  // ── Kitsune — nine-tailed spirit fox, fanned bushy tails, sharp ears, mystic brow-mark, wisp of foxfire (front)
  kitsune: (c) => {
    const E = eyeInk(c);
    const tail = (a, len) => { const rad = a * Math.PI/180; const tx = 60 + len*Math.cos(rad), ty = 78 + len*Math.sin(rad);
      return `${tube(`M60 82 Q${(60+tx)/2} ${(80+ty)/2} ${tx.toFixed(1)} ${ty.toFixed(1)}`, c.body, c.line, 7)}<circle cx="${tx.toFixed(1)}" cy="${ty.toFixed(1)}" r="4.5" fill="${IVORY}" stroke="${c.line}" stroke-width="1.6"/>`; };
    return `
    <g class="tail-wag">${[196,210,224,238,252,308,322,336,350].map((a)=>tail(a, 30)).join("")}</g>
    <g class="breathe">
      <ellipse cx="60" cy="84" rx="20" ry="15" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M48 90 q12 8 24 0" fill="${c.shade}" opacity=".7"/>
    </g>
    <g class="head-tilt">
      <path d="M46 48 L38 22 L60 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M47 44 L43 28 L55 40 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M46 48 L38 22 L60 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M47 44 L43 28 L55 40 Z" fill="${c.shade}"/>`)}
      <path d="M40 52 Q40 74 60 76 Q80 74 80 52 Q60 42 40 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M50 60 Q60 82 70 60 Q66 72 60 72 Q54 72 50 60 Z" fill="${c.shade}"/>
      <path d="M56 42 Q60 36 64 42" fill="none" stroke="${GEM}" stroke-width="2" stroke-linecap="round"/>
      <ellipse cx="60" cy="68" rx="2.6" ry="2" fill="${INK}"/>
      <path d="M60 70 l-7 5 M60 70 l7 5" stroke="${INK}" stroke-width="1.4"/>
      ${eyes(51, 69, 56, 2.8, E)}
      <circle cx="30" cy="40" r="4" fill="${FIRE2}" opacity=".85"/><circle cx="30" cy="40" r="7" fill="${FIRE}" opacity=".2"/>
    </g>`;
  },

  // ── Wyvern — two-legged winged dragon, huge wing-arms, barbed whip tail, horned crest, sleek snout (float, head right)
  wyvern: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M40 72 Q18 78 12 60 Q8 48 20 46", c.body, c.line, 7)}
      <path d="M20 46 l-8 -6 l1 8 l-8 2 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
    </g>
    <g class="tail-wag">
      <path d="M60 52 Q54 12 22 12 Q34 26 40 42 Q30 34 20 36 Q34 48 46 52 Q34 52 26 58 Q48 66 62 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M56 50 Q42 26 28 18 M54 53 Q42 40 32 38" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".6"/>
      <path d="M22 12 l-4 -5 M40 42 l-3 -4" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="breathe">
      <path d="M38 66 Q38 48 62 48 Q84 48 88 64 Q84 80 60 82 Q38 80 38 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 76 Q62 84 80 76 Q62 82 46 76 Z" fill="${c.shade}"/>
      ${tube("M56 80 q-2 10 4 16", c.body, c.line, 6)}
      <path d="M58 96 l-3 3 m3 -3 l0 4 m0 -4 l3 3" stroke="${IVORY}" stroke-width="1.5" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M82 44 Q80 30 70 26 Q76 36 78 48 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M78 62 Q78 44 94 44 Q108 44 108 58 Q108 64 100 66 L112 66 Q110 74 100 72 Q80 74 78 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M104 66 l1.4 4 l1.4 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      <ellipse cx="108" cy="63" rx="1.3" ry="1" fill="${INK}"/>
      ${eye(90, 55, 3, E)}
    </g>`;
  },

  // ── Sphinx — reclining lion body with a serene pharaoh head, striped nemes headdress, calm eyes (profile)
  sphinx: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">${tube("M28 82 Q12 84 14 70 Q16 62 24 64", c.body, c.line, 5)}<circle cx="14" cy="70" r="4" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4"/></g>
    <g class="breathe">
      <path d="M24 84 Q24 72 60 70 Q92 70 96 82 Q92 92 58 92 Q24 92 24 84 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M28 84 Q26 78 34 78 Q42 78 42 86" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M84 84 Q84 78 90 78 Q96 78 96 84" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      <path d="M30 82 l-2 4 m2 -4 l1 5 m-1 -5 l3 4" stroke="${IVORY}" stroke-width="1.2" stroke-linecap="round"/>
    </g>
    <g class="head-tilt">
      <path d="M62 40 Q86 38 90 56 Q92 68 78 72 Q62 72 60 60 Q58 46 62 40 Z" fill="${HORN}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${[0,1,2,3].map(i=>`<path d="M${64+i*6} 42 Q${64+i*6} 58 ${62+i*6} 70" fill="none" stroke="${INK}" stroke-width="1.4" opacity=".55"/>`).join("")}
      <path d="M74 54 Q92 54 92 66 Q92 74 80 74 Q72 72 72 62 Q72 56 74 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M88 66 q4 3 4 6 Q88 74 86 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${smile(86, 68, 2.4, E)}
      ${eye(83, 60, 2.8, E)}
    </g>`;
  },

  // ── Yeti — hulking snow-ape, shaggy fluff outline, big friendly face, tiny horns, huge feet & arms (front)
  yeti: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${pom(30, 66, 10, c.body, c.line, 8, 2.4)}${pom(90, 66, 10, c.body, c.line, 8, 2.4)}
    </g>
    <g class="breathe">
      ${pom(60, 82, 28, c.body, c.line, 12, 2.6)}
      <ellipse cx="60" cy="86" rx="15" ry="14" fill="${c.shade}" opacity=".6"/>
      ${pom(44, 104, 9, c.body, c.line, 7, 2.2)}${pom(76, 104, 9, c.body, c.line, 7, 2.2)}
    </g>
    <g class="head-tilt">
      <path d="M48 30 l-3 -8 l6 4 Z M72 30 l3 -8 l-6 4 Z" fill="${IVORY}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${pom(60, 46, 20, c.body, c.line, 11, 2.6)}
      <ellipse cx="60" cy="52" rx="13" ry="11" fill="${c.shade}"/>
      <ellipse cx="60" cy="50" rx="3.4" ry="2.6" fill="${INK}"/>
      <path d="M52 60 Q60 66 68 60" fill="none" stroke="${INK}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M48 42 q5 -3 10 0 M62 42 q5 -3 10 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round" opacity=".6"/>
      ${eyes(51, 69, 42, 3, E)}
    </g>`;
  },

  // ── Werewolf — hunched bipedal wolf-man, fanged snarl, pointed ears, fur ruff, clawed hands, bushy tail (front)
  werewolf: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      <path d="M84 92 C104 92 108 70 92 60 C90 72 84 82 76 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M44 98 Q40 68 60 66 Q80 68 76 98 Q60 106 44 98 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${pom(60, 70, 16, c.shade, c.line, 9, 2)}
      ${["", "s"].map((_, i) => `<path d="M${i ? 76 : 30} 72 Q${i ? 94 : 14} 78 ${i ? 86 : 22} 94" fill="none" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/><path d="M${i ? 76 : 30} 72 Q${i ? 94 : 14} 78 ${i ? 86 : 22} 94" fill="none" stroke="${c.body}" stroke-width="5" stroke-linecap="round"/>`).join("")}
      <path d="M18 94 l-3 4 m3 -4 l1 5 m-1 -5 l3 4 M84 94 l3 4 m-3 -4 l-1 5 m1 -5 l-3 4" stroke="${IVORY}" stroke-width="1.5" stroke-linecap="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 48}" y="94" width="10" height="14" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M46 46 L38 22 L58 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M47 42 L43 28 L54 38 Z" fill="${c.shade}"/>
      ${mirror(`<path d="M46 46 L38 22 L58 38 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/><path d="M47 42 L43 28 L54 38 Z" fill="${c.shade}"/>`)}
      <path d="M42 50 Q42 70 60 72 Q78 70 78 50 Q60 40 42 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M48 60 Q60 78 72 60 Q60 66 48 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M51 60 l2 5 l2 -5 Z M65 60 l2 5 l2 -5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="55" rx="2.6" ry="2" fill="${INK}"/>
      <path d="M50 48 q4 3 8 2 M62 50 q4 -1 8 -2" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eyes(51, 69, 50, 2.8, "#ffd24a")}
    </g>`;
  },

  // ── Fairy — tiny chibi sprite, translucent butterfly wings, antennae, glowing wand, sparkles (float)
  fairy: (c) => {
    const E = eyeInk(c);
    const wing = `
      <path d="M56 60 Q30 40 26 58 Q28 70 42 70 Q30 74 32 86 Q46 84 56 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round" opacity=".92"/>
      <circle cx="38" cy="58" r="3" fill="${GLOW}" opacity=".8"/><circle cx="40" cy="76" r="2.4" fill="${GLOW}" opacity=".7"/>`;
    return `
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M52 66 Q52 56 60 56 Q68 56 68 66 Q68 82 60 86 Q52 82 52 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 86 q-6 8 -10 10 M60 86 q6 8 10 10" fill="none" stroke="${c.line}" stroke-width="4.6" stroke-linecap="round"/>
      <path d="M60 86 q-6 8 -10 10 M60 86 q6 8 10 10" fill="none" stroke="${c.body}" stroke-width="2.8" stroke-linecap="round"/>
      <path d="M54 58 Q40 60 34 52" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M54 58 Q40 60 34 52" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M34 52 v-14" stroke="${HORN}" stroke-width="2" stroke-linecap="round"/>
      <path d="M34 34 l1.6 4 l4 1.6 l-4 1.6 l-1.6 4 l-1.6 -4 l-4 -1.6 l4 -1.6 Z" fill="${FIRE2}" stroke="${HORN}" stroke-width="0.8" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M52 26 Q50 18 46 16 M68 26 Q70 18 74 16" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="46" cy="15" r="2" fill="${GEM}"/><circle cx="74" cy="15" r="2" fill="${GEM}"/>
      <circle cx="60" cy="38" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 34 Q48 22 60 22 Q72 22 74 34 Q60 30 46 34 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${smile(60, 42, 3, E)}
      ${eyes(54, 66, 38, 3, E)}
      <circle cx="50" cy="44" r="1.8" fill="${GEM}" opacity=".5"/><circle cx="70" cy="44" r="1.8" fill="${GEM}" opacity=".5"/>
    </g>`;
  },

  // ── Golem — hewn stone giant, angular boulder body, glowing runes & eyes, mossy cracks, blocky fists (front)
  golem: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      <path d="M30 62 L20 66 L18 82 L30 86 L34 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M90 62 L100 66 L102 82 L90 86 L86 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M36 60 L58 56 L84 60 L88 92 L60 100 L32 92 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M46 66 L58 64 L52 80 L62 82 L54 96 M72 66 L80 74 L70 78" fill="none" stroke="${c.line}" stroke-width="1.4" opacity=".55"/>
      <path d="M40 88 L34 100 L46 100 Z M74 88 L70 100 L82 100 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <circle cx="70" cy="72" r="2.6" fill="${RUNE}" opacity=".9"/><circle cx="50" cy="74" r="2.2" fill="${RUNE}" opacity=".8"/>
      <path d="M44 60 q8 4 16 0 q8 4 20 0" fill="none" stroke="${c.shade}" stroke-width="2" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M44 34 L60 30 L76 34 L78 52 L60 58 L42 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M48 46 L54 44 L52 52 M68 44 L72 48 L66 50" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
      <rect x="49" y="40" width="8" height="5" rx="1" fill="${RUNE}" stroke="${c.line}" stroke-width="1.4"/>
      <rect x="63" y="40" width="8" height="5" rx="1" fill="${RUNE}" stroke="${c.line}" stroke-width="1.4"/>
      <circle cx="53" cy="42.5" r="1.4" fill="${INK}"/><circle cx="67" cy="42.5" r="1.4" fill="${INK}"/>
      <path d="M52 52 h16" stroke="${INK}" stroke-width="1.6" stroke-linecap="round"/>
    </g>`;
  },

  // ── Slime — glowing gelatinous blob, glossy dome with inner bubble, wobbly base, happy face, drip & aura
  slime: (c) => {
    const E = eyeInk(c);
    return `
    <g class="breathe">
      <ellipse cx="60" cy="70" rx="36" ry="30" fill="${GLOW}" opacity=".25"/>
      <path d="M26 62 Q26 36 60 36 Q94 36 94 62 Q94 92 88 96 Q82 90 76 96 Q70 90 64 96 Q58 90 52 96 Q46 90 40 96 Q34 90 30 96 Q24 90 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round" opacity=".92"/>
      <path d="M40 46 Q54 36 66 40 Q52 44 46 54 Z" fill="#fff" opacity=".55"/>
      <circle cx="74" cy="66" r="6" fill="#fff" opacity=".22"/>
      <ellipse cx="50" cy="76" rx="9" ry="6" fill="${c.shade}" opacity=".4"/>
    </g>
    <g class="tail-wag">
      <path d="M96 44 Q104 44 104 52 Q104 60 96 60 Q92 56 94 50 Q95 46 96 44 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round" opacity=".9"/>
    </g>
    <g class="head-tilt">
      ${eyes(50, 70, 62, 4, E)}
      ${smile(60, 70, 4.4, E)}
      <circle cx="44" cy="72" r="3" fill="${GEM}" opacity=".35"/><circle cx="76" cy="72" r="3" fill="${GEM}" opacity=".35"/>
    </g>`;
  },

  // ── Cyclops — one-eyed giant, single huge central eye, tiny tuft, snaggletooth grin, stubby arms & legs (front)
  cyclops: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M34 74 Q18 78 16 92", c.body, c.line, 6)}${tube("M86 74 Q102 78 104 92", c.body, c.line, 6)}
    </g>
    <g class="breathe">
      <path d="M40 96 Q36 66 60 64 Q84 66 80 96 Q60 104 40 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="88" rx="13" ry="11" fill="${c.shade}" opacity=".55"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 48}" y="94" width="10" height="14" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M60 22 q-3 -6 2 -8 q4 3 3 8 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <circle cx="60" cy="44" r="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M42 40 q18 -8 36 0" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round" opacity=".6"/>
      <circle cx="60" cy="42" r="12" fill="#fff" stroke="${c.line}" stroke-width="2.2"/>
      <circle cx="60" cy="43" r="6" fill="${MAGIC}"/>
      <circle cx="60" cy="43" r="3.4" fill="${INK}"/>
      <circle cx="57.6" cy="40.6" r="1.6" fill="#fff"/>
      <path d="M48 58 Q60 68 72 58 Q60 62 48 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M55 58 l1.8 4 l1.8 -4 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.6" stroke-linejoin="round"/>
    </g>`;
  },
};

export const ROSTER_MYTHICAL = [
  { n: "Dragon",   e: "🐉", tier: 6, float: true },
  { n: "Phoenix",  e: "🔥", tier: 6, float: true },
  { n: "Griffin",  e: "🦅", tier: 5, float: false },
  { n: "Unicorn",  e: "🦄", tier: 5, float: false },
  { n: "Pegasus",  e: "🐎", tier: 5, float: true },
  { n: "Kraken",   e: "🦑", tier: 6, float: true },
  { n: "Cerberus", e: "🐕", tier: 5, float: false },
  { n: "Hydra",    e: "🐍", tier: 5, float: false },
  { n: "Minotaur", e: "🐂", tier: 5, float: false },
  { n: "Chimera",  e: "🐐", tier: 5, float: false },
  { n: "Basilisk", e: "🦎", tier: 5, float: false },
  { n: "Kitsune",  e: "🦊", tier: 4, float: false },
  { n: "Wyvern",   e: "🐲", tier: 5, float: true },
  { n: "Sphinx",   e: "🦁", tier: 5, float: false },
  { n: "Yeti",     e: "❄️", tier: 4, float: false },
  { n: "Werewolf", e: "🐺", tier: 4, float: false },
  { n: "Fairy",    e: "🧚", tier: 4, float: true },
  { n: "Golem",    e: "🗿", tier: 4, float: false },
  { n: "Slime",    e: "🟢", tier: 4, float: false },
  { n: "Cyclops",  e: "👁️", tier: 4, float: false },
];
