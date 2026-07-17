// pets-art/freshwaterfish.js — BESPOKE hand-drawn SVG art for the FRESHWATER FISH batch of NADO Pets.
// Each entry: slug -> (c) => "<svg inner markup string>" for <svg viewBox="0 0 120 120">.
// Coat: c.body (main fill), c.shade (underside/accent), c.line (outline). All aquatic => float:true,
// bodies oriented HORIZONTALLY, head to the RIGHT (like sea.js / reef.js). Float fish omit floorShadow.
// Helpers from ../pets-draw.js. Tooth/barbel accents below; nose/eyes = INK/eyeInk.
import { INK, ceye, eye, eyes, belly, tint, deepen, tube, mirror, eyeInk, smile } from "../pets-draw.js";

const TOOTH = "#fff"; // teeth / fangs

export const ART_FRESHWATERFISH = {
  // Largemouth Bass — deep robust body, huge gaping mouth past the eye, blotchy midline, notched dorsal
  largemouthbass: (c) => { const E = eyeInk(c); const D = deepen(c.body, .34); return `
    <g class="tail-wag"><path d="M26 62 Q12 48 6 50 Q14 62 6 74 Q12 76 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q34 40 62 42 Q86 44 96 60 Q86 76 62 80 Q34 82 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 74 Q64 84 92 66 Q64 78 40 74 Z" fill="${c.shade}"/>
      <path d="M44 44 Q52 30 58 44 Q64 34 78 46 Q60 48 50 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M52 80 Q58 90 66 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      <path d="M34 60 Q58 57 82 60" fill="none" stroke="${D}" stroke-width="3" opacity=".55" stroke-linecap="round"/>
      ${[40, 52, 64, 76].map((x) => `<ellipse cx="${x}" cy="60" rx="3" ry="2.4" fill="${D}" opacity=".45"/>`).join("")}
    </g>
    <g class="head-tilt">
      <path d="M80 64 Q92 71 101 63 Q94 69 86 69 Q82 68 80 64 Z" fill="${INK}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M82 50 q-2 8 0 15" fill="none" stroke="${c.line}" stroke-width="1.3" opacity=".5"/>
      ${eye(86, 55, 3.2, E)}
    </g>`; },

  // Rainbow Trout — streamlined torpedo, dark speckles all over, pale lateral stripe, little adipose fin
  rainbowtrout: (c) => { const E = eyeInk(c); const P = tint(c.body, .55); const D = deepen(c.body, .3);
    const spots = [[36, 52], [44, 50], [52, 52], [60, 50], [68, 52], [46, 56], [58, 56], [70, 56], [40, 58], [64, 58]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.3" fill="${D}" opacity=".8"/>`).join("");
    return `
    <g class="tail-wag"><path d="M24 62 Q10 50 5 52 Q13 62 5 72 Q10 74 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 62 Q40 46 70 48 Q92 50 100 62 Q92 74 70 78 Q40 80 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M28 62 Q60 56 96 62 Q60 68 28 62 Z" fill="${P}"/>
      <path d="M38 72 Q64 80 94 66 Q64 76 38 72 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M50 48 Q58 34 70 48 Q60 50 54 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M34 50 q4 -5 7 -1 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M54 78 Q60 88 68 79 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${spots}
    </g>
    <g class="head-tilt">
      <path d="M90 64 q6 2 9 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M84 52 q-2 8 0 15" fill="none" stroke="${c.line}" stroke-width="1.2" opacity=".5"/>
      ${eye(87, 57, 3, E)}
    </g>`; },

  // Salmon — streamlined, spots on the upper back, the signature HOOKED jaw (kype), forked tail
  salmon: (c) => { const E = eyeInk(c); const D = deepen(c.body, .32);
    const spots = [[38, 52], [50, 50], [62, 51], [46, 56], [58, 55], [70, 54], [34, 58]].map(([x, y]) => `<ellipse cx="${x}" cy="${y}" rx="1.8" ry="1.4" fill="${D}" opacity=".75"/>`).join("");
    return `
    <g class="tail-wag"><path d="M24 62 Q10 50 5 52 Q13 62 5 72 Q10 74 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 62 Q40 46 66 48 Q84 50 90 58 Q84 70 66 76 Q40 78 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M38 72 Q62 80 88 66 Q62 76 38 72 Z" fill="${c.shade}" opacity=".55"/>
      <path d="M48 48 Q56 36 66 48 Q58 50 52 50 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M34 50 q4 -5 7 -1 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M50 76 Q56 86 64 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${spots}
    </g>
    <g class="head-tilt">
      <path d="M85 53 Q99 52 105 58 Q107 61 104 62 Q108 66 104 70 Q99 66 95 66 Q97 62 93 61 Q86 61 85 53 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M90 61 Q98 62 104 61" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${eye(88, 57, 2.9, E)}
    </g>`; },

  // Catfish — broad flat scaleless head, four long trailing barbels, single dorsal spine, wide flat mouth
  catfish: (c) => { const E = eyeInk(c); const B = belly(c);
    const barb = `<path d="M90 58 Q104 54 112 48 M90 61 Q106 60 114 58 M90 65 Q104 68 111 74 M90 67 Q103 72 109 80" fill="none" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round" opacity=".9"/>`;
    return `
    <g class="tail-wag"><path d="M22 62 Q10 52 5 54 Q12 62 5 70 Q10 72 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M20 62 Q28 51 54 51 Q82 51 94 60 Q96 62 94 64 Q82 73 54 73 Q28 73 20 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M34 68 Q60 76 90 66 Q60 72 34 68 Z" fill="${B}" opacity=".8"/>
      <path d="M46 51 Q54 40 62 51 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M34 51 q3 -5 6 -1 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
      <path d="M62 72 Q68 82 76 72 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M74 66 Q80 74 70 74 Q70 69 74 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    ${barb}
    <g class="head-tilt">
      <path d="M84 66 q7 1 11 -1" fill="none" stroke="${c.line}" stroke-width="1.8" stroke-linecap="round"/>
      ${eye(84, 58, 2.8, E)}
    </g>`; },

  // Carp — chunky deep body, big scale grid, two short mouth barbels, thick fleshy lips, long dorsal
  carp: (c) => { const E = eyeInk(c);
    const scales = []; for (let r = 0; r < 3; r++) for (let q = 0; q < 7; q++) { const x = 34 + q * 9 + (r % 2 ? 4.5 : 0), y = 52 + r * 7; if (x > 86) continue; scales.push(`<path d="M${x} ${y} q4 3.5 0 7" fill="none" stroke="${c.shade}" stroke-width="1.1" opacity=".5"/>`); }
    return `
    <g class="tail-wag"><path d="M22 62 Q9 48 4 50 Q12 62 4 74 Q9 76 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 62 Q32 43 62 44 Q88 46 98 62 Q88 78 62 80 Q32 80 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M36 74 Q62 82 92 66 Q62 78 36 74 Z" fill="${c.shade}"/>
      <path d="M40 46 Q60 32 84 50 Q60 50 48 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      <path d="M54 80 Q60 90 68 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      <path d="M78 66 Q84 76 74 76 Q72 70 78 66 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${scales.join("")}
    </g>
    <g class="head-tilt">
      <path d="M90 60 Q99 58 102 62 Q99 66 90 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2" stroke-linejoin="round"/>
      <path d="M96 60 Q104 56 108 58 M96 65 Q104 66 107 70" fill="none" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>
      ${eye(86, 56, 3, E)}
    </g>`; },

  // Yellow Perch — oval body ringed by bold vertical bars, spiny + soft dorsals, forked tail
  yellowperch: (c) => { const E = eyeInk(c); const D = deepen(c.body, .34);
    const bars = [38, 48, 58, 68, 78].map((x) => `<path d="M${x} 49 Q${x - 2} 62 ${x} 76" stroke="${D}" stroke-width="4" fill="none" opacity=".5" stroke-linecap="round"/>`).join("");
    return `
    <g class="tail-wag"><path d="M24 62 Q11 49 6 51 Q14 62 6 73 Q11 75 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 62 Q34 46 62 47 Q86 48 96 62 Q86 76 62 78 Q34 78 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${bars}
      <path d="M36 74 Q62 82 92 66 Q62 78 36 74 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M58 47 l3 -10 l3 10 l3 -10 l3 10 l3 -10 l3 10 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M42 47 Q48 39 54 47 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M54 78 Q60 88 68 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M88 64 q6 2 9 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(86, 56, 3, E)}
    </g>`; },

  // Northern Pike — long low body, broad duck-bill toothy snout, bean spots, dorsal set far back near tail
  northernpike: (c) => { const E = eyeInk(c); const L = tint(c.body, .5);
    const spots = []; for (let r = 0; r < 3; r++) for (let q = 0; q < 6; q++) { const x = 30 + q * 10 + (r % 2 ? 5 : 0), y = 57 + r * 4; if (x > 80) continue; spots.push(`<ellipse cx="${x}" cy="${y}" rx="2.4" ry="1.5" fill="${L}" opacity=".7"/>`); }
    return `
    <g class="tail-wag"><path d="M18 62 Q6 51 2 53 Q9 62 2 71 Q6 73 18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M18 62 Q44 51 80 53 Q92 54 98 60 Q92 70 80 71 Q44 73 18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 68 Q66 74 94 64 Q66 71 40 68 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M26 53 Q34 43 44 53 Q36 54 30 54 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      <path d="M28 71 Q36 80 46 71 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${spots.join("")}
    </g>
    <g class="head-tilt">
      <path d="M90 55 Q112 55 116 60 Q112 65 108 64 L90 66 Q86 60 90 55 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M92 61 L114 61" stroke="${c.line}" stroke-width="1.4" stroke-linecap="round"/>
      ${[94, 99, 104, 109].map((x) => `<path d="M${x} 61 l0 -3" stroke="${TOOTH}" stroke-width="1.3" stroke-linecap="round"/><path d="M${x + 2} 61 l0 3" stroke="${TOOTH}" stroke-width="1.3" stroke-linecap="round"/>`).join("")}
      ${eye(88, 57, 3, E)}
    </g>`; },

  // Walleye — long body, spiny dorsal, forked tail, the signature BIG glassy reflective eye
  walleye: (c) => { const E = eyeInk(c); const G = tint(c.body, .55); return `
    <g class="tail-wag"><path d="M22 62 Q9 49 4 51 Q12 62 4 73 Q9 75 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M22 62 Q40 50 68 51 Q88 52 98 62 Q88 74 68 76 Q40 77 22 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M36 72 Q64 80 94 64 Q64 76 36 72 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M56 51 l3 -11 l3 11 l3 -11 l3 11 l3 -11 l3 11 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M40 51 Q46 43 52 51 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M52 76 Q58 86 66 77 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M90 63 Q98 64 101 61" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${[92, 96, 99].map((x) => `<path d="M${x} 62 l0 2.4" stroke="${TOOTH}" stroke-width="1.1" stroke-linecap="round"/>`).join("")}
      <circle cx="86" cy="56" r="5.2" fill="${G}" stroke="${c.line}" stroke-width="1.8"/>
      <circle cx="86" cy="56" r="2.6" fill="${INK}"/>
      <circle cx="87.4" cy="54.4" r="1.5" fill="#fff" opacity=".95"/>
    </g>`; },

  // Bluegill — very round compressed disc, faint bars, the dark opercular "ear" spot, tiny mouth
  bluegill: (c) => { const E = eyeInk(c); const D = deepen(c.body, .4);
    const bars = [44, 54, 64].map((x) => `<path d="M${x} 46 Q${x - 2} 62 ${x} 78" stroke="${c.shade}" stroke-width="3" fill="none" opacity=".4" stroke-linecap="round"/>`).join("");
    return `
    <g class="tail-wag"><path d="M28 62 Q16 50 10 52 Q18 62 10 72 Q16 74 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M28 62 Q34 40 62 40 Q90 42 96 62 Q90 82 62 84 Q34 84 28 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${bars}
      <path d="M40 76 Q64 84 90 68 Q64 80 40 76 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M44 42 Q56 30 72 42 Q60 45 52 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      <path d="M52 84 Q58 92 66 84 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <ellipse cx="80" cy="52" rx="4.5" ry="6" fill="${D}" opacity=".85"/>
      <path d="M90 62 q5 1 8 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(86, 55, 3, E)}
    </g>`; },

  // Crappie — papery compressed body, all-over speckled mottling, tall long dorsal, upturned mouth
  crappie: (c) => { const E = eyeInk(c); const D = deepen(c.body, .36);
    const spk = []; for (let r = 0; r < 4; r++) for (let q = 0; q < 6; q++) { const x = 38 + q * 9 + (r % 2 ? 4 : 0), y = 48 + r * 7; if (x > 84) continue; spk.push(`<circle cx="${x}" cy="${y}" r="1.5" fill="${D}" opacity=".55"/>`); }
    return `
    <g class="tail-wag"><path d="M26 62 Q14 50 8 52 Q16 62 8 72 Q14 74 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q34 42 62 43 Q88 45 96 62 Q88 80 62 82 Q34 82 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 76 Q64 84 90 68 Q64 80 40 76 Z" fill="${c.shade}" opacity=".45"/>
      <path d="M40 43 Q56 28 78 44 Q60 46 50 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      <path d="M50 82 Q58 92 68 81 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${spk.join("")}
    </g>
    <g class="head-tilt">
      <path d="M88 58 Q97 56 100 60 Q96 62 90 63 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.8" stroke-linejoin="round"/>
      ${eye(85, 55, 3, E)}
    </g>`; },

  // Sturgeon — long armoured body with rows of bony scutes, hanging barbels, ventral sucker mouth, shark tail
  sturgeon: (c) => { const E = eyeInk(c);
    const dscute = [34, 44, 54, 64, 74].map((x) => `<path d="M${x} 54 l3 -6 l3 6 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`).join("");
    const lscute = [38, 50, 62, 74].map((x) => `<path d="M${x} 62 l3 -2.5 l3 2.5 l-3 2.5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1" opacity=".8"/>`).join("");
    return `
    <g class="tail-wag"><path d="M26 60 L8 44 Q18 58 13 62 L5 68 Q16 66 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 60 Q48 52 78 54 Q94 55 106 60 Q102 61 106 64 Q94 68 78 70 Q48 72 24 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 68 Q66 73 94 64 Q66 70 40 68 Z" fill="${c.shade}" opacity=".45"/>
      <path d="M30 70 Q38 80 48 71 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${dscute}${lscute}
    </g>
    <g class="head-tilt">
      <path d="M92 63 q3 6 0 9 M96 62 q3 6 0 9 M100 61 q4 6 1 9 M104 60 q3 6 1 8" fill="none" stroke="${c.line}" stroke-width="1.3" stroke-linecap="round"/>
      <ellipse cx="99" cy="70" rx="3" ry="2" fill="${INK}" opacity=".8"/>
      ${eye(90, 58, 2.6, E)}
    </g>`; },

  // Alligator Gar — very long cylinder, armoured diamond scales, dorsal far back, long broad toothy snout
  alligatorgar: (c) => { const E = eyeInk(c);
    const sc = []; for (let r = 0; r < 3; r++) for (let q = 0; q < 6; q++) { const x = 32 + q * 9 + (r % 2 ? 4.5 : 0), y = 57 + r * 4; if (x > 78) continue; sc.push(`<path d="M${x} ${y} l2 2 l-2 2 l-2 -2 Z" fill="none" stroke="${c.shade}" stroke-width="1" opacity=".55"/>`); }
    return `
    <g class="tail-wag"><path d="M18 62 Q7 51 3 53 Q9 62 3 71 Q7 73 18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M18 62 Q46 54 78 55 Q90 56 96 60 Q90 66 78 69 Q46 70 18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 67 Q66 72 92 63 Q66 69 40 67 Z" fill="${c.shade}" opacity=".45"/>
      <path d="M26 55 Q34 46 44 55 Q36 56 30 56 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M28 69 Q36 78 46 69 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      ${sc.join("")}
    </g>
    <g class="head-tilt">
      <path d="M88 56 Q114 56 118 60 L118 62 Q114 65 88 66 Q84 61 88 56 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/>
      <path d="M90 61 L116 61" stroke="${c.line}" stroke-width="1.3"/>
      ${[91, 96, 101, 106, 111].map((x) => `<path d="M${x} 61 l0 -3" stroke="${TOOTH}" stroke-width="1.2" stroke-linecap="round"/><path d="M${x + 2} 61 l0 3" stroke="${TOOTH}" stroke-width="1.2" stroke-linecap="round"/>`).join("")}
      ${eye(86, 58, 2.8, E)}
    </g>`; },

  // Tilapia — deep laterally-compressed cichlid, long spiny dorsal, faint vertical bars, moderate mouth
  tilapia: (c) => { const E = eyeInk(c);
    const bars = [42, 54, 66].map((x) => `<path d="M${x} 48 Q${x - 2} 62 ${x} 76" stroke="${c.shade}" stroke-width="3" fill="none" opacity=".38" stroke-linecap="round"/>`).join("");
    return `
    <g class="tail-wag"><path d="M26 62 Q13 50 7 52 Q15 62 7 72 Q13 74 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M26 62 Q34 44 62 45 Q88 47 96 62 Q88 78 62 80 Q34 80 26 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${bars}
      <path d="M40 74 Q64 82 90 66 Q64 78 40 74 Z" fill="${c.shade}" opacity=".5"/>
      <path d="M38 45 Q60 31 82 48 Q60 47 48 46 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${[44, 52, 60, 68, 76].map((x) => `<path d="M${x} 44 l-1 -6" stroke="${c.line}" stroke-width="1" opacity=".5"/>`).join("")}
      <path d="M52 80 Q58 90 66 80 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M90 62 q5 1 8 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(86, 55, 3, E)}
    </g>`; },

  // Arowana — very long ribbon body, big mirror scales, chin barbels pointing up, fins far back, upturned mouth
  arowana: (c) => { const E = eyeInk(c);
    const sc = []; for (let r = 0; r < 2; r++) for (let q = 0; q < 7; q++) { const x = 32 + q * 10 + (r % 2 ? 5 : 0), y = 58 + r * 6; if (x > 86) continue; sc.push(`<path d="M${x} ${y} q4 4 0 8" fill="none" stroke="${c.shade}" stroke-width="1.3" opacity=".6"/>`); }
    return `
    <g class="tail-wag"><path d="M18 62 Q7 52 3 54 Q9 62 3 70 Q7 72 18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M18 62 Q46 53 78 53 Q94 54 102 61 Q94 68 78 70 Q46 72 18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 68 Q66 73 96 64 Q66 70 40 68 Z" fill="${c.shade}" opacity=".4"/>
      <path d="M22 55 Q40 49 58 53 Q40 54 30 55 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M22 69 Q40 76 58 71 Q40 70 30 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
      ${sc.join("")}
    </g>
    <g class="head-tilt">
      <path d="M96 58 Q102 54 105 50 M100 59 Q106 56 110 53" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M92 57 Q102 52 104 58 Q100 60 94 60 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${eye(88, 57, 3, E)}
    </g>`; },

  // Discus — near-perfect round disc, vertical bars + fine wavy lines, fringing dorsal/anal fins, tiny mouth
  discus: (c) => { const E = eyeInk(c); const D = deepen(c.body, .3);
    const bars = [44, 54, 64, 74].map((x) => `<path d="M${x} 44 Q${x - 3} 62 ${x} 80" stroke="${D}" stroke-width="3.5" fill="none" opacity=".4" stroke-linecap="round"/>`).join("");
    const waves = [50, 58, 66].map((y) => `<path d="M42 ${y} q9 -3 18 0 q9 3 18 0" fill="none" stroke="${c.shade}" stroke-width="1" opacity=".4"/>`).join("");
    return `
    <g class="tail-wag"><path d="M34 62 Q22 52 16 54 Q24 62 16 70 Q22 72 34 62 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M38 48 Q46 33 62 32 Q80 33 86 49 Q62 44 38 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M38 76 Q46 91 62 92 Q80 91 86 75 Q62 80 38 76 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M30 62 Q30 38 60 38 Q90 38 92 62 Q90 86 60 86 Q30 86 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      ${bars}${waves}
    </g>
    <g class="head-tilt">
      <path d="M88 60 q4 1 6 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      ${eye(84, 54, 3.2, E)}
    </g>`; },

  // Neon Tetra — tiny slender body, oversized eye, the glowing neon lateral stripe over a darker belly
  neontetra: (c) => { const E = eyeInk(c); const N = tint(c.body, .65); return `
    <g class="tail-wag"><path d="M30 62 Q18 52 12 54 Q20 62 12 70 Q18 72 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M30 62 Q40 50 64 51 Q84 52 92 62 Q84 72 64 73 Q40 74 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M36 58 Q60 56 86 58 Q60 60 36 58 Z" fill="${N}"/>
      <path d="M40 65 Q60 68 82 64 Q60 68 40 65 Z" fill="${c.shade}" opacity=".7"/>
      <path d="M50 51 Q56 43 64 51 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.4" stroke-linejoin="round"/>
      <path d="M52 73 Q58 81 66 73 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M88 62 q4 1 6 -1" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(84, 58, 3.4, E)}
    </g>`; },

  // Molly — stout plump body, tall sailfin dorsal, broad rounded fan tail, pale round belly
  molly: (c) => { const E = eyeInk(c); const B = belly(c); return `
    <g class="tail-wag"><path d="M30 62 Q15 48 9 52 Q17 62 9 72 Q15 76 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M30 62 Q38 48 62 49 Q84 50 92 62 Q84 77 62 78 Q38 78 30 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 72 Q62 80 88 66 Q62 76 40 72 Z" fill="${B}" opacity=".85"/>
      <path d="M40 49 Q46 31 72 34 Q66 46 58 48 Q48 47 42 48 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${[46, 54, 62, 68].map((x) => `<path d="M${x} 46 l-1 -12" stroke="${c.line}" stroke-width="0.9" opacity=".4"/>`).join("")}
      <path d="M52 78 Q58 88 66 78 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M88 62 q4 1 6 -1" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(85, 56, 3, E)}
    </g>`; },

  // Oscar — big oval cichlid, marbled blotches, rounded fins, the tell-tale ringed eye-spot near the tail
  oscar: (c) => { const E = eyeInk(c); const D = deepen(c.body, .34);
    const marb = [[46, 52], [56, 68], [64, 54], [52, 60], [70, 66]].map(([x, y]) => `<ellipse cx="${x}" cy="${y}" rx="4" ry="3" fill="${D}" opacity=".45" transform="rotate(25 ${x} ${y})"/>`).join("");
    return `
    <g class="tail-wag"><path d="M24 62 Q11 49 5 51 Q13 62 5 73 Q11 75 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 62 Q34 44 62 45 Q88 47 98 62 Q88 78 62 80 Q34 80 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M38 74 Q64 82 92 66 Q64 78 38 74 Z" fill="${c.shade}" opacity=".4"/>
      <path d="M42 45 Q62 33 84 48 Q64 47 52 47 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M46 80 Q62 90 80 80 Q64 82 56 81 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      ${marb}
      <circle cx="34" cy="58" r="4.6" fill="${D}"/><circle cx="34" cy="58" r="2" fill="${tint(c.body, .6)}"/>
    </g>
    <g class="head-tilt">
      <path d="M90 60 Q98 58 100 62 Q97 65 90 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.7" stroke-linejoin="round"/>
      ${eye(85, 55, 3.2, E)}
    </g>`; },

  // Bichir — eel-like elongated body, the signature row of individual dorsal finlets, blunt reptilian head
  bichir: (c) => { const E = eyeInk(c);
    const finlets = [30, 40, 50, 60, 70].map((x) => `<path d="M${x} 56 l2 -7 l4 2 l-1 5 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.3" stroke-linejoin="round"/>`).join("");
    return `
    <g class="tail-wag"><path d="M18 62 Q8 54 4 56 Q9 62 4 68 Q8 70 18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M18 62 Q46 55 76 55 Q90 56 98 61 Q90 67 76 68 Q46 69 18 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M40 66 Q66 71 94 63 Q66 69 40 66 Z" fill="${c.shade}" opacity=".45"/>
      ${finlets}
      <path d="M78 64 Q84 74 74 73 Q72 68 78 64 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M90 63 q5 1 8 -1" fill="none" stroke="${c.line}" stroke-width="1.6" stroke-linecap="round"/>
      <path d="M84 52 q-2 8 0 15" fill="none" stroke="${c.line}" stroke-width="1.1" opacity=".4"/>
      ${eye(86, 58, 2.8, E)}
    </g>`; },

  // Paddlefish — smooth shark-like body, shark heterocercal tail, the giant elongated paddle snout (rostrum)
  paddlefish: (c) => { const E = eyeInk(c); return `
    <g class="tail-wag"><path d="M26 60 L8 44 Q18 58 13 62 L6 70 Q16 66 26 63 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.4" stroke-linejoin="round"/></g>
    <g class="breathe">
      <path d="M24 62 Q46 52 72 54 Q86 55 92 61 Q86 68 72 70 Q46 72 24 62 Z" fill="${c.body}" stroke="${c.line}" stroke-width="2.6" stroke-linejoin="round"/>
      <path d="M38 68 Q62 73 88 64 Q62 70 38 68 Z" fill="${c.shade}" opacity=".45"/>
      <path d="M40 54 Q48 44 58 54 Q50 55 44 55 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M46 70 Q54 79 62 70 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="1.5" stroke-linejoin="round"/>
    </g>
    <g class="head-tilt">
      <path d="M84 58 Q104 57 118 60 Q120 61 118 62 Q104 64 88 66 Q82 62 84 58 Z" fill="${c.shade}" stroke="${c.line}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M86 65 Q92 68 98 65" fill="none" stroke="${c.line}" stroke-width="1.5" stroke-linecap="round"/>
      ${eye(84, 57, 2.6, E)}
    </g>`; },
};

export const ROSTER_FRESHWATERFISH = [
  { n: "Largemouth Bass", e: "🐟", tier: 2, float: true },
  { n: "Rainbow Trout",   e: "🐟", tier: 2, float: true },
  { n: "Salmon",          e: "🐟", tier: 2, float: true },
  { n: "Catfish",         e: "🐟", tier: 1, float: true },
  { n: "Carp",            e: "🐟", tier: 1, float: true },
  { n: "Yellow Perch",    e: "🐟", tier: 1, float: true },
  { n: "Northern Pike",   e: "🐟", tier: 3, float: true },
  { n: "Walleye",         e: "🐟", tier: 2, float: true },
  { n: "Bluegill",        e: "🐟", tier: 1, float: true },
  { n: "Crappie",         e: "🐟", tier: 1, float: true },
  { n: "Sturgeon",        e: "🐟", tier: 3, float: true },
  { n: "Alligator Gar",   e: "🐟", tier: 3, float: true },
  { n: "Tilapia",         e: "🐟", tier: 1, float: true },
  { n: "Arowana",         e: "🐟", tier: 3, float: true },
  { n: "Discus",          e: "🐟", tier: 2, float: true },
  { n: "Neon Tetra",      e: "🐟", tier: 1, float: true },
  { n: "Molly",           e: "🐟", tier: 1, float: true },
  { n: "Oscar",           e: "🐟", tier: 2, float: true },
  { n: "Bichir",          e: "🐟", tier: 2, float: true },
  { n: "Paddlefish",      e: "🐟", tier: 3, float: true },
];
