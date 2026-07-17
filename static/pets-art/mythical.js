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
      <path d="M60 58 Q42 36 22 28 Q35 43 35 52 Q24 47 16 49 Q31 58 44 60 Q31 63 24 71 Q46 67 60 62 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M58 58 Q44 44 30 40 Q40 49 43 56 Z" fill="${FIRE2}" opacity=".9"/>`;
    const plume = (x, s) => `<path d="M${x} 80 Q${x - s*5} 102 ${x - s*1.5} 116 Q${x + s*3} 102 ${x + s*5} 82 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/><path d="M${x} 84 Q${x - s*3} 100 ${x} 110" fill="none" stroke="${FIRE2}" stroke-width="1.8"/>`;
    return `
    <g class="tail-wag">${plume(48,1)}${plume(72,-1)}${plume(60,0.3)}</g>
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M60 42 Q78 46 76 68 Q72 88 60 90 Q48 88 44 68 Q42 46 60 42 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M60 56 Q69 60 67 76 Q64 86 60 86 Q56 86 53 76 Q51 60 60 56 Z" fill="${c.shade}"/>
      <path d="M54 62 q6 5 12 0 M56 72 q4 4 8 0" fill="none" stroke="${c.line}" stroke-width="1" opacity=".45"/>
    </g>
    <g class="head-tilt">
      <path d="M51 28 Q46 12 39 8 Q49 18 52 30 Z M60 24 Q60 8 60 4 Q67 14 66 27 Z M69 28 Q74 12 81 8 Q71 18 68 30 Z" fill="${FIRE}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <circle cx="60" cy="40" r="13" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M56 46 L60 53 L64 46 Z" fill="${MANE}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${eyes(54, 66, 38, 3.2, E)}
      <path d="M50 38 q4 -3 8 0 M62 38 q4 -3 8 0" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".5"/>
    </g>`;
  },

  // ── Griffin — eagle head + wings + lion body, hooked beak, feathered chest, taloned fore-claws, tufted lion tail (profile, right)
  griffin: (c) => {
    const E = eyeInk(c);
    return `
    <g class="tail-wag">
      ${tube("M30 80 Q12 84 14 68 Q16 58 26 60", c.body, c.line, 6)}
      ${pom(15, 68, 7, MANE, c.line, 7, 2)}
    </g>
    <g class="breathe">
      <path d="M34 74 Q34 54 60 54 Q84 54 88 72 Q84 88 58 88 Q34 88 34 74 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 74 : 40}" y="84" width="9" height="18" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
      <path d="M40 102 l-3 3 m3 -3 l0 4 m0 -4 l3 3 M44 102 l-3 3 m3 -3 l0 4 m0 -4 l3 3 M74 102 l-3 3 m3 -3 l0 4 m0 -4 l3 3 M78 102 l-3 3 m3 -3 l0 4 m0 -4 l3 3" stroke="${IVORY}" stroke-width="1.4" stroke-linecap="round"/>
    </g>
    <g class="tail-wag">
      <path d="M58 54 Q40 22 14 11 Q25 32 31 47 Q20 40 10 42 Q27 54 40 58 Q25 58 17 65 Q44 71 60 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.3" stroke-linejoin="round"/>
      <path d="M52 54 Q40 34 26 26 M50 57 Q40 46 30 44 M48 61 Q38 55 30 57" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M62 62 Q70 50 82 54 Q76 60 78 70 Q68 64 62 68 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round" opacity=".85"/>
      <path d="M80 44 Q82 32 88 30 Q86 40 88 47 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <circle cx="90" cy="54" r="13" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M100 49 Q114 49 114 60 Q112 67 103 65 Q106 58 101 56 Q97 55 100 49 Z" fill="${MANE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M114 60 Q112 67 103 65 Q108 63 111 59 Z" fill="${c.line}" opacity=".45"/>
      <path d="M82 48 q6 -3 12 0" fill="none" stroke="${c.line}" stroke-width="2" stroke-linecap="round"/>
      ${eye(90, 53, 3, E)}
    </g>`;
  },

  // ── Unicorn — graceful pony, single golden spiral horn, flowing mane + tail, cloven-free hooves, sparkle (profile, right)
  unicorn: (c) => {
    const E = eyeInk(c);
    const spiral = Array.from({ length: 4 }, (_, i) => `<path d="M${94 - i*1.4} ${31 - i*5} l4 1.6" stroke="${c.line}" stroke-width="0.9" opacity=".75"/>`).join("");
    return `
    <g class="tail-wag">
      <path d="M30 66 Q13 65 8 84 Q16 78 22 74 Q12 89 22 95 Q24 78 34 73 Q42 69 34 63 Z" fill="${MANE}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M28 72 C28 58 44 54 62 55 C74 56 80 60 80 68 C80 80 70 82 58 82 C40 82 28 80 28 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <rect x="36" y="78" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><rect x="35.5" y="97" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="62" y="78" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><rect x="61.5" y="97" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="46" y="80" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><rect x="45.5" y="96" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="70" y="80" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><rect x="69.5" y="96" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
    </g>
    <g class="head-tilt">
      ${tube("M72 64 Q80 54 88 46", c.body, c.line, 13)}
      <path d="M83 46 Q80 36 89 33 Q97 33 101 40 L105 49 Q108 53 103 57 Q97 59 91 57 Q82 55 83 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M101 51 Q108 53 105 59 Q100 61 96 57 Z" fill="${c.shade}"/>
      <ellipse cx="102" cy="53" rx="1.3" ry="1" fill="${INK}"/>
      <path d="M85 37 Q81 27 88 23 Q93 31 92 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M91 37 L98 9 L103 38 Z" fill="${HORN}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${spiral}
      <path d="M84 40 Q75 43 78 54 Q70 50 66 58 Q75 56 78 63 Q67 63 63 71 Q77 65 85 59 Z" fill="${MANE}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(94, 47, 2.8, E)}
      <path d="M36 18 l1.5 4 l4 1.5 l-4 1.5 l-1.5 4 l-1.5 -4 l-4 -1.5 l4 -1.5 Z" fill="${GLOW}" stroke="${HORN}" stroke-width="0.8" stroke-linejoin="round"/>
    </g>`;
  },

  // ── Pegasus — winged stallion, broad feathered wings, streaming mane + tail, galloping legs (float, head right)
  pegasus: (c) => {
    const E = eyeInk(c);
    const wing = `<path d="M66 60 Q46 30 16 22 Q28 40 33 52 Q21 47 11 51 Q27 61 42 62 Q27 66 19 76 Q45 76 68 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M60 60 Q44 42 28 36 M58 62 Q44 54 32 54 M56 64 Q44 61 34 65" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".55"/>`;
    return `
    <g class="tail-wag">
      <path d="M30 66 Q13 65 8 84 Q16 78 22 74 Q12 89 22 95 Q24 78 34 73 Q42 69 34 63 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
    </g>
    <g class="breathe">
      <path d="M28 72 C28 58 44 54 62 55 C74 56 80 60 80 68 C80 80 70 82 58 82 C40 82 28 80 28 72 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <rect x="36" y="78" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><rect x="35.5" y="97" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="62" y="78" width="8" height="22" rx="3" fill="${c.shade}" stroke="${c.line}" stroke-width="2"/><rect x="61.5" y="97" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="46" y="80" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><rect x="45.5" y="96" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
      <rect x="70" y="80" width="8" height="20" rx="3" fill="${c.body}" stroke="${c.line}" stroke-width="2.2"/><rect x="69.5" y="96" width="9" height="4.5" rx="1.5" fill="${c.line}"/>
    </g>
    <g class="head-tilt">
      ${tube("M72 64 Q80 54 88 46", c.body, c.line, 13)}
      <path d="M83 46 Q80 36 89 33 Q97 33 101 40 L105 49 Q108 53 103 57 Q97 59 91 57 Q82 55 83 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M101 51 Q108 53 105 59 Q100 61 96 57 Z" fill="${c.shade}"/>
      <ellipse cx="102" cy="53" rx="1.3" ry="1" fill="${INK}"/>
      <path d="M85 37 Q81 27 88 23 Q93 31 92 40 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M84 40 Q75 43 78 54 Q70 50 66 58 Q75 56 78 63 Q67 63 63 71 Q77 65 85 59 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${eye(94, 47, 2.8, E)}
    </g>
    <g class="tail-wag">${wing}</g>`;
  },

  // ── Kraken — colossal squid-beast, domed spiky mantle, glowing eyes, eight thick suckered tentacles, hooked beak (float)
  kraken: (c) => {
    const E = eyeInk(c);
    const arm = (rx, mx, my, ex, ey) => tube(`M${rx} 62 Q${mx} ${my} ${ex} ${ey}`, c.body, c.line, 7);
    const L = [[46,26,88,20,106],[52,40,98,36,110],[56,52,104,54,112],[59,58,106,60,112]];
    const arms = L.map(([rx,mx,my,ex,ey])=>arm(rx,mx,my,ex,ey)).join("") + L.map(([rx,mx,my,ex,ey])=>arm(120-rx,120-mx,my,120-ex,ey)).join("");
    const suckers = L.flatMap(([rx,mx,my])=>[[mx,my],[120-mx,my]]).map(([x,y])=>`<circle cx="${x}" cy="${y}" r="1.7" fill="${c.shade}"/>`).join("");
    return `
    <g class="tail-wag">${arms}${suckers}</g>
    <g class="breathe">
      <path d="M60 14 Q82 24 84 52 Q84 68 60 70 Q36 68 36 52 Q38 24 60 14 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M46 30 Q58 22 66 26 Q54 30 50 40 Z" fill="#fff" opacity=".2"/>
      <path d="M47 59 Q60 75 73 59 Q66 69 60 69 Q54 69 47 59 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M52 61 l2.2 5.5 l2.2 -5.5 Z M60 63 l2.2 5.5 l2.2 -5.5 Z M67 61 l-2.2 5.5 l-2.2 -5.5 Z" fill="${TOOTH}" stroke="${c.line}" stroke-width="0.5" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M37 39 L58 47 M83 39 L62 47" fill="none" stroke="${c.line}" stroke-width="3.4" stroke-linecap="round"/>
      <path d="M40 52 Q50 44 60 51 Q50 56 40 52 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M60 51 Q70 44 80 52 Q70 56 60 51 Z" fill="${GLOW}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M50 49 l4 3 l-4 3 Z" fill="${INK}"/><path d="M70 49 l-4 3 l4 3 Z" fill="${INK}"/>
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
      ${tube("M84 76 Q104 74 102 56 Q101 49 93 52", c.body, c.line, 6)}
      <path d="M93 52 l7 -3 l-2 7 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${neck(48, 68, 22, 34)} ${serp(22, 34)}
    </g>
    <g class="breathe">
      <path d="M30 80 Q28 58 56 58 Q86 58 92 74 Q94 84 84 84 Q88 90 80 90 Q72 92 68 86 Q60 92 50 90 Q40 92 34 86 Q28 88 30 80 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 84 Q58 92 76 84 Q58 89 40 84 Z" fill="${c.shade}"/>
      ${[[38,74],[50,76],[62,75],[74,73]].map(([x,y])=>`<path d="M${x} ${y} q4 3 8 0" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>`).join("")}
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
      <ellipse cx="60" cy="58" rx="15" ry="11" fill="${c.shade}"/>
      <ellipse cx="54" cy="56" rx="2" ry="2.8" fill="${INK}"/><ellipse cx="66" cy="56" rx="2" ry="2.8" fill="${INK}"/>
      <path d="M53 63 q7 3 14 0" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M56 59 Q60 65 64 59" fill="none" stroke="${HORN}" stroke-width="2"/>
      <path d="M44 39 q7 -4 13 -1 M63 38 q7 -3 13 1" fill="none" stroke="${c.line}" stroke-width="2.2" stroke-linecap="round"/>
      ${eyes(52, 68, 46, 3, E)}
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
      ${tube("M52 62 Q47 48 43 40", c.shade, c.line, 6)}
      <path d="M43 42 Q35 34 39 26 Q45 30 49 30 Q55 26 57 34 Q57 44 49 46 Q42 46 43 42 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M41 30 Q35 22 39 16 M51 30 Q57 22 55 15" fill="none" stroke="${IVORY}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M47 45 q0 6 -3 9" fill="none" stroke="${c.shade}" stroke-width="2.4" stroke-linecap="round"/>
      <ellipse cx="46" cy="40" rx="1.4" ry="1.2" fill="${INK}"/>
      ${eye(51, 38, 2, E)}
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
    <g class="breathe">
      ${tube("M40 52 Q28 64 44 74 Q64 84 80 74 Q92 64 80 54 Q72 48 62 54", c.body, c.line, 12)}
      <path d="M62 54 l-9 -3 l4 9 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${[42,54,66].map((x,i)=>`<path d="M${x} ${74-(i%2)*2} q4 3 8 0" fill="none" stroke="${c.line}" stroke-width="1" opacity=".5"/>`).join("")}
    </g>
    <g class="head-tilt">
      ${[0,1,2].map(i=>`<path d="M${30+i*7} 32 L${33+i*7} 20 L${37+i*7} 32 Z" fill="#d94141" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>`).join("")}
      <path d="M24 46 Q24 30 42 30 Q60 30 60 46 Q60 60 42 60 Q24 58 24 46 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M24 48 Q12 48 6 44 M24 52 Q12 54 6 58" fill="none" stroke="#d94141" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M32 42 q6 -3 12 0" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <circle cx="44" cy="46" r="4.4" fill="${GLOW}" stroke="${c.line}" stroke-width="1.6"/>
      <path d="M44 42 v8" stroke="${INK}" stroke-width="1.9"/>
      <ellipse cx="44" cy="46" rx="1.7" ry="4.4" fill="${INK}"/>
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
      ${tube("M50 80 q-3 10 1 18", c.body, c.line, 6)}${tube("M66 80 q3 10 -1 18", c.body, c.line, 6)}
      <path d="M51 97 l-4 3 m4 -3 l0 5 m0 -5 l4 3 M65 97 l-4 3 m4 -3 l0 5 m0 -5 l4 3" stroke="${IVORY}" stroke-width="1.5" stroke-linecap="round"/>
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
      <path d="M22 86 Q22 72 52 70 Q78 70 92 80 Q96 84 92 88 Q60 92 40 90 Q22 92 22 86 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M26 84 Q24 75 34 75 Q42 77 42 88 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M62 82 L97 82 Q100 86 97 90 L62 90 Q59 86 62 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M73 83 v6 M82 83 v6 M91 83 v6" stroke="${c.line}" stroke-width="1.2"/>
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
      ${["", "s"].map((_, i) => `<path d="M${i ? 74 : 46} 74 Q${i ? 96 : 14} 80 ${i ? 86 : 22} 94" fill="none" stroke="${c.line}" stroke-width="8" stroke-linecap="round"/><path d="M${i ? 74 : 46} 74 Q${i ? 96 : 14} 80 ${i ? 86 : 22} 94" fill="none" stroke="${c.body}" stroke-width="5" stroke-linecap="round"/>`).join("")}
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
      <path d="M58 62 Q34 44 24 56 Q30 64 40 64 Q28 72 34 84 Q48 78 58 66 Z" fill="${MAGIC}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round" opacity=".85"/>
      <circle cx="36" cy="60" r="2.6" fill="${GLOW}" opacity=".8"/>`;
    return `
    <g class="tail-wag">${wing}${mirror(wing)}</g>
    <g class="breathe">
      <path d="M60 58 L52 82 Q60 88 68 82 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M55 82 l-3 12 M65 82 l3 12" fill="none" stroke="${c.line}" stroke-width="4.4" stroke-linecap="round"/>
      <path d="M55 82 l-3 12 M65 82 l3 12" fill="none" stroke="${c.body}" stroke-width="2.6" stroke-linecap="round"/>
      <path d="M54 64 Q44 66 40 58" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M54 64 Q44 66 40 58" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M66 64 Q78 62 82 52" fill="none" stroke="${c.line}" stroke-width="4" stroke-linecap="round"/>
      <path d="M66 64 Q78 62 82 52" fill="none" stroke="${c.body}" stroke-width="2.4" stroke-linecap="round"/>
      <path d="M82 52 v-12" stroke="${HORN}" stroke-width="2" stroke-linecap="round"/>
      <path d="M82 34 l1.6 4 l4 1.6 l-4 1.6 l-1.6 4 l-1.6 -4 l-4 -1.6 l4 -1.6 Z" fill="${FIRE2}" stroke="${HORN}" stroke-width="0.8" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <circle cx="60" cy="42" r="14" fill="${c.body}" stroke="${c.line}" stroke-width="2.4"/>
      <path d="M46 40 Q46 24 60 24 Q74 24 74 40 Q68 32 60 33 Q52 32 46 40 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M47 42 Q44 52 48 58 M73 42 Q76 52 72 58" fill="none" stroke="${c.shade}" stroke-width="3" stroke-linecap="round"/>
      ${smile(60, 46, 3, E)}
      ${eyes(54, 66, 42, 3, E)}
      <circle cx="50" cy="48" r="2" fill="${GEM}" opacity=".45"/><circle cx="70" cy="48" r="2" fill="${GEM}" opacity=".45"/>
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
      ${tube("M46 72 Q28 76 22 90", c.body, c.line, 7)}<circle cx="22" cy="90" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
      ${tube("M74 72 Q92 76 98 90", c.body, c.line, 7)}<circle cx="98" cy="90" r="5" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>
    </g>
    <g class="breathe">
      <path d="M40 96 Q36 66 60 64 Q84 66 80 96 Q60 104 40 96 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <ellipse cx="60" cy="88" rx="13" ry="11" fill="${c.shade}" opacity=".55"/>
      ${["", "s"].map((_, i) => `<rect x="${i ? 62 : 48}" y="94" width="10" height="14" rx="3.4" fill="${c.body}" stroke="${c.line}" stroke-width="2"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M60 22 q-3 -6 2 -8 q4 3 3 8 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <circle cx="60" cy="44" r="22" fill="${c.body}" stroke="${c.line}" stroke-width="2.6"/>
      <path d="M46 29 L60 34 L74 29" fill="none" stroke="${c.line}" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="60" cy="44" r="11" fill="#fff" stroke="${c.line}" stroke-width="2.2"/>
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
