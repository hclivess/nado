// pets-art/marinemammals.js — BESPOKE hand-drawn SVG art for the MARINE MAMMALS batch (NADO Pets).
// Each entry: slug -> (c) => "<svg inner markup>" for <svg viewBox="0 0 120 120">. All aquatic => float:true,
// bodies oriented HORIZONTALLY with the head to the RIGHT (like sea.js swimmers). No floor shadow (they float).
// Coat comes from `c`: c.body (main fill), c.shade (accent/underside), c.line (outline). Colours are applied at
// runtime so nothing hardcodes a species colour; tusks/callosities use #fff sparingly, nose/eyes use INK.
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, pom, mirror, eyeInk, smile } from "../pets-draw.js";

// ── shared body-plan helpers (kept generic; every animal below stays bespoke) ─────────────
// two-lobed horizontal tail FLUKES rooted at the body's left tip (X) — cetaceans + dugong
const fluke = (c, X, Y = 63, w = 2.6) =>
  `<path d="M${X} ${Y} Q${X - 12} ${Y - 11} ${X - 17} ${Y - 15} Q${X - 10} ${Y} ${X - 17} ${Y + 15} Q${X - 12} ${Y + 11} ${X} ${Y} Z" fill="${c.body}" stroke="${c.line}" stroke-width="${w}" stroke-linejoin="round"/>`;
// pinniped HIND-flipper fan trailing to the left (two flippers pressed together)
const hind = (c, X, Y = 66) =>
  `<path d="M${X} ${Y - 6} Q${X - 15} ${Y - 13} ${X - 20} ${Y - 5} Q${X - 12} ${Y - 2} ${X - 8} ${Y} Q${X - 12} ${Y + 2} ${X - 20} ${Y + 9} Q${X - 15} ${Y + 13} ${X} ${Y + 6} Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`;
// a FORE-flipper paddle hanging down, rooted INSIDE the body at (X,Y)
const foreflip = (c, X, Y, fill) =>
  `<path d="M${X} ${Y} Q${X - 12} ${Y + 17} ${X - 3} ${Y + 22} Q${X + 8} ${Y + 17} ${X + 9} ${Y - 3} Z" fill="${fill || c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>`;

export const ART_MARINEMAMMALS = {
  // ── Sea Lion — long dog-like snout, small external EAR flap, big fore-flipper (tier 2)
  sealion: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 24, 66)}</g>
    <g class="breathe">
      <path d="M20 64 Q26 46 52 46 Q78 46 90 58 Q94 64 90 70 Q82 82 52 82 Q28 80 20 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M36 74 Q60 84 90 68 Q60 82 36 74 Z" fill="${B}"/>
      ${foreflip(c, 64, 74)}
    </g>
    <g class="head-tilt">
      <path d="M80 50 Q92 44 104 50 Q112 54 108 60 Q100 65 92 64 Q82 62 80 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M82 50 Q79 41 86 43 Q89 48 87 51 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <ellipse cx="106" cy="54" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M100 58 l8 1 M100 61 l7 0" stroke="${c.line}" stroke-width="0.9" opacity=".7"/>
      ${eye(94, 54, 3.2, E)}
    </g>`; },

  // ── Fur Seal — pointier snout, thick fuzzy fur RUFF at the shoulders, small ear (tier 2)
  furseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 24, 66)}</g>
    <g class="breathe">
      <path d="M20 64 Q26 46 50 46 Q72 46 82 54 Q86 60 82 66 Q76 82 50 82 Q28 80 20 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M34 74 Q56 84 82 66 Q56 82 34 74 Z" fill="${B}"/>
      ${foreflip(c, 58, 74)}
      ${pom(74, 58, 12, c.body, c.line, 12, 2.4)}
    </g>
    <g class="head-tilt">
      <path d="M84 52 Q97 47 109 55 Q114 59 109 63 Q100 67 92 65 Q84 60 84 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M85 52 Q82 44 89 45 Q92 50 90 53 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <ellipse cx="109" cy="57" rx="2.6" ry="2.1" fill="${INK}"/>
      <path d="M103 61 l7 1 M103 63 l6 0" stroke="${c.line}" stroke-width="0.9" opacity=".7"/>
      ${eye(96, 56, 3, E)}
    </g>`; },

  // ── Manatee — rotund blimp body, big rounded PADDLE tail, square bristly muzzle, tiny eye (tier 2)
  manatee: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag"><path d="M28 50 Q3 52 3 64 Q3 78 28 80 Q17 64 28 50 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M12 58 Q8 64 12 72" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".5"/></g>
    <g class="breathe">
      <path d="M24 64 Q24 42 60 42 Q92 42 98 60 Q100 66 96 70 Q90 86 58 86 Q24 84 24 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 76 Q64 88 94 70 Q64 84 40 76 Z" fill="${B}"/>
      ${["M42 56 q22 -6 44 0", "M40 66 q24 -4 48 0"].map(d => `<path d="${d}" stroke="${c.shade}" stroke-width="1.4" fill="none" opacity=".45"/>`).join("")}
      ${foreflip(c, 58, 76)}
      <path d="M51 96 l0 4 M55 97 l0 4 M59 96 l0 4" stroke="${c.line}" stroke-width="1.1" opacity=".6"/>
    </g>
    <g class="head-tilt">
      <path d="M88 54 Q100 52 100 62 Q100 72 90 72 Q86 64 88 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round" opacity=".85"/>
      ${[[93, 66], [97, 66], [93, 69], [97, 69]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="0.9" fill="${INK}" opacity=".7"/>`).join("")}
      ${eye(86, 58, 2.4, E)}
    </g>`; },

  // ── Dugong — manatee cousin with a notched FLUKED tail + downturned broad snout (tier 2)
  dugong: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 26, 64, 2.6)}</g>
    <g class="breathe">
      <path d="M24 64 Q26 44 60 44 Q92 44 98 60 Q100 66 96 70 Q90 84 58 84 Q24 82 24 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 74 Q64 86 94 70 Q64 82 40 74 Z" fill="${B}"/>
      ${foreflip(c, 58, 74)}
    </g>
    <g class="head-tilt">
      <path d="M86 52 Q100 50 102 60 Q102 72 90 74 Q84 66 84 58 Q84 54 86 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M91 68 Q100 70 100 75 Q94 75 89 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${[[94, 71], [98, 72]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="0.9" fill="${INK}" opacity=".7"/>`).join("")}
      ${eye(88, 58, 2.4, E)}
    </g>`; },

  // ── Harbor Porpoise — small, rounded blunt head (no beak), tiny triangular dorsal (tier 2)
  harborporpoise: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 26, 63, 2.4)}</g>
    <g class="breathe">
      <path d="M24 63 Q30 50 54 49 Q80 48 96 60 Q90 74 62 76 Q34 76 24 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M38 70 Q62 80 92 66 Q62 78 38 70 Z" fill="${B}"/>
      <path d="M49 50 L54 43 L60 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${foreflip(c, 58, 72)}
    </g>
    <g class="head-tilt">
      <path d="M88 62 q6 3 10 -1" stroke="${c.line}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <ellipse cx="94" cy="60" rx="1.6" ry="1.3" fill="${INK}"/>
      ${eye(86, 58, 2.6, E)}
    </g>`; },

  // ── Pilot Whale — very BULBOUS round melon head, backswept broad dorsal, long low body (tier 3)
  pilotwhale: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 22, 63, 2.6)}</g>
    <g class="breathe">
      <path d="M20 63 Q26 50 48 48 Q78 44 98 58 Q104 63 98 68 Q80 80 54 78 Q30 76 20 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 70 Q66 80 96 64 Q66 76 40 70 Z" fill="${B}"/>
      <path d="M40 48 Q46 34 60 40 Q54 46 52 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${foreflip(c, 54, 72)}
      <path d="M90 50 Q99 50 101 57 Q94 57 88 56 Z" fill="${deepen(c.body, 0.12)}"/>
    </g>
    <g class="head-tilt">
      <path d="M92 62 q6 3 10 -2" stroke="${c.line}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eye(90, 58, 2.6, E)}
    </g>`; },

  // ── Sperm Whale — enormous SQUARE blocky head, underslung narrow jaw, wrinkled skin, angled spout (tier 4)
  spermwhale: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 18, 63, 2.6)}</g>
    <g class="breathe">
      <path d="M16 63 Q20 55 30 53 Q40 51 58 50 L70 46 Q104 44 106 54 L108 74 Q104 82 72 80 L58 76 Q40 75 30 73 Q20 71 16 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M60 76 Q84 82 106 74 Q84 79 60 76 Z" fill="${B}"/>
      <path d="M70 75 L108 75 L108 78 Q100 80 84 80 L72 79 Z" fill="${c.shade}" opacity=".6"/>
      ${[66, 74, 82, 90, 98].map(x => `<path d="M${x} 50 q-1 12 0 24" stroke="${c.line}" stroke-width="1" fill="none" opacity=".33"/>`).join("")}
      <path d="M40 50 Q44 42 52 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${foreflip(c, 50, 72)}
    </g>
    <g class="head-tilt">
      <path d="M80 46 q-4 -8 -7 -12 M80 46 q0 -9 1 -14 M80 46 q4 -8 8 -11" stroke="#bcd6ea" stroke-width="1.8" fill="none" stroke-linecap="round" opacity=".8"/>
      ${eye(88, 70, 2.4, E)}
    </g>`; },

  // ── Humpback Whale — VERY long knobby white pectoral flipper, tubercle bumps on head, broad flukes (tier 4)
  humpbackwhale: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 20, 63, 2.6)}</g>
    <g class="tail-wag"><path d="M64 66 Q70 88 84 96 Q92 98 92 92 Q84 88 80 76 Q76 68 72 64 Z" fill="${tint(c.body, 0.5)}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M70 74 q4 2 8 0 M76 82 q4 2 8 0" stroke="${c.line}" stroke-width="1.2" fill="none" opacity=".5"/></g>
    <g class="breathe">
      <path d="M18 63 Q24 50 50 48 Q82 46 100 58 Q106 63 100 68 Q84 78 54 78 Q28 76 18 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 70 Q68 80 98 64 Q68 76 40 70 Z" fill="${B}"/>
      <path d="M46 48 Q50 38 62 44 Q56 48 54 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${[86, 90, 94, 98].map(x => `<circle cx="${x}" cy="${52 + (x - 86) / 3}" r="1.2" fill="${c.shade}"/>`).join("")}
      ${foreflip(c, 52, 72)}
    </g>
    <g class="head-tilt">
      <path d="M92 60 q6 3 10 -2" stroke="${c.line}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      ${eye(90, 57, 2.6, E)}
    </g>`; },

  // ── Right Whale — strongly ARCHED bowed mouth, white CALLOSITIES on the head, no dorsal fin (tier 3)
  rightwhale: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 20, 63, 2.6)}</g>
    <g class="breathe">
      <path d="M18 63 Q24 48 52 47 Q78 46 96 54 Q104 58 104 64 Q102 72 92 72 Q88 80 58 80 Q28 78 18 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 72 Q66 82 92 72 Q66 79 40 72 Z" fill="${B}"/>
      <path d="M86 60 Q94 62 102 60 Q96 73 84 72 Q80 66 86 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      ${foreflip(c, 54, 72)}
    </g>
    <g class="head-tilt">
      <path d="M82 66 Q92 74 104 64" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
      ${[[90, 56], [96, 58], [100, 55]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.8" fill="#fff" stroke="${c.line}" stroke-width="0.7"/>`).join("")}
      ${eye(84, 62, 2.4, E)}
    </g>`; },

  // ── Minke Whale — sleek slender rorqual, sharply pointed head, falcate dorsal, white flipper band (tier 3)
  minkewhale: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 20, 63, 2.4)}</g>
    <g class="breathe">
      <path d="M18 63 Q26 52 52 50 Q84 47 106 58 Q100 70 66 74 Q34 74 18 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M38 68 Q68 78 100 62 Q68 74 38 68 Z" fill="${B}"/>
      <path d="M56 51 Q60 40 70 47 Q64 51 62 53 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M50 66 Q60 84 72 72 Q60 70 54 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M52 68 Q58 74 66 70" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round" opacity=".9"/>
    </g>
    <g class="head-tilt">
      <path d="M96 60 q5 3 8 -1" stroke="${c.line}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      ${eye(95, 58, 2.4, E)}
    </g>`; },

  // ── Bowhead Whale — huge strongly arched BOW head + big curved mouth, pale chin, no dorsal fin (tier 3)
  bowheadwhale: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 18, 63, 2.6)}</g>
    <g class="breathe">
      <path d="M16 63 Q22 50 48 49 Q70 48 84 52 Q98 44 106 56 Q110 64 104 72 Q94 80 84 76 Q70 80 54 80 Q26 78 16 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M38 74 Q60 82 82 74 Q60 79 38 74 Z" fill="${B}"/>
      <path d="M84 70 Q94 78 104 70 Q96 60 90 62 Q86 65 84 70 Z" fill="${B}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${foreflip(c, 54, 74)}
      <path d="M90 50 Q97 48 99 55 Q93 55 89 55 Z" fill="${deepen(c.body, 0.12)}"/>
    </g>
    <g class="head-tilt">
      <path d="M82 66 Q92 74 104 68" stroke="${c.line}" stroke-width="2" fill="none" stroke-linecap="round"/>
      ${eye(82, 60, 2.4, E)}
    </g>`; },

  // ── Vaquita — tiny porpoise with dark EYE RINGS + dark lip patch, small triangular dorsal (tier 3)
  vaquita: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${fluke(c, 30, 63, 2.4)}</g>
    <g class="breathe">
      <path d="M28 63 Q33 50 54 49 Q80 48 96 60 Q90 74 62 76 Q36 76 28 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M40 70 Q62 80 92 66 Q62 78 40 70 Z" fill="${B}"/>
      <path d="M47 50 Q51 34 57 38 Q57 44 60 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      ${foreflip(c, 58, 72)}
    </g>
    <g class="head-tilt">
      <ellipse cx="90" cy="58" rx="6" ry="5" fill="${deepen(c.body, 0.28)}"/>
      <path d="M90 66 Q96 69 101 62" stroke="${deepen(c.body, 0.28)}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
      ${eye(90, 58, 2.4, E)}
    </g>`; },

  // ── Leopard Seal — long sinuous body, BIG reptilian head + wide gape, spotted coat (tier 3)
  leopardseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 22, 64)}</g>
    <g class="breathe">
      <path d="M18 64 Q24 50 48 50 Q70 50 82 56 Q88 60 86 66 Q80 80 50 80 Q26 78 18 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M36 72 Q58 82 84 66 Q58 80 36 72 Z" fill="${B}"/>
      ${[[36, 58], [48, 56], [60, 60], [44, 68], [56, 70], [68, 64]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.8" fill="${c.shade}" opacity=".8"/>`).join("")}
      ${foreflip(c, 60, 72)}
    </g>
    <g class="head-tilt">
      <path d="M76 52 Q94 46 110 54 Q116 60 110 66 Q100 72 88 70 Q78 66 76 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M90 66 Q100 72 113 62" stroke="${c.line}" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <ellipse cx="111" cy="57" rx="2.6" ry="2.1" fill="${INK}"/>
      <path d="M104 61 l7 1 M104 63 l6 0" stroke="${c.line}" stroke-width="0.9" opacity=".7"/>
      ${[[82, 60], [88, 64], [94, 62]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.4" fill="${c.shade}" opacity=".7"/>`).join("")}
      ${eye(90, 56, 3, E)}
    </g>`; },

  // ── Elephant Seal — massive bulk, big overhanging TRUNK/proboscis nose, wrinkled neck (tier 3)
  elephantseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 22, 66)}</g>
    <g class="breathe">
      <path d="M18 66 Q24 46 54 46 Q84 46 94 58 Q98 64 94 70 Q86 84 54 84 Q24 82 18 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M38 76 Q62 86 92 70 Q62 82 38 76 Z" fill="${B}"/>
      ${[70, 76, 82].map(x => `<path d="M${x} 50 q-3 6 0 12" stroke="${c.line}" stroke-width="1" fill="none" opacity=".35"/>`).join("")}
      ${foreflip(c, 58, 76)}
    </g>
    <g class="head-tilt">
      <path d="M82 52 Q98 48 106 56 Q110 62 106 68 Q112 70 110 79 Q104 85 96 78 Q92 74 92 68 Q84 66 82 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M100 74 Q106 76 104 81 Q99 81 97 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      ${eye(90, 58, 2.6, E)}
    </g>`; },

  // ── Weddell Seal — plump body, small ROUND head with an upturned smile, gentle eyes (tier 2)
  weddellseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 24, 66)}</g>
    <g class="breathe">
      <path d="M22 66 Q28 48 56 48 Q84 48 92 60 Q96 66 92 72 Q84 84 54 84 Q28 82 22 66 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M38 76 Q62 86 90 70 Q62 82 38 76 Z" fill="${B}"/>
      ${[[38, 58], [50, 62], [62, 58], [46, 70]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.5" fill="${c.shade}" opacity=".55"/>`).join("")}
      ${foreflip(c, 60, 74)}
    </g>
    <g class="head-tilt">
      <ellipse cx="94" cy="60" rx="14" ry="13" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <ellipse cx="104" cy="60" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M97 65 Q101 70 106 64" stroke="${c.line}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <path d="M99 61 l6 1 M99 63 l5 0" stroke="${c.line}" stroke-width="0.9" opacity=".7"/>
      ${ceye(89, 58, 3.6)}
    </g>`; },

  // ── Ribbon Seal — dark coat wrapped by bold pale RIBBON bands (neck + hip loops) (tier 2)
  ribbonseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 24, 66)}</g>
    <g class="breathe">
      <path d="M20 65 Q26 48 54 48 Q82 48 92 58 Q96 64 92 70 Q84 82 54 82 Q26 80 20 65 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M35 53 Q41 65 35 77 Q28 72 28 65 Q28 58 35 53 Z" fill="${belly(c)}"/>
      <path d="M64 50 Q72 65 64 80 Q57 65 64 50 Z" fill="${belly(c)}"/>
      <path d="M42 76 Q60 84 86 70 Q60 80 42 76 Z" fill="${B}" opacity=".5"/>
      ${foreflip(c, 58, 74)}
    </g>
    <g class="head-tilt">
      <path d="M78 52 Q96 48 102 58 Q104 64 98 70 Q88 74 82 68 Q78 60 78 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="100" cy="60" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M94 64 l7 1 M94 66 l6 0" stroke="${c.line}" stroke-width="0.9" opacity=".7"/>
      ${eye(88, 57, 2.8, E)}
    </g>`; },

  // ── Hooded Seal — inflatable bulbous NOSE HOOD bump over the snout (tier 3)
  hoodedseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 24, 66)}</g>
    <g class="breathe">
      <path d="M20 65 Q26 48 54 48 Q82 48 92 58 Q96 64 92 70 Q84 82 54 82 Q26 80 20 65 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M38 74 Q60 84 90 68 Q60 80 38 74 Z" fill="${B}"/>
      ${[[40, 58], [52, 62], [64, 58]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.5" fill="${c.shade}" opacity=".55"/>`).join("")}
      ${foreflip(c, 58, 74)}
    </g>
    <g class="head-tilt">
      <path d="M78 55 Q92 49 104 55 Q110 59 106 65 Q98 71 88 69 Q80 65 78 55 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M83 53 Q88 39 100 45 Q105 51 101 56 Q92 55 84 55 Z" fill="${deepen(c.body, 0.14)}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <ellipse cx="104" cy="59" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M98 63 l7 1 M98 65 l6 0" stroke="${c.line}" stroke-width="0.9" opacity=".7"/>
      ${eye(88, 59, 2.8, E)}
    </g>`; },

  // ── Bearded Seal — broad muzzle with a mass of long curly WHISKERS (tier 2)
  beardedseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 24, 66)}</g>
    <g class="breathe">
      <path d="M20 65 Q26 48 54 48 Q82 48 92 58 Q96 64 92 70 Q84 82 54 82 Q26 80 20 65 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M38 74 Q60 84 90 68 Q60 80 38 74 Z" fill="${B}"/>
      ${foreflip(c, 58, 74)}
    </g>
    <g class="head-tilt">
      <path d="M78 52 Q94 48 102 58 Q104 64 98 70 Q88 74 82 68 Q78 60 78 52 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <ellipse cx="98" cy="63" rx="5" ry="4" fill="${belly(c)}"/>
      <ellipse cx="100" cy="60" rx="2.4" ry="2" fill="${INK}"/>
      ${[0, 1, 2, 3, 4].map(i => `<path d="M97 ${61 + i * 1.5} q11 ${i - 2} 17 ${i - 1}" stroke="${c.line}" stroke-width="0.9" fill="none" opacity=".85"/>`).join("")}
      ${[0, 1, 2].map(i => `<path d="M97 ${63 + i * 1.6} q10 ${3 - i} 15 ${5 - i}" stroke="${c.line}" stroke-width="0.9" fill="none" opacity=".7"/>`).join("")}
      ${eye(88, 56, 2.8, E)}
    </g>`; },

  // ── Baikal Seal — the roundest, most compact seal; short snout + huge cute eye (tier 2)
  baikalseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 28, 66)}</g>
    <g class="breathe">
      <ellipse cx="56" cy="66" rx="34" ry="26" fill="${c.body}" stroke="${c.line}" stroke-width="3.2"/>
      <path d="M36 76 Q58 88 86 72 Q58 84 36 76 Z" fill="${B}"/>
      ${foreflip(c, 60, 76)}
    </g>
    <g class="head-tilt">
      <circle cx="90" cy="60" r="15" fill="${c.body}" stroke="${c.line}" stroke-width="3"/>
      <ellipse cx="103" cy="61" rx="2.8" ry="2.2" fill="${INK}"/>
      <path d="M96 65 Q100 69 104 64" stroke="${c.line}" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      <path d="M96 61 l7 1 M96 63 l6 0" stroke="${c.line}" stroke-width="0.9" opacity=".7"/>
      ${ceye(85, 58, 4)}
    </g>`; },

  // ── Crabeater Seal — slender pale body with a long slim snout (tier 2)
  crabeaterseal: (c) => { const E = eyeInk(c), B = belly(c); return `
    <g class="tail-wag">${hind(c, 22, 64)}</g>
    <g class="breathe">
      <path d="M18 64 Q24 52 50 51 Q76 50 86 58 Q90 62 86 68 Q78 78 50 78 Q26 76 18 64 Z" fill="${c.body}" stroke="${c.line}" stroke-width="3" stroke-linejoin="round"/>
      <path d="M36 70 Q58 80 84 66 Q58 78 36 70 Z" fill="${B}"/>
      ${foreflip(c, 58, 70)}
    </g>
    <g class="head-tilt">
      <path d="M78 54 Q96 50 112 56 Q116 60 112 64 Q100 70 88 68 Q80 62 78 54 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.8" stroke-linejoin="round"/>
      <ellipse cx="112" cy="59" rx="2.4" ry="2" fill="${INK}"/>
      <path d="M105 62 l7 1 M105 64 l6 0" stroke="${c.line}" stroke-width="0.9" opacity=".7"/>
      ${eye(91, 57, 2.8, E)}
    </g>`; },
};

// roster metadata — every `n` slugifies to a matching ART_MARINEMAMMALS key (1:1, no orphans)
export const ROSTER_MARINEMAMMALS = [
  { n: "Sea Lion",         e: "🦭", tier: 2, float: true },
  { n: "Fur Seal",         e: "🦭", tier: 2, float: true },
  { n: "Manatee",          e: "🦭", tier: 2, float: true },
  { n: "Dugong",           e: "🦭", tier: 2, float: true },
  { n: "Harbor Porpoise",  e: "🐋", tier: 2, float: true },
  { n: "Pilot Whale",      e: "🐋", tier: 3, float: true },
  { n: "Sperm Whale",      e: "🐋", tier: 4, float: true },
  { n: "Humpback Whale",   e: "🐋", tier: 4, float: true },
  { n: "Right Whale",      e: "🐋", tier: 3, float: true },
  { n: "Minke Whale",      e: "🐋", tier: 3, float: true },
  { n: "Bowhead Whale",    e: "🐳", tier: 3, float: true },
  { n: "Vaquita",          e: "🐋", tier: 3, float: true },
  { n: "Leopard Seal",     e: "🦭", tier: 3, float: true },
  { n: "Elephant Seal",    e: "🦭", tier: 3, float: true },
  { n: "Weddell Seal",     e: "🦭", tier: 2, float: true },
  { n: "Ribbon Seal",      e: "🦭", tier: 2, float: true },
  { n: "Hooded Seal",      e: "🦭", tier: 3, float: true },
  { n: "Bearded Seal",     e: "🦭", tier: 2, float: true },
  { n: "Baikal Seal",      e: "🦭", tier: 2, float: true },
  { n: "Crabeater Seal",   e: "🦭", tier: 2, float: true },
];
